# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Tests mit echter Qt-Oberfläche (PySide6, ohne Bildschirm: QT_QPA_PLATFORM=offscreen).

Die Fenster werden geöffnet, im Demo-Modus betrieben und ihre Dialoge aufgerufen; modale Dialoge kehren sofort zurück
(siehe conftest.qt_log). Ziel: Abstürze, fehlende Methoden und falsche Qt-Aufrufe finden, bevor ein Release entsteht."""
import json
import os
import sys
import time

import pytest

from conftest import wait

pytestmark = pytest.mark.gui


def _close(win):
    """Fenster schließen und Qt kurz Zeit zum Aufräumen geben."""
    win.close()
    wait(50)


def test_logger_demo_recording(qt_log, demo_config, tmp_path):
    """Logger im Demo-Modus: aufzeichnen, Analyse, Bericht, Ereignisse, Webadresse, Prozessbild, IO-Check,
    Offline-Ansicht mit Export, Sprung zu einem Ereignis und erneutes Laden der CSV-Datei – ohne kritische Meldung.
    """
    import plc_gui
    w = plc_gui.MainWindow(demo_config, demo=True)
    w.show()
    w.act_run.setChecked(True)
    wait(2500)
    assert w.rec is not None and w.rec.count() > 5, "Demo-Aufzeichnung liefert keine Werte"
    # Analyse-Fenster, Bericht, Notiz, Ereignisse, Web-Adresse
    w.open_analysis("xy")
    w.open_analysis("fft")
    qt_log.file = str(tmp_path / "bericht.pdf")
    w.make_report()
    assert os.path.exists(qt_log.file), qt_log.messages
    w.show_events()
    w.show_web_url()
    w.open_process_view()
    w.open_iocheck()
    wait(200)
    w._iocheck.close()
    # Offline: Lineale, Export
    w.act_online.setChecked(False)
    wait(300)
    qt_log.file = str(tmp_path / "export.csv")
    w.export_values()
    # Vom Ereignis zur Stelle im Diagramm (Daten im Speicher)
    t_mid = float(w.t[len(w.t) // 2])
    w.goto_time(t_mid, t_mid + 0.5, "Test")
    assert not w.online and abs(w.ruler_t[0] - t_mid) < 1e-6
    w.show_events()
    w.event_viewer.goto_selected()                           # ohne Auswahl: nichts
    w.act_run.setChecked(False)
    wait(300)
    # CSV wieder laden
    import glob
    files = [f for f in glob.glob(os.path.join(str(tmp_path), "*.csv")) if "ereignis" not in f and "export" not in f]
    assert files, "keine CSV-Datei geschrieben"
    qt_log.files = files[:1]
    w.load_csv()
    wait(200)
    assert w.source == "csv"
    # Ereignis außerhalb der geladenen Daten: passende CSV-Datei wird gesucht
    w.goto_time(float(w.t[0]) + 0.2)
    assert abs(w.ruler_t[0] - (float(w.t[0]) + 0.2)) < 1e-6
    # Menüleiste im Fenster (nicht im globalen Menü der Arbeitsoberfläche); Konfig-Editor unter Linux im selben Prozess
    assert not w.menuBar().isNativeMenuBar()
    if sys.platform != "win32":
        w.open_config()
        assert w._config_win.isVisible() and not w._config_win.menuBar().isNativeMenuBar()
        _close(w._config_win)
    # Ereignis von vorgestern: Werte kommen aus der Datenbank der Konfiguration (vor den CSV-Dateien)
    import datetime as dt
    import plc_db
    from plc_common import load_config, load_plcs, save_config
    conn, charts, cvars = load_config(demo_config)
    conn.update(db_typ="sqlite", db_datei=str(tmp_path / "werte.db"))
    save_config(conn, charts, cvars, demo_config, plcs=load_plcs(demo_config))
    b = plc_db.SqliteBackend(plc_db.db_settings(conn))
    b.connect()
    t_ev = time.time() - 2 * 86400
    z0 = dt.datetime.fromtimestamp(t_ev - 60, dt.timezone.utc)
    b.insert([(z0 + dt.timedelta(seconds=k), conn.get("projekt") or "", v.name, float(k)) for k in range(120)
              for v in cvars if not v.formula])
    b.close()
    w.goto_time(t_ev, t_ev + 5, "aus DB")
    assert w.source == "db" and abs(w.ruler_t[0] - t_ev) < 1e-6, qt_log.messages
    for kind, _title, text in qt_log.messages:
        assert kind != "critical", text
    _close(w)


def test_logger_separate_time_axes_and_zoom(qt_log, demo_config):
    """Mausrad/Zoom wirken nur auf ein Diagramm (eigene Zeitachse), „Zeitachsen angleichen“ setzt alle gleich,
    Zoom-Rechteck vergrößert Zeit und Y-Achsen, „Zoom zurücksetzen“ stellt die Skalierung wieder her."""
    import plc_gui
    from PySide6.QtCore import QRectF
    w = plc_gui.MainWindow(demo_config, demo=True)
    w.show()
    assert len(w.panels) >= 2, "Demo-Konfiguration braucht mindestens zwei Diagramme"
    w.act_run.setChecked(True)
    wait(2500)
    a, b = w.panels[0], w.panels[1]
    rng = lambda p: tuple(p.plot.getViewBox().viewRange()[0])
    # online: Mausrad über Diagramm b (Bereich ändern + Signal wie bei pyqtgraph) -> nur b bekommt eine eigene Breite
    t1 = rng(b)[1]
    b.plot.getViewBox().setXRange(t1 - 3, t1, padding=0)
    b.plot.getViewBox().sigRangeChangedManually.emit([True, False])
    w.dirty = True
    wait(400)
    assert not w.synced and w.active is b and abs(b.win - 3) < 0.01
    assert abs((rng(b)[1] - rng(b)[0]) - 3) < 0.05 and abs((rng(a)[1] - rng(a)[0]) - 3) > 0.5
    w.sync_axes()
    wait(400)
    assert w.synced and all(p.win is None for p in w.panels) and w.win_spin.value() == 3
    # offline: Zoom-Rechteck in a -> Zeit und Y nur in a; Scrollleiste verschiebt beide, Angleichen setzt gleich
    w.act_online.setChecked(False)
    wait(300)
    w.act_zoomrect.setChecked(True)
    assert all(p.plot.getViewBox().rect_zoom for p in w.panels)
    x0, x1 = rng(a)
    y0, y1 = a.axis_vbs[0].viewRange()[1]
    rect = QRectF(x0 + (x1 - x0) * 0.25, y0 + (y1 - y0) * 0.25, (x1 - x0) * 0.5, (y1 - y0) * 0.5)
    w.on_zoom_rect(a, rect)
    assert a.y_zoomed and abs(rng(a)[0] - rect.left()) < 1e-6 and abs(rng(a)[1] - rect.right()) < 1e-6
    assert abs(a.axis_vbs[0].viewRange()[1][0] - rect.top()) < 1e-6
    assert rng(b) == (x0, x1) and not b.y_zoomed
    width_a, width_b = rng(a)[1] - rng(a)[0], rng(b)[1] - rng(b)[0]
    w.scroll.setValue(max(0, w.scroll.value() - 100))
    assert abs((rng(a)[1] - rng(a)[0]) - width_a) < 1e-6 and abs((rng(b)[1] - rng(b)[0]) - width_b) < 1e-6
    w.on_zoom_rect(a, QRectF(rect.left(), rect.top(), 1e-9, 1e-9))     # Klick statt Rechteck: nichts
    w.reset_zoom()
    assert w.synced and rng(a) == rng(b) and not a.y_zoomed
    w.act_zoomrect.setChecked(False)
    w.act_run.setChecked(False)
    wait(300)
    for kind, _title, text in qt_log.messages:
        assert kind != "critical", text
    _close(w)


def test_config_export_grafana(qt_log, demo_config, tmp_path):
    """Konfigurationsprogramm: Grafana-Dashboard exportieren (VictoriaMetrics), ohne passende Datenbank ein Hinweis."""
    import json
    import plc_config
    from plc_common import load_config, load_plcs, save_config
    w = plc_config.ConfigWindow(demo_config)
    qt_log.file = str(tmp_path / "dash.json")
    w.export_grafana()                                           # Demo-Konfiguration ohne Datenbank
    assert not os.path.exists(qt_log.file) and "Datenbank" in qt_log.last()[2]
    _close(w)
    conn, charts, cvars = load_config(demo_config)
    conn.update(db_typ="victoriametrics", db_tabelle="anlage")
    save_config(conn, charts, cvars, demo_config, plcs=load_plcs(demo_config))
    w = plc_config.ConfigWindow(demo_config)
    w.export_grafana()
    d = json.load(open(qt_log.file, encoding="utf-8"))
    assert d["__inputs"][0]["pluginId"] == "prometheus" and any(p["type"] == "timeseries" for p in d["panels"])
    _close(w)


def test_netpanel_touch(qapp, demo_config):
    """Netzwerk-Panel: Übersicht mit IP und Webserver-QR, feste Adresse per Zifferntastatur, WLAN verbinden."""
    import plc_netpanel
    from test_logic import _FakeNm
    from plc_common import load_config, load_plcs, save_config
    conn, charts, cvars = load_config(demo_config)
    conn.update(web_aktiv=1, web_port=8081)
    save_config(conn, charts, cvars, demo_config, plcs=load_plcs(demo_config))
    fake = _FakeNm()
    w = plc_netpanel.NetPanel(plc_netz_fake(fake), config_path=demo_config, service="", background=False)
    w.resize(800, 480)
    w.show()
    assert "192.168.0.50/24" in w.lbl_info.text() and w.web_url() == "http://192.168.0.50:8081/"
    assert w.qr.matrix
    from plc_common import APP_VERSION
    assert APP_VERSION in w.lbl_version.text()
    w.show_power()                                               # Ausschalten: Seite ist die Rückfrage
    assert w.stack.currentWidget() is w.page_power
    w.power("reboot")
    assert ["systemctl", "reboot"] in fake.calls and not w.btn_poweroff.isEnabled()
    w.show_home()
    w.show_ip("ethernet")
    assert w.stack.currentWidget() is w.page_ip and w.btn_manual.isChecked() and w.ed_addr.text() == "192.168.0.50/24"
    w.ed_addr.clear()
    w.numpad.target = w.ed_addr
    for ch in "10.1.2.3/24":
        w.numpad.type(ch)
    w.ed_gw.setText("10.1.2.1")
    w.ed_dns.setText("")
    w.apply_ip()
    mod = next(c for c in fake.calls if c[:3] == ["nmcli", "connection", "modify"])
    assert "10.1.2.3/24" in mod and "10.1.2.1" in mod
    w.ed_gw.setText("192.168.9.1")                               # Gateway außerhalb des Netzes
    w.apply_ip()
    assert "Gateway" in w.lbl_ip_msg.text()
    w.show_wifi()
    assert w.list_wifi.count() == 3
    w.choose_wifi(w.list_wifi.item(2))
    assert w.chosen_wifi.ssid == "Gast"
    w.keyboard.target = w.ed_pw
    w.keyboard.toggle_shift()
    for ch in "Ab1":
        w.keyboard.type(ch)
    assert w.ed_pw.text() == "Ab1"
    w.connect_wifi()
    conn_call = next(c for c in fake.calls if c[:4] == ["nmcli", "device", "wifi", "connect"])
    assert conn_call[4:7] == ["Gast", "password", "Ab1"]
    assert w.stack.currentWidget() is w.page_home
    w.close()


def test_netpanel_time(qapp, demo_config, monkeypatch):
    """Netzwerk-Panel, Datum und Uhrzeit: von Hand stellen, Zeitzone, Uhrzeit der Steuerung lesen und übernehmen
    (Ortszeit bzw. UTC), automatischer Abgleich."""
    import datetime

    import plc_netpanel
    from test_logic import _FakeNm
    from plc_treiber.s7 import S7Driver
    monkeypatch.setattr(plc_netpanel, "save_settings", lambda data: None)
    plc_dt = datetime.datetime.now().replace(microsecond=0) - datetime.timedelta(hours=1, seconds=30)
    monkeypatch.setattr(S7Driver, "read_clock", lambda self, plc: plc_dt)
    fake = _FakeNm()
    w = plc_netpanel.NetPanel(plc_netz_fake(fake), config_path=demo_config, service="", background=False,
                              settings={})
    w.resize(800, 480)
    w.show()
    w.show_time()
    assert w.stack.currentWidget() is w.page_time and w.btn_ntp.isChecked() and not w.plc_row.isHidden()
    assert "Europe/Berlin" in w.lbl_time_info.text() and w.btn_plc.text() == "SPS 1"
    # von Hand: 29.02. gibt es 2027 nicht
    w.st_year.set_value(2028)
    w.st_month.set_value(2)
    w.st_day.set_value(29)
    w.st_year.step(-1)
    assert w.st_day.value == 28
    w.st_hour.set_value(23)
    w.st_hour.step(1)
    assert w.st_hour.value == 0
    w.st_min.set_value(5)
    fake.calls.clear()
    w.apply_time()
    assert ["timedatectl", "set-time", "2027-02-28 00:05:00"] in fake.calls, fake.calls
    assert not w.btn_ntp.isChecked() and "gestellt" in w.lbl_time_msg.text()
    # Zeitzone
    w.show_timezone()
    assert w.list_tz.count() == 3 and w.list_tz.currentItem().text() == "Europe/Berlin"
    w.list_tz.setCurrentRow(2)
    old_tz = os.environ.get("TZ")
    try:
        w.apply_timezone()
        assert ["timedatectl", "set-timezone", "UTC"] in fake.calls and w.stack.currentWidget() is w.page_time
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        if hasattr(time, "tzset"):                               # nicht unter Windows
            time.tzset()
    # Steuerung lesen und übernehmen
    w.read_plc_clock()
    assert w.plc_time and w.btn_take_plc.isEnabled() and "-363" in w.lbl_time_msg.text(), w.lbl_time_msg.text()
    fake.calls.clear()
    w.take_plc_clock()
    stamp = next(c for c in fake.calls if c[:2] == ["timedatectl", "set-time"])[2]
    assert abs((datetime.datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S") - plc_dt).total_seconds()) <= 2
    # Uhr der Steuerung in UTC: wird in Ortszeit umgerechnet
    w.btn_utc.setChecked(True)
    w.toggle_utc()
    assert not w.btn_take_plc.isEnabled()
    expect = plc_dt.replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
    assert w.plc_local_time(plc_dt) == expect
    # automatisch: NTP nicht synchronisiert -> stellen
    w.btn_auto.setChecked(True)
    w.toggle_auto()
    fake.calls.clear()
    w.auto_sync()
    assert any(c[:2] == ["timedatectl", "set-time"] for c in fake.calls) and "gestellt" in w.lbl_status.text()
    w.close()


def test_netpanel_display_dim(qapp, demo_config, tmp_path, monkeypatch):
    """Netzwerk-Panel: Display nach der eingestellten Zeit abdunkeln, die erste Berührung schaltet nur ein (löst keinen
    Knopf aus); ohne Hintergrundbeleuchtung schwarzes Bild."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    import plc_netpanel
    from test_logic import _FakeNm
    monkeypatch.setattr(plc_netpanel, "save_settings", lambda data: None)
    dev = tmp_path / "backlight" / "10-0045"
    dev.mkdir(parents=True)
    for name, val in (("max_brightness", "255"), ("brightness", "255"), ("bl_power", "0")):
        (dev / name).write_text(val)
    bl = plc_netpanel.Backlight(str(tmp_path / "backlight"))
    assert bl.available and bl.get() == 100
    settings = {"dunkel_min": 2, "hell_prozent": 80, "dunkel_prozent": 10}
    w = plc_netpanel.NetPanel(plc_netz_fake(_FakeNm()), config_path=demo_config, service="", background=False,
                              settings=settings, backlight=bl)
    w.resize(800, 480)
    w.show()
    wait(100)
    assert (dev / "brightness").read_text() == "204" and w.idle.isActive() and w.idle.interval() == 120_000
    w.dim()
    assert w.dimmed and (dev / "brightness").read_text() == "26"
    QTest.mouseClick(w.btn_time, Qt.MouseButton.LeftButton)          # erste Berührung: nur einschalten
    assert not w.dimmed and (dev / "brightness").read_text() == "204" and w.stack.currentWidget() is w.page_home
    QTest.mouseClick(w.btn_display, Qt.MouseButton.LeftButton)       # jetzt wirkt der Knopf
    assert w.stack.currentWidget() is w.page_display and "10-0045" in w.lbl_display_info.text()
    w.st_dim_level.step(-1)
    assert settings["dunkel_prozent"] == 5
    w.st_dim_min.set_value(0)
    assert not w.idle.isActive()                                     # 0 = nie abdunkeln
    w.dim()
    assert (dev / "brightness").read_text() == "13"
    w.st_dim_level.set_value(0)
    w.wake()
    w.dim()
    assert (dev / "bl_power").read_text() == "4"                     # 0 % = Beleuchtung aus
    w.wake()
    assert (dev / "bl_power").read_text() == "0" and w.stack.currentWidget() is w.page_home
    w.close()
    # ohne Hintergrundbeleuchtung: schwarzes Bild
    w2 = plc_netpanel.NetPanel(plc_netz_fake(_FakeNm()), config_path=demo_config, service="", background=False,
                               settings={}, backlight=plc_netpanel.Backlight(str(tmp_path / "keins")))
    w2.resize(800, 480)
    w2.show()
    w2.dim()
    assert w2.black.isVisible()
    QTest.mouseClick(w2.btn_time, Qt.MouseButton.LeftButton)
    assert not w2.black.isVisible() and w2.stack.currentWidget() is w2.page_home
    w2.close()


