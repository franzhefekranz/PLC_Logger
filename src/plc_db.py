# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Aufzeichnung in eine Datenbank (zusätzlich oder statt CSV): SQLite, MariaDB/MySQL, TimescaleDB/PostgreSQL, QuestDB,
InfluxDB 3, VictoriaMetrics oder Prometheus.

Ein eigener Schreib-Thread (``DbWriter``) nimmt die Messzeilen vom Sammler-Thread des Recorders entgegen und schreibt
sie stapelweise (etwa einmal pro Sekunde) in die Datenbank. Netzwerk- oder Plattenwartezeiten der Datenbank bremsen
dadurch weder das Lesen aus der Steuerung noch die Oberfläche. Ist die Datenbank nicht erreichbar, bleiben die Werte
im Speicher (bis zu ``MAX_BUFFER`` Zeilen) und werden nach dem erneuten Verbinden nachgetragen.

Tabellenaufbau ("schmal", eine Zeile je Wert – geeignet für Grafana und TimescaleDB):

    zeit      Zeitpunkt der Messung in UTC (Millisekunden)
    projekt   Projektname aus der Konfiguration (mehrere Logger können eine Tabelle teilen)
    variable  Name der Variable
    wert      Messwert (Gleitkommazahl; BOOL = 0/1)

InfluxDB 3: Zeitspalte ``time``, projekt/variable sind Tags. VictoriaMetrics und Prometheus: Metrik
``<tabelle>_wert`` mit den Labels projekt und variable.

Prometheus wird über „Remote Write“ beschrieben (``/api/v1/write``, Protobuf + Snappy – beides hier ohne Bibliothek
umgesetzt, siehe ``prom_write_request`` und ``snappy_compress``). Der Server muss Remote Write annehmen: Start mit
``--web.enable-remote-write-receiver``. Prometheus nimmt Werte je Serie nur in zeitlicher Reihenfolge und nicht älter
als etwa eine Stunde an (sonst ``out_of_order_time_window`` in der Prometheus-Konfiguration setzen); abgelehnte Stapel
werden verworfen und gemeldet statt endlos wiederholt.

Werte ohne Gültigkeit (NaN, z. B. Verbindungsausfall) werden nicht geschrieben. Mit "nur Änderungen" wird ein Wert
nur geschrieben, wenn er sich geändert hat, spätestens aber alle ``HEARTBEAT_S`` Sekunden.

Treiber (nur für den gewählten Typ nötig): SQLite ist in Python enthalten; MariaDB: ``PyMySQL``;
TimescaleDB/PostgreSQL: ``psycopg`` (Version 3, ``pip install "psycopg[binary]"``); QuestDB, InfluxDB 3, VictoriaMetrics und
Prometheus: keine Bibliothek nötig (HTTP-Schnittstelle, Standardports 9000, 8181, 8428 bzw. 9090).
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
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from plc_common import BASE_DIR
from plc_i18n import N_, tr

# Datenbanktypen: Schlüssel in der Konfigurationsdatei -> Anzeige.
DB_TYPES = {"": N_("Keine"), "sqlite": N_("SQLite (Datei)"), "mariadb": N_("MariaDB / MySQL"),
            "timescale": N_("TimescaleDB / PostgreSQL"), "questdb": N_("QuestDB"),
            "influxdb3": N_("InfluxDB 3 Core"), "victoriametrics": N_("VictoriaMetrics"),
            "prometheus": N_("Prometheus (Remote Write)")}
DEFAULT_PORTS = {"mariadb": 3306, "timescale": 5432, "questdb": 9000, "influxdb3": 8181, "victoriametrics": 8428,
                 "prometheus": 9090}
# Datenbanken, die über ihre HTTP-Schnittstelle angesprochen werden (Feld Server darf eine URL sein)
HTTP_TYPES = ("questdb", "influxdb3", "victoriametrics", "prometheus")
# Datenbanken mit Metrik <tabelle>_wert und Labels statt einer Tabelle (Aufbewahrung stellt der Server selbst ein)
METRIC_TYPES = ("victoriametrics", "prometheus")
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
    if s["typ"] == "prometheus":
        return f"Prometheus {who}{server_url(s)} › {vm_metric(s['tabelle'])}"
    return f"{DB_TYPES.get(s['typ'], s['typ'])} {s['user']}@{s['host']}:{s['port']}/{s['name']} › {s['tabelle']}"


# ---------------------------------------------------------------------------------------
# Anbindungen je Datenbanktyp
# ---------------------------------------------------------------------------------------
class _Backend:
    """Gemeinsame Schnittstelle: connect() legt bei Bedarf die Tabelle an, insert() schreibt Zeilen
    (zeit als datetime in UTC, projekt, variable, wert), close() trennt."""
    note = ""

    def __init__(self, s):
        """Einstellungen ``s`` (siehe ``db_settings``) übernehmen; der Tabellenname wird geprüft, weil er direkt in
        SQL-Befehle eingesetzt wird.
        """
        self.s = s
        self.con = None
        if not check_table_name(s["tabelle"]):
            raise ValueError(tr("Ungültiger Tabellenname: {0!r} (nur Buchstaben, Ziffern, _)").format(s['tabelle']))
        self.t = s["tabelle"]

    def close(self):
        """Verbindung schließen (Fehler beim Schließen sind ohne Bedeutung)."""
        if self.con is not None:
            try:
                self.con.close()
            except Exception:
                pass
            self.con = None

    def cleanup(self, days=0, max_mb=0):
        """Alte Werte löschen (siehe plc_cleanup): älter als ``days`` Tage; ``max_mb`` nur, wo die Datenbank es
        unterstützt. Rückgabe: Meldungstext oder "" (nichts gelöscht). Ohne Unterstützung: ``NotImplementedError``."""
        raise NotImplementedError(tr("{0}: Aufbewahrungsdauer bitte in der Datenbank selbst einstellen").format(
            DB_TYPES.get(self.s["typ"], self.s["typ"])))

    @staticmethod
    def cutoff(days):
        """Zeitpunkt (UTC, datetime mit Zeitzone) vor ``days`` Tagen."""
        return datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)


