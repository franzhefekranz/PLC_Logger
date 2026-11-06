# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Sprachumschaltung: Übersetzung der Oberflächentexte aus einfachen Textdateien.

Alle Texte stehen im Programm auf Deutsch. Eine Sprachdatei ``sprachen/<Kürzel>.txt`` (z. B. ``en.txt``, ``fr.txt``)
ordnet jedem deutschen Text die Übersetzung zu:

    # Sprache: English
    @ Konfiguration laden
    > Load configuration

    @ {0} offene Ereignisse
    > {0} open events

* ``@`` leitet den deutschen Originaltext ein, ``>`` die Übersetzung (leer = Original bleibt stehen).
* ``\\n`` steht für einen Zeilenumbruch. Platzhalter wie ``{0}`` oder ``{1:.1f}`` müssen in der Übersetzung erhalten
  bleiben (Reihenfolge beliebig); sonst wird für diesen Text das Original verwendet.
* Neue Sprache: ``de.txt`` (Vorlage mit allen Texten) kopieren, in ``<Kürzel>.txt`` umbenennen, oben den Namen der
  Sprache eintragen und die ``>``-Zeilen ausfüllen. Die Datei erscheint danach im Menü „Sprache“.

Gesucht wird zuerst im Datenordner (``<Datenordner>/sprachen``, für eigene Übersetzungen), dann im Programmordner.
Die gewählte Sprache steht in den Einstellungen (``plc_einstellungen.json``) und gilt ab dem nächsten Start.