def test_netpanel_logger_start(qapp, demo_config, tmp_path, monkeypatch):
    """Netzwerk-Panel, Seite Logger: Konfigurationsdateien auflisten, über den Dienst starten (Ergänzung mit
    ExecStart) bzw. ohne Dienst direkt, stoppen."""
    import plc_headless
    import plc_netpanel
    from plc_common import Plc, load_config, save_config
    from test_logic import _FakeNm
    monkeypatch.setattr(plc_netpanel, "save_settings", lambda data: None)
    folder = tmp_path / "PLC Daten"
    folder.mkdir()
    conn, charts, cvars = load_config(demo_config)
    for name, project in (("kessel.json", "Kesselhaus"), ("linie2.json", "Linie 2")):
        conn["projekt"] = project
        save_config(conn, charts, cvars, str(folder / name), plcs=[Plc(name="SPS 1")])
    (folder / "anderes.json").write_text('{"kein": "logger"}')
    run_dir = str(tmp_path / "laufend")
    plc_headless.write_status({"pid": 999999, "projekt": "Alt", "start": 0}, run_dir)
    fake = _FakeNm()
    started = []
    ctl = plc_netpanel.LoggerControl(fake, "plc-datenlogger", dropin_dir=str(tmp_path / "dropin"),
                                     popen=lambda cmd, **kw: started.append(cmd),
                                     program=["/usr/bin/plc-datenlogger"], run_dirs=[run_dir])
    monkeypatch.setattr("time.sleep", lambda s: None)
    w = plc_netpanel.NetPanel(plc_netz_fake(fake), config_path=demo_config, service="", background=False,
                              settings={}, logger_ctl=ctl, config_dirs=[str(folder)])
    w.resize(800, 480)
    w.show()
    w.show_logger()
    names = [w.list_cfg.item(i).text() for i in range(w.list_cfg.count())]
    assert any("kessel.json" in n and "Kesselhaus" in n for n in names) and not any("anderes" in n for n in names)
    assert w.list_cfg.currentItem().toolTip() == demo_config                  # aktuelle Konfiguration markiert
    w.list_cfg.setCurrentRow(next(i for i, n in enumerate(names) if "linie2" in n))
    w.start_logger()
    conf = (tmp_path / "dropin" / "konfig.conf").read_text()
    assert f'ExecStart=/usr/bin/plc-datenlogger --headless "{folder / "linie2.json"}"' in conf, conf
    assert ["systemctl", "restart", "plc-datenlogger"] in fake.calls and ["systemctl", "enable", "plc-datenlogger"] \
        in fake.calls
    assert plc_headless.stop_requested(999999, run_dir)                       # laufender Logger wurde beendet
    assert w.config_path == str(folder / "linie2.json") and "Dienst" in w.lbl_logger_msg.text()
    w.stop_logger()
    assert ["systemctl", "disable", "plc-datenlogger"] in fake.calls
    # ohne Dienst: direkt starten
    monkeypatch.setattr(ctl, "has_service", lambda: False)
    w.list_cfg.setCurrentRow(0)
    w.start_logger()
    assert started and started[-1][-2:] == ["--headless", w.configs[0][0]], started
    assert "Neustart" in w.lbl_logger_msg.text()
    w.close()


