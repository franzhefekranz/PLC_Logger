"""Gemeinsame Grundlagen des S7-Datenloggers: Datenmodell, INI-Konfiguration und SPS-Zugriff.

Dieses Modul wird vom Logger (s7_logger.py), vom Konfigurationsprogramm (s7_config.py) und von
den Dialogen verwendet. Es enthält

* das Datenmodell:  Plc (Steuerung) und Axis (Y-Achse) -> Chart (Diagramm) -> Variable, außerdem Block
  (Blocklesemodus). Eine Variable gehört zu genau einer Steuerung, einem Diagramm und einer Y-Achse darin;
* das Laden/Speichern der Konfiguration in einer INI-Datei (load_config / load_plcs / load_blocks /
  save_config) sowie die Merkhilfe für die zuletzt benutzte Konfigurationsdatei;
* das Lesen aus der SPS mit python-snap7: einzelne Variablen (read_var) oder ganze Bereiche mit
  einer einzigen Anfrage (build_plan / read_plan);
* kleine Hilfen wie die Liste der Datenbausteine einer SPS (list_plc_dbs).

Das Modul enthält keine Oberfläche (kein Qt), ist also auch ohne Bildschirm testbar.
"""
import colorsys
import configparser
import os
import struct
import sys
from dataclasses import dataclass, field
from s7_i18n import N_

# python-snap7 hat die Aufzählung der Speicherbereiche je nach Version unterschiedlich benannt
# (Area bzw. Areas, Modul snap7.type bzw. snap7.types). Damit das Programm mit mehreren Versionen
# läuft, werden die bekannten Schreibweisen der Reihe nach ausprobiert.
# Kompatibel zu verschiedenen python-snap7 Versionen
try:
    from snap7.type import Area as Areas
except ImportError:
    try:
        from snap7.type import Areas
    except ImportError:
        from snap7.types import Areas

# Basisordner für alle Dateien, die das Programm selbst anlegt (INI, CSV, Archiv, Logo-Pfade).
def _app_dir() -> str:
    """Ordner für Konfiguration, CSV-Dateien und Archiv.

    Normalbetrieb (Python-Skripte): der Ordner der Programmdateien.
    Installierte Version (PyInstaller): der Programmordner ist meist schreibgeschützt
    (C:\\Program Files), daher liegen die Daten unter %APPDATA%\\S7Datenlogger. Eine Datei
    ``portable.txt`` neben der .exe schaltet auf den portablen Betrieb (Daten neben der .exe)."""
    # PyInstaller setzt sys.frozen, wenn das Programm als .exe läuft.
    if getattr(sys, "frozen", False):
        # Portabler Betrieb: liegt portable.txt neben der .exe, bleiben alle Daten im Programmordner.
        # Linux-AppImage: das Programm läuft aus einem schreibgeschützten Abbild; maßgeblich ist der Ordner der
        # .AppImage-Datei (Umgebungsvariable APPIMAGE).
        exe_dir = os.path.dirname(os.environ.get("APPIMAGE") or sys.executable)
        if os.path.exists(os.path.join(exe_dir, "portable.txt")):
            return exe_dir
        # Sonst die Benutzerdaten (Windows: %APPDATA%); ohne APPDATA der Home-Ordner des Benutzers.
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(root, "S7Datenlogger")
        os.makedirs(path, exist_ok=True)
        return path
    # Entwicklungsbetrieb (python s7_logger.py): der Ordner dieser Datei.
    return os.path.dirname(os.path.abspath(__file__))


# Wird beim Import einmalig berechnet; alle relativen Pfade der Konfiguration beziehen sich darauf.
BASE_DIR = _app_dir()
# Standardname der Konfigurationsdatei (das Konfigurationsprogramm kann auch andere Dateien laden).
CONFIG_FILE = os.path.join(BASE_DIR, "s7_config.ini")

# Programmname und Version (Startbild, Info-Dialog, Fenstertitel).
APP_NAME = "S7 Datenlogger"
APP_VERSION = "2.1.0"
# Programmdateien der installierten Windows-Version.
LOGGER_EXE, CONFIG_EXE = "S7Logger.exe", "S7Konfiguration.exe"
# Persönliche Einstellungen (Sprache, Startbild, zuletzt benutzte Konfigurationen) – JSON im Datenordner.
SETTINGS_FILE = os.path.join(BASE_DIR, "s7_einstellungen.json")


def load_settings() -> dict:
    """Einstellungen lesen (fehlende Datei oder Fehler: Vorgaben)."""
    import json
    data = {"sprache": "", "startbild": True, "zuletzt": []}
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            stored = json.load(f)
        if isinstance(stored, dict):
            data.update(stored)
    except (OSError, ValueError):
        pass
    return data


def save_settings(**changes):
    """Einzelne Einstellungen ändern und speichern (Fehler beim Schreiben sind unkritisch)."""
    import json
    data = load_settings()
    data.update(changes)
    try:
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_FILE)
    except OSError:
        pass


def recent_configs(limit: int = 10) -> list:
    """Zuletzt benutzte Konfigurationsdateien (neueste zuerst, nur vorhandene)."""
    out = []
    for p in load_settings().get("zuletzt", []):
        if isinstance(p, str) and os.path.exists(p) and p not in out:
            out.append(p)
    return out[:limit]


