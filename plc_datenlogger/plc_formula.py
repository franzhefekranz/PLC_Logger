"""Berechnete Variablen: sichere Auswertung von Formeln.

Variablen werden in geschweiften Klammern angegeben, z. B.  ({Temp_Vorlauf} + {Temp_Ruecklauf}) / 2
Erlaubt sind Zahlen, + - * / // % **, Vergleiche, and/or/not, bedingte Ausdrücke
(``a if bedingung else b``) und die unten aufgeführten Funktionen. Es wird nie beliebiger
Python-Code ausgeführt: die Formel wird als Syntaxbaum geprüft und nur erlaubte Elemente
werden zugelassen.

Wie es funktioniert (Überblick)
-------------------------------
1. ``{Name}`` wird durch einen gültigen Python-Namen ``_v0``, ``_v1`` ... ersetzt (so dürfen
   Variablennamen Punkte, Leerzeichen oder Klammern enthalten, z. B. ``{Prozess.Motor[3]}``).
2. Der Text wird mit ``ast.parse`` in einen Syntaxbaum umgewandelt. Der ``_Checker`` lässt nur
   die in ``_ALLOWED`` aufgeführten Knotentypen zu (keine Attribute, Importe, Lambdas, Indizes ...).
3. Funktionsaufrufe sind auf die Tabelle ``FUNCTIONS`` beschränkt. ``**`` wird durch eine sichere
   Potenzfunktion ersetzt; ``ddt``, ``integ`` und ``avg`` bekommen einen Zustandsindex.
4. Der geprüfte Baum wird einmal kompiliert; ``evaluate`` führt ihn mit leeren ``__builtins__``
   und nur den erlaubten Funktionen aus. Fehler (Division durch 0 ...) ergeben NaN.
"""


import ast
import math
import re
from collections import deque
from plc_i18n import tr

# NaN = "Not a Number": steht im ganzen Programm für "kein Wert" (Lücke in der Kurve, leeres CSV-Feld).
NAN = float("nan")
# Findet {Name}-Platzhalter; der Name darf alles außer geschweiften Klammern enthalten.
_REF = re.compile(r"\{([^{}]*)\}")
# Obergrenze der Formellänge (Schutz vor versehentlich riesigen Eingaben).
MAX_LEN = 1000


class FormulaError(Exception):
    """Fehler in einer Formel (Syntax, unbekannte Variable/Funktion, nicht erlaubtes Element)."""
    pass


# Vorzeichen: -1, 0 oder 1 (NaN bleibt NaN).
def _sign(x):
    return NAN if x != x else float((x > 0) - (x < 0))


# Begrenzt x auf den Bereich lo..hi.
def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _pow(a, b):
    return math.pow(float(a), float(b))   # Überlauf -> OverflowError statt riesiger Zahlen


