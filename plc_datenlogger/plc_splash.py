"""Startbild mit Auswahl der Konfiguration, Lade-Anzeige und ein verstecktes Info-Fenster.

* ``StartWindow``: erscheint beim Programmstart (Logger und Konfigurationsprogramm). Links Logo, Programmname und
  Version, rechts die zuletzt benutzten Konfigurationen sowie „Öffnen“, „Durchsuchen …“ und „Neue Konfiguration …“
  (im Logger zusätzlich „Demo“). Nach der Auswahl zeigt dasselbe Fenster den Ladefortschritt, bis das Hauptfenster
  bereit ist. „Beim Start nicht mehr anzeigen“ überspringt die Auswahl (Einstellung ``startbild``); ist beim Aufruf
  eine Datei angegeben, erscheint nur die Lade-Anzeige.
* ``LogoLabel``: Logo, das bei **Doppelklick mit gedrückter Strg- und Umschalttaste** das versteckte Info-Fenster
  ``EasterEggDialog`` öffnet (im Startbild und im Logger rechts oben).
"""
import math
import os
import platform
import random
import time

from PyQt6.QtCore import QPointF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QProgressBar, QPushButton, QVBoxLayout, QWidget)

from plc_branding import default_pixmap, logo_pixmap
from plc_common import APP_NAME, APP_VERSION, BASE_DIR, load_settings, recent_configs, save_settings
from plc_i18n import tr

START_TIME = time.time()
FILE_FILTER = tr("Konfiguration (*.ini *.txt *.cfg);;Alle Dateien (*)")
# Farben des Startbilds (dunkles Industrie-Blau mit Akzent).
C_BG1, C_BG2, C_ACCENT, C_TEXT, C_MUTED = "#0f1b2d", "#1d3557", "#4fc3f7", "#eef3f8", "#9fb3c8"

STYLE = f"""
QWidget#start {{ background: {C_BG1}; }}
QLabel {{ color: {C_TEXT}; }}
QLabel#muted {{ color: {C_MUTED}; }}
QListWidget {{ background: #13233a; color: {C_TEXT}; border: 1px solid #2c4a6e; border-radius: 4px;
               outline: none; font-size: 10pt; }}
QListWidget::item {{ padding: 6px 8px; border-bottom: 1px solid #1b304d; }}
QListWidget::item:selected {{ background: #24507e; color: white; }}
QListWidget::item:hover {{ background: #1b3a5e; }}
QPushButton {{ background: #22446b; color: {C_TEXT}; border: 1px solid #2f5d8f; border-radius: 4px;
               padding: 6px 14px; }}
QPushButton:hover {{ background: #2c5a8c; }}
QPushButton:disabled {{ color: #6f8399; background: #1a3150; }}
QPushButton#primary {{ background: #0a84d6; border-color: #3aa0e8; font-weight: bold; }}
QPushButton#primary:hover {{ background: #1993e6; }}
QPushButton#flat {{ background: transparent; border: none; color: {C_MUTED}; padding: 2px 6px; }}
QPushButton#flat:hover {{ color: white; }}
QCheckBox {{ color: {C_MUTED}; }}
QProgressBar {{ background: #13233a; border: 1px solid #2c4a6e; border-radius: 3px; height: 6px;
                text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {C_ACCENT}; border-radius: 3px; }}
"""


# ---------------------------------------------------------------------------------------
# Logo mit verstecktem Info-Fenster
# ---------------------------------------------------------------------------------------
class LogoLabel(QLabel):
    """QLabel mit Logo; Strg + Umschalt + Doppelklick öffnet das versteckte Info-Fenster."""

    def __init__(self, pixmap=None, parent=None):
        super().__init__(parent)
        if pixmap is not None:
            self.setPixmap(pixmap)

    def mouseDoubleClickEvent(self, ev):
        mods = ev.modifiers()
        if (mods & Qt.KeyboardModifier.ControlModifier) and (mods & Qt.KeyboardModifier.ShiftModifier):
            EasterEggDialog(self.window()).exec()
            return
        super().mouseDoubleClickEvent(ev)


QUOTES = [
    tr("Never change a running system – außer, die Regelparameter sind von Ziegler-Nichols."),
    tr("Es ist nicht kaputt. Es befindet sich in einem undefinierten Zustand."),
    tr("Ein Datenlogger vergisst nie. Außer, die CSV-Datei wurde nicht archiviert."),
    tr("Totzeit ist die Zeit, in der man auf die Totzeit wartet."),
    tr("Funktioniert auf der Anlage – und das zählt."),
    tr("Bit 0.0 hat heute gute Laune."),
    tr("Ohne Messung ist alles nur eine Meinung."),
    tr("Wer misst, misst Mist – wer viel misst, loggt viel Mist. Darum: Trigger setzen."),
    tr("Der PID-Regler sagt: Ich schwinge nicht, ich zeige Begeisterung."),
]


