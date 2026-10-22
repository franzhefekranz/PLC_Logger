# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Dialoge zur PID-Regler-Optimierung.

* ``PidSetupDialog`` (Konfigurationsprogramm): legt für ein Diagramm fest, welche Variablen Soll-, Ist- und Stellwert
  sind, sowie Reglertyp und gewünschtes Regelverhalten.
* ``PidTuneDialog`` (Logger): bestimmt aus einem Zeitbereich der Aufzeichnung das Streckenmodell, berechnet die
  Reglerparameter nach mehreren Einstellregeln und zeigt Modellgüte und simulierte Sprungantworten
  (Rechenteil: plc_pid.py).
"""
import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from plc_pid import (BEHAVIOURS, CONTROLLER_TYPES, PLC_HINT, PidError, assess, format_params, guess_roles,
                       identify, simulate_loop, tune)
from plc_i18n import tr

NONE = tr("(keiner)")


def _fill_combo(cb, names, current, allow_none=False):
    """Auswahlliste mit Variablennamen füllen und ``current`` wählen; optional Eintrag „(keiner)“.

    Ist ``current`` nicht (mehr) vorhanden, z. B. nach dem Umbenennen einer Variable, bleibt er als „(unbekannt)“
    sichtbar, statt still auf eine andere Variable zu springen.
    """
    cb.clear()
    if allow_none:
        cb.addItem(NONE, "")
    for n in names:
        cb.addItem(n, n)
    if current and current not in names:                 # z. B. umbenannte Variable: Eintrag sichtbar lassen
        cb.addItem(tr("{0} (unbekannt)").format(current), current)
    i = cb.findData(current)
    cb.setCurrentIndex(i if i >= 0 else 0)


# ---------------------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------------------
class PidSetupDialog(QDialog):
    """Soll-/Ist-/Stellwert, Reglertyp und Regelverhalten eines Diagramms festlegen (ändert ``chart`` bei OK)."""

    def __init__(self, parent, chart, chart_names, all_names):
        """Auswahl von Soll-, Ist- und Stellwert (Vorschlag aus den Variablennamen, siehe ``guess_roles``), Reglertyp
        und Regelverhalten.
        """
        super().__init__(parent)
        self.chart = chart
        self.setWindowTitle(tr("PID-Optimierung – {0}").format(chart.name))
        # Variablen des Diagramms zuerst, danach alle übrigen.
        names = list(chart_names) + [n for n in all_names if n not in chart_names]
        sw, iw, stw = chart.pid_sw, chart.pid_iw, chart.pid_stw
        if not (iw or stw):
            sw, iw, stw = guess_roles(chart_names or all_names)
        self.cb_sw, self.cb_iw, self.cb_stw = QComboBox(), QComboBox(), QComboBox()
        _fill_combo(self.cb_sw, names, sw, allow_none=True)
        _fill_combo(self.cb_iw, names, iw)
        _fill_combo(self.cb_stw, names, stw)
        self.cb_typ = QComboBox()
        self.cb_typ.addItems(CONTROLLER_TYPES)
        self.cb_typ.setCurrentText(chart.pid_typ)
        self.cb_beh = QComboBox()
        for k, text in BEHAVIOURS.items():
            self.cb_beh.addItem(text, k)
        self.cb_beh.setCurrentIndex(max(self.cb_beh.findData(chart.pid_verhalten), 0))
        form = QFormLayout()
        form.addRow(tr("Sollwert:"), self.cb_sw)
        form.addRow(tr("Istwert (Regelgröße):"), self.cb_iw)
        form.addRow(tr("Stellwert (Reglerausgang):"), self.cb_stw)
        form.addRow(tr("Reglertyp:"), self.cb_typ)
        form.addRow(tr("Regelverhalten:"), self.cb_beh)
        info = QLabel(tr("Im Logger öffnet <b>Analyse › PID-Optimierung</b> (oder Rechtsklick ins Diagramm) die "
                      "Berechnung. Sie bestimmt aus einem Zeitbereich der Aufzeichnung das Streckenmodell und daraus "
                      "die Reglerparameter. Der Bereich muss eine deutliche Änderung des Stellwerts enthalten "
                      "(Sollwertsprung oder Stellwertsprung im Handbetrieb). Der Sollwert dient nur der Anzeige."))
        info.setWordWrap(True)
        info.setStyleSheet("color:#555")
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept_checked)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(info)
        lay.addWidget(bb)
        self.resize(520, 300)

    def accept_checked(self):
        """OK: Istwert und Stellwert müssen gewählt und verschieden sein; dann die Auswahl ins Diagramm übernehmen."""
        iw, stw = self.cb_iw.currentData(), self.cb_stw.currentData()
        if not iw or not stw or iw == stw:
            QMessageBox.warning(self, tr("PID-Optimierung"), tr("Bitte Istwert und Stellwert (zwei verschiedene "
                                "Variablen) auswählen."))
            return
        c = self.chart
        c.pid_sw, c.pid_iw, c.pid_stw = self.cb_sw.currentData() or "", iw, stw
        c.pid_typ, c.pid_verhalten = self.cb_typ.currentText(), self.cb_beh.currentData()
        self.accept()


# ---------------------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------------------
COLS = [tr("Einstellregel"), "Kp", "Ti [s]", "Td [s]", "Ki [1/s]", "Kd [s]", tr("Überschwingen"), tr("Ausregelzeit"), tr("Hinweis")]


def _num(v, unit=""):
    """Zahl für die Ergebnistabelle (4 signifikante Stellen, optional Einheit); NaN = „—“, unendlich = „∞“."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if isinstance(v, float) and math.isinf(v):
        return "∞"
    return f"{v:.4g}{unit}"


