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
# Analogeingänge: Drahtbruchprüfung (Verdrahtung öffnen -> Fehlerwert, schließen -> wieder gültig)
SEEN_BREAK, SEEN_BACK = 4, 8


@dataclass(eq=False)                      # Vergleich über die Identität (Signale stehen in Mengen)
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
    photos: list = field(default_factory=list)   # Fotos (Dateinamen im Fotoordner des Prüfstands)

    def __post_init__(self):
        """Laufzeitfelder anlegen, die nicht gespeichert werden (letzter Wert, Zeit des Wechsels, Lesefehler, Zustand
        der automatischen Prüfpunkte).
        """
        self.value = math.nan             # letzter Wert (binär 0/1, analog Rohwert)
        self.changed = 0.0                # Zeitpunkt des letzten Wechsels (time.time())
        self.error = ""                   # Lesefehler dieses Signals
        self.stable_since = 0.0           # Analog: Wert seit … in der Nähe eines Prüfpunkts
        self.stable_point = None
        self.logged = math.nan            # Analog: zuletzt gemeldeter Wert („Was hat sich bewegt?“)

    @property
    def key(self):
        """Eindeutiger Schlüssel (Steuerung, vereinheitlichte Adresse) – erkennt dasselbe Signal auch in anderer
        Schreibweise.
        """
        return (self.plc, canon_address(self.address))

    @property
    def binary(self) -> bool:
        """True bei Digitalsignalen (DI/DO)."""
        return self.kind in ("DI", "DO")

    @property
    def is_input(self) -> bool:
        """True bei Eingängen (DI/AI) – nur sie können sich „im Feld“ bewegen und vertauscht sein."""
        return self.kind in ("DI", "AI")

    @property
    def label(self) -> str:
        """Anzeigename: Symbol, sonst Adresse."""
        return self.symbol or self.address

    def to_dict(self) -> dict:
        """Für die Prüfstand-Datei: nur Felder mit Inhalt (spart Platz), Adresse, Art und Status immer."""
        d = asdict(self)
        return {k: v for k, v in d.items() if v not in ("", {}, [], 0, False) or k in ("address", "kind", "status")}

    @classmethod
    def from_dict(cls, d: dict):
        """Signal aus der Prüfstand-Datei; unbekannte Felder (neuere Versionen) werden ignoriert."""
        names = cls.__dataclass_fields__
        sig = cls(**{k: v for k, v in d.items() if k in names})
        sig.points = {str(k): float(v) for k, v in (sig.points or {}).items()}
        sig.photos = [str(n) for n in (sig.photos or []) if valid_photo_name(n)]
        return sig


# ---------------------------------------------------------------------------------------------------------------------
# Fotos zu Signalen: JPEG/PNG im Ordner „<Prüfstand>_fotos“ neben der Prüfstand-Datei
# ---------------------------------------------------------------------------------------------------------------------
PHOTO_MAX_BYTES = 20 * 1024 * 1024
PHOTO_TYPES = {b"\xff\xd8": ".jpg", b"\x89PNG\r\n\x1a\n": ".png"}


def valid_photo_name(name) -> bool:
    """Nur einfache Dateinamen (kein Pfad) mit .jpg/.png."""
    name = str(name)
    return (bool(name) and os.path.basename(name) == name and name not in (".", "..")
            and os.path.splitext(name)[1].lower() in (".jpg", ".png"))


def photo_dir(project_path: str) -> str:
    """Fotoordner eines Prüfstands: „Anlage.iocheck.json“ -> „Anlage_fotos“ daneben; ohne Datei ""."""
    if not project_path:
        return ""
    base = project_path[:-len(EXTENSION)] if project_path.endswith(EXTENSION) else os.path.splitext(project_path)[0]
    return base + "_fotos"


def photo_type(data: bytes) -> str:
    """Dateiendung zu Bilddaten (".jpg"/".png") oder "" bei anderen Daten."""
    for magic, ext in PHOTO_TYPES.items():
        if data[:len(magic)] == magic:
            return ext
    return ""


