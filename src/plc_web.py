# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Webserver des PLC-Datenloggers: Diagramme online im Browser ansehen (PC, Tablet, Smartphone).

Der Server läuft in einem eigenen Thread neben der Aufzeichnung (im Logger mit Oberfläche genauso wie im
Headless-Modus) und liest die Messwerte aus dem Recorder (plc_recorder.py). Er verwendet

* Flask       – für die Adressen (Routen) und die JSON-Schnittstelle,
* Chart.js    – für die Diagramme im Browser (Datei ``web_static/chart.umd.js``; fehlt sie, lädt die Seite
                Chart.js ersatzweise aus dem Internet, siehe CDN_URL).

Adressen
--------
``/``             die Seite (eine Seite je „Seite/Tab“ der Konfiguration, Diagramme als Kacheln)
``/api/config``   Struktur: Projekt, Seiten, Diagramme, Y-Achsen, Variablen
``/api/data``     Messdaten eines Zeitfensters (Parameter: window = Sekunden, end = Endzeit, max = Punkte je Kurve)
``/api/status``   Zustand der Steuerungen und letzte Werte

Zugriffsschutz
--------------
* Anmeldung (web_benutzer): Benutzer mit Passwort (gespeichert nur als Hash, siehe ``hash_password``). Ohne gültige
  Anmeldung leitet die Seite auf ``/login`` um; die Anmeldung gilt bis zum Abmelden bzw. 12 Stunden (Sitzungs-Cookie,
  HttpOnly, SameSite=Strict, bei HTTPS zusätzlich Secure). Nach 5 Fehlversuchen ist eine Adresse 60 s gesperrt.
* Zugriffscode (web_token): alternativ oder zusätzlich – Aufrufe mit ``?token=...`` sind ohne Anmeldung erlaubt
  (z. B. für ein fest installiertes Anzeigegerät).
* HTTPS (web_https): verschlüsselte Verbindung. Ohne eigenes Zertifikat erzeugt das Programm einmalig ein
  selbstsigniertes (Ordner ``web_tls`` im Datenordner); der Browser zeigt dann beim ersten Aufruf eine Warnung, die
  man nach Prüfen des Fingerabdrucks (Menü „Webserver-Adresse“) bestätigt. Ohne HTTPS ist die Verbindung
  unverschlüsselt – Passwörter und Werte sind im Netz lesbar; dann nur in vertrauenswürdigen Netzen verwenden.
"""
import datetime as _dt
import gzip
import hashlib
import hmac
import html
import ipaddress
import json
import os
import secrets
import socket
import ssl
import sys
import threading
import time

from flask import Flask, Response, abort, redirect, request, send_from_directory, session
from werkzeug.serving import make_server

from plc_common import BASE_DIR
from plc_util import decimate_minmax
from plc_webauth import check_password, hash_password, parse_users  # noqa: F401 (hash_password: Schnittstelle)

# Ersatzquelle für Chart.js, falls web_static/chart.umd.js fehlt (benötigt Internet auf dem Anzeigegerät).
CDN_URL = "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.js"


def static_dirs():
    """Ordner, in denen web_static/chart.umd.js gesucht wird (zuerst der des Benutzers, dann der mitgelieferte)."""
    dirs = []
    if os.environ.get("PLC_WEB_STATIC"):
        dirs.append(os.environ["PLC_WEB_STATIC"])
    dirs.append(os.path.join(BASE_DIR, "web_static"))
    dirs.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_static"))
    if getattr(sys, "frozen", False):                   # PyInstaller: mitgelieferte Dateien
        dirs.append(os.path.join(getattr(sys, "_MEIPASS", ""), "web_static"))
        dirs.append(os.path.join(os.path.dirname(sys.executable), "web_static"))
    return [d for d in dirs if os.path.isdir(d)]


def page_groups(charts):
    """Seiten bestimmen: [(Seitenname, [Diagramm-Indizes])] – wie im Logger: gleicher Seitenname = gleiche Seite;
    ohne Seitenangaben liegen alle Diagramme auf einer Seite."""
    if not any(c.page for c in charts):
        return [("Diagramme", list(range(len(charts))))]
    groups = {}
    for ci, c in enumerate(charts):
        groups.setdefault(c.page or c.name, []).append(ci)
    return list(groups.items())


def _clean(arr, digits=5):
    """numpy-Feld -> Liste für JSON; NaN wird zu null (Lücke in der Linie)."""
    return [None if v != v else round(v, digits) for v in arr.tolist()]


def local_ip():
    """IP-Adresse des Rechners im lokalen Netz (für die Anzeige der Adresse); ohne Netz 127.0.0.1."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))            # es wird nichts gesendet; nur die Route wird bestimmt
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


# ---------------------------------------------------------------------------------------
# Benutzer, Passwörter und Zertifikat
# ---------------------------------------------------------------------------------------
def tls_dir():
    return os.path.join(BASE_DIR, "web_tls")


