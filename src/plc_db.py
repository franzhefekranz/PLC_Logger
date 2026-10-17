# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Aufzeichnung in eine Datenbank (zusätzlich oder statt CSV): SQLite, MariaDB/MySQL, TimescaleDB/PostgreSQL, QuestDB,
InfluxDB 3 oder VictoriaMetrics.

Ein eigener Schreib-Thread (``DbWriter``) nimmt die Messzeilen vom Sammler-Thread des Recorders entgegen und schreibt
sie stapelweise (etwa einmal pro Sekunde) in die Datenbank. Netzwerk- oder Plattenwartezeiten der Datenbank bremsen
dadurch weder das Lesen aus der Steuerung noch die Oberfläche. Ist die Datenbank nicht erreichbar, bleiben die Werte
im Speicher (bis zu ``MAX_BUFFER`` Zeilen) und werden nach dem erneuten Verbinden nachgetragen.

Tabellenaufbau ("schmal", eine Zeile je Wert – geeignet für Grafana und TimescaleDB):

    zeit      Zeitpunkt der Messung in UTC (Millisekunden)
    projekt   Projektname aus der Konfiguration (mehrere Logger können eine Tabelle teilen)
    variable  Name der Variable
    wert      Messwert (Gleitkommazahl; BOOL = 0/1)

InfluxDB 3: Zeitspalte ``time``, projekt/variable sind Tags. VictoriaMetrics: Metrik ``<tabelle>_wert`` mit den
Labels projekt und variable.

Werte ohne Gültigkeit (NaN, z. B. Verbindungsausfall) werden nicht geschrieben. Mit "nur Änderungen" wird ein Wert
nur geschrieben, wenn er sich geändert hat, spätestens aber alle ``HEARTBEAT_S`` Sekunden.

