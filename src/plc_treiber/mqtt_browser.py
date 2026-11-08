# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Auswahldialog des Treibers „mqtt“: eine Weile am Broker mithören und die empfangenen Werte anbieten.

``listen`` (ohne Qt) abonniert einen Filter (z. B. ``#`` oder ``halle1/#``) und sammelt die Nachrichten;
``candidates`` macht daraus Variablen: Zahlen bzw. „true/false“ direkt, JSON-Nachrichten je Zahl mit Pfad
(``tele/sonoff/SENSOR|AM2301.Temperature``).
"""
import json
import re
import threading
import time

from plc_i18n import tr
from plc_treiber.mqtt import payload_value

MAX_TOPICS = 5000


class Listener:
    """Hört im Hintergrund auf einen Topic-Filter; ``messages`` {Topic: letzte Nachricht}."""

    def __init__(self, params, topic_filter="#"):
        self.params, self.filter = params, topic_filter.strip() or "#"
        self.messages = {}
        self.lock = threading.Lock()
        self.error = ""
        self.done = threading.Event()
        self.client = None

    def start(self):
        """Verbinden und abonnieren (wartet auf die Anmeldung) -> True bei Erfolg, sonst Text in ``error``."""
        from plc_mqtt import make_client, reason_ok, reason_text
        p = self.params
        ready = threading.Event()

        def on_connect(c, userdata, flags, rc, *rest):
            if reason_ok(rc):
                c.subscribe(self.filter, 0)
            else:
                self.error = tr("Broker lehnt die Anmeldung ab: {0}").format(reason_text(rc))
            ready.set()

        def on_message(c, userdata, msg):
            with self.lock:
                if msg.topic in self.messages or len(self.messages) < MAX_TOPICS:
                    self.messages[msg.topic] = msg.payload

        try:
            c = make_client("", p.get("benutzer", ""), p.get("passwort", ""), bool(p.get("tls")),
                            bool(p.get("tls_pruefen", True)), p.get("ca", ""))
            c.on_connect, c.on_message = on_connect, on_message
            c.connect(p.get("host", ""), int(p.get("port", 1883) or 1883), keepalive=30)
            c.loop_start()
            self.client = c
        except Exception as e:
            self.error = str(e) or type(e).__name__
            return False
        if not ready.wait(float(p.get("timeout_s", 5.0) or 5.0)):
            self.error = self.error or tr("Keine Antwort vom Broker")
        if self.error:
            self.stop()
            return False
        return True

    def snapshot(self):
        with self.lock:
            return dict(self.messages)

    def stop(self):
        if self.client is not None:
            try:
                self.client.disconnect()
                self.client.loop_stop()
            except Exception:
                pass
            self.client = None


def _walk(data, path, out):
    """Alle Zahlen/Wahrheitswerte einer JSON-Struktur mit Pfad sammeln (höchstens 200)."""
    if len(out) >= 200:
        return
    if isinstance(data, bool) or isinstance(data, (int, float)):
        out.append((path, float(data), "BOOL" if isinstance(data, bool) else "REAL"))
    elif isinstance(data, dict):
        for k, v in data.items():
            if re.fullmatch(r"[^.\[\]|]+", str(k)):
                _walk(v, f"{path}.{k}" if path else str(k), out)
    elif isinstance(data, list):
        for i, v in enumerate(data[:50]):
            _walk(v, f"{path}[{i}]", out)


def candidates(messages):
    """{Topic: Nachricht} -> [(Adresse, Wert, Typ, Namensvorschlag)], sortiert nach Adresse."""
    out = []
    for topic, payload in messages.items():
        name = topic.rstrip("/").split("/")[-1] or topic
        try:
            x = payload_value(payload)
            text = payload.decode("utf-8", "replace").strip().lower() if isinstance(payload, bytes) else str(payload)
            out.append((topic, x, "BOOL" if text in ("true", "false", "on", "off") else "REAL", name))
            continue
        except ValueError:
            pass
        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            continue
        found = []
        _walk(data, "", found)
        for path, x, dtype in found:
            out.append((f"{topic}|{path}", x, dtype, f"{name}_{path}".replace(".", "_").replace("[", "_")
                        .replace("]", "")))
    return sorted(out, key=lambda o: o[0].lower())


def clean_name(text):
    """Namensvorschlag für eine Variable (Buchstaben, Ziffern, _)."""
    return re.sub(r"[^\w]+", "_", text).strip("_") or "mqtt"


try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView,
                                   QLabel, QLineEdit, QPushButton, QSpinBox, QTreeWidget, QTreeWidgetItem,
                                   QVBoxLayout)
except ImportError:                    # ohne Qt nur die Hilfsfunktionen (Tests, Headless)
    QDialog = object


class MqttBrowserDialog(QDialog):
    """Mithören: Filter und Dauer wählen, „Mithören“; empfangene Werte erscheinen in der Liste (abhaken, übernehmen).
    Ergebnis: ``result_vars`` [(Name, Adresse, Typ)], ``target_index``."""

    def __init__(self, parent, plc, existing, target_labels, default_target=0):
        super().__init__(parent)
        self.plc, self.existing = plc, set(existing)
        self.result_vars = []
        self.target_index = default_target
        self.listener = None
        self.until = 0.0
        self.setWindowTitle(tr("MQTT – Topics wählen ({0})").format(plc.params.get("host", "")))
        self.resize(820, 560)
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.ed_filter = QLineEdit("#")
        self.ed_filter.setToolTip(tr("Topic-Filter: # = alles, halle1/# = alles unter halle1, +/status = …"))
        self.sp_secs = QSpinBox()
        self.sp_secs.setRange(1, 600)
        self.sp_secs.setValue(5)
        self.sp_secs.setSuffix(" s")
        self.btn_listen = QPushButton(tr("Mithören"))
        self.btn_listen.clicked.connect(self.listen)
        row.addWidget(QLabel(tr("Filter:")))
        row.addWidget(self.ed_filter, 1)
        row.addWidget(QLabel(tr("Dauer:")))
        row.addWidget(self.sp_secs)
        row.addWidget(self.btn_listen)
        lay.addLayout(row)
        self.lbl = QLabel(tr("Werte, die während des Mithörens gesendet werden, erscheinen hier. Geräte, die selten "
                             "senden, erscheinen nur mit „retained“-Nachrichten oder bei längerer Dauer."))
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Topic | Pfad"), tr("Wert"), tr("Typ")])
        self.tree.setRootIsDecorated(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.tree, 1)
        form = QFormLayout()
        self.cb_target = QComboBox()
        self.cb_target.addItems(list(target_labels))
        self.cb_target.setCurrentIndex(max(0, min(default_target, len(target_labels) - 1)))
        form.addRow(tr("Neue Variablen anlegen in:"), self.cb_target)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Auswahl übernehmen"))
        bb.accepted.connect(self.take)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.items = {}                # Adresse -> QTreeWidgetItem
        self.timer = QTimer(self)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.poll)

    def listen(self):
        """Mithören starten (bzw. erneut, vorhandene Einträge bleiben)."""
        self.stop()
        self.listener = Listener(self.plc.params, self.ed_filter.text())
        self.lbl.setText(tr("Verbinde …"))
        if not self.listener.start():
            self.lbl.setText(tr("Fehler: {0}").format(self.listener.error))
            self.listener = None
            return
        self.until = time.time() + self.sp_secs.value()
        self.btn_listen.setEnabled(False)
        self.timer.start()

    def poll(self):
        """Neue Werte in die Liste übernehmen; nach Ablauf der Dauer aufhören."""
        if self.listener is None:
            return
        self.add(candidates(self.listener.snapshot()))
        left = self.until - time.time()
        if left <= 0:
            self.stop()
            self.lbl.setText(tr("{0} Werte gefunden. Gewünschte abhaken und übernehmen.").format(len(self.items)))
        else:
            self.lbl.setText(tr("Höre mit … noch {0:.0f} s, {1} Werte").format(left, len(self.items)))

    def add(self, found):
        """Gefundene Werte eintragen bzw. aktualisieren (vorhandene Variablen ausgegraut)."""
        for address, x, dtype, name in found:
            it = self.items.get(address)
            if it is None:
                it = QTreeWidgetItem([address, "", dtype])
                it.setData(0, Qt.ItemDataRole.UserRole, (clean_name(name), address, dtype))
                if address in self.existing:
                    it.setDisabled(True)
                    it.setToolTip(0, tr("bereits vorhanden"))
                else:
                    it.setCheckState(0, Qt.CheckState.Unchecked)
                self.tree.addTopLevelItem(it)
                self.items[address] = it
            it.setText(1, f"{x:g}")

    def stop(self):
        self.timer.stop()
        if self.listener is not None:
            self.listener.stop()
            self.add(candidates(self.listener.snapshot()))
            self.listener = None
        self.btn_listen.setEnabled(True)

    def take(self):
        """Abgehakte Einträge übernehmen."""
        self.stop()
        self.result_vars = []
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if not it.isDisabled() and it.checkState(0) == Qt.CheckState.Checked:
                self.result_vars.append(it.data(0, Qt.ItemDataRole.UserRole))
        self.target_index = self.cb_target.currentIndex()
        self.accept()

    def reject(self):
        self.stop()
        super().reject()
