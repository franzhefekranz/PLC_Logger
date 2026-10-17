# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Tag-Liste einer Logix-Steuerung mit pycomm3 – ohne Oberfläche (für den Auswahldialog clx_browser.py).

Anders als bei einer Siemens-S7 kennt eine Logix-Steuerung die Namen und Datentypen ihrer Tags selbst. pycomm3 lädt
sie mit ``LogixDriver.get_tag_list()`` aus der Steuerung, einschließlich der Struktur benutzerdefinierter
Datentypen (UDTs) und vordefinierter Strukturen (TIMER, COUNTER …).

Ablauf
------
1. ``fetch_tag_list(plc)`` verbindet sich mit pycomm3, holt Controller- und (optional) Programm-Tags und wandelt die
   pycomm3-Beschreibungen in eine einfache, JSON-fähige Form um (``simplify``).
2. Die einfache Form wird im Datenordner zwischengespeichert (``save_cache``/``load_cache``), damit der Baum auch
   ohne Verbindung durchsucht werden kann.
3. ``TagTree`` liefert daraus Baumknoten (``TagNode``): oben die Bereiche *Controller* und *Program:…*, darunter Tags,
   Strukturglieder und Array-Elemente. Kinder werden erst bei Bedarf erzeugt (große Arrays/UDTs).

Einfache Form (JSON)
--------------------
``{"tags": [{"name": "Program:Main.Temp", "type": "REAL", "dims": [10], "struct": false}, …],
   "types": {"MOTOR": [{"name": "Drehzahl", "type": "REAL", "array": 0, "struct": false}, …]},
   "info": {"name": "...", "revision": "...", "product": "..."}}``

