# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Menü „Hilfe“: Bedienungsanleitung öffnen, Kontexthilfe (F1) und Dialog „Über PLC Datenlogger“.

Kontexthilfe: F1 öffnet die HTML-Fassung der Anleitung an der Stelle, die zum Fenster, Dialog, Reiter oder Feld mit
dem Eingabefokus passt. Die Zuordnung steht in HELP_TOPICS (Klassenname -> Überschrift der Anleitung) bzw. wird mit
set_help() an einzelnen Widgets hinterlegt. Die Sprungmarke wird zur Laufzeit aus der HTML-Datei gelesen
(Überschrift -> id des Abschnitts); fehlt die Überschrift, öffnet sich die Anleitung am Anfang.

Der Dialog zeigt Version, Copyright, Lizenz (LGPL-3.0-or-later), die Lizenzen der Drittkomponenten
(THIRD_PARTY_LICENSES.md) und die Versionen der verwendeten Bibliotheken. Anleitung und Lizenzdateien werden
an allen Orten gesucht, an denen sie je nach Betriebsart liegen (Quelltext, Installer, portabel, AppImage).
"""
import glob
import html
import json
import os
import platform
import re
import sys
import tempfile

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QFontDatabase, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMenu, QMessageBox,
                               QPushButton, QTabWidget, QTextBrowser, QVBoxLayout)

from plc_branding import default_pixmap
from plc_common import APP_NAME, APP_VERSION, BASE_DIR
from plc_i18n import tr

COPYRIGHT = "Copyright (C) 2026 Michael Taxis"
LICENSE_ID = "LGPL-3.0-or-later"
# Anleitung in bevorzugter Reihenfolge: PDF (enthält die Bilder), HTML (Bilder im Ordner images), Quelltext (.rst).
MANUAL_FILES = ("Bedienungsanleitung.pdf", "PLC_Datenlogger_Bedienungsanleitung_*.pdf",
                "bedienungsanleitung.html", "bedienungsanleitung.rst")
# Bibliotheken für die Versionsliste (außer Python, Qt, PySide6): (Anzeigename, Paketname, Modulname).
LIBRARIES = [("pyqtgraph", "pyqtgraph", "pyqtgraph"),
             ("NumPy", "numpy", "numpy"), ("Flask", "Flask", "flask"), ("python-snap7", "python-snap7", "snap7"),
             ("s7commplus", "s7commplus", "s7commplus"), ("pycomm3", "pycomm3", "pycomm3"),
             ("pymodbus", "pymodbus", "pymodbus"), ("pyserial", "pyserial", "serial"),
             ("asyncua", "asyncua", "asyncua"), ("PyMySQL", "PyMySQL", "pymysql"), ("psycopg", "psycopg", "psycopg"),
             ("openpyxl", "openpyxl", "openpyxl")]


def _search_dirs():
    """Ordner, in denen Anleitung und Lizenzdateien liegen können (erste Fundstelle gilt)."""
    dirs = []
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        # Installer und portable Version: Programmordner bzw. Unterordner Doku; AppImage: usr/share/doc/<Programm>.
        dirs += [os.path.join(exe_dir, "Doku"), exe_dir,
                 os.path.join(exe_dir, "..", "..", "share", "doc", os.path.basename(exe_dir)),
                 getattr(sys, "_MEIPASS", "")]
    # Quelltext: Projektordner (über src) mit build\doc (PDF aus tools/build_doc.py), doc und dist.
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here) if os.path.basename(here).lower() == "src" else here
    dirs += [os.path.join(root, "build", "doc"), os.path.join(root, "doc"), root, os.path.join(root, "dist"), BASE_DIR]
    return [os.path.normpath(d) for d in dirs if d]


def find_file(*names) -> str:
    """Erste vorhandene Datei zu den Namen (Platzhalter * erlaubt) in den Suchordnern, sonst ""."""
    for name in names:
        for folder in _search_dirs():
            hits = sorted(glob.glob(os.path.join(folder, name)))
            if hits:
                return hits[-1]                       # bei mehreren Versionen die neueste (Sortierung nach Name)
    return ""


def open_manual(parent=None):
    """Bedienungsanleitung mit dem Standardprogramm des Systems öffnen (PDF-Anzeige bzw. Browser)."""
    path = find_file(*MANUAL_FILES)
    if path and QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
        return
    if path:
        msg = tr("Die Bedienungsanleitung konnte nicht geöffnet werden:\n{0}").format(path)
    else:
        msg = tr("Die Bedienungsanleitung wurde nicht gefunden (Bedienungsanleitung.pdf bzw. "
                 "bedienungsanleitung.html im Programmordner oder im Unterordner Doku).")
    QMessageBox.warning(parent, tr("Bedienungsanleitung"), msg)


# ---- Kontexthilfe (F1) -------------------------------------------------------------------------------------------
# Überschrift der Anleitung je Fenster/Dialog (Klassenname). Wert: Text der Überschrift (wie in bedienungsanleitung.rst,
# ohne Formatierung) oder Funktion(widget) -> Überschrift. Ein Text mit "…" am Ende passt auf die erste Überschrift,
# die so beginnt.
HELP_TOPICS = {
    "StartWindow": "Startbild",
    "ConfigWindow": "Konfigurationsprogramm (plc_config.py)",
    "AssignTree": "Aufbau: Diagramme, Y-Achsen und Variablen",
    "PlcSettingsDialog": lambda w: "Treiber {0} –…".format(getattr(getattr(w, "driver", None), "id", "")),
    "SymbolBrowser": "Variablen aus der Steuerung wählen",
    "TagBrowser": "Variablen aus der Steuerung wählen",
    "OpcUaBrowserDialog": "Variablen aus der Steuerung wählen",
    "BlockSpecDialog": "Blocklesemodus",
    "BlockEditor": "Blocklesemodus",
    "FormulaEditor": "Berechnete Variablen (Formeln)",
    "TriggerEditor": "Trigger anlegen",
    "PidSetupDialog": "Einschalten (Konfigurationsprogramm)",
    "MainWindow": "Bedienelemente",
    "ChartPanel": "Seiten, Diagramme und Anordnung",
    "DbLoadDialog": "Lesemodus: Aufzeichnungen aus der Datenbank anzeigen",
    "EventViewer": "Ereignis-Viewer und Quittieren",
    "NoteDialog": "Notizen (eigene Einträge)",
    "PidTuneDialog": "Berechnen (Logger)",
    "AboutDialog": "Lizenz",
    "ExportDialog": "Werte exportieren (CSV/Excel)",
}


def set_help(widget, topic):
    """Hilfethema für ein einzelnes Widget (und alles darin) festlegen: Überschrift oder Funktion(widget)."""
    widget._help_topic = topic


def help_topic(widget):
    """Überschrift der Anleitung zum Widget: vom Widget aus nach außen die erste Zuordnung (set_help, Reiter, Klasse)."""
    w = widget
    while w is not None:
        page = w.currentWidget() if isinstance(w, QTabWidget) else None
        # set_help am Widget; Fokus auf der Reiterleiste: Thema der aktuellen Seite; sonst nach Klassenname
        for t in (getattr(w, "_help_topic", None), getattr(page, "_help_topic", None),
                  HELP_TOPICS.get(type(w).__name__)):
            if callable(t):
                t = t(w)
            if t:
                return t
        w = w.parentWidget()
    return None


def _norm(text):
    """Überschrift vergleichbar machen: ohne Formatierung, Leerraum zusammengefasst, Groß-/Kleinschreibung egal."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", text)).replace("``", "").split()).casefold()


