"""Variablenliste einer S7-1200/1500 (TIA Portal) – ohne Oberfläche (für den Auswahldialog und den Leser).

S7CommPlus kann die Symbolik direkt aus der Steuerung lesen (``s7commplus.Client.browse``): alle Datenbausteine mit
ihren Variablen, Strukturen und Array-Elementen sowie die Bereiche Eingänge (``IArea``), Ausgänge (``QArea``) und
Merker (``MArea``). Ein Export aus TIA Portal ist nicht nötig.

Das Ergebnis ist eine flache Liste von Einträgen (ein Eintrag je lesbarem Wert), z. B.
``{"name": "Anlage_DB.Motor[2].Drehzahl", "data_type": "REAL", "access_sequence": "8A0E0005.A.3.1", …}``.
Sie wird je Steuerung im Datenordner zwischengespeichert (``taglisten/vars_<ip>_<port>.json``) und vom Leser
(tia_io) für die Zuordnung Name -> Kennung verwendet. Nach einer Programmänderung in der Steuerung genügt es, die
Liste im Auswahldialog neu zu laden; der Leser liest sie außerdem selbstständig neu, wenn er Namen nicht findet.

``TagTree`` baut aus der flachen Liste einen Baum (Datenbaustein > Struktur > Array > Element) für den Dialog.
"""
import json
import os
import re
from dataclasses import dataclass, field

from plc_treiber.tia_common import BASE_DIR, BLOCK_TYPES, TYPES, Plc
from plc_i18n import tr

# Typnamen der Steuerung, die unter anderem Namen aufgezeichnet werden.
TYPE_ALIASES = {"BBOOL": "BOOL"}
# Höchstzahl der Array-Elemente, die im Baum einzeln aufgeführt werden (größere Arrays: als Block übernehmen).
MAX_ELEMENTS = 500


def readable_type(type_name):
    """Typname der Steuerung -> Typ für die Aufzeichnung (tia_common.TYPES) oder None, wenn nicht als Zahl lesbar."""
    t = TYPE_ALIASES.get(type_name, type_name)
    return t if t in TYPES else None


# ---------------------------------------------------------------------------------------
# Laden und Zwischenspeichern
# ---------------------------------------------------------------------------------------
def cache_path(plc: Plc):
    """Datei für die zwischengespeicherte Variablenliste einer Steuerung (Name aus IP und Port)."""
    key = re.sub(r"[^\w.-]+", "_", f"{plc.ip}_{plc.port}").strip("_")
    return os.path.join(BASE_DIR, "taglisten", f"vars_{key}.json")


def save_cache(plc: Plc, data):
    os.makedirs(os.path.dirname(cache_path(plc)), exist_ok=True)
    tmp = cache_path(plc) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, cache_path(plc))                 # erst nach vollständigem Schreiben ersetzen


def load_cache(plc: Plc):
    """Zwischengespeicherte Variablenliste ({"items": [...], "info": {...}}) oder None."""
    try:
        with open(cache_path(plc), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data.get("items"), list) else None
    except (OSError, ValueError, AttributeError):
        return None


def load_cache_items(plc: Plc):
    """Nur die Einträge der zwischengespeicherten Liste (für tia_io) oder None."""
    data = load_cache(plc)
    return data["items"] if data else None


def save_cache_items(plc: Plc, items, info=None):
    """Neu gelesene Einträge zwischenspeichern (Fehler beim Schreiben sind unkritisch)."""
    try:
        save_cache(plc, {"items": _jsonable(items), "info": dict(info or {})})
    except OSError:
        pass


def _jsonable(items):
    """browse()-Ergebnis JSON-fähig machen (Tupel -> Listen)."""
    out = []
    for it in items:
        d = dict(it)
        d["array_dimensions"] = [list(x) for x in d.get("array_dimensions", ())]
        out.append(d)
    return out


def fetch_tag_list(plc: Plc):
    """Variablenliste aus der Steuerung lesen (browse) und zwischenspeichern. Dauert je nach Projekt einige Sekunden
    bis Minuten. Rückgabe: {"items": [...], "info": {...}}."""
    from s7commplus import Client                    # erst hier importieren: das Programm läuft auch ohne s7commplus
    from plc_treiber.tia_io import _connect_args
    client = Client()
    client.connect(plc.ip, **_connect_args(plc))
    try:
        items = client.browse()
        info = {"protokoll": str(getattr(client, "protocol_version", "")),
                "tls": "ja" if getattr(client, "tls_active", False) else "nein"}
    finally:
        try:
            client.disconnect()
        except Exception:
            pass
    data = {"items": _jsonable(items), "info": info}
    save_cache(plc, data)
    return data


# ---------------------------------------------------------------------------------------
# Baum
# ---------------------------------------------------------------------------------------
@dataclass
class TagNode:
    """Ein Knoten im Variablenbaum.

    kind: 'scope' (Datenbaustein bzw. Bereich), 'struct' (aufklappbare Struktur), 'array' (Array, Elemente als
    Kinder), 'leaf' (einzelner Wert). ``path`` ist der vollständige Name zum Lesen (bei 'leaf')."""
    label: str
    path: str
    type: str
    kind: str
    dims: list = field(default_factory=list)      # Elementzahl (nur 'array')
    struct: bool = False                          # Elemente sind Strukturen (nur 'array')
    access: str = ""
    lower: int = 0                                # kleinster Index (nur 'array', z. B. 1 bei Array[1..10])
    indices: list = field(default_factory=list)   # vorhandene Einzelindizes (nur eindimensionale Arrays)

    @property
    def dtype(self):
        """Aufzeichnungstyp (bei Blättern), sonst None."""
        return readable_type(self.type) if self.kind == "leaf" else None

    @property
    def can_block(self):
        """Eindimensionales Array aus lesbaren Werten: als Block übernehmbar."""
        return (self.kind == "array" and not self.struct and bool(self.indices)
                and readable_type(self.type) in BLOCK_TYPES)

    @property
    def length(self):
        return self.dims[0] if self.dims else 0


