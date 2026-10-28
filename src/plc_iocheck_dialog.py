# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""IO-Check (Inbetriebnahme): Fenster mit Signalliste, Matrix (E/A als LEDs) und „Was hat sich bewegt?“.

Aufruf aus dem Logger (Analyse › IO-Check …) oder eigenständig:  plc_logger.py --iocheck [Konfiguration | *.iocheck.json]
Die Logik (Import, Prüfstatus, Auswertung, Lesen) steht in plc_iocheck.py.
"""
import math
import os
import queue
import time

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, QSize, QSortFilterProxyModel, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QProgressBar, QPushButton, QScrollArea, QSpinBox, QSplitter, QTableView, QTableWidget,
                               QTableWidgetItem, QTabWidget, QToolBar, QVBoxLayout, QWidget)

import plc_iocheck as io
from plc_common import Plc, load_plcs
from plc_i18n import tr

# Farben: Zeilen/Zellen je Prüfstatus, LEDs
STATUS_BG = {"ok": "#c8e6c9", "fehler": "#ffcdd2", "uebersprungen": "#e0e0e0"}
STATUS_FG = {"ok": "#1b5e20", "fehler": "#b71c1c", "uebersprungen": "#616161", "offen": "#455a64"}
STATUS_MARK = {"ok": "✓", "fehler": "✗", "uebersprungen": "–", "offen": ""}
LED_ON_IN, LED_ON_OUT, LED_OFF, LED_NONE = "#2ecc71", "#f5a623", "#9aa3ad", "#e5484d"
FLASH_S = 1.5                     # so lange wird ein Wechsel hervorgehoben

COLS = [("status", "Status"), ("value", "Wert"), ("address", "Adresse"), ("symbol", "Symbol"),
        ("comment", "Kommentar"), ("bmk", "BMK"), ("group", "Gruppe"), ("kind", "Typ"), ("plc", "Steuerung"),
        ("checked_at", "Geprüft am"), ("checker", "Prüfer"), ("remark", "Bemerkung")]
COL = {k: i for i, (k, _t) in enumerate(COLS)}


def value_text(sig) -> str:
    """Wert eines Signals für Tabelle und Tooltip: digital 0/1, analog skaliert mit Einheit und Rohwert; Lesefehler mit
    ⚠.
    """
    if sig.error and math.isnan(sig.value):
        return "⚠ " + sig.error
    if math.isnan(sig.value):
        return "–"
    if sig.binary:
        return "1" if sig.value else "0"
    eng = io.scale(sig, sig.value)
    unit = f" {sig.unit}" if sig.unit else ""
    return f"{eng:.4g}{unit}  ({sig.value:g})"


# ---------------------------------------------------------------------------------------------------------------------
# Tabelle der Signale
# ---------------------------------------------------------------------------------------------------------------------
class SignalModel(QAbstractTableModel):
    """Tabellenmodell der Signalliste (Qt Model/View): eine Zeile je Signal, Spalten nach COLS; nur „Bemerkung“ ist
    editierbar.

    Das Modell hält nur die Signal-Objekte; Farben, Symbole und Tooltips berechnet ``data`` bei jeder Anzeige aus deren
    aktuellem Zustand. Neue Werte melden ``refresh_values``/``refresh_rows`` (dataChanged), statt die Tabelle neu
    aufzubauen.
    """
    edited = Signal(object)

    def __init__(self, parent=None):
        """Leeres Modell."""
        super().__init__(parent)
        self.signals = []

    def set_signals(self, signals):
        """Neue Signalliste übernehmen (Ansicht wird komplett neu aufgebaut)."""
        self.beginResetModel()
        self.signals = list(signals)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        """Anzahl Zeilen = Anzahl Signale (flache Tabelle, keine Unterebenen)."""
        return 0 if parent.isValid() else len(self.signals)

    def columnCount(self, parent=QModelIndex()):
        """Anzahl Spalten (COLS)."""
        return len(COLS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        """Spaltenüberschriften (übersetzt)."""
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return tr(COLS[section][1])
        return None

    def flags(self, index):
        """Zellen wählbar; die Spalte Bemerkung zusätzlich editierbar."""
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if COLS[index.column()][0] == "remark":
            f |= Qt.ItemFlag.ItemIsEditable
        return f

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        """Inhalt einer Zelle je Rolle: Text, Hintergrund (Status, gelb nach einem Wechsel), Schriftfarbe, LED-Farbe in
        der Wertspalte, Tooltip mit Details und Fett für geprüfte Status.
        """
        if not index.isValid():
            return None
        s = self.signals[index.row()]
        key = COLS[index.column()][0]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if key == "status":
                return f"{STATUS_MARK[s.status]} {tr(io.STATUS[s.status])}".strip()
            if key == "value":
                return value_text(s)
            return getattr(s, key)
        if role == Qt.ItemDataRole.BackgroundRole:
            if key == "value" and time.time() - s.changed < FLASH_S:
                return QBrush(QColor("#fff176"))
            bg = STATUS_BG.get(s.status)
            return QBrush(QColor(bg)) if bg else None
        if role == Qt.ItemDataRole.ForegroundRole:
            if s.status in STATUS_BG or (key == "value" and time.time() - s.changed < FLASH_S):
                return QBrush(QColor("#000000" if key != "status" else STATUS_FG[s.status]))
            if key == "status":
                return QBrush(QColor(STATUS_FG[s.status]))
            return None
        if role == Qt.ItemDataRole.DecorationRole and key == "value" and s.binary:
            if math.isnan(s.value):
                return QColor(LED_NONE) if s.error else None
            return QColor((LED_ON_IN if s.is_input else LED_ON_OUT) if s.value else LED_OFF)
        if role == Qt.ItemDataRole.ToolTipRole:
            tip = [f"<b>{s.address}</b> {s.symbol}", s.comment, s.bmk and f"BMK: {s.bmk}",
                   tr(io.KIND_TEXT.get(s.kind, s.kind))]
            if not s.binary:
                tip.append(tr("Messbereich {0} … {1} {2} (Rohwert {3} … {4})").format(
                    f"{s.eng_min:g}", f"{s.eng_max:g}", s.unit, f"{s.raw_min:g}", f"{s.raw_max:g}"))
                fault = io.analog_fault(s, s.value)
                if fault:
                    tip.append(f"<span style='color:#c62828'>⚠ {fault}</span>")
            if s.error:
                tip.append(f"<span style='color:#c62828'>⚠ {s.error}</span>")
            return "<br>".join(t for t in tip if t)
        if role == Qt.ItemDataRole.FontRole and key == "status" and s.status != "offen":
            f = QFont()
            f.setBold(True)
            return f
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        """Bemerkung übernehmen und ``edited`` senden (das Fenster speichert dann)."""
        if role == Qt.ItemDataRole.EditRole and COLS[index.column()][0] == "remark":
            sig = self.signals[index.row()]
            sig.remark = str(value)
            self.dataChanged.emit(index, index)
            self.edited.emit(sig)
            return True
        return False

    def refresh_values(self):
        """Nur die Wertspalte neu zeichnen lassen (nach neuen Messwerten)."""
        if self.signals:
            self.dataChanged.emit(self.index(0, COL["value"]), self.index(len(self.signals) - 1, COL["value"]))

    def refresh_rows(self, sigs=None):
        """Ganze Zeilen der Signale ``sigs`` neu zeichnen lassen (alle, wenn None)."""
        if not self.signals:
            return
        if sigs is None:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.signals) - 1, len(COLS) - 1))
            return
        rows = {id(s) for s in sigs}
        for r, s in enumerate(self.signals):
            if id(s) in rows:
                self.dataChanged.emit(self.index(r, 0), self.index(r, len(COLS) - 1))


class SignalFilter(QSortFilterProxyModel):
    """Filter der Signalliste: Suchtext (alle Wörter in Adresse, Symbol, Kommentar, BMK oder Bemerkung), Gruppe, Typ und
    Status.
    """
    def __init__(self, parent=None):
        """Ohne Filter (alles sichtbar)."""
        super().__init__(parent)
        self.text, self.group, self.kind, self.status = "", "", "", ""

    def set_filter(self, text, group, kind, status):
        """Neue Filterwerte setzen und die Liste neu filtern."""
        self.text, self.group, self.kind, self.status = text.lower(), group, kind, status
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        """Zeile anzeigen? (von Qt für jede Zeile des Quellmodells aufgerufen)"""
        s = self.sourceModel().signals[row]
        if self.group and s.group != self.group:
            return False
        if self.kind and s.kind != self.kind:
            return False
        if self.status and s.status != self.status:
            return False
        if self.text:
            hay = " ".join((s.address, s.symbol, s.comment, s.bmk, s.remark)).lower()
            return all(w in hay for w in self.text.split())
        return True


# ---------------------------------------------------------------------------------------------------------------------
# Matrix: Binärsignale als LEDs (Byte × Bit), geprüfte abgehakt/farbig
# ---------------------------------------------------------------------------------------------------------------------
class MatrixWidget(QWidget):
    """Binärsignale als Raster von LEDs (Zeile = Byte, Spalte = Bit), mit Prüfstatus und Hervorhebung frischer Wechsel.

    Klick wählt ein Signal (``selected``), Doppelklick schaltet OK an/aus, Rechtsklick öffnet das Statusmenü
    (``status_request``).
    """
    selected = Signal(object)               # Signal angeklickt
    status_request = Signal(object, str)    # (Signal, Status) über Doppelklick/Kontextmenü

    CELL, GAP, LABEL_W, HEAD_H, SECTION_H = 34, 4, 92, 18, 26

    def __init__(self, parent=None):
        """Leere Matrix; ``layout_items`` merkt sich die Rechtecke der Zellen für Zeichnen und Mausklicks."""
        super().__init__(parent)
        self.rows = []
        self.sections = []                  # [(y, Abschnitt oder None, Bitanzahl bzw. Zeilenbeschriftung)]
        self._height = 100
        self.layout_items = []              # [(QRectF, Signal)]
        self.current = None
        self.setMouseTracking(True)

    def set_rows(self, rows):
        """Neue Zeilen (siehe ``plc_iocheck.matrix_rows``) übernehmen, Anordnung berechnen, Größe anpassen."""
        self.rows = rows
        self._layout()
        self.resize(self.sizeHint())
        self.updateGeometry()
        self.update()

    def _layout(self):
        """Position jeder Zelle, der Abschnittsüberschriften und der Bitnummern berechnen."""
        self.layout_items, self.sections = [], []
        y, last = 6, None
        for section, label, cells in self.rows:
            if section != last:
                if last is not None:
                    y += 8
                self.sections.append((y, section, len(cells)))
                y += self.SECTION_H + self.HEAD_H
                last = section
            row = []
            for k, sig in enumerate(cells):
                r = QRectF(self.LABEL_W + k * (self.CELL + self.GAP), y, self.CELL, self.CELL)
                row.append((r, sig))
                if sig is not None:
                    self.layout_items.append((r, sig))
            self.sections.append((y, None, label))
            y += self.CELL + self.GAP
        self._height = y + 6

    def sizeHint(self):
        """Benötigte Größe (die Matrix steht in einer Scrollfläche)."""
        n = max((len(c) for _s, _l, c in self.rows), default=8)
        return QSize(self.LABEL_W + n * (self.CELL + self.GAP) + 10, self._height)

    def minimumSizeHint(self):
        """Nicht kleiner als nötig (sonst würde die Scrollfläche abschneiden)."""
        return self.sizeHint()

    def paintEvent(self, _ev):
        """Abschnittsüberschriften, Bitnummern, Zeilenbeschriftungen und alle Zellen zeichnen."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        text = pal.color(pal.ColorRole.WindowText)
        muted = pal.color(pal.ColorRole.PlaceholderText)
        now = time.time()
        bold = QFont(self.font())
        bold.setBold(True)
        small = QFont(self.font())
        small.setPointSizeF(max(6.5, self.font().pointSizeF() * 0.8))
        for y, section, info in self.sections:
            if section is not None:
                p.setFont(bold)
                p.setPen(text)
                p.drawText(QRectF(4, y, 600, self.SECTION_H), Qt.AlignmentFlag.AlignVCenter, section)
                p.setFont(small)
                p.setPen(muted)
                for k in range(info):
                    r = QRectF(self.LABEL_W + k * (self.CELL + self.GAP), y + self.SECTION_H, self.CELL, self.HEAD_H)
                    p.drawText(r, Qt.AlignmentFlag.AlignCenter, str(k))
            else:
                p.setFont(self.font())
                p.setPen(text)
                p.drawText(QRectF(4, y, self.LABEL_W - 10, self.CELL),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, info)
        for r, sig in self.layout_items:
            self._paint_cell(p, r, sig, now, small)
        p.end()

    def _paint_cell(self, p, r, sig, now, small):
        """Eine Zelle: Hintergrund nach Status, LED (Eingang grün, Ausgang orange, 0 grau, Fehler rot), gelber Ring nach
        einem Wechsel, Haken/Kreuz bzw. blauer Punkt (0→1 gesehen), Rahmen um das gewählte Signal.
        """
        bg = STATUS_BG.get(sig.status)
        p.setPen(QPen(QColor("#b0bec5"), 1))
        p.setBrush(QColor(bg) if bg else self.palette().color(self.palette().ColorRole.Base))
        p.drawRoundedRect(r, 5, 5)
        # LED
        led = r.adjusted(8, 6, -8, -10)
        if math.isnan(sig.value):
            color = QColor(LED_NONE) if sig.error else QColor("#eceff1")
        else:
            color = QColor((LED_ON_IN if sig.is_input else LED_ON_OUT) if sig.value else LED_OFF)
        p.setPen(QPen(color.darker(150), 1))
        p.setBrush(color)
        p.drawEllipse(led)
        # Wechsel eben gesehen: gelber Ring
        if now - sig.changed < FLASH_S:
            p.setPen(QPen(QColor("#fbc02d"), 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 5, 5)
        # Prüfstatus: Haken/Kreuz unten rechts; nur 0→1 gesehen: kleiner Punkt oben rechts
        mark = STATUS_MARK.get(sig.status, "")
        if mark:
            p.setFont(small)
            p.setPen(QColor(STATUS_FG[sig.status]))
            p.drawText(r.adjusted(0, 0, -2, 1), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, mark)
        elif sig.seen & io.SEEN_RISE:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#1e88e5"))
            p.drawEllipse(QRectF(r.right() - 9, r.top() + 3, 6, 6))
        if sig is self.current:
            p.setPen(QPen(QColor("#1565c0"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 6, 6)

    def _at(self, pos):
        """Signal unter der Mausposition oder None."""
        for r, sig in self.layout_items:
            if r.contains(pos):
                return sig
        return None

    def mouseMoveEvent(self, ev):
        """Tooltip mit Adresse, Kommentar, Wert, Status und Prüfer des Signals unter der Maus."""
        sig = self._at(ev.position())
        if sig is None:
            self.setToolTip("")
            return
        lines = [f"<b>{sig.address}</b> {sig.symbol}", sig.comment, sig.bmk and f"BMK: {sig.bmk}",
                 tr("Wert: {0}").format(value_text(sig)), tr("Status: {0}").format(tr(io.STATUS[sig.status]))]
        if sig.checked_at:
            lines.append(f"{sig.checked_at} {sig.checker}")
        if sig.remark:
            lines.append(sig.remark)
        self.setToolTip("<br>".join(x for x in lines if x))

    def mousePressEvent(self, ev):
        """Signal wählen; mit der rechten Maustaste zusätzlich das Statusmenü."""
        sig = self._at(ev.position())
        if sig is None:
            return
        self.current = sig
        self.selected.emit(sig)
        self.update()
        if ev.button() == Qt.MouseButton.RightButton:
            menu = QMenu(self)
            for st in ("ok", "fehler", "uebersprungen", "offen"):
                a = menu.addAction(f"{STATUS_MARK[st] or '○'}  " + (tr("Zurücksetzen") if st == "offen"
                                                                    else tr(io.STATUS[st])))
                a.triggered.connect(lambda _=False, s=st: self.status_request.emit(sig, s))
            menu.exec(ev.globalPosition().toPoint())

    def mouseDoubleClickEvent(self, ev):
        """Doppelklick: OK setzen bzw. zurücknehmen."""
        sig = self._at(ev.position())
        if sig is not None:
            self.status_request.emit(sig, "offen" if sig.status == "ok" else "ok")


# ---------------------------------------------------------------------------------------------------------------------
# Dialog: Bereiche scannen
# ---------------------------------------------------------------------------------------------------------------------
class ScanDialog(QDialog):
    """Dialog „Bereiche scannen“: Liste der Scan-Bereiche (Steuerung, Startadresse, Anzahl Bits); Ergebnis in ``scans``.
    """
    def __init__(self, parent, scans, plcs):
        """Tabelle mit den vorhandenen Bereichen und Knöpfen Hinzufügen/Entfernen."""
        super().__init__(parent)
        self.setWindowTitle(tr("Bereiche scannen"))
        self.plcs = plcs
        lay = QVBoxLayout(self)
        hint = QLabel(tr("Zusammenhängende Bits ohne IO-Liste lesen und in der Matrix anzeigen, z. B. Startadresse "
                         "E0.0 und 256 Bits (= E0.0 … E31.7). Adressen in der Schreibweise des Treibers; Signale, "
                         "die schon in der IO-Liste stehen, werden übernommen."))
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([tr("Steuerung"), tr("Startadresse"), tr("Anzahl Bits")])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table)
        for s in scans:
            self._add(s)
        row = QHBoxLayout()
        b_add = QPushButton(tr("Hinzufügen"))
        b_add.clicked.connect(lambda: self._add(io.ScanRange()))
        b_del = QPushButton(tr("Entfernen"))
        b_del.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()))
        row.addWidget(b_add)
        row.addWidget(b_del)
        row.addStretch(1)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(560, 320)
        self.scans = list(scans)

    def _add(self, s):
        """Zeile für einen Bereich anhängen (Auswahl der Steuerung, Startadresse, Anzahl)."""
        r = self.table.rowCount()
        self.table.insertRow(r)
        cb = QComboBox()
        for p in self.plcs:
            cb.addItem(p.name, p.name)
        i = cb.findData(s.plc)
        cb.setCurrentIndex(max(0, i))
        self.table.setCellWidget(r, 0, cb)
        self.table.setItem(r, 1, QTableWidgetItem(s.start))
        sp = QSpinBox()
        sp.setRange(1, 8192)
        sp.setValue(int(s.count))
        self.table.setCellWidget(r, 2, sp)

    def _ok(self):
        """Zeilen mit Startadresse übernehmen; die erste Steuerung wird als "" gespeichert (Standard)."""
        out = []
        first = self.plcs[0].name if self.plcs else ""
        for r in range(self.table.rowCount()):
            start = (self.table.item(r, 1).text() if self.table.item(r, 1) else "").strip()
            if not start:
                continue
            name = self.table.cellWidget(r, 0).currentData() or ""
            out.append(io.ScanRange(start=start, count=self.table.cellWidget(r, 2).value(),
                                    plc="" if name == first else name))
        self.scans = out
        self.accept()