_anchor_cache = {}


def _anchors(path):
    """Überschriften der HTML-Anleitung -> Sprungmarke (id des umgebenden Abschnitts). Zwischengespeichert."""
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return {}
    if key not in _anchor_cache:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        found = {}
        # docutils/Sphinx: <section id="..."> [<span id="label"></span>] <hN>Überschrift</hN>
        pattern = r'<section[^>]*\bid="([^"]+)"[^>]*>\s*(?:<span[^>]*></span>\s*)*<h[1-6][^>]*>(.*?)</h[1-6]>'
        for m in re.finditer(pattern, text, re.S):
            found.setdefault(_norm(m.group(2)), m.group(1))
        _anchor_cache.clear()
        _anchor_cache[key] = found
    return _anchor_cache[key]


def find_anchor(path, topic):
    """Sprungmarke zur Überschrift (genau, oder bei "…" am Ende: erste Überschrift mit diesem Anfang), sonst ""."""
    anchors = _anchors(path)
    if topic.endswith("…"):
        start = _norm(topic[:-1])
        return next((a for t, a in anchors.items() if t.startswith(start)), "")
    return anchors.get(_norm(topic), "")


def open_help(topic=None, parent=None):
    """Anleitung zur Überschrift öffnen (HTML im Browser, an der passenden Stelle); ohne Treffer wie open_manual.

    Windows und viele Linux-Desktops verwerfen beim Öffnen einer lokalen Datei den Teil hinter '#'. Deshalb wird eine
    kleine Weiterleitungsseite im Temp-Ordner geöffnet, die den Browser an die Sprungmarke weiterleitet."""
    page = find_file("bedienungsanleitung.html")
    anchor = find_anchor(page, topic) if page and topic else ""
    if not anchor:
        open_manual(parent)
        return
    url = QUrl.fromLocalFile(page)
    url.setFragment(anchor)
    target = url.toString(QUrl.ComponentFormattingOption.FullyEncoded)
    redirect = os.path.join(tempfile.gettempdir(), "plc_datenlogger_hilfe.html")
    try:
        with open(redirect, "w", encoding="utf-8") as f:
            f.write("<!DOCTYPE html><meta charset='utf-8'>"
                    f"<meta http-equiv='refresh' content='0; url={html.escape(target, quote=True)}'>"
                    f"<script>location.replace({json.dumps(target)})</script>"
                    f"<a href='{html.escape(target, quote=True)}'>{html.escape(APP_NAME)}</a>")
    except OSError:
        open_manual(parent)
        return
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(redirect)):
        open_manual(parent)


