# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Symbolinformation aus DB-/UDT-Quellen (TIA Portal / STEP 7).

Die klassische S7-Kommunikation (snap7) kennt keine Variablennamen - diese stehen nur im
Projekt. Dieses Modul liest daher die DB-Quellen (z. B. TIA Portal: Rechtsklick auf den
Baustein > "Quelle aus Bausteinen generieren", STEP 7: .db/.awl) und berechnet daraus die
Adressen (Byte-/Bit-Offsets) nach den Regeln für **Standard-Bausteinzugriff** (nicht optimiert).

Unterstützt: STRUCT, verschachtelte STRUCT, ARRAY (mehrdimensional), UDTs (aus derselben
oder weiteren Quelldateien), STRING/WSTRING, alle elementaren Typen.

Aufbau des Moduls (in drei Stufen)
----------------------------------
1. ``_Parser``   zerlegt den Quelltext in Tokens und erkennt DATA_BLOCK- und TYPE-Definitionen.
                 Ergebnis: Typbeschreibungen als verschachtelte Tupel, z. B.
                 ``("struct", [(name, typ), ...])``, ``("array", [(lo, hi), ...], typ)``,
                 ``("elem", "REAL")``, ``("string", "STRING", 10)``, ``("udt", "Name")``.
2. ``_Layout``   berechnet aus den Typen die Adressen (Byte/Bit) mit den S7-Ausrichtungsregeln
                 und erzeugt einen Baum aus ``SymNode``-Objekten.
3. ``Source`` / ``SymbolSet``  verwalten die importierten Dateien (Pfad, DB-Nummern) und bauen den
                 Gesamtbaum für den Dialog (s7_browser.py).