def program_command(kind: str, *args) -> list:
    """Befehlszeile, um den Logger (kind="logger") oder das Konfigurationsprogramm (kind="config") zu starten.

    Windows-Installation: die .exe-Dateien liegen nebeneinander. Linux (AppImage bzw. PyInstaller-Ordner): eine
    einzige Programmdatei, das Konfigurationsprogramm startet mit ``--konfig``. Python-Skripte: dieselbe
    Python-Installation."""
    args = [str(a) for a in args if a]
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            exe = LOGGER_EXE if kind == "logger" else CONFIG_EXE
            return [os.path.join(os.path.dirname(sys.executable), exe)] + args
        prog = os.environ.get("APPIMAGE") or sys.executable
        return [prog] + (["--konfig"] if kind == "config" else []) + args
    here = os.path.dirname(os.path.abspath(__file__))
    script = "s7_logger.py" if kind == "logger" else "s7_config.py"
    return [sys.executable, os.path.join(here, script)] + args

# Unterstützte Datentypen der Variablen.
# Schlüssel: Typname wie in der SPS; Wert: (Größe in Bytes, struct-Format).
# Die S7 speichert Zahlen im Big-Endian-Format (höchstwertiges Byte zuerst), daher das ">".
# BOOL hat kein struct-Format: Das Bit wird aus dem Byte herausgelöst (siehe read_var).
# Typ -> (Größe in Bytes, struct-Format; Big Endian wie in der S7)
TYPES = {
    "BOOL": (1, None),
    "BYTE": (1, ">B"),
    "SINT": (1, ">b"),
    "INT": (2, ">h"),
    "WORD": (2, ">H"),
    "DINT": (4, ">i"),
    "DWORD": (4, ">I"),
    "REAL": (4, ">f"),
    "LREAL": (8, ">d"),
}

# Speicherbereiche der SPS: Kürzel in der Oberfläche (deutsche Bezeichnungen wie in STEP 7)
# -> Konstante der snap7-Bibliothek.
# Bereich (deutsche Bezeichnung) -> snap7-Bereich
AREAS = {
    "DB": Areas.DB,
    "M": Areas.MK,   # Merker
    "E": Areas.PE,   # Eingänge
    "A": Areas.PA,   # Ausgänge
}

# Anordnungen der Diagramm-Seiten: Schlüssel in der INI-Datei -> Text im Menü bzw. in der Auswahl.
LAYOUTS = {"untereinander": N_("Untereinander"),
           "nebeneinander": N_("Nebeneinander"),
           "tabs": N_("Tabs")}

# Anordnung der Diagramme INNERHALB einer Seite (Menü Ansicht): Schlüssel in der INI-Datei -> Text.
# 'raster' ordnet die Diagramme in Zeilen und Spalten an (Spaltenzahl: Einstellung raster_spalten).
PAGE_LAYOUTS = {"untereinander": N_("Untereinander"),
                "nebeneinander": N_("Nebeneinander"),
                "raster": N_("Raster (Grid)")}

# Standardfarben (Matplotlib-Palette); neue Variablen und Blöcke erhalten reihum eine davon.
PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
           "#9467bd", "#8c564b", "#e377c2", "#17becf"]


# ---------------------------------------------------------------------------------------
# Datenmodell: Diagramm -> Y-Achse(n) -> Variable(n)
# ---------------------------------------------------------------------------------------
@dataclass
class Plc:
    """Eine Steuerung (SPS), aus der gelesen wird. Jede Steuerung bekommt einen eigenen Lese-Thread
    und ein eigenes Abtastintervall; Variablen verweisen über ihren Index (``Variable.plc``) darauf."""
    name: str = "SPS 1"           # frei wählbarer Name (Anzeige, Status-LED)
    ip: str = "192.168.0.1"
    rack: int = 0
    slot: int = 1
    intervall_ms: int = 200       # Abtastzeit dieser Steuerung in Millisekunden
    enabled: bool = True          # False: Steuerung wird nicht gelesen (ihre Variablen bleiben ohne Wert)


@dataclass
class Axis:
    """Eine Y-Achse innerhalb eines Diagramms."""
    name: str = "Achse 1"
    auto: bool = True      # Auto-Skalierung; sonst feste Grenzen y_min..y_max
    y_min: float = 0.0
    y_max: float = 100.0


@dataclass
class Chart:
    """Ein Diagramm: eigener Name, eine oder mehrere Y-Achsen und optional eine 'Seite'.

    Diagramme mit gleichem Seitennamen werden im Logger gemeinsam in einem Tab/Dock angezeigt.
    """
    name: str = "Diagramm 1"
    axes: list = field(default_factory=lambda: [Axis()])
    page: str = ""            # Seite/Tab; Diagramme mit gleichem Namen teilen sich eine Seite
    # PID-Regler-Optimierung (siehe *_pid.py): eingeschaltet, Namen der Variablen für Soll-, Ist- und Stellwert,
    # Reglertyp ("PI"/"PID") und gewünschtes Regelverhalten ("schnell"/"normal"/"robust").
    pid: bool = False
    pid_sw: str = ""
    pid_iw: str = ""
    pid_stw: str = ""
    pid_typ: str = "PID"
    pid_verhalten: str = "normal"