def _context_help(window):
    """F1 im Fenster: Thema des Widgets mit dem Eingabefokus (sonst des Fensters) öffnen."""
    w = QApplication.focusWidget()
    if w is None or w.window() is not window:
        w = window
    open_help(help_topic(w), window)


def _attach_f1(window):
    """F1-Tastenkürzel einmalig an ein Fenster/einen Dialog hängen (wirkt auch in modalen Dialogen)."""
    if window is None or isinstance(window, QMenu) or getattr(window, "_help_f1", None) is not None:
        return
    sc = QShortcut(QKeySequence(Qt.Key.Key_F1), window)
    sc.setContext(Qt.ShortcutContext.WindowShortcut)
    sc.activated.connect(lambda win=window: _context_help(win))
    window._help_f1 = sc


def install_help(app=None):
    """Kontexthilfe für alle Fenster der Anwendung einschalten: jedes Fenster bekommt beim ersten Fokus sein F1.

    (Ein anwendungsweiter Ereignisfilter würde jedes Ereignis durch Python leiten und die Diagramme bremsen;
    das Signal focusChanged kommt dagegen nur beim Wechsel des Eingabefokus.)"""
    app = app or QApplication.instance()
    if app is None or getattr(app, "_help_installed", False):
        return
    app._help_installed = True
    app.focusChanged.connect(lambda _old, new: _attach_f1(new.window()) if new is not None else None)
    for w in app.topLevelWidgets():
        if w.isVisible():
            _attach_f1(w)


def _version(dist, module):
    """Version eines Pakets: aus den Paketdaten, sonst aus dem bereits geladenen Modul; None = nicht vorhanden."""
    try:
        from importlib.metadata import version
        return version(dist)
    except Exception:
        pass
    mod = sys.modules.get(module)
    if mod is None:
        try:
            import importlib.util
            if importlib.util.find_spec(module) is None:
                return None
        except (ImportError, ValueError):
            return None
        return "?"
    return str(getattr(mod, "__version__", "?"))


def _read(name):
    """Lizenzdatei als Text lesen ("" wenn sie fehlt)."""
    path = find_file(name)
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