def plc_netz_fake(fake):
    import plc_netz
    return plc_netz.Netz(run=fake)


def test_config_window(qt_log, demo_config):
    """Konfigurationsprogramm: Variablentabelle und Filter, alle Unterdialoge öffnen, Dialoge für OPC-UA-Server und
    Benachrichtigungen auswerten, Konfiguration speichern.
    """
    import plc_config
    w = plc_config.ConfigWindow(demo_config)
    w.show()
    wait(100)
    assert w.table.rowCount() > 3
    w.ed_filter.setText("Druck")
    wait(50)
    hidden = [w.table.isRowHidden(r) for r in range(w.table.rowCount())]
    assert any(hidden) and not all(hidden)
    w.ed_filter.setText("")
    # Dialoge öffnen (kehren sofort zurück)
    for name in ("show_drivers", "edit_triggers", "edit_web_users", "edit_rec_condition", "open_block_editor",
                 "add_computed", "edit_pid"):
        getattr(w, name)()
    w.edit_plc_params(0)
    w.edit_notify()
    w.edit_opcua_server()
    w.edit_mqtt()
    from plc_mqtt_dialog import MqttDialog
    md = MqttDialog(w, {"aktiv": True, "host": "broker", "ha": True}, "Testanlage")
    assert md.collect()["host"] == "broker" and md.collect()["ha"] and "plc-logger/Testanlage" in md.lbl_topics.text()
    md.ed_host.setText("")
    md.test_connection()                                     # Hinweis statt Absturz
    from plc_opcua_dialog import OpcUaServerDialog
    od = OpcUaServerDialog(w, {"aktiv": True, "port": 4841}, 2)
    assert od.collect()["port"] == 4841 and od.collect()["sicherheit"] == ["none"]
    from plc_notify_dialog import NotifyDialog
    nd = NotifyDialog(w, {"aktiv": True, "email": {"aktiv": True}}, "Testanlage")
    assert nd.collect()["email"]["aktiv"] and nd.collect()["aktiv"]
    nd.send_test()                                           # Fehlermeldung (kein Server) statt Absturz
    # Block mit Elementen in einem anderen Diagramm bei gewählter Achse (Fehler in 3.3.0: Auswahl überschrieben)
    from plc_common import Block
    w.blocks.append(Block(name="Ziele", address="DB9.DBD0", count=3, targets={1: (len(w.charts) - 1, 0)}))
    w.prop_key = ("axis", 0, 0)
    w.refresh_tree()
    w.blocks.pop()
    w.refresh_tree()
    w.sp_bar_w.setValue(8)
    w.ed_customer_logo.setText("kunde.png")
    w.web_users, w.web_rights = {"chef": "h1", "gast": "h2"}, {"chef": "schreiben", "gast": "lesen", "alt": "lesen"}
    w._update_web_users()
    assert "chef ✎" in w.lbl_web_users.text() and "gast ✎" not in w.lbl_web_users.text()
    assert w._write(demo_config), qt_log.messages
    doc = json.load(open(demo_config, encoding="utf-8"))
    assert doc["einstellungen"]["projekt"] == "Testanlage"
    assert doc["einstellungen"]["web_rechte"] == {"chef": "schreiben", "gast": "lesen"}
    assert int(doc["einstellungen"]["balken_breite"]) == 8 and doc["einstellungen"]["kundenlogo"] == "kunde.png"
    _close(w)


