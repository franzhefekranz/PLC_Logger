# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Gemeinsame Grundlagen des PLC-Datenloggers: Datenmodell und Konfiguration (JSON) – für alle Steuerungstypen.

Der PLC-Datenlogger liest aus beliebigen Steuerungen; das Protokoll steckt in austauschbaren **Treibern** (Paket
plc_treiber: Siemens S7 über PUT/GET, Siemens S7-1200/1500 symbolisch über S7CommPlus, Allen-Bradley Logix über
EtherNet/IP, Modbus TCP – und eigene Treiber). Jede Steuerung hat einen Treiber und dessen Parameter; die Adresse
einer Variable ist ein Text, den der Treiber versteht (z. B. ``DB10.DBD4``, ``Program:Main.Temp``,
``Anlage_DB.Motor[2].Drehzahl`` oder ``40001``).

Dieses Modul enthält

* das Datenmodell:  Plc (Steuerung mit Treiber und Parametern) und Axis (Y-Achse) -> Chart (Diagramm) -> Variable,
  außerdem Block (Blocklesemodus);
* das Laden/Speichern der Konfiguration (JSON). Umgewandelte Konfigurationsdateien des S7-, CLX- und TIA-Datenloggers werden
  erkannt und übernommen (Treiber aus den Parametern der Steuerung, Adressen umgerechnet);
* die Merkhilfe für die zuletzt benutzte Konfigurationsdatei und persönliche Einstellungen.

Das Modul enthält keine Oberfläche (kein Qt) und keine Kommunikation.
"""
import colorsys
import json
import os
import re
import sys
from dataclasses import dataclass, field
from plc_i18n import N_

# Basisordner für alle Dateien, die das Programm selbst anlegt (Konfiguration, CSV, Archiv, Logo-Pfade).
def _app_dir() -> str:
    """Ordner für Konfiguration, CSV-Dateien und Archiv.

    Normalbetrieb (Python-Skripte): der Projektordner (über ``src``, in dem die Programmdateien liegen); dort
    liegen auch Sprachdateien, Icon, Logo und plctag.dll.
    Installierte Version (PyInstaller): der Programmordner ist meist schreibgeschützt
    (C:\\Program Files), daher liegen die Daten unter %APPDATA%\\PLCDatenlogger. Eine Datei
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
        path = os.path.join(root, "PLCDatenlogger")
        os.makedirs(path, exist_ok=True)
        return path
    # Entwicklungsbetrieb (python src/plc_logger.py): der Projektordner über src, sonst der Ordner dieser Datei.
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here) if os.path.basename(here).lower() == "src" else here


# Wird beim Import einmalig berechnet; alle relativen Pfade der Konfiguration beziehen sich darauf.
BASE_DIR = _app_dir()
# Standardname der Konfigurationsdatei (das Konfigurationsprogramm kann auch andere Dateien laden).
CONFIG_FILE = os.path.join(BASE_DIR, "plc_config.json")

# Programmname und Version (Startbild, Info-Dialog, Fenstertitel).
APP_NAME = "PLC Datenlogger"
APP_VERSION = "3.3.2"
# Programmdateien der installierten Windows-Version.
LOGGER_EXE, CONFIG_EXE, IOCHECK_EXE = "PLCLogger.exe", "PLCKonfiguration.exe", "PLCIOCheck.exe"
# Persönliche Einstellungen (Sprache, Startbild, zuletzt benutzte Konfigurationen) – JSON im Datenordner.
SETTINGS_FILE = os.path.join(BASE_DIR, "plc_einstellungen.json")


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
    """Befehlszeile, um den Logger (kind="logger"), das Konfigurationsprogramm (kind="config") oder den IO-Check
    (kind="iocheck") zu starten.

    Windows-Installation: die .exe-Dateien liegen nebeneinander. Linux (AppImage bzw. PyInstaller-Ordner): eine
    einzige Programmdatei, Konfigurationsprogramm und IO-Check starten mit ``--konfig`` bzw. ``--iocheck``.
    Python-Skripte: dieselbe Python-Installation."""
    args = [str(a) for a in args if a]
    switch = {"config": ["--konfig"], "iocheck": ["--iocheck"]}.get(kind, [])
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            exe = {"config": CONFIG_EXE, "iocheck": IOCHECK_EXE}.get(kind, LOGGER_EXE)
            return [os.path.join(os.path.dirname(sys.executable), exe)] + args
        prog = os.environ.get("APPIMAGE") or sys.executable
        return [prog] + switch + args
    here = os.path.dirname(os.path.abspath(__file__))
    if kind == "config":
        return [sys.executable, os.path.join(here, "plc_config.py")] + args
    return [sys.executable, os.path.join(here, "plc_logger.py")] + (switch if kind == "iocheck" else []) + args


