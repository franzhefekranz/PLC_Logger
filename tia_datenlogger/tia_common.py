"""Gemeinsame Grundlagen des TIA-Datenloggers: Datenmodell, Konfiguration (JSON) und Hilfen für Tag-Namen.

Der TIA-Datenlogger liest Variablen aus Siemens S7-1200/S7-1500-Steuerungen (TIA Portal) über das Protokoll
S7CommPlus – symbolisch über den Variablennamen, also auch aus Datenbausteinen mit "Optimiertem Bausteinzugriff" und
ohne PUT/GET-Freigabe. Die Kommunikation übernimmt die Python-Bibliothek ``s7commplus`` (Modul tia_io.py); die
Variablenliste für die Auswahl liefert die Steuerung selbst (browse, Modul tia_taglist.py).

Dieses Modul wird vom Logger, vom Konfigurationsprogramm und von den Dialogen verwendet. Es enthält

* das Datenmodell:  Plc (Steuerung) und Axis (Y-Achse) -> Chart (Diagramm) -> Variable, außerdem Block
  (Ausschnitt eines Arrays, dessen Elemente gemeinsam gelesen werden). Eine Variable gehört zu genau einer Steuerung, einem Diagramm
  und einer Y-Achse darin;
* das Laden/Speichern der Konfiguration in einer JSON-Datei (load_config / load_plcs / load_blocks /
  save_config) sowie die Merkhilfe für die zuletzt benutzte Konfigurationsdatei;
* Hilfen für Variablennamen (check_tag_name).

Das Modul enthält keine Oberfläche (kein Qt) und keine Kommunikation, ist also ohne Steuerung testbar.
"""
import colorsys
import json
import os
import re
import sys
from dataclasses import dataclass, field
from tia_i18n import N_