# Alle erlaubten Funktionen.
# Schlüssel = Name in der Formel; Wert = (Text für die Funktionsliste im Editor,
# kleinste und größte Anzahl der Argumente). Die Argumentanzahl wird beim Prüfen kontrolliert.
# Funktion -> (Beschreibung für den Editor, min. Argumente, max. Argumente)
FUNCTIONS = {
    "abs": (tr("abs(x) – Betrag"), 1, 1),
    "min": (tr("min(a, b, …) – kleinster Wert"), 1, 8),
    "max": (tr("max(a, b, …) – größter Wert"), 1, 8),
    "sqrt": (tr("sqrt(x) – Quadratwurzel"), 1, 1),
    "sin": (tr("sin(x) – Sinus (Bogenmaß)"), 1, 1),
    "cos": (tr("cos(x) – Kosinus (Bogenmaß)"), 1, 1),
    "tan": (tr("tan(x) – Tangens (Bogenmaß)"), 1, 1),
    "asin": (tr("asin(x) – Arkussinus"), 1, 1),
    "acos": (tr("acos(x) – Arkuskosinus"), 1, 1),
    "atan": (tr("atan(x) – Arkustangens"), 1, 1),
    "atan2": (tr("atan2(y, x) – Arkustangens zweier Werte"), 2, 2),
    "exp": (tr("exp(x) – e hoch x"), 1, 1),
    "ln": (tr("ln(x) – natürlicher Logarithmus"), 1, 1),
    "log10": (tr("log10(x) – Zehnerlogarithmus"), 1, 1),
    "log": (tr("log(x, basis) – Logarithmus"), 1, 2),
    "floor": (tr("floor(x) – abrunden"), 1, 1),
    "ceil": (tr("ceil(x) – aufrunden"), 1, 1),
    "round": (tr("round(x, stellen) – runden"), 1, 2),
    "hypot": (tr("hypot(a, b) – √(a²+b²)"), 2, 2),
    "radians": (tr("radians(grad) – Grad in Bogenmaß"), 1, 1),
    "degrees": (tr("degrees(rad) – Bogenmaß in Grad"), 1, 1),
    "sign": (tr("sign(x) – Vorzeichen (-1, 0, 1)"), 1, 1),
    "clamp": (tr("clamp(x, min, max) – auf Bereich begrenzen"), 3, 3),
    "ddt": (tr("ddt(x) – Ableitung nach der Zeit (pro Sekunde)"), 1, 1),
    "integ": (tr("integ(x) – Integral über die Zeit (x · s)"), 1, 1),
    "avg": (tr("avg(x, n) – gleitender Mittelwert über n Messwerte"), 2, 2),
}
# Funktionen mit Gedächtnis: ihr Ergebnis hängt von früheren Messungen ab (siehe _ddt/_integ/_avg).
STATEFUL = ("ddt", "integ", "avg")
# Erlaubte Konstanten in Formeln.
CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}

# Die eigentlichen Python-Funktionen zu den Namen aus FUNCTIONS (ohne die zustandsbehafteten,
# diese stehen als Methoden in der Formel-Instanz). '_pow' ersetzt den Operator ** (siehe _Checker).
_IMPL = {
    "abs": abs, "min": min, "max": max, "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos,
    "tan": math.tan, "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "atan2": math.atan2, "exp": math.exp, "ln": math.log, "log10": math.log10,
    "log": math.log, "floor": math.floor, "ceil": math.ceil, "round": round,
    "hypot": math.hypot, "radians": math.radians, "degrees": math.degrees,
    "sign": _sign, "clamp": _clamp, "_pow": _pow,
}

# Whitelist der erlaubten Syntaxbaum-Knoten. Alles andere (Attribute wie x.real, Indizes, Listen,
# Lambda, Strings, Importe, Zuweisungen ...) wird abgelehnt. Das ist die Sicherheitsgrenze.
_ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
            ast.Call, ast.Name, ast.Constant, ast.Load,
            ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
            ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or,
            ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)


