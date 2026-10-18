# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Auswertungen ohne Oberfläche: XY-Darstellung und Frequenzanalyse (FFT).

Frequenzanalyse
---------------
Die Messwerte liegen nicht unbedingt in exakt gleichen Abständen vor (schwankende Lesezeit, mehrere Steuerungen).
Für die FFT werden sie deshalb zuerst linear auf ein gleichmäßiges Raster mit dem üblichen (Median-)Messabstand
umgerechnet; fehlende Werte (NaN) werden dabei überbrückt. Danach: Mittelwert abziehen (optional auch einen linearen
Trend), Fensterfunktion anwenden, einseitiges Amplitudenspektrum berechnen. Die Amplituden sind so normiert, dass ein
Sinus der Amplitude A (Spitze) im Spektrum etwa die Höhe A hat (Korrektur der Fensterfunktion).

Die höchste darstellbare Frequenz ist die halbe Abtastrate (Nyquist): bei 100 ms Messabstand also 5 Hz.
"""
import math

import numpy as np

from plc_i18n import N_

WINDOWS = {"hann": N_("Hann (Standard)"), "hamming": N_("Hamming"), "blackman": N_("Blackman"),
           "rechteck": N_("Rechteck (ohne Fenster)"), "flattop": N_("Flat-Top (genaue Amplituden)")}


def _window(name, n):
    if name == "hamming":
        return np.hamming(n)
    if name == "blackman":
        return np.blackman(n)
    if name == "rechteck":
        return np.ones(n)
    if name == "flattop":
        k = np.arange(n) / max(n - 1, 1) * 2 * math.pi
        return (0.21557895 - 0.41663158 * np.cos(k) + 0.277263158 * np.cos(2 * k)
                - 0.083578947 * np.cos(3 * k) + 0.006947368 * np.cos(4 * k))
    return np.hanning(n)


def resample_uniform(t, y, dt=None):
    """Messwerte (t, y) linear auf ein gleichmäßiges Raster umrechnen -> (Zeiten, Werte, dt).

    dt: Rasterabstand in s (Standard: Median der Messabstände). NaN-Werte werden überbrückt."""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(t) & np.isfinite(y)
    t, y = t[ok], y[ok]
    if len(t) < 2:
        raise ValueError("zu wenige gültige Messwerte")
    d = np.diff(t)
    d = d[d > 0]
    if dt is None:
        if not len(d):
            raise ValueError("alle Messwerte haben denselben Zeitstempel")
        dt = float(np.median(d))
    n = int(math.floor((t[-1] - t[0]) / dt)) + 1
    if n > 2_000_000:                                  # Schutz vor riesigen Feldern
        dt = (t[-1] - t[0]) / 2_000_000
        n = 2_000_001
    tu = t[0] + np.arange(n) * dt
    return tu, np.interp(tu, t, y), dt


def spectrum(t, y, window="hann", detrend="mean"):
    """Amplitudenspektrum -> dict(f, amp, dt, fs, n, df, peaks, rms).

    detrend: "mean" (Mittelwert abziehen), "linear" (Gerade abziehen) oder "" (nichts)."""
    tu, yu, dt = resample_uniform(t, y)
    n = len(yu)
    if n < 8:
        raise ValueError("für eine Frequenzanalyse werden mindestens 8 Messwerte benötigt")
    if detrend == "linear":
        k = np.arange(n)
        a, b = np.polyfit(k, yu, 1)
        yu = yu - (a * k + b)
    elif detrend == "mean":
        yu = yu - yu.mean()
    w = _window(window, n)
    spec = np.fft.rfft(yu * w)
    amp = np.abs(spec) * 2.0 / (n * w.mean())
    amp[0] /= 2.0
    if n % 2 == 0:
        amp[-1] /= 2.0
    f = np.fft.rfftfreq(n, dt)
    return {"f": f, "amp": amp, "dt": dt, "fs": 1.0 / dt, "n": n, "df": f[1] - f[0] if len(f) > 1 else 0.0,
            "peaks": find_peaks(f, amp), "rms": float(np.sqrt(np.mean(yu ** 2)))}


def find_peaks(f, amp, count=5, min_rel=0.05):
    """Die höchsten lokalen Maxima (ohne Gleichanteil) -> [(Frequenz, Amplitude)], höchstes zuerst.

    Die Frequenz wird mit einer Parabel durch die drei Nachbarwerte verfeinert."""
    a = np.asarray(amp, dtype=float)
    if len(a) < 3:
        return []
    top = float(a[1:].max()) if len(a) > 1 else 0.0
    if top <= 0:
        return []
    idx = [i for i in range(1, len(a) - 1) if a[i] >= a[i - 1] and a[i] > a[i + 1] and a[i] >= min_rel * top]
    idx.sort(key=lambda i: a[i], reverse=True)
    out = []
    df = f[1] - f[0]
    for i in idx[:count]:
        y0, y1, y2 = a[i - 1], a[i], a[i + 1]
        den = y0 - 2 * y1 + y2
        p = 0.5 * (y0 - y2) / den if den else 0.0
        out.append((float(f[i] + p * df), float(y1)))
    return out


def xy_pairs(x, y):
    """Wertepaare ohne fehlende Werte -> (x, y)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    return x[ok], y[ok]


def correlation(x, y):
    """Korrelationskoeffizient nach Pearson und Ausgleichsgerade -> (r, Steigung, Achsenabschnitt) oder None."""
    x, y = xy_pairs(x, y)
    if len(x) < 3 or np.ptp(x) == 0 or np.ptp(y) == 0:
        return None
    r = float(np.corrcoef(x, y)[0, 1])
    a, b = np.polyfit(x, y, 1)
    return r, float(a), float(b)


def fmt_freq(f):
    """Frequenz lesbar: Hz bzw. mHz, dazu die Periodendauer."""
    if f <= 0:
        return "0 Hz"
    per = 1.0 / f
    ftxt = f"{f:.4g} Hz" if f >= 0.1 else f"{f * 1000:.4g} mHz"
    if per < 1:
        ptxt = f"{per * 1000:.4g} ms"
    elif per < 120:
        ptxt = f"{per:.4g} s"
    else:
        ptxt = f"{per / 60:.4g} min"
    return f"{ftxt} (T = {ptxt})"