class ColumnsDialog(QDialog):
    """Dialog „Spalten der IO-Liste“: je Feld die Spaltenüberschriften, unter denen es in der Excel-/CSV-Liste steht.

    Mehrere Überschriften durch Komma oder Semikolon trennen; Groß-/Kleinschreibung, Leer- und Sonderzeichen zählen
    nicht. Ein leeres Feld wird nicht eingelesen und seine Spalte in der Signalliste nicht angezeigt (die Adresse ist
    Pflicht). Gespeichert wird in den persönlichen Einstellungen; Ergebnis nach OK in ``aliases``."""

    def __init__(self, parent, aliases):
        """Tabelle Feld | Überschriften, vorbelegt mit den gültigen Namen (eigene oder Vorgabe)."""
        super().__init__(parent)
        self.setWindowTitle(tr("Spalten der IO-Liste"))
        lay = QVBoxLayout(self)
        hint = QLabel(tr("Unter welchen Spaltenüberschriften stehen die Angaben in der IO-Liste (Excel/ODS/CSV)? Mehrere "
                         "Namen durch Komma trennen; Groß-/Kleinschreibung und Leerzeichen zählen nicht. "
                         "Leer = Spalte nicht einlesen und in der Signalliste nicht anzeigen."))
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.fields = list(io.FIELD_TEXT)
        self.table = QTableWidget(len(self.fields), 2)
        self.table.setHorizontalHeaderLabels([tr("Feld"), tr("Spaltenüberschriften in der IO-Liste")])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._fill(aliases)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        b_def = QPushButton(tr("Vorgabe"))
        b_def.setToolTip(tr("Alle Felder auf die eingebauten Spaltennamen zurücksetzen"))
        b_def.clicked.connect(lambda: self._fill({}))
        row.addWidget(b_def)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        lay.addLayout(row)
        self.resize(760, 560)
        self.aliases = dict(aliases)

    def _fill(self, aliases):
        """Tabelle mit den Namen aus ``aliases`` (fehlende Felder: Vorgabe) füllen."""
        for r, fld in enumerate(self.fields):
            it = QTableWidgetItem(tr(io.FIELD_TEXT[fld]))
            it.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, 0, it)
            self.table.setItem(r, 1, QTableWidgetItem(", ".join(io.column_names(fld, aliases))))
        self.table.resizeColumnToContents(0)

    def names(self, fld):
        """Eingetragene Überschriften eines Feldes als Liste."""
        it = self.table.item(self.fields.index(fld), 1)
        text = it.text() if it else ""
        return [x.strip() for x in text.replace(";", ",").split(",") if x.strip()]

    def _ok(self):
        """Prüfen (Adresse darf nicht leer sein) und übernehmen."""
        if not self.names("address"):
            QMessageBox.warning(self, self.windowTitle(), tr("Für die Adresse ist mindestens eine Überschrift nötig."))
            return
        self.aliases = {fld: self.names(fld) for fld in self.fields}
        self.accept()


