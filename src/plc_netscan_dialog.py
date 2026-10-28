# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Dialog „Netzwerk durchsuchen“ im Konfigurationsprogramm: erreichbare Steuerungen finden und übernehmen.

Die Suche (``plc_netscan.scan``) läuft in einem eigenen Thread; ein Timer holt Fortschritt und Ergebnis ab, die
Oberfläche bleibt bedienbar und die Suche lässt sich abbrechen. Markierte bzw. angehakte Geräte übernimmt **Als
Steuerung übernehmen** mit dem vorgeschlagenen Treiber und ihrer Adresse (Ergebnis in ``result``: [Found]).
"""
import threading

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QProgressBar, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

import plc_netscan
from plc_common import get_driver
from plc_i18n import tr

COLS = [tr("Übernehmen"), tr("Adresse"), tr("Gefunden"), tr("Gerät"), tr("Angaben"), tr("Treiber")]
(C_TAKE, C_IP, C_PROTO, C_DEV, C_INFO, C_DRV) = range(6)


class NetScanDialog(QDialog):
    """Adressbereich angeben, suchen, Treffer anhaken und als Steuerungen übernehmen."""

    def __init__(self, parent=None, known_ips=()):
        """``known_ips``: Adressen bereits konfigurierter Steuerungen (werden gekennzeichnet, nicht vorgewählt)."""
        super().__init__(parent)
        self.setWindowTitle(tr("Netzwerk durchsuchen"))
        self.resize(980, 560)
        self.known = set(known_ips)
        self.found = []
        self.result = []
        self._thread = None
        self._state = {}                         # Austausch mit dem Such-Thread: Fortschritt, Ergebnis, Fehler
        self._cancel = False

        info = QLabel(tr("Sucht im angegebenen Bereich nach Steuerungen: EtherNet/IP-Rundruf und Verbindungsversuche "
                         "auf die Ports von S7 (102), Modbus (502), EtherNet/IP (44818), OPC UA (4840), ADS (48898), "
                         "FINS (9600), SLMP (5007) und Keyence (8501). Bei S7-CPUs wird die Baugruppe ausgelesen. "
                         "Geräte hinter Routern nur, wenn ihr Bereich angegeben ist."))
        info.setWordWrap(True)
        self.ed_range = QLineEdit(plc_netscan.default_range())
        self.ed_range.setToolTip(tr("z. B. 192.168.0.0/24, 192.168.0.10-50 oder einzelne Adressen, durch Komma getrennt"))
        self.sp_timeout = QSpinBox()
        self.sp_timeout.setRange(50, 5000)
        self.sp_timeout.setValue(400)
        self.sp_timeout.setSuffix(" ms")
        self.sp_timeout.setToolTip(tr("Wartezeit je Verbindungsversuch (länger bei langsamen oder fernen Netzen)"))
        self.cb_ident = QCheckBox(tr("Gerätekennung lesen"))
        self.cb_ident.setChecked(True)
        self.cb_ident.setToolTip(tr("S7: Baugruppe und Station, EtherNet/IP: Produktname"))
        self.btn_scan = QPushButton(tr("Suchen"))
        self.btn_scan.clicked.connect(self.start_or_stop)
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("Bereich:")))
        top.addWidget(self.ed_range, 1)
        top.addWidget(QLabel(tr("Zeitlimit:")))
        top.addWidget(self.sp_timeout)
        top.addWidget(self.cb_ident)
        top.addWidget(self.btn_scan)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.lbl_status = QLabel("")
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.horizontalHeader().setSectionResizeMode(C_INFO, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        box = QDialogButtonBox()
        self.btn_take = box.addButton(tr("Als Steuerung übernehmen"), QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton(QDialogButtonBox.StandardButton.Close)
        box.accepted.connect(self.take)
        box.rejected.connect(self.reject)
        self.btn_take.setEnabled(False)

        lay = QVBoxLayout(self)
        lay.addWidget(info)
        lay.addLayout(top)
        lay.addWidget(self.progress)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.lbl_status)
        lay.addWidget(box)
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self._poll)

    # ---------------------------------------------------------------- Suche
    def start_or_stop(self):
        """Suche starten bzw. laufende Suche abbrechen."""
        if self._thread is not None and self._thread.is_alive():
            self._cancel = True
            self.btn_scan.setEnabled(False)
            self.lbl_status.setText(tr("Wird abgebrochen …"))
            return
        text = self.ed_range.text().strip()
        try:
            n = len(plc_netscan.parse_targets(text))
        except ValueError as e:
            self.lbl_status.setText(str(e))
            return
        self._cancel = False
        self._state = {"done": 0, "total": 1}
        timeout = self.sp_timeout.value() / 1000.0
        ident = self.cb_ident.isChecked()

        def work():
            try:
                self._state["result"] = plc_netscan.scan(
                    text, timeout=timeout, identify=ident, cancel=lambda: self._cancel,
                    progress=lambda d, t: self._state.update(done=d, total=t))
            except Exception as e:                         # Fehler im Thread an die Oberfläche melden
                self._state["error"] = str(e)
        self.table.setRowCount(0)
        self.btn_take.setEnabled(False)
        self.btn_scan.setText(tr("Abbrechen"))
        self.lbl_status.setText(tr("Durchsuche {0} Adressen …").format(n))
        self._thread = threading.Thread(target=work, name="netzsuche", daemon=True)
        self._thread.start()
        self.timer.start()

    def _poll(self):
        """Fortschritt anzeigen; nach dem Ende die Ergebnisse eintragen."""
        st = self._state
        self.progress.setValue(int(100 * st.get("done", 0) / max(1, st.get("total", 1))))
        if self._thread is not None and self._thread.is_alive():
            return
        self.timer.stop()
        self.btn_scan.setText(tr("Suchen"))
        self.btn_scan.setEnabled(True)
        if "error" in st:
            self.lbl_status.setText(tr("Fehler: {0}").format(st["error"]))
            return
        self.show_results(st.get("result", []), cancelled=self._cancel)

    def show_results(self, found, cancelled=False):
        """Ergebnisse in die Tabelle schreiben (neue Geräte mit Treibervorschlag sind angehakt)."""
        self.found = list(found)
        t = self.table
        t.setRowCount(0)
        for f in self.found:
            r = t.rowCount()
            t.insertRow(r)
            take = QTableWidgetItem()
            known = f.ip in self.known
            if f.driver:
                take.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                take.setCheckState(Qt.CheckState.Unchecked if known else Qt.CheckState.Checked)
            else:
                take.setFlags(Qt.ItemFlag.ItemIsEnabled)
            t.setItem(r, C_TAKE, take)
            ip = QTableWidgetItem(f.ip + (" " + tr("(schon konfiguriert)") if known else ""))
            t.setItem(r, C_IP, ip)
            t.setItem(r, C_PROTO, QTableWidgetItem(f.protocols or "EtherNet/IP"))
            t.setItem(r, C_DEV, QTableWidgetItem(f.device or "–"))
            t.setItem(r, C_INFO, QTableWidgetItem(f.details))
            drv = ""
            if f.driver:
                try:
                    drv = f"{f.driver} – {get_driver(f.driver).name}"
                except Exception:
                    drv = f.driver
            t.setItem(r, C_DRV, QTableWidgetItem(drv))
        for col in (C_TAKE, C_IP, C_PROTO, C_DEV, C_DRV):          # „Angaben“ füllt den Rest
            t.resizeColumnToContents(col)
        text = tr("{0} Geräte gefunden").format(len(self.found))
        if cancelled:
            text += " " + tr("(abgebrochen)")
        if not self.found:
            text = tr("Keine Steuerung gefunden – Bereich, Zeitlimit und Firewall prüfen.")
        self.lbl_status.setText(text)
        self.btn_take.setEnabled(any(f.driver for f in self.found))

    # ---------------------------------------------------------------- Übernehmen
    def checked(self):
        """Angehakte Geräte (mit Treibervorschlag)."""
        out = []
        for r, f in enumerate(self.found):
            it = self.table.item(r, C_TAKE)
            if f.driver and it is not None and it.checkState() == Qt.CheckState.Checked:
                out.append(f)
        return out

    def take(self):
        """Angehakte Geräte übernehmen und schließen."""
        self.result = self.checked()
        if not self.result:
            self.lbl_status.setText(tr("Bitte mindestens ein Gerät anhaken."))
            return
        self.accept()

    def reject(self):
        """Schließen bricht eine laufende Suche ab."""
        self._cancel = True
        self.timer.stop()
        super().reject()
