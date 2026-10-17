# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Trigger und Ereignisprotokoll – ohne Oberfläche (wird vom Recorder, vom Viewer und vom Konfigurationsprogramm
verwendet).

Trigger
-------
Ein Trigger ist eine Bedingung über die Variablen, geschrieben wie eine Formel berechneter Variablen, z. B.
``{Temperatur} > 80``, ``{Druck} < 2 and {Pumpe} == 1`` oder ``abs(ddt({Füllstand})) > 5``. Ist das Ergebnis wahr
(ungleich 0), "kommt" das Ereignis; wird es wieder falsch, "geht" es. Optionen je Trigger:

* Verzögerung: die Bedingung muss so viele Sekunden ununterbrochen erfüllt sein (filtert kurze Spitzen);
* Gehen protokollieren: auch das Ende des Ereignisses eintragen;
* Quittierpflicht: das Ereignis bleibt "offen", bis es im Viewer quittiert wird (zählt in der Statusleiste);
* Meldetext mit Platzhaltern: ``{Name}`` wird durch den aktuellen Wert der Variable ersetzt.

Ereignisprotokoll
-----------------
Eine Textdatei (CSV mit Semikolon, UTF-8, in Excel lesbar) mit einer Zeile je Vorgang:

    ID;Zeit;Art;Trigger;Priorität;Text;Benutzer
    17;2026-10-15 16:20:01.250;KOMMT;Übertemperatur;Alarm;Temperatur zu hoch: 81.3 °C;
    17;2026-10-15 16:22:40.100;GEHT;Übertemperatur;Alarm;;
    17;2026-10-15 16:25:12.000;QUITTIERT;Übertemperatur;Alarm;;mmuster

Notizen (von Hand im Viewer oder im Logger eingetragen) stehen als Art ``NOTIZ`` mit dem Namen des Verfassers in der
Spalte Benutzer in derselben Datei; sie müssen nicht quittiert werden.

