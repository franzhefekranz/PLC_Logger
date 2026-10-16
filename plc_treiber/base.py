"""Schnittstelle der Steuerungstreiber (ohne Oberfläche).

Jeder Treiber beschreibt eine Steuerungsfamilie bzw. ein Protokoll: welche Verbindungsparameter es gibt, wie
Variablen adressiert werden, welche Datentypen lesbar sind, und er liefert den Leser (``Reader``), der im Lese-Thread
des Loggers zyklisch alle Variablen einer Steuerung liest. Optional bietet er einen Auswahldialog für Variablen aus
der Steuerung (``browse``).

Eigener Treiber (Kurzfassung, ausführlich in der Bedienungsanleitung, Kapitel „Treiber entwickeln“):

    from plc_treiber.base import Driver, Param, Reader

    class MeinReader(Reader):
        def connect(self):              # Verbindung aufbauen -> Anzahl lesbarer Variablen
            ...
        def read(self):                 # ein Messzyklus -> Liste von float (NaN = kein Wert)
            ...
        def close(self):
            ...

    class MeinTreiber(Driver):
        id = "mein"                      # eindeutiges Kürzel (steht in der Konfigurationsdatei)
        name = "Meine Steuerung"
        params = [Param("ip", "IP-Adresse", "text", "192.168.0.10")]
        types = ["BOOL", "INT", "REAL"]
        def create_reader(self, plc, variables):
            return MeinReader(self, plc, variables)

    DRIVER = MeinTreiber()

Die Datei kommt in den Ordner ``treiber`` im Datenordner des Programms (oder in das Paket ``plc_treiber``); sie wird
beim Start automatisch geladen und erscheint in der Auswahl „Treiber“ der Steuerungen.
"""
from dataclasses import dataclass, field

from plc_i18n import tr

NAN = float("nan")

# Alle Datentypen, die der Logger kennt (ein Treiber unterstützt eine Auswahl davon). Die Größe in Bytes dient nur
# Anzeigen (z. B. Blockgröße); gelesen und dekodiert wird im Treiber.
TYPE_SIZES = {
    "BOOL": 1, "BYTE": 1, "WORD": 2, "DWORD": 4, "LWORD": 8,
    "SINT": 1, "INT": 2, "DINT": 4, "LINT": 8,
    "USINT": 1, "UINT": 2, "UDINT": 4, "ULINT": 8,
    "REAL": 4, "LREAL": 8,
    "TIME": 4, "LTIME": 8, "S5TIME": 2, "CHAR": 1, "WCHAR": 2,
}
FLOAT_TYPES = ("REAL", "LREAL")


@dataclass
class Param:
    """Ein Verbindungsparameter einer Steuerung (wird im Konfigurationsprogramm als Eingabefeld gezeigt).

    kind: "text" | "int" | "float" | "choice" | "password" | "bool". choices: [(Wert, Anzeigetext)] bei "choice".
    advanced: nur im Bereich „Erweitert“ des Einstellungsdialogs zeigen."""
    key: str
    label: str
    kind: str = "text"
    default: object = ""
    choices: list = field(default_factory=list)
    tip: str = ""
    minimum: float = 0
    maximum: float = 1_000_000
    advanced: bool = False
    suffix: str = ""

    def convert(self, value):
        """Wert aus der INI-Datei (Text) in den passenden Typ umwandeln; ungültig -> Vorgabe."""
        try:
            if self.kind == "int":
                return int(min(max(int(float(value)), self.minimum), self.maximum))
            if self.kind == "float":
                return float(min(max(float(value), self.minimum), self.maximum))
            if self.kind == "bool":
                return str(value).strip().lower() in ("1", "true", "ja", "yes", "on")
            if self.kind == "choice":
                keys = [c[0] for c in self.choices]
                return value if value in keys else self.default
            return "" if value is None else str(value)
        except (TypeError, ValueError):
            return self.default

    def to_text(self, value):
        if self.kind == "bool":
            return "1" if value else "0"
        return str(value)


class Reader:
    """Liest die Variablen EINER Steuerung (ein Objekt je Lese-Thread; muss nicht thread-sicher sein).

    variables: Liste von Variablen (ohne berechnete) mit ``address``, ``dtype``, ``block``, ``block_idx``, ``name``.
    ``read()`` liefert die Werte in derselben Reihenfolge (float, NaN = nicht lesbar). Fehler einzelner Variablen
    stehen in ``errors`` ({Adresse: Text}) und stören die übrigen nicht. Ist die Verbindung gestört, lösen
    ``connect()``/``read()`` eine Ausnahme aus (z. B. ConnectionError); der Lese-Thread verbindet dann neu."""

    def __init__(self, driver, plc, variables):
        self.driver, self.plc, self.vars = driver, plc, list(variables)
        self.errors = {}

    def connect(self) -> int:
        """Verbindung aufbauen und prüfen. Rückgabe: Anzahl der lesbaren Variablen."""
        raise NotImplementedError

    def read(self) -> list:
        raise NotImplementedError

    def close(self):
        pass