class SqliteBackend(_Backend):
    """SQLite-Datei: Zeit als ISO-Text in UTC, WAL-Modus für gleichzeitiges Lesen, Index (variable, zeit)."""
    def connect(self):
        """Datei öffnen bzw. anlegen, Tabelle und Index anlegen, falls sie fehlen."""
        os.makedirs(os.path.dirname(self.s["datei"]) or ".", exist_ok=True)
        self.con = sqlite3.connect(self.s["datei"], timeout=10, check_same_thread=False)
        cur = self.con.cursor()
        cur.execute("PRAGMA journal_mode=WAL")          # gleichzeitiges Lesen (z. B. Grafana) während des Schreibens
        cur.execute(f"CREATE TABLE IF NOT EXISTS {self.t} (zeit TEXT NOT NULL, projekt TEXT, "
                    f"variable TEXT NOT NULL, wert REAL)")
        cur.execute(f"CREATE INDEX IF NOT EXISTS {self.t}_variable_zeit ON {self.t} (variable, zeit)")
        self.con.commit()

    def insert(self, rows):
        """Zeilen in einer Transaktion einfügen."""
        # SQLite kennt keinen Zeitstempeltyp: ISO-Text in UTC mit Millisekunden (sortierbar, von Grafana lesbar).
        data = [(z.strftime("%Y-%m-%d %H:%M:%S.") + f"{z.microsecond // 1000:03d}", p, v, w) for z, p, v, w in rows]
        self.con.executemany(f"INSERT INTO {self.t} (zeit, projekt, variable, wert) VALUES (?, ?, ?, ?)", data)
        self.con.commit()

    @staticmethod
    def _iso(z):
        """Zeit im Speicherformat der Tabelle (ISO-Text in UTC)."""
        return z.strftime("%Y-%m-%d %H:%M:%S.") + f"{z.microsecond // 1000:03d}"

    def used_bytes(self):
        """Von Daten belegter Platz der Datei (Seiten minus freie Seiten; die Datei selbst schrumpft nicht)."""
        cur = self.con.cursor()
        pages = cur.execute("PRAGMA page_count").fetchone()[0]
        free = cur.execute("PRAGMA freelist_count").fetchone()[0]
        size = cur.execute("PRAGMA page_size").fetchone()[0]
        return (pages - free) * size

    def cleanup(self, days=0, max_mb=0):
        """Zeilen älter als ``days`` Tage löschen; über ``max_mb`` jeweils den ältesten Tag, bis die Grenze eingehalten
        ist. Freigegebener Platz wird für neue Werte wiederverwendet (die Datei wird nicht kleiner)."""
        n = 0
        if days > 0:
            n += self.con.execute(f"DELETE FROM {self.t} WHERE zeit < ?", (self._iso(self.cutoff(days)),)).rowcount
            self.con.commit()
        if max_mb > 0:
            self.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            for _ in range(400):                       # höchstens 400 Tage je Durchlauf
                if self.used_bytes() <= max_mb * 1024 * 1024:
                    break
                first = self.con.execute(f"SELECT MIN(zeit) FROM {self.t}").fetchone()[0]
                if first is None:
                    break
                day = datetime.datetime.strptime(first[:10], "%Y-%m-%d") + datetime.timedelta(days=1)
                k = self.con.execute(f"DELETE FROM {self.t} WHERE zeit < ?", (day.strftime("%Y-%m-%d"),)).rowcount
                self.con.commit()
                self.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                n += k
        return tr("{0} alte Werte gelöscht").format(n) if n else ""


class MariaDbBackend(_Backend):
    """MariaDB/MySQL über PyMySQL: DATETIME(3) in UTC, InnoDB mit Indizes für Variable+Zeit und Zeit."""
    def connect(self):
        """Verbinden und die Tabelle anlegen, falls sie fehlt."""
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
        """Zeilen mit ``executemany`` in einer Transaktion einfügen (DATETIME ohne Zeitzone, Werte in UTC)."""
        data = [(z.replace(tzinfo=None), p, v, w) for z, p, v, w in rows]   # DATETIME ohne Zeitzone (UTC)
        with self.con.cursor() as cur:
            cur.executemany(f"INSERT INTO `{self.t}` (zeit, projekt, variable, wert) VALUES (%s, %s, %s, %s)", data)
        self.con.commit()

    def cleanup(self, days=0, max_mb=0):
        """Zeilen älter als ``days`` Tage löschen – in Portionen, damit die Tabelle nicht lange gesperrt ist."""
        if days <= 0:
            return ""
        limit, n = self.cutoff(days).replace(tzinfo=None), 0
        while True:
            with self.con.cursor() as cur:
                k = cur.execute(f"DELETE FROM `{self.t}` WHERE zeit < %s LIMIT 50000", (limit,))
            self.con.commit()
            n += k or 0
            if not k or k < 50000:
                break
        return tr("{0} alte Werte gelöscht").format(n) if n else ""


