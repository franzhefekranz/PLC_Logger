# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Headless-Modus des PLC-Datenloggers: nur Aufzeichnung, ohne Oberfläche und ohne Diagramme.

Der Modus ist für Rechner ohne Bildschirm gedacht (Schaltschrank-PC, Server, Dienst/Aufgabenplanung). Er
benötigt weder PySide6 noch pyqtgraph. Es laufen

* der Recorder (plc_recorder.py) mit einem Lese-Thread je Steuerung, CSV-Datei, Rotation und Archivierung,
* optional der Webserver (plc_web.py), damit die Diagramme trotzdem im Browser ansehbar sind.

Alle Meldungen gehen in die Logdatei ``plc_logger.log`` im Datenordner (rotierend, 3 x 1 MB) und – wenn eine
Konsole vorhanden ist – auch dorthin. Beendet wird mit Strg+C, SIGTERM (Dienst beenden) oder Schließen der
Konsole; dabei wird die aktuelle CSV-Datei wie im normalen Betrieb archiviert (Einstellung ``archiv_beenden``).
"""
import logging
import logging.handlers
import os
import signal
import sys
import threading
import time

from plc_common import BASE_DIR, load_config, load_plcs
from plc_recorder import Recorder, demo_config

LOG_FILE = os.path.join(BASE_DIR, "plc_logger.log")


def setup_logging():
    """Logger mit rotierender Datei (und Konsole, falls vorhanden) einrichten."""
    log = logging.getLogger("s7logger")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%d %H:%M:%S")
    try:
        fh = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except OSError:
        pass                                          # Datenordner nicht beschreibbar: nur Konsole
    if sys.stderr is not None:                        # bei windowed-.exe gibt es keine Konsole
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        log.addHandler(sh)
    return log


def run(config_path, demo=False):
    """Aufzeichnung ohne Oberfläche starten und bis zum Beenden-Signal laufen lassen. Rückgabe: Exit-Code."""
    log = setup_logging()
    try:
        conn, charts, variables = load_config(config_path)
        plcs = load_plcs(config_path)
    except Exception as e:                            # fehlerhafte oder fehlende Konfiguration
        log.error("Konfiguration %s nicht lesbar: %s", config_path, e)
        return 2
    if demo and not variables:
        charts, variables = demo_config()
    if not variables:
        log.error("Keine Variablen in %s – es gibt nichts aufzuzeichnen.", config_path)
        return 2
    projekt = conn.get("projekt") or os.path.basename(config_path)
    log.info("Headless-Modus gestartet – Projekt „%s“, %d Steuerung(en), %d Variablen%s",
             projekt, len(plcs), len(variables), " (Demo)" if demo else "")

    # Der Recorder startet beim Start auch Trigger, Benachrichtigungen, Datenbank und OPC-UA-Server; seine Meldungen
    # gehen über log.info in die Logdatei.
    rec = Recorder(conn, plcs, charts, variables, demo=demo, log=log.info, config_path=config_path)
    for err in rec.formula_errors:
        log.warning("Formelfehler: %s", err)

    # Beenden-Signale: setzen nur ein Ereignis; das Aufräumen passiert im Hauptthread.
    stop = threading.Event()

    def on_signal(signum, _frame):
        """Signal-Handler: nur das Ende anfordern; aufgeräumt wird im Hauptthread (Signal-Handler dürfen nicht
        blockieren).
        """
        log.info("Signal %s empfangen – beende.", signum)
        stop.set()

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):    # SIGBREAK: Windows (Strg+Pause, Konsole schließen)
        if hasattr(signal, name):
            try:
                signal.signal(getattr(signal, name), on_signal)
            except (ValueError, OSError):
                pass

    web = None
    try:
        rec.start()
        if conn.get("web_aktiv"):
            try:
                from plc_web import WebServer
                web = WebServer.from_conn(lambda: rec, conn)
                web.start()
                log.info("Webserver läuft: %s%s", web.url(),
                         f" (Anmeldung: {len(web.users)} Benutzer)" if web.users else "")
                if web.fingerprint():
                    log.info("HTTPS-Zertifikat SHA-256: %s", web.fingerprint())
            except Exception as e:                    # Port belegt, Flask fehlt ...
                log.error("Webserver konnte nicht gestartet werden: %s", e)
                web = None
        last_report = time.monotonic()
        # Hauptthread: nur warten. Gelesen und geschrieben wird in den Threads des Recorders bzw. des Webservers.
        while not stop.wait(0.5):
            # Alle 10 Minuten eine Lebenszeichen-Zeile mit Zeilenzahl und Verbindungszustand.
            if time.monotonic() - last_report >= 600:
                last_report = time.monotonic()
                states = ", ".join(f"{n}: {s}" for n, s, _t, _ms in rec.status_list())
                log.info("läuft – %d Zeilen im Speicher; %s; verworfen: %d; offene Ereignisse: %d", rec.count(),
                         states, rec.dropped, rec.events.open_count())
    finally:
        if web:
            web.stop()
        rec.shutdown()                                # stoppt und archiviert die aktuelle CSV-Datei
        log.info("Headless-Modus beendet.")
    return 0
