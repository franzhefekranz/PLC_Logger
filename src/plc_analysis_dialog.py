# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Dialoge des Logger-Menüs „Analyse“: XY-Diagramm und Frequenzanalyse (FFT).

Beide arbeiten auf einem wählbaren Zeitbereich der angezeigten Daten (zwischen den Linealen, sichtbarer Ausschnitt
oder alles) und bleiben neben dem Hauptfenster offen; „Aktualisieren“ holt die Daten neu (z. B. während einer
laufenden Aufzeichnung). Rechenteil: plc_analysis.py.
"""
import csv
import os

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSplitter, QVBoxLayout,
                               QWidget)
import pyqtgraph as pg  # nach PySide6 importieren

from plc_analysis import WINDOWS, correlation, fmt_freq, spectrum, xy_pairs
from plc_i18n import tr


class _AnalysisBase(QDialog):
    """Gemeinsamer Rahmen: Zeitbereich, Diagramm, Infozeile, Knöpfe."""

    def __init__(self, parent, title, variables, data_fn, ranges, base_dir):
        """variables: [Variable]; data_fn(t0, t1) -> (Zeiten, {Name: Werte}); ranges: [(Text, t0, t1)]."""
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.resize(1000, 640)
        self.vars = [v for v in variables]
        self.data_fn = data_fn
        self.ranges = list(ranges)
        self.base_dir = base_dir
        self.cb_range = QComboBox()
        for text, a, b in self.ranges:
            self.cb_range.addItem(text, (a, b))
        self.cb_range.currentIndexChanged.connect(lambda _i: self.recompute())
        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.plot.addLegend(offset=(10, 10))
        self.lbl_info = QLabel("")
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.form = QFormLayout()
        self.form.addRow(tr("Zeitbereich:"), self.cb_range)
        btn_upd = QPushButton(tr("Aktualisieren"))
        btn_upd.setToolTip(tr("Daten neu holen (z. B. während einer laufenden Aufzeichnung)"))
        btn_upd.clicked.connect(self.recompute)
        btn_png = QPushButton(tr("Bild speichern …"))
        btn_png.clicked.connect(self.save_image)
        btn_csv = QPushButton(tr("Werte speichern (CSV) …"))
        btn_csv.clicked.connect(self.save_csv)
        btn_close = QPushButton(tr("Schließen"))
        btn_close.clicked.connect(self.close)
        self.left = QVBoxLayout()
        self.left.addLayout(self.form)
        left_w = QWidget()
        left_w.setLayout(self.left)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.plot, 1)
        rl.addWidget(self.lbl_info)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left_w)
        split.addWidget(right)
        split.setStretchFactor(1, 3)
        buttons = QHBoxLayout()
        for b in (btn_upd, btn_png, btn_csv):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(btn_close)
        lay = QVBoxLayout(self)
        lay.addWidget(split, 1)
        lay.addLayout(buttons)
        self.export_rows = ([], [])                       # (Kopfzeile, Zeilen) für „Werte speichern“

    def current_range(self):
        return self.cb_range.currentData() or (self.ranges[-1][1], self.ranges[-1][2])

    def var(self, name):
        return next((v for v in self.vars if v.name == name), None)

    def fetch(self, names):
        a, b = self.current_range()
        return self.data_fn(a, b, names)

    def save_image(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("Bild speichern"), os.path.join(self.base_dir, "analyse.png"),
                                              tr("PNG-Bild (*.png)"))
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        pix = self.plot.grab()
        if not pix.save(path, "PNG"):
            QMessageBox.warning(self, tr("Bild speichern"), tr("Die Datei konnte nicht geschrieben werden."))

    def save_csv(self):
        head, rows = self.export_rows
        if not rows:
            QMessageBox.information(self, tr("Werte speichern"), tr("Es sind keine Werte vorhanden."))
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("Werte speichern"), os.path.join(self.base_dir, "analyse.csv"),
                                              tr("CSV-Datei (*.csv)"))
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(head)
                for r in rows:
                    w.writerow([f"{x:.9g}" if isinstance(x, float) else x for x in r])
        except OSError as e:
            QMessageBox.warning(self, tr("Werte speichern"), str(e))

    def recompute(self):
        raise NotImplementedError


# ---------------------------------------------------------------------------------------------------------- XY
class XYDialog(_AnalysisBase):
    """Eine oder mehrere Variablen (Y) über einer anderen Variable (X) – z. B. Druck über Hub, Kennlinien."""

    def __init__(self, parent, variables, data_fn, ranges, base_dir, x_name="", y_names=()):
        super().__init__(parent, tr("XY-Diagramm"), variables, data_fn, ranges, base_dir)
        names = [v.name for v in self.vars]
        self.cb_x = QComboBox()
        self.cb_x.addItems(names)
        if x_name in names:
            self.cb_x.setCurrentText(x_name)
        self.cb_x.currentIndexChanged.connect(lambda _i: self.recompute())
        self.lst_y = QListWidget()
        for n in names:
            it = QListWidgetItem(n)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if n in y_names else Qt.CheckState.Unchecked)
            v = self.var(n)
            if v is not None:
                it.setForeground(QColor(v.color))
            self.lst_y.addItem(it)
        if not any(n in y_names for n in names) and len(names) > 1:
            self.lst_y.item(1).setCheckState(Qt.CheckState.Checked)
        self.lst_y.itemChanged.connect(lambda _it: self.recompute())
        self.cb_style = QComboBox()
        for key, text in (("punkte", tr("Punkte")), ("linie", tr("Linie (zeitliche Reihenfolge)")),
                          ("beides", tr("Linie und Punkte"))):
            self.cb_style.addItem(text, key)
        self.cb_style.currentIndexChanged.connect(lambda _i: self.recompute())
        self.chk_fit = QCheckBox(tr("Ausgleichsgerade und Korrelation"))
        self.chk_fit.toggled.connect(lambda _on: self.recompute())
        self.form.addRow(tr("X-Achse:"), self.cb_x)
        self.form.addRow(tr("Darstellung:"), self.cb_style)
        self.form.addRow("", self.chk_fit)
        self.left.addWidget(QLabel(tr("<b>Y-Achse</b> (eine oder mehrere Variablen)")))
        self.left.addWidget(self.lst_y, 1)
        self.recompute()

    def y_names(self):
        return [self.lst_y.item(i).text() for i in range(self.lst_y.count())
                if self.lst_y.item(i).checkState() == Qt.CheckState.Checked]

    def recompute(self):
        self.plot.clear()
        xn, yns = self.cb_x.currentText(), self.y_names()
        if not xn or not yns:
            self.lbl_info.setText(tr("Bitte eine X-Variable und mindestens eine Y-Variable wählen."))
            return
        t, data = self.fetch([xn] + yns)
        if xn not in data or len(t) == 0:
            self.lbl_info.setText(tr("Im gewählten Zeitbereich liegen keine Messwerte."))
            return
        style = self.cb_style.currentData()
        self.plot.setLabel("bottom", xn)
        self.plot.setLabel("left", ", ".join(yns))
        info, head, cols = [], ["Zeit", xn], [t, data[xn]]
        for yn in yns:
            if yn not in data:
                continue
            v = self.var(yn)
            col = v.color if v else "#4fc3f7"
            x, y = xy_pairs(data[xn], data[yn])
            pen = pg.mkPen(col, width=1.5) if style in ("linie", "beides") else None
            sym = "o" if style in ("punkte", "beides") else None
            self.plot.plot(x, y, pen=pen, symbol=sym, symbolSize=4, symbolPen=None,
                           symbolBrush=pg.mkBrush(col), name=yn)
            head.append(yn)
            cols.append(data[yn])
            if self.chk_fit.isChecked():
                c = correlation(x, y)
                if c is not None:
                    r, a, b = c
                    xs = np.array([x.min(), x.max()])
                    self.plot.plot(xs, a * xs + b, pen=pg.mkPen(col, width=1, style=Qt.PenStyle.DashLine))
                    info.append(tr("{0}: r = {1:.4f}, Gerade y = {2:.5g}·x {3:+.5g}").format(yn, r, a, b))
        n = len(t)
        self.lbl_info.setText(tr("{0} Messpunkte im Zeitbereich.").format(n) + ("  " + "  ·  ".join(info) if info else ""))
        self.export_rows = (head, [[float(c[i]) for c in cols] for i in range(n)])


# ---------------------------------------------------------------------------------------------------------- FFT
class FftDialog(_AnalysisBase):
    """Frequenzanalyse einer Variable: Amplitudenspektrum mit den stärksten Frequenzen."""

    def __init__(self, parent, variables, data_fn, ranges, base_dir, name=""):
        super().__init__(parent, tr("Frequenzanalyse (FFT)"), variables, data_fn, ranges, base_dir)
        names = [v.name for v in self.vars if v.dtype != "BOOL"] or [v.name for v in self.vars]
        self.cb_var = QComboBox()
        self.cb_var.addItems(names)
        if name in names:
            self.cb_var.setCurrentText(name)
        self.cb_win = QComboBox()
        for key, text in WINDOWS.items():
            self.cb_win.addItem(tr(text), key)
        self.cb_trend = QComboBox()
        for key, text in (("mean", tr("Mittelwert abziehen")), ("linear", tr("Linearen Trend abziehen")),
                          ("", tr("nichts abziehen"))):
            self.cb_trend.addItem(text, key)
        self.cb_x = QComboBox()
        self.cb_x.addItem(tr("Frequenz [Hz]"), "f")
        self.cb_x.addItem(tr("Periodendauer [s]"), "T")
        self.chk_log = QCheckBox(tr("Amplitude logarithmisch"))
        for w in (self.cb_var, self.cb_win, self.cb_trend, self.cb_x):
            w.currentIndexChanged.connect(lambda _i: self.recompute())
        self.chk_log.toggled.connect(lambda _on: self.recompute())
        self.form.addRow(tr("Variable:"), self.cb_var)
        self.form.addRow(tr("Fenster:"), self.cb_win)
        self.form.addRow(tr("Vorbehandlung:"), self.cb_trend)
        self.form.addRow(tr("X-Achse:"), self.cb_x)
        self.form.addRow("", self.chk_log)
        hint = QLabel(tr("Die Werte werden auf gleichmäßige Abstände umgerechnet. Höchste Frequenz = halbe "
                         "Abtastrate; feinere Auflösung durch einen längeren Zeitbereich."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#777")
        self.left.addWidget(hint)
        self.left.addStretch(1)
        self.recompute()

    def recompute(self):
        self.plot.clear()
        name = self.cb_var.currentText()
        if not name:
            return
        t, data = self.fetch([name])
        if name not in data or len(t) < 8:
            self.lbl_info.setText(tr("Zu wenige Messwerte im gewählten Zeitbereich (mindestens 8)."))
            return
        try:
            s = spectrum(t, data[name], self.cb_win.currentData(), self.cb_trend.currentData())
        except ValueError as e:
            self.lbl_info.setText(str(e))
            return
        f, amp = s["f"][1:], s["amp"][1:]                     # ohne Gleichanteil
        v = self.var(name)
        col = v.color if v else "#4fc3f7"
        period = self.cb_x.currentData() == "T"
        x = 1.0 / f if period else f
        self.plot.setLogMode(x=period, y=self.chk_log.isChecked())
        self.plot.setLabel("bottom", tr("Periodendauer") if period else tr("Frequenz"), units="s" if period else "Hz")
        self.plot.setLabel("left", tr("Amplitude"))
        y = np.maximum(amp, 1e-12) if self.chk_log.isChecked() else amp
        self.plot.plot(x, y, pen=pg.mkPen(col, width=1.5), name=name)
        peaks = s["peaks"]
        if peaks:
            px = [1.0 / p[0] if period else p[0] for p in peaks]
            self.plot.plot(px, [max(p[1], 1e-12) for p in peaks], pen=None, symbol="t", symbolSize=10,
                           symbolBrush=pg.mkBrush("#ffd400"))
        lines = [tr("{0} Werte, Abtastrate {1:.4g} Hz (Abstand {2:.4g} s), Auflösung {3:.4g} Hz, "
                    "höchste Frequenz {4:.4g} Hz, Effektivwert {5:.4g}").format(
            s["n"], s["fs"], s["dt"], s["df"], s["fs"] / 2, s["rms"])]
        if peaks:
            lines.append(tr("Stärkste Frequenzen: ") + "; ".join(
                f"{fmt_freq(fp)} – {ap:.4g}" for fp, ap in peaks))
        self.lbl_info.setText("<br>".join(lines))
        self.export_rows = (["Frequenz_Hz", "Periodendauer_s", "Amplitude"],
                            [[float(fi), float(1.0 / fi), float(ai)] for fi, ai in zip(f, amp)])
