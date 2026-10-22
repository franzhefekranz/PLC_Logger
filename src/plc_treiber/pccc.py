# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Treiber „pccc“: Allen-Bradley MicroLogix 1100/1400, SLC 5/05 (und SLC 5/03/04 über ENBT/1761-NET-ENI) über
EtherNet/IP mit PCCC-Befehlen – Bibliothek pycomm3 (SLCDriver).

Adressen in RSLogix-500-Schreibweise:

    N7:0   N7:10/3          Ganzzahl-Datei (INT), Bit eines Elements
    F8:2                    Gleitkomma (REAL)
    L9:0                    Langwort (DINT, MicroLogix 1100/1400)
    B3:0/5   B3:2           Bit-Datei: Bit bzw. ganzes Wort
    T4:0.ACC  T4:0.PRE  C5:1.ACC  T4:0.DN   Timer/Zähler: Ist-/Vorgabewert, Statusbits
    I:0/1   O:0/2   S:1/5   Eingänge, Ausgänge, Status

Elemente derselben Datei (N, F, L, B), die nah beieinander liegen, werden mit EINER Anfrage gelesen
(Datei-Lesebefehl mit Elementanzahl); Timer/Zähler, E/A und Status je Adresse.
"""
import re

from plc_i18n import tr
from plc_treiber.base import NAN, Driver, Param, Reader

# Dateityp -> (Datentyp des Loggers, Elemente je Anfrage höchstens)
FILE_TYPES = {"N": ("INT", 110), "B": ("WORD", 110), "F": ("REAL", 55), "L": ("DINT", 55)}
_FILE = re.compile(r"^([NBFL])(\d{1,3}):(\d{1,3})(?:/(\d{1,2}))?$")
_OTHER = re.compile(r"^(?:([TC])(\d{1,3}):(\d{1,3})\.(ACC|PRE|EN|DN|TT|CU|CD|OV|UN)|([IOS])(\d{0,3}):(\d{1,3})(?:\.\d{1,3})?"
                    r"(?:/(\d{1,2}))?)$")
TYPES = ["BOOL", "INT", "WORD", "DINT", "REAL"]


def parse(address):
    """-> ("file", Dateityp, Dateinummer, Element, Bit|None) | ("single", normalisierte Adresse, ist_Bit)."""
    a = (address or "").strip().upper().replace(" ", "")
    m = _FILE.match(a)
    if m:
        bit = int(m.group(4)) if m.group(4) is not None else None
        if bit is not None and bit > 15:
            raise ValueError(tr("Bitnummer 0 … 15 erwartet: {0}").format(address))
        return ("file", m.group(1), int(m.group(2)), int(m.group(3)), bit)
    m = _OTHER.match(a)
    if m:
        is_bit = (m.group(4) not in (None, "ACC", "PRE")) if m.group(1) else m.group(8) is not None
        return ("single", a, is_bit)
    raise ValueError(tr("Ungültige Adresse „{0}“ (z. B. N7:0, F8:2, B3:0/5, T4:0.ACC, I:0/1)").format(address))


class _Group:
    """Eine Datei-Anfrage: Dateityp und -nummer, erstes Element, Anzahl und die Variablen darin."""
    __slots__ = ("ftype", "fnum", "start", "count", "items")


class PcccReader(Reader):
    """Leser für MicroLogix/SLC: Elemente einer Datei gruppenweise, übrige Adressen einzeln."""
    GAP = 8

    def __init__(self, driver, plc, variables):
        """Adressen prüfen; Elemente derselben Datei nach Elementnummer sortieren und zu Gruppen zusammenfassen (Lücke
        höchstens GAP, höchstens so viele Elemente, wie in eine Antwort passen).
        """
        super().__init__(driver, plc, variables)
        self.plc_conn = None
        self.groups, self.singles = [], []                # Datei-Anfragen bzw. [(pos, Adresse)]
        files = {}
        for pos, v in enumerate(self.vars):
            try:
                kind = parse(v.address)
                if v.dtype not in TYPES:
                    raise ValueError(tr("Typ {0} wird nicht unterstützt").format(v.dtype))
            except ValueError as e:
                self.errors[v.address] = str(e)
                continue
            if kind[0] == "file":
                _k, ftype, fnum, elem, bit = kind
                if bit is not None and v.dtype != "BOOL":
                    self.errors[v.address] = tr("Bitadresse nur mit Typ BOOL")
                    continue
                files.setdefault((ftype, fnum), []).append((elem, bit, pos, v.address))
            else:
                self.singles.append((pos, kind[1], v.address))
        for (ftype, fnum), items in files.items():
            limit = FILE_TYPES[ftype][1]
            cur = None
            for elem, bit, pos, addr in sorted(items, key=lambda x: (x[0], x[2])):
                if cur and elem - (cur.start + cur.count) <= self.GAP and elem - cur.start < limit:
                    cur.count = max(cur.count, elem - cur.start + 1)
                    cur.items.append((elem, bit, pos, addr))
                else:
                    cur = _Group()
                    cur.ftype, cur.fnum, cur.start, cur.count, cur.items = ftype, fnum, elem, 1, [(elem, bit, pos, addr)]
                    self.groups.append(cur)

    def connect(self):
        """Mit pycomm3 (SLCDriver) verbinden – optional über einen CIP-Pfad – und einmal lesen."""
        self.close()
        from pycomm3 import SLCDriver
        p = self.plc.params
        path = str(p.get("ip", "")) + (f"/{p.get('pfad')}" if str(p.get("pfad", "")).strip() else "")
        try:
            c = SLCDriver(path)
            c.open()
        except Exception as e:
            raise ConnectionError(f"{path}: {e}") from None
        self.plc_conn = c
        self.read()
        return max(0, len(self.vars) - len(self.errors))

    def _read(self, address):
        """Eine Adresse bzw. einen Dateibereich (``N7:0{10}``) lesen -> (Wert, Fehler); Ausnahmen gelten als
        Verbindungsfehler.
        """
        try:
            tag = self.plc_conn.read(address)
        except Exception as e:
            raise ConnectionError(f"{type(e).__name__}: {e}") from None
        return tag.value, tag.error

    def read(self):
        """Ein Messzyklus: Gruppen (ein Wert je Element, Bits ausmaskiert), dann die Einzeladressen."""
        if self.plc_conn is None:
            raise ConnectionError(tr("nicht verbunden"))
        out = [NAN] * len(self.vars)
        for g in self.groups:
            addr = f"{g.ftype}{g.fnum}:{g.start}" + (f"{{{g.count}}}" if g.count > 1 else "")
            value, err = self._read(addr)
            if err or value is None:
                for _e, _b, _p, a in g.items:
                    self.errors[a] = tr("Lesefehler: {0}").format(err or tr("kein Wert"))
                continue
            vals = value if isinstance(value, (list, tuple)) else [value]
            for elem, bit, pos, a in g.items:
                k = elem - g.start
                if k >= len(vals) or vals[k] is None:
                    self.errors[a] = tr("Antwort zu kurz")
                    continue
                v = vals[k]
                out[pos] = float((int(v) >> bit) & 1) if bit is not None else float(v)
                self.errors.pop(a, None)
        for pos, address, label in self.singles:
            value, err = self._read(address)
            if err or value is None:
                self.errors[label] = tr("Lesefehler: {0}").format(err or tr("kein Wert"))
                continue
            out[pos] = float(1.0 if value is True else 0.0 if value is False else value)
            self.errors.pop(label, None)
        return out

    def close(self):
        """Verbindung schließen."""
        if self.plc_conn is not None:
            try:
                self.plc_conn.close()
            except Exception:
                pass
            self.plc_conn = None


class PcccDriver(Driver):
    """Treiber „pccc“ (siehe Modulbeschreibung)."""
    id = "pccc"
    name = tr("Allen-Bradley MicroLogix / SLC 500 (PCCC)")
    description = tr("MicroLogix 1100/1400, SLC 5/05 über EtherNet/IP (pycomm3); Adressen wie N7:0, F8:2, B3:0/5")
    params = [
        Param("ip", tr("IP-Adresse"), "text", "192.168.1.10"),
        Param("pfad", tr("CIP-Pfad"), "text", "", advanced=True,
              tip=tr("Nur bei SLC 5/03/04 hinter einem ENBT-/Brückenmodul, z. B. bp/1 (leer = direkt)")),
    ]
    types = TYPES
    default_type = "INT"
    address_label = tr("Adresse")
    address_hint = tr("RSLogix-500-Adresse: N7:0, F8:2, L9:0, B3:0/5, N7:10/3, T4:0.ACC, C5:1.PRE, I:0/1, O:0/2")
    block_hint = tr("Erstes Element, z. B. N7:0 (Elemente derselben Datei folgen lückenlos)")
    block_uses_index = False
    library = "pycomm3"

    def summary(self, plc):
        """IP-Adresse (ggf. mit CIP-Pfad)."""
        p = plc.params
        return str(p.get("ip", "")) + (f"/{p.get('pfad')}" if str(p.get("pfad", "")).strip() else "")

    def check_address(self, address, dtype):
        """Adresse gültig, Typ unterstützt, BOOL genau dann, wenn eine Bitadresse angegeben ist?"""
        try:
            kind = parse(address)
        except ValueError as e:
            return str(e)
        if dtype not in TYPES:
            return tr("Typ {0} wird nicht unterstützt").format(dtype)
        is_bit = kind[4] is not None if kind[0] == "file" else kind[2]
        if is_bit and dtype != "BOOL":
            return tr("Bitadresse nur mit Typ BOOL")
        if dtype == "BOOL" and not is_bit:
            return tr("BOOL braucht eine Bitadresse, z. B. B3:0/5")
        return ""

    def normalize_address(self, address, dtype):
        """Großbuchstaben ohne Leerzeichen."""
        return (address or "").strip().upper().replace(" ", "")

    def block_element_address(self, block, i):
        """Adresse des i-ten Elements (BOOL zählt Bits über Elementgrenzen, sonst Elemente)."""
        try:
            kind = parse(block.address)
        except ValueError:
            return f"{block.address}+{i}"
        if kind[0] != "file":
            return f"{block.address}+{i}"
        _k, ftype, fnum, elem, bit = kind
        if block.dtype == "BOOL":
            pos = (bit or 0) + i
            return f"{ftype}{fnum}:{elem + pos // 16}/{pos % 16}"
        return f"{ftype}{fnum}:{elem + i}"

    def check_block(self, block):
        """Blöcke nur in N-, F-, L- und B-Dateien."""
        try:
            kind = parse(block.address)
        except ValueError as e:
            return str(e)
        if kind[0] != "file":
            return tr("Blöcke nur in N-, F-, L- und B-Dateien")
        return super().check_block(block)

    def check_library(self):
        """pycomm3 vorhanden?"""
        import pycomm3  # noqa: F401
        return True

    def create_reader(self, plc, variables):
        """Leser für eine Steuerung (siehe PcccReader)."""
        return PcccReader(self, plc, variables)


DRIVER = PcccDriver()