def qt_platform_setup():
    """Vor dem Anlegen der QApplication aufrufen: unter Linux mit Wayland Qt über XWayland (``xcb``) starten.

    Unter Wayland verschiebt Qt angedockte Fenster (QDockWidget) über eine Drag-and-Drop-Schleife; beim Ziehen eines
    Diagramm- oder Wertefensters stürzte das Programm dabei ab (Qt/Wayland, Speicherfehler beim Freigeben). Über
    XWayland gibt es diesen Weg nicht, und Fenster lassen sich frei positionieren. Ein selbst gesetztes
    ``QT_QPA_PLATFORM`` gilt weiter; ``PLC_WAYLAND=1`` erzwingt Wayland. Ohne XWayland (``DISPLAY`` leer) bleibt es bei
    Wayland – dann sperrt ``dock_features`` das Verschieben der Docks."""
    if not sys.platform.startswith("linux") or os.environ.get("QT_QPA_PLATFORM"):
        return
    wayland = bool(os.environ.get("WAYLAND_DISPLAY")) or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    if wayland and os.environ.get("DISPLAY") and os.environ.get("PLC_WAYLAND", "") != "1":
        os.environ["QT_QPA_PLATFORM"] = "xcb"


def child_env() -> dict:
    """Umgebung für ein neu gestartetes Programm (Logger, Konfiguration, IO-Check aus einem anderen heraus).

    Die PyInstaller-Programmdatei (auch im AppImage) setzt für den eigenen Prozess Variablen wie ``_PYI_…``,
    ``LD_LIBRARY_PATH`` oder Qt-Pfade. Erbt ein zweites Programm sie, hält es sich für einen Teilprozess des ersten
    bzw. lädt dessen Bibliotheken – unter Linux startet es dann oft gar nicht. Deshalb: ursprüngliche Werte
    wiederherstellen und den Neustart als eigenständiges Programm anfordern (``PYINSTALLER_RESET_ENVIRONMENT``)."""
    env = dict(os.environ)
    if getattr(sys, "frozen", False):
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        for key in [k for k in env if k.startswith("_PYI_") or k == "_MEIPASS2"]:
            env.pop(key)
        for key in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
            orig = env.pop(key + "_ORIG", None)
            if orig is not None:
                env[key] = orig
            elif sys.platform != "win32":
                env.pop(key, None)
        for key in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "PYTHONHOME", "PYTHONPATH"):
            env.pop(key, None)
    return env


def recent_iochecks(limit: int = 10) -> list:
    """Zuletzt benutzte IO-Check-Prüfstände (*.iocheck.json, neueste zuerst, nur vorhandene)."""
    out = []
    for p in load_settings().get("iocheck_zuletzt", []):
        if isinstance(p, str) and os.path.exists(p) and p not in out:
            out.append(p)
    return out[:limit]


def remember_iocheck(path: str):
    """Prüfstand für das Startbild des IO-Checks merken."""
    p = os.path.abspath(path)
    save_settings(iocheck_zuletzt=([p] + [x for x in load_settings().get("iocheck_zuletzt", []) if x != p])[:15])


