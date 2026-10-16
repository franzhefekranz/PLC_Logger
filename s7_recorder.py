"""Aufzeichnungskern des S7-Datenloggers – ohne Oberfläche (kein Qt), daher auch für den Headless-Betrieb.

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

from s7_common import BASE_DIR, PALETTE, Axis, Chart, Variable, build_plan, read_plan
from s7_events import EventLog, Trigger, TriggerEngine, event_log_path, load_triggers
from s7_formula import Formula, FormulaError
from s7_util import fmt_csv
from s7_db import DbWriter, describe as db_describe, db_settings
from s7_i18n import tr

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
# Lese-Thread einer Steuerung
# ---------------------------------------------------------------------------------------
class PlcSampler(threading.Thread):
    """Liest zyklisch alle Variablen EINER Steuerung und stellt die Messzyklen in die Warteschlange des Recorders."""

    def __init__(self, rec, idx, plc, var_idx):
        super().__init__(name=f"plc-{idx}", daemon=True)
        self.rec, self.idx, self.plc = rec, idx, plc
        self.var_idx = var_idx                                   # globale Indizes der Variablen dieser Steuerung
        self.vars = [rec.vars[i] for i in var_idx]
        # Leseplan einmal berechnen: Block-Elemente werden mit einer Anfrage je Block gelesen.
        self.plan = build_plan(self.vars)

    def _sleep(self, seconds):
        """Wartet, bricht aber in 50-ms-Schritten ab, sobald der Recorder beendet wird."""
        end = time.perf_counter() + seconds
        while not self.rec.stop_evt.is_set() and time.perf_counter() < end:
            time.sleep(min(0.05, max(0.0, end - time.perf_counter())))

    def run(self):
        if self.rec.demo:
            self._run_demo()
        else:
            self._run_plc()

    def _put(self, ts, values):
        self.rec.put_sample(self.idx, ts, values)

    # Simulation: Werte werden berechnet statt gelesen.
    def _run_demo(self):
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

    # Echte Steuerung: verbinden -> lesen -> melden -> warten; bei Fehlern neu verbinden.
    def _run_plc(self):
        from snap7.client import Client              # erst hier importieren (Demo und Tests brauchen snap7 nicht)
        r, plc = self.rec, self.plc
        interval = plc.intervall_ms / 1000.0
        client, connected = Client(), False
        nxt = time.perf_counter()
        while not r.stop_evt.is_set():
            if not connected:
                r.set_status(self.idx, ST_CONNECTING, tr("Verbinde mit {0} …").format(plc.ip))
                try:
                    client.connect(plc.ip, plc.rack, plc.slot)
                    connected = True
                    r.set_status(self.idx, ST_OK, tr("Verbunden mit {0}").format(plc.ip))
                    nxt = time.perf_counter()
                except Exception as e:
                    r.set_status(self.idx, ST_ERROR, tr("Verbindung zu {0} fehlgeschlagen: {1}").format(plc.ip, e))
                    self._sleep(2.0)
                    continue
            # Zeitstempel unmittelbar vor dem Lesen: so gehört der Wert möglichst genau zu diesem Zeitpunkt.
            ts, t_start = time.time(), time.perf_counter()
            try:
                values = read_plan(client, self.plan, len(self.vars))
            except Exception as e:
                connected = False
                try:
                    client.disconnect()
                except Exception:
                    pass
                r.set_status(self.idx, ST_ERROR, tr("Lesefehler: {0} – neuer Verbindungsversuch").format(e))
                self._sleep(1.0)
                continue
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
        try:
            client.disconnect()
        except Exception:
            pass
        r.set_status(self.idx, ST_OFF, tr("Getrennt"))


# ---------------------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------------------
class Recorder:
    """Aufzeichnung für eine Konfiguration: Lesen, Rechnen, Puffern, CSV, Archiv.

    conn/plcs/charts/variables stammen aus s7_common.load_config/load_plcs. ``demo=True`` simuliert die Werte.
    ``log`` (optional) erhält jede Meldung als Text (Headless: Logdatei)."""

    MAX_POINTS = 300_000          # Obergrenze der im Speicher gehaltenen Zeilen (die CSV-Datei enthält alles)
    FLUSH_S = 0.5                 # CSV spätestens alle 0,5 s auf den Datenträger schreiben (flush)

    def __init__(self, conn, plcs, charts, variables, demo=False, log=None, config_path=""):
        self.conn, self.plcs, self.charts, self.vars = conn, plcs, charts, variables
        self.demo, self.log, self.config_path = demo, log, config_path
        n = len(variables)
        self.names = [v.name for v in variables]
        # Variablen je Steuerung (nur gelesene, keine berechneten) und berechnete Variablen.
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
        self.tbuf = np.empty(self._cap)
        self.ybuf = np.full((n, self._cap), np.nan)
        self.n = 0
        self.dirty = False                       # neue Daten seit dem letzten Abholen (für die Anzeige)
        # Verbindungszustände: [(Zustand, Text)] je Steuerung und geglättete Lesezeit in ms.
        self.status = [(ST_OFF, "gestoppt")] * len(plcs)
        self.read_ms = [0.0] * len(plcs)
        self.messages = collections.deque(maxlen=1000)
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

    # ------------------------------------------------------------------ Ordner
    def csv_dir(self):
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
        """CSV-Datei öffnen, Sammler und je Steuerung einen Lese-Thread starten."""
        if self.running:
            return
        self.stop_evt.clear()
        if self.csv_on:
            self.open_csv()
        if self.db_conf["typ"]:
            self.db = DbWriter(self.conn, self.names, self.emit)
            self.db.start()
        self.trigger_engine = TriggerEngine(self.triggers, self.events, self.emit, self.names) if self.triggers else None
        if self.trigger_engine is not None:
            for err in self.trigger_engine.errors:
                self.emit("⚠ " + err)
            if not self.trigger_engine:
                self.trigger_engine = None
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
        targets = ([self.csv_path] if self.csv_on else []) + ([db_describe(self.db_conf)] if self.db else [])
        self.emit(tr("Aufzeichnung gestartet → ") + (" und ".join(targets) or tr("nur Anzeige (weder CSV noch Datenbank)")))
        if self.trigger_engine:
            self.emit(tr("{0} Trigger aktiv → Ereignisprotokoll {1}").format(len(self.trigger_engine.states), self.events.path))

    def stop(self):
        """Lese-Threads und Sammler beenden, CSV-Datei schließen (bleibt ungepackt im CSV-Ordner)."""
        if not self.running:
            return
        self.stop_evt.set()
        for s in self.samplers:
            s.join(5.0)
        self.q.put(None)                         # Ende-Marke: der Sammler verarbeitet vorher noch alles Übrige
        if self.collector:
            self.collector.join(10.0)
        if self.db:                              # Datenbank: restliche Werte schreiben, Thread beenden
            self.db.stop()
            if self.db.buf:
                self.emit(tr("⚠ Datenbank: {0} Werte konnten nicht mehr geschrieben werden").format(len(self.db.buf)))
        self.running = False
        if self.csv_fh:
            try:
                self.csv_fh.close()
            finally:
                self.csv_fh = self.csv_w = None
        for k in range(len(self.plcs)):
            self.set_status(k, ST_OFF, tr("gestoppt"))
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
        for t in self._archive_threads:          # noch laufende Archivierungen (Rotation) abwarten
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
            for gi, val in zip(self.plc_vars[idx], values):
                cur[gi] = val
            row = cur.copy()
            engine = self.trigger_engine
            if self.computed_idx or engine:
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
            self._write_csv(ts, row)
            if self.db:
                self.db.put(ts, row)
        self._flush_if_due(force=True)

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
