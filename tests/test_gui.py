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
    assert fake.calls[-1][:6] == ["nmcli", "device", "wifi", "connect", "Gast", "password"]
    assert w.stack.currentWidget() is w.page_home
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
    assert w._write(demo_config), qt_log.messages
    doc = json.load(open(demo_config, encoding="utf-8"))
    assert doc["einstellungen"]["projekt"] == "Testanlage"
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
