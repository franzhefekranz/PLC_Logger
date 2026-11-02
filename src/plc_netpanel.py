# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Netzwerk-Panel für einen Touchscreen am Raspberry Pi (Programm ``plc-netzwerk``, Startparameter ``--netzwerk``).

Läuft bildschirmfüllend direkt auf dem Display – ohne Desktop (Qt-Plattform ``eglfs`` bzw. ``linuxfb``) – und zeigt:

* **Übersicht:** Rechnername, Uhrzeit, Ethernet und WLAN mit IP-Adressen, Zustand des Logger-Dienstes, Adresse des
  Webservers mit QR-Code (aus der Konfigurationsdatei, falls angegeben).
* **IP-Einstellung** je Schnittstelle: DHCP oder feste Adresse (IP/Präfix, Gateway, DNS) mit Zifferntastatur.
* **WLAN:** ein/aus, Netze suchen, verbinden (Passwort über die Bildschirmtastatur).
* **Datum und Uhrzeit:** von Hand stellen, Internetzeit (NTP) ein/aus, Zeitzone; Uhrzeit aus einer Steuerung der
  Konfiguration lesen und übernehmen – auf Wunsch automatisch (beim Start und stündlich, solange keine Internetzeit
  synchronisiert ist). Treiber mit Uhrzeit: s7, clx, opcua (``Driver.read_clock``).