Treiber (nur für den gewählten Typ nötig): SQLite ist in Python enthalten; MariaDB: ``PyMySQL``;
TimescaleDB/PostgreSQL: ``psycopg`` (Version 3, ``pip install "psycopg[binary]"``); QuestDB, InfluxDB 3 und VictoriaMetrics:
keine Bibliothek nötig (HTTP-Schnittstelle, Standardports 9000, 8181 bzw. 8428).
"""
import base64
import collections
import csv
import datetime
import io
import itertools
import json
import math
import os
import re
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request

from plc_common import BASE_DIR
from plc_i18n import N_, tr

# Datenbanktypen: Schlüssel in der Konfigurationsdatei -> Anzeige.
DB_TYPES = {"": N_("Keine"), "sqlite": N_("SQLite (Datei)"), "mariadb": N_("MariaDB / MySQL"),
            "timescale": N_("TimescaleDB / PostgreSQL"), "questdb": N_("QuestDB"),
            "influxdb3": N_("InfluxDB 3 Core"), "victoriametrics": N_("VictoriaMetrics")}
DEFAULT_PORTS = {"mariadb": 3306, "timescale": 5432, "questdb": 9000, "influxdb3": 8181, "victoriametrics": 8428}
# Datenbanken, die über ihre HTTP-Schnittstelle angesprochen werden (Feld Server darf eine URL sein)
HTTP_TYPES = ("questdb", "influxdb3", "victoriametrics")
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
    who = (s["user"] + "@") if s["user"] else ""
    if s["typ"] == "questdb":
        return f"QuestDB {who}{server_url(s)} › {s['tabelle']}"
    if s["typ"] == "influxdb3":
        return f"InfluxDB 3 {who}{server_url(s)}/{s['name']} › {s['tabelle']}"
    if s["typ"] == "victoriametrics":
        return f"VictoriaMetrics {who}{server_url(s)} › {vm_metric(s['tabelle'])}"
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


# ---- Datenbanken mit HTTP-Schnittstelle (QuestDB, InfluxDB 3, VictoriaMetrics), ohne Zusatzbibliothek.
# Alle drei nehmen Messwerte im InfluxDB Line Protocol an: eine Zeile je Wert,
#   <tabelle>[,projekt=<Projekt>],variable=<Variable> wert=<Wert> <Zeit in ns>
_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
_US = datetime.timedelta(microseconds=1)


def server_url(s):
    """Basis-URL eines HTTP-Datenbankservers. Im Feld Server darf auch eine vollständige URL stehen
    (z. B. https://server:8181)."""
    host = s["host"].strip().rstrip("/")
    if host.lower().startswith(("http://", "https://")):
        return host
    return f"http://{host}:{s['port']}"


questdb_url = server_url            # früherer Name


def vm_metric(table):
    """Name der Metrik in VictoriaMetrics: Messung (Tabelle) + "_" + Feld (wert)."""
    return f"{table}_wert"


def _http_error_text(e):
    """Fehlermeldung aus der Antwort des Servers (JSON mit "error" bzw. "message") oder der Rohtext."""
    try:
        body = e.read().decode("utf-8", "replace")
    except Exception:
        return str(e.reason)
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            return str(data.get("error") or data.get("message") or body)
        return body.strip()[:300]
    except ValueError:
        return body.strip()[:300] or str(e.reason)


class HttpDbError(RuntimeError):
    """Fehlerantwort eines HTTP-Datenbankservers (``code`` = HTTP-Status)."""

    def __init__(self, label, code, text):
        super().__init__(f"{label} HTTP {code}: {text}")
        self.code = code


def _ilp_tag(text):
    """Wert für ein Tag im InfluxDB Line Protocol: \\ , = und Leerzeichen maskieren (Zeilenumbruch nicht erlaubt)."""
    text = str(text).replace("\r", " ").replace("\n", " ")
    return text.replace("\\", "\\\\").replace(",", "\\,").replace("=", "\\=").replace(" ", "\\ ")


def _ilp_lines(table, rows):
    """Messzeilen (zeit, projekt, variable, wert) als InfluxDB Line Protocol (Zeitstempel in Nanosekunden)."""
    out = []
    for z, p, v, w in rows:
        ns = (z - _EPOCH) // _US * 1000             # ganzzahlig, ohne Rundungsfehler
        proj = f",projekt={_ilp_tag(p)}" if p else ""   # leerer Projektname: Tag weglassen (NULL bzw. ohne Label)
        out.append(f"{table}{proj},variable={_ilp_tag(v) or '_'} wert={float(w)!r} {ns}\n")
    return "".join(out)


def _sql_literal(v):
    """Python-Wert als QuestDB-SQL-Literal (die HTTP-Schnittstelle kennt keine Parameter)."""
    if v is None:
        return "null"
    if isinstance(v, datetime.datetime):
        return "'" + v.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ") + "'"
    if isinstance(v, (int, float)):
        if isinstance(v, float) and not math.isfinite(v):
            return "null"
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def _bind(sql, params):
    """Platzhalter ? (außerhalb von '…') der Reihe nach durch die Literale von ``params`` ersetzen."""
    params = list(params)
    out, quoted, k = [], False, 0
    for ch in sql:
        if ch == "'":
            quoted = not quoted
        elif ch == "?" and not quoted:
            if k >= len(params):
                raise ValueError("SQL: zu wenige Parameter")
            out.append(_sql_literal(params[k]))
            k += 1
            continue
        out.append(ch)
    if k != len(params):
        raise ValueError("SQL: zu viele Parameter")
    return "".join(out)


class _HttpDb:
    """Gemeinsame Grundlage der HTTP-Datenbanken: Basis-URL, Anmeldung, Anfragen, Fehlermeldungen.

    Anmeldung: Benutzer + Passwort -> HTTP Basic; nur Passwort (ohne Benutzer) -> Token (``Authorization: Bearer``,
    z. B. InfluxDB-3-Token oder QuestDB Enterprise); beides leer -> ohne Anmeldung."""
    label = "HTTP"
    write_path = "/write"

    def __init__(self, s, timeout=10.0):
        self.s = s
        self.url = server_url(s)
        self.timeout = timeout
        self.headers = {}
        if s["user"]:
            auth = base64.b64encode(f"{s['user']}:{s['passwort']}".encode("utf-8")).decode("ascii")
            self.headers["Authorization"] = "Basic " + auth
        elif s["passwort"]:
            self.headers["Authorization"] = "Bearer " + s["passwort"]

    def open(self, path, params=None, data=None, timeout=None, content_type="text/plain; charset=utf-8"):
        """Anfrage senden (mit ``data`` als POST); ``params`` als Dict oder Liste von Paaren (mehrfache Namen)."""
        url = self.url + path + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, data=data, headers=dict(self.headers),
                                     method="POST" if data is not None else "GET")
        if data is not None:
            req.add_header("Content-Type", content_type)
        try:
            return urllib.request.urlopen(req, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as e:
            raise HttpDbError(self.label, e.code, _http_error_text(e)) from None

    def get_json(self, path, params=None, data=None, timeout=None):
        with self.open(path, params, data=data, timeout=timeout,
                       content_type="application/json") as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")

    def write_params(self):
        return None

    def write(self, lines):
        """Zeilen im InfluxDB Line Protocol schreiben (eine Anfrage je Stapel)."""
        with self.open(self.write_path, self.write_params(), data=lines.encode("utf-8"),
                       timeout=max(self.timeout, 30.0)) as resp:
            resp.read()

    def csv_query(self, sql):
        """SQL-Abfrage, Ergebnis als CSV-Strom (Antwortobjekt) – nur für Datenbanken mit SQL."""
        raise NotImplementedError

    def cursor(self):
        return _CsvCursor(self)

    def close(self):
        pass                                            # zustandslos (jede Anfrage eine eigene HTTP-Verbindung)


class QuestDbHttp(_HttpDb):
    """QuestDB: ``exec()`` führt SQL aus (/exec), Schreiben über /write, Lesen als CSV über /exp."""
    label = "QuestDB"

    def exec(self, sql):
        """SQL-Befehl ausführen (z. B. CREATE TABLE); Rückgabe: Antwort als Dict."""
        with self.open("/exec", {"query": sql}) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
        if data.get("error"):
            raise RuntimeError(f"QuestDB: {data['error']}")
        return data

    def csv_query(self, sql):
        return self.open("/exp", {"query": sql}, timeout=120.0)


class InfluxDb3Http(_HttpDb):
    """InfluxDB 3 Core/Enterprise (Standardport 8181): Schreiben über /api/v3/write_lp, SQL über /api/v3/query_sql
    (Ergebnis als CSV), Datenbank und Tabelle anlegen über /api/v3/configure/…"""
    label = "InfluxDB"
    write_path = "/api/v3/write_lp"

    def write_params(self):
        return {"db": self.s["name"]}

    def configure(self, what, body):
        """Datenbank bzw. Tabelle anlegen. Rückgabe: True = angelegt, False = gab es schon."""
        try:
            with self.open(f"/api/v3/configure/{what}", data=json.dumps(body).encode("utf-8"),
                           content_type="application/json") as resp:
                resp.read()
            return True
        except HttpDbError as e:
            if e.code == 409:                           # existiert bereits
                return False
            raise

    def csv_query(self, sql):
        return self.open("/api/v3/query_sql", {"db": self.s["name"], "q": sql, "format": "csv"}, timeout=120.0)


class VictoriaMetricsHttp(_HttpDb):
    """VictoriaMetrics (Standardport 8428): Schreiben über /write (Line Protocol, die Metrik heißt
    <tabelle>_wert, projekt und variable werden Labels), Lesen über die Prometheus-Schnittstelle /api/v1/…"""
    label = "VictoriaMetrics"


class _CsvCursor:
    """Abfrage mit CSV-Ergebnis (QuestDB /exp, InfluxDB /api/v3/query_sql): das Ergebnis kommt als Strom und wird
    stückweise gelesen (auch sehr große Ergebnisse). Alle Werte kommen als Text (die Aufrufer wandeln mit float/int
    um); leere Felder werden zu None. Die HTTP-Schnittstellen kennen keine Parameter: ``?`` wird durch Literale ersetzt."""

    def __init__(self, http):
        self.http = http
        self._resp = None
        self._rows = iter(())

    def execute(self, sql, params=()):
        self.close()
        self._resp = self.http.csv_query(_bind(sql, params))
        self._rows = csv.reader(io.TextIOWrapper(self._resp, encoding="utf-8", newline=""))
        next(self._rows, None)                          # Kopfzeile mit den Spaltennamen

    def fetchmany(self, n):
        return [tuple(None if v == "" else v for v in row) for row in itertools.islice(self._rows, n) if row]

    def fetchall(self):
        out = []
        while True:
            chunk = self.fetchmany(20000)
            if not chunk:
                return out
            out.extend(chunk)

    def close(self):
        if self._resp is not None:
            try:
                self._resp.close()
            except Exception:
                pass
            self._resp = None
        self._rows = iter(())


class QuestDbBackend(_Backend):
    """QuestDB: Tabelle per SQL anlegen (zeitlich partitioniert, projekt/variable als SYMBOL), Werte im InfluxDB Line
    Protocol über HTTP schreiben. Mit Deduplizierung führt ein wiederholt gesendeter Stapel (z. B. nach einer
    Zeitüberschreitung) nicht zu doppelten Zeilen."""

    def connect(self):
        con = QuestDbHttp(self.s)
        table = (f"CREATE TABLE IF NOT EXISTS {self.t} (zeit TIMESTAMP, projekt SYMBOL, variable SYMBOL, wert DOUBLE) "
                 "TIMESTAMP(zeit) PARTITION BY DAY")
        try:
            con.exec(table + " WAL DEDUP UPSERT KEYS(zeit, projekt, variable)")
        except RuntimeError as e:
            con.exec(table)                             # ältere QuestDB (vor 7.3) kennt WAL/DEDUP nicht
            self.note = tr("ohne Deduplizierung: {0}").format(str(e).splitlines()[0])
        self.con = con

    def insert(self, rows):
        self.con.write(_ilp_lines(self.t, rows))


class InfluxDb3Backend(_Backend):
    """InfluxDB 3: Datenbank und Tabelle (Tags projekt, variable; Feld wert) anlegen, Werte im Line Protocol schreiben.
    Gleiche Serie und gleicher Zeitpunkt überschreiben sich – ein wiederholt gesendeter Stapel ergibt keine Dubletten."""

    def connect(self):
        con = InfluxDb3Http(self.s)
        con.configure("database", {"db": self.s["name"]})
        try:
            con.configure("table", {"db": self.s["name"], "table": self.t, "tags": ["projekt", "variable"],
                                    "fields": [{"name": "wert", "type": "float64"}]})
        except HttpDbError as e:
            if e.code in (401, 403):
                raise
            # Tabelle nicht vorab angelegt (z. B. ältere Version): InfluxDB legt sie beim ersten Schreiben an
            self.note = tr("Tabelle wird beim ersten Schreiben angelegt ({0})").format(str(e).splitlines()[0])
        self.con = con

    def insert(self, rows):
        self.con.write(_ilp_lines(self.t, rows))


class VictoriaMetricsBackend(_Backend):
    """VictoriaMetrics: nichts anzulegen (Metrik <tabelle>_wert entsteht beim Schreiben); Werte im Line Protocol."""

    def connect(self):
        con = VictoriaMetricsHttp(self.s)
        con.get_json("/api/v1/labels")                  # erreichbar und Anmeldung gültig?
        self.note = tr("Metrik {0}, Labels projekt und variable").format(vm_metric(self.t))
        self.con = con

    def insert(self, rows):
        self.con.write(_ilp_lines(self.t, rows))


BACKENDS = {"sqlite": SqliteBackend, "mariadb": MariaDbBackend, "timescale": TimescaleBackend,
            "questdb": QuestDbBackend, "influxdb3": InfluxDb3Backend, "victoriametrics": VictoriaMetricsBackend}


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


# ---------------------------------------------------------------------------------------
# Lesemodus: Aufzeichnungen aus der Datenbank wieder laden (Logger › Datei › Aus Datenbank laden …)
# ---------------------------------------------------------------------------------------
# Zeitstempel werden in der Datenbank als Unix-Zeit (Sekunden, UTC) berechnet, damit alle Typen dieselbe Zeitbasis
# liefern. Lange Zeiträume lassen sich serverseitig zu Mittelwerten je Zeitraster zusammenfassen (weniger Daten über das
# Netz, flüssige Anzeige).
MAX_LOAD_VALUES = 20_000_000    # Höchstzahl gelesener Werte (Speicherschutz); darüber -> Mittelwerte wählen
AUTO_POINTS = 20_000            # "Automatisch": Ziel-Höchstzahl Punkte je Variable
RASTER_STEPS = (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400)


class LoadCancelled(Exception):
    """Laden wurde abgebrochen."""


def nice_raster(span_s, points=AUTO_POINTS):
    """Kleinstes "rundes" Zeitraster (s), mit dem ein Zeitraum höchstens ``points`` Punkte ergibt (0 = Rohdaten)."""
    need = span_s / max(points, 1)
    if need <= 0.5:
        return 0
    for step in RASTER_STEPS:
        if step >= need:
            return step
    return int(math.ceil(need / 86400.0)) * 86400


class _ReadSql:
    """SQL-Bausteine je Datenbanktyp für das Lesen (Platzhalter, Zeitspalte, Unix-Zeit, Zeitgrenzen)."""
    ph = "?"
    time_col = "zeit"

    def epoch(self):                # Ausdruck: Unix-Zeit der Spalte zeit (float, Sekunden)
        raise NotImplementedError

    def bound(self, epoch):         # Python-Wert für einen Vergleich mit der Spalte zeit
        raise NotImplementedError

    def table(self, t):
        return t

    def floor(self, expr):          # ganzzahliger Anteil (Zeit >= 0)
        return f"FLOOR({expr})"

    def project_cond(self, project):    # Bedingung und Parameter für den Projektnamen
        return f"projekt = {self.ph}", [project]

    def raster_sql(self, t, where, r):  # Spalten: Rasternummer (Unix-Zeit / r), variable, Mittelwert; nach Zeit sortiert
        bucket = self.floor(f"{self.epoch()} / {r!r}")
        return f"SELECT {bucket} AS b, variable, AVG(wert) FROM {t}{where} GROUP BY b, variable ORDER BY b"


class _SqliteSql(_ReadSql):
    ph = "?"

    def floor(self, expr):          # FLOOR fehlt in manchen SQLite-Versionen; CAST schneidet ab (für Zeiten >= 0 gleich)
        return f"CAST({expr} AS INTEGER)"

    def epoch(self):
        # exakt auf Millisekunden (julianday wäre als Gleitkommazahl um einige µs ungenau)
        return "(CAST(strftime('%s', zeit) AS INTEGER) + CAST(substr(zeit, 21, 3) AS INTEGER) / 1000.0)"

    def bound(self, epoch):
        z = datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)
        return z.strftime("%Y-%m-%d %H:%M:%S.") + f"{z.microsecond // 1000:03d}"