def templates_dir() -> str:
    """Ordner ``vorlagen`` mit den SPS-Bausteinen für Ringpuffer: beim Entwickeln im Projektordner, im installierten
    Programm neben den Programmdateien (bzw. in den mitgelieferten Daten von PyInstaller)."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [os.path.join(os.path.dirname(sys.executable), "vorlagen")] if getattr(sys, "frozen", False) else []
    if getattr(sys, "_MEIPASS", None):
        candidates.append(os.path.join(sys._MEIPASS, "vorlagen"))
    candidates += [os.path.join(os.path.dirname(here), "vorlagen"), os.path.join(here, "vorlagen")]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return candidates[0]

# Alle Datentypen, die der Logger kennt (Größe in Bytes). Welche davon eine Steuerung liefern kann, legt ihr Treiber
# fest (Driver.types).
TYPES = {
    "BOOL": 1, "BYTE": 1, "WORD": 2, "DWORD": 4, "LWORD": 8,
    "SINT": 1, "INT": 2, "DINT": 4, "LINT": 8,
    "USINT": 1, "UINT": 2, "UDINT": 4, "ULINT": 8,
    "REAL": 4, "LREAL": 8,
    "TIME": 4, "LTIME": 8, "S5TIME": 2, "CHAR": 1, "WCHAR": 2,
}

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
DEFAULT_DRIVER = "s7"


def get_driver(ident):
    """Treiber zu einem Kürzel (aus plc_treiber; hier, damit das Datenmodell ohne Zirkelimport auskommt)."""
    from plc_treiber import get_driver as _get
    return _get(ident)


# ---------------------------------------------------------------------------------------
# Datenmodell: Diagramm -> Y-Achse(n) -> Variable(n)
# ---------------------------------------------------------------------------------------
@dataclass
class Plc:
    """Eine Steuerung, aus der gelesen wird. Jede Steuerung bekommt einen eigenen Lese-Thread und ein eigenes
    Abtastintervall; Variablen verweisen über ihren Index (``Variable.plc``) darauf.

    driver: Kürzel des Treibers (z. B. "s7", "tia", "clx", "modbus"); params: dessen Verbindungsparameter
    (z. B. ip, rack, slot). Parameter lassen sich auch als Attribut lesen (``plc.ip``)."""
    name: str = "SPS 1"           # frei wählbarer Name (Anzeige, Status-LED)
    driver: str = DEFAULT_DRIVER
    params: dict = field(default_factory=dict)
    intervall_ms: int = 200       # Abtastzeit dieser Steuerung in Millisekunden
    enabled: bool = True          # False: Steuerung wird nicht gelesen (ihre Variablen bleiben ohne Wert)

    def __post_init__(self):
        """Ohne Parameter (neue Steuerung) die Vorgabewerte des Treibers eintragen, z. B. IP, Rack und Slot."""
        if not self.params:
            try:
                self.params = get_driver(self.driver).default_params()
            except Exception:
                self.params = {}

    def __getattr__(self, name):
        """Fehlendes Attribut als Treiberparameter lesen: ``plc.ip`` liefert ``plc.params["ip"]``.

        Wird nur aufgerufen, wenn das normale Attribut nicht existiert. ``params`` und Doppelunterstrich-Namen sind
        ausgenommen, sonst entstünde beim Kopieren/Unpickeln (``__setstate__``) eine Endlosschleife.
        """
        # Nur für fehlende Attribute: Treiberparameter (plc.ip, plc.rack …) – für Leser und Anzeigen.
        if name in ("params", "__setstate__") or name.startswith("__"):
            raise AttributeError(name)
        params = self.__dict__.get("params") or {}
        if name in params:
            return params[name]
        raise AttributeError(name)

    def summary(self) -> str:
        """Kurzbeschreibung der Verbindung (vom Treiber), z. B. "192.168.0.1, Rack 0/Slot 1"."""
        try:
            return get_driver(self.driver).summary(self)
        except Exception:
            return str(self.params.get("ip", ""))


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

    Normale Variable: ``address`` ist die Adresse in der Schreibweise des Treibers ihrer Steuerung (z. B.
    ``DB10.DBD4``, ``Program:Main.Druck``, ``40001``), ``dtype`` der Datentyp. Berechnete Variable: formula ist nicht
    leer, die Adresse ist ohne Bedeutung. Block-Element: block/block_idx sind gesetzt; das Element wird zusammen mit
    seinem Block gelesen.
    """
    name: str
    address: str = ""
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
    # Element eines Ringpuffers: der Block (Block mit ring > 0). Solche Variablen liest der Treiber nicht im Takt,
    # sondern holt die in der Steuerung gesammelten Datensätze ab (siehe plc_treiber/ringbuffer.py).
    ring: object = field(default=None, repr=False, compare=False)

    @property
    def tag(self) -> str:
        """Gleichbedeutend mit address (Schreibweise der Tag-basierten Treiber)."""
        return self.address


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
    """Blocklesemodus: zusammenhängende Werte gleichen Formats, die gemeinsam (meist mit EINER Anfrage) gelesen
    werden. Jedes Element wird zu einer Variable ``<Name>[i]``.

    address: Startadresse (adressbasierte Treiber, z. B. ``DB10.DBD0``, ``40001``) bzw. Name des Arrays ohne Index
    (Tag-basierte Treiber, z. B. ``Messwerte``); start: erster Array-Index (nur Tag-basierte Treiber).

    ring > 0: **Ringpuffer** mit so vielen Datensätzen (zyklussynchrone Aufzeichnung, Treiber s7, tia, clx). Die
    Steuerung sammelt je Zyklus einen Datensatz mit ``count`` Werten; ``address`` ist dann die Adresse des Zählers am
    Anfang des Puffers (S7/TIA, z. B. ``DB100.DBX0.0``) bzw. der Tag des Puffers (Logix, z. B. ``Puffer``). Aufbau siehe
    ``plc_treiber/ringbuffer.py``."""
    name: str = "Block1"
    address: str = ""
    start: int = 0
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
    driver: str = DEFAULT_DRIVER                # Treiber der Steuerung (bestimmt die Elementadressen)
    ring: int = 0                               # > 0: Ringpuffer mit so vielen Datensätzen (0 = normaler Block)

    def size_bytes(self) -> int:
        """Größe des Blocks in Bytes (Anzahl × Größe des Datentyps; Ringpuffer: Zähler + alle Datensätze)."""
        if self.ring:
            rec = 8 + self.count * TYPES.get(self.dtype, 4)
            return 4 + self.ring * (rec + (rec & 1))
        return self.count * TYPES.get(self.dtype, 4)

    def element_address(self, i: int) -> str:
        """Adresse des i-ten Elements in der Schreibweise des Treibers (z. B. ``DB10.DBD8`` oder ``Messwerte[2]``).

        Die Berechnung übernimmt der Treiber (Byte-Abstände bzw. Array-Index); ist er nicht verfügbar, wird die
        Tag-Schreibweise ``Adresse[Index]`` angenommen. Ringpuffer: ``<Adresse> › Werte[i]`` (nur zur Anzeige).
        """
        if self.ring:
            return f"{self.address} › Werte[{i}]"
        try:
            return get_driver(self.driver).block_element_address(self, i)
        except Exception:
            return f"{self.address}[{self.start + i}]"

    # Erzeugt aus dem Block die einzelnen Variablen ('Name[0]' ... 'Name[n-1]' oder eigene Namen).
    def variables(self) -> list:
        """Die Elemente des Blocks als einzelne Variablen (``Name[0]`` … ``Name[n-1]`` oder eigene Namen).

        Jedes Element bekommt eine eigene, aus der Blockfarbe abgeleitete Farbe (siehe ``_shade``) und merkt sich in
        ``block``/``block_idx``, zu welchem Block es gehört – der Recorder liest so alle Elemente mit einer Anfrage.
        """
        out = []
        for i in range(self.count):
            # Einzelne Elemente dürfen in einem ANDEREN Diagramm/auf einer anderen Y-Achse liegen als der Rest
            # des Blocks (self.targets); gelesen werden sie trotzdem gemeinsam.
            chart, axis = self.targets.get(i, (self.chart, self.axis))
            out.append(Variable(
                name=self.names.get(i) or f"{self.name}[{i}]", address=self.element_address(i),
                dtype=self.dtype, color=_shade(self.color, i), show_value=self.show_value,
                chart=chart, axis=axis, bar=self.bar, block=self.name, block_idx=i, plc=self.plc,
                ring=self if self.ring else None))
        return out

    def address_range(self) -> str:
        """Bereich als Text, z. B. 'DB10.DBD0 … DB10.DBD36' oder 'Messwerte[0] … Messwerte[9]'."""
        if self.ring:
            from plc_i18n import tr
            return tr("{0}: Ringpuffer {1} × {2} Werte").format(self.address, self.ring, self.count)
        if self.count <= 1:
            return self.element_address(0)
        return f"{self.element_address(0)} … {self.element_address(self.count - 1)}"