class Scope(QWidget):
    """Kleines animiertes Oszilloskop (für das Info-Fenster)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(460, 170)
        self.phase = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(30)

    def _tick(self):
        self.phase += 0.06
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#06120a"))
        p.setPen(QPen(QColor(30, 90, 50), 1))
        for i in range(1, 10):
            x = w * i / 10
            p.drawLine(int(x), 0, int(x), h)
        for i in range(1, 6):
            y = h * i / 6
            p.drawLine(0, int(y), w, int(y))
        curves = ((QColor("#39ff14"), 0.30, 1.0, 0.0),        # Istwert
                  (QColor("#ffb74d"), 0.18, 2.3, 1.1),        # Stellwert
                  (QColor("#4fc3f7"), 0.10, 5.0, 2.0))        # Rauschen
        for color, amp, freq, ph in curves:
            path = QPainterPath()
            for k in range(0, 201):
                x = w * k / 200
                t = k / 200 * 2 * math.pi
                y = h / 2 - h * amp * math.sin(freq * t + self.phase * (1 + ph / 3) + ph) \
                    * (0.6 + 0.4 * math.sin(self.phase / 3 + t))
                path.lineTo(QPointF(x, y)) if k else path.moveTo(QPointF(x, y))
            p.setPen(QPen(color, 2))
            p.drawPath(path)
        p.setPen(QColor("#39ff14"))
        p.setFont(QFont("Consolas", 9))
        p.drawText(8, 16, f"CH1 PV   CH2 CV   CH3 Δ    t = {time.time() - START_TIME:7.1f} s")
        p.end()


class EasterEggDialog(QDialog):
    """Verstecktes Info-Fenster mit Oszilloskop, Versionen und einer Weisheit des Tages."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Über {0} – psst …").format(APP_NAME))
        self.setStyleSheet(STYLE + "QDialog { background: %s; }" % C_BG1)
        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(default_pixmap(72))
        head.addWidget(logo)
        title = QLabel(tr("<div style='font-size:18pt;font-weight:bold'>{0}</div><div style='color:{1}'>Version {2} · Du hast das Geheimnis gefunden! 🎉</div>").format(APP_NAME, C_ACCENT, APP_VERSION))
        head.addWidget(title, 1)
        lay.addLayout(head)
        lay.addWidget(Scope())
        try:
            from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
            qt = tr("Qt {0} · PyQt {1}").format(QT_VERSION_STR, PYQT_VERSION_STR)
        except ImportError:
            qt = "Qt"
        info = QLabel(tr("Python {0} · {1} · {2} {3}<br>Datenordner: {4}<br>Seit dem Start vergangen: {5} s").format(platform.python_version(), qt, platform.system(), platform.machine(), BASE_DIR, int(time.time() - START_TIME)))
        info.setObjectName("muted")
        info.setWordWrap(True)
        info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(info)
        self.quote = QLabel()
        self.quote.setWordWrap(True)
        self.quote.setStyleSheet(f"color:{C_TEXT}; font-style:italic; font-size:11pt; padding:8px 2px")
        lay.addWidget(self.quote)
        row = QHBoxLayout()
        btn_more = QPushButton(tr("Noch eine Weisheit"))
        btn_more.clicked.connect(self.next_quote)
        btn_ok = QPushButton(tr("Zurück an die Arbeit"))
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(btn_more)
        row.addWidget(btn_ok)
        lay.addLayout(row)
        self.resize(560, 480)
        self.next_quote()

    def next_quote(self):
        self.quote.setText("„" + random.choice(QUOTES) + "“")


