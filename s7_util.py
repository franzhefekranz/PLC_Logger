"""Kleine, oberflächenfreie Hilfsfunktionen des S7-Datenloggers.

Das Modul wird vom Aufzeichnungskern (s7_recorder.py), vom Logger, vom Webserver (s7_web.py) und vom
SVG-Export (s7_svg.py) gemeinsam verwendet. Es braucht nur numpy – weder Qt noch snap7.

* Textformate:   fmt_value (Anzeige), fmt_csv (CSV-Datei), fmt_time (Zeitstempel mit Millisekunden)
* Kurvenform:    to_step (Treppenlinie), decimate_minmax (Datenmenge verkleinern, Spitzen bleiben erhalten)
* Achsenteilung: nice_ticks (runde Teilstriche für Y-Achsen), time_ticks (Teilstriche der Zeitachse)
"""
import math
from datetime import datetime

import numpy as np


def fmt_value(v, dtype):
    """Wert als Text für Tabelle und Legende: REAL mit 3 Nachkommastellen, Ganzzahlen ohne; ungültig = Strich."""
    if v is None or math.isnan(v):
        return "—"
    return f"{v:.3f}" if dtype in ("REAL", "LREAL") else f"{int(v)}"


def fmt_csv(v, dtype):
    """Wert für die CSV-Datei: REAL mit 7 signifikanten Stellen, sonst ganzzahlig; NaN = leeres Feld."""
    if math.isnan(v):
        return ""
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


# Mögliche Schrittweiten der Zeitachse in Sekunden (1 s ... 1 Tag).
_TIME_STEPS = (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 14400, 21600, 43200, 86400)


def time_ticks(t0, t1, target=7):
    """Teilstriche der Zeitachse (Unix-Zeit) zwischen t0 und t1 -> Liste (Zeit, Beschriftung).

    Die Schrittweite wird so gewählt, dass etwa ``target`` Striche entstehen; Beschriftung mit Sekunden, wenn der
    Schritt unter einer Minute liegt, sonst nur Stunde:Minute. Teilstriche liegen auf runden Uhrzeiten (lokale Zeit)."""
    span = t1 - t0
    if span <= 0:
        return []
    step = next((s for s in _TIME_STEPS if span / s <= target), _TIME_STEPS[-1])
    # Ausrichtung auf lokale Zeit: den Offset der Zeitzone berücksichtigen.
    off = datetime.fromtimestamp(t0).astimezone().utcoffset().total_seconds()
    first = math.ceil((t0 + off) / step) * step - off
    out, t = [], first
    while t <= t1 and len(out) < 200:
        d = datetime.fromtimestamp(t)
        out.append((t, d.strftime("%H:%M:%S") if step < 60 else d.strftime("%H:%M")))
        t += step
    return out