# ---------------------------------------------------------------------------------------
# Konfigurationsdatei im JSON-Format
# ---------------------------------------------------------------------------------------
# Auf der Platte steht die Konfiguration als verschachteltes JSON (Listen für Steuerungen, Diagramme mit Achsen,
# Variablen, Blöcke und Trigger; Zahlen und Wahrheitswerte mit echtem Typ). Intern arbeitet das Programm weiter mit
# Abschnitten und Schlüsseln (ConfigParser) – die Umwandlung übernehmen read_config_store()/write_config_store().
# Ältere INI-Dateien werden nicht mehr gelesen; convert_ini() wandelt sie einmalig um (Konfigurationsprogramm:
# Datei › INI-Datei umwandeln …, oder tools/ini2json.py).
CONFIG_EXT = ".json"
CONFIG_FORMAT = "PLC Datenlogger Konfiguration"
CONFIG_VERSION = 1

# Nummerierte Abschnitte: (JSON-Schlüssel, Zählabschnitt, Präfix der Einzelabschnitte)
_GROUPS = (("steuerungen", "Steuerungen", "Steuerung"), ("diagramme", "Diagramme", "Diagramm"),
           ("variablen", "Variablen", "Var"), ("bloecke", "Bloecke", "Block"), ("trigger", "Trigger", "Trigger"))