# ---------------------------------------------------------------------------------------
# Startbild
# ---------------------------------------------------------------------------------------
class _Banner(QWidget):
    """Linke Seite des Startbilds: Verlauf, Messkurven im Hintergrund, Logo, Name und Version."""

    def __init__(self, logo_path, subtitle, parent=None):
        super().__init__(parent)
        self.setFixedWidth(300)
        self.subtitle = subtitle
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 34, 28, 22)
        self.logo = LogoLabel(logo_pixmap(logo_path, 96) if logo_path else default_pixmap(96))
        self.logo.setToolTip(APP_NAME)
        lay.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addSpacing(18)
        name = QLabel(APP_NAME)
        name.setStyleSheet("font-size: 22pt; font-weight: 600; background: transparent;")
        lay.addWidget(name)
        sub = QLabel(subtitle)
        sub.setStyleSheet(f"color: {C_ACCENT}; font-size: 11pt; background: transparent;")
        lay.addWidget(sub)
        lay.addStretch(1)
        ver = QLabel(tr("Version {0}").format(APP_VERSION))
        ver.setObjectName("muted")
        ver.setStyleSheet("background: transparent;")
        lay.addWidget(ver)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0, QColor(C_BG2))
        g.setColorAt(1, QColor(C_BG1))
        p.fillRect(self.rect(), g)
        # dezente Messkurven im unteren Bereich
        w, h = self.width(), self.height()
        for color, amp, freq, ph, alpha in (("#4fc3f7", 0.06, 1.6, 0.0, 90), ("#ffb74d", 0.045, 2.4, 1.3, 70),
                                            ("#81c784", 0.03, 4.0, 2.1, 60)):
            c = QColor(color)
            c.setAlpha(alpha)
            path = QPainterPath()
            for k in range(0, 121):
                x = w * k / 120
                y = h * 0.78 - h * amp * math.sin(freq * k / 120 * 2 * math.pi + ph)
                path.lineTo(QPointF(x, y)) if k else path.moveTo(QPointF(x, y))
            p.setPen(QPen(c, 2))
            p.drawPath(path)
        p.setPen(QPen(QColor(C_ACCENT), 3))
        p.drawLine(0, 0, 0, h)
        p.end()