def test_iocheck_window(qt_log, demo_config, tmp_path, monkeypatch):
    """IO-Check: Liste importieren, Bereiche abtasten, filtern, Werte lesen (Demo), Status setzen, Matrix zeichnen,
    Projekt speichern, Ergebnis/Protokoll exportieren, mobile Ansicht starten und beim Schließen wieder beenden.
    """
    import plc_iocheck_dialog as d
    csv = tmp_path / "io.csv"
    csv.write_text("Adresse;Symbol;Kommentar;Schrank;Messbereich\nE0.0;B1;Endlage;+S1;\nE0.1;B2;Endlage 2;+S1;\n"
                   "A4.0;Y1;Ventil;+S2;\nEW256;PT1;Druck;+S2;0..10 bar\n", encoding="utf-8")
    w = d.IoCheckWindow(config_path=demo_config, demo=True)
    w.show()
    qt_log.file = str(csv)
    w.import_list()
    assert len(w.all_signals) == 4, qt_log.messages
    w.project.scans = [__import__("plc_iocheck").ScanRange("E0.0", 24)]
    w._rebuild()
    assert len(w.all_signals) == 26
    w.ed_filter.setText("Ventil")
    wait(50)
    assert w.proxy.rowCount() == 1
    w.ed_filter.setText("")
    w.chk_auto.setChecked(True)
    w.start_reading()
    wait(1500)
    assert any(s.value == s.value for s in w.all_signals), "keine Werte gelesen"
    w.view.selectRow(3)                                     # Analogsignal wählen: Analog-Feld
    wait(300)
    assert w.analog.isVisible()
    w.set_status([w.all_signals[0]], "ok")
    w.tabs.setCurrentIndex(1)
    wait(100)
    assert not w.matrix.grab().isNull()                      # Matrix zeichnen
    import plc_common
    monkeypatch.setattr(plc_common, "SETTINGS_FILE", str(tmp_path / "einstellungen.json"))
    w.act_moved.setChecked(False)                                    # „Was hat sich bewegt?“ ausblenden
    assert not w.side.isVisible() and plc_common.load_settings()["iocheck_bewegt"] is False
    w.act_moved.setChecked(True)
    monkeypatch.setattr(plc_common, "SETTINGS_FILE", str(tmp_path / "einstellungen.json"))
    cd = d.ColumnsDialog(w, {})
    cd.table.item(cd.fields.index("bmk"), 1).setText("")             # BMK abschalten
    cd._ok()
    assert cd.aliases["bmk"] == [] and cd.aliases["address"]
    io_mod = __import__("plc_iocheck")
    io_mod.save_aliases(cd.aliases)
    w._apply_columns()
    assert w.view.isColumnHidden(d.COL["bmk"]) and not w.view.isColumnHidden(d.COL["symbol"])
    io_mod.save_aliases({})
    w._apply_columns()
    assert not w.view.isColumnHidden(d.COL["bmk"])
    w.edit_scans()
    qt_log.file = str(tmp_path / "pruef")
    assert w.save_project(as_new=True)
    assert os.path.exists(str(tmp_path / "pruef.iocheck.json"))
    qt_log.file = str(tmp_path / "ergebnis.xlsx")
    w.export_result()
    assert os.path.exists(qt_log.file)
    qt_log.file = str(tmp_path / "protokoll.pdf")
    w.make_protocol()
    assert os.path.exists(qt_log.file)
    w.show_mobile()                                          # eigener Webserver
    assert w.web is not None
    w.stop_reading()
    w.dirty = False
    _close(w)
    import plc_web
    assert plc_web.io_bridge() is None and not plc_web.RUNNING


def test_about_help_and_dialogs(qt_log, demo_config, tmp_path, monkeypatch):
    """Info-Fenster, Anleitung öffnen, Ereignisanzeige und kleinere Dialoge ohne Absturz."""
    import plc_about
    from plc_events import EventLog
    from plc_event_viewer import EventViewer
    from plc_web_dialog import WebUsersDialog
    dlg = plc_about.AboutDialog()
    dlg.show()
    wait(50)
    dlg.close()
    plc_about.open_manual()
    plc_about.open_help("IO-Check (Inbetriebnahme)")
    log_path = os.path.join(os.path.dirname(demo_config), "ereignisse.csv")
    ev = EventViewer(EventLog(log_path))
    ev.show()
    wait(50)
    ev.close()
    WebUsersDialog(None, {}).show()
    # Schreibrecht je Benutzer: Häkchen in der Liste; ohne Eintrag schreiben, neue Benutzer nur lesen
    from PySide6.QtCore import Qt
    wd = WebUsersDialog(None, {"chef": "h1", "gast": "h2"}, {"gast": "lesen"})
    states = {wd.lst.item(i).text(): wd.lst.item(i).checkState() for i in range(wd.lst.count())}
    assert states == {"chef": Qt.CheckState.Checked, "gast": Qt.CheckState.Unchecked}
    next(wd.lst.item(i) for i in range(wd.lst.count()) if wd.lst.item(i).text() == "chef").setCheckState(
        Qt.CheckState.Unchecked)
    assert wd.rights == {"chef": "lesen", "gast": "lesen"}
    import plc_web_dialog
    monkeypatch.setattr(plc_web_dialog.QInputDialog, "getText", staticmethod(lambda *a, **k: ("neu", True)))
    monkeypatch.setattr(wd, "_set_password", lambda name: wd.users.__setitem__(name, "h3") or True)
    wd.add()
    assert wd.rights["neu"] == "lesen" and wd.lst.count() == 3
    wd.close()
    # Startbild des IO-Checks: Prüfstände und Konfigurationen, Demo-Knopf, kein „Neue Konfiguration“
    import plc_common
    from plc_splash import StartWindow
    monkeypatch.setattr(plc_common, "SETTINGS_FILE", str(tmp_path / "einstellungen.json"))
    proj = tmp_path / "anlage.iocheck.json"
    __import__("plc_iocheck").IoProject(config=demo_config).save(str(proj))
    plc_common.remember_iocheck(str(proj))
    sw = StartWindow("iocheck", demo_config)
    texts = [sw.list.item(i).text() for i in range(sw.list.count())]
    assert texts[0].startswith("anlage.iocheck.json") and any("test.json" in t for t in texts), texts
    sw.open_selected()
    assert sw.result["path"] == str(proj)
    sw.close()


