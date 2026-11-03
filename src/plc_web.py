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
``/api/data``     Messdaten eines Zeitfensters (Parameter: window = Sekunden, end = Endzeit, max = Punkte je Kurve);
                  älter als der Speicher des Loggers: aus der Datenbank der Konfiguration (siehe ``load_range``)
``/api/status``   Zustand der Steuerungen und letzte Werte
``/api/export``   Werte eines Zeitraums als CSV- oder Excel-Datei (t0, t1, format=csv|xlsx, vars=Indizes)
``/api/bericht``  PDF-Bericht eines Zeitraums (t0, t1)
``/api/ereignisse`` Ereignisse und Notizen (GET); quittieren bzw. Notiz eintragen (POST, JSON, nur mit Schreibrecht)
``/api/konfig``   Konfiguration für den Logger als Client (Diagramme, Variablen, Anzeige; ohne Passwörter)
``/api/zeilen``   Messwerte als Rohzeilen seit einem Zeitpunkt (seit = Unix-Zeit, 0 = die letzten ``max`` Zeilen)
``/prozess``      Prozessbild: Kacheln (Wert, Zeiger, Balken, Lampe, Kurzverlauf), im Browser bearbeitbar
``/api/prozess``  Layout des Prozessbilds lesen (GET) bzw. speichern (POST, JSON; siehe *_web_prozess.py)

Zugriffsschutz
--------------
* Anmeldung (web_benutzer): Benutzer mit Passwort (gespeichert nur als Hash, siehe ``hash_password``). Ohne gültige
  Anmeldung leitet die Seite auf ``/login`` um; die Anmeldung gilt bis zum Abmelden bzw. 12 Stunden (Sitzungs-Cookie,
  HttpOnly, SameSite=Strict, bei HTTPS zusätzlich Secure). Nach 5 Fehlversuchen ist eine Adresse 60 s gesperrt.
* Rechte (web_rechte): je Benutzer „lesen“ (ansehen, exportieren) oder „schreiben“ (zusätzlich Ereignisse quittieren,
  Notizen eintragen, Prozessbild bearbeiten). Ohne eingerichtete Benutzer darf jeder mit Zugang schreiben, mit
  Benutzern der Zugriffscode nur lesen.
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
import re
import secrets
import socket
import ssl
import sys
import threading
import time

from flask import Flask, Response, abort, redirect, request, send_from_directory, session
from werkzeug.serving import make_server

from plc_common import BASE_DIR, logo_paths
from plc_i18n import tr
from plc_util import decimate_minmax
from plc_webauth import WRITE, check_password, hash_password, parse_rights, parse_users  # noqa: F401 (hash_password)

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
    """Ordner für das selbstsignierte Zertifikat und den Sitzungsschlüssel (``web_tls`` im Datenordner)."""
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
    # Common Name höchstens 64 Zeichen (lange Rechnernamen, z. B. „…local“ auf Macs); der volle Name steht in den
    # Alternativnamen (SAN), nach denen Browser prüfen.
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host[:64]),
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


# IO-Check (Inbetriebnahme): das geöffnete IO-Check-Fenster meldet sich hier an (plc_iocheck.IoWebBridge); alle
# Webserver dieses Programms zeigen es dann unter /io. RUNNING: laufende Webserver (für die Adresse im IO-Check).
_io_bridge = None
RUNNING = []


def set_io_bridge(bridge):
    """IO-Check-Fenster an- bzw. abmelden (None); danach zeigen alle Webserver es unter /io."""
    global _io_bridge
    _io_bridge = bridge


def io_bridge():
    """Angemeldete IO-Check-Brücke oder None."""
    return _io_bridge


# Übersetzbare Texte der Webseiten: {{T:Text}} in HTML (Übersetzung HTML-maskiert), {{J:Text}} innerhalb von
# JavaScript-Zeichenketten (Anführungszeichen und Zeilenumbrüche maskiert). Übersetzt wird beim Ausliefern in die
# eingestellte Programmsprache (plc_i18n); tools/extract_tr.py sammelt die Texte für die Sprachdateien.
_MARK = re.compile(r"\{\{([TJ]):((?:[^{}]|\{\d+\})+?)\}\}")   # Text darf {0}, {1} … enthalten


def localize(page: str) -> str:
    """Markierte Texte einer Seite übersetzen und das lang-Attribut setzen."""
    from plc_i18n import current, tr

    def rep(m):
        """Einen markierten Text ersetzen (HTML- bzw. JavaScript-gerecht maskiert)."""
        t = tr(m.group(2))
        if m.group(1) == "T":
            return html.escape(t, quote=True)
        return t.replace("\\", "\\\\").replace("'", "\\x27").replace('"', "\\x22").replace("\n", "\\n")
    lang = current() or "de"
    return _MARK.sub(rep, page).replace('<html lang="de">', f'<html lang="{lang}">', 1)


def logos_html(logos) -> str:
    """<img>-Elemente für die Kopfzeile der Webseiten (Logo n unter ``logo/n``); ohne Logos ""."""
    return "".join(f'<img class="logo" src="logo/{n}" alt="">' for n, p in enumerate(logos) if os.path.isfile(p))


# ---------------------------------------------------------------------------------------
# Werte eines Zeitraums: Speicher des Loggers, davor die Datenbank
# ---------------------------------------------------------------------------------------
# Einstellungen, die ein Logger als Client vom Server übernimmt (Anzeige; keine Zugangsdaten).
CLIENT_CONN_KEYS = ("projekt", "anordnung", "seite_anordnung", "raster_spalten", "fenster_s", "balken", "balken_breite",
                    "csv_name", "db_typ", "bericht_schichten", "bericht_beginn")
DB_RASTER_FROM_S = 900          # längere Zeiträume liest der Server aus der Datenbank als Mittelwerte (Raster)


def store_vars(rec):
    """Aufgezeichnete Variablen [(Index, Variable)] (nur diese stehen in CSV und Datenbank)."""
    return [(vi, v) for vi, v in enumerate(rec.vars) if getattr(v, "record", True)]


def has_db(rec):
    return bool((getattr(rec, "db_conf", None) or {}).get("typ"))


def _db_values(rec, t0, t1, points=0, raw=False):
    """Werte [t0, t1] aus der Datenbank der Konfiguration -> (Zeiten, Werte[Variable][Zeile]) in der Reihenfolge von
    ``rec.vars`` (nicht aufgezeichnete Variablen NaN); lange Zeiträume als Mittelwerte auf etwa ``points`` Punkte."""
    import numpy as np
    from plc_db import create_reader
    pairs = store_vars(rec)
    raster = 0.0 if raw or not points or (t1 - t0) <= DB_RASTER_FROM_S else (t1 - t0) / points
    reader = create_reader(rec.conn).connect()
    try:
        td, names, cols = reader.load([v.name for _vi, v in pairs], t0, t1, project=rec.conn.get("projekt", ""),
                                      raster_s=raster, hold=bool(int(rec.conn.get("db_nur_aenderungen", 0) or 0)))
    finally:
        reader.close()
    y = np.full((len(rec.vars), len(td)), np.nan)
    pos = {n: k for k, n in enumerate(names)}
    for vi, v in pairs:
        if v.name in pos:
            y[vi] = cols[pos[v.name]]
    return np.asarray(td, dtype=float), y


_DB_CACHE = {}                  # id(Recorder) -> letzter Datenbank-Teil (ändert sich nicht mehr, siehe load_range)
_DB_CACHE_LOCK = threading.Lock()
DB_CACHE_S = 300                # so lange wird der Datenbank-Teil eines Zeitfensters wiederverwendet


def _db_part(rec, t0, end, points, raw):
    """Datenbank-Teil [t0, end] – im Live-Betrieb fragt die Seite jede Sekunde; der Teil vor dem Speicher ändert
    sich aber nicht. Deshalb: ein früheres Ergebnis, das den Bereich abdeckt, wiederverwenden (bis DB_CACHE_S)."""
    key = id(rec)
    now = time.time()
    with _DB_CACHE_LOCK:
        c = _DB_CACHE.get(key)
    if (c and not raw and c["end"] == end and c["t0"] <= t0 and now - c["at"] < DB_CACHE_S
            and c["points"] * 0.5 <= points <= c["points"] * 2 and (c["t1span"] >= (end - t0) * 0.5)):
        k = c["t"] >= t0
        return c["t"][k], c["y"][:, k]
    td, yd = _db_values(rec, t0, end, points, raw)
    if not raw:
        with _DB_CACHE_LOCK:
            _DB_CACHE.clear()
            _DB_CACHE[key] = {"t0": t0, "end": end, "points": points, "t": td, "y": yd, "at": now,
                              "t1span": end - t0}
    return td, yd


def load_range(rec, t0, t1, points=0, raw=False):
    """Werte [t0, t1]: aus dem Speicher des Loggers, der Teil davor aus der Datenbank (falls eingestellt).

    Rückgabe (Zeiten, Werte[Variable][Zeile], Quelle, Fehlertext); Quelle "speicher", "datenbank" oder
    "datenbank+speicher". Ist die Datenbank nicht erreichbar, bleibt es beim Speicher (Fehlertext gesetzt)."""
    import numpy as np
    t, y = rec.slice_time(t0, t1)
    first = rec.first_time() if hasattr(rec, "first_time") else (float(t[0]) if len(t) else None)
    if not has_db(rec) or (first is not None and t0 >= first):
        return t, y, "speicher", ""
    end = t1 if first is None else min(t1, first)
    if end <= t0:
        return t, y, "speicher", ""
    try:
        td, yd = _db_part(rec, t0, end, points, raw)
    except Exception as e:
        return t, y, "speicher", tr("Datenbank: {0}").format(e)
    if first is not None and len(td):
        keep = td < first - 0.01                 # Datenbank speichert auf ms gerundet: Nahtstelle nicht doppelt
        td, yd = td[keep], yd[:, keep]
    if not len(td):
        return t, y, "speicher", ""
    return (np.concatenate([td, t]), np.concatenate([yd, y], axis=1),
            "datenbank+speicher" if len(t) else "datenbank", "")


