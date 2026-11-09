# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""MQTT im Logger: Werte an einen Broker senden (Ausgang, wie Webserver und OPC-UA-Server optional) und gemeinsame
Hilfen für den Treiber ``mqtt`` (Eingang, plc_treiber/mqtt.py). Bibliothek: paho-mqtt (2.x, 1.6 geht auch).

Topics des Ausgangs (``<basis>`` = Einstellung „Basis-Topic“, Vorgabe ``plc-logger/<Projekt>``)::

    <basis>/<Steuerung>/<Variable>      Wert als Text ("1"/"0" bei BOOL); leer = kein Wert (Verbindung gestört)
    <basis>/Berechnet/<Variable>        berechnete Variablen
    <basis>/werte                       JSON {"zeit": …, "ts": …, "werte": {Name: Wert}} (Format „JSON“ oder „beides“)
    <basis>/ereignis/<Trigger>          "1"/"0": Ereignis steht an
    <basis>/ereignisse                  JSON je Kommen/Gehen/Quittieren (nicht gespeichert)
    <basis>/status                      "online"/"offline" (Letzter Wille des Loggers)
    <basis>/status/<Steuerung>          "1"/"0": Steuerung verbunden; …/text: Zustandstext

Senden „bei Änderung“ (nur geänderte Werte, höchstens einmal je Intervall) oder „zyklisch“ (alle Werte je
Intervall). Mit Home-Assistant-Discovery erscheinen die Variablen dort automatisch als Sensoren.

Einstellung ``mqtt`` (JSON): aktiv, host, port, tls, tls_pruefen, ca, benutzer, passwort, client_id, basis, modus,
intervall_ms, format, qos, retain, ha, ha_prefix.
"""
import json
import math
import re
import socket
import ssl
import threading
import time
from datetime import datetime

from plc_i18n import N_, tr

MODES = {"aenderung": N_("Bei Änderung"), "zyklisch": N_("Zyklisch (alle Werte)")}
FORMATS = {"einzeln": N_("Ein Topic je Variable"), "json": N_("Ein JSON mit allen Werten"), "beide": N_("Beides")}
DEFAULTS = {"aktiv": False, "host": "", "port": 1883, "tls": False, "tls_pruefen": True, "ca": "",
            "benutzer": "", "passwort": "", "client_id": "", "basis": "", "modus": "aenderung",
            "intervall_ms": 1000, "format": "einzeln", "qos": 0, "retain": True, "ha": False,
            "ha_prefix": "homeassistant"}


def settings(raw) -> dict:
    """Einstellung ``mqtt`` (dict oder JSON-Text) mit Vorgabewerten ergänzt und geprüft."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except ValueError:
            raw = {}
    out = dict(DEFAULTS)
    for k, v in (raw or {}).items():
        if k in out:
            out[k] = v
    for k in ("aktiv", "tls", "tls_pruefen", "retain", "ha"):
        out[k] = bool(out[k])
    try:
        out["port"] = min(max(int(out["port"]), 1), 65535)
    except (TypeError, ValueError):
        out["port"] = 1883
    try:
        out["intervall_ms"] = min(max(int(out["intervall_ms"]), 50), 3_600_000)
    except (TypeError, ValueError):
        out["intervall_ms"] = 1000
    try:
        out["qos"] = min(max(int(out["qos"]), 0), 1)
    except (TypeError, ValueError):
        out["qos"] = 0
    if out["modus"] not in MODES:
        out["modus"] = "aenderung"
    if out["format"] not in FORMATS:
        out["format"] = "einzeln"
    for k in ("host", "ca", "benutzer", "passwort", "client_id", "basis", "ha_prefix"):
        out[k] = str(out[k] or "").strip() if k != "passwort" else str(out[k] or "")
    out["basis"] = out["basis"].strip("/")
    out["ha_prefix"] = out["ha_prefix"].strip("/") or "homeassistant"
    return out


