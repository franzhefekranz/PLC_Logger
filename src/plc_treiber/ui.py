# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Einstellungsdialog für die Verbindungsparameter einer Steuerung – wird aus den Parametern des Treibers aufgebaut.

Jeder Param (plc_treiber.base) wird zu einem Eingabefeld: Text, Zahl, Auswahl, Passwort oder Kästchen. Parameter mit
``advanced=True`` stehen im Bereich „Erweitert“. Ergebnis nach OK: ``result`` (Dict der Parameter).
"""
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QLabel, QLineEdit, QMessageBox, QSpinBox, QVBoxLayout)

from plc_i18n import tr


def _widget(p, value):
    """Eingabefeld passend zur Art des Parameters ``p`` (int, float, choice, bool, password, Text) mit Startwert."""
    if p.kind == "int":
        w = QSpinBox()
        w.setRange(int(p.minimum), int(p.maximum))
        w.setValue(int(value))
        if p.suffix:
            w.setSuffix(p.suffix)
    elif p.kind == "float":
        w = QDoubleSpinBox()
        w.setRange(float(p.minimum), float(p.maximum))
        w.setDecimals(3)
        w.setValue(float(value))
        if p.suffix:
            w.setSuffix(p.suffix)
    elif p.kind == "choice":
        w = QComboBox()
        for key, text in p.choices:
            w.addItem(tr(text), key)
        w.setCurrentIndex(max(w.findData(value), 0))
    elif p.kind == "bool":
        w = QCheckBox()
        w.setChecked(bool(value))
    else:
        w = QLineEdit(str(value))
        if p.kind == "password":
            w.setEchoMode(QLineEdit.EchoMode.Password)
    if p.tip:
        w.setToolTip(tr(p.tip))
    return w


def _value(p, w):
    """Wert aus dem Eingabefeld ``w`` lesen (Text ohne Leerzeichen am Rand; Passwörter unverändert)."""
    if p.kind in ("int", "float"):
        return w.value()
    if p.kind == "choice":
        return w.currentData()
    if p.kind == "bool":
        return w.isChecked()
    return w.text().strip() if p.kind != "password" else w.text()


class PlcSettingsDialog(QDialog):
    """Dialog „Verbindung – Steuerung (Treiber)“; nach OK steht das Parameter-Dict in ``result``."""
    def __init__(self, parent, plc_name, driver, params):
        """Ein Feld je Parameter des Treibers (erweiterte im Bereich „Erweitert“), dazu ob die benötigte Bibliothek
        installiert ist.
        """
        super().__init__(parent)
        self.driver = driver
        self.result = None
        self.setWindowTitle(tr("Verbindung – {0} ({1})").format(plc_name, driver.name))
        lay = QVBoxLayout(self)
        if driver.description:
            info = QLabel(tr(driver.description))
            info.setWordWrap(True)
            info.setStyleSheet("color:#555")
            lay.addWidget(info)
        self.widgets = {}
        normal = QFormLayout()
        adv_box = QGroupBox(tr("Erweitert"))
        adv = QFormLayout(adv_box)
        values = driver.normalize_params(params or {})
        for p in driver.params:
            w = _widget(p, values.get(p.key, p.default))
            self.widgets[p.key] = (p, w)
            (adv if p.advanced else normal).addRow(tr(p.label) + ":", w)
        lay.addLayout(normal)
        if adv.rowCount():
            lay.addWidget(adv_box)
        # Bibliothek vorhanden?
        try:
            driver.check_library()
            lib = "<span style='color:#27ae60'>✓ " + tr("Bibliothek vorhanden") + "</span>"
        except Exception as e:
            lib = ("<span style='color:#c0392b'>✗ " + tr("Bibliothek fehlt: {0}").format(str(e).splitlines()[0])
                   + "</span>")
        if driver.library:
            lbl = QLabel(f"{driver.library}: {lib}")
            lbl.setWordWrap(True)
            lay.addWidget(lbl)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(480, 0)

    def _ok(self):
        """Werte einsammeln und vom Treiber prüfen lassen; bei Fehler Meldung und Dialog offen lassen."""
        params = {k: _value(p, w) for k, (p, w) in self.widgets.items()}
        err = self.driver.check_params(params)
        if err:
            QMessageBox.warning(self, tr("Verbindung"), err)
            return
        self.result = params
        self.accept()