Im Programm: ``tr("Text")`` übersetzt; Texte mit Werten als ``tr("{0} offen").format(n)``. ``N_("Text")`` markiert
Texte in Konstanten für die Sprachdatei, übersetzt wird beim Anzeigen mit ``tr(konstante)``.
"""
import os
import re
import string
import sys

DEFAULT = "de"
FOLDER = "sprachen"
_table = None            # {Original: Übersetzung}, None = noch nicht geladen
_lang = DEFAULT


def N_(text):
    """Markiert einen Text für die Sprachdatei, ohne ihn zu übersetzen (für Konstanten)."""
    return text


def _placeholders(text):
    """Namen der Platzhalter eines Textes, sortiert (``{0} von {1}`` -> ['0', '1']); None bei ungültigen Klammern.

    Damit prüft ``parse_file``, ob eine Übersetzung dieselben Platzhalter enthält – sonst stürzte ``.format()`` ab.
    """
    try:
        return sorted(str(f) for _lit, f, _spec, _conv in string.Formatter().parse(text) if f is not None)
    except ValueError:
        return None


def _unescape(s):
    """``\n`` in der Sprachdatei -> Zeilenumbruch, ``\\`` -> Backslash (Hilfszeichen \0 schützt doppelte Backslashes).
    """
    return s.replace("\\\\", "\0").replace("\\n", "\n").replace("\0", "\\")


def escape(s):
    """Gegenstück zu ``_unescape``: Text für eine Zeile der Sprachdatei (Zeilenumbrüche als ``\n``)."""
    return s.replace("\\", "\\\\").replace("\n", "\\n")


def parse_file(path):
    """Sprachdatei lesen -> (Name der Sprache, {Original: Übersetzung}, Warnungen)."""
    name, table, warnings = "", {}, []
    key = None
    with open(path, encoding="utf-8-sig") as f:
        for no, line in enumerate(f, 1):
            line = line.rstrip("\r\n")
            m = re.match(r"#\s*Sprache\s*:\s*(.+)", line)
            if m and not name:
                name = m.group(1).strip()
                continue
            if line.startswith("@ ") or line == "@":
                key = _unescape(line[2:])
            elif (line.startswith("> ") or line == ">") and key is not None:
                val = _unescape(line[2:])
                if val:
                    if _placeholders(val) != _placeholders(key):
                        warnings.append(f"Zeile {no}: Platzhalter passen nicht – Original wird verwendet")
                    else:
                        table[key] = val
                key = None
    return name, table, warnings


def folders():
    """Ordner mit Sprachdateien: Datenordner (eigene Übersetzungen) und Programmordner (mitgeliefert)."""
    out = []
    try:
        from plc_common import BASE_DIR
        out.append(os.path.join(BASE_DIR, FOLDER))
    except Exception:
        pass
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    out.append(os.path.join(base, FOLDER))
    return list(dict.fromkeys(out))


def available():
    """Verfügbare Sprachen -> [(Kürzel, Name)] (Deutsch immer zuerst)."""
    langs = {DEFAULT: "Deutsch"}
    for folder in folders():
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for fn in names:
            code, ext = os.path.splitext(fn)
            if ext.lower() != ".txt" or code in langs or not re.fullmatch(r"[A-Za-z]{2,3}([_-][A-Za-z0-9]+)?", code):
                continue
            try:
                name = parse_file(os.path.join(folder, fn))[0]
            except (OSError, UnicodeDecodeError):
                continue
            langs[code] = name or code
    return list(langs.items())


def _find(code):
    """Pfad der Sprachdatei ``<Kürzel>.txt`` (Datenordner vor Programmordner) oder None."""
    for folder in folders():
        p = os.path.join(folder, f"{code}.txt")
        if os.path.exists(p):
            return p
    return None


def load(code=None):
    """Sprache laden (ohne Angabe: aus den Einstellungen, sonst Deutsch)."""
    global _table, _lang
    if code is None:
        try:
            from plc_common import load_settings
            code = load_settings().get("sprache") or DEFAULT
        except Exception:
            code = DEFAULT
    _table, _lang = {}, code
    if code == DEFAULT:
        return
    p = _find(code)
    if p:
        try:
            _table = parse_file(p)[1]
        except (OSError, UnicodeDecodeError):
            _table = {}


def current():
    """Kürzel der geladenen Sprache (lädt beim ersten Aufruf die Sprache aus den Einstellungen)."""
    if _table is None:
        load()
    return _lang


def tr(text):
    """Text in die gewählte Sprache übersetzen (unbekannte Texte bleiben unverändert)."""
    if _table is None:
        load()
    return _table.get(text, text) if _table else text


# ---------------------------------------------------------------------------------------
# Qt: eigene Standardtexte (Ja/Nein/Abbrechen …) und Menü "Sprache"
# ---------------------------------------------------------------------------------------
_qt_translators = []


# Farbschema der Oberfläche (Einstellung ``farbschema``): wie das System, hell oder dunkel
SCHEMES = (("system", N_("Wie das System")), ("hell", N_("Hell")), ("dunkel", N_("Dunkel")))


def _dark_palette():
    """Dunkle Farbpalette für den Stil Fusion (wenn Qt das Farbschema nicht selbst umschalten kann)."""
    from PySide6.QtGui import QColor, QPalette
    p = QPalette()
    R, G = QPalette.ColorRole, QPalette.ColorGroup
    for role, color in ((R.Window, "#2b2f33"), (R.WindowText, "#e8eaed"), (R.Base, "#1f2226"),
                        (R.AlternateBase, "#2b2f33"), (R.ToolTipBase, "#3c4043"), (R.ToolTipText, "#e8eaed"),
                        (R.Text, "#e8eaed"), (R.Button, "#33373b"), (R.ButtonText, "#e8eaed"), (R.BrightText, "#ff6b6b"),
                        (R.Link, "#8ab4f8"), (R.Highlight, "#3d7bd9"), (R.HighlightedText, "#ffffff"),
                        (R.PlaceholderText, "#9aa0a6")):
        p.setColor(role, QColor(color))
    for role in (R.WindowText, R.Text, R.ButtonText):
        p.setColor(G.Disabled, role, QColor("#80868b"))
    return p


def apply_color_scheme(app=None, scheme=None):
    """Farbschema anwenden (``system``/``hell``/``dunkel``; None = aus den Einstellungen). Ab Qt 6.8 über die
    Stil-Hinweise (behält das Aussehen des Systems), sonst bzw. wenn das System es ablehnt: Stil Fusion mit heller
    bzw. dunkler Palette. Wirkt sofort, auch in schon offenen Fenstern."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    app = app or QApplication.instance()
    if app is None:
        return
    if scheme is None:
        from plc_common import load_settings
        scheme = str(load_settings().get("farbschema", "system") or "system")
    hints = app.styleHints()
    want = {"hell": Qt.ColorScheme.Light, "dunkel": Qt.ColorScheme.Dark}.get(scheme, Qt.ColorScheme.Unknown)
    if hasattr(hints, "setColorScheme"):
        hints.setColorScheme(want)
        if scheme == "system" or hints.colorScheme() == want:
            return
    if scheme == "system":
        return
    app.setStyle("Fusion")
    app.setPalette(_dark_palette() if scheme == "dunkel" else app.style().standardPalette())


