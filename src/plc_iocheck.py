# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""IO-Check (Inbetriebnahme): Signalliste prüfen – Logik ohne Oberfläche.

* IO-Liste aus CSV/Excel importieren (EPLAN, TIA-Portal-Variablentabelle, eigene Listen); Spalten werden über ihre
  Überschrift erkannt (deutsch/englisch), Signalart und Datentyp aus der Adresse abgeleitet.
* Prüfstatus je Signal (offen / OK / Fehler / übersprungen) mit Zeit, Prüfer und Bemerkung; Speichern als
  ``*.iocheck.json`` (am nächsten Tag weitermachen), Ergebnis als CSV/Excel.
* IoTracker: verfolgt die gelesenen Werte – „Was hat sich bewegt?“ (letzte Wechsel), Vertauschungen (anderes Signal
  als das erwartete hat gewechselt), gesehene Flanken digitaler Signale (optional automatisch abhaken),
  Analogwerte (Skalierung, Fehlerwerte, Prüfpunkte 0/50/100 % mit Toleranz).
* Bereiche scannen ohne Liste (z. B. E0.0 + 256 Bits) und Matrix-Anordnung (Byte × Bit) der Binärsignale.
* IoReader: liest die Signale je Steuerung in einem eigenen Thread (oder simuliert sie im Demo-Modus).
"""
import json
import math
import os
import queue
import random
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime

from plc_common import Block, Plc, Variable, get_driver
from plc_i18n import N_, tr

FORMAT = "plc-iocheck"
EXTENSION = ".iocheck.json"
KINDS = ("DI", "DO", "AI", "AO")
KIND_TEXT = {"DI": N_("Digitaleingang"), "DO": N_("Digitalausgang"), "AI": N_("Analogeingang"),
             "AO": N_("Analogausgang")}
STATUS = {"offen": N_("offen"), "ok": N_("OK"), "fehler": N_("Fehler"), "uebersprungen": N_("übersprungen")}
POINTS = (0, 50, 100)                     # Prüfpunkte der Analogwerte in % des Messbereichs
S7_RAW_MAX = 27648                        # Nennbereich der S7-Analogbaugruppen (0 … 27648)

# Gesehene Flanken digitaler Signale (Bitmaske in IoSignal.seen)
SEEN_RISE, SEEN_FALL = 1, 2


@dataclass
class IoSignal:
    """Ein Signal der IO-Liste mit Prüfstatus. Laufzeitwerte (value, raw, changed) werden nicht gespeichert."""
    address: str
    symbol: str = ""
    comment: str = ""
    bmk: str = ""                         # Betriebsmittelkennzeichen
    group: str = ""                       # Schrank, Baugruppe, Ort …
    kind: str = "DI"                      # DI, DO, AI, AO
    dtype: str = "BOOL"
    plc: str = ""                         # Name der Steuerung ("" = erste Steuerung der Konfiguration)
    raw_min: float = 0.0                  # Analog: Rohwert bei 0 % und 100 % …
    raw_max: float = float(S7_RAW_MAX)
    eng_min: float = 0.0                  # … und der zugehörige Messbereich in technischer Einheit
    eng_max: float = 100.0
    unit: str = ""
    status: str = "offen"
    checked_at: str = ""
    checker: str = ""
    remark: str = ""
    points: dict = field(default_factory=dict)   # Analog: {"0": gemessener Wert, "50": …, "100": …}
    seen: int = 0                         # gesehene Flanken (SEEN_RISE | SEEN_FALL)
    scanned: bool = False                 # aus einem Scan-Bereich (nicht aus der IO-Liste)

    def __post_init__(self):
        self.value = math.nan             # letzter Wert (binär 0/1, analog Rohwert)
        self.changed = 0.0                # Zeitpunkt des letzten Wechsels (time.time())
        self.error = ""                   # Lesefehler dieses Signals
        self.stable_since = 0.0           # Analog: Wert seit … in der Nähe eines Prüfpunkts
        self.stable_point = None
        self.logged = math.nan            # Analog: zuletzt gemeldeter Wert („Was hat sich bewegt?“)

    @property
    def key(self):
        return (self.plc, canon_address(self.address))

    @property
    def binary(self) -> bool:
        return self.kind in ("DI", "DO")

    @property
    def is_input(self) -> bool:
        return self.kind in ("DI", "AI")

    @property
    def label(self) -> str:
        return self.symbol or self.address

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v not in ("", {}, 0, False) or k in ("address", "kind", "status")}

    @classmethod
    def from_dict(cls, d: dict):
        names = cls.__dataclass_fields__
        sig = cls(**{k: v for k, v in d.items() if k in names})
        sig.points = {str(k): float(v) for k, v in (sig.points or {}).items()}
        return sig


def norm_address(address: str) -> str:
    return (address or "").strip().replace(" ", "").upper()


def canon_address(address: str) -> str:
    """Vergleichbare Form einer Adresse: Siemens-Adressen einheitlich deutsch ohne '%'/'P' (I0.0, %I0.0, E0.0 ->
    E0.0; PIW256, IW256 -> EW256), alle anderen nur ohne Leerzeichen und in Großbuchstaben."""
    parts = s7_parts(address)
    if not parts:
        return norm_address(address)
    area, width, byte, bit = parts
    if area.startswith("DB"):
        return f"{area}.DB{width}{byte}" + (f".{bit}" if width == "X" else "")
    return f"{area}{'' if width == 'X' else width}{byte}" + (f".{bit}" if width == "X" else "")


def user_name() -> str:
    return os.environ.get("USERNAME") or os.environ.get("USER") or ""


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def set_status(sig: IoSignal, status: str, remark=None, checker=None):
    """Prüfstatus setzen (mit Zeit und Prüfer); "offen" setzt auch Zeit, Prüfer, Flanken und Messpunkte zurück."""
    sig.status = status
    if status == "offen":
        sig.checked_at, sig.checker, sig.seen, sig.points = "", "", 0, {}
    else:
        sig.checked_at, sig.checker = now_text(), user_name() if checker is None else checker
    if remark is not None:
        sig.remark = remark


# ---------------------------------------------------------------------------------------------------------------------
# Adressen: Signalart und Datentyp ableiten (Siemens-Schreibweise, auch %I0.0, PEW256, englisch)
# ---------------------------------------------------------------------------------------------------------------------
_RE_S7 = re.compile(r"^%?(P?)([EIAQM])([XBWD]?)(\d+)(?:\.([0-7]))?$")
_RE_DBX = re.compile(r"^DB(\d+)\.DB([XBWD])(\d+)(?:\.([0-7]))?$")
_IN, _OUT = {"E", "I"}, {"A", "Q"}
_DTYPES = {"BOOL": "BOOL", "BIT": "BOOL", "BYTE": "BYTE", "WORD": "WORD", "INT": "INT", "DINT": "DINT",
           "DWORD": "DWORD", "REAL": "REAL", "UINT": "UINT", "UDINT": "UDINT", "USINT": "USINT", "SINT": "SINT",
           "LREAL": "LREAL", "FLOAT": "REAL", "DOUBLE": "LREAL", "SHORT": "INT"}


def s7_parts(address: str):
    """'%IW256' / 'PEW256' / 'E1.3' -> (Bereich 'E'|'A'|'M'|'DBn', Breite 'X'|'B'|'W'|'D', Byte, Bit) oder None."""
    a = norm_address(address)
    m = _RE_S7.match(a)
    if m:
        area = {"I": "E", "Q": "A"}.get(m.group(2), m.group(2))
        width = m.group(3) or ("X" if m.group(5) is not None else "")
        if not width:
            return None
        return area, width, int(m.group(4)), int(m.group(5) or 0)
    m = _RE_DBX.match(a)
    if m:
        return "DB" + m.group(1), m.group(2), int(m.group(3)), int(m.group(4) or 0)
    return None


def guess_kind_dtype(address: str, kind_text: str = "", dtype_text: str = ""):
    """Signalart (DI/DO/AI/AO) und Datentyp aus Spalten bzw. Adresse ableiten."""
    dtype = _DTYPES.get((dtype_text or "").strip().upper(), "")
    kind = _parse_kind(kind_text)
    parts = s7_parts(address)
    if parts:
        area, width, _byte, _bit = parts
        if not dtype:
            dtype = {"X": "BOOL", "B": "BYTE", "W": "INT", "D": "DINT"}[width]
        if not kind:
            binary = dtype == "BOOL"
            if area in ("E", "I"):
                kind = "DI" if binary else "AI"
            elif area in ("A", "Q"):
                kind = "DO" if binary else "AO"
    dtype = dtype or ("BOOL" if kind in ("DI", "DO") else "INT" if kind else "BOOL")
    kind = kind or ("DI" if dtype == "BOOL" else "AI")
    return kind, dtype


def _parse_kind(text: str) -> str:
    t = (text or "").strip().upper().replace(" ", "").replace("-", "")
    if not t:
        return ""
    table = {"DI": "DI", "DE": "DI", "DIGITALEINGANG": "DI", "DIGITALINPUT": "DI", "BE": "DI", "EINGANG": "DI",
             "INPUT": "DI", "DO": "DO", "DA": "DO", "DQ": "DO", "DIGITALAUSGANG": "DO", "DIGITALOUTPUT": "DO",
             "BA": "DO", "AUSGANG": "DO", "OUTPUT": "DO", "AI": "AI", "AE": "AI", "ANALOGEINGANG": "AI",
             "ANALOGINPUT": "AI", "AO": "AO", "AA": "AO", "AQ": "AO", "ANALOGAUSGANG": "AO", "ANALOGOUTPUT": "AO"}
    return table.get(t, "")


def driver_address(address: str, driver_id: str, symbol: str = "", kind: str = "") -> str:
    """Adresse in die Schreibweise des Treibers bringen: s7/logo ohne '%' und Peripherie-'P' (PEW256 -> EW256),
    ADS mit '%' (TwinCAT: %IX0.1), tia über den Symbolnamen (IArea.<Name> bzw. QArea.<Name>)."""
    a = norm_address(address)
    parts = s7_parts(a)
    if not parts:
        return (address or "").strip()
    area, width, byte, bit = parts
    if driver_id == "s7":
        return canon_address(a)
    if driver_id == "ads" and not area.startswith("DB"):
        letter = {"E": "I", "A": "Q"}.get(area, area)
        return f"%{letter}{width}{byte}" + (f".{bit}" if width == "X" else "")
    if driver_id == "tia" and symbol and not area.startswith("DB"):
        return f"{ {'E': 'IArea', 'A': 'QArea', 'M': 'MArea'}[area] }.{symbol}"
    return (address or "").strip()


# ---------------------------------------------------------------------------------------------------------------------
# IO-Liste importieren
# ---------------------------------------------------------------------------------------------------------------------
# Feld -> mögliche Spaltenüberschriften (klein geschrieben, ohne Leer-/Sonderzeichen; erster Treffer gilt)
COLUMNS = {
    "address": ["adresse", "address", "logischeadresse", "logicaladdress", "operand", "eaadresse", "ioadresse",
                "absoluteadresse", "absoluteaddress", "tag", "tagname", "nodeid", "gerät", "device"],
    "symbol": ["symbol", "name", "symbolname", "variable", "signal", "signalname"],
    "comment": ["kommentar", "comment", "beschreibung", "description", "text", "funktion", "function",
                "bezeichnung"],
    "bmk": ["bmk", "betriebsmittelkennzeichen", "kennzeichen", "betriebsmittel", "devicetag", "tagid", "akz"],
    "group": ["gruppe", "schrank", "baugruppe", "ort", "ortskennzeichen", "group", "cabinet", "station", "modul",
              "module", "anlage", "anlagenteil"],
    "kind": ["typ", "art", "signalart", "kind", "signaltype", "iotyp", "iotype", "type"],
    "dtype": ["datentyp", "datatype", "dtype"],
    "plc": ["steuerung", "sps", "plc", "controller", "cpu"],
    "raw_min": ["rohwertmin", "rohmin", "rawmin", "rohwertvon"],
    "raw_max": ["rohwertmax", "rohmax", "rawmax", "rohwertbis"],
    "eng_min": ["messbereichmin", "bereichvon", "min", "skalmin", "engmin", "unten", "messbereichvon"],
    "eng_max": ["messbereichmax", "bereichbis", "max", "skalmax", "engmax", "oben", "messbereichbis"],
    "range": ["messbereich", "bereich", "range", "measuringrange"],
    "unit": ["einheit", "unit"],
    "status": ["status", "prüfstatus", "ergebnis"],
    "remark": ["bemerkung", "remark", "notiz", "note"],
}


def _key(text) -> str:
    return re.sub(r"[^0-9a-zäöüß]", "", str(text or "").lower())


def map_columns(header) -> dict:
    """{Feld: Spaltenindex} aus der Kopfzeile."""
    keys = [_key(h) for h in header]
    found = {}
    for fld, names in COLUMNS.items():
        for name in names:
            if name in keys and keys.index(name) not in found.values():
                found[fld] = keys.index(name)
                break
    return found


def _num(text, default=None):
    if text in (None, ""):
        return default
    if isinstance(text, (int, float)):
        return float(text)
    try:
        return float(str(text).strip().replace(",", "."))
    except ValueError:
        return default


_RE_RANGE = re.compile(r"^\s*(-?[\d.,]+)\s*(?:\.\.\.?|…|-|–|bis|to)\s*(-?[\d.,]+)\s*(.*)$", re.I)


def parse_range(text):
    """'0 … 10 bar' / '4-20 mA' / '-50..150 °C' -> (min, max, Einheit) oder None."""
    m = _RE_RANGE.match(str(text or ""))
    if not m:
        return None
    lo, hi = _num(m.group(1)), _num(m.group(2))
    if lo is None or hi is None:
        return None
    return lo, hi, m.group(3).strip()


_STATUS_IN = {"ok": "ok", "io": "ok", "i.o.": "ok", "geprüft": "ok", "fehler": "fehler", "nio": "fehler",
              "n.i.o.": "fehler", "error": "fehler", "übersprungen": "uebersprungen", "skipped": "uebersprungen",
              "entfällt": "uebersprungen"}


def import_rows(header, rows):
    """Zeilen einer Tabelle -> (Signale, Warnungen). Zeilen ohne Adresse entfallen (z. B. Zwischenüberschriften)."""
    cols = map_columns(header)
    if "address" not in cols:
        raise ValueError(tr("Die Tabelle hat keine Spalte „Adresse“ (erkannt werden z. B. Adresse, Address, "
                            "Logische Adresse, Operand, Tag-Name)."))

    def cell(row, fld):
        i = cols.get(fld)
        if i is None or i >= len(row) or row[i] is None:
            return ""
        v = row[i]
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        return str(v).strip()

    signals, warnings, seen = [], [], set()
    for n, row in enumerate(rows, start=2):
        address = cell(row, "address")
        if not address:
            continue
        kind, dtype = guess_kind_dtype(address, cell(row, "kind"), cell(row, "dtype"))
        sig = IoSignal(address=address.lstrip("%") if s7_parts(address) else address, symbol=cell(row, "symbol"),
                       comment=cell(row, "comment"), bmk=cell(row, "bmk"), group=cell(row, "group"), kind=kind,
                       dtype=dtype, plc=cell(row, "plc"), unit=cell(row, "unit"), remark=cell(row, "remark"))
        rng = parse_range(cell(row, "range"))
        if rng:
            sig.eng_min, sig.eng_max = rng[0], rng[1]
            sig.unit = sig.unit or rng[2]
        sig.eng_min = _num(cell(row, "eng_min"), sig.eng_min)
        sig.eng_max = _num(cell(row, "eng_max"), sig.eng_max)
        sig.raw_min = _num(cell(row, "raw_min"), sig.raw_min)
        sig.raw_max = _num(cell(row, "raw_max"), sig.raw_max)
        st = _STATUS_IN.get(cell(row, "status").lower())
        if st:
            sig.status = st
        if sig.key in seen:
            warnings.append(tr("Zeile {0}: Adresse {1} doppelt – übersprungen").format(n, address))
            continue
        seen.add(sig.key)
        signals.append(sig)
    return signals, warnings


def import_file(path):
    from plc_export import read_table
    header, rows = read_table(path)
    if not header:
        raise ValueError(tr("Die Datei enthält keine Daten."))
    return import_rows(header, rows)


# ---------------------------------------------------------------------------------------------------------------------
# Bereiche scannen und Matrix-Anordnung
# ---------------------------------------------------------------------------------------------------------------------
@dataclass
class ScanRange:
    """Zusammenhängende Bits ohne IO-Liste, z. B. E0.0 + 256 Bits (= E0.0 … E31.7)."""
    start: str = "E0.0"
    count: int = 64
    plc: str = ""

    def addresses(self, driver_id: str) -> list:
        drv = get_driver(driver_id)
        blk = Block(name="scan", address=driver_address(self.start, driver_id), dtype="BOOL",
                    count=max(1, int(self.count)), driver=driver_id)
        return [drv.block_element_address(blk, i) for i in range(blk.count)]


def scan_signals(rng: ScanRange, driver_id: str, existing: dict) -> list:
    """Signale eines Scan-Bereichs; Adressen, die schon in der IO-Liste stehen, werden übernommen (gleiches Objekt)."""
    out = []
    for a in rng.addresses(driver_id):
        sig = existing.get((rng.plc, canon_address(a)))
        if sig is None:
            parts = s7_parts(a)
            kind = "DO" if parts and parts[0] == "A" else "DI"
            sig = IoSignal(address=a, kind=kind, dtype="BOOL", plc=rng.plc, scanned=True)
        out.append(sig)
    return out


def matrix_rows(signals, per_row: int = 8):
    """Binärsignale als Matrix: [(Abschnitt, Zeilenbeschriftung, [Signal oder None] * per_row)].

    Siemens-Bitadressen (E12.3, A4.0, M10.1, DB5.DBX2.7) werden nach Byte und Bit angeordnet (Spalte = Bitnummer),
    alle anderen der Reihe nach je per_row Signale."""
    by_byte, other = {}, []
    for sig in signals:
        if not sig.binary:
            continue
        parts = s7_parts(sig.address)
        if parts and parts[1] == "X":
            by_byte.setdefault((sig.plc, parts[0], parts[2]), [None] * 8)[parts[3]] = sig
        else:
            other.append(sig)
    order = {"E": 0, "A": 1, "M": 2}
    rows = []
    for (plc, area, byte), cells in sorted(by_byte.items(), key=lambda kv: (kv[0][0], order.get(kv[0][1], 3),
                                                                            kv[0][1], kv[0][2])):
        section = {"E": tr("Eingänge"), "A": tr("Ausgänge"), "M": tr("Merker")}.get(area, area)
        if plc:
            section = f"{plc} · {section}"
        rows.append((section, f"{area}{byte}" if not area.startswith("DB") else f"{area}.DBB{byte}", cells))
    for k in range(0, len(other), per_row):
        chunk = other[k:k + per_row]
        section = tr("Weitere Signale")
        rows.append((section, chunk[0].address, chunk + [None] * (per_row - len(chunk))))
    return rows


# ---------------------------------------------------------------------------------------------------------------------
# Analogwerte
# ---------------------------------------------------------------------------------------------------------------------
def scale(sig: IoSignal, raw: float) -> float:
    span = sig.raw_max - sig.raw_min
    if not span or math.isnan(raw):
        return math.nan
    return sig.eng_min + (raw - sig.raw_min) * (sig.eng_max - sig.eng_min) / span


def point_target(sig: IoSignal, pct: float) -> float:
    return sig.eng_min + (sig.eng_max - sig.eng_min) * pct / 100.0


def point_ok(sig: IoSignal, pct: float, eng: float, tol_pct: float) -> bool:
    span = abs(sig.eng_max - sig.eng_min) or 1.0
    return not math.isnan(eng) and abs(eng - point_target(sig, pct)) <= span * tol_pct / 100.0


def analog_fault(sig: IoSignal, raw: float) -> str:
    """Fehlerwert bzw. Bereichsverletzung eines Analogeingangs, sonst ""."""
    if math.isnan(raw):
        return ""
    if sig.raw_max == S7_RAW_MAX and sig.raw_min in (0, -S7_RAW_MAX):
        # Siemens: 32767 Überlauf/Drahtbruch (mit Diagnose), -32768 Unterlauf; 27649 … 32511 Übersteuerung
        if raw >= 32767:
            return tr("Überlauf bzw. Drahtbruch (32767)")
        if raw <= -32768:
            return tr("Unterlauf bzw. Drahtbruch (−32768)")
        if raw > 32511:
            return tr("Überlauf")
        if raw > S7_RAW_MAX:
            return tr("Übersteuerungsbereich (> 100 %)")
        if sig.raw_min == 0 and raw < -4864:
            return tr("Unterlauf (Drahtbruch bei 4 … 20 mA?)")
        if sig.raw_min == 0 and raw < 0:
            return tr("Untersteuerungsbereich (< 0 %)")
        return ""
    span = sig.raw_max - sig.raw_min
    if span and (raw > sig.raw_max + 0.176 * span or raw < sig.raw_min - 0.176 * span):
        return tr("Außerhalb des Messbereichs")
    return ""


# ---------------------------------------------------------------------------------------------------------------------
# Verfolgen der Werte
# ---------------------------------------------------------------------------------------------------------------------
@dataclass
class Change:
    ts: float
    sig: IoSignal
    old: float
    new: float
    expected: IoSignal = None             # gesetzt: Vertauschung? (erwartet war dieses Signal)
    note: str = ""


class IoTracker:
    """Wertet die gelesenen Werte aus: Wechsel, Flanken, Vertauschungen, Analog-Prüfpunkte.

    auto_ok: digitale Signale nach 0→1→0 automatisch abhaken (nur Signale mit Status „offen“).
    expected: das Signal, das gerade geprüft wird (Auswahl in der Liste) – wechselt stattdessen ein anderes
    Eingangssignal, meldet der Tracker eine mögliche Vertauschung.
    auto_points: Analog-Prüfpunkte des erwarteten Signals automatisch übernehmen, wenn der Wert 1 s lang innerhalb
    der Toleranz um 0/50/100 % liegt."""

    HISTORY = 200
    STABLE_S = 1.0
    SWAP_QUIET_S = 3.0

    def __init__(self):
        self.auto_ok = False
        self.auto_points = True
        self.tolerance = 1.0              # % des Messbereichs
        self.expected = None
        self.history = []                 # neueste zuerst
        self.status_changed = []          # Signale, deren Status sich automatisch geändert hat (seit dem Abholen)

    def _log(self, ch: Change):
        self.history.insert(0, ch)
        del self.history[self.HISTORY:]

    def feed(self, sig: IoSignal, value: float, ts: float, error: str = ""):
        """Neuen Wert eines Signals verarbeiten. Rückgabe: Change oder None."""
        sig.error = error
        old = sig.value
        if value is None or math.isnan(value):
            sig.value = math.nan
            return None
        if sig.binary:
            value = 1.0 if value >= 0.5 else 0.0
        sig.value = value
        if math.isnan(old):
            sig.logged = value
            return None
        if sig.binary:
            if value == old:
                return None
            sig.seen |= SEEN_RISE if value else (SEEN_FALL if sig.seen & SEEN_RISE else 0)
            if self.auto_ok and sig.status == "offen" and sig.seen & SEEN_RISE and sig.seen & SEEN_FALL:
                set_status(sig, "ok", remark=sig.remark or tr("automatisch (0→1→0 erkannt)"))
                sig.seen = SEEN_RISE | SEEN_FALL
                self.status_changed.append(sig)
        else:
            self._analog_points(sig, value, ts)
            span = abs(sig.raw_max - sig.raw_min) or 1.0
            if not math.isnan(sig.logged) and abs(value - sig.logged) < 0.02 * span:
                return None                   # Rauschen: erst ab 2 % des Messbereichs melden
            old, sig.logged = sig.logged, value
        ch = Change(ts, sig, old, value)
        exp = self.expected
        if exp is not None and exp is not sig and sig.is_input and sig.binary and exp.binary \
                and ts - exp.changed > self.SWAP_QUIET_S:
            ch.expected = exp
            ch.note = tr("Vertauschung? Erwartet {0}, gekommen {1}").format(exp.label, sig.label)
        sig.changed = ts
        self._log(ch)
        return ch

    def _analog_points(self, sig: IoSignal, value: float, ts: float):
        if not self.auto_points or sig is not self.expected:
            return
        eng = scale(sig, value)
        hit = next((p for p in POINTS if point_ok(sig, p, eng, self.tolerance)), None)
        if hit is None:
            sig.stable_point = None
            return
        if sig.stable_point != hit:
            sig.stable_point, sig.stable_since = hit, ts
            return
        if ts - sig.stable_since >= self.STABLE_S and str(hit) not in sig.points:
            sig.points[str(hit)] = round(eng, 6)
            if all(str(p) in sig.points for p in POINTS) and sig.status == "offen":
                set_status(sig, "ok", remark=sig.remark or tr("Prüfpunkte 0/50/100 % in Toleranz"))
                self.status_changed.append(sig)

    def take_point(self, sig: IoSignal, pct: int):
        """Prüfpunkt von Hand übernehmen (aktueller Wert). Rückgabe: in Toleranz?"""
        eng = scale(sig, sig.value)
        if math.isnan(eng):
            return False
        sig.points[str(pct)] = round(eng, 6)
        return point_ok(sig, pct, eng, self.tolerance)

    def pop_status_changes(self):
        out, self.status_changed = self.status_changed, []
        return out


def progress(signals):
    """{"gesamt", "ok", "fehler", "uebersprungen", "offen"} für die Fortschrittsanzeige."""
    out = {"gesamt": len(signals), "ok": 0, "fehler": 0, "uebersprungen": 0, "offen": 0}
    for s in signals:
        out[s.status if s.status in out else "offen"] += 1
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Speichern, Laden, Ergebnis
# ---------------------------------------------------------------------------------------------------------------------
@dataclass
class IoProject:
    signals: list = field(default_factory=list)
    scans: list = field(default_factory=list)
    config: str = ""                       # Konfigurationsdatei (Steuerungen)
    options: dict = field(default_factory=dict)
    path: str = ""

    def save(self, path=None):
        path = path or self.path
        doc = {"format": FORMAT, "version": 1, "gespeichert": now_text(), "config": self.config,
               "options": self.options, "scans": [asdict(s) for s in self.scans],
               "signals": [s.to_dict() for s in self.signals]}
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        self.path = path

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        if doc.get("format") != FORMAT:
            raise ValueError(tr("{0} ist keine IO-Check-Datei.").format(os.path.basename(path)))
        return cls(signals=[IoSignal.from_dict(d) for d in doc.get("signals", [])],
                   scans=[ScanRange(**{k: v for k, v in d.items() if k in ScanRange.__dataclass_fields__})
                          for d in doc.get("scans", [])],
                   config=doc.get("config", ""), options=doc.get("options", {}), path=path)


RESULT_HEADER = [N_("Steuerung"), N_("Adresse"), N_("Symbol"), N_("Kommentar"), N_("BMK"), N_("Gruppe"), N_("Typ"),
                 N_("Status"), N_("Geprüft am"), N_("Prüfer"), N_("Bemerkung"), N_("Messpunkte")]


def result_rows(signals):
    rows = []
    for s in signals:
        pts = ", ".join(f"{p} %: {s.points[str(p)]:g}{(' ' + s.unit) if s.unit else ''}"
                        for p in POINTS if str(p) in s.points)
        rows.append([s.plc, s.address, s.symbol, s.comment, s.bmk, s.group, s.kind, tr(STATUS.get(s.status, s.status)),
                     s.checked_at, s.checker, s.remark, pts])
    return rows


def write_result(path, signals):
    from plc_export import write_table
    write_table(path, [tr(h) for h in RESULT_HEADER], result_rows(signals), sheet=tr("IO-Check"))


# ---------------------------------------------------------------------------------------------------------------------
# Lesen
# ---------------------------------------------------------------------------------------------------------------------
def make_variables(driver_id: str, signals):
    """Variablen zum Lesen der Signale einer Steuerung. s7: benachbarte Adressen werden zu Blöcken
    zusammengefasst (eine Anfrage je Bereich statt je Signal)."""
    out = []
    for k, s in enumerate(signals):
        out.append(Variable(name=f"io{k}", address=driver_address(s.address, driver_id, s.symbol, s.kind),
                            dtype=s.dtype))
    if driver_id != "s7":
        return out
    from plc_treiber.s7 import S7_TYPES, parse
    groups = {}
    for v in out:
        try:
            area, db, byte, _bit, _l = parse(v.address)
        except ValueError:
            continue
        size = 1 if v.dtype == "BOOL" else S7_TYPES.get(v.dtype, (4,))[0]
        groups.setdefault((area, db), []).append((byte, size, v))
    n = 0
    for (_area, _db), items in groups.items():
        items.sort(key=lambda x: x[0])
        start = end = None
        for byte, size, v in items:
            # neuer Block bei Lücke > 32 Byte oder Blockgröße > 200 Byte (PDU-Grenze)
            if start is None or byte - end > 32 or byte + size - start > 200:
                n += 1
                start, end = byte, byte + size
            else:
                end = max(end, byte + size)
            v.block = f"io{n}"
    return out


class IoReader(threading.Thread):
    """Liest die Signale EINER Steuerung zyklisch und stellt (Steuerung, Zeit, Werte, Fehler) in die Warteschlange.
    Status ("verbinde", "ok", "fehler", Text) ebenfalls über die Warteschlange. demo: simulierte Werte."""

    def __init__(self, idx: int, plc: Plc, signals, out: queue.Queue, interval_ms=200, demo=False):
        super().__init__(name=f"iocheck-{plc.name}", daemon=True)
        self.idx, self.plc, self.signals, self.out = idx, plc, list(signals), out
        self.interval = max(0.05, interval_ms / 1000.0)
        self.demo = demo
        self.stop_evt = threading.Event()

    def stop(self):
        self.stop_evt.set()

    def _status(self, state, text):
        self.out.put(("status", self.idx, state, text))

    def run(self):
        if self.demo:
            return self._run_demo()
        try:
            driver = get_driver(self.plc.driver)
            variables = make_variables(self.plc.driver, self.signals)
            reader = driver.create_reader(self.plc, variables)
        except Exception as e:
            self._status("fehler", tr("Treiber {0}: {1}").format(self.plc.driver, e))
            return
        connected = False
        while not self.stop_evt.is_set():
            if not connected:
                self._status("verbinde", tr("Verbinde mit {0} …").format(self.plc.summary()))
                try:
                    reader.connect()
                    connected = True
                    self._status("ok", tr("Verbunden mit {0}").format(self.plc.summary()))
                except Exception as e:
                    self._status("fehler", tr("Verbindung fehlgeschlagen: {0}").format(e))
                    self.stop_evt.wait(2.0)
                    continue
            t0 = time.perf_counter()
            try:
                values = reader.read()
            except Exception as e:
                connected = False
                reader.close()
                self._status("fehler", tr("Lesefehler: {0} – neuer Verbindungsversuch").format(e))
                self.stop_evt.wait(1.0)
                continue
            errors = {}
            for k, v in enumerate(variables):
                if v.address in reader.errors:
                    errors[k] = reader.errors[v.address]
            self.out.put(("values", self.idx, time.time(), values, errors))
            self.stop_evt.wait(max(0.0, self.interval - (time.perf_counter() - t0)))
        reader.close()
        self._status("aus", tr("Getrennt"))

    def _run_demo(self):
        """Simulation: digitale Eingänge schalten gelegentlich (wie ein Monteur im Feld), Analogwerte wandern."""
        self._status("ok", tr("Demo-Modus (simulierte Werte)"))
        rnd = random.Random(1)
        state = [0.0] * len(self.signals)
        t0 = time.time()
        while not self.stop_evt.is_set():
            ts = time.time()
            for k, s in enumerate(self.signals):
                if s.binary:
                    if rnd.random() < (0.004 if s.is_input else 0.001):
                        state[k] = 1.0 - state[k]
                else:
                    pct = 50 + 50 * math.sin((ts - t0) / (20 + k % 7))
                    state[k] = s.raw_min + (s.raw_max - s.raw_min) * pct / 100.0 + rnd.uniform(-20, 20)
            self.out.put(("values", self.idx, ts, list(state), {}))
            self.stop_evt.wait(self.interval)
        self._status("aus", tr("Getrennt"))


def assign_plcs(signals, plcs):
    """Signale den Steuerungen zuordnen: {Index der Steuerung: [Signale]} und Liste unbekannter Namen."""
    names = {p.name: i for i, p in enumerate(plcs)}
    out, unknown = {}, set()
    for s in signals:
        if not plcs:
            unknown.add(s.plc or "?")
            continue
        idx = names.get(s.plc, 0 if not s.plc else None)
        if idx is None:
            unknown.add(s.plc)
            continue
        out.setdefault(idx, []).append(s)
    return out, sorted(unknown)
