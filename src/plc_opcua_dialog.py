# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Dialog „OPC-UA-Server“ (Konfigurationsprogramm, Reiter Webserver & Headless)."""
import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QLabel, QLineEdit,
                               QSpinBox, QVBoxLayout)

import plc_opcua_server as us
from plc_i18n import tr


class OpcUaServerDialog(QDialog):
    """Ergebnis bei OK in self.settings (dict, wie plc_opcua_server.settings)."""

    def __init__(self, parent, settings, n_users=0):
        """Dialog aufbauen: Schalter, Adresse/Port/Aktualisierung mit angezeigtem Endpunkt, Sicherheitsstufen mit
        Zertifikat, Zugriff.

        ``settings``: gespeicherte Einstellung; ``n_users``: Zahl der Web-Benutzer (nur für die Beschriftung).
        """
        super().__init__(parent)
        self.setWindowTitle(tr("OPC-UA-Server"))
        self.settings = copy.deepcopy(us.settings(settings))
        s = self.settings
        lay = QVBoxLayout(self)
        self.chk_on = QCheckBox(tr("OPC-UA-Server starten (während der Aufzeichnung)"))
        self.chk_on.setChecked(bool(s["aktiv"]))
        lay.addWidget(self.chk_on)
        f = QFormLayout()
        self.ed_host = QLineEdit(str(s["host"]))
        self.ed_host.setToolTip(tr("0.0.0.0 = erreichbar im ganzen Netzwerk, 127.0.0.1 = nur auf diesem Rechner"))
        f.addRow(tr("Adresse (Host):"), self.ed_host)
        self.sp_port = QSpinBox()
        self.sp_port.setRange(1, 65535)
        self.sp_port.setValue(int(s["port"] or 4840))
        f.addRow(tr("Port:"), self.sp_port)
        self.sp_int = QSpinBox()
        self.sp_int.setRange(50, 60000)
        self.sp_int.setSuffix(" ms")
        self.sp_int.setValue(int(s["intervall_ms"] or 500))
        self.sp_int.setToolTip(tr("So oft werden geänderte Werte im Server aktualisiert"))
        f.addRow(tr("Aktualisierung:"), self.sp_int)
        self.lbl_url = QLabel("")
        self.lbl_url.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        f.addRow(tr("Endpunkt:"), self.lbl_url)
        lay.addLayout(f)
        self.ed_host.textChanged.connect(self._update_url)
        self.sp_port.valueChanged.connect(self._update_url)

        g_sec = QGroupBox(tr("Sicherheit (Endpunkte)"))
        v = QVBoxLayout(g_sec)
        self.chk_sec = {}
        for key in us.SECURITY:
            c = QCheckBox(us.security_label(key))
            c.setChecked(key in s["sicherheit"])
            v.addWidget(c)
            self.chk_sec[key] = c
        self.ed_cert = QLineEdit(str(s["zertifikat"]))
        self.ed_cert.setPlaceholderText(tr("leer = selbstsigniert"))
        self.ed_key = QLineEdit(str(s["schluessel"]))
        self.ed_key.setPlaceholderText(tr("leer = selbstsigniert"))
        fc = QFormLayout()
        fc.addRow(tr("Zertifikat (DER/PEM):"), self.ed_cert)
        fc.addRow(tr("Schlüssel (PEM):"), self.ed_key)
        v.addLayout(fc)
        lay.addWidget(g_sec)

        g_user = QGroupBox(tr("Zugriff"))
        v2 = QVBoxLayout(g_user)
        self.chk_anon = QCheckBox(tr("Anonym (ohne Anmeldung)"))
        self.chk_anon.setChecked(bool(s["anonym"]))
        self.chk_web = QCheckBox(tr("Anmeldung mit den Benutzern des Webservers ({0} eingerichtet)").format(n_users))
        self.chk_web.setChecked(s["benutzer"] == "web")
        v2.addWidget(self.chk_anon)
        v2.addWidget(self.chk_web)
        lay.addWidget(g_user)
        hint = QLabel(tr("Nur lesend. Firewall: eingehende Verbindungen auf dem Port erlauben. Das selbstsignierte "
                         "Zertifikat liegt im Ordner opcua des Datenordners; Clients müssen ihm ggf. vertrauen."))
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        lay.addWidget(hint)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._update_url()

    def _update_url(self):
        """Angezeigten Endpunkt nach Änderung von Adresse oder Port neu berechnen."""
        self.lbl_url.setText(us.endpoint_url({"host": self.ed_host.text().strip(), "port": self.sp_port.value()}))

    def collect(self):
        """Alle Felder in ``self.settings`` übernehmen -> Einstellungen (dict); ohne gewählte Sicherheitsstufe gilt
        „Keine“.
        """
        s = self.settings
        s.update(aktiv=self.chk_on.isChecked(), host=self.ed_host.text().strip() or "0.0.0.0",
                 port=self.sp_port.value(), intervall_ms=self.sp_int.value(),
                 sicherheit=[k for k, c in self.chk_sec.items() if c.isChecked()] or ["none"],
                 anonym=self.chk_anon.isChecked(), benutzer="web" if self.chk_web.isChecked() else "",
                 zertifikat=self.ed_cert.text().strip(), schluessel=self.ed_key.text().strip())
        return s

    def _ok(self):
        """OK: Felder übernehmen und schließen."""
        self.collect()
        self.accept()