# Basisordner für alle Dateien, die das Programm selbst anlegt (Konfiguration, CSV, Archiv, Logo-Pfade).
def _app_dir() -> str:
    """Ordner für Konfiguration, CSV-Dateien und Archiv.

    Normalbetrieb (Python-Skripte): der Ordner der Programmdateien.
    Installierte Version (PyInstaller): der Programmordner ist meist schreibgeschützt
    (C:\\Program Files), daher liegen die Daten unter %APPDATA%\\TIADatenlogger. Eine Datei
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
        path = os.path.join(root, "TIADatenlogger")
        os.makedirs(path, exist_ok=True)
        return path
    # Entwicklungsbetrieb (python tia_logger.py): der Ordner dieser Datei.
    return os.path.dirname(os.path.abspath(__file__))


# Wird beim Import einmalig berechnet; alle relativen Pfade der Konfiguration beziehen sich darauf.
BASE_DIR = _app_dir()
# Standardname der Konfigurationsdatei (das Konfigurationsprogramm kann auch andere Dateien laden).
CONFIG_FILE = os.path.join(BASE_DIR, "tia_config.json")

# Programmname und Version (Startbild, Info-Dialog, Fenstertitel).
APP_NAME = "TIA Datenlogger"
APP_VERSION = "2.1.0"
# Programmdateien der installierten Windows-Version.
LOGGER_EXE, CONFIG_EXE = "TIALogger.exe", "TIAKonfiguration.exe"
# Persönliche Einstellungen (Sprache, Startbild, zuletzt benutzte Konfigurationen) – JSON im Datenordner.
SETTINGS_FILE = os.path.join(BASE_DIR, "tia_einstellungen.json")


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
        if isinstance(p, str) and p.lower().endswith(".json") and os.path.exists(p) and p not in out:
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
    script = "tia_logger.py" if kind == "logger" else "tia_config.py"
    return [sys.executable, os.path.join(here, script)] + args

# Aufzeichenbare Datentypen (Namen wie in TIA Portal). Der Wert ist die Größe in Bytes (nur zur Information);
# dekodiert wird nach dem Typ, den die Steuerung beim Durchsuchen meldet (s7commplus SymbolicTag.decode_value).
TYPES = {
    "BOOL": 1, "BYTE": 1, "WORD": 2, "DWORD": 4, "LWORD": 8,
    "SINT": 1, "INT": 2, "DINT": 4, "LINT": 8,
    "USINT": 1, "UINT": 2, "UDINT": 4, "ULINT": 8,
    "REAL": 4, "LREAL": 8,
    "TIME": 4, "LTIME": 8, "S5TIME": 2, "CHAR": 1, "WCHAR": 2,
}
# Formate, die als Block (Ausschnitt eines Arrays) übernommen werden können.
BLOCK_TYPES = list(TYPES)
# Ganzzahltypen (für Anzeige ohne Nachkommastellen); Zeiten werden in Millisekunden aufgezeichnet.
INT_TYPES = ("BYTE", "WORD", "DWORD", "LWORD", "SINT", "INT", "DINT", "LINT", "USINT", "UINT", "UDINT", "ULINT",
             "TIME", "LTIME", "S5TIME", "CHAR", "WCHAR")

# TLS-Betriebsarten der Verbindung (Schlüssel in der Konfiguration -> Anzeige).
TLS_MODES = {"auto": N_("Automatisch"), "aus": N_("Aus"), "an": N_("An (TLS erzwingen)")}
# Rolle, mit der sich der Logger anmeldet (s7commplus connection_type).
ROLES = {"hmi": N_("HMI (Standard)"), "es": N_("Engineering"), "pg": N_("PG")}

# Anordnungen der Diagramm-Seiten: Schlüssel in der Konfiguration -> Text im Menü bzw. in der Auswahl.
LAYOUTS = {"untereinander": N_("Untereinander"),
           "nebeneinander": N_("Nebeneinander"),
           "tabs": N_("Tabs")}

# Anordnung der Diagramme INNERHALB einer Seite (Menü Ansicht): Schlüssel in der Konfiguration -> Text.
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
    """Eine Steuerung, aus der gelesen wird. Jede Steuerung bekommt einen eigenen Lese-Thread und ein eigenes
    Abtastintervall; Variablen verweisen über ihren Index (``Variable.plc``) darauf."""
    name: str = "SPS 1"           # frei wählbarer Name (Anzeige, Status-LED)
    ip: str = "192.168.0.1"       # IP-Adresse der CPU bzw. des Kommunikationsmoduls
    port: int = 102               # ISO-on-TCP (Standard 102)
    tls: str = "auto"             # "auto" | "aus" | "an" (siehe TLS_MODES)
    passwort: str = ""            # Passwort der Zugriffsstufe (leer = keine Legitimation)
    rolle: str = "hmi"            # Anmelderolle (siehe ROLES)
    intervall_ms: int = 200       # Abtastzeit dieser Steuerung in Millisekunden
    enabled: bool = True          # False: Steuerung wird nicht gelesen (ihre Variablen bleiben ohne Wert)
    tags_je_anfrage: int = 50     # Höchstzahl Variablen je Leseanfrage (größere Mengen werden aufgeteilt)


def check_tag_name(tag: str) -> bool:
    """True, wenn der Variablenname formal brauchbar ist: nicht leer, ohne Steuerzeichen und ';', Klammern
    ausgeglichen. TIA-Namen dürfen fast alle Zeichen enthalten; ob es die Variable gibt, prüft erst die Steuerung."""
    if not tag or tag != tag.strip() or ";" in tag or any(ord(ch) < 32 for ch in tag):
        return False
    depth = 0
    for ch in tag:
        depth += 1 if ch == "[" else -1 if ch == "]" else 0
        if depth < 0:
            return False
    return depth == 0 and not tag.startswith(".") and not tag.endswith(".") and ".." not in tag


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

    Normale Variable: ``tag`` ist der symbolische Name in der Steuerung, wie ihn die Variablenliste liefert:
    ``<Datenbaustein>.<Variable>[.<Glied>…]``, Array-Elemente mit Index, z. B. ``Anlage_DB.Motor[2].Drehzahl``;
    Merker/Ein-/Ausgänge (PLC-Variablen) unter ``MArea``, ``IArea``, ``QArea``. ``dtype`` ist der Datentyp.
    Berechnete Variable: formula ist nicht leer, der Tag ist ohne Bedeutung. Block-Element: block/block_idx sind
    gesetzt; das Element wird zusammen mit seinem Block mit einer Anfrage gelesen.
    """
    name: str
    tag: str = ""
    dtype: str = "REAL"
    color: str = "#1f77b4"
    show_value: bool = True   # in der Werteanzeige/Lineal-Tabelle aufführen
    chart: int = 0            # Index des Diagramms (0-basiert)
    axis: int = 0             # Index der Y-Achse innerhalb des Diagramms (0-basiert)
    bar: bool = True          # schmaler Balken für den Aktualwert
    formula: str = ""         # nicht leer: berechnete Variable (Tag/Typ ohne Bedeutung)
    block: str = ""           # Name des Blocks, zu dem die Variable gehört (Blocklesemodus)
    block_idx: int = 0        # Position innerhalb des Blocks
    plc: int = 0              # Index der Steuerung (0-basiert, siehe Plc)

    def address(self) -> str:
        """Adresse für Anzeigen und Tooltips: der Tag-Name (bzw. 'berechnet')."""
        return "berechnet" if self.formula else self.tag


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
    """Blocklesemodus: ein Ausschnitt eines Arrays (gleiches Format), dessen Elemente gemeinsam in einer Anfrage
    gelesen werden. ``tag`` ist der Name des Arrays (ohne Index), ``start`` der erste Index (wie in TIA, also z. B. 1
    bei Array[1..10]), ``count`` die Anzahl der Elemente. Jedes Element wird zu einer Variable ``<Name>[i]``."""
    name: str = "Block1"
    tag: str = ""             # Array ohne Index, z. B. Messwerte_DB.Temp
    start: int = 0            # erster Array-Index
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

    def size_bytes(self) -> int:
        """Größe der Nutzdaten in Bytes (nur zur Information)."""
        return self.count * TYPES.get(self.dtype, 4)

    def read_tag(self) -> str:
        """Name des ersten Elements, z. B. ``Messwerte_DB.Temp[1]``."""
        return f"{self.tag}[{self.start}]"

    # Erzeugt aus dem Block die einzelnen Variablen ('Name[0]' ... 'Name[n-1]' oder eigene Namen).
    def variables(self) -> list:
        out = []
        for i in range(self.count):
            # Einzelne Elemente dürfen in einem ANDEREN Diagramm/auf einer anderen Y-Achse liegen als der Rest
            # des Blocks (self.targets); gelesen werden sie trotzdem gemeinsam mit einer Anfrage.
            chart, axis = self.targets.get(i, (self.chart, self.axis))
            out.append(Variable(
                name=self.names.get(i) or f"{self.name}[{i}]", tag=f"{self.tag}[{self.start + i}]",
                dtype=self.dtype, color=_shade(self.color, i), show_value=self.show_value,
                chart=chart, axis=axis, bar=self.bar, block=self.name, block_idx=i, plc=self.plc))
        return out

    def address_range(self) -> str:
        """Bereich als Text, z. B. 'Messwerte[0] … Messwerte[19]'."""
        if self.count <= 1:
            return f"{self.tag}[{self.start}]"
        return f"{self.tag}[{self.start}] … {self.tag}[{self.start + self.count - 1}]"