@dataclass
class Variable:
    """Eine aufzuzeichnende Größe.

    Normale Variable: area/db/byte/bit/dtype beschreiben die SPS-Adresse. Berechnete Variable:
    formula ist nicht leer, die Adresse ist ohne Bedeutung. Block-Element: block/block_idx sind gesetzt;
    das Element wird zusammen mit seinem Block mit einer Anfrage gelesen.
    """
    name: str
    area: str = "DB"
    db: int = 1
    byte: int = 0
    bit: int = 0
    dtype: str = "REAL"
    color: str = "#1f77b4"
    show_value: bool = True   # in der Werteanzeige/Lineal-Tabelle aufführen
    chart: int = 0            # Index des Diagramms (0-basiert)
    axis: int = 0             # Index der Y-Achse innerhalb des Diagramms (0-basiert)
    bar: bool = True          # schmaler Balken für den Aktualwert
    formula: str = ""         # nicht leer: berechnete Variable (Bereich/DB/Byte/Typ ohne Bedeutung)
    block: str = ""           # Name des Blocks, zu dem die Variable gehört (Blocklesemodus)
    block_idx: int = 0        # Position innerhalb des Blocks
    plc: int = 0              # Index der Steuerung (0-basiert, siehe Plc)

    def address(self) -> str:
        """Adresse in Siemens-Schreibweise (z. B. DB10.DBD4, M5.0), für Anzeigen und Tooltips."""
        if self.formula:
            return "berechnet"
        # Siemens-Adresssyntax: X = Bit, B = Byte, W = Wort (2 Bytes), D = Doppelwort (4 Bytes).
        # (Für LREAL gibt es keine eigene Syntax; verwendet wird ebenfalls D.)
        suffix = {"BOOL": "X", "BYTE": "B", "SINT": "B", "INT": "W", "WORD": "W",
                  "DINT": "D", "DWORD": "D", "REAL": "D", "LREAL": "D"}[self.dtype]
        # Bit nur bei BOOL, z. B. DB10.DBX4.2
        bit = f".{self.bit}" if self.dtype == "BOOL" else ""
        # Datenbaustein:  DB<nummer>.DB<typ><byte>;  sonst  M/E/A<typ><byte>  (Merker/Eingang/Ausgang).
        if self.area == "DB":
            return f"DB{self.db}.DB{suffix}{self.byte}{bit}"
        return f"{self.area}{suffix}{self.byte}{bit}"


def _shade(color: str, i: int) -> str:
    """Farbe des i-ten Block-Elements: das erste hat die Blockfarbe, die weiteren unterscheiden sich im Farbton."""
    # Das erste Element behält exakt die Blockfarbe.
    if i == 0:
        return color
    # Hex-Farbe "#rrggbb" in Rot/Grün/Blau (0..1) zerlegen.
    try:
        r, g, b = (int(color[k:k + 2], 16) / 255 for k in (1, 3, 5))
    except ValueError:
        return color
    # In den HSV-Farbraum wechseln: nur der Farbton (Hue) wird je Element verschoben.
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    # 0.1618... ist der "goldene Schnitt": aufeinanderfolgende Elemente liegen dadurch im Farbkreis
    # weit auseinander und bleiben unterscheidbar. Sättigung und Helligkeit werden nach unten
    # begrenzt, damit die Kurven auf dunklem Hintergrund gut lesbar sind.
    r, g, b = colorsys.hsv_to_rgb((h + i * 0.1618034) % 1.0, max(s, 0.55), max(v, 0.75))
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


# ---------------------------------------------------------------------------------------
# Blocklesemodus: ein zusammenhängender Bereich gleichen Formats wird mit EINER Anfrage gelesen
# ---------------------------------------------------------------------------------------
@dataclass
class Block:
    """Blocklesemodus: ein zusammenhängender Bereich gleichen Formats, der mit EINER Anfrage
    gelesen wird. Jedes Element wird zu einer Variable ``<Name>[i]``."""
    name: str = "Block1"
    area: str = "DB"
    db: int = 1
    start: int = 0            # Startadresse (Byte)
    bit: int = 0              # Startbit (nur BOOL)
    dtype: str = "REAL"
    count: int = 10
    chart: int = 0
    axis: int = 0
    color: str = "#1f77b4"
    show_value: bool = True
    bar: bool = False
    names: dict = field(default_factory=dict)   # eigene Elementnamen {Index: Name}
    plc: int = 0                                # Steuerung, aus der der Block gelesen wird
    targets: dict = field(default_factory=dict)  # abweichendes Ziel einzelner Elemente {Index: (Diagramm, Achse)}

    # Größe des gesamten Bereichs in Bytes.
    def size_bytes(self) -> int:
        # BOOL: Bits sind dicht gepackt; ab dem Startbit werden 'count' Bits belegt -> aufrunden auf Bytes.
        if self.dtype == "BOOL":
            return (self.bit + self.count + 7) // 8
        return self.count * TYPES[self.dtype][0]

    # Erzeugt aus dem Block die einzelnen Variablen ('Name[0]' ... 'Name[n-1]' oder eigene Namen).
    def variables(self) -> list:
        out = []
        size = TYPES[self.dtype][0]
        for i in range(self.count):
            # BOOL: fortlaufende Bitnummer ab dem Startbit; Überlauf geht ins nächste Byte (8 Bits je Byte).
            if self.dtype == "BOOL":
                pos = self.bit + i
                byte, bit = self.start + pos // 8, pos % 8
            # Alle anderen Typen liegen lückenlos hintereinander (Elementgröße = Typgröße).
            else:
                byte, bit = self.start + i * size, 0
            # Alle Elemente erben Bereich, DB, Diagramm, Achse, Anzeige-Optionen vom Block; block/block_idx
            # merken die Zugehörigkeit, damit der Leseplan sie wieder zu einer Anfrage zusammenfassen kann.
            # Einzelne Elemente dürfen in einem ANDEREN Diagramm/auf einer anderen Y-Achse liegen als der Rest
            # des Blocks (self.targets); gelesen werden sie trotzdem gemeinsam mit einer Anfrage.
            chart, axis = self.targets.get(i, (self.chart, self.axis))
            out.append(Variable(
                name=self.names.get(i) or f"{self.name}[{i}]", area=self.area, db=self.db, byte=byte, bit=bit,
                dtype=self.dtype, color=_shade(self.color, i), show_value=self.show_value,
                chart=chart, axis=axis, bar=self.bar, block=self.name, block_idx=i, plc=self.plc))
        return out

    # Adressbereich als Text, z. B. 'DB10.DBD0 … DB10.DBD76' (für Anzeigen im Editor).
    def address_range(self) -> str:
        v = self.variables()
        if not v:
            return ""
        a, b = v[0].address(), v[-1].address()
        return a if a == b else f"{a} … {b}"


