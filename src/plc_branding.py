# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Programm-Icon und Logo.

* ``app_icon``      liefert das Fenster-/Taskleisten-Icon (konfigurierte Datei oder Standard-Symbol),
* ``logo_pixmap``   liefert ein Logo aus der Konfiguration (Startbild),
* ``logos_pixmap``  setzt Kundenlogo und Logo nebeneinander (Menüleiste des Loggers rechts oben; leer = kein Logo),
* ``company_pixmap`` liefert das feste Herstellerlogo (``logo.png``) für „Über …“ und das versteckte Info-Fenster,
* ``default_pixmap`` zeichnet das Standard-Symbol selbst (Qt-Zeichenbefehle), sodass das Programm
  ohne mitgelieferte Bilddateien auskommt,
* ``set_windows_app_id`` sorgt unter Windows für ein eigenes Taskleisten-Symbol.

Die Bilddateien (PNG, SVG, ICO, JPG ...) werden in der Konfiguration angegeben; relative Pfade
beziehen sich auf den Programm-/Datenordner (siehe plc_common.BASE_DIR). Ohne Angabe gilt für das Icon die
mitgelieferte Datei ``app.ico``, sonst das gezeichnete Standard-Symbol. Logo und Kundenlogo (Logger, Webseiten,
Berichte) entfallen ohne Angabe; nur das Startbild zeigt dann das mitgelieferte Herstellerlogo ``logo.png``.
"""
import math
import os
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

from plc_common import BASE_DIR


def resolve(path: str) -> str:
    """Relativen Pfad auf den Programmordner beziehen."""
    if not path:
        return ""
    # Absolute Pfade bleiben unverändert, relative gelten ab dem Basisordner des Programms.
    return path if os.path.isabs(path) else os.path.join(BASE_DIR, path)


def bundled(name: str) -> str:
    """Mitgelieferte Bilddatei (Datenordner, Programmordner, PyInstaller-Archiv) oder ""."""
    for folder in (BASE_DIR, os.path.dirname(os.path.abspath(__file__)), getattr(sys, "_MEIPASS", "")):
        path = os.path.join(folder, name) if folder else ""
        if path and os.path.exists(path):
            return path
    return ""


def default_pixmap(size: int = 256) -> QPixmap:
    """Standard-Icon: dunkles Quadrat mit zwei Kurven."""
    # Leere (transparente) Zeichenfläche; Größe in Pixeln, Standard 256 x 256.
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    # QPainter zeichnet in das Pixmap; Antialiasing glättet die Kanten.
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    # Hintergrund: dunkelblaues Quadrat mit abgerundeten Ecken (3 % Rand, Eckenradius 18 %).
    p.setBrush(QColor("#1b2a41"))
    # QRectF: Kommazahlen sind nur mit dem Float-Rechteck erlaubt (neuere Qt-Bindungen lehnen
    # Kommazahlen bei der Variante mit einzelnen int-Werten ab).
    p.drawRoundedRect(QRectF(size * 0.03, size * 0.03, size * 0.94, size * 0.94), size * 0.18, size * 0.18)
    # Zwei Kurven (Sinus mit unterschiedlicher Phase/Amplitude) in Blau und Orange - wie Messkurven.
    for color, phase, amp in (("#4fc3f7", 0.0, 0.22), ("#ffb74d", 1.4, 0.16)):
        # Kurve als Linienzug aus 41 Punkten aufbauen.
        poly = QPolygonF()
        for k in range(0, 41):
            # x: gleichmäßig über 76 % der Breite verteilt, y: Sinus um die Bildmitte (1,5 Perioden).
            x = size * (0.12 + 0.76 * k / 40)
            y = size * 0.5 - size * amp * math.sin(k / 40 * 6.28318 * 1.5 + phase)
            poly.append(QPointF(x, y))
        # Linienbreite wächst mit der Bildgröße; runde Enden und Ecken sehen weicher aus.
        p.setPen(QPen(QColor(color), max(2.0, size / 18), Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(poly)
    # Zeichnen beenden (muss vor der Verwendung des Pixmaps geschehen).
    p.end()
    return pm


# Programme mit eigenem Icon (Ordner icons, erzeugt mit tools/make_program_icons.py): das „Ti“ des Logos mit einem
# farbigen Abzeichen, damit sich die Programme in Taskleiste, Startmenü und Dock unterscheiden lassen.
PROGRAM_ICONS = ("logger", "konfiguration", "iocheck", "ereignisse", "headless")


def app_icon(*paths, program: str = "logger") -> QIcon:
    """Erste vorhandene Bilddatei als Icon: konfiguriertes Icon, Icon des Programms (``icons/<program>.ico``),
    mitgeliefertes app.ico, weitere Pfade (z. B. das Logo), sonst das Standard-Icon."""
    own = bundled(os.path.join("icons", program + ".ico")) if program in PROGRAM_ICONS else ""
    candidates = list(paths[:1]) + [own, bundled("app.ico")] + list(paths[1:])
    for path in candidates:
        full = resolve(path)
        if full and os.path.exists(full):
            icon = QIcon(full)
            if not icon.isNull():
                return icon
    # Nichts gefunden: Standard-Symbol verwenden.
    return QIcon(default_pixmap(256))


def logo_pixmap(path: str, height: int = 28, max_width: int = 0) -> QPixmap:
    """Logo auf feste Höhe skaliert (Seitenverhältnis bleibt, höchstens max_width breit); ohne Datei das
    mitgelieferte logo.png, sonst das Standard-Icon."""
    # Logo laden (SVG funktioniert, wenn das Qt-SVG-Plugin vorhanden ist).
    for full in (resolve(path), bundled("logo.png")):
        if full and os.path.exists(full):
            pm = QPixmap(full)
            if not pm.isNull():
                # Auf feste Höhe skalieren, Seitenverhältnis bleibt erhalten; SmoothTransformation = hohe Qualität.
                pm = pm.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)
                if max_width and pm.width() > max_width:
                    pm = pm.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)
                return pm
    return default_pixmap(256).scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)


def company_pixmap(height: int = 48, max_width: int = 0) -> QPixmap:
    """Festes Herstellerlogo (mitgeliefertes ``logo.png``, unabhängig von der Konfiguration), sonst das Standard-Icon."""
    return logo_pixmap("", height, max_width)


def logos_pixmap(paths, height: int = 28, gap: int = 12) -> QPixmap:
    """Mehrere Logos (z. B. Kundenlogo und Logo) nebeneinander in einem Bild; leere oder fehlende Dateien entfallen.

    Ohne ein einziges Logo: leeres QPixmap (das Feld nimmt dann keinen Platz ein)."""
    pms = []
    for path in paths:
        full = resolve(path)
        if full and os.path.exists(full):
            pm = QPixmap(full)
            if not pm.isNull():
                pms.append(pm.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation))
    if not pms:
        return QPixmap()
    if len(pms) == 1:
        return pms[0]
    out = QPixmap(sum(p.width() for p in pms) + gap * (len(pms) - 1), height)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    x = 0
    for pm in pms:
        p.drawPixmap(x, 0, pm)
        x += pm.width() + gap
    p.end()
    return out


def launch(parent, kind: str, *args, title: str = ""):
    """Anderes Programm des Datenloggers starten (``kind``: logger, config, iocheck; siehe plc_common.program_command).

    Saubere Umgebung (plc_common.child_env); die Fehlerausgabe landet in einer temporären Datei. Bricht das Programm
    in den ersten Sekunden mit einem Fehler ab, erscheint eine Meldung mit den letzten Zeilen statt stiller Untätigkeit.
    Rückgabe: True, wenn der Start angestoßen wurde."""
    import subprocess
    import tempfile
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox
    from plc_common import child_env, program_command
    from plc_i18n import tr
    title = title or tr("Programm starten")
    log = tempfile.NamedTemporaryFile(prefix="plc_start_", suffix=".log", delete=False)
    try:
        proc = subprocess.Popen(program_command(kind, *args), env=child_env(), stdout=log, stderr=log,
                                stdin=subprocess.DEVNULL)
    except OSError as e:
        log.close()
        QMessageBox.critical(parent, title, tr("Das Programm konnte nicht gestartet werden:\n{0}").format(e))
        return False
    log.close()

    def check():
        """Nach einigen Sekunden: abgestürzt? Dann Meldung mit der Fehlerausgabe."""
        code = proc.poll()
        if code is None or code == 0:
            return
        try:
            with open(log.name, encoding="utf-8", errors="replace") as f:
                tail = "".join(f.readlines()[-15:]).strip()
        except OSError:
            tail = ""
        QMessageBox.warning(parent, title, tr("Das Programm wurde mit Fehler {0} beendet.").format(code)
                            + ("\n\n" + tail if tail else ""))
    QTimer.singleShot(5000, check)
    return True


def set_windows_app_id(app_id: str = "PLCDatenlogger"):
    """Unter Windows: eigene Taskleisten-Gruppe, damit das Programm-Icon angezeigt wird."""
    # Nur Windows kennt die 'AppUserModelID'; auf anderen Systemen ist nichts zu tun.
    if sys.platform == "win32":
        try:
            import ctypes
            # Ohne eigene ID gruppiert Windows das Programm unter python.exe und zeigt dessen Icon in der Taskleiste.
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        # Das Icon ist nur kosmetisch: ein Fehler hier darf den Programmstart nie verhindern.
        except Exception:
            pass
