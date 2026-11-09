# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""MQTT: Ausgang (plc_mqtt.MqttPublisher, auch mit dem Recorder) und Treiber „mqtt“ (Eingang) gegen einen Broker.

Broker: der kleine Test-Broker (tests/mqtt_broker.py); ist ``PLC_TEST_MQTT`` gesetzt (z. B. 127.0.0.1:1883, Linux-CI
mit Mosquitto), läuft der Treibertest zusätzlich gegen diesen echten Broker.
"""
import json
import math
import os
import time

import pytest

pytest.importorskip("paho.mqtt.client")

from mqtt_broker import Broker  # noqa: E402


def wait_for(cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


@pytest.fixture
def broker():
    b = Broker()
    yield b
    b.close()


def test_settings_and_helpers():
    import plc_mqtt as m
    s = m.settings('{"aktiv": 1, "host": " broker ", "port": "99999", "qos": 5, "modus": "x", "basis": "/a/b/"}')
    assert s["aktiv"] is True and s["host"] == "broker" and s["port"] == 65535 and s["qos"] == 1
    assert s["modus"] == "aenderung" and s["basis"] == "a/b" and m.settings("kaputt")["port"] == 1883
    assert m.slug("Halle/1 #+") == "Halle_1 __" and m.object_id("Plc-Logger/Linie 1") == "plc_logger_linie_1"
    assert m.base_topic({"basis": ""}, "Anlage/A") == "plc-logger/Anlage_A"
    assert m.format_value(True, True) == "1" and m.format_value(math.nan) == "" and m.format_value(0.1 + 0.2) == "0.3"
    assert m.describe({"aktiv": False}) == m.tr("aus")
    assert "mqtts://b:8883" in m.describe({"aktiv": True, "host": "b", "port": 8883, "tls": True, "ha": True})


def test_payload_parsing():
    from plc_treiber.mqtt import check_topic, payload_value, split_address
    assert split_address("a/b|x.y[2].z") == ("a/b", ["x", "y", 2, "z"])
    assert payload_value(b" 21.5 ") == 21.5 and payload_value(b"21,5") == 21.5
    assert payload_value(b"ON") == 1.0 and payload_value("aus") == 0.0
    assert payload_value(b'{"AM2301": {"Temperature": 22.1}}', ["AM2301", "Temperature"]) == 22.1
    assert payload_value(b'{"l": [1, {"w": true}]}', ["l", 1, "w"]) == 1.0
    assert payload_value(b'{"v": "17"}', ["v"]) == 17.0
    with pytest.raises(ValueError):
        payload_value(b"hallo")
    with pytest.raises(ValueError):
        payload_value(b'{"a": 1}', ["b"])
    assert check_topic("a/+/b") and check_topic("") and check_topic("a|") and not check_topic("a/b|c.d")


def _plc(port, **kw):
    from plc_common import Plc
    from plc_treiber import get_driver
    drv = get_driver("mqtt")
    params = drv.default_params()
    params.update(host="127.0.0.1", port=port, timeout_s=3.0, **kw)
    return drv, Plc(name="Broker", driver="mqtt", params=params)


def _vars(*addresses):
    from plc_common import Variable
    return [Variable(name=f"v{i}", address=a, dtype="REAL") for i, a in enumerate(addresses)]


def _driver_roundtrip(publish, host_port, drop=None):
    host, port = host_port
    drv, plc = _plc(port, max_alter_s=0)
    plc.params["host"] = host
    vs = _vars("halle1/temp", "tele/s1/SENSOR|AM2301.Temperature", "schalter/1", "fehlt/nie", "kaputt/x")
    r = drv.create_reader(plc, vs)
    assert r.connect() == 5
    try:
        vals = r.read()
        assert all(math.isnan(x) for x in vals)                     # noch nichts empfangen
        publish("halle1/temp", "21.5")
        publish("tele/s1/SENSOR", json.dumps({"AM2301": {"Temperature": 19.25, "Humidity": 40}}))
        publish("schalter/1", "ON")
        publish("kaputt/x", "Text")
        assert wait_for(lambda: not math.isnan(r.read()[2]))
        assert wait_for(lambda: (r.read(), "kaputt/x" in r.errors)[1])    # letzte Nachricht auch angekommen
        vals = r.read()
        assert vals[:3] == [21.5, 19.25, 1.0] and math.isnan(vals[3]) and math.isnan(vals[4])
        assert "kaputt/x" in r.errors
        plc.params["max_alter_s"] = 0.2                             # Höchstalter: alte Werte -> kein Wert
        time.sleep(0.4)
        assert all(math.isnan(x) for x in r.read())
        if drop:
            drop()
            assert wait_for(lambda: not r.connected.is_set())
            with pytest.raises(ConnectionError):
                r.read()
    finally:
        r.close()


def test_driver_reads_topics(broker):
    _driver_roundtrip(broker.publish, ("127.0.0.1", broker.port), drop=broker.drop_all)


def test_driver_real_broker():
    """Gegen einen echten Broker (Linux-CI: Mosquitto), sonst übersprungen."""
    addr = os.environ.get("PLC_TEST_MQTT", "")
    if not addr:
        pytest.skip("PLC_TEST_MQTT nicht gesetzt")
    host, _sep, port = addr.partition(":")
    from plc_mqtt import make_client
    c = make_client()
    c.connect(host, int(port or 1883))
    c.loop_start()
    assert wait_for(c.is_connected)                     # erst nach der Antwort des Brokers senden
    try:
        _driver_roundtrip(lambda t, p: c.publish(t, p, qos=1).wait_for_publish(3), (host, int(port or 1883)))
    finally:
        c.disconnect()
        c.loop_stop()


def test_driver_login_refused():
    b = Broker(users={"chef": "geheim"})
    try:
        drv, plc = _plc(b.port, benutzer="chef", passwort="falsch")
        r = drv.create_reader(plc, _vars("a"))
        with pytest.raises(ConnectionError, match="Anmeldung"):
            r.connect()
        plc.params["passwort"] = "geheim"
        r = drv.create_reader(plc, _vars("a"))
        assert r.connect() == 1
        r.close()
    finally:
        b.close()
    drv, plc = _plc(1)                                              # kein Broker
    with pytest.raises(ConnectionError):
        drv.create_reader(plc, _vars("a")).connect()


def test_browse_candidates():
    from plc_treiber.mqtt_browser import candidates, clean_name
    found = candidates({"halle/temp": b"21.5", "dev/state": b"true", "tele/s1/SENSOR": json.dumps(
        {"Time": "2026", "AM2301": {"Temperature": 19.2, "Humidity": 40}, "list": [1, 2]}).encode(),
        "text": b"hallo"})
    addr = [f[0] for f in found]
    assert addr == ["dev/state", "halle/temp", "tele/s1/SENSOR|AM2301.Humidity",
                    "tele/s1/SENSOR|AM2301.Temperature", "tele/s1/SENSOR|list[0]", "tele/s1/SENSOR|list[1]"]
    assert found[0][2] == "BOOL" and clean_name(found[3][3]) == "SENSOR_AM2301_Temperature"


def test_publisher_topics_change_mode_json_ha(broker):
    import plc_mqtt as m
    from plc_common import Plc, Variable
    from plc_events import Trigger
    vs = [Variable(name="Temp", address="DB1.DBD0", dtype="REAL"),
          Variable(name="Pumpe", address="M0.0", dtype="BOOL"),
          Variable(name="Mittel", formula="Temp*2", dtype="REAL")]
    status = [("ok", "verbunden")]
    pub = m.MqttPublisher({"projekt": "Anlage A", "mqtt": {"aktiv": True, "host": "127.0.0.1", "port": broker.port,
                                                            "intervall_ms": 50, "format": "beide", "ha": True}},
                          vs, [Plc(name="Linie 1")], [Trigger(name="Übertemp", bedingung="Temp>50")],
                          status_fn=lambda: status)
    base = "plc-logger/Anlage A"
    assert pub.start()
    try:
        assert wait_for(lambda: broker.messages(f"{base}/status") == [b"online"])
        pub.update(1.0, [21.5, 1.0, 43.0])
        assert wait_for(lambda: broker.messages(f"{base}/Berechnet/Mittel") == [b"43"])
        assert broker.messages(f"{base}/Linie 1/Temp") == [b"21.5"]
        assert broker.messages(f"{base}/Linie 1/Pumpe") == [b"1"]
        assert broker.retained[f"{base}/Linie 1/Temp"] == b"21.5"
        doc = json.loads(broker.messages(f"{base}/werte")[-1])
        assert doc["werte"] == {"Temp": 21.5, "Pumpe": 1, "Mittel": 43.0} and doc["ts"] == 1.0
        assert wait_for(lambda: broker.messages(f"{base}/status/Linie 1") == [b"1"])
        node = m.object_id(base)
        cfg = json.loads(broker.retained[f"homeassistant/sensor/{node}/linie_1_temp/config"])
        assert cfg["state_topic"] == f"{base}/Linie 1/Temp" and cfg["availability_topic"] == f"{base}/status"
        bcfg = json.loads(broker.retained[f"homeassistant/binary_sensor/{node}/linie_1_pumpe/config"])
        assert bcfg["payload_on"] == "1"
        assert f"homeassistant/binary_sensor/{node}/ereignis_bertemp/config" in broker.retained
        # bei Änderung: nur Temp neu; NaN -> leere Nachricht
        pub.update(2.0, [22.0, 1.0, math.nan])
        assert wait_for(lambda: broker.messages(f"{base}/Linie 1/Temp") == [b"21.5", b"22"])
        assert wait_for(lambda: broker.messages(f"{base}/Berechnet/Mittel") == [b"43", b""])
        time.sleep(0.2)
        assert broker.messages(f"{base}/Linie 1/Pumpe") == [b"1"]
        assert f"{base}/Berechnet/Mittel" not in broker.retained
        # Ereignis
        pub.event("KOMMT", "Übertemp", "Alarm", "zu heiß", 3.0)
        assert wait_for(lambda: broker.messages(f"{base}/ereignis/Übertemp")[-1:] == [b"1"])
        ev = json.loads(broker.messages(f"{base}/ereignisse")[-1])
        assert ev["art"] == "KOMMT" and ev["trigger"] == "Übertemp"
        # Verbindungsabbruch: letzter Wille, dann Wiederverbinden und alles neu senden
        broker.drop_all()
        assert wait_for(lambda: broker.messages(f"{base}/status")[-2:] == [b"offline", b"online"], 15)
        assert wait_for(lambda: broker.messages(f"{base}/Linie 1/Pumpe") == [b"1", b"1"])
    finally:
        pub.stop()
    assert broker.messages(f"{base}/status")[-1] == b"offline"


def test_publisher_cyclic_json_only(broker):
    import plc_mqtt as m
    from plc_common import Plc, Variable
    pub = m.MqttPublisher({"mqtt": {"aktiv": True, "host": "127.0.0.1", "port": broker.port, "intervall_ms": 50,
                                    "format": "json", "modus": "zyklisch", "basis": "x/y", "ha": True,
                                    "retain": False}},
                          [Variable(name="A", address="1", dtype="REAL")], [Plc(name="P")])
    assert pub.start()
    try:
        pub.update(1.0, [5.0])
        assert wait_for(lambda: len(broker.messages("x/y/werte")) >= 3)
        assert not broker.messages("x/y/P/A") and "x/y/werte" not in broker.retained
        cfg = json.loads(broker.retained["homeassistant/sensor/x_y/p_a/config"])
        assert cfg["state_topic"] == "x/y/werte" and "value_json" in cfg["value_template"]
    finally:
        pub.stop()
    assert not m.MqttPublisher({"mqtt": {"aktiv": True, "host": ""}}, [], [])       # ohne Broker: aus


def test_recorder_publishes_and_reads_back(broker, tmp_path):
    """Demo-Aufzeichnung sendet an den Broker; eine zweite Steuerung mit Treiber mqtt liest die Werte zurück."""
    from plc_common import Plc, Variable, default_connection
    from plc_recorder import Recorder, demo_config
    from plc_treiber import get_driver
    charts, variables = demo_config()
    conn = default_connection()
    conn.update(csv_ordner=str(tmp_path), csv_aktiv=0, projekt="Demo",
                mqtt={"aktiv": True, "host": "127.0.0.1", "port": broker.port, "intervall_ms": 100})
    rec = Recorder(conn, [Plc(name="SPS")], charts, variables, demo=True)
    rec.start()
    try:
        assert rec.mqtt is not None, list(rec.messages)
        name = next(v.name for v in variables if not v.formula and v.dtype != "BOOL")
        topic = f"plc-logger/Demo/SPS/{name}"
        assert wait_for(lambda: broker.messages(topic))
        drv = get_driver("mqtt")
        params = drv.default_params()
        params.update(host="127.0.0.1", port=broker.port)
        r = drv.create_reader(Plc(name="B", driver="mqtt", params=params),
                              [Variable(name="x", address=topic, dtype="REAL")])
        r.connect()
        try:
            assert wait_for(lambda: not math.isnan(r.read()[0]))          # gespeicherte Nachricht (retain)
        finally:
            r.close()
    finally:
        rec.stop()
    assert rec.mqtt is None
    assert broker.messages("plc-logger/Demo/status")[-1] == b"offline"
