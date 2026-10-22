# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Aufzeichnungskern des PLC-Datenloggers – ohne Oberfläche (kein Qt), daher auch für den Headless-Betrieb.

Der Recorder liest aus einer oder mehreren Steuerungen, wertet berechnete Variablen aus, hält die Messwerte
im Speicher (für Diagramme und Webserver) und schreibt sie in die CSV-Datei (mit Rotation und Archivierung).

Threads (alle Arbeit außerhalb des Oberflächen-Threads, damit die GUI flüssig bleibt)
-----------------------------------------------------------------------------------
* ``PlcSampler``  – ein Thread je Steuerung: verbindet, liest den Leseplan im eingestellten Takt und stellt
  jeden Messzyklus in die Warteschlange. Netzwerk-Wartezeiten einer Steuerung bremsen die anderen nicht.
* Sammler (``Recorder._collector``) – ein Thread: nimmt die Messzyklen aus der Warteschlange, führt die
  Werte aller Steuerungen zu einer Zeile zusammen, rechnet die Formeln, hängt die Zeile an die Puffer an und
  schreibt die CSV-Datei. Plattenzugriffe und Rechnerei blockieren dadurch weder SPS-Lesen noch Oberfläche.
* Archivierung   – packt eine volle CSV-Datei in einem eigenen Thread (ZIP, prüfen, Original löschen).

Zusammenführen mehrerer Steuerungen
-----------------------------------
Jede Steuerung liefert zu eigenen Zeitpunkten. Der Sammler hält für jede Variable den zuletzt gelesenen Wert und
erzeugt bei JEDEM eintreffenden Messzyklus eine Zeile mit allen Variablen (Werte der anderen Steuerungen
bleiben auf dem letzten bekannten Wert). Die Zeitstempel sind die der jeweiligen Messung.

