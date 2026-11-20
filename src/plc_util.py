# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Kleine, oberflächenfreie Hilfsfunktionen des PLC-Datenloggers.

Das Modul wird vom Aufzeichnungskern (plc_recorder.py), vom Logger, vom Webserver (plc_web.py) und vom
SVG-Export (plc_svg.py) gemeinsam verwendet. Es braucht nur numpy – weder Qt noch Steuerungsbibliotheken.

* Textformate:   fmt_value (Anzeige), fmt_csv (CSV-Datei), fmt_time (Zeitstempel mit Millisekunden)
* Kurvenform:    to_step (Treppenlinie), decimate_minmax (Datenmenge verkleinern, Spitzen bleiben erhalten)
* Achsenteilung: nice_ticks (runde Teilstriche für Y-Achsen), time_ticks (Teilstriche der Zeitachse)
"""
import math
from datetime import datetime, timedelta

import numpy as np


def fmt_value(v, dtype):
    """Wert als Text für Tabelle und Legende: REAL mit 3 Nachkommastellen, Ganzzahlen ohne; ungültig = Strich."""
    if v is None or math.isnan(v):
        return "—"
    return f"{v:.3f}" if dtype in ("REAL", "LREAL") else f"{int(v)}"


def fmt_csv(v, dtype):
    """Wert für die CSV-Datei: REAL mit 7 signifikanten Stellen, sonst ganzzahlig; NaN = leeres Feld, ±inf bei REAL
    als „inf“/„-inf“, bei Ganzzahltypen leer (int(inf) ginge nicht)."""
    if not math.isfinite(v):
        return f"{v}" if dtype in ("REAL", "LREAL") and not math.isnan(v) else ""
    return f"{v:.7g}" if dtype in ("REAL", "LREAL") else str(int(v))


def fmt_time(ts):
    """Zeitstempel als lesbarer Text mit Millisekunden (für Lineal-Anzeige und Statusmeldungen)."""
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M:%S.%f")[:-3]


def to_step(x, y):
    """Aus Messpunkten (x, y) eine Treppenlinie machen: jeder Wert gilt bis zum nächsten Messpunkt.

    Beispiel: x=[1,2,3], y=[a,b,c] -> x'=[1,2,2,3,3], y'=[a,a,b,b,c]."""
    if len(x) < 2:
        return x, y
    return np.repeat(x, 2)[1:], np.repeat(y, 2)[:-1]


def decimate_minmax(x, y, buckets):
    """Verkleinert (x, y) auf höchstens ``2 * buckets`` Punkte, ohne Spitzen zu verlieren.

    Die Daten werden in ``buckets`` gleich große Abschnitte geteilt; aus jedem Abschnitt bleiben der Punkt mit dem
    kleinsten und der mit dem größten Wert (in zeitlicher Reihenfolge) erhalten. So verschwinden kurze Spitzen
    und BOOL-Impulse nicht, wie es beim bloßen Auslassen jedes n-ten Punktes passieren würde.
    NaN-Werte werden dabei ignoriert; ein Abschnitt, der nur aus NaN besteht, liefert seinen ersten Punkt."""
    n = len(x)
    if buckets <= 0 or n <= 2 * buckets:
        return x, y
    # Abschnittsgrenzen: gleichmäßig über die Indizes verteilt.
    edges = np.linspace(0, n, buckets + 1).astype(int)
    keep = []
    for a, b in zip(edges[:-1], edges[1:]):
        if b <= a:
            continue
        seg = y[a:b]
        finite = np.isfinite(seg)
        if not finite.any():
            keep.append(a)
            continue
        lo = a + int(np.argmin(np.where(finite, seg, np.inf)))
        hi = a + int(np.argmax(np.where(finite, seg, -np.inf)))
        keep.extend(sorted({lo, hi}))
    idx = np.asarray(keep, dtype=int)
    return x[idx], y[idx]


def nice_ticks(lo, hi, target=6):
    """Runde Teilstriche (1, 2, 5 · 10^k) im Bereich lo..hi, etwa ``target`` Stück."""
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return []
    if hi < lo:
        lo, hi = hi, lo
    span = hi - lo
    if span <= 0:
        return [lo]
    raw = span / max(target, 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    first = math.ceil(lo / step - 1e-9) * step
    out, v = [], first
    while v <= hi + step * 1e-9 and len(out) < 100:
        out.append(round(v, 12))
        v += step
    return out


# Mögliche Schrittweiten der Zeitachse in Sekunden (1 s ... 7 Tage).
_TIME_STEPS = (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 14400, 21600, 43200,
               86400, 2 * 86400, 7 * 86400)


def time_ticks(t0, t1, target=7):
    """Teilstriche der Zeitachse (Unix-Zeit) zwischen t0 und t1 -> Liste (Zeit, Beschriftung).

    Die Schrittweite wird so gewählt, dass etwa ``target`` Striche entstehen; die Striche liegen auf runden Uhrzeiten
    der Ortszeit. Ab einer Stunde Schrittweite wird in Ortszeit (Wanduhr) weitergezählt, damit sie über eine
    Zeitumstellung hinweg auf vollen Stunden bzw. 0:00 bleiben. Beschriftung: Sekunden bei Schritten unter einer
    Minute, Datum (TT.MM.) bei Tagesschritten, über mehrere Tage um Mitternacht Datum und Uhrzeit, sonst hh:mm."""
    span = t1 - t0
    if span <= 0:
        return []
    step = next((s for s in _TIME_STEPS if span / s <= target), _TIME_STEPS[-1])
    times = []
    if step >= 3600:
        d = datetime.fromtimestamp(t0).replace(minute=0, second=0, microsecond=0)
        if step >= 86400:
            d = d.replace(hour=0)
        while d.timestamp() < t0 or (step < 86400 and (d.hour * 3600) % step):
            d += timedelta(hours=1) if step < 86400 else timedelta(days=1)
        while d.timestamp() <= t1 and len(times) < 200:
            times.append(d.timestamp())
            d += timedelta(seconds=step)          # naive Ortszeit: Rechnen auf der Wanduhr
    else:
        off = datetime.fromtimestamp(t0).astimezone().utcoffset().total_seconds()
        t = math.ceil((t0 + off) / step) * step - off
        while t <= t1 and len(times) < 200:
            times.append(t)
            t += step
    out = []
    for t in times:
        d = datetime.fromtimestamp(t)
        if step < 60:
            lab = d.strftime("%H:%M:%S")
        elif step >= 86400:
            lab = d.strftime("%d.%m.")
        elif span > 86400 and (d.hour, d.minute) == (0, 0):
            lab = d.strftime("%d.%m. %H:%M")
        else:
            lab = d.strftime("%H:%M")
        out.append((t, lab))
    return out


def text_filter(pattern):
    """Suchtext -> Prüffunktion f(*Felder) -> bool (für Such-/Filterfelder).

    Groß-/Kleinschreibung egal; mehrere Wörter müssen alle vorkommen (in irgendeinem Feld); ``*`` und ``?`` sind
    Platzhalter; ein Wort mit vorangestelltem ``-`` schließt aus. Leerer Suchtext: alles passt."""
    import fnmatch
    import re
    words = [w for w in str(pattern or "").lower().split() if w not in ("", "-")]
    if not words:
        return lambda *fields: True
    tests = []
    for w in words:
        neg = w.startswith("-")
        w = w[1:] if neg else w
        if any(c in w for c in "*?["):
            rx = re.compile(fnmatch.translate(w).replace(r"\Z", "").rstrip("$"), re.S)
            # Die äußere Funktion bindet den aktuellen Wert von rx bzw. w (sonst sähen alle Prüfungen das letzte Wort
            # der Schleife).
            match = (lambda rx: lambda s: rx.search(s) is not None)(rx)
        else:
            match = (lambda w: lambda s: w in s)(w)
        tests.append((neg, match))

    def check(*fields):
        """Alle Suchwörter prüfen: ein Wort passt, wenn es in irgendeinem Feld vorkommt; ausschließende Wörter
        (``-wort``) dürfen in keinem Feld vorkommen.
        """
        texts = [str(f or "").lower() for f in fields]
        for neg, match in tests:
            hit = any(match(t) for t in texts)
            if hit == neg:
                return False
        return True
    return check