class Driver:
    """Basisklasse aller Treiber. Unterklassen überschreiben die Attribute und mindestens ``create_reader``."""
    id = "basis"
    name = "Treiber"
    description = ""
    params = []                 # Liste von Param
    types = ["BOOL", "INT", "DINT", "REAL"]
    block_types = None          # Formate für Blöcke (None = wie types)
    default_type = "REAL"
    address_label = "Adresse"   # Spaltenüberschrift für die Adresse (z. B. "Tag-Name")
    address_hint = ""           # Tooltip/Platzhalter für die Adresse einer Variable
    block_hint = ""             # Tooltip für die Startadresse eines Blocks
    block_uses_index = False    # True: Block = Array-Name + erster Index (sonst: Startadresse + Elementgröße)
    browse_label = ""           # Text des Knopfs „Aus Steuerung wählen …“ (leer = kein Auswahldialog)
    library = ""                # benötigte Bibliothek (für Hinweise, z. B. "python-snap7")

    # ------------------------------------------------------------------ Parameter
    def default_params(self) -> dict:
        return {p.key: p.default for p in self.params}

    def normalize_params(self, raw: dict) -> dict:
        """Parameter aus der Datei (Text) -> vollständiges Dict mit passenden Typen und Vorgaben."""
        out = self.default_params()
        for p in self.params:
            if p.key in raw and raw[p.key] is not None:
                out[p.key] = p.convert(raw[p.key])
        return out

    def summary(self, plc) -> str:
        """Kurzbeschreibung der Verbindung für Tabellen und Meldungen, z. B. "192.168.0.1, Rack 0/Slot 1"."""
        return str(plc.params.get("ip", "")) or self.name

    def check_params(self, params: dict) -> str:
        """Fehlertext für ungültige Parameter oder ""."""
        if "ip" in params and not str(params.get("ip", "")).strip():
            return tr("IP-Adresse fehlt")
        return ""

    # ------------------------------------------------------------------ Adressen
    def check_address(self, address: str, dtype: str) -> str:
        """Fehlertext für eine ungültige Adresse (formale Prüfung) oder ""."""
        return "" if address.strip() else tr("Adresse fehlt")

    def normalize_address(self, address: str, dtype: str) -> str:
        """Adresse in einheitlicher Schreibweise (Standard: unverändert ohne Leerzeichen am Rand)."""
        return address.strip()

    def block_element_address(self, block, i: int) -> str:
        """Adresse des i-ten Elements eines Blocks."""
        if self.block_uses_index:
            return f"{block.address}[{block.start + i}]"
        return f"{block.address}+{i}"

    def check_block(self, block) -> str:
        """Fehlertext für einen ungültigen Block oder ""."""
        if not block.address.strip():
            return tr("Startadresse fehlt")
        if block.dtype not in (self.block_types or self.types):
            return tr("Format {0} wird für Blöcke nicht unterstützt").format(block.dtype)
        return ""

    def type_size(self, dtype: str) -> int:
        return TYPE_SIZES.get(dtype, 4)

    # ------------------------------------------------------------------ Lesen
    def check_library(self):
        """Prüft, ob die benötigte Bibliothek vorhanden ist (löst sonst ImportError/OSError mit Hinweis aus)."""
        return True

    def create_reader(self, plc, variables) -> Reader:
        raise NotImplementedError

    def read_once(self, plc, variables):
        """Variablen einmal lesen (Verbindungstest). Rückgabe: (Werte, Fehler je Adresse).

        Löst eine Ausnahme aus, wenn die Steuerung nicht erreichbar ist."""
        r = self.create_reader(plc, variables)
        try:
            r.connect()
            values = r.read()
            return values, dict(r.errors)
        finally:
            r.close()

    # ------------------------------------------------------------------ Auswahldialog (optional, mit Qt)
    def browse(self, parent, ctx):
        """Variablen aus der Steuerung auswählen. ctx: BrowseContext. Rückgabe: BrowseResult oder None."""
        return None


@dataclass
class BrowseContext:
    """Angaben für den Auswahldialog eines Treibers."""
    plc: object                         # Steuerung (Plc)
    existing: set                       # bereits vorhandene Adressen (normalisiert) dieser Steuerung
    target_labels: list                 # Texte "Diagramm › Y-Achse"
    default_target: int = 0
    store: dict = field(default_factory=dict)   # treibereigene, in der Konfiguration gespeicherte Werte


@dataclass
class BrowseResult:
    """Ergebnis eines Auswahldialogs."""
    variables: list = field(default_factory=list)   # [(Namensvorschlag, Adresse, Typ)]
    blocks: list = field(default_factory=list)      # [(Namensvorschlag, Startadresse/Array, erster Index, Anzahl, Typ)]
    target_index: int = 0
    store: dict = field(default_factory=dict)       # geänderte treibereigene Werte


def to_number(value) -> float:
    """Gelesenen Wert in float umwandeln (bool -> 0/1; nicht darstellbar -> NaN)."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return NAN