# ---------------------------------------------------------------------------------------
# Konfigurationsdatei im JSON-Format
# ---------------------------------------------------------------------------------------
# Auf der Platte steht die Konfiguration als verschachteltes JSON (Listen für Steuerungen, Diagramme mit Achsen,
# Variablen, Blöcke und Trigger; Zahlen und Wahrheitswerte mit echtem Typ). Intern arbeitet das Programm weiter mit
# Abschnitten und Schlüsseln (ConfigParser) – die Umwandlung übernehmen read_config_store()/write_config_store().
# Ältere INI-Dateien werden nicht mehr gelesen; convert_ini() wandelt sie einmalig um (Konfigurationsprogramm:
# Datei › INI-Datei umwandeln …, oder tools/ini2json.py).
CONFIG_EXT = ".json"
CONFIG_FORMAT = "TIA Datenlogger Konfiguration"
CONFIG_VERSION = 1

# Nummerierte Abschnitte: (JSON-Schlüssel, Zählabschnitt, Präfix der Einzelabschnitte)
_GROUPS = (("steuerungen", "Steuerungen", "Steuerung"), ("diagramme", "Diagramme", "Diagramm"),
           ("variablen", "Variablen", "Var"), ("bloecke", "Bloecke", "Block"), ("trigger", "Trigger", "Trigger"))
# Schlüssel mit festem Typ in der JSON-Datei (alle übrigen bleiben Text)
_BOOL_KEYS = {"aktiv", "auto", "y_auto", "wert_anzeigen", "balken", "pid_aktiv", "gehen", "quittieren",
              "web_aktiv", "headless", "csv_aktiv", "archiv_beenden", "db_nur_aenderungen"}