def break_gaps(t, y, factor=10.0, min_gap_s=5.0):
    """Lücken (Aufzeichnung unterbrochen, Nahtstelle Datenbank/Speicher) als NaN-Zeile einfügen, damit die Diagramme
    dort keine Linie ziehen: Abstand größer als ``factor`` × üblicher Abstand und mindestens ``min_gap_s``."""
    import numpy as np
    if len(t) < 3:
        return t, y
    dt = np.diff(t)
    limit = max(float(np.median(dt)) * factor, min_gap_s)
    gaps = np.nonzero(dt > limit)[0]
    if not len(gaps):
        return t, y
    t2 = np.insert(t, gaps + 1, t[gaps] + dt[gaps] / 2)
    y2 = np.insert(np.asarray(y, dtype=float), gaps + 1, np.nan, axis=1)
    return t2, y2


def event_json(e):
    """Ereignis (plc_events.Event) -> dict für die Webseite (mit Unix-Zeit ``ts``)."""
    from plc_events import parse_stamp
    return {"id": e.id, "zeit": e.zeit[:19], "ts": parse_stamp(e.zeit), "prio": tr(e.prio), "prio_de": e.prio,
            "trigger": e.trigger,
            "text": e.text, "offen": bool(e.offen), "quittiert": e.quittiert[:19], "benutzer": e.benutzer,
            "gegangen": e.gegangen[:19], "notiz": bool(e.notiz), "pflicht": bool(e.pflicht)}