Ausrichtungsregeln (Standard-Bausteinzugriff): BOOLs sind bitweise gepackt; Elemente mit 2 und mehr
Bytes beginnen auf einer geraden Byte-Adresse; Strukturen und Arrays beginnen und enden auf einer
geraden Adresse; einzelne Bytes/Chars haben keine Ausrichtung.
"""


import itertools
import math
import re
from dataclasses import dataclass, field
from plc_i18n import tr

# Beginnt ein STRING auf beliebiger Byte-Adresse (False) oder auf einer geraden (True)?
# Die Dokumentation ist hier nicht eindeutig - bei abweichender Bausteingröße im SPS-Abgleich umstellen.
STRING_EVEN_ALIGN = False   # STRING beginnt auf beliebiger Byte-Grenze (bei Bedarf auf True setzen)
# Höchstens so viele Elemente eines Arrays werden im Baum erzeugt (größere Arrays würden die Oberfläche bremsen);
# der Rest wird nur für die Adressrechnung berücksichtigt.
ARRAY_LIMIT = 500           # max. dargestellte Array-Elemente je Array

# Größe der elementaren Typen in Bytes (Ausnahme BOOL: 1 Bit, daher 0 - wird gesondert behandelt).
# Größe in Bytes (BOOL belegt 1 Bit)
ELEM_SIZE = {
    "BOOL": 0, "BYTE": 1, "CHAR": 1, "SINT": 1, "USINT": 1,
    "WORD": 2, "INT": 2, "UINT": 2, "DATE": 2, "S5TIME": 2, "WCHAR": 2,
    "DWORD": 4, "DINT": 4, "UDINT": 4, "REAL": 4, "TIME": 4, "TIME_OF_DAY": 4, "TOD": 4,
    "LWORD": 8, "LINT": 8, "ULINT": 8, "LREAL": 8, "LTIME": 8, "LTOD": 8, "LDT": 8,
    "DATE_AND_TIME": 8, "DT": 8, "DTL": 12, "POINTER": 6, "ANY": 10,
}

# Welche Typen der Logger aufzeichnen kann: Quelltyp -> Typ in s7_common.TYPES.
# Vorzeichenlose Typen werden auf gleich große Typen abgebildet (Anzeige kann bei sehr großen Werten abweichen);
# TIME ist in der SPS eine Zahl in Millisekunden (DINT).
# Quelltyp -> Typ im Logger (nicht aufgeführte Typen sind nicht aufzeichenbar)
TYPE_MAP = {
    "BOOL": "BOOL", "BYTE": "BYTE", "USINT": "BYTE", "SINT": "SINT",
    "WORD": "WORD", "UINT": "WORD", "INT": "INT",
    "DWORD": "DWORD", "UDINT": "DWORD", "DINT": "DINT",
    "REAL": "REAL", "LREAL": "LREAL", "TIME": "DINT",
}


# Logger-Typ zu einem Quelltyp (None = nicht aufzeichenbar, z. B. STRING, DTL, DATE).
def config_type(dtype: str):
    return TYPE_MAP.get(dtype.upper())


class SymbolError(Exception):
    """Fehler beim Einlesen einer Quelle (Syntax, unbekannter Typ, ...)."""
    pass


# Ein Knoten im Symbolbaum: Datenbaustein, Struktur, Array, Variable (leaf) oder Hinweiszeile (note).
@dataclass
class SymNode:
    name: str
    kind: str                 # "db" | "struct" | "array" | "leaf" | "note"
    dtype: str = ""
    byte: int = 0
    bit: int = 0
    size: int = 0
    children: list = field(default_factory=list)
    path: str = ""
    db: int = 0
    note: str = ""
    source: object = None     # nur bei kind == "db"

    # Nur Blätter mit einem vom Logger lesbaren Typ können zur Aufzeichnung ausgewählt werden.
    @property
    def supported(self) -> bool:
        return self.kind == "leaf" and config_type(self.dtype) is not None


# Tokenizer: erkennt (in dieser Reihenfolge) Namen in Anführungszeichen, ':=', '..', Bezeichner,
# Zahlen, einzelne Satzzeichen und als Auffangnetz jedes andere Zeichen.
# ------------------------------------------------------------------ Tokenizer / Parser
_TOKEN = re.compile(r'"[^"]*"|:=|\.\.|[^\W\d][\w#]*|\d+(?:\.\d+)?|[:;\[\],()=\-]|\S')


# Entfernt Kommentare ((* *), /* */, //) und TIA-Attribute in geschweiften Klammern vor dem Zerlegen.
def _strip(text: str) -> str:
    text = re.sub(r"\(\*.*?\*\)", " ", text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    text = re.sub(r"\{[^}]*\}", " ", text)       # TIA-Attribute { ... }
    return text


# Anführungszeichen um einen Namen entfernen ("Motor" -> Motor).
def _unquote(t: str) -> str:
    return t[1:-1] if len(t) >= 2 and t[0] == t[-1] == '"' else t


# Ein gelesener Datenbaustein (noch ohne Adressen): Name, Nummer (None bei TIA-Quellen), Typbeschreibung.
@dataclass
class RawDB:
    name: str
    number: object            # int | None
    root: object              # Typbeschreibung | None
    optimized: bool = False
    error: str = ""


# Rekursiver Abstiegsparser für die Deklarationsteile von DATA_BLOCK und TYPE.
class _Parser:
    def __init__(self, text: str):
        # Tokenliste aufbauen; self.i ist die aktuelle Leseposition.
        self.toks = _TOKEN.findall(_strip(text))
        self.i = 0
        self.dbs = []
        self.udts = {}

    # Kleine Hilfsfunktionen zum Lesen der Tokens.
    # --- Hilfen
    # Nächstes Token ansehen, ohne es zu verbrauchen (None am Dateiende).
    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    # Nächstes Token verbrauchen (Fehler am Dateiende).
    def next(self):
        if self.i >= len(self.toks):
            raise SymbolError(tr("Unerwartetes Dateiende"))
        t = self.toks[self.i]
        self.i += 1
        return t

    # Verbrauchtes Token muss dem erwarteten Schlüsselwort/Zeichen entsprechen.
    def expect(self, tok):
        t = self.next()
        if t.upper() != tok:
            raise SymbolError(f"„{tok}“ erwartet, gefunden: „{t}“")

    # Ganze Zahl lesen, auch negative (Array-Grenzen wie -1..1).
    def int_(self):
        neg = False
        if self.peek() == "-":
            self.i += 1
            neg = True
        t = self.next()
        if not t.isdigit():
            raise SymbolError(tr("Zahl erwartet, gefunden: „{0}“").format(t))
        return -int(t) if neg else int(t)

    # Bis hinter das Schlüsselwort end_word weiterlesen (zum Überspringen fehlerhafter Bausteine).
    def skip_to(self, end_word):
        while self.i < len(self.toks) and self.toks[self.i].upper() != end_word:
            self.i += 1
        self.i += 1

    # Eine Initialisierung wie ':= 5.0;' oder ':= (a := 1, b := 2);' überspringen; Klammern werden gezählt.
    def skip_value(self):
        """Initialwert (:= ...) bis zum Semikolon überspringen."""
        depth = 0
        while True:
            t = self.next()
            if t in "([":
                depth += 1
            elif t in ")]":
                depth -= 1
            elif t == ";" and depth <= 0:
                return

    # Hauptschleife: alles überspringen, bis DATA_BLOCK oder TYPE kommt (Kopfzeilen, Initialwerte, BEGIN-Teil ...).
    # --- Hauptschleife
    def parse(self):
        while self.i < len(self.toks):
            u = self.toks[self.i].upper()
            self.i += 1
            if u == "DATA_BLOCK":
                self.parse_db()
            # 'TYPE' ohne folgenden Doppelpunkt ist ein UDT (ein ':' würde auf eine Deklaration wie 'TYPE : ...' hindeuten).
            elif u == "TYPE" and self.peek() not in (":", None):
                self.parse_udt()

    # DATA_BLOCK: klassisch 'DATA_BLOCK DB 10' (mit Nummer) oder TIA 'DATA_BLOCK "Name"' (ohne Nummer).
    def parse_db(self):
        start = self.i
        try:
            t = self.next()
            name, number = None, None
            nxt = self.peek()
            if t.upper() == "DB" and nxt is not None and nxt.isdigit():
                number = int(self.next())
            else:
                name = _unquote(t)
            root = None
            # Kopfzeilen (TITLE, VERSION, AUTHOR ...) überspringen, bis die Deklaration beginnt.
            while True:
                t = self.peek()
                if t is None:
                    break
                u = t.upper()
                # Deklarationsteil: klassisch STRUCT ... END_STRUCT, TIA VAR ... END_VAR.
                if u in ("STRUCT", "VAR"):
                    self.i += 1
                    members = self.members({"END_STRUCT"} if u == "STRUCT" else {"END_VAR"})
                    root = ("struct", members)
                    break
                # DB auf Basis eines UDT (klassisch: 'UDT 5').
                if u == "UDT":
                    self.i += 1
                    root = ("udt", f"UDT{self.int_()}")
                    break
                # TIA: der DB ist ein Typ in Anführungszeichen (UDT oder Funktionsbaustein) - wird später aufgelöst.
                if t.startswith('"'):                 # TIA: DB auf Basis eines UDT/FB
                    self.i += 1
                    root = ("udt", _unquote(t))
                    break
                # Leerer DB ohne Deklaration.
                if u in ("BEGIN", "END_DATA_BLOCK"):
                    break
                self.i += 1
            self.dbs.append(RawDB(name or "", number, root))
        # Fehler im Baustein: merken, den Rest des Bausteins überspringen und mit dem nächsten weitermachen.
        except SymbolError as e:
            self.i = max(self.i, start)
            self.dbs.append(RawDB(name or "", number, None, error=str(e)))
            self.skip_to("END_DATA_BLOCK")

    # TYPE ... END_TYPE: benutzerdefinierter Datentyp (UDT); wird unter seinem Namen abgelegt.
    def parse_udt(self):
        try:
            t = self.next()
            name = f"UDT{self.int_()}" if t.upper() == "UDT" else _unquote(t)
            while True:
                t = self.next()
                if t.upper() == "STRUCT":
                    break
                if t.upper() == "END_TYPE":
                    raise SymbolError(tr("UDT „{0}“ ohne STRUCT").format(name))
            self.udts[name] = ("struct", self.members({"END_STRUCT"}))
        except SymbolError:
            self.skip_to("END_TYPE")

    # Liste von Deklarationen 'Name : Typ [:= Wert];' bis zu einem der Endwörter (END_STRUCT/END_VAR).
    def members(self, end_kws):
        out = []
        while True:
            t = self.peek()
            if t is None:
                raise SymbolError(tr("Unerwartetes Dateiende in der Deklaration"))
            # Endwort erreicht: danach optional ein Semikolon verbrauchen und die Liste zurückgeben.
            if t.upper() in end_kws:
                self.i += 1
                if self.peek() == ";":
                    self.i += 1
                return out
            if t == ";":
                self.i += 1
                continue
            # Mehrere Namen mit gleichem Typ sind erlaubt: 'a, b : INT;'.
            names = [_unquote(self.next())]
            while self.peek() == ",":
                self.i += 1
                names.append(_unquote(self.next()))
            self.expect(":")
            typ = self.parse_type()
            # Initialwert (interessiert für die Adressen nicht) überspringen, sonst das Semikolon verbrauchen.
            if self.peek() == ":=":
                self.skip_value()
            elif self.peek() == ";":
                self.i += 1
            for n in names:
                out.append((n, typ))

    # Typangabe lesen: STRUCT, ARRAY, STRING, UDT-Verweis oder elementarer Typ.
    def parse_type(self):
        t = self.next()
        u = t.upper()
        # Verschachtelte Struktur: rekursiv die Mitglieder lesen.
        if u == "STRUCT":
            return ("struct", self.members({"END_STRUCT"}))
        # ARRAY [lo..hi, lo..hi] OF Typ - auch mehrdimensional.
        if u == "ARRAY":
            self.expect("[")
            dims = []
            while True:
                lo = self.int_()
                self.expect("..")
                hi = self.int_()
                if hi < lo:
                    raise SymbolError(tr("Ungültige Array-Grenzen {0}..{1}").format(lo, hi))
                dims.append((lo, hi))
                if self.peek() == ",":
                    self.i += 1
                    continue
                break
            self.expect("]")
            self.expect("OF")
            return ("array", dims, self.parse_type())
        # STRING[n] / WSTRING[n]; ohne Längenangabe gilt die Standardlänge 254.
        if u in ("STRING", "WSTRING"):
            n = 254
            if self.peek() == "[":
                self.i += 1
                n = self.int_()
                self.expect("]")
            return ("string", u, n)
        if u == "UDT":
            return ("udt", f"UDT{self.int_()}")
        # Elementarer Typ (BOOL, INT, REAL ...).
        if u in ELEM_SIZE:
            return ("elem", u)
        # Alles andere ist ein Verweis auf einen benutzerdefinierten Typ (UDT) - wird erst beim Layout aufgelöst.
        return ("udt", _unquote(t))


# ---------------------------------------------------------------------------------------
# Adress-Layout
# ---------------------------------------------------------------------------------------
# ------------------------------------------------------------------ Adress-Layout
# Schreibmarke beim Vergeben der Adressen: aktuelles Byte und das nächste freie Bit darin (0 = Byte-Grenze).
class _Cursor:
    def __init__(self):
        """Position Byte 0, Bit 0."""
        self.byte = 0
        self.bit = 0

    # Ausrichten: angefangene Bits abschließen (nächstes Byte) und optional auf eine gerade Adresse aufrunden.
    def align(self, even):
        if self.bit:
            self.byte += 1
            self.bit = 0
        if even and self.byte % 2:
            self.byte += 1

    # Nächstes freies Bit vergeben (BOOLs sind dicht gepackt, 8 je Byte).
    def take_bool(self):
        pos = (self.byte, self.bit)
        self.bit += 1
        if self.bit == 8:
            self.byte += 1
            self.bit = 0
        return pos

    # n Bits überspringen (für große BOOL-Arrays, deren Elemente nicht einzeln erzeugt werden).
    def skip_bits(self, n):
        total = self.byte * 8 + self.bit + n
        self.byte, self.bit = divmod(total, 8)


# Erzeugt aus den Typbeschreibungen den Baum mit Adressen.
class _Layout:
    def __init__(self, udts):
        """``udts``: bekannte UDT-Definitionen (Name in Großbuchstaben -> Typ)."""
        self.udts = udts          # Name (groß) -> Typ

    # UDT-Verweise bis zum eigentlichen Typ auflösen (mit Schutz vor zyklischen Definitionen).
    def resolve(self, typ, depth=0):
        while typ[0] == "udt":
            if depth > 32:
                raise SymbolError(tr("UDT-Verschachtelung zu tief (zyklische Definition?)"))
            # Groß-/Kleinschreibung ignorieren (TIA und STEP 7 sind hier nicht einheitlich).
            nxt = self.udts.get(typ[1].upper())
            if nxt is None:
                raise SymbolError(
                    tr("Unbekannter Typ „{0}“ – UDT-Quelle ebenfalls importieren (Instanz-DBs von Funktionsbausteinen werden nicht unterstützt)").format(typ[1]))
            typ = nxt
            depth += 1
        return typ

    # Knoten für eine Deklaration erzeugen und dabei die Schreibmarke 'cur' weiterschieben.
    def build(self, name, typ, cur):
        typ = self.resolve(typ)
        kind = typ[0]
        # Elementarer Typ.
        if kind == "elem":
            dt = typ[1]
            # BOOL: nächstes freies Bit; keine Byte-Ausrichtung.
            if dt == "BOOL":
                b, bit = cur.take_bool()
                return SymNode(name, "leaf", "BOOL", b, bit)
            size = ELEM_SIZE[dt]
            # Typen mit 2 oder mehr Bytes beginnen auf einer geraden Adresse (kein Vielfaches der Größe!).
            cur.align(size >= 2)
            node = SymNode(name, "leaf", dt, cur.byte, 0, size)
            cur.byte += size
            return node
        # STRING: Länge + 2 Bytes Kopf (maximale und aktuelle Länge); WSTRING: 2 Bytes je Zeichen + 4 Bytes Kopf.
        if kind == "string":
            _, st, n = typ
            size = n + 2 if st == "STRING" else 2 * n + 4
            cur.align(STRING_EVEN_ALIGN or st == "WSTRING")
            node = SymNode(name, "leaf", f"{st}[{n}]", cur.byte, 0, size)
            cur.byte += size
            return node
        # Struktur: beginnt und endet auf einer geraden Adresse; Mitglieder nacheinander.
        if kind == "struct":
            cur.align(True)
            node = SymNode(name, "struct", byte=cur.byte)
            for n, t in typ[1]:
                node.children.append(self.build(n, t, cur))
            cur.align(True)
            node.size = cur.byte - node.byte
            return node
        # Array: wie eine Struktur gerade ausgerichtet; jedes Element wird mit dem Elementtyp erzeugt.
        # Array
        _, dims, elem = typ
        cur.align(True)
        node = SymNode(name, "array", byte=cur.byte)
        # Gesamtzahl der Elemente = Produkt der Dimensionsgrößen.
        count = math.prod(hi - lo + 1 for lo, hi in dims)
        is_bool = self.resolve(elem) == ("elem", "BOOL")
        last_size = 0
        indices = itertools.product(*[range(lo, hi + 1) for lo, hi in dims])
        # Über alle Indexkombinationen iterieren (z. B. [0,0], [0,1], ...), ohne alle zu speichern.
        for k, idx in enumerate(indices):
            # Ab ARRAY_LIMIT werden keine Knoten mehr erzeugt; die Adressrechnung läuft aber weiter:
            if k >= ARRAY_LIMIT:
                rest = count - k
                # BOOL-Arrays: restliche Bits überspringen ...
                if is_bool:
                    cur.skip_bits(rest)
                # ... sonst: restliche Elemente * Größe des letzten Elements.
                else:
                    cur.byte += rest * last_size
                node.children.append(SymNode(tr("… {0} weitere Elemente").format(rest), "note"))
                break
            start = cur.byte
            # Beschriftung des Elements, z. B. '[3]' oder '[1,2]'.
            label = "[" + ",".join(str(i) for i in idx) + "]"
            node.children.append(self.build(label, elem, cur))
            last_size = cur.byte - start
        cur.align(True)
        node.size = cur.byte - node.byte
        return node


# Pfade und DB-Nummer rekursiv eintragen: 'DB.Struktur.Variable' bzw. 'DB.Array[3]'.
def _finalize(node, path, db):
    node.path = path
    node.db = db
    for ch in node.children:
        if ch.kind == "note":
            ch.db = db
            continue
        # Array-Elemente ('[3]') werden ohne Punkt angehängt.
        sub = path + ch.name if ch.name.startswith("[") else f"{path}.{ch.name}"
        _finalize(ch, sub, db)


# ---------------------------------------------------------------------------------------
# Quellen
# ---------------------------------------------------------------------------------------
# ------------------------------------------------------------------ Quellen
class Source:
    """Eine eingelesene Quelldatei (kann mehrere DBs/UDTs enthalten)."""

    def __init__(self, path, numbers=None):
        """Quelldatei ``path`` lesen und zerlegen; ``numbers`` = vom Benutzer vergebene DB-Nummern für DBs ohne Nummer.
        """
        self.path = path
        # Für TIA-Quellen ohne DB-Nummer: die vom Benutzer vergebenen Nummern, damit sie beim nächsten Start
        # automatisch wieder zugeordnet werden können (siehe entry()).
        self.assigned = []        # vom Benutzer vergebene DB-Nummern (für DBs ohne Nummer)
        # Textdatei lesen: erst UTF-8 (TIA), bei Fehlern Windows-Zeichensatz (ältere STEP-7-Dateien).
        try:
            with open(path, encoding="utf-8-sig") as f:
                raw = f.read()
        except UnicodeDecodeError:
            with open(path, encoding="cp1252", errors="replace") as f:
                raw = f.read()
        p = _Parser(raw)
        p.parse()
        self.dbs, self.udts = p.dbs, p.udts
        # Optimierter Zugriff ('S7_Optimized_Access := TRUE') ist im Kopf des Bausteins als Attribut vermerkt.
        pat = re.compile(r"S7_Optimized_Access\s*:=\s*'TRUE'", re.I)
        # Die Quelle in die Abschnitte der einzelnen DATA_BLOCKs teilen, damit jeder Baustein einzeln geprüft wird.
        chunks = re.split(r"(?i)\bDATA_BLOCK\b", raw)[1:]
        for k, d in enumerate(self.dbs):   # je DB prüfen (Fallback: ganze Datei)
            d.optimized = bool(pat.search(chunks[k] if len(chunks) == len(self.dbs) else raw))
        if not self.dbs and not self.udts:
            raise SymbolError(tr("Keine DATA_BLOCK- oder TYPE-Definition gefunden"))
        if numbers:
            self.assign(list(numbers))

    # DBs, für die der Benutzer noch eine Nummer angeben muss.
    def unnumbered(self):
        return [d for d in self.dbs if d.number is None and not d.error]

    # Nummern der Reihe nach an DBs ohne Nummer vergeben.
    def assign(self, numbers):
        numbers = list(numbers)
        for d in self.dbs:
            if d.number is None and not d.error and numbers:
                d.number = numbers.pop(0)
                self.assigned.append(d.number)

    # Eintrag für die Konfiguration: 'Pfad' oder 'Pfad#Nr1,Nr2' (mit den vergebenen DB-Nummern).
    def entry(self):
        return self.path + ("#" + ",".join(str(n) for n in self.assigned) if self.assigned else "")


# Alle importierten Quellen zusammen (Grundlage des Symbolbaums im Dialog).
class SymbolSet:
    def __init__(self):
        """Leere Sammlung von Quelldateien."""
        self.sources = []

    # Eintrag laden: Pfad, optional mit '#<Nummern>' am Ende.
    def load(self, entry: str) -> Source:
        path, numbers = entry, []
        # Nur ein '#' am Ende mit Zahlen zählt als Nummernliste (ein '#' im Pfad bleibt unberührt).
        if "#" in entry:
            head, _, tail = entry.rpartition("#")
            if re.fullmatch(r"\d+(,\d+)*", tail):
                path, numbers = head, [int(x) for x in tail.split(",")]
        src = Source(path, numbers)
        self.sources.append(src)
        return src

    def remove(self, src):
        """Quelldatei aus der Sammlung entfernen."""
        if src in self.sources:
            self.sources.remove(src)

    def entries(self):
        """Einträge zum Speichern in der Konfiguration (Pfad, ggf. mit „#Nummern“)."""
        return [s.entry() for s in self.sources]

    def build(self):
        """-> (Liste von DB-Wurzelknoten, Liste von Fehler-/Warntexten)"""
        # UDT-Definitionen aller Quellen zusammenführen (ein DB darf einen UDT aus einer anderen Datei verwenden).
        udts = {}
        for s in self.sources:
            for n, t in s.udts.items():
                udts[n.upper()] = t
        # seen merkt sich bereits verwendete DB-Nummern, um Doppelte zu melden.
        nodes, errors, seen = [], [], {}
        for s in self.sources:
            # Dateiname für Fehlermeldungen (Windows- und Unix-Pfade).
            fname = s.path.replace("\\", "/").rsplit("/", 1)[-1]
            for d in s.dbs:
                label = d.name or (f"DB{d.number}" if d.number else "?")
                if d.error:
                    errors.append(f"{fname} › {label}: {d.error}")
                    continue
                if d.number is None:
                    errors.append(tr("{0} › {1}: DB-Nummer fehlt").format(fname, label))
                    continue
                if d.root is None:
                    errors.append(tr("{0} › {1}: keine Deklaration gefunden").format(fname, label))
                    continue
                # Adressen berechnen; Fehler (z. B. unbekannter UDT) betreffen nur diesen einen Baustein.
                try:
                    lay = _Layout(udts)
                    cur = _Cursor()
                    top = lay.build(d.name or f"DB{d.number}", d.root, cur)
                    # Gesamtlänge des Bausteins auf gerade Byte-Zahl aufrunden (so legt die SPS ihn an).
                    cur.align(True)
                except SymbolError as e:
                    errors.append(f"{fname} › {label}: {e}")
                    continue
                # Wurzelknoten des Bausteins; seine Größe kann mit der Größe in der SPS verglichen werden.
                root = SymNode(d.name or f"DB{d.number}", "db", size=cur.byte, source=s)
                root.children = top.children if top.kind == "struct" else [top]
                _finalize(root, root.name, d.number)
                # Optimierte Bausteine haben keine festen Adressen -> Hinweis anzeigen.
                if d.optimized:
                    root.note = tr("optimierter Zugriff – Adressen für PUT/GET nicht nutzbar")
                if d.number in seen:
                    errors.append(tr("{0} › {1}: DB{2} ist doppelt vorhanden ({3})").format(fname, label, d.number, seen[d.number]))
                seen[d.number] = fname
                nodes.append(root)
        return nodes, errors