class TimescaleBackend(_Backend):
    """PostgreSQL/TimescaleDB über psycopg 3: TIMESTAMPTZ; mit TimescaleDB als Hypertable (zeitlich partitioniert)."""
    def connect(self):
        """Verbinden, Tabelle anlegen, nach Möglichkeit in eine Hypertable umwandeln und den Index anlegen."""
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
        """Zeilen in einer Transaktion einfügen."""
        with self.con.cursor() as cur:
            cur.executemany(f'INSERT INTO "{self.t}" (zeit, projekt, variable, wert) VALUES (%s, %s, %s, %s)', rows)
        self.con.commit()

    def cleanup(self, days=0, max_mb=0):
        """Daten älter als ``days`` Tage löschen: als Hypertable ganze Zeitabschnitte (drop_chunks), sonst DELETE."""
        if days <= 0:
            return ""
        limit = self.cutoff(days)
        with self.con.cursor() as cur:
            if self.note == "TimescaleDB-Hypertable":
                cur.execute("SELECT drop_chunks(%s, older_than => %s)", (self.t, limit))
                n = len(cur.fetchall())
                self.con.commit()
                return tr("{0} alte Zeitabschnitte gelöscht").format(n) if n else ""
            cur.execute(f'DELETE FROM "{self.t}" WHERE zeit < %s', (limit,))
            n = cur.rowcount
        self.con.commit()
        return tr("{0} alte Werte gelöscht").format(n) if n else ""


# ---- Datenbanken mit HTTP-Schnittstelle (QuestDB, InfluxDB 3, VictoriaMetrics), ohne Zusatzbibliothek.
# Alle drei nehmen Messwerte im InfluxDB Line Protocol an: eine Zeile je Wert,
#   <tabelle>[,projekt=<Projekt>],variable=<Variable> wert=<Wert> <Zeit in ns>
_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
_US = datetime.timedelta(microseconds=1)
_MS = datetime.timedelta(milliseconds=1)


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
        """Fehlertext „<Datenbank> HTTP <Status>: <Meldung>“; der Status bleibt in ``code`` für die Auswertung."""
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
        """Basis-URL und Anmeldekopf aus den Einstellungen bilden."""
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
        """Anfrage senden und die Antwort als JSON lesen."""
        with self.open(path, params, data=data, timeout=timeout,
                       content_type="application/json") as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")

    def write_params(self):
        """Zusätzliche Parameter der Schreibadresse (InfluxDB: Datenbankname); Standard: keine."""
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
        """Cursor im Stil von DB-API für SQL-Abfragen mit CSV-Ergebnis (siehe ``_CsvCursor``)."""
        return _CsvCursor(self)

    def close(self):
        """Nichts zu tun: jede Anfrage nutzt eine eigene HTTP-Verbindung."""
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
        """SQL-Abfrage über /exp; die Antwort ist eine CSV-Datei."""
        return self.open("/exp", {"query": sql}, timeout=120.0)


class InfluxDb3Http(_HttpDb):
    """InfluxDB 3 Core/Enterprise (Standardport 8181): Schreiben über /api/v3/write_lp, SQL über /api/v3/query_sql
    (Ergebnis als CSV), Datenbank und Tabelle anlegen über /api/v3/configure/…"""
    label = "InfluxDB"
    write_path = "/api/v3/write_lp"

    def write_params(self):
        """InfluxDB 3 braucht beim Schreiben den Namen der Datenbank."""
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
        """SQL-Abfrage über /api/v3/query_sql mit CSV-Ergebnis."""
        return self.open("/api/v3/query_sql", {"db": self.s["name"], "q": sql, "format": "csv"}, timeout=120.0)


class VictoriaMetricsHttp(_HttpDb):
    """VictoriaMetrics (Standardport 8428): Schreiben über /write (Line Protocol, die Metrik heißt
    <tabelle>_wert, projekt und variable werden Labels), Lesen über die Prometheus-Schnittstelle /api/v1/…"""
    label = "VictoriaMetrics"


class RejectedBatch(RuntimeError):
    """Der Server hat einen Stapel endgültig abgelehnt (z. B. Prometheus: Werte zu alt oder nicht in zeitlicher
    Reihenfolge). Wiederholen hilft nicht – der Stapel wird verworfen."""


# ---- Prometheus Remote Write: Protobuf und Snappy ohne Bibliothek
def _uvarint(n):
    """Zahl >= 0 als Varint (Protobuf, Snappy-Länge)."""
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _pb_bytes(field, data):
    """Protobuf-Feld mit Länge (Wire-Typ 2): Text, Bytes oder eingebettete Nachricht."""
    return _uvarint((field << 3) | 2) + _uvarint(len(data)) + data


def prom_write_request(series):
    """Prometheus ``WriteRequest`` (remote.proto) als Protobuf-Bytes.

    ``series``: [(Labels, Werte)] mit Labels = [(Name, Wert)] (wird nach Namen sortiert, leere Werte entfallen) und
    Werte = [(Zeit in ms, Wert)] in zeitlicher Reihenfolge."""
    out = bytearray()
    for labels, samples in series:
        ts = bytearray()
        for name, value in sorted(labels):
            if value != "":
                ts += _pb_bytes(1, _pb_bytes(1, name.encode("utf-8")) + _pb_bytes(2, str(value).encode("utf-8")))
        for ms, value in samples:
            # Sample: value (double, Feld 1, Wire-Typ 1) und timestamp (int64 als Varint, Feld 2)
            ts += _pb_bytes(2, b"\x09" + struct.pack("<d", float(value)) + b"\x10" + _uvarint(int(ms)))
        out += _pb_bytes(1, bytes(ts))
    return bytes(out)


def _snappy_literal(data):
    """Snappy-Element „Literal“ (unkomprimierte Bytes)."""
    n = len(data) - 1
    if n < 60:
        return bytes([n << 2]) + data
    for k, code in ((1, 60), (2, 61), (3, 62), (4, 63)):
        if n < 1 << (8 * k):
            return bytes([code << 2]) + n.to_bytes(k, "little") + data
    raise ValueError("Literal zu lang")