class StartWindow(QWidget):
    """Startbild: Auswahl der Konfiguration, danach Lade-Anzeige.

    kind: "logger" oder "config". ``chosen`` wird nach der Auswahl gesendet; Ergebnis in ``result``:
    {"path": Datei oder "", "new": bool, "demo": bool}."""

    chosen = pyqtSignal()

    def __init__(self, kind="logger", current_path="", select=True):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.kind, self.current = kind, current_path
        self.result = None
        self._drag = None
        self.setObjectName("start")
        self.setStyleSheet(STYLE)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedSize(820, 470)
        logo = ""
        try:                                           # Logo der zuletzt benutzten Konfiguration
            if current_path and os.path.exists(current_path):
                from plc_common import load_config
                logo = load_config(current_path)[0].get("logo", "")
        except Exception:
            logo = ""
        subtitle = tr("Aufzeichnung & Analyse") if kind == "logger" else tr("Konfiguration")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(_Banner(logo, subtitle))

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(26, 18, 22, 18)
        top = QHBoxLayout()
        self.lbl_head = QLabel(tr("Konfiguration wählen"))
        self.lbl_head.setStyleSheet("font-size: 14pt; font-weight: 600;")
        top.addWidget(self.lbl_head, 1)
        btn_x = QPushButton("✕")
        btn_x.setObjectName("flat")
        btn_x.setToolTip(tr("Beenden"))
        btn_x.clicked.connect(self.cancel)
        top.addWidget(btn_x)
        rl.addLayout(top)
        hint = QLabel(tr("Zuletzt benutzt:"))
        hint.setObjectName("muted")
        rl.addWidget(hint)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _it: self.open_selected())
        self.list.currentRowChanged.connect(lambda _r: self._update())
        rl.addWidget(self.list, 1)
        self._fill_recent()

        row = QHBoxLayout()
        self.btn_open = QPushButton(tr("Öffnen"))
        self.btn_open.setObjectName("primary")
        self.btn_open.clicked.connect(self.open_selected)
        btn_browse = QPushButton(tr("Durchsuchen …"))
        btn_browse.clicked.connect(self.browse)
        btn_new = QPushButton(tr("Neue Konfiguration …"))
        btn_new.clicked.connect(self.new_file)
        row.addWidget(self.btn_open)
        row.addWidget(btn_browse)
        row.addWidget(btn_new)
        if kind == "logger":
            btn_demo = QPushButton(tr("Demo"))
            btn_demo.setToolTip(tr("Mit simulierten Werten starten (ohne Steuerung)"))
            btn_demo.clicked.connect(self.demo)
            row.addWidget(btn_demo)
        row.addStretch(1)
        self.buttons = QWidget()
        self.buttons.setLayout(row)
        rl.addWidget(self.buttons)

        self.chk_skip = QCheckBox(tr("Beim Start nicht mehr anzeigen (zuletzt benutzte Datei öffnen)"))
        self.chk_skip.setChecked(not load_settings().get("startbild", True))
        rl.addWidget(self.chk_skip)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("muted")
        rl.addWidget(self.progress)
        rl.addWidget(self.lbl_status)
        outer.addWidget(right, 1)

        if not select:
            self.set_loading("Starte …")
        self._update()
        self._center()

    # ------------------------------------------------------------------ Liste
    def _fill_recent(self):
        self.list.clear()
        files = recent_configs()
        if self.current and os.path.exists(self.current) and self.current not in files:
            files.insert(0, self.current)
        for p in files:
            try:
                when = time.strftime("%d.%m.%Y %H:%M", time.localtime(os.path.getmtime(p)))
            except OSError:
                when = ""
            it = QListWidgetItem(f"{os.path.basename(p)}\n{os.path.dirname(p)}   ·   {when}")
            it.setData(Qt.ItemDataRole.UserRole, p)
            it.setToolTip(p)
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            it = QListWidgetItem(tr("Noch keine Konfiguration benutzt – „Neue Konfiguration …“ oder „Durchsuchen …“."))
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(it)

    def _update(self):
        if not hasattr(self, "btn_open"):          # Liste wird gefüllt, bevor die Knöpfe existieren
            return
        it = self.list.currentItem()
        self.btn_open.setEnabled(bool(it and it.data(Qt.ItemDataRole.UserRole)))

    def _center(self):
        scr = QApplication.primaryScreen()
        if scr is not None:
            g = scr.availableGeometry()
            self.move(g.center().x() - self.width() // 2, g.center().y() - self.height() // 2)

    # ------------------------------------------------------------------ Auswahl
    def _finish(self, path, new=False, demo=False):
        save_settings(startbild=not self.chk_skip.isChecked())
        self.result = {"path": path, "new": new, "demo": demo}
        self.set_loading("Lade …")
        self.chosen.emit()

    def open_selected(self):
        it = self.list.currentItem()
        p = it.data(Qt.ItemDataRole.UserRole) if it else None
        if p:
            self._finish(p)

    def browse(self):
        start = os.path.dirname(self.current) if self.current else BASE_DIR
        p, _flt = QFileDialog.getOpenFileName(self, tr("Konfiguration öffnen"), start, FILE_FILTER)
        if p:
            self._finish(os.path.abspath(p))

    def new_file(self):
        if self.kind == "config":
            self._finish("", new=True)
            return
        p, _flt = QFileDialog.getSaveFileName(self, tr("Neue Konfiguration anlegen"), BASE_DIR, FILE_FILTER)
        if p:
            if not os.path.splitext(p)[1]:
                p += ".ini"
            self._finish(os.path.abspath(p), new=True)

    def demo(self):
        it = self.list.currentItem()
        self._finish((it.data(Qt.ItemDataRole.UserRole) if it else "") or self.current, demo=True)

    def cancel(self):
        self.result = None
        self.close()
        self.chosen.emit()

    # ------------------------------------------------------------------ Laden
    def set_loading(self, text, percent=None):
        """Auswahl ausblenden und den Ladefortschritt zeigen."""
        self.lbl_head.setText(tr("Wird geladen …"))
        self.buttons.setVisible(False)
        self.chk_skip.setVisible(False)
        self.list.setEnabled(False)
        self.progress.setVisible(True)
        if percent is None:
            self.progress.setRange(0, 0)            # Lauflicht
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(int(percent))
        self.lbl_status.setText(text)
        QApplication.processEvents()

    # Rahmenloses Fenster mit der Maus verschieben
    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, ev):
        if self._drag is not None and ev.buttons() & Qt.MouseButton.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _ev):
        self._drag = None

    def closeEvent(self, ev):
        # Fenster ohne Auswahl geschlossen (z. B. Alt+F4): wie Abbrechen behandeln.
        if self.result is None and self.buttons.isVisible():
            self.chosen.emit()
        super().closeEvent(ev)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape and self.buttons.isVisible():
            self.cancel()
        elif ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.buttons.isVisible():
            self.open_selected()
        else:
            super().keyPressEvent(ev)


def choose(kind, current_path="", explicit=False):
    """Startbild zeigen. Ohne Auswahl (Datei angegeben oder Startbild abgeschaltet) nur die Lade-Anzeige.

    Rückgabe: (StartWindow, Ergebnis) – Ergebnis None = abgebrochen. Das Fenster bleibt offen (Lade-Anzeige), bis der
    Aufrufer ``win.close()`` aufruft."""
    select = not explicit and bool(load_settings().get("startbild", True))
    win = StartWindow(kind, current_path, select=select)
    win.show()
    QApplication.processEvents()
    if not select:
        return win, {"path": current_path, "new": False, "demo": False}
    from PyQt6.QtCore import QEventLoop
    loop = QEventLoop()
    win.chosen.connect(loop.quit)
    loop.exec()
    return win, win.result


def splash_pixmap(size=64) -> QPixmap:
    """Programmsymbol (für Fenster ohne eigenes Logo)."""
    return default_pixmap(size)