def create_app(get_rec, token="", refresh_ms=1000, users=None, https=False, logos=None, rights=None):
    """Flask-Anwendung. ``get_rec`` liefert bei jedem Aufruf den aktuellen Recorder (oder None).

    users: {Name: Passwort-Hash} – nicht leer = Anmeldung erforderlich; rights: {Name: "lesen"|"schreiben"} (ohne
    Eintrag: schreiben); https: Cookies nur über HTTPS senden; logos: Liste der Logo-Dateien für die Kopfzeilen (wird
    bei jedem Seitenaufruf gelesen, darf sich also ändern)."""
    logos = logos if logos is not None else []
    app = Flask(__name__, static_folder=None)    # eigene Route für statische Dateien (siehe unten)
    app.config["JSON_AS_ASCII"] = False
    users = dict(users or {})
    rights = parse_rights(rights or {}, users)
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
        """True, wenn die Anfrage den richtigen Zugriffscode trägt (``?token=`` oder Kopf ``X-Token``; Vergleich in
        konstanter Zeit).
        """
        sent = request.args.get("token", "") or request.headers.get("X-Token", "")
        return bool(token) and hmac.compare_digest(sent.encode(), token.encode())

    def logged_in():
        """True, wenn die Sitzung zu einem (noch vorhandenen) Benutzer gehört."""
        u = session.get("user")
        return bool(u) and u in users

    @app.before_request
    def check_access():
        """Anmeldung bzw. Zugriffscode prüfen (Chart.js-Datei und Anmeldeseite sind frei abrufbar)."""
        if request.path.startswith(("/static/", "/logo/")) or request.path in ("/login", "/logout"):
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
        """Sicherheits-Kopfzeilen für jede Antwort: kein MIME-Raten, nicht in fremde Seiten einbetten, kein Referrer;
        bei HTTPS HSTS.
        """
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        if https:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return resp

    @app.route("/login", methods=["GET", "POST"])
    def login():
        """Anmeldeseite: GET zeigt das Formular, POST prüft Benutzer und Passwort.

        Nach 5 Fehlversuchen ist die Adresse 60 s gesperrt; jeder Fehlversuch wartet zusätzlich 0,8 s. Bei Erfolg
        beginnt eine neue Sitzung (``session.clear``, schützt vor untergeschobenen Sitzungen).
        """
        if not users:
            return redirect("./")
        err = ""
        if request.method == "POST":
            ip = request.remote_addr or "?"
            with fail_lock:
                n, last = failures.get(ip, (0, 0.0))
                if n >= 5 and time.time() - last < 60:
                    err = "{{T:Zu viele Fehlversuche – bitte eine Minute warten.}}"
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
                err = "{{T:Benutzer oder Passwort falsch.}}"
        page = (LOGIN_HTML.replace("__ERR__", err).replace("__LOGOS__", logos_html(logos))
                .replace("__WARN__", "" if https else '<p class="warn">{{T:Unverschlüsselte Verbindung (HTTP): '
                         'Passwort und Werte sind im Netz lesbar.}}</p>'))
        page = localize(page)
        return Response(page, mimetype="text/html", headers={"Cache-Control": "no-store"})

    @app.route("/logout")
    def logout():
        """Abmelden: Sitzung löschen und zur Anmeldung bzw. Startseite."""
        session.clear()
        return redirect("login" if users else "./")

    def current_user():
        """Prüfer für den IO-Check: Anmeldename, sonst Kennzeichnung des Zugangs."""
        if users and logged_in():
            return session.get("user")
        if token_ok():
            return "Web (" + tr("Zugriffscode") + ")"
        return f"Web ({request.remote_addr or '?'})"

    @app.route("/")
    def index():
        """Startseite mit den Diagrammen; läuft nur der IO-Check (keine Aufzeichnung), geht es direkt zu /io."""
        if get_rec() is None and _io_bridge is not None:
            return redirect("io" + (("?token=" + request.args["token"]) if request.args.get("token") else ""))
        user = session.get("user") if users else ""
        out = ('<a id="logout" href="logout" title="{{T:Abmelden}}">⎋ ' + html.escape(user) + "</a>") if user else ""
        if _io_bridge is not None:
            out = '<a id="logout" href="io" title="{{T:IO-Check (Inbetriebnahme)}}">{{T:IO-Check}}</a> ' + out
        out = '<a id="logout" href="prozess' + _tok() + '" title="{{T:Prozessbild}}">{{T:Prozessbild}}</a> ' + out
        return Response(localize(INDEX_HTML.replace("__CDN__", CDN_URL).replace("__LOGOUT__", out)
                                 .replace("__LOGOS__", logos_html(logos))), mimetype="text/html")

    @app.route("/logo/<int:n>")
    def logo(n):
        """Logo n der Konfiguration (Kundenlogo, Logo) – frei abrufbar, damit es auch auf der Anmeldeseite erscheint."""
        if not 0 <= n < len(logos) or not os.path.isfile(logos[n]):
            abort(404)
        return send_from_directory(os.path.dirname(logos[n]), os.path.basename(logos[n]), max_age=300)

    def _tok():
        """Zugriffscode der Anfrage für Links auf andere Seiten (``?token=…``) oder ""."""
        return ("?token=" + html.escape(request.args["token"])) if request.args.get("token") else ""

    def may_edit():
        """Schreibrecht (Prozessbild bearbeiten, Ereignisse quittieren, Notizen): angemeldete Benutzer mit Recht
        „schreiben“; ohne eingerichtete Anmeldung jeder mit Zugang; mit Benutzern der Zugriffscode nicht."""
        if not users:
            return True
        return logged_in() and rights.get(session.get("user"), WRITE) == WRITE

    # ---- Prozessbild --------------------------------------------------------------------------------------------
    @app.route("/prozess")
    def prozess_page():
        """Seite des Prozessbilds (HTML aus plc_web_prozess) mit Links zu Diagrammen und Abmelden."""
        from plc_web_prozess import PROZESS_HTML
        user = session.get("user") if users else ""
        out = '<a class="lnk" href="./' + _tok() + '">{{T:Diagramme}}</a>'
        if user:
            out += ' <a class="lnk" href="logout" title="{{T:Abmelden}}">⎋ ' + html.escape(user) + "</a>"
        return Response(localize(PROZESS_HTML.replace("__LINKS__", out).replace("__LOGOS__", logos_html(logos))),
                        mimetype="text/html",
                        headers={"Cache-Control": "no-store"})

    @app.route("/api/prozess", methods=["GET", "POST"])
    def api_prozess():
        """Layout des Prozessbilds lesen (GET) oder speichern (POST, JSON).

        GET liefert Layout (gespeichert oder Vorschlag), die Variablen und ob der Benutzer bearbeiten darf;
        ``?vorschlag=1`` liefert immer den Vorschlag. POST prüft die Berechtigung, nimmt nur JSON an (Schutz vor
        Formularen fremder Seiten) und speichert das bereinigte Layout.
        """
        import plc_web_prozess as wp
        rec = get_rec()
        if rec is None:
            return reply({"version": None})
        cfg_path = getattr(rec, "config_path", "") or ""
        if request.method == "POST":
            if not may_edit():
                return reply({"error": tr("Nur Benutzer mit Schreibrecht dürfen das Prozessbild ändern.")}, 403)
            if not request.is_json:              # nur JSON: Formulare fremder Seiten (CSRF) werden abgewiesen
                abort(415)
            try:
                doc = wp.save_layout(cfg_path, request.get_json(silent=True))
            except (ValueError, TypeError):
                return reply({"error": tr("Layout ungültig")}, 400)
            except OSError as e:
                return reply({"error": tr("Speichern fehlgeschlagen: {0}").format(e)}, 500)
            return reply({"ok": True, "layout": doc})
        layout = None if request.args.get("vorschlag") else wp.load_layout(cfg_path)
        return reply({"version": id(rec), "project": rec.conn.get("projekt", ""), "refresh_ms": refresh_ms,
                      "edit": may_edit(), "saved": layout is not None,
                      "layout": layout or wp.default_layout(rec.vars),
                      "vars": [{"i": i, "name": v.name, "dtype": v.dtype, "color": v.color, "calc": bool(v.formula)}
                               for i, v in enumerate(rec.vars)]})

    @app.route("/static/<path:name>")
    def static_file(name):
        """Statische Dateien (Chart.js) aus den Ordnern ``web_static`` ausliefern."""
        for d in static_dirs():
            if os.path.exists(os.path.join(d, name)):
                return send_from_directory(d, name, max_age=3600)
        abort(404)

    @app.route("/api/config")
    def api_config():
        """Aufbau für die Seite: Projekt, Seiten, Diagramme mit Achsen und Variablen; ``version`` ändert sich mit jedem
        neuen Recorder.
        """
        rec = get_rec()
        if rec is None:
            return reply({"version": None, "message": tr("Keine Aufzeichnung aktiv"), "refresh_ms": refresh_ms})
        charts_out = []
        for ci, ch in enumerate(rec.charts):
            vars_out = [{"i": vi, "name": v.name, "dtype": v.dtype, "color": v.color, "axis": v.axis}
                        for vi, v in enumerate(rec.vars) if v.chart == ci and getattr(v, "shown", True)]
            charts_out.append({"i": ci, "name": ch.name, "vars": vars_out,
                               "axes": [{"name": a.name, "auto": a.auto, "min": a.y_min, "max": a.y_max}
                                        for a in ch.axes]})
        return reply({"version": id(rec), "project": rec.conn.get("projekt", ""), "refresh_ms": refresh_ms,
                      "pages": [{"name": n, "charts": c} for n, c in page_groups(rec.charts)],
                      "charts": charts_out, "write": may_edit(), "user": session.get("user", "") if users else "",
                      "db": has_db(rec), "events": getattr(rec, "events", None) is not None,
                      "vars": [{"i": vi, "name": v.name, "dtype": v.dtype, "color": v.color,
                                "shown": bool(getattr(v, "shown", True))} for vi, v in store_vars(rec)]})

    @app.route("/api/data")
    def api_data():
        """Messwerte eines Zeitfensters für die Diagramme.

        Parameter: ``window`` (Sekunden), ``end`` (Endzeit, leer = live), ``max`` (Punkte je Kurve), ``only`` (nur diese
        Variablen-Indizes als Kurve). Die Kurven werden auf die Bildschirmbreite verdichtet (Min/Max je Abschnitt
        bleiben erhalten); Zeiten relativ zu t0, um Daten zu sparen. Dazu letzte Werte, Zustand der Steuerungen und
        offene Ereignisse.
        """
        rec = get_rec()
        if rec is None:
            return reply({"version": None})
        try:
            window = min(max(float(request.args.get("window", 60)), 1.0), 7 * 86400.0)
            maxpts = min(max(int(request.args.get("max", 400)), 50), 3000)
            end = request.args.get("end", "")
            end = float(end) if end else None
            only = request.args.get("only", "")      # nur diese Kurven (Prozessbild: Kurzverläufe); "-" = keine
            only = None if not only else {int(x) for x in only.split(",") if x not in ("", "-")}
        except ValueError:
            abort(400)
        last_t, _ = rec.last_row()
        if last_t is None and not (end is not None and has_db(rec)):
            return reply({"version": id(rec), "empty": True, "plcs": _plcs(rec)})
        t1 = end if end is not None else last_t
        t0 = t1 - window
        t, y, source, db_error = load_range(rec, t0, t1, maxpts)
        t, y = break_gaps(t, y)
        series = {}
        for vi in range(len(rec.vars)):
            if only is not None and vi not in only:
                continue
            xs, ys = decimate_minmax(t, y[vi], maxpts // 2) if len(t) else (t, t)
            # Zeit relativ zu t0 (kleinere Zahlen = weniger Daten), auf 10 ms gerundet.
            series[vi] = {"x": _clean(xs - t0, 2), "y": _clean(ys)}
        values = {vi: (None if len(t) == 0 or y[vi][-1] != y[vi][-1] else round(float(y[vi][-1]), 5))
                  for vi in range(len(rec.vars))}
        first = rec.first_time() if hasattr(rec, "first_time") else None
        return reply({"version": id(rec), "t0": t0, "t1": t1, "last": last_t, "live": end is None,
                      "series": series, "values": values, "plcs": _plcs(rec), "rows": rec.count(),
                      "running": rec.running, "events": _events(rec), "source": source, "db_error": db_error,
                      "first": first, "marks": _marks(rec, t0, t1)})

    # ---- Logger als Client (plc_client): Konfiguration und Rohzeilen ----------------------------------------------
    @app.route("/api/konfig")
    def api_konfig():
        """Konfiguration für einen Logger als Client: Diagramme mit Achsen, alle Variablen (auch nicht angezeigte, in
        der Reihenfolge der Zeilen von ``/api/zeilen``), Steuerungen (Name, Kurzbeschreibung) und Anzeige-Einstellungen.
        Keine Zugangsdaten (Datenbank, Steuerungen, Web-Benutzer)."""
        rec = get_rec()
        if rec is None:
            return reply({"version": None, "message": tr("Keine Aufzeichnung aktiv")})
        conn = {k: rec.conn.get(k) for k in CLIENT_CONN_KEYS if k in rec.conn}
        plcs = []
        for p in getattr(rec, "plcs", []):
            try:
                summary = p.summary()
            except Exception:
                summary = ""
            plcs.append({"name": p.name, "driver": getattr(p, "driver", ""), "summary": summary})
        charts = [{"name": c.name, "page": c.page, "pid": c.pid, "pid_sw": c.pid_sw, "pid_iw": c.pid_iw,
                   "pid_stw": c.pid_stw, "pid_typ": c.pid_typ, "pid_verhalten": c.pid_verhalten,
                   "axes": [{"name": a.name, "auto": a.auto, "y_min": a.y_min, "y_max": a.y_max} for a in c.axes]}
                  for c in rec.charts]
        variables = [{"name": v.name, "address": v.address, "dtype": v.dtype, "color": v.color,
                      "show_value": v.show_value, "chart": v.chart, "axis": v.axis, "bar": v.bar, "formula": v.formula,
                      "block": v.block, "block_idx": v.block_idx, "plc": v.plc,
                      "record": bool(getattr(v, "record", True)), "display": bool(getattr(v, "display", True))}
                     for v in rec.vars]
        return reply({"version": id(rec), "project": rec.conn.get("projekt", ""), "refresh_ms": refresh_ms,
                      "write": may_edit(), "user": session.get("user", "") if users else "", "conn": conn,
                      "plcs": plcs, "charts": charts, "vars": variables, "events": getattr(rec, "events", None)
                      is not None, "rows": rec.count()})

    @app.route("/api/zeilen")
    def api_rows():
        """Rohzeilen für den Client: alle Zeilen mit Zeit > ``seit`` (höchstens ``max``, ``mehr`` = es gibt weitere);
        ``seit`` = 0: die letzten ``max`` Zeilen. Dazu Zustand der Steuerungen und der Ereignisse."""
        import numpy as np
        rec = get_rec()
        if rec is None:
            return reply({"version": None})
        try:
            since = float(request.args.get("seit", 0) or 0)
            maxn = min(max(int(request.args.get("max", 20000)), 1), 200000)
        except ValueError:
            abort(400)
        last_t, _ = rec.last_row()
        more = False
        if last_t is None:
            t, y = np.empty(0), np.empty((len(rec.vars), 0))
        elif since <= 0:
            t, y = rec.snapshot()
            t, y = t[-maxn:], y[:, -maxn:]
        else:
            t, y = rec.slice_time(since, last_t)
            keep = t > since
            t, y = t[keep], y[:, keep]
            if len(t) > maxn:
                t, y, more = t[:maxn], y[:, :maxn], True
        log = getattr(rec, "events", None)
        ev = {"version": None, "open": 0}
        if log is not None:
            try:
                if log.changed_on_disk():
                    log.reload()
                ev = {"version": f"{id(log)}:{log.version}", "open": log.open_count()}
            except Exception:
                pass
        return reply({"version": id(rec), "t": [round(float(x), 3) for x in t],
                      "y": [_clean(np.asarray(row, dtype=float), 6) for row in y], "more": more,
                      "plcs": _plcs(rec), "running": rec.running, "events": ev,
                      "capture": rec.capture_state() if hasattr(rec, "capture_state") and rec.running else None})

    @app.route("/api/verlauf")
    def api_history():
        """Werte eines Zeitraums für den Client (``t0``, ``t1``; höchstens ``max`` Zeilen): aus dem Speicher, der Teil
        davor aus der Datenbank (lange Zeiträume als Mittelwerte). Zu viele Zeilen werden gleichmäßig ausgedünnt."""
        import numpy as np
        rec = get_rec()
        if rec is None:
            return reply({"version": None})
        t0, t1, _sel = _range_args()
        try:
            maxn = min(max(int(request.args.get("max", 200000)), 100), 500000)
        except ValueError:
            abort(400)
        try:
            t, y, source, err = load_range(rec, t0, t1, points=maxn)
        except MemoryError as e:
            return reply({"error": str(e)}, 400)
        keep = (t >= t0) & (t <= t1)
        t, y = t[keep], np.asarray(y, dtype=float)[:, keep]
        if len(t) > maxn:
            step = int(np.ceil(len(t) / maxn))
            t, y = t[::step], y[:, ::step]
        return reply({"version": id(rec), "t": [round(float(x), 3) for x in t],
                      "y": [_clean(np.asarray(row, dtype=float), 6) for row in y], "source": source,
                      "db_error": err})

    # ---- Export, Bericht, Ereignisse ------------------------------------------------------------------------------
    def _range_args():
        """t0, t1 (Unix-Zeit) und die gewählten Variablen (``vars`` = Indizes, leer = alle aufgezeichneten)."""
        try:
            t0, t1 = float(request.args["t0"]), float(request.args["t1"])
            sel = request.args.get("vars", "")
            sel = None if not sel else {int(x) for x in sel.split(",") if x}
        except (KeyError, ValueError):
            abort(400)
        if not t1 > t0 or t1 - t0 > 400 * 86400:
            abort(400)
        return t0, t1, sel

    def _selected(rec, sel):
        return [vi for vi, _v in store_vars(rec) if sel is None or vi in sel]

    def _file_reply(path, mimetype, name, inline=False):
        with open(path, "rb") as f:
            data = f.read()
        try:
            os.remove(path)
        except OSError:
            pass
        disp = "inline" if inline else "attachment"
        return Response(data, mimetype=mimetype, headers={"Content-Disposition": f'{disp}; filename="{name}"',
                                                          "Cache-Control": "no-store"})

    def _stem(rec):
        return re.sub(r"[^\w\-]+", "_", rec.conn.get("csv_name") or "export").strip("_") or "export"

    @app.route("/api/export")
    def api_export():
        """Werte eines Zeitraums (Rohdaten aus Speicher bzw. Datenbank) als CSV- oder Excel-Datei."""
        import tempfile

        import numpy as np
        from plc_export import write_values
        rec = get_rec()
        if rec is None:
            abort(404)
        t0, t1, sel = _range_args()
        fmt = "xlsx" if request.args.get("format") == "xlsx" else "csv"
        try:
            t, y, _src, err = load_range(rec, t0, t1, raw=True)
        except MemoryError as e:
            return reply({"error": str(e)}, 400)
        keep = (t >= t0) & (t <= t1)
        idx = _selected(rec, sel)
        if not keep.any() or not idx:
            return reply({"error": err or tr("Im gewählten Zeitbereich liegen keine Messwerte.")}, 404)
        name = f"{_stem(rec)}_{_dt.datetime.fromtimestamp(t0):%Y%m%d_%H%M%S}.{fmt}"
        fd, path = tempfile.mkstemp(suffix="." + fmt)
        os.close(fd)
        try:
            write_values(path, t[keep], [rec.vars[i].name for i in idx], [rec.vars[i].dtype for i in idx],
                         np.asarray(y)[idx][:, keep])
        except ValueError as e:                    # z. B. zu viele Zeilen für Excel
            os.remove(path)
            return reply({"error": str(e)}, 400)
        mime = ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if fmt == "xlsx"
                else "text/csv; charset=utf-8")
        return _file_reply(path, mime, name)

    @app.route("/api/bericht")
    def api_report():
        """PDF-Bericht eines Zeitraums (Statistik, Diagramme, Ereignisse) – wie im Logger."""
        import tempfile

        import numpy as np
        from plc_report import ReportAccumulator, events_in, write_report
        from plc_util import fmt_time
        rec = get_rec()
        if rec is None:
            abort(404)
        t0, t1, sel = _range_args()
        try:
            t, y, _src, err = load_range(rec, t0, t1, points=20000)
        except MemoryError as e:
            return reply({"error": str(e)}, 400)
        keep = (t >= t0) & (t <= t1)
        idx = _selected(rec, sel)
        if not keep.any() or not idx:
            return reply({"error": err or tr("Im gewählten Zeitbereich liegen keine Messwerte.")}, 404)
        acc = ReportAccumulator([rec.vars[i].name for i in idx], [rec.vars[i].dtype for i in idx], t0, t1,
                                label=f"{fmt_time(t0)[:16]} – {fmt_time(t1)[:16]}")
        acc.add_many(t[keep], np.asarray(y)[idx][:, keep])
        log = getattr(rec, "events", None)
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        write_report(path, acc, rec.charts, [rec.vars[i] for i in idx], rec.conn.get("projekt", ""),
                     events_in(log, t0, t1) if log is not None else [], logos=list(logos))
        return _file_reply(path, "application/pdf", f"Bericht_{_stem(rec)}.pdf", inline=True)

    @app.route("/api/ereignisse", methods=["GET", "POST"])
    def api_events():
        """Ereignisse und Notizen (GET: ``tage`` bzw. t0/t1, neueste zuerst, höchstens 500); POST (JSON, nur mit
        Schreibrecht): {"aktion": "quittieren", "ids": [..] | "alle"} oder {"aktion": "notiz", "text": …, "ts": …}."""
        rec = get_rec()
        log = getattr(rec, "events", None) if rec is not None else None
        if log is None:
            return reply({"events": [], "open": 0, "write": False})
        if request.method == "POST":
            if not may_edit():
                return reply({"error": tr("Kein Schreibrecht.")}, 403)
            if not request.is_json:              # nur JSON: Formulare fremder Seiten (CSRF) werden abgewiesen
                abort(415)
            d = request.get_json(silent=True) or {}
            who = current_user()
            try:
                if d.get("aktion") == "quittieren":
                    ids = None if d.get("ids") == "alle" else [int(i) for i in d.get("ids") or []]
                    n = log.acknowledge(ids, user=who)
                    ev_cache.clear()
                    return reply({"ok": True, "count": n})
                if d.get("aktion") == "notiz":
                    ts = float(d["ts"]) if d.get("ts") not in (None, "") else None
                    eid = log.note(str(d.get("text", ""))[:2000], ts, user=who)
                    ev_cache.clear()
                    return reply({"ok": True, "id": eid})
            except ValueError as e:
                return reply({"error": str(e)}, 400)
            except OSError as e:
                return reply({"error": tr("Ereignisprotokoll nicht beschreibbar: {0}").format(e)}, 500)
            abort(400)
        try:
            if log.changed_on_disk():
                log.reload()
            evs = [event_json(e) for e in log.events()]
        except Exception as e:
            return reply({"events": [], "open": 0, "write": may_edit(), "error": str(e)})
        try:
            if request.args.get("t0"):
                t0, t1 = float(request.args["t0"]), float(request.args.get("t1") or time.time() + 1)
            else:
                t1 = time.time() + 1
                t0 = t1 - min(max(float(request.args.get("tage", 7)), 0.01), 400) * 86400
        except ValueError:
            abort(400)
        evs = [e for e in evs if e["ts"] is not None and t0 <= e["ts"] <= t1]
        evs.sort(key=lambda e: e["ts"], reverse=True)
        return reply({"events": evs[:500], "open": log.open_count(), "write": may_edit()})

    @app.route("/api/status")
    def api_status():
        """Nur Zustand: Steuerungen, Zeilenzahl, läuft die Aufzeichnung, offene Ereignisse."""
        rec = get_rec()
        if rec is None:
            return reply({"version": None})
        return reply({"version": id(rec), "plcs": _plcs(rec), "rows": rec.count(), "running": rec.running,
                      "events": _events(rec)})

    # ---- IO-Check (Smartphone/Tablet) ---------------------------------------------------------------------------
    @app.route("/io")
    def io_page():
        from plc_iocheck_web import IO_HTML
        user = session.get("user") if users else ""
        out = ('<a class="lnk" href="logout" title="{{T:Abmelden}}">⎋ ' + html.escape(user) + "</a>") if user else ""
        if get_rec() is not None:
            out = '<a class="lnk" href="./">{{T:Diagramme}}</a> ' + out
        return Response(localize(IO_HTML.replace("__LOGOUT__", out)), mimetype="text/html",
                        headers={"Cache-Control": "no-store"})

    @app.route("/api/io")
    def api_io():
        """IO-Check: Momentaufnahme der Signale für die Mobilseite (``ver`` = bekannte Version, ``sel`` = gewähltes
        Signal).
        """
        b = _io_bridge
        if b is None:
            return reply({"active": False})
        try:
            ver = int(request.args.get("ver", -1))
            sel = request.args.get("sel", "")
            sel = int(sel) if sel not in ("", "-1") else None
        except ValueError:
            abort(400)
        return reply(b.snapshot(ver, sel, current_user()))

    @app.route("/api/io/cmd", methods=["POST"])
    def api_io_cmd():
        """IO-Check: Befehl von der Mobilseite (Status setzen, Bemerkung …); nur JSON, Prüfer = angemeldeter Benutzer.
        """
        b = _io_bridge
        if b is None:
            return reply({"error": "inactive"}, 409)
        if not request.is_json:                  # nur JSON: Formulare fremder Seiten (CSRF) werden abgewiesen
            abort(415)
        d = request.get_json(silent=True) or {}
        try:
            err = b.command(int(d.get("ver", -1)), str(d.get("cmd", "")), int(d.get("i", -1)), d, current_user())
        except (TypeError, ValueError):
            abort(400)
        return reply({"error": err} if err else {"ok": True}, 409 if err == "version" else 400 if err else 200)

    @app.route("/api/io/protokoll.pdf")
    def api_io_protocol():
        """IO-Check: Abnahmeprotokoll als PDF erzeugen und im Browser anzeigen."""
        b = _io_bridge
        if b is None or not b.signals:
            abort(404)
        import tempfile
        from plc_iocheck import write_protocol
        path = os.path.join(tempfile.gettempdir(), f"io-protokoll-{os.getpid()}.pdf")
        write_protocol(path, b.signals, b.title, b.source, b.plcs, getattr(b, "logos", ()))
        with open(path, "rb") as f:
            data = f.read()
        return Response(data, mimetype="application/pdf",
                        headers={"Content-Disposition": 'inline; filename="IO-Check-Protokoll.pdf"',
                                 "Cache-Control": "no-store"})

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
                lst = [{"zeit": e.zeit[:19], "prio": tr(e.prio), "trigger": e.trigger, "text": e.text}
                       for e in log.events() if e.offen][:20]
                ev_cache.update(key=key, value={"open": log.open_count(), "list": lst})
            return ev_cache["value"]
        except Exception:
            return {"open": 0, "list": []}

    def _marks(rec, t0, t1):
        """Ereignisse und Notizen im Zeitfenster (für senkrechte Marken in den Diagrammen), höchstens 100."""
        log = getattr(rec, "events", None)
        if log is None:
            return []
        try:
            key = (id(log), log.version)
            if ev_cache.get("mkey") != key:
                ev_cache.update(mkey=key, marks=[event_json(e) for e in log.events()])
            return [m for m in ev_cache["marks"] if m["ts"] is not None and t0 <= m["ts"] <= t1][:100]
        except Exception:
            return []

    def _plcs(rec):
        """Zustand der Steuerungen für die Status-LEDs der Webseite."""
        return [{"name": n, "state": s, "text": t, "read_ms": round(ms, 1)} for n, s, t, ms in rec.status_list()]

    return app


