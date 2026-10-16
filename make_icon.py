"""Erzeugt app.ico und app.png aus dem Standard-Symbol des Programms.

Wird von build.bat aufgerufen, wenn noch keine app.ico existiert. Wer ein eigenes Icon verwenden
möchte, legt einfach eine eigene Datei ``app.ico`` in den Programmordner - sie wird dann nicht
überschrieben und fließt in die .exe-Dateien und den Installer ein.
"""
import sys

from PyQt6.QtGui import QGuiApplication

from s7_branding import default_pixmap

# QPixmap benötigt eine laufende Qt-Anwendung (ohne Fenster genügt QGuiApplication).
app = QGuiApplication(sys.argv)

pixmap = default_pixmap(256)          # dasselbe Symbol, das das Programm ohne eigenes Icon zeichnet
pixmap.save("app.png", "PNG")         # PNG als Vorlage / für Dokumentation
if not pixmap.save("app.ico", "ICO"):
    print("FEHLER: app.ico konnte nicht geschrieben werden. Bitte eine eigene app.ico anlegen.")
    sys.exit(1)
print("app.ico und app.png erzeugt.")
