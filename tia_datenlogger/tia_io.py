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
"""
import datetime
import math

from tia_common import Plc
from tia_i18n import tr

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


class TagReader:
    """Liest die Variablen EINER Steuerung. Nicht thread-sicher: jeder Lese-Thread hat seinen eigenen Reader.

    variables: Liste von Variable (ohne berechnete); ``read()`` liefert die Werte in derselben Reihenfolge,
    nicht lesbare Werte sind NaN. ``client_factory`` (Tests) erzeugt statt s7commplus.Client ein Ersatzobjekt;
    ``catalog_items`` (Tests) ersetzt die Variablenliste."""

    def __init__(self, plc: Plc, variables, client_factory=None, catalog_items=None):
        self.plc, self.vars = plc, list(variables)
        self.client_factory = client_factory
        self.catalog_items = catalog_items
        self.client = None
        self.tags = [None] * len(self.vars)      # aufgelöste Kennungen (SymbolicTag) je Variable
        self.errors = {}                         # Variablenname (Tag) -> Fehlertext
        self.catalog_refreshed = False           # Variablenliste in dieser Sitzung schon neu gelesen?

    # ------------------------------------------------------------------ Verbindung
    def _new_client(self):
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
        self._resolve()
        n_ok = sum(1 for t in self.tags if t is not None)
        if n_ok:
            self.read()                           # erst ein erfolgreicher Lesezyklus beweist die Verbindung
        return n_ok - sum(1 for i, t in enumerate(self.tags) if t is not None and self.vars[i].tag in self.errors)

    def _catalog(self, refresh=False):
        """Variablenkatalog (s7commplus.SymbolCatalog): aus dem Zwischenspeicher oder neu aus der Steuerung."""
        from s7commplus import SymbolCatalog
        import tia_taglist
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
        """Namen der Variablen in Kennungen übersetzen; fehlen Namen, die Liste einmal neu aus der Steuerung lesen."""
        catalog = self._catalog()
        missing = self._apply(catalog)
        if missing and not self.catalog_refreshed:
            catalog = self._catalog(refresh=True)
            missing = self._apply(catalog)
        for i in missing:
            self.errors[self.vars[i].tag] = tr("Variable in der Steuerung nicht gefunden")

    def _apply(self, catalog):
        missing = []
        for i, v in enumerate(self.vars):
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

    def _read_items(self, indices):
        items = [(self.tags[i].access_area, list(self.tags[i].lids), 0) for i in indices]
        return self.client.read_symbolic_multi(items)

    def close(self):
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