Eingestellt wird über NetworkManager bzw. timedatectl (plc_netz); die Befehle laufen in einem Hintergrund-Thread, damit
die Oberfläche bedienbar bleibt. Ohne NetworkManager zeigt das Panel nur die Adressen an. Die Einstellungen des Panels
(Steuerung für die Uhrzeit, automatisch, Uhr der Steuerung in UTC) stehen in ``plc_netzwerk.json`` im Datenordner.
"""
import datetime
import json
import os
import sys
import threading

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QApplication, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScroller,
    QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

import plc_netz
from plc_i18n import tr

STYLE = """
QWidget { background: #1b2a41; color: #f0f0f0; }
QPushButton { background: #2f4566; border: 1px solid #4a6a96; border-radius: 8px; padding: 6px 10px; }
QPushButton:pressed, QPushButton:checked { background: #e08a1e; color: #111; }
QPushButton:disabled { color: #7a8aa0; }
QLineEdit { background: #f5f5f5; color: #111; border-radius: 6px; padding: 4px 8px; }
QLineEdit:focus { border: 3px solid #e08a1e; }
QListWidget { background: #24385a; border-radius: 8px; }
QListWidget::item { padding: 10px; border-bottom: 1px solid #33496c; }
QListWidget::item:selected { background: #e08a1e; color: #111; }
QLabel#titel { font-weight: bold; }
QLabel#fehler { color: #ff8a80; }
QLabel#ok { color: #a5d6a7; }
"""


class QrLabel(QWidget):
    """QR-Code (plc_qr) als Bild; leer ohne Text."""

    def __init__(self):
        super().__init__()
        self.matrix = None
        self.setMinimumSize(QSize(120, 120))

    def set_text(self, text):
        self.matrix = None
        if text:
            try:
                from plc_qr import encode
                self.matrix = encode(text)
            except Exception:
                self.matrix = None
        self.update()

    def paintEvent(self, _ev):
        if not self.matrix:
            return
        p = QPainter(self)
        n = len(self.matrix) + 8
        size = min(self.width(), self.height())
        cell = size / n
        x0 = (self.width() - size) / 2
        y0 = (self.height() - size) / 2
        p.fillRect(QRectF(x0, y0, size, size), QColor("white"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("black"))
        for r, row in enumerate(self.matrix):
            for c, dark in enumerate(row):
                if dark:
                    p.drawRect(QRectF(x0 + (c + 4) * cell, y0 + (r + 4) * cell, cell + 0.5, cell + 0.5))
        p.end()


class Keyboard(QWidget):
    """Bildschirmtastatur: schreibt in das zuletzt angetippte Eingabefeld. ``numeric``: nur Ziffern, Punkt, /."""

    ROWS = ["1234567890", "qwertzuiop", "asdfghjkl", "yxcvbnm"]
    SYMBOLS = ["1234567890", "!\"§$%&/()=", "?@#+-_.,:;", "*'<>|[]{}"]

    def __init__(self, numeric=False):
        super().__init__()
        self.target = None
        self.shift = False
        self.symbols = False
        self.numeric = numeric
        self.grid = QGridLayout(self)
        self.grid.setSpacing(4)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self._build()

    def _key(self, text, slot, span=1):
        b = QPushButton(text)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        b.clicked.connect(slot)
        return b, span

    def _build(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        if self.numeric:
            keys = ["789", "456", "123", "0./"]
            for r, row in enumerate(keys):
                for c, ch in enumerate(row):
                    b, _ = self._key(ch, lambda _=False, ch=ch: self.type(ch))
                    self.grid.addWidget(b, r, c)
            b, _ = self._key("⌫", self.backspace)
            self.grid.addWidget(b, 0, 3, 2, 1)
            b, _ = self._key(tr("Leeren"), self.clear)
            self.grid.addWidget(b, 2, 3, 2, 1)
            return
        rows = self.SYMBOLS if self.symbols else self.ROWS
        for r, row in enumerate(rows):
            for c, ch in enumerate(row):
                shown = ch.upper() if self.shift and not self.symbols else ch
                b, _ = self._key(shown, lambda _=False, s=shown: self.type(s))
                self.grid.addWidget(b, r, c)
        last = len(rows)
        b, _ = self._key("⇧", self.toggle_shift)
        self.grid.addWidget(b, last, 0, 1, 2)
        b, _ = self._key("abc" if self.symbols else "?#1", self.toggle_symbols)
        self.grid.addWidget(b, last, 2, 1, 2)
        b, _ = self._key(tr("Leertaste"), lambda: self.type(" "))
        self.grid.addWidget(b, last, 4, 1, 4)
        b, _ = self._key("⌫", self.backspace)
        self.grid.addWidget(b, last, 8, 1, 2)

    def type(self, text):
        if self.target is not None:
            self.target.insert(text)
        if self.shift and not self.symbols:
            self.shift = False
            self._build()

    def backspace(self):
        if self.target is not None:
            self.target.backspace()

    def clear(self):
        if self.target is not None:
            self.target.clear()

    def toggle_shift(self):
        self.shift = not self.shift
        self._build()

    def toggle_symbols(self):
        self.symbols = not self.symbols
        self._build()


class TouchEdit(QLineEdit):
    """Eingabefeld, das beim Antippen die Bildschirmtastatur auf sich richtet."""

    def __init__(self, keyboard, password=False):
        super().__init__()
        self.keyboard = keyboard
        if password:
            self.setEchoMode(QLineEdit.EchoMode.Password)

    def focusInEvent(self, ev):
        self.keyboard.target = self
        super().focusInEvent(ev)


class Stepper(QWidget):
    """Zahl mit großen Tasten ▲/▼ (Touch): ``value`` zwischen ``lo`` und ``hi``, am Ende geht es von vorn los."""

    def __init__(self, label, lo, hi, width=2, changed=None):
        super().__init__()
        self.lo, self.hi, self.width, self.changed = lo, hi, width, changed
        self.value = lo
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        t = QLabel(label)
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(t)
        for text, step in (("▲", 1), (None, 0), ("▼", -1)):
            if text is None:
                self.lbl = QLabel()
                self.lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.lbl.setObjectName("titel")
                v.addWidget(self.lbl)
                continue
            b = QPushButton(text)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setMinimumHeight(48)
            b.setAutoRepeat(True)
            b.setAutoRepeatDelay(400)
            b.setAutoRepeatInterval(120)
            b.clicked.connect(lambda _=False, d=step: self.step(d))
            v.addWidget(b)
        self.set_value(lo, notify=False)

    def set_range(self, lo, hi):
        self.lo, self.hi = lo, hi
        self.set_value(min(max(self.value, lo), hi), notify=False)

    def set_value(self, value, notify=True):
        self.value = int(value)
        self.lbl.setText(str(self.value).zfill(self.width))
        if notify and self.changed:
            self.changed()

    def step(self, d):
        n = self.hi - self.lo + 1
        self.set_value(self.lo + (self.value - self.lo + d) % n)


SETTINGS_FILE = "plc_netzwerk.json"


def load_settings():
    """Einstellungen des Panels (Datenordner) -> dict."""
    from plc_common import BASE_DIR
    try:
        with open(os.path.join(BASE_DIR, SETTINGS_FILE), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data):
    from plc_common import BASE_DIR
    try:
        os.makedirs(BASE_DIR, exist_ok=True)
        with open(os.path.join(BASE_DIR, SETTINGS_FILE), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def clock_plcs(config_path):
    """Aktive Steuerungen der Konfiguration, deren Treiber die Uhrzeit lesen kann -> [(Plc, Treiber)]."""
    if not config_path:
        return []
    try:
        from plc_common import get_driver, load_plcs
        out = []
        for p in load_plcs(config_path):
            try:
                d = get_driver(p.driver)
            except Exception:
                continue
            if p.enabled and d.clock_support:
                out.append((p, d))
        return out
    except Exception:
        return []


class NetPanel(QWidget):
    """Hauptfenster des Panels mit den Seiten Übersicht, IP-Einstellung, WLAN und WLAN-Passwort."""

    SYNC_LIMIT_S = 2.0              # automatisch: erst ab dieser Abweichung stellen
    SYNC_EVERY_MS = 3600 * 1000     # automatisch: stündlich

    def __init__(self, netz=None, config_path="", service="plc-datenlogger", background=True, settings=None):
        super().__init__()
        self.netz = netz or plc_netz.Netz()
        self.config_path = config_path
        self.settings = load_settings() if settings is None else settings
        self.clock_plcs = clock_plcs(config_path)
        self.plc_time = None                    # zuletzt gelesene Uhrzeit der Steuerung (Ortszeit) und Lesezeitpunkt
        self.timezones = []
        self.service = service
        self.background = background            # Befehle im Hintergrund-Thread (Tests: False)
        self.devs = []
        self.edit_dev = None
        self.wifis = []
        self.chosen_wifi = None
        self._job = None
        self.setWindowTitle(tr("PLC Datenlogger – Netzwerk"))
        self.setStyleSheet(STYLE)
        self.stack = QStackedWidget()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(self.stack)
        self.page_home = self._build_home()
        self.page_ip = self._build_ip()
        self.page_wifi = self._build_wifi()
        self.page_pw = self._build_password()
        self.page_time = self._build_time()
        self.page_tz = self._build_timezone()
        for p in (self.page_home, self.page_ip, self.page_wifi, self.page_pw, self.page_time, self.page_tz):
            self.stack.addWidget(p)
        self.timer = QTimer(self)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self.refresh)
        self.clock = QTimer(self)
        self.clock.setInterval(1000)
        self.clock.timeout.connect(self._tick)
        self.poll = QTimer(self)
        self.poll.setInterval(200)
        self.poll.timeout.connect(self._poll_job)
        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(self.SYNC_EVERY_MS)
        self.sync_timer.timeout.connect(self.auto_sync)
        self.refresh()
        self.timer.start()
        self.clock.start()
        self.sync_timer.start()
        if background and self.settings.get("uhr_auto") and self.clock_plcs:
            QTimer.singleShot(15000, self.auto_sync)            # beim Start: Steuerung braucht evtl. etwas länger

    # ------------------------------------------------------------------ Seiten
    @staticmethod
    def _button(text, slot, checkable=False):
        b = QPushButton(text)
        b.setCheckable(checkable)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setMinimumHeight(56)
        b.clicked.connect(slot)
        return b

    def _build_home(self):
        w = QWidget()
        v = QVBoxLayout(w)
        top = QHBoxLayout()
        self.lbl_host = QLabel()
        self.lbl_host.setObjectName("titel")
        self.lbl_clock = QLabel()
        top.addWidget(self.lbl_host, 1)
        top.addWidget(self.lbl_clock)
        v.addLayout(top)
        mid = QHBoxLayout()
        self.lbl_info = QLabel()
        self.lbl_info.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_info.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.lbl_info.setWordWrap(True)
        mid.addWidget(self.lbl_info, 2)
        self.qr = QrLabel()
        mid.addWidget(self.qr, 1)
        v.addLayout(mid, 1)
        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        v.addWidget(self.lbl_status)
        row = QHBoxLayout()
        self.btn_eth = self._button(tr("Ethernet"), lambda: self.show_ip("ethernet"))
        self.btn_wifi = self._button(tr("WLAN"), self.show_wifi)
        self.btn_time = self._button(tr("Uhrzeit"), self.show_time)
        row.addWidget(self.btn_eth)
        row.addWidget(self.btn_wifi)
        row.addWidget(self.btn_time)
        row.addWidget(self._button(tr("Aktualisieren"), self.refresh))
        v.addLayout(row)
        return w

    def _build_ip(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.lbl_ip_title = QLabel()
        self.lbl_ip_title.setObjectName("titel")
        v.addWidget(self.lbl_ip_title)
        h = QHBoxLayout()
        self.btn_dhcp = self._button(tr("DHCP (automatisch)"), lambda: self._set_mode(True), checkable=True)
        self.btn_manual = self._button(tr("Feste Adresse"), lambda: self._set_mode(False), checkable=True)
        h.addWidget(self.btn_dhcp)
        h.addWidget(self.btn_manual)
        v.addLayout(h)
        body = QHBoxLayout()
        form = QGridLayout()
        self.numpad = Keyboard(numeric=True)
        self.ed_addr = TouchEdit(self.numpad)
        self.ed_addr.setPlaceholderText("192.168.0.50/24")
        self.ed_gw = TouchEdit(self.numpad)
        self.ed_gw.setPlaceholderText("192.168.0.1")
        self.ed_dns = TouchEdit(self.numpad)
        self.ed_dns.setPlaceholderText(tr("leer = keiner"))
        for r, (text, ed) in enumerate(((tr("IP/Präfix"), self.ed_addr), (tr("Gateway"), self.ed_gw),
                                        (tr("DNS"), self.ed_dns))):
            form.addWidget(QLabel(text), r, 0)
            ed.setMinimumHeight(48)
            form.addWidget(ed, r, 1)
        fw = QWidget()
        fw.setLayout(form)
        body.addWidget(fw, 3)
        body.addWidget(self.numpad, 2)
        v.addLayout(body, 1)
        self.lbl_ip_msg = QLabel()
        self.lbl_ip_msg.setWordWrap(True)
        v.addWidget(self.lbl_ip_msg)
        row = QHBoxLayout()
        row.addWidget(self._button(tr("Zurück"), self.show_home))
        self.btn_apply = self._button(tr("Übernehmen"), self.apply_ip)
        row.addWidget(self.btn_apply)
        v.addLayout(row)
        return w

    def _build_wifi(self):
        w = QWidget()
        v = QVBoxLayout(w)
        h = QHBoxLayout()
        t = QLabel(tr("WLAN"))
        t.setObjectName("titel")
        h.addWidget(t, 1)
        self.btn_wifi_on = self._button(tr("WLAN an"), self.toggle_wifi, checkable=True)
        h.addWidget(self.btn_wifi_on)
        v.addLayout(h)
        self.list_wifi = QListWidget()
        self.list_wifi.itemClicked.connect(self.choose_wifi)
        v.addWidget(self.list_wifi, 1)
        self.lbl_wifi_msg = QLabel()
        self.lbl_wifi_msg.setWordWrap(True)
        v.addWidget(self.lbl_wifi_msg)
        row = QHBoxLayout()
        row.addWidget(self._button(tr("Zurück"), self.show_home))
        row.addWidget(self._button(tr("Suchen"), self.scan_wifi))
        row.addWidget(self._button(tr("IP-Einstellung"), lambda: self.show_ip("wifi")))
        v.addLayout(row)
        return w

    def _build_password(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.lbl_pw_title = QLabel()
        self.lbl_pw_title.setObjectName("titel")
        v.addWidget(self.lbl_pw_title)
        self.keyboard = Keyboard()
        self.ed_pw = TouchEdit(self.keyboard, password=True)
        self.ed_pw.setMinimumHeight(48)
        self.ed_pw.setPlaceholderText(tr("Passwort"))
        h = QHBoxLayout()
        h.addWidget(self.ed_pw, 1)
        self.btn_show_pw = self._button(tr("Zeigen"), self._toggle_pw, checkable=True)
        h.addWidget(self.btn_show_pw)
        v.addLayout(h)
        v.addWidget(self.keyboard, 1)
        self.lbl_pw_msg = QLabel()
        v.addWidget(self.lbl_pw_msg)
        row = QHBoxLayout()
        row.addWidget(self._button(tr("Abbrechen"), self.show_wifi))
        self.btn_connect = self._button(tr("Verbinden"), self.connect_wifi)
        row.addWidget(self.btn_connect)
        v.addLayout(row)
        return w

    def _build_time(self):
        w = QWidget()
        v = QVBoxLayout(w)
        h = QHBoxLayout()
        t = QLabel(tr("Datum und Uhrzeit"))
        t.setObjectName("titel")
        h.addWidget(t, 1)
        self.btn_ntp = self._button(tr("Internetzeit (NTP)"), self.toggle_ntp, checkable=True)
        h.addWidget(self.btn_ntp)
        v.addLayout(h)
        self.lbl_time_info = QLabel()
        self.lbl_time_info.setWordWrap(True)
        v.addWidget(self.lbl_time_info)
        steps = QHBoxLayout()
        self.st_day = Stepper(tr("Tag"), 1, 31)
        self.st_month = Stepper(tr("Monat"), 1, 12, changed=self._fix_days)
        self.st_year = Stepper(tr("Jahr"), 2020, 2099, width=4, changed=self._fix_days)
        self.st_hour = Stepper(tr("Stunde"), 0, 23)
        self.st_min = Stepper(tr("Minute"), 0, 59)
        for k, st in enumerate((self.st_day, self.st_month, self.st_year, self.st_hour, self.st_min)):
            if k == 3:
                steps.addSpacing(24)
            steps.addWidget(st, 1)
        v.addLayout(steps, 1)
        # Steuerung: Uhrzeit lesen und übernehmen
        prow = QHBoxLayout()
        self.btn_plc = self._button("", self.next_plc)
        self.btn_plc.setToolTip(tr("Steuerung wählen (antippen = nächste)"))
        self.btn_read_plc = self._button(tr("Lesen"), self.read_plc_clock)
        self.btn_take_plc = self._button(tr("Übernehmen"), self.take_plc_clock)
        self.btn_utc = self._button(tr("UTC"), self.toggle_utc, checkable=True)
        self.btn_utc.setToolTip(tr("Die Steuerung liefert die Uhrzeit in UTC (sonst Ortszeit) – nur bei S7 von "
                                   "Bedeutung"))
        self.btn_auto = self._button(tr("Automatisch"), self.toggle_auto, checkable=True)
        for b in (self.btn_plc, self.btn_read_plc, self.btn_take_plc, self.btn_utc, self.btn_auto):
            prow.addWidget(b)
        self.plc_row = QWidget()
        self.plc_row.setLayout(prow)
        v.addWidget(self.plc_row)
        self.lbl_time_msg = QLabel()
        self.lbl_time_msg.setWordWrap(True)
        v.addWidget(self.lbl_time_msg)
        row = QHBoxLayout()
        row.addWidget(self._button(tr("Zurück"), self.show_home))
        row.addWidget(self._button(tr("Zeitzone"), self.show_timezone))
        self.btn_set_time = self._button(tr("Uhr stellen"), self.apply_time)
        row.addWidget(self.btn_set_time)
        v.addLayout(row)
        return w

    def _build_timezone(self):
        w = QWidget()
        v = QVBoxLayout(w)
        t = QLabel(tr("Zeitzone"))
        t.setObjectName("titel")
        v.addWidget(t)
        self.list_tz = QListWidget()
        QScroller.grabGesture(self.list_tz.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
        v.addWidget(self.list_tz, 1)
        self.lbl_tz_msg = QLabel()
        v.addWidget(self.lbl_tz_msg)
        row = QHBoxLayout()
        row.addWidget(self._button(tr("Zurück"), self.show_time))
        row.addWidget(self._button(tr("Übernehmen"), self.apply_timezone))
        v.addLayout(row)
        return w

    # ------------------------------------------------------------------ Übersicht
    def _tick(self):
        self.lbl_clock.setText(datetime.datetime.now().strftime("%d.%m.%Y  %H:%M:%S"))

    def web_url(self):
        """Adresse des Logger-Webservers (aus der Konfiguration) mit der ersten IP-Adresse oder ""."""
        if not self.config_path:
            return ""
        try:
            from plc_common import load_config
            conn = load_config(self.config_path)[0]
        except Exception:
            return ""
        if not conn.get("web_aktiv"):
            return ""
        ip = next((a.split("/")[0] for d in self.devs for a in d.ipv4), "")
        if not ip:
            return ""
        scheme = "https" if conn.get("web_https") else "http"
        return f"{scheme}://{ip}:{int(conn.get('web_port', 8080) or 8080)}/"

    def refresh(self):
        """Schnittstellen und Dienst neu lesen und die Übersicht füllen."""
        try:
            self.devs = self.netz.devices()
        except Exception as e:
            self.devs = []
            self.lbl_status.setText(tr("Fehler: {0}").format(e))
        self.lbl_host.setText(plc_netz.hostname())
        self._tick()
        names = {"ethernet": tr("Ethernet"), "wifi": tr("WLAN")}
        rows = []
        for d in self.devs:
            ips = ", ".join(a for a in d.ipv4) or tr("keine Adresse")
            how = "" if not d.method else (" (" + (tr("DHCP") if d.dhcp else tr("fest")) + ")")
            extra = f" – {d.connection}" if d.typ == "wifi" and d.connection else ""
            rows.append(f"<p><b>{names.get(d.typ, d.typ)} {d.name}</b>{extra}<br>"
                        f"<span style='font-size:130%'>{ips}</span>{how}</p>")
        if not rows:
            rows.append("<p>" + tr("Keine Netzwerkschnittstelle gefunden.") + "</p>")
        state = plc_netz.service_state(self.service) if self.service else ""
        if state:
            color = "#a5d6a7" if state == "active" else "#ff8a80"
            text = {"active": tr("läuft"), "inactive": tr("gestoppt"), "failed": tr("Fehler")}.get(state, state)
            rows.append(f"<p>{tr('Logger')}: <span style='color:{color}'><b>{text}</b></span></p>")
        url = self.web_url()
        if url:
            rows.append(f"<p>{tr('Webserver')}: <b>{url}</b></p>")
        self.lbl_info.setText("".join(rows))
        self.qr.set_text(url)
        has_nm = self.netz.has_nm()
        for b in (self.btn_eth, self.btn_wifi):
            b.setEnabled(has_nm)
        if not has_nm:
            self.lbl_status.setText(tr("Ohne NetworkManager nur Anzeige (Einstellen: NetworkManager einrichten, "
                                       "siehe Anleitung)."))

    def show_home(self):
        self.refresh()
        self.stack.setCurrentWidget(self.page_home)

    # ------------------------------------------------------------------ IP-Einstellung
    def show_ip(self, typ):
        dev = next((d for d in self.devs if d.typ == typ), None)
        if dev is None:
            self.lbl_status.setText(tr("Keine Schnittstelle vom Typ {0}").format(typ))
            return
        self.edit_dev = dev
        self.lbl_ip_title.setText(tr("IP-Einstellung {0}").format(dev.name))
        self.ed_addr.setText(dev.ipv4[0] if dev.ipv4 else "")
        self.ed_gw.setText(dev.gateway)
        self.ed_dns.setText(" ".join(dev.dns))
        self._set_mode(dev.dhcp)
        self.lbl_ip_msg.setText("")
        self.stack.setCurrentWidget(self.page_ip)
        self.ed_addr.setFocus()

    def _set_mode(self, dhcp):
        self.btn_dhcp.setChecked(dhcp)
        self.btn_manual.setChecked(not dhcp)
        for ed in (self.ed_addr, self.ed_gw, self.ed_dns):
            ed.setEnabled(not dhcp)
        self.numpad.setEnabled(not dhcp)

    def apply_ip(self):
        dhcp = self.btn_dhcp.isChecked()
        addr, gw, dns = self.ed_addr.text(), self.ed_gw.text(), self.ed_dns.text()
        if not dhcp:
            err = plc_netz.check_ipv4(addr, gw, dns)
            if err:
                self._msg(self.lbl_ip_msg, err, False)
                return
        name = self.edit_dev.name
        self._msg(self.lbl_ip_msg, tr("Wird übernommen …"), True)
        self.btn_apply.setEnabled(False)
        self._run(lambda: self.netz.set_ipv4(name, dhcp, addr, gw, dns), self._ip_done)

    def _ip_done(self, err):
        self.btn_apply.setEnabled(True)
        if err:
            self._msg(self.lbl_ip_msg, tr("Fehler: {0}").format(err), False)
            return
        self._msg(self.lbl_ip_msg, tr("Übernommen."), True)
        QTimer.singleShot(1500, self.show_home)

    # ------------------------------------------------------------------ WLAN
    def show_wifi(self):
        self.lbl_wifi_msg.setText("")
        try:
            self.btn_wifi_on.setChecked(self.netz.wifi_enabled())
        except Exception as e:
            self._msg(self.lbl_wifi_msg, tr("Fehler: {0}").format(e), False)
        self.stack.setCurrentWidget(self.page_wifi)
        self.scan_wifi()

    def scan_wifi(self):
        if not self.btn_wifi_on.isChecked():
            self.list_wifi.clear()
            return
        self._msg(self.lbl_wifi_msg, tr("Suche Netze …"), True)

        def work():
            self._scan_result = self.netz.wifi_list()
        self._run(work, self._scan_done)

    def _scan_done(self, err):
        if err:
            self._msg(self.lbl_wifi_msg, tr("Fehler: {0}").format(err), False)
            return
        self.wifis = getattr(self, "_scan_result", [])
        self.list_wifi.clear()
        for w in self.wifis:
            bars = "▂▄▆█"[: max(1, min(4, w.signal // 25 + 1))]
            lock = " 🔒" if w.security and w.security != "--" else ""
            mark = "✓ " if w.active else ""
            it = QListWidgetItem(f"{mark}{w.ssid}{lock}   {bars} {w.signal} %")
            it.setSizeHint(QSize(0, 56))
            self.list_wifi.addItem(it)
        self.lbl_wifi_msg.setText(tr("{0} Netze gefunden").format(len(self.wifis)) if self.wifis
                                  else tr("Kein WLAN gefunden."))

    def toggle_wifi(self):
        on = self.btn_wifi_on.isChecked()
        self._run(lambda: self.netz.set_wifi_enabled(on), lambda err: (
            self._msg(self.lbl_wifi_msg, tr("Fehler: {0}").format(err), False) if err else self.scan_wifi()))

    def choose_wifi(self, item):
        row = self.list_wifi.row(item)
        if not 0 <= row < len(self.wifis):
            return
        self.chosen_wifi = self.wifis[row]
        self.lbl_pw_title.setText(tr("WLAN „{0}“").format(self.chosen_wifi.ssid))
        self.ed_pw.clear()
        self.lbl_pw_msg.setText("")
        self.stack.setCurrentWidget(self.page_pw)
        self.ed_pw.setFocus()

    def _toggle_pw(self):
        self.ed_pw.setEchoMode(QLineEdit.EchoMode.Normal if self.btn_show_pw.isChecked()
                               else QLineEdit.EchoMode.Password)

    def connect_wifi(self):
        if self.chosen_wifi is None:
            return
        ssid, pw = self.chosen_wifi.ssid, self.ed_pw.text()
        dev = next((d.name for d in self.devs if d.typ == "wifi"), "")
        self._msg(self.lbl_pw_msg, tr("Verbinde …"), True)
        self.btn_connect.setEnabled(False)
        self._run(lambda: self.netz.wifi_connect(ssid, pw, dev), self._wifi_done)

    def _wifi_done(self, err):
        self.btn_connect.setEnabled(True)
        if err:
            self._msg(self.lbl_pw_msg, tr("Fehler: {0}").format(err), False)
            return
        self.ed_pw.clear()
        self.show_home()

    # ------------------------------------------------------------------ Datum und Uhrzeit
    def show_time(self):
        """Seite Datum/Uhrzeit: Felder mit der aktuellen Zeit füllen."""
        now = datetime.datetime.now()
        for st, val in ((self.st_year, now.year), (self.st_month, now.month), (self.st_day, now.day),
                        (self.st_hour, now.hour), (self.st_min, now.minute)):
            st.set_value(val, notify=False)
        self._fix_days()
        info = self.netz.time_info()
        self.btn_ntp.setChecked(info.ntp)
        for b in (self.btn_ntp, self.btn_set_time):
            b.setEnabled(info.available)
        self.plc_row.setVisible(bool(self.clock_plcs))
        self.btn_utc.setChecked(bool(self.settings.get("uhr_utc")))
        self.btn_auto.setChecked(bool(self.settings.get("uhr_auto")))
        self.btn_take_plc.setEnabled(self.plc_time is not None)
        self._update_plc_button()
        self._time_info_text(info)
        self.lbl_time_msg.setText("" if info.available else
                                  tr("timedatectl fehlt – die Uhr lässt sich hier nicht stellen."))
        self.stack.setCurrentWidget(self.page_time)

    def _time_info_text(self, info=None):
        info = info or self.netz.time_info()
        parts = [tr("Zeitzone: {0}").format(info.timezone or "?")]
        if info.ntp:
            parts.append(tr("Internetzeit: synchronisiert") if info.synced else tr("Internetzeit: nicht erreichbar"))
        else:
            parts.append(tr("Internetzeit: aus"))
        self.lbl_time_info.setText("   ·   ".join(parts))

    def _fix_days(self):
        """Tage des gewählten Monats (Schaltjahr) begrenzen."""
        import calendar
        self.st_day.set_range(1, calendar.monthrange(self.st_year.value, self.st_month.value)[1])

    def chosen_time(self):
        return datetime.datetime(self.st_year.value, self.st_month.value, self.st_day.value,
                                 self.st_hour.value, self.st_min.value)

    def apply_time(self):
        """Uhr auf die eingestellte Zeit stellen (Sekunden 0; Internetzeit wird dabei ausgeschaltet)."""
        dt = self.chosen_time()
        self._msg(self.lbl_time_msg, tr("Wird gestellt …"), True)
        self._run(lambda: self.netz.set_time(dt), lambda err: self._time_done(err, dt))

    def _time_done(self, err, dt):
        if err:
            self._msg(self.lbl_time_msg, tr("Fehler: {0}").format(err), False)
            return
        self.btn_ntp.setChecked(False)
        self._time_info_text()
        self._tick()
        self._msg(self.lbl_time_msg, tr("Uhr gestellt: {0}").format(dt.strftime("%d.%m.%Y %H:%M:%S")), True)

    def toggle_ntp(self):
        on = self.btn_ntp.isChecked()
        self._run(lambda: self.netz.set_ntp(on), lambda err: (
            self._msg(self.lbl_time_msg, tr("Fehler: {0}").format(err), False) if err else
            (self._time_info_text(), self._msg(self.lbl_time_msg, tr("Internetzeit eingeschaltet") if on
                                               else tr("Internetzeit ausgeschaltet"), True))))

    def show_timezone(self):
        if not self.timezones:
            try:
                self.timezones = self.netz.timezones()
            except Exception as e:
                self._msg(self.lbl_time_msg, tr("Fehler: {0}").format(e), False)
                return
        cur = self.netz.time_info().timezone
        self.list_tz.clear()
        for z in self.timezones:
            it = QListWidgetItem(z)
            it.setSizeHint(QSize(0, 48))
            self.list_tz.addItem(it)
            if z == cur:
                self.list_tz.setCurrentItem(it)
        if self.list_tz.currentItem():
            self.list_tz.scrollToItem(self.list_tz.currentItem(), QListWidget.ScrollHint.PositionAtCenter)
        self.lbl_tz_msg.setText("")
        self.stack.setCurrentWidget(self.page_tz)

    def apply_timezone(self):
        it = self.list_tz.currentItem()
        if it is None:
            return
        tz = it.text()

        def done(err):
            if err:
                self._msg(self.lbl_tz_msg, tr("Fehler: {0}").format(err), False)
                return
            os.environ["TZ"] = tz                       # auch die Anzeige dieses Programms umstellen
            try:
                import time
                time.tzset()
            except AttributeError:
                pass
            self.show_time()
            self._msg(self.lbl_time_msg, tr("Zeitzone {0} eingestellt").format(tz), True)
        self._run(lambda: self.netz.set_timezone(tz), done)

    # Steuerung
    def current_plc(self):
        """(Plc, Treiber) der gewählten Steuerung oder None."""
        if not self.clock_plcs:
            return None
        name = self.settings.get("uhr_steuerung", "")
        return next((x for x in self.clock_plcs if x[0].name == name), self.clock_plcs[0])

    def _update_plc_button(self):
        cur = self.current_plc()
        self.btn_plc.setText(cur[0].name if cur else "")
        self.btn_plc.setEnabled(len(self.clock_plcs) > 1)

    def next_plc(self):
        cur = self.current_plc()
        if not cur:
            return
        k = (self.clock_plcs.index(cur) + 1) % len(self.clock_plcs)
        self.settings["uhr_steuerung"] = self.clock_plcs[k][0].name
        save_settings(self.settings)
        self.plc_time = None
        self.btn_take_plc.setEnabled(False)
        self._update_plc_button()

    def toggle_utc(self):
        self.settings["uhr_utc"] = self.btn_utc.isChecked()
        save_settings(self.settings)
        self.plc_time = None
        self.btn_take_plc.setEnabled(False)

    def toggle_auto(self):
        self.settings["uhr_auto"] = self.btn_auto.isChecked()
        save_settings(self.settings)
        self._msg(self.lbl_time_msg, tr("Automatisch: Uhrzeit beim Start und stündlich von der Steuerung übernehmen, "
                                        "solange keine Internetzeit synchronisiert ist.")
                  if self.settings["uhr_auto"] else tr("Automatisch aus"), True)

    def plc_local_time(self, dt):
        """Uhrzeit der Steuerung -> Ortszeit (ohne Zeitzone liefert die Steuerung Orts- bzw. – Schalter UTC – UTC)."""
        if dt.tzinfo is None and self.settings.get("uhr_utc"):
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return plc_netz.local_naive(dt) if dt.tzinfo else dt.replace(microsecond=0)

    def _read_clock(self, result):
        """Im Hintergrund: Uhr der gewählten Steuerung lesen -> result["plc"] (Ortszeit), result["at"] (Pi-Zeit)."""
        plc, drv = self.current_plc()
        dt = drv.read_clock(plc)
        result["at"] = datetime.datetime.now()
        result["plc"] = self.plc_local_time(dt)

    def read_plc_clock(self):
        cur = self.current_plc()
        if not cur:
            return
        result = {}
        self._msg(self.lbl_time_msg, tr("Lese Uhrzeit von {0} …").format(cur[0].name), True)
        self.btn_read_plc.setEnabled(False)

        def done(err):
            self.btn_read_plc.setEnabled(True)
            if err:
                self.plc_time = None
                self.btn_take_plc.setEnabled(False)
                self._msg(self.lbl_time_msg, tr("Fehler: {0}").format(err), False)
                return
            self.plc_time = (result["plc"], result["at"])
            diff = (result["plc"] - result["at"]).total_seconds()
            self.btn_take_plc.setEnabled(True)
            self._msg(self.lbl_time_msg, tr("{0}: {1}   (Abweichung zum Pi: {2:+.0f} s) – „Übernehmen“ stellt den Pi")
                      .format(cur[0].name, result["plc"].strftime("%d.%m.%Y %H:%M:%S"), diff), True)
        self._run(lambda: self._read_clock(result), done)

    def take_plc_clock(self):
        """Gelesene Uhrzeit der Steuerung übernehmen (um die seit dem Lesen vergangene Zeit weitergerechnet)."""
        if self.plc_time is None:
            return
        plc_dt, at = self.plc_time
        dt = plc_dt + (datetime.datetime.now() - at)
        self._msg(self.lbl_time_msg, tr("Wird gestellt …"), True)
        self._run(lambda: self.netz.set_time(dt), lambda err: self._time_done(err, plc_netz.local_naive(dt)))

    def auto_sync(self):
        """Automatisch: Uhr der Steuerung übernehmen, wenn keine Internetzeit synchronisiert ist und die Abweichung
        größer als SYNC_LIMIT_S ist (Meldung in der Statuszeile der Übersicht)."""
        if not self.settings.get("uhr_auto") or not self.current_plc() or self._job is not None:
            return
        info = self.netz.time_info()
        if not info.available or info.synced:
            return
        result = {}

        def work():
            self._read_clock(result)
            dt = result["plc"] + (datetime.datetime.now() - result["at"])
            result["diff"] = (dt - datetime.datetime.now()).total_seconds()
            if abs(result["diff"]) > self.SYNC_LIMIT_S:
                self.netz.set_time(dt)

        def done(err):
            name = self.current_plc()[0].name
            if err:
                self.lbl_status.setText(tr("Uhrzeit von {0}: {1}").format(name, err))
            elif abs(result.get("diff", 0)) > self.SYNC_LIMIT_S:
                self.lbl_status.setText(tr("Uhr nach {0} gestellt (Abweichung {1:+.0f} s)").format(name, result["diff"]))
            self._tick()
        self._run(work, done)

    # ------------------------------------------------------------------ Hilfen
    @staticmethod
    def _msg(label, text, ok):
        label.setObjectName("ok" if ok else "fehler")
        label.setStyleSheet("")                     # neuen Objektnamen anwenden
        label.setText(text)

    def _run(self, fn, done):
        """``fn`` im Hintergrund ausführen, danach ``done(Fehlertext oder "")`` im Oberflächen-Thread."""
        if not self.background:
            try:
                fn()
                done("")
            except Exception as e:
                done(str(e))
            return
        state = {}

        def work():
            try:
                fn()
            except Exception as e:
                state["err"] = str(e) or type(e).__name__
        th = threading.Thread(target=work, daemon=True)
        self._job = (th, state, done)
        th.start()
        self.poll.start()

    def _poll_job(self):
        if self._job is None:
            self.poll.stop()
            return
        th, state, done = self._job
        if th.is_alive():
            return
        self._job = None
        self.poll.stop()
        done(state.get("err", ""))


def _sudo_xauthority(environ=None):
    """Mit sudo in einer Desktop-/Remotedesktop-Sitzung gestartet: X-Anmeldedaten des aufrufenden Benutzers verwenden
    (sonst „Authorization required, but no authorization protocol specified“)."""
    env = os.environ if environ is None else environ
    user = env.get("SUDO_USER", "")
    if not user or not env.get("DISPLAY") or env.get("XAUTHORITY") or not hasattr(os, "geteuid") or os.geteuid():
        return ""
    try:
        import pwd
        path = os.path.join(pwd.getpwnam(user).pw_dir, ".Xauthority")
    except (ImportError, KeyError):
        return ""
    if os.path.exists(path):
        env["XAUTHORITY"] = path
        return path
    return ""


def display_platform(windowed, environ=None, platform=None, dri=None):
    """Qt-Plattform für das angeschlossene Display: ``eglfs`` (mit Grafiktreiber /dev/dri/card*), sonst ``linuxfb``.

    "" = nichts ändern: Fenster im Desktop (``--fenster``), nicht Linux oder QT_QPA_PLATFORM schon gesetzt. Auch aus
    einem Terminal im Remotedesktop gestartet geht das Panel ohne ``--fenster`` auf das Display des Rechners."""
    env = os.environ if environ is None else environ
    if windowed or not (platform or sys.platform).startswith("linux") or env.get("QT_QPA_PLATFORM"):
        return ""
    if dri is None:
        import glob
        dri = bool(glob.glob("/dev/dri/card*"))
    return "eglfs" if dri else "linuxfb"


def run_panel(config_path="", service="plc-datenlogger", windowed=False):
    """Panel starten: bildschirmfüllend auf dem Display (``eglfs`` bzw. ``linuxfb``, siehe display_platform) oder mit
    ``windowed`` als Fenster im Desktop."""
    plat = display_platform(windowed)
    if plat:
        os.environ["QT_QPA_PLATFORM"] = plat
        os.environ.setdefault("QT_QPA_EGLFS_HIDECURSOR", "1")
        for k in ("DISPLAY", "WAYLAND_DISPLAY"):          # nicht in einer (Remote-)Desktop-Sitzung öffnen
            os.environ.pop(k, None)
    else:
        _sudo_xauthority()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from plc_i18n import install_qt
    install_qt(app)
    h = app.primaryScreen().size().height() if app.primaryScreen() else 600
    f = QFont(app.font())
    f.setPixelSize(max(16, h // 26))
    app.setFont(f)
    w = NetPanel(config_path=config_path, service=service)
    if windowed:
        w.resize(800, 480)
        w.show()
    else:
        w.showFullScreen()
    return app.exec()
