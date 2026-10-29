# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Lesen von Variablen aus S7-1200/S7-1500 (TIA Portal) über S7CommPlus mit der Bibliothek ``s7commplus``.

S7CommPlus ist das Protokoll, mit dem auch TIA Portal und Siemens-HMIs mit der Steuerung sprechen. Anders als das
klassische S7-Protokoll (PUT/GET, snap7) adressiert es Variablen **symbolisch**: Jede Variable hat in der Steuerung
eine feste Kennung (Bereich + LID-Pfad). Dadurch funktionieren auch Datenbausteine mit "Optimiertem Bausteinzugriff",
und PUT/GET muss nicht freigegeben werden.

Ablauf je Steuerung (Klasse ``TagReader``, ein Objekt je Lese-Thread)
--------------------------------------------------------------------
1. ``connect()``: Verbindung aufbauen (TLS automatisch/aus/an, optional Passwort der Zugriffsstufe).
2. Variablenkatalog: Namen -> Kennungen. Er stammt aus der zwischengespeicherten Variablenliste (siehe tia_taglist);
   fehlen Namen darin, wird die Liste einmal neu aus der Steuerung gelesen (``browse``, dauert einige Sekunden).
3. ``read()``: alle Variablen mit möglichst wenigen Anfragen lesen (GetMultiVariables, je Anfrage höchstens
   ``Plc.tags_je_anfrage`` Variablen) und nach dem von der Steuerung gemeldeten Datentyp dekodieren.

Fehler einzelner Variablen (z. B. nach einer Programmänderung gelöschte Variable) stehen in ``errors`` und stören die
übrigen nicht. Ist die Verbindung gestört, löst ``read()`` ConnectionError aus; der Lese-Thread verbindet neu.

Blöcke (Ausschnitte eines Arrays) brauchen keine Sonderbehandlung: Ihre Elemente sind gewöhnliche Variablen, die mit
den übrigen in derselben Anfrage gelesen werden.

Ringpuffer (zyklussynchrone Aufzeichnung, siehe ringbuffer.py), beides ohne PUT/GET:

* **absolute Adresse** wie beim Treiber s7, z. B. ``DB100.DBX0.0``: Puffer in einem *nicht optimierten* Datenbaustein,
  byteweise gelesen (``db_read``) – wenige, große Anfragen.
* **symbolischer Name** des Puffers, z. B. ``PLC_Ringpuffer`` (globaler DB), ``Cycl_Rec_DB`` (Instanz-DB) oder
  ``Anlage_DB.Puffer`` (Struktur): auch in *optimierten* Bausteinen. Gelesen werden die Variablen ``<Name>.Zaehler``
  und je Datensatz ``<Name>.Daten[i].Seq``, ``.Zeit`` und ``.Werte[0..M-1]`` (2 + M Variablen je Datensatz, mit den
  übrigen Anfragen gebündelt). Die Untergrenzen der Arrays (0 oder 1) erkennt der Treiber selbst.
"""
import re
import datetime
import math
import struct

from plc_treiber.tia_common import Plc
from plc_treiber.ringbuffer import HEADER_BYTES, RingSupport
from plc_i18n import tr

RING_CHUNK = 4000                                # höchstens so viele Bytes je db_read beim Abholen eines Ringpuffers
ABSOLUTE_RING = re.compile(r"^\s*DB\d+\.DB[XBWD]", re.IGNORECASE)   # absolute Adresse (sonst symbolischer Name)


def ring_is_symbolic(address: str) -> bool:
    """True, wenn die Adresse eines Ringpuffers ein symbolischer Name ist (nicht ``DB100.DBX0.0``)."""
    return not ABSOLUTE_RING.match(address or "")

# Werte, die als Zahl aufgezeichnet werden können: Wahrheitswerte, Ganz- und Gleitkommazahlen, Zeitdauern (in ms),
# einzelne Zeichen (Zeichencode). Alles andere (Texte, Datum …) wird NaN.


def to_number(value):
    """Von s7commplus dekodierten Wert in eine Zahl (float) umwandeln; nicht darstellbare Werte -> NaN."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime.timedelta):
        return value.total_seconds() * 1000.0
    if isinstance(value, str) and len(value) == 1:
        return float(ord(value))
    return math.nan


def _connect_args(plc: Plc):
    """Argumente für s7commplus.Client.connect aus den Einstellungen der Steuerung."""
    args = {"port": int(plc.port),
            "use_tls": {"auto": "auto", "an": True, "aus": False}.get(plc.tls, "auto"),
            "connection_type": plc.rolle or "hmi"}
    if plc.passwort:
        args["password"] = plc.passwort
    return args