class PidTuneDialog(QDialog):
    """Modell bestimmen, Parameter berechnen, Ergebnisse anzeigen.

    chart: Diagramm (Chart) mit den PID-Einstellungen; names: alle Variablennamen; get_data(t0, t1, names) ->
    (Zeiten, {Name: Werte}); ranges: [(Bezeichnung, t0, t1)] wählbarer Zeitbereiche (der erste ist voreingestellt)."""

    def __init__(self, parent, chart, names, get_data, ranges):
        """Dialog aufbauen: oben Auswahl (Variablen, Zeitbereich, Reglertyp, Verhalten), links Modell und
        Ergebnistabelle, rechts drei Diagramme (Messung/Modell, Stellwert, simulierter Sollwertsprung).
        """
        super().__init__(parent)
        import pyqtgraph as pg                       # erst hier (das Konfigurationsprogramm braucht es nicht)
        self.pg = pg
        self.chart, self.get_data, self.ranges = chart, get_data, ranges
        self.model, self.tunings, self.t0 = None, [], 0.0
        self.setWindowTitle(tr("PID-Regler-Optimierung – {0}").format(chart.name))
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.resize(1250, 800)

        # Einstellungen
        self.cb_sw, self.cb_iw, self.cb_stw = QComboBox(), QComboBox(), QComboBox()
        _fill_combo(self.cb_sw, names, chart.pid_sw, allow_none=True)
        _fill_combo(self.cb_iw, names, chart.pid_iw)
        _fill_combo(self.cb_stw, names, chart.pid_stw)
        self.cb_range = QComboBox()
        for label, t0, t1 in ranges:
            self.cb_range.addItem("{0} ({1:.0f} s)".format(label, t1 - t0), (t0, t1))
        self.cb_typ = QComboBox()
        self.cb_typ.addItems(CONTROLLER_TYPES)
        self.cb_typ.setCurrentText(chart.pid_typ)
        self.cb_beh = QComboBox()
        for k, text in BEHAVIOURS.items():
            self.cb_beh.addItem(text, k)
        self.cb_beh.setCurrentIndex(max(self.cb_beh.findData(chart.pid_verhalten), 0))
        btn_calc = QPushButton(tr("Strecke bestimmen und berechnen"))
        btn_calc.setDefault(True)
        btn_calc.clicked.connect(self.calculate)
        self.cb_typ.currentIndexChanged.connect(lambda _i: self.retune())
        self.cb_beh.currentIndexChanged.connect(lambda _i: self.retune())

        f1, f2 = QFormLayout(), QFormLayout()
        f1.addRow(tr("Sollwert:"), self.cb_sw)
        f1.addRow(tr("Istwert:"), self.cb_iw)
        f1.addRow(tr("Stellwert:"), self.cb_stw)
        f2.addRow(tr("Zeitbereich:"), self.cb_range)
        f2.addRow(tr("Reglertyp:"), self.cb_typ)
        f2.addRow(tr("Regelverhalten:"), self.cb_beh)
        top = QHBoxLayout()
        top.addLayout(f1, 1)
        top.addSpacing(20)
        top.addLayout(f2, 1)
        top.addSpacing(20)
        top.addWidget(btn_calc, 0, Qt.AlignmentFlag.AlignBottom)

        # Ergebnis: Modell, Hinweise, Tabelle
        self.lbl_model = QLabel(tr("Zeitbereich wählen und „Strecke bestimmen und berechnen“ klicken."))
        self.lbl_model.setWordWrap(True)
        self.lbl_model.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_warn = QLabel("")
        self.lbl_warn.setWordWrap(True)
        self.lbl_warn.setStyleSheet("color:#b9770e")
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hh = self.table.horizontalHeader()
        for c in range(len(COLS)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(len(COLS) - 1, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.draw_loop)
        hint = QLabel(PLC_HINT)
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#555")
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.lbl_model)
        ll.addWidget(self.lbl_warn)
        ll.addWidget(self.table, 1)
        ll.addWidget(hint)

        # Diagramme: Messung/Modell und simulierter Regelkreis
        self.plot_fit = pg.PlotWidget(title=tr("Messung und Streckenmodell"))
        self.plot_fit.showGrid(x=True, y=True, alpha=0.3)
        self.plot_fit.addLegend(offset=(10, 10))
        self.plot_fit.setLabel("bottom", tr("Zeit"), "s")
        self.plot_u = pg.PlotWidget(title=tr("Stellwert"))
        self.plot_u.showGrid(x=True, y=True, alpha=0.3)
        self.plot_u.setXLink(self.plot_fit)
        self.plot_u.setLabel("bottom", tr("Zeit"), "s")
        self.plot_loop = pg.PlotWidget(title=tr("Simulierter Sollwertsprung (Modell + Regler)"))
        self.plot_loop.showGrid(x=True, y=True, alpha=0.3)
        self.plot_loop.addLegend(offset=(10, 10))
        self.plot_loop.setLabel("bottom", tr("Zeit"), "s")
        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self.plot_fit)
        right.addWidget(self.plot_u)
        right.addWidget(self.plot_loop)
        right.setSizes([330, 160, 330])
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([620, 630])

        btns = QHBoxLayout()
        btn_copy = QPushButton(tr("Ergebnis kopieren"))
        btn_copy.setToolTip(tr("Modell und alle Parameter als Text in die Zwischenablage"))
        btn_copy.clicked.connect(self.copy)
        btn_close = QPushButton(tr("Schließen"))
        btn_close.clicked.connect(self.close)
        btns.addStretch(1)
        btns.addWidget(btn_copy)
        btns.addWidget(btn_close)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(split, 1)
        lay.addLayout(btns)

    # ------------------------------------------------------------------ Berechnung
    def calculate(self):
        """Daten des Zeitbereichs holen und das Streckenmodell bestimmen (``plc_pid.identify``); Fehler erscheinen rot
        im Dialog.
        """
        iw, stw, sw = self.cb_iw.currentData(), self.cb_stw.currentData(), self.cb_sw.currentData()
        if not iw or not stw or iw == stw:
            QMessageBox.warning(self, tr("PID-Optimierung"), tr("Bitte Istwert und Stellwert auswählen."))
            return
        t0, t1 = self.cb_range.currentData() or (0, 0)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            wanted = [n for n in (iw, stw, sw) if n]
            t, data = self.get_data(t0, t1, wanted)
            missing = [n for n in wanted if n not in data]
            if missing:
                raise PidError(tr("Unbekannte Variable(n): ") + ", ".join(missing))
            self.t0 = float(t[0]) if len(t) else 0.0
            self.raw = (t, data, sw)
            self.model = identify(t, data[stw], data[iw])
        except Exception as e:                       # PidError oder unerwarteter Rechenfehler
            QApplication.restoreOverrideCursor()
            self.model, self.tunings = None, []
            self.table.setRowCount(0)
            self.lbl_model.setText(f"<span style='color:#c0392b'>✗ {e}</span>".replace("\n", "<br>"))
            self.lbl_warn.setText("")
            for p in (self.plot_fit, self.plot_u, self.plot_loop):
                p.clear()
            return
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
        m = self.model
        self.lbl_model.setText(tr("<b>Streckenmodell:</b> {0}<br>Auswertung mit {1} Punkten im Abstand {2:.3g} s.").format(m.describe(), len(m.t), m.dt))
        self.lbl_warn.setText("<br>".join("⚠ " + w for w in m.warnings))
        self.draw_fit()
        self.retune()

    def retune(self):
        """Reglerparameter für das bestimmte Modell nach allen Regeln berechnen, simulieren und in die Tabelle
        schreiben.

        Wird auch beim Wechsel von Reglertyp oder Verhalten aufgerufen – das Modell muss dafür nicht neu bestimmt
        werden. Die erste Zeile ist die empfohlene Regel (fett), instabile Ergebnisse sind rot.
        """
        if self.model is None:
            return
        typ, beh = self.cb_typ.currentText(), self.cb_beh.currentData()
        self.tunings = [assess(self.model, tn) for tn in tune(self.model, typ, beh)]
        self.table.setRowCount(len(self.tunings))
        for r, tn in enumerate(self.tunings):
            vals = [tn.method + ("  (empfohlen)" if r == 0 else ""), _num(tn.kp), _num(tn.ti), _num(tn.td),
                    _num(tn.ki), _num(tn.kd), _num(tn.overshoot, " %"), _num(tn.settling, " s"),
                    "; ".join(tr(n) for n in tn.note.split("; ") if n)]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c > 0 and c < 8:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if r == 0:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                if "instabil" in tn.note:
                    it.setForeground(QBrush(QColor("#c0392b")))
                self.table.setItem(r, c, it)
        self.table.selectRow(0)
        self.draw_loop()

    # ------------------------------------------------------------------ Anzeige
    def draw_fit(self):
        """Messung (Istwert, ggf. Sollwert) und simulierte Modellantwort übereinander zeichnen, darunter den Stellwert.
        """
        pg, m = self.pg, self.model
        self.plot_fit.clear()
        self.plot_u.clear()
        tt = m.t - m.t[0]
        t, data, sw = self.raw
        if sw and sw in data:
            self.plot_fit.plot(t - self.t0, data[sw], pen=pg.mkPen("#2e86de", width=1, style=Qt.PenStyle.DashLine),
                               name=tr("Sollwert"))
        self.plot_fit.plot(tt, m.y, pen=pg.mkPen("#9aa5b1", width=1), name="Istwert (Messung)")
        self.plot_fit.plot(tt, m.y_model, pen=pg.mkPen("#e67e22", width=2), name=tr("Modell"))
        self.plot_u.plot(tt, m.u, pen=pg.mkPen("#27ae60", width=2))

    def draw_loop(self):
        """Simulierten Sollwertsprung zeichnen: die gewählte Regel rot und dick, alle übrigen stabilen Regeln grau."""
        pg = self.pg
        self.plot_loop.clear()
        if self.model is None or not self.tunings:
            return
        rows = {i.row() for i in self.table.selectedItems()}
        sel = min(rows) if rows else 0
        first = True
        for r, tn in enumerate(self.tunings):
            if "instabil" in tn.note:
                continue
            t, sp, y, _u = simulate_loop(self.model, tn)
            if first:
                self.plot_loop.plot(t, sp, pen=pg.mkPen("#2e86de", width=1, style=Qt.PenStyle.DashLine),
                                    name=tr("Sollwert"))
                first = False
            if r == sel:
                continue
            self.plot_loop.plot(t, y, pen=pg.mkPen((150, 150, 150, 110), width=1))
        tn = self.tunings[sel]
        if "instabil" not in tn.note:
            t, sp, y, _u = simulate_loop(self.model, tn)
            self.plot_loop.plot(t, y, pen=pg.mkPen("#e74c3c", width=3), name=f"Istwert – {tn.method}")
        self.plot_loop.setTitle(tr("Simulierter Sollwertsprung: {0} (grau: übrige Regeln)").format(tn.method))

    def copy(self):
        """Modell und Parameter aller Regeln als Text in die Zwischenablage kopieren (für Inbetriebnahmeprotokoll oder
        E-Mail).
        """
        if self.model is None:
            return
        lines = [f"PID-Optimierung – {self.chart.name}",
                 f"Istwert: {self.cb_iw.currentData()}, Stellwert: {self.cb_stw.currentData()}, "
                 f"Zeitbereich: {self.cb_range.currentText()}",
                 f"Streckenmodell: {self.model.describe()}",
                 f"Reglertyp {self.cb_typ.currentText()}, Regelverhalten {self.cb_beh.currentText()}:"]
        lines += ["  " + format_params(tn) + tr("; Überschwingen {0}, Ausregelzeit {1}").format(_num(tn.overshoot, ' %'), _num(tn.settling, ' s')) for tn in self.tunings]
        QGuiApplication.clipboard().setText("\n".join(lines))
