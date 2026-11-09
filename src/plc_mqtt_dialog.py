# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Dialog „MQTT“ (Konfigurationsprogramm, Reiter Webserver & Headless): Werte an einen MQTT-Broker senden."""
import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout)

import plc_mqtt as mq
from plc_i18n import tr


class MqttDialog(QDialog):
    """Ergebnis bei OK in ``self.settings`` (dict, wie plc_mqtt.settings)."""

    def __init__(self, parent, settings, project=""):
        """Felder aus den Einstellungen füllen (``settings``: dict oder JSON wie in der Konfiguration; ``project``: für das
        vorgeschlagene Basis-Topic)."""
        super().__init__(parent)
        self.setWindowTitle(tr("MQTT"))
        self.project = project
        self.settings = copy.deepcopy(mq.settings(settings))
        s = self.settings
        lay = QVBoxLayout(self)
        self.chk_on = QCheckBox(tr("Werte an einen MQTT-Broker senden (während der Aufzeichnung)"))
        self.chk_on.setChecked(s["aktiv"])
        lay.addWidget(self.chk_on)

        g = QGroupBox(tr("Broker"))
        f = QFormLayout(g)
        self.ed_host = QLineEdit(s["host"])
        self.ed_host.setPlaceholderText(tr("z. B. 192.168.0.5 oder homeassistant.local"))
        f.addRow(tr("Adresse (Host):"), self.ed_host)
        self.sp_port = QSpinBox()
        self.sp_port.setRange(1, 65535)
        self.sp_port.setValue(s["port"])
        f.addRow(tr("Port:"), self.sp_port)
        self.chk_tls = QCheckBox(tr("TLS (verschlüsselt, meist Port 8883)"))
        self.chk_tls.setChecked(s["tls"])
        self.chk_verify = QCheckBox(tr("Zertifikat prüfen"))
        self.chk_verify.setChecked(s["tls_pruefen"])
        self.chk_verify.setToolTip(tr("Aus: auch selbstsignierte Zertifikate annehmen (nur im eigenen Netz)"))
        f.addRow("", self.chk_tls)
        f.addRow("", self.chk_verify)
        self.ed_ca = QLineEdit(s["ca"])
        self.ed_ca.setPlaceholderText(tr("leer = Zertifikate des Systems"))
        f.addRow(tr("CA-Zertifikat (Datei):"), self.ed_ca)
        self.ed_user = QLineEdit(s["benutzer"])
        self.ed_user.setPlaceholderText(tr("leer = ohne Anmeldung"))
        f.addRow(tr("Benutzer:"), self.ed_user)
        self.ed_pw = QLineEdit(s["passwort"])
        self.ed_pw.setEchoMode(QLineEdit.EchoMode.Password)
        f.addRow(tr("Passwort:"), self.ed_pw)
        self.ed_cid = QLineEdit(s["client_id"])
        self.ed_cid.setPlaceholderText(tr("leer = automatisch"))
        f.addRow(tr("Client-ID:"), self.ed_cid)
        lay.addWidget(g)

        g2 = QGroupBox(tr("Senden"))
        f2 = QFormLayout(g2)
        self.ed_base = QLineEdit(s["basis"])
        self.ed_base.setPlaceholderText(mq.base_topic({}, project))
        self.ed_base.setToolTip(tr("Topics: <Basis>/<Steuerung>/<Variable>, <Basis>/werte, <Basis>/ereignisse, "
                                   "<Basis>/status"))
        f2.addRow(tr("Basis-Topic:"), self.ed_base)
        self.cb_mode = QComboBox()
        for k, label in mq.MODES.items():
            self.cb_mode.addItem(tr(label), k)
        self.cb_mode.setCurrentIndex(max(0, self.cb_mode.findData(s["modus"])))
        f2.addRow(tr("Senden:"), self.cb_mode)
        self.sp_int = QSpinBox()
        self.sp_int.setRange(50, 3_600_000)
        self.sp_int.setSuffix(" ms")
        self.sp_int.setValue(s["intervall_ms"])
        self.sp_int.setToolTip(tr("Bei Änderung: höchstens so oft je Variable; zyklisch: alle Werte in diesem Takt"))
        f2.addRow(tr("Intervall:"), self.sp_int)
        self.cb_format = QComboBox()
        for k, label in mq.FORMATS.items():
            self.cb_format.addItem(tr(label), k)
        self.cb_format.setCurrentIndex(max(0, self.cb_format.findData(s["format"])))
        f2.addRow(tr("Format:"), self.cb_format)
        self.cb_qos = QComboBox()
        self.cb_qos.addItem(tr("0 – höchstens einmal"), 0)
        self.cb_qos.addItem(tr("1 – mindestens einmal"), 1)
        self.cb_qos.setCurrentIndex(s["qos"])
        f2.addRow(tr("QoS:"), self.cb_qos)
        self.chk_retain = QCheckBox(tr("Werte beim Broker speichern (retain)"))
        self.chk_retain.setChecked(s["retain"])
        self.chk_retain.setToolTip(tr("Neue Abonnenten erhalten sofort den letzten Wert"))
        f2.addRow("", self.chk_retain)
        self.chk_ha = QCheckBox(tr("Home-Assistant-Discovery (Variablen erscheinen dort als Sensoren)"))
        self.chk_ha.setChecked(s["ha"])
        f2.addRow("", self.chk_ha)
        self.ed_ha = QLineEdit(s["ha_prefix"])
        f2.addRow(tr("Discovery-Präfix:"), self.ed_ha)
        lay.addWidget(g2)

        self.lbl_topics = QLabel()
        self.lbl_topics.setObjectName("muted")
        self.lbl_topics.setWordWrap(True)
        self.lbl_topics.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.lbl_topics)
        btn = QPushButton(tr("Verbindung testen"))
        btn.clicked.connect(self.test_connection)
        lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        for w in (self.ed_base, self.ed_host):
            w.textChanged.connect(self._update)
        self.chk_tls.toggled.connect(self._update)
        self.chk_ha.toggled.connect(self._update)
        self.sp_port.valueChanged.connect(self._update)
        self._update()

    def _update(self):
        """Beispiel-Topics anzeigen, abhängige Felder freigeben."""
        s = self.collect()
        base = mq.base_topic(s, self.project)
        self.lbl_topics.setText(tr("{0} → {1}/<Steuerung>/<Variable>, {1}/werte, {1}/ereignisse, {1}/status")
                                .format(mq.broker_url(s), base))
        for w in (self.chk_verify, self.ed_ca):
            w.setEnabled(self.chk_tls.isChecked())
        self.ed_ha.setEnabled(self.chk_ha.isChecked())

    def collect(self):
        """Felder -> Einstellungen (dict)."""
        s = self.settings
        s.update(aktiv=self.chk_on.isChecked(), host=self.ed_host.text().strip(), port=self.sp_port.value(),
                 tls=self.chk_tls.isChecked(), tls_pruefen=self.chk_verify.isChecked(), ca=self.ed_ca.text().strip(),
                 benutzer=self.ed_user.text().strip(), passwort=self.ed_pw.text(),
                 client_id=self.ed_cid.text().strip(), basis=self.ed_base.text().strip().strip("/"),
                 modus=self.cb_mode.currentData(), intervall_ms=self.sp_int.value(),
                 format=self.cb_format.currentData(), qos=self.cb_qos.currentData(),
                 retain=self.chk_retain.isChecked(), ha=self.chk_ha.isChecked(),
                 ha_prefix=self.ed_ha.text().strip().strip("/") or "homeassistant")
        return s

    def test_connection(self):
        """Mit den eingetragenen Daten beim Broker anmelden und das Ergebnis melden."""
        import threading
        s = self.collect()
        if not s["host"]:
            QMessageBox.warning(self, tr("MQTT"), tr("Bitte die Adresse des Brokers eintragen."))
            return
        try:
            c = mq.make_client(s["client_id"], s["benutzer"], s["passwort"], s["tls"], s["tls_pruefen"], s["ca"])
            done, result = threading.Event(), []

            def on_connect(client, userdata, flags, rc, *rest):
                """Antwort des Brokers merken; der Dialog wartet höchstens 5 s darauf."""
                result.append(rc)
                done.set()
            c.on_connect = on_connect
            c.connect(s["host"], s["port"], keepalive=10)
            c.loop_start()
            ok = done.wait(5)
            c.disconnect()
            c.loop_stop()
        except Exception as e:
            QMessageBox.warning(self, tr("MQTT"), tr("Keine Verbindung zu {0}:\n{1}").format(mq.broker_url(s), e))
            return
        if ok and result and mq.reason_ok(result[0]):
            QMessageBox.information(self, tr("MQTT"), tr("Verbindung zu {0} in Ordnung.").format(mq.broker_url(s)))
        else:
            QMessageBox.warning(self, tr("MQTT"), tr("Broker lehnt die Anmeldung ab: {0}").format(
                mq.reason_text(result[0]) if result else tr("keine Antwort")))

    def _ok(self):
        """Felder übernehmen und den Dialog schließen."""
        self.collect()
        self.accept()
