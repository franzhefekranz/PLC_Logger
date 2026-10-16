"""Aufzeichnung in eine Datenbank: SQLite, MariaDB/MySQL oder TimescaleDB/PostgreSQL (zusätzlich oder statt CSV).

Ein eigener Schreib-Thread (``DbWriter``) nimmt die Messzeilen vom Sammler-Thread des Recorders entgegen und schreibt
sie stapelweise (etwa einmal pro Sekunde) in die Datenbank. Netzwerk- oder Plattenwartezeiten der Datenbank bremsen
dadurch weder das Lesen aus der Steuerung noch die Oberfläche. Ist die Datenbank nicht erreichbar, bleiben die Werte
im Speicher (bis zu ``MAX_BUFFER`` Zeilen) und werden nach dem erneuten Verbinden nachgetragen.

Tabellenaufbau ("schmal", eine Zeile je Wert – geeignet für Grafana und TimescaleDB):

    zeit      Zeitpunkt der Messung in UTC (Millisekunden)
    projekt   Projektname aus der Konfiguration (mehrere Logger können eine Tabelle teilen)
    variable  Name der Variable
    wert      Messwert (Gleitkommazahl; BOOL = 0/1)

Werte ohne Gültigkeit (NaN, z. B. Verbindungsausfall) werden nicht geschrieben. Mit "nur Änderungen" wird ein Wert
nur geschrieben, wenn er sich geändert hat, spätestens aber alle ``HEARTBEAT_S`` Sekunden.

Treiber (nur für den gewählten Typ nötig): SQLite ist in Python enthalten; MariaDB: ``PyMySQL``;
TimescaleDB/PostgreSQL: ``psycopg`` (Version 3, ``pip install "psycopg[binary]"``).
"""
import collections
import datetime
import math
import os
import re
import sqlite3
import threading

from s7_common import BASE_DIR
from s7_i18n import N_, tr

# Datenbanktypen: Schlüssel in der INI-Datei -> Anzeige.
DB_TYPES = {"": N_("Keine"), "sqlite": N_("SQLite (Datei)"), "mariadb": N_("MariaDB / MySQL"),
            "timescale": N_("TimescaleDB / PostgreSQL")}
DEFAULT_PORTS = {"mariadb": 3306, "timescale": 5432}
MAX_BUFFER = 2_000_000          # Höchstzahl gepufferter Werte bei Ausfall der Datenbank (älteste werden verworfen)
BATCH = 5000                    # Werte je Einfüge-Anfrage
HEARTBEAT_S = 60.0              # "nur Änderungen": unveränderte Werte spätestens nach dieser Zeit erneut schreiben

ST_OFF, ST_CONNECTING, ST_OK, ST_ERROR = "off", "connecting", "ok", "error"
_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def check_table_name(name):
    """Tabellennamen nur aus Buchstaben, Ziffern und _ (er wird in SQL-Befehle eingesetzt)."""
    return bool(_TABLE_RE.match(name or ""))


def db_settings(conn):
    """Datenbank-Einstellungen aus dem Verbindungs-Dict der Konfiguration."""
    typ = (conn.get("db_typ") or "").strip().lower()
    port = int(conn.get("db_port") or 0) or DEFAULT_PORTS.get(typ, 0)
    path = conn.get("db_datei") or "datenlogger.db"
    if not os.path.isabs(path):
        path = os.path.join(BASE_DIR, path)
    return {"typ": typ if typ in DB_TYPES else "", "host": conn.get("db_host") or "localhost", "port": port,
            "name": conn.get("db_name") or "datenlogger", "user": conn.get("db_user") or "",
            "passwort": conn.get("db_passwort") or "", "tabelle": conn.get("db_tabelle") or "messwerte",
            "datei": path, "nur_aenderungen": bool(int(conn.get("db_nur_aenderungen") or 0)),
            "projekt": conn.get("projekt") or ""}


def describe(s):
    """Kurzbeschreibung des Ziels für Meldungen (ohne Passwort)."""
    if s["typ"] == "sqlite":
        return f"SQLite {s['datei']} › {s['tabelle']}"
    return f"{DB_TYPES.get(s['typ'], s['typ'])} {s['user']}@{s['host']}:{s['port']}/{s['name']} › {s['tabelle']}"


# ---------------------------------------------------------------------------------------
# Anbindungen je Datenbanktyp
# ---------------------------------------------------------------------------------------
class _Backend:
    """Gemeinsame Schnittstelle: connect() legt bei Bedarf die Tabelle an, insert() schreibt Zeilen
    (zeit als datetime in UTC, projekt, variable, wert), close() trennt."""
    note = ""

    def __init__(self, s):
        self.s = s
        self.con = None
        if not check_table_name(s["tabelle"]):
            raise ValueError(tr("Ungültiger Tabellenname: {0!r} (nur Buchstaben, Ziffern, _)").format(s['tabelle']))
        self.t = s["tabelle"]

    def close(self):
        if self.con is not None:
            try:
                self.con.close()
            except Exception:
                pass
            self.con = None