# Schlüssel mit festem Typ in der JSON-Datei (alle übrigen bleiben Text)
_BOOL_KEYS = {"aktiv", "auto", "y_auto", "wert_anzeigen", "balken", "pid_aktiv", "gehen", "quittieren",
              "web_aktiv", "web_https", "headless", "csv_aktiv", "bericht_aktiv", "archiv_beenden", "db_nur_aenderungen"}
_INT_KEYS = {"intervall_ms", "timeout_ms", "diagramm", "achse", "steuerung", "start", "fenster_s", "max_records",
             "raster_spalten", "web_port", "web_intervall_ms", "db_port", "rack", "slot", "port", "unit",
             "max_register", "luecke", "tags_je_anfrage", "db", "byte", "bit", "anzahl", "puffer"}
_FLOAT_KEYS = {"y_min", "y_max", "verzoegerung_s", "amplitude", "aufz_vorlauf_s", "aufz_nachlauf_s", "aufz_max_s"}
_JSON_KEYS = {"treiberdaten", "web_benutzer", "benachrichtigung", "opcua_server"}                  # Text mit JSON-Inhalt -> verschachteltes Objekt


class ConfigFormatError(ValueError):
    """Die Datei ist keine Konfiguration im JSON-Format (z. B. eine ältere INI-Datei)."""


def _new_cp():
    """Leere interne Darstellung der Konfiguration (ConfigParser ohne %-Platzhalter, damit Formeln mit ``%`` erhalten
    bleiben).
    """
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
    """Einen Abschnitt (Schlüssel -> Text) in ein JSON-Objekt mit passenden Typen umsetzen.

    Die Blockschlüssel ``elem_<i>`` (eigene Elementnamen) und ``elemziel_<i>`` (abweichendes Diagramm/Achse) werden zu
    den verschachtelten Objekten ``elementnamen`` bzw. ``elementziele`` zusammengefasst.
    """
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
    """Gegenstück zu ``_section_to_json``: JSON-Objekt -> Abschnitt mit Textwerten.

    ``elementnamen``/``elementziele`` werden wieder zu ``elem_<i>``/``elemziel_<i>``; die Achsenliste der Diagramme
    behandelt der Aufrufer (eigene Abschnitte ``DiagrammN_AchseM``).
    """
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


# Die Gruppen (Steuerungen, Diagramme, Variablen, Blöcke, Trigger) stehen intern als Zählabschnitt
# (z. B. [Variablen] anzahl=3) plus nummerierte Abschnitte ([Var1] … [Var3]); in der Datei als JSON-Liste.
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
def logo_paths(conn) -> list:
    """Kundenlogo und Logo aus der Konfiguration als Pfade (relativ = ab Datenordner); leere Angaben entfallen.

    Verwendet von Webseiten und PDF-Berichten (Reihenfolge: Kundenlogo links, Logo rechts)."""
    out = []
    for key in ("kundenlogo", "logo"):
        p = str(conn.get(key, "") or "").strip()
        if p:
            out.append(p if os.path.isabs(p) else os.path.join(BASE_DIR, p))
    return out