def ensure_self_signed(cert_path=None, key_path=None):
    """Selbstsigniertes Zertifikat (RSA 2048, 10 Jahre, für Rechnername, lokale IP und localhost) anlegen, falls es
    fehlt -> (Zertifikat, Schlüssel). Benötigt das Paket „cryptography“."""
    cert_path = cert_path or os.path.join(tls_dir(), "zertifikat.pem")
    key_path = key_path or os.path.join(tls_dir(), "schluessel.pem")
    if os.path.exists(cert_path) and os.path.exists(key_path):
        return cert_path, key_path
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    os.makedirs(os.path.dirname(cert_path), exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    host = socket.gethostname() or "localhost"
    names = [x509.DNSName(host), x509.DNSName("localhost")]
    for ip in {local_ip(), "127.0.0.1"}:
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            pass
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host),
                         x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PLC Datenlogger")])
    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - _dt.timedelta(days=1))
            .not_valid_after(now + _dt.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(names), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                  serialization.NoEncryption()))
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def cert_fingerprint(cert_path):
    """SHA-256-Fingerabdruck eines PEM-Zertifikats (AA:BB:…) zum Vergleich im Browser; Fehler -> ""."""
    try:
        with open(cert_path, "rb") as f:
            pem = f.read().decode("ascii", "replace")
        der = ssl.PEM_cert_to_DER_cert(pem[pem.index("-----BEGIN CERTIFICATE-----"):])
        h = hashlib.sha256(der).hexdigest().upper()
        return ":".join(h[i:i + 2] for i in range(0, len(h), 2))
    except (OSError, ValueError):
        return ""


def _secret_key():
    """Schlüssel für die Sitzungs-Cookies (bleibt über Neustarts gleich: Anmeldung bleibt gültig)."""
    path = os.path.join(tls_dir(), "sitzung.key")
    try:
        with open(path, "rb") as f:
            k = f.read()
        if len(k) >= 32:
            return k
    except OSError:
        pass
    k = secrets.token_bytes(32)
    try:
        os.makedirs(tls_dir(), exist_ok=True)
        with open(path, "wb") as f:
            f.write(k)
        os.chmod(path, 0o600)
    except OSError:
        pass
    return k