class SqliteBackend(_Backend):
    def connect(self):
        os.makedirs(os.path.dirname(self.s["datei"]) or ".", exist_ok=True)
        self.con = sqlite3.connect(self.s["datei"], timeout=10, check_same_thread=False)
        cur = self.con.cursor()
        cur.execute("PRAGMA journal_mode=WAL")          # gleichzeitiges Lesen (z. B. Grafana) während des Schreibens
        cur.execute(f"CREATE TABLE IF NOT EXISTS {self.t} (zeit TEXT NOT NULL, projekt TEXT, "
                    f"variable TEXT NOT NULL, wert REAL)")
        cur.execute(f"CREATE INDEX IF NOT EXISTS {self.t}_variable_zeit ON {self.t} (variable, zeit)")
        self.con.commit()

    def insert(self, rows):
        # SQLite kennt keinen Zeitstempeltyp: ISO-Text in UTC mit Millisekunden (sortierbar, von Grafana lesbar).
        data = [(z.strftime("%Y-%m-%d %H:%M:%S.") + f"{z.microsecond // 1000:03d}", p, v, w) for z, p, v, w in rows]
        self.con.executemany(f"INSERT INTO {self.t} (zeit, projekt, variable, wert) VALUES (?, ?, ?, ?)", data)
        self.con.commit()