_INT_KEYS = {"intervall_ms", "timeout_ms", "diagramm", "achse", "steuerung", "start", "fenster_s", "max_records",
             "raster_spalten", "web_port", "web_intervall_ms", "db_port", "rack", "slot", "port", "unit",
             "max_register", "luecke", "tags_je_anfrage", "db", "byte", "bit", "anzahl"}
_FLOAT_KEYS = {"y_min", "y_max", "verzoegerung_s", "amplitude"}
_JSON_KEYS = {"treiberdaten"}                    # Text mit JSON-Inhalt -> verschachteltes Objekt


class ConfigFormatError(ValueError):
    """Die Datei ist keine Konfiguration im JSON-Format (z. B. eine ältere INI-Datei)."""


def _new_cp():
    import configparser
    return configparser.ConfigParser(interpolation=None)


def _to_json_value(key, text):
    """Wert eines Schlüssels (Text) -> passender JSON-Typ."""
    t = "" if text is None else str(text)
    try:
        if key in _BOOL_KEYS:
            return t.strip().lower() in ("1", "true", "ja", "yes", "on")
        if key in _INT_KEYS and t.strip() != "":
            return int(float(t))
        if key in _FLOAT_KEYS and t.strip() != "":
            return float(t)
        if key in _JSON_KEYS:
            return json.loads(t) if t.strip() else {}
    except (TypeError, ValueError):
        pass
    return t


