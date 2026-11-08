# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Treiber „mqtt“: Werte von einem MQTT-Broker aufzeichnen (Sensoren, IoT-Geräte, Tasmota/Shelly, Node-RED,
Steuerungen mit MQTT-Bibliothek). Bibliothek: paho-mqtt.

Adresse einer Variable: das Topic, optional mit „|“ und einem Pfad in einer JSON-Nachricht::

    halle1/temperatur                   Nachricht "21.5" (auch "true"/"false", "on"/"off", "1"/"0")
    tele/sonoff/SENSOR|AM2301.Temperature    {"AM2301": {"Temperature": 21.5, …}}
    werte|daten[2].wert                 Listenelemente mit [i]

Der Treiber abonniert alle Topics (ohne Platzhalter „+“/„#“) und liefert in jedem Lesezyklus den zuletzt empfangenen
Wert; noch keiner empfangen oder älter als „Höchstalter“ -> kein Wert (NaN). Bricht die Verbindung zum Broker ab,
meldet ``read`` einen Fehler und der Logger verbindet neu.
"""
import json
import math
import re
import threading
import time

from plc_i18n import tr
from plc_treiber.base import NAN, BrowseResult, Driver, Param, Reader

TRUE_WORDS = {"true", "on", "yes", "ja", "ein", "an", "high", "open", "auf"}
FALSE_WORDS = {"false", "off", "no", "nein", "aus", "low", "closed", "zu"}
_PATH_PART = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def split_address(address):
    """'topic|pfad' -> (topic, [Pfadteile]); Teile: Schlüssel (str) oder Listenindex (int)."""
    topic, _sep, path = (address or "").partition("|")
    parts = []
    for key, idx in _PATH_PART.findall(path.strip()):
        parts.append(int(idx) if idx else key)
    return topic.strip(), parts


def check_topic(address):
    """Formale Prüfung -> Fehlertext oder ""."""
    topic, parts = split_address(address)
    if not topic:
        return tr("Topic fehlt")
    if "+" in topic or "#" in topic:
        return tr("Platzhalter „+“ und „#“ sind im Topic einer Variable nicht erlaubt")
    if len(topic.encode("utf-8")) > 65535:
        return tr("Topic zu lang")
    _t, _sep, path = address.partition("|")
    if _sep and not parts:
        return tr("Pfad nach „|“ fehlt (z. B. sensor.temperatur)")
    return ""


def payload_value(payload, parts=()):
    """Nachricht (bytes/str) -> float; ``parts``: Pfad in einer JSON-Nachricht. Nicht lesbar -> ValueError."""
    text = payload.decode("utf-8", "replace") if isinstance(payload, (bytes, bytearray)) else str(payload)
    text = text.strip()
    if not parts:
        low = text.lower()
        if low in TRUE_WORDS:
            return 1.0
        if low in FALSE_WORDS:
            return 0.0
        try:
            return float(text.replace(",", ".")) if text.count(",") == 1 and "." not in text else float(text)
        except ValueError:
            pass
    try:
        data = json.loads(text)
    except ValueError:
        raise ValueError(tr("kein Zahlenwert: „{0}“").format(text[:40])) from None
    for p in parts:
        try:
            data = data[p]
        except (KeyError, IndexError, TypeError):
            raise ValueError(tr("„{0}“ nicht in der Nachricht").format(p)) from None
    if isinstance(data, bool):
        return 1.0 if data else 0.0
    if isinstance(data, (int, float)):
        return float(data)
    if isinstance(data, str):
        return payload_value(data)
    raise ValueError(tr("kein Zahlenwert an dieser Stelle der Nachricht"))


class MqttReader(Reader):
    """Abonniert die Topics der Variablen und hält je Topic die letzte Nachricht."""

    def connect(self):
        from plc_mqtt import make_client, reason_ok, reason_text
        p = self.plc.params
        self.items = []
        topics = {}
        for v in self.vars:
            err = check_topic(v.address)
            if err:
                self.errors[v.address] = err
                self.items.append(None)
                continue
            topic, parts = split_address(v.address)
            topics[topic] = None
            self.items.append((topic, parts, v.address))
        self.lock = threading.Lock()
        self.last = {}                      # Topic -> (Nachricht, Empfangszeit)
        self.connected = threading.Event()
        self.answer = threading.Event()
        self.refused = ""
        client = make_client(p.get("client_id", ""), p.get("benutzer", ""), p.get("passwort", ""),
                             bool(p.get("tls")), bool(p.get("tls_pruefen", True)), p.get("ca", ""))
        qos = int(p.get("qos", 0) or 0)

        def on_connect(c, userdata, flags, rc, *rest):
            if reason_ok(rc):
                if topics:
                    c.subscribe([(t, qos) for t in topics])
                self.connected.set()
            else:
                self.refused = reason_text(rc)
            self.answer.set()

        def on_disconnect(c, userdata, *args):
            self.connected.clear()

        def on_message(c, userdata, msg):
            with self.lock:
                self.last[msg.topic] = (msg.payload, time.time())

        client.on_connect, client.on_disconnect, client.on_message = on_connect, on_disconnect, on_message
        timeout = float(p.get("timeout_s", 5.0) or 5.0)
        try:
            client.connect(p.get("host", ""), int(p.get("port", 1883) or 1883), keepalive=30)
        except OSError as e:
            raise ConnectionError(tr("Broker {0} nicht erreichbar: {1}").format(self.driver.summary(self.plc), e)) \
                from None
        client.loop_start()
        self.client = client
        if not self.answer.wait(timeout) or not self.connected.is_set():
            self.close()
            raise ConnectionError(tr("Broker lehnt die Anmeldung ab: {0}").format(self.refused) if self.refused
                                  else tr("Keine Antwort vom Broker {0}").format(self.driver.summary(self.plc)))
        return sum(1 for it in self.items if it)

    def read(self):
        if not self.connected.is_set():
            raise ConnectionError(tr("Verbindung zum Broker getrennt"))
        max_age = float(self.plc.params.get("max_alter_s", 0) or 0)
        now = time.time()
        with self.lock:
            last = dict(self.last)
        out = []
        for it in self.items:
            if it is None:
                out.append(NAN)
                continue
            topic, parts, address = it
            msg = last.get(topic)
            if msg is None or (max_age and now - msg[1] > max_age):
                out.append(NAN)
                continue
            try:
                x = payload_value(msg[0], parts)
                self.errors.pop(address, None)
            except ValueError as e:
                self.errors[address] = str(e)
                x = NAN
            out.append(x if not math.isinf(x) else NAN)
        return out

    def close(self):
        client = getattr(self, "client", None)
        if client is None:
            return
        self.client = None
        try:
            client.disconnect()
            client.loop_stop()
        except Exception:
            pass


class MqttDriver(Driver):
    """MQTT-Broker (Eingang): Variablen = Topics, optional mit Pfad in einer JSON-Nachricht."""
    id = "mqtt"
    name = "MQTT"
    description = tr("Werte von einem MQTT-Broker (Sensoren, IoT, Node-RED, Steuerungen mit MQTT)")
    library = "paho-mqtt"
    params = [
        Param("host", tr("Broker (Host)"), "text", "localhost", tip=tr("Rechnername oder IP-Adresse des Brokers")),
        Param("port", tr("Port"), "int", 1883, minimum=1, maximum=65535, tip=tr("1883, mit TLS meist 8883")),
        Param("tls", tr("TLS (verschlüsselt)"), "bool", False),
        Param("benutzer", tr("Benutzer"), "text", "", tip=tr("Leer = ohne Anmeldung")),
        Param("passwort", tr("Passwort"), "password", ""),
        Param("tls_pruefen", tr("Zertifikat prüfen"), "bool", True, advanced=True,
              tip=tr("Aus: auch selbstsignierte Zertifikate annehmen (nur im eigenen Netz)")),
        Param("ca", tr("CA-Zertifikat (Datei)"), "text", "", advanced=True,
              tip=tr("Leer = Zertifikate des Systems")),
        Param("client_id", tr("Client-ID"), "text", "", advanced=True, tip=tr("Leer = automatisch")),
        Param("qos", tr("QoS"), "choice", "0", choices=[("0", "0"), ("1", "1"), ("2", "2")], advanced=True),
        Param("max_alter_s", tr("Höchstalter eines Werts"), "float", 0.0, minimum=0, maximum=86400 * 365,
              suffix=" s", advanced=True,
              tip=tr("Ältere Werte gelten als „kein Wert“ (Sender ausgefallen); 0 = unbegrenzt")),
        Param("timeout_s", tr("Zeitlimit"), "float", 5.0, minimum=0.5, maximum=120, suffix=" s", advanced=True),
    ]
    types = ["REAL", "LREAL", "BOOL", "INT", "DINT"]
    default_type = "REAL"
    address_label = "Topic"
    address_hint = tr("Topic, optional mit Pfad in einer JSON-Nachricht: halle1/temperatur, "
                      "tele/sonoff/SENSOR|AM2301.Temperature")
    block_hint = tr("Blöcke sind bei MQTT nicht möglich – je Wert eine Variable")
    browse_label = tr("Topics vom Broker …")

    def summary(self, plc):
        p = plc.params
        return f"{'mqtts' if p.get('tls') else 'mqtt'}://{p.get('host', '')}:{p.get('port', 1883)}"

    def check_params(self, params):
        return "" if str(params.get("host", "")).strip() else tr("Broker (Host) fehlt")

    def check_address(self, address, dtype):
        return check_topic(address)

    def normalize_address(self, address, dtype):
        topic, _sep, path = (address or "").partition("|")
        return f"{topic.strip()}|{path.strip()}" if _sep else topic.strip()

    def check_block(self, block):
        return tr("Blöcke sind bei MQTT nicht möglich – je Wert eine Variable")

    def create_reader(self, plc, variables):
        return MqttReader(self, plc, variables)

    def browse(self, parent, ctx):
        """Auswahldialog: eine Weile am Broker mithören und empfangene Topics (mit Zahlen in JSON) anbieten."""
        from plc_treiber.mqtt_browser import MqttBrowserDialog
        dlg = MqttBrowserDialog(parent, ctx.plc, set(ctx.existing), ctx.target_labels, ctx.default_target)
        if not dlg.exec():
            return None
        res = BrowseResult(target_index=dlg.target_index)
        res.variables = list(dlg.result_vars)
        return res


DRIVER = MqttDriver()
