# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Aufzeichnungen (CSV oder archivierte ZIP-Dateien) lesen und aneinanderhängen – ohne Oberfläche.

Aufbau einer Aufzeichnung: Kopfzeile ``Zeit;Epoch;<Variablen …>``, danach eine Zeile je Messzeitpunkt (Semikolon,
UTF-8). Beim Zusammenfügen mehrerer Dateien

* werden die Spalten über den Variablennamen zugeordnet (Reihenfolge der ersten Datei, neue Namen hinten angehängt;
  fehlt eine Variable in einer Datei, bleibt sie dort leer),
* werden alle Zeilen nach der Zeit sortiert (auch wenn die Dateien in beliebiger Reihenfolge gewählt wurden),
* werden doppelte Zeitpunkte (überlappende Dateien) nur einmal übernommen – je Variable mit dem ersten
  vorhandenen Wert,
* wird an Lücken zwischen den Dateien eine leere Zeile eingefügt, damit die Kurven dort unterbrochen sind
  (z. B. zwischen zwei Aufnahmen per Trigger) – auf Wunsch abschaltbar.
"""
import contextlib
import csv
import io
import zipfile

import numpy as np

from plc_i18n import tr


@contextlib.contextmanager
def open_log(path):
    """Öffnet eine CSV- oder ZIP-Datei (erste CSV im Archiv) als Textdatei."""
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
            if name is None:
                raise ValueError(tr("Das Archiv enthält keine CSV-Datei."))
            with z.open(name) as raw:
                yield io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
    else:
        with open(path, newline="", encoding="utf-8-sig") as f:
            yield f


CHUNK = 5000                    # Zeilen je Umwandlungsschritt (Speicher: Textfeld nur für einen Block)


def _num(text):
    """Feld als Zahl (Dezimalkomma erlaubt); leer oder ungültig -> NaN."""
    text = text.strip().replace(",", ".")
    try:
        return float(text) if text else np.nan
    except ValueError:
        return np.nan


def _convert(rows, n):
    """Block von CSV-Zeilen -> (Zeiten, Werte[n][Zeilen]) als numpy-Felder; Zeilen ohne gültige Zeit entfallen.

    Vektorisiert über numpy-Text; nur wenn der Block ungültige Felder enthält, wird zellweise umgewandelt."""
    a = np.array([r[1:2 + n] for r in rows], dtype=str)
    a = np.char.replace(np.char.strip(a), ",", ".")
    a[a == ""] = "nan"
    try:
        v = a.astype(float)
    except ValueError:
        v = np.array([[_num(x) for x in r] for r in a], dtype=float).reshape(len(rows), n + 1)
    ok = np.isfinite(v[:, 0])
    return v[ok, 0], v[ok, 1:].T


def read_log(path):
    """Aufzeichnung lesen -> (Namen, Zeiten[n], Werte[Variable][n]) als numpy-Felder (leere Felder = NaN).

    Die Zeilen werden blockweise in numpy-Felder umgewandelt (8 Byte je Wert statt rund 32 als Python-Zahl in einer
    Liste) – auch große Tagesdateien passen so auf einem Raspberry Pi in den Speicher."""
    with open_log(path) as f:
        rd = csv.reader(f, delimiter=";")
        try:
            head = next(rd)
        except StopIteration:
            raise ValueError(tr("Die Datei ist leer.")) from None
        if len(head) < 2 or head[1].strip().lower() != "epoch":
            raise ValueError(tr("Unbekannter Aufbau (erwartet: Zeit;Epoch;Variablen …)"))
        names = head[2:]
        n = len(names)
        ts, ys, rows = [], [], []
        for row in rd:
            if len(row) >= 2 + n:
                rows.append(row)
                if len(rows) >= CHUNK:
                    t, y = _convert(rows, n)
                    ts.append(t)
                    ys.append(y)
                    rows = []
        if rows:
            t, y = _convert(rows, n)
            ts.append(t)
            ys.append(y)
    if not ts:
        return names, np.empty(0), np.empty((n, 0))
    return names, np.concatenate(ts), np.concatenate(ys, axis=1)


def join_logs(parts, gaps=True):
    """Mehrere gelesene Aufzeichnungen [(Namen, Zeiten, Werte)] zu einer zusammenfügen -> (Namen, Zeiten, Werte).

    gaps: an Lücken zwischen den Dateien (Abstand größer als das Zehnfache des üblichen Messabstands, mindestens
    1 s) eine Zeile ohne Werte einfügen, damit die Kurven dort unterbrochen sind."""
    parts = [p for p in parts if len(p[1])]
    if not parts:
        return [], np.empty(0), np.empty((0, 0))
    names = []
    for nm, _t, _y in parts:
        for n in nm:
            if n not in names:
                names.append(n)
    col = {n: i for i, n in enumerate(names)}
    # Dateien nach ihrem Beginn ordnen; Lücken-Zeilen gehören jeweils hinter das Ende einer Datei.
    parts = sorted(parts, key=lambda p: float(p[1][0]))
    ts_list, ys_list = [], []
    for k, (nm, t, y) in enumerate(parts):
        block = np.full((len(names), len(t)), np.nan)
        for j, n in enumerate(nm):
            block[col[n]] = y[j]
        ts_list.append(t)
        ys_list.append(block)
        if gaps and k + 1 < len(parts):
            nxt = float(parts[k + 1][1][0])
            dt = float(np.median(np.diff(t))) if len(t) > 1 else 1.0
            if nxt - float(t[-1]) > max(10 * dt, 1.0):
                ts_list.append(np.array([float(t[-1]) + min(0.001, (nxt - float(t[-1])) / 2)]))
                ys_list.append(np.full((len(names), 1), np.nan))
    t = np.concatenate(ts_list)
    y = np.concatenate(ys_list, axis=1)
    order = np.argsort(t, kind="mergesort")             # stabil: bei gleicher Zeit bleibt die Dateireihenfolge
    t, y = t[order], y[:, order]
    first = np.r_[True, np.diff(t) > 0]                 # erste Zeile je Zeitpunkt
    if first.all():
        return names, t, y
    # Doppelte Zeitpunkte (überlappende Dateien bzw. Dateien verschiedener Logger mit gleicher Zeit) zu einer Zeile
    # zusammenführen: je Spalte gilt der erste gültige Wert – so gehen Variablen, die nur in einer Datei stehen, nicht
    # verloren. Rückwärts zuweisen: bei mehrfachen Zielen gewinnt die letzte Zuweisung, also der erste Wert.
    g = np.cumsum(first) - 1
    out = np.full((len(names), int(g[-1]) + 1), np.nan)
    g_rev = g[::-1]
    for k in range(len(names)):
        row = y[k, ::-1]
        m = ~np.isnan(row)
        out[k, g_rev[m]] = row[m]
    return names, t[first], out


def read_and_join(paths, gaps=True):
    """Dateien lesen und zusammenfügen -> (Namen, Zeiten, Werte, Fehler [(Pfad, Text)])."""
    parts, errors = [], []
    for p in paths:
        try:
            parts.append(read_log(p))
        except Exception as e:
            errors.append((p, str(e)))
    names, t, y = join_logs(parts, gaps=gaps)
    return names, t, y, errors