def test_language_english(qt_log, demo_config):
    """Oberfläche auf Englisch: Fenster bauen sich auf, Texte sind übersetzt."""
    import plc_i18n
    plc_i18n.load("en")
    try:
        import plc_iocheck_dialog as d
        w = d.IoCheckWindow(config_path=demo_config, demo=True)
        assert w.tabs.tabText(0) == "Signal list"
        w.dirty = False
        _close(w)
    finally:
        plc_i18n.load("de")


def test_block_editor_ring(qt_log, monkeypatch):
    """Blockeditor: Spalte Ringpuffer (Formate des Ringpuffers, gesperrt bei Treibern ohne Ringpuffer), Test eines
    Ringpuffers, SPS-Vorlagen öffnen, Übernahme mit OK."""
    from plc_block_dialog import BlockEditor, C_PLC, C_RING, C_START, C_TYPE
    from plc_common import Block, Plc
    from plc_treiber.s7 import S7Driver
    plcs = [Plc(name="S7", driver="s7"), Plc(name="Modbus", driver="modbus")]
    blk = Block(name="Puffer", address="DB100.DBX0.0", dtype="REAL", count=3, ring=100, driver="s7")
    dlg = BlockEditor(None, [blk], [(0, 0)], ["Diagramm 1 › Achse 1"], lambda i: plcs[i], set(),
                      plc_names=[p.name for p in plcs])
    t = dlg.table
    assert t.cellWidget(0, C_RING).value() == 100 and not t.cellWidget(0, C_START).isEnabled()
    types = [t.cellWidget(0, C_TYPE).itemText(i) for i in range(t.cellWidget(0, C_TYPE).count())]
    assert "BOOL" not in types and "REAL" in types
    assert dlg.block_of_row(0).ring == 100
    monkeypatch.setattr(S7Driver, "read_ring_once", lambda self, plc, v: (
        [([0, 1, 2], 100.0, [1.0, 2.0, 3.0]), ([0, 1, 2], 100.05, [1.5, 2.5, 3.5])], {}, {"Puffer": 2}))
    t.selectRow(0)
    dlg.test_block()
    assert "Zähler 2" in qt_log.last()[2] and "50.0 ms" in qt_log.last()[2], qt_log.messages
    dlg.open_templates()
    assert qt_log.opened and "vorlagen" in qt_log.opened[-1]
    dlg.accept_checked()
    assert dlg.result_blocks and dlg.result_blocks[0].ring == 100
    t.cellWidget(0, C_PLC).setCurrentIndex(1)                 # Modbus: keine Ringpuffer
    assert t.cellWidget(0, C_RING).value() == 0 and not t.cellWidget(0, C_RING).isEnabled()
    dlg.close()


def test_record_display_flags(qt_log, demo_config):
    """Aufzeichnen/Anzeigen: Blockeditor (je Element und für alle), Variablentabelle und Baum des
    Konfigurationsprogramms, Logger zeigt nur angezeigte Variablen und speichert nur aufgezeichnete."""
    from PySide6.QtCore import Qt
    from plc_block_dialog import T_DISP, T_REC, BlockEditor
    from plc_common import Block, Plc, load_blocks, load_config, save_config
    plcs = [Plc(name="S7", driver="s7")]
    blk = Block(name="Blk", address="DB2.DBD0", dtype="REAL", count=4, driver="s7", no_record={3})
    dlg = BlockEditor(None, [blk], [(0, 0)], ["Diagramm 1 › Achse 1"], lambda i: plcs[i], set(), plc_names=["S7"])
    dlg.table.selectRow(0)
    top = dlg.tree.topLevelItem(0)
    top.setExpanded(True)
    assert top.childCount() == 4 and top.child(3).checkState(T_REC) == Qt.CheckState.Unchecked
    top.child(1).setCheckState(T_DISP, Qt.CheckState.Unchecked)           # nur aufzeichnen
    top.child(3).setCheckState(T_DISP, Qt.CheckState.Checked)             # anzeigen schaltet aufzeichnen ein
    assert top.child(3).checkState(T_REC) == Qt.CheckState.Checked
    top.child(0).setCheckState(T_REC, Qt.CheckState.Unchecked)            # nicht aufzeichnen: auch nicht anzeigen
    assert top.child(0).checkState(T_DISP) == Qt.CheckState.Unchecked
    b = dlg.block_of_row(0)
    assert b.no_record == {0} and b.no_display == {1}
    dlg.cb_flags.setCurrentIndex(1)                                       # alle: nur aufzeichnen
    dlg.set_all_flags()
    assert dlg.block_of_row(0).no_record == set() and dlg.block_of_row(0).no_display == {0, 1, 2, 3}
    dlg.cb_flags.setCurrentIndex(0)
    dlg.set_all_flags()
    dlg.close()

    # Konfiguration: Block mit Elementen ohne Aufzeichnung/Anzeige, eine Variable ohne Aufzeichnung.
    conn, charts, variables = load_config(demo_config)
    variables[4].record = False                                           # Zähler (in keiner Formel)
    variables[1].display = False                                          # Druck
    names = (variables[4].name, variables[1].name)
    save_config(conn, charts, variables, demo_config, plcs=[Plc(name="SPS 1")],
                blocks=[Block(name="Blk", address="DB2.DBD0", count=3, driver="s7", no_record={1}, no_display={2})])
    import plc_config
    w = plc_config.ConfigWindow(demo_config)
    w.show()
    wait(100)
    assert w.table.item(4, plc_config.C_REC).checkState() == Qt.CheckState.Unchecked
    texts = []
    stack = [w.tree.topLevelItem(i) for i in range(w.tree.topLevelItemCount())]
    while stack:
        it = stack.pop()
        texts.append(it.text(0))
        stack += [it.child(i) for i in range(it.childCount())]
    assert any("nicht aufgezeichnet" in x and x.startswith(names[0]) for x in texts), texts
    assert any("1 nicht aufgezeichnet, 1 nicht angezeigt" in x for x in texts), texts
    w.cb_filter_kind.setCurrentIndex(w.cb_filter_kind.findData("norec"))
    wait(50)
    assert [r for r in range(w.table.rowCount()) if not w.table.isRowHidden(r)] == [4]
    w.cb_filter_kind.setCurrentIndex(0)
    w.table.item(4, plc_config.C_REC).setCheckState(Qt.CheckState.Checked)
    assert w.collect()[4].record and not w.collect()[1].display
    w.table.item(4, plc_config.C_REC).setCheckState(Qt.CheckState.Unchecked)
    assert w._write(demo_config), qt_log.messages
    assert load_blocks(demo_config)[0].no_record == {1}
    assert not load_config(demo_config, alle=True)[2][4].record
    _close(w)

    # Logger: nicht aufgezeichnete Variable fehlt, „nur aufzeichnen“ ohne Kurve, CSV ohne Blk[1].
    import plc_gui
    m = plc_gui.MainWindow(demo_config, demo=True)
    m.show()
    assert names[0] not in [v.name for v in m.vars]
    curves = {m.vars[i].name for i, c in enumerate(m.curves) if c is not None}
    assert names[1] not in curves and "Blk[0]" in curves and not {"Blk[1]", "Blk[2]"} & curves
    m.act_run.setChecked(True)
    wait(800)
    m.act_run.setChecked(False)
    wait(300)
    with open(m.rec.csv_path, encoding="utf-8") as f:
        header = f.readline().strip().split(";")
    assert names[1] in header and "Blk[2]" in header and "Blk[1]" not in header and names[0] not in header
    _close(m)