class MariaDbBackend(_Backend):
    def connect(self):
        import pymysql                                  # nur bei Bedarf (pip install PyMySQL)
        s = self.s
        self.con = pymysql.connect(host=s["host"], port=s["port"], user=s["user"], password=s["passwort"],
                                   database=s["name"], charset="utf8mb4", connect_timeout=5, autocommit=False)
        with self.con.cursor() as cur:
            cur.execute(f"CREATE TABLE IF NOT EXISTS `{self.t}` ("
                        "zeit DATETIME(3) NOT NULL, projekt VARCHAR(100), variable VARCHAR(200) NOT NULL, "
                        "wert DOUBLE, KEY idx_variable_zeit (variable, zeit), KEY idx_zeit (zeit)"
                        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
        self.con.commit()

    def insert(self, rows):
        data = [(z.replace(tzinfo=None), p, v, w) for z, p, v, w in rows]   # DATETIME ohne Zeitzone (UTC)
        with self.con.cursor() as cur:
            cur.executemany(f"INSERT INTO `{self.t}` (zeit, projekt, variable, wert) VALUES (%s, %s, %s, %s)", data)
        self.con.commit()


class TimescaleBackend(_Backend):
    def connect(self):
        import psycopg                                  # nur bei Bedarf (pip install "psycopg[binary]")
        s = self.s
        self.con = psycopg.connect(host=s["host"], port=s["port"], dbname=s["name"], user=s["user"] or None,
                                   password=s["passwort"] or None, connect_timeout=5, autocommit=False)
        with self.con.cursor() as cur:
            cur.execute(f'CREATE TABLE IF NOT EXISTS "{self.t}" (zeit TIMESTAMPTZ NOT NULL, projekt TEXT, '
                        'variable TEXT NOT NULL, wert DOUBLE PRECISION)')
        self.con.commit()
        # TimescaleDB: Tabelle in eine Hypertable umwandeln (zeitlich partitioniert). Fehlt die Erweiterung, bleibt
        # es eine normale PostgreSQL-Tabelle – die Aufzeichnung funktioniert trotzdem.
        try:
            with self.con.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
                cur.execute("SELECT create_hypertable(%s, 'zeit', if_not_exists => TRUE, migrate_data => TRUE)",
                            (self.t,))
            self.con.commit()
            self.note = "TimescaleDB-Hypertable"
        except Exception as e:
            self.con.rollback()
            self.note = tr("normale PostgreSQL-Tabelle, TimescaleDB nicht verfügbar: {0}").format(str(e).splitlines()[0])
        with self.con.cursor() as cur:
            cur.execute(f'CREATE INDEX IF NOT EXISTS "{self.t}_variable_zeit" ON "{self.t}" (variable, zeit DESC)')
        self.con.commit()

    def insert(self, rows):
        with self.con.cursor() as cur:
            cur.executemany(f'INSERT INTO "{self.t}" (zeit, projekt, variable, wert) VALUES (%s, %s, %s, %s)', rows)
        self.con.commit()


BACKENDS = {"sqlite": SqliteBackend, "mariadb": MariaDbBackend, "timescale": TimescaleBackend}


def test_connection(conn):
    """Verbindung prüfen und Tabelle anlegen (Konfigurationsprogramm). Rückgabe: Meldungstext; Fehler als Ausnahme."""
    s = db_settings(conn)
    if not s["typ"]:
        return tr("Keine Datenbank gewählt.")
    b = BACKENDS[s["typ"]](s)
    try:
        b.connect()
    finally:
        b.close()
    return tr("Verbindung erfolgreich: {0}").format(describe(s)) + (f"\n{b.note}" if b.note else "")


# ---------------------------------------------------------------------------------------
# Schreib-Thread
# ---------------------------------------------------------------------------------------
class DbWriter(threading.Thread):
    """Schreibt Messzeilen im Hintergrund in die Datenbank.

    ``put(ts, row)`` (aus dem Sammler-Thread) nimmt eine Zeile entgegen; ``stop()`` schreibt den Rest und beendet.
    ``status()`` liefert (Zustand, Text) für die Status-LED; Meldungen gehen an ``emit``."""

    def __init__(self, conn, names, emit=None, interval_s=1.0):
        super().__init__(name="db-writer", daemon=True)
        self.s = db_settings(conn)
        self.names = list(names)
        self.emit = emit or (lambda _t: None)
        self.interval = interval_s
        self.buf = collections.deque()
        self.lock = threading.Lock()
        self.stop_evt = threading.Event()
        self.state = (ST_CONNECTING, "Starte …")
        self.written = 0
        self.dropped = 0
        self._last = {}                 # "nur Änderungen": Variable -> (Wert, Zeit) zuletzt geschrieben
        self.backend = None

    # ---- aus dem Sammler-Thread
    def put(self, ts, row):
        z = datetime.datetime.fromtimestamp(round(ts, 3), datetime.timezone.utc)
        proj, only = self.s["projekt"], self.s["nur_aenderungen"]
        items = []
        for name, val in zip(self.names, row):
            val = float(val)
            if not math.isfinite(val):
                continue
            if only:
                last = self._last.get(name)
                if last is not None and last[0] == val and ts - last[1] < HEARTBEAT_S:
                    continue
                self._last[name] = (val, ts)
            items.append((z, proj, name, val))
        if not items:
            return
        with self.lock:
            self.buf.extend(items)
            over = len(self.buf) - MAX_BUFFER
            if over > 0:
                for _ in range(over):
                    self.buf.popleft()
                self.dropped += over

    # ---- Zustand
    def _set(self, state, text):
        if self.state != (state, text):
            self.state = (state, text)
            self.emit(tr("[Datenbank] {0}").format(text))

    def status(self):
        with self.lock:
            queued = len(self.buf)
        st, text = self.state
        extra = tr(" – {0} Werte geschrieben").format(self.written) + (f", {queued} warten" if queued > BATCH else "")
        if self.dropped:
            extra += tr(", {0} verworfen (Puffer voll)").format(self.dropped)
        return st, text + extra

    # ---- Thread
    def run(self):
        while True:
            stopping = self.stop_evt.wait(self.interval)
            ok = self._flush()
            if stopping:
                break
            if not ok:
                self.stop_evt.wait(5.0)             # nach einem Fehler etwas warten, dann erneut versuchen
                if self.stop_evt.is_set():
                    self._flush()
                    break
        if self.backend:
            self.backend.close()
        self._set(ST_OFF, "getrennt")

    def _flush(self):
        """Alle gepufferten Werte schreiben. Rückgabe: False bei einem Fehler (Werte bleiben im Puffer)."""
        if self.backend is None or self.backend.con is None:
            try:
                self._set(ST_CONNECTING, tr("Verbinde mit {0} …").format(describe(self.s)))
                b = BACKENDS[self.s["typ"]](self.s)
                b.connect()
                self.backend = b
                self._set(ST_OK, f"Verbunden: {describe(self.s)}" + (f" ({b.note})" if b.note else ""))
            except Exception as e:
                self._set(ST_ERROR, tr("Verbindung fehlgeschlagen: {0}").format(e))
                return False
        while True:
            with self.lock:
                batch = [self.buf.popleft() for _ in range(min(BATCH, len(self.buf)))]
            if not batch:
                return True
            try:
                self.backend.insert(batch)
                self.written += len(batch)
                if self.state[0] != ST_OK:
                    self._set(ST_OK, f"Verbunden: {describe(self.s)}")
            except Exception as e:
                with self.lock:
                    self.buf.extendleft(reversed(batch))    # Reihenfolge erhalten, später erneut versuchen
                self._set(ST_ERROR, f"Schreibfehler: {e}")
                self.backend.close()
                return False

    def stop(self, timeout=15.0):
        """Restliche Werte schreiben und den Thread beenden."""
        self.stop_evt.set()
        self.join(timeout)