Lesbar (aufzeichenbar) sind atomare Typen aus clx_common.TYPES; BYTE/WORD/DWORD/LWORD werden als USINT/UINT/UDINT/
ULINT gelesen. Strings und andere Typen erscheinen im Baum, sind aber nicht wählbar.
"""
import json
import os
import re
from dataclasses import dataclass, field

from plc_treiber.clx_common import BASE_DIR, BLOCK_TYPES, TYPES, Plc, pycomm3_path

# Bit-String-Typen der Logix werden als vorzeichenlose Ganzzahlen gelesen.
TYPE_ALIASES = {"BYTE": "USINT", "WORD": "UINT", "DWORD": "UDINT", "LWORD": "ULINT"}
# Höchstzahl der Array-Elemente, die im Baum einzeln aufgeführt werden (größere Arrays: als Block übernehmen).
MAX_ELEMENTS = 500


def readable_type(type_name):
    """Logix-Typname -> Typ für die Aufzeichnung (clx_common.TYPES) oder None, wenn nicht lesbar."""
    t = TYPE_ALIASES.get(type_name, type_name)
    return t if t in TYPES else None


# ---------------------------------------------------------------------------------------
# pycomm3 -> einfache Form
# ---------------------------------------------------------------------------------------
def _members(data_type, types):
    """Glieder eines Struktur-Datentyps (pycomm3-Dict) in ``types`` eintragen (rekursiv) und den Typnamen liefern."""
    name = data_type.get("name") or "?"
    if name in types:
        return name
    types[name] = []                     # Platzhalter gegen Endlosrekursion bei verschachtelten Typen
    out = []
    internal = data_type.get("internal_tags", {})
    for m in data_type.get("attributes", list(internal)):
        info = internal.get(m)
        if not info:
            continue
        is_struct = info.get("tag_type") == "struct"
        if is_struct:
            tname = _members(info["data_type"], types)
        else:
            tname = info.get("data_type_name") or str(info.get("data_type"))
        out.append({"name": m, "type": tname, "array": int(info.get("array") or 0), "struct": is_struct})
    if data_type.get("string"):          # STRING-artige Typen: nicht aufklappen
        out = []
    types[name] = out
    return name


def simplify(tags, info=None):
    """pycomm3-Tagliste (Liste von Dicts aus get_tag_list) -> einfache, JSON-fähige Form."""
    types, out = {}, []
    for t in tags:
        is_struct = t.get("tag_type") == "struct"
        if is_struct:
            tname = _members(t["data_type"], types)
        else:
            tname = t.get("data_type_name") or str(t.get("data_type"))
        dim = int(t.get("dim") or 0)
        dims = [int(x) for x in (t.get("dimensions") or [0, 0, 0])[:dim]]
        out.append({"name": t["tag_name"], "type": tname, "dims": dims, "struct": is_struct,
                    "access": t.get("external_access", "")})
    out.sort(key=lambda x: x["name"].lower())
    return {"tags": out, "types": types, "info": dict(info or {})}


def fetch_tag_list(plc: Plc, program_tags=True):
    """Tag-Liste aus der Steuerung holen (pycomm3) -> einfache Form. Dauert je nach Projekt einige Sekunden."""
    from pycomm3 import LogixDriver                # erst hier importieren: das Programm läuft auch ohne pycomm3
    with LogixDriver(pycomm3_path(plc), init_tags=False) as drv:
        tags = drv.get_tag_list(program="*" if program_tags else None)
        raw = getattr(drv, "info", {}) or {}
        rev = raw.get("revision", {})
        rev = f"{rev.get('major', '?')}.{rev.get('minor', '?')}" if isinstance(rev, dict) else str(rev)
        info = {"name": str(raw.get("name", "")), "product": str(raw.get("product_name", "")), "revision": rev}
    return simplify(tags, info)


# ---------------------------------------------------------------------------------------
# Zwischenspeicher je Steuerung
# ---------------------------------------------------------------------------------------
def cache_path(plc: Plc):
    """Datei für die zwischengespeicherte Tag-Liste einer Steuerung (Name aus IP und Pfad)."""
    key = re.sub(r"[^\w.-]+", "_", f"{plc.ip}_{plc.pfad}").strip("_")
    return os.path.join(BASE_DIR, "taglisten", f"tags_{key}.json")


def save_cache(plc: Plc, data):
    os.makedirs(os.path.dirname(cache_path(plc)), exist_ok=True)
    with open(cache_path(plc), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def load_cache(plc: Plc):
    """Zwischengespeicherte Tag-Liste oder None."""
    try:
        with open(cache_path(plc), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------------------
# Baum
# ---------------------------------------------------------------------------------------
@dataclass
class TagNode:
    """Ein Knoten im Tag-Baum.

    kind: 'scope' (Controller/Programm), 'struct' (aufklappbare Struktur), 'array' (Array, Elemente als Kinder),
    'leaf' (atomarer Wert). ``path`` ist der vollständige Tag-Name zum Lesen (bei 'scope' leer)."""
    label: str
    path: str
    type: str
    kind: str
    dims: list = field(default_factory=list)      # Arraygrößen (nur 'array')
    struct: bool = False                          # Elementtyp ist eine Struktur (nur 'array') bzw. Knoten ist eine
    access: str = ""

    @property
    def dtype(self):
        """Aufzeichnungstyp (bei Blättern), sonst None."""
        return readable_type(self.type) if self.kind == "leaf" else None

    @property
    def can_block(self):
        """Array aus atomaren Werten (außer BOOL), eindimensional: als Block lesbar."""
        return (self.kind == "array" and not self.struct and len(self.dims) == 1
                and readable_type(self.type) in BLOCK_TYPES)

    @property
    def length(self):
        n = 1
        for d in self.dims:
            n *= max(d, 1)
        return n


class TagTree:
    """Baum über der einfachen Form der Tag-Liste."""

    def __init__(self, data):
        self.data = data or {"tags": [], "types": {}}
        self.types = self.data.get("types", {})

    def roots(self):
        """Oberste Ebene: 'Controller' und je Programm ein Knoten."""
        progs = sorted({t["name"].split(".", 1)[0] for t in self.data["tags"] if t["name"].startswith("Program:")})
        out = [TagNode("Controller-Tags", "", "", "scope")]
        out += [TagNode(p, p, "", "scope") for p in progs]
        return out

    def _node(self, label, path, type_name, dims, struct, access=""):
        if dims:
            return TagNode(label, path, type_name, "array", list(dims), struct, access)
        return TagNode(label, path, type_name, "struct" if struct else "leaf", [], struct, access)

    def children(self, node: TagNode):
        """Kinder eines Knotens (bei großen Arrays höchstens MAX_ELEMENTS Elemente)."""
        if node.kind == "scope":
            out = []
            for t in self.data["tags"]:
                name = t["name"]
                if node.path:                                        # Programm
                    if not name.startswith(node.path + "."):
                        continue
                    label = name[len(node.path) + 1:]
                elif name.startswith("Program:"):
                    continue
                else:
                    label = name
                out.append(self._node(label, name, t["type"], t.get("dims", []), t.get("struct", False),
                                      t.get("access", "")))
            return out
        if node.kind == "struct":
            out = []
            for m in self.types.get(node.type, []):
                dims = [m["array"]] if m.get("array") else []
                out.append(self._node(m["name"], f"{node.path}.{m['name']}", m["type"], dims, m.get("struct", False)))
            return out
        if node.kind == "array":
            out = []
            for idx in _indices(node.dims, MAX_ELEMENTS):
                sub = ",".join(str(i) for i in idx)
                out.append(self._node(f"[{sub}]", f"{node.path}[{sub}]", node.type, [], node.struct))
            return out
        return []

    def search(self, text, limit=2000):
        """Alle wählbaren Blätter (und Arrays) deren Pfad ``text`` enthält (Groß-/Kleinschreibung egal).

        Durchsucht Strukturen rekursiv; bei Arrays aus Strukturen nur das erste Element (sonst zu viele Treffer)."""
        text = text.lower()
        hits = []

        def visit(n, depth):
            if len(hits) >= limit or depth > 12:
                return
            if n.kind in ("leaf", "array") and text in n.path.lower():
                hits.append(n)
            kids = self.children(n)
            if n.kind == "array":
                if not n.struct:
                    return
                kids = kids[:1]
            for c in kids:
                visit(c, depth + 1)

        for r in self.roots():
            visit(r, 0)
        return hits


def _indices(dims, limit):
    """Indizes eines (mehrdimensionalen) Arrays in Zeilenreihenfolge, höchstens ``limit`` Stück."""
    dims = [max(d, 1) for d in dims] or [1]
    out, idx = [], [0] * len(dims)
    while len(out) < limit:
        out.append(tuple(idx))
        k = len(dims) - 1
        while k >= 0:
            idx[k] += 1
            if idx[k] < dims[k]:
                break
            idx[k] = 0
            k -= 1
        if k < 0:
            break
    return out