class AboutDialog(QDialog):
    """Dialog „Über …“: Programm, Lizenz, Drittkomponenten und Bibliotheksversionen in Registerkarten."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Über {0}").format(APP_NAME))
        self.resize(680, 560)
        lay = QVBoxLayout(self)
        # Kopf: Programmsymbol, Name und Version
        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(default_pixmap(64))
        head.addWidget(logo)
        version = tr("Version {0}").format(APP_VERSION)
        title = QLabel(f"<div style='font-size:16pt;font-weight:bold'>{APP_NAME}</div>"
                       f"<div>{version}</div><div>{COPYRIGHT}</div>")
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        head.addWidget(title, 1)
        lay.addLayout(head)

        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self.tabs.addTab(self._about_page(), tr("Programm"))
        self.tabs.addTab(self._libraries_page(), tr("Bibliotheken"))
        third = _read("THIRD_PARTY_LICENSES.md")
        self.tab_third = self._text_page(third, markdown=True) if third else None
        if self.tab_third is not None:
            self.tabs.addTab(self.tab_third, tr("Drittkomponenten"))
        self.tab_lgpl = self._add_license_tab("LICENSE", tr("Lizenz (LGPL v3)"))
        self.tab_gpl = self._add_license_tab("COPYING", tr("GPL v3"))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_manual = QPushButton(tr("Bedienungsanleitung"))
        btn_manual.clicked.connect(lambda: open_manual(self))
        buttons.addButton(btn_manual, QDialogButtonBox.ButtonRole.HelpRole)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _browser(self):
        """Textanzeige; Links ins Internet öffnet der Browser, LICENSE/COPYING springen zur Registerkarte."""
        b = QTextBrowser()
        b.setOpenLinks(False)
        b.anchorClicked.connect(self._link)
        return b

    def _link(self, url):
        target = url.toString()
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
        elif target.endswith("COPYING") and self.tab_gpl is not None:
            self.tabs.setCurrentWidget(self.tab_gpl)
        elif target.endswith("LICENSE") and self.tab_lgpl is not None:
            self.tabs.setCurrentWidget(self.tab_lgpl)

    def _about_page(self):
        b = self._browser()
        b.setHtml(
            "<p>" + tr("Liest zyklisch Werte aus Steuerungen, zeichnet sie als CSV und/oder in einer Datenbank auf "
                       "und zeigt sie als y-t-Diagramme an (Oberfläche, Browser, Headless).") + "</p>"
            + f"<p><b>{COPYRIGHT}</b></p>"
            + "<p>" + tr("Dieses Programm ist freie Software: Sie können es unter den Bedingungen der GNU Lesser "
                         "General Public License, wie von der Free Software Foundation veröffentlicht, weitergeben "
                         "und/oder verändern, entweder gemäß Version 3 der Lizenz oder (nach Ihrer Wahl) jeder "
                         "späteren Version.") + f" (<code>{LICENSE_ID}</code>)</p>"
            + "<p>" + tr("Dieses Programm wird in der Hoffnung verbreitet, dass es nützlich ist, aber OHNE JEDE "
                         "GEWÄHR; sogar ohne die implizite Gewähr der MARKTREIFE oder der EIGNUNG FÜR EINEN "
                         "BESTIMMTEN ZWECK.") + "</p>"
            + "<p>" + tr("Lizenztexte: <a href='LICENSE'>GNU LGPL v3</a>, <a href='COPYING'>GNU GPL v3</a> "
                         "(<a href='https://www.gnu.org/licenses/'>gnu.org/licenses</a>).") + "</p>"
            + "<p>" + tr("Die Oberfläche verwendet Qt über PySide6 (LGPL-3.0). Die Bibliotheken liegen als eigene "
                         "Dateien im Programmordner und können durch kompatible Fassungen ersetzt werden.") + "</p>")
        return b

    def _libraries_page(self):
        from PySide6 import __version__ as pyside_version
        from PySide6.QtCore import qVersion
        rows = [("Python", platform.python_version()), ("Qt", qVersion()), ("PySide6", pyside_version)]
        for name, dist, module in LIBRARIES:
            v = _version(dist, module)
            rows.append((name, v if v else tr("nicht installiert")))
        rows.append((tr("System"), f"{platform.system()} {platform.release()} ({platform.machine()})"))
        b = self._browser()
        b.setHtml("<table cellspacing='0' cellpadding='3'>"
                  + "".join(f"<tr><td><b>{n}</b></td><td>{v}</td></tr>" for n, v in rows) + "</table>")
        return b

    def _text_page(self, text, markdown=False):
        b = self._browser()
        if markdown:
            b.setMarkdown(text)
        else:
            b.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
            b.setPlainText(text)
        return b

    def _add_license_tab(self, name, title):
        text = _read(name)
        if not text:
            return None
        page = self._text_page(text)
        self.tabs.addTab(page, title)
        return page


def show_about(parent=None):
    AboutDialog(parent).exec()


def add_help_menu(window):
    """Menü „Hilfe“ an die Menüleiste eines Hauptfensters anhängen (Bedienungsanleitung, Über …), F1 einschalten."""
    menu = window.menuBar().addMenu(tr("&Hilfe"))
    # F1 ist kein Kürzel dieser Aktion, sondern die Kontexthilfe (install_help); "\tF1" zeigt es im Menü nur an.
    a = QAction(tr("&Bedienungsanleitung") + "\tF1", window)
    a.triggered.connect(lambda _=False: open_manual(window))
    menu.addAction(a)
    menu.addSeparator()
    a = QAction(tr("&Über {0} …").format(APP_NAME), window)
    a.triggered.connect(lambda _=False: show_about(window))
    menu.addAction(a)
    install_help()
    _attach_f1(window)
    return menu