Die Quittierung ist selbst ein Eintrag (die Datei wird nur fortgeschrieben, nie geändert). Offen sind alle KOMMT-
Einträge mit Quittierpflicht ohne spätere QUITTIERT-Zeile derselben ID. ``EventLog`` ist thread-sicher: der Recorder
schreibt aus seinem Sammler-Thread, der Viewer quittiert aus der Oberfläche.
"""
import csv
import getpass
import io
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime

from plc_common import BASE_DIR
from plc_formula import Formula, FormulaError
from plc_i18n import N_
from plc_i18n import tr

PRIORITIES = [N_("Info"), N_("Warnung"), N_("Alarm")]
KINDS = ("KOMMT", "GEHT", "QUITTIERT", "NOTIZ")
NOTE = N_("Notiz")                   # Trigger- und Prioritätsspalte von Notizen (von Hand eingetragen)
HEADER = ["ID", "Zeit", "Art", "Trigger", "Priorität", "Text", "Benutzer"]
_REF = re.compile(r"\{([^{}]*)\}")


@dataclass
class Trigger:
    """Eine Ereignisbedingung (siehe Modulbeschreibung)."""
    name: str = "Trigger1"
    bedingung: str = ""
    text: str = ""
    prio: str = "Warnung"
    verzoegerung_s: float = 0.0
    gehen: bool = True
    quittieren: bool = True
    aktiv: bool = True


# ---------------------------------------------------------------------------------------
# Speichern in der Konfigurationsdatei ([Trigger] / [TriggerN])
# ---------------------------------------------------------------------------------------
def load_triggers(path):
    """Trigger aus der Konfigurationsdatei lesen (fehlt die Datei oder der Abschnitt: leere Liste)."""
    if not path or not os.path.exists(path):
        return []
    from plc_common import read_config_store
    cp = read_config_store(path)
    out = []
    for i in range(1, cp.getint("Trigger", "anzahl", fallback=0) + 1):
        sec = f"Trigger{i}"
        if not cp.has_section(sec):
            continue
        s = cp[sec]
        prio = s.get("prio", "Warnung")
        out.append(Trigger(name=s.get("name", sec), bedingung=s.get("bedingung", ""), text=s.get("text", ""),
                           prio=prio if prio in PRIORITIES else "Warnung",
                           verzoegerung_s=max(0.0, s.getfloat("verzoegerung_s", 0.0)),
                           gehen=s.getboolean("gehen", True), quittieren=s.getboolean("quittieren", True),
                           aktiv=s.getboolean("aktiv", True)))
    return out


def save_triggers(path, triggers):
    """Trigger in die (bereits geschriebene) Konfigurationsdatei eintragen; vorhandene Trigger-Abschnitte werden ersetzt."""
    from plc_common import read_config_store, write_config_store
    cp = read_config_store(path)
    for sec in [s for s in cp.sections() if s == "Trigger" or re.fullmatch(r"Trigger\d+", s)]:
        cp.remove_section(sec)
    cp["Trigger"] = {"anzahl": str(len(triggers))}
    for i, t in enumerate(triggers, 1):
        cp[f"Trigger{i}"] = {"name": t.name, "bedingung": " ".join(t.bedingung.split()),
                             "text": " ".join(t.text.split()), "prio": t.prio,
                             "verzoegerung_s": f"{t.verzoegerung_s:g}", "gehen": "1" if t.gehen else "0",
                             "quittieren": "1" if t.quittieren else "0", "aktiv": "1" if t.aktiv else "0"}
    write_config_store(cp, path)


def event_log_path(conn):
    """Pfad des Ereignisprotokolls: Einstellung ``ereignis_datei`` oder <CSV-Ordner>/<CSV-Name>_ereignisse.csv."""
    p = (conn.get("ereignis_datei") or "").strip()
    if not p:
        folder = conn.get("csv_ordner") or "logs"
        p = os.path.join(folder, f"{conn.get('csv_name') or 'log'}_ereignisse.csv")
    return p if os.path.isabs(p) else os.path.join(BASE_DIR, p)


def check_trigger(t, names):
    """Fehlertext für einen Trigger oder "" (Bedingung gültig, alle Variablen bekannt)."""
    if not t.name.strip() or ";" in t.name:
        return tr("Name fehlt oder enthält ';'")
    try:
        f = Formula(t.bedingung)
    except FormulaError as e:
        return f"Bedingung: {e}"
    missing = [n for n in f.refs if n not in names]
    if missing:
        return tr("unbekannte Variablen: ") + ", ".join(missing)
    bad = [n for n in _REF.findall(t.text) if n not in names]
    if bad:
        return tr("Meldetext: unbekannte Variablen ") + ", ".join(bad)
    return ""


# ---------------------------------------------------------------------------------------
# Ereignisprotokoll (Datei)
# ---------------------------------------------------------------------------------------
@dataclass
class Event:
    """Ein Ereignis (KOMMT-Eintrag) mit seinem Verlauf."""
    id: int
    zeit: str
    trigger: str
    prio: str
    text: str
    gegangen: str = ""          # Zeit des GEHT-Eintrags
    quittiert: str = ""         # Zeit der Quittierung
    benutzer: str = ""          # wer quittiert hat
    pflicht: bool = True        # Quittierpflicht
    notiz: bool = False         # von Hand eingetragene Notiz

    @property
    def offen(self):
        return self.pflicht and not self.quittiert


def _stamp(ts=None):
    ts = time.time() if ts is None else ts
    ms = int(round(ts * 1000))
    return datetime.fromtimestamp(ms // 1000).strftime("%Y-%m-%d %H:%M:%S") + f".{ms % 1000:03d}"


class EventLog:
    """Ereignisprotokoll-Datei mit Quittierung (thread-sicher)."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.next_id = 1
        self.open_ids = set()           # offene (unquittierte) Ereignisse
        self.version = 0                # wird bei jeder Änderung erhöht (Viewer/Statusleiste aktualisieren)
        self._mtime = None
        self.reload()

    # ---- Lesen
    def _rows(self):
        try:
            with open(self.path, encoding="utf-8", newline="") as f:
                rows = list(csv.reader(f, delimiter=";"))
        except FileNotFoundError:
            return []
        return [r for r in rows[1:] if len(r) >= 6 and r[0].isdigit() and r[2] in KINDS]

    def events(self):
        """Alle Ereignisse (neueste zuerst) mit Gehen- und Quittierzeit."""
        with self.lock:
            rows = self._rows()
        out, by_id = [], {}
        for r in rows:
            eid, zeit, kind, trig, prio, text = int(r[0]), r[1], r[2], r[3], r[4], r[5]
            user = r[6] if len(r) > 6 else ""
            if kind == "KOMMT":
                ev = Event(eid, zeit, trig, prio, text, pflicht=(user != "-"))
                by_id[eid] = ev
                out.append(ev)
            elif kind == "NOTIZ":
                out.append(Event(eid, zeit, NOTE, NOTE, text, benutzer=user, pflicht=False, notiz=True))
            elif eid in by_id:
                if kind == "GEHT":
                    by_id[eid].gegangen = zeit
                else:
                    by_id[eid].quittiert, by_id[eid].benutzer = zeit, user
        out.reverse()
        out.sort(key=lambda e: e.zeit, reverse=True)       # neueste zuerst (Notizen dürfen zurückdatiert sein)
        return out

    def reload(self):
        """Zähler und offene Ereignisse aus der Datei neu bestimmen (z. B. nach Änderung durch ein anderes Programm)."""
        evs = self.events()
        with self.lock:
            self.next_id = max([e.id for e in evs], default=0) + 1
            self.open_ids = {e.id for e in evs if e.offen}
            self._mtime = self._file_mtime()
            self.version += 1

    def _file_mtime(self):
        try:
            return os.path.getmtime(self.path)
        except OSError:
            return None

    def changed_on_disk(self):
        """True, wenn die Datei seit dem letzten Lesen/Schreiben von außen geändert wurde."""
        return self._file_mtime() != self._mtime

    def open_count(self):
        """Anzahl offener Ereignisse (liest die Datei neu, wenn ein anderes Programm sie geändert hat)."""
        if self.changed_on_disk():
            try:
                self.reload()
            except (OSError, ValueError):
                pass
        with self.lock:
            return len(self.open_ids)

    # ---- Schreiben
    def _write(self, rows):
        new = not os.path.exists(self.path)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
        if new:
            w.writerow(HEADER)
        w.writerows(rows)
        with open(self.path, "a", encoding="utf-8", newline="") as f:
            f.write(buf.getvalue())
        self._mtime = self._file_mtime()
        self.version += 1

    def come(self, trigger, text, ts=None):
        """Ereignis kommt -> ID."""
        with self.lock:
            eid = self.next_id
            self.next_id += 1
            # Benutzerspalte bei KOMMT: "-" = keine Quittierpflicht (sonst leer).
            self._write([[eid, _stamp(ts), "KOMMT", trigger.name, trigger.prio, text, "" if trigger.quittieren else "-"]])
            if trigger.quittieren:
                self.open_ids.add(eid)
            return eid

    def note(self, text, ts=None, user=None):
        """Notiz von Hand eintragen (Zeit ts, Standard: jetzt) -> ID."""
        text = str(text).replace("\r", "").strip()
        if not text:
            raise ValueError(tr("Die Notiz ist leer."))
        user = user or getpass.getuser()
        with self.lock:
            eid = self.next_id
            self.next_id += 1
            self._write([[eid, _stamp(ts), "NOTIZ", NOTE, NOTE, text, user]])
            return eid

    def go(self, eid, trigger, ts=None):
        with self.lock:
            self._write([[eid, _stamp(ts), "GEHT", trigger.name, trigger.prio, "", ""]])

    def acknowledge(self, ids=None, user=None):
        """Ereignisse quittieren (ids=None: alle offenen). Rückgabe: Anzahl quittierter Ereignisse."""
        if self.changed_on_disk():
            self.reload()                       # z. B. Logger läuft in einem anderen Prozess
        user = user or getpass.getuser()
        evs = {e.id: e for e in self.events() if e.offen}
        with self.lock:
            todo = sorted(evs if ids is None else [i for i in ids if i in evs])
            if todo:
                now = _stamp()
                self._write([[i, now, "QUITTIERT", evs[i].trigger, evs[i].prio, "", user] for i in todo])
                self.open_ids -= set(todo)
            return len(todo)


