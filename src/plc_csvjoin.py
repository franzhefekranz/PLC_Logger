# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Aufzeichnungen (CSV oder archivierte ZIP-Dateien) lesen und aneinanderhängen – ohne Oberfläche.

Aufbau einer Aufzeichnung: Kopfzeile ``Zeit;Epoch;<Variablen …>``, danach eine Zeile je Messzeitpunkt (Semikolon,
UTF-8). Beim Zusammenfügen mehrerer Dateien

* werden die Spalten über den Variablennamen zugeordnet (Reihenfolge der ersten Datei, neue Namen hinten angehängt;
  fehlt eine Variable in einer Datei, bleibt sie dort leer),
* werden alle Zeilen nach der Zeit sortiert (auch wenn die Dateien in beliebiger Reihenfolge gewählt wurden),
* werden doppelte Zeitpunkte (überlappende Dateien) nur einmal übernommen,
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


def read_log(path):
    """Aufzeichnung lesen -> (Namen, Zeiten[n], Werte[Variable][n]) als numpy-Felder (leere Felder = NaN)."""
    with open_log(path) as f:
        rd = csv.reader(f, delimiter=";")
        try:
            head = next(rd)
        except StopIteration:
            raise ValueError(tr("Die Datei ist leer.")) from None
        if len(head) < 2 or head[1].strip().lower() != "epoch":
            raise ValueError(tr("Unbekannter Aufbau (erwartet: Zeit;Epoch;Variablen …)"))
        names = head[2:]
        t, cols = [], [[] for _ in names]
        for row in rd:
            if len(row) < 2 + len(names):
                continue
            try:
                ts = float(row[1])
            except ValueError:
                continue
            t.append(ts)
            for k in range(len(names)):
                s = row[2 + k].strip().replace(",", ".")
                try:
                    cols[k].append(float(s) if s else np.nan)
                except ValueError:
                    cols[k].append(np.nan)
    return names, np.asarray(t, dtype=float), np.asarray(cols, dtype=float).reshape(len(names), len(t))


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
    keep = np.ones(len(t), dtype=bool)
    keep[1:] = np.diff(t) > 0                            # doppelte Zeitpunkte: den ersten behalten
    return names, t[keep], y[:, keep]


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