def snappy_compress(data):
    """Daten im Snappy-Blockformat komprimieren (einfaches Verfahren: Wiederholungen ab 4 Bytes werden als Kopie mit
    2-Byte-Abstand kodiert; das Ergebnis ist mit jedem Snappy-Dekoder lesbar)."""
    data = bytes(data)
    n = len(data)
    out = bytearray(_uvarint(n))
    table, i, lit = {}, 0, 0
    while i + 4 <= n:
        key = data[i:i + 4]
        cand = table.get(key)
        table[key] = i
        if cand is None or i - cand > 0xFFFF:
            i += 1
            continue
        m = 4
        while i + m < n and data[cand + m] == data[i + m]:
            m += 1
        if lit < i:
            out += _snappy_literal(data[lit:i])
        off, rest = i - cand, m
        while rest > 0:                                  # Kopie mit 2-Byte-Abstand: 1 … 64 Bytes je Element
            k = min(rest, 64)
            out += bytes([((k - 1) << 2) | 2]) + off.to_bytes(2, "little")
            rest -= k
        i += m
        lit = i
    if lit < n:
        out += _snappy_literal(data[lit:])
    return bytes(out)


class PrometheusHttp(_HttpDb):
    """Prometheus (Standardport 9090): Schreiben über Remote Write (/api/v1/write), Lesen über /api/v1/…"""
    label = "Prometheus"
    write_path = "/api/v1/write"

    def write_series(self, series):
        """Serien [(Labels, Werte)] per Remote Write senden. HTTP 400 (Werte abgelehnt) -> RejectedBatch."""
        body = snappy_compress(prom_write_request(series))
        url = self.url + self.write_path
        req = urllib.request.Request(url, data=body, headers=dict(self.headers), method="POST")
        req.add_header("Content-Type", "application/x-protobuf")
        req.add_header("Content-Encoding", "snappy")
        req.add_header("X-Prometheus-Remote-Write-Version", "0.1.0")
        try:
            with urllib.request.urlopen(req, timeout=max(self.timeout, 30.0)) as resp:
                resp.read()
        except urllib.error.HTTPError as e:
            text = _http_error_text(e)
            if e.code == 404:
                raise HttpDbError(self.label, e.code, tr("Remote Write ist nicht eingeschaltet (Prometheus mit "
                                                         "--web.enable-remote-write-receiver starten)")) from None
            if e.code == 400:
                raise RejectedBatch(f"{self.label} HTTP 400: {text}") from None
            raise HttpDbError(self.label, e.code, text) from None


class _CsvCursor:
    """Abfrage mit CSV-Ergebnis (QuestDB /exp, InfluxDB /api/v3/query_sql): das Ergebnis kommt als Strom und wird
    stückweise gelesen (auch sehr große Ergebnisse). Alle Werte kommen als Text (die Aufrufer wandeln mit float/int
    um); leere Felder werden zu None. Die HTTP-Schnittstellen kennen keine Parameter: ``?`` wird durch Literale ersetzt."""

    def __init__(self, http):
        """Cursor für die Verbindung ``http``; noch ohne Abfrage."""
        self.http = http
        self._resp = None
        self._rows = iter(())

    def execute(self, sql, params=()):
        """Abfrage senden (Parameter als Literale eingesetzt); die Kopfzeile des CSV wird übersprungen."""
        self.close()
        self._resp = self.http.csv_query(_bind(sql, params))
        self._rows = csv.reader(io.TextIOWrapper(self._resp, encoding="utf-8", newline=""))
        next(self._rows, None)                          # Kopfzeile mit den Spaltennamen

    def fetchmany(self, n):
        """Bis zu n weitere Zeilen; leere Felder werden zu None."""
        return [tuple(None if v == "" else v for v in row) for row in itertools.islice(self._rows, n) if row]

    def fetchall(self):
        """Alle restlichen Zeilen (in Blöcken gelesen)."""
        out = []
        while True:
            chunk = self.fetchmany(20000)
            if not chunk:
                return out
            out.extend(chunk)

    def close(self):
        """Antwortstrom schließen."""
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
        """Tabelle anlegen: zeitlich partitioniert, projekt/variable als SYMBOL, nach Möglichkeit mit Deduplizierung."""
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
        """Zeilen im Line Protocol über HTTP schreiben."""
        self.con.write(_ilp_lines(self.t, rows))

    def cleanup(self, days=0, max_mb=0):
        """Tagespartitionen löschen, die vollständig älter als ``days`` Tage sind (QuestDB löscht keine Einzelzeilen)."""
        if days <= 0:
            return ""
        limit = self.cutoff(days).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
        try:
            self.con.exec(f"ALTER TABLE {self.t} DROP PARTITION WHERE zeit < '{limit}'")
        except RuntimeError as e:
            if "no partitions" in str(e).lower() or "could not find" in str(e).lower():
                return ""
            raise
        return tr("alte Tagespartitionen gelöscht")


class InfluxDb3Backend(_Backend):
    """InfluxDB 3: Datenbank und Tabelle (Tags projekt, variable; Feld wert) anlegen, Werte im Line Protocol schreiben.
    Gleiche Serie und gleicher Zeitpunkt überschreiben sich – ein wiederholt gesendeter Stapel ergibt keine Dubletten."""

    def connect(self):
        """Datenbank und Tabelle anlegen (409 = gibt es schon); bei Rechtefehlern abbrechen."""
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
        """Zeilen im Line Protocol schreiben."""
        self.con.write(_ilp_lines(self.t, rows))


