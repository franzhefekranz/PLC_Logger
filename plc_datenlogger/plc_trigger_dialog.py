"""Editor für Trigger (Ereignisbedingungen) – wird vom Konfigurationsprogramm geöffnet.

Jede Zeile ist ein Trigger: Name, Bedingung über die Variablen (wie eine Formel, wahr = ungleich 0), Meldetext mit
Platzhaltern ``{Name}``, Priorität, Verzögerung, ob das Gehen protokolliert wird und ob das Ereignis quittiert werden
muss. Die Bedingung lässt sich im Formeleditor (mit Testwerten) bearbeiten. Fehlerhafte Zeilen werden rot markiert.

Ergebnis nach OK: ``result_triggers`` (Liste von Trigger).
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                             QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from plc_events import PRIORITIES, Trigger, check_trigger
from plc_formula_dialog import FormulaEditor
from plc_i18n import tr

COLS = [tr("Aktiv"), tr("Name"), tr("Bedingung"), tr("Meldetext"), tr("Priorität"), tr("Verzögerung"), tr("Gehen"), tr("Quittieren")]
T_ACTIVE, T_NAME, T_COND, T_TEXT, T_PRIO, T_DELAY, T_GO, T_ACK = range(len(COLS))

HELP = (
    tr("<b>Bedingung</b> wie eine Formel, z. B. <code>{Temperatur} &gt; 80</code>, "
    "<code>{Druck} &lt; 2 and {Pumpe} == 1</code>, <code>abs(ddt({Füllstand})) &gt; 5</code>. "
    "Wird sie wahr, <i>kommt</i> das Ereignis (ein Eintrag im Ereignisprotokoll), wird sie wieder falsch, "
    "<i>geht</i> es. <b>Meldetext</b>: <code>{Name}</code> wird durch den aktuellen Wert ersetzt "
    "(leer = Bedingung). <b>Verzögerung</b>: so lange muss die Bedingung ununterbrochen erfüllt sein. "
    "<b>Quittieren</b>: das Ereignis zählt in der Statusleiste des Loggers, bis es im Ereignis-Viewer quittiert wird.")
)


def _centered(widget):
    """Kästchen mittig in einer Tabellenzelle."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(widget)
    return w