class _MariaSql(_ReadSql):
    ph = "%s"

    def epoch(self):
        return "UNIX_TIMESTAMP(zeit)"            # Sitzungszeitzone wird auf UTC gestellt (siehe DbReader.connect)

    def bound(self, epoch):
        return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).replace(tzinfo=None)

    def table(self, t):
        return f"`{t}`"


class _PgSql(_ReadSql):
    ph = "%s"

    def epoch(self):
        return "EXTRACT(EPOCH FROM zeit)::double precision"

    def bound(self, epoch):
        return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)

    def table(self, t):
        return f'"{t}"'


class _QuestSql(_ReadSql):
    ph = "?"                        # QuestDbHttp setzt die Werte selbst als Literale ein

    def epoch(self):
        return "(cast(zeit AS long) / 1000000.0)"       # Zeitstempel = Mikrosekunden seit 1970

    def bound(self, epoch):
        return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)

    def project_cond(self, project):
        if not project:                                 # leerer Projektname wird als NULL geschrieben
            return "projekt IS NULL", []
        return super().project_cond(project)

    def raster_sql(self, t, where, r):
        # SAMPLE BY: QuestDB-eigene Zeitraster (Zeitstempel = Beginn des Rasters); Einheit T = Millisekunden
        ms = max(int(round(r * 1000)), 1)
        inner = f"SELECT zeit, variable, avg(wert) AS m FROM {t}{where} SAMPLE BY {ms}T ALIGN TO CALENDAR"
        return f"SELECT cast(zeit AS long) / 1000000.0 / {r!r} AS b, variable, m FROM ({inner}) ORDER BY b, variable"