class VictoriaMetricsBackend(_Backend):
    """VictoriaMetrics: nichts anzulegen (Metrik <tabelle>_wert entsteht beim Schreiben); Werte im Line Protocol."""

    def connect(self):
        """Erreichbarkeit und Anmeldung prüfen (Abfrage der Labels)."""
        con = VictoriaMetricsHttp(self.s)
        con.get_json("/api/v1/labels")                  # erreichbar und Anmeldung gültig?
        self.note = tr("Metrik {0}, Labels projekt und variable").format(vm_metric(self.t))
        self.con = con

    def insert(self, rows):
        """Zeilen im Line Protocol schreiben (Metrik ``<tabelle>_wert``)."""
        self.con.write(_ilp_lines(self.t, rows))


class PrometheusBackend(_Backend):
    """Prometheus: nichts anzulegen (Metrik <tabelle>_wert entsteht beim Schreiben); Werte per Remote Write."""

    def connect(self):
        """Erreichbarkeit und Anmeldung prüfen (Versionsabfrage)."""
        con = PrometheusHttp(self.s)
        con.get_json("/api/v1/status/buildinfo")       # erreichbar und Anmeldung gültig?
        self.note = tr("Metrik {0}, Labels projekt und variable (Remote Write: Prometheus mit "
                       "--web.enable-remote-write-receiver starten)").format(vm_metric(self.t))
        self.con = con

    def insert(self, rows):
        """Zeilen (zeit, projekt, variable, wert) je Serie gruppiert und zeitlich geordnet senden."""
        groups = {}
        for z, p, v, w in rows:
            ms = (z - _EPOCH) // _MS
            groups.setdefault((p, v), []).append((ms, w))
        metric = vm_metric(self.t)
        series = [([("__name__", metric), ("projekt", p or ""), ("variable", v or "_")], sorted(samples))
                  for (p, v), samples in groups.items()]
        self.con.write_series(series)


BACKENDS = {"sqlite": SqliteBackend, "mariadb": MariaDbBackend, "timescale": TimescaleBackend,
            "questdb": QuestDbBackend, "influxdb3": InfluxDb3Backend, "victoriametrics": VictoriaMetricsBackend,
            "prometheus": PrometheusBackend}


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
        """Schreib-Thread anlegen (noch nicht gestartet). ``names``: Variablennamen in der Reihenfolge der Messzeilen.
        """
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
        self.rejected = 0               # vom Server endgültig abgelehnte Werte (RejectedBatch)
        self._rejected_note = 0.0       # Zeitpunkt der letzten Meldung darüber (höchstens einmal je Minute)
        self._last = {}                 # "nur Änderungen": Variable -> (Wert, Zeit) zuletzt geschrieben
        self.backend = None
        from plc_cleanup import settings as cleanup_settings
        cs = cleanup_settings(conn)
        self.clean_days, self.clean_mb = cs["db_tage"], cs["db_mb"]
        self._next_clean = 0.0          # Aufräumen: beim ersten erfolgreichen Schreiben, dann stündlich

    # ---- aus dem Sammler-Thread
    def put(self, ts, row):
        """Eine Messzeile (aus dem Sammler-Thread) in den Puffer übernehmen – nur gültige Werte.

        Mit „nur Änderungen“ entfällt ein Wert, wenn er gleich dem zuletzt geschriebenen ist und dieser jünger als
        ``HEARTBEAT_S`` ist. Läuft der Puffer über (Datenbank lange nicht erreichbar), werden die ältesten Werte
        verworfen und gezählt.
        """
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
        """Zustand für die Status-LED setzen; bei einer Änderung eine Meldung ausgeben."""
        if self.state != (state, text):
            self.state = (state, text)
            self.emit(tr("[Datenbank] {0}").format(text))

    def status(self):
        """(Zustand, Text) für die Status-LED, mit geschriebenen, wartenden und verworfenen Werten."""
        with self.lock:
            queued = len(self.buf)
        st, text = self.state
        extra = tr(" – {0} Werte geschrieben").format(self.written) + (f", {queued} warten" if queued > BATCH else "")
        if self.dropped:
            extra += tr(", {0} verworfen (Puffer voll)").format(self.dropped)
        if self.rejected:
            extra += tr(", {0} vom Server abgelehnt").format(self.rejected)
        return st, text + extra

    # ---- Thread
    def run(self):
        """Thread-Hauptschleife: etwa jede Sekunde den Puffer schreiben; nach einem Fehler 5 s warten. Beim Stoppen ein
        letztes Mal schreiben.
        """
        while True:
            stopping = self.stop_evt.wait(self.interval)
            ok = self._flush()
            if stopping:
                break
            if ok and (self.clean_days or self.clean_mb) and time.monotonic() >= self._next_clean:
                self._cleanup()
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
            except RejectedBatch as e:                  # endgültig abgelehnt: verwerfen, nicht wiederholen
                self.rejected += len(batch)
                if time.monotonic() - self._rejected_note > 60.0:
                    self._rejected_note = time.monotonic()
                    self.emit(tr("⚠ [Datenbank] {0} Werte abgelehnt: {1}").format(len(batch), e))
            except Exception as e:
                with self.lock:
                    self.buf.extendleft(reversed(batch))    # Reihenfolge erhalten, später erneut versuchen
                self._set(ST_ERROR, f"Schreibfehler: {e}")
                self.backend.close()
                return False

    def _cleanup(self):
        """Alte Werte nach den Einstellungen löschen (im Schreib-Thread, mit dessen Verbindung); Ergebnis melden."""
        from plc_cleanup import INTERVAL_S
        self._next_clean = time.monotonic() + INTERVAL_S
        try:
            text = self.backend.cleanup(self.clean_days, self.clean_mb)
            if text:
                self.emit(tr("[Aufräumen] Datenbank: {0}").format(text))
        except NotImplementedError as e:
            self.emit(tr("[Aufräumen] {0}").format(e))
            self.clean_days = self.clean_mb = 0       # nur einmal melden
        except Exception as e:
            self.emit(tr("⚠ [Aufräumen] Datenbank: {0}").format(e))

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
        """Tabellenname in der Schreibweise der Datenbank (ggf. mit Anführungszeichen)."""
        return t

    def floor(self, expr):          # ganzzahliger Anteil (Zeit >= 0)
        """Ganzzahliger Anteil eines Ausdrucks (für Zeiten >= 0)."""
        return f"FLOOR({expr})"

    def project_cond(self, project):    # Bedingung und Parameter für den Projektnamen
        """Bedingung und Parameter für den Projektnamen."""
        return f"projekt = {self.ph}", [project]

    def raster_sql(self, t, where, r):  # Spalten: Rasternummer (Unix-Zeit / r), variable, Mittelwert; nach Zeit sortiert
        """SQL für Mittelwerte je Zeitraster r: Spalten Rasternummer (Unix-Zeit / r), Variable, Mittelwert; nach Zeit
        sortiert.
        """
        bucket = self.floor(f"{self.epoch()} / {r!r}")
        return f"SELECT {bucket} AS b, variable, AVG(wert) FROM {t}{where} GROUP BY b, variable ORDER BY b"