def slug(name) -> str:
    """Teil eines Topics aus einem Namen: ohne „/“, „+“, „#“ und Steuerzeichen (die haben in MQTT Bedeutung)."""
    return re.sub(r"[/#+\x00-\x1f]", "_", str(name)).strip() or "_"


def object_id(text) -> str:
    """Kennung für Home Assistant (Kleinbuchstaben, Ziffern, Unterstrich)."""
    return re.sub(r"[^a-z0-9_]+", "_", str(text).lower()).strip("_") or "x"


def base_topic(s, project="") -> str:
    """Basis-Topic: eingestellt oder ``plc-logger/<Projekt bzw. Rechnername>``."""
    return s.get("basis") or "plc-logger/" + slug(project or socket.gethostname())


def broker_url(s) -> str:
    """Anzeige des Brokers: mqtt://host:port bzw. mqtts://…"""
    return f"{'mqtts' if s.get('tls') else 'mqtt'}://{s.get('host') or '?'}:{int(s.get('port') or 1883)}"


def describe(s, project="") -> str:
    """Kurztext für das Konfigurationsprogramm: „aus“ oder Broker, Basis-Topic und Art."""
    s = settings(s)
    if not s["aktiv"]:
        return tr("aus")
    extra = [tr(MODES[s["modus"]])]
    if s["ha"]:
        extra.append("Home Assistant")
    return f"{broker_url(s)} → {base_topic(s, project)}/…  ({', '.join(extra)})"