class _InfluxSql(_QuestSql):
    """InfluxDB 3 (SQL von Apache DataFusion): Zeitspalte ``time`` (Nanosekunden); leerer Projektname = NULL und
    Literale statt Parameter wie bei QuestDB."""
    time_col = "time"

    def epoch(self):
        return "(CAST(time AS BIGINT) / 1000000000.0)"

    def table(self, t):
        return f'"{t}"'

    def raster_sql(self, t, where, r):
        # date_bin: Zeitraster ab 1970-01-01 (Zeitstempel = Beginn des Rasters)
        ms = max(int(round(r * 1000)), 1)
        bucket = f"date_bin(INTERVAL '{ms} milliseconds', time)"
        return (f"SELECT CAST({bucket} AS BIGINT) / 1000000000.0 / {r!r} AS b, variable, avg(wert) "
                f"FROM {t}{where} GROUP BY 1, 2 ORDER BY 1, 2")


_READ_SQL = {"sqlite": _SqliteSql, "mariadb": _MariaSql, "timescale": _PgSql, "questdb": _QuestSql,
             "influxdb3": _InfluxSql}


class DbReader:
    """Liest Aufzeichnungen aus der Datenbank der Konfiguration (nur lesend, legt nichts an).

    Ablauf: ``connect()``, ``projects()``, ``variables(projekt)`` (Name, erster/letzter Zeitpunkt, Anzahl),
    ``count(...)`` und ``load(...)`` -> (Zeiten, Namen, Spalten) wie beim Laden einer CSV-Datei; ``close()``.
    ``conn`` ist das Verbindungs-Dict der Konfiguration; ``sqlite_file`` liest stattdessen eine andere SQLite-Datei."""

    def __init__(self, conn, sqlite_file=None):
        s = dict(db_settings(conn))
        if sqlite_file:
            s["typ"], s["datei"] = "sqlite", sqlite_file
        if not s["typ"]:
            raise ValueError(tr("In der Konfiguration ist keine Datenbank eingestellt."))
        if not check_table_name(s["tabelle"]):
            raise ValueError(tr("Ungültiger Tabellenname: {0!r} (nur Buchstaben, Ziffern, _)").format(s['tabelle']))
        self.s = s
        self.sql = _READ_SQL[s["typ"]]()
        self.t = self.sql.table(s["tabelle"])
        self.con = None

    def describe(self):
        return describe(self.s)

    def connect(self):
        s = self.s
        if s["typ"] == "sqlite":
            if not os.path.exists(s["datei"]):
                raise FileNotFoundError(tr("Datenbankdatei nicht gefunden: {0}").format(s["datei"]))
            # nur lesend öffnen (die Aufzeichnung darf gleichzeitig weiterschreiben)
            uri = "file:" + s["datei"].replace("\\", "/").replace("?", "%3F").replace("#", "%23") + "?mode=ro"
            self.con = sqlite3.connect(uri, uri=True, timeout=10, check_same_thread=False)
        elif s["typ"] == "mariadb":
            import pymysql
            self.con = pymysql.connect(host=s["host"], port=s["port"], user=s["user"], password=s["passwort"],
                                       database=s["name"], charset="utf8mb4", connect_timeout=5)
            with self.con.cursor() as cur:
                cur.execute("SET time_zone = '+00:00'")
        elif s["typ"] == "questdb":
            self.con = QuestDbHttp(s)
        elif s["typ"] == "influxdb3":
            self.con = InfluxDb3Http(s)
        else:
            import psycopg
            self.con = psycopg.connect(host=s["host"], port=s["port"], dbname=s["name"], user=s["user"] or None,
                                       password=s["passwort"] or None, connect_timeout=5, autocommit=True)
        return self

    def close(self):
        if self.con is not None:
            try:
                self.con.close()
            except Exception:
                pass
            self.con = None

    def _query(self, sql, params=(), each=None, cancel=None):
        """SQL ausführen; mit ``each`` werden die Zeilen stückweise übergeben (Speicher sparen), sonst als Liste."""
        cur = self.con.cursor()
        try:
            cur.execute(sql, tuple(params))
            if each is None:
                return list(cur.fetchall())
            while True:
                if cancel is not None and cancel():
                    raise LoadCancelled()
                chunk = cur.fetchmany(20000)
                if not chunk:
                    return None
                each(chunk)
        finally:
            try:
                cur.close()
            except Exception:
                pass

    def _where(self, project, t0=None, t1=None, names=None):
        ph, cond, params = self.sql.ph, [], []
        if project is not None:
            c, p = self.sql.project_cond(project)
            cond.append(c)
            params.extend(p)
        tc = self.sql.time_col
        if t0 is not None:
            cond.append(f"{tc} >= {ph}")
            params.append(self.sql.bound(t0))
        if t1 is not None:
            cond.append(f"{tc} <= {ph}")
            params.append(self.sql.bound(t1))
        if names:
            cond.append("variable IN (" + ", ".join([ph] * len(names)) + ")")
            params.extend(names)
        return (" WHERE " + " AND ".join(cond)) if cond else "", params

    # ---- Übersicht
    def projects(self):
        """Projektnamen in der Tabelle (leerer Name möglich)."""
        rows = self._query(f"SELECT DISTINCT projekt FROM {self.t}")
        return sorted("" if r[0] is None else str(r[0]) for r in rows)

    def variables(self, project=None):
        """[(Name, erster Zeitpunkt, letzter Zeitpunkt, Anzahl Werte)] (Zeit als Unix-Zeit); project=None: alle."""
        where, params = self._where(project)
        ep = self.sql.epoch()
        rows = self._query(f"SELECT variable, MIN({ep}), MAX({ep}), COUNT(*) FROM {self.t}{where} "
                           f"GROUP BY variable ORDER BY variable", params)
        return [(str(n), float(a), float(b), int(c)) for n, a, b, c in rows if a is not None]

    def count(self, names, t0, t1, project=None):
        """Anzahl Werte der gewählten Variablen im Zeitraum."""
        where, params = self._where(project, t0, t1, names)
        return int(self._query(f"SELECT COUNT(*) FROM {self.t}{where}", params)[0][0] or 0)

    # ---- Laden
    def load(self, names, t0, t1, project=None, raster_s=0, hold=False, cancel=None, progress=None):
        """Werte der Variablen ``names`` im Zeitraum [t0, t1] (Unix-Zeit) laden.

        raster_s > 0: Mittelwert je Zeitraster (Sekunden), Zeitstempel = Mitte des Rasters. hold: fehlende Werte mit
        dem letzten Wert füllen (für Aufzeichnungen mit "nur Änderungen"). Rückgabe: (Zeiten, Namen, Spalten) als
        numpy-Arrays bzw. Liste; Spalten[k][i] = Wert von names[k] zur Zeit i (NaN = kein Wert)."""
        import numpy as np
        names = list(dict.fromkeys(names))
        if not names:
            raise ValueError(tr("Keine Variable gewählt."))
        where, params = self._where(project, t0, t1, names)
        ep = self.sql.epoch()
        if raster_s and raster_s > 0:
            r = float(raster_s)
            sql = self.sql.raster_sql(self.t, where, r)
        else:
            r = 0.0
            sql = f"SELECT {ep} AS e, variable, wert FROM {self.t}{where} ORDER BY e"
        col_of = {n: k for k, n in enumerate(names)}
        times, idx, vals = [], [], []        # Zeitachse; je Wert (Zeilenindex, Spalte, Wert)
        state = {"last": None, "n": 0}

        def each(chunk):
            for key, var, val in chunk:
                k = col_of.get(var)
                if k is None or key is None:
                    continue
                key = float(key)
                ts = (key + 0.5) * r if r else round(key, 3)
                if ts != state["last"]:
                    times.append(ts)
                    state["last"] = ts
                idx.append(len(times) - 1)
                vals.append((k, float("nan") if val is None else float(val)))
            state["n"] += len(chunk)
            if state["n"] > MAX_LOAD_VALUES:
                raise MemoryError(tr("Mehr als {0} Werte – bitte einen kürzeren Zeitraum oder Mittelwerte wählen.")
                                  .format(f"{MAX_LOAD_VALUES:,}".replace(",", ".")))
            if progress is not None:
                progress(state["n"])

        self._query(sql, params, each=each, cancel=cancel)
        t = np.asarray(times, dtype=float)
        cols = np.full((len(names), len(times)), np.nan)
        if vals:
            rows = np.asarray(idx, dtype=np.int64)
            ks = np.fromiter((k for k, _v in vals), dtype=np.int64, count=len(vals))
            vs = np.fromiter((v for _k, v in vals), dtype=float, count=len(vals))
            cols[ks, rows] = vs
        if hold and len(times):
            cols = _hold(cols)
        return t, names, cols