class _SqliteSql(_ReadSql):
    """SQLite: Zeit ist ISO-Text; Unix-Zeit aus strftime('%s') plus Millisekunden."""
    ph = "?"

    def floor(self, expr):          # FLOOR fehlt in manchen SQLite-Versionen; CAST schneidet ab (für Zeiten >= 0 gleich)
        """FLOOR fehlt in manchen SQLite-Versionen; CAST schneidet ab (für Zeiten >= 0 gleichwertig)."""
        return f"CAST({expr} AS INTEGER)"

    def epoch(self):
        """Unix-Zeit der Spalte zeit, exakt auf Millisekunden (julianday wäre um einige µs ungenau)."""
        # exakt auf Millisekunden (julianday wäre als Gleitkommazahl um einige µs ungenau)
        return "(CAST(strftime('%s', zeit) AS INTEGER) + CAST(substr(zeit, 21, 3) AS INTEGER) / 1000.0)"

    def bound(self, epoch):
        """Zeitgrenze als ISO-Text in UTC (vergleichbar mit der Textspalte zeit)."""
        z = datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)
        return z.strftime("%Y-%m-%d %H:%M:%S.") + f"{z.microsecond // 1000:03d}"


class _MariaSql(_ReadSql):
    """MariaDB/MySQL: Platzhalter %s, Tabellenname in Backticks, Sitzungszeitzone UTC."""
    ph = "%s"

    def epoch(self):
        """Unix-Zeit über UNIX_TIMESTAMP (Sitzungszeitzone UTC, siehe DbReader.connect)."""
        return "UNIX_TIMESTAMP(zeit)"            # Sitzungszeitzone wird auf UTC gestellt (siehe DbReader.connect)

    def bound(self, epoch):
        """Zeitgrenze als datetime ohne Zeitzone (UTC)."""
        return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).replace(tzinfo=None)

    def table(self, t):
        return f"`{t}`"


class _PgSql(_ReadSql):
    """PostgreSQL/TimescaleDB: Platzhalter %s, Zeit als TIMESTAMPTZ."""
    ph = "%s"

    def epoch(self):
        """Unix-Zeit über EXTRACT(EPOCH …)."""
        return "EXTRACT(EPOCH FROM zeit)::double precision"

    def bound(self, epoch):
        """Zeitgrenze als datetime mit Zeitzone UTC."""
        return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)

    def table(self, t):
        return f'"{t}"'


class _QuestSql(_ReadSql):
    """QuestDB: Zeitstempel in Mikrosekunden, Mittelwerte mit SAMPLE BY; Werte als Literale (HTTP ohne Parameter)."""
    ph = "?"                        # QuestDbHttp setzt die Werte selbst als Literale ein

    def epoch(self):
        """Unix-Zeit aus den Mikrosekunden des Zeitstempels."""
        return "(cast(zeit AS long) / 1000000.0)"       # Zeitstempel = Mikrosekunden seit 1970

    def bound(self, epoch):
        """Zeitgrenze als datetime in UTC (wird als Literal eingesetzt)."""
        return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)

    def project_cond(self, project):
        """Leerer Projektname steht in QuestDB als NULL – dann ``IS NULL`` statt Vergleich."""
        if not project:                                 # leerer Projektname wird als NULL geschrieben
            return "projekt IS NULL", []
        return super().project_cond(project)

    def raster_sql(self, t, where, r):
        """Mittelwerte mit SAMPLE BY (QuestDB-eigenes Zeitraster, Zeitstempel = Beginn des Rasters)."""
        # SAMPLE BY: QuestDB-eigene Zeitraster (Zeitstempel = Beginn des Rasters); Einheit T = Millisekunden
        ms = max(int(round(r * 1000)), 1)
        inner = f"SELECT zeit, variable, avg(wert) AS m FROM {t}{where} SAMPLE BY {ms}T ALIGN TO CALENDAR"
        return f"SELECT cast(zeit AS long) / 1000000.0 / {r!r} AS b, variable, m FROM ({inner}) ORDER BY b, variable"


