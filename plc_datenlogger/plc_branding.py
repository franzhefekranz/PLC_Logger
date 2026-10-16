"""Programm-Icon und Logo.

* ``app_icon``      liefert das Fenster-/Taskleisten-Icon (konfigurierte Datei oder Standard-Symbol),
* ``logo_pixmap``   liefert das Logo für die Menüleiste rechts oben,
* ``default_pixmap`` zeichnet das Standard-Symbol selbst (Qt-Zeichenbefehle), sodass das Programm
  ohne mitgelieferte Bilddateien auskommt,
* ``set_windows_app_id`` sorgt unter Windows für ein eigenes Taskleisten-Symbol.

Die Bilddateien (PNG, SVG, ICO, JPG ...) werden in der Konfiguration angegeben; relative Pfade
beziehen sich auf den Programm-/Datenordner (siehe plc_common.BASE_DIR).
"""
import math
import os
import sys

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

from plc_common import BASE_DIR


def resolve(path: str) -> str:
    """Relativen Pfad auf den Programmordner beziehen."""
    if not path:
        return ""
    # Absolute Pfade bleiben unverändert, relative gelten ab dem Basisordner des Programms.
    return path if os.path.isabs(path) else os.path.join(BASE_DIR, path)


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
    # QRectF: Kommazahlen sind nur mit dem Float-Rechteck erlaubt (neuere PyQt6-Versionen lehnen
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


def app_icon(*paths) -> QIcon:
    """Erste vorhandene Bilddatei aus paths als Icon, sonst das Standard-Icon."""
    # Der erste Pfad, der existiert und ein lesbares Bild ist, gewinnt (z. B. erst das Icon, dann das Logo).
    for path in paths:
        full = resolve(path)
        if full and os.path.exists(full):
            icon = QIcon(full)
            if not icon.isNull():
                return icon
    # Nichts gefunden: Standard-Symbol verwenden.
    return QIcon(default_pixmap(256))


def logo_pixmap(path: str, height: int = 28) -> QPixmap:
    """Logo auf feste Höhe skaliert (Seitenverhältnis bleibt); ohne Datei das Standard-Icon."""
    # Logo laden (SVG funktioniert, wenn das Qt-SVG-Plugin vorhanden ist).
    full = resolve(path)
    if full and os.path.exists(full):
        pm = QPixmap(full)
        if not pm.isNull():
            # Auf feste Höhe skalieren, Seitenverhältnis bleibt erhalten; SmoothTransformation = hohe Qualität.
            return pm.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)
    return default_pixmap(256).scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)


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