def create_app(get_rec, token="", refresh_ms=1000, users=None, https=False):
    """Flask-Anwendung. ``get_rec`` liefert bei jedem Aufruf den aktuellen Recorder (oder None).

    users: {Name: Passwort-Hash} – nicht leer = Anmeldung erforderlich; https: Cookies nur über HTTPS senden."""
    app = Flask(__name__, static_folder=None)    # eigene Route für statische Dateien (siehe unten)
    app.config["JSON_AS_ASCII"] = False
    users = dict(users or {})
    app.secret_key = _secret_key()
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict", SESSION_COOKIE_SECURE=bool(https),
                      SESSION_COOKIE_NAME="plc_sitzung", PERMANENT_SESSION_LIFETIME=_dt.timedelta(hours=12))
    failures = {}                                # Fehlversuche je Adresse: [Anzahl, Zeit des letzten]
    fail_lock = threading.Lock()

    def reply(obj, status=200):
        """JSON-Antwort, bei größeren Daten und gzip-fähigem Browser komprimiert (spart Mobilfunk-Datenvolumen)."""
        raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers = {"Cache-Control": "no-store"}
        if len(raw) > 1500 and "gzip" in request.headers.get("Accept-Encoding", ""):
            raw = gzip.compress(raw, 4)
            headers["Content-Encoding"] = "gzip"
        return Response(raw, status=status, mimetype="application/json", headers=headers)

    def token_ok():
        sent = request.args.get("token", "") or request.headers.get("X-Token", "")
        return bool(token) and hmac.compare_digest(sent.encode(), token.encode())

    def logged_in():
        u = session.get("user")
        return bool(u) and u in users

    @app.before_request
    def check_access():
        """Anmeldung bzw. Zugriffscode prüfen (Chart.js-Datei und Anmeldeseite sind frei abrufbar)."""
        if request.path.startswith("/static/") or request.path in ("/login", "/logout"):
            return None
        if not token and not users:
            return None
        if token_ok() or (users and logged_in()):
            return None
        if users:                                # zur Anmeldung (Seite) bzw. 401 mit Hinweis (Daten)
            if request.path.startswith("/api/"):
                return Response('{"login":true}', status=401, mimetype="application/json", headers={"X-Login": "1"})
            return redirect("login")
        abort(401)

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        if https:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return resp

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not users:
            return redirect("./")
        err = ""
        if request.method == "POST":
            ip = request.remote_addr or "?"
            with fail_lock:
                n, last = failures.get(ip, (0, 0.0))
                if n >= 5 and time.time() - last < 60:
                    err = "Zu viele Fehlversuche – bitte eine Minute warten."
            if not err:
                name = (request.form.get("benutzer") or "").strip()
                pw = request.form.get("passwort") or ""
                if name in users and check_password(users[name], pw):
                    with fail_lock:
                        failures.pop(ip, None)
                    session.clear()
                    session["user"] = name
                    session.permanent = True
                    return redirect("./")
                time.sleep(0.8)                  # bremst das Durchprobieren von Passwörtern
                with fail_lock:
                    n, _last = failures.get(ip, (0, 0.0))
                    failures[ip] = (n + 1, time.time())
                err = "Benutzer oder Passwort falsch."
        page = (LOGIN_HTML.replace("__ERR__", html.escape(err))
                .replace("__WARN__", "" if https else '<p class="warn">Unverschlüsselte Verbindung (HTTP): '
                         'Passwort und Werte sind im Netz lesbar.</p>'))
        return Response(page, mimetype="text/html", headers={"Cache-Control": "no-store"})

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect("login" if users else "./")

    @app.route("/")
    def index():
        user = session.get("user") if users else ""
        out = '<a id="logout" href="logout" title="Abmelden">⎋ ' + html.escape(user) + "</a>" if user else ""
        return Response(INDEX_HTML.replace("__CDN__", CDN_URL).replace("__LOGOUT__", out), mimetype="text/html")

    @app.route("/static/<path:name>")
    def static_file(name):
        for d in static_dirs():
            if os.path.exists(os.path.join(d, name)):
                return send_from_directory(d, name, max_age=3600)
        abort(404)

    @app.route("/api/config")
    def api_config():
        rec = get_rec()
        if rec is None:
            return reply({"version": None, "message": "Keine Aufzeichnung aktiv", "refresh_ms": refresh_ms})
        charts_out = []
        for ci, ch in enumerate(rec.charts):
            vars_out = [{"i": vi, "name": v.name, "dtype": v.dtype, "color": v.color, "axis": v.axis}
                        for vi, v in enumerate(rec.vars) if v.chart == ci]
            charts_out.append({"i": ci, "name": ch.name, "vars": vars_out,
                               "axes": [{"name": a.name, "auto": a.auto, "min": a.y_min, "max": a.y_max}
                                        for a in ch.axes]})
        return reply({"version": id(rec), "project": rec.conn.get("projekt", ""), "refresh_ms": refresh_ms,
                      "pages": [{"name": n, "charts": c} for n, c in page_groups(rec.charts)],
                      "charts": charts_out})

    @app.route("/api/data")
    def api_data():
        rec = get_rec()
        if rec is None:
            return reply({"version": None})
        try:
            window = min(max(float(request.args.get("window", 60)), 1.0), 7 * 86400.0)
            maxpts = min(max(int(request.args.get("max", 400)), 50), 3000)
            end = request.args.get("end", "")
            end = float(end) if end else None
        except ValueError:
            abort(400)
        last_t, _ = rec.last_row()
        if last_t is None:
            return reply({"version": id(rec), "empty": True, "plcs": _plcs(rec)})
        t1 = end if end is not None else last_t
        t0 = t1 - window
        t, y = rec.slice_time(t0, t1)
        series = {}
        for vi in range(len(rec.vars)):
            xs, ys = decimate_minmax(t, y[vi], maxpts // 2) if len(t) else (t, t)
            # Zeit relativ zu t0 (kleinere Zahlen = weniger Daten), auf 10 ms gerundet.
            series[vi] = {"x": _clean(xs - t0, 2), "y": _clean(ys)}
        values = {vi: (None if len(t) == 0 or y[vi][-1] != y[vi][-1] else round(float(y[vi][-1]), 5))
                  for vi in range(len(rec.vars))}
        return reply({"version": id(rec), "t0": t0, "t1": t1, "last": last_t, "live": end is None,
                      "series": series, "values": values, "plcs": _plcs(rec), "rows": rec.count(),
                      "running": rec.running, "events": _events(rec)})

    @app.route("/api/status")
    def api_status():
        rec = get_rec()
        if rec is None:
            return reply({"version": None})
        return reply({"version": id(rec), "plcs": _plcs(rec), "rows": rec.count(), "running": rec.running,
                      "events": _events(rec)})

    ev_cache = {}

    def _events(rec):
        """Offene (unquittierte) Ereignisse für die Anzeige im Kopf der Seite; Quittieren nur im Viewer."""
        log = getattr(rec, "events", None)
        if log is None:
            return {"open": 0, "list": []}
        try:
            if log.changed_on_disk():
                log.reload()
            key = (id(log), log.version)
            if ev_cache.get("key") != key:
                lst = [{"zeit": e.zeit[:19], "prio": e.prio, "trigger": e.trigger, "text": e.text}
                       for e in log.events() if e.offen][:20]
                ev_cache.update(key=key, value={"open": log.open_count(), "list": lst})
            return ev_cache["value"]
        except Exception:
            return {"open": 0, "list": []}

    def _plcs(rec):
        return [{"name": n, "state": s, "text": t, "read_ms": round(ms, 1)} for n, s, t, ms in rec.status_list()]

    return app


def web_settings(conn):
    """Einstellungen des Webservers aus der Konfiguration -> Tupel (zum Vergleichen und für WebServer)."""
    return (conn.get("web_host", "0.0.0.0") or "0.0.0.0", int(conn.get("web_port", 8080) or 8080),
            conn.get("web_token", "") or "", int(conn.get("web_intervall_ms", 1000) or 1000),
            bool(int(conn.get("web_https", 0) or 0)), conn.get("web_zertifikat", "") or "",
            conn.get("web_schluessel", "") or "", json.dumps(parse_users(conn.get("web_benutzer", "")), sort_keys=True))


class WebServer:
    """Startet die Flask-Anwendung in einem eigenen Thread (werkzeug-Server, mehrere Anfragen gleichzeitig)."""

    def __init__(self, get_rec, host="0.0.0.0", port=8080, token="", refresh_ms=1000, https=False, cert="", key="",
                 users=None):
        self.host, self.port = host, int(port)
        self.https = bool(https)
        self.cert, self.key = cert, key
        self.users = parse_users(users) if not isinstance(users, dict) else dict(users)
        self.token = token
        self.app = create_app(get_rec, token, refresh_ms, self.users, self.https)
        self.srv = None
        self.thread = None

    @classmethod
    def from_conn(cls, get_rec, conn):
        host, port, token, refresh, https, cert, key, users = web_settings(conn)
        return cls(get_rec, host, port, token, refresh, https, cert, key, json.loads(users))

    def _ssl_context(self):
        """TLS-Kontext: eigenes Zertifikat (Pfade relativ zum Datenordner) oder das selbstsignierte."""
        cert, key = self.cert, self.key
        if cert:
            cert = cert if os.path.isabs(cert) else os.path.join(BASE_DIR, cert)
            key = (key if os.path.isabs(key) else os.path.join(BASE_DIR, key)) if key else ""
        else:
            cert, key = ensure_self_signed()
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(cert, key or None)
        self.cert_used = cert
        return ctx

    def fingerprint(self):
        return cert_fingerprint(getattr(self, "cert_used", "")) if self.https else ""

    def start(self):
        """Server starten; wirft OSError, wenn der Port belegt ist (bzw. ssl.SSLError/ImportError bei HTTPS)."""
        ctx = self._ssl_context() if self.https else None
        self.srv = make_server(self.host, self.port, self.app, threaded=True, ssl_context=ctx)
        self.thread = threading.Thread(target=self.srv.serve_forever, name="webserver", daemon=True)
        self.thread.start()

    def stop(self):
        if self.srv:
            self.srv.shutdown()
            self.srv = None

    def url(self):
        """Adresse für Tablet/Smartphone im selben Netz."""
        host = local_ip() if self.host in ("0.0.0.0", "") else self.host
        return f"{'https' if self.https else 'http'}://{host}:{self.port}/"


# ---------------------------------------------------------------------------------------
# Die Seite (HTML, CSS und JavaScript in einer Datei, damit nichts weiter ausgeliefert werden muss)
# ---------------------------------------------------------------------------------------
INDEX_HTML = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PLC Datenlogger</title>
<style>
:root{--bg:#10151b;--card:#18202a;--fg:#dfe6ee;--mute:#8b98a7;--line:#2a3544;--accent:#4aa3ff;
 --ok:#2ecc71;--err:#ff5252;--warn:#ffc107;--off:#6b7785;color-scheme:dark}
@media (prefers-color-scheme:light){:root{--bg:#f2f4f7;--card:#fff;--fg:#1b2430;--mute:#5b6878;--line:#d5dbe3;
 --accent:#0a6fd6;--off:#9aa5b1;color-scheme:light}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.4 system-ui,"Segoe UI",Roboto,Arial,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line);padding:8px 12px}
.row{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px}
h1{font-size:17px;margin:0;font-weight:600}
.leds{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:13px;color:var(--mute)}
.evbadge{background:#c62828;color:#fff;border-radius:10px;padding:0 8px;font-weight:600;cursor:help}
.led{display:inline-block;width:11px;height:11px;border-radius:50%;background:var(--off);margin-right:5px;
 vertical-align:-1px;box-shadow:0 0 0 1px rgba(0,0,0,.25) inset}
.led.ok{background:var(--ok);box-shadow:0 0 6px var(--ok)}.led.error{background:var(--err)}
.led.connecting{background:var(--warn)}
.ctrl{display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-size:14px}
button,select{background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:6px 10px;
 font:inherit;min-height:34px}
button:active{background:var(--line)}
button.on{border-color:var(--accent);color:var(--accent)}
label.chk{display:flex;gap:5px;align-items:center;color:var(--mute)}
nav{display:flex;gap:6px;overflow-x:auto;margin-top:8px}
nav button{white-space:nowrap}
nav button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
main{padding:10px;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 10px;min-width:0}
.hd{display:flex;align-items:center;gap:8px;margin:0 0 6px}
.card h2{font-size:14px;margin:0;font-weight:600;flex:1;min-width:0}
button.fs{min-height:28px;padding:2px 7px;line-height:0;color:var(--mute)}
button.fs svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round}
.cv{position:relative;height:300px}
@media (max-width:600px){.cv{height:240px}}
/* Vollbild eines Diagramms: Kopfzeile (Zeitfenster, Live …) bleibt sichtbar, das Diagramm füllt den Rest */
body.max{overflow:hidden}
body.max .card:not(.max){display:none}
.card.max{position:fixed;left:0;right:0;bottom:0;top:var(--hh,0px);z-index:4;border-radius:0;border-width:1px 0 0;
 display:flex;flex-direction:column;padding:8px 12px}
.card.max .cv{flex:1;height:auto;min-height:0}
.legend{display:flex;flex-wrap:wrap;gap:4px 14px;margin-top:6px;font-size:13px}
.it{display:flex;align-items:center;gap:6px;cursor:pointer;user-select:none;-webkit-user-select:none}
.sw{width:16px;height:4px;border-radius:2px;flex:none}
.it canvas{flex:none}
.it.off{opacity:.4}.it.dim{opacity:.55}.it.hl .nm{font-weight:700}
.msg{padding:30px;text-align:center;color:var(--mute);grid-column:1/-1}
.info{font-size:12px;color:var(--mute)}
#logout{color:var(--mute);text-decoration:none;font-size:13px;border:1px solid var(--line);border-radius:6px;padding:4px 8px}
</style>
</head>
<body>
<header>
 <div class="row"><h1 id="proj">PLC Datenlogger</h1><div class="leds" id="leds"></div>
  <span class="info" id="info"></span><span style="flex:1"></span>__LOGOUT__</div>
 <div class="ctrl" style="margin-top:6px">
  <select id="win" title="Zeitfenster"></select>
  <button id="back" title="Zurück in der Zeit">◀</button>
  <button id="fwd" title="Vorwärts">▶</button>
  <button id="live" class="on">Live</button>
  <button id="pause" title="Anzeige anhalten">⏸</button>
  <label class="chk"><input type="checkbox" id="boolplot"> Bool im Diagramm</label>
 </div>
 <nav id="tabs"></nav>
</header>
<main id="main"><div class="msg">Lade …</div></main>
<script>
(function(){
'use strict';
var TOKEN=new URLSearchParams(location.search).get('token')||'';
function api(u){return TOKEN?u+(u.indexOf('?')<0?'?':'&')+'token='+encodeURIComponent(TOKEN):u;}
function $(id){return document.getElementById(id);}
function store(k,v){try{if(v===undefined)return localStorage.getItem('plc_'+k);localStorage.setItem('plc_'+k,v);}catch(e){return null;}}
function css(n){return getComputedStyle(document.documentElement).getPropertyValue(n).trim();}
function hexA(c,a){var m=/^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(c);
 return m?'rgba('+parseInt(m[1],16)+','+parseInt(m[2],16)+','+parseInt(m[3],16)+','+a+')':c;}
function fmtVal(v,dt){if(v===null||v===undefined)return '—';
 return (dt==='REAL'||dt==='LREAL')?v.toFixed(3):String(Math.round(v));}
function pad(n,l){n=String(n);while(n.length<(l||2))n='0'+n;return n;}
function fmtT(ms,withMs){var d=new Date(ms);var s=pad(d.getHours())+':'+pad(d.getMinutes())+':'+pad(d.getSeconds());
 return withMs?s+'.'+pad(d.getMilliseconds(),3):s;}
function fmtD(ms){var d=new Date(ms);return pad(d.getDate())+'.'+pad(d.getMonth()+1)+'.'+d.getFullYear()+' '+fmtT(ms,true);}

var cfg=null, ver=null, cos=[], curPage=0, endT=null, paused=false, lastRes=null, busy=false, timer=null, maxCo=null;
var winS=parseInt(store('win')||'60',10), boolPlot=store('bool')==='1';
var WINS=[[10,'10 s'],[30,'30 s'],[60,'1 min'],[300,'5 min'],[900,'15 min'],[3600,'1 h'],[21600,'6 h'],[86400,'24 h']];

function msg(t){$('main').innerHTML='<div class="msg">'+t+'</div>';}

/* ---------- Chart.js laden: lokal, sonst aus dem Netz ---------- */
function loadChartJs(cb){
 if(window.Chart){cb();return;}
 var s=document.createElement('script');s.src='static/chart.umd.js';
 s.onload=cb;
 s.onerror=function(){var c=document.createElement('script');c.src='__CDN__';c.onload=cb;
  c.onerror=function(){msg('Chart.js konnte nicht geladen werden. Datei <code>web_static/chart.umd.js</code> '+
   'neben das Programm legen (siehe Bedienungsanleitung).');};document.head.appendChild(c);};
 document.head.appendChild(s);
}

/* ---------- Aufbau ---------- */
function destroyAll(){
 if(maxCo){maxCo=null;document.body.classList.remove('max');}
 cos.forEach(function(c){if(c.chart)c.chart.destroy();});cos=[];}
function build(){
 destroyAll();
 $('proj').textContent=cfg.project?('PLC Datenlogger – '+cfg.project):'PLC Datenlogger';
 document.title=$('proj').textContent;
 var tabs=$('tabs');tabs.innerHTML='';
 cfg.pages.forEach(function(p,pi){
  var b=document.createElement('button');b.textContent=p.name;b.onclick=function(){showPage(pi);};tabs.appendChild(b);});
 tabs.style.display=cfg.pages.length>1?'flex':'none';
 var main=$('main');main.innerHTML='';
 cfg.charts.forEach(function(ch){
  var card=document.createElement('div');card.className='card';
  card.innerHTML='<div class="hd"><h2></h2><button class="fs"></button></div>'+
   '<div class="cv"><canvas></canvas></div><div class="legend"></div>';
  card.querySelector('h2').textContent=ch.name;
  main.appendChild(card);
  var co={ch:ch,card:card,hidden:{},hl:null,items:{},chart:null,btn:card.querySelector('button.fs')};
  co.btn.onclick=function(){if(maxCo===co)exitMax(false);else enterMax(co);};
  card.querySelector('.cv').addEventListener('dblclick',function(){if(maxCo===co)exitMax(false);else enterMax(co);});
  fsIcon(co);
  makeChart(co);makeLegend(co);cos.push(co);
 });
 showPage(Math.min(curPage,cfg.pages.length-1));
}

/* ---------- Vollbild eines Diagramms ----------
   Das Diagramm füllt das Fenster unterhalb der Kopfzeile; wo der Browser es erlaubt, zusätzlich echtes Vollbild
   (ohne Adressleiste). Zurück: Knopf, Doppelklick, Esc oder die Zurück-Geste/-Taste des Browsers. */
var ICON_MAX='<svg viewBox="0 0 24 24"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>';
var ICON_MIN='<svg viewBox="0 0 24 24"><path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/></svg>';
function fsIcon(co){var on=maxCo===co;co.btn.innerHTML=on?ICON_MIN:ICON_MAX;
 co.btn.title=on?'Normale Darstellung (Esc)':'Vollbild';co.btn.className='fs'+(on?' on':'');}
function headerHeight(){document.documentElement.style.setProperty('--hh',
 document.querySelector('header').offsetHeight+'px');}
function resizeAll(){requestAnimationFrame(function(){cos.forEach(function(c){if(c.chart)c.chart.resize();});});}
function enterMax(co){
 if(maxCo)exitMax(true);
 maxCo=co;headerHeight();
 co.card.classList.add('max');document.body.classList.add('max');fsIcon(co);
 try{history.pushState({plcMax:1},'');}catch(e){}
 var el=document.documentElement;
 if(el.requestFullscreen&&!document.fullscreenElement){el.requestFullscreen().catch(function(){});}
 resizeAll();refresh();
}
function exitMax(quiet){
 if(!maxCo)return;
 var co=maxCo;maxCo=null;
 co.card.classList.remove('max');document.body.classList.remove('max');fsIcon(co);
 if(!quiet){
  if(document.fullscreenElement&&document.exitFullscreen)document.exitFullscreen().catch(function(){});
  if(history.state&&history.state.plcMax){try{history.back();}catch(e){}}
 }
 resizeAll();refresh();
}
function showPage(pi){
 if(maxCo)exitMax(false);
 curPage=pi;
 var tb=$('tabs').children;for(var i=0;i<tb.length;i++)tb[i].className=i===pi?'on':'';
 var vis={};cfg.pages[pi].charts.forEach(function(ci){vis[ci]=1;});
 cos.forEach(function(co){co.card.style.display=vis[co.ch.i]?'':'none';if(vis[co.ch.i]&&co.chart)co.chart.resize();});
}
function makeChart(co){
 var ch=co.ch, fg=css('--fg'), grid=hexA(fg,0.12);
 var scales={x:{type:'linear',ticks:{color:fg,maxTicksLimit:6,callback:function(v){return fmtT(v,false);}},
  grid:{color:grid}}};
 var axisColor={};
 ch.vars.forEach(function(v){if(v.dtype!=='BOOL'&&axisColor[v.axis]===undefined)axisColor[v.axis]=v.color;});
 ch.axes.forEach(function(a,k){
  var col=axisColor[k]||fg;
  var sc={type:'linear',position:k===0?'left':'right',ticks:{color:col},grid:{color:grid,drawOnChartArea:k===0},
   border:{color:col},title:{display:true,text:a.name,color:col},grace:'5%'};
  if(!a.auto){sc.min=a.min;sc.max=a.max;sc.grace=0;}
  scales['y'+k]=sc;});
 scales.yb={display:false,min:-0.05,max:1.05,position:'right',grid:{drawOnChartArea:false}};
 var ds=ch.vars.map(function(v){
  var b=v.dtype==='BOOL';
  return {label:v.name,_vi:v.i,_dt:v.dtype,data:[],borderColor:v.color,borderWidth:2,pointRadius:0,pointHitRadius:8,
   tension:0,spanGaps:false,yAxisID:b?'yb':'y'+Math.min(v.axis,ch.axes.length-1),stepped:b?'after':false,
   fill:b?'origin':false,backgroundColor:b?hexA(v.color,0.22):v.color,hidden:b&&!boolPlot};});
 co.chart=new Chart(co.card.querySelector('canvas'),{type:'line',plugins:[boolLanes],data:{datasets:ds},options:{
  animation:false,parsing:false,normalized:true,responsive:true,maintainAspectRatio:false,
  interaction:{mode:'nearest',intersect:false,axis:'x'},
  plugins:{legend:{display:false},tooltip:{callbacks:{title:function(it){return it.length?fmtD(it[0].parsed.x):'';},
   label:function(c){return c.dataset.label+': '+fmtVal(c.parsed.y,c.dataset._dt);}}}},
  scales:scales}});
}
function makeLegend(co){
 var lg=co.card.querySelector('.legend');lg.innerHTML='';
 co.ch.vars.forEach(function(v){
  var it=document.createElement('div');it.className='it';
  var vis=document.createElement('span');
  vis.className='sw';vis.style.background=v.color;
  var nm=document.createElement('span');nm.className='nm';nm.style.color=v.color;nm.textContent=v.name;
  it.appendChild(vis);it.appendChild(nm);lg.appendChild(it);
  co.items[v.i]={el:it,nm:nm,vis:vis,v:v};
  /* Tippen/Klicken: Kurve hervorheben; langes Drücken bzw. Doppelklick: ein-/ausblenden */
  var tmr=null,long=false;
  it.addEventListener('pointerdown',function(){long=false;tmr=setTimeout(function(){long=true;toggleHide(co,v.i);},600);});
  it.addEventListener('pointerup',function(){clearTimeout(tmr);if(!long)toggleHl(co,v.i);});
  it.addEventListener('pointerleave',function(){clearTimeout(tmr);});
  it.addEventListener('contextmenu',function(e){e.preventDefault();});
  it.addEventListener('dblclick',function(){toggleHide(co,v.i);});
 });
}
function toggleHl(co,vi){co.hl=co.hl===vi?null:vi;style(co);}
function toggleHide(co,vi){if(co.hidden[vi])delete co.hidden[vi];else co.hidden[vi]=1;style(co);}
function style(co){
 co.chart.data.datasets.forEach(function(d){
  var v=co.items[d._vi].v,isB=v.dtype==='BOOL';
  d.hidden=!!co.hidden[d._vi]||(isB&&!boolPlot);
  var on=co.hl===d._vi,faded=co.hl!==null&&!on;
  d.borderColor=faded?hexA(v.color,0.3):v.color;d.borderWidth=on?4:2;
  if(isB)d.backgroundColor=hexA(v.color,faded?0.08:0.22);
  d.order=on?-1:0;
 });
 Object.keys(co.items).forEach(function(k){var it=co.items[k];
  it.el.className='it'+(co.hidden[k]?' off':'')+(co.hl!==null&&co.hl!==+k?' dim':'')+(co.hl===+k?' hl':'');});
 co.chart.update('none');
}
/* BOOL-Signale: je BOOL-Variable eine Zeile im oberen Teil des Diagramms - Name links, rechts davon über die Diagrammbreite
   eine Linie auf der Grundlinie (Wert 0) bzw. ein nach oben gehender Streifen (Wert 1), wie ein digitales Signal. */
var boolLanes={id:'boolLanes',afterDatasetsDraw:function(chart){
 var co=null;cos.forEach(function(c){if(c.chart===chart)co=c;});if(!co)return;
 var rows=chart.data.datasets.filter(function(d){var it=co.items[d._vi];return it&&it.v.dtype==='BOOL'&&!co.hidden[d._vi];});
 if(!rows.length)return;
 var ctx=chart.ctx,ca=chart.chartArea,xs=chart.scales.x,rowH=20,hh=10;
 ctx.save();ctx.font='12px sans-serif';ctx.textBaseline='alphabetic';
 var lw=0;rows.forEach(function(d){lw=Math.max(lw,ctx.measureText(d.label).width);});
 var xl=ca.left+8+lw+10;
 rows.forEach(function(d,k){
  var v=co.items[d._vi].v,on=co.hl===d._vi,faded=co.hl!==null&&!on,base=ca.top+18+k*rowH;
  var col=faded?hexA(v.color,0.3):v.color,h=on?13:hh;
  ctx.fillStyle=col;ctx.fillText(d.label,ca.left+8,base);
  ctx.save();ctx.beginPath();ctx.rect(xl,ca.top,ca.right-xl,ca.bottom-ca.top);ctx.clip();
  ctx.strokeStyle=col;ctx.lineWidth=on?3:2;
  var pts=d.data;
  for(var i=0;i<pts.length;i++){
   var xa=xs.getPixelForValue(pts[i].x),xb=i+1<pts.length?xs.getPixelForValue(pts[i+1].x):ca.right;
   xa=Math.max(xa,xl);xb=Math.min(xb,ca.right);if(xb<=xa)continue;
   if(pts[i].y!==null&&pts[i].y>=0.5)ctx.fillRect(xa,base-h,xb-xa,h);
   else{ctx.beginPath();ctx.moveTo(xa,base);ctx.lineTo(xb,base);ctx.stroke();}
  }
  ctx.restore();});
 ctx.restore();}};

/* ---------- Daten ---------- */
function leds(plcs,ev){
 var h='';(plcs||[]).forEach(function(p){
  h+='<span title="'+(p.text+(p.read_ms?(' – Zyklus '+p.read_ms+' ms'):'')).replace(/"/g,'&quot;')+
   '"><i class="led '+p.state+'"></i>'+p.name.replace(/</g,'&lt;')+'</span>';});
 if(ev&&ev.open){
  var tip=ev.list.map(function(e){return e.zeit+'  '+e.prio+'  '+e.trigger+(e.text?(': '+e.text):'');}).join('\n');
  h+='<span class="evbadge" title="'+(tip+'\n(Quittieren im Ereignis-Viewer des Loggers)').replace(/"/g,'&quot;')
   .replace(/</g,'&lt;')+'">🔔 '+ev.open+' offen</span>';}
 $('leds').innerHTML=h;
}
function apply(res){
 lastRes=res;leds(res.plcs,res.events);
 if(res.empty){$('info').textContent='noch keine Daten';return;}
 $('info').textContent=(res.live?'Live ':'Verlauf ')+fmtD(res.t1*1000)+(res.running?'':' · gestoppt');
 cos.forEach(function(co){
  var sc=co.chart.options.scales;sc.x.min=res.t0*1000;sc.x.max=res.t1*1000;
  co.chart.data.datasets.forEach(function(d){
   var s=res.series[d._vi],a=[];
   if(s){for(var i=0;i<s.x.length;i++)a.push({x:(res.t0+s.x[i])*1000,y:s.y[i]});}
   d.data=a;});
  style(co);
  Object.keys(co.items).forEach(function(k){var it=co.items[k],v=it.v;
   it.nm.textContent=v.name+': '+fmtVal(res.values[k],v.dtype)+(co.hidden[k]?' (aus)':'');});
 });
}
function fetchJson(u){return fetch(api(u),{cache:'no-store'}).then(function(r){
 if(r.status===401){if(r.headers.get('X-Login')){location.href='login';throw new Error('Anmeldung erforderlich');}
  throw new Error('Zugriff verweigert – Zugriffscode in der Adresse fehlt (?token=…)');}
 if(!r.ok)throw new Error('Serverfehler '+r.status);return r.json();});}
function loadConfig(){
 return fetchJson('/api/config').then(function(c){
  if(c.version===null){cfg=null;ver=null;destroyAll();msg(c.message||'Keine Aufzeichnung aktiv');leds([]);return;}
  cfg=c;ver=c.version;build();
  clearInterval(timer);timer=setInterval(tick,Math.max(c.refresh_ms||1000,200));});
}
function refresh(){
 if(busy)return;busy=true;
 /* Punktzahl nach der Breite des (vergrößerten bzw. ersten sichtbaren) Diagramms */
 var vis=maxCo||cos.filter(function(c){return c.card.style.display!=='none';})[0]||cos[0];
 var w=Math.max(vis?vis.card.querySelector('canvas').clientWidth:400,200);
 var u='/api/data?window='+winS+'&max='+Math.min(Math.round(w),2500)+(endT!==null?'&end='+endT:'');
 fetchJson(u).then(function(res){
  busy=false;
  if(res.version!==ver){return loadConfig();}
  apply(res);
 }).catch(function(e){busy=false;$('info').textContent='⚠ '+e.message;});
}
function tick(){
 if(!cfg){loadConfig().catch(function(e){msg('⚠ '+e.message);});return;}
 if(!paused&&endT===null)refresh();
}

/* ---------- Bedienung ---------- */
function init(){
 var sel=$('win');WINS.forEach(function(w){var o=document.createElement('option');o.value=w[0];o.textContent=w[1];
  if(w[0]===winS)o.selected=true;sel.appendChild(o);});
 if(!WINS.some(function(w){return w[0]===winS;})){winS=60;sel.value='60';}
 sel.onchange=function(){winS=+sel.value;store('win',String(winS));refresh();};
 $('back').onclick=function(){var base=endT!==null?endT:(lastRes?lastRes.t1:0);endT=base-winS/2;
  $('live').className='';refresh();};
 $('fwd').onclick=function(){if(endT===null)return;endT+=winS/2;
  if(lastRes&&endT>=lastRes.last){endT=null;$('live').className='on';}refresh();};
 $('live').onclick=function(){endT=null;paused=false;$('pause').className='';$('live').className='on';refresh();};
 $('pause').onclick=function(){paused=!paused;$('pause').className=paused?'on':'';};
 var bp=$('boolplot');bp.checked=boolPlot;
 bp.onchange=function(){boolPlot=bp.checked;store('bool',boolPlot?'1':'0');cos.forEach(style);};
 tick();
 timer=setInterval(tick,1000);
}
loadChartJs(init);
window.addEventListener('resize',function(){if(maxCo)headerHeight();cos.forEach(function(c){if(c.chart)c.chart.resize();});});
/* Vollbild verlassen: Esc (ohne echtes Vollbild), Ende des echten Vollbilds (Esc/F11 des Browsers), Zurück-Geste */
document.addEventListener('keydown',function(e){if(e.key==='Escape'&&maxCo&&!document.fullscreenElement)exitMax(false);});
document.addEventListener('fullscreenchange',function(){if(!document.fullscreenElement&&maxCo)exitMax(false);
 else if(maxCo){headerHeight();resizeAll();}});
window.addEventListener('popstate',function(){if(maxCo)exitMax(true);});
})();
</script>
</body>
</html>
"""


# Anmeldeseite (eigenständig, ohne JavaScript)
LOGIN_HTML = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Anmelden – PLC Datenlogger</title>
<style>
:root{--bg:#10151b;--card:#18202a;--fg:#dfe6ee;--mute:#8b98a7;--line:#2a3544;--accent:#4aa3ff;color-scheme:dark}
@media (prefers-color-scheme:light){:root{--bg:#f2f4f7;--card:#fff;--fg:#1b2430;--mute:#5b6878;--line:#d5dbe3;
 --accent:#0a6fd6;color-scheme:light}}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:var(--bg);
 color:var(--fg);font:15px/1.4 system-ui,"Segoe UI",Roboto,Arial,sans-serif;padding:16px}
form{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:22px;width:100%;max-width:340px}
h1{font-size:18px;margin:0 0 16px}
label{display:block;font-size:13px;color:var(--mute);margin:10px 0 4px}
input{width:100%;padding:9px 10px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg);
 font:inherit}
button{margin-top:18px;width:100%;padding:10px;border:0;border-radius:6px;background:var(--accent);color:#fff;
 font:inherit;font-weight:600;cursor:pointer}
.err{color:#ff5252;min-height:1.4em;margin:10px 0 0}
.warn{color:#ffc107;font-size:12px;margin:12px 0 0}
</style>
</head>
<body>
<form method="post" action="login" autocomplete="on">
 <h1>PLC Datenlogger</h1>
 <label for="b">Benutzer</label><input id="b" name="benutzer" autocomplete="username" required autofocus>
 <label for="p">Passwort</label><input id="p" name="passwort" type="password" autocomplete="current-password" required>
 <button type="submit">Anmelden</button>
 <p class="err">__ERR__</p>
 __WARN__
</form>
</body>
</html>
"""