# ---------------------------------------------------------------------------------------
# Konfigurationsdatei (INI)
# ---------------------------------------------------------------------------------------
# Aufbau:  [Verbindung]  [Diagramme] [DiagrammN] [DiagrammN_AchseM]  [Variablen] [VarN]  [Bloecke] [BlockN]
def default_connection() -> dict:
    """Vorgabewerte für die Verbindungs- und Anzeigeeinstellungen."""
    # Vorgabewerte der Verbindungs- und Anzeigeeinstellungen (Abschnitt [Verbindung]).
    # Schlüssel: ip/rack/slot = SPS-Adresse; intervall_ms = Abtastzeit; csv_ordner/csv_name/max_records/
    # archiv_ordner = CSV-Protokoll und Archivierung; fenster_s = Anzeigefenster online; anordnung/balken =
    # Darstellung; symbolquellen = importierte DB-Quellen; logo/icon = Branding.
    return {"ip": "192.168.0.1", "rack": 0, "slot": 1,
            "intervall_ms": 200, "csv_ordner": "logs", "fenster_s": 60,
            "anordnung": "untereinander", "balken": 1,
            "symbolquellen": "", "logo": "", "icon": "", "csv_name": "log", "max_records": 0,
            "archiv_ordner": "archiv",
            # Neu: Projektname, Archivierung beim Beenden, Seitenraster, Webserver und Headless-Modus.
            "projekt": "", "archiv_beenden": 1, "seite_anordnung": "", "raster_spalten": 0,
            "web_aktiv": 0, "web_host": "0.0.0.0", "web_port": 8080, "web_token": "",
            "web_intervall_ms": 1000, "headless": 0,
            # Aufzeichnungsziele: CSV-Datei (abschaltbar) und optional eine Datenbank (siehe *_db.py).
            "csv_aktiv": 1, "db_typ": "", "db_host": "localhost", "db_port": 0, "db_name": "datenlogger",
            "db_user": "", "db_passwort": "", "db_tabelle": "messwerte", "db_datei": "datenlogger.db",
            "db_nur_aenderungen": 0,
            # Ereignisprotokoll der Trigger (leer = <CSV-Ordner>/<CSV-Name>_ereignisse.csv, siehe *_events.py).
            "ereignis_datei": ""}


# Welche Schlüssel des Abschnitts [Verbindung] Zahlen bzw. Text sind (zum Lesen mit passendem Typ).
CONN_INT_KEYS = ("rack", "slot", "intervall_ms", "fenster_s", "balken", "max_records", "archiv_beenden",
                 "raster_spalten", "web_aktiv", "web_port", "web_intervall_ms", "headless",
                 "csv_aktiv", "db_port", "db_nur_aenderungen")
CONN_STR_KEYS = ("ip", "csv_ordner", "anordnung", "symbolquellen", "logo", "icon", "csv_name",
                 "archiv_ordner", "projekt", "seite_anordnung", "web_host", "web_token",
                 "db_typ", "db_host", "db_name", "db_user", "db_passwort", "db_tabelle", "db_datei",
                 "ereignis_datei")


def _parse_plcs(cp, conn):
    """Steuerungen aus [Steuerungen]/[SteuerungN] lesen. Ältere Dateien kennen nur [Verbindung]
    (ip/rack/slot/intervall_ms): daraus entsteht dann genau eine Steuerung."""
    plcs = []
    for i in range(1, cp.getint("Steuerungen", "anzahl", fallback=0) + 1):
        sec = f"Steuerung{i}"
        if not cp.has_section(sec):
            continue
        s = cp[sec]
        plcs.append(Plc(name=s.get("name", f"SPS {i}") or f"SPS {i}", ip=s.get("ip", "192.168.0.1"),
                        rack=s.getint("rack", 0), slot=s.getint("slot", 1),
                        intervall_ms=max(10, s.getint("intervall_ms", 200)),
                        enabled=s.getboolean("aktiv", True)))
    if not plcs:        # Kompatibilität mit Dateien ohne [Steuerungen]
        plcs = [Plc(ip=conn["ip"], rack=conn["rack"], slot=conn["slot"],
                    intervall_ms=max(10, conn["intervall_ms"]))]
    return plcs