def fill_scheme_menu(menu):
    """Untermenü „Farbschema“: wie das System, hell, dunkel (gespeichert, gilt für alle Programme)."""
    from PySide6.QtGui import QAction, QActionGroup
    from plc_common import load_settings, save_settings
    sub = menu.addMenu(tr("Farbschema"))
    grp = QActionGroup(sub)
    grp.setExclusive(True)
    cur = str(load_settings().get("farbschema", "system") or "system")
    for code, name in SCHEMES:
        a = QAction(tr(name), sub)
        a.setCheckable(True)
        a.setChecked(code == cur)

        def choose(_=False, c=code):
            save_settings(farbschema=c)
            apply_color_scheme(scheme=c)
        a.triggered.connect(choose)
        grp.addAction(a)
        sub.addAction(a)
    return sub


def is_dark():
    """True, wenn die Oberfläche gerade dunkel ist (Fensterfarbe der Palette)."""
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    return bool(app) and app.palette().color(QPalette.ColorRole.Window).lightness() < 128


def install_qt(app):
    """Qt-eigene Übersetzungen (Knöpfe der Meldungsfenster, Dateidialoge) passend zur Sprache laden; Farbschema."""
    try:
        apply_color_scheme(app)
    except Exception:
        pass
    try:
        from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
        code = current()
        QLocale.setDefault(QLocale(code.replace("-", "_")))
        path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        for name in ("qtbase", "qt"):
            t = QTranslator(app)
            if t.load(f"{name}_{code.split('_')[0].split('-')[0]}", path):
                app.installTranslator(t)
                _qt_translators.append(t)
                break
    except Exception:
        pass


def fill_language_menu(menu, window, restart_cmd):
    """Menü mit allen Sprachen füllen. restart_cmd: Funktion -> Befehlszeile für den Neustart (oder None)."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QAction, QActionGroup, QDesktopServices
    grp = QActionGroup(menu)
    grp.setExclusive(True)
    cur = current()
    for code, name in available():
        a = QAction(f"{name} ({code})", menu)
        a.setCheckable(True)
        a.setChecked(code == cur)
        a.triggered.connect(lambda _=False, c=code: _switch(window, c, restart_cmd))
        grp.addAction(a)
        menu.addAction(a)
    menu.addSeparator()
    a = QAction(tr("Ordner mit Sprachdateien öffnen …"), menu)
    a.setToolTip(tr("Eigene Übersetzung: de.txt kopieren, umbenennen (z. B. fr.txt) und übersetzen"))

    def open_folder():
        """Ordner der eigenen Sprachdateien öffnen; die Vorlage ``de.txt`` wird bei Bedarf dorthin kopiert."""
        folder = folders()[0]
        os.makedirs(folder, exist_ok=True)
        tpl = _find(DEFAULT)                          # Vorlage in den Datenordner kopieren, falls sie dort fehlt
        if tpl and not os.path.exists(os.path.join(folder, f"{DEFAULT}.txt")):
            try:
                import shutil
                shutil.copy(tpl, os.path.join(folder, f"{DEFAULT}.txt"))
            except OSError:
                pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
    a.triggered.connect(open_folder)
    menu.addAction(a)
    menu.addSeparator()
    fill_scheme_menu(menu)


def _switch(window, code, restart_cmd):
    """Andere Sprache wählen: in den Einstellungen speichern und anbieten, das Programm neu zu starten.

    Die Texte werden beim Aufbau der Fenster übersetzt; ein Wechsel wirkt deshalb erst nach dem Neustart.
    """
    from PySide6.QtWidgets import QMessageBox
    from plc_common import save_settings
    if code == current():
        return
    save_settings(sprache=code)
    ans = QMessageBox.question(window, tr("Sprache"),
                               tr("Die Sprache wird beim nächsten Start übernommen.\nJetzt neu starten?"))
    if ans == QMessageBox.StandardButton.Yes and restart_cmd:
        import subprocess
        try:
            cmd = restart_cmd()
            if cmd:
                from plc_common import child_env
                subprocess.Popen(cmd, env=child_env())
                window.close()
        except OSError as e:
            QMessageBox.warning(window, tr("Sprache"), str(e))
