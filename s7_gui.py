"""S7 Datenlogger – Oberfläche (PyQt6 + pyqtgraph).

Die Oberfläche zeigt die Messwerte des Recorders (s7_recorder.py) als y-t-Diagramme an. Aufgezeichnet wird
im Recorder – in eigenen Threads, nicht in der Oberfläche; das Fenster bleibt dadurch flüssig.

Online : aktuelle Werte laufen fortlaufend durch das Zeitfenster, Logging in CSV.
Offline: Ansicht eingefroren; per Scrollbar/Maus in der Zeit zurückscrollen.
         Zwei Lineale (L1/L2) zeigen t- und y-Werte sowie das Delta.
Diagramme liegen auf Seiten (Dock-Fenster/Tabs); mehrere Diagramme je Seite (untereinander, nebeneinander
oder als Raster) mit Mindesthöhe und Scrollleiste. Seiten lassen sich per Drag & Drop neben-/untereinander,
als Tabs oder frei schwebend anordnen. Berechnete Variablen werten Formeln aus den Messwerten aus.
Mehrere Steuerungen werden gleichzeitig gelesen; je Steuerung zeigt eine Status-LED den Verbindungszustand.

Aufbau der Datei (von oben nach unten)
--------------------------------------
* Hilfsfunktion:     open_log (CSV/ZIP öffnen).
* BarStrip:          schmale Balken für Aktualwerte neben einem Diagramm.
* Legende:           CurveLegend (Klicks), CurveSample/BoolSample (Muster, BOOL als Zeitverlauf).
* ChartPanel:        ein Diagramm mit mehreren Y-Achsen, Kurven, Legende, Linealen, Balken; SVG-Export.
* ChartPage:         eine Seite (Dock/Tab) mit Diagrammen (untereinander / nebeneinander / Raster), Scrollleiste.
* PlcLed:            Status-LED mit Name einer Steuerung.
* MainWindow:        Werkzeugleiste, Seiten/Docks, Wertetabelle, Online-/Offline-Modus, Anbindung an den
                     Recorder, Lineale, Screenshots, Konfiguration laden, Webserver.
* run_gui:           Programmstart der Oberfläche (aufgerufen von s7_logger.py).

Datenfluss
----------
SPS -> PlcSampler (je Steuerung ein Thread) -> Sammler-Thread -> Puffer im Recorder (+ CSV-Datei)
     -> MainWindow.refresh (alle 100 ms) holt das Zeitfenster aus dem Recorder, setzt die Kurven und aktualisiert
        Legende, Tabelle, Balken und Status-LEDs.
Im Offline-Modus arbeitet die Oberfläche mit einer Kopie (Momentaufnahme) aller Daten: self.t (Zeiten) und
self.y[i] (Werte der Variable i) sind numpy-Felder.
"""
# Standardbibliothek: contextlib/io/zipfile (CSV und ZIP-Archive öffnen), csv, math, os, re, subprocess
# (Konfigurationsprogramm starten), sys, datetime.
import contextlib
import csv
import io
import math
import os
import re
import subprocess
import sys
import zipfile
from datetime import datetime

# numpy: schnelles Rechnen mit den Messreihen (Ausschnitte, Treppenlinien, Abtastung der BOOL-Verläufe).
import numpy as np
# Qt-Klassen: Kerntypen (Qt, Signale, Timer), Zeichnen (QPainter ...) und Widgets/Fenster.
from PyQt6.QtCore import QMimeData, QPoint, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QAction, QActionGroup, QBrush, QColor, QDrag, QGuiApplication, QImage,
                         QPainter, QPen)
from PyQt6.QtWidgets import (
    QApplication, QGraphicsItem, QDockWidget, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QMainWindow, QMessageBox, QScrollArea, QScrollBar, QSizePolicy,
    QSpinBox, QTableWidget, QMenu, QTableWidgetItem, QToolBar, QToolButton,
    QVBoxLayout, QWidget,
)
# pyqtgraph muss nach PyQt6 importiert werden, damit es dieselbe Qt-Bindung verwendet.
import pyqtgraph as pg  # nach PyQt6 importieren
# ItemSample ist das Muster (Linienstück) vor dem Namen in der Legende; wir leiten eigene Muster davon ab.
from pyqtgraph.graphicsItems.LegendItem import ItemSample

# Eigene Module: Icon/Logo, Datenmodell, Aufzeichnungskern, Webserver, SVG-Export, Hilfsfunktionen.
from s7_branding import app_icon, logo_pixmap, set_windows_app_id
from s7_common import (BASE_DIR, LAYOUTS, PAGE_LAYOUTS, PALETTE, Variable, load_config,
                       load_plcs, remember_config_path,
                        load_settings, program_command, save_settings)
from s7_events import EventLog, event_log_path
from s7_recorder import Recorder, demo_config
from s7_splash import LogoLabel
from s7_svg import build_svg
from s7_util import fmt_time, fmt_value, to_step
from s7_i18n import tr


# ---------------------------------------------------------------------------------------
# Hilfsfunktion
# ---------------------------------------------------------------------------------------
# Als Kontextmanager (with-Anweisung) verwendbar: öffnet CSV-Dateien und ZIP-Archive einheitlich als Textdatei.
@contextlib.contextmanager
def open_log(path):
    """Öffnet eine CSV- oder ZIP-Datei (erste CSV im Archiv) als Textdatei."""
    # ZIP: die erste CSV-Datei im Archiv lesen (archivierte Dateien enthalten genau eine).
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
            if name is None:
                raise ValueError(tr("Das Archiv enthält keine CSV-Datei."))
            with z.open(name) as raw:
                yield io.TextIOWrapper(raw, encoding="utf-8", newline="")
    else:
        # Normale CSV-Datei: UTF-8, newline='' (csv-Modul behandelt Zeilenenden selbst).
        with open(path, newline="", encoding="utf-8") as f:
            yield f


# ---------------------------------------------------------------------------------------
# Balkenanzeige (schmale Balken für die Aktualwerte)
# ---------------------------------------------------------------------------------------
# ------------------------------------------------------------------ Balkenanzeige
class BarStrip(QWidget):
    """Schmale Balken (ein Balken je Variable), skaliert wie die jeweilige Y-Achse."""
    # Breite eines Balkens und Abstand in Pixeln.
    BAR_W = 14
    GAP = 3

    # colors/names: Farbe und Name je Balken. Es wird nichts in einer Liste vorgehalten außer den letzten Werten.
    def __init__(self, colors, names):
        super().__init__()
        self.colors = [QColor(c) for c in colors]
        self.names = names
        # Anfangs 'kein Wert' (NaN): leere Balken.
        self.values = [float("nan")] * len(colors)
        # Skalierung je Balken (min, max) = sichtbarer Bereich der zugehörigen Y-Achse.
        self.ranges = [(0.0, 1.0)] * len(colors)
        # Oberer/unterer Rand: Der Balken füllt genau die Höhe der Plotfläche (ohne Achsenbeschriftung).
        self.top = 0
        self.bottom = 0
        # Feste Breite: Anzahl der Balken * (Balkenbreite + Abstand).
        self.setFixedWidth(len(colors) * (self.BAR_W + self.GAP) + self.GAP)

    # Skalierungsbereiche der Balken setzen (bei Änderung der Y-Achsen).
    def set_ranges(self, ranges):
        self.ranges = ranges
        self.update()

    # Ränder setzen, damit die Balken mit der Plotfläche des Diagramms bündig sind.
    def set_margins(self, top, bottom):
        self.top, self.bottom = int(round(top)), int(round(bottom))   # Qt erwartet ganze Pixel
        self.update()

    # Neue Werte übernehmen; der Tooltip zeigt Name und Wert aller Balken.
    def set_values(self, values):
        self.values = values
        self.setToolTip("\n".join(f"{n}: {v:.4g}" for n, v in zip(self.names, values)))
        self.update()

    # Zeichnet Rahmen und Füllung jedes Balkens. Füllhöhe = (Wert - min) / (max - min), auf 0..1 begrenzt.
    def paintEvent(self, _event):
        h = self.height() - self.top - self.bottom
        if h <= 2:
            return
        p = QPainter(self)
        for k, (color, v) in enumerate(zip(self.colors, self.values)):
            # Skalierung der Y-Achse dieses Balkens; bei min == max Division durch 0 vermeiden.
            ymin, ymax = self.ranges[k]
            span = (ymax - ymin) or 1.0
            x = self.GAP + k * (self.BAR_W + self.GAP)
            if not math.isnan(v):
                frac = min(max((v - ymin) / span, 0.0), 1.0)
                fh = int(round(frac * (h - 1)))
                p.fillRect(x + 1, self.top + h - fh, self.BAR_W - 1, fh, color)
            p.setPen(QPen(QColor("#888888"), 1))
            p.drawRect(x, self.top, self.BAR_W, h)
        p.end()


# ---------------------------------------------------------------------------------------
# Legende und Titelzeile
# ---------------------------------------------------------------------------------------
# ------------------------------------------------------------------ Legende / Titelzeile
# MIME-Typ für das Umordnen der Diagramme per Drag & Drop (Titelzeile).
MIME_CHART = "application/x-s7chart"


# Muster in der Legende, das Mausklicks nicht selbst auswertet (siehe Klassenbeschreibung).
class _NoClickSample(ItemSample):
    """Legenden-Muster ohne eigene Klickbehandlung.

    pyqtgraph blendet die Kurve standardmäßig bei Linksklick auf das Muster aus. Das würde am
    Zustand des Programms (Tabellen-Häkchen, gemerkte Auswahl) vorbei laufen. Deshalb wird der
    Klick an die Legende weitergereicht, die ihn zentral auswertet."""

    # ev.ignore(): der Klick wird an das nächste Element darunter (die Legende) weitergegeben.
    def mouseClickEvent(self, ev):
        ev.ignore()


# Unverändertes pyqtgraph-Muster für analoge Kurven; die Klasse existiert nur, um die Klickbehandlung zu ersetzen.
class CurveSample(_NoClickSample):
    """Muster für analoge Kurven (zeichnet wie das pyqtgraph-Standardmuster)."""


# Muster für BOOL-Variablen in der Legende: normales Linienstück wie bei analogen Kurven. Zusätzlich hält es den Zeitverlauf
# des BOOL-Signals (Auflösung N Punkte über den sichtbaren Zeitbereich), den BoolLanes neben der Legende zeichnet.
class BoolSample(_NoClickSample):
    """Legenden-Muster einer BOOL-Variable plus Halter ihres Zeitverlaufs für die Streifen im Diagramm."""
    N = 800      # Anzahl der Zeitpunkte des Verlaufs über die Diagrammbreite

    def __init__(self, item, color):
        super().__init__(item)
        self.color = QColor(color)
        self.vals = None        # auf N Zeitpunkte abgetasteter Verlauf (numpy) oder None
        self.dim = False        # Kurve ausgeblendet
        self.bold = False       # Kurve hervorgehoben -> dickerer Streifen
        self.faded = False      # eine andere Kurve ist hervorgehoben -> abblenden
        self.on_change = None   # Rückruf, wenn sich Verlauf oder Stil ändern (zeichnet die Streifen neu)

    def _changed(self):
        self.update()
        if self.on_change:
            self.on_change()

    # Ausgeblendete Kurve: Streifen entfällt.
    def set_dim(self, flag):
        self.dim = flag
        self._changed()

    # bold: Kurve ist hervorgehoben (dicker); faded: eine andere Kurve ist hervorgehoben (abblenden).
    def set_emphasis(self, bold, faded):
        self.bold, self.faded = bold, faded
        self._changed()

    def set_history(self, tt, yy, x0, x1):
        """Verlauf aus den Messwerten (tt, yy) für den Zeitbereich x0..x1 übernehmen."""
        if len(tt) == 0 or x1 <= x0:
            self.vals = None
        else:
            grid = np.linspace(x0, x1, self.N)
            # Für jeden Rasterzeitpunkt der letzte Messwert davor (Halte-Verhalten wie bei einer SPS-Variable);
            # davor: NaN (kein Wert).
            idx = np.searchsorted(tt, grid, side="right") - 1
            self.vals = np.where(idx >= 0, yy[np.clip(idx, 0, None)], np.nan)
        self._changed()


# Zeichnet die BOOL-Verläufe neben der Legende über die Breite des Diagramms: je BOOL-Variable in der Höhe ihrer
# Legendenzeile eine Linie (Wert 0) auf der Grundlinie bzw. ein nach oben gehender Streifen (Wert 1) über den dargestellten
# Zeitbereich - wie ein digitales Signal.
class BoolLanes(QGraphicsItem):
    """Kindobjekt der ViewBox (Pixelkoordinaten); liest Verläufe und Zeilenhöhen vom ChartPanel."""

    def __init__(self, panel, vb):
        super().__init__(vb)
        self.panel, self.vb = panel, vb
        self.setZValue(5)

    def boundingRect(self):
        return QRectF(self.vb.boundingRect())

    def paint(self, p, *args):
        panel = self.panel
        rect = self.vb.boundingRect()
        # Die Streifen beginnen rechts von der Legende und reichen bis zum rechten Diagrammrand.
        leg = panel.legend.mapRectToItem(self.vb, panel.legend.boundingRect())
        x_left = leg.right() + 8
        if rect.width() - x_left < 10:
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setClipRect(QRectF(x_left, 0, rect.width() - x_left, rect.height()))
        for vi, sample in panel.legend_samples.items():
            if not isinstance(sample, BoolSample) or sample.vals is None or not panel.user_visible.get(vi, True):
                continue
            label = panel.legend_labels.get(vi)
            if label is None:
                continue
            yc = label.mapToItem(self.vb, QPointF(0, label.boundingRect().height() / 2)).y()
            col = QColor(sample.color)
            col.setAlpha(int(255 * (0.25 if sample.faded else 1.0)))
            vals = sample.vals
            n = len(vals)
            on = np.where(np.isfinite(vals), vals >= 0.5, False)
            dx = rect.width() / (n - 1) if n > 1 else rect.width()
            base = yc + 5.0                              # Grundlinie (Wert 0) am unteren Rand der Legendenzeile
            height = 13.0 if sample.bold else 10.0       # Streifenhöhe (Wert 1) - nur nach oben
            k = 0
            while k < n:
                j = k
                while j + 1 < n and on[j + 1] == on[k]:
                    j += 1
                xa, xb = k * dx, min((j + 1) * dx, rect.width())
                if on[k]:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(col)
                    p.drawRect(QRectF(xa, base - height, max(xb - xa, 1.0), height))
                else:
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setPen(QPen(col, 3 if sample.bold else 2))
                    p.drawLine(QPointF(xa, base), QPointF(xb, base))
                k = j + 1