# ---------------------------------------------------------------------------------------
# Auswertung (im Sammler-Thread des Recorders)
# ---------------------------------------------------------------------------------------
class _State:
    __slots__ = ("trigger", "formula", "since", "on", "eid")

    def __init__(self, trigger, formula):
        self.trigger, self.formula = trigger, formula
        self.since, self.on, self.eid = None, False, None


def _fmt(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    v = float(v)
    if v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    return f"{v:.2f}" if 1 <= abs(v) < 1e6 else f"{v:.4g}"


class TriggerEngine:
    """Wertet die aktiven Trigger je Messzeile aus und schreibt Ereignisse ins Protokoll."""

    def __init__(self, triggers, log: EventLog, emit=None, names=None):
        """names: bekannte Variablennamen; Trigger mit unbekannten Variablen werden dann übersprungen (errors)."""
        self.log = log
        self.emit = emit or (lambda _t: None)
        self.states, self.errors = [], []
        for t in triggers:
            if not t.aktiv:
                continue
            if names is not None:
                err = check_trigger(t, set(names))
                if err:
                    self.errors.append(tr("Trigger {0} übersprungen: {1}").format(t.name, err))
                    continue
            try:
                self.states.append(_State(t, Formula(t.bedingung)))
            except FormulaError as e:
                self.errors.append(f"Trigger {t.name}: {e}")

    def __bool__(self):
        return bool(self.states)

    def evaluate(self, ts, values):
        """values: {Variablenname: Wert} der aktuellen Zeile."""
        for st in self.states:
            try:
                r = st.formula.evaluate(ts, values)
            except Exception:
                r = float("nan")
            active = r == r and r != 0                       # NaN (kein Wert) gilt als "nicht erfüllt"
            t = st.trigger
            if active:
                if st.on:
                    continue
                if st.since is None:
                    st.since = ts
                if ts - st.since >= t.verzoegerung_s:
                    text = _REF.sub(lambda m: _fmt(values.get(m.group(1))), t.text) if t.text else t.bedingung
                    st.eid = self.log.come(t, text, ts)
                    st.on = True
                    self.emit(f"⚠ {t.prio}: {t.name} – {text}")
            else:
                st.since = None
                if st.on:
                    st.on = False
                    if t.gehen:
                        self.log.go(st.eid, t, ts)