def _prom_str(text):
    """Text als Zeichenkette in einem PromQL/MetricsQL-Selektor ("…" mit maskiertem \\ und ")."""
    text = str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{text}"'


class VmReader:
    """Lesemodus für VictoriaMetrics (keine SQL-Datenbank): gleiche Schnittstelle wie ``DbReader``, gelesen über die
    Prometheus-Schnittstelle. Rohdaten über /api/v1/export, Mittelwerte je Zeitraster über /api/v1/query_range.

    Die Werte liegen in der Metrik <tabelle>_wert mit den Labels projekt und variable; ein leerer Projektname ist
    eine Serie ohne Label projekt (im Selektor: projekt="")."""

    def __init__(self, conn):
        s = dict(db_settings(conn))
        if not check_table_name(s["tabelle"]):
            raise ValueError(tr("Ungültiger Tabellenname: {0!r} (nur Buchstaben, Ziffern, _)").format(s['tabelle']))
        self.s = s
        self.metric = vm_metric(s["tabelle"])
        self.con = None

    def describe(self):
        return describe(self.s)

    def connect(self):
        self.con = VictoriaMetricsHttp(self.s)
        self.con.get_json("/api/v1/labels")
        return self

    def close(self):
        self.con = None

    # ---- Hilfen
    def _sel(self, project=None, name=None):
        parts = [f"__name__={_prom_str(self.metric)}"]
        if project is not None:
            parts.append(f"projekt={_prom_str(project)}")
        if name is not None:
            parts.append(f"variable={_prom_str(name)}")
        return "{" + ",".join(parts) + "}"

    def _data(self, path, params):
        res = self.con.get_json(path, params, timeout=120.0)
        if res.get("status") not in (None, "success"):
            raise RuntimeError(f"VictoriaMetrics: {res.get('error') or res}")
        return res.get("data")

    def _instant(self, query, at=None):
        """Sofortabfrage -> [(Labels, Wert)]."""
        params = {"query": query}
        if at is not None:
            params["time"] = f"{at:.3f}"
        data = self._data("/api/v1/query", params) or {}
        return [(r.get("metric", {}), float(r["value"][1])) for r in data.get("result", [])]

    @staticmethod
    def _all_time():
        """Rückblick-Fenster bis 1970 (VictoriaMetrics durchsucht sonst nur den letzten Tag bzw. das Fenster)."""
        import time
        return int(time.time()) + 86400

    # ---- Übersicht
    def projects(self):
        span = {"start": "0", "match[]": self._sel()}
        names = [str(p) for p in (self._data("/api/v1/label/projekt/values", span) or [])]
        if self._data("/api/v1/series", {"start": "0", "match[]": self._sel("")}):
            names.append("")                            # Serien ohne Label projekt
        return sorted(set(names))

    def variables(self, project=None):
        sel, w = self._sel(project), f"{self._all_time()}s"
        count = {m.get("variable"): v for m, v in self._instant(f"sum by (variable) (count_over_time({sel}[{w}]))")}
        first = {m.get("variable"): v for m, v in self._instant(f"min by (variable) (tfirst_over_time({sel}[{w}]))")}
        last = {m.get("variable"): v for m, v in self._instant(f"max by (variable) (tlast_over_time({sel}[{w}]))")}
        return [(str(n), first.get(n, last[n]), last[n], int(count.get(n, 0)))
                for n in sorted(last) if n is not None]

    def count(self, names, t0, t1, project=None):
        w = max(int(math.ceil(t1 - t0)), 1)
        total = 0
        for n in dict.fromkeys(names):
            total += sum(v for _m, v in self._instant(f"sum(count_over_time({self._sel(project, n)}[{w}s]))", at=t1))
        return int(total)

    # ---- Laden
    def load(self, names, t0, t1, project=None, raster_s=0, hold=False, cancel=None, progress=None):
        """Wie ``DbReader.load``: (Zeiten, Namen, Spalten); raster_s > 0 = Mittelwerte, Zeit = Mitte des Rasters."""
        import numpy as np
        names = list(dict.fromkeys(names))
        if not names:
            raise ValueError(tr("Keine Variable gewählt."))
        series = []                                     # (Spalte, Zeiten in s, Werte)
        n_total = 0

        def check(n):
            nonlocal n_total
            if cancel is not None and cancel():
                raise LoadCancelled()
            n_total += n
            if n_total > MAX_LOAD_VALUES:
                raise MemoryError(tr("Mehr als {0} Werte – bitte einen kürzeren Zeitraum oder Mittelwerte wählen.")
                                  .format(f"{MAX_LOAD_VALUES:,}".replace(",", ".")))
            if progress is not None:
                progress(n_total)

        if raster_s and raster_s > 0:
            r = float(raster_s)
            ms = max(int(round(r * 1000)), 1)
            for k, n in enumerate(names):
                sel = self._sel(project, n)
                # Mittelwert über alle Serien der Variable (bei "alle Projekte" mehrere): Summe / Anzahl
                q = f"sum(sum_over_time({sel}[{ms}ms])) / sum(count_over_time({sel}[{ms}ms]))"
                data = self._data("/api/v1/query_range", {"query": q, "start": f"{t0 + r:.3f}",
                                                          "end": f"{t1 + r:.3f}", "step": f"{ms}ms"}) or {}
                for res in data.get("result", []):
                    pts = res.get("values", [])
                    # Wert zur Zeit t = Mittel über (t - r, t] -> Zeitstempel = Mitte des Rasters
                    ts = np.fromiter((float(p[0]) - r / 2 for p in pts), dtype=float, count=len(pts))
                    vs = np.fromiter((float(p[1]) for p in pts), dtype=float, count=len(pts))
                    series.append((k, ts, vs))
                    check(len(pts))
        else:
            col_of = {n: k for k, n in enumerate(names)}
            params = [("match[]", self._sel(project, n)) for n in names]
            params += [("start", f"{t0:.3f}"), ("end", f"{t1:.3f}")]
            with self.con.open("/api/v1/export", params, timeout=120.0) as resp:
                for line in io.TextIOWrapper(resp, encoding="utf-8"):
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    k = col_of.get(item.get("metric", {}).get("variable"))
                    if k is None:
                        continue
                    ts = np.asarray(item.get("timestamps", []), dtype=float) / 1000.0
                    vs = np.asarray([float("nan") if v is None else v for v in item.get("values", [])], dtype=float)
                    series.append((k, ts, vs))
                    check(len(ts))
        if series:
            t = np.unique(np.round(np.concatenate([ts for _k, ts, _v in series]), 3))
        else:
            t = np.zeros(0)
        cols = np.full((len(names), len(t)), np.nan)
        for k, ts, vs in series:
            cols[k, np.searchsorted(t, np.round(ts, 3))] = vs
        if hold and len(t):
            cols = _hold(cols)
        return t, names, cols


def create_reader(conn, sqlite_file=None):
    """Leser für die Datenbank der Konfiguration (bzw. eine SQLite-Datei): ``DbReader`` oder ``VmReader``."""
    if not sqlite_file and db_settings(conn)["typ"] == "victoriametrics":
        return VmReader(conn)
    return DbReader(conn, sqlite_file)


def _hold(cols):
    """Fehlende Werte (NaN) je Zeile mit dem zuletzt gültigen Wert füllen (vor dem ersten Wert bleibt NaN)."""
    import numpy as np
    out = cols.copy()
    n = out.shape[1]
    for k in range(out.shape[0]):
        row = out[k]
        valid = ~np.isnan(row)
        if not valid.any():
            continue
        pos = np.where(valid, np.arange(n), 0)
        np.maximum.accumulate(pos, out=pos)
        filled = row[pos]
        filled[: int(np.argmax(valid))] = np.nan
        out[k] = filled
    return out