def web_settings(conn):
    """Einstellungen des Webservers aus der Konfiguration -> Tupel (zum Vergleichen und für WebServer)."""
    return (conn.get("web_host", "0.0.0.0") or "0.0.0.0", int(conn.get("web_port", 8080) or 8080),
            conn.get("web_token", "") or "", int(conn.get("web_intervall_ms", 1000) or 1000),
            bool(int(conn.get("web_https", 0) or 0)), conn.get("web_zertifikat", "") or "",
            conn.get("web_schluessel", "") or "", json.dumps(parse_users(conn.get("web_benutzer", "")), sort_keys=True),
            json.dumps(parse_rights(conn.get("web_rechte", ""), parse_users(conn.get("web_benutzer", ""))),
                       sort_keys=True))


class WebServer:
    """Startet die Flask-Anwendung in einem eigenen Thread (werkzeug-Server, mehrere Anfragen gleichzeitig)."""

    def __init__(self, get_rec, host="0.0.0.0", port=8080, token="", refresh_ms=1000, https=False, cert="", key="",
                 users=None, logos=None, rights=None):
        """Flask-Anwendung anlegen (noch nicht gestartet); Benutzer als {Name: Hash} oder JSON-Text; ``logos``: Pfade
        der Logos für die Kopfzeilen (änderbar über ``set_logos``)."""
        self.logos = list(logos or [])
        self.host, self.port = host, int(port)
        self.https = bool(https)
        self.cert, self.key = cert, key
        self.users = parse_users(users) if not isinstance(users, dict) else dict(users)
        self.token = token
        self.app = create_app(get_rec, token, refresh_ms, self.users, self.https, self.logos, rights)
        self.srv = None
        self.thread = None

    @classmethod
    def from_conn(cls, get_rec, conn):
        """Webserver mit den Einstellungen der Konfiguration (siehe ``web_settings``)."""
        host, port, token, refresh, https, cert, key, users, rights = web_settings(conn)
        return cls(get_rec, host, port, token, refresh, https, cert, key, json.loads(users), logo_paths(conn),
                   json.loads(rights))

    def set_logos(self, conn):
        """Logos nach einer Änderung der Konfiguration übernehmen (ohne Neustart des Servers)."""
        self.logos[:] = logo_paths(conn)

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
        """SHA-256-Fingerabdruck des verwendeten Zertifikats (nur bei HTTPS, sonst "")."""
        return cert_fingerprint(getattr(self, "cert_used", "")) if self.https else ""

    def start(self):
        """Server starten; wirft OSError, wenn der Port belegt ist (bzw. ssl.SSLError/ImportError bei HTTPS)."""
        ctx = self._ssl_context() if self.https else None
        self.srv = make_server(self.host, self.port, self.app, threaded=True, ssl_context=ctx)
        self.thread = threading.Thread(target=self.srv.serve_forever, name="webserver", daemon=True)
        self.thread.start()
        RUNNING.append(self)

    def stop(self):
        """Server beenden und aus der Liste der laufenden Server entfernen."""
        if self in RUNNING:
            RUNNING.remove(self)
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
.evbadge{background:#c62828;color:#fff;border-radius:10px;padding:0 8px;font-weight:600;cursor:pointer}
.led{display:inline-block;width:11px;height:11px;border-radius:50%;background:var(--off);margin-right:5px;
 vertical-align:-1px;box-shadow:0 0 0 1px rgba(0,0,0,.25) inset}
.led.ok{background:var(--ok);box-shadow:0 0 6px var(--ok)}.led.error{background:var(--err)}
.led.connecting{background:var(--warn)}
.ctrl{display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-size:14px}
.sep{width:1px;height:24px;background:var(--line);margin:0 2px}
button,select,input{background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:6px 10px;
 font:inherit;min-height:34px}
input[type=datetime-local]{padding:4px 6px;max-width:210px}
button:active{background:var(--line)}
button.on{border-color:var(--accent);color:var(--accent)}
button:disabled{opacity:.45}
button.pri{background:var(--accent);border-color:var(--accent);color:#fff}
label.chk{display:flex;gap:5px;align-items:center;color:var(--mute)}
nav{display:flex;gap:6px;overflow-x:auto;margin-top:8px}
nav button{white-space:nowrap}
nav button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
#rulerbar{display:none;margin-top:6px;font-size:13px;gap:6px 16px;flex-wrap:wrap;color:var(--mute)}
#rulerbar b{color:var(--fg);font-weight:600}
main{padding:10px;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 10px;min-width:0}
.card.act{border-color:var(--accent)}
.hd{display:flex;align-items:center;gap:8px;margin:0 0 6px}
.card h2{font-size:14px;margin:0;font-weight:600;flex:1;min-width:0}
.own{font-size:12px;color:var(--accent);display:none}
button.fs{min-height:28px;padding:2px 7px;line-height:0;color:var(--mute)}
button.fs svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round}
.cv{position:relative;height:300px}
.cv canvas{touch-action:pan-y}
.zr{position:absolute;border:1px dashed var(--accent);background:rgba(74,163,255,.12);pointer-events:none;display:none}
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
.it.off{opacity:.4}.it.dim{opacity:.55}.it.hl .nm{font-weight:700}
.msg{padding:30px;text-align:center;color:var(--mute);grid-column:1/-1}
.info{font-size:12px;color:var(--mute)}
img.logo{height:30px;max-width:180px;object-fit:contain;background:#fff;border-radius:5px;padding:2px 5px;flex:none}
#logout{color:var(--mute);text-decoration:none;font-size:13px;border:1px solid var(--line);border-radius:6px;padding:4px 8px}
/* Dialoge (Export, Ereignisse) */
.dlg{position:fixed;inset:0;z-index:20;background:rgba(0,0,0,.45);display:none;align-items:flex-start;
 justify-content:center;padding:40px 10px;overflow:auto}
.dlg.open{display:flex}
.box{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;width:100%;max-width:620px}
.box h3{margin:0 0 12px;font-size:16px}
.box .r{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;margin:8px 0}
.box .btns{display:flex;flex-wrap:wrap;gap:8px;justify-content:flex-end;margin-top:14px}
.box .err{color:var(--err);min-height:1.2em;font-size:13px}
#evlist{max-height:60vh;overflow:auto;border-top:1px solid var(--line);margin-top:8px}
.ev{display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;padding:8px 2px;border-bottom:1px solid var(--line);
 font-size:13px}
.ev .tx{flex:1;min-width:200px}
.ev .st{color:var(--mute);font-size:12px}
.prio{border-radius:8px;padding:0 7px;font-size:12px;color:#fff;background:#5c6bc0}
.prio.p-Alarm{background:#c62828}.prio.p-Warnung{background:#ef6c00}.prio.p-Info{background:#1e88e5}
.prio.p-Notiz{background:#607d8b}
.ev button{min-height:28px;padding:2px 8px;font-size:13px}
</style>
</head>
<body>
<header>
 <div class="row">__LOGOS__<h1 id="proj">PLC Datenlogger</h1><div class="leds" id="leds"></div>
  <span class="info" id="info"></span><span style="flex:1"></span>__LOGOUT__</div>
 <div class="ctrl" style="margin-top:6px">
  <select id="win" title="{{T:Zeitfenster}}"></select>
  <button id="back" title="{{T:Zurück in der Zeit}}">◀</button>
  <button id="fwd" title="{{T:Vorwärts}}">▶</button>
  <button id="live" class="on">{{T:Live}}</button>
  <button id="pause" title="{{T:Anzeige anhalten}}">⏸</button>
  <input type="datetime-local" id="goto" step="1" title="{{T:Gehe zu Datum und Uhrzeit (auch ältere Daten aus der Datenbank)}}">
  <span class="sep"></span>
  <button id="zreset" title="{{T:Zoom zurücksetzen: alle Diagramme wieder live, Y-Achsen automatisch}}">⟲ {{T:Zoom}}</button>
  <button id="sync" title="{{T:Zeitachsen angleichen: alle Diagramme auf den Zeitbereich des markierten Diagramms}}" disabled>⇔ {{T:Angleichen}}</button>
  <button id="rulers" title="{{T:Lineale ein/aus: Werte an zwei Zeitpunkten und Differenz (Lineal ziehen oder ins Diagramm klicken)}}">┆ {{T:Lineale}}</button>
  <span class="sep"></span>
  <button id="export" title="{{T:Werte als CSV/Excel speichern oder PDF-Bericht erstellen}}">⇩ {{T:Export}}</button>
  <button id="events" title="{{T:Ereignisse und Notizen}}">🔔 {{T:Ereignisse}}</button>
  <label class="chk"><input type="checkbox" id="boolplot"> {{T:Bool im Diagramm}}</label>
 </div>
 <div class="row" id="rulerbar"></div>
 <nav id="tabs"></nav>
</header>
<main id="main"><div class="msg">{{T:Lade …}}</div></main>

<div class="dlg" id="dlgExport"><div class="box">
 <h3>{{T:Export}}</h3>
 <div class="r"><label class="chk"><input type="radio" name="xr" value="view" checked> {{T:Angezeigter Zeitbereich}}</label>
  <label class="chk"><input type="radio" name="xr" value="rulers" id="xrRulers"> {{T:Zwischen den Linealen}}</label>
  <label class="chk"><input type="radio" name="xr" value="free"> {{T:Von – bis}}</label></div>
 <div class="r"><input type="datetime-local" id="xFrom" step="1"> – <input type="datetime-local" id="xTo" step="1"></div>
 <div class="r"><label class="chk"><input type="checkbox" id="xShown" checked> {{T:Nur angezeigte Kurven (sonst alle aufgezeichneten Variablen)}}</label></div>
 <div class="r">{{T:Format}}: <label class="chk"><input type="radio" name="xf" value="xlsx" checked> Excel</label>
  <label class="chk"><input type="radio" name="xf" value="csv"> CSV</label></div>
 <div class="err" id="xErr"></div>
 <div class="btns"><button id="xClose">{{T:Schließen}}</button><button id="xReport">{{T:PDF-Bericht}}</button>
  <button id="xGo" class="pri">{{T:Werte herunterladen}}</button></div>
</div></div>

<div class="dlg" id="dlgEvents"><div class="box">
 <h3>{{T:Ereignisse und Notizen}}</h3>
 <div class="r"><select id="evDays"><option value="1">{{T:letzter Tag}}</option><option value="7" selected>{{T:letzte 7 Tage}}</option>
  <option value="30">{{T:letzte 30 Tage}}</option><option value="365">{{T:letztes Jahr}}</option></select>
  <label class="chk"><input type="checkbox" id="evOpen"> {{T:nur offene}}</label><span style="flex:1"></span>
  <button id="evNote" class="w">✎ {{T:Notiz …}}</button><button id="evAckAll" class="w">✓ {{T:Alle quittieren}}</button></div>
 <div class="err" id="evErr"></div>
 <div id="evlist"></div>
 <div class="btns"><button id="evClose">{{T:Schließen}}</button></div>
</div></div>

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
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');}
function fmtVal(v,dt){if(v===null||v===undefined||v!==v)return '—';
 return (dt==='REAL'||dt==='LREAL')?v.toFixed(3):String(Math.round(v));}
function pad(n,l){n=String(n);while(n.length<(l||2))n='0'+n;return n;}
function fmtT(ms,withMs){var d=new Date(ms);var s=pad(d.getHours())+':'+pad(d.getMinutes())+':'+pad(d.getSeconds());
 return withMs?s+'.'+pad(d.getMilliseconds(),3):s;}
function fmtD(ms){var d=new Date(ms);return pad(d.getDate())+'.'+pad(d.getMonth()+1)+'.'+d.getFullYear()+' '+fmtT(ms,true);}
function fmtTick(ms,span){var d=new Date(ms);
 return span>2*86400000?pad(d.getDate())+'.'+pad(d.getMonth()+1)+'. '+pad(d.getHours())+':'+pad(d.getMinutes()):fmtT(ms,false);}
function fmtDur(s){s=Math.abs(s);if(s<120)return (Math.round(s*1000)/1000)+' s';if(s<7200)return (Math.round(s/6)/10)+' min';
 if(s<172800)return (Math.round(s/360)/10)+' h';return (Math.round(s/8640)/10)+' {{J:Tage}}';}
function localInput(ms){var d=new Date(ms);return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+'T'+
 pad(d.getHours())+':'+pad(d.getMinutes())+':'+pad(d.getSeconds());}
function fromInput(v){var t=v?new Date(v).getTime():NaN;return isNaN(t)?null:t/1000;}

var cfg=null, ver=null, cos=[], curPage=0, endT=null, paused=false, lastRes=null, busy=false, timer=null, maxCo=null;
var winS=parseInt(store('win')||'60',10), boolPlot=store('bool')==='1';
var active=null;                 /* zuletzt bedientes Diagramm (für „Angleichen“) */
var rulers=null;                 /* [Zeit 1, Zeit 2] in ms oder null */
var WINS=[[10,'10 s'],[30,'30 s'],[60,'1 min'],[300,'5 min'],[900,'15 min'],[3600,'1 h'],[21600,'6 h'],[86400,'24 h'],
 [604800,'{{J:7 Tage}}']];

function msg(t){$('main').innerHTML='<div class="msg">'+t+'</div>';}

/* ---------- Chart.js laden: lokal, sonst aus dem Netz ---------- */
function loadChartJs(cb){
 if(window.Chart){cb();return;}
 var s=document.createElement('script');s.src='static/chart.umd.js';
 s.onload=cb;
 s.onerror=function(){var c=document.createElement('script');c.src='__CDN__';c.onload=cb;
  c.onerror=function(){msg('{{J:Chart.js konnte nicht geladen werden. Datei <code>web_static/chart.umd.js</code> neben das Programm legen (siehe Bedienungsanleitung).}}');};document.head.appendChild(c);};
 document.head.appendChild(s);
}

/* ---------- Aufbau ---------- */
function destroyAll(){
 if(maxCo){maxCo=null;document.body.classList.remove('max');}
 cos.forEach(function(c){if(c.chart)c.chart.destroy();});cos=[];active=null;}
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
  card.innerHTML='<div class="hd"><h2></h2><span class="own" title="{{J:Eigener Zeitbereich (Mausrad, Bereich aufziehen) – „Angleichen“ bzw. „Zoom“ setzt zurück}}">⏱ {{J:eigene Zeitachse}}</span><button class="fs"></button></div>'+
   '<div class="cv"><canvas></canvas><div class="zr"></div></div><div class="legend"></div>';
  card.querySelector('h2').textContent=ch.name;
  main.appendChild(card);
  var co={ch:ch,card:card,hidden:{},hl:null,items:{},chart:null,btn:card.querySelector('button.fs'),
   own:null,ownRes:null,yz:null,marks:[],res:null};
  co.btn.onclick=function(){if(maxCo===co)exitMax(false);else enterMax(co);};
  card.querySelector('.cv').addEventListener('dblclick',function(){if(maxCo===co)exitMax(false);else enterMax(co);});
  fsIcon(co);
  makeChart(co);makeLegend(co);attachZoom(co);cos.push(co);
 });
 showPage(Math.min(curPage,cfg.pages.length-1));
 $('export').disabled=false;
 $('events').style.display=cfg.events?'':'none';
 document.querySelectorAll('.w').forEach(function(b){b.style.display=cfg.write?'':'none';});
}

/* ---------- Vollbild eines Diagramms ---------- */
var ICON_MAX='<svg viewBox="0 0 24 24"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>';
var ICON_MIN='<svg viewBox="0 0 24 24"><path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/></svg>';
function fsIcon(co){var on=maxCo===co;co.btn.innerHTML=on?ICON_MIN:ICON_MAX;
 co.btn.title=on?'{{J:Normale Darstellung (Esc)}}':'{{J:Vollbild}}';co.btn.className='fs'+(on?' on':'');}
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
 var scales={x:{type:'linear',ticks:{color:fg,maxTicksLimit:6,callback:function(v){
  var sc=co.chart&&co.chart.scales.x;return fmtTick(v,sc?sc.max-sc.min:0);}},grid:{color:grid}}};
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
 co.chart=new Chart(co.card.querySelector('canvas'),{type:'line',plugins:[boolLanes,overlay],data:{datasets:ds},options:{
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
function toggleHide(co,vi){if(co.hidden[vi])delete co.hidden[vi];else co.hidden[vi]=1;style(co);legendValues(co);}
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
/* BOOL-Signale: je BOOL-Variable eine Zeile im oberen Teil des Diagramms (wie ein digitales Signal). */
var boolLanes={id:'boolLanes',afterDatasetsDraw:function(chart){
 var co=coOf(chart);if(!co)return;
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
/* Ereignis-Marken und Lineale über den Kurven */
var PRIOCOL={'Alarm':'#e53935','Warnung':'#fb8c00','Info':'#1e88e5','Notiz':'#90a4ae'};
var overlay={id:'overlay',afterDraw:function(chart){
 var co=coOf(chart);if(!co)return;
 var ctx=chart.ctx,ca=chart.chartArea,xs=chart.scales.x;
 ctx.save();ctx.beginPath();ctx.rect(ca.left,ca.top,ca.right-ca.left,ca.bottom-ca.top);ctx.clip();
 ctx.font='11px sans-serif';var free=-1e9;
 (co.marks||[]).slice().sort(function(a,b){return a.ts-b.ts;}).forEach(function(m){
  var x=xs.getPixelForValue(m.ts*1000);if(x<ca.left||x>ca.right)return;
  var col=m.notiz?PRIOCOL.Notiz:(PRIOCOL[m.prio_de]||PRIOCOL[m.prio]||'#7e57c2');
  ctx.strokeStyle=col;ctx.lineWidth=1.5;ctx.setLineDash([4,3]);
  ctx.beginPath();ctx.moveTo(x,ca.top);ctx.lineTo(x,ca.bottom);ctx.stroke();ctx.setLineDash([]);
  ctx.fillStyle=col;var lab=(m.notiz?'✎ ':'')+(m.notiz?m.text:m.trigger);
  if(lab.length>24)lab=lab.slice(0,23)+'…';
  if(x>=free){ctx.fillText(lab,x+3,ca.bottom-4);free=x+ctx.measureText(lab).width+10;}});
 if(rulers){rulers.forEach(function(t,k){
  var x=xs.getPixelForValue(t);if(x<ca.left-1||x>ca.right+1)return;
  ctx.strokeStyle=k?'#ab47bc':'#26a69a';ctx.lineWidth=2;
  ctx.beginPath();ctx.moveTo(x,ca.top);ctx.lineTo(x,ca.bottom);ctx.stroke();
  ctx.fillStyle=ctx.strokeStyle;ctx.fillRect(x-8,ca.top,16,15);ctx.fillStyle='#fff';ctx.font='bold 11px sans-serif';
  ctx.fillText(String(k+1),x-3,ca.top+11);});}
 ctx.restore();}};
function coOf(chart){for(var i=0;i<cos.length;i++)if(cos[i].chart===chart)return cos[i];return null;}

/* ---------- Zoom, Verschieben, Lineale (Maus, Mausrad, zwei Finger) ---------- */
function range(co){var sc=co.chart.scales.x;return [sc.min,sc.max];}
function setActive(co){if(active&&active!==co)active.card.classList.remove('act');active=co;
 if(co)co.card.classList.add('act');$('sync').disabled=!cos.some(function(c){return c.own;});}
function setOwn(co,t0,t1){
 if(!(t1>t0))return;
 if(t1-t0<0.05*1000)t1=t0+50;
 co.own={t0:t0,t1:t1};co.card.querySelector('.own').style.display='inline';
 var sc=co.chart.options.scales;sc.x.min=t0;sc.x.max=t1;co.chart.update('none');
 setActive(co);fetchOwn(co);
}
function clearOwn(co){co.own=null;co.ownRes=null;co.yz=null;co.card.querySelector('.own').style.display='none';
 co.chart.options.scales&&Object.keys(co.chart.options.scales).forEach(function(k){
  if(k.charAt(0)==='y'&&k!=='yb'){var a=co.ch.axes[+k.slice(1)];var s=co.chart.options.scales[k];
   if(a&&a.auto){delete s.min;delete s.max;s.grace='5%';}else if(a){s.min=a.min;s.max=a.max;}}});}
function rulerAt(co,px){if(!rulers)return -1;var xs=co.chart.scales.x,best=-1,bd=10;
 rulers.forEach(function(t,k){var d=Math.abs(xs.getPixelForValue(t)-px);if(d<bd){bd=d;best=k;}});return best;}
function attachZoom(co){
 var cv=co.card.querySelector('canvas'),zr=co.card.querySelector('.zr'),pts={},drag=null,pinch=null;
 function pos(e){var r=cv.getBoundingClientRect();return {x:e.clientX-r.left,y:e.clientY-r.top};}
 cv.addEventListener('wheel',function(e){
  e.preventDefault();var p=pos(e),xs=co.chart.scales.x,r=range(co),c=xs.getValueForPixel(p.x);
  var f=e.deltaY>0?1.25:0.8;setOwn(co,c-(c-r[0])*f,c+(r[1]-c)*f);},{passive:false});
 cv.addEventListener('pointerdown',function(e){
  var p=pos(e);pts[e.pointerId]=p;setActive(co);
  var ids=Object.keys(pts);
  if(ids.length===2){drag=null;zr.style.display='none';var a=pts[ids[0]],b=pts[ids[1]],r=range(co);
   pinch={d:Math.abs(a.x-b.x)||1,c:(a.x+b.x)/2,r:r};return;}
  var k=rulerAt(co,p.x);
  if(k>=0){drag={ruler:k};cv.setPointerCapture(e.pointerId);e.preventDefault();return;}
  if(e.pointerType==='mouse'&&e.button===0){drag={x:p.x,y:p.y,mx:p.x,my:p.y};cv.setPointerCapture(e.pointerId);}
  else if(e.pointerType!=='mouse')drag={tap:p,x:p.x};
 });
 cv.addEventListener('pointermove',function(e){
  if(!(e.pointerId in pts))return;var p=pos(e);pts[e.pointerId]=p;
  var ids=Object.keys(pts),xs=co.chart.scales.x,ca=co.chart.chartArea;
  if(pinch&&ids.length===2){e.preventDefault();var a=pts[ids[0]],b=pts[ids[1]];
   var d=Math.abs(a.x-b.x)||1,c=(a.x+b.x)/2,f=pinch.d/d,r=pinch.r;
   var span=(r[1]-r[0])*f,tc=r[0]+(pinch.c-ca.left)/(ca.right-ca.left)*(r[1]-r[0]);
   var shift=(c-pinch.c)/(ca.right-ca.left)*span;
   var t0=tc-(pinch.c-ca.left)/(ca.right-ca.left)*span-shift;
   co.own={t0:t0,t1:t0+span};var sc=co.chart.options.scales;sc.x.min=t0;sc.x.max=t0+span;co.chart.update('none');return;}
  if(!drag)return;
  if(drag.ruler!==undefined){e.preventDefault();rulers[drag.ruler]=xs.getValueForPixel(Math.min(Math.max(p.x,ca.left),ca.right));
   drawRulers();return;}
  if(drag.mx!==undefined){drag.mx=p.x;drag.my=p.y;
   zr.style.display='block';zr.style.left=Math.min(drag.x,p.x)+'px';zr.style.top=Math.min(drag.y,p.y)+'px';
   zr.style.width=Math.abs(p.x-drag.x)+'px';zr.style.height=Math.abs(p.y-drag.y)+'px';}
 });
 function up(e){
  var had=e.pointerId in pts;delete pts[e.pointerId];
  if(pinch){if(Object.keys(pts).length<2){var o=co.own;pinch=null;if(o)setOwn(co,o.t0,o.t1);}return;}
  if(!had||!drag)return;var d=drag;drag=null;zr.style.display='none';
  if(d.ruler!==undefined){drawRulers();return;}
  var xs=co.chart.scales.x,p=pos(e);
  if(d.mx!==undefined&&Math.abs(d.mx-d.x)>8){
   var t0=xs.getValueForPixel(Math.min(d.x,d.mx)),t1=xs.getValueForPixel(Math.max(d.x,d.mx));
   if(Math.abs(d.my-d.y)>8){co.yz={};var sc=co.chart.options.scales;
    Object.keys(co.chart.scales).forEach(function(k){if(k.charAt(0)!=='y'||k==='yb')return;var s=co.chart.scales[k];
     sc[k].min=s.getValueForPixel(Math.max(d.y,d.my));sc[k].max=s.getValueForPixel(Math.min(d.y,d.my));sc[k].grace=0;});}
   setOwn(co,t0,t1);return;}
  /* Klick/Tippen ohne Ziehen: mit Linealen das nähere Lineal an diese Stelle */
  if(rulers&&(d.mx===undefined||Math.abs(d.mx-d.x)<=8)){
   var t=xs.getValueForPixel(p.x),k=Math.abs(t-rulers[0])<=Math.abs(t-rulers[1])?0:1;rulers[k]=t;drawRulers();}
 }
 cv.addEventListener('pointerup',up);
 cv.addEventListener('pointercancel',function(e){delete pts[e.pointerId];drag=null;pinch=null;zr.style.display='none';});
}

/* ---------- Lineale ---------- */
function valueAt(d,t){var a=d.data;if(!a.length)return null;var lo=0,hi=a.length-1;
 if(t<a[0].x||t>a[hi].x+60000)return null;
 while(lo<hi){var m=(lo+hi+1)>>1;if(a[m].x<=t)lo=m;else hi=m-1;}return a[lo].y;}
function drawRulers(){
 cos.forEach(function(co){co.chart.draw();legendValues(co);});
 var bar=$('rulerbar');
 if(!rulers){bar.style.display='none';return;}
 bar.style.display='flex';
 bar.innerHTML='<span><b style="color:#26a69a">1</b> '+fmtD(rulers[0])+'</span><span><b style="color:#ab47bc">2</b> '+
  fmtD(rulers[1])+'</span><span>Δt <b>'+fmtDur((rulers[1]-rulers[0])/1000)+'</b></span>';
}
function legendValues(co){
 var res=co.own?co.ownRes:lastRes;
 Object.keys(co.items).forEach(function(k){var it=co.items[k],v=it.v,txt;
  if(rulers){var d=co.chart.data.datasets.filter(function(x){return x._vi===+k;})[0];
   var a=d?valueAt(d,rulers[0]):null,b=d?valueAt(d,rulers[1]):null;
   txt=v.name+': '+fmtVal(a,v.dtype)+' | '+fmtVal(b,v.dtype)+' | Δ '+
    (a===null||b===null?'—':fmtVal(b-a,v.dtype==='BOOL'?'INT':v.dtype));}
  else txt=v.name+': '+fmtVal(res&&res.values?res.values[k]:null,v.dtype);
  it.nm.textContent=txt+(co.hidden[k]?' ({{J:aus}})':'');});
}
function toggleRulers(){
 if(rulers){rulers=null;$('rulers').className='';drawRulers();return;}
 var co=active||cos.filter(function(c){return c.card.style.display!=='none';})[0];if(!co)return;
 var r=range(co);rulers=[r[0]+(r[1]-r[0])/3,r[0]+2*(r[1]-r[0])/3];
 paused=true;$('pause').className='on';$('rulers').className='on';drawRulers();
}

/* ---------- Daten ---------- */
function leds(plcs,ev){
 var h='';(plcs||[]).forEach(function(p){
  h+='<span title="'+esc(p.text+(p.read_ms?(' – '+'{{J:Zyklus {0} ms}}'.replace('{0}',p.read_ms)):''))+
   '"><i class="led '+p.state+'"></i>'+esc(p.name)+'</span>';});
 if(ev&&ev.open){
  var tip=ev.list.map(function(e){return e.zeit+'  '+e.prio+'  '+e.trigger+(e.text?(': '+e.text):'');}).join('\n');
  h+='<span class="evbadge" id="evbadge" title="'+esc(tip+'\n{{J:(Klicken: Ereignisliste)}}')+'">'+
   '{{J:🔔 {0} offen}}'.replace('{0}',ev.open)+'</span>';}
 $('leds').innerHTML=h;
 var b=$('evbadge');if(b)b.onclick=openEvents;
}
function fill(co,res){
 co.res=res;co.marks=res.marks||[];
 var sc=co.chart.options.scales;sc.x.min=res.t0*1000;sc.x.max=res.t1*1000;
 co.chart.data.datasets.forEach(function(d){
  var s=res.series[d._vi],a=[];
  if(s){for(var i=0;i<s.x.length;i++)a.push({x:(res.t0+s.x[i])*1000,y:s.y[i]});}
  d.data=a;});
 style(co);legendValues(co);
}
function apply(res){
 lastRes=res;leds(res.plcs,res.events);
 if(res.empty){$('info').textContent='{{J:noch keine Daten}}';return;}
 var src=res.source&&res.source.indexOf('datenbank')>=0?' · {{J:Datenbank}}':'';
 $('info').textContent=(res.live?'{{J:Live}} ':'{{J:Verlauf}} ')+fmtD(res.t1*1000)+src+(res.running?'':' · {{J:gestoppt}}')+
  (res.db_error?' · ⚠ '+res.db_error:'');
 cos.forEach(function(co){if(!co.own)fill(co,res);});
}
function fetchJson(u,opt){return fetch(api(u),opt||{cache:'no-store'}).then(function(r){
 if(r.status===401){if(r.headers.get('X-Login')){location.href='login';throw new Error('{{J:Anmeldung erforderlich}}');}
  throw new Error('{{J:Zugriff verweigert – Zugriffscode in der Adresse fehlt (?token=…)}}');}
 return r.json().then(function(j){if(!r.ok)throw new Error(j&&j.error?j.error:'{{J:Serverfehler}} '+r.status);return j;},
  function(){throw new Error('{{J:Serverfehler}} '+r.status);});});}
function loadConfig(){
 return fetchJson('/api/config').then(function(c){
  if(c.version===null){cfg=null;ver=null;destroyAll();msg(c.message||'{{J:Keine Aufzeichnung aktiv}}');leds([]);return;}
  cfg=c;ver=c.version;build();
  clearInterval(timer);timer=setInterval(tick,Math.max(c.refresh_ms||1000,200));});
}
function points(co){var c=co||maxCo||cos.filter(function(x){return x.card.style.display!=='none';})[0]||cos[0];
 return Math.min(Math.round(Math.max(c?c.card.querySelector('canvas').clientWidth:400,200)),2500);}
function refresh(){
 if(busy||!cfg)return;busy=true;
 var u='/api/data?window='+winS+'&max='+points()+(endT!==null?'&end='+endT:'');
 fetchJson(u).then(function(res){
  busy=false;
  if(res.version!==ver){return loadConfig();}
  apply(res);
 }).catch(function(e){busy=false;$('info').textContent='⚠ '+e.message;});
}
function fetchOwn(co){
 var o=co.own;if(!o)return;
 var only=co.ch.vars.map(function(v){return v.i;}).join(',')||'-';
 var u='/api/data?window='+((o.t1-o.t0)/1000)+'&end='+(o.t1/1000)+'&max='+points(co)+'&only='+only;
 co.ownSeq=(co.ownSeq||0)+1;var seq=co.ownSeq;
 fetchJson(u).then(function(res){if(seq!==co.ownSeq||!co.own||res.version!==ver)return;co.ownRes=res;
  if(!res.empty)fill(co,res);var sc=co.chart.options.scales;sc.x.min=o.t0;sc.x.max=o.t1;co.chart.update('none');})
  .catch(function(e){$('info').textContent='⚠ '+e.message;});
}
function tick(){
 if(!cfg){loadConfig().catch(function(e){msg('⚠ '+e.message);});return;}
 if(!paused&&endT===null)refresh();
}
function setWindow(s){
 winS=s;var sel=$('win'),found=false;
 for(var i=0;i<sel.options.length;i++){if(+sel.options[i].value===s){sel.selectedIndex=i;found=true;}}
 var cust=$('wincustom');
 if(!found){if(!cust){cust=document.createElement('option');cust.id='wincustom';sel.appendChild(cust);}
  cust.value=s;cust.textContent=fmtDur(s);cust.selected=true;}else if(cust)cust.remove();
}
function goTo(tSec,keepRulers){
 /* Zeitpunkt in die Mitte des Zeitfensters; alle Diagramme dorthin, Anzeige angehalten */
 cos.forEach(clearOwn);setActive(null);
 endT=tSec+winS/2;paused=true;$('pause').className='on';$('live').className='';
 if(!keepRulers&&rulers){rulers=null;$('rulers').className='';drawRulers();}
 refresh();
}

/* ---------- Export und Bericht ---------- */
function shownVars(){var out=[];cos.forEach(function(co){co.ch.vars.forEach(function(v){
 if(!co.hidden[v.i]&&out.indexOf(v.i)<0)out.push(v.i);});});return out;}
function openExport(){
 var co=active||cos.filter(function(c){return c.card.style.display!=='none';})[0];
 var r=co?range(co):[Date.now()-60000,Date.now()];
 $('xFrom').value=localInput(r[0]);$('xTo').value=localInput(r[1]);
 $('xrRulers').disabled=!rulers;if(!rulers&&$('xrRulers').checked)document.querySelector('input[name=xr][value=view]').checked=true;
 $('xErr').textContent='';$('dlgExport').classList.add('open');
}
function exportRange(){
 var mode=document.querySelector('input[name=xr]:checked').value,co=active||cos.filter(function(c){return c.card.style.display!=='none';})[0];
 var a,b;
 if(mode==='rulers'&&rulers){a=Math.min(rulers[0],rulers[1])/1000;b=Math.max(rulers[0],rulers[1])/1000;}
 else if(mode==='free'){a=fromInput($('xFrom').value);b=fromInput($('xTo').value);}
 else{var r=range(co);a=r[0]/1000;b=r[1]/1000;}
 if(a===null||b===null||!(b>a)){$('xErr').textContent='{{J:Bitte einen gültigen Zeitbereich wählen.}}';return null;}
 var u='t0='+a.toFixed(3)+'&t1='+b.toFixed(3);
 if($('xShown').checked){var sv=shownVars();if(!sv.length){$('xErr').textContent='{{J:Keine Kurve angezeigt.}}';return null;}
  u+='&vars='+sv.join(',');}
 return u;
}
function download(url,name,openIt){
 $('xErr').textContent='{{J:Wird erstellt …}}';
 fetch(api(url),{cache:'no-store'}).then(function(r){
  if(!r.ok)return r.json().then(function(j){throw new Error(j.error||r.status);},function(){throw new Error('{{J:Serverfehler}} '+r.status);});
  var cd=r.headers.get('Content-Disposition')||'',m=/filename="([^"]+)"/.exec(cd);
  return r.blob().then(function(b){var a=document.createElement('a');a.href=URL.createObjectURL(b);
   if(openIt)a.target='_blank';else a.download=m?m[1]:name;document.body.appendChild(a);a.click();
   setTimeout(function(){URL.revokeObjectURL(a.href);a.remove();},60000);$('xErr').textContent='';});
 }).catch(function(e){$('xErr').textContent='⚠ '+e.message;});
}

/* ---------- Ereignisse ---------- */
function openEvents(){$('dlgEvents').classList.add('open');loadEvents();}
function loadEvents(){
 $('evErr').textContent='';
 fetchJson('/api/ereignisse?tage='+$('evDays').value).then(function(j){
  var only=$('evOpen').checked,h='';
  document.querySelectorAll('.w').forEach(function(b){b.style.display=j.write?'':'none';});
  (j.events||[]).forEach(function(e){
   if(only&&!e.offen)return;
   var st=e.notiz?'{{J:Notiz}}'+(e.benutzer?' – '+e.benutzer:''):e.offen?'{{J:offen}}':
    (e.quittiert?'{{J:quittiert}} '+e.quittiert.slice(11)+(e.benutzer?' – '+e.benutzer:''):(e.pflicht?'':'{{J:ohne Quittierpflicht}}'));
   if(e.gegangen&&!e.notiz)st+=(st?' · ':'')+'{{J:gegangen}} '+e.gegangen.slice(11);
   h+='<div class="ev"><span>'+esc(e.zeit)+'</span><span class="prio p-'+esc(e.notiz?'Notiz':e.prio_de)+'">'+esc(e.notiz?'{{J:Notiz}}':e.prio)+
    '</span><span class="tx"><b>'+esc(e.notiz?'':e.trigger)+'</b> '+esc(e.text||'')+' <span class="st">'+esc(st)+'</span></span>'+
    '<button data-go="'+e.ts+'" title="{{J:Im Diagramm anzeigen}}">⌖</button>'+
    (j.write&&e.offen?'<button data-ack="'+e.id+'">✓ {{J:Quittieren}}</button>':'')+'</div>';});
  $('evlist').innerHTML=h||'<div class="msg">{{J:Keine Ereignisse im Zeitraum.}}</div>';
  $('evlist').querySelectorAll('button[data-go]').forEach(function(b){b.onclick=function(){
   var t=+b.getAttribute('data-go');$('dlgEvents').classList.remove('open');
   rulers=[t*1000,t*1000+Math.max(winS*100,1000)];$('rulers').className='on';goTo(t,true);};});
  $('evlist').querySelectorAll('button[data-ack]').forEach(function(b){b.onclick=function(){ack([+b.getAttribute('data-ack')]);};});
 }).catch(function(e){$('evErr').textContent='⚠ '+e.message;});
}
function post(u,body){return fetchJson(u,{method:'POST',cache:'no-store',headers:{'Content-Type':'application/json'},
 body:JSON.stringify(body)});}
function ack(ids){post('/api/ereignisse',{aktion:'quittieren',ids:ids}).then(function(){loadEvents();refresh();})
 .catch(function(e){$('evErr').textContent='⚠ '+e.message;});}
function note(){
 var t=window.prompt(rulers?'{{J:Notiz zum Zeitpunkt von Lineal 1:}}':'{{J:Notiz (Zeitpunkt jetzt):}}');
 if(!t)return;
 post('/api/ereignisse',{aktion:'notiz',text:t,ts:rulers?rulers[0]/1000:null}).then(function(){loadEvents();refresh();})
  .catch(function(e){$('evErr').textContent='⚠ '+e.message;});
}

/* ---------- Bedienung ---------- */
function init(){
 var sel=$('win');WINS.forEach(function(w){var o=document.createElement('option');o.value=w[0];o.textContent=w[1];sel.appendChild(o);});
 if(!WINS.some(function(w){return w[0]===winS;}))winS=60;
 setWindow(winS);
 sel.onchange=function(){winS=+sel.value;store('win',String(winS));setWindow(winS);refresh();};
 $('back').onclick=function(){var base=endT!==null?endT:(lastRes?lastRes.t1:0);endT=base-winS/2;
  $('live').className='';refresh();};
 $('fwd').onclick=function(){if(endT===null)return;endT+=winS/2;
  if(lastRes&&lastRes.last!==null&&endT>=lastRes.last){endT=null;$('live').className='on';}refresh();};
 $('live').onclick=function(){endT=null;paused=false;$('pause').className='';$('live').className='on';refresh();};
 $('pause').onclick=function(){paused=!paused;$('pause').className=paused?'on':'';};
 $('goto').onchange=function(){var t=fromInput($('goto').value);if(t!==null)goTo(t,false);};
 $('zreset').onclick=function(){cos.forEach(clearOwn);setActive(null);
  endT=null;paused=false;$('pause').className='';$('live').className='on';refresh();};
 $('sync').onclick=function(){var src=active&&active.own?active:cos.filter(function(c){return c.own;})[0];if(!src)return;
  var o=src.own;cos.forEach(clearOwn);setWindow(Math.max((o.t1-o.t0)/1000,1));endT=o.t1/1000;paused=true;
  $('pause').className='on';$('live').className='';setActive(src);$('sync').disabled=true;refresh();};
 $('rulers').onclick=toggleRulers;
 $('export').onclick=openExport;$('export').disabled=true;
 $('xClose').onclick=function(){$('dlgExport').classList.remove('open');};
 $('xGo').onclick=function(){var u=exportRange();if(u){var f=document.querySelector('input[name=xf]:checked').value;
  download('/api/export?'+u+'&format='+f,'export.'+f,false);}};
 $('xReport').onclick=function(){var u=exportRange();if(u)download('/api/bericht?'+u,'bericht.pdf',true);};
 $('events').onclick=openEvents;$('evClose').onclick=function(){$('dlgEvents').classList.remove('open');};
 $('evDays').onchange=loadEvents;$('evOpen').onchange=loadEvents;
 $('evAckAll').onclick=function(){if(window.confirm('{{J:Alle offenen Ereignisse quittieren?}}'))ack('alle');};
 $('evNote').onclick=note;
 document.querySelectorAll('.dlg').forEach(function(d){d.addEventListener('click',function(e){if(e.target===d)d.classList.remove('open');});});
 var bp=$('boolplot');bp.checked=boolPlot;
 bp.onchange=function(){boolPlot=bp.checked;store('bool',boolPlot?'1':'0');cos.forEach(style);};
 tick();
 timer=setInterval(tick,1000);
}
loadChartJs(init);
window.addEventListener('resize',function(){if(maxCo)headerHeight();cos.forEach(function(c){if(c.chart)c.chart.resize();});});
/* Vollbild verlassen: Esc (ohne echtes Vollbild), Ende des echten Vollbilds (Esc/F11 des Browsers), Zurück-Geste */
document.addEventListener('keydown',function(e){if(e.key==='Escape'){
 var open=document.querySelector('.dlg.open');if(open){open.classList.remove('open');return;}
 if(maxCo&&!document.fullscreenElement)exitMax(false);}});
document.addEventListener('fullscreenchange',function(){if(!document.fullscreenElement&&maxCo)exitMax(false);
 else if(maxCo){headerHeight();resizeAll();}});
window.addEventListener('popstate',function(){if(maxCo)exitMax(true);});
window.__plc={cos:function(){return cos;},rulers:function(){return rulers;},setOwn:function(i,a,b){setOwn(cos[i],a,b);},
 state:function(){return {endT:endT,winS:winS,paused:paused,cfg:cfg,last:lastRes};}};
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
<title>{{T:Anmelden}} – PLC Datenlogger</title>
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
.logos{display:flex;gap:10px;align-items:center;justify-content:space-between}.logos:not(:empty){margin-bottom:14px}
img.logo{height:40px;max-width:150px;object-fit:contain;background:#fff;border-radius:5px;padding:3px 6px}
</style>
</head>
<body>
<form method="post" action="login" autocomplete="on">
 <div class="logos">__LOGOS__</div>
 <h1>PLC Datenlogger</h1>
 <label for="b">{{T:Benutzer}}</label><input id="b" name="benutzer" autocomplete="username" required autofocus>
 <label for="p">{{T:Passwort}}</label><input id="p" name="passwort" type="password" autocomplete="current-password" required>
 <button type="submit">{{T:Anmelden}}</button>
 <p class="err">__ERR__</p>
 __WARN__
</form>
</body>
</html>
"""