class _Checker(ast.NodeTransformer):
    """Prüft den Syntaxbaum und ergänzt Zustands-Indizes für ddt/integ/avg."""

    def __init__(self):
        self.k = 0

    # Wird für jeden Knoten aufgerufen, für den es keine eigene visit_-Methode gibt: nur Whitelist-Knoten durchlassen.
    def generic_visit(self, node):
        if not isinstance(node, _ALLOWED):
            raise FormulaError(tr("Nicht erlaubtes Element in der Formel: {0}").format(type(node).__name__))
        return super().generic_visit(node)

    def visit_Constant(self, node):
        # Zahlen und Wahrheitswerte sind erlaubt, Zeichenketten und andere Konstanten nicht.
        if isinstance(node.value, (int, float, bool)):
            return node
        raise FormulaError(tr("Nur Zahlen sind als Konstanten erlaubt"))

    def visit_Name(self, node):
        n = node.id
        # Erlaubt sind nur unsere Platzhalter _v0, _v1 ... und die Konstanten (pi, e, tau).
        if re.fullmatch(r"_v\d+", n) or n in CONSTANTS:
            return node
        # Hilfreiche Fehlermeldung, wenn eine Funktion ohne Klammern verwendet wurde.
        if n in FUNCTIONS:
            raise FormulaError(tr("„{0}“ ist eine Funktion und braucht Klammern: {1}(…)").format(n, n))
        raise FormulaError(tr("Unbekannter Name „{0}“ – Variablen in {{geschweiften Klammern}} angeben").format(n))

    def visit_Call(self, node):
        # Nur Aufrufe einfacher Namen aus der Funktionstabelle (kein x.y() oder (lambda)()).
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
            raise FormulaError(tr("Unbekannte Funktion in der Formel"))
        name = node.func.id
        if node.keywords:
            raise FormulaError(tr("{0}(): Schlüsselwort-Argumente sind nicht erlaubt").format(name))
        # Anzahl der Argumente gegen die Tabelle prüfen.
        _, lo, hi = FUNCTIONS[name]
        if not lo <= len(node.args) <= hi:
            raise FormulaError(tr("{0}(): falsche Anzahl von Argumenten").format(name))
        # Auch die Argumente selbst prüfen (verschachtelte Aufrufe).
        node.args = [self.visit(a) for a in node.args]
        # Zustandsbehaftete Funktion: eine laufende Nummer als zusätzliches Argument anhängen. Sie dient als
        # Schlüssel, damit jede Stelle der Formel ihren eigenen Zustand hat (zwei ddt() in einer Formel stören sich nicht).
        if name in STATEFUL:
            node.args.append(ast.Constant(self.k))
            self.k += 1
        return node

    def visit_BinOp(self, node):
        # Zuerst die Operanden prüfen ...
        self.generic_visit(node)
        # ... dann den Operator ** durch den Aufruf _pow(a, b) ersetzen: so ist 9**9**9 kein Problem
        # (OverflowError statt einer riesigen Ganzzahl, die den Rechner blockieren würde).
        if isinstance(node.op, ast.Pow):
            return ast.copy_location(
                ast.Call(func=ast.Name(id="_pow", ctx=ast.Load()),
                         args=[node.left, node.right], keywords=[]), node)
        return node