class _InfluxSql(_QuestSql):
    """InfluxDB 3 (SQL von Apache DataFusion): Zeitspalte ``time`` (Nanosekunden); leerer Projektname = NULL und
    Literale statt Parameter wie bei QuestDB."""
    time_col = "time"

    def epoch(self):
        """Unix-Zeit aus den Nanosekunden der Spalte time."""
        return "(CAST(time AS BIGINT) / 1000000000.0)"

    def table(self, t):
        """Tabellenname in doppelten Anführungszeichen."""
        return f'"{t}"'

    def raster_sql(self, t, where, r):
        """Mittelwerte mit date_bin (Raster ab 1970-01-01, Zeitstempel = Beginn des Rasters)."""
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
        """Leser für die Datenbank der Konfiguration (bzw. die SQLite-Datei ``sqlite_file``) anlegen – noch ohne
        Verbindung.
        """
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
        """Kurzbeschreibung der Datenbank (ohne Passwort)."""
        return describe(self.s)

    def connect(self):
        """Verbindung öffnen (SQLite nur lesend, MariaDB mit Sitzungszeitzone UTC) -> self."""
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
        """Verbindung schließen."""
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
        """WHERE-Teil und Parameter aus Projekt, Zeitgrenzen und Variablennamen (alles optional)."""
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
            """Einen Block Ergebniszeilen verarbeiten: neue Zeitpunkte an die Zeitachse hängen, Werte mit (Zeile,
            Spalte) merken.

            Die Zeilen kommen nach Zeit sortiert; so entsteht die Zeitachse ohne nachträgliches Sortieren. Mit Raster
            ist der Zeitstempel die Mitte des Rasters.
            """
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
            # Alle Werte in einem Schritt in die Matrix (Variable × Zeitpunkt) schreiben; Lücken bleiben NaN.
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
        """Kurzbeschreibung der Datenbank (ohne Passwort)."""
        return describe(self.s)

    def connect(self):
        """Erreichbarkeit und Anmeldung prüfen -> self."""
        self.con = VictoriaMetricsHttp(self.s)
        self.con.get_json("/api/v1/labels")
        return self

    def close(self):
        """Nichts offen zu halten (zustandslose HTTP-Anfragen)."""
        self.con = None

    # ---- Hilfen
    def _sel(self, project=None, name=None):
        """Serien-Selektor ``{__name__="…", projekt="…", variable="…"}`` (projekt/variable optional)."""
        parts = [f"__name__={_prom_str(self.metric)}"]
        if project is not None:
            parts.append(f"projekt={_prom_str(project)}")
        if name is not None:
            parts.append(f"variable={_prom_str(name)}")
        return "{" + ",".join(parts) + "}"

    def _data(self, path, params):
        """Prometheus-Anfrage senden und den Teil ``data`` der Antwort liefern (Fehlerstatus -> RuntimeError)."""
        res = self.con.get_json(path, params, timeout=120.0)
        if res.get("status") not in (None, "success"):
            raise RuntimeError(f"{self.con.label}: {res.get('error') or res}")
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
        """Projektnamen (Werte des Labels projekt); Serien ohne Label projekt ergeben den leeren Namen."""
        span = {"start": "0", "match[]": self._sel()}
        names = [str(p) for p in (self._data("/api/v1/label/projekt/values", span) or [])]
        if self._data("/api/v1/series", {"start": "0", "match[]": self._sel("")}):
            names.append("")                            # Serien ohne Label projekt
        return sorted(set(names))

    def variables(self, project=None):
        """Je Variable erster/letzter Zeitpunkt und Anzahl Werte über die gesamte Zeit (Funktionen
        tfirst/tlast/count_over_time).
        """
        sel, w = self._sel(project), f"{self._all_time()}s"
        count = {m.get("variable"): v for m, v in self._instant(f"sum by (variable) (count_over_time({sel}[{w}]))")}
        first = {m.get("variable"): v for m, v in self._instant(f"min by (variable) (tfirst_over_time({sel}[{w}]))")}
        last = {m.get("variable"): v for m, v in self._instant(f"max by (variable) (tlast_over_time({sel}[{w}]))")}
        return [(str(n), first.get(n, last[n]), last[n], int(count.get(n, 0)))
                for n in sorted(last) if n is not None]

    def count(self, names, t0, t1, project=None):
        """Anzahl Werte der Variablen im Zeitraum (count_over_time über das Fenster t0 … t1)."""
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
            """Nach jedem Teilstück: Abbruch prüfen, Werte zählen (Speicherschutz) und Fortschritt melden."""
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


_DURATION_S = {"y": 365 * 86400, "w": 7 * 86400, "d": 86400, "h": 3600, "m": 60, "s": 1}


