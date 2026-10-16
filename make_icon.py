"""Erzeugt fehlende Symboldateien für den Build: app.ico (Windows) und app.png (Linux-AppImage).

Vorhandene Dateien werden nie überschrieben. Gibt es schon eine eigene app.ico, entsteht app.png daraus (größtes Bild
der ICO-Datei); sonst werden beide aus dem Standard-Symbol des Programms gezeichnet. Ein eigenes Icon: einfach eine
Datei ``app.ico`` (am besten mit 256×256 Pixeln) in den Programmordner legen.
"""
import os
import sys

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QGuiApplication, QIcon

from plc_branding import default_pixmap

# QPixmap benötigt eine laufende Qt-Anwendung (ohne Fenster genügt QGuiApplication).
app = QGuiApplication(sys.argv)

if os.path.exists("app.ico"):
    icon = QIcon("app.ico")
    sizes = icon.availableSizes() or [QSize(256, 256)]
    pixmap = icon.pixmap(max(sizes, key=lambda s: s.width()))
    if pixmap.width() < 256:                          # kleines Icon: für das AppImage-Symbol vergrößern
        pixmap = pixmap.scaled(256, 256)
else:
    pixmap = default_pixmap(256)          # dasselbe Symbol, das das Programm ohne eigenes Icon zeichnet
    if not pixmap.save("app.ico", "ICO"):
        print("FEHLER: app.ico konnte nicht geschrieben werden. Bitte eine eigene app.ico anlegen.")
        sys.exit(1)
    print("app.ico erzeugt.")
if not os.path.exists("app.png"):
    pixmap.save("app.png", "PNG")
    print("app.png erzeugt.")