_IDX = re.compile(r"\[[^\]]*\]")


def split_name(name):
    """Namen in Glieder zerlegen: Punkte trennen (außer innerhalb von [ ]), Indizes werden eigene Glieder.

    ``"DB.Motor[2].Drehzahl"`` -> ``["DB", "Motor", "[2]", "Drehzahl"]``."""
    parts, cur, depth = [], "", 0
    for ch in name:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "." and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    out = []
    for p in parts:
        m = _IDX.search(p)
        if m and p.endswith("]"):
            out.append(p[:m.start()])
            out.extend(_IDX.findall(p[m.start():]))
        else:
            out.append(p)
    return [x for x in out if x != ""]


class _Build:
    __slots__ = ("label", "path", "type", "children", "is_index", "leaf")

    def __init__(self, label, path, is_index=False):
        self.label, self.path, self.is_index = label, path, is_index
        self.type, self.children, self.leaf = "", {}, False


class TagTree:
    """Baum über der flachen Variablenliste."""

    # Reihenfolge der Bereiche ganz oben: Datenbausteine zuerst, dann Merker, Ein-, Ausgänge, Zeiten, Zähler.
    AREA_ORDER = {"MArea": 1, "IArea": 2, "QArea": 3, "S7Timers": 4, "S7Counters": 5}
    AREA_LABELS = {"MArea": tr("Merker (MArea)"), "IArea": tr("Eingänge (IArea)"), "QArea": tr("Ausgänge (QArea)"),
                   "S7Timers": tr("Zeiten (S7Timers)"), "S7Counters": tr("Zähler (S7Counters)")}

    def __init__(self, data):
        self.data = data or {"items": []}
        self.types = {}                               # Kompatibilität mit dem Dialog (keine UDT-Beschreibungen)
        self.root = _Build("", "")
        self.leaves = []
        for it in self.data.get("items", []):
            name = it.get("name", "")
            if not name:
                continue
            self._insert(name, it.get("data_type", ""))
            self.leaves.append((name, it.get("data_type", "")))

    def _insert(self, name, dtype):
        node, path = self.root, ""
        for tok in split_name(name):
            is_index = tok.startswith("[")
            path = path + tok if (is_index or not path) else f"{path}.{tok}"
            child = node.children.get(tok)
            if child is None:
                child = node.children[tok] = _Build(tok, path, is_index)
            node = child
        node.leaf, node.type = True, dtype

    # ---- Umwandlung in TagNode
    def _to_node(self, b, top=False):
        kids = list(b.children.values())
        if b.leaf and not kids:
            return TagNode(b.label, b.path, b.type, "leaf")
        if kids and all(k.is_index for k in kids):
            # Array: Typ und Art aus den Elementen.
            first = kids[0]
            elem_struct = bool(first.children) and not first.leaf
            one_dim = all("," not in k.label for k in kids)
            idx = sorted(int(k.label[1:-1]) for k in kids) if one_dim and all(
                re.fullmatch(r"\[-?\d+\]", k.label) for k in kids) else []
            etype = "STRUCT" if elem_struct else first.type
            return TagNode(b.label, b.path, etype, "array", [len(kids)], elem_struct,
                           lower=idx[0] if idx else 0, indices=idx)
        if top:
            return TagNode(self.AREA_LABELS.get(b.label, b.label), b.path, "", "scope")
        return TagNode(b.label, b.path, "STRUCT", "struct")

    def _find(self, path):
        node = self.root
        if not path:
            return node
        for tok in split_name(path):
            node = node.children.get(tok)
            if node is None:
                return None
        return node

    def roots(self):
        """Oberste Ebene: Datenbausteine (alphabetisch), danach Merker, Ein-/Ausgänge, Zeiten, Zähler."""
        kids = sorted(self.root.children.values(),
                      key=lambda b: (self.AREA_ORDER.get(b.label, 0), b.label.lower()))
        return [self._to_node(b, top=True) for b in kids]

    def children(self, node: TagNode):
        """Kinder eines Knotens (bei großen Arrays höchstens MAX_ELEMENTS Elemente)."""
        b = self._find(node.path)
        if b is None:
            return []
        kids = list(b.children.values())
        if node.kind == "array":
            kids = kids[:MAX_ELEMENTS]
        return [self._to_node(k) for k in kids]

    def search(self, text, limit=2000):
        """Alle lesbaren Werte und Arrays, deren Name ``text`` enthält (Groß-/Kleinschreibung egal)."""
        text = text.lower()
        hits, arrays = [], set()
        for name, dtype in self.leaves:
            if text in name.lower():
                # Array-Elemente eines passenden Arrays nur einmal als Array zeigen (sonst Tausende Treffer).
                parts = split_name(name)
                if parts and parts[-1].startswith("["):
                    base = name[: name.rfind("[")]
                    if base not in arrays:
                        arrays.add(base)
                        b = self._find(base)
                        if b is not None:
                            hits.append(self._to_node(b))
                else:
                    hits.append(TagNode(name, name, dtype, "leaf"))
            if len(hits) >= limit:
                break
        return hits
