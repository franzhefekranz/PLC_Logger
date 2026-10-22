# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Dialog „Benachrichtigungen“ (Konfigurationsprogramm, Reiter Trigger & Ereignisse): wann und wohin gemeldet wird."""
import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTabWidget,
                               QVBoxLayout, QWidget)

import plc_notify as nf
from plc_events import PRIORITIES
from plc_i18n import tr


class NotifyDialog(QDialog):
    """Ergebnis bei OK in self.settings (dict, wie plc_notify.settings)."""

    def __init__(self, parent, settings, project=""):
        super().__init__(parent)
        self.setWindowTitle(tr("Benachrichtigungen"))
        self.project = project
        self.settings = copy.deepcopy(nf.settings(settings))
        s = self.settings
        lay = QVBoxLayout(self)

        self.chk_on = QCheckBox(tr("Bei Ereignissen benachrichtigen"))
        self.chk_on.setChecked(bool(s["aktiv"]))
        lay.addWidget(self.chk_on)
        gen = QGroupBox(tr("Wann"))
        f = QFormLayout(gen)
        self.cb_prio = QComboBox()
        for p in PRIORITIES:
            self.cb_prio.addItem(tr("ab {0}").format(tr(p)), p)
        self.cb_prio.setCurrentIndex(max(0, self.cb_prio.findData(s["prio_min"])))
        f.addRow(tr("Priorität:"), self.cb_prio)
        self.ed_trig = QLineEdit(s["trigger"])
        self.ed_trig.setPlaceholderText(tr("leer = alle Trigger; sonst Namen, durch Komma getrennt"))
        f.addRow(tr("Nur Trigger:"), self.ed_trig)
        self.chk_go = QCheckBox(tr("Auch melden, wenn ein Ereignis geht"))
        self.chk_go.setChecked(bool(s["gehen"]))
        f.addRow("", self.chk_go)
        self.sp_block = QSpinBox()
        self.sp_block.setRange(0, 86400)
        self.sp_block.setSuffix(" s")
        self.sp_block.setValue(int(s["sperre_s"] or 0))
        self.sp_block.setToolTip(tr("Kommt derselbe Trigger innerhalb dieser Zeit erneut, wird nicht noch einmal gemeldet "
                                    "(die nächste Meldung nennt die Zahl der unterdrückten)."))
        f.addRow(tr("Sperrzeit je Trigger:"), self.sp_block)
        lay.addWidget(gen)

        self.tabs = QTabWidget()
        self.fields = {}
        self._channel_tab("email", [("server", tr("SMTP-Server"), "smtp.firma.de"), ("port", tr("Port"), 587),
                                    ("modus", tr("Verschlüsselung"), nf.SMTP_MODES),
                                    ("benutzer", tr("Benutzer"), ""), ("passwort", tr("Passwort"), "*"),
                                    ("von", tr("Absender"), "datenlogger@firma.de"),
                                    ("an", tr("Empfänger"), "a@firma.de, b@firma.de")])
        self._channel_tab("webhook", [("art", tr("Art"), nf.WEBHOOK_KINDS),
                                      ("url", tr("Webhook-Adresse"), "https://…")],
                          tr("Teams: im Kanal einen Workflow „Bei Empfang einer Webhookanforderung posten“ anlegen und "
                             "dessen Adresse eintragen. Slack: Incoming Webhook. Allgemein: JSON an beliebige Adresse."))
        self._channel_tab("ntfy", [("url", tr("Adresse mit Thema"), "https://ntfy.sh/mein-geheimes-thema"),
                                   ("token", tr("Zugriffstoken"), "*")],
                          tr("App „ntfy“ auf dem Handy installieren und dasselbe Thema abonnieren. Bei ntfy.sh ist das "
                             "Thema öffentlich: einen schwer zu erratenden Namen wählen oder einen eigenen Server "
                             "verwenden."))
        self._channel_tab("telegram", [("token", tr("Bot-Token"), "*"), ("chat", tr("Chat-ID"), "123456789")],
                          tr("Bot bei @BotFather anlegen, dem Bot eine Nachricht schreiben und die Chat-ID eintragen."))
        lay.addWidget(self.tabs)
        hint = QLabel(tr("Passwörter und Token stehen im Klartext in der Konfigurationsdatei."))
        hint.setObjectName("muted")
        lay.addWidget(hint)

        row = QHBoxLayout()
        b_test = QPushButton(tr("Testnachricht senden"))
        b_test.setToolTip(tr("Über alle eingeschalteten Kanäle eine Testnachricht senden"))
        b_test.clicked.connect(self.send_test)
        row.addWidget(b_test)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        lay.addLayout(row)
        self.resize(560, 560)

    def _channel_tab(self, key, spec, help_text=""):
        c = self.settings[key]
        page = QWidget()
        v = QVBoxLayout(page)
        chk = QCheckBox(tr("{0} verwenden").format(tr(nf.CHANNELS[key])))
        chk.setChecked(bool(c.get("aktiv")))
        v.addWidget(chk)
        form = QFormLayout()
        widgets = {"aktiv": chk}
        for name, label, example in spec:
            if isinstance(example, dict):
                w = QComboBox()
                for k, t in example.items():
                    w.addItem(tr(t), k)
                w.setCurrentIndex(max(0, w.findData(c.get(name))))
            elif isinstance(example, int):
                w = QSpinBox()
                w.setRange(1, 65535)
                w.setValue(int(c.get(name) or example))
            else:
                w = QLineEdit(str(c.get(name, "")))
                if example == "*":
                    w.setEchoMode(QLineEdit.EchoMode.Password)
                else:
                    w.setPlaceholderText(example)
            form.addRow(label + ":", w)
            widgets[name] = w
        v.addLayout(form)
        if help_text:
            lbl = QLabel(help_text)
            lbl.setWordWrap(True)
            lbl.setObjectName("muted")
            v.addWidget(lbl)
        v.addStretch(1)
        self.fields[key] = widgets
        self.tabs.addTab(page, tr(nf.CHANNELS[key]))

    def collect(self):
        s = self.settings
        s.update(aktiv=self.chk_on.isChecked(), prio_min=self.cb_prio.currentData(), trigger=self.ed_trig.text().strip(),
                 gehen=self.chk_go.isChecked(), sperre_s=self.sp_block.value())
        for key, widgets in self.fields.items():
            for name, w in widgets.items():
                if isinstance(w, QCheckBox):
                    s[key][name] = w.isChecked()
                elif isinstance(w, QComboBox):
                    s[key][name] = w.currentData()
                elif isinstance(w, QSpinBox):
                    s[key][name] = w.value()
                else:
                    s[key][name] = w.text().strip()
        return s

    def send_test(self):
        s = self.collect()
        channels = nf.active_channels(s)
        if not channels:
            QMessageBox.information(self, tr("Testnachricht"), tr("Bitte mindestens einen Kanal einschalten."))
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            res = nf.send_all(s, nf.test_message(self.project), channels)
        finally:
            QApplication.restoreOverrideCursor()
        lines = [("✓ " if not err else "✗ ") + tr(nf.CHANNELS[ch]) + ("" if not err else f": {err}") for ch, err in res]
        (QMessageBox.information if all(not e for _c, e in res) else QMessageBox.warning)(
            self, tr("Testnachricht"), "\n".join(lines))

    def _ok(self):
        self.collect()
        self.accept()
