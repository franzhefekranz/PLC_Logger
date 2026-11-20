# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Aufbau der Fenster und Dialoge mitschreiben (Grundlage des Kapitels „Referenz“ der Bedienungsanleitung).

``tools/make_screenshots.py --referenz DATEI.json`` ruft ``record`` für jedes Fenster auf, das es zeigt oder
fotografiert (auch modale Dialoge, die nicht fotografiert werden). Erfasst werden je Fenster (Klasse + Titel, jedes
nur einmal):

* Menüleiste mit allen Untermenüs: Text, Tastenkürzel, ankreuzbar, Tooltip/Statustext;
* Werkzeugleisten;
* Reiter (auch verschachtelt) und je Reiter die Bedienelemente: Knöpfe, Kästchen, Gruppen, Formularzeilen
  (Beschriftung + Tooltip/Platzhalter des Felds), Tabellenspalten.

Das Ergebnis ist eine JSON-Datei (Reihenfolge wie im Fenster); die Texte sind in der Sprache des Laufs.
"""
import json

DATA = {"windows": []}
_seen = set()


def _clean(text):
    """Menütext ohne Kurztaste-Markierung (&) und ohne Leerraum am Rand."""
    return (text or "").replace("&&", "\0").replace("&", "").replace("\0", "&").strip()


def _action(a):
    """QAction -> dict (Text, Tastenkürzel, ankreuzbar, Tooltip, Untermenü)."""
    from PySide6.QtGui import QKeySequence
    d = {"text": _clean(a.text())}
    keys = [s.toString(QKeySequence.SequenceFormat.NativeText) for s in a.shortcuts() if not s.isEmpty()]
    if keys:
        d["keys"] = keys
    if a.isCheckable():
        d["check"] = True
    tip = a.statusTip() or (a.toolTip() if _clean(a.toolTip()) != d["text"] else "")
    if tip:
        d["tip"] = tip.strip()
    if a.menu() is not None:
        d["sub"] = _menu(a.menu())
    return d


def _menu(menu):
    """Einträge eines Menüs (Trennlinien als {"sep": True})."""
    out = []
    for a in menu.actions():
        if a.isSeparator():
            if out and not out[-1].get("sep"):
                out.append({"sep": True})
        elif a.isVisible() or a.menu() is not None:
            out.append(_action(a))
    while out and out[-1].get("sep"):
        out.pop()
    return out


def _tab_path(w, top):
    """Reiter-Pfad eines Widgets im Fenster ``top`` (äußerer Reiter zuerst), z. B. ["Verbindung", "Datenbank"]."""
    from PySide6.QtWidgets import QTabWidget
    path = []
    child, p = w, w.parentWidget()
    while p is not None and p is not top:
        if isinstance(p, QTabWidget):
            for i in range(p.count()):
                page = p.widget(i)
                if page is child or page.isAncestorOf(child):
                    path.insert(0, _clean(p.tabText(i)))
                    break
        child, p = p, p.parentWidget()
    return path


def _tip(w):
    """Tooltip, sonst Platzhalter eines Eingabefelds."""
    t = (w.toolTip() or "").strip()
    if not t and hasattr(w, "placeholderText"):
        try:
            t = (w.placeholderText() or "").strip()
        except Exception:
            t = ""
    return t


def _controls(win):
    """Bedienelemente in Fensterreihenfolge mit Reiter-Pfad."""
    from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QFormLayout, QGroupBox, QLabel, QMenu,
                                   QTabBar, QToolButton)
    out, done = [], set()
    for w in win.findChildren(object):
        if not hasattr(w, "isWidgetType") and not isinstance(w, QFormLayout):
            continue
        try:
            if isinstance(w, QFormLayout):
                for r in range(w.rowCount()):
                    li = w.itemAt(r, QFormLayout.ItemRole.LabelRole)
                    fi = w.itemAt(r, QFormLayout.ItemRole.FieldRole)
                    lab = li.widget() if li is not None else None
                    fld = fi.widget() if fi is not None else None
                    if isinstance(lab, QLabel) and _clean(lab.text()):
                        done.add(id(lab))
                        out.append({"kind": "feld", "text": _clean(lab.text()).rstrip(":"),
                                    "tip": _tip(fld) if fld is not None else "",
                                    "tabs": _tab_path(lab, win)})
                continue
            if not w.isWidgetType() or isinstance(w, (QMenu, QTabBar)):
                continue
            if isinstance(w, QGroupBox) and _clean(w.title()):
                out.append({"kind": "gruppe", "text": _clean(w.title()), "tip": _tip(w), "tabs": _tab_path(w, win)})
            elif isinstance(w, QAbstractButton) and not isinstance(w, QToolButton) and _clean(w.text()):
                out.append({"kind": "kaestchen" if w.isCheckable() and type(w).__name__ in ("QCheckBox", "QRadioButton")
                            else "knopf", "text": _clean(w.text()), "tip": _tip(w), "tabs": _tab_path(w, win)})
            elif isinstance(w, QToolButton) and (_clean(w.text()) or w.toolTip()):
                out.append({"kind": "knopf", "text": _clean(w.text()), "tip": _tip(w), "tabs": _tab_path(w, win)})
            elif isinstance(w, QAbstractItemView) and w.model() is not None and hasattr(w, "horizontalHeader"):
                from PySide6.QtCore import Qt
                m = w.model()
                cols = [str(m.headerData(c, Qt.Orientation.Horizontal) or "") for c in range(m.columnCount())]
                cols = [c for c in cols if c.strip()]
                if cols:
                    out.append({"kind": "tabelle", "text": ", ".join(cols), "tip": _tip(w), "tabs": _tab_path(w, win)})
        except RuntimeError:                        # bereits gelöschtes Qt-Objekt
            continue
    return out


def record(win, shot=""):
    """Aufbau des Fensters ``win`` (jedes Fenster nur einmal) mitschreiben; ``shot`` = Bild, bei dem es gezeigt wurde."""
    from PySide6.QtWidgets import QMainWindow, QTabWidget, QToolBar
    try:
        win = win.window()
        key = (type(win).__name__, win.windowTitle())
    except (RuntimeError, AttributeError):
        return
    if key in _seen:
        return
    _seen.add(key)
    d = {"class": key[0], "title": key[1], "shot": shot}
    if isinstance(win, QMainWindow) and win.menuBar() is not None:
        d["menus"] = [{"text": _clean(a.text()), "sub": _menu(a.menu())} for a in win.menuBar().actions()
                      if a.menu() is not None]
    bars = []
    for tb in win.findChildren(QToolBar):
        acts = [_action(a) for a in tb.actions() if not a.isSeparator() and _clean(a.text())]
        if acts:
            bars.append({"text": _clean(tb.windowTitle()), "sub": acts})
    if bars:
        d["toolbars"] = bars
    tabs = []
    for t in win.findChildren(QTabWidget):
        tabs.append({"tabs": _tab_path(t, win), "pages": [_clean(t.tabText(i)) for i in range(t.count())]})
    if tabs:
        d["tabwidgets"] = tabs
    d["controls"] = _controls(win)
    DATA["windows"].append(d)


def write(path):
    """Mitschrift als JSON speichern."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(DATA, f, ensure_ascii=False, indent=1)
    print(f"Referenz: {len(DATA['windows'])} Fenster -> {path}", flush=True)
