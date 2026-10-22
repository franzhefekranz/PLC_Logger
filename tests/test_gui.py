# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Tests mit echter Qt-Oberfläche (PySide6, ohne Bildschirm: QT_QPA_PLATFORM=offscreen).

Die Fenster werden geöffnet, im Demo-Modus betrieben und ihre Dialoge aufgerufen; modale Dialoge kehren sofort zurück
(siehe conftest.qt_log). Ziel: Abstürze, fehlende Methoden und falsche Qt-Aufrufe finden, bevor ein Release entsteht."""
import json
import os

import pytest

from conftest import wait

pytestmark = pytest.mark.gui


def _close(win):
    win.close()
    wait(50)


def test_logger_demo_recording(qt_log, demo_config, tmp_path):
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
    for kind, _title, text in qt_log.messages:
        assert kind != "critical", text
    _close(w)


def test_config_window(qt_log, demo_config):
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
    from plc_notify_dialog import NotifyDialog
    nd = NotifyDialog(w, {"aktiv": True, "email": {"aktiv": True}}, "Testanlage")
    assert nd.collect()["email"]["aktiv"] and nd.collect()["aktiv"]
    nd.send_test()                                           # Fehlermeldung (kein Server) statt Absturz
    assert w._write(demo_config), qt_log.messages
    doc = json.load(open(demo_config, encoding="utf-8"))
    assert doc["einstellungen"]["projekt"] == "Testanlage"
    _close(w)


def test_iocheck_window(qt_log, demo_config, tmp_path):
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


def test_about_help_and_dialogs(qt_log, demo_config):
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
