# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Netzwerk-Panel für einen Touchscreen am Raspberry Pi (Programm ``plc-netzwerk``, Startparameter ``--netzwerk``).

Läuft bildschirmfüllend direkt auf dem Display – ohne Desktop (Qt-Plattform ``eglfs`` bzw. ``linuxfb``) – und zeigt:

* **Übersicht:** Rechnername, Uhrzeit, Ethernet und WLAN mit IP-Adressen, Zustand des Logger-Dienstes, Adresse des
  Webservers mit QR-Code (aus der Konfigurationsdatei, falls angegeben).
* **IP-Einstellung** je Schnittstelle: DHCP oder feste Adresse (IP/Präfix, Gateway, DNS) mit Zifferntastatur.
* **WLAN:** ein/aus, Netze suchen, verbinden (Passwort über die Bildschirmtastatur).

Eingestellt wird über NetworkManager (plc_netz); die Befehle laufen in einem Hintergrund-Thread, damit die Oberfläche
bedienbar bleibt. Ohne NetworkManager zeigt das Panel nur die Adressen an.
"""
import datetime
import os
import sys
import threading

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QApplication, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
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


class NetPanel(QWidget):
    """Hauptfenster des Panels mit den Seiten Übersicht, IP-Einstellung, WLAN und WLAN-Passwort."""

    def __init__(self, netz=None, config_path="", service="plc-datenlogger", background=True):
        super().__init__()
        self.netz = netz or plc_netz.Netz()
        self.config_path = config_path
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
        for p in (self.page_home, self.page_ip, self.page_wifi, self.page_pw):
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
        self.refresh()
        self.timer.start()
        self.clock.start()

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
        row.addWidget(self.btn_eth)
        row.addWidget(self.btn_wifi)
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


def run_panel(config_path="", service="plc-datenlogger", windowed=False):
    """Panel starten (bildschirmfüllend). Ohne Desktop wählt Qt ``eglfs`` (anders: QT_QPA_PLATFORM=linuxfb)."""
    if sys.platform.startswith("linux") and not os.environ.get("QT_QPA_PLATFORM") \
            and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "eglfs"
        os.environ.setdefault("QT_QPA_EGLFS_HIDECURSOR", "1")
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