class Formula:
    """Kompilierte Formel. refs = Namen der referenzierten Variablen (in Reihenfolge)."""

    def __init__(self, text: str):
        # Mehrzeilige Eingaben zu einer Zeile zusammenfassen (Leerräume vereinheitlichen).
        text = " ".join(str(text).split())
        if not text:
            raise FormulaError(tr("Die Formel ist leer"))
        if len(text) > MAX_LEN:
            raise FormulaError(tr("Die Formel ist zu lang (max. {0} Zeichen)").format(MAX_LEN))
        self.text = text
        self.refs = []

        # Ersetzungsfunktion für re.sub: merkt sich jeden Variablennamen einmal in refs und liefert den Platzhalter.
        def sub(m):
            name = m.group(1).strip()
            if not name:
                raise FormulaError(tr("Leere Variablenangabe {}"))
            if name not in self.refs:
                self.refs.append(name)
            return f"_v{self.refs.index(name)}"

        expr = _REF.sub(sub, text)
        # Übrig gebliebene Klammern = unpaarig oder verschachtelt.
        if "{" in expr or "}" in expr:
            raise FormulaError(tr("Unpaarige geschweifte Klammer"))
        # Python-Parser: erzeugt den Syntaxbaum; Syntaxfehler werden in eine verständliche Meldung übersetzt.
        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError as e:
            raise FormulaError(f"Syntaxfehler: {e.msg}")
        except (RecursionError, MemoryError, ValueError):
            raise FormulaError(tr("Die Formel ist zu komplex"))
        # Whitelist-Prüfung und Umbau (Zustandsindizes, sichere Potenz).
        tree = _Checker().visit(tree)
        # Die Transformation erzeugt neue Knoten ohne Positionsangaben; sie werden für compile() ergänzt.
        ast.fix_missing_locations(tree)
        # In Bytecode übersetzen (einmal); evaluate() führt ihn danach in jedem Messzyklus schnell aus.
        self.code = compile(tree, "<formel>", "eval")
        # Zustand der Funktionen ddt/integ/avg: {Index: Werte}; wird bei reset() gelöscht.
        self._state = {}
        # Zeitstempel der aktuellen Auswertung (für ddt/integ nötig).
        self._ts = 0.0
        # Umgebung für die Auswertung: erlaubte Funktionen, Konstanten und die gebundenen Zustandsfunktionen.
        self._env = dict(_IMPL)
        self._env.update(CONSTANTS)
        self._env.update(ddt=self._ddt, integ=self._integ, avg=self._avg)

    # Zustandsbehaftete Funktionen. Der letzte Parameter k ist der vom _Checker eingefügte Zustandsindex.
    # --- Zustandsbehaftete Funktionen
    def _ddt(self, x, k):
        # Ungültiger Eingangswert: kein Ergebnis, Zustand bleibt unverändert (z. B. kurze Lücke).
        if x != x:
            return NAN
        prev = self._state.get(k)
        self._state[k] = (self._ts, x)
        # Erste Messung: es gibt noch keinen Vorgängerwert -> noch keine Ableitung.
        if prev is None:
            return NAN
        # Differenzenquotient (x - x_vorher) / (t - t_vorher), in Einheiten pro Sekunde.
        dt = self._ts - prev[0]
        return (x - prev[1]) / dt if dt > 0 else NAN

    def _integ(self, x, k):
        prev = self._state.get(k)           # (t, x, summe)
        # Bei fehlendem Messwert die bisherige Summe unverändert weitergeben.
        if x != x:
            return prev[2] if prev else NAN
        # Erste Messung: die Summe beginnt bei 0.
        if prev is None:
            self._state[k] = (self._ts, x, 0.0)
            return 0.0
        dt = self._ts - prev[0]
        # Trapezregel: Fläche = Mittelwert der beiden Messwerte * Zeitschritt.
        acc = prev[2] + (x + prev[1]) / 2.0 * dt if dt > 0 else prev[2]
        self._state[k] = (self._ts, x, acc)
        return acc

    def _avg(self, x, n, k):
        # Fenstergröße mindestens 1; als ganze Zahl (die Formel liefert evtl. eine Kommazahl).
        n = max(1, int(n))
        dq = self._state.get(k)
        # Fenster neu anlegen, wenn es noch nicht existiert oder sich n geändert hat.
        if dq is None or dq.maxlen != n:
            dq = deque(maxlen=n)
            self._state[k] = dq
        if x == x:
            dq.append(x)
        return sum(dq) / len(dq) if dq else NAN

    # Zustand löschen (bei jedem neuen Start der Aufzeichnung).
    def reset(self):
        self._state.clear()

    def evaluate(self, ts: float, values: dict) -> float:
        """Wert zum Zeitpunkt ts berechnen; fehlende/ungültige Werte ergeben NaN."""
        # Zeit für ddt/integ merken.
        self._ts = ts
        # Kopie der Umgebung: erlaubte Funktionen + die aktuellen Werte der referenzierten Variablen.
        env = dict(self._env)
        for i, n in enumerate(self.refs):
            # Fehlt ein Wert, wird NaN eingesetzt (das Ergebnis wird dann i. d. R. NaN).
            env[f"_v{i}"] = values.get(n, NAN)
        try:
            # Auswertung ohne Zugriff auf Python-Builtins (__builtins__ = {}): es gibt nur die Funktionen aus env.
            return float(eval(self.code, {"__builtins__": {}}, env))
        # Rechenfehler (Division durch 0, sqrt(-1), Überlauf, ...) ergeben "kein Wert" statt eines Programmabbruchs.
        except (ArithmeticError, ValueError, TypeError, NameError):
            return NAN


def check(text: str):
    """-> (Formel oder None, Fehlertext oder "")"""
    try:
        return Formula(text), ""
    except FormulaError as e:
        return None, str(e)