def format_value(x, is_bool=False) -> str:
    """Wert als Text für MQTT: BOOL "1"/"0", sonst bis 10 gültige Stellen; NaN -> "" (kein Wert)."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return ""
    if math.isnan(x):
        return ""
    if is_bool:
        return "1" if x else "0"
    if math.isinf(x):
        return "inf" if x > 0 else "-inf"
    return f"{x:.10g}"


# ---------------------------------------------------------------------------------------------------------------------
# paho-mqtt: Client erzeugen (Version 1.x und 2.x)
# ---------------------------------------------------------------------------------------------------------------------
def paho():
    """paho.mqtt.client oder ImportError mit verständlichem Text."""
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        raise ImportError(tr("Bibliothek paho-mqtt fehlt (pip install paho-mqtt)")) from None
    return mqtt


def make_client(client_id="", user="", password="", tls=False, verify=True, ca="", will=None):
    """paho-Client mit Anmeldung, TLS und letztem Willen (``will`` = (Topic, Text)) – noch nicht verbunden."""
    mqtt = paho()
    cid = client_id or f"plc-logger-{socket.gethostname()}-{int(time.time() * 1000) % 100000}"
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid, protocol=mqtt.MQTTv311)
    except AttributeError:                               # paho-mqtt 1.x
        client = mqtt.Client(client_id=cid, protocol=mqtt.MQTTv311)
    if user:
        client.username_pw_set(user, password or None)
    if tls:
        client.tls_set(ca_certs=ca or None, cert_reqs=ssl.CERT_REQUIRED if verify else ssl.CERT_NONE)
        if not verify:
            client.tls_insecure_set(True)
    if will:
        client.will_set(will[0], will[1], qos=1, retain=True)
    return client


def reason_ok(rc) -> bool:
    """Antwort des Brokers auf die Anmeldung erfolgreich (paho 1.x: Zahl, 2.x: ReasonCode)?"""
    try:
        return not rc.is_failure
    except AttributeError:
        return int(rc) == 0


def reason_text(rc) -> str:
    """Anmeldefehler als Text (z. B. „Not authorized“)."""
    try:
        import paho.mqtt.client as mqtt
        if isinstance(rc, int):
            return mqtt.connack_string(rc)
    except ImportError:
        pass
    return str(rc)


# ---------------------------------------------------------------------------------------------------------------------
# Ausgang: Werte an den Broker senden
# ---------------------------------------------------------------------------------------------------------------------
class MqttPublisher:
    """Sendet die Messwerte einer Aufzeichnung an einen MQTT-Broker. ``update`` (Sammler-Thread) übergibt jede
    Messzeile, ``event`` die Trigger; gesendet wird in einem eigenen Thread im Takt ``intervall_ms``. Verbindet nach
    Abbrüchen selbst neu (paho) und sendet dann alle Werte erneut."""

    def __init__(self, conn, variables, plcs, triggers=(), emit=None, status_fn=None):
        """Vorbereiten (noch nicht verbunden). Argumente wie beim OPC-UA-Server."""
        self.conn = conn if isinstance(conn, dict) else {}
        self.s = settings(self.conn.get("mqtt", "") if isinstance(conn, dict) else conn)
        self.vars, self.plcs = list(variables), list(plcs)
        self.trigger_names = [t.name for t in triggers]
        self.emit = emit or (lambda _t: None)
        self.status_fn = status_fn or (lambda: [])
        self.project = self.conn.get("projekt", "") or ""
        self.base = base_topic(self.s, self.project)
        self.lock = threading.Lock()
        self.latest = None                     # (ts, row)
        self.events = []                       # [(Art, Trigger, Prio, Text, ts)] seit dem letzten Senden
        self.active = {}                       # Trigger -> steht an
        self.connected = threading.Event()
        self.resend = threading.Event()        # nach (Wieder-)Verbindung alles neu senden
        self.stop_evt = threading.Event()
        self.thread = None
        self.client = None
        self.error = ""
        self.sent = 0                          # Zahl gesendeter Nachrichten (Anzeige, Test)
        used = set()
        self.topics = []                       # (Index, Topic, BOOL?, Name)
        for i, v in enumerate(self.vars):
            # „Berechnet“ bewusst unübersetzt: Topics bleiben beim Umschalten der Sprache gleich
            folder = "Berechnet" if v.formula else (self.plcs[v.plc].name if 0 <= v.plc < len(self.plcs)
                                                    else f"SPS {v.plc + 1}")
            topic = f"{self.base}/{slug(folder)}/{slug(v.name)}"
            while topic in used:
                topic += "_"
            used.add(topic)
            self.topics.append((i, topic, v.dtype == "BOOL" and not v.formula, v.name))

    def __bool__(self):
        """True, wenn der Ausgang eingeschaltet und ein Broker eingetragen ist."""
        return bool(self.s.get("aktiv") and self.s.get("host"))

    # ---- Schnittstelle zum Recorder ---------------------------------------------------------------------------------
    def update(self, ts, row):
        """Neueste Messzeile übernehmen (gesendet wird im eigenen Takt)."""
        with self.lock:
            self.latest = (ts, row)

    def event(self, kind, trigger, prio, text, ts):
        """Ereignis (gleiche Schnittstelle wie Notifier.event): Zustand merken, Meldung zum Senden vormerken."""
        with self.lock:
            if kind in ("KOMMT", "GEHT"):
                self.active[trigger] = (kind == "KOMMT")
            if len(self.events) < 1000:
                self.events.append((kind, trigger, prio, text, ts))

    def start(self):
        """Client anlegen und Verbindung im Hintergrund aufbauen -> True, wenn gestartet (die Verbindung selbst kann
        noch fehlen; paho verbindet laufend neu)."""
        if not self or self.thread is not None:
            return False
        s = self.s
        try:
            self.client = make_client(s["client_id"], s["benutzer"], s["passwort"], s["tls"], s["tls_pruefen"],
                                      s["ca"], will=(f"{self.base}/status", "offline"))
        except Exception as e:                 # Bibliothek fehlt, CA-Datei nicht lesbar …
            self.error = str(e) or type(e).__name__
            self.emit(tr("⚠ MQTT nicht gestartet: {0}").format(self.error))
            return False
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        # Wiederverbinden nach 1 s, bei weiteren Fehlschlägen bis 30 s Abstand
        self.client.reconnect_delay_set(1, 30)
        try:
            # connect_async blockiert nicht: ist der Broker beim Start nicht erreichbar, versucht paho es weiter
            self.client.connect_async(s["host"], int(s["port"]), keepalive=30)
            self.client.loop_start()
        except Exception as e:
            self.error = str(e) or type(e).__name__
            self.emit(tr("⚠ MQTT nicht gestartet: {0}").format(self.error))
            return False
        self.thread = threading.Thread(target=self._run, name="mqtt-publisher", daemon=True)
        self.thread.start()
        self.emit(tr("MQTT: sende an {0} → {1}/…").format(broker_url(s), self.base))
        return True

    def stop(self, wait_s=3.0):
        """Senden beenden: Status „offline“ melden, trennen."""
        if self.thread is None:
            return
        self.stop_evt.set()
        self.thread.join(wait_s)
        self.thread = None
        try:
            if self.connected.is_set():
                self.client.publish(f"{self.base}/status", "offline", qos=1, retain=True).wait_for_publish(2)
        except Exception:
            pass
        try:
            self.client.disconnect()
            self.client.loop_stop()
        except Exception:
            pass

    # ---- paho-Rückrufe (Netzwerk-Thread von paho) ----------------------------------------------------------------
    def _on_connect(self, client, userdata, flags, rc, *rest):
        """Anmeldung beantwortet (paho-Thread): bei Erfolg alles neu senden lassen, sonst den Grund melden."""
        if reason_ok(rc):
            self.connected.set()
            self.resend.set()
            self.error = ""
            self.emit(tr("MQTT verbunden: {0}").format(broker_url(self.s)))
        else:
            self.error = reason_text(rc)
            self.emit(tr("⚠ MQTT: Broker lehnt die Anmeldung ab: {0}").format(self.error))

    def _on_disconnect(self, client, userdata, *args):
        """Verbindung verloren (paho verbindet selbst neu); nur einmal melden, nicht beim gewollten Beenden."""
        if self.connected.is_set() and not self.stop_evt.is_set():
            self.emit(tr("⚠ MQTT: Verbindung zum Broker getrennt – verbinde neu …"))
        self.connected.clear()

    # ---- Sende-Thread ----------------------------------------------------------------------------------------------
    def _pub(self, topic, payload, retain=None, qos=None):
        """Eine Nachricht senden -> True, wenn paho sie angenommen hat."""
        info = self.client.publish(topic, payload, qos=self.s["qos"] if qos is None else qos,
                                   retain=self.s["retain"] if retain is None else retain)
        ok = info.rc == 0
        self.sent += ok
        return ok

    def _run(self):
        """Im Takt: nach (Wieder-)Verbindung Status und ggf. Discovery senden, dann Werte, Ereignisse, Zustände."""
        period = self.s["intervall_ms"] / 1000.0
        # Zuletzt gesendete Texte je Topic (für „bei Änderung“); nach einer neuen Verbindung geleert, damit alles neu
        # kommt
        last_vals, last_ev, last_st = {}, {}, {}
        last_ts = None
        while not self.stop_evt.is_set():
            if self.connected.is_set():
                try:
                    if self.resend.is_set():
                        self.resend.clear()
                        last_vals.clear()
                        last_ev.clear()
                        last_st.clear()
                        last_ts = None
                        self._pub(f"{self.base}/status", "online", retain=True, qos=1)
                        if self.s["ha"]:
                            self._discovery()
                    last_ts = self._publish(last_vals, last_ev, last_st, last_ts)
                except Exception as e:          # nie abbrechen; beim nächsten Takt erneut
                    self.emit(tr("⚠ MQTT: {0}").format(e))
            self.stop_evt.wait(period)

    def _publish(self, last_vals, last_ev, last_st, last_ts):
        """Werte (geänderte bzw. alle), Ereignisse und Zustände senden; Rückgabe: Zeitstempel der gesendeten Zeile."""
        s = self.s
        with self.lock:
            latest, events, active = self.latest, self.events, dict(self.active)
            self.events = []
        if latest is not None and (latest[0] != last_ts or s["modus"] == "zyklisch"):
            ts, row = latest
            if s["format"] in ("einzeln", "beide"):
                for i, topic, is_bool, _name in self.topics:
                    text = format_value(row[i] if i < len(row) else math.nan, is_bool)
                    if s["modus"] == "aenderung" and last_vals.get(topic) == text:
                        continue
                    if self._pub(topic, text):
                        last_vals[topic] = text
            if s["format"] in ("json", "beide"):
                values = {}
                for i, _topic, is_bool, name in self.topics:
                    text = format_value(row[i] if i < len(row) else math.nan, is_bool)
                    values[name] = None if text == "" else (int(text) if is_bool else float(text))
                if s["modus"] == "zyklisch" or values != last_vals.get("\0json"):
                    doc = {"zeit": datetime.fromtimestamp(ts).isoformat(timespec="milliseconds"),
                           "ts": round(ts, 3), "werte": values}
                    if self._pub(f"{self.base}/werte", json.dumps(doc, ensure_ascii=False, allow_nan=False)):
                        last_vals["\0json"] = values
            last_ts = ts
        for name in self.trigger_names:
            on = bool(active.get(name, False))
            if last_ev.get(name) != on and self._pub(f"{self.base}/ereignis/{slug(name)}", "1" if on else "0",
                                                    retain=True):
                last_ev[name] = on
        for kind, trigger, prio, text, ts in events:
            self._pub(f"{self.base}/ereignisse", json.dumps(
                {"art": kind, "trigger": trigger, "prio": prio, "text": text,
                 "zeit": datetime.fromtimestamp(ts).isoformat(timespec="milliseconds")}, ensure_ascii=False),
                retain=False)
        for k, (state, text) in enumerate(self.status_fn() or []):
            if k < len(self.plcs) and last_st.get(k) != (state, text):
                name = slug(self.plcs[k].name)
                if self._pub(f"{self.base}/status/{name}", "1" if state == "ok" else "0", retain=True) and \
                        self._pub(f"{self.base}/status/{name}/text", str(text), retain=True):
                    last_st[k] = (state, text)
        return last_ts

    def _discovery(self):
        """Home-Assistant-Discovery: je Variable ein Sensor (BOOL: binary_sensor), je Trigger ein binary_sensor."""
        from plc_common import APP_VERSION
        s = self.s
        # Home Assistant: Discovery-Topic <Präfix>/<Komponente>/<Knoten>/<Objekt>/config, Inhalt als JSON (retained)
        node = object_id(self.base)
        device = {"identifiers": [node], "name": "PLC Datenlogger" + (f" {self.project}" if self.project else ""),
                  "manufacturer": "PLC Datenlogger", "model": "PLC Logger", "sw_version": APP_VERSION}
        avail = {"availability_topic": f"{self.base}/status", "payload_available": "online",
                 "payload_not_available": "offline"}
        per_topic = s["format"] in ("einzeln", "beide")
        for i, topic, is_bool, name in self.topics:
            obj = object_id(topic[len(self.base) + 1:])
            cfg = {"name": name, "unique_id": f"{node}_{obj}", "object_id": f"{node}_{obj}", "device": device,
                   **avail}
            if per_topic:
                cfg["state_topic"] = topic
            else:
                cfg["state_topic"] = f"{self.base}/werte"
                cfg["value_template"] = "{{ value_json.werte[%s] }}" % json.dumps(name)
            if is_bool:
                cfg.update(payload_on="1", payload_off="0")
                comp = "binary_sensor"
            else:
                cfg["state_class"] = "measurement"
                comp = "sensor"
            self._pub(f"{s['ha_prefix']}/{comp}/{node}/{obj}/config", json.dumps(cfg, ensure_ascii=False),
                      retain=True, qos=1)
        for name in self.trigger_names:
            obj = "ereignis_" + object_id(name)
            cfg = {"name": tr("Ereignis {0}").format(name), "unique_id": f"{node}_{obj}", "object_id": f"{node}_{obj}",
                   "state_topic": f"{self.base}/ereignis/{slug(name)}", "payload_on": "1", "payload_off": "0",
                   "device_class": "problem", "device": device, **avail}
            self._pub(f"{s['ha_prefix']}/binary_sensor/{node}/{obj}/config", json.dumps(cfg, ensure_ascii=False),
                      retain=True, qos=1)
