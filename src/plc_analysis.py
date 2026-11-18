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

from plc_i18n import N_, tr

WINDOWS = {"hann": N_("Hann (Standard)"), "hamming": N_("Hamming"), "blackman": N_("Blackman"),
           "rechteck": N_("Rechteck (ohne Fenster)"), "flattop": N_("Flat-Top (genaue Amplituden)")}


def _window(name, n):
    """Fensterfunktion ``name`` mit n Werten (Hann, Hamming, Blackman, Rechteck oder Flat-Top).

    Das Fenster blendet den Anfang und das Ende der Messreihe weich aus, damit der harte Schnitt an den Rändern keine
    Scheinfrequenzen erzeugt („Leckeffekt“). Flat-Top liefert genaue Amplituden, aber breitere Spitzen.
    """
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


MAX_POINTS = 2 ** 19          # höchstens so viele Rasterpunkte (≈ 0,5 Mio.; Speicher und Rechenzeit auch auf dem Pi)
GAP_FACTOR = 10               # Lücke = mehr als das Zehnfache des üblichen Messabstands


def resample_uniform(t, y, dt=None, info=None):
    """Messwerte (t, y) linear auf ein gleichmäßiges Raster umrechnen -> (Zeiten, Werte, dt).

    dt: Rasterabstand in s (Standard: Median der Messabstände). NaN-Werte werden überbrückt. Die Werte werden nach
    der Zeit sortiert (Zeitsprünge der Uhr). Enthält der Bereich Lücken (Aufzeichnung unterbrochen, mehr als
    GAP_FACTOR × dt), wird der längste lückenlose Abschnitt verwendet – eine lineare Überbrückung über Stunden ergäbe
    Scheinfrequenzen. Wären es mehr als MAX_POINTS Punkte, wird das Raster gröber. ``info`` (dict, optional) erhält
    dann ``gap`` bzw. ``coarser`` = True für die Anzeige."""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(t) & np.isfinite(y)
    t, y = t[ok], y[ok]
    if len(t) < 2:
        raise ValueError(tr("zu wenige gültige Messwerte"))
    if np.any(np.diff(t) < 0):                         # nicht aufsteigend (Uhr zurückgestellt): sortieren
        o = np.argsort(t, kind="stable")
        t, y = t[o], y[o]
    d = np.diff(t)
    d = d[d > 0]
    if dt is None:
        if not len(d):
            raise ValueError(tr("alle Messwerte haben denselben Zeitstempel"))
        dt = float(np.median(d))
        cuts = np.flatnonzero(np.diff(t) > GAP_FACTOR * dt)
        if len(cuts):                                  # längsten lückenlosen Abschnitt nehmen
            edges = np.r_[0, cuts + 1, len(t)]
            k = int(np.argmax(np.diff(edges)))
            t, y = t[edges[k]:edges[k + 1]], y[edges[k]:edges[k + 1]]
            if info is not None:
                info["gap"] = True
            if len(t) < 2:
                raise ValueError(tr("zu wenige gültige Messwerte"))
    n = int(math.floor((t[-1] - t[0]) / dt)) + 1
    if n > MAX_POINTS:                                 # Schutz vor riesigen Feldern: gröberes Raster
        dt = (t[-1] - t[0]) / (MAX_POINTS - 1)
        n = MAX_POINTS
        if info is not None:
            info["coarser"] = True
    tu = t[0] + np.arange(n) * dt
    return tu, np.interp(tu, t, y), dt


def spectrum(t, y, window="hann", detrend="mean"):
    """Amplitudenspektrum -> dict(f, amp, dt, fs, n, df, peaks, rms).

    detrend: "mean" (Mittelwert abziehen), "linear" (Gerade abziehen) oder "" (nichts)."""
    info = {}
    tu, yu, dt = resample_uniform(t, y, info=info)
    n = len(yu)
    if n < 8:
        raise ValueError(tr("für eine Frequenzanalyse werden mindestens 8 Messwerte benötigt"))
    if detrend == "linear":
        k = np.arange(n)
        a, b = np.polyfit(k, yu, 1)
        yu = yu - (a * k + b)
    elif detrend == "mean":
        yu = yu - yu.mean()
    w = _window(window, n)
    spec = np.fft.rfft(yu * w)
    # Normierung: ×2 für das einseitige Spektrum (die negativen Frequenzen fallen weg), ÷ (n · Fenstermittel)
    # gleicht die Dämpfung durch das Fenster aus. Gleichanteil und Nyquist-Frequenz kommen nur einmal vor (÷2).
    amp = np.abs(spec) * 2.0 / (n * w.mean())
    amp[0] /= 2.0
    if n % 2 == 0:
        amp[-1] /= 2.0
    f = np.fft.rfftfreq(n, dt)
    return {"f": f, "amp": amp, "dt": dt, "fs": 1.0 / dt, "n": n, "df": f[1] - f[0] if len(f) > 1 else 0.0,
            "peaks": find_peaks(f, amp), "rms": float(np.sqrt(np.mean(yu ** 2))),
            "gap": bool(info.get("gap")), "coarser": bool(info.get("coarser"))}


def find_peaks(f, amp, count=5, min_rel=0.05):
    """Die höchsten lokalen Maxima (ohne Gleichanteil) -> [(Frequenz, Amplitude)], höchstes zuerst.

    Die Frequenz wird mit einer Parabel durch die drei Nachbarwerte verfeinert."""
    a = np.asarray(amp, dtype=float)
    if len(a) < 3:
        return []
    top = float(a[1:].max())
    if top <= 0:
        return []
    mid = a[1:-1]                                      # lokale Maxima, vektorisiert (schnell auch bei 0,5 Mio. Werten)
    idx = np.flatnonzero((mid >= a[:-2]) & (mid > a[2:]) & (mid >= min_rel * top)) + 1
    idx = idx[np.argsort(-a[idx], kind="stable")]
    out = []
    df = f[1] - f[0]
    for i in idx[:count]:
        y0, y1, y2 = a[i - 1], a[i], a[i + 1]
        den = y0 - 2 * y1 + y2
        # Parabel durch die drei Nachbarpunkte: Scheitel liegt p Rasterschritte neben dem Maximum (−0,5 … 0,5).
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