# pyqtgraph-Legende mit Mausbedienung für Namen und Muster. Die Klicks kommen über die pyqtgraph-eigene
# Szene an (mouseClickEvent), nicht über normale Qt-Mausereignisse.
class CurveLegend(pg.LegendItem):
    """Legende mit Mausbedienung auf den Einträgen (Muster und Name):
    Linksklick = Kurve hervorheben, Rechtsklick = Menü (Kurve aus-/einblenden)."""

    # on_menu(kurve, bildschirmposition): Rechtsklick; on_click(kurve): Linksklick.
    def __init__(self, on_menu, on_click, **kwargs):
        super().__init__(**kwargs)
        self.on_menu = on_menu
        self.on_click = on_click

    # Findet den Eintrag, auf den geklickt wurde: Namensfeld oder Muster. None = daneben.
    def _entry_at(self, pos):
        """Kurve des Legendeneintrags unter der Szenenposition pos (oder None)."""
        for sample, label in self.items:
            if (label.sceneBoundingRect().contains(pos)
                    or sample.sceneBoundingRect().contains(pos)):
                return sample.item
        return None

    # Linksklick -> hervorheben; Rechtsklick -> Menü. ev.accept() verhindert, dass pyqtgraph den Klick weiterverarbeitet
    # (z. B. das Standard-Kontextmenü der Diagrammfläche).
    def mouseClickEvent(self, ev):
        item = self._entry_at(ev.scenePos())
        if item is None:
            ev.ignore()
        elif ev.button() == Qt.MouseButton.RightButton:
            ev.accept()
            self.on_menu(item, ev.screenPos())
        elif ev.button() == Qt.MouseButton.LeftButton:
            ev.accept()
            self.on_click(item)
        else:
            ev.ignore()


# Titelzeile über dem Diagramm: zeigt den Namen und ist Quelle und Ziel beim Umordnen per Drag & Drop.
class ChartTitle(QLabel):
    """Titelzeile eines Diagramms. Ziehen und auf die Titelzeile eines anderen Diagramms
    derselben Seite ablegen ändert die Reihenfolge."""
    # Signal: Nummer des Diagramms, das auf diese Titelzeile gezogen wurde.
    dropped = pyqtSignal(int)

    def __init__(self, text, ci):
        super().__init__(text)
        self.ci = ci
        # Position des Mausklicks, um den Beginn des Ziehens zu erkennen.
        self._press = QPoint()
        self.setStyleSheet("font-weight: bold; padding: 2px 4px;")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(tr("Zum Umordnen ziehen und auf die Titelzeile eines anderen Diagramms ablegen"))

    # Mausklick merken (Startpunkt des Ziehens).
    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._press = ev.position().toPoint()

    # Maus bewegt bei gedrückter Taste: erst nach Überschreiten der Mindeststrecke (startDragDistance) beginnt das Ziehen.
    def mouseMoveEvent(self, ev):
        if (ev.buttons() & Qt.MouseButton.LeftButton
                and (ev.position().toPoint() - self._press).manhattanLength()
                >= QApplication.startDragDistance()):
            # Qt-Drag mit unserem MIME-Typ und der Diagrammnummer als Inhalt.
            drag = QDrag(self)
            md = QMimeData()
            md.setData(MIME_CHART, str(self.ci).encode())
            drag.setMimeData(md)
            drag.exec(Qt.DropAction.MoveAction)

    # Nur Ziehvorgänge mit unserem MIME-Typ annehmen.
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasFormat(MIME_CHART):
            ev.acceptProposedAction()

    # Losgelassen auf dieser Titelzeile: Nummer des gezogenen Diagramms melden (die Seite ordnet um).
    def dropEvent(self, ev):
        try:
            src = int(bytes(ev.mimeData().data(MIME_CHART)).decode())
        except ValueError:
            return
        ev.acceptProposedAction()
        self.dropped.emit(src)