def default_connection() -> dict:
    """Vorgabewerte für die Verbindungs- und Anzeigeeinstellungen (Abschnitt [Verbindung])."""
    # ip/pfad/cpu/intervall_ms spiegeln die erste Steuerung; csv_*/archiv_* = CSV-Protokoll und Archivierung;
    # fenster_s = Anzeigefenster online; anordnung/balken = Darstellung; logo/kundenlogo/icon = Branding (Logo und
    # Kundenlogo erscheinen im Logger, auf den Webseiten und in den PDF-Berichten; leer = kein Logo).
    return {"csv_ordner": "logs", "fenster_s": 60,
            "anordnung": "untereinander", "balken": 1, "balken_breite": 14,
            "logo": "", "kundenlogo": "", "icon": "", "csv_name": "log", "max_records": 0,
            "archiv_ordner": "archiv",
            "projekt": "", "archiv_beenden": 1, "seite_anordnung": "", "raster_spalten": 0,
            "web_aktiv": 0, "web_host": "0.0.0.0", "web_port": 8080, "web_token": "",
            "web_intervall_ms": 1000, "headless": 0,
            # HTTPS (eigenes oder selbstsigniertes Zertifikat) und Anmeldung (JSON {Benutzer: Passwort-Hash}).
            "web_https": 0, "web_zertifikat": "", "web_schluessel": "", "web_benutzer": "",
            # Aufzeichnungsziele: CSV-Datei (abschaltbar) und optional eine Datenbank (siehe *_db.py).
            "csv_aktiv": 1, "db_typ": "", "db_host": "localhost", "db_port": 0, "db_name": "datenlogger",
            "db_user": "", "db_passwort": "", "db_tabelle": "messwerte", "db_datei": "datenlogger.db",
            "db_nur_aenderungen": 0,
            # Aufräumen alter Aufzeichnungen (siehe *_cleanup.py): Tage bzw. MB, 0 = aus.
            "aufr_csv_tage": 0, "aufr_csv_mb": 0, "aufr_db_tage": 0, "aufr_db_mb": 0,
            # Ereignisprotokoll der Trigger (leer = <CSV-Ordner>/<CSV-Name>_ereignisse.csv, siehe *_events.py).
            "ereignis_datei": "",
            # Aufzeichnung: dauernd oder nur per Trigger (Startbedingung) mit Vor- und Nachlauf (siehe *_recorder.py).
            "aufz_modus": "dauernd", "aufz_bedingung": "", "aufz_vorlauf_s": 10.0, "aufz_nachlauf_s": 10.0,
            "aufz_max_s": 0.0,
            # PDF-Berichte je Schicht/Tag/Woche/Monat (siehe *_report.py).
            "bericht_aktiv": 0, "bericht_zeitraum": "tag", "bericht_schichten": "06:00,14:00,22:00",
            "bericht_beginn": "00:00", "bericht_ordner": "berichte",
            # Benachrichtigungen bei Ereignissen (JSON, siehe *_notify.py): E-Mail, Teams/Slack, ntfy, Telegram.
            "benachrichtigung": "",
            # OPC-UA-Server im Logger (JSON, siehe *_opcua_server.py): stellt die Variablen anderen Systemen bereit.
            "opcua_server": "",
            # Treibereigene Werte (JSON {Treiber: {Schlüssel: Wert}}), z. B. die importierten DB-Quellen des S7-Treibers.
            "treiberdaten": ""}


# Welche Schlüssel des Abschnitts [Verbindung] Zahlen bzw. Text sind (zum Lesen mit passendem Typ).
CONN_INT_KEYS = ("fenster_s", "balken", "balken_breite", "max_records", "archiv_beenden",
                 "raster_spalten", "web_aktiv", "web_port", "web_intervall_ms", "headless", "web_https",
                 "csv_aktiv", "db_port", "db_nur_aenderungen", "bericht_aktiv",
                 "aufr_csv_tage", "aufr_csv_mb", "aufr_db_tage", "aufr_db_mb")
CONN_STR_KEYS = ("csv_ordner", "anordnung", "logo", "kundenlogo", "icon", "csv_name",
                 "archiv_ordner", "projekt", "seite_anordnung", "web_host", "web_token",
                 "db_typ", "db_host", "db_name", "db_user", "db_passwort", "db_tabelle", "db_datei",
                 "ereignis_datei", "treiberdaten", "aufz_modus", "aufz_bedingung",
                 "web_zertifikat", "web_schluessel", "web_benutzer",
                 "bericht_zeitraum", "bericht_schichten", "bericht_beginn", "bericht_ordner", "benachrichtigung",
                 "opcua_server")
CONN_FLOAT_KEYS = ("aufz_vorlauf_s", "aufz_nachlauf_s", "aufz_max_s")
RECORD_MODES = {"dauernd": N_("Dauernd"), "trigger": N_("Per Trigger mit Vor- und Nachlauf")}


# Kennzeichen der Konfigurationsdateien der Einzelprogramme: Parameter der Steuerung -> Treiber.
_GUESS = (("rack", "s7"), ("slot", "s7"), ("pfad", "clx"), ("cpu", "clx"), ("tls", "tia"), ("rolle", "tia"),
          ("port", "tia"))
_PLC_KEYS = ("name", "treiber", "intervall_ms", "aktiv")


# Die Einzelprogramme (S7-, CLX-, TIA-Datenlogger) kannten noch keinen Eintrag 'treiber'. Ihre Dateien werden
# an typischen Parametern erkannt, z. B. 'rack'/'slot' = Siemens S7, 'pfad'/'cpu' = Allen-Bradley Logix.
def guess_driver(section) -> str:
    """Treiber einer Steuerung: Eintrag 'treiber', sonst aus den vorhandenen Parametern erraten (Dateien des S7-,
    CLX- bzw. TIA-Datenloggers)."""
    d = (section.get("treiber", "") or "").strip()
    if d:
        return d
    keys = set(section.keys())
    for key, drv in _GUESS:
        if key in keys:
            return drv
    return DEFAULT_DRIVER