def load_plcs(path: str = None) -> list:
    """Nur die Steuerungen einer Konfigurationsdatei (für das Konfigurationsprogramm)."""
    path = path or CONFIG_FILE
    conn = default_connection()
    if not os.path.exists(path):
        return _parse_plcs(configparser.ConfigParser(interpolation=None), conn)
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(path, encoding="utf-8")
    if cp.has_section("Verbindung"):
        s = cp["Verbindung"]
        conn["ip"] = s.get("ip", conn["ip"])
        for key in ("rack", "slot", "intervall_ms"):
            conn[key] = s.getint(key, conn[key])
    return _parse_plcs(cp, conn)


# ---------------------------------------------------------------------------------------
# Zuletzt benutzte Konfigurationsdatei
# ---------------------------------------------------------------------------------------
# Logger und Konfigurationsprogramm sollen ohne Parameter dieselbe Datei öffnen. Der Pfad der zuletzt
# benutzten Datei steht in einer kleinen Textdatei im Basisordner.
LAST_FILE = os.path.join(BASE_DIR, "s7_last.txt")


def last_config_path() -> str:
    """Pfad der zuletzt benutzten Konfigurationsdatei (Standard: s7_config.ini im Basisordner)."""
    try:
        with open(LAST_FILE, encoding="utf-8") as f:
            p = f.read().strip()
        if p and os.path.exists(p):
            return p
    except OSError:
        pass
    return CONFIG_FILE


def remember_config_path(path: str):
    """Merkt sich die Konfigurationsdatei für den nächsten Start (Fehler beim Schreiben sind unkritisch)."""
    try:
        with open(LAST_FILE, "w", encoding="utf-8") as f:
            f.write(os.path.abspath(path))
    except OSError:
        pass
    # Liste der zuletzt benutzten Dateien (für das Startbild).
    p = os.path.abspath(path)
    lst = [p] + [x for x in load_settings().get("zuletzt", []) if x != p]
    save_settings(zuletzt=lst[:15])


def _parse_blocks(cp, charts, n_plc=1):
    """Block-Abschnitte der INI-Datei in Block-Objekte umsetzen (n_plc: Anzahl der Steuerungen)."""
    # Block-Abschnitte ([BlockN]) aus der geöffneten INI-Datei lesen.
    # charts wird benötigt, um Diagramm-/Achsenindizes auf gültige Werte zu begrenzen.
    blocks = []
    for i in range(1, cp.getint("Bloecke", "anzahl", fallback=0) + 1):
        sec = f"Block{i}"
        if not cp.has_section(sec):
            continue
        s = cp[sec]
        dtype = s.get("typ", "REAL")
        # Unbekannte Typen (z. B. aus einer manuell geänderten Datei) werden übersprungen.
        if dtype not in TYPES:
            continue
        # In der Datei sind Diagramm und Achse 1-basiert; intern 0-basiert und auf den gültigen Bereich begrenzt.
        chart = min(max(s.getint("diagramm", 1) - 1, 0), len(charts) - 1)
        axis = min(max(s.getint("achse", 1) - 1, 0), len(charts[chart].axes) - 1)
        # Höchstens 1000 Elemente je Block (Schutz vor versehentlich riesigen Blöcken).
        count = max(1, min(s.getint("anzahl", 1), 1000))
        names = {}                               # eigene Elementnamen: elem_<Index> = Name
        for key, val in s.items():
            if key.startswith("elem_") and key[5:].isdigit() and val.strip():
                if int(key[5:]) < count:
                    names[int(key[5:])] = val.strip()
        # Abweichende Ziele einzelner Elemente: elemziel_<Index> = "Diagramm,Achse" (1-basiert).
        targets = {}
        for key, val in s.items():
            if key.startswith("elemziel_") and key[9:].isdigit() and int(key[9:]) < count:
                try:
                    tc, ta = (int(x) for x in val.split(","))
                except ValueError:
                    continue
                tc = min(max(tc - 1, 0), len(charts) - 1)
                ta = min(max(ta - 1, 0), len(charts[tc].axes) - 1)
                if (tc, ta) != (chart, axis):
                    targets[int(key[9:])] = (tc, ta)
        blocks.append(Block(
            name=s.get("name", f"Block{i}"), area=s.get("bereich", "DB"), db=s.getint("db", 1),
            start=s.getint("start", 0), bit=s.getint("bit", 0), dtype=dtype,
            plc=min(max(s.getint("steuerung", 1) - 1, 0), max(n_plc - 1, 0)), targets=targets,
            count=count, chart=chart, axis=axis, names=names,
            color=s.get("farbe", PALETTE[(i - 1) % len(PALETTE)]),
            show_value=s.getboolean("wert_anzeigen", True), bar=s.getboolean("balken", False)))
    return blocks


def load_blocks(path: str = None) -> list:
    """Nur die Blockdefinitionen (für das Konfigurationsprogramm)."""
    path = path or CONFIG_FILE
    if not os.path.exists(path):
        return []
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(path, encoding="utf-8")
    charts = [Chart()]
    n = cp.getint("Diagramme", "anzahl", fallback=0)
    if n:
        charts = []
        for i in range(1, n + 1):
            axes = max(1, cp.getint(f"Diagramm{i}", "achsen", fallback=1))
            charts.append(Chart(axes=[Axis() for _ in range(axes)]))
    return _parse_blocks(cp, charts, max(cp.getint("Steuerungen", "anzahl", fallback=1), 1))