# ---------------------------------------------------------------------------------------
# Diagramm
# ---------------------------------------------------------------------------------------
# ------------------------------------------------------------------ Diagramm-Panel
class ChartPanel(QWidget):
    """Ein Diagramm mit beliebig vielen Y-Achsen (Achse 0 links, weitere rechts)."""

    # Signal: Sichtbarkeit einer Kurve wurde geändert (für die Wertetabelle).
    visibility_changed = pyqtSignal(int, bool)   # Variablen-Index, sichtbar
    # Signal: Titelzeile 'src' wurde auf die Titelzeile 'dst' dieses Diagramms gezogen.
    dropped = pyqtSignal(int, int)               # (verschobenes Diagramm, Ziel-Diagramm)

    # ci: Nummer des Diagramms; cfg: Chart (Name, Achsen); var_idx: Indizes der Variablen dieses Diagramms (in der
    # Gesamtliste); variables: Gesamtliste; show_bars: Balken anzeigen; bool_in_plot: BOOLs auch im Diagramm zeichnen.
    def __init__(self, ci, cfg, var_idx, variables, show_bars, bool_in_plot=False):
        super().__init__()
        self.user_visible = {}            # Variablen-Index -> vom Benutzer sichtbar geschaltet
        self.highlighted = None           # Variablen-Index der hervorgehobenen Kurve
        self.bool_in_plot = bool_in_plot  # BOOL-Kurven zusätzlich im Diagramm zeichnen?
        self.ci = ci
        # Zustand des Panels: Konfiguration, Variablenliste, zuletzt gezeigte Werte (für die Legende) und der Textcache
        # (damit Legendentexte nur bei Änderung neu gesetzt werden).
        self.cfg = cfg
        self.vars = variables
        self._vals = {}
        self._txt = {}
        self.var_idx = var_idx
        # Variablen mit eingeschaltetem Balken (Option 'Balken' in der Konfiguration).
        self.bar_idx = [i for i in var_idx if variables[i].bar]
        n_ax = len(cfg.axes)
        # Achse jeder Variable; ungültige Achsennummern werden auf den gültigen Bereich begrenzt.
        self.var_axis = {vi: min(max(variables[vi].axis, 0), n_ax - 1) for vi in var_idx}

        # Diagrammfläche mit Datums-/Zeitachse unten (die x-Werte sind Unix-Zeitstempel in Sekunden).
        self.plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()})
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        # PlotItem = innere Hauptstruktur des PlotWidget (Achsen, Layout, ViewBox).
        pi = self.plot.plotItem
        # Eigene Legende (mit Klickbehandlung). Sie wird wie die pyqtgraph-Standardlegende in die ViewBox gehängt und beim
        # PlotItem registriert; die Einträge fügen wir unten selbst hinzu (Muster + Name je Variable).
        self.legend = CurveLegend(self._legend_menu, self._legend_click, offset=(10, 10))
        self.legend.setParentItem(pi.vb)
        pi.legend = self.legend
        # Hauptachse (Achse 0, links). Die Maus bedient im Online-Modus nichts; offline wird x freigegeben (MainWindow._apply_mode).
        main_vb = pi.vb
        main_vb.setMouseEnabled(x=False, y=False)

        # Jede weitere Y-Achse ist eine eigene ViewBox mit eigenem Wertebereich über derselben Fläche. Ihre x-Achse ist mit der
        # Hauptachse verknüpft, nur y ist unabhängig. Das ist das übliche pyqtgraph-Muster für mehrere Y-Achsen.
        # --- Y-Achsen: je Achse eine eigene ViewBox (X ist mit der Hauptachse verknüpft)
        self.axis_vbs = [main_vb]
        self.axis_items = [pi.getAxis("left")]
        for k in range(1, n_ax):
            # Zusätzliche ViewBox: nimmt keine Mausereignisse an (die Bedienung bleibt bei der Hauptachse).
            vb2 = pg.ViewBox()
            vb2.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            vb2.setMouseEnabled(x=False, y=False)
            # Erste zusätzliche Achse = die vorhandene rechte Achse des PlotItems; weitere werden daneben eingefügt (Spalte 2 + k).
            if k == 1:
                pi.showAxis("right")
                ax = pi.getAxis("right")
            else:
                ax = pg.AxisItem("right")
                pi.layout.addItem(ax, 2, 1 + k)
            # Die zusätzliche ViewBox liegt direkt in der Szene über der Hauptfläche (nicht im Layout); ihre Geometrie wird
            # in _update_views an die der Hauptfläche angeglichen.
            pi.scene().addItem(vb2)
            # Achse mit der ViewBox verbinden (Skala folgt dem Wertebereich der ViewBox) und x mit der Hauptachse koppeln.
            ax.linkToView(vb2)
            vb2.setXLink(main_vb)
            self.axis_vbs.append(vb2)
            self.axis_items.append(ax)
        # Bei jeder Größenänderung die zusätzlichen ViewBoxen an die Hauptfläche anpassen.
        main_vb.sigResized.connect(self._update_views)

        # --- Kurven. Die Legendeneinträge legen wir selbst an (eigene Muster-Items); deshalb
        #     bekommen die Kurven keinen Namen, sonst würde PlotItem sie zusätzlich eintragen.
        self.curves = {}
        self.legend_samples = {}
        # Für jede Variable eine Kurve (PlotDataItem) in der ViewBox ihrer Achse und einen Legendeneintrag erzeugen.
        for vi in var_idx:
            v = variables[vi]
            ai = self.var_axis[vi]
            is_bool = v.dtype == "BOOL"
            # BOOL: transparent gefüllte Treppenlinie (fillLevel=0 füllt bis zur Nulllinie, fillBrush ist halbtransparent).
            if is_bool:                                    # Treppenlinie, transparent gefüllt
                fill = QColor(v.color)
                fill.setAlpha(60)
                item = pg.PlotDataItem(pen=pg.mkPen(v.color, width=2), fillLevel=0,
                                       fillBrush=pg.mkBrush(fill))
            else:
                item = pg.PlotDataItem(pen=pg.mkPen(v.color, width=2))
            # Achse 0: in das PlotItem einfügen (Hauptachse); alle anderen: in die ViewBox der jeweiligen Achse.
            if ai == 0:
                pi.addItem(item)
            else:
                self.axis_vbs[ai].addItem(item)
            # Nur den sichtbaren Ausschnitt zeichnen und bei vielen Punkten pro Pixel vergröbern ('peak' behält Spitzen).
            item.setClipToView(True)
            item.setDownsampling(auto=True, method="peak")
            # Legendenmuster: BOOL als kleiner Zeitverlauf, sonst das normale Linienstück; Name = Variablenname (wird später
            # mit dem aktuellen Wert überschrieben, siehe set_legend_values).
            sample = BoolSample(item, v.color) if is_bool else CurveSample(item)
            self.legend.addItem(sample, v.name)
            self.curves[vi] = item
            self.legend_samples[vi] = sample
            self.user_visible[vi] = True
            # BOOL-Kurven sind im Diagramm standardmäßig unsichtbar (Anzeige nur in der Legende, achsenunabhängig).
            if is_bool:                                    # BOOL: standardmäßig nur in der Legende
                item.setVisible(self.bool_in_plot)

        # Zu jeder Variable das Textfeld (Label) ihres Legendeneintrags merken, um den Text später ändern zu können.
        # --- Legendeneinträge (Label) je Variable
        self.legend_labels = {}
        for sample, label in self.legend.items:
            for vi, c in self.curves.items():
                if sample.item is c:
                    self.legend_labels[vi] = label
        # BOOL-Linien/-Streifen neben der Legende (über die Diagrammbreite); jede Änderung eines Verlaufs zeichnet sie neu.
        self.bool_lanes = BoolLanes(self, pi.vb)
        pi.vb.sigResized.connect(lambda *_: self.bool_lanes.update())
        for smp in self.legend_samples.values():
            if isinstance(smp, BoolSample):
                smp.on_change = self.bool_lanes.update

        # Achsen: Beschriftung = Achsenname, Farbe = Farbe der ersten Variable auf dieser Achse; feste Breite, damit
        # untereinanderliegende Diagramme bündig sind.
        # --- Achsenbeschriftung in der Farbe der ersten zugeordneten Variable
        self.axis_colors = []
        for ai, a in enumerate(cfg.axes):
            here = [variables[vi] for vi in var_idx if self.var_axis[vi] == ai]
            col = here[0].color if here else "#888888"
            self.axis_colors.append(col)
            ax = self.axis_items[ai]
            ax.setLabel(a.name, color=col)
            ax.setPen(pg.mkPen(col))
            ax.setTextPen(pg.mkPen(col))
            ax.setWidth(70)

        # Lineale: zwei senkrechte, verschiebbare Linien. Gelb = L1, Cyan = L2; die Beschriftung 'L1'/'L2' sitzt oben an der Linie.
        # Sie sind nur im Offline-Modus sichtbar und werden vom Hauptfenster über alle Diagramme synchronisiert.
        # --- zwei Lineale (nur offline sichtbar)
        self.rulers = []
        for k, col in enumerate(("#ffd400", "#00e5ff")):
            ln = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen(col, width=2),
                                 label=f"L{k + 1}",
                                 labelOpts={"position": 0.92, "color": col})
            ln.setVisible(False)
            # ignoreBounds: die Lineale beeinflussen die automatische Skalierung der Achsen nicht.
            self.plot.addItem(ln, ignoreBounds=True)
            self.rulers.append(ln)

        # Balken neben dem Diagramm: je ein Balken pro Variable mit eingeschalteter Balkenoption.
        # --- Balken
        self.bars = BarStrip([variables[i].color for i in self.bar_idx],
                             [variables[i].name for i in self.bar_idx])
        self.bars.setVisible(show_bars and bool(self.bar_idx))
        # Ändert sich der Wertebereich einer Achse, muss die Balkenskalierung folgen.
        for vb in self.axis_vbs:
            vb.sigYRangeChanged.connect(lambda *_: self._update_bar_ranges())
        # Bei Größenänderung die Balken wieder bündig zur Plotfläche ausrichten.
        main_vb.sigResized.connect(self._sync_bars)

        # Titelzeile (Name des Diagramms) oben; Ziehen auf eine andere Titelzeile ordnet die Diagramme um.
        self.title = ChartTitle(cfg.name, ci)
        self.title.dropped.connect(lambda src: self.dropped.emit(src, self.ci))
        # Layout: oben die Titelzeile, darunter in einer Zeile die Diagrammfläche (dehnbar) und die Balken (feste Breite).
        row = QHBoxLayout()
        row.setSpacing(2)
        row.addWidget(self.plot, 1)
        row.addWidget(self.bars)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        lay.addWidget(self.title)
        lay.addLayout(row, 1)
        # Anfangszustand herstellen: Geometrien der Zusatzachsen und Balkenskalierung.
        self._update_views()
        self._update_bar_ranges()

    # Geometrie der zusätzlichen ViewBoxen an die der Hauptfläche anpassen (gleiche Position und Größe).
    def _update_views(self, *_):
        main = self.plot.plotItem.vb
        for vb2 in self.axis_vbs[1:]:
            vb2.setGeometry(main.sceneBoundingRect())
            vb2.linkedViewChanged(main, vb2.XAxis)

    # Balkenskalierung = aktuell sichtbarer y-Bereich der Achse jeder Variable.
    def _update_bar_ranges(self):
        self.bars.set_ranges([tuple(self.axis_vbs[self.var_axis[vi]].viewRange()[1])
                              for vi in self.bar_idx])

    def _sync_bars(self, *_):
        """Balken vertikal exakt an der Plotfläche (ohne Achsenbeschriftung) ausrichten."""
        r = self.plot.plotItem.vb.sceneBoundingRect()
        tl = self.plot.mapFromScene(r.topLeft())
        br = self.plot.mapFromScene(r.bottomRight())
        self.bars.set_margins(max(tl.y(), 0), max(self.plot.height() - br.y(), 0))

    def apply_scaling(self, force_auto):
        """Jede Y-Achse: Auto-Skalierung oder feste Grenzen. force_auto überschreibt alles."""
        # Je Achse: automatisch an die sichtbaren Daten anpassen (setAutoVisible: nur der gezeigte Zeitausschnitt zählt)
        # oder feste Grenzen aus der Konfiguration setzen.
        for ai, a in enumerate(self.cfg.axes):
            vb = self.axis_vbs[ai]
            if force_auto or a.auto:
                vb.setAutoVisible(y=True)
                vb.enableAutoRange(axis="y")
            else:
                vb.setYRange(a.y_min, a.y_max, padding=0)

    # Balken ein-/ausblenden; ohne Balken-Variablen bleibt der Streifen immer ausgeblendet.
    def set_bars_visible(self, flag):
        self.bars.setVisible(flag and bool(self.bar_idx))

    # Titelzeile nur zeigen, wenn die Seite mehrere Diagramme enthält (sonst steht der Name schon im Tab).
    def title_visible(self, flag):
        self.title.setVisible(flag)

    # --- Kurven ein-/ausblenden (Rechtsklick auf den Namen in der Legende)
    def _curve_vi(self, item):
        """Variablen-Index der Kurve item."""
        return next((v for v, c in self.curves.items() if c is item), None)

    # Rechtsklick-Menü der Legende: Kurve ein-/ausblenden bzw. alle Kurven dieses Diagramms einblenden.
    def _legend_menu(self, item, pos):
        vi = self._curve_vi(item)
        if vi is None:
            return
        menu = QMenu(self)
        shown = self.user_visible.get(vi, True)
        act = menu.addAction(tr("Kurve ausblenden") if shown else tr("Kurve einblenden"))
        act_all = menu.addAction(tr("Alle Kurven dieses Diagramms einblenden"))
        # Menü an der Mausposition (Bildschirmkoordinaten) anzeigen und auf die Auswahl warten.
        chosen = menu.exec(QPoint(int(pos.x()), int(pos.y())))
        if chosen is act:
            self.set_curve_visible(vi, not shown)
        elif chosen is act_all:
            for v in self.curves:
                self.set_curve_visible(v, True)

    # Der 'Benutzerzustand' (user_visible) unterscheidet sich vom tatsächlichen Zustand des Kurven-Items: BOOLs sind im Diagramm
    # auch dann unsichtbar, wenn sie 'eingeblendet' sind, solange 'Bool im Diagramm' aus ist.
    def set_curve_visible(self, vi, flag):
        """Kurve ein-/ausblenden (Zustand des Benutzers) und Tabelle/Legende nachziehen."""
        if vi not in self.curves or self.user_visible.get(vi, True) == flag:
            return
        self.user_visible[vi] = flag
        self._apply_visibility(vi)
        self.set_legend_values()
        self.visibility_changed.emit(vi, flag)

    # Tatsächliche Sichtbarkeit der Kurve setzen; das Legendenmuster wird bei ausgeblendeten BOOLs abgeblendet.
    def _apply_visibility(self, vi):
        """Sichtbarkeit des Kurven-Items aus Benutzerwunsch und Bool-Einstellung ableiten."""
        show = self.user_visible[vi]
        if self.vars[vi].dtype == "BOOL":
            show = show and self.bool_in_plot       # BOOLs sind sonst nur in der Legende zu sehen
        self.curves[vi].setVisible(show)
        sample = self.legend_samples[vi]
        if isinstance(sample, BoolSample):
            sample.set_dim(not self.user_visible[vi])
        sample.update()

    # Schalter 'Bool im Diagramm': BOOL-Kurven zusätzlich im Diagramm zeichnen.
    def set_bool_in_plot(self, flag):
        """BOOL-Kurven zusätzlich als gefüllte Treppenlinie im Diagramm zeichnen (abhängig von der Achse)."""
        self.bool_in_plot = flag
        for vi in self.curves:
            if self.vars[vi].dtype == "BOOL":
                self._apply_visibility(vi)

    # Wird von MainWindow.update_bool_strips aufgerufen.
    def set_bool_history(self, vi, tt, yy, x0, x1):
        """Zeitverlauf für den BOOL-Streifen in der Legende setzen."""
        sample = self.legend_samples.get(vi)
        if isinstance(sample, BoolSample):
            sample.set_history(tt, yy, x0, x1)

    # --- Hervorheben (Linksklick auf den Namen in der Legende)
    # Linksklick auf einen Legendeneintrag: Kurve hervorheben bzw. die Hervorhebung wieder aufheben.
    def _legend_click(self, item):
        vi = self._curve_vi(item)
        if vi is not None:
            self.toggle_highlight(vi)

    def toggle_highlight(self, vi):
        """Kurve hervorheben (dicke Linie, fetter Name, übrige abgeblendet); nochmal klicken hebt auf."""
        # Nochmal auf dieselbe Kurve klicken hebt die Hervorhebung auf; sonst wird die neue Kurve hervorgehoben.
        self.highlighted = None if self.highlighted == vi else vi
        h = self.highlighted
        # Für jede Kurve: hervorgehoben = dicke Linie, im Vordergrund (ZValue), volle Deckkraft; die übrigen werden blass (30 %).
        for v, curve in self.curves.items():
            on = (v == h)
            curve.setPen(pg.mkPen(self.vars[v].color, width=4 if on else 2))
            curve.setZValue(10 if on else 0)
            curve.setOpacity(1.0 if (h is None or on) else 0.3)
            # BOOL-Streifen in der Legende folgen der Hervorhebung (dickere Linie bzw. abgeblendet).
            sample = self.legend_samples[v]
            if isinstance(sample, BoolSample):
                sample.set_emphasis(on, h is not None and not on)
        # Der Name der hervorgehobenen Kurve wird fett gesetzt (in set_legend_values).
        self.set_legend_values()

    # --- Werte in der Legende (Name: Wert, in der Farbe der Variable)
    # Legendentexte aktualisieren: 'Name: Wert' in der Farbe der Variable, fett bei Hervorhebung, grau mit '(aus)' wenn ausgeblendet.
    # values = {Variablen-Index: aktueller Wert}; None = vorherige Werte beibehalten (nur Stil neu setzen).
    def set_legend_values(self, values=None):
        if values is not None:
            self._vals = values
        for vi, label in self.legend_labels.items():
            v = self.vars[vi]
            val = self._vals.get(vi)
            txt = v.name if val is None else f"{v.name}: {fmt_value(val, v.dtype)}"
            bold = (vi == self.highlighted)
            if self.user_visible.get(vi, True):
                color = v.color
            else:
                txt, color = f"{txt} (aus)", "#888888"
            # Nur neu setzen, wenn sich Text, Farbe oder Fettdruck geändert haben (setText ist vergleichsweise teuer).
            key = (txt, color, bold)
            if self._txt.get(vi) == key:          # unverändert: nicht neu zeichnen
                continue
            self._txt[vi] = key
            label.setText(txt, color=color, bold=bold)
        # Die Legende an die neue Textbreite anpassen (Methode je nach pyqtgraph-Version vorhanden).
        if hasattr(self.legend, "updateSize"):
            self.legend.updateSize()
        # Muster neu zeichnen lassen (z. B. BOOL-Streifen).
        for sample, _label in self.legend.items:
            sample.update()
        self.bool_lanes.update()

    # Textfarbe aller Legendeneinträge einheitlich ändern (derzeit nicht verwendet, da die Einträge variablenfarbig sind).
    def _legend_text(self, color):
        leg = self.legend
        if hasattr(leg, "setLabelTextColor"):
            leg.setLabelTextColor(color)
        else:  # ältere pyqtgraph-Versionen
            for _sample, lbl in getattr(leg, "items", []):
                lbl.setText(lbl.text, color=color)

    # Für Screenshots mit hellem Hintergrund: Hintergrund weiß, Zeitachse und Lineale dunkel. set_light_theme(False)
    # stellt den Normalzustand wieder her.
    def set_light_theme(self, on):
        """Heller Hintergrund mit dunkler Schrift (für Screenshots/Berichte); False stellt zurück."""
        fg = "#000000" if on else pg.getConfigOption("foreground")
        self.plot.setBackground("#ffffff" if on else "default")
        bottom = self.plot.getAxis("bottom")
        bottom.setPen(pg.mkPen(fg))
        bottom.setTextPen(pg.mkPen(fg))
        # Die gelben/cyanfarbenen Lineale sind auf Weiß schlecht zu erkennen -> dunklere Töne.
        cols = ("#b38f00", "#008ba3") if on else ("#ffd400", "#00e5ff")
        for ln, col in zip(self.rulers, cols):
            ln.setPen(pg.mkPen(col, width=2))
            # Beschriftung der Linie ('L1'/'L2') mit umfärben; falls die pyqtgraph-Version das nicht kann, ist es nicht schlimm.
            try:
                ln.label.setColor(QColor(col))
            except Exception:
                pass


    # ---- SVG-Export (eigene Zeichnung aus den Daten, siehe s7_svg.py) ----
    def svg_text(self, title, light=False):
        """SVG-Text dieses Diagramms: Achsen, sichtbare Kurven, Lineale und Legende wie auf dem Bildschirm.

        Das Diagramm wird nicht über Qt gerendert (QSvgGenerator gibt pyqtgraph-Kurven nicht zuverlässig wieder und
        verschiebt die Lineale), sondern aus den angezeigten Daten neu gezeichnet."""
        w, h = max(self.plot.width(), 480), max(self.plot.height(), 280)
        x0, x1 = self.axis_vbs[0].viewRange()[0]
        axes = []
        for ai, a in enumerate(self.cfg.axes):
            lo, hi = self.axis_vbs[ai].viewRange()[1]
            col = self.axis_colors[ai] if ai < len(self.axis_colors) else "#888888"
            axes.append(dict(name=a.name, color=col, lo=lo, hi=hi))
        # Kurven: die gerade angezeigten (sichtbaren) Daten; getData() liefert den sichtbaren, ggf. vergröberten Ausschnitt.
        series = []
        for vi, item in self.curves.items():
            if not item.isVisible():
                continue
            xd, yd = item.getData()
            if xd is None or len(xd) == 0:
                continue
            on = vi == self.highlighted
            faded = self.highlighted is not None and not on
            series.append(dict(x=np.asarray(xd, dtype=float), y=np.asarray(yd, dtype=float),
                               color=self.vars[vi].color, axis=self.var_axis[vi],
                               fill=self.vars[vi].dtype == "BOOL", width=4 if on else 2,
                               opacity=0.3 if faded else 1.0))
        # Lineale (nur offline sichtbar) in den Farben des jeweiligen Themas.
        cols = ("#b38f00", "#008ba3") if light else ("#ffd400", "#00e5ff")
        rulers = [dict(x=float(ln.value()), color=cols[k], label=f"L{k + 1}")
                  for k, ln in enumerate(self.rulers) if ln.isVisible()]
        # Legende mit den aktuell angezeigten Werten; BOOL als kleiner Verlauf (aus dem Legendenmuster).
        legend = []
        for vi in self.var_idx:
            v = self.vars[vi]
            val = self._vals.get(vi)
            txt = v.name if val is None else f"{v.name}: {fmt_value(val, v.dtype)}"
            shown = self.user_visible.get(vi, True)
            strip = None
            smp = self.legend_samples.get(vi)
            if isinstance(smp, BoolSample) and smp.vals is not None:
                strip = np.asarray(smp.vals)
            legend.append(dict(text=txt if shown else f"{txt} (aus)", color=v.color if shown else "#888888",
                               strip=strip, bold=vi == self.highlighted, dim=not shown))
        return build_svg(int(w), int(h), title, (x0, x1), axes, series, rulers, legend, light)

    def export_svg(self, path, title, light=False):
        """Diagramm als SVG-Datei speichern."""
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.svg_text(title, light))