# ---------------------------------------------------------------------------------------------------------------------
# Analogwert des gewählten Signals
# ---------------------------------------------------------------------------------------------------------------------
class AnalogPanel(QGroupBox):
    """Feld unter der Signalliste für das gewählte Analogsignal: großer Wert, Rohwert, Fehlerwerte, Drahtbruchprüfung,
    Skalierung und die Prüfpunkte 0/50/100 %.
    """
    changed = Signal(object)

    def __init__(self, tracker, parent=None):
        """Felder anlegen; ``tracker`` liefert die Toleranz und übernimmt Prüfpunkte."""
        super().__init__(tr("Analogwert"), parent)
        self.tracker, self.sig = tracker, None
        grid = QGridLayout(self)
        self.lbl_value = QLabel()
        f = self.lbl_value.font()
        f.setPointSizeF(f.pointSizeF() * 1.6)
        f.setBold(True)
        self.lbl_value.setFont(f)
        self.lbl_raw = QLabel()
        self.lbl_fault = QLabel()
        self.lbl_fault.setStyleSheet("color:#c62828;font-weight:bold")
        grid.addWidget(self.lbl_value, 0, 0, 1, 2)
        grid.addWidget(self.lbl_raw, 1, 0, 1, 2)
        grid.addWidget(self.lbl_fault, 2, 0, 1, 2)
        self.lbl_break = QLabel()
        self.lbl_break.setWordWrap(True)
        self.lbl_break.setToolTip(tr("Drahtbruchprüfung: Verdrahtung öffnen (Klemme lösen) – die Baugruppe meldet "
                                     "einen Fehlerwert – und wieder schließen. Bei 0 … 10 V und 0 … 20 mA ist eine "
                                     "Unterbrechung nicht erkennbar: dann die Prüfpunkte verwenden oder von Hand "
                                     "abhaken."))
        grid.addWidget(self.lbl_break, 3, 0, 1, 2)
        form = QFormLayout()
        self.ed = {}
        for key, text in (("raw_min", "Rohwert bei 0 %"), ("raw_max", "Rohwert bei 100 %"),
                          ("eng_min", "Messbereich von"), ("eng_max", "Messbereich bis")):
            sp = QDoubleSpinBox()
            sp.setRange(-1e9, 1e9)
            sp.setDecimals(3)
            sp.editingFinished.connect(self._edited)
            self.ed[key] = sp
            form.addRow(tr(text), sp)
        self.ed_unit = QLineEdit()
        self.ed_unit.setMaximumWidth(90)
        self.ed_unit.editingFinished.connect(self._edited)
        form.addRow(tr("Einheit"), self.ed_unit)
        grid.addLayout(form, 0, 2, 4, 1)
        pts = QGridLayout()
        self.lbl_pts_title = QLabel(f"<b>{tr('Prüfpunkte (optional, z. B. mit Kalibrator)')}</b>")
        grid.addWidget(self.lbl_pts_title, 0, 3)
        pts.addWidget(QLabel(f"<b>{tr('Prüfpunkt')}</b>"), 0, 0)
        pts.addWidget(QLabel(f"<b>{tr('Soll')}</b>"), 0, 1)
        pts.addWidget(QLabel(f"<b>{tr('Gemessen')}</b>"), 0, 2)
        self.pt_widgets = {}
        for k, pct in enumerate(io.POINTS, start=1):
            lbl_t, lbl_m, lbl_s = QLabel(), QLabel(), QLabel()
            btn = QPushButton(tr("Übernehmen"))
            btn.setToolTip(tr("Aktuellen Wert als Messpunkt übernehmen"))
            btn.clicked.connect(lambda _=False, p=pct: self._take(p))
            pts.addWidget(QLabel(f"{pct} %"), k, 0)
            pts.addWidget(lbl_t, k, 1)
            pts.addWidget(lbl_m, k, 2)
            pts.addWidget(lbl_s, k, 3)
            pts.addWidget(btn, k, 4)
            self.pt_widgets[pct] = (lbl_t, lbl_m, lbl_s)
        b_clear = QPushButton(tr("Messpunkte löschen"))
        b_clear.clicked.connect(self._clear)
        pts.addWidget(b_clear, len(io.POINTS) + 1, 0, 1, 2)
        self.lbl_auto = QLabel(tr("Wert 1 s lang in Toleranz um 0/50/100 % → Messpunkt wird automatisch übernommen."))
        self.lbl_auto.setWordWrap(True)
        self.lbl_auto.setObjectName("muted")
        pts.addWidget(self.lbl_auto, len(io.POINTS) + 2, 0, 1, 5)
        grid.addLayout(pts, 1, 3, 3, 1)
        grid.setColumnStretch(3, 1)

    def set_signal(self, sig):
        """Anzuzeigendes Signal wählen (bei Digitalsignalen wird das Feld ausgeblendet)."""
        self.sig = sig
        self.setVisible(sig is not None and not sig.binary)
        if self.isVisible():
            for key, sp in self.ed.items():
                sp.blockSignals(True)
                sp.setValue(getattr(sig, key))
                sp.blockSignals(False)
            self.ed_unit.setText(sig.unit)
            self.setTitle(tr("Analogwert: {0}").format(sig.label))
            self.refresh()

    def _edited(self):
        """Skalierung oder Einheit geändert: ins Signal übernehmen und melden (``changed``)."""
        if self.sig is None:
            return
        for key, sp in self.ed.items():
            setattr(self.sig, key, sp.value())
        self.sig.unit = self.ed_unit.text().strip()
        self.refresh()
        self.changed.emit(self.sig)

    def _take(self, pct):
        """Prüfpunkt ``pct`` mit dem aktuellen Wert übernehmen."""
        if self.sig is not None and not math.isnan(self.sig.value):
            self.tracker.take_point(self.sig, pct)
            self.refresh()
            self.changed.emit(self.sig)

    def _clear(self):
        """Alle Messpunkte des Signals löschen."""
        if self.sig is not None:
            self.sig.points = {}
            self.refresh()
            self.changed.emit(self.sig)

    def refresh(self):
        """Anzeige mit dem aktuellen Wert aktualisieren: skalierter Wert, Fehler, Fortschritt der Drahtbruchprüfung,
        Soll/Ist der Prüfpunkte.
        """
        s = self.sig
        if s is None or not self.isVisible():
            return
        eng = io.scale(s, s.value)
        unit = f" {s.unit}" if s.unit else ""
        self.lbl_value.setText("–" if math.isnan(eng) else f"{eng:.4g}{unit}")
        self.lbl_raw.setText(tr("Rohwert: {0}").format("–" if math.isnan(s.value) else f"{s.value:g}"))
        self.lbl_fault.setText(io.analog_fault(s, s.value) or s.error)
        if s.is_input:
            ok1, ok2 = bool(s.seen & io.SEEN_BREAK), bool(s.seen & io.SEEN_BACK)
            mark = lambda done: f"<span style='color:{STATUS_FG['ok']};font-weight:bold'>✓</span>" if done else "○"  # noqa: E731
            self.lbl_break.setText(f"<b>{tr('Drahtbruchprüfung')}</b><br>{mark(ok1)} "
                                   f"{tr('1. Verdrahtung öffnen → Fehlerwert erkannt')}<br>{mark(ok2)} "
                                   f"{tr('2. Wieder schließen → Wert gültig')}")
        else:
            self.lbl_break.setText("")
        for pct, (lbl_t, lbl_m, lbl_s) in self.pt_widgets.items():
            lbl_t.setText(f"{io.point_target(s, pct):.4g}{unit}")
            got = s.points.get(str(pct))
            if got is None:
                near = io.point_ok(s, pct, eng, self.tracker.tolerance)
                lbl_m.setText(tr("(jetzt in Toleranz)") if near else "")
                lbl_s.setText("")
            else:
                ok = io.point_ok(s, pct, got, self.tracker.tolerance)
                lbl_m.setText(f"{got:.4g}{unit}")
                lbl_s.setText(f"<span style='color:{STATUS_FG['ok' if ok else 'fehler']};font-weight:bold'>"
                              f"{'✓' if ok else '✗'}</span>")