def _plc_from(section, name, default_interval=200):
    """Eine Steuerung aus einem Abschnitt der Konfiguration erzeugen.

    Allgemeine Schlüssel (Name, Treiber, Intervall, aktiv) gehören zur Steuerung, alle übrigen sind Treiberparameter;
    der Treiber bringt sie in seine Form (``normalize_params``: Typen, alte Schlüsselnamen). Das Intervall ist
    mindestens 10 ms.
    """
    drv_id = guess_driver(section)
    raw = {k: v for k, v in section.items() if k not in _PLC_KEYS}
    try:
        params = get_driver(drv_id).normalize_params(raw)
    except Exception:
        params = dict(raw)
    return Plc(name=section.get("name", name) or name, driver=drv_id, params=params,
               intervall_ms=max(10, int(float(section.get("intervall_ms", default_interval) or default_interval))),
               enabled=str(section.get("aktiv", "1")).strip().lower() not in ("0", "false", "nein", "no"))


def _parse_plcs(cp, conn):
    """Steuerungen aus [Steuerungen]/[SteuerungN] lesen. Ohne diese Abschnitte (sehr alte Dateien) entsteht aus
    [Verbindung] genau eine Steuerung."""
    plcs = []
    for i in range(1, cp.getint("Steuerungen", "anzahl", fallback=0) + 1):
        sec = f"Steuerung{i}"
        if cp.has_section(sec):
            plcs.append(_plc_from(cp[sec], f"SPS {i}"))
    if not plcs:
        if cp.has_section("Verbindung") and any(k in cp["Verbindung"] for k in ("ip", "rack", "pfad", "port")):
            plcs = [_plc_from(cp["Verbindung"], "SPS 1")]
            plcs[0].name = "SPS 1"
        else:
            plcs = [Plc()]
    return plcs


def load_plcs(path: str = None) -> list:
    """Nur die Steuerungen einer Konfigurationsdatei (für das Konfigurationsprogramm)."""
    path = path or CONFIG_FILE
    cp = read_config_store(path)
    return _parse_plcs(cp, default_connection())


def s7_address(area, db, byte, bit, dtype) -> str:
    """Adresse in Siemens-Schreibweise aus den Feldern des S7-Datenloggers (Bereich/DB/Byte/Bit)."""
    suffix = {"BOOL": "X", "BYTE": "B", "SINT": "B", "USINT": "B", "CHAR": "B", "INT": "W", "WORD": "W",
              "UINT": "W", "DINT": "D", "DWORD": "D", "UDINT": "D", "REAL": "D", "TIME": "D",
              "LREAL": "D", "LINT": "D", "ULINT": "D", "LWORD": "D"}.get(dtype, "B")
    bit_txt = f".{bit}" if dtype == "BOOL" else ""
    if area == "DB":
        return f"DB{db}.DB{suffix}{byte}{bit_txt}"
    return f"{area}{suffix if dtype != 'BOOL' else ''}{byte}{bit_txt}"


def _address_from(section, dtype):
    """Adresse einer Variable aus der Konfiguration: 'adresse' (neu), 'tag' (CLX/TIA) oder bereich/db/byte/bit (S7)."""
    for key in ("adresse", "tag"):
        if section.get(key, "").strip():
            return section.get(key).strip()
    if "bereich" in section:
        try:
            return s7_address(section.get("bereich", "DB"), int(section.get("db", 1)),
                              int(section.get("byte", section.get("start", 0))), int(section.get("bit", 0)), dtype)
        except ValueError:
            return ""
    return ""


# ---------------------------------------------------------------------------------------
# Zuletzt benutzte Konfigurationsdatei
# ---------------------------------------------------------------------------------------
# Logger und Konfigurationsprogramm sollen ohne Parameter dieselbe Datei öffnen. Der Pfad der zuletzt
# benutzten Datei steht in einer kleinen Textdatei im Basisordner.
LAST_FILE = os.path.join(BASE_DIR, "plc_last.txt")


def last_config_path() -> str:
    """Pfad der zuletzt benutzten Konfigurationsdatei (Standard: plc_config.json im Basisordner)."""
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