class TriggerEditor(QDialog):
    """Tabelle der Trigger mit Prüfung."""

    def __init__(self, parent, triggers, names):
        super().__init__(parent)
        self.setWindowTitle(tr("Trigger (Ereignisse)"))
        self.resize(1150, 520)
        self.names = list(names)
        self.result_triggers = None
        lay = QVBoxLayout(self)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        hh = self.table.horizontalHeader()
        for c in (T_ACTIVE, T_PRIO, T_DELAY, T_GO, T_ACK):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(T_NAME, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(T_COND, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(T_TEXT, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(T_NAME, 160)
        self.table.itemChanged.connect(lambda _it: self.validate())
        self.table.cellDoubleClicked.connect(self._double_click)
        lay.addWidget(self.table, 1)

        btns = QHBoxLayout()
        for text, fn, tip in [
                (tr("+ Trigger"), self.add, tr("Neuen Trigger anlegen")),
                (tr("Bedingung bearbeiten …"), self.edit_condition,
                 tr("Bedingung im Formeleditor bearbeiten (mit Variablenliste und Testwerten); auch Doppelklick")),
                (tr("Duplizieren"), self.duplicate, tr("Ausgewählten Trigger kopieren")),
                (tr("Entfernen"), self.remove, tr("Ausgewählten Trigger löschen")),
                ("▲", lambda: self.move(-1), tr("nach oben")), ("▼", lambda: self.move(1), tr("nach unten"))]:
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)

        help_lbl = QLabel(HELP)
        help_lbl.setWordWrap(True)
        help_lbl.setStyleSheet("color:#555")
        lay.addWidget(help_lbl)
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept_checked)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        for t in triggers:
            self._add_row(t)
        self.validate()

    # ------------------------------------------------------------------ Zeilen
    def _add_row(self, t: Trigger, row=None):
        self.table.blockSignals(True)
        r = self.table.rowCount() if row is None else row
        self.table.insertRow(r)
        chk = QCheckBox()
        chk.setChecked(t.aktiv)
        chk.toggled.connect(lambda _c: self.validate())
        self.table.setCellWidget(r, T_ACTIVE, _centered(chk))
        self.table.setItem(r, T_NAME, QTableWidgetItem(t.name))
        self.table.setItem(r, T_COND, QTableWidgetItem(t.bedingung))
        self.table.setItem(r, T_TEXT, QTableWidgetItem(t.text))
        cb = QComboBox()
        for pr in PRIORITIES:
            cb.addItem(tr(pr), pr)
        cb.setCurrentIndex(max(cb.findData(t.prio), 0))
        self.table.setCellWidget(r, T_PRIO, cb)
        sp = QDoubleSpinBox()
        sp.setRange(0, 86400)
        sp.setDecimals(1)
        sp.setSuffix(" s")
        sp.setValue(t.verzoegerung_s)
        self.table.setCellWidget(r, T_DELAY, sp)
        for col, val in ((T_GO, t.gehen), (T_ACK, t.quittieren)):
            c = QCheckBox()
            c.setChecked(val)
            self.table.setCellWidget(r, col, _centered(c))
        self.table.blockSignals(False)
        return r

    def _check(self, r, col):
        return self.table.cellWidget(r, col).findChild(QCheckBox).isChecked()

    def row_trigger(self, r):
        return Trigger(name=self.table.item(r, T_NAME).text().strip(),
                       bedingung=" ".join(self.table.item(r, T_COND).text().split()),
                       text=self.table.item(r, T_TEXT).text().strip(),
                       prio=self.table.cellWidget(r, T_PRIO).currentData(),
                       verzoegerung_s=self.table.cellWidget(r, T_DELAY).value(),
                       gehen=self._check(r, T_GO), quittieren=self._check(r, T_ACK),
                       aktiv=self._check(r, T_ACTIVE))

    def triggers(self):
        return [self.row_trigger(r) for r in range(self.table.rowCount())]

    def _current(self):
        r = self.table.currentRow()
        return r if 0 <= r < self.table.rowCount() else None

    def _unique_name(self, base):
        taken = {t.name for t in self.triggers()}
        name, n = base, 1
        while name in taken:
            n += 1
            name = f"{base}{n}" if base == "Trigger" else f"{base} ({n})"
        return name

    def add(self):
        first = self.names[0] if self.names else "Variable"
        t = Trigger(name=self._unique_name("Trigger"), bedingung=f"{{{first}}} > 0",
                    text=f"{first} = {{{first}}}")
        r = self._add_row(t)
        self.table.selectRow(r)
        self.validate()
        self.edit_condition()

    def duplicate(self):
        r = self._current()
        if r is None:
            return
        t = self.row_trigger(r)
        t.name = self._unique_name(t.name)
        self.table.selectRow(self._add_row(t, r + 1))
        self.validate()

    def remove(self):
        r = self._current()
        if r is not None:
            self.table.removeRow(r)
            self.validate()

    def move(self, d):
        r = self._current()
        if r is None or not 0 <= r + d < self.table.rowCount():
            return
        t = self.row_trigger(r)
        self.table.removeRow(r)
        self._add_row(t, r + d)
        self.table.selectRow(r + d)
        self.validate()

    def _double_click(self, r, col):
        if col == T_COND:
            self.table.selectRow(r)
            self.edit_condition()

    def edit_condition(self):
        r = self._current()
        if r is None:
            return
        t = self.row_trigger(r)
        taken = {x.name for i, x in enumerate(self.triggers()) if i != r}
        dlg = FormulaEditor(self, self.names, t.name, t.bedingung, taken=taken)
        dlg.setWindowTitle(tr("Trigger-Bedingung (wahr = Ergebnis ungleich 0)"))
        if dlg.exec():
            self.table.item(r, T_NAME).setText(dlg.result_name)
            self.table.item(r, T_COND).setText(dlg.result_formula)

    # ------------------------------------------------------------------ Prüfung
    def problems(self):
        """[(Zeile, Fehlertext)] aller fehlerhaften Trigger."""
        out, seen = [], set()
        for r, t in enumerate(self.triggers()):
            err = check_trigger(t, set(self.names))
            if not err and t.name in seen:
                err = tr("Name doppelt vergeben")
            seen.add(t.name)
            if err:
                out.append((r, err))
        return out

    def validate(self):
        bad = dict(self.problems())
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            for c in (T_NAME, T_COND, T_TEXT):
                it = self.table.item(r, c)
                if it is None:
                    continue
                it.setBackground(QBrush(QColor("#f8d0d0")) if r in bad else QBrush())
                it.setToolTip(bad.get(r, ""))
        self.table.blockSignals(False)
        n = self.table.rowCount()
        active = sum(1 for r in range(n) if self._check(r, T_ACTIVE))
        txt = tr("{0} Trigger, davon {1} aktiv.").format(n, active)
        if bad:
            txt += "  <span style='color:#c0392b'>✗ " + "; ".join(
                f"Zeile {r + 1}: {e}" for r, e in list(bad.items())[:4]) + ("…" if len(bad) > 4 else "") + "</span>"
        self.lbl_status.setText(txt)

    def accept_checked(self):
        # Fehlerhafte, aber ausgeschaltete Trigger dürfen bleiben (sie werden nicht ausgewertet).
        bad = [(r, e) for r, e in self.problems() if self._check(r, T_ACTIVE)]
        if bad:
            QMessageBox.warning(self, tr("Trigger prüfen"),
                                "\n".join(f"Zeile {r + 1}: {e}" for r, e in bad))
            return
        self.result_triggers = self.triggers()
        self.accept()
