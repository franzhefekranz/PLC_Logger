# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Bilder für die Bedienungsanleitung automatisch erzeugen (Fenster im Demo-Modus öffnen und abfotografieren).

Aufruf:  python tools/make_screenshots.py [--lang de|en] [--out ORDNER]

Erzeugt die Bilder der neueren Funktionen, deren Fenster sich ohne Steuerung zeigen lassen:

* ``benachrichtigungen.png``   Dialog Benachrichtigungen (Reiter E-Mail)
* ``opcua_server.png``         Dialog OPC-UA-Server
* ``webserver_qr.png``         Webserver-Adresse mit QR-Code
* ``ereignis_diagramm.png``    Logger nach „Im Diagramm zeigen“ (offline, Lineale auf Beginn und Ende)
* ``config_web_headless.png``  Konfigurationsprogramm, Reiter Webserver & Headless (mit OPC-UA-Server)
* ``config_trigger_ereignis.png`` Konfigurationsprogramm, Reiter Trigger & Ereignisse (mit Benachrichtigungen)

Deutsch landet in ``doc/images``, Englisch in ``doc/images/en``. Läuft auch ohne Bildschirm
(``QT_QPA_PLATFORM=offscreen``); der Workflow *Screenshots* führt das Skript unter Windows aus, damit die Bilder wie
im echten Programm aussehen.
"""
import argparse
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))


def demo_config(folder):
    """Demo-Konfiguration mit gültigen Adressen, Webserver, OPC-UA-Server, Benachrichtigungen und Triggern -> Pfad."""
    from plc_common import Plc, default_connection, save_config
    from plc_recorder import demo_config as demo
    charts, variables = demo()
    for k, v in enumerate(variables):
        if not v.formula:
            v.address = f"DB1.DBX100.{k % 8}" if v.dtype == "BOOL" else f"DB1.DBD{4 * k}"
    conn = default_connection()
    from plc_webauth import hash_password
    import json
    conn.update(csv_ordner=folder, projekt="Kesselhaus Linie 1", web_port=8080, web_host="0.0.0.0", web_aktiv=1,
                web_https=1, web_benutzer=json.dumps({"franz": hash_password("geheim123", 1000)}),
                benachrichtigung=json.dumps({"aktiv": True, "prio_min": "Warnung",
                                  "email": {"aktiv": True, "server": "smtp.firma.de", "an": "schicht@firma.de"},
                                  "ntfy": {"aktiv": True, "url": "https://ntfy.sh/kesselhaus-4711"}}),
                opcua_server=json.dumps({"aktiv": True, "port": 4840,
                                         "sicherheit": ["none", "Basic256Sha256,SignAndEncrypt"],
                                         "anonym": False, "benutzer": "web"}))
    path = os.path.join(folder, "anlage.json")
    save_config(conn, charts, variables, path, plcs=[Plc(name="SPS 1")])
    from plc_events import save_triggers
    from plc_recorder import demo_triggers
    save_triggers(path, demo_triggers())                 # Beispiel-Trigger (Übertemperatur, Druck niedrig)
    return path


def wait(ms):
    """Qt-Ereignisse verarbeiten (Zeichnen, Timer) für ms Millisekunden."""
    from PySide6.QtTest import QTest
    QTest.qWait(ms)


def shot(widget, path, size=None):
    """Fenster anzeigen, zeichnen lassen und als PNG speichern."""
    if size:
        widget.resize(*size)
    widget.show()
    widget.raise_()
    wait(400)
    widget.grab().save(path)
    print("Bild:", path)


def main():
    """Sprache laden, modale Meldungen abschalten, Demo-Konfiguration anlegen und die Fenster nacheinander öffnen und
    abfotografieren.

    Der Rechnername wird durch „ipc-kesselhaus“ ersetzt, damit in den Bildern nicht der Name des Build-Rechners steht.
    Für das Bild „Ereignis im Diagramm“ läuft zuerst 75 s eine Demo-Aufzeichnung, damit links und rechts der Lineale
    Daten zu sehen sind.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="de")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    out = args.out or os.path.join(ROOT, "doc", "images", *([] if args.lang == "de" else ["en"]))
    os.makedirs(out, exist_ok=True)
    import plc_i18n
    plc_i18n.load(args.lang)
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
    app = QApplication.instance() or QApplication(["PLC Datenlogger"])
    plc_i18n.install_qt(app)
    QDialog.exec = lambda self: 0                      # modale Dialoge (Meldungen) nicht abwarten
    for kind in ("information", "warning", "critical", "question"):
        setattr(QMessageBox, kind, staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    import socket
    socket.gethostname = lambda: "ipc-kesselhaus"     # neutraler Rechnername in Endpunkt-Adressen
    folder = tempfile.mkdtemp(prefix="plc_bilder_")
    cfg = demo_config(folder)

    # Dialog Benachrichtigungen: Beispiel mit E-Mail und ntfy
    from plc_notify_dialog import NotifyDialog
    dlg = NotifyDialog(None, {"aktiv": True, "prio_min": "Warnung", "trigger": "", "gehen": True, "sperre_s": 300,
                              "email": {"aktiv": True, "server": "smtp.firma.de", "port": 587, "modus": "starttls",
                                        "benutzer": "datenlogger@firma.de", "passwort": "geheim",
                                        "von": "datenlogger@firma.de", "an": "schichtleiter@firma.de, instandhaltung@firma.de"},
                              "ntfy": {"aktiv": True, "url": "https://ntfy.sh/kesselhaus-4711-xyz"}},
                       "Kesselhaus Linie 1")
    shot(dlg, os.path.join(out, "benachrichtigungen.png"), (560, 600))
    dlg.close()

    # Dialog OPC-UA-Server
    from plc_opcua_dialog import OpcUaServerDialog
    dlg = OpcUaServerDialog(None, {"aktiv": True, "host": "0.0.0.0", "port": 4840, "intervall_ms": 500,
                                   "sicherheit": ["none", "Basic256Sha256,SignAndEncrypt"], "anonym": False,
                                   "benutzer": "web"}, 2)
    dlg.lbl_url.setText("opc.tcp://ipc-kesselhaus:4840/plc-datenlogger/")
    shot(dlg, os.path.join(out, "opcua_server.png"), (520, 560))
    dlg.close()

    # Webserver-Adresse mit QR-Code (gleicher Aufbau wie Logger › Datei › Webserver-Adresse …)
    from html import escape
    from plc_i18n import tr
    from plc_iocheck_dialog import qr_dialog
    url = "https://192.168.0.20:8080/"
    text = tr("Adresse für Tablet/Smartphone im selben Netz:\n\n{0}").format(url)
    text += "\n\n" + tr("Anmeldung erforderlich ({0} Benutzer).").format(2)
    text += "\n\n" + tr("Prozessbild: {0}").format(url + "prozess")
    text += "\n\n" + tr("(Adresse in die Zwischenablage kopiert)")
    dlg = qr_dialog(None, tr("Webserver"), url, escape(text).replace("\n", "<br>"))
    shot(dlg, os.path.join(out, "webserver_qr.png"))
    dlg.close()

    # Konfigurationsprogramm: Reiter Webserver & Headless (nur die Seite) und Trigger & Ereignisse (mit Reiterleiste)
    import plc_config
    cw = plc_config.ConfigWindow(cfg)
    cw.resize(1600, 900)
    cw.show()
    wait(500)
    cw.tabs.setCurrentIndex(3)
    wait(300)
    cw.tabs.currentWidget().grab().save(os.path.join(out, "config_web_headless.png"))
    cw.tabs.setCurrentIndex(5)
    wait(300)
    cw.tabs.grab().save(os.path.join(out, "config_trigger_ereignis.png"))
    print("Bilder: Konfigurationsprogramm")
    cw.close()

    # Logger: Ereignis im Diagramm zeigen (Demo-Aufzeichnung, dann offline mit Linealen)
    import plc_gui
    w = plc_gui.MainWindow(cfg, demo=True)
    w.resize(1280, 760)
    w.show()
    w.act_run.setChecked(True)
    t_end = time.time() + 75
    while time.time() < t_end:
        wait(200)
    w.act_run.setChecked(False)
    wait(500)
    t = w.rec.snapshot()[0] if w.rec is not None else w.t
    t_mid = float(t[len(t) // 2])                     # Mitte der Aufzeichnung: links und rechts liegen Daten
    w.goto_time(t_mid, t_mid + 6.0, "Übertemperatur")
    wait(600)
    shot(w, os.path.join(out, "ereignis_diagramm.png"))
    w.close()
    wait(200)
    return 0


if __name__ == "__main__":
    sys.exit(main())
