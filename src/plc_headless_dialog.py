# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Dialog „Laufende Headless-Logger“ im Konfigurationsprogramm: anzeigen und sauber beenden.

Grundlage sind die Statusdateien, die jeder Headless-Logger im Datenordner (``laufend``) schreibt
(``plc_headless.running_loggers``). **Logger beenden** legt eine Beenden-Datei an; der Logger schließt daraufhin die CSV-Datei,
archiviert sie (Einstellung *Beim Beenden archivieren*) und meldet sich ab. Die Liste wird jede Sekunde erneuert.
"""
import datetime
import os

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

import plc_headless
from plc_i18n import tr

COLS = [tr("Projekt"), tr("Konfiguration"), tr("Gestartet"), tr("Rechner"), tr("PID"), tr("Webserver"), tr("Zustand")]
(C_PROJ, C_CFG, C_START, C_HOST, C_PID, C_WEB, C_STATE) = range(7)


class HeadlessDialog(QDialog):
    """Laufende Headless-Logger dieses Datenordners anzeigen und beenden."""

    def __init__(self, parent=None, run_dir=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Laufende Headless-Logger"))
        self.resize(900, 320)
        self.run_dir = run_dir
        self.loggers = []
        self._stopping = {}                       # PID -> Projekt der zum Beenden aufgeforderten Logger

        self.lbl_info = info = QLabel(tr("Headless-Logger, die mit dem Datenordner {0} laufen. „Logger beenden“ beendet den gewählten "
                         "Logger sauber: die CSV-Datei wird geschlossen und – falls eingestellt – archiviert. "
                         "Läuft der Logger als Dienst mit automatischem Neustart, startet der Dienst ihn wieder.")
                           .format(os.path.dirname(run_dir or plc_headless.RUN_DIR)))
        info.setWordWrap(True)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.horizontalHeader().setSectionResizeMode(C_CFG, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)

        box = QDialogButtonBox()
        self.btn_stop = QPushButton(tr("Logger beenden"))
        self.btn_stop.setToolTip(tr("Gewählten Headless-Logger sauber beenden"))
        self.btn_stop.clicked.connect(lambda: self.stop_selected())
        box.addButton(self.btn_stop, QDialogButtonBox.ButtonRole.ActionRole)
        box.addButton(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(info)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.lbl_status)
        lay.addWidget(box)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.refresh()
        self.timer.start()

    def refresh(self):
        """Liste neu einlesen; die Auswahl (PID) bleibt erhalten."""
        sel = self.selected()
        keep = sel["pid"] if sel else None
        self.loggers = plc_headless.running_loggers(self.run_dir)
        pids = {i["pid"] for i in self.loggers}
        for pid in [p for p in self._stopping if p not in pids]:          # inzwischen beendet
            self.lbl_status.setText(tr("Headless-Logger „{0}“ (PID {1}) wurde beendet.")
                                    .format(self._stopping.pop(pid), pid))
        t = self.table
        t.blockSignals(True)
        t.setRowCount(0)
        for info in self.loggers:
            r = t.rowCount()
            t.insertRow(r)
            start = datetime.datetime.fromtimestamp(float(info.get("start", 0))).strftime("%Y-%m-%d %H:%M:%S")
            state = tr("wird beendet …") if info.get("stop") else tr("läuft")
            cells = (info.get("projekt", ""), info.get("config", ""), start, info.get("rechner", ""),
                     str(info["pid"]), info.get("web", "") or "–", state)
            for c, text in enumerate(cells):
                it = QTableWidgetItem(str(text))
                if c == C_CFG:
                    it.setToolTip(str(text))
                t.setItem(r, c, it)
            if info["pid"] == keep:
                t.selectRow(r)
        for c in (C_PROJ, C_START, C_HOST, C_PID, C_WEB, C_STATE):
            t.resizeColumnToContents(c)
        if len(self.loggers) == 1 and keep is None:
            t.selectRow(0)
        t.blockSignals(False)
        if not self.loggers and not self._stopping and not self.lbl_status.text():
            self.lbl_status.setText(tr("Kein Headless-Logger läuft."))
        self._update_buttons()

    def selected(self):
        """Statusangaben des gewählten Loggers oder None."""
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows or rows[0].row() >= len(self.loggers):
            return None
        return self.loggers[rows[0].row()]

    def _update_buttons(self):
        sel = self.selected()
        self.btn_stop.setEnabled(bool(sel) and not sel.get("stop"))

    def stop_selected(self, confirm=True):
        """Gewählten Logger zum Beenden auffordern (mit Rückfrage)."""
        sel = self.selected()
        if not sel:
            return False
        name = sel.get("projekt", "")
        if confirm and QMessageBox.question(
                self, tr("Headless-Logger beenden"),
                tr("Headless-Logger „{0}“ (PID {1}) beenden?\nDie Aufzeichnung endet; die CSV-Datei wird "
                   "geschlossen.").format(name, sel["pid"])) != QMessageBox.StandardButton.Yes:
            return False
        try:
            plc_headless.request_stop(sel["pid"], self.run_dir)
        except OSError as e:
            self.lbl_status.setText(tr("Fehler: {0}").format(e))
            return False
        self._stopping[sel["pid"]] = name
        self.lbl_status.setText(tr("Headless-Logger „{0}“ wird beendet …").format(name))
        self.refresh()
        return True

    def done(self, r):
        self.timer.stop()
        super().done(r)