Zugriff von außen (thread-sicher)
---------------------------------
``window``/``slice_time``/``snapshot`` liefern Kopien der Puffer; ``status_list`` die Verbindungszustände
(für die Status-LEDs); ``drain_messages`` die aufgelaufenen Meldungen.
"""
import collections
import csv
import math
import os
import queue
import random
import re
import threading
import time
import zipfile
from datetime import datetime

import numpy as np

from plc_common import BASE_DIR, PALETTE, Axis, Chart, Variable, get_driver
from plc_events import EventLog, Trigger, TriggerEngine, event_log_path, load_triggers
from plc_formula import Formula, FormulaError
from plc_util import fmt_csv
from plc_db import DbWriter, describe as db_describe, db_settings
from plc_i18n import N_, tr

# Verbindungszustände einer Steuerung (für Status-LED und Meldungen).
ST_OFF, ST_CONNECTING, ST_OK, ST_ERROR = "off", "connecting", "ok", "error"


# ---------------------------------------------------------------------------------------
# Archivierung
# ---------------------------------------------------------------------------------------
def zip_and_remove(path, target_dir, notify):
    """CSV-Datei packen (ZIP), prüfen, in target_dir ablegen und das Original löschen.

    Läuft in einem eigenen Thread, damit die Aufzeichnung nicht stockt. Bei jedem Fehler bleibt die CSV-Datei
    erhalten; Meldungen gehen über ``notify(text)`` zurück. Rückgabe: True bei Erfolg."""
    try:
        # Zielordner (Archiv/Name/Jahr/Monat/Tag) anlegen, falls er noch nicht existiert.
        os.makedirs(target_dir, exist_ok=True)
        base = os.path.splitext(os.path.basename(path))[0]
        # Gleicher Name schon vorhanden? Dann _1, _2, ... anhängen, statt zu überschreiben.
        zpath, n = os.path.join(target_dir, base + ".zip"), 1
        while os.path.exists(zpath):
            zpath = os.path.join(target_dir, f"{base}_{n}.zip")
            n += 1
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(path, arcname=os.path.basename(path))
        # Erst wenn sich das Archiv fehlerfrei wieder öffnen lässt, wird das Original gelöscht (kein Datenverlust).
        with zipfile.ZipFile(zpath) as z:
            if z.testzip() is not None:
                raise OSError(tr("Archiv ist fehlerhaft"))
        os.remove(path)
        notify(f"Archiviert: {zpath}")
        return True
    except Exception as e:
        notify(tr("⚠ Archivierung von {0} fehlgeschlagen: {1} (CSV-Datei bleibt erhalten)").format(os.path.basename(path), e))
        return False


# ---------------------------------------------------------------------------------------
# Demo-Werte
# ---------------------------------------------------------------------------------------
def demo_value(k, v, el):
    """Testwert für Variable Nr. k zum Zeitpunkt el (Sekunden seit Start): Sinus + Rauschen, Rechteck, Sägezahn."""
    ph = k * 0.9
    if v.dtype == "BOOL":                      # Rechtecksignal (Vorzeichen eines Sinus)
        return float(math.sin(2 * math.pi * el / (6 + 2 * k) + ph) > 0)
    if v.dtype in ("REAL", "LREAL"):           # Sinus 50 ± 30 plus schneller kleiner Sinus plus Rauschen
        base = (50 + 30 * math.sin(2 * math.pi * el / (20 + 7 * k) + ph)
                + 5 * math.sin(2 * math.pi * el / (3 + k)))
        return base + random.gauss(0, 0.5)
    period = 30 + 10 * k                       # Ganzzahlen: Sägezahn 0..199 mit variabler Periode
    return float(int((el % period) / period * 200))


def demo_config():
    """Beispiel-Diagramme/-Variablen, falls im Demo-Modus noch nichts konfiguriert ist: zwei Diagramme mit je zwei
    Y-Achsen, ein BOOL-Signal (feste Y-Skalierung) und eine berechnete Variable (Mittelwert)."""
    charts = [
        Chart(name="Prozess", axes=[Axis(name="Sinus"), Axis(name="Druck bar")]),
        Chart(name="Regelkreis", axes=[Axis(name="Temperatur °C"), Axis(name="Stellwert %")], pid=True,
              pid_sw="Sollwert", pid_iw="Istwert", pid_stw="Stellwert", pid_typ="PI"),
        Chart(name="Zustände", axes=[Axis(name="Analog"),
                                     Axis(name="Digital", auto=False, y_min=-0.1, y_max=1.5)]),
    ]
    variables = [
        Variable("Sinus", dtype="REAL", color=PALETTE[0], chart=0, axis=0),
        Variable("Druck", dtype="REAL", color=PALETTE[1], chart=0, axis=1),
        Variable("Temperatur", dtype="REAL", color=PALETTE[2], chart=2, axis=0),
        Variable("Pumpe", dtype="BOOL", color=PALETTE[3], chart=2, axis=1),
        Variable("Zähler", dtype="INT", color=PALETTE[4], chart=2, axis=0),
        Variable("Sollwert", dtype="REAL", color=PALETTE[7], chart=1, axis=0),
        Variable("Istwert", dtype="REAL", color=PALETTE[3], chart=1, axis=0),
        Variable("Stellwert", dtype="REAL", color=PALETTE[2], chart=1, axis=1),
        Variable("Mittel", dtype="REAL", color=PALETTE[5], chart=0, axis=0,
                 formula="({Sinus} + {Temperatur}) / 2"),
    ]
    return charts, variables


def demo_triggers():
    """Beispiel-Trigger zur Demo-Konfiguration (nur wenn keine eigenen Trigger angelegt sind)."""
    return [Trigger(name="Übertemperatur", bedingung="{Temperatur} > 75", prio="Alarm", verzoegerung_s=1.0,
                    text="Temperatur zu hoch: {Temperatur} °C"),
            Trigger(name="Druck niedrig", bedingung="{Pumpe} == 1 and {Druck} < 25", prio="Warnung",
                    text="Pumpe läuft, Druck nur {Druck} bar", quittieren=False)]


class DemoLoop:
    """Simulierter Regelkreis für den Demo-Modus: Strecke PT1 mit Totzeit (K = 1.5, T = 12 s, θ = 2 s), träge
    eingestellter PI-Regler, Sollwert wechselt jede Minute (Beispiel für die PID-Optimierung)."""
    K, T, THETA, KP, TI = 1.5, 12.0, 2.0, 0.6, 30.0
    SETPOINTS = (40.0, 60.0, 50.0, 70.0)

    def __init__(self):
        self.y, self.integ, self.u, self.last = 20.0, 0.0, 0.0, None
        self.hist = collections.deque()               # (Zeit, Stellwert) für die Totzeit

    def step(self, el):
        """Zustand bis zur Zeit el (s seit Start) weiterrechnen -> (Sollwert, Istwert, Stellwert)."""
        sp = self.SETPOINTS[int(el // 60) % len(self.SETPOINTS)]
        if self.last is not None:
            dt = min(max(el - self.last, 0.0), 1.0)
            while len(self.hist) > 1 and self.hist[1][0] <= el - self.THETA:
                self.hist.popleft()
            ud = self.hist[0][1] if self.hist and self.hist[0][0] <= el - self.THETA else 0.0
            self.y += dt / self.T * (20.0 + self.K * ud - self.y)
            e = sp - self.y
            self.integ += e * dt / self.TI
            self.u = min(100.0, max(0.0, self.KP * (e + self.integ)))
            if self.u in (0.0, 100.0):                # einfacher Anti-Windup
                self.integ -= e * dt / self.TI
        self.last = el
        self.hist.append((el, self.u))
        return sp, self.y + random.gauss(0, 0.15), self.u


# ---------------------------------------------------------------------------------------
# Triggergesteuerte Aufzeichnung (Vor- und Nachlauf)
# ---------------------------------------------------------------------------------------
class CaptureGate:
    """Entscheidet je Messzeile, ob sie in CSV-Datei/Datenbank geschrieben wird (Einstellung „Per Trigger“).

    Ein Ringspeicher hält die Zeilen der letzten ``pre_s`` Sekunden. Wird die Startbedingung wahr, beginnt eine
    Aufnahme: zuerst der Inhalt des Ringspeichers (Vorlauf), dann jede neue Zeile. Ist die Bedingung wieder falsch,
    läuft die Aufnahme noch ``post_s`` Sekunden weiter (Nachlauf); wird sie in dieser Zeit erneut wahr, verlängert
    sich die Aufnahme. ``max_s`` (> 0) begrenzt die Dauer einer Aufnahme; danach muss die Bedingung erst wieder
    falsch werden, bevor die nächste Aufnahme beginnen kann.

    ``feed`` liefert (zu schreibende Zeilen [(Zeit, Zeile)], Ereignis) mit Ereignis None, "start" oder "stop"."""

    def __init__(self, condition, pre_s=10.0, post_s=10.0, max_s=0.0):
        self.formula = Formula(condition)             # FormulaError bei ungültiger Bedingung
        self.condition = condition
        self.pre, self.post, self.max = max(0.0, float(pre_s)), max(0.0, float(post_s)), max(0.0, float(max_s))
        self.ring = collections.deque()
        self.active = False
        self.armed = True
        self.t_trigger = self.last_true = None
        self.rows = 0                                 # Zeilen der laufenden Aufnahme
        self.captures = 0                             # Anzahl der Aufnahmen seit dem Start

    def check(self, ts, values):
        """Startbedingung für eine Messzeile auswerten -> True, wenn erfüllt.

        ``values`` ist {Variablenname: Wert}. Rechenfehler (z. B. Division durch null) und NaN gelten als „nicht
        erfüllt“, damit eine fehlerhafte Bedingung keine Daueraufnahme auslöst.
        """
        try:
            r = self.formula.evaluate(ts, values)
        except Exception:
            r = float("nan")
        return r == r and r != 0                      # NaN (kein Wert) gilt als „nicht erfüllt“

    def feed(self, ts, row, values):
        """Eine Messzeile verarbeiten -> (zu speichernde Zeilen, Ereignis).

        Ohne laufende Aufnahme wandert die Zeile nur in den Ringspeicher (älter als der Vorlauf wird verworfen). Wird
        die Bedingung wahr und ist das Gate „scharf“ (``armed``), beginnt die Aufnahme mit dem Ringspeicher als Vorlauf
        (Ereignis "start"). Während der Aufnahme wird jede Zeile weitergegeben; sie endet, wenn die Bedingung länger als
        der Nachlauf falsch ist oder die Höchstdauer erreicht ist (Ereignis "stop"). Nach einem Abbruch wegen
        Höchstdauer bleibt das Gate unscharf, bis die Bedingung einmal falsch war – sonst begänne sofort die nächste
        Aufnahme.
        """
        cond = self.check(ts, values)
        if not self.active:
            self.ring.append((ts, row))
            while self.ring and self.ring[0][0] < ts - self.pre:
                self.ring.popleft()
            if not cond:
                self.armed = True
                return [], None
            if not self.armed:
                return [], None
            rows = list(self.ring)
            self.ring.clear()
            self.active, self.t_trigger, self.last_true = True, ts, ts
            self.rows = len(rows)
            self.captures += 1
            return rows, "start"
        self.rows += 1
        if cond:
            self.last_true = ts
        too_long = self.max > 0 and ts - self.t_trigger >= self.max
        if too_long or (not cond and ts - self.last_true >= self.post):
            self.active = False
            self.armed = not cond
            return [(ts, row)], "stop"
        return [(ts, row)], None


# ---------------------------------------------------------------------------------------
# Lese-Thread einer Steuerung
# ---------------------------------------------------------------------------------------
class PlcSampler(threading.Thread):
    """Liest zyklisch alle Variablen EINER Steuerung und stellt die Messzyklen in die Warteschlange des Recorders."""

    def __init__(self, rec, idx, plc, var_idx):
        super().__init__(name=f"plc-{idx}", daemon=True)
        self.rec, self.idx, self.plc = rec, idx, plc
        self.var_idx = var_idx                                   # globale Indizes der Variablen dieser Steuerung
        self.vars = [rec.vars[i] for i in var_idx]

    def _sleep(self, seconds):
        """Wartet, bricht aber in 50-ms-Schritten ab, sobald der Recorder beendet wird."""
        end = time.perf_counter() + seconds
        while not self.rec.stop_evt.is_set() and time.perf_counter() < end:
            time.sleep(min(0.05, max(0.0, end - time.perf_counter())))

    def run(self):
        """Thread-Hauptfunktion: simulierte Werte (Demo) oder echte Steuerung lesen, bis der Recorder stoppt."""
        if self.rec.demo:
            self._run_demo()
        else:
            self._run_plc()

    def _put(self, ts, values):
        """Einen Messzyklus (Zeitstempel, Werte in der Reihenfolge von ``var_idx``) an den Sammler übergeben."""
        self.rec.put_sample(self.idx, ts, values)

    # Simulation: Werte werden berechnet statt gelesen.
    def _run_demo(self):
        """Demo-Betrieb: statt zu lesen werden Testwerte berechnet (siehe ``demo_value`` und ``DemoLoop``).

        Der Takt wird wie beim echten Lesen mit einem fortlaufenden Sollzeitpunkt ``nxt`` gehalten.
        """
        r, interval = self.rec, self.plc.intervall_ms / 1000.0
        r.set_status(self.idx, ST_OK, tr("Demo-Modus (simulierte Werte)"))
        t0, nxt = time.time(), time.perf_counter()
        roles = {"Sollwert": 0, "Istwert": 1, "Stellwert": 2}
        loop = DemoLoop() if any(v.name in roles and not v.block for v in self.vars) else None
        while not r.stop_evt.is_set():
            ts = time.time()
            vals = [demo_value(gi, v, ts - t0) for gi, v in zip(self.var_idx, self.vars)]
            if loop is not None:                      # Regelkreis-Beispiel (siehe DemoLoop)
                lv = loop.step(ts - t0)
                vals = [lv[roles[v.name]] if v.name in roles else x for v, x in zip(self.vars, vals)]
            self._put(ts, vals)
            nxt += interval
            delay = nxt - time.perf_counter()
            if delay > 0:
                self._sleep(delay)
            else:
                nxt = time.perf_counter()

    # Echte Steuerung: Tags anlegen -> lesen -> melden -> warten; bei Verbindungsfehlern neu verbinden.
    def _run_plc(self):
        """Lese-Schleife einer echten Steuerung: verbinden, zyklisch lesen, Werte melden.

        Ablauf je Durchlauf:

        1. Nicht verbunden: ``reader.connect()``; bei Fehler Status „Fehler“ und nach 2 s neuer Versuch.
        2. Zeitstempel nehmen und ``reader.read()`` aufrufen (eine Liste mit einem Wert je Variable, NaN = kein Wert).
        3. Fehler einzelner Variablen (``reader.errors``) je Variable nur einmal melden.
        4. Werte an den Sammler übergeben und bis zum nächsten Takt warten.

        Ein Lesefehler (Verbindung weg) schließt den Leser und führt zurück zu Schritt 1.
        """
        r, plc = self.rec, self.plc
        interval = plc.intervall_ms / 1000.0
        # Leser des Treibers dieser Steuerung (siehe plc_treiber); Tests können eine Ersatzfabrik setzen.
        try:
            if r.reader_factory is not None:
                reader = r.reader_factory(plc, self.vars)
            else:
                reader = get_driver(plc.driver).create_reader(plc, self.vars)
        except Exception as e:
            r.set_status(self.idx, ST_ERROR, tr("Treiber {0}: {1}").format(plc.driver, e))
            return
        connected = False
        where = plc.summary()
        reported = {}                                 # bereits gemeldete Fehler einzelner Tags
        nxt = time.perf_counter()
        while not r.stop_evt.is_set():
            if not connected:
                r.set_status(self.idx, ST_CONNECTING, tr("Verbinde mit {0} …").format(where))
                try:
                    n_ok = reader.connect()
                    connected = True
                    r.set_status(self.idx, ST_OK, tr("Verbunden mit {0} ({1} Variablen)").format(where, n_ok))
                    nxt = time.perf_counter()
                except Exception as e:
                    r.set_status(self.idx, ST_ERROR, tr("Verbindung zu {0} fehlgeschlagen: {1}").format(where, e))
                    self._sleep(2.0)
                    continue
            # Zeitstempel unmittelbar vor dem Lesen: so gehört der Wert möglichst genau zu diesem Zeitpunkt.
            ts, t_start = time.time(), time.perf_counter()
            try:
                values = reader.read()
            except Exception as e:
                connected = False
                reader.close()
                r.set_status(self.idx, ST_ERROR, tr("Lesefehler: {0} – neuer Verbindungsversuch").format(e))
                self._sleep(1.0)
                continue
            # Fehler einzelner Tags (z. B. falscher Name) einmal melden; die übrigen Tags laufen weiter.
            for name, err in reader.errors.items():
                if reported.get(name) != err:
                    reported[name] = err
                    r.emit(tr("[{0}] Variable {1}: {2}").format(plc.name, name, err))
            r.note_read_time(self.idx, (time.perf_counter() - t_start) * 1000.0)
            self._put(ts, values)
            # Takt: das nächste Ziel wird um das Intervall weitergeschoben (konstante Abtastrate trotz schwankender
            # Lesezeit). Ist das Lesen langsamer als das Intervall, wird der Takt neu gestartet.
            nxt += interval
            delay = nxt - time.perf_counter()
            if delay > 0:
                self._sleep(delay)
            else:
                nxt = time.perf_counter()
        reader.close()
        r.set_status(self.idx, ST_OFF, tr("Getrennt"))


# ---------------------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------------------
class Recorder:
    """Aufzeichnung für eine Konfiguration: Lesen, Rechnen, Puffern, CSV, Archiv.

    conn/plcs/charts/variables stammen aus plc_common.load_config/load_plcs. ``demo=True`` simuliert die Werte.
    ``log`` (optional) erhält jede Meldung als Text (Headless: Logdatei)."""

    MAX_POINTS = 300_000          # Obergrenze der im Speicher gehaltenen Zeilen (die CSV-Datei enthält alles)
    FLUSH_S = 0.5                 # CSV spätestens alle 0,5 s auf den Datenträger schreiben (flush)

    def __init__(self, conn, plcs, charts, variables, demo=False, log=None, config_path=""):
        """Recorder für eine Konfiguration anlegen (noch ohne zu lesen; das beginnt mit ``start``).

        Hier werden die Variablen den Steuerungen zugeordnet, die Formeln übersetzt, die Messwertpuffer angelegt und die
        Einstellungen für CSV, Datenbank, Trigger, Aufzeichnung per Trigger und Berichte gelesen.
        """
        self.conn, self.plcs, self.charts, self.vars = conn, plcs, charts, variables
        self.demo, self.log, self.config_path = demo, log, config_path
        n = len(variables)
        self.names = [v.name for v in variables]
        # Variablen je Steuerung (nur gelesene, keine berechneten) und berechnete Variablen.
        # Indizes in self.vars: computed_idx = berechnete Variablen, plc_vars[k] = die von Steuerung k gelesenen.
        # Die Werte einer Zeile stehen immer in der Reihenfolge von self.vars (CSV-Spalten, Puffer, Diagramme).
        self.computed_idx = [i for i, v in enumerate(variables) if v.formula]
        self.plc_vars = [[i for i, v in enumerate(variables) if not v.formula and v.plc == k]
                         for k in range(len(plcs))]
        self.formulas = {}
        self.formula_errors = []
        for i in self.computed_idx:
            try:
                self.formulas[i] = Formula(variables[i].formula)
            except FormulaError as e:
                self.formula_errors.append(f"{variables[i].name}: {e}")
        # Zusammenarbeit der Threads.
        self.stop_evt = threading.Event()
        self.q = queue.Queue(maxsize=20000)
        self.lock = threading.Lock()             # schützt Puffer, Status und Zähler
        self.samplers, self.collector = [], None
        self.running = False
        self.dropped = 0                         # verworfene Messzyklen (Warteschlange voll)
        # Messwertpuffer: Zeit und Werte in vorab angelegten numpy-Feldern (schnelle Ausschnitte ohne Umrechnung).
        self._cap = 4096
        # tbuf[i] = Zeit der Zeile i, ybuf[v, i] = Wert der Variable v in Zeile i; gültig sind die ersten self.n Zeilen.
        # Der Puffer wächst durch Verdoppeln bis MAX_POINTS (siehe _append).
        self.tbuf = np.empty(self._cap)
        self.ybuf = np.full((n, self._cap), np.nan)
        self.n = 0
        self.dirty = False                       # neue Daten seit dem letzten Abholen (für die Anzeige)
        # Verbindungszustände: [(Zustand, Text)] je Steuerung und geglättete Lesezeit in ms.
        self.status = [(ST_OFF, "gestoppt")] * len(plcs)
        self.read_ms = [0.0] * len(plcs)
        self.messages = collections.deque(maxlen=1000)
        # Ersatz für den Leser (Tests): Funktion (plc, variables) -> Reader; None = Treiber der Steuerung.
        self.reader_factory = None
        # CSV-Datei und Archivierung.
        self.csv_base = "demo" if demo else (re.sub(r'[\\/:*?"<>|]+', "_", conn.get("csv_name") or "log"))
        self.csv_fh = self.csv_w = None
        self.csv_path, self.csv_rows, self.csv_first = "", 0, None
        self._csv_pending = False                # aktuelle CSV-Datei ist noch nicht archiviert/entfernt
        self._last_flush = 0.0
        self._archive_threads = []
        # Ziele der Aufzeichnung: CSV-Datei (abschaltbar) und/oder Datenbank (SQLite, MariaDB, TimescaleDB).
        self.csv_on = bool(int(conn.get("csv_aktiv", 1)))
        self.db_conf = db_settings(conn)
        self.db = None                           # DbWriter, solange die Aufzeichnung läuft
        # Trigger (Ereignisbedingungen) aus der Konfigurationsdatei und das Ereignisprotokoll (siehe *_events.py).
        self.triggers = load_triggers(config_path) if config_path else []
        if demo and not self.triggers and {"Temperatur", "Pumpe", "Druck"} <= set(self.names):
            self.triggers = demo_triggers()
        self.events = EventLog(event_log_path(conn))
        self.trigger_engine = None               # TriggerEngine, solange die Aufzeichnung läuft
        self.notifier = None                     # Benachrichtigungen (plc_notify), solange die Aufzeichnung läuft
        self.opcua = None                        # OPC-UA-Server (plc_opcua_server), solange die Aufzeichnung läuft
        # Aufzeichnung per Trigger (Vor-/Nachlauf): CaptureGate, solange die Aufzeichnung läuft (sonst dauernd).
        self.capture_mode = (conn.get("aufz_modus") == "trigger")
        self.gate = None
        self._capture_eid = None
        # PDF-Berichte je Zeitraum (Schicht/Tag/Woche/Monat): Kennwerte und Verlauf des laufenden Zeitraums.
        self.report_on = bool(int(conn.get("bericht_aktiv", 0) or 0))
        self.report_acc = None
        self._report_threads = []

    # ------------------------------------------------------------------ Ordner
    def csv_dir(self):
        """Ordner der CSV-Dateien (relativer Pfad bezogen auf den Datenordner BASE_DIR)."""
        d = self.conn["csv_ordner"]
        return d if os.path.isabs(d) else os.path.join(BASE_DIR, d)

    def archive_dir(self, when):
        """Archiv-Ordner: <archiv>/<Name>/<Jahr>/<Monat>/<Tag>"""
        base = self.conn.get("archiv_ordner") or "archiv"
        if not os.path.isabs(base):
            base = os.path.join(BASE_DIR, base)
        return os.path.join(base, self.csv_base, f"{when:%Y}", f"{when:%m}", f"{when:%d}")

    # ------------------------------------------------------------------ Meldungen und Status
    def emit(self, text):
        """Meldung für die Oberfläche (Statuszeile) und die Logdatei."""
        self.messages.append(text)
        if self.log:
            try:
                self.log(text)
            except Exception:
                pass

    def drain_messages(self):
        """Alle aufgelaufenen Meldungen abholen (und aus der Warteschlange entfernen)."""
        out = []
        while True:
            try:
                out.append(self.messages.popleft())
            except IndexError:
                return out

    def set_status(self, idx, state, text):
        """Zustand einer Steuerung setzen; bei einer Änderung kommt eine Meldung."""
        with self.lock:
            changed = self.status[idx] != (state, text)
            self.status[idx] = (state, text)
        if changed:
            self.emit(f"[{self.plcs[idx].name}] {text}")

    def note_read_time(self, idx, ms):
        """Lesezeit eines Zyklus in ms (exponentiell geglättet) für die Anzeige im Tooltip der LED."""
        self.read_ms[idx] = ms if self.read_ms[idx] == 0 else 0.9 * self.read_ms[idx] + 0.1 * ms

    def status_list(self):
        """[(Name, Zustand, Text, Lesezeit ms)] je Steuerung; bei aktiver Datenbank zusätzlich ein Eintrag für sie."""
        with self.lock:
            out = [(p.name, s, t, self.read_ms[i]) for i, (p, (s, t)) in enumerate(zip(self.plcs, self.status))]
        if self.db_conf["typ"]:
            st, text = self.db.status() if self.db else ("off", "gestoppt")
            out.append(("Datenbank", st, text, 0.0))
        return out

    # ------------------------------------------------------------------ Start / Stop
    def open_csv(self):
        """Neue CSV-Datei im CSV-Ordner anlegen (Name: <Name>_JJJJMMTT_HHMMSS.csv)."""
        os.makedirs(self.csv_dir(), exist_ok=True)
        stem = os.path.join(self.csv_dir(), f"{self.csv_base}_{datetime.now():%Y%m%d_%H%M%S}")
        path, n = stem + ".csv", 1
        while os.path.exists(path):              # gleiche Sekunde: _1, _2 ... anhängen
            path = f"{stem}_{n}.csv"
            n += 1
        self.csv_path = path
        # Semikolon als Trennzeichen (deutsches Excel); Kopfzeile: Zeit, Epoch und die Variablennamen.
        self.csv_fh = open(path, "w", newline="", encoding="utf-8")
        self.csv_w = csv.writer(self.csv_fh, delimiter=";")
        self.csv_w.writerow(["Zeit", "Epoch"] + self.names)
        self.csv_rows, self.csv_first, self._last_flush = 0, None, time.monotonic()
        self._csv_pending = True

    def start(self):
        """CSV-Datei öffnen, Sammler und je Steuerung einen Lese-Thread starten.

        Außerdem werden gestartet bzw. angelegt: der Datenbank-Schreiber, die Benachrichtigungen, der OPC-UA-Server und
        die Trigger-Auswertung (``TriggerEngine``). Deren Ereignisse gehen über ``notify`` sowohl an die
        Benachrichtigungen als auch an den OPC-UA-Server. Bei „Aufzeichnung per Trigger“ wird die CSV-Datei erst mit der
        ersten Aufnahme geöffnet.
        """
        if self.running:
            return
        self.stop_evt.clear()
        self.gate = self._make_gate() if self.capture_mode else None
        if self.csv_on and self.gate is None:
            self.open_csv()
        if self.db_conf["typ"]:
            self.db = DbWriter(self.conn, self.names, self.emit)
            self.db.start()
        from plc_notify import Notifier
        self.notifier = Notifier(self.conn, self.conn.get("projekt", ""), self.emit)
        self.opcua = None
        if self.conn.get("opcua_server"):
            from plc_opcua_server import OpcUaServer
            srv = OpcUaServer(self.conn, self.vars, self.plcs, self.triggers, self.emit,
                              lambda: list(self.status))
            if srv and srv.start():
                self.opcua = srv
        hooks = [h.event for h in (self.notifier, self.opcua) if h]

        def notify(*a):
            for h in hooks:
                h(*a)
        self.trigger_engine = TriggerEngine(self.triggers, self.events, self.emit, self.names,
                                            notify=notify if hooks else None) if self.triggers else None
        if self.trigger_engine is not None:
            for err in self.trigger_engine.errors:
                self.emit("⚠ " + err)
            if not self.trigger_engine:
                self.trigger_engine = None
        if self.report_on:
            self.report_acc = self._new_report(time.time())
        self.running = True
        self.collector = threading.Thread(target=self._collector, name="collector", daemon=True)
        self.collector.start()
        self.samplers = []
        for k, plc in enumerate(self.plcs):
            if not plc.enabled:
                self.set_status(k, ST_OFF, tr("deaktiviert"))
            elif not self.plc_vars[k]:
                self.set_status(k, ST_OFF, tr("keine Variablen zugeordnet"))
            else:
                self.set_status(k, ST_CONNECTING, tr("Starte …"))
                s = PlcSampler(self, k, plc, self.plc_vars[k])
                self.samplers.append(s)
                s.start()
        if self.gate is not None:
            targets = ([tr("CSV-Ordner {0}").format(self.csv_dir())] if self.csv_on else []) + \
                      ([db_describe(self.db_conf)] if self.db else [])
            self.emit(tr("Aufzeichnung per Trigger: warte auf „{0}“ (Vorlauf {1:g} s, Nachlauf {2:g} s) → {3}").format(
                self.gate.condition, self.gate.pre, self.gate.post,
                " und ".join(targets) or tr("nur Anzeige (weder CSV noch Datenbank)")))
        else:
            targets = ([self.csv_path] if self.csv_on else []) + ([db_describe(self.db_conf)] if self.db else [])
            self.emit(tr("Aufzeichnung gestartet → ") + (" und ".join(targets) or tr("nur Anzeige (weder CSV noch Datenbank)")))
        if self.trigger_engine:
            self.emit(tr("{0} Trigger aktiv → Ereignisprotokoll {1}").format(len(self.trigger_engine.states), self.events.path))

    def stop(self):
        """Lese-Threads und Sammler beenden, CSV-Datei schließen (bleibt ungepackt im CSV-Ordner).

        Reihenfolge: zuerst die Lese-Threads (keine neuen Werte mehr), dann die Ende-Marke für den Sammler, der vorher
        noch alle wartenden Messzyklen verarbeitet. Danach Teilbericht, offene Trigger-Aufnahme, Datenbank,
        Benachrichtigungen und OPC-UA-Server abschließen.
        """
        if not self.running:
            return
        self.stop_evt.set()
        for s in self.samplers:
            s.join(5.0)
        self.q.put(None)                         # Ende-Marke: der Sammler verarbeitet vorher noch alles Übrige
        if self.collector:
            self.collector.join(10.0)
        if self.report_acc is not None and self.report_acc.rows:   # Teilbericht des angefangenen Zeitraums
            self._write_report(self.report_acc, partial=True)
        self.report_acc = None
        if self.gate is not None and self.gate.active:   # laufende Trigger-Aufnahme abschließen
            self._capture_event("stop", time.time())
            self.gate.active = False
        if self.db:                              # Datenbank: restliche Werte schreiben, Thread beenden
            self.db.stop()
            if self.db.buf:
                self.emit(tr("⚠ Datenbank: {0} Werte konnten nicht mehr geschrieben werden").format(len(self.db.buf)))
        if self.notifier is not None:            # ausstehende Benachrichtigungen noch senden
            self.notifier.stop()
            self.notifier = None
        if self.opcua is not None:
            self.opcua.stop()
            self.opcua = None
        self.running = False
        if self.csv_fh:
            try:
                self.csv_fh.close()
            finally:
                self.csv_fh = self.csv_w = None
        for k in range(len(self.plcs)):
            self.set_status(k, ST_OFF, tr("gestoppt"))
        if self.gate is not None:
            self.emit(tr("Gestoppt – {0} Trigger-Aufnahmen").format(self.gate.captures))
        else:
            self.emit(tr("Gestoppt") + (tr(" – gespeichert in {0}").format(self.csv_path) if self.csv_on else ""))

    def shutdown(self, archive=None):
        """Aufzeichnung beenden. Mit ``archive`` (Standard: Einstellung ``archiv_beenden``) wird die aktuelle
        CSV-Datei zum Schluss noch gepackt und im Archiv abgelegt – das Programm wartet darauf."""
        self.stop()
        if archive is None:
            archive = bool(self.conn.get("archiv_beenden", 1))
        if archive and self._csv_pending and self.csv_path and os.path.exists(self.csv_path):
            self._csv_pending = False
            if self.csv_rows > 0:
                when = datetime.fromtimestamp(self.csv_first) if self.csv_first else datetime.now()
                zip_and_remove(self.csv_path, self.archive_dir(when), self.emit)
            else:                                # nur eine Kopfzeile: nichts zu archivieren, Datei entfernen
                try:
                    os.remove(self.csv_path)
                except OSError:
                    pass
        for t in self._archive_threads + self._report_threads:   # laufende Archivierungen/Berichte abwarten
            t.join(60.0)

    # ------------------------------------------------------------------ Datenfluss
    def put_sample(self, idx, ts, values):
        """Von den Lese-Threads: einen Messzyklus an den Sammler übergeben (bei voller Warteschlange verwerfen)."""
        try:
            self.q.put_nowait((idx, ts, values))
        except queue.Full:
            self.dropped += 1

    def _collector(self):
        """Sammler-Thread: Messzyklen zu Zeilen zusammenführen, Formeln rechnen, puffern, CSV schreiben."""
        n = len(self.vars)
        cur = np.full(n, np.nan)                 # zuletzt bekannter Wert jeder Variable
        while True:
            try:
                item = self.q.get(timeout=0.25)
            except queue.Empty:
                self._flush_if_due()
                continue
            if item is None:
                break
            idx, ts, values = item
            # Werte dieser Steuerung in die Gesamtzeile eintragen; die anderen Steuerungen behalten ihren letzten Wert.
            for gi, val in zip(self.plc_vars[idx], values):
                cur[gi] = val
            row = cur.copy()
            engine = self.trigger_engine
            gate = self.gate
            byname = None
            if self.computed_idx or engine or gate:
                # Formeln in Tabellenreihenfolge: spätere dürfen frühere verwenden.
                byname = {self.names[i]: row[i] for i in range(n) if i not in self.formulas}
                for i in self.computed_idx:
                    f = self.formulas.get(i)
                    r = f.evaluate(ts, byname) if f else float("nan")
                    row[i] = r
                    byname[self.names[i]] = r
                if engine:                       # Trigger prüfen (Ereignisse ins Protokoll schreiben)
                    try:
                        engine.evaluate(ts, {k: float(v) for k, v in byname.items()})
                    except OSError as e:
                        self.emit(tr("⚠ Ereignisprotokoll nicht beschreibbar: {0}").format(e))
            self._append(ts, row)
            if self.opcua is not None:
                self.opcua.update(ts, row)
            acc = self.report_acc
            if acc is not None:
                if ts >= acc.t1:                 # Zeitraum vorbei: Bericht schreiben, nächsten beginnen
                    if acc.rows:
                        self._write_report(acc, partial=False)
                    acc = self.report_acc = self._new_report(ts)
                acc.add(ts, row)
            if gate is None:
                self._store(ts, row)
            else:                                # per Trigger: nur Vorlauf, Aufnahme und Nachlauf speichern
                rows, event = gate.feed(ts, row, {k: float(v) for k, v in byname.items()})
                if event == "start":
                    self._capture_event("start", gate.t_trigger)
                for t_, r_ in rows:
                    self._store(t_, r_)
                if event == "stop":
                    self._capture_event("stop", ts)
        self._flush_if_due(force=True)

    def _store(self, ts, row):
        """Zeile in die CSV-Datei und die Datenbank schreiben."""
        self._write_csv(ts, row)
        if self.db:
            self.db.put(ts, row)

    # ------------------------------------------------------------------ PDF-Berichte
    def _new_report(self, ts):
        from plc_report import ReportAccumulator, period_bounds, period_label
        c = self.conn
        kind = c.get("bericht_zeitraum") or "tag"
        t0, t1 = period_bounds(ts, kind, c.get("bericht_schichten", ""), c.get("bericht_beginn", "00:00"))
        return ReportAccumulator(self.names, [v.dtype for v in self.vars], t0, t1, kind=kind,
                                 label=period_label(kind, t0, t1, c.get("bericht_schichten", "")))

    def _write_report(self, acc, partial):
        """Bericht eines Zeitraums im Hintergrund schreiben (Ereignisse aus dem Ereignisprotokoll)."""
        from plc_common import logo_paths
        from plc_report import events_in, report_path, write_in_background
        try:
            path = report_path(self.conn, acc, self.csv_base, partial)
            th = write_in_background(path, acc, self.charts, self.vars, self.conn.get("projekt", ""),
                                     events_in(self.events, acc.t0, acc.t1), partial, self.emit,
                                     logos=logo_paths(self.conn))
            self._report_threads = [t for t in self._report_threads if t.is_alive()] + [th]
        except Exception as e:
            self.emit(tr("⚠ Bericht konnte nicht erstellt werden: {0}").format(e))

    # ------------------------------------------------------------------ Aufzeichnung per Trigger
    def _make_gate(self):
        """CaptureGate aus den Einstellungen; bei Fehlern Meldung und dauernde Aufzeichnung (es geht nichts verloren)."""
        cond = (self.conn.get("aufz_bedingung") or "").strip()
        try:
            if not cond:
                raise FormulaError(tr("keine Startbedingung angegeben"))
            gate = CaptureGate(cond, self.conn.get("aufz_vorlauf_s", 10.0), self.conn.get("aufz_nachlauf_s", 10.0),
                               self.conn.get("aufz_max_s", 0.0))
            missing = [n for n in gate.formula.refs if n not in self.names]
            if missing:
                raise FormulaError(tr("unbekannte Variablen: ") + ", ".join(missing))
            return gate
        except FormulaError as e:
            self.emit(tr("⚠ Aufzeichnung per Trigger: {0} – es wird dauernd aufgezeichnet").format(e))
            return None

    CAPTURE_TRIGGER = Trigger(name=N_("Aufnahme"), prio="Info", quittieren=False, gehen=True)

    def _capture_event(self, kind, ts):
        """Beginn/Ende einer Trigger-Aufnahme: CSV-Datei öffnen bzw. schließen, Ereignisprotokoll und Meldung."""
        g = self.gate
        if kind == "start":
            if self.csv_on:
                try:
                    self.open_csv()
                except OSError as e:
                    self.emit(tr("⚠ CSV-Fehler: {0}").format(e))
            text = tr("Aufnahme {0} gestartet: {1}").format(g.captures, g.condition)
            try:
                self._capture_eid = self.events.come(self.CAPTURE_TRIGGER, text, ts)
            except OSError as e:
                self.emit(tr("⚠ Ereignisprotokoll nicht beschreibbar: {0}").format(e))
            self.emit("● " + text + (f" → {self.csv_path}" if self.csv_on else ""))
            return
        path = self.csv_path if self.csv_fh else ""
        if self.csv_fh:
            try:
                self.csv_fh.close()
            except OSError as e:
                self.emit(tr("⚠ CSV-Fehler: {0}").format(e))
            self.csv_fh = self.csv_w = None
            self._csv_pending = False            # fertige Aufnahme bleibt im CSV-Ordner
        if self._capture_eid is not None:
            try:
                self.events.go(self._capture_eid, self.CAPTURE_TRIGGER, ts)
            except OSError:
                pass
            self._capture_eid = None
        self.emit(tr("○ Aufnahme {0} beendet ({1} Zeilen){2}").format(
            g.captures, g.rows, f" → {path}" if path else ""))

    def capture_state(self):
        """Zustand der Aufzeichnung per Trigger: None (dauernd), "wait" oder "rec"."""
        g = self.gate
        if g is None:
            return None
        return "rec" if g.active else "wait"

    def _append(self, ts, row):
        """Zeile an die Puffer anhängen; bei Überlauf das älteste Zehntel verwerfen."""
        with self.lock:
            if self.n >= self._cap:
                if self._cap < self.MAX_POINTS:                  # Puffer vergrößern (verdoppeln)
                    cap = min(self._cap * 2, self.MAX_POINTS)
                    t2 = np.empty(cap)
                    y2 = np.full((len(self.vars), cap), np.nan)
                    t2[:self.n] = self.tbuf[:self.n]
                    y2[:, :self.n] = self.ybuf[:, :self.n]
                    self.tbuf, self.ybuf, self._cap = t2, y2, cap
                else:                                            # voll: ältestes Zehntel verwerfen
                    d = self.MAX_POINTS // 10
                    self.tbuf[:self.n - d] = self.tbuf[d:self.n].copy()
                    self.ybuf[:, :self.n - d] = self.ybuf[:, d:self.n].copy()
                    self.n -= d
            self.tbuf[self.n] = ts
            self.ybuf[:, self.n] = row
            self.n += 1
            self.dirty = True

    def _write_csv(self, ts, row):
        """Eine Zeile in die CSV-Datei schreiben (Zeit lesbar und als Unix-Zeit, Werte je Datentyp formatiert).

        Ist die maximale Zeilenzahl je Datei erreicht (``max_records``), wird die Datei gewechselt und die alte
        archiviert.
        """
        if not self.csv_w:
            return
        # 'Zeit' (lesbar) und 'Epoch' (Unix-Zeit) werden aus derselben ganzzahligen Millisekunde gebildet.
        ms = int(round(ts * 1000))
        stamp = datetime.fromtimestamp(ms // 1000).strftime("%Y-%m-%d %H:%M:%S") + f".{ms % 1000:03d}"
        self.csv_w.writerow([stamp, f"{ms / 1000:.3f}"] +
                            [fmt_csv(float(val), self.vars[i].dtype) for i, val in enumerate(row)])
        if self.csv_first is None:
            self.csv_first = ts
        self.csv_rows += 1
        self._flush_if_due()
        limit = self.conn.get("max_records", 0)
        if limit > 0 and self.csv_rows >= limit:
            self._rotate_csv()

    def _flush_if_due(self, force=False):
        """CSV auf den Datenträger schreiben: höchstens alle FLUSH_S Sekunden (schont die Platte)."""
        if self.csv_fh and (force or time.monotonic() - self._last_flush >= self.FLUSH_S):
            try:
                self.csv_fh.flush()
            except OSError as e:
                self.emit(tr("⚠ CSV-Fehler: {0}").format(e))
            self._last_flush = time.monotonic()

    def _rotate_csv(self):
        """Maximale Datensatzzahl erreicht: Datei schließen, im Hintergrund archivieren, neue Datei beginnen."""
        path, first = self.csv_path, self.csv_first
        self.csv_fh.close()
        self.csv_fh = self.csv_w = None
        when = datetime.fromtimestamp(first) if first else datetime.now()
        self._csv_pending = False
        t = threading.Thread(target=zip_and_remove, args=(path, self.archive_dir(when), self.emit))
        t.start()
        self._archive_threads = [x for x in self._archive_threads if x.is_alive()] + [t]
        self.open_csv()                          # die Aufzeichnung läuft ohne Lücke weiter

    # ------------------------------------------------------------------ Zugriff auf die Daten
    def count(self):
        """Anzahl der Zeilen im Speicher."""
        with self.lock:
            return self.n

    def slice_time(self, t0, t1):
        """Kopie der Zeilen mit t0 <= t <= t1 (plus eine Zeile davor, damit Linien am linken Rand beginnen)
        -> (Zeiten, Werte[Variable][Zeile])."""
        with self.lock:
            n = self.n
            if n == 0:
                return np.empty(0), np.empty((len(self.vars), 0))
            t = self.tbuf[:n]
            i0 = max(int(np.searchsorted(t, t0, side="left")) - 1, 0)
            i1 = int(np.searchsorted(t, t1, side="right"))
            return t[i0:i1].copy(), self.ybuf[:, i0:i1].copy()

    def window(self, seconds):
        """Die letzten ``seconds`` Sekunden -> (Zeiten, Werte[Variable][Zeile])."""
        with self.lock:
            n = self.n
            if n == 0:
                return np.empty(0), np.empty((len(self.vars), 0))
            t = self.tbuf[:n]
            i0 = int(np.searchsorted(t, t[n - 1] - seconds, side="left"))
            return t[i0:n].copy(), self.ybuf[:, i0:n].copy()

    def snapshot(self):
        """Kopie aller Daten im Speicher -> (Zeiten, Werte[Variable][Zeile])."""
        with self.lock:
            return self.tbuf[:self.n].copy(), self.ybuf[:, :self.n].copy()

    def last_row(self):
        """Letzte Zeile -> (Zeit, Werte) oder (None, None) ohne Daten."""
        with self.lock:
            if self.n == 0:
                return None, None
            return float(self.tbuf[self.n - 1]), self.ybuf[:, self.n - 1].copy()
