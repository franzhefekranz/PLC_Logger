# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Dialog „Mit Logger verbinden“: Adresse, Benutzer und Passwort (bzw. Zugriffscode) eines Loggers, dessen Aufzeichnung
dieser Logger als Client anzeigt (siehe plc_client.py).

Zuletzt benutzte Verbindungen (Adresse und Benutzer, nie das Passwort) und bestätigte Fingerabdrücke selbstsignierter
Zertifikate stehen in den Einstellungen (``client_zuletzt``, ``client_zertifikate``).
"""
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
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
        """Dialog aufbauen: Adresse (mit zuletzt benutzten), Benutzer, Passwort bzw. Zugangscode, „merken“; ``initial``:
        vorgeschlagene Adresse."""
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
        self.lbl_warn = QLabel(tr("⚠ Ohne HTTPS gehen Passwort bzw. Zugriffscode unverschlüsselt über das Netz – "
                                  "Adresse mit https:// verwenden, wenn der Logger HTTPS anbietet."))
        self.lbl_warn.setWordWrap(True)
        self.lbl_warn.setStyleSheet("color:#b26a00")
        for w in (self.ed_user, self.ed_token):
            w.textChanged.connect(self._check_secure)
        self.cb_url.editTextChanged.connect(self._check_secure)
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
        lay.addWidget(self.lbl_warn)
        lay.addWidget(self.lbl_err)
        lay.addWidget(bb)
        (self.ed_pw if self.ed_user.text() else self.cb_url).setFocus()
        self._check_secure()

    def _check_secure(self, *_):
        """Hinweis zeigen, wenn Anmeldedaten ohne HTTPS übertragen würden."""
        from plc_client import is_insecure
        self.lbl_warn.setVisible(is_insecure(self.cb_url.currentText(), self.ed_user.text(), self.ed_token.text()))

    def _recent_chosen(self, i):
        """Zuletzt benutzte Adresse gewählt: den dazu gemerkten Benutzer eintragen."""
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
        """Mit den eingegebenen Daten verbinden – im Hintergrund (Anmelden und Konfiguration holen können je bis zum
        Zeitlimit dauern; der Dialog bleibt bedienbar). Unbekanntes Zertifikat: nachfragen und bei Zustimmung den
        Fingerabdruck merken und erneut verbinden. Bei Erfolg steht die Verbindung in self.connection, sonst der Fehler im
        Dialog."""
        from plc_client import ClientError, Connection
        pins = dict(load_settings().get("client_zertifikate") or {})
        self.lbl_err.setText("")
        try:
            con = Connection(self.cb_url.currentText(), self.ed_user.text(), self.ed_pw.text(), self.ed_token.text(),
                             pins=pins)
        except ClientError as e:
            self.lbl_err.setText(str(e))
            return
        self._connect(con, retry=True)

    def _connect(self, con, retry):
        """Verbindungsaufbau im Hintergrund starten; Ergebnis in _connected bzw. _failed."""
        from plc_branding import run_in_background
        self.setEnabled(False)
        run_in_background(self, tr("Mit Logger verbinden"), con.connect, lambda _k, _ms: self._connected(con),
                          error=lambda e: self._failed(con, e, retry), text=tr("Verbinde mit {0} …").format(con.url))

    def _failed(self, con, err, retry):
        """Verbindung gescheitert: unbekanntes Zertifikat -> nachfragen und einmal neu versuchen, sonst Fehler zeigen."""
        from plc_client import ClientError, LoginRequired, UntrustedCertificate
        self.setEnabled(True)
        if isinstance(err, UntrustedCertificate) and retry:
            if self.ask_trust(err):
                con.trust(err.fingerprint)
                self._connect(con, retry=False)
            return
        if isinstance(err, LoginRequired):
            self.ed_pw.setFocus()
        self.lbl_err.setText(str(err) if isinstance(err, ClientError) else tr("Fehler: {0}").format(err))

    def _connected(self, con):
        """Verbunden: Adresse/Benutzer bzw. Fingerabdrücke merken und den Dialog schließen."""
        self.setEnabled(True)
        if self.chk_remember.isChecked():
            remember(con.url, con.user, con.pins)
        else:
            save_settings(client_zertifikate=con.pins)
        self.connection = con
        self.accept()