def load_config(path: str = None):
    """Liest die INI-Datei -> (Verbindungs-Dict, Liste von Chart, Liste von Variable).

    Die Steuerungen liefert load_plcs(); Variable.plc verweist auf deren Index."""
    path = path or CONFIG_FILE
    # Mit Vorgabewerten beginnen; was in der Datei steht, überschreibt sie.
    conn = default_connection()
    charts, variables = [], []
    # Fehlt die Datei (erster Start), liefert die Funktion eine leere Standardkonfiguration.
    if not os.path.exists(path):
        return conn, [Chart()], variables
    # interpolation=None: '%' in Namen oder Formeln soll nicht als Platzhalter gedeutet werden.
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(path, encoding="utf-8")

    if cp.has_section("Verbindung"):
        s = cp["Verbindung"]
        # Textwerte; leer = Vorgabe (außer bei Feldern, die leer sein dürfen).
        for key in CONN_STR_KEYS:
            conn[key] = s.get(key, conn[key])
        conn["csv_name"] = conn["csv_name"] or "log"
        conn["archiv_ordner"] = conn["archiv_ordner"] or "archiv"
        if conn["anordnung"] not in LAYOUTS:
            conn["anordnung"] = "untereinander"
        if conn["seite_anordnung"] not in PAGE_LAYOUTS:
            conn["seite_anordnung"] = ""       # leer = automatisch (aus 'anordnung' abgeleitet)
        # Zahlenwerte mit Vorgabe lesen (ungültiger Text -> ValueError; die Datei wird bewusst nicht still repariert).
        for key in CONN_INT_KEYS:
            conn[key] = s.getint(key, conn[key])
    plcs = _parse_plcs(cp, conn)

    # Diagramme: [Diagramm1] ... mit Achsen [Diagramm1_Achse1] ...
    for i in range(1, cp.getint("Diagramme", "anzahl", fallback=0) + 1):
        sec = f"Diagramm{i}"
        if not cp.has_section(sec):
            continue
        s = cp[sec]
        axes = []
        for j in range(1, s.getint("achsen", 0) + 1):
            asec = f"Diagramm{i}_Achse{j}"
            if cp.has_section(asec):
                a = cp[asec]
                axes.append(Axis(name=a.get("name", f"Achse {j}"),
                                 auto=a.getboolean("auto", True),
                                 y_min=a.getfloat("y_min", 0.0),
                                 y_max=a.getfloat("y_max", 100.0)))
        # Kompatibilität: ältere Dateien kannten nur eine Skalierung je Diagramm (y_auto/y_min/y_max).
        if not axes:  # ältere Konfiguration: eine Achse je Diagramm
            axes = [Axis(auto=s.getboolean("y_auto", True),
                         y_min=s.getfloat("y_min", 0.0),
                         y_max=s.getfloat("y_max", 100.0))]
        charts.append(Chart(name=s.get("name", f"Diagramm {i}"), axes=axes,
                            page=s.get("seite", ""), pid=s.getboolean("pid_aktiv", False),
                            pid_sw=s.get("pid_sollwert", ""), pid_iw=s.get("pid_istwert", ""),
                            pid_stw=s.get("pid_stellwert", ""),
                            pid_typ=s.get("pid_typ", "PID") if s.get("pid_typ", "PID") in ("PI", "PID") else "PID",
                            pid_verhalten=s.get("pid_verhalten", "normal")
                            if s.get("pid_verhalten", "normal") in ("schnell", "normal", "robust") else "normal"))
    # Jede Konfiguration braucht mindestens ein Diagramm mit einer Achse.
    if not charts:
        charts = [Chart()]

    # Variablen: [Var1] ... (ohne die Elemente von Blöcken, diese entstehen unten aus [BlockN]).
    for i in range(1, cp.getint("Variablen", "anzahl", fallback=0) + 1):
        sec = f"Var{i}"
        if not cp.has_section(sec):
            continue
        s = cp[sec]
        chart = min(max(s.getint("diagramm", 1) - 1, 0), len(charts) - 1)
        axis = min(max(s.getint("achse", 1) - 1, 0), len(charts[chart].axes) - 1)
        variables.append(Variable(
            name=s.get("name", sec),
            area=s.get("bereich", "DB"),
            db=s.getint("db", 1),
            byte=s.getint("byte", 0),
            bit=s.getint("bit", 0),
            dtype=s.get("typ", "REAL"),
            color=s.get("farbe", PALETTE[(i - 1) % len(PALETTE)]),
            show_value=s.getboolean("wert_anzeigen", True),
            chart=chart,
            axis=axis,
            bar=s.getboolean("balken", True),
            formula=s.get("formel", ""),
            plc=min(max(s.getint("steuerung", 1) - 1, 0), len(plcs) - 1),
        ))
    # Block-Elemente stehen NICHT als [VarN] in der Datei, sondern werden hier aus den Blockdefinitionen
    # erzeugt und hinten an die Variablenliste gehängt (Reihenfolge: normale Variablen, dann Blöcke).
    for blk in _parse_blocks(cp, charts, len(plcs)):   # Block-Elemente als Variablen anhängen
        variables.extend(blk.variables())
    return conn, charts, variables


