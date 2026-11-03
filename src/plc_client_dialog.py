# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Dialog „Mit Logger verbinden“: Adresse, Benutzer und Passwort (bzw. Zugriffscode) eines Loggers, dessen Aufzeichnung
dieser Logger als Client anzeigt (siehe plc_client.py).

Zuletzt benutzte Verbindungen (Adresse und Benutzer, nie das Passwort) und bestätigte Fingerabdrücke selbstsignierter
Zertifikate stehen in den Einstellungen (``client_zuletzt``, ``client_zertifikate``).
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
                               QLineEdit, QMessageBox, QVBoxLayout)

from plc_common import load_settings, save_settings
from plc_i18n import tr

MAX_RECENT = 8


def recent_connections():
    """Zuletzt benutzte Verbindungen [{"url", "benutzer"}], neueste zuerst."""
    lst = load_settings().get("client_zuletzt") or []
    return [c for c in lst if isinstance(c, dict) and c.get("url")]


def remember(url, user, pins):
    """Verbindung (ohne Passwort) und Fingerabdrücke merken."""
    lst = [c for c in recent_connections() if c.get("url") != url]
    save_settings(client_zuletzt=([{"url": url, "benutzer": user}] + lst)[:MAX_RECENT], client_zertifikate=pins)


class ClientDialog(QDialog):
    """Verbindung zu einem Logger aufbauen; nach OK steht die angemeldete Verbindung in ``connection``."""

    def __init__(self, parent=None, url="", user=""):
        super().__init__(parent)
        self.setWindowTitle(tr("Mit Logger verbinden (Client)"))
        self.resize(560, 300)
        self.connection = None
        info = QLabel(tr("Zeigt die Aufzeichnung eines anderen Loggers an (z. B. headless auf einem Raspberry Pi) – "
                         "Diagramme, Variablen und Anzeige kommen von dort, eine eigene Konfiguration ist nicht "
                         "nötig. Dort muss der Webserver eingeschaltet sein."))
        info.setWordWrap(True)
        self.cb_url = QComboBox()
        self.cb_url.setEditable(True)
        self.cb_url.setMinimumWidth(360)
        self.cb_url.lineEdit().setPlaceholderText("https://logger-kessel:8080/")
        self.recent = recent_connections()
        for c in self.recent:
            self.cb_url.addItem(c["url"], c.get("benutzer", ""))
        self.ed_user = QLineEdit()
        self.ed_pw = QLineEdit()
        self.ed_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_token = QLineEdit()
        self.ed_token.setPlaceholderText(tr("nur ohne Benutzer"))
        self.cb_url.currentIndexChanged.connect(self._recent_chosen)
        if url:
            self.cb_url.setEditText(url)
        if user:
            self.ed_user.setText(user)
        elif self.recent and not url:
            self._recent_chosen(0)
        self.chk_remember = QCheckBox(tr("Adresse und Benutzer merken (nicht das Passwort)"))
        self.chk_remember.setChecked(True)
        self.lbl_err = QLabel("")
        self.lbl_err.setWordWrap(True)
        self.lbl_err.setStyleSheet("color:#c62828")
        form = QFormLayout()
        form.addRow(tr("Adresse:"), self.cb_url)
        form.addRow(tr("Benutzer:"), self.ed_user)
        form.addRow(tr("Passwort:"), self.ed_pw)
        form.addRow(tr("Zugriffscode:"), self.ed_token)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Verbinden"))
        bb.accepted.connect(self.try_connect)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(info)
        lay.addLayout(form)
        lay.addWidget(self.chk_remember)
        lay.addWidget(self.lbl_err)
        lay.addWidget(bb)
        (self.ed_pw if self.ed_user.text() else self.cb_url).setFocus()

    def _recent_chosen(self, i):
        if 0 <= i < len(self.recent):
            self.ed_user.setText(self.recent[i].get("benutzer", ""))

    def ask_trust(self, err):
        """Unbekanntes Zertifikat: Fingerabdruck zeigen und fragen, ob ihm vertraut wird."""
        return QMessageBox.question(
            self, tr("Zertifikat prüfen"),
            tr("Der Logger {0} verwendet ein Zertifikat, das dieser Rechner nicht kennt (z. B. selbstsigniert).\n\n"
               "SHA-256-Fingerabdruck:\n{1}\n\nVergleichen Sie ihn mit der Anzeige am Logger (Datei › "
               "Webserver-Adresse … bzw. Logdatei im Headless-Betrieb). Stimmt er überein, diesem Zertifikat "
               "vertrauen?").format(err.host, err.fingerprint)) == QMessageBox.StandardButton.Yes

    def try_connect(self):
        from plc_client import ClientError, Connection, LoginRequired, UntrustedCertificate
        pins = dict(load_settings().get("client_zertifikate") or {})
        self.lbl_err.setText("")
        try:
            con = Connection(self.cb_url.currentText(), self.ed_user.text(), self.ed_pw.text(), self.ed_token.text(),
                             pins=pins)
        except ClientError as e:
            self.lbl_err.setText(str(e))
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for _attempt in range(2):
                try:
                    con.connect()
                    break
                except UntrustedCertificate as e:
                    QApplication.restoreOverrideCursor()
                    if not self.ask_trust(e):
                        return
                    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                    con.trust(e.fingerprint)
            else:
                return
        except LoginRequired as e:
            self.lbl_err.setText(str(e))
            self.ed_pw.setFocus()
            return
        except ClientError as e:
            self.lbl_err.setText(str(e))
            return
        finally:
            while QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
        if self.chk_remember.isChecked():
            remember(con.url, con.user, con.pins)
        else:
            save_settings(client_zertifikate=con.pins)
        self.connection = con
        self.accept()
