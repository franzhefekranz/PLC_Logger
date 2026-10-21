# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""PLC Datenlogger – Startprogramm.

Dieses kleine Programm entscheidet, WIE der Logger läuft, bevor schwere Bibliotheken geladen werden:

* mit Oberfläche (Diagramme, Online/Offline, Lineale ...)  -> plc_gui.py (PySide6 + pyqtgraph)
* ohne Oberfläche (Headless, nur Aufzeichnung)             -> plc_headless.py (kein Qt nötig)

Der Headless-Modus wird in der Konfiguration eingestellt (Option „Headless“) oder per Parameter erzwungen.

Aufruf
------
    plc_logger.py [Konfigurationsdatei] [--config DATEI] [--headless | --gui] [--demo]
    plc_logger.py --ereignisse [Konfigurationsdatei | Ereignisdatei.csv]
    plc_logger.py --iocheck [Konfigurationsdatei | Prüfstand.iocheck.json] [--demo]
    plc_logger.py --konfig [Konfigurationsdatei]     (Konfigurationsprogramm, z. B. im Linux-AppImage)

Ohne Dateiangabe wird die zuletzt benutzte Konfiguration geöffnet (Standard: plc_config.json). ``--gui`` öffnet die
Oberfläche auch dann, wenn die Konfiguration den Headless-Modus verlangt; ``--headless`` erzwingt ihn.
``--ereignisse`` öffnet nur den Ereignis-Viewer (Ereignisse der Trigger anzeigen und quittieren), z. B. neben einem
Headless-Logger. ``--iocheck`` öffnet nur den IO-Check (Inbetriebnahme: Signalliste prüfen).
"""
import argparse
import os
import sys

from plc_common import last_config_path, load_config, remember_config_path


def parse_args(argv):
    ap = argparse.ArgumentParser(description="PLC Datenlogger")
    ap.add_argument("config", nargs="?", help="Konfigurationsdatei (JSON)")
    ap.add_argument("--config", dest="config_opt", help="Konfigurationsdatei (wie das Positionsargument)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--headless", action="store_true", help="ohne Oberfläche, nur Aufzeichnung")
    mode.add_argument("--gui", action="store_true", help="Oberfläche auch bei eingestelltem Headless-Modus")
    mode.add_argument("--konfig", action="store_true",
                      help="Konfigurationsprogramm öffnen (eine Programmdatei für alles, z. B. AppImage)")
    mode.add_argument("--ereignisse", action="store_true",
                      help="nur den Ereignis-Viewer öffnen (Ereignisse anzeigen und quittieren)")
    mode.add_argument("--iocheck", action="store_true",
                      help="nur den IO-Check öffnen (Inbetriebnahme: Signalliste prüfen)")
    ap.add_argument("--demo", action="store_true", help="simulierte Werte statt SPS-Verbindung")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    explicit = args.config_opt or args.config
    if args.konfig:
        from plc_config import main as config_main
        return config_main([explicit] if explicit else [])
    if args.ereignisse:
        from plc_event_viewer import run_viewer
        return run_viewer(explicit)
    if args.iocheck:
        from plc_iocheck_dialog import run_iocheck
        return run_iocheck(explicit, demo=args.demo)
    path = os.path.abspath(explicit) if explicit else last_config_path()
    if explicit and os.path.exists(path):
        remember_config_path(path)                    # die nächste Sitzung öffnet dieselbe Datei
    # Nur die Verbindungs-/Optionswerte lesen, um den Headless-Schalter zu kennen. Eine fehlerhafte Datei
    # meldet später die jeweilige Betriebsart selbst.
    try:
        headless = bool(load_config(path)[0].get("headless", 0))
    except Exception:
        headless = False
    if args.headless:
        headless = True
    if args.gui:
        headless = False
    if headless:
        from plc_headless import run
        return run(path, demo=args.demo)
    return run_with_start_window(path, bool(explicit), args.demo)


def run_with_start_window(path, explicit, demo):
    """Oberfläche starten: zuerst das Startbild (Auswahl der Konfiguration, danach Lade-Anzeige), dann das
    Hauptfenster. Das Startbild erscheint, bevor die großen Bibliotheken (pyqtgraph) geladen werden."""
    from PySide6.QtWidgets import QApplication, QMessageBox
    from plc_branding import set_windows_app_id
    from plc_i18n import install_qt, tr
    set_windows_app_id()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    install_qt(app)
    from plc_splash import choose
    win, res = choose("logger", path, explicit=explicit)
    if res is None:
        return 0
    path = res["path"] or path
    demo = demo or res["demo"]
    if res["new"]:                                    # neue Konfiguration: Datei anlegen, Konfigurationsprogramm öffnen
        import subprocess
        from plc_common import Chart, default_connection, program_command, save_config
        try:
            save_config(default_connection(), [Chart()], [], path)
            subprocess.Popen(program_command("config", path))
        except OSError as e:
            QMessageBox.warning(win, tr("Neue Konfiguration"), str(e))
    if os.path.exists(path):
        remember_config_path(path)
    win.set_loading(tr("Lade Oberfläche (Diagramme) …"))
    from plc_gui import run_gui
    return run_gui(path, demo=demo, splash=win)


if __name__ == "__main__":
    sys.exit(main())