def add_photo(sig, folder: str, data: bytes) -> str:
    """Foto (JPEG/PNG-Daten) im Fotoordner speichern und beim Signal eintragen. Rückgabe: Dateiname.
    Wirft ValueError bei anderem Format, zu großen Daten oder fehlendem Ordner (Prüfstand nicht gespeichert)."""
    ext = photo_type(data)
    if not ext:
        raise ValueError(tr("Kein JPEG- oder PNG-Bild."))
    if len(data) > PHOTO_MAX_BYTES:
        raise ValueError(tr("Bild zu groß (höchstens {0} MB).").format(PHOTO_MAX_BYTES // (1024 * 1024)))
    if not folder:
        raise ValueError(tr("Prüfstand zuerst speichern – die Fotos liegen in einem Ordner daneben."))
    os.makedirs(folder, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", canon_address(sig.address)).strip("_.") or "signal"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    n = 1
    while True:
        name = f"{stem}_{stamp}" + (f"_{n}" if n > 1 else "") + ext
        if not os.path.exists(os.path.join(folder, name)):
            break
        n += 1
    tmp = os.path.join(folder, name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, os.path.join(folder, name))
    sig.photos.append(name)
    return name


def remove_photo(sig, folder: str, name: str) -> bool:
    """Foto vom Signal entfernen und die Datei löschen. Rückgabe: True, wenn es eingetragen war."""
    if name not in sig.photos:
        return False
    sig.photos.remove(name)
    if folder and valid_photo_name(name):
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass
    return True


def protocol_photos() -> bool:
    """Gespeicherte Wahl „Fotos im Protokoll“ (Einstellung ``iocheck_protokoll_fotos``, Standard: ja)."""
    try:
        from plc_common import load_settings
        return bool(load_settings().get("iocheck_protokoll_fotos", True))
    except Exception:
        return True


def norm_address(address: str) -> str:
    """Adresse ohne Leerzeichen und in Großbuchstaben."""
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


def system_user() -> str:
    """Angemeldeter Benutzer des Rechners (Windows-/Linux-Anmeldename)."""
    return os.environ.get("USERNAME") or os.environ.get("USER") or ""


def user_name() -> str:
    """Prüfer, wenn am PC abgehakt wird: der im IO-Check eingestellte Name bzw. das Kürzel (Einstellung
    ``iocheck_pruefer``), sonst der angemeldete Benutzer des Rechners."""
    try:
        from plc_common import load_settings
        name = str(load_settings().get("iocheck_pruefer") or "").strip()
    except Exception:
        name = ""
    return name or system_user()


def now_text() -> str:
    """Jetzt als „JJJJ-MM-TT hh:mm:ss“."""
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
    """Signalart aus einer Spalte „Typ“: DI, DE, Digitaleingang, Input … -> DI/DO/AI/AO oder ""."""
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
# Feld -> mögliche Spaltenüberschriften der IO-Liste (Vorgabe). Verglichen wird ohne Groß-/Kleinschreibung, Leer- und
# Sonderzeichen (siehe _key); die erste passende Überschrift gilt. Im IO-Check (Spalten …) lassen sich die Namen je Feld
# ändern; eine leere Liste schaltet das Feld ab (Spalte wird weder eingelesen noch angezeigt).
COLUMNS = {
    "address": ["Adresse", "Address", "Logische Adresse", "Logical Address", "Operand", "E/A-Adresse", "IO-Adresse",
                "Absolute Adresse", "Absolute Address", "Tag", "Tag Name", "NodeId", "Gerät", "Device"],
    "symbol": ["Symbol", "Name", "Symbolname", "Variable", "Signal", "Signalname"],
    "comment": ["Kommentar", "Comment", "Beschreibung", "Description", "Text", "Funktion", "Function",
                "Bezeichnung"],
    "bmk": ["BMK", "Betriebsmittelkennzeichen", "Kennzeichen", "Betriebsmittel", "Device Tag", "Tag ID", "AKZ"],
    "group": ["Gruppe", "Schrank", "Baugruppe", "Ort", "Ortskennzeichen", "Group", "Cabinet", "Station", "Modul",
              "Module", "Anlage", "Anlagenteil"],
    "kind": ["Typ", "Art", "Signalart", "Kind", "Signal Type", "IO-Typ", "IO Type", "Type"],
    "dtype": ["Datentyp", "Data Type", "DType"],
    "plc": ["Steuerung", "SPS", "PLC", "Controller", "CPU"],
    "raw_min": ["Rohwert min", "Roh min", "Raw min", "Rohwert von"],
    "raw_max": ["Rohwert max", "Roh max", "Raw max", "Rohwert bis"],
    "eng_min": ["Messbereich min", "Bereich von", "Min", "Skal min", "Eng min", "Unten", "Messbereich von"],
    "eng_max": ["Messbereich max", "Bereich bis", "Max", "Skal max", "Eng max", "Oben", "Messbereich bis"],
    "range": ["Messbereich", "Bereich", "Range", "Measuring Range"],
    "unit": ["Einheit", "Unit"],
    "status": ["Status", "Prüfstatus", "Ergebnis"],
    "remark": ["Bemerkung", "Remark", "Notiz", "Note"],
}

# Anzeigenamen der Felder im Dialog „Spalten der IO-Liste“ (Reihenfolge = Reihenfolge im Dialog)
FIELD_TEXT = {"address": N_("Adresse"), "symbol": N_("Symbol"), "comment": N_("Kommentar"), "bmk": N_("BMK"),
              "group": N_("Gruppe"), "kind": N_("Typ (DI/DO/AI/AO)"), "dtype": N_("Datentyp"), "plc": N_("Steuerung"),
              "range": N_("Messbereich (z. B. 0 … 10 bar)"), "eng_min": N_("Messbereich von"),
              "eng_max": N_("Messbereich bis"), "unit": N_("Einheit"), "raw_min": N_("Rohwert von"),
              "raw_max": N_("Rohwert bis"), "status": N_("Status"), "remark": N_("Bemerkung")}


def _key(text) -> str:
    """Spaltenüberschrift vergleichbar machen: klein, nur Buchstaben und Ziffern („Logische Adresse“ ->
    „logischeadresse“).
    """
    return re.sub(r"[^0-9a-zäöüß]", "", str(text or "").lower())


def load_aliases() -> dict:
    """Eigene Spaltenüberschriften je Feld aus den persönlichen Einstellungen: {Feld: [Überschrift, …]}.

    Nur geänderte Felder stehen darin; eine leere Liste bedeutet „Feld abgeschaltet“."""
    try:
        from plc_common import load_settings
        data = load_settings().get("iocheck_spalten", {})
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {f: [str(x) for x in v] for f, v in data.items() if f in COLUMNS and isinstance(v, list)}


def save_aliases(aliases: dict):
    """Eigene Spaltenüberschriften speichern; Felder, die der Vorgabe entsprechen, entfallen."""
    from plc_common import save_settings
    save_settings(iocheck_spalten={f: list(v) for f, v in aliases.items()
                                   if f in COLUMNS and list(v) != COLUMNS[f]})


def column_names(fld, aliases=None) -> list:
    """Gültige Überschriften eines Feldes: die eigenen, sonst die Vorgabe (leer = Feld abgeschaltet)."""
    aliases = load_aliases() if aliases is None else aliases
    return list(aliases[fld]) if fld in aliases else list(COLUMNS[fld])


def disabled_fields(aliases=None) -> set:
    """Felder ohne Überschrift: werden nicht eingelesen und im IO-Check nicht angezeigt (Adresse ist Pflicht)."""
    aliases = load_aliases() if aliases is None else aliases
    return {f for f in COLUMNS if f != "address" and not column_names(f, aliases)}


def map_columns(header, aliases=None) -> dict:
    """{Feld: Spaltenindex} aus der Kopfzeile (eigene Überschriften statt der Vorgabe, abgeschaltete Felder nie).

    Jede Spalte wird höchstens einem Feld zugeordnet; die Felder werden in der Reihenfolge von COLUMNS vergeben."""
    keys = [_key(h) for h in header]
    aliases = load_aliases() if aliases is None else aliases
    found = {}
    for fld in COLUMNS:
        for name in column_names(fld, aliases):
            k = _key(name)
            if k and k in keys and keys.index(k) not in found.values():
                found[fld] = keys.index(k)
                break
    return found


def _num(text, default=None):
    """Zahl aus einer Zelle (auch mit Dezimalkomma); leer oder ungültig: ``default``."""
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


def import_rows(header, rows, aliases=None):
    """Zeilen einer Tabelle -> (Signale, Warnungen). Zeilen ohne Adresse entfallen (z. B. Zwischenüberschriften).

    ``aliases``: eigene Spaltenüberschriften (Standard: aus den Einstellungen, siehe ``map_columns``)."""
    cols = map_columns(header, aliases)
    if "address" not in cols:
        raise ValueError(tr("Die Tabelle hat keine Spalte „Adresse“ (erkannt werden: {0}). Weitere Überschriften "
                            "lassen sich unter „Spalten …“ eintragen.").format(", ".join(column_names("address"))))

    def cell(row, fld):
        """Inhalt der Spalte für ``fld`` als Text (ganze Zahlen aus Excel ohne „.0“)."""
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


def read_list(path):
    """Tabelle einer IO-Liste lesen -> (Kopfzeile, Zeilen); leere Datei: ValueError."""
    from plc_export import read_table
    header, rows = read_table(path)
    if not header:
        raise ValueError(tr("Die Datei enthält keine Daten."))
    return header, rows


def import_file(path, aliases=None):
    """IO-Liste aus einer CSV-, Excel- oder ODS-Datei importieren -> (Signale, Warnungen)."""
    header, rows = read_list(path)
    return import_rows(header, rows, aliases)


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
        """Alle Bitadressen des Bereichs in der Schreibweise des Treibers (über dessen Blockadressen)."""
        drv = get_driver(driver_id)
        blk = Block(name="scan", address=driver_address(self.start, driver_id), dtype="BOOL",
                    count=max(1, int(self.count)), driver=driver_id)
        return [drv.block_element_address(blk, i) for i in range(blk.count)]


def change_address(sig: IoSignal, address: str):
    """Adresse eines Signals ändern (Siemens-Schreibweise ohne '%'); wechselt dabei Bereich oder Breite (z. B. E -> A,
    Bit -> Wort), werden Signalart und Datentyp neu aus der Adresse abgeleitet."""
    address = (address or "").strip()
    new, old = s7_parts(canon_address(address)), s7_parts(canon_address(sig.address))   # E/I, %, P einheitlich
    if new and (not old or new[:2] != old[:2]):
        sig.kind, sig.dtype = guess_kind_dtype(address)
    sig.address = address.lstrip("%") if new else address


def worth_saving(sig: IoSignal) -> bool:
    """Signal aus einem Scan-Bereich mit Inhalt (Status, Bemerkung, Messpunkte oder eingetragene Texte)."""
    return bool(sig.status != "offen" or sig.remark or sig.points or sig.photos or sig.symbol or sig.comment or sig.bmk
                or sig.group)


CHECK_FIELDS = ("status", "checked_at", "checker", "remark", "points", "seen", "photos")


def update_list(old, new):
    """IO-Liste aktualisieren: ``new`` (frisch importiert) übernimmt von Signalen gleicher Adresse (und Steuerung) aus
    ``old`` den Prüfstand (Status, Zeit, Prüfer, Bemerkung, Messpunkte); Texte, Typ, Messbereich kommen aus der neuen
    Liste. Rückgabe: (neue Liste, Anzahl übernommener Prüfeinträge, entfallene Signale aus ``old``)."""
    by_key = {s.key: s for s in old}
    kept = 0
    for s in new:
        o = by_key.pop(s.key, None)
        if o is None:
            continue
        for name in CHECK_FIELDS:
            setattr(s, name, getattr(o, name))
        s.points = dict(o.points)
        s.photos = list(o.photos)
        if o.status != "offen" or o.remark or o.photos:
            kept += 1
    return new, kept, [o for o in by_key.values() if not o.scanned]


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
            # Zeile je (Steuerung, Bereich, Byte); Spalte = Bitnummer.
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
    """Rohwert in die technische Einheit umrechnen (lineare Skalierung Rohwert min/max -> Messbereich min/max)."""
    span = sig.raw_max - sig.raw_min
    if not span or math.isnan(raw):
        return math.nan
    return sig.eng_min + (raw - sig.raw_min) * (sig.eng_max - sig.eng_min) / span


def point_target(sig: IoSignal, pct: float) -> float:
    """Sollwert eines Prüfpunkts (0/50/100 %) in der technischen Einheit."""
    return sig.eng_min + (sig.eng_max - sig.eng_min) * pct / 100.0


def point_ok(sig: IoSignal, pct: float, eng: float, tol_pct: float) -> bool:
    """True, wenn der Messwert ``eng`` innerhalb der Toleranz (in % des Messbereichs) um den Prüfpunkt liegt."""
    span = abs(sig.eng_max - sig.eng_min) or 1.0
    return not math.isnan(eng) and abs(eng - point_target(sig, pct)) <= span * tol_pct / 100.0


def analog_broken(sig: IoSignal, raw: float) -> bool:
    """Unterbrechung erkannt: Fehlerwert der Baugruppe (Drahtbruch, Über-/Unterlauf) oder Wert deutlich unter dem
    Messbereichsanfang (4 … 20 mA ohne Strom). Bei 0 … 10 V / 0 … 20 mA ist eine Unterbrechung nicht erkennbar."""
    if math.isnan(raw):
        return False
    if sig.raw_max == S7_RAW_MAX and sig.raw_min in (0, -S7_RAW_MAX):
        # Siemens: Überlauf (> 32511, 32767 = Drahtbruch mit Diagnose), Unterlauf (< -4864 bzw. -32768); der Über-/
        # Untersteuerungsbereich (bis ±17,6 %) gilt noch als gültiger Wert
        return raw > 32511 or raw < (-4864 if sig.raw_min == 0 else -32512)
    span = abs(sig.raw_max - sig.raw_min) or 1.0
    return raw > max(sig.raw_min, sig.raw_max) + 0.176 * span or raw < min(sig.raw_min, sig.raw_max) - 0.176 * span


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
    """Ein erkannter Wechsel eines Signals (für „Was hat sich bewegt?“), ggf. mit Hinweis auf Vertauschung."""
    ts: float
    sig: IoSignal
    old: float
    new: float
    expected: IoSignal = None             # gesetzt: Vertauschung? (erwartet war dieses Signal)
    note: str = ""
    seq: int = 0                          # laufende Nummer (für die Webseite: neue Wechsel erkennen)


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
        """Leerer Tracker: Optionen (automatisch abhaken, Prüfpunkte, Toleranz) und die Wechselhistorie."""
        self.auto_ok = False
        self.auto_points = True
        self.tolerance = 1.0              # % des Messbereichs
        self.expected = None
        self.history = []                 # neueste zuerst
        self.status_changed = []          # Signale, deren Status sich automatisch geändert hat (seit dem Abholen)
        self.watched = set()              # zusätzlich beobachtete Signale (auf Smartphones gewählt): Analog-Prüfpunkte
        self.seq = 0

    def _log(self, ch: Change):
        """Wechsel nummerieren und vorn in die Historie einfügen (höchstens HISTORY Einträge)."""
        self.seq += 1
        ch.seq = self.seq
        self.history.insert(0, ch)
        del self.history[self.HISTORY:]

    def feed(self, sig: IoSignal, value: float, ts: float, error: str = ""):
        """Neuen Wert eines Signals verarbeiten. Rückgabe: Change oder None.

        Digital: ein Wechsel setzt die Flankenbits; nach 0→1→0 wird ein offenes Signal bei „automatisch abhaken“ OK.
        Analog: Drahtbruch erkennen (Fehlerwert kommt und geht), Prüfpunkte verfolgen und nur Änderungen über 2 % des
        Messbereichs als Wechsel melden (Rauschen). Wechselt ein anderes Eingangssignal als das gerade geprüfte, bekommt
        der Wechsel einen Hinweis „Vertauschung?“ – aber nur, wenn das geprüfte Signal einige Sekunden ruhig war.
        """
        sig.error = error
        old = sig.value
        if value is None or math.isnan(value):
            sig.value = math.nan
            return None
        if sig.binary:
            value = 1.0 if value >= 0.5 else 0.0
        sig.value = value
        broke = False
        if not sig.binary and sig.is_input:
            if analog_broken(sig, value):
                # Neuer Drahtbruch, wenn noch keiner gesehen wurde oder das Signal schon wieder gültig war.
                broke = not sig.seen & SEEN_BREAK or bool(sig.seen & SEEN_BACK)
                sig.seen = (sig.seen | SEEN_BREAK) & ~SEEN_BACK if broke else sig.seen
            elif sig.seen & SEEN_BREAK and not sig.seen & SEEN_BACK:
                sig.seen |= SEEN_BACK
                if self.auto_ok and sig.status == "offen":
                    set_status(sig, "ok", remark=sig.remark or tr("automatisch (Drahtbruch erkannt, wieder gültig)"))
                    sig.seen = SEEN_BREAK | SEEN_BACK
                    self.status_changed.append(sig)
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
            if not broke and not math.isnan(sig.logged) and abs(value - sig.logged) < 0.02 * span:
                return None                   # Rauschen: erst ab 2 % des Messbereichs melden
            old, sig.logged = sig.logged, value
        ch = Change(ts, sig, old, value)
        exp = self.expected
        # Vertauschung: anderes Eingangssignal hat gewechselt (digital) bzw. Drahtbruch gemeldet (analog), das gewählte
        # nicht
        same_kind = (sig.binary and exp is not None and exp.binary) or \
                    (broke and exp is not None and not exp.binary and exp.is_input)
        if exp is not None and exp is not sig and sig.is_input and same_kind \
                and ts - exp.changed > self.SWAP_QUIET_S:
            ch.expected = exp
            ch.note = tr("Vertauschung? Erwartet {0}, gekommen {1}").format(exp.label, sig.label)
        sig.changed = ts
        self._log(ch)
        return ch

    def _analog_points(self, sig: IoSignal, value: float, ts: float):
        """Prüfpunkte automatisch übernehmen: liegt der Wert des geprüften (oder auf einem Smartphone gewählten)
        Analogsignals STABLE_S lang um 0/50/100 %, wird der Punkt eingetragen; sind alle drei da, wird das Signal OK.
        """
        if not self.auto_points or (sig is not self.expected and sig not in self.watched):
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

    def take_point(self, sig: IoSignal, pct: int, checker=None):
        """Prüfpunkt von Hand übernehmen (aktueller Wert); sind alle Punkte in Toleranz, wird ein offenes Signal OK.
        Rückgabe: dieser Punkt in Toleranz?"""
        eng = scale(sig, sig.value)
        if math.isnan(eng):
            return False
        sig.points[str(pct)] = round(eng, 6)
        if sig.status == "offen" and all(str(p) in sig.points and point_ok(sig, p, sig.points[str(p)], self.tolerance)
                                         for p in POINTS):
            set_status(sig, "ok", remark=sig.remark or tr("Prüfpunkte 0/50/100 % in Toleranz"), checker=checker)
        return point_ok(sig, pct, eng, self.tolerance)

    def pop_status_changes(self):
        """Automatisch geänderte Signale seit dem letzten Abruf abholen (das Fenster aktualisiert sie)."""
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
    """Ein Prüfstand: Signale, Scan-Bereiche, zugehörige Konfiguration und Optionen (Datei ``*.iocheck.json``).

    ``signals`` ist die IO-Liste; ``scanned`` hält bearbeitete Signale aus Scan-Bereichen (Status, Bemerkung, Texte),
    damit sie mit gespeichert werden."""
    signals: list = field(default_factory=list)
    scans: list = field(default_factory=list)
    scanned: list = field(default_factory=list)
    config: str = ""                       # Konfigurationsdatei (Steuerungen)
    options: dict = field(default_factory=dict)
    path: str = ""

    def save(self, path=None):
        """Prüfstand speichern (erst in eine temporäre Datei, dann ersetzen). Unter neuem Namen gespeichert, werden
        die Fotos in den neuen Fotoordner kopiert."""
        path = path or self.path
        old, new = photo_dir(self.path), photo_dir(path)
        if old and new and os.path.normcase(os.path.abspath(old)) != os.path.normcase(os.path.abspath(new)):
            import shutil
            for s in self.signals + self.scanned:
                for name in s.photos:
                    src = os.path.join(old, name)
                    if os.path.isfile(src) and not os.path.exists(os.path.join(new, name)):
                        os.makedirs(new, exist_ok=True)
                        shutil.copy2(src, os.path.join(new, name))
        doc = {"format": FORMAT, "version": 1, "gespeichert": now_text(), "config": self.config,
               "options": self.options, "scans": [asdict(s) for s in self.scans],
               "signals": [s.to_dict() for s in self.signals]
               + [s.to_dict() for s in self.scanned if s not in self.signals]}
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        self.path = path

    @classmethod
    def load(cls, path):
        """Prüfstand laden; andere JSON-Dateien werden mit einer Meldung abgewiesen."""
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        if doc.get("format") != FORMAT:
            raise ValueError(tr("{0} ist keine IO-Check-Datei.").format(os.path.basename(path)))
        sigs = [IoSignal.from_dict(d) for d in doc.get("signals", [])]
        return cls(signals=[s for s in sigs if not s.scanned], scanned=[s for s in sigs if s.scanned],
                   scans=[ScanRange(**{k: v for k, v in d.items() if k in ScanRange.__dataclass_fields__})
                          for d in doc.get("scans", [])],
                   config=doc.get("config", ""), options=doc.get("options", {}), path=path)


RESULT_HEADER = [N_("Steuerung"), N_("Adresse"), N_("Symbol"), N_("Kommentar"), N_("BMK"), N_("Gruppe"), N_("Typ"),
                 N_("Status"), N_("Geprüft am"), N_("Prüfer"), N_("Bemerkung"), N_("Messpunkte")]


def result_rows(signals):
    """Zeilen der Ergebnistabelle (eine je Signal, Messpunkte als Text)."""
    rows = []
    for s in signals:
        pts = ", ".join(f"{p} %: {s.points[str(p)]:g}{(' ' + s.unit) if s.unit else ''}"
                        for p in POINTS if str(p) in s.points)
        rows.append([s.plc, s.address, s.symbol, s.comment, s.bmk, s.group, s.kind, tr(STATUS.get(s.status, s.status)),
                     s.checked_at, s.checker, s.remark, pts])
    return rows


# Farben im Excel-Ergebnis (wie in der Signalliste): Zeilenhintergrund und Schrift der Statusspalte
RESULT_FILL = {"ok": "C8E6C9", "fehler": "FFCDD2", "uebersprungen": "E0E0E0"}
RESULT_FONT = {"ok": "1B5E20", "fehler": "B71C1C", "uebersprungen": "616161", "offen": "455A64"}


def write_result(path, signals, colors=True):
    """Ergebnis als CSV- oder Excel-Datei speichern; Excel mit den Statusfarben der Signalliste (``colors``)."""
    from plc_export import write_table
    fills = fonts = None
    if colors:
        col = RESULT_HEADER.index(N_("Status")) if N_("Status") in RESULT_HEADER else 7
        fills = [RESULT_FILL.get(s.status) for s in signals]
        fonts = [{col: RESULT_FONT.get(s.status, "000000")} for s in signals]
    write_table(path, [tr(h) for h in RESULT_HEADER], result_rows(signals), sheet=tr("IO-Check"), fills=fills,
                fonts=fonts)


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
        """Lese-Thread für Steuerung Nummer ``idx`` und ihre Signale; Ergebnisse gehen in die Warteschlange ``out``."""
        super().__init__(name=f"iocheck-{plc.name}", daemon=True)
        self.idx, self.plc, self.signals, self.out = idx, plc, list(signals), out
        self.interval = max(0.05, interval_ms / 1000.0)
        self.demo = demo
        self.stop_evt = threading.Event()

    def stop(self):
        """Thread beenden lassen (wirkt beim nächsten Warten)."""
        self.stop_evt.set()

    def _status(self, state, text):
        """Verbindungszustand über die Warteschlange an das Fenster melden."""
        self.out.put(("status", self.idx, state, text))

    def run(self):
        """Lese-Schleife (wie im Recorder): verbinden, lesen, Werte und Fehler je Signal melden; bei Fehlern neu
        verbinden.
        """
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
        breaks = {}
        t0 = time.time()
        while not self.stop_evt.is_set():
            ts = time.time()
            for k, s in enumerate(self.signals):
                if s.binary:
                    if rnd.random() < (0.004 if s.is_input else 0.001):
                        state[k] = 1.0 - state[k]
                elif breaks.get(k, 0) > ts:
                    state[k] = 32767.0                # simulierter Drahtbruch (Klemme geöffnet)
                else:
                    if s.is_input and rnd.random() < 0.002:
                        breaks[k] = ts + 3.0
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


# ---------------------------------------------------------------------------------------------------------------------
# Webseite (Smartphone/Tablet): Verbindung zwischen IO-Check-Fenster und Webserver
# ---------------------------------------------------------------------------------------------------------------------
STATUS_KEYS = tuple(STATUS)


class IoWebBridge:
    """Stellt den IO-Check dem Webserver (andere Threads) zur Verfügung.

    Das Fenster veröffentlicht Signale und Matrix (publish) und arbeitet die Befehle der Webseite im eigenen Thread ab
    (commands: ("status" | "point", Signal, Wert, Benutzer)). Die Webseite liest mit snapshot(); der Prüfer ist der
    Anmeldename im Webserver."""

    WATCH_S = 15.0

    def __init__(self):
        """Leere Brücke; ``version`` wird bei jeder neuen Signalliste erhöht (die Webseite lädt dann die festen Daten
        neu).
        """
        self.lock = threading.Lock()
        self.version = 0
        self.signals, self.matrix, self.groups = [], [], []
        self.tracker = None
        self.title = ""
        self.source = ""                      # Datei des Prüfstands (für das Protokoll)
        self.plcs = []
        self.logos = []                       # Logos der Konfiguration (für das Protokoll)
        self.plc_state = []
        self.commands = queue.Queue()
        self.watch = {}                       # Signal-Index -> Zeitpunkt der letzten Auswahl auf einer Webseite
        self.photo_dir = ""                   # Fotoordner des Prüfstands ("" = noch nicht gespeichert)

    def publish(self, signals, tracker, title, matrix):
        """Neue Signalliste veröffentlichen (Fenster-Thread): Signale, Tracker, Titel und Matrix als Indizes."""
        index = {id(s): i for i, s in enumerate(signals)}
        with self.lock:
            self.version += 1
            self.signals, self.tracker, self.title = list(signals), tracker, title
            self.groups = sorted({s.group for s in signals if s.group})
            self.matrix = [[sec, label, [index.get(id(c), -1) if c is not None else -1 for c in cells]]
                           for sec, label, cells in matrix]
            self.watch = {}

    def set_title(self, title):
        """Titel des Prüfstands für die Webseite."""
        self.title = title

    def set_plc_state(self, states):
        """Zustand der Steuerungen für die Webseite."""
        self.plc_state = [list(x) for x in states]

    def watched(self):
        """Signale, die auf einer Webseite in den letzten WATCH_S Sekunden gewählt waren (deren Analog-Prüfpunkte werden
        verfolgt).
        """
        now = time.time()
        with self.lock:
            return {self.signals[i] for i, t in self.watch.items() if now - t < self.WATCH_S and i < len(self.signals)}

    def snapshot(self, client_version=None, selected=None, user=""):
        """Daten für die Webseite: feste Daten (Adressen, Texte, Matrix) nur, wenn die Seite eine ältere Version kennt;
        dazu je Signal Status, Wert, Fehler, Alter des letzten Wechsels, Flanken, Prüfer, Bemerkung, Messpunkte sowie
        die letzten Wechsel und den Fortschritt.

        ``selected``: auf der Webseite gewähltes Signal (wird beobachtet); ``user``: Prüfer der Anfrage.
        """
        now = time.time()
        with self.lock:
            sigs, tracker, version = self.signals, self.tracker, self.version
            if selected is not None and 0 <= selected < len(sigs):
                self.watch[selected] = now
            static = None
            if client_version != version:
                static = {"sig": [[s.address, s.symbol, s.comment, s.bmk, s.group, s.kind, s.unit, s.eng_min,
                                   s.eng_max, s.raw_min, s.raw_max, s.plc] for s in sigs],
                          "groups": self.groups, "matrix": self.matrix}
        index = {id(s): i for i, s in enumerate(sigs)}
        dyn = []
        for s in sigs:
            v = None if math.isnan(s.value) else round(s.value, 4)
            dyn.append([s.status, v, s.error, round(now - s.changed, 1) if s.changed else -1, s.seen,
                        s.checked_at, s.checker, s.remark, s.points, list(s.photos)])
        changes = []
        if tracker is not None:
            for ch in tracker.history[:40]:
                i = index.get(id(ch.sig))
                if i is not None:
                    changes.append([ch.seq, round(now - ch.ts, 1), i, ch.old, ch.new])
        out = {"active": True, "ver": version, "title": self.title, "user": user, "progress": progress(sigs),
               "tol": tracker.tolerance if tracker else 1.0, "plcs": self.plc_state, "dyn": dyn, "changes": changes}
        if static is not None:
            out["static"] = static
        return out

    def command(self, version, cmd, idx, value, user):
        """Befehl der Webseite prüfen und an das Fenster weitergeben. Rückgabe: Fehlertext oder ""."""
        with self.lock:
            if version != self.version:
                return "version"
            if not (0 <= idx < len(self.signals)):
                return "index"
            sig = self.signals[idx]
        if cmd == "status":
            status = value.get("status")
            if status not in STATUS_KEYS:
                return "status"
            remark = value.get("remark")
            self.commands.put(("status", sig, (status, None if remark is None else str(remark)[:500]), user))
        elif cmd == "point":
            pct = value.get("pct")
            if pct not in POINTS or sig.binary:
                return "point"
            self.commands.put(("point", sig, pct, user))
        elif cmd == "remark":
            self.commands.put(("remark", sig, str(value.get("remark", ""))[:500], user))
        elif cmd == "photo_del":
            name = str(value.get("name", ""))
            if name not in sig.photos:
                return "photo"
            self.commands.put(("photo_del", sig, name, user))
        else:
            return "cmd"
        return ""

    def add_photo(self, version, idx, data, user):
        """Foto von der Webseite: prüfen und dem Fenster übergeben (das speichert die Datei). Rückgabe: Fehlertext
        oder ""."""
        with self.lock:
            if version != self.version:
                return "version"
            if not (0 <= idx < len(self.signals)):
                return "index"
            sig = self.signals[idx]
        if not photo_type(data):
            return tr("Kein JPEG- oder PNG-Bild.")
        if len(data) > PHOTO_MAX_BYTES:
            return tr("Bild zu groß (höchstens {0} MB).").format(PHOTO_MAX_BYTES // (1024 * 1024))
        if not self.photo_dir:
            return tr("Prüfstand zuerst am PC speichern – die Fotos liegen in einem Ordner daneben.")
        self.commands.put(("photo", sig, data, user))
        return ""

    def photo_path(self, idx, name):
        """Datei eines Fotos für die Webseite (nur eingetragene Fotos) oder None."""
        with self.lock:
            if not (0 <= idx < len(self.signals)) or not self.photo_dir:
                return None
            sig = self.signals[idx]
        if name not in sig.photos or not valid_photo_name(name):
            return None
        path = os.path.join(self.photo_dir, name)
        return path if os.path.isfile(path) else None


# ---------------------------------------------------------------------------------------------------------------------
# Abnahmeprotokoll (PDF)
# ---------------------------------------------------------------------------------------------------------------------
def protocol_signals(signals):
    """Signale für das Protokoll: die IO-Liste und aus Scan-Bereichen nur die bearbeiteten."""
    return [s for s in signals if not s.scanned or s.status != "offen" or s.remark or s.photos]


def _short_date(text):
    """'2026-10-21 08:55:01' -> '21.10.26' (Datum für die Spalte „Geprüft am“ im Protokoll)."""
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%d.%m.%y")
    except ValueError:
        return text[:10]


def protocol_landscape() -> bool:
    """Gespeicherte Wahl „Protokoll im Querformat“ (Einstellung ``iocheck_querformat``, Standard: hoch)."""
    try:
        from plc_common import load_settings
        return bool(load_settings().get("iocheck_querformat", False))
    except Exception:
        return False


def write_protocol(path, signals, project="", source="", plcs=(), logos=(), landscape=None, photos=None):
    """Abnahmeprotokoll als PDF: Zusammenfassung, Prüfer, Fehler/offene Signale, alle Signale je Gruppe,
    Unterschriftsfelder, als Anhang die Fotos. Prüfer = eingestellter Name am PC bzw. Anmeldename im Webserver;
    ``logos``: Bilddateien für den Seitenkopf (Kundenlogo, Logo); ``landscape``: A4 quer (None: gespeicherte Wahl);
    ``photos``: Fotos anhängen (None: gespeicherte Wahl; Fotoordner neben ``source``). Kommentar und Bemerkung werden
    mehrzeilig gedruckt, „Geprüft am“ nur mit Datum."""
    from plc_report import MARGIN, _Doc, _table, load_image, text_width
    if landscape is None:
        landscape = protocol_landscape()
    if photos is None:
        photos = protocol_photos()
    sigs = protocol_signals(signals)
    txt, mute, head = "#1b2430", "#5b6878", "#0d47a1"
    colors = {"ok": "#1b5e20", "fehler": "#b71c1c", "uebersprungen": "#616161", "offen": "#b26a00"}
    doc = _Doc(tr("IO-Check – Abnahmeprotokoll"), project or os.path.basename(source), logos, landscape)
    p = doc.pdf
    pr = progress(sigs)
    done = pr["ok"] + pr["fehler"] + pr["uebersprungen"]
    times = sorted(s.checked_at for s in sigs if s.checked_at)
    lines = [(tr("Projekt:"), project or "—"), (tr("Prüfstand:"), os.path.basename(source) or "—"),
             (tr("Steuerungen:"), ", ".join(f"{pl.name} ({pl.summary()})" for pl in plcs) or "—"),
             (tr("Prüfzeitraum:"), f"{times[0][:16]} – {times[-1][:16]}" if times else "—"),
             (tr("Ergebnis:"), tr("{0} von {1} Signalen geprüft ({2:.0f} %): {3} OK, {4} Fehler, {5} übersprungen, "
                                  "{6} offen").format(done, pr["gesamt"], 100.0 * done / max(1, pr["gesamt"]),
                                                      pr["ok"], pr["fehler"], pr["uebersprungen"], pr["offen"]))]
    for k, v in lines:
        p.text(MARGIN, doc.y, k, 9, bold=True, color=txt)
        p.text(MARGIN + 80, doc.y, v, 9, color=txt)
        doc.y -= 13
    doc.y -= 4

    # Zusammenfassung je Signalart und je Gruppe
    doc.heading(tr("Zusammenfassung"))

    def count_rows(keyfn, labels):
        rows = []
        for key in labels:
            part = [s for s in sigs if keyfn(s) == key]
            if not part:
                continue
            c = progress(part)
            rows.append([key or "—", str(c["gesamt"]), (str(c["ok"]), colors["ok"]), (str(c["fehler"]), colors["fehler"]),
                         str(c["uebersprungen"]), (str(c["offen"]), colors["offen"] if c["offen"] else txt)])
        return rows
    heads = [tr("Signalart"), tr("Gesamt"), tr("OK"), tr("Fehler"), tr("übersprungen"), tr("offen")]
    w6 = [175, 68, 68, 68, 68, 68]
    _table(doc, heads, [[f"{k} – {tr(KIND_TEXT[k])}" if k else r[0]] + r[1:]
                        for k, r in zip([k for k in KINDS if any(s.kind == k for s in sigs)],
                                        count_rows(lambda s: s.kind, KINDS))], w6, ["left"] + ["right"] * 5)
    groups = sorted({s.group for s in sigs})
    if len(groups) > 1 or (groups and groups[0]):
        _table(doc, [tr("Gruppe")] + heads[1:], count_rows(lambda s: s.group, groups), w6, ["left"] + ["right"] * 5)

    # Prüfer
    by = {}
    for s in sigs:
        if s.status != "offen":
            by[s.checker or "—"] = by.get(s.checker or "—", 0) + 1
    if by:
        doc.heading(tr("Prüfer"))
        _table(doc, [tr("Prüfer"), tr("Signale")], [[k, str(v)] for k, v in sorted(by.items(), key=lambda kv: -kv[1])],
               [200, 68], ["left", "right"])

    cols = [tr("Adresse"), tr("Symbol"), tr("Kommentar"), tr("BMK"), tr("Typ"), tr("Status"), tr("Geprüft am"),
            tr("Prüfer"), tr("Bemerkung")]
    widths = [46, 62, 98, 44, 20, 46, 46, 52, 101]       # A4 hoch: 515 pt
    extra = doc.pdf.W - 2 * MARGIN - sum(widths)          # quer: mehr Platz für Symbol, Kommentar, BMK, Bemerkung
    if extra > 0:
        for j, part in ((1, 0.15), (2, 0.35), (3, 0.05), (7, 0.05), (8, 0.40)):
            widths[j] += extra * part
    wrap = (2, 8)                                         # Kommentar und Bemerkung mehrzeilig

    # Fotos: fortlaufend nummeriert (Verweis in der Bemerkung, Bilder im Anhang)
    folder = photo_dir(source) if photos else ""
    shots, numbers = [], {}
    for s in sigs if folder else ():
        for name in s.photos:
            img = load_image(os.path.join(folder, name))
            if img is not None:
                shots.append((s, img))
                numbers.setdefault(id(s), []).append(len(shots))

    def row(s):
        note = s.remark
        pts = " ".join(f"{q}%={s.points[str(q)]:.4g}" for q in POINTS if str(q) in s.points)
        if pts:
            note = f"{note}; {pts}" if note else pts
        if id(s) in numbers:
            ref = tr("Foto {0}").format(", ".join(str(n) for n in numbers[id(s)]))
            note = f"{note} ({ref})" if note else ref
        return [s.address, s.symbol, s.comment, s.bmk, s.kind, (tr(STATUS[s.status]), colors[s.status]),
                _short_date(s.checked_at), s.checker, note]

    bad = [s for s in sigs if s.status in ("fehler", "offen")]
    doc.heading(tr("Fehler und offene Signale"))
    if bad:
        _table(doc, cols, [row(s) for s in sorted(bad, key=lambda s: (s.status != "fehler", s.group, s.address))],
               widths, ["left"] * 9, size=7.2, wrap=wrap)
    else:
        p.text(MARGIN, doc.y, tr("Keine – alle Signale geprüft und in Ordnung bzw. übersprungen."), 8.5, color=mute)
        doc.y -= 14

    doc.heading(tr("Alle Signale"))
    for g in groups:
        part = [s for s in sigs if s.group == g]
        if g:
            doc.need(40)
            p.text(MARGIN, doc.y, g, 9, bold=True, color=head)
            doc.y -= 12
        _table(doc, cols, [row(s) for s in part], widths, ["left"] * 9, size=7.2, wrap=wrap)

    # Unterschriften
    doc.need(120)
    doc.heading(tr("Bestätigung"))
    x2 = MARGIN + (p.W - 2 * MARGIN) / 2 + 10
    for x, label in ((MARGIN, tr("Prüfer")), (x2, tr("Abnahme (Auftraggeber)"))):
        y = doc.y - 50
        p.line(x, y, x + 220, y, color=txt, width=0.6)
        p.text(x, y - 11, tr("{0}: Name, Datum, Unterschrift").format(label), 8, color=mute)
    doc.y -= 80

    # Anhang: Fotos, zwei nebeneinander (quer: drei), mit Nummer, Signal, Status und Bemerkung
    if shots:
        doc.new_page()
        doc.heading(tr("Anhang: Fotos"))
        per_row = 3 if p.W > p.H else 2
        gap = 12
        cw = (p.W - 2 * MARGIN - gap * (per_row - 1)) / per_row
        max_h = 200.0

        def fit(text, size, width, bold=False):
            while text and text_width(text, size, bold) > width:
                text = text[:-2] + "…" if len(text) > 2 else ""
            return text
        for k in range(0, len(shots), per_row):
            part = shots[k:k + per_row]
            sizes = []
            for _s, img in part:
                w = cw
                h = w * img.h / max(img.w, 1)
                if h > max_h:
                    h, w = max_h, max_h * img.w / max(img.h, 1)
                sizes.append((w, h))
            row_h = max(h for _w, h in sizes) + 30
            doc.need(row_h)
            for j, ((s, img), (w, h)) in enumerate(zip(part, sizes)):
                x = MARGIN + j * (cw + gap)
                p.image(x, doc.y - h, w, h, img)
                cap = f"{tr('Foto {0}').format(k + j + 1)}: {s.address} {s.symbol}".strip()
                if s.bmk:
                    cap += f" · {s.bmk}"
                p.text(x, doc.y - h - 10, fit(cap, 7.5, cw, True), 7.5, bold=True, color=txt)
                sub = tr(STATUS[s.status]) + (f" – {s.remark}" if s.remark else "")
                p.text(x, doc.y - h - 19, fit(sub, 7, cw), 7, color=colors[s.status])
            doc.y -= row_h
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    p.save(path, tr("IO-Check – Abnahmeprotokoll"))
    return path
