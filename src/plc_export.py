# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Export und Import von Tabellen (CSV oder Excel): Messwerte eines Zeitbereichs mit optionalem Downsampling
und die Variablenliste des Konfigurationsprogramms.

CSV: Semikolon als Trennzeichen, UTF-8 mit BOM (Excel erkennt so die Umlaute). Die exportierten Messwerte haben
denselben Aufbau wie die Aufzeichnung (Zeit;Epoch;Variablen ...) und lassen sich mit "CSV laden" wieder öffnen.
Excel (.xlsx) braucht das Paket openpyxl; die Zeit steht dort als echte Datums-/Zeitzelle.
"""
import csv
import math
import os
import warnings
from datetime import datetime

import numpy as np

from plc_i18n import N_, tr
from plc_util import fmt_csv

# Höchstzahl Zeilen eines Excel-Tabellenblatts (einschließlich Kopfzeile).
EXCEL_MAX_ROWS = 1048576
# Verfahren für das Downsampling: Schlüssel -> Anzeigetext.
DOWNSAMPLE_METHODS = {
    "mittel": N_("Mittelwert"),
    "min": N_("Minimum"),
    "max": N_("Maximum"),
    "erster": N_("Erster Wert"),
    "letzter": N_("Letzter Wert"),
}


def is_excel(path):
    """True, wenn der Dateiname auf eine Excel-Datei (.xlsx/.xlsm) endet – sonst wird CSV geschrieben bzw. gelesen."""
    return os.path.splitext(path)[1].lower() in (".xlsx", ".xlsm")


def _openpyxl():
    """openpyxl importieren; fehlt das Paket, eine verständliche Fehlermeldung statt ImportError."""
    try:
        import openpyxl
        return openpyxl
    except ImportError:
        raise RuntimeError(tr("Für Excel-Dateien wird das Paket openpyxl benötigt (pip install openpyxl)."))


# ---- Tabellen allgemein (Variablenliste) -------------------------------------------------------------------------
def write_table(path, header, rows, sheet="Tabelle"):
    """Kopfzeile und Zeilen als CSV (Semikolon) oder Excel-Datei schreiben."""
    if is_excel(path):
        wb = _openpyxl().Workbook()
        ws = wb.active
        ws.title = sheet[:31]
        ws.append(list(header))
        for row in rows:
            ws.append(list(row))
        for i, h in enumerate(header):                # Spaltenbreite grob an Kopf und Inhalt anpassen
            width = max([len(str(h))] + [len(str(r[i])) for r in rows if i < len(r) and r[i] is not None])
            ws.column_dimensions[ws.cell(1, i + 1).column_letter].width = min(max(width + 2, 8), 60)
        ws.freeze_panes = "A2"
        wb.save(path)
        return
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(header)
        for row in rows:
            w.writerow(["" if c is None else c for c in row])


def read_table(path):
    """CSV- oder Excel-Datei lesen -> (Kopfzeile, Zeilen). Leere Zeilen entfallen; Zellen sind Text (Excel: Werte)."""
    if is_excel(path):
        wb = _openpyxl().load_workbook(path, read_only=True, data_only=True)
        try:
            data = [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
        finally:
            wb.close()
    else:
        with open(path, newline="", encoding="utf-8-sig") as f:
            text = f.read()
        # Trennzeichen erkennen (Semikolon, Komma oder Tabulator; Standard Semikolon).
        try:
            delim = csv.Sniffer().sniff(text[:4096], delimiters=";,\t").delimiter
        except csv.Error:
            delim = ";"
        data = list(csv.reader(text.splitlines(), delimiter=delim))
    data = [r for r in data if any(c not in (None, "") for c in r)]
    if not data:
        return [], []
    header = ["" if c is None else str(c).strip() for c in data[0]]
    return header, data[1:]


# ---- Messwerte ---------------------------------------------------------------------------------------------------
def downsample(t, y, interval, method="mittel", dtypes=None):
    """Messwerte auf ein festes Zeitraster verdichten.

    t: Zeitstempel (aufsteigend, Sekunden), y: Werte (Variablen x Zeitpunkte), interval: Rasterbreite in Sekunden,
    method: Schlüssel aus DOWNSAMPLE_METHODS. Je Rasterintervall entsteht eine Zeile mit dem Beginn des Intervalls als
    Zeitstempel; fehlende Werte (NaN) werden übergangen. BOOL-Variablen (dtypes) bleiben 0/1: beim Mittelwert zählt
    das Maximum (1, wenn das Signal im Intervall an war). Rückgabe: (t_neu, y_neu)."""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float).reshape(-1, len(t))
    if len(t) == 0 or interval <= 0:
        return t, y
    start = math.floor(t[0] / interval) * interval
    # Nummer des Rasterintervalls jeder Messung; first/last = erster und letzter Index jedes belegten Intervalls.
    # reduceat fasst dann je Intervall alle Werte in einem Schritt zusammen (ohne Python-Schleife über die Zeilen).
    bucket = np.floor((t - start) / interval + 1e-9).astype(np.int64)
    first = np.flatnonzero(np.r_[True, bucket[1:] != bucket[:-1]])     # erster Index jedes belegten Intervalls
    last = np.r_[first[1:] - 1, len(t) - 1]
    t_new = start + bucket[first] * interval
    out = np.empty((y.shape[0], len(first)))
    with warnings.catch_warnings(), np.errstate(invalid="ignore", divide="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        for k in range(y.shape[0]):
            col = y[k]
            m = method
            if dtypes is not None and dtypes[k] == "BOOL" and m == "mittel":
                m = "max"
            if m == "mittel":
                valid = ~np.isnan(col)
                sums = np.add.reduceat(np.where(valid, col, 0.0), first)
                cnt = np.add.reduceat(valid.astype(float), first)
                out[k] = sums / np.where(cnt > 0, cnt, np.nan)
            elif m == "min":
                out[k] = np.fmin.reduceat(col, first)
            elif m == "max":
                out[k] = np.fmax.reduceat(col, first)
            elif m == "erster":
                out[k] = col[first]
            else:                                                   # "letzter"
                out[k] = col[last]
    return t_new, out


def stats(values):
    """Kennwerte einer Messreihe ohne fehlende Werte: (Minimum, Maximum, Mittelwert, Standardabweichung).

    Standardabweichung der Stichprobe (n − 1, wie STABW in Excel); bei weniger als zwei Werten 0. Ohne Werte: NaN."""
    v = np.asarray(values, dtype=float)
    v = v[~np.isnan(v)]
    if len(v) == 0:
        return (math.nan,) * 4
    return float(v.min()), float(v.max()), float(v.mean()), float(v.std(ddof=1)) if len(v) > 1 else 0.0


def write_values(path, t, names, dtypes, y):
    """Messwerte schreiben: CSV im Aufbau der Aufzeichnung (Zeit;Epoch;Variablen) oder Excel (.xlsx).

    Excel: Spalte A Datum/Uhrzeit (mit Millisekunden), B Epoch, dann die Variablen; fehlende Werte bleiben leer."""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float).reshape(len(names), len(t))
    if is_excel(path):
        if len(t) + 1 > EXCEL_MAX_ROWS:
            raise ValueError(tr("Zu viele Zeilen für Excel ({0}; höchstens {1}). Bitte Downsampling verwenden oder "
                                "als CSV speichern.").format(len(t), EXCEL_MAX_ROWS - 1))
        opx = _openpyxl()
        from openpyxl.cell import WriteOnlyCell
        wb = opx.Workbook(write_only=True)
        ws = wb.create_sheet(tr("Messwerte"))
        ws.freeze_panes = "C2"
        ws.column_dimensions["A"].width = 24
        ws.column_dimensions["B"].width = 16
        ws.append(["Zeit", "Epoch"] + list(names))
        ints = [d not in ("REAL", "LREAL") for d in dtypes]
        for j in range(len(t)):
            ms = int(round(t[j] * 1000))
            cell = WriteOnlyCell(ws, value=datetime.fromtimestamp(ms / 1000))
            cell.number_format = "yyyy-mm-dd hh:mm:ss.000"
            row = [cell, ms / 1000]
            for k in range(len(names)):
                v = y[k, j]
                row.append(None if math.isnan(v) else (int(v) if ints[k] else float(v)))
            ws.append(row)
        wb.save(path)
        return
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Zeit", "Epoch"] + list(names))
        for j in range(len(t)):
            ms = int(round(t[j] * 1000))
            stamp = datetime.fromtimestamp(ms // 1000).strftime("%Y-%m-%d %H:%M:%S") + f".{ms % 1000:03d}"
            w.writerow([stamp, f"{ms / 1000:.3f}"] + [fmt_csv(float(y[k, j]), dtypes[k]) for k in range(len(names))])


# ---- Dialog „Werte exportieren“ (Logger) -------------------------------------------------------------------------
def export_dialog_class():
    """Dialogklasse erst bei Bedarf bauen (das Modul wird auch ohne Oberfläche verwendet)."""
    from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                                   QFormLayout, QGroupBox, QHBoxLayout, QLabel, QRadioButton, QVBoxLayout)

    class ExportDialog(QDialog):
        """Auswahl für den Export: Zeitbereich, Variablen, Downsampling. Ergebnis in self.result (dict) bei OK.

        ranges: Liste (Schlüssel, Text, (t0, t1) oder None = nicht verfügbar); count(t0, t1): (Zahl der Messpunkte,
        erster, letzter Zeitpunkt im Bereich)."""

        def __init__(self, parent, ranges, count, n_vars, n_visible):
            """Dialog aufbauen: Auswahl des Zeitbereichs, „nur eingeblendete Variablen“, Downsampling (Raster und
            Verfahren) und die voraussichtliche Zeilenzahl.
            """
            super().__init__(parent)
            self.setWindowTitle(tr("Werte exportieren"))
            self.ranges, self.count = ranges, count
            self.result = None
            lay = QVBoxLayout(self)
            box = QGroupBox(tr("Zeitbereich"))
            bl = QVBoxLayout(box)
            self.grp = QButtonGroup(self)
            for k, (key, text, rng) in enumerate(ranges):
                rb = QRadioButton(text)
                rb.setEnabled(rng is not None)
                self.grp.addButton(rb, k)
                bl.addWidget(rb)
            first = next((k for k, r in enumerate(ranges) if r[2] is not None), 0)
            self.grp.button(first).setChecked(True)
            self.grp.idToggled.connect(lambda *_: self._update())
            lay.addWidget(box)

            self.chk_visible = QCheckBox(tr("Nur eingeblendete Variablen ({0} von {1})").format(n_visible, n_vars))
            self.chk_visible.setEnabled(n_visible < n_vars)
            lay.addWidget(self.chk_visible)

            self.chk_ds = QCheckBox(tr("Downsampling (Werte auf ein Zeitraster verdichten)"))
            self.sp_int = QDoubleSpinBox()
            self.sp_int.setRange(0.001, 86400.0)
            self.sp_int.setDecimals(3)
            self.sp_int.setValue(1.0)
            self.sp_int.setSuffix(" s")
            self.cb_method = QComboBox()
            for key, text in DOWNSAMPLE_METHODS.items():
                self.cb_method.addItem(tr(text), key)
            form = QFormLayout()
            form.addRow(tr("Raster:"), self.sp_int)
            form.addRow(tr("Verfahren:"), self.cb_method)
            ds = QGroupBox()
            ds.setLayout(form)
            ds.setEnabled(False)
            self.chk_ds.toggled.connect(ds.setEnabled)
            for w in (self.chk_ds, self.sp_int):
                (w.toggled if w is self.chk_ds else w.valueChanged).connect(lambda *_: self._update())
            lay.addWidget(self.chk_ds)
            lay.addWidget(ds)
            hint = QLabel(tr("Zeitstempel = Beginn des Intervalls; BOOL-Variablen bleiben 0/1 (beim Mittelwert: 1, wenn "
                             "das Signal im Intervall an war)."))
            hint.setWordWrap(True)
            hint.setObjectName("muted")
            lay.addWidget(hint)
            self.lbl_rows = QLabel()
            lay.addWidget(self.lbl_rows)

            bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            bb.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Speichern …"))
            bb.accepted.connect(self._ok)
            bb.rejected.connect(self.reject)
            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(bb)
            lay.addLayout(row)
            self._update()

        def _range(self):
            """Gewählter Zeitbereich (t0, t1) oder None."""
            return self.ranges[self.grp.checkedId()][2]

        def _update(self):
            """Zeilenzahl für die aktuelle Auswahl anzeigen (mit Downsampling: höchstens eine Zeile je Rasterintervall).
            """
            rng = self._range()
            if rng is None:
                self.lbl_rows.setText("")
                return
            n, first, last = self.count(*rng)
            if self.chk_ds.isChecked() and n:
                iv = self.sp_int.value()                 # Rasterintervalle zwischen erstem und letztem Messpunkt
                n = min(n, int(math.floor(last / iv + 1e-9) - math.floor(first / iv + 1e-9)) + 1)
                self.lbl_rows.setText(tr("Höchstens {0} Zeilen").format(n))
            else:
                self.lbl_rows.setText(tr("{0} Zeilen").format(n))

        def _ok(self):
            """Auswahl in ``self.result`` übernehmen und den Dialog schließen."""
            self.result = {"range": self._range(), "key": self.ranges[self.grp.checkedId()][0],
                           "visible_only": self.chk_visible.isChecked() and self.chk_visible.isEnabled(),
                           "interval": self.sp_int.value() if self.chk_ds.isChecked() else 0.0,
                           "method": self.cb_method.currentData()}
            self.accept()

    return ExportDialog