def _parse_blocks(cp, charts, n_plc=1, plc_drivers=()):
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
        plc = min(max(s.getint("steuerung", 1) - 1, 0), max(n_plc - 1, 0))
        drv = plc_drivers[plc] if plc < len(plc_drivers) else DEFAULT_DRIVER
        old_s7 = "bereich" in s and not s.get("adresse", "").strip()
        ring = max(0, min(s.getint("puffer", 0), 100_000))           # Ringpuffer: Anzahl Datensätze (0 = Block)
        blocks.append(Block(
            ring=ring,
            name=s.get("name", f"Block{i}"), address=_address_from(s, dtype),
            start=0 if old_s7 else max(0, s.getint("start", 0)), dtype=dtype, driver=drv,
            plc=plc, targets=targets,
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
    plcs = _parse_plcs(cp, default_connection())
    return _parse_blocks(cp, charts, len(plcs), [p.driver for p in plcs])


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
        for key in CONN_FLOAT_KEYS:
            conn[key] = max(0.0, s.getfloat(key, conn[key]))
        if conn["aufz_modus"] not in RECORD_MODES:
            conn["aufz_modus"] = "dauernd"
        # S7-Datenlogger: importierte DB-Quellen in die Treiberdaten des Treibers "s7" übernehmen.
        if s.get("symbolquellen", "").strip() and not conn["treiberdaten"].strip():
            import json
            conn["treiberdaten"] = json.dumps({"s7": {"symbolquellen": s.get("symbolquellen")}}, ensure_ascii=False)
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
        dtype = s.get("typ", "REAL").upper() if s.get("typ", "REAL").upper() in TYPES else "REAL"
        variables.append(Variable(
            name=s.get("name", sec),
            address=_address_from(s, dtype),
            dtype=dtype,
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
    for blk in _parse_blocks(cp, charts, len(plcs), [p.driver for p in plcs]):   # Block-Elemente anhängen
        variables.extend(blk.variables())
    return conn, charts, variables


def save_config(conn: dict, charts, variables, path: str = None, blocks=(), plcs=None):
    """Konfiguration in die Datei (JSON) schreiben.

    conn: Verbindungs-/Anzeigeeinstellungen, charts: Diagramme mit Achsen, variables: normale und
    berechnete Variablen, blocks: Blockdefinitionen (deren Elemente werden nicht einzeln gespeichert),
    plcs: Steuerungen (ohne Angabe wird eine Steuerung aus conn ip/pfad/cpu/intervall_ms erzeugt).
    """
    path = path or CONFIG_FILE
    if not plcs:
        plcs = [Plc()]
    # Die Felder der ersten Steuerung (ip, rack …) stehen bei den Steuerungen, nicht mehr bei den Einstellungen.
    conn = {k: v for k, v in conn.items() if k not in ("ip", "pfad", "cpu", "rack", "slot", "port", "intervall_ms")}
    # Block-Elemente nie als einzelne [VarN] speichern - sie entstehen beim Laden aus [BlockN].
    variables = [v for v in variables if not v.block]
    cp = _new_cp()
    # Interne Darstellung aufbauen: jeder Abschnitt ist ein Wörterbuch Schlüssel -> Text (Zahlen 1-basiert).
    cp["Verbindung"] = {k: str(v) for k, v in conn.items()}
    cp["Steuerungen"] = {"anzahl": str(len(plcs))}
    for i, p in enumerate(plcs, 1):
        sec = {"name": p.name, "treiber": p.driver, "intervall_ms": str(p.intervall_ms),
               "aktiv": "1" if p.enabled else "0"}
        try:
            kinds = {pp.key: pp for pp in get_driver(p.driver).params}
        except Exception:
            kinds = {}
        for k, v in p.params.items():
            if k not in sec:
                sec[k] = kinds[k].to_text(v) if k in kinds else str(v)
        cp[f"Steuerung{i}"] = sec
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
            "name": v.name, "adresse": v.address, "typ": v.dtype,
            "farbe": v.color, "wert_anzeigen": "1" if v.show_value else "0",
            "diagramm": str(v.chart + 1), "achse": str(v.axis + 1),
            "balken": "1" if v.bar else "0",
            "formel": " ".join(v.formula.split()),
            "steuerung": str(v.plc + 1),
        }
    cp["Bloecke"] = {"anzahl": str(len(blocks))}
    for i, b in enumerate(blocks, 1):
        cp[f"Block{i}"] = {
            "name": b.name, "adresse": b.address, "start": str(b.start), "typ": b.dtype, "anzahl": str(b.count),
            "diagramm": str(b.chart + 1), "achse": str(b.axis + 1), "farbe": b.color,
            "wert_anzeigen": "1" if b.show_value else "0", "balken": "1" if b.bar else "0",
            "steuerung": str(b.plc + 1)}
        if b.ring:
            cp[f"Block{i}"]["puffer"] = str(b.ring)
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


def driver_store(conn: dict) -> dict:
    """Treibereigene Werte aus der Konfiguration -> {Treiber: {Schlüssel: Wert}}."""
    import json
    try:
        data = json.loads(conn.get("treiberdaten") or "{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}
