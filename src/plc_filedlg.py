# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Datei- und Ordnerdialoge, die sich den zuletzt benutzten Ordner merken.

Die Funktionen haben dieselben Argumente wie die statischen ``QFileDialog``-Methoden. Zeigt der vorgeschlagene Pfad
keinen eigenen Ordner (nur ein Dateiname, leer), den Programmordner oder den Datenordner bzw. einen Unterordner davon
(z. B. ``csv``, ``berichte``), wird stattdessen der Ordner genommen, in dem zuletzt mit diesem Dialog (gleicher Titel)
gespeichert bzw. geöffnet wurde – sonst der zuletzt überhaupt benutzte. Ein Ordner außerhalb davon (z. B. der Ordner
des geöffneten Prüfstands oder ein eingestellter CSV-Ordner auf einem Netzlaufwerk) bleibt unverändert. Gemerkt wird
in den persönlichen Einstellungen (``ordner_zuletzt``)."""
import os
import sys

from PySide6.QtWidgets import QFileDialog

SETTING = "ordner_zuletzt"
_ANY = ""                                     # Schlüssel für „zuletzt überhaupt benutzter Ordner“


def _norm(path):
    """Pfad zum Vergleichen (absolut, ohne Groß-/Kleinschreibung unter Windows)."""
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _program_dirs():
    """Ordner, die nicht als bewusst gewählter Speicherort gelten: Daten-, Programm- und Arbeitsordner."""
    from plc_common import BASE_DIR
    dirs = {BASE_DIR, os.getcwd(), os.path.dirname(os.path.abspath(sys.executable)),
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}
    if os.environ.get("APPIMAGE"):
        dirs.add(os.path.dirname(os.environ["APPIMAGE"]))
    return {_norm(d) for d in dirs if d}


def _is_default(folder):
    """True, wenn ``folder`` kein bewusst gewählter Ort ist: Programm-/Arbeitsordner, Datenordner oder darunter."""
    from plc_common import BASE_DIR
    f, base = _norm(folder), _norm(BASE_DIR)
    return f in _program_dirs() or f.startswith(base.rstrip(os.sep) + os.sep)


def _remembered():
    """Gemerkte Ordner {Dialogtitel: Ordner} (Fehler: leer)."""
    try:
        from plc_common import load_settings
        data = load_settings().get(SETTING)
        return dict(data) if isinstance(data, dict) else {}
    except Exception:
        return {}


def start_path(key, start=""):
    """Vorgeschlagenen Pfad ``start`` ggf. in den gemerkten Ordner verlegen (Dateiname bleibt)."""
    start = start or ""
    folder, name = (start, "") if start and os.path.isdir(start) else os.path.split(start)
    if folder and not _is_default(folder):
        return start                          # bewusst vorgegebener Ordner
    known = _remembered()
    for k in (key, _ANY):
        d = known.get(k)
        if d and os.path.isdir(d):
            return os.path.join(d, name) if name else d
    return start


def remember(key, path):
    """Ordner von ``path`` (Datei oder Ordner) für diesen Dialog und allgemein merken."""
    if not path:
        return
    folder = path if os.path.isdir(path) else os.path.dirname(os.path.abspath(path))
    if not folder:
        return
    try:
        from plc_common import save_settings
        known = _remembered()
        known[key] = known[_ANY] = folder
        if len(known) > 60:                   # nicht endlos wachsen lassen
            known = {k: v for k, v in list(known.items())[-60:]}
            known[_ANY] = folder
        save_settings(**{SETTING: known})
    except Exception:
        pass


def save_name(parent, caption="", start="", flt="", *args, **kw):
    """Wie ``QFileDialog.getSaveFileName``; Rückgabe (Pfad, Filter)."""
    path, chosen = QFileDialog.getSaveFileName(parent, caption, start_path(caption, start), flt, *args, **kw)
    remember(caption, path)
    return path, chosen


def open_name(parent, caption="", start="", flt="", *args, **kw):
    """Wie ``QFileDialog.getOpenFileName``; Rückgabe (Pfad, Filter)."""
    path, chosen = QFileDialog.getOpenFileName(parent, caption, start_path(caption, start), flt, *args, **kw)
    remember(caption, path)
    return path, chosen


def open_names(parent, caption="", start="", flt="", *args, **kw):
    """Wie ``QFileDialog.getOpenFileNames``; Rückgabe (Pfade, Filter)."""
    paths, chosen = QFileDialog.getOpenFileNames(parent, caption, start_path(caption, start), flt, *args, **kw)
    if paths:
        remember(caption, paths[0])
    return paths, chosen


def directory(parent, caption="", start="", *args, **kw):
    """Wie ``QFileDialog.getExistingDirectory``; Rückgabe: Ordner oder ""."""
    if not start or _is_default(start):
        start = start_path(caption, "") or start
    path = QFileDialog.getExistingDirectory(parent, caption, start, *args, **kw)
    remember(caption, path)
    return path