def save_config(conn: dict, charts, variables, path: str = None, blocks=(), plcs=None):
    """Konfiguration in die INI-Datei schreiben.

    conn: Verbindungs-/Anzeigeeinstellungen, charts: Diagramme mit Achsen, variables: normale und
    berechnete Variablen, blocks: Blockdefinitionen (deren Elemente werden nicht einzeln gespeichert),
    plcs: Steuerungen (ohne Angabe wird eine Steuerung aus conn ip/rack/slot/intervall_ms erzeugt).
    """
    path = path or CONFIG_FILE
    if not plcs:
        plcs = [Plc(ip=conn.get("ip", "192.168.0.1"), rack=conn.get("rack", 0), slot=conn.get("slot", 1),
                    intervall_ms=conn.get("intervall_ms", 200))]
    conn = dict(conn)
    # Die erste Steuerung bleibt zusätzlich unter [Verbindung] stehen (ältere Programmversionen lesen nur dort).
    conn.update(ip=plcs[0].ip, rack=plcs[0].rack, slot=plcs[0].slot, intervall_ms=plcs[0].intervall_ms)
    # Block-Elemente nie als einzelne [VarN] speichern - sie entstehen beim Laden aus [BlockN].
    variables = [v for v in variables if not v.block]   # Block-Elemente werden aus den Blöcken erzeugt
    cp = configparser.ConfigParser(interpolation=None)
    # Alle Werte der Verbindungseinstellungen als Text ablegen (configparser kennt nur Strings).
    cp["Verbindung"] = {k: str(v) for k, v in conn.items()}
    cp["Steuerungen"] = {"anzahl": str(len(plcs))}
    for i, p in enumerate(plcs, 1):
        cp[f"Steuerung{i}"] = {"name": p.name, "ip": p.ip, "rack": str(p.rack), "slot": str(p.slot),
                               "intervall_ms": str(p.intervall_ms), "aktiv": "1" if p.enabled else "0"}
    cp["Diagramme"] = {"anzahl": str(len(charts))}
    for i, c in enumerate(charts, 1):
        cp[f"Diagramm{i}"] = {"name": c.name, "achsen": str(len(c.axes)), "seite": c.page}
        if c.pid or c.pid_iw or c.pid_stw:
            cp[f"Diagramm{i}"].update(pid_aktiv="1" if c.pid else "0", pid_sollwert=c.pid_sw, pid_istwert=c.pid_iw,
                                      pid_stellwert=c.pid_stw, pid_typ=c.pid_typ, pid_verhalten=c.pid_verhalten)
        for j, a in enumerate(c.axes, 1):
            cp[f"Diagramm{i}_Achse{j}"] = {
                "name": a.name, "auto": "1" if a.auto else "0",
                "y_min": str(a.y_min), "y_max": str(a.y_max)}
    cp["Variablen"] = {"anzahl": str(len(variables))}
    for i, v in enumerate(variables, 1):
        cp[f"Var{i}"] = {
            "name": v.name, "bereich": v.area, "db": str(v.db),
            "byte": str(v.byte), "bit": str(v.bit), "typ": v.dtype,
            "farbe": v.color, "wert_anzeigen": "1" if v.show_value else "0",
            "diagramm": str(v.chart + 1), "achse": str(v.axis + 1),
            "balken": "1" if v.bar else "0",
            "formel": " ".join(v.formula.split()),
            "steuerung": str(v.plc + 1),
        }
    cp["Bloecke"] = {"anzahl": str(len(blocks))}
    for i, b in enumerate(blocks, 1):
        cp[f"Block{i}"] = {
            "name": b.name, "bereich": b.area, "db": str(b.db), "start": str(b.start),
            "bit": str(b.bit), "typ": b.dtype, "anzahl": str(b.count),
            "diagramm": str(b.chart + 1), "achse": str(b.axis + 1), "farbe": b.color,
            "wert_anzeigen": "1" if b.show_value else "0", "balken": "1" if b.bar else "0",
            "steuerung": str(b.plc + 1)}
        # Elemente, die in einem anderen Diagramm/auf einer anderen Y-Achse liegen als der Block.
        for idx, (tc, ta) in sorted(b.targets.items()):
            if 0 <= idx < b.count and (tc, ta) != (b.chart, b.axis):
                cp[f"Block{i}"][f"elemziel_{idx}"] = f"{tc + 1},{ta + 1}"
        # Nur Elementnamen speichern, die vom Standardnamen abweichen (Schlüssel elem_<Index>).
        for idx, nm in sorted(b.names.items()):       # nur abweichende Elementnamen speichern
            if nm and 0 <= idx < b.count:
                cp[f"Block{i}"][f"elem_{idx}"] = " ".join(nm.split())
    # Datei komplett neu schreiben (die Konfiguration ist klein; so bleibt sie immer konsistent).
    with open(path, "w", encoding="utf-8") as f:
        cp.write(f)


# ---------------------------------------------------------------------------------------
# Lesen aus der SPS
# ---------------------------------------------------------------------------------------
# Ablauf: build_plan() fasst die Variablen zu einem Leseplan zusammen (einmal beim Start),
# read_plan() führt ihn in jedem Messzyklus aus. Für einen Block genügt eine einzige Anfrage,
# während jede Einzelvariable eine eigene Anfrage (und damit mehr Zeit) braucht.
class BlockRead:
    """Ein Block, der mit einer einzigen Anfrage gelesen wird."""

    def __init__(self, area, db):
        """area/db: Speicherbereich und DB-Nummer des Blocks (für die Anfrage an die SPS)."""
        self.area, self.db = area, db
        # Elemente des Blocks als (Position in der Gesamtliste, Variable); die Position bestimmt später,
        # wohin der gelesene Wert in der Ergebnisliste geschrieben wird.
        self.items = []           # (Position in der Variablenliste, Variable)
        self.start = 0
        self.nbytes = 0

    def finish(self):
        """Start und Länge des Bereichs aus den Elementen berechnen (nach dem Hinzufügen aller Elemente aufrufen)."""
        # Startadresse = kleinste Byteadresse aller Elemente.
        self.start = min(v.byte for _, v in self.items)
        # Ende = letztes belegtes Byte (BOOL belegt immer das ganze Byte, in dem das Bit liegt).
        end = max(v.byte + (1 if v.dtype == "BOOL" else TYPES[v.dtype][0]) for _, v in self.items)
        self.nbytes = end - self.start