class PromReader(VmReader):
    """Lesemodus für Prometheus: wie ``VmReader``, aber nur mit den Funktionen von Prometheus.

    * Rohdaten: Bereichsabfragen ``<Selektor>[1h]`` (liefern die gespeicherten Werte unverändert), stundenweise.
    * Mittelwerte je Raster: ``query_range`` in Stücken (Prometheus erlaubt höchstens 11 000 Punkte je Abfrage).
    * Übersicht (erster/letzter Zeitpunkt, Anzahl): Anzahl je Zeitabschnitt über den ganzen Aufbewahrungszeitraum;
      erster und letzter Zeitpunkt sind daher auf einen Abschnitt (etwa 1/2000 des Zeitraums) genau."""

    RAW_CHUNK_S = 3600.0
    MAX_POINTS = 10_000

    def connect(self):
        """Erreichbarkeit und Anmeldung prüfen -> self."""
        self.con = PrometheusHttp(self.s)
        self.con.get_json("/api/v1/status/buildinfo")
        return self

    def _retention_s(self):
        """Aufbewahrungsdauer des Servers in Sekunden (aus runtimeinfo, z. B. "15d"; unbekannt: 400 Tage)."""
        try:
            text = str((self._data("/api/v1/status/runtimeinfo", None) or {}).get("storageRetention", ""))
            total = sum(int(n) * _DURATION_S[u] for n, u in re.findall(r"(\d+)([ywdhms])", text.split(" or ")[0]))
            if total > 0:
                return float(total)
        except Exception:
            pass
        return 400 * 86400.0

    def variables(self, project=None):
        """Je Variable erster/letzter Zeitpunkt (auf einen Zeitabschnitt genau) und Anzahl Werte."""
        now = time.time()
        span = self._retention_s() + 86400
        step = max(1, int(math.ceil(span / 2000)))
        q = f"sum by (variable) (count_over_time({self._sel(project)}[{step}s]))"
        # Ausgewertet wird an den Zeitpunkten start + k·step: das Ende eine Schrittweite hinter „jetzt“ legen, damit
        # auch die jüngsten Werte in einen Abschnitt fallen.
        data = self._data("/api/v1/query_range", {"query": q, "start": f"{now - span:.3f}",
                                                  "end": f"{now + step:.3f}", "step": f"{step}s"}) or {}
        out = []
        for res in data.get("result", []):
            name = res.get("metric", {}).get("variable")
            pts = [(float(t), float(v)) for t, v in res.get("values", []) if float(v) > 0]
            if name is None or not pts:
                continue
            out.append((str(name), max(pts[0][0] - step, now - span), min(pts[-1][0], now), int(sum(v for _t, v in pts))))
        return sorted(out)

    def load(self, names, t0, t1, project=None, raster_s=0, hold=False, cancel=None, progress=None):
        """Wie ``DbReader.load``: (Zeiten, Namen, Spalten); raster_s > 0 = Mittelwerte, Zeit = Mitte des Rasters."""
        import numpy as np
        names = list(dict.fromkeys(names))
        if not names:
            raise ValueError(tr("Keine Variable gewählt."))
        col_of = {n: k for k, n in enumerate(names)}
        series = {}                                     # Spalte -> [(Zeiten, Werte)]
        n_total = 0

        def check(n):
            """Abbruch prüfen, Werte zählen (Speicherschutz) und Fortschritt melden."""
            nonlocal n_total
            if cancel is not None and cancel():
                raise LoadCancelled()
            n_total += n
            if n_total > MAX_LOAD_VALUES:
                raise MemoryError(tr("Mehr als {0} Werte – bitte einen kürzeren Zeitraum oder Mittelwerte wählen.")
                                  .format(f"{MAX_LOAD_VALUES:,}".replace(",", ".")))
            if progress is not None:
                progress(n_total)

        regex = "|".join(re.escape(n).replace("\\ ", " ") for n in names)
        sel = self._sel(project)[:-1] + f",variable=~{_prom_str('^(?:' + regex + ')$')}}}"
        if raster_s and raster_s > 0:
            r = float(raster_s)
            ms = max(int(round(r * 1000)), 1)
            q = f"sum by (variable) (sum_over_time({sel}[{ms}ms])) / sum by (variable) (count_over_time({sel}[{ms}ms]))"
            start = t0 + r
            while start <= t1 + r:
                end = min(t1 + r, start + r * (self.MAX_POINTS - 1))
                data = self._data("/api/v1/query_range", {"query": q, "start": f"{start:.3f}", "end": f"{end:.3f}",
                                                          "step": f"{ms}ms"}) or {}
                for res in data.get("result", []):
                    k = col_of.get(res.get("metric", {}).get("variable"))
                    pts = res.get("values", [])
                    if k is None or not pts:
                        continue
                    ts = np.fromiter((float(p[0]) - r / 2 for p in pts), dtype=float, count=len(pts))
                    vs = np.fromiter((float(p[1]) for p in pts), dtype=float, count=len(pts))
                    series.setdefault(k, []).append((ts, vs))
                    check(len(pts))
                start = end + r
        else:
            w = self.RAW_CHUNK_S
            lo = t0 - 0.001                              # Bereich (lo, hi] – so ist t0 selbst enthalten
            while lo < t1:
                hi = min(t1, lo + w)
                data = self._data("/api/v1/query", {"query": f"{sel}[{int(round((hi - lo) * 1000))}ms]",
                                                    "time": f"{hi:.3f}"}) or {}
                for res in data.get("result", []):
                    k = col_of.get(res.get("metric", {}).get("variable"))
                    pts = res.get("values", [])
                    if k is None or not pts:
                        continue
                    ts = np.fromiter((float(p[0]) for p in pts), dtype=float, count=len(pts))
                    vs = np.fromiter((float(p[1]) for p in pts), dtype=float, count=len(pts))
                    series.setdefault(k, []).append((ts, vs))
                    check(len(pts))
                lo = hi
        parts = [(k, ts, vs) for k, lst in series.items() for ts, vs in lst]
        t = np.unique(np.round(np.concatenate([ts for _k, ts, _v in parts]), 3)) if parts else np.zeros(0)
        cols = np.full((len(names), len(t)), np.nan)
        for k, ts, vs in parts:
            cols[k, np.searchsorted(t, np.round(ts, 3))] = vs
        if hold and len(t):
            cols = _hold(cols)
        return t, names, cols


def create_reader(conn, sqlite_file=None):
    """Leser für die Datenbank der Konfiguration (bzw. eine SQLite-Datei): ``DbReader``, ``VmReader`` oder
    ``PromReader``."""
    typ = "" if sqlite_file else db_settings(conn)["typ"]
    if typ == "victoriametrics":
        return VmReader(conn)
    if typ == "prometheus":
        return PromReader(conn)
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
        # Für jede Stelle den Index des letzten gültigen Werts davor bestimmen (laufendes Maximum), dann einsetzen.
        pos = np.where(valid, np.arange(n), 0)
        np.maximum.accumulate(pos, out=pos)
        filled = row[pos]
        filled[: int(np.argmax(valid))] = np.nan
        out[k] = filled
    return out