def test_program_icons(qapp):
    """Jedes Programm bekommt sein eigenes Icon; ein konfiguriertes Icon geht vor."""
    from plc_branding import PROGRAM_ICONS, app_icon
    keys = set()
    for name in PROGRAM_ICONS:
        icon = app_icon(program=name)
        assert not icon.isNull() and {s.width() for s in icon.availableSizes()} >= {16, 32, 256}, name
        keys.add(bytes(icon.pixmap(32, 32).toImage().constBits()))
    assert len(keys) == len(PROGRAM_ICONS)                      # alle verschieden
    import os
    from conftest import ROOT
    custom = app_icon(os.path.join(ROOT, "logo.png"), program="ereignisse")
    assert custom.pixmap(64, 64).toImage() != app_icon(program="ereignisse").pixmap(64, 64).toImage()


def test_headless_dialog(qt_log, demo_config, tmp_path, monkeypatch):
    """Laufende Headless-Logger: anzeigen, beenden anfordern, Meldung nach dem Abmelden; Aufruf im Konfig-Programm."""
    import plc_config
    import plc_headless as hl
    from plc_headless_dialog import C_STATE, HeadlessDialog
    run_dir = str(tmp_path / "laufend")
    monkeypatch.setattr(hl, "RUN_DIR", run_dir)
    hl.write_status({"pid": 4711, "projekt": "Anlage", "config": "/x/anlage.json", "start": 1.0e9,
                     "rechner": "pi", "web": "http://pi:8080/"}, run_dir)
    d = HeadlessDialog(None, run_dir=run_dir)
    assert d.table.rowCount() == 1 and d.selected()["pid"] == 4711 and d.btn_stop.isEnabled()
    assert d.stop_selected(confirm=False)
    assert hl.stop_requested(4711, run_dir)
    assert d.table.item(0, C_STATE).text() == "wird beendet …" and not d.btn_stop.isEnabled()
    hl.remove_status(4711, run_dir)                              # der Logger hat sich abgemeldet
    d.refresh()
    assert d.table.rowCount() == 0 and "wurde beendet" in d.lbl_status.text()
    d.close()
    w = plc_config.ConfigWindow(demo_config)
    w.show_headless()
    assert w.lbl_headless.text() == "keiner läuft"
    hl.write_status({"pid": 4712, "projekt": "B", "start": 1.0e9}, run_dir)
    w.update_headless_label()
    assert w.lbl_headless.text() == "1 laufen"
    w.close()


def test_netscan_dialog_and_take(qt_log, demo_config, monkeypatch):
    """Netzwerksuche: Ergebnisse anzeigen (bekannte Adressen nicht vorgewählt), übernehmen als neue Steuerungen."""
    import plc_config
    import plc_netscan as ns
    from plc_netscan_dialog import NetScanDialog
    found = [ns.suggest(ns.Found(ip="10.1.1.5", ports=[102]), s7={"device": "CPU 315-2 PN/DP", "slot": 2}),
             ns.suggest(ns.Found(ip="10.1.1.6", ports=[502])),
             ns.Found(ip="10.1.1.7", ports=[])]
    d = NetScanDialog(None, known_ips={"10.1.1.6"})
    d.show_results(found)
    assert [f.ip for f in d.checked()] == ["10.1.1.5"]          # 10.1.1.6 schon konfiguriert, 10.1.1.7 ohne Treiber
    d.close()
    w = plc_config.ConfigWindow(demo_config)
    n = w.plc_table.rowCount()

    def fake_exec(self):
        self.result = [found[0], found[1]]
        return 1
    monkeypatch.setattr(NetScanDialog, "exec", fake_exec)
    w.scan_network()
    plcs = w.collect_plcs()
    assert len(plcs) == n + 2
    assert plcs[-2].driver == "s7" and plcs[-2].params["slot"] == 2 and plcs[-2].name == "CPU 315-2 PN/DP"
    assert plcs[-1].driver == "modbus" and plcs[-1].params["ip"] == "10.1.1.6"
    w.close()