def build_plan(variables):
    """Leseplan: Variablen mit gleichem ``block`` werden zu einer Blockanfrage zusammengefasst,
    alle anderen einzeln gelesen."""
    plan, blocks = [], {}
    # pos = Position der Variable in der Messwertliste (die Reihenfolge muss mit dem Logger übereinstimmen).
    for pos, v in enumerate(variables):
        if v.block:
            # Alle Variablen eines Blocks teilen sich ein BlockRead-Objekt (Schlüssel: Blockname).
            b = blocks.get(v.block)
            if b is None:
                b = blocks[v.block] = BlockRead(v.area, v.db)
                plan.append(b)
            b.items.append((pos, v))
        else:
            plan.append((pos, v))
    # Erst jetzt, wenn alle Elemente bekannt sind, Start und Länge des Bereichs berechnen.
    for b in blocks.values():
        b.finish()
    return plan


def _decode_at(raw, v: Variable, base: int) -> float:
    """Wert eines Elements aus den gelesenen Rohdaten des Blocks dekodieren (base = Startadresse des Blocks)."""
    # Abstand des Elements vom Anfang des gelesenen Bereichs.
    off = v.byte - base
    if v.dtype == "BOOL":
        # BOOL: Bit aus dem Byte herauslösen (Verschieben + Maskieren).
        return float((raw[off] >> v.bit) & 1)
    # Zahl aus den Rohbytes dekodieren (Big Endian, siehe TYPES).
    return float(struct.unpack_from(TYPES[v.dtype][1], raw, off)[0])


def read_plan(client, plan, n: int) -> list:
    """Führt den Leseplan aus -> Liste der n Werte (in der Reihenfolge der Variablenliste)."""
    # Nicht lesbare Werte bleiben NaN ("kein Wert"), z. B. wenn ein Eintrag im Plan fehlt.
    out = [float("nan")] * n
    for entry in plan:
        # Block: ein Aufruf für den ganzen Bereich ...
        if isinstance(entry, BlockRead):
            # Nur Datenbausteine haben eine Nummer; Merker, Ein- und Ausgänge werden mit 0 angesprochen.
            db = entry.db if entry.area == "DB" else 0
            raw = bytes(client.read_area(AREAS[entry.area], db, entry.start, entry.nbytes))
            # ... danach die Elemente einzeln aus den gelesenen Bytes herausschneiden und dekodieren.
            for pos, v in entry.items:
                out[pos] = _decode_at(raw, v, entry.start)
        # Einzelvariable: eigene Anfrage.
        else:
            pos, v = entry
            out[pos] = read_var(client, v)
    return out


def read_var(client, v: Variable) -> float:
    """Liest eine Variable aus der SPS und gibt den Wert als float zurück."""
    # size = Anzahl zu lesender Bytes, fmt = struct-Format zum Dekodieren (None bei BOOL).
    size, fmt = TYPES[v.dtype]
    db = v.db if v.area == "DB" else 0
    raw = client.read_area(AREAS[v.area], db, v.byte, size)
    if v.dtype == "BOOL":
        return float((raw[0] >> v.bit) & 1)
    return float(struct.unpack(fmt, bytes(raw))[0])


# Je nach python-snap7-Version heißt die Konstante für 'Datenbaustein' anders - alle bekannten
# Fundstellen werden probiert (neu: snap7.type.Block, älter: snap7.types, ganz alt: snap7types).
def _block_db_type():
    """Block-Typ "DB" für list_blocks_of_type (je nach python-snap7-Version unterschiedlich)."""
    for mod, attr in (("snap7.type", "Block"), ("snap7.types", "Block"),
                      ("snap7.type", "Blocks"), ("snap7.types", "Blocks")):
        try:
            m = __import__(mod, fromlist=[attr])
            return getattr(getattr(m, attr), "DB")
        except Exception:
            continue
    try:
        import snap7.snap7types as t
        return t.block_types["DB"]
    except Exception:
        return None


def list_plc_dbs(client) -> dict:
    """Liefert {DB-Nummer: Größe in Bytes (oder None)} der in der SPS vorhandenen Datenbausteine.

    Die SPS kann nur Nummern und Größen nennen - keine Namen oder Strukturen."""
    # Block-Typ 'DB' ermitteln; ohne ihn ist keine Bausteinliste möglich.
    db_type = _block_db_type()
    if db_type is None:
        raise RuntimeError("Die installierte python-snap7-Version unterstützt keine Bausteinliste.")
    # Anfrage an die SPS: Nummern aller vorhandenen Datenbausteine (bis zu 2000).
    numbers = [int(n) for n in client.list_blocks_of_type(db_type, 2000)]
    result = {}
    for n in numbers:
        # Größe je Baustein (MC7Size = Länge der Daten); kann je nach Schutzstufe der CPU scheitern -> None.
        try:
            result[n] = int(client.get_block_info(db_type, n).MC7Size)
        except Exception:
            result[n] = None
    return result
