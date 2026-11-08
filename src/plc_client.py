# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Logger als Client: zeigt an, was ein anderer Logger aufzeichnet (z. B. headless auf einem Raspberry Pi) – ohne
eigene Konfiguration, ohne Steuerung, ohne eigene Aufzeichnung (ohne Oberfläche; Qt-Teil: plc_client_dialog.py).

Konfiguration (Diagramme, Variablen, Anzeige) und Messwerte kommen vom Webserver des aufzeichnenden Loggers:

* ``/api/konfig`` einmal beim Verbinden (und wenn der Server eine neue Aufzeichnung beginnt),
* ``/api/zeilen`` zuerst die letzten Zeilen aus seinem Speicher, danach im Takt des Servers nur die neuen Zeilen,
* ``/api/ereignisse`` Ereignisse und Notizen; Quittieren und Notizen (mit Schreibrecht) gehen an den Server.

``RemoteRecorder`` hat dieselbe Schnittstelle wie ``plc_recorder.Recorder`` (Puffer, Zustand, Ereignisse), so dass die
Oberfläche des Loggers unverändert damit arbeitet.

    con = Connection("https://logger-kessel:8080/", "chef", "geheim")
    con.connect()                            # anmelden, Konfiguration holen; UntrustedCertificate bei unbekanntem
    rec = RemoteRecorder(con)                # selbstsigniertem Zertifikat (Fingerabdruck bestätigen, dann pins)
    rec.start()