# ---------------------------------------------------------------------------------------
# Seite (Tab/Dock) mit mehreren Diagrammen
# ---------------------------------------------------------------------------------------
class ChartPage(QScrollArea):
    """Eine Seite (Dock/Tab) mit einem oder mehreren Diagrammen. Jedes Diagramm hat eine Mindesthöhe
    (bzw. -breite); passen nicht alle ins Fenster, erscheint eine Scrollleiste.

    Anordnung der Diagramme: ``untereinander`` (eine Spalte), ``nebeneinander`` (eine Zeile) oder
    ``raster`` (Zeilen und Spalten; Spaltenzahl vorgegeben oder automatisch ~ Wurzel der Diagrammzahl)."""
    # Mindesthöhe jedes Diagramms (und -breite bei mehreren Spalten) in Pixeln.
    MIN_H = 240
    MIN_W = 380

    # panels: ChartPanel-Objekte dieser Seite; mode: Anordnung; columns: Spaltenzahl im Raster (0 = automatisch).
    def __init__(self, panels, mode="untereinander", columns=0):
        super().__init__()
        self.panels = list(panels)
        self.mode, self.columns = mode, columns
        # widgetResizable: der Inhalt passt sich der Fensterbreite an; ist er höher als der sichtbare Bereich, erscheint die Scrollleiste.
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # Auch eine sehr kleine Seite bleibt bedienbar (sie scrollt dann).
        self.setMinimumHeight(120)
        # Innenwidget mit dem Gitter-Layout (alle Anordnungen sind Spezialfälle eines Gitters), das alle Diagramme aufnimmt.
        body = QWidget()
        self.grid = QGridLayout(body)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(6)
        ncol = self.n_cols()
        # Jedes Diagramm: Mindestgröße setzen, Titelzeile nur zeigen, wenn es mehrere gibt, und das Umordnen per Drag & Drop anbinden.
        for p in self.panels:
            p.setMinimumHeight(self.MIN_H)
            if ncol > 1:
                p.setMinimumWidth(self.MIN_W)
            p.title_visible(len(self.panels) > 1)
            p.dropped.connect(self.on_dropped)
        self.layout_panels()
        self.setWidget(body)

    def n_cols(self):
        """Anzahl der Spalten der aktuellen Anordnung."""
        n = max(len(self.panels), 1)
        if self.mode == "untereinander":
            return 1
        if self.mode == "nebeneinander":
            return n
        return min(self.columns if self.columns > 0 else math.ceil(math.sqrt(n)), n)

    def layout_panels(self):
        """Diagramme der Reihe nach in das Gitter setzen (Zeile für Zeile). Im Raster füllt das letzte Diagramm
        den Rest einer unvollständigen Zeile aus."""
        # Alte Positionen und Dehnungsfaktoren verwerfen.
        for p in self.panels:
            self.grid.removeWidget(p)
        for r in range(self.grid.rowCount()):
            self.grid.setRowStretch(r, 0)
        for c in range(self.grid.columnCount()):
            self.grid.setColumnStretch(c, 0)
        ncol, n = self.n_cols(), len(self.panels)
        for k, p in enumerate(self.panels):
            r, c = divmod(k, ncol)
            span = ncol - c if (k == n - 1 and self.mode == "raster") else 1
            self.grid.addWidget(p, r, c, 1, span)
        for r in range((n + ncol - 1) // ncol):
            self.grid.setRowStretch(r, 1)
        for c in range(ncol):
            self.grid.setColumnStretch(c, 1)

    def on_dropped(self, src_ci, dst_ci):
        """Diagramm per Drag & Drop an die Position eines anderen Diagramms verschieben."""
        src = next((p for p in self.panels if p.ci == src_ci), None)
        dst = next((p for p in self.panels if p.ci == dst_ci), None)
        if src is None or dst is None or src is dst:
            return
        # Reihenfolge ändern: das gezogene Diagramm hinter (bei Ziehen nach hinten) bzw. vor (bei Ziehen nach vorn) das Ziel setzen.
        si, di = self.panels.index(src), self.panels.index(dst)
        self.panels.remove(src)
        self.panels.insert(self.panels.index(dst) + (1 if si < di else 0), src)
        # Gitter neu aufbauen: alle Diagramme in neuer Reihenfolge wieder einsetzen.
        self.layout_panels()


# ---------------------------------------------------------------------------------------
# Status-LED einer Steuerung
# ---------------------------------------------------------------------------------------
# Farben der Zustände: grau = aus/gestoppt, gelb = Verbindungsaufbau, grün = verbunden, rot = Fehler.
LED_COLORS = {"off": "#7d8590", "connecting": "#e6b800", "ok": "#2ecc71", "error": "#e5484d"}


class _Dot(QWidget):
    """Ein farbiger Punkt (die eigentliche LED)."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(14, 14)
        self.color = QColor(LED_COLORS["off"])

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(self.color.darker(160), 1))
        p.setBrush(QBrush(self.color))
        p.drawEllipse(1, 1, 11, 11)
        p.end()


class PlcLed(QWidget):
    """Status-LED mit Name; der Tooltip zeigt den Text des Zustands (Verbindung, Fehler, Zykluszeit)."""

    def __init__(self, name):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(4)
        self.dot = _Dot()
        self.lbl = QLabel(name)
        lay.addWidget(self.dot)
        lay.addWidget(self.lbl)
        self._key = None

    def set_state(self, state, text):
        """Zustand anzeigen; wird nur neu gezeichnet, wenn er sich geändert hat."""
        if self._key == (state, text):
            return
        self._key = (state, text)
        self.dot.color = QColor(LED_COLORS.get(state, LED_COLORS["off"]))
        self.dot.update()
        self.setToolTip(text)


# ---------------------------------------------------------------------------------------
# Hauptfenster
# ---------------------------------------------------------------------------------------
class MainWindow(QMainWindow):
    # config_path: Konfigurationsdatei (INI/TXT); demo: Demo-Modus vorwählen.
    def __init__(self, config_path, demo=False):
        super().__init__()
        self.resize(1400, 800)
        self.config_path = config_path
        # Konfiguration laden; ohne INI-Datei erscheint eine leere Standardkonfiguration, bei einer fehlerhaften Datei
        # eine Meldung (das Fenster öffnet trotzdem, die Konfiguration kann dann neu geladen werden).
        self.conn, self.charts, self.vars, self.plcs = self._read_config(config_path)
        # Aktuelle Anordnung der Seiten (untereinander/nebeneinander/tabs) und der Diagramme innerhalb einer Seite.
        self.layout_mode = self.conn["anordnung"]
        self.page_mode = self._page_mode_from(self.conn)
        # Aufzeichnung: der Recorder (Threads, Puffer, CSV, Archiv). source: Herkunft der angezeigten Daten
        # ('rec' = laufende/gestoppte Aufzeichnung, 'csv' = geladene Datei, 'none' = noch nichts).
        self.rec = None
        self.source = "none"
        # Webserver (optional) und der Schlüssel seiner Einstellungen (zum Erkennen von Änderungen).
        self.web = None
        self._web_key = None
        # Betriebsart: True = online (fortlaufend), False = offline (Rückblick). dirty: Anzeige muss beim nächsten Takt
        # aktualisiert werden, auch ohne neue Daten (z. B. nach Änderung der Fensterbreite).
        self.online = True
        self.dirty = False
        # _block/_rblock: Sperren gegen Rückkopplung (Programm ändert Zeitbereich bzw. Lineale und löst dabei selbst Ereignisse aus).
        self._block = False
        self._rblock = False
        # Offline: Zeitgrenzen der Momentaufnahme, aktueller Ausschnitt (view_x) und Lineal-Zeitpunkte.
        self.snap_t0 = 0.0
        self.snap_t1 = 0.0
        self.view_x = (0.0, 1.0)
        self.ruler_t = [None, None]
        # Angezeigte Daten: self.t = Zeitstempel (aufsteigend), self.y[i] = Werte der Variable i (numpy-Felder).
        # Online ist das der Ausschnitt des Zeitfensters, offline eine Kopie aller Daten.
        self.t = np.empty(0)
        self.y = np.empty((len(self.vars), 0))
        # Anzeigeobjekte: Kurven je Variable, Panels je Diagramm, Docks je Seite sowie Zuordnungen für den schnellen Zugriff.
        self.curves = []
        self.panels = []
        self.page_docks = []
        self.dock_of_chart = {}
        self.panel_of_var = {}
        # Vom Benutzer ausgeblendete Kurven (nach Variablenname), bleiben beim Neuaufbau der Anzeige erhalten.
        self.hidden = set()     # ausgeblendete Kurven (Variablennamen)
        # master: erstes Diagramm (alle anderen sind mit seiner Zeitachse verknüpft); row_of: Variable -> Zeile der Wertetabelle.
        self.master = None
        self.row_of = {}
        # Status-LEDs (eine je Steuerung) und der Textspeicher der letzten Meldungen.
        self.leds = []
        # Gemerkte Dock-Anordnungen (QMainWindow.saveState) je Seitenstruktur, damit sie beim Neuaufbau erhalten bleiben.
        self._states = {}
        self._sig = None
        self._shot_dir = BASE_DIR
        # Ereignisprotokoll der Trigger: Viewer-Fenster (bei Bedarf angelegt) und Protokoll ohne laufende Aufzeichnung.
        self.event_viewer = None
        self._offline_events = None
        self._ev_seen = None
        # Oberfläche und Anzeige aufbauen, dann den 100-ms-Takt starten, der die Anzeige aktualisiert (refresh).
        self._build_ui()
        self.act_demo.setChecked(demo)
        self.setWindowTitle(self._title())
        self._sync_menus()
        self._rebuild()
        self._rebuild_leds()
        self._apply_web()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(100)
        # Zähler der offenen Ereignisse jede Sekunde prüfen (auch ohne Aufzeichnung, z. B. neben einem Headless-Logger).
        self.ev_timer = QTimer(self)
        self.ev_timer.timeout.connect(self.update_event_button)
        self.ev_timer.start(1000)
        self.update_event_button()

    # Konfiguration einer Datei lesen -> (conn, charts, variables, plcs); bei Fehlern Meldung und Standardkonfiguration.
    def _read_config(self, path):
        try:
            conn, charts, variables = load_config(path)
            return conn, charts, variables, load_plcs(path)
        except Exception as e:
            QMessageBox.warning(self, tr("Konfiguration"), tr("Die Konfiguration konnte nicht gelesen werden:\n{0}\n\n{1}").format(path, e))
            from s7_common import Chart, Plc, default_connection
            return default_connection(), [Chart()], [], [Plc()]

    # Anordnung der Diagramme innerhalb einer Seite: aus der Konfiguration, sonst abgeleitet von der Seitenanordnung
    # (ältere Konfigurationen: 'nebeneinander' stellte auch die Diagramme einer Seite nebeneinander).
    @staticmethod
    def _page_mode_from(conn):
        return conn.get("seite_anordnung") or ("nebeneinander" if conn["anordnung"] == "nebeneinander"
                                               else "untereinander")

    # Fenstertitel: Programmname, Projektname und Name der Konfigurationsdatei.
    def _title(self):
        proj = self.conn.get("projekt", "")
        return "S7 Datenlogger" + (f" – {proj}" if proj else "") + f"  [{os.path.basename(self.config_path)}]"

    # ---------------- UI ----------------
    def _build_ui(self):
        # Fenster-Icon: konfiguriertes Icon, sonst das Logo, sonst das Standard-Symbol.
        self.setWindowIcon(app_icon(self.conn.get("icon", ""), self.conn.get("logo", "")))
        # Verschachtelte Docks erlauben (frei kombinierbar: nebeneinander, übereinander, als Tabs).
        self.setDockNestingEnabled(True)
        # Die Diagramme liegen alle in Docks; das zentrale Widget bleibt leer und wird versteckt, damit die Docks das ganze Fenster füllen.
        central = QWidget()
        self.setCentralWidget(central)
        central.hide()  # Diagramm-Docks füllen das gesamte Fenster

        # Wertetabelle als Dock rechts: online 'Aktuell', offline Lineal 1, Lineal 2 und Differenz.
        # Werte-/Lineal-Tabelle
        self.dock = QDockWidget(tr("Werte"), self)
        self.dock.setObjectName("werte")
        box = QWidget()
        bl = QVBoxLayout(box)
        self.lbl_time = QLabel("–")
        self.table = QTableWidget(0, 4)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemChanged.connect(self.on_item_changed)
        bl.addWidget(self.lbl_time)
        bl.addWidget(self.table)
        self.dock.setWidget(box)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)

        # ---- Aktionen (Werkzeugleiste und Menüs) ----
        # Aktionen
        # Start/Stop: umschaltbar; toggled meldet sowohl das Anhaken als auch das Abhaken.
        self.act_run = QAction(tr("▶ Start"), self)
        self.act_run.setCheckable(True)
        self.act_run.toggled.connect(self.on_run_toggled)
        # Online/Offline-Umschalter (Standard: online).
        self.act_online = QAction(tr("Online"), self)
        self.act_online.setCheckable(True)
        self.act_online.setChecked(True)
        self.act_online.toggled.connect(self.set_online)
        act_load = QAction(tr("CSV laden"), self)
        act_load.triggered.connect(self.load_csv)
        act_load_db = QAction(tr("Aus Datenbank laden …"), self)
        act_load_db.setShortcut("Ctrl+D")
        act_load_db.setToolTip(tr("Zeitraum aus der Datenbank wählen und offline anzeigen"))
        act_load_db.triggered.connect(self.load_db)
        act_cfg = QAction(tr("Konfig-Editor"), self)
        act_cfg.setToolTip(tr("Konfigurationsprogramm mit dieser Konfigurationsdatei öffnen"))
        act_cfg.triggered.connect(self.open_config)
        # Konfigurationsdatei laden (beliebiger Dateiname) bzw. die aktuelle neu einlesen (nach Änderungen im Editor).
        act_cfg_load = QAction(tr("Config laden …"), self)
        act_cfg_load.setShortcut("Ctrl+O")
        act_cfg_load.setToolTip(tr("Andere Konfigurationsdatei laden (beliebiger Dateiname)"))
        act_cfg_load.triggered.connect(self.load_config_file)
        act_cfg_reload = QAction(tr("Konfiguration neu laden"), self)
        act_cfg_reload.setShortcut("F5")
        act_cfg_reload.triggered.connect(lambda: self.set_config(self.config_path))
        act_web = QAction(tr("Webserver-Adresse …"), self)
        act_web.triggered.connect(self.show_web_url)
        act_quit = QAction(tr("Beenden"), self)
        act_quit.triggered.connect(self.close)
        # Die Werteanzeige schaltet das Dock der Wertetabelle (dessen eigene Anzeigen-Aktion wird wiederverwendet).
        self.act_vals = self.dock.toggleViewAction()
        self.act_vals.setText(tr("Werteanzeige"))
        # Balken: Anfangszustand aus der Konfiguration; Umschalten wirkt sofort auf alle Diagramme.
        self.act_bars = QAction(tr("Balken"), self)
        self.act_bars.setCheckable(True)
        self.act_bars.setChecked(bool(self.conn["balken"]))
        self.act_bars.toggled.connect(
            lambda on: [p.set_bars_visible(on) for p in self.panels])
        # Lineale auf 1/3 und 2/3 des sichtbaren Zeitbereichs zurücksetzen (nur offline sinnvoll).
        act_rul = QAction(tr("Lineale zurücksetzen"), self)
        act_rul.triggered.connect(self.reset_rulers)
        # Demo-Modus: simulierte Werte; wird vor dem Start gewählt und ist während der Aufzeichnung gesperrt.
        self.act_demo = QAction(tr("Demo"), self)
        self.act_demo.setCheckable(True)
        self.act_demo.setToolTip(tr("Simulierte Werte statt SPS-Verbindung (vor dem Start wählen)"))
        # BOOL-Kurven zusätzlich im Diagramm zeichnen (Standard aus: nur Streifen in der Legende).
        self.act_boolplot = QAction(tr("Bool im Diagramm"), self)
        self.act_boolplot.setCheckable(True)
        self.act_boolplot.setToolTip(tr("BOOL-Kurven zusätzlich im Diagramm zeichnen (sonst nur als Linie/Streifen neben dem Namen in der Legende)"))
        self.act_boolplot.toggled.connect(
            lambda on: ([p.set_bool_in_plot(on) for p in self.panels], setattr(self, "dirty", True)))
        # Y-Auto: alle Y-Achsen automatisch skalieren (überschreibt feste Bereiche aus der Konfiguration).
        self.act_yauto = QAction(tr("Y-Auto"), self)
        self.act_yauto.setCheckable(True)
        self.act_yauto.setToolTip(tr("Alle Y-Achsen automatisch skalieren (überschreibt feste Bereiche)"))
        self.act_yauto.toggled.connect(
            lambda on: [p.apply_scaling(on) for p in self.panels])

        # Screenshot-Menü (Einträge je Diagramm werden in _rebuild erzeugt) und die Option für hellen Hintergrund.
        self.menu_shot = QMenu(tr("Screenshot"), self)  # wird je Diagramm gefüllt
        self.act_shot_light = QAction(tr("Heller Hintergrund (für Berichte/Druck)"), self)
        self.act_shot_light.setCheckable(True)
        # Werkzeugleiste oben (nicht verschiebbar). Die Objektnamen werden für saveState/restoreState benötigt.
        tb = self.addToolBar(tr("Steuerung"))
        tb.setObjectName("tb_steuerung")
        tb.setMovable(False)
        for a in (self.act_run, self.act_online, act_load, act_cfg_load, act_cfg,
                  self.act_vals, self.act_bars, self.act_yauto, self.act_boolplot,
                  act_rul, self.act_demo):
            tb.addAction(a)
        # Breite des sichtbaren Zeitfensters in Sekunden (online: letzte N Sekunden, offline: Breite des Ausschnitts).
        tb.addWidget(QLabel(tr("  Fenster [s]: ")))
        self.win_spin = QSpinBox()
        self.win_spin.setRange(1, 604800)
        self.win_spin.setValue(self.conn["fenster_s"])
        self.win_spin.valueChanged.connect(self.on_window_changed)
        tb.addWidget(self.win_spin)
        # Screenshot-Knopf mit Auswahlmenü (InstantPopup: das Menü öffnet sich beim Klick).
        btn_shot = QToolButton()
        btn_shot.setText(tr("Screenshot"))
        btn_shot.setToolTip(tr("Einzelnes Diagramm als PNG oder SVG speichern"))
        btn_shot.setMenu(self.menu_shot)
        btn_shot.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        tb.addWidget(btn_shot)

        # Zeit-Scrollleiste in einer zweiten Werkzeugleiste am unteren Rand (nur offline aktiv). Wertebereich 0..1000
        # entspricht der Position innerhalb der aufgezeichneten Zeit.
        # Zeit-Scrollbar (offline) unten
        self.scroll = QScrollBar(Qt.Orientation.Horizontal)
        self.scroll.setRange(0, 1000)
        self.scroll.setValue(1000)
        self.scroll.setEnabled(False)
        self.scroll.setMinimumWidth(300)
        self.scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.scroll.valueChanged.connect(self.apply_offline_view)
        tb2 = QToolBar(tr("Zeit"))
        tb2.setObjectName("tb_zeit")
        tb2.setMovable(False)
        tb2.addWidget(self.scroll)
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, tb2)

        # Menü 'Datei': Konfiguration laden/neu laden, Konfigurationsprogramm, CSV laden, Webserver-Adresse, Beenden.
        m_file = self.menuBar().addMenu(tr("Datei"))
        for a in (act_cfg_load, act_cfg_reload, act_cfg):
            m_file.addAction(a)
        m_file.addSeparator()
        m_file.addAction(act_load)
        m_file.addAction(act_load_db)
        m_file.addAction(act_web)
        act_events = QAction(tr("Ereignisprotokoll …"), self)
        act_events.setShortcut("Ctrl+E")
        act_events.setToolTip(tr("Ereignisse der Trigger anzeigen und quittieren"))
        act_events.triggered.connect(self.show_events)
        m_file.addAction(act_events)
        act_note = QAction(tr("Notiz ins Ereignisprotokoll …"), self)
        act_note.setShortcut("Ctrl+M")
        act_note.setToolTip(tr("Eigenen Eintrag mit Zeitstempel ins Ereignisprotokoll schreiben "
                            "(offline: Zeitpunkt von Lineal 1)"))
        act_note.triggered.connect(self.add_note)
        m_file.addAction(act_note)
        m_file.addSeparator()
        self.act_startbild = QAction(tr("Startbild beim Programmstart zeigen"), self)
        self.act_startbild.setCheckable(True)
        self.act_startbild.setChecked(bool(load_settings().get("startbild", True)))
        self.act_startbild.toggled.connect(lambda on: save_settings(startbild=on))
        m_file.addAction(self.act_startbild)
        m_file.addSeparator()
        m_file.addAction(act_quit)
        # Menü 'Sprache': alle Sprachdateien im Ordner 'sprachen' (Umschalten mit Neustart).
        self.menu_lang = self.menuBar().addMenu(tr("Sprache"))
        from s7_i18n import fill_language_menu
        fill_language_menu(self.menu_lang, self, lambda: program_command("logger", self.config_path))
        # Menü 'Ansicht': Anordnung der Seiten (Auswahl: genau eine), Seiten ein-/ausblenden, Werteanzeige, Balken.
        # Menü Ansicht
        m_view = self.menuBar().addMenu(tr("Ansicht"))
        m_arr = m_view.addMenu(tr("Anordnung"))
        # QActionGroup mit exclusive: immer genau ein Modus ist angehakt.
        grp = QActionGroup(self)
        grp.setExclusive(True)
        self.arr_actions = {}
        # Je Anordnungsmodus ein Menüeintrag; bei Auswahl wird die Anzeige mit set_layout neu aufgebaut.
        for key, text in LAYOUTS.items():
            a = QAction(tr(text), self)
            a.setCheckable(True)
            a.triggered.connect(lambda _=False, k=key: self.set_layout(k))
            grp.addAction(a)
            m_arr.addAction(a)
            self.arr_actions[key] = a
        # Anordnung der Diagramme INNERHALB einer Seite: untereinander, nebeneinander oder als Raster (Spaltenzahl wählbar).
        m_page = m_view.addMenu(tr("Diagramme auf der Seite"))
        grp2 = QActionGroup(self)
        grp2.setExclusive(True)
        self.page_actions = {}
        for key, text in PAGE_LAYOUTS.items():
            a = QAction(tr(text), self)
            a.setCheckable(True)
            a.triggered.connect(lambda _=False, k=key: self.set_page_mode(k))
            grp2.addAction(a)
            m_page.addAction(a)
            self.page_actions[key] = a
        m_cols = m_view.addMenu(tr("Raster-Spalten"))
        grp3 = QActionGroup(self)
        grp3.setExclusive(True)
        self.col_actions = {}
        for n in range(0, 7):
            a = QAction(tr("Automatisch") if n == 0 else str(n), self)
            a.setCheckable(True)
            a.triggered.connect(lambda _=False, c=n: self.set_columns(c))
            grp3.addAction(a)
            m_cols.addAction(a)
            self.col_actions[n] = a
        self.menu_charts = m_view.addMenu(tr("Seiten / Diagramme"))
        # Menü 'Screenshot' in der Menüleiste (zusätzlich zum Knopf in der Werkzeugleiste).
        self.menuBar().addMenu(self.menu_shot)
        # Menü 'Analyse': PID-Regler-Optimierung je Diagramm, bei dem sie in der Konfiguration eingeschaltet ist.
        self.menu_pid = self.menuBar().addMenu(tr("Analyse"))
        m_view.addAction(self.act_vals)
        m_view.addAction(self.act_bars)
        # Logo rechts oben in der Menüleiste (Eckenwidget), 28 Pixel hoch.
        self.logo_lbl = LogoLabel()                # Strg + Umschalt + Doppelklick: verstecktes Info-Fenster
        self.logo_lbl.setPixmap(logo_pixmap(self.conn.get("logo", ""), 28))
        self.logo_lbl.setContentsMargins(8, 0, 8, 0)
        self.menuBar().setCornerWidget(self.logo_lbl, Qt.Corner.TopRightCorner)  # Logo rechts oben
        # Statusleiste: links die Meldungen, rechts die Webserver-Adresse und je Steuerung eine Status-LED.
        self.lbl_web = QLabel("")
        self.statusBar().addPermanentWidget(self.lbl_web)
        # Zähler der offenen (unquittierten) Ereignisse; Klick öffnet den Ereignis-Viewer zum Quittieren.
        self.btn_events = QToolButton()
        self.btn_events.setAutoRaise(True)
        self.btn_events.clicked.connect(self.show_events)
        self.statusBar().addPermanentWidget(self.btn_events)
        self.led_box = QWidget()
        self.led_lay = QHBoxLayout(self.led_box)
        self.led_lay.setContentsMargins(0, 0, 0, 0)
        self.led_lay.setSpacing(2)
        self.statusBar().addPermanentWidget(self.led_box)
        self.statusBar().showMessage(tr("Bereit"))

    def page_groups(self):
        """Seiten (Docks/Tabs) bestimmen: [(Seitenname, [Diagramm-Indizes])].

        Diagramme mit gleichem Seitennamen (Konfiguration) teilen sich eine Seite. Ohne Seitenangaben
        liegen alle Diagramme auf einer Seite - im Modus "Tabs" je Diagramm ein Tab."""
        # Ohne Seitenangaben in der Konfiguration: alle Diagramme auf einer Seite; im Modus 'Tabs' dagegen je Diagramm ein Tab.
        if not any(c.page for c in self.charts):
            if self.layout_mode == "tabs":
                return [(c.name, [ci]) for ci, c in enumerate(self.charts)]
            return [(tr("Diagramme"), list(range(len(self.charts))))]
        # Mit Seitenangaben: Diagramme mit gleichem Seitennamen gruppieren; Diagramme ohne Seitenname bilden eine eigene Seite.
        groups = {}
        for ci, c in enumerate(self.charts):
            groups.setdefault(c.page or c.name, []).append(ci)
        return list(groups.items())

    def _rebuild(self):
        """Seiten, Diagramme, Kurven und Werte-Tabelle passend zu Konfiguration/Variablen aufbauen."""
        # Aktuelle Dock-Anordnung merken (Größen, Positionen), bevor die Docks abgebaut werden.
        if self.page_docks and self._sig is not None:
            self._states[self._sig] = self.saveState()
        # Alte Seiten und Diagramme entfernen und die Zuordnungstabellen zurücksetzen.
        for d in self.page_docks:
            self.removeDockWidget(d)
            d.deleteLater()
        self.page_docks, self.panels = [], []
        self.dock_of_chart, self.panel_of_var = {}, {}
        self.curves = [None] * len(self.vars)
        self.master = None
        self.ruler_t = [None, None]
        show_bars = self.act_bars.isChecked()

        # Pro Diagramm ein ChartPanel (Kurven, Legende, Balken, Lineale) anlegen.
        for ci, ch in enumerate(self.charts):
            # Variablen dieses Diagramms: alle, deren Diagramm-Index passt (Reihenfolge wie in der Konfiguration).
            idx = [i for i, v in enumerate(self.vars) if v.chart == ci]
            panel = ChartPanel(ci, ch, idx, self.vars, show_bars, self.act_boolplot.isChecked())
            panel.apply_scaling(self.act_yauto.isChecked())
            self.panels.append(panel)
            # Kurven und Panel je Variable eintragen; vom Benutzer ausgeblendete Kurven (Namen in self.hidden) bleiben ausgeblendet.
            for vi, c in panel.curves.items():
                self.curves[vi] = c
                self.panel_of_var[vi] = panel
                if self.vars[vi].name in self.hidden:
                    panel.set_curve_visible(vi, False)
            # Legendeneinträge zunächst nur mit Name und Farbe (Werte folgen mit der ersten Messung).
            panel.set_legend_values({})
            # Wird eine Kurve in der Legende ein-/ausgeblendet, muss die Wertetabelle (Häkchen) folgen.
            panel.visibility_changed.connect(self.on_curve_visibility)
            # Das erste Diagramm ist das Leitdiagramm: seine Zeitachse steuert alle anderen (setXLink) und löst die Anpassung der Scrollleiste aus.
            if self.master is None:
                self.master = panel
                panel.plot.getViewBox().sigXRangeChanged.connect(self.on_xrange)
            else:
                panel.plot.setXLink(self.master.plot)
            # Lineale aller Diagramme melden Verschiebungen an das Hauptfenster, das sie synchronisiert.
            for k, ln in enumerate(panel.rulers):
                ln.sigPositionChanged.connect(lambda l, k=k: self.on_ruler(k, l.value()))

        # Seiten bilden: je Seite ein Dock mit einer ChartPage (scrollbar, Mindesthöhe); die Diagramme einer Seite stehen untereinander, nebeneinander oder im Raster (page_mode).
        groups = self.page_groups()
        columns = int(self.conn.get("raster_spalten", 0))
        for k, (pname, members) in enumerate(groups):
            page = ChartPage([self.panels[ci] for ci in members], self.page_mode, columns)
            dock = QDockWidget(pname, self)
            dock.setObjectName(f"page{k}")
            dock.setWidget(page)
            self.page_docks.append(dock)
            for ci in members:
                self.dock_of_chart[ci] = dock

        # Signatur der Seitenstruktur: Anordnung + Seitennamen. Gleiche Signatur = gespeicherte Dock-Anordnung wiederverwendbar.
        self._sig = (self.layout_mode,) + tuple(n for n, _ in groups)
        # Menüs aktualisieren: Seiten ein-/ausblenden und Screenshot-Einträge je Diagramm.
        self.menu_charts.clear()
        for d in self.page_docks:
            self.menu_charts.addAction(d.toggleViewAction())
        self.menu_shot.clear()
        for ci, ch in enumerate(self.charts):
            act = self.menu_shot.addAction(f"{ch.name} …")
            act.triggered.connect(lambda _=False, c=ci: self.save_screenshot(c))
        self.menu_shot.addSeparator()
        self.menu_shot.addAction(self.act_shot_light)
        # PID-Optimierung: Menü 'Analyse' und Rechtsklickmenü der betroffenen Diagramme.
        self.menu_pid.clear()
        for ci, ch in enumerate(self.charts):
            if not ch.pid:
                continue
            act = self.menu_pid.addAction(tr("PID-Optimierung: {0} …").format(ch.name))
            act.triggered.connect(lambda _=False, c=ci: self.open_pid(c))
            vb_menu = getattr(self.panels[ci].plot.getViewBox(), "menu", None)
            if vb_menu is not None:
                vb_menu.addSeparator()
                a2 = vb_menu.addAction(tr("PID-Regler optimieren …"))
                a2.triggered.connect(lambda _=False, c=ci: self.open_pid(c))
        if self.menu_pid.isEmpty():
            a = self.menu_pid.addAction(tr("PID-Optimierung (im Konfigurationsprogramm beim Diagramm einschalten)"))
            a.setEnabled(False)
        # Docks anordnen; danach die früher gespeicherte Anordnung (vom Benutzer per Drag & Drop angepasst) wiederherstellen.
        self._arrange_docks(self.layout_mode)
        if self._sig in self._states:  # frühere, per Drag & Drop angepasste Anordnung
            self.restoreState(self._states[self._sig])
        self._apply_mode()

        # Wertetabelle neu füllen: eine Zeile je Variable mit eingeschalteter Werteanzeige. Spalten: Name (mit Kontrollkästchen
        # zum Ein-/Ausblenden der Kurve), Wert/Lineal 1, Lineal 2, Differenz. Die Variablen-Nummer steht in UserRole.
        # Werte-Tabelle
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.row_of = {}
        for i, v in enumerate(self.vars):
            if not v.show_value:
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)
            name = QTableWidgetItem(v.name)
            name.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            # Kontrollkästchen: angehakt = Kurve sichtbar (ausgeblendete Kurven bleiben abgehakt).
            name.setCheckState(Qt.CheckState.Unchecked if v.name in self.hidden
                               else Qt.CheckState.Checked)
            name.setForeground(QBrush(QColor(v.color)))
            name.setData(Qt.ItemDataRole.UserRole, i)
            # Tooltip: Formel (berechnete Variable) oder SPS-Adresse.
            name.setToolTip(v.formula if v.formula else v.address())
            self.table.setItem(r, 0, name)
            for col in (1, 2, 3):
                it = QTableWidgetItem("—")
                it.setFlags(Qt.ItemFlag.ItemIsEnabled)
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, col, it)
            self.row_of[i] = r
        self.table.blockSignals(False)

    # Haken in den Ansichtsmenüs passend zum Zustand setzen (Seitenanordnung, Diagrammanordnung, Rasterspalten).
    def _sync_menus(self):
        self.arr_actions[self.layout_mode].setChecked(True)
        self.page_actions[self.page_mode].setChecked(True)
        self.col_actions.get(int(self.conn.get("raster_spalten", 0)), self.col_actions[0]).setChecked(True)

    # Eine Status-LED je Steuerung (Name aus der Konfiguration) in der Statusleiste anlegen.
    def _rebuild_leds(self):
        for led in self.leds:
            self.led_lay.removeWidget(led)
            led.deleteLater()
        self.leds = []
        plcs = self.rec.plcs if self.rec is not None and self.source == "rec" else self.plcs
        for p in plcs:
            led = PlcLed(p.name)
            led.set_state("off", tr("{0}: nicht verbunden ({1})").format(p.name, p.ip))
            self.led_lay.addWidget(led)
            self.leds.append(led)
        # Zusätzliche LED für die Datenbank (wenn in der Konfiguration eine gewählt ist).
        conn = self.rec.conn if self.rec is not None and self.source == "rec" else self.conn
        if conn.get("db_typ"):
            led = PlcLed(tr("Datenbank"))
            led.set_state("off", tr("Datenbank: nicht verbunden"))
            self.led_lay.addWidget(led)
            self.leds.append(led)

    # Meldungen und Verbindungszustände vom Recorder abholen (wird vom 100-ms-Takt aufgerufen; billig).
    def poll_recorder(self):
        rec = self.rec
        if rec is None:
            return
        for m in rec.drain_messages():
            self.statusBar().showMessage(m, 20000)
        for led, (name, state, text, ms) in zip(self.leds, rec.status_list()):
            led.set_state(state, f"{name}: {text}" + (tr("\nZykluszeit {0:.0f} ms").format(ms) if ms else ""))
        if rec.events.version != self._ev_seen:          # neues Ereignis: Zähler sofort aktualisieren
            self.update_event_button()

    # ---------------------------------------------------------------------------------------
    # PID-Regler-Optimierung
    # ---------------------------------------------------------------------------------------
    # Alle Messdaten (Zeiten, Werte je Variable): während der Aufzeichnung aus dem Recorder, sonst die angezeigten.
    def _pid_source(self):
        if self.online and self.rec is not None and self.source == "rec":
            return self.rec.snapshot()
        return self.t, self.y

    def _pid_data(self, t0, t1, names):
        t, y = self._pid_source()
        i0 = int(np.searchsorted(t, t0, side="left"))
        i1 = int(np.searchsorted(t, t1, side="right"))
        index = {v.name: i for i, v in enumerate(self.vars)}
        return t[i0:i1], {n: y[index[n]][i0:i1] for n in names if n in index}

    # Dialog der PID-Optimierung für Diagramm ci öffnen; Zeitbereiche: sichtbar, zwischen den Linealen, alle Daten.
    def open_pid(self, ci):
        from s7_pid_dialog import PidTuneDialog
        t, _y = self._pid_source()
        if len(t) < 20:
            QMessageBox.information(self, tr("PID-Optimierung"), tr("Es sind noch keine (oder zu wenige) Messdaten "
                                    "vorhanden. Bitte aufzeichnen oder eine CSV-Datei laden."))
            return
        first, last = float(t[0]), float(t[-1])
        ranges = []
        panel = self.panels[ci] if ci < len(self.panels) else None
        r1, r2 = self.ruler_t
        if not self.online and r1 is not None and r2 is not None and abs(r2 - r1) > 0:
            ranges.append((tr("Zwischen Lineal 1 und 2"), min(r1, r2), max(r1, r2)))
        if panel is not None:
            x0, x1 = panel.axis_vbs[0].viewRange()[0]
            x0, x1 = max(x0, first), min(x1, last)
            if x1 > x0:
                ranges.append((tr("Sichtbarer Bereich"), x0, x1))
        ranges.append((tr("Alle Daten"), first, last))
        dlg = PidTuneDialog(self, self.charts[ci], [v.name for v in self.vars], self._pid_data, ranges)
        dlg.show()
        self._pid_dialogs = [d for d in getattr(self, "_pid_dialogs", []) if d.isVisible()] + [dlg]

    # ---------------------------------------------------------------------------------------
    # Ereignisse (Trigger)
    # ---------------------------------------------------------------------------------------
    # Aktuelles Ereignisprotokoll: das der Aufzeichnung, sonst das der geladenen Konfiguration.
    def event_log(self):
        if self.rec is not None and self.source == "rec":
            return self.rec.events
        path = event_log_path(self.conn)
        if self._offline_events is None or self._offline_events.path != path:
            self._offline_events = EventLog(path)
        return self._offline_events

    # Knopf in der Statusleiste: Anzahl offener Ereignisse, rot hinterlegt, solange etwas zu quittieren ist.
    def update_event_button(self):
        log = self.event_log()
        try:
            if log.changed_on_disk():                     # z. B. von einem anderen Programm quittiert
                log.reload()
        except Exception:
            pass
        n = log.open_count()
        self._ev_seen = log.version
        if self.event_viewer is not None and self.event_viewer.log is not log:
            self.event_viewer.set_log(log)
        if getattr(self, "_ev_shown", None) == (n, log.path):
            return                                       # unverändert: Knopf nicht neu zeichnen
        self._ev_shown = (n, log.path)
        if n:
            self.btn_events.setText(tr("🔔 {0} offen").format(n))
            self.btn_events.setStyleSheet("QToolButton{background:#c62828;color:white;font-weight:bold;"
                                          "border-radius:3px;padding:0 6px}")
        else:
            self.btn_events.setText("🔔 0")
            self.btn_events.setStyleSheet("")
        self.btn_events.setToolTip(tr("{0} offene (nicht quittierte) Ereignisse\n{1}\nKlicken: Ereignisprotokoll öffnen und quittieren").format(n, log.path))

    # Notiz von Hand ins Ereignisprotokoll (offline mit dem Zeitpunkt von Lineal 1).
    def add_note(self):
        from s7_event_viewer import add_note
        when = self.ruler_t[0] if not self.online and self.ruler_t[0] is not None else None
        if add_note(self, self.event_log(), when):
            self.update_event_button()
            if self.event_viewer is not None:
                self.event_viewer.fill(force=True)
            self.statusBar().showMessage(tr("Notiz gespeichert."), 5000)

    # Ereignis-Viewer öffnen (nicht modal; bleibt neben dem Hauptfenster offen).
    def show_events(self):
        if self.event_viewer is None:
            from s7_event_viewer import EventViewer
            self.event_viewer = EventViewer(self.event_log(), self, on_change=self.update_event_button)
        else:
            self.update_event_button()
            self.event_viewer.fill(force=True)
        self.event_viewer.show()
        self.event_viewer.raise_()
        self.event_viewer.activateWindow()

    # Menü 'Diagramme auf der Seite': Anordnung ändern -> Seiten neu aufbauen und Kurven wieder füllen.
    def set_page_mode(self, mode):
        if mode == self.page_mode:
            return
        self.page_mode = mode
        self._rebuild()
        self._reload_curves()

    # Menü 'Raster-Spalten' (0 = automatisch); wirkt nur im Raster, gilt bis zum nächsten Laden der Konfiguration.
    def set_columns(self, n):
        self.conn["raster_spalten"] = n
        if self.page_mode == "raster":
            self._rebuild()
            self._reload_curves()

    # Nach einem Neuaufbau der Anzeige die Kurven mit den vorhandenen Daten füllen.
    def _reload_curves(self):
        if self.online:
            self.dirty = True
        else:
            self.enter_offline()

    # ---------------------------------------------------------------------------------------
    # Konfiguration laden
    # ---------------------------------------------------------------------------------------
    # Dialog 'Konfiguration laden': beliebiger Dateiname (INI/TXT/…); die Wahl wird für den nächsten Start gemerkt.
    def load_config_file(self):
        start = os.path.dirname(self.config_path) or BASE_DIR
        path, _ = QFileDialog.getOpenFileName(self, tr("Konfiguration laden"), start,
                                              tr("Konfiguration (*.ini *.txt *.cfg);;Alle Dateien (*)"))
        if path:
            self.set_config(path)

    # Konfigurationsdatei laden: beendet eine laufende Aufzeichnung (ohne Archivierung) und baut die Anzeige neu auf.
    def set_config(self, path):
        try:
            conn, charts, variables = load_config(path)
            plcs = load_plcs(path)
        except Exception as e:
            QMessageBox.warning(self, tr("Konfiguration"), tr("Die Konfiguration konnte nicht gelesen werden:\n{0}\n\n{1}").format(path, e))
            return False
        if self.rec is not None and self.rec.running:
            self.act_run.setChecked(False)          # stoppt die Aufzeichnung (on_run_toggled)
        self.config_path = path
        remember_config_path(path)
        self.conn, self.charts, self.vars, self.plcs = conn, charts, variables, plcs
        # Die bisherigen Daten gehören zur alten Konfiguration: verwerfen.
        self.rec, self.source = None, "none"
        self.t, self.y = np.empty(0), np.empty((len(variables), 0))
        self.hidden = set()
        self._states = {}
        self.layout_mode = conn["anordnung"]
        self.page_mode = self._page_mode_from(conn)
        self.act_bars.setChecked(bool(conn["balken"]))
        self.win_spin.setValue(conn["fenster_s"])
        self.setWindowIcon(app_icon(conn.get("icon", ""), conn.get("logo", "")))
        self.logo_lbl.setPixmap(logo_pixmap(conn.get("logo", ""), 28))
        self.setWindowTitle(self._title())
        self._sync_menus()
        self._rebuild()
        self._rebuild_leds()
        self._apply_web()
        self.update_event_button()
        self.statusBar().showMessage(tr("Konfiguration geladen: {0}").format(path), 10000)
        return True

    # ---------------------------------------------------------------------------------------
    # Webserver (optional, Einstellung 'web_aktiv')
    # ---------------------------------------------------------------------------------------
    # Webserver passend zur Konfiguration starten, neu starten (geänderte Einstellungen) oder beenden.
    def _apply_web(self):
        want = bool(self.conn.get("web_aktiv"))
        key = (self.conn.get("web_host", "0.0.0.0"), int(self.conn.get("web_port", 8080)),
               self.conn.get("web_token", ""), int(self.conn.get("web_intervall_ms", 1000)))
        if self.web is not None and (not want or self._web_key != key):
            self.web.stop()
            self.web = None
        if want and self.web is None:
            try:
                from s7_web import WebServer
                self.web = WebServer(lambda: self.rec, *key)
                self.web.start()
                self._web_key = key
            except Exception as e:                  # Port belegt, Flask fehlt ...
                self.web = None
                self.statusBar().showMessage(tr("Webserver nicht gestartet: {0}").format(e), 20000)
        self.lbl_web.setText(tr("Web: {0}   ").format(self.web.url()) if self.web else "")

    # Menü 'Webserver-Adresse': zeigt die Adresse für Tablet/Smartphone und kopiert sie in die Zwischenablage.
    def show_web_url(self):
        if self.web is None:
            QMessageBox.information(self, tr("Webserver"), tr("Der Webserver ist nicht aktiviert.\n"
                                    "Aktivierung: Konfigurationsprogramm → Webserver."))
            return
        url = self.web.url() + (tr("?token={0}").format(self._web_key[2]) if self._web_key[2] else "")
        QGuiApplication.clipboard().setText(url)
        QMessageBox.information(self, tr("Webserver"), tr("Adresse für Tablet/Smartphone im selben Netz:\n\n{0}\n\n(in die Zwischenablage kopiert)").format(url))

    def set_layout(self, mode):
        """Anordnung wechseln: baut die Seiten neu auf (Gruppierung/Ausrichtung hängen vom Modus ab)."""
        # Gleicher Modus gewählt: nur die Standardanordnung der Docks herstellen (setzt Drag & Drop-Änderungen zurück).
        if mode == self.layout_mode:
            self._arrange_docks(mode)   # gleiche Anordnung: Standardanordnung wiederherstellen
            return
        # Neuer Modus: Seiten neu aufbauen, weil Gruppierung (Tabs) und Ausrichtung (nebeneinander) vom Modus abhängen;
        # danach die Kurven mit den vorhandenen Daten füllen.
        self.layout_mode = mode
        self._rebuild()
        if self.online:
            self.dirty = True
        else:
            self.enter_offline()

    def _arrange_docks(self, mode):
        """Seiten-Docks untereinander, nebeneinander oder als Tabs anordnen."""
        self.layout_mode = mode
        self.arr_actions[mode].setChecked(True)
        docks = self.page_docks
        if not docks:
            return
        # Zuerst alle Docks aus dem Fenster nehmen, damit sie frisch angeordnet werden können.
        for d in docks:
            self.removeDockWidget(d)
        first = docks[0]
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, first)
        first.show()
        # Erstes Dock oben anlegen; die weiteren werden daran angedockt.
        prev = first
        # Ausrichtung beim Teilen: 'untereinander' = vertikal, sonst nebeneinander = horizontal.
        orient = (Qt.Orientation.Vertical if mode == "untereinander"
                  else Qt.Orientation.Horizontal)
        # Tabs: alle Docks mit dem ersten zusammenlegen (tabifyDockWidget); sonst jedes Dock an das vorherige anteilen (splitDockWidget).
        for d in docks[1:]:
            if mode == "tabs":
                self.tabifyDockWidget(first, d)
            else:
                self.splitDockWidget(prev, d, orient)
                prev = d
            d.show()
        # Im Tab-Modus das erste Tab in den Vordergrund holen.
        first.raise_()
        # Gleichmäßig verteilen: Platz je Dock = 1000 / Anzahl (relative Größen).
        if mode != "tabs":
            self.resizeDocks(docks, [1000 // len(docks)] * len(docks), orient)

    def _apply_mode(self):
        """Online/Offline: Mausbedienung, Lineale und Tabellenspalten umschalten."""
        for p in self.panels:
            # Mausbedienung der Zeitachse nur offline (zum Verschieben/Zoomen); y bleibt unveränderlich (Skalierung über die Konfiguration).
            p.plot.getViewBox().setMouseEnabled(x=not self.online, y=False)
            # Lineale sind nur offline sichtbar.
            for ln in p.rulers:
                ln.setVisible(not self.online)
        # Tabellenüberschriften: online 'Aktuell'; offline 'Lineal 1', 'Lineal 2' und die Differenz. Die Spalten 2 und 3 gibt es nur offline.
        self.table.setHorizontalHeaderLabels(
            [tr("Variable"), tr("Aktuell") if self.online else tr("Lineal 1"), tr("Lineal 2"), "Δ (L2 − L1)"])
        self.table.setColumnHidden(2, self.online)
        self.table.setColumnHidden(3, self.online)

    # Kontrollkästchen vor einem Namen in der Wertetabelle: Kurve ein-/ausblenden (das Diagramm macht die Arbeit).
    def on_item_changed(self, item):
        if item.column() == 0:
            i = item.data(Qt.ItemDataRole.UserRole)
            panel = self.panel_of_var.get(i)
            if panel is not None:
                panel.set_curve_visible(i, item.checkState() == Qt.CheckState.Checked)

    def on_curve_visibility(self, vi, flag):
        """Kurve wurde (z. B. per Rechtsklick in der Legende) ein-/ausgeblendet: Tabelle nachziehen."""
        # Zustand merken (self.hidden), damit er einen Neuaufbau der Anzeige überlebt, und das Kontrollkästchen ohne Rückkopplung anpassen.
        self.dirty = True            # unsichtbare Kurven werden online nicht aktualisiert: jetzt nachholen
        if flag:
            self.hidden.discard(self.vars[vi].name)
        else:
            self.hidden.add(self.vars[vi].name)
        r = self.row_of.get(vi)
        if r is not None:
            self.table.blockSignals(True)
            self.table.item(r, 0).setCheckState(
                Qt.CheckState.Checked if flag else Qt.CheckState.Unchecked)
            self.table.blockSignals(False)

    # CSV-Ordner als absoluter Pfad (relativ = ab dem Basisordner des Programms).
    def csv_dir(self):
        d = self.conn["csv_ordner"]
        return d if os.path.isabs(d) else os.path.join(BASE_DIR, d)

    # Start-Taste angehakt -> start(), abgehakt -> stop().
    def on_run_toggled(self, on):
        self.start() if on else self.stop()

    # Start-Taste abhaken, ohne on_run_toggled auszulösen.
    def _uncheck_run(self):
        self.act_run.blockSignals(True)
        self.act_run.setChecked(False)
        self.act_run.blockSignals(False)

    # Aufzeichnung starten: Konfiguration neu laden (Änderungen wirken so sofort), Recorder anlegen, Anzeige neu aufbauen,
    # dann starten (CSV-Datei öffnen, je Steuerung ein Lese-Thread).
    def start(self):
        try:
            conn, charts, variables = load_config(self.config_path)
            plcs = load_plcs(self.config_path)
        except Exception as e:
            QMessageBox.warning(self, tr("Konfiguration"), tr("Die Konfiguration konnte nicht gelesen werden:\n{0}\n\n{1}").format(self.config_path, e))
            self._uncheck_run()
            return
        demo = self.act_demo.isChecked()
        # Demo ohne konfigurierte Variablen: Beispielkonfiguration verwenden.
        if demo and not variables:
            charts, variables = demo_config()
        # Ohne Variablen gibt es nichts aufzuzeichnen: Hinweis, Start-Taste wieder abhaken (ohne erneutes Auslösen).
        if not variables:
            QMessageBox.warning(self, tr("Keine Variablen"),
                                tr("Bitte zuerst im Konfigurationsprogramm Variablen anlegen."))
            self._uncheck_run()
            return
        # Konfiguration übernehmen; der Recorder bekommt eine eigene Sicht darauf (Formeln werden dort kompiliert).
        self.conn, self.charts, self.vars, self.plcs = conn, charts, variables, plcs
        rec = Recorder(conn, plcs, charts, variables, demo=demo, config_path=self.config_path)
        if rec.formula_errors:
            QMessageBox.warning(self, tr("Fehler in Formeln"),
                                "\n".join(rec.formula_errors) + tr("\n\nDiese berechneten Variablen bleiben ohne Wert."))
        # Neuer Datenbestand; Diagramme, LEDs und Webserver passend aufbauen.
        self.rec, self.source = rec, "rec"
        self.t, self.y = np.empty(0), np.empty((len(variables), 0))
        self._rebuild()
        self._rebuild_leds()
        self._apply_web()
        self.update_event_button()
        try:
            rec.start()
        except OSError as e:                         # CSV-Ordner nicht beschreibbar o. Ä.
            QMessageBox.critical(self, tr("CSV-Datei"), tr("Die CSV-Datei konnte nicht angelegt werden:\n{0}").format(e))
            self.rec, self.source = None, "none"
            self._uncheck_run()
            return
        # Demo-Schalter während der Aufzeichnung sperren (Wechsel nur vor dem Start); zurück auf Online schalten.
        self.act_demo.setEnabled(False)
        self.act_run.setText(tr("■ Stop"))
        self.act_online.setChecked(True)

    # Aufzeichnung beenden: Threads stoppen, CSV-Datei schließen (bleibt ungepackt im CSV-Ordner; archiviert wird beim
    # Beenden des Programms, Einstellung 'archiv_beenden'). Die Daten bleiben für den Offline-Modus erhalten.
    def stop(self):
        if self.rec is not None and self.rec.running:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self.rec.stop()
            finally:
                QApplication.restoreOverrideCursor()
            self.poll_recorder()
        self.act_run.setText(tr("▶ Start"))
        self.act_demo.setEnabled(True)

    # ---------------------------------------------------------------------------------------
    # Online- und Offline-Anzeige
    # ---------------------------------------------------------------------------------------
    # ---------------- Online / Offline ----------------
    # Zwischen Online (fortlaufend) und Offline (Rückblick mit Scrollleiste und Linealen) umschalten.
    def set_online(self, flag):
        self.online = flag
        self.act_online.setText(tr("Online") if flag else tr("Offline"))
        self.scroll.setEnabled(not flag)
        self._apply_mode()
        if flag:
            self.dirty = True
        else:
            self.enter_offline()

    # Daten einer Kurve setzen. BOOL-Kurven werden als Treppenlinie gezeichnet; 'finite' trennt die Linie bei fehlenden Werten (NaN).
    def set_curve(self, i, tt, yy):
        c = self.curves[i]
        if c is None:
            return
        if self.vars[i].dtype == "BOOL":
            tt, yy = to_step(tt, yy)
        c.setData(tt, yy, connect="finite")

    # Wird alle 100 ms vom Timer aufgerufen: Meldungen/LEDs aktualisieren; online und bei neuen Daten das Zeitfenster
    # (letzte N Sekunden) vom Recorder holen, Kurven neu setzen, Zeitachse nachführen und Wertetabelle/Legende/Balken
    # aktualisieren. Alles Aufwendige (Lesen, Rechnen, CSV) läuft in den Threads des Recorders.
    def refresh(self):
        """Online-Anzeige: letzte N Sekunden, läuft mit den Daten mit."""
        self.poll_recorder()
        rec = self.rec
        if not (self.online and self.source == "rec" and rec is not None and self.master):
            return
        if not (rec.dirty or self.dirty):
            return
        rec.dirty = self.dirty = False
        w = self.win_spin.value()
        tt, yy = rec.window(w)
        if len(tt) == 0:
            return
        self.t, self.y = tt, yy
        t_end = float(tt[-1])
        for i in range(len(self.curves)):
            c = self.curves[i]
            if c is not None and c.isVisible():      # unsichtbare Kurven (z. B. BOOL nur in der Legende) nicht neu setzen
                self.set_curve(i, tt, yy[i])
        # Die Zeitachse des Leitdiagramms setzen; die anderen Diagramme folgen über die X-Kopplung.
        self._block = True
        self.master.plot.setXRange(t_end - w, t_end, padding=0)  # andere Diagramme sind X-verknüpft
        self._block = False
        # BOOL-Streifen in den Legenden für den sichtbaren Zeitbereich nachführen.
        self.update_bool_strips(t_end - w, t_end)
        # Wertetabelle, Balken und Legende mit dem letzten Messwert aktualisieren.
        self.update_values(len(tt) - 1)

    def enter_offline(self):
        """Momentaufnahme aller Daten laden; danach frei scrollbar."""
        # Aus einer Aufzeichnung: Kopie ALLER Daten im Speicher des Recorders (geladene CSV-Daten liegen schon in self.t/self.y).
        if self.source == "rec" and self.rec is not None:
            self.t, self.y = self.rec.snapshot()
        # Ohne Daten (oder ohne Diagramme) gibt es nichts zu zeigen.
        if len(self.t) == 0 or not self.master:
            return
        # Momentaufnahme: ALLE Daten in die Kurven laden. pyqtgraph schneidet beim Zeichnen auf den sichtbaren Bereich
        # zu und vergröbert bei Bedarf ('peak'), daher bleibt das Scrollen auch bei vielen Punkten flüssig.
        tt = self.t
        for i in range(len(self.curves)):
            self.set_curve(i, tt, self.y[i])
        # Zeitgrenzen der Momentaufnahme: Grundlage der Scrollleisten-Berechnung.
        self.snap_t0, self.snap_t1 = float(tt[0]), float(tt[-1])
        self._block = True
        # Scrollleiste ganz rechts = neueste Daten (ohne dabei apply_offline_view auszulösen).
        self.scroll.setValue(1000)  # ans Ende (neueste Daten)
        self._block = False
        self.apply_offline_view()
        # Beim ersten Wechsel in den Offline-Modus die Lineale platzieren; später bleiben sie, wo der Benutzer sie hingestellt hat.
        if self.ruler_t[0] is None:
            self.reset_rulers()
        else:
            self.update_offline_values()

    # Sichtbaren Ausschnitt aus Scrollleiste und Fensterbreite berechnen und auf die Zeitachse anwenden.
    def apply_offline_view(self, *_):
        if self.online or self._block or len(self.t) == 0 or not self.master:
            return
        w = self.win_spin.value()
        # Scrollbereich = Gesamtdauer - Fensterbreite; die Scrollleistenposition (0..1000) wird darauf abgebildet.
        span = max((self.snap_t1 - self.snap_t0) - w, 0.0)
        x0 = self.snap_t0 + span * self.scroll.value() / 1000.0
        self.view_x = (x0, x0 + w)
        # _block verhindert, dass setXRange über on_xrange wieder Scrollleiste und Fensterbreite verändert (Rückkopplung).
        self._block = True
        self.master.plot.setXRange(x0, x0 + w, padding=0)
        self._block = False
        self.update_bool_strips(x0, x0 + w)

    def update_bool_strips(self, x0, x1):
        """Zeitverlauf der BOOL-Streifen in den Legenden für den sichtbaren Bereich x0..x1 setzen."""
        if len(self.t) == 0:
            return
        # Ab einem Messpunkt vor dem Bereich beginnen, damit der Zustand am linken Rand bekannt ist.
        i0 = max(int(np.searchsorted(self.t, x0, side="left")) - 1, 0)      # einen Wert davor: Zustand am Anfang
        i1 = int(np.searchsorted(self.t, x1, side="right"))
        tt = self.t[i0:i1]
        for vi, panel in self.panel_of_var.items():
            if self.vars[vi].dtype == "BOOL":
                panel.set_bool_history(vi, tt, self.y[vi][i0:i1], x0, x1)

    # Fensterbreite geändert: online beim nächsten Takt neu zeichnen, offline den Ausschnitt neu berechnen.
    def on_window_changed(self, *_):
        if self._block:
            return
        if self.online:
            self.dirty = True
        else:
            self.apply_offline_view()

    # Der Benutzer hat die Zeitachse mit der Maus verschoben/gezoomt: Scrollleiste und Fensterbreite nachführen.
    def on_xrange(self, _vb, rng):
        """Maus-Pan/Zoom im Offline-Modus -> Scrollbar und Fensterbreite nachführen."""
        # Nicht reagieren, wenn das Programm selbst den Bereich gesetzt hat (_block), online (nur offline bedienbar) oder ohne Daten.
        if self._block or self.online or self.snap_t1 <= self.snap_t0:
            return
        x0, x1 = rng
        self.view_x = (x0, x1)
        # Position der Scrollleiste aus dem neuen Ausschnitt: Anteil von x0 am verfügbaren Scrollbereich.
        span = (self.snap_t1 - self.snap_t0) - (x1 - x0)
        pos = 1000 if span <= 0 else int(round(1000 * (x0 - self.snap_t0) / span))
        self._block = True
        self.scroll.setValue(max(0, min(1000, pos)))
        self.win_spin.setValue(max(1, int(round(x1 - x0))))
        self._block = False
        self.update_bool_strips(x0, x1)

    # ---------------------------------------------------------------------------------------
    # Lineale (nur offline)
    # ---------------------------------------------------------------------------------------
    # ---------------- Lineale ----------------
    def reset_rulers(self):
        """Lineale auf 1/3 und 2/3 des sichtbaren Zeitbereichs setzen."""
        if not self.master or self.online:
            return
        # Der sichtbare Zeitbereich (view_x) wird in Drittel geteilt: L1 bei 1/3, L2 bei 2/3.
        x0, x1 = self.view_x
        self.set_rulers(0, x0 + (x1 - x0) / 3)
        self.set_rulers(1, x0 + 2 * (x1 - x0) / 3)
        self.update_offline_values()

    # Lineal k (0 = L1, 1 = L2) in allen Diagrammen auf die Zeit pos setzen. _rblock verhindert Endlosschleifen, weil das Setzen
    # selbst wieder das Signal 'Lineal verschoben' auslöst.
    def set_rulers(self, k, pos):
        self._rblock = True
        for p in self.panels:
            p.rulers[k].setValue(pos)
        self._rblock = False
        self.ruler_t[k] = pos

    # Der Benutzer hat ein Lineal in einem Diagramm verschoben: in allen anderen nachziehen und die Werte aktualisieren.
    def on_ruler(self, k, pos):
        if self._rblock:
            return
        self.set_rulers(k, pos)
        self.update_offline_values()

    def idx_at(self, ts):
        """Index des zeitlich nächsten Messwerts."""
        # Binäre Suche in den sortierten Zeiten; dann den näheren der beiden Nachbarn nehmen (keine Interpolation).
        n = len(self.t)
        i = int(np.searchsorted(self.t, ts, side="left"))
        if i >= n:
            return n - 1
        if i > 0 and abs(self.t[i - 1] - ts) <= abs(self.t[i] - ts):
            return i - 1
        return i

    # ---------------------------------------------------------------------------------------
    # Werteanzeige: Tabelle, Balken, Legende
    # ---------------------------------------------------------------------------------------
    # ---------------- Werteanzeige ----------------
    @staticmethod
    def set_cell(item, val, v):
        # BOOL: bei 1 ist die Zelle in der Variablenfarbe gefüllt (weiße Schrift), bei 0 normal.
        """Wert anzeigen; BOOL zusätzlich als gefüllte Linie (Zelle in Variablenfarbe) bei 1."""
        item.setText(fmt_value(val, v.dtype))
        if v.dtype == "BOOL":
            on = not math.isnan(val) and val >= 0.5
            item.setBackground(QBrush(QColor(v.color)) if on else QBrush())
            item.setForeground(QBrush(QColor("#ffffff")) if on else QBrush())

    def update_values(self, idx):
        """Online: Aktualwerte in Tabelle und Balken."""
        if not (0 <= idx < len(self.t)):
            return
        self.lbl_time.setText(fmt_time(self.t[idx]))
        # Jede Zeile der Tabelle: aktueller Wert in Spalte 1.
        for i, r in self.row_of.items():
            self.set_cell(self.table.item(r, 1), self.y[i][idx], self.vars[i])
        self.update_bars(idx)
        self.update_legends(idx)

    def update_offline_values(self):
        """Offline: Werte an Lineal 1 und 2 sowie Delta."""
        t1, t2 = self.ruler_t
        if len(self.t) == 0 or t1 is None or t2 is None:
            return
        i1, i2 = self.idx_at(t1), self.idx_at(t2)
        # Kopf über der Tabelle: Zeitpunkte der beiden Lineale und ihr Abstand in Sekunden.
        self.lbl_time.setText("L1: {0}\nL2: {1}\nΔt: {2:.3f} s".format(fmt_time(t1), fmt_time(t2), t2 - t1))
        for i, r in self.row_of.items():
            # Je Variable: Wert an L1 (Spalte 1), an L2 (Spalte 2) und Differenz L2 - L1 (Spalte 3); ungültige Werte ergeben '—'.
            dt = self.vars[i].dtype
            a, b = self.y[i][i1], self.y[i][i2]
            self.set_cell(self.table.item(r, 1), a, self.vars[i])
            self.set_cell(self.table.item(r, 2), b, self.vars[i])
            self.table.item(r, 3).setText(
                "—" if math.isnan(a) or math.isnan(b) else fmt_value(b - a, dt))
        self.update_bars(i1)  # Balken und Legende zeigen offline die Werte an Lineal 1
        self.update_legends(i1)

    # Legenden aller Diagramme mit den Werten des Messpunkts idx aktualisieren.
    def update_legends(self, idx):
        for p in self.panels:
            p.set_legend_values({vi: self.y[vi][idx] for vi in p.var_idx})

    # Balken der Diagramme mit den Werten des Messpunkts idx setzen (nur sichtbare Balken).
    def update_bars(self, idx):
        for p in self.panels:
            if p.bars.isVisible():
                p.bars.set_values([self.y[vi][idx] for vi in p.bar_idx])

    # ---------------------------------------------------------------------------------------
    # CSV laden, Konfiguration
    # ---------------------------------------------------------------------------------------
    # ---------------- CSV laden / Konfiguration ----------------
    # Gespeicherte Aufzeichnung (CSV oder ZIP-Archiv) laden und offline anzeigen.
    def load_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("CSV laden"), self.csv_dir(),
                                              tr("CSV/ZIP (*.csv *.zip);;Alle Dateien (*)"))
        if not path:
            return
        # Läuft gerade eine Aufzeichnung, wird sie beendet (Laden ersetzt die Daten im Speicher).
        if self.rec is not None and self.rec.running:
            self.act_run.setChecked(False)  # stoppt das Logging
        try:
            # Dateiaufbau: Spalte 0 = Zeit (Text), Spalte 1 = Epoch (Unix-Zeit in Sekunden), ab Spalte 2 die Variablen.
            # Die Anzeige verwendet die Epoch-Spalte; leere Felder werden zu 'kein Wert'.
            with open_log(path) as f:
                rd = csv.reader(f, delimiter=";")
                names = next(rd)[2:]
                t, cols = [], [[] for _ in names]
                for row in rd:
                    if len(row) < 2 + len(names):
                        continue
                    t.append(float(row[1]))
                    for k in range(len(names)):
                        s = row[2 + k]
                        cols[k].append(float(s) if s else float("nan"))
        except Exception as e:
            QMessageBox.warning(self, tr("Fehler beim Laden"), str(e))
            return
        if not t:
            QMessageBox.information(self, tr("Leer"), tr("Die Datei enthält keine Daten."))
            return
        self._show_loaded(names, t, cols, "csv", tr("Geladen: {0} ({1} Zeilen)").format(path, len(t)))

    def load_db(self):
        """Lesemodus Datenbank: Zeitraum und Variablen wählen, Werte laden und offline anzeigen."""
        from s7_db_dialog import DbLoadDialog
        conn = self.conn
        names = [v.name for v in self.vars]
        try:
            conn, _charts, cfg_vars = load_config(self.config_path)
            names = [v.name for v in cfg_vars]
        except Exception:
            pass
        dlg = DbLoadDialog(self, conn, names, conn.get("projekt", ""))
        if not dlg.exec() or dlg.result is None:
            return
        t, names, cols, label = dlg.result
        if self.rec is not None and self.rec.running:
            self.act_run.setChecked(False)  # stoppt das Logging (Laden ersetzt die Daten im Speicher)
        self._show_loaded(names, list(t), cols, "db", tr("Geladen: {0} ({1} Zeitpunkte)").format(label, len(t)))

    def _show_loaded(self, names, t, cols, source, message):
        """Geladene Daten (CSV oder Datenbank) offline anzeigen."""
        # Farben, Diagramm- und Achsenzuordnung der Variablen kommen aus der aktuellen Konfiguration, soweit der Name dort vorkommt;
        # unbekannte Variablen erscheinen auf der ersten Achse des ersten Diagramms.
        _conn, charts, cfg_vars = load_config(self.config_path)
        ref = {v.name: v for v in cfg_vars}
        self.charts = charts
        self.vars = [ref.get(n) or Variable(name=n, color=PALETTE[k % len(PALETTE)])
                     for k, n in enumerate(names)]
        self.t, self.y = np.asarray(t, dtype=float), np.asarray(cols, dtype=float).reshape(len(names), len(t))
        self.source = source
        # Anzeige für die geladenen Variablen neu aufbauen.
        self._rebuild()
        self.statusBar().showMessage(message)
        # In den Offline-Modus wechseln (löst enter_offline aus) bzw. die Anzeige direkt aktualisieren, wenn schon offline.
        if self.act_online.isChecked():
            self.act_online.setChecked(False)  # ruft enter_offline() auf
        else:
            self.enter_offline()

    def save_screenshot(self, ci):
        """Ein einzelnes Diagramm (inkl. Achsen, Legende, Balken, Lineale) als PNG oder SVG speichern."""
        if not (0 <= ci < len(self.panels)):
            return
        # Panel, Dock und Titel des gewählten Diagramms nachschlagen.
        panel, dock, title = self.panels[ci], self.dock_of_chart[ci], self.charts[ci].name
        # Vorschlag für den Dateinamen: Diagrammname ohne Sonderzeichen.
        name = re.sub(r"[^\w\-]+", "_", title).strip("_") or f"Diagramm{ci + 1}"
        default = os.path.join(self._shot_dir, f"{name}_{datetime.now():%Y%m%d_%H%M%S}.png")
        # Speichern-Dialog; die Filterauswahl (PNG/SVG) bestimmt das Format, wenn keine Endung getippt wurde.
        path, flt = QFileDialog.getSaveFileName(
            self, tr("Screenshot – {0}").format(title), default,
            tr("PNG-Bild (*.png);;SVG-Vektorgrafik (*.svg)"))
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        # Format aus der Dateiendung ableiten, sonst aus dem gewählten Filter.
        fmt = ext[1:] if ext in (".png", ".svg") else ("svg" if "svg" in flt.lower() else "png")
        if ext not in (".png", ".svg"):
            path += "." + fmt
        # Zielordner für den nächsten Screenshot merken.
        self._shot_dir = os.path.dirname(path) or BASE_DIR
        # Optional heller Hintergrund (für Ausdrucke/Berichte).
        light = self.act_shot_light.isChecked()
        try:
            if fmt == "svg":
                # SVG wird aus den Daten gezeichnet (s7_svg) und braucht weder Umschalten des Themas noch ein sichtbares Panel.
                panel.export_svg(path, title, light)
            else:
                # PNG: das Panel wird gerendert; ein verdecktes Panel (anderer Tab) muss dazu erst sichtbar sein.
                if not panel.isVisible():
                    dock.show()
                    dock.raise_()
                    QApplication.processEvents()
                # try/finally: Das dunkle Theme wird auch bei einem Fehler wiederhergestellt.
                try:
                    if light:
                        panel.set_light_theme(True)
                        QApplication.processEvents()
                    self._render_png(panel, path)
                finally:
                    if light:
                        panel.set_light_theme(False)
        except Exception as e:
            QMessageBox.warning(self, tr("Screenshot fehlgeschlagen"), str(e))
            return
        self.statusBar().showMessage(tr("Screenshot gespeichert: {0}").format(path), 8000)

    @staticmethod
    def _render_png(panel, path, scale=2):
        """PNG mit doppelter Auflösung (Vektorinhalt wird neu gezeichnet, nicht hochskaliert)."""
        w, h = panel.width(), panel.height()
        # Bild mit doppelter Größe anlegen; weißer Untergrund.
        img = QImage(w * scale, h * scale, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.white)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Zeichenfläche skalieren: Vektorinhalte werden scharf neu gezeichnet.
        p.scale(scale, scale)
        panel.render(p)
        p.end()
        # Speichern fehlgeschlagen (Pfad, Rechte) -> Fehlermeldung.
        if not img.save(path, "PNG"):
            raise OSError(tr("Datei konnte nicht geschrieben werden:\n{0}").format(path))

    def open_config(self):
        """Konfigurationsprogramm in eigenem Prozess starten (mit der aktuellen Konfigurationsdatei)."""
        try:
            subprocess.Popen(program_command("config", self.config_path))
        except OSError as e:
            QMessageBox.critical(self, tr("Konfigurationsprogramm"), tr("Das Programm konnte nicht gestartet werden:\n{0}").format(e))

    def closeEvent(self, event):
        """Beim Schließen: Webserver beenden, Aufzeichnung stoppen und die aktuelle CSV-Datei archivieren
        (Einstellung 'archiv_beenden'; das Programm wartet, bis das Archiv geschrieben ist)."""
        self.statusBar().showMessage(tr("Beende … (Aufzeichnung stoppen, CSV archivieren)"))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            if self.web is not None:
                self.web.stop()
            if self.rec is not None:
                self.rec.shutdown()
        finally:
            QApplication.restoreOverrideCursor()
        event.accept()


# Programmstart der Oberfläche (von s7_logger.py aufgerufen): Windows-App-ID (Taskleistensymbol), QApplication,
# Hauptfenster, Ereignisschleife. Rückgabe: Exit-Code.
def run_gui(config_path, demo=False, splash=None):
    set_windows_app_id()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    if splash is None:
        from s7_i18n import install_qt
        install_qt(app)
    win = MainWindow(config_path, demo)
    app.setWindowIcon(win.windowIcon())
    win.show()
    if splash is not None:
        splash.close()
    return app.exec()