def _to_text(value):
    """JSON-Wert -> Text für die interne Darstellung."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return repr(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False) if value else ""
    return str(value)


def _section_to_json(sec):
    out = {}
    for k, v in sec.items():
        m = re.fullmatch(r"elem_(\d+)", k)
        if m:
            out.setdefault("elementnamen", {})[m.group(1)] = v
            continue
        m = re.fullmatch(r"elemziel_(\d+)", k)
        if m:
            try:
                d, a = (int(x) for x in v.split(","))
                out.setdefault("elementziele", {})[m.group(1)] = [d, a]
            except ValueError:
                pass
            continue
        out[k] = _to_json_value(k, v)
    return out


def _json_to_section(d):
    sec = {}
    for k, v in d.items():
        if k == "elementnamen" and isinstance(v, dict):
            for idx, name in v.items():
                sec[f"elem_{int(idx)}"] = str(name)
        elif k == "elementziele" and isinstance(v, dict):
            for idx, (dg, ax) in v.items():
                sec[f"elemziel_{int(idx)}"] = f"{int(dg)},{int(ax)}"
        elif k != "achsen" or not isinstance(v, list):
            sec[k] = _to_text(v)
    return sec


def cp_to_json(cp) -> dict:
    """Interne Darstellung (Abschnitte) -> JSON-Dokument."""
    doc = {"format": CONFIG_FORMAT, "version": CONFIG_VERSION}
    used = set()
    if cp.has_section("Verbindung"):
        doc["einstellungen"] = _section_to_json(cp["Verbindung"])
        used.add("Verbindung")
    for key, count_sec, prefix in _GROUPS:
        items = []
        n = cp.getint(count_sec, "anzahl", fallback=0) if cp.has_section(count_sec) else 0
        used.add(count_sec)
        for i in range(1, n + 1):
            name = f"{prefix}{i}"
            if not cp.has_section(name):
                continue
            used.add(name)
            item = _section_to_json(cp[name])
            if key == "diagramme":
                axes = []
                for j in range(1, int(item.pop("achsen", 0) or 0) + 1):
                    an = f"{name}_Achse{j}"
                    if cp.has_section(an):
                        axes.append(_section_to_json(cp[an]))
                        used.add(an)
                item["achsen"] = axes
            items.append(item)
        if items or cp.has_section(count_sec):
            doc[key] = items
    rest = {s: dict(cp[s]) for s in cp.sections() if s not in used}
    if rest:
        doc["weitere"] = rest                  # unbekannte Abschnitte verlustfrei aufbewahren
    return doc


def json_to_cp(doc):
    """JSON-Dokument -> interne Darstellung (Abschnitte)."""
    cp = _new_cp()
    if not isinstance(doc, dict) or "einstellungen" not in doc and not any(g[0] in doc for g in _GROUPS):
        raise ConfigFormatError("Unbekannter Aufbau der Konfigurationsdatei")
    cp["Verbindung"] = _json_to_section(doc.get("einstellungen") or {})
    for key, count_sec, prefix in _GROUPS:
        if key not in doc:
            continue
        items = [it for it in (doc.get(key) or []) if isinstance(it, dict)]
        cp[count_sec] = {"anzahl": str(len(items))}
        for i, it in enumerate(items, 1):
            sec = _json_to_section(it)
            if key == "diagramme":
                axes = [a for a in (it.get("achsen") or []) if isinstance(a, dict)]
                sec["achsen"] = str(len(axes))
                for j, a in enumerate(axes, 1):
                    cp[f"{prefix}{i}_Achse{j}"] = _json_to_section(a)
            cp[f"{prefix}{i}"] = sec
    for name, sec in (doc.get("weitere") or {}).items():
        cp[name] = {k: _to_text(v) for k, v in sec.items()}
    return cp


def read_config_store(path):
    """Konfigurationsdatei (JSON) lesen -> interne Darstellung. Fehlt die Datei: leere Darstellung.

    Eine INI- oder sonstige Datei löst ConfigFormatError aus (mit Hinweis auf die Umwandlung)."""
    if not path or not os.path.exists(path):
        return _new_cp()
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    if not text.strip():
        return _new_cp()
    try:
        doc = json.loads(text)
    except ValueError as e:
        if text.lstrip().startswith("["):
            raise ConfigFormatError(
                f"„{os.path.basename(path)}“ ist eine INI-Datei. Konfigurationen werden jetzt als JSON gespeichert – "
                "bitte einmalig umwandeln: Konfigurationsprogramm › Datei › INI-Datei umwandeln … "
                "(oder tools/ini2json.py).") from None
        raise ConfigFormatError(f"„{os.path.basename(path)}“ ist keine gültige JSON-Datei: {e}") from None
    return json_to_cp(doc)


def write_config_store(cp, path):
    """Interne Darstellung als JSON schreiben (erst in eine temporäre Datei, dann ersetzen)."""
    doc = cp_to_json(cp)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def convert_ini(ini_path, json_path=None):
    """Ältere INI-Konfiguration einmalig in eine JSON-Datei umwandeln. Rückgabe: Pfad der JSON-Datei.

    Die INI-Datei bleibt unverändert. Vorhandene JSON-Datei gleichen Namens wird überschrieben."""
    cp = _new_cp()
    with open(ini_path, encoding="utf-8-sig") as f:
        cp.read_file(f)
    json_path = json_path or os.path.splitext(ini_path)[0] + CONFIG_EXT
    write_config_store(cp, json_path)
    return json_path

# ---------------------------------------------------------------------------------------
# Konfiguration: Lesen und Schreiben (intern in Abschnitten, Datei als JSON – siehe oben)
# ---------------------------------------------------------------------------------------
# Abschnitte:  [Verbindung]  [Diagramme] [DiagrammN] [DiagrammN_AchseM]  [Variablen] [VarN]  [Bloecke] [BlockN]
def default_connection() -> dict:
    """Vorgabewerte für die Verbindungs- und Anzeigeeinstellungen (Abschnitt [Verbindung])."""
    # ip/port/intervall_ms spiegeln die erste Steuerung; csv_*/archiv_* = CSV-Protokoll und Archivierung;
    # fenster_s = Anzeigefenster online; anordnung/balken = Darstellung; logo/icon = Branding.
    return {"ip": "192.168.0.1", "port": 102,
            "intervall_ms": 200, "csv_ordner": "logs", "fenster_s": 60,
            "anordnung": "untereinander", "balken": 1,
            "logo": "", "icon": "", "csv_name": "log", "max_records": 0,
            "archiv_ordner": "archiv",
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
CONN_INT_KEYS = ("port", "intervall_ms", "fenster_s", "balken", "max_records", "archiv_beenden",
                 "raster_spalten", "web_aktiv", "web_port", "web_intervall_ms", "headless",
                 "csv_aktiv", "db_port", "db_nur_aenderungen")
CONN_STR_KEYS = ("ip", "csv_ordner", "anordnung", "logo", "icon", "csv_name",
                 "archiv_ordner", "projekt", "seite_anordnung", "web_host", "web_token",
                 "db_typ", "db_host", "db_name", "db_user", "db_passwort", "db_tabelle", "db_datei",
                 "ereignis_datei")


def _parse_plcs(cp, conn):
    """Steuerungen aus [Steuerungen]/[SteuerungN] lesen. Ohne diese Abschnitte entsteht aus [Verbindung]
    (ip/port/intervall_ms) genau eine Steuerung."""
    plcs = []
    for i in range(1, cp.getint("Steuerungen", "anzahl", fallback=0) + 1):
        sec = f"Steuerung{i}"
        if not cp.has_section(sec):
            continue
        s = cp[sec]
        tls = s.get("tls", "auto").strip().lower()
        rolle = s.get("rolle", "hmi").strip().lower()
        plcs.append(Plc(name=s.get("name", f"SPS {i}") or f"SPS {i}", ip=s.get("ip", "192.168.0.1"),
                        port=s.getint("port", 102), tls=tls if tls in TLS_MODES else "auto",
                        passwort=s.get("passwort", ""), rolle=rolle if rolle in ROLES else "hmi",
                        intervall_ms=max(10, s.getint("intervall_ms", 200)),
                        tags_je_anfrage=min(max(s.getint("tags_je_anfrage", 50), 1), 1000),
                        enabled=s.getboolean("aktiv", True)))
    if not plcs:
        plcs = [Plc(ip=conn["ip"], port=conn.get("port", 102), intervall_ms=max(10, conn["intervall_ms"]))]
    return plcs


def load_plcs(path: str = None) -> list:
    """Nur die Steuerungen einer Konfigurationsdatei (für das Konfigurationsprogramm)."""
    path = path or CONFIG_FILE
    conn = default_connection()
    cp = read_config_store(path)
    if cp.has_section("Verbindung"):
        s = cp["Verbindung"]
        conn["ip"] = s.get("ip", conn["ip"])
        for key in ("port", "intervall_ms"):
            conn[key] = s.getint(key, conn[key])
    return _parse_plcs(cp, conn)


# ---------------------------------------------------------------------------------------
# Zuletzt benutzte Konfigurationsdatei
# ---------------------------------------------------------------------------------------
# Logger und Konfigurationsprogramm sollen ohne Parameter dieselbe Datei öffnen. Der Pfad der zuletzt
# benutzten Datei steht in einer kleinen Textdatei im Basisordner.
LAST_FILE = os.path.join(BASE_DIR, "tia_last.txt")


def last_config_path() -> str:
    """Pfad der zuletzt benutzten Konfigurationsdatei (Standard: tia_config.json im Basisordner)."""
    try:
        with open(LAST_FILE, encoding="utf-8") as f:
            p = f.read().strip()
        # früher benutzte INI-Datei: gleichnamige, bereits umgewandelte JSON-Datei verwenden
        alt = os.path.splitext(p)[0] + CONFIG_EXT
        if p and not p.lower().endswith(CONFIG_EXT) and os.path.exists(alt):
            return alt
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
    """Block-Abschnitte der Konfiguration in Block-Objekte umsetzen (n_plc: Anzahl der Steuerungen)."""
    # Block-Abschnitte ([BlockN]) aus der geöffneten Konfiguration lesen.
    # charts wird benötigt, um Diagramm-/Achsenindizes auf gültige Werte zu begrenzen.
    blocks = []
    for i in range(1, cp.getint("Bloecke", "anzahl", fallback=0) + 1):
        sec = f"Block{i}"
        if not cp.has_section(sec):
            continue
        s = cp[sec]
        dtype = s.get("typ", "REAL").upper()
        # Unbekannte Typen (z. B. aus einer manuell geänderten Datei) werden übersprungen.
        if dtype not in BLOCK_TYPES:
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
            name=s.get("name", f"Block{i}"), tag=s.get("tag", "").strip(),
            start=max(0, s.getint("start", 0)), dtype=dtype,
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
    cp = read_config_store(path)
    charts = [Chart()]
    n = cp.getint("Diagramme", "anzahl", fallback=0)
    if n:
        charts = []
        for i in range(1, n + 1):
            axes = max(1, cp.getint(f"Diagramm{i}", "achsen", fallback=1))
            charts.append(Chart(axes=[Axis() for _ in range(axes)]))
    return _parse_blocks(cp, charts, max(cp.getint("Steuerungen", "anzahl", fallback=1), 1))


def load_config(path: str = None):
    """Liest die Konfigurationsdatei (JSON) -> (Verbindungs-Dict, Liste von Chart, Liste von Variable).

    Die Steuerungen liefert load_plcs(); Variable.plc verweist auf deren Index."""
    path = path or CONFIG_FILE
    # Mit Vorgabewerten beginnen; was in der Datei steht, überschreibt sie.
    conn = default_connection()
    charts, variables = [], []
    # Fehlt die Datei (erster Start), liefert die Funktion eine leere Standardkonfiguration.
    if not os.path.exists(path):
        return conn, [Chart()], variables
    # interpolation=None: '%' in Namen oder Formeln soll nicht als Platzhalter gedeutet werden.
    cp = read_config_store(path)

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
            tag=s.get("tag", "").strip(),
            dtype=s.get("typ", "REAL").upper() if s.get("typ", "REAL").upper() in TYPES else "REAL",
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
    """Konfiguration in die Datei (JSON) schreiben.

    conn: Verbindungs-/Anzeigeeinstellungen, charts: Diagramme mit Achsen, variables: normale und
    berechnete Variablen, blocks: Blockdefinitionen (deren Elemente werden nicht einzeln gespeichert),
    plcs: Steuerungen (ohne Angabe wird eine Steuerung aus conn ip/port/intervall_ms erzeugt).
    """
    path = path or CONFIG_FILE
    if not plcs:
        plcs = [Plc(ip=conn.get("ip", "192.168.0.1"), port=conn.get("port", 102),
                    intervall_ms=conn.get("intervall_ms", 200))]
    conn = dict(conn)
    # Die erste Steuerung steht zusätzlich unter [Verbindung] (Dateien mit nur einer Steuerung bleiben lesbar).
    conn.update(ip=plcs[0].ip, port=plcs[0].port, intervall_ms=plcs[0].intervall_ms)
    # Block-Elemente nie als einzelne [VarN] speichern - sie entstehen beim Laden aus [BlockN].
    variables = [v for v in variables if not v.block]
    cp = _new_cp()
    cp["Verbindung"] = {k: str(v) for k, v in conn.items()}
    cp["Steuerungen"] = {"anzahl": str(len(plcs))}
    for i, p in enumerate(plcs, 1):
        cp[f"Steuerung{i}"] = {"name": p.name, "ip": p.ip, "port": str(p.port), "tls": p.tls,
                               "passwort": p.passwort, "rolle": p.rolle,
                               "intervall_ms": str(p.intervall_ms), "tags_je_anfrage": str(p.tags_je_anfrage),
                               "aktiv": "1" if p.enabled else "0"}
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
            "name": v.name, "tag": v.tag, "typ": v.dtype,
            "farbe": v.color, "wert_anzeigen": "1" if v.show_value else "0",
            "diagramm": str(v.chart + 1), "achse": str(v.axis + 1),
            "balken": "1" if v.bar else "0",
            "formel": " ".join(v.formula.split()),
            "steuerung": str(v.plc + 1),
        }
    cp["Bloecke"] = {"anzahl": str(len(blocks))}
    for i, b in enumerate(blocks, 1):
        cp[f"Block{i}"] = {
            "name": b.name, "tag": b.tag, "start": str(b.start), "typ": b.dtype, "anzahl": str(b.count),
            "diagramm": str(b.chart + 1), "achse": str(b.axis + 1), "farbe": b.color,
            "wert_anzeigen": "1" if b.show_value else "0", "balken": "1" if b.bar else "0",
            "steuerung": str(b.plc + 1)}
        # Elemente, die in einem anderen Diagramm/auf einer anderen Y-Achse liegen als der Block.
        for idx, (tc, ta) in sorted(b.targets.items()):
            if 0 <= idx < b.count and (tc, ta) != (b.chart, b.axis):
                cp[f"Block{i}"][f"elemziel_{idx}"] = f"{tc + 1},{ta + 1}"
        # Nur Elementnamen speichern, die vom Standardnamen abweichen (Schlüssel elem_<Index>).
        for idx, nm in sorted(b.names.items()):
            if nm and 0 <= idx < b.count:
                cp[f"Block{i}"][f"elem_{idx}"] = " ".join(nm.split())
    # Datei komplett neu schreiben (die Konfiguration ist klein; so bleibt sie immer konsistent).
    write_config_store(cp, path)