"""
import collections
import hashlib
import http.client
import http.cookiejar
import json
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np

from plc_common import Axis, Chart, Variable, default_connection
from plc_i18n import tr

TIMEOUT_S = 10.0
INITIAL_ROWS = 30000            # so viele Zeilen holt der Client beim Verbinden (der Rest: Datenbank am Server)
MAX_POINTS = 300_000            # wie Recorder.MAX_POINTS


class ClientError(OSError):
    """Verbindung zum Server fehlgeschlagen (Text für den Benutzer). Unterklasse von OSError, damit Dialoge, die beim
    Schreiben ins Ereignisprotokoll OSError abfangen, auch Netzfehler melden."""


class LoginRequired(ClientError):
    """Der Server verlangt eine Anmeldung bzw. Benutzer/Passwort sind falsch."""


class UntrustedCertificate(ClientError):
    """HTTPS mit einem Zertifikat, dem (noch) nicht vertraut wird – ``fingerprint`` zum Vergleich anzeigen."""

    def __init__(self, host, fingerprint):
        super().__init__(tr("Unbekanntes Zertifikat von {0}").format(host))
        self.host, self.fingerprint = host, fingerprint


def fingerprint_of(der):
    """SHA-256-Fingerabdruck eines Zertifikats (DER) als AA:BB:… (wie im Logger unter Webserver-Adresse)."""
    h = hashlib.sha256(der).hexdigest().upper()
    return ":".join(h[i:i + 2] for i in range(0, len(h), 2))


def normalize_url(url):
    """``logger-kessel:8080`` -> ``http://logger-kessel:8080/`` (Schema ergänzen, Schrägstrich am Ende)."""
    url = (url or "").strip()
    if not url:
        raise ClientError(tr("Bitte die Adresse des Loggers angeben, z. B. https://logger-kessel:8080/"))
    if "://" not in url:
        url = "http://" + url
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ClientError(tr("Ungültige Adresse: {0}").format(url))
    path = p.path if p.path.endswith("/") else p.path + "/"
    return urllib.parse.urlunsplit((p.scheme, p.netloc, path, "", ""))


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS-Verbindung, die nur ein Zertifikat mit dem gemerkten Fingerabdruck annimmt (selbstsignierte Zertifikate)."""

    def __init__(self, host, pin="", **kw):
        super().__init__(host, **kw)
        self.pin = pin

    def connect(self):
        super().connect()
        fp = fingerprint_of(self.sock.getpeercert(binary_form=True) or b"")
        if fp != self.pin:
            self.sock.close()
            raise ssl.SSLError(tr("Der Fingerabdruck des Zertifikats hat sich geändert: {0}").format(fp))


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, pin):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE           # geprüft wird stattdessen der Fingerabdruck (siehe oben)
        super().__init__(context=ctx)
        self.pin = pin

    def https_open(self, req):
        return self.do_open(lambda host, **kw: _PinnedHTTPSConnection(host, pin=self.pin, **kw), req,
                            context=self._context)


class Connection:
    """Verbindung zum Webserver eines Loggers: Anmeldung (Benutzer/Passwort oder Zugriffscode), JSON lesen/senden.

    ``pins``: {"host:port": Fingerabdruck} vertrauter selbstsignierter Zertifikate (wird beim Bestätigen ergänzt)."""

    def __init__(self, url, user="", password="", token="", pins=None):
        self.url = normalize_url(url)
        # Adresse mit Zugriffscode (wie „Webserver-Adresse …“ sie kopiert): …/?token=…
        q = urllib.parse.parse_qs(urllib.parse.urlsplit((url or "").strip()).query)
        token = token.strip() or (q.get("token") or [""])[0]
        self.user, self.password, self.token = user.strip(), password, token.strip()
        self.pins = dict(pins or {})
        self.konfig = None
        p = urllib.parse.urlsplit(self.url)
        self.https = p.scheme == "https"
        self.host = p.hostname
        self.port = p.port or (443 if self.https else 80)
        self.hostkey = f"{self.host}:{self.port}"
        self.cookies = http.cookiejar.CookieJar()
        self._opener = None

    # ---------------------------------------------------------------- Netz
    def _build_opener(self):
        handlers = [urllib.request.ProxyHandler({}),                 # im Anlagennetz nie über einen Proxy
                    urllib.request.HTTPCookieProcessor(self.cookies)]
        if self.https and self.hostkey in self.pins:
            handlers.append(_PinnedHTTPSHandler(self.pins[self.hostkey]))
        self._opener = urllib.request.build_opener(*handlers)

    def server_fingerprint(self):
        """Fingerabdruck des Server-Zertifikats (ohne Prüfung gelesen)."""
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((self.host, self.port), timeout=TIMEOUT_S) as sock:
            with ctx.wrap_socket(sock, server_hostname=self.host) as s:
                return fingerprint_of(s.getpeercert(binary_form=True) or b"")

    def trust(self, fingerprint):
        """Selbstsigniertem Zertifikat mit diesem Fingerabdruck vertrauen (gilt für host:port)."""
        self.pins[self.hostkey] = fingerprint
        self._opener = None

    def _open(self, path, data=None, headers=None, timeout=TIMEOUT_S):
        if self._opener is None:
            self._build_opener()
        h = {"Accept-Encoding": "gzip", "Accept": "application/json"}
        if self.token:
            h["X-Token"] = self.token
        h.update(headers or {})
        req = urllib.request.Request(urllib.parse.urljoin(self.url, path.lstrip("/")), data=data, headers=h)
        try:
            return self._opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise LoginRequired(tr("Anmeldung erforderlich (Benutzer und Passwort bzw. Zugriffscode)")) from None
            if e.code == 403:
                raise ClientError(tr("Keine Berechtigung: der Benutzer hat am Logger nur Leserecht.")) from None
            try:
                body = json.loads(_read(e).decode("utf-8"))
                msg = body.get("error") or str(e)
            except Exception:
                msg = str(e)
            raise ClientError(f"{e.code}: {msg}") from None
        except urllib.error.URLError as e:
            reason = e.reason
            if isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(reason):
                raise UntrustedCertificate(self.hostkey, self.server_fingerprint()) from None
            raise ClientError(tr("{0} nicht erreichbar: {1}").format(self.hostkey, reason)) from None
        except (OSError, http.client.HTTPException) as e:
            raise ClientError(tr("{0} nicht erreichbar: {1}").format(self.hostkey, e)) from None

    def get_json(self, path, params=None, timeout=TIMEOUT_S):
        if params:
            path += ("&" if "?" in path else "?") + urllib.parse.urlencode(params)
        with self._open(path, timeout=timeout) as r:
            return json.loads(_read(r).decode("utf-8") or "null")

    def post_json(self, path, body):
        data = json.dumps(body).encode("utf-8")
        with self._open(path, data, {"Content-Type": "application/json"}) as r:
            return json.loads(_read(r).decode("utf-8") or "null")

    # ---------------------------------------------------------------- Anmelden
    def login(self):
        """Mit Benutzer/Passwort anmelden (Sitzungs-Cookie); ohne Benutzer: nichts zu tun."""
        if not self.user:
            return
        data = urllib.parse.urlencode({"benutzer": self.user, "passwort": self.password}).encode("utf-8")
        with self._open("login", data, {"Content-Type": "application/x-www-form-urlencoded",
                                        "Accept": "text/html"}) as r:
            page = _read(r).decode("utf-8", "replace")
        if not any(c.name == "plc_sitzung" for c in self.cookies):
            if 'name="passwort"' in page:
                raise LoginRequired(tr("Benutzer oder Passwort falsch."))

    def connect(self):
        """Anmelden und die Konfiguration holen -> konfig (dict). Fehler: ClientError (bzw. Unterklassen)."""
        self.login()
        try:
            k = self.get_json("api/konfig")
        except LoginRequired:
            raise
        except ClientError as e:
            if str(e).startswith("404"):          # Webserver da, Schnittstelle fehlt: Logger am Server zu alt
                raise ClientError(tr("Der Logger unter {0} unterstützt die Betriebsart Client noch nicht (404). "
                                     "Bitte dort mindestens Version 3.11 installieren.").format(self.url)) from None
            raise
        if not isinstance(k, dict) or k.get("version") is None:
            raise ClientError((k or {}).get("message") or tr("Der Logger zeichnet gerade nicht auf."))
        self.konfig = k
        return k


def _read(resp):
    raw = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip":
        import gzip
        raw = gzip.decompress(raw)
    return raw


# ---------------------------------------------------------------------------------------------- Konfiguration
class RemotePlc:
    """Steuerung des Servers (nur Name und Kurzbeschreibung für die Status-LEDs)."""

    def __init__(self, name, summary="", driver=""):
        self.name, self._summary, self.driver = name, summary, driver
        self.enabled = True
        self.params = {}

    def summary(self):
        return self._summary


def model_from_konfig(k):
    """Antwort von /api/konfig -> (conn, charts, variables, plcs) wie aus plc_common.load_config/load_plcs."""
    conn = default_connection()
    conn.update({key: val for key, val in (k.get("conn") or {}).items() if key in conn and val is not None})
    conn.update(web_aktiv=0, opcua_server="", mqtt="", bericht_aktiv=0, csv_aktiv=0, headless=0)   # nichts selbst starten
    charts = []
    for c in k.get("charts") or []:
        axes = [Axis(name=a.get("name", ""), auto=bool(a.get("auto", True)), y_min=float(a.get("y_min", 0)),
                     y_max=float(a.get("y_max", 100))) for a in c.get("axes") or []] or [Axis()]
        charts.append(Chart(name=c.get("name", ""), axes=axes, page=c.get("page", ""), pid=bool(c.get("pid")),
                            pid_sw=c.get("pid_sw", ""), pid_iw=c.get("pid_iw", ""), pid_stw=c.get("pid_stw", ""),
                            pid_typ=c.get("pid_typ", "PID"), pid_verhalten=c.get("pid_verhalten", "normal")))
    if not charts:
        charts = [Chart()]
    variables = []
    for v in k.get("vars") or []:
        ci = min(max(int(v.get("chart", 0)), 0), len(charts) - 1)
        ai = min(max(int(v.get("axis", 0)), 0), len(charts[ci].axes) - 1)
        variables.append(Variable(name=v["name"], address=v.get("address", ""), dtype=v.get("dtype", "REAL"),
                                  color=v.get("color", "#1f77b4"), show_value=bool(v.get("show_value", True)),
                                  chart=ci, axis=ai, bar=bool(v.get("bar", False)), formula=v.get("formula", ""),
                                  block=v.get("block", ""), block_idx=int(v.get("block_idx", 0)),
                                  plc=int(v.get("plc", 0)), record=bool(v.get("record", True)),
                                  display=bool(v.get("display", True))))
    plcs = [RemotePlc(p.get("name", ""), p.get("summary", ""), p.get("driver", "")) for p in k.get("plcs") or []]
    return conn, charts, variables, plcs


# ---------------------------------------------------------------------------------------------- Ereignisse
class RemoteEventLog:
    """Ereignisprotokoll des Servers mit der Schnittstelle von plc_events.EventLog (für Viewer, Marken, Zähler)."""

    def __init__(self, con):
        self.con = con
        self.path = con.url + "  (" + tr("Server") + ")"
        self.version = 0
        self._server_version = None
        self._open = 0
        self._events = None
        self.open_ids = set()
        self.lock = threading.Lock()

    def update_state(self, ev):
        """Zustand aus /api/zeilen ({"version", "open"}): bei Änderung beim nächsten events() neu laden."""
        if not ev:
            return
        if ev.get("version") != self._server_version:
            with self.lock:
                self._server_version = ev.get("version")
                self._events = None
                self.version += 1
        self._open = int(ev.get("open") or 0)

    def changed_on_disk(self):
        return False

    def reload(self):
        with self.lock:
            self._events = None
            self.version += 1

    def events(self):
        from plc_events import Event
        with self.lock:
            if self._events is not None:
                return list(self._events)
        try:
            data = self.con.get_json("api/ereignisse", {"tage": 400})
        except ClientError:
            return list(self._events or [])
        out = []
        for e in data.get("events") or []:
            out.append(Event(id=int(e["id"]), zeit=e.get("zeit", ""), trigger=e.get("trigger", ""),
                             prio=e.get("prio_de") or e.get("prio", ""), text=e.get("text", ""),
                             gegangen=e.get("gegangen", ""), quittiert=e.get("quittiert", ""),
                             benutzer=e.get("benutzer", ""), pflicht=bool(e.get("pflicht", True)),
                             notiz=bool(e.get("notiz", False))))
        with self.lock:
            self._events = out
            self.open_ids = {e.id for e in out if e.offen}
            self._open = int(data.get("open") or len(self.open_ids))
        return list(out)

    def open_count(self):
        return self._open

    def acknowledge(self, ids=None, user=None):
        r = self.con.post_json("api/ereignisse", {"aktion": "quittieren",
                                                  "ids": "alle" if ids is None else [int(i) for i in ids]})
        self.reload()
        return int((r or {}).get("count", 0))

    def note(self, text, ts=None, user=None):
        r = self.con.post_json("api/ereignisse", {"aktion": "notiz", "text": str(text), "ts": ts})
        self.reload()
        return (r or {}).get("id")


# ---------------------------------------------------------------------------------------------- Aufzeichnung
class RemoteRecorder:
    """Daten eines Loggers über das Netz (Schnittstelle wie plc_recorder.Recorder, soweit die Oberfläche sie nutzt).

    ``start`` beginnt einen Thread, der zuerst die letzten INITIAL_ROWS Zeilen und danach im Takt des Servers die neuen
    Zeilen holt. Ändert sich die Aufzeichnung am Server (neu gestartet, andere Konfiguration), setzt er ``reconfigure``;
    die Oberfläche verbindet sich dann neu."""

    def __init__(self, con, konfig=None):
        self.con = con
        self.konfig = konfig or con.konfig or con.connect()
        self.conn, self.charts, self.vars, self.plcs = model_from_konfig(self.konfig)
        self.version = self.konfig.get("version")
        self.refresh_s = max(float(self.konfig.get("refresh_ms") or 1000), 200) / 1000.0
        self.write = bool(self.konfig.get("write"))
        self.events = RemoteEventLog(con)
        self.config_path = ""
        self.formula_errors = []
        self.messages = collections.deque(maxlen=1000)
        self.lock = threading.Lock()
        n = len(self.vars)
        self._cap = 4096
        self.tbuf = np.empty(self._cap)
        self.ybuf = np.full((n, self._cap), np.nan)
        self.n = 0
        self.dirty = False
        self.running = False
        self.reconfigure = False
        self.server_running = True
        self._capture = None
        self._status = [(p.name, "connecting", tr("verbinde …"), 0.0) for p in self.plcs]
        if self.conn.get("db_typ"):
            self._status.append((tr("Datenbank"), "off", "", 0.0))
        self._link = ("connecting", tr("verbinde …"))
        self._stop = threading.Event()
        self._thread = None

    # ---------------------------------------------------------------- Ablauf
    def start(self):
        if self.running:
            return
        self._stop.clear()
        self.running = True
        self._thread = threading.Thread(target=self._loop, name="client", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        th = self._thread
        if th is not None and th.is_alive() and th is not threading.current_thread():
            th.join(timeout=TIMEOUT_S + 2)
        self._thread = None
        self.running = False

    shutdown = stop

    def emit(self, text):
        self.messages.append(text)

    def _loop(self):
        last = 0.0
        failed = False
        while not self._stop.is_set():
            t_start = time.monotonic()
            try:
                params = {"seit": f"{last:.3f}", "max": INITIAL_ROWS if last <= 0 else 20000}
                d = self.con.get_json("api/zeilen", params)
                if d.get("version") is None:
                    raise ClientError(tr("Der Logger zeichnet gerade nicht auf."))
                if d.get("version") != self.version:
                    self.reconfigure = True
                    self.emit(tr("Die Aufzeichnung am Server wurde neu gestartet – verbinde neu …"))
                    break
                t = np.asarray(d.get("t") or [], dtype=float)
                if len(t):
                    y = np.array([[np.nan if v is None else v for v in row] for row in d.get("y") or []],
                                 dtype=float).reshape(len(self.vars), len(t))
                    self._append_many(t, y)
                    last = float(t[-1])
                self._status = [(p["name"], p["state"], p["text"], float(p.get("read_ms") or 0))
                                for p in d.get("plcs") or []]
                self.server_running = bool(d.get("running", True))
                self._capture = d.get("capture")
                self.events.update_state(d.get("events"))
                if failed:
                    self.emit(tr("Verbindung zu {0} wiederhergestellt").format(self.con.hostkey))
                failed = False
                self._link = ("ok", tr("verbunden"))
                if d.get("more"):
                    continue                                       # noch mehr Zeilen: sofort weiter holen
            except LoginRequired as e:
                self._link = ("error", str(e))
                try:
                    self.con.login()                               # Sitzung abgelaufen: erneut anmelden
                except ClientError:
                    pass
                failed = True
            except ClientError as e:
                if not failed:
                    self.emit("⚠ " + str(e))
                self._link = ("error", str(e))
                self._status = [(n, "error", str(e), 0.0) for n, *_r in self._status]
                failed = True
            except Exception as e:                                 # z. B. unerwartete Antwort
                if not failed:
                    self.emit("⚠ " + tr("Client: {0}").format(e))
                failed = True
            wait = self.refresh_s * (5 if failed else 1) - (time.monotonic() - t_start)
            self._stop.wait(max(wait, 0.05))
        self.running = False

    # ---------------------------------------------------------------- Puffer (wie Recorder)
    def _append_many(self, t, y):
        """Zeilen anhängen; der Puffer wächst durch Verdoppeln bis MAX_POINTS, danach fallen die ältesten weg."""
        if len(t) > MAX_POINTS:
            t, y = t[-MAX_POINTS:], y[:, -MAX_POINTS:]
        with self.lock:
            need = self.n + len(t)
            if need > self._cap and self._cap < MAX_POINTS:
                cap = self._cap
                while cap < need and cap < MAX_POINTS:
                    cap = min(cap * 2, MAX_POINTS)
                t2, y2 = np.empty(cap), np.full((len(self.vars), cap), np.nan)
                t2[:self.n], y2[:, :self.n] = self.tbuf[:self.n], self.ybuf[:, :self.n]
                self.tbuf, self.ybuf, self._cap = t2, y2, cap
            if need > self._cap:                                   # voll: älteste Zeilen (plus ein Zehntel) verwerfen
                drop = min(self.n, need - self._cap + self._cap // 10)
                self.tbuf[:self.n - drop] = self.tbuf[drop:self.n].copy()
                self.ybuf[:, :self.n - drop] = self.ybuf[:, drop:self.n].copy()
                self.n -= drop
            k = len(t)
            self.tbuf[self.n:self.n + k] = t
            self.ybuf[:, self.n:self.n + k] = y
            self.n += k
            self.dirty = True

    def count(self):
        with self.lock:
            return self.n

    def window(self, seconds):
        with self.lock:
            n = self.n
            if n == 0:
                return np.empty(0), np.empty((len(self.vars), 0))
            t = self.tbuf[:n]
            i0 = int(np.searchsorted(t, t[n - 1] - seconds, side="left"))
            return t[i0:n].copy(), self.ybuf[:, i0:n].copy()

    def slice_time(self, t0, t1):
        with self.lock:
            n = self.n
            if n == 0:
                return np.empty(0), np.empty((len(self.vars), 0))
            t = self.tbuf[:n]
            i0 = max(int(np.searchsorted(t, t0, side="left")) - 1, 0)
            i1 = int(np.searchsorted(t, t1, side="right"))
            return t[i0:i1].copy(), self.ybuf[:, i0:i1].copy()

    def snapshot(self):
        with self.lock:
            return self.tbuf[:self.n].copy(), self.ybuf[:, :self.n].copy()

    def last_row(self):
        with self.lock:
            if self.n == 0:
                return None, None
            return float(self.tbuf[self.n - 1]), self.ybuf[:, self.n - 1].copy()

    def first_time(self):
        with self.lock:
            return float(self.tbuf[0]) if self.n else None

    # ---------------------------------------------------------------- Zustand
    def status_list(self):
        """Zustand der Steuerungen (wie vom Server gemeldet); ohne Verbindung alle mit der Fehlermeldung."""
        st, text = self._link
        if st == "error":
            return [(n, "error", tr("Server nicht erreichbar: {0}").format(text), 0.0) for n, *_r in self._status]
        return list(self._status)

    def link_state(self):
        """Zustand der Verbindung zum Server: ("ok"|"connecting"|"error", Text)."""
        return self._link

    def drain_messages(self):
        out = []
        while True:
            try:
                out.append(self.messages.popleft())
            except IndexError:
                return out

    def capture_state(self):
        return self._capture

    def load_range(self, t0, t1, max_rows=200_000):
        """Werte t0..t1 vom Server (sein Speicher, davor seine Datenbank) -> (Zeiten, Werte[Variable][Zeile], Quelle,
        Fehlertext). Für „Aus Datenbank laden“ und „Im Diagramm zeigen“ im Client."""
        d = self.con.get_json("api/verlauf", {"t0": f"{t0 - 0.001:.3f}", "t1": f"{t1 + 0.001:.3f}",  # gerundet: Ränder dabei
                                              "max": int(max_rows)},
                              timeout=120)
        t = np.asarray(d.get("t") or [], dtype=float)
        y = (np.array([[np.nan if v is None else v for v in row] for row in d.get("y") or []], dtype=float)
             .reshape(len(self.vars), len(t)) if len(t) else np.empty((len(self.vars), 0)))
        return t, y, d.get("source", ""), d.get("db_error", "")

    def describe(self):
        """Kurztext für Titel und Statusleiste."""
        k = self.konfig
        user = k.get("user") or ""
        return f"{self.con.url}" + (f" ({user})" if user else "")