def test_logger_client_mode(qt_log, demo_config, tmp_path):
    """Betriebsart Client: Verbindungsdialog, Hauptfenster mit Konfiguration und Werten vom Server (Demo-Aufzeichnung
    hinter dem Webserver), Zeitraum vom Server laden, Ereignisse, Export und zurück zur eigenen Konfiguration."""
    pytest.importorskip("flask")
    import socket

    import plc_gui
    import plc_web
    from plc_client_dialog import ClientDialog
    from plc_common import Plc, default_connection
    from plc_recorder import Recorder
    from plc_recorder import demo_config as demo
    from plc_webauth import hash_password
    conn = default_connection()
    conn.update(csv_ordner=str(tmp_path / "server"), csv_aktiv=0, projekt="Kessel", anordnung="tabs")
    charts, variables = demo()
    rec = Recorder(conn, [Plc(name="SPS Kessel")], charts, variables, demo=True)
    rec.start()
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = plc_web.WebServer(lambda: rec, "127.0.0.1", port, users={"chef": hash_password("pw", 1000)})
    srv.start()
    try:
        wait(1200)
        dlg = ClientDialog(None, f"127.0.0.1:{port}", "chef")
        dlg.ed_pw.setText("falsch")
        dlg.try_connect()
        assert dlg.connection is None and dlg.lbl_err.text()
        dlg.ed_pw.setText("pw")
        dlg.try_connect()
        assert dlg.connection is not None, dlg.lbl_err.text()
        w = plc_gui.MainWindow(demo_config, client=dlg.connection)
        w.show()
        wait(2500)
        assert w.rec is not None and w.rec.count() > 5 and w.act_run.isChecked()
        assert "Client" in w.windowTitle() and "Kessel" in w.windowTitle()
        assert not w.act_cfg.isEnabled() and not w.act_demo.isEnabled() and w.act_leave.isEnabled()
        assert w.leds and w.leds[0].lbl.text() == "SPS Kessel"
        assert len(w.panels) == len(charts) and w.web is None
        w.show_events()
        assert w.event_log() is w.rec.events
        qt_log.file = str(tmp_path / "export.csv")
        w.export_values()
        # Zeitraum vom Server laden (offline), dann wieder live
        t, _y = rec.snapshot()
        assert w._client_load_range(float(t[0]), float(t[-1]))
        assert w.source == "client" and not w.online and len(w.t) > 5
        w.goto_time(float(t[len(t) // 2]))
        w.act_online.setChecked(True)
        wait(1200)
        assert w.source == "rec" and w.rec.running
        assert not w.connect_client()                         # Dialog (exec ersetzt) abgebrochen
        w.leave_client()
        assert w.client is None and w.source == "none" and w.act_cfg.isEnabled()
        for kind, _title, text in qt_log.messages:
            assert kind != "critical", text
        _close(w)
    finally:
        srv.stop()
        rec.stop()


def test_opcua_browser_dialog_take(qt_log, tmp_path):
    """Auswahldialog OPC UA gegen den eigenen OPC-UA-Server: Ordner aufklappen, Variablen anhaken, übernehmen
    (früher brach „Auswahl übernehmen“ mit einem AttributeError ab)."""
    pytest.importorskip("asyncua")
    import socket

    from PySide6.QtCore import Qt

    from plc_common import Plc, default_connection
    from plc_recorder import Recorder, demo_config
    from plc_treiber.opcua_browser import OpcUaBrowserDialog
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    charts, variables = demo_config()
    conn = default_connection()
    conn.update(csv_ordner=str(tmp_path), csv_aktiv=0,
                opcua_server={"aktiv": True, "host": "127.0.0.1", "port": port, "anonym": True})
    rec = Recorder(conn, [Plc(name="Linie1")], charts, variables, demo=True)
    rec.start()
    try:
        wait(1200)
        plc = Plc(name="Pi", driver="opcua")
        plc.params.update(endpoint=f"opc.tcp://127.0.0.1:{port}/plc-datenlogger/")
        d = OpcUaBrowserDialog(None, plc, {"ns=2;s=Pumpe"}, ["Diagramm 1"])
        root = d.tree.invisibleRootItem()
        top = next(root.child(i) for i in range(root.childCount()) if root.child(i).text(0) == "PLC Datenlogger")
        d.on_expand(top)
        line = next(top.child(i) for i in range(top.childCount()) if top.child(i).text(0) == "Linie1")
        d.on_expand(line)
        items = {line.child(i).text(0): line.child(i) for i in range(line.childCount())}
        assert items["Pumpe"].isDisabled()                      # schon in der Liste
        items["Druck"].setCheckState(0, Qt.CheckState.Checked)
        items["Istwert"].setCheckState(0, Qt.CheckState.Checked)
        d.take()
        assert sorted(a for _n, a, _t in d.result_vars) == ["ns=2;s=Druck", "ns=2;s=Istwert"]
        assert d.result_vars[0][0].startswith("PLC Datenlogger.Linie1.") and d.result_vars[0][2] == "LREAL"
    finally:
        rec.stop()


def test_color_scheme_and_iocheck_selection(qt_log, demo_config, tmp_path):
    """Farbschema hell/dunkel umschalten (Menü, gespeichert); IO-Check: markierte Zeile auf farbigem Status-Hintergrund
    sichtbar (Markierungsfarbe darübergelegt), Status „offen“ im dunklen Schema hell."""
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication, QMenu

    import plc_i18n
    import plc_iocheck as io
    import plc_iocheck_dialog as d
    from plc_common import load_settings
    app = QApplication.instance()
    style, pal = app.style().name(), app.palette()
    try:
        menu = QMenu()
        sub = plc_i18n.fill_scheme_menu(menu)
        acts = {a.text(): a for a in sub.actions()}
        acts["Dunkel"].trigger()
        assert load_settings()["farbschema"] == "dunkel" and plc_i18n.is_dark()
        assert d.status_fg("offen") != d.STATUS_FG["offen"]
        w = d.IoCheckWindow(config_path=demo_config, demo=True)
        w.resize(900, 500)
        w.show()
        sigs = [io.IoSignal(f"E0.{k}", symbol=f"B{k}") for k in range(4)]
        io.set_status(sigs[1], "ok")
        w.all_signals = sigs
        w.model.set_signals(sigs)
        wait(100)
        row = w.proxy.mapFromSource(w.model.index(1, 0)).row()
        rect = w.view.visualRect(w.proxy.index(row, d.COL["symbol"]))
        before = w.view.viewport().grab().toImage().pixelColor(rect.center())
        w.view.selectRow(row)
        wait(100)
        after = w.view.viewport().grab().toImage().pixelColor(rect.center())
        assert before.name() != after.name(), (before.name(), after.name())     # Markierung erkennbar
        # offene Zeile (ohne Statusfarbe): voll in der Markierungsfarbe, auch wenn die Tabelle keinen Fokus hat
        row0 = w.proxy.mapFromSource(w.model.index(0, 0)).row()
        rect0 = w.view.visualRect(w.proxy.index(row0, d.COL["symbol"]))
        w.view.selectRow(row0)
        w.view.clearFocus()
        wait(100)
        got = w.view.viewport().grab().toImage().pixelColor(rect0.center())
        hl = w.view.palette().color(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight)
        assert abs(got.red() - hl.red()) + abs(got.green() - hl.green()) + abs(got.blue() - hl.blue()) < 40, \
            (got.name(), hl.name())
        w.close()
        acts["Hell"].trigger()
        assert load_settings()["farbschema"] == "hell" and not plc_i18n.is_dark()
        assert app.palette().color(QPalette.ColorRole.Window).lightness() > 128
    finally:
        from plc_common import save_settings
        save_settings(farbschema="system")
        plc_i18n.apply_color_scheme(scheme="system")
        app.setStyle(style)
        app.setPalette(pal)


def test_iocheck_checker_and_protocol_format(qt_log, demo_config, tmp_path, monkeypatch):
    """IO-Check: Prüfer (Name/Kürzel) über den Knopf der Werkzeugleiste ändern und wieder auf den Anmeldenamen
    zurücksetzen; Querformat des Protokolls im Menü des Protokoll-Knopfs, gespeichert."""
    import plc_common
    import plc_iocheck as io
    import plc_iocheck_dialog as d
    monkeypatch.setattr(plc_common, "SETTINGS_FILE", str(tmp_path / "einstellungen.json"))
    monkeypatch.setenv("USERNAME", "mtaxis")
    w = d.IoCheckWindow(config_path=demo_config, demo=True)
    assert w.act_checker.text().endswith("mtaxis") and not w.act_landscape.isChecked()
    monkeypatch.setattr(d.QInputDialog, "getText", staticmethod(lambda *a, **k: ("  Max Mustermann ", True)))
    w.act_checker.trigger()
    assert io.user_name() == "Max Mustermann" and w.act_checker.text().endswith("Max Mustermann")
    s = io.IoSignal("E0.0")
    io.set_status(s, "ok")
    assert s.checker == "Max Mustermann"
    monkeypatch.setattr(d.QInputDialog, "getText", staticmethod(lambda *a, **k: ("", True)))
    w.edit_checker()
    assert io.user_name() == "mtaxis"
    w.act_landscape.setChecked(True)
    assert plc_common.load_settings()["iocheck_querformat"] is True and io.protocol_landscape()
    assert w.act_protocol.menu() is not None
    w.close()


def test_file_dialogs_remember_folder(qt_log, tmp_path, monkeypatch):
    """Dateidialoge: Vorschlag ohne eigenen Ordner bzw. im Programm-/Datenordner -> zuletzt benutzter Ordner (je
    Dialogtitel, sonst allgemein); ein bewusst vorgegebener Ordner bleibt."""
    import plc_common
    import plc_filedlg as fd
    monkeypatch.setattr(plc_common, "SETTINGS_FILE", str(tmp_path / "einstellungen.json"))
    a, b, own = tmp_path / "a", tmp_path / "b", tmp_path / "eigen"
    for d in (a, b, own):
        d.mkdir()
    assert fd.start_path("Export", "x.csv") == "x.csv"                       # noch nichts gemerkt
    qt_log.file = str(a / "x.csv")
    assert fd.save_name(None, "Export", "x.csv", "CSV (*.csv)")[0] == qt_log.file
    assert fd.start_path("Export", "y.csv") == os.path.join(str(a), "y.csv")
    assert fd.start_path("Export", os.path.join(plc_common.BASE_DIR, "y.csv")) == os.path.join(str(a), "y.csv")
    assert fd.start_path("Export", str(own / "y.csv")) == str(own / "y.csv")
    assert fd.start_path("Export", os.path.join(plc_common.BASE_DIR, "csv", "y.csv")) == os.path.join(str(a), "y.csv")
    assert fd.start_path("Anderer Dialog", "") == str(a)                       # allgemein zuletzt benutzt
    qt_log.file = str(b / "p.pdf")
    fd.open_name(None, "Öffnen", "", "")
    assert fd.start_path("Export", "z.csv") == os.path.join(str(a), "z.csv")  # je Dialog gemerkt
    assert fd.start_path("Neu", "z.csv") == os.path.join(str(b), "z.csv")
    qt_log.file = ""                                                            # abgebrochen: nichts merken
    fd.save_name(None, "Export", "x.csv")
    assert fd.start_path("Export", "") == str(a)
    qt_log.file = str(own)
    assert fd.directory(None, "Ordner", plc_common.BASE_DIR) == str(own)
    assert fd.start_path("Ordner", "") == str(own)


def test_iocheck_edit_texts_and_update_list(qt_log, demo_config, tmp_path, monkeypatch):
    """IO-Check: BMK/Kommentar in der Tabelle ändern (gespeichert); geänderte IO-Liste „aktualisieren“ – Prüfeinträge
    gleicher Adressen bleiben, neue Texte werden übernommen."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    import plc_iocheck as io
    import plc_iocheck_dialog as d
    csv = tmp_path / "io.csv"
    csv.write_text("Adresse;Symbol;BMK\nE0.0;B1;-B1\nE0.1;B2;-B2\nE0.2;B3;-B3\n", encoding="utf-8")
    w = d.IoCheckWindow(config_path=demo_config, demo=True)
    qt_log.file = str(csv)
    w.import_list()
    assert [s.bmk for s in w.project.signals] == ["-B1", "-B2", "-B3"]
    qt_log.file = str(tmp_path / "pruef")
    assert w.save_project(as_new=True)
    w.set_status(w.project.signals[:2], "ok")
    sig = w.project.signals[1]
    idx = w.model.index(w.model.signals.index(sig), d.COL["bmk"])
    assert w.model.flags(idx) & Qt.ItemFlag.ItemIsEditable
    assert not w.model.flags(w.model.index(0, d.COL["kind"])) & Qt.ItemFlag.ItemIsEditable
    assert w.model.setData(idx, " -B2.1 ")
    assert io.IoProject.load(w.project.path).signals[1].bmk == "-B2.1"    # sofort gespeichert
    # geänderte Liste: E0.0 neues BMK, E0.2 entfällt, E0.3 neu
    csv.write_text("Adresse;Symbol;BMK\nE0.0;B1;-B10\nE0.1;B2;-B2\nE0.3;B4;-B4\n", encoding="utf-8")
    monkeypatch.setattr(QMessageBox, "clickedButton",
                        lambda self: next(b for b in self.buttons() if b.text() == d.tr("Liste aktualisieren")))
    qt_log.file = str(csv)
    w.import_list()
    by = {s.address: s for s in w.project.signals}
    assert sorted(by) == ["E0.0", "E0.1", "E0.3"]
    assert by["E0.0"].bmk == "-B10" and by["E0.0"].status == "ok" and by["E0.1"].status == "ok"
    assert by["E0.3"].status == "offen"
    assert any("E0.2" in m[2] for m in qt_log.messages if m[0] == "information")
    # Adresse ändern: offenes Signal E0.3 -> A4.0 (wird Digitalausgang); doppelte Adresse abgelehnt
    s3 = by["E0.3"]
    w.model.setData(w.model.index(w.model.signals.index(s3), d.COL["address"]), "A4.0")
    wait(50)
    assert s3.address == "A4.0" and s3.kind == "DO" and s3 in w.all_signals
    assert io.IoProject.load(w.project.path).signals[-1].address == "A4.0"
    w.model.setData(w.model.index(w.model.signals.index(s3), d.COL["address"]), "%I0.0")
    wait(50)
    assert s3.address == "A4.0" and any(m[0] == "warning" for m in qt_log.messages)
    w.dirty = False
    _close(w)


def test_iocheck_photos(qt_log, demo_config, tmp_path, monkeypatch):
    """IO-Check: Fotos am PC hinzufügen (großes Bild wird verkleinert), Spalte „Fotos“, Foto vom Smartphone über die
    Brücke, Entfernen; Protokoll-Menü „Fotos anhängen“."""
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QMessageBox

    import plc_common
    import plc_iocheck as io
    import plc_iocheck_dialog as d
    monkeypatch.setattr(plc_common, "SETTINGS_FILE", str(tmp_path / "einstellungen.json"))
    logo = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logo.png")
    big = QImage(3000, 2000, QImage.Format.Format_RGB32)
    big.fill(QColor("#336699"))
    assert big.save(str(tmp_path / "gross.bmp"))
    w = d.IoCheckWindow(config_path=demo_config, demo=True)
    w.project.signals = [io.IoSignal("E0.0", symbol="B1"), io.IoSignal("E0.1")]
    w._rebuild()
    qt_log.file = str(tmp_path / "anlage")
    assert w.save_project(as_new=True)
    folder = io.photo_dir(w.project.path)
    assert w.bridge.photo_dir == folder
    sig = w.project.signals[0]
    dlg = d.PhotoDialog(w, sig, folder)
    qt_log.files = [str(tmp_path / "gross.bmp"), logo]
    dlg.add()
    assert len(sig.photos) == 2 and dlg.changed and dlg.list.count() == 2
    jpg = QImage(os.path.join(folder, sig.photos[0]))
    assert sig.photos[0].endswith(".jpg") and max(jpg.width(), jpg.height()) == d.PhotoDialog.MAX_SIDE
    assert sig.photos[1].endswith(".png")
    row = w.model.signals.index(sig)
    assert w.model.data(w.model.index(row, d.COL["photos"])) == "2"
    # vom Smartphone: Foto über die Brücke, das Fenster speichert es
    assert w.bridge.add_photo(w.bridge.version, row, open(logo, "rb").read(), "tablet1") == ""
    w._web_commands()
    assert len(sig.photos) == 3
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    dlg.fill()
    dlg.list.item(0).setSelected(True)
    first = sig.photos[0]
    dlg.remove_selected()
    assert first not in sig.photos and not os.path.exists(os.path.join(folder, first))
    w.act_photos_pdf.setChecked(False)
    assert plc_common.load_settings()["iocheck_protokoll_fotos"] is False and not io.protocol_photos()
    w.dirty = False
    _close(w)


def test_mqtt_browser_dialog(qt_log):
    """Treiber mqtt: Topics vom Broker mithören, JSON-Zahlen einzeln, abhaken und übernehmen."""
    pytest.importorskip("paho.mqtt.client")
    from PySide6.QtCore import Qt

    from mqtt_broker import Broker
    from plc_common import Plc
    from plc_treiber import get_driver
    from plc_treiber.mqtt_browser import MqttBrowserDialog
    b = Broker()
    try:
        b.publish("halle/temp", "21.5", retain=True)
        b.publish("tele/s1/SENSOR", json.dumps({"AM2301": {"Temperature": 19.5}}), retain=True)
        params = get_driver("mqtt").default_params()
        params.update(host="127.0.0.1", port=b.port)
        dlg = MqttBrowserDialog(None, Plc(name="B", driver="mqtt", params=params), {"halle/temp"}, ["Diagramm 1"])
        dlg.sp_secs.setValue(1)
        dlg.listen()
        for _i in range(60):
            wait(50)
            if len(dlg.items) == 2 and dlg.btn_listen.isEnabled():
                break
        assert set(dlg.items) == {"halle/temp", "tele/s1/SENSOR|AM2301.Temperature"}
        assert dlg.items["halle/temp"].isDisabled()                  # schon vorhanden
        dlg.items["tele/s1/SENSOR|AM2301.Temperature"].setCheckState(0, Qt.CheckState.Checked)
        dlg.take()
        assert dlg.result_vars == [("SENSOR_AM2301_Temperature", "tele/s1/SENSOR|AM2301.Temperature", "REAL")]
    finally:
        b.close()