# ---------------------------------------------------------------------------------------------------------------------
# Hauptfenster
# ---------------------------------------------------------------------------------------------------------------------
class IoCheckWindow(QMainWindow):
    """Hauptfenster des IO-Checks: Werkzeugleiste, Reiter Signalliste und Matrix, rechts „Was hat sich bewegt?“.

    Das Lesen läuft in je einem ``IoReader``-Thread pro Steuerung; ein Timer (150 ms) holt die Werte aus der
    Warteschlange, gibt sie an den ``IoTracker`` und aktualisiert die Anzeige. Die ``IoWebBridge`` stellt alles der
    Webseite /io bereit; deren Befehle werden ebenfalls im Timer übernommen.
    """
    def __init__(self, config_path="", plcs=None, demo=False, project_path="", parent=None):
        """Fenster aufbauen; ``config_path``: Konfiguration mit den Steuerungen, ``project_path``: Prüfstand zum Öffnen,
        ``demo``: simulierte Werte.
        """
        super().__init__(parent)
        self.setWindowTitle(tr("IO-Check"))
        self.resize(1280, 800)
        self.project = io.IoProject(config=config_path or "")
        self.plcs = list(plcs) if plcs is not None else self._load_plcs(config_path)
        self.tracker = io.IoTracker()
        self.queue = queue.Queue()
        self.readers, self.reader_signals, self.plc_state = [], {}, {}
        self.all_signals = []
        self.dirty = False
        self._hist_seen = None
        self._swap_until, self._swap_text = 0.0, ""
        self.bridge = io.IoWebBridge()            # Webseite /io (Smartphone/Tablet)
        self.web = None                           # eigener Webserver (wenn keiner läuft)
        try:
            import plc_web
            plc_web.set_io_bridge(self.bridge)
        except Exception:                         # ohne Flask: keine Webseite
            pass

        self._build_toolbar(demo)
        self._build_central()
        self.statusBar().addPermanentWidget(self.lbl_plc)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(150)
        if project_path:
            self.open_project(project_path)
        else:
            self._rebuild()

    # ------------------------------------------------------------------ Aufbau
    def _build_toolbar(self, demo):
        """Werkzeugleiste: Datei-Aktionen, Protokoll, Mobil, Lesen starten/stoppen, Demo, automatisch abhaken, Toleranz.
        """
        tb = QToolBar(tr("IO-Check"))
        tb.setMovable(False)
        self.addToolBar(tb)

        def act(text, slot, tip="", key=None):
            """Aktion mit Text, Tooltip und Tastenkürzel anlegen und in die Leiste stellen."""
            a = QAction(text, self)
            a.triggered.connect(slot)
            if tip:
                a.setToolTip(tip)
            if key:
                a.setShortcut(QKeySequence(key))
            tb.addAction(a)
            return a

        act(tr("IO-Liste importieren …"), self.import_list,
            tr("Signalliste aus CSV, Excel oder ODS übernehmen (EPLAN, TIA-Portal-Variablentabelle, eigene Liste)"))
        act(tr("Spalten …"), self.edit_columns,
            tr("Spaltenüberschriften der IO-Liste festlegen; leere Felder werden nicht eingelesen und nicht angezeigt"))
        act(tr("Öffnen …"), lambda: self.open_project(), tr("Gespeicherten IO-Check öffnen"), "Ctrl+O")
        act(tr("Speichern"), lambda: self.save_project(), tr("Prüfstand speichern (*.iocheck.json)"), "Ctrl+S")
        act(tr("Speichern unter …"), lambda: self.save_project(as_new=True))
        act(tr("Ergebnis exportieren …"), self.export_result, tr("Prüfergebnis als CSV oder Excel speichern"))
        act(tr("Protokoll (PDF) …"), self.make_protocol,
            tr("Abnahmeprotokoll mit Zusammenfassung, Fehlerliste, allen Signalen und Unterschriftsfeldern"))
        act(tr("📱 Mobil …"), self.show_mobile,
            tr("IO-Check auf Smartphone/Tablet: Adresse der Webseite anzeigen (startet bei Bedarf den Webserver)"))
        tb.addSeparator()
        self.act_run = act(tr("▶ Lesen starten"), self.toggle_reading, tr("Signale zyklisch aus den Steuerungen lesen"),
                           "F5")
        self.chk_demo = QCheckBox(tr("Demo"))
        self.chk_demo.setToolTip(tr("Simulierte Werte statt Verbindung zur Steuerung"))
        self.chk_demo.setChecked(bool(demo))
        tb.addWidget(self.chk_demo)
        tb.addSeparator()
        # Seitenleiste „Was hat sich bewegt?“ ein-/ausblenden (persönliche Einstellung, Standard: sichtbar)
        self.act_moved = QAction(tr("Was hat sich bewegt?"), self)
        self.act_moved.setCheckable(True)
        self.act_moved.setToolTip(tr("Seitenleiste mit den zuletzt gewechselten Signalen ein- oder ausblenden"))
        try:
            from plc_common import load_settings
            self.act_moved.setChecked(bool(load_settings().get("iocheck_bewegt", True)))
        except Exception:
            self.act_moved.setChecked(True)
        self.act_moved.toggled.connect(self._toggle_moved)
        tb.addAction(self.act_moved)
        self.chk_auto = QCheckBox(tr("Signale automatisch abhaken"))
        self.chk_auto.setToolTip(tr("Optional: Ein Signal mit Status „offen“ wird OK, sobald ein Digitalsignal 0→1→0 "
                                    "gewechselt hat (Sensor betätigt und losgelassen) bzw. ein Analogeingang einen "
                                    "Drahtbruch gemeldet hat und wieder gültig ist (Verdrahtung geöffnet und "
                                    "geschlossen). Geprüft werden nur Signale aus der Liste bzw. den Scan-Bereichen."))
        self.chk_auto.toggled.connect(self._options_changed)
        tb.addWidget(self.chk_auto)
        tb.addWidget(QLabel("  " + tr("Toleranz Analog:")))
        self.sp_tol = QDoubleSpinBox()
        self.sp_tol.setRange(0.1, 20.0)
        self.sp_tol.setDecimals(1)
        self.sp_tol.setSuffix(" %")
        self.sp_tol.setValue(1.0)
        self.sp_tol.setToolTip(tr("Zulässige Abweichung der Analog-Prüfpunkte in % des Messbereichs"))
        self.sp_tol.valueChanged.connect(self._options_changed)
        tb.addWidget(self.sp_tol)
        self.lbl_plc = QLabel()

    def _build_central(self):
        """Mittelteil: Reiter Signalliste (Filter, Fortschritt, Tabelle, Statusknöpfe, Analogfeld) und Matrix; rechts
        die Liste der Wechsel.
        """
        split = QSplitter(Qt.Orientation.Horizontal)
        self.tabs = QTabWidget()
        split.addWidget(self.tabs)

        # --- Signalliste
        page = QWidget()
        v = QVBoxLayout(page)
        frow = QHBoxLayout()
        self.ed_filter = QLineEdit()
        self.ed_filter.setPlaceholderText(tr("Suchen (Adresse, Symbol, Kommentar, BMK) …"))
        self.ed_filter.setClearButtonEnabled(True)
        self.cb_group = QComboBox()
        self.cb_kind = QComboBox()
        self.cb_kind.addItem(tr("Alle Typen"), "")
        for k in io.KINDS:
            self.cb_kind.addItem(f"{k} – {tr(io.KIND_TEXT[k])}", k)
        self.cb_status = QComboBox()
        self.cb_status.addItem(tr("Alle Status"), "")
        for k, t in io.STATUS.items():
            self.cb_status.addItem(tr(t), k)
        for w in (self.ed_filter, self.cb_group, self.cb_kind, self.cb_status):
            (w.textChanged if w is self.ed_filter else w.currentIndexChanged).connect(self._apply_filter)
        frow.addWidget(self.ed_filter, 3)
        frow.addWidget(self.cb_group, 1)
        frow.addWidget(self.cb_kind, 1)
        frow.addWidget(self.cb_status, 1)
        v.addLayout(frow)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        v.addWidget(self.progress)
        self.model = SignalModel(self)
        self.model.edited.connect(lambda _s: self._mark_dirty())
        self.proxy = SignalFilter(self)
        self.proxy.setSourceModel(self.model)
        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSortingEnabled(True)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(22)
        self.view.horizontalHeader().setStretchLastSection(True)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                  | QAbstractItemView.EditTrigger.EditKeyPressed)
        for key, w in (("status", 110), ("value", 150), ("address", 90), ("symbol", 150), ("comment", 200),
                       ("bmk", 90), ("group", 80), ("kind", 40), ("plc", 70), ("checked_at", 130), ("checker", 80)):
            self.view.setColumnWidth(COL[key], w)
        self.view.selectionModel().currentRowChanged.connect(self._row_changed)
        v.addWidget(self.view, 1)
        brow = QHBoxLayout()
        for st, text, key in (("ok", tr("✓ OK"), "Ctrl+1"), ("fehler", tr("✗ Fehler …"), "Ctrl+2"),
                              ("uebersprungen", tr("– Übersprungen"), "Ctrl+3"), ("offen", tr("Zurücksetzen"),
                                                                                    "Ctrl+0")):
            b = QPushButton(text)
            b.setToolTip(f"{text} ({key})")
            b.clicked.connect(lambda _=False, s=st: self.set_selected_status(s))
            a = QAction(self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(lambda _=False, s=st: self.set_selected_status(s))
            self.addAction(a)
            brow.addWidget(b)
        brow.addStretch(1)
        v.addLayout(brow)
        self.analog = AnalogPanel(self.tracker)
        self.analog.changed.connect(self._signal_edited)
        self.analog.setVisible(False)
        v.addWidget(self.analog)
        self.tabs.addTab(page, tr("Signalliste"))

        # --- Matrix
        mpage = QWidget()
        mv = QVBoxLayout(mpage)
        mrow = QHBoxLayout()
        b_scan = QPushButton(tr("Bereiche scannen …"))
        b_scan.setToolTip(tr("Zusammenhängende Ein-/Ausgänge ohne IO-Liste lesen, z. B. E0.0 … E31.7"))
        b_scan.clicked.connect(self.edit_scans)
        mrow.addWidget(b_scan)
        legend = QLabel(
            f"<span style='color:{LED_ON_IN}'>●</span> {tr('Eingang 1')} &nbsp; "
            f"<span style='color:{LED_ON_OUT}'>●</span> {tr('Ausgang 1')} &nbsp; "
            f"<span style='color:{LED_OFF}'>●</span> 0 &nbsp; "
            f"<span style='background:{STATUS_BG['ok']}'>&nbsp;✓&nbsp;</span> {tr('geprüft')} &nbsp; "
            f"<span style='background:{STATUS_BG['fehler']}'>&nbsp;✗&nbsp;</span> {tr('Fehler')} &nbsp; "
            f"<span style='color:#1e88e5'>●</span> {tr('0→1 gesehen')} &nbsp; "
            f"<span style='color:#fbc02d'>▢</span> {tr('eben gewechselt')}")
        mrow.addWidget(legend)
        mrow.addStretch(1)
        mv.addLayout(mrow)
        hint = QLabel(tr("Klick: Signal wählen · Doppelklick: OK an/aus · Rechtsklick: Status"))
        hint.setObjectName("muted")
        mv.addWidget(hint)
        self.matrix = MatrixWidget()
        self.matrix.selected.connect(self._matrix_selected)
        self.matrix.status_request.connect(lambda s, st: self.set_status([s], st))
        sa = QScrollArea()
        sa.setWidget(self.matrix)
        sa.setWidgetResizable(False)
        mv.addWidget(sa, 1)
        self.tabs.addTab(mpage, tr("Matrix"))

        # --- Was hat sich bewegt?
        side = QWidget()
        sv = QVBoxLayout(side)
        sv.setContentsMargins(4, 0, 0, 0)
        title = QLabel(f"<b>{tr('Was hat sich bewegt?')}</b>")
        sv.addWidget(title)
        self.lbl_expected = QLabel()
        self.lbl_expected.setWordWrap(True)
        sv.addWidget(self.lbl_expected)
        self.lbl_swap = QLabel()
        self.lbl_swap.setWordWrap(True)
        self.lbl_swap.setStyleSheet("QLabel{background:#c62828;color:white;font-weight:bold;padding:6px;"
                                    "border-radius:4px}")
        self.lbl_swap.setVisible(False)
        sv.addWidget(self.lbl_swap)
        self.last_big = QLabel()
        f = self.last_big.font()
        f.setPointSizeF(f.pointSizeF() * 1.5)
        f.setBold(True)
        self.last_big.setFont(f)
        self.last_big.setWordWrap(True)
        sv.addWidget(self.last_big)
        self.changes = QTableWidget(0, 3)
        self.changes.setHorizontalHeaderLabels([tr("Zeit"), tr("Signal"), tr("Wechsel")])
        self.changes.verticalHeader().setVisible(False)
        self.changes.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.changes.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.changes.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.changes.cellDoubleClicked.connect(self._change_clicked)
        sv.addWidget(self.changes, 1)
        split.addWidget(side)
        self.side = side
        self.side.setVisible(self.act_moved.isChecked())
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setSizes([900, 360])
        self.setCentralWidget(split)

    # ------------------------------------------------------------------ Daten
    @staticmethod
    def _load_plcs(path):
        """Steuerungen aus der Konfiguration (Fehler: keine)."""
        try:
            return load_plcs(path) if path else []
        except Exception:
            return []

    def _rebuild(self):
        """Signale (IO-Liste + Scan-Bereiche) neu zusammenstellen, Tabelle und Matrix füllen."""
        was_running = bool(self.readers)
        if was_running:
            self.stop_reading()
        sigs = list(self.project.signals)
        existing = {s.key: s for s in sigs}
        for rng in self.project.scans:
            drv = self._plc_for(rng.plc)
            if drv is None:
                continue
            try:
                for s in io.scan_signals(rng, drv.driver, existing):
                    if s.key not in existing:
                        existing[s.key] = s
                        sigs.append(s)
            except Exception as e:
                self.statusBar().showMessage(tr("Bereich {0}: {1}").format(rng.start, e), 8000)
        self.all_signals = sigs
        self.model.set_signals(sigs)
        self._apply_columns()
        groups = sorted({s.group for s in sigs if s.group})
        cur = self.cb_group.currentData()
        self.cb_group.blockSignals(True)
        self.cb_group.clear()
        self.cb_group.addItem(tr("Alle Gruppen"), "")
        for g in groups:
            self.cb_group.addItem(g, g)
        self.cb_group.setCurrentIndex(max(0, self.cb_group.findData(cur)))
        self.cb_group.blockSignals(False)
        self._apply_filter()
        rows = io.matrix_rows(sigs)
        self.matrix.set_rows(rows)
        self.bridge.publish(sigs, self.tracker, self._project_title(), rows)
        self.bridge.source, self.bridge.plcs = self.project.path, list(self.plcs)
        from plc_common import logo_paths
        self.bridge.logos = logo_paths(self._conn())
        self._update_progress()
        self._update_title()
        if was_running:
            self.start_reading()

    def _toggle_moved(self, on):
        """Seitenleiste „Was hat sich bewegt?“ zeigen/verbergen und die Wahl merken."""
        self.side.setVisible(on)
        try:
            from plc_common import save_settings
            save_settings(iocheck_bewegt=bool(on))
        except Exception:
            pass

    def _apply_columns(self):
        """Spalten abgeschalteter Felder (leere Überschriften, siehe „Spalten …“) in der Signalliste ausblenden."""
        off = io.disabled_fields()
        for key, _t in COLS:
            self.view.setColumnHidden(COL[key], key in off)

    def _apply_filter(self, *_):
        """Suchfeld und Auswahl (Gruppe, Typ, Status) auf die Signalliste anwenden."""
        self.proxy.set_filter(self.ed_filter.text(), self.cb_group.currentData() or "",
                              self.cb_kind.currentData() or "", self.cb_status.currentData() or "")

    def _plc_for(self, name):
        """Steuerung zum Namen aus der IO-Liste (leer = erste); ohne Konfiguration im Demo-Modus eine Demo-Steuerung."""
        if not self.plcs:
            return Plc(name="Demo", driver="s7") if self.chk_demo.isChecked() else None
        for p in self.plcs:
            if p.name == name:
                return p
        return self.plcs[0] if not name else None

    def _update_title(self):
        """Fenstertitel mit Dateiname und * bei ungespeicherten Änderungen."""
        name = os.path.basename(self.project.path) if self.project.path else tr("(nicht gespeichert)")
        self.setWindowTitle(f"{tr('IO-Check')} – {name}{' *' if self.dirty else ''}")

    def _update_progress(self):
        """Fortschrittsbalken: geprüft von gesamt, mit OK/Fehler/übersprungen."""
        pr = io.progress(self.all_signals)
        done = pr["ok"] + pr["fehler"] + pr["uebersprungen"]
        self.progress.setMaximum(max(1, pr["gesamt"]))
        self.progress.setValue(done)
        self.progress.setFormat(tr("{0} von {1} geprüft – {2} OK, {3} Fehler, {4} übersprungen").format(
            done, pr["gesamt"], pr["ok"], pr["fehler"], pr["uebersprungen"]))

    def _mark_dirty(self):
        """Änderung vermerken; ist der Prüfstand schon gespeichert, sofort automatisch speichern (nichts geht verloren).
        """
        self.dirty = True
        self._update_progress()
        self._update_title()
        if self.project.path:                 # mit Dateiname: automatisch speichern (nichts geht verloren)
            try:
                self.project.options = self._options()
                self.project.save()
                self.dirty = False
                self._update_title()
            except OSError as e:
                self.statusBar().showMessage(tr("Speichern fehlgeschlagen: {0}").format(e), 8000)

    def _options(self):
        """Optionen für die Prüfstand-Datei."""
        return {"auto_ok": self.chk_auto.isChecked(), "tolerance": self.sp_tol.value()}

    def _options_changed(self, *_):
        """Optionen an den Tracker weitergeben."""
        self.tracker.auto_ok = self.chk_auto.isChecked()
        self.tracker.tolerance = self.sp_tol.value()
        self.analog.refresh()

    # ------------------------------------------------------------------ Datei
    def import_list(self):
        """IO-Liste importieren; bei vorhandener Liste fragen, ob ersetzt oder ergänzt wird (Ergänzen übernimmt nur neue
        Adressen).
        """
        path, _f = QFileDialog.getOpenFileName(self, tr("IO-Liste importieren"), "",
                                               tr("Tabellen (*.xlsx *.xlsm *.ods *.csv *.txt);;Alle Dateien (*)"))
        if not path:
            return
        try:
            header, rows = io.read_list(path)
            sigs, warnings = io.import_rows(header, rows)
        except Exception as e:
            QMessageBox.warning(self, tr("IO-Liste importieren"), str(e))
            return
        found = io.map_columns(header)
        cols_text = ", ".join(f"{tr(io.FIELD_TEXT[f])} = „{header[i]}“" for f, i in found.items())
        if not sigs:
            QMessageBox.information(self, tr("IO-Liste importieren"), tr("Keine Signale gefunden."))
            return
        replace = True
        if self.project.signals:
            box = QMessageBox(QMessageBox.Icon.Question, tr("IO-Liste importieren"),
                              tr("{0} Signale gelesen. Vorhandene Liste ersetzen oder ergänzen?").format(len(sigs)),
                              parent=self)
            b_rep = box.addButton(tr("Ersetzen"), QMessageBox.ButtonRole.AcceptRole)
            b_add = box.addButton(tr("Ergänzen"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            if box.clickedButton() not in (b_rep, b_add):
                return
            replace = box.clickedButton() is b_rep
        if replace:
            self.project.signals = sigs
        else:
            have = {s.key for s in self.project.signals}
            self.project.signals += [s for s in sigs if s.key not in have]
        counts = {k: sum(1 for s in sigs if s.kind == k) for k in io.KINDS}
        msg = tr("{0} Signale übernommen: {1} DI, {2} DO, {3} AI, {4} AO.").format(
            len(sigs), counts["DI"], counts["DO"], counts["AI"], counts["AO"])
        msg += "\n\n" + tr("Erkannte Spalten: {0}").format(cols_text)
        if warnings:
            msg += "\n\n" + "\n".join(warnings[:15]) + ("\n…" if len(warnings) > 15 else "")
        self._rebuild()
        self._mark_dirty()
        QMessageBox.information(self, tr("IO-Liste importieren"), msg)

    def edit_columns(self):
        """Dialog „Spalten der IO-Liste“; nach OK speichern und die Signalliste anpassen. Wirkt auf den nächsten Import
        (schon eingelesene Angaben bleiben erhalten, abgeschaltete Spalten werden nur ausgeblendet)."""
        dlg = ColumnsDialog(self, io.load_aliases())
        if dlg.exec():
            io.save_aliases(dlg.aliases)
            self._apply_columns()

    def open_project(self, path=None):
        """Prüfstand öffnen (fragt vorher nach dem Speichern); seine Konfiguration liefert die Steuerungen, falls noch
        keine geladen sind.
        """
        if not self._confirm_discard():
            return
        if not path:
            path, _f = QFileDialog.getOpenFileName(self, tr("IO-Check öffnen"), "",
                                                   tr("IO-Check (*.iocheck.json);;Alle Dateien (*)"))
            if not path:
                return
        try:
            proj = io.IoProject.load(path)
        except Exception as e:
            QMessageBox.warning(self, tr("IO-Check öffnen"), str(e))
            return
        self.stop_reading()
        if proj.config and os.path.exists(proj.config) and (not self.plcs or not self.project.config):
            self.plcs = self._load_plcs(proj.config)
        proj.config = proj.config or self.project.config
        self.project = proj
        self.chk_auto.setChecked(bool(proj.options.get("auto_ok", False)))
        self.sp_tol.setValue(float(proj.options.get("tolerance", 1.0)))
        self.dirty = False
        self._rebuild()
        self._remember(path)

    @staticmethod
    def _remember(path):
        """Prüfstand für das Startbild des IO-Checks merken (Fehler sind unkritisch)."""
        try:
            from plc_common import remember_iocheck
            remember_iocheck(path)
        except Exception:
            pass

    def save_project(self, as_new=False):
        """Prüfstand speichern (``as_new`` oder ohne Dateiname: Dateidialog) -> True bei Erfolg."""
        path = self.project.path
        if as_new or not path:
            path, _f = QFileDialog.getSaveFileName(self, tr("IO-Check speichern"), path or "io-check" + io.EXTENSION,
                                                   tr("IO-Check (*.iocheck.json)"))
            if not path:
                return False
            if not path.endswith(".json"):
                path += io.EXTENSION
        try:
            self.project.options = self._options()
            self.project.save(path)
        except OSError as e:
            QMessageBox.warning(self, tr("IO-Check speichern"), str(e))
            return False
        self.dirty = False
        self._update_title()
        self.bridge.source = path
        self.bridge.set_title(self._project_title())
        self.statusBar().showMessage(tr("Gespeichert: {0}").format(path), 5000)
        self._remember(path)
        return True

    def export_result(self):
        """Ergebnis als Excel- oder CSV-Datei speichern."""
        path, _f = QFileDialog.getSaveFileName(self, tr("Ergebnis exportieren"), "io-check-ergebnis.xlsx",
                                               tr("Excel (*.xlsx);;CSV (*.csv)"))
        if not path:
            return
        try:
            io.write_result(path, self.all_signals)
        except Exception as e:
            QMessageBox.warning(self, tr("Ergebnis exportieren"), str(e))
            return
        self.statusBar().showMessage(tr("Ergebnis gespeichert: {0}").format(path), 6000)

    def edit_scans(self):
        """Dialog „Bereiche scannen“; danach Liste und Matrix neu aufbauen und zur Matrix wechseln."""
        plcs = self.plcs or ([Plc(name="Demo", driver="s7")] if self.chk_demo.isChecked() else [])
        if not plcs:
            QMessageBox.information(self, tr("Bereiche scannen"), tr("In der Konfiguration ist keine Steuerung "
                                                                     "angelegt (oder „Demo“ einschalten)."))
            return
        dlg = ScanDialog(self, self.project.scans, plcs)
        if dlg.exec():
            self.project.scans = dlg.scans
            self._rebuild()
            self._mark_dirty()
            self.tabs.setCurrentIndex(1)

    def _confirm_discard(self):
        """Ungespeicherte Änderungen? Speichern, verwerfen oder abbrechen -> True = weitermachen."""
        if not self.dirty or not self.all_signals:
            return True
        r = QMessageBox.question(self, tr("IO-Check"), tr("Der Prüfstand ist nicht gespeichert. Jetzt speichern?"),
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                                 | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Save:
            return self.save_project()
        return r == QMessageBox.StandardButton.Discard

    def closeEvent(self, ev):
        """Schließen: Lesen stoppen, von der Webseite abmelden, eigenen Webserver beenden."""
        if not self._confirm_discard():
            ev.ignore()
            return
        self.stop_reading()
        try:
            import plc_web
            if plc_web.io_bridge() is self.bridge:
                plc_web.set_io_bridge(None)
        except Exception:
            pass
        if self.web is not None:
            self.web.stop()
            self.web = None
        ev.accept()

    # ------------------------------------------------------------------ Protokoll und Webseite
    def _conn(self):
        """Einstellungen der Konfiguration (für Projektname und Webserver)."""
        from plc_common import default_connection, load_config
        try:
            return load_config(self.project.config)[0] if self.project.config else default_connection()
        except Exception:
            return default_connection()

    def _project_title(self):
        """Titel für Webseite und Protokoll: Projektname der Konfiguration, sonst Name der Prüfstand-Datei."""
        name = self._conn().get("projekt", "") if self.project.config else ""
        return name or (os.path.basename(self.project.path).replace(io.EXTENSION, "") if self.project.path else "")

    def make_protocol(self):
        """Abnahmeprotokoll (PDF) erzeugen und mit dem Standardprogramm öffnen."""
        if not self.all_signals:
            QMessageBox.information(self, tr("IO-Check"), tr("Zuerst eine IO-Liste importieren oder Bereiche scannen."))
            return
        base = os.path.splitext(self.project.path.replace(io.EXTENSION, ""))[0] if self.project.path else "io-check"
        path, _f = QFileDialog.getSaveFileName(self, tr("Protokoll (PDF)"), base + "_protokoll.pdf", tr("PDF (*.pdf)"))
        if not path:
            return
        try:
            from plc_common import logo_paths
            io.write_protocol(path, self.all_signals, self._project_title(), self.project.path, self.plcs,
                              logo_paths(self._conn()))
        except Exception as e:
            QMessageBox.warning(self, tr("Protokoll (PDF)"), str(e))
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def show_mobile(self):
        """Adresse der Mobilseite mit QR-Code zeigen.

        Läuft im Programm schon ein Webserver (Logger), wird er verwendet; sonst startet der IO-Check einen eigenen mit
        den Einstellungen der Konfiguration (ist der Port belegt, einen der nächsten fünf).
        """
        try:
            import plc_web
        except Exception as e:
            QMessageBox.warning(self, tr("Mobil"), tr("Webserver nicht verfügbar: {0}").format(e))
            return
        srv = plc_web.RUNNING[0] if plc_web.RUNNING else None
        conn = self._conn()
        if srv is None:
            srv = plc_web.WebServer.from_conn(lambda: None, conn)
            port, err = srv.port, None
            for p in range(port, port + 6):             # Port belegt (z. B. Logger in einem anderen Programm)?
                srv.port = p
                try:
                    srv.start()
                    err = None
                    break
                except OSError as e:
                    err = e
                except Exception as e:                  # HTTPS: Zertifikat/Bibliothek
                    err = e
                    break
            if err is not None:
                QMessageBox.warning(self, tr("Mobil"), tr("Der Webserver konnte nicht gestartet werden: {0}").format(err))
                return
            self.web = srv
        url = srv.url() + "io"
        if srv.token and not srv.users:
            url += "?token=" + srv.token
        QApplication.clipboard().setText(url)
        lines = [tr("Im Browser des Smartphones oder Tablets öffnen (gleiches Netz):"), f"<p style='font-size:15pt'>"
                 f"<b>{url}</b></p>", tr("Die Adresse wurde in die Zwischenablage kopiert.")]
        if srv.users:
            lines.append(tr("Anmeldung mit den Benutzern des Webservers; der Anmeldename wird als Prüfer eingetragen."))
        else:
            lines.append("<span style='color:#c62828'>" + tr(
                "Ohne Benutzer kann jeder im Netz den Prüfstatus ändern. Benutzer im Konfigurationsprogramm (Reiter "
                "Webserver) anlegen – der Anmeldename wird dann als Prüfer eingetragen.") + "</span>")
        if srv.https:
            lines.append(tr("HTTPS-Fingerabdruck (SHA-256): {0}").format(srv.fingerprint()))
        lines.insert(1, tr("Oder den QR-Code mit der Kamera des Smartphones scannen."))
        self.mobile_dialog = qr_dialog(self, tr("IO-Check auf Smartphone/Tablet"), url, "<br>".join(lines))
        self.mobile_dialog.exec()

    # ------------------------------------------------------------------ Status
    def selected_signals(self):
        """In der Tabelle markierte Signale (über den Filter auf die Zeilen des Modells umgerechnet)."""
        rows = sorted({self.proxy.mapToSource(i).row() for i in self.view.selectionModel().selectedRows()})
        return [self.model.signals[r] for r in rows]

    def set_selected_status(self, status):
        """Status der markierten Signale setzen (ohne Markierung: das gerade geprüfte Signal)."""
        sigs = self.selected_signals()
        if not sigs and self.tracker.expected is not None:
            sigs = [self.tracker.expected]
        self.set_status(sigs, status)

    def set_status(self, sigs, status):
        """Status setzen; bei „Fehler“ wird eine Bemerkung abgefragt."""
        if not sigs:
            return
        remark = None
        if status == "fehler":
            text, ok = QInputDialog.getText(self, tr("Fehler"), tr("Bemerkung (z. B. Verdrahtung, Sensor defekt):"),
                                            text=sigs[0].remark)
            if not ok:
                return
            remark = text
        for s in sigs:
            io.set_status(s, status, remark=remark)
        self.model.refresh_rows(sigs)
        self.matrix.update()
        self._mark_dirty()

    def _signal_edited(self, sig):
        """Signal im Analogfeld geändert: Zeile neu zeichnen und speichern."""
        self.model.refresh_rows([sig])
        self._mark_dirty()

    # ------------------------------------------------------------------ Auswahl = erwartetes Signal
    def _row_changed(self, cur, _prev):
        """Andere Zeile gewählt: dieses Signal wird das erwartete (für Vertauschungen und Analogfeld)."""
        if not cur.isValid():
            return
        sig = self.model.signals[self.proxy.mapToSource(cur).row()]
        self._set_expected(sig)

    def _matrix_selected(self, sig):
        """In der Matrix gewählt: erwartetes Signal setzen und in der Tabelle markieren."""
        self._set_expected(sig)
        self._select_in_view(sig)

    def _select_in_view(self, sig):
        """Signal in der Tabelle markieren und hinscrollen, ohne die Auswahl-Signale auszulösen."""
        try:
            row = next(r for r, s in enumerate(self.model.signals) if s is sig)
        except StopIteration:
            return
        idx = self.proxy.mapFromSource(self.model.index(row, 0))
        if idx.isValid():
            self.view.selectionModel().blockSignals(True)
            self.view.selectRow(idx.row())
            self.view.selectionModel().blockSignals(False)
            self.view.scrollTo(idx)

    def _set_expected(self, sig):
        """Erwartetes (gerade geprüftes) Signal setzen: Tracker, Matrix, Analogfeld und Anzeige „Erwartet“."""
        self.tracker.expected = sig
        self.matrix.current = sig
        self.matrix.update()
        self.analog.set_signal(sig)
        txt = f"{sig.address} {sig.symbol}".strip()
        if sig.comment:
            txt += f" – {sig.comment}"
        self.lbl_expected.setText(tr("Erwartet: {0}").format(txt))

    def _change_clicked(self, row, _col):
        """Doppelklick auf einen Wechsel: dieses Signal wählen."""
        if 0 <= row < len(self.tracker.history):
            sig = self.tracker.history[row].sig
            self._set_expected(sig)
            self._select_in_view(sig)

    # ------------------------------------------------------------------ Lesen
    def toggle_reading(self):
        """Lesen starten bzw. stoppen (Knopf und F5)."""
        if self.readers:
            self.stop_reading()
        else:
            self.start_reading()

    def start_reading(self):
        """Signale den Steuerungen zuordnen und je Steuerung einen Lese-Thread starten (Takt höchstens 200 ms)."""
        if not self.all_signals:
            QMessageBox.information(self, tr("IO-Check"), tr("Zuerst eine IO-Liste importieren oder Bereiche scannen."))
            return
        demo = self.chk_demo.isChecked()
        plcs = self.plcs or ([Plc(name="Demo", driver="s7")] if demo else [])
        if not plcs:
            QMessageBox.information(self, tr("IO-Check"), tr("In der Konfiguration ist keine Steuerung angelegt."))
            return
        groups, unknown = io.assign_plcs(self.all_signals, plcs)
        if unknown:
            self.statusBar().showMessage(tr("Unbekannte Steuerung in der IO-Liste: {0}").format(", ".join(unknown)),
                                         10000)
        self.queue = queue.Queue()
        self.reader_signals = groups
        self.plc_state = {}
        for idx, sigs in groups.items():
            r = io.IoReader(idx, plcs[idx], sigs, self.queue, interval_ms=min(plcs[idx].intervall_ms, 200), demo=demo)
            r.start()
            self.readers.append(r)
        self.act_run.setText(tr("■ Lesen stoppen"))
        self.chk_demo.setEnabled(False)

    def stop_reading(self):
        """Alle Lese-Threads beenden und die Anzeige der Steuerungen zurücksetzen."""
        for r in self.readers:
            r.stop()
        for r in self.readers:
            r.join(2.0)
        self.readers = []
        self.act_run.setText(tr("▶ Lesen starten"))
        self.chk_demo.setEnabled(True)
        self.plc_state = {}
        self.lbl_plc.setText("")
        self.bridge.set_plc_state([])

    def _tick(self):
        """Timer (150 ms): Meldungen der Lese-Threads verarbeiten (Status, Werte -> Tracker), Webbefehle übernehmen,
        Anzeige aktualisieren.
        """
        got = False
        while True:
            try:
                msg = self.queue.get_nowait()
            except queue.Empty:
                break
            if msg[0] == "status":
                self.plc_state[msg[1]] = (msg[2], msg[3])
                self._show_plc_state()
            elif msg[0] == "values":
                _k, idx, ts, values, errors = msg
                for k, (sig, v) in enumerate(zip(self.reader_signals.get(idx, []), values)):
                    self.tracker.feed(sig, v, ts, errors.get(k, ""))
                got = True
        changed = self.tracker.pop_status_changes() + self._web_commands()
        self.tracker.watched = self.bridge.watched()
        if changed:
            self.model.refresh_rows(changed)
            self._mark_dirty()
        if got or self.readers:
            self.model.refresh_values()
            self.matrix.update()
            self.analog.refresh()
            self._refresh_changes()

    def _web_commands(self):
        """Befehle der Webseite (Smartphone/Tablet) übernehmen; Prüfer = Anmeldename. Rückgabe: geänderte Signale."""
        out = []
        while True:
            try:
                cmd, sig, value, user = self.bridge.commands.get_nowait()
            except queue.Empty:
                break
            if cmd == "status":
                status, remark = value
                io.set_status(sig, status, remark=remark, checker=user)
            elif cmd == "point":
                self.tracker.take_point(sig, value, checker=user)
            elif cmd == "remark":
                sig.remark = value
            out.append(sig)
            self.statusBar().showMessage(tr("{0}: {1} – {2}").format(user, sig.label, tr(io.STATUS[sig.status])), 5000)
        if out:
            self.matrix.update()
            if self.analog.sig in out:
                self.analog.refresh()
        return out

    def _show_plc_state(self):
        """Zustand der Steuerungen in der Statusleiste (farbige Punkte) und für die Webseite."""
        colors = {"ok": "#2e7d32", "verbinde": "#b8860b", "fehler": "#c62828", "aus": "#7d8590"}
        parts = []
        plcs = self.plcs or [Plc(name="Demo", driver="s7")]
        for idx, (state, text) in sorted(self.plc_state.items()):
            name = plcs[idx].name if idx < len(plcs) else "?"
            parts.append(f"<span style='color:{colors.get(state, '#000')}'>●</span> {name}")
            if state == "fehler":
                self.statusBar().showMessage(f"{name}: {text}", 6000)
        self.lbl_plc.setText(" &nbsp; ".join(parts))
        self.bridge.set_plc_state([(plcs[i].name if i < len(plcs) else "?", st, t)
                                   for i, (st, t) in sorted(self.plc_state.items())])
        self.lbl_plc.setToolTip("\n".join(f"{plcs[i].name if i < len(plcs) else '?'}: {t}"
                                          for i, (_s, t) in sorted(self.plc_state.items())))

    def _refresh_changes(self):
        """Liste der Wechsel und großes Feld „zuletzt bewegt“ aktualisieren; bei einer möglichen Vertauschung roter
        Hinweis (10 s) und Signalton.
        """
        hist = self.tracker.history
        head = hist[0] if hist else None
        if head is self._hist_seen:
            if self.lbl_swap.isVisible() and time.time() > self._swap_until:
                self.lbl_swap.setVisible(False)
            return
        # neue Wechsel seit dem letzten Aufruf
        new = []
        for ch in hist:
            if ch is self._hist_seen:
                break
            new.append(ch)
        self._hist_seen = head
        swap = next((c for c in new if c.expected is not None), None)
        if swap is not None:
            self._swap_until = time.time() + 10.0
            self.lbl_swap.setText("⚠ " + swap.note)
            self.lbl_swap.setVisible(True)
            if not self.side.isVisible():             # Seitenleiste ausgeblendet: Hinweis in der Statuszeile
                self.statusBar().showMessage("⚠ " + swap.note, 10000)
            QApplication.beep()
        elif time.time() > self._swap_until:
            self.lbl_swap.setVisible(False)
        if head is not None:
            self.last_big.setText(f"{head.sig.label}: {self._change_text(head)}"
                                  + (f"<br><span style='font-size:9pt;font-weight:normal'>{head.sig.comment}</span>"
                                     if head.sig.comment else ""))
        self.changes.setRowCount(len(hist))
        for r, ch in enumerate(hist):
            t = time.strftime("%H:%M:%S", time.localtime(ch.ts)) + f".{int(ch.ts * 10) % 10}"
            label = f"{ch.sig.address} {ch.sig.symbol}".strip()
            items = (QTableWidgetItem(t), QTableWidgetItem(label), QTableWidgetItem(self._change_text(ch)))
            tip = ch.sig.comment + (f"\n{ch.note}" if ch.note else "")
            for c, it in enumerate(items):
                it.setToolTip(tip)
                if ch.expected is not None:
                    it.setBackground(QColor("#ffcdd2"))
                    it.setForeground(QColor("#000000"))
                self.changes.setItem(r, c, it)

    @staticmethod
    def _change_text(ch):
        """Wechsel als Text: digital „0 → 1“, analog skaliert mit Einheit."""
        s = ch.sig
        if s.binary:
            return f"{int(ch.old)} → {int(ch.new)}"
        unit = f" {s.unit}" if s.unit else ""
        return f"{io.scale(s, ch.old):.4g} → {io.scale(s, ch.new):.4g}{unit}"


def qr_pixmap(text, size=260):
    """QR-Code als Bild (QPixmap), dunkle Module schwarz auf weiß mit Ruhezone."""
    from PySide6.QtGui import QImage, QPixmap
    import plc_qr
    m = plc_qr.encode(text)
    n, border = len(m), 4
    scale = max(2, size // (n + 2 * border))
    img = QImage((n + 2 * border) * scale, (n + 2 * border) * scale, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#000000"))
    for y, row in enumerate(m):
        for x, dark in enumerate(row):
            if dark:
                p.drawRect((x + border) * scale, (y + border) * scale, scale, scale)
    p.end()
    return QPixmap.fromImage(img)


def qr_dialog(parent, title, url, html):
    """Dialog mit QR-Code, Adresse (zum Kopieren) und Hinweisen."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QHBoxLayout(dlg)
    qr = QLabel()
    try:
        qr.setPixmap(qr_pixmap(url))
    except ValueError:
        qr.setText(tr("(Adresse zu lang für einen QR-Code)"))
    qr.setToolTip(url)
    lay.addWidget(qr, 0, Qt.AlignmentFlag.AlignTop)
    right = QVBoxLayout()
    info = QLabel(html)
    info.setTextFormat(Qt.TextFormat.RichText)
    info.setWordWrap(True)
    info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    info.setMinimumWidth(360)
    right.addWidget(info, 1)
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    b_copy = bb.addButton(tr("Adresse kopieren"), QDialogButtonBox.ButtonRole.ActionRole)
    b_copy.clicked.connect(lambda: QApplication.clipboard().setText(url))
    bb.rejected.connect(dlg.reject)
    right.addWidget(bb)
    lay.addLayout(right, 1)
    return dlg


def run_iocheck(arg=None, demo=False):
    """Eigenständiger Aufruf (PLCIOCheck.exe bzw. plc_logger.py --iocheck [Konfiguration | *.iocheck.json]).

    Ohne Datei erscheint das Startbild mit den zuletzt benutzten Prüfständen und Konfigurationen (eine Konfiguration
    beginnt einen neuen Prüfstand mit deren Steuerungen)."""
    import sys
    from plc_about import install_help
    from plc_branding import app_icon, set_windows_app_id
    from plc_common import last_config_path
    from plc_i18n import install_qt
    set_windows_app_id("PLCDatenlogger.IOCheck")
    from plc_common import qt_platform_setup
    qt_platform_setup()                      # Linux/Wayland: über XWayland (siehe dort)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    install_qt(app)
    app.setWindowIcon(app_icon(program="iocheck"))
    if not arg:
        from plc_splash import choose
        start, res = choose("iocheck", last_config_path())
        start.close()
        if res is None:
            return 0
        arg, demo = res["path"], demo or res["demo"]
    project = arg if arg and arg.endswith(".json") and _is_project(arg) else ""
    config = arg if arg and not project else last_config_path()
    win = IoCheckWindow(config_path=config, demo=demo, project_path=project)
    win.show()
    install_help(app)
    return app.exec()


def _is_project(path):
    """True, wenn die JSON-Datei ein Prüfstand ist (Kennung im Dateianfang) – sonst gilt sie als Konfiguration."""
    try:
        with open(path, encoding="utf-8") as f:
            return f'"format": "{io.FORMAT}"' in f.read(400)
    except OSError:
        return False