def _is_connection_error(exc):
    """True für Fehler, nach denen die Verbindung neu aufgebaut werden muss."""
    try:
        from s7commplus.error import S7ConnectionError, S7ProtocolError, S7ReturnValueError, S7TimeoutError
        if isinstance(exc, S7ReturnValueError):
            return False                          # Steuerung hat geantwortet, nur die Anfrage abgelehnt
        if isinstance(exc, (S7ConnectionError, S7TimeoutError, S7ProtocolError)):
            return True
    except ImportError:
        pass
    return isinstance(exc, (OSError, ConnectionError, TimeoutError))


class TagReader(RingSupport):
    """Liest die Variablen EINER Steuerung. Nicht thread-sicher: jeder Lese-Thread hat seinen eigenen Reader.

    variables: Liste von Variable (ohne berechnete); ``read()`` liefert die Werte in derselben Reihenfolge,
    nicht lesbare Werte sind NaN. ``client_factory`` (Tests) erzeugt statt s7commplus.Client ein Ersatzobjekt;
    ``catalog_items`` (Tests) ersetzt die Variablenliste."""

    def __init__(self, plc: Plc, variables, client_factory=None, catalog_items=None):
        """Reader anlegen (noch ohne Verbindung); die Kennungen werden erst in ``connect`` aufgelöst."""
        self.plc, self.vars = plc, list(variables)
        self.client_factory = client_factory
        self.catalog_items = catalog_items
        self.client = None
        self.tags = [None] * len(self.vars)      # aufgelöste Kennungen (SymbolicTag) je Variable
        self.errors = {}                         # Variablenname (Tag) -> Fehlertext
        self.catalog_refreshed = False           # Variablenliste in dieser Sitzung schon neu gelesen?
        self.ring_pos = self._setup_rings(self.vars)  # Elemente von Ringpuffern (werden nicht symbolisch gelesen)
        from plc_treiber.s7 import parse_ring
        from plc_treiber.tia_common import check_tag_name
        for ring in self.rings:
            ring.symbolic = ring_is_symbolic(ring.address)
            if ring.symbolic:
                ring.base = ring.address.strip()
                if not check_tag_name(ring.base) or ring.base.endswith("]"):
                    ring.error = tr("Ungültiger Variablenname „{0}“").format(ring.address)
                continue
            try:
                ring.db, ring.byte = parse_ring(ring.address)
            except ValueError as e:
                ring.error = str(e)

    # ------------------------------------------------------------------ Verbindung
    def _new_client(self):
        """s7commplus-Client erzeugen (in Tests das Ersatzobjekt aus ``client_factory``)."""
        if self.client_factory:
            return self.client_factory()
        from s7commplus import Client             # erst hier importieren: Demo und Tests brauchen s7commplus nicht
        return Client()

    def connect(self):
        """Verbinden, Variablen auflösen und einmal lesen. Rückgabe: Anzahl der lesbaren Variablen.

        Löst ConnectionError aus, wenn die Steuerung nicht erreichbar ist oder die Anmeldung scheitert."""
        self.close()
        client = self._new_client()
        try:
            client.connect(self.plc.ip, **_connect_args(self.plc))
        except Exception as e:
            raise ConnectionError(f"{self.plc.ip}: {e}") from None
        self.client = client
        self.errors = {}
        if len(self.ring_pos) < len(self.vars) or any(getattr(r, "symbolic", False) for r in self.rings):
            self._resolve()
        n_ok = sum(1 for t in self.tags if t is not None)
        if n_ok:
            self.read()                           # erst ein erfolgreicher Lesezyklus beweist die Verbindung
        n_ring = 0
        if self.rings:
            self.check_rings()                    # Zähler einmal lesen (prüft auch die Verbindung)
            n_ring = sum(len(r.positions) for r in self.rings if r.label not in self.errors)
        return n_ring + n_ok - sum(1 for i, t in enumerate(self.tags)
                                   if t is not None and self.vars[i].tag in self.errors)

    def _catalog(self, refresh=False):
        """Variablenkatalog (s7commplus.SymbolCatalog): aus dem Zwischenspeicher oder neu aus der Steuerung."""
        from s7commplus import SymbolCatalog
        from plc_treiber import tia_taglist
        items = self.catalog_items
        if items is None and not refresh:
            items = tia_taglist.load_cache_items(self.plc)
        if items is None or refresh:
            if self.catalog_items is not None:
                items = self.catalog_items
            else:
                items = self.client.browse()
                tia_taglist.save_cache_items(self.plc, items)
            self.catalog_refreshed = True
        # Doppelte Namen (sollte nicht vorkommen) überspringen statt abzubrechen.
        seen, unique = set(), []
        for it in items:
            if it.get("name") not in seen:
                seen.add(it.get("name"))
                unique.append(it)
        tags = []
        from s7commplus import SymbolicTag
        for it in unique:
            try:
                tags.append(SymbolicTag.from_browse(it))
            except ValueError:
                continue                          # Einträge ohne lesbare Kennung (z. B. unbekannter Typ)
        return SymbolCatalog(tags)

    def _resolve(self):
        """Namen der Variablen (und symbolischer Ringpuffer) in Kennungen übersetzen; fehlen Namen, die Liste einmal
        neu aus der Steuerung lesen."""
        catalog = self._catalog()
        missing = self._apply(catalog)
        ring_missing = self._apply_rings(catalog)
        if (missing or ring_missing) and not self.catalog_refreshed:
            catalog = self._catalog(refresh=True)
            missing = self._apply(catalog)
            self._apply_rings(catalog)
        for i in missing:
            self.errors[self.vars[i].tag] = tr("Variable in der Steuerung nicht gefunden")

    def _apply_rings(self, catalog):
        """Symbolische Ringpuffer im Katalog nachschlagen: Zähler und für jeden Platz Seq, Zeit, Werte -> True, wenn
        bei einem Puffer etwas fehlt (der Fehler steht dann in ``ring.error``)."""
        failed = False
        for ring in self.rings:
            if not getattr(ring, "symbolic", False) or (ring.error and not getattr(ring, "resolve_error", False)):
                continue
            ring.error, ring.resolve_error = "", False
            try:
                ring.tags = self._ring_tags(catalog, ring)
            except KeyError as e:
                ring.error, ring.resolve_error, ring.tags = str(e.args[0] if e.args else e), True, None
                failed = True
        return failed

    @staticmethod
    def _ring_tags(catalog, ring):
        """Kennungen eines symbolischen Puffers -> {"zaehler": Tag, "slots": [[Seq, Zeit, Wert0 …] je Platz]}.

        KeyError mit verständlichem Text, wenn eine Variable fehlt oder der Puffer kleiner ist als eingestellt."""
        b = ring.base

        def get(name):
            try:
                return catalog.resolve(name)
            except KeyError:
                return None

        def need(name):
            tag = get(name)
            if tag is None:
                raise KeyError(tr("Ringpuffer {0}: Variable „{1}“ nicht gefunden (Aufbau: Zaehler, "
                                  "Daten[0..N-1] mit Seq, Zeit und Werte[0..M-1])").format(ring.name, name))
            return tag
        counter = need(f"{b}.Zaehler")
        lo = 0 if get(f"{b}.Daten[0].Seq") is not None else 1          # Array[0..N-1] oder Array[1..N]
        need(f"{b}.Daten[{lo}].Seq")
        wlo = 0 if get(f"{b}.Daten[{lo}].Werte[0]") is not None else 1
        last = f"{b}.Daten[{lo + ring.records - 1}].Seq"
        if get(last) is None:
            raise KeyError(tr("Ringpuffer {0}: „{1}“ fehlt – hat der Puffer in der Steuerung weniger als {2} "
                              "Datensätze?").format(ring.name, last, ring.records))
        if get(f"{b}.Daten[{lo}].Werte[{wlo + ring.count - 1}]") is None:
            raise KeyError(tr("Ringpuffer {0}: „Werte“ hat in der Steuerung weniger als {1} Elemente").format(
                ring.name, ring.count))
        slots = []
        for k in range(ring.records):
            d = f"{b}.Daten[{lo + k}]"
            slots.append([need(d + ".Seq"), need(d + ".Zeit")]
                         + [need(f"{d}.Werte[{wlo + j}]") for j in range(ring.count)])
        return {"zaehler": counter, "slots": slots}

    def _apply(self, catalog):
        """Jede Variable im Katalog nachschlagen und die Kennung merken -> Indizes der nicht gefundenen Variablen."""
        missing = []
        for i, v in enumerate(self.vars):
            if i in self.ring_pos:
                continue
            try:
                self.tags[i] = catalog.resolve(v.tag)
            except KeyError:
                self.tags[i] = None
                missing.append(i)
        return missing

    # ------------------------------------------------------------------ Lesen
    def read(self):
        """Ein Messzyklus -> Liste der Werte (NaN = nicht lesbar)."""
        out = [math.nan] * len(self.vars)
        idx = [i for i, t in enumerate(self.tags) if t is not None]
        size = max(1, int(self.plc.tags_je_anfrage))
        for k in range(0, len(idx), size):
            part = idx[k:k + size]
            try:
                raws = self._read_items(part)
            except Exception as e:
                if _is_connection_error(e):
                    raise ConnectionError(str(e)) from None
                # Die Steuerung hat nicht alle Variablen beantwortet: einzeln lesen, um die fehlerhafte zu finden.
                raws = []
                for i in part:
                    try:
                        raws.append(self._read_items([i])[0])
                    except Exception as e2:
                        if _is_connection_error(e2):
                            raise ConnectionError(str(e2)) from None
                        raws.append(None)
            for i, raw in zip(part, raws):
                name = self.vars[i].tag
                if raw is None:
                    self.errors[name] = tr("Lesefehler (Variable nicht lesbar oder geändert)")
                    continue
                self.errors.pop(name, None)
                try:
                    out[i] = to_number(self.tags[i].decode_value(raw))
                except Exception:
                    out[i] = math.nan
        return out

    # ------------------------------------------------------------------ Ringpuffer (siehe ringbuffer.py)
    def _ring_is_connection_error(self, exc):
        """Verbindung neu aufbauen? (wie beim symbolischen Lesen)"""
        return _is_connection_error(exc)

    def _ring_counter(self, ring):
        """Zähler (DINT) am Anfang des Puffers."""
        if getattr(ring, "symbolic", False):
            tag = ring.tags["zaehler"]
            raw = self.client.read_symbolic_multi([(tag.access_area, list(tag.lids), 0)])[0]
            if raw is None:
                raise RuntimeError(tr("Ringpuffer {0}: Zähler nicht lesbar").format(ring.name))
            return int(to_number(tag.decode_value(raw)))
        return struct.unpack(">i", bytes(self.client.db_read(ring.db, ring.byte, HEADER_BYTES))[:4])[0]

    def _ring_fetch(self, ring, lo, hi):
        """Datensätze ``lo … hi`` lesen; symbolisch: alle Variablen der Plätze, gebündelt zu Anfragen mit höchstens
        ``tags_je_anfrage`` Variablen. Nicht lesbare Datensätze bekommen Seq -1 (zählen als verloren)."""
        if not getattr(ring, "symbolic", False):
            return super()._ring_fetch(ring, lo, hi)
        tags = []
        for seq in range(lo, hi + 1):
            tags.extend(ring.tags["slots"][seq % ring.records])
        raws = []
        size = max(1, int(self.plc.tags_je_anfrage))
        for k in range(0, len(tags), size):
            part = tags[k:k + size]
            raws.extend(self.client.read_symbolic_multi([(t.access_area, list(t.lids), 0) for t in part]))
        per = 2 + ring.count
        out = []
        for i in range(hi - lo + 1):
            chunk, raw = tags[i * per:(i + 1) * per], raws[i * per:(i + 1) * per]
            try:
                vals = [to_number(t.decode_value(r)) if r is not None else math.nan for t, r in zip(chunk, raw)]
                if math.isnan(vals[0]) or math.isnan(vals[1]):
                    raise ValueError
                out.append((int(vals[0]), int(vals[1]), vals[2:]))
            except (ValueError, TypeError):
                out.append((-1, 0, [math.nan] * ring.count))
        return out

    def _ring_bytes(self, ring, slot, n):
        """``n`` Datensätze ab Platz ``slot`` – in Stücken von höchstens ``RING_CHUNK`` Bytes (ganze Datensätze)."""
        rs = ring.record_size
        per = max(1, RING_CHUNK // rs)
        out = bytearray()
        for k in range(0, n, per):
            m = min(per, n - k)
            out += bytes(self.client.db_read(ring.db, ring.byte + HEADER_BYTES + (slot + k) * rs, m * rs))
        return bytes(out)

    def _read_items(self, indices):
        """Eine GetMultiVariables-Anfrage für die Variablen mit diesen Indizes -> Rohwerte (None = Fehler)."""
        items = [(self.tags[i].access_area, list(self.tags[i].lids), 0) for i in indices]
        return self.client.read_symbolic_multi(items)

    def close(self):
        """Verbindung trennen (Fehler beim Trennen werden ignoriert)."""
        if self.client is not None:
            try:
                self.client.disconnect()
            except Exception:
                pass
            self.client = None


def read_once(plc: Plc, variables, client_factory=None):
    """Variablen einmal lesen (Verbindungstest im Konfigurationsprogramm).

    Rückgabe: (Werte, Fehler je Variablenname). ConnectionError, wenn die Steuerung nicht erreichbar ist."""
    r = TagReader(plc, variables, client_factory)
    try:
        r.connect()
        return r.read(), dict(r.errors)
    finally:
        r.close()


def check_library():
    """Prüft, ob s7commplus installiert ist (Fehlermeldung sonst als ImportError)."""
    import s7commplus  # noqa: F401
    return True
