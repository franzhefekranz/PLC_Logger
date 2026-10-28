# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Konfigurationsprogramm: Projekt, Steuerungen, Diagramme, Y-Achsen & Variablen -> Konfigurationsdatei (JSON)

Struktur: Diagramm > Y-Achse(n) > Variablen.
Variablen können über die Auswahlliste "Diagramm › Y-Achse" ODER per Drag & Drop im
Zuordnungsbaum (links) zugewiesen werden:
  * auf eine Y-Achse ziehen        -> Variable gehört zu dieser Achse
  * auf eine andere Variable ziehen -> Variable übernimmt deren Y-Achse
  * auf ein Diagramm ziehen         -> erste Y-Achse des Diagramms

Überblick über das Fenster
--------------------------
* Oben: Reiter für Projektname und Steuerungen (mehrere Steuerungen beliebiger Typen: Name, Treiber, Verbindung, Intervall),
  Aufzeichnung
  (CSV/Archiv), Anzeige (Fenster, Anordnung, Raster, Logo/Icon) sowie Webserver und Headless-Modus.
* Links: der Zuordnungsbaum (Diagramme > Y-Achsen > Variablen/Blöcke) mit den Eigenschaften der
  Auswahl (Name, Seite/Tab, Auto-Skalierung bzw. feste Grenzen der Y-Achse).
* Rechts: die Variablentabelle (Adresse im Format des Treibers, Typ, Farbe, Anzeigeoptionen, Formel) mit den Knöpfen
  für die Auswahl aus der Steuerung, Blöcke, berechnete Variablen und Verbindungstest.
* Menü „Datei“: Neu, Öffnen (beliebiger Dateiname), Speichern, Speichern unter, Logger starten. Als Startparameter
  kann eine Konfigurationsdatei übergeben werden; sonst wird die zuletzt benutzte geöffnet.

Jede Variable und jeder Block gehört zu einer Steuerung (Spalte „Steuerung“). Die Elemente eines Blocks lassen sich im
Blockeditor einzeln anderen Diagrammen zuordnen (Block.targets).

Datenhaltung: Die Variablentabelle ist die einzige Quelle für die Variablen und deren Zuordnung
(Combobox "Diagramm › Y-Achse" je Zeile). Der Baum wird daraus immer neu aufgebaut
(refresh_tree). Diagramme/Achsen stehen in self.charts, Blöcke in self.blocks. Bei Änderungen
der Diagramm-/Achsenstruktur werden alle Zuordnungen (Variablen UND Blöcke) über
assignments()/set_assignments() gesichert und neu gesetzt.
"""


import os
import re
import sys

# Qt-Grundbausteine: Qt (Konstanten), QTimer (verzögerte Aktionen), Signal (eigene Ereignisse).
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QColorDialog, QComboBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget, QMenu,
)

# Eigene Module: Branding, Dialoge (Blöcke, Formeln), Datenmodell/Konfiguration, Treiber, Formelprüfung.
# Die Treiber (plc_treiber) laden ihre Bibliotheken erst bei Bedarf: das Programm startet auch ohne sie.
from plc_branding import app_icon, set_windows_app_id
from plc_about import set_help
from plc_block_dialog import BlockEditor
from plc_common import (RECORD_MODES, CONFIG_EXT, ConfigFormatError, convert_ini, read_config_store, BASE_DIR, LAYOUTS, PAGE_LAYOUTS, PALETTE,
                       Axis, Block, Chart, Plc, Variable, default_connection, driver_store,
                       last_config_path, load_blocks, load_config, load_plcs,
                       remember_config_path, save_config,
                        program_command)
from plc_formula import check as check_formula
from plc_formula_dialog import FormulaEditor
from plc_events import EventLog, check_trigger, event_log_path, load_triggers, save_triggers
from plc_db import DB_TYPES, DEFAULT_PORTS, HTTP_TYPES, METRIC_TYPES, check_table_name, test_connection as test_db
from plc_i18n import N_, tr
from plc_treiber import drivers, get_driver, load_errors
from plc_treiber.base import BrowseContext

# Benutzerdefinierte Datenrollen der Baumeinträge (QTreeWidgetItem.setData): ID der Variable, Art des Knotens,
# Diagramm- und Achsenindex. Der Wert von UserRole ist die erste freie Rolle.
ROLE_UID = Qt.ItemDataRole.UserRole.value
ROLE_KIND = ROLE_UID + 1   # "chart" | "axis" | "var"
ROLE_CI = ROLE_UID + 2     # Diagramm-Index
ROLE_AI = ROLE_UID + 3     # Achsen-Index

# Spalten der Variablentabelle (Nummern) und ihre Überschriften.
# Spalten der Variablentabelle
(C_NAME, C_PLC, C_AXIS, C_TAG, C_TYPE, C_COLOR, C_SHOW, C_BAR, C_TEST, C_FORMULA) = range(10)
# Spalten der Variablenliste für Import/Export (CSV/Excel). Die Kopfzeile bleibt in jeder Sprache deutsch, damit
# Dateien austauschbar sind; beim Import zählt nur der Spaltenname (Reihenfolge und Groß-/Kleinschreibung egal).
VAR_IO_COLS = ["Name", "Steuerung", "Diagramm", "Y-Achse", "Adresse", "Typ", "Farbe", "Werteanzeige", "Balken",
               "Formel"]
VAR_COLS = [tr("Name"), tr("Steuerung"), tr("Diagramm › Y-Achse"), tr("Adresse"), tr("Typ"),
            tr("Farbe"), tr("Werteanzeige"), tr("Balken"), tr("Testwert"), tr("Formel")]

# Spalten der Steuerungen-Tabelle (Reiter „Projekt & Steuerungen“).
PLC_COLS = [tr("Name"), tr("Treiber"), tr("Verbindung"), "", tr("Intervall"), tr("Aktiv")]
(P_NAME, P_DRV, P_CONN, P_SET, P_INT, P_ON) = range(6)
ROLE_PARAMS = Qt.ItemDataRole.UserRole.value + 10     # Parameter der Steuerung (Dict) im Verbindungs-Element

# Dateifilter für die Dateidialoge: beliebige Dateinamen sind erlaubt.
FILE_FILTER = tr("Konfiguration (*.json);;Alle Dateien (*)")


# Kleines farbiges Quadrat als Symbol im Baum (zeigt die Variablenfarbe).
def swatch(color: str) -> QIcon:
    """Farbquadrat 12 x 12 Pixel als QIcon."""
    pm = QPixmap(12, 12)
    pm.fill(QColor(color))
    return QIcon(pm)


# Baum für die Zuordnung. Eigene Behandlung des Ablegens (dropEvent), weil Qt das Verschieben von Einträgen
# zwischen Eltern nicht so abbilden kann, wie wir es brauchen (z. B. Ablegen AUF eine andere Variable).
class AssignTree(QTreeWidget):
    """Baum Diagramm > Y-Achse > Variable. Das Verschieben wird nicht von Qt erledigt,
    sondern als Signal gemeldet; die Tabelle ist die einzige Datenquelle."""
    # Wird beim Ablegen gesendet: IDs der verschobenen Variablen, Ziel-Diagramm, Ziel-Achse.
    moved = Signal(list, int, int)   # uids, Diagramm-Index, Achsen-Index

    def __init__(self):
        """Baum ohne Kopfzeile; Einträge lassen sich einzeln ziehen und im selben Baum ablegen."""
        super().__init__()
        self.setHeaderHidden(True)
        # Es wird immer genau ein Eintrag gezogen.
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # DragDrop: Einträge dürfen gezogen und im selben Baum abgelegt werden.
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    # Ablegen: Zielposition bestimmen und als Signal melden. Die Tabelle wird vom Fenster angepasst.
    def dropEvent(self, event):
        target = self.itemAt(event.position().toPoint())
        # Gezogen werden nur Variablen (kind == 'var').
        uids = [it.data(0, ROLE_UID) for it in self.selectedItems()
                if it.data(0, ROLE_KIND) == "var"]
        if target is None or not uids:
            event.ignore()
            return
        # Ziel bestimmen: Diagramm -> erste Achse; Achse -> diese Achse; Variable -> deren Achse (Ablegen auf eine Variable).
        kind = target.data(0, ROLE_KIND)
        if kind == "chart":
            ci, ai = target.data(0, ROLE_CI), 0
        elif kind == "axis":
            ci, ai = target.data(0, ROLE_CI), target.data(0, ROLE_AI)
        else:  # auf eine andere Variable: deren Achse übernehmen
            p = target.parent()
            ci, ai = p.data(0, ROLE_CI), p.data(0, ROLE_AI)
        # Qt soll nach dem Ablegen NICHT selbst Einträge entfernen (bei MoveAction würde es die Quelle löschen).
        event.setDropAction(Qt.DropAction.CopyAction)  # Qt soll nichts selbst entfernen
        event.accept()
        self.moved.emit(uids, ci, ai)


# Hauptfenster des Konfigurationsprogramms.
class ConfigWindow(QMainWindow):
    """Konfigurationsfenster: bearbeitet die Konfigurationsdatei von plc_logger.py."""
    def __init__(self, path=None):
        """Fenster aufbauen und die Konfiguration ``path`` (sonst die zuletzt benutzte) laden.

        Aufbau von oben nach unten: Reiter mit den Einstellungen (Projekt & Steuerungen, Aufzeichnung, Anzeige,
        Webserver & Headless, Datenbank, Trigger & Ereignisse, Berichte), darunter links der Zuordnungsbaum mit den
        Eigenschaften und rechts die Variablentabelle, dazu Menüs, Werkzeugleiste und Kontexthilfe (F1). Am Ende füllt
        ``fill`` die Felder aus der Datei (Einstellungen, Diagramme, Variablen, Blöcke, Steuerungen, Trigger).
        """
        super().__init__()
        # Menü im Fenster (Linux: sonst evtl. nur im globalen Menü); macOS: wie üblich oben am Bildschirm
        self.menuBar().setNativeMenuBar(sys.platform == "darwin")
        self.resize(1300, 820)
        # Pfad der aktuell bearbeiteten Konfigurationsdatei: Startparameter, sonst die zuletzt benutzte Datei ('' = neu, ungespeichert).
        self.path = os.path.abspath(path) if path else last_config_path()
        # Zähler für Variablen-IDs (stabil, auch wenn sich Tabellenzeilen verschieben).
        self._uid = 0
        # Während Eigenschaften programmatisch in die Felder geschrieben werden, sollen die Felder keine Änderungen melden.
        self._loading = False
        # Aktuelle Auswahl im Baum: ('chart', Diagramm, 0) oder ('axis', Diagramm, Achse), sonst None.
        self.prop_key = None   # ("chart", ci, 0) | ("axis", ci, ai) | None
        self.charts = [Chart()]
        self.blocks = []           # Blöcke (Blocklesemodus)
        self.triggers = []         # Trigger (Ereignisbedingungen), gespeichert in [Trigger]/[TriggerN]
        self.store = {}            # treibereigene Werte {Treiber: {Schlüssel: Wert}} (z. B. DB-Quellen des S7-Treibers)

        # ---- Reiter 1: Projekt und Steuerungen ----
        self.ed_project = QLineEdit()
        self.ed_project.setPlaceholderText(tr("z. B. Prüfstand 3"))
        self.ed_project.setToolTip(tr("Projektname: erscheint in den Fenstertiteln, im Webserver und in der Logdatei"))
        self.ed_project.textChanged.connect(lambda _t: self.update_title())
        # Tabelle der Steuerungen: jede Zeile = eine SPS mit eigenem Lese-Thread und eigenem Abtastintervall.
        self.plc_table = QTableWidget(0, len(PLC_COLS))
        self.plc_table.setHorizontalHeaderLabels(PLC_COLS)
        self.plc_table.horizontalHeader().setSectionResizeMode(P_NAME, QHeaderView.ResizeMode.Stretch)
        self.plc_table.horizontalHeader().setSectionResizeMode(P_CONN, QHeaderView.ResizeMode.Stretch)
        self.plc_table.cellDoubleClicked.connect(lambda r, c: self.edit_plc_params(r) if c == P_CONN else None)
        self.plc_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.plc_table.itemChanged.connect(self.on_plc_item_changed)
        plc_btns = QHBoxLayout()
        for text, fn in [(tr("+ Steuerung"), self.add_plc), (tr("Steuerung entfernen"), self.remove_plc),
                         (tr("Netzwerk durchsuchen …"), self.scan_network)]:
            bt = QPushButton(text); bt.clicked.connect(fn); plc_btns.addWidget(bt)
        plc_btns.itemAt(2).widget().setToolTip(tr("Erreichbare Steuerungen im Netzwerk suchen und als Steuerung übernehmen"))
        plc_btns.addStretch(1)
        plc_box = QVBoxLayout(); plc_box.addWidget(self.plc_table, 1); plc_box.addLayout(plc_btns)
        proj_form = QFormLayout(); proj_form.addRow(tr("Projektname:"), self.ed_project)
        tab_plc = QWidget()
        tl = QHBoxLayout(tab_plc); tl.addLayout(proj_form, 1); tl.addSpacing(20); tl.addLayout(plc_box, 3)

        # ---- Reiter 2: Aufzeichnung ----
        # Anzeigefenster und CSV/Archiv
        self.sp_win = QSpinBox(); self.sp_win.setRange(1, 604800); self.sp_win.setSuffix(" s")
        self.ed_dir = QLineEdit()
        btn_dir = QPushButton("…"); btn_dir.setFixedWidth(30)
        btn_dir.clicked.connect(self.pick_dir)
        dir_row = QHBoxLayout(); dir_row.addWidget(self.ed_dir); dir_row.addWidget(btn_dir)
        self.ed_csvname = QLineEdit()
        self.ed_csvname.setToolTip(tr("Dateiname-Präfix und Name des Archiv-Unterordners"))
        # 0 bedeutet 'unbegrenzt' (Spezialtext statt der Zahl 0).
        self.sp_maxrec = QSpinBox()
        self.sp_maxrec.setRange(0, 100_000_000)
        self.sp_maxrec.setSingleStep(1000)
        self.sp_maxrec.setSpecialValueText(tr("unbegrenzt"))
        self.sp_maxrec.setToolTip(tr("Ist die Anzahl erreicht, wird die Datei gepackt, archiviert "
                                  "und eine neue begonnen (0 = unbegrenzt)"))
        self.ed_arch = QLineEdit()
        btn_arch = QPushButton("…"); btn_arch.setFixedWidth(30)
        btn_arch.clicked.connect(self.pick_arch_dir)
        arch_row = QHBoxLayout(); arch_row.addWidget(self.ed_arch); arch_row.addWidget(btn_arch)
        self.chk_arch_end = QCheckBox(tr("Beim Beenden des Loggers die aktuelle CSV-Datei archivieren"))
        # Aufräumen: CSV-Dateien und Archiv dieses Loggers nach Alter bzw. Gesamtgröße löschen (0 = aus).
        self.sp_clean_days = self._days_spin(tr("CSV-Dateien und Archiv-ZIPs dieses Loggers löschen, deren letzte "
                                                "Änderung länger zurückliegt (0 = nie)"))
        self.sp_clean_mb = self._mb_spin(tr("Belegen CSV-Dateien und Archiv dieses Loggers mehr Platz, werden die "
                                            "ältesten gelöscht (0 = unbegrenzt)"))
        form_rec1 = QFormLayout()
        # CSV-Datei abschaltbar (z. B. wenn nur in eine Datenbank aufgezeichnet werden soll).
        self.chk_csv = QCheckBox(tr("CSV-Datei schreiben"))
        self.chk_csv.setToolTip(tr("Ausgeschaltet: keine CSV-Datei (z. B. nur Datenbank, Reiter „Datenbank“)"))
        form_rec1.addRow("", self.chk_csv)
        form_rec1.addRow(tr("CSV-Ordner:"), dir_row)
        form_rec1.addRow(tr("CSV-Name:"), self.ed_csvname)
        form_rec1.addRow(tr("Max. Datensätze je Datei:"), self.sp_maxrec)
        form_rec2 = QFormLayout()
        form_rec2.addRow(tr("Archiv-Ordner:"), arch_row)
        form_rec2.addRow("", self.chk_arch_end)
        form_rec2.addRow(tr("Löschen nach:"), self.sp_clean_days)
        form_rec2.addRow(tr("Höchstens belegen:"), self.sp_clean_mb)
        # Aufzeichnung dauernd oder per Trigger: Startbedingung, Vorlauf (Ringspeicher), Nachlauf, Höchstdauer.
        self.cb_rec_mode = QComboBox()
        for key, text in RECORD_MODES.items():
            self.cb_rec_mode.addItem(tr(text), key)
        self.cb_rec_mode.setToolTip(tr("Per Trigger: in CSV-Datei/Datenbank wird nur geschrieben, wenn die Startbedingung "
                                       "erfüllt ist – mit den Werten der Vorlaufzeit davor und der Nachlaufzeit danach. "
                                       "Jede Aufnahme bekommt eine eigene CSV-Datei. Die Anzeige läuft immer."))
        self.ed_rec_cond = QLineEdit()
        self.ed_rec_cond.setPlaceholderText(tr("z. B. {Druck} > 5 or {Störung} == 1"))
        self.ed_rec_cond.setToolTip(tr("Bedingung wie bei Triggern und berechneten Variablen; wahr (≠ 0) startet die Aufnahme"))
        btn_cond = QPushButton("…")
        btn_cond.setFixedWidth(30)
        btn_cond.setToolTip(tr("Bedingung mit dem Formeleditor bearbeiten"))
        btn_cond.clicked.connect(self.edit_rec_condition)
        cond_row = QHBoxLayout(); cond_row.addWidget(self.ed_rec_cond); cond_row.addWidget(btn_cond)
        self.sp_pre = QDoubleSpinBox(); self.sp_pre.setRange(0, 86400); self.sp_pre.setDecimals(1); self.sp_pre.setSuffix(" s")
        self.sp_pre.setToolTip(tr("So viele Sekunden vor dem Trigger werden mitgespeichert (Ringspeicher)"))
        self.sp_post = QDoubleSpinBox(); self.sp_post.setRange(0, 86400); self.sp_post.setDecimals(1); self.sp_post.setSuffix(" s")
        self.sp_post.setToolTip(tr("So lange wird nach dem Ende der Bedingung weiter gespeichert"))
        self.sp_max = QDoubleSpinBox(); self.sp_max.setRange(0, 7 * 86400); self.sp_max.setDecimals(0)
        self.sp_max.setSuffix(" s"); self.sp_max.setSpecialValueText(tr("unbegrenzt"))
        self.sp_max.setToolTip(tr("Höchstdauer einer Aufnahme (0 = unbegrenzt); danach muss die Bedingung erst "
                                  "wieder falsch werden"))
        prepost = QHBoxLayout()
        for lbl, w in ((tr("Vorlauf"), self.sp_pre), (tr("Nachlauf"), self.sp_post), (tr("max."), self.sp_max)):
            prepost.addWidget(QLabel(lbl)); prepost.addWidget(w)
        self.cb_rec_mode.currentIndexChanged.connect(lambda _i: self._update_rec_mode())
        form_rec3 = QFormLayout()
        form_rec3.addRow(tr("Aufzeichnung:"), self.cb_rec_mode)
        form_rec3.addRow(tr("Startbedingung:"), cond_row)
        form_rec3.addRow("", prepost)
        tab_rec = QWidget()
        rl0 = QHBoxLayout(tab_rec); rl0.addLayout(form_rec1, 1); rl0.addSpacing(20); rl0.addLayout(form_rec2, 1)
        rl0.addSpacing(20); rl0.addLayout(form_rec3, 1)

        # ---- Reiter 3: Anzeige ----
        # Logo und Programm-Icon: Dateiauswahl mit Durchsuchen-Knopf (siehe _file_row).
        self.ed_logo = QLineEdit()
        self.ed_logo.setToolTip(tr("Bilddatei (PNG/JPG, im Logger und auf den Webseiten auch SVG): Logger rechts oben, "
                                   "Webseiten (Diagramme, Prozessbild, Anmeldung) und PDF-Berichte; leer = kein Logo"))
        self.ed_logo.setPlaceholderText(tr("leer = kein Logo"))
        self.ed_customer_logo = QLineEdit()
        self.ed_customer_logo.setToolTip(tr("Zusätzliches Logo des Kunden (PNG/JPG), erscheint neben dem Logo; "
                                            "leer = kein Kundenlogo"))
        self.ed_customer_logo.setPlaceholderText(tr("leer = kein Kundenlogo"))
        self.ed_icon = QLineEdit()
        self.ed_icon.setToolTip(tr("Programm-Icon (PNG/ICO/SVG); leer = Logo bzw. Standard-Icon"))
        logo_row = self._file_row(self.ed_logo, tr("Logo wählen"))
        customer_row = self._file_row(self.ed_customer_logo, tr("Kundenlogo wählen"))
        icon_row = self._file_row(self.ed_icon, tr("Programm-Icon wählen"))
        # Standard-Anordnung der Seiten im Logger: Anzeigetext + interner Schlüssel.
        self.cb_layout = QComboBox()
        for key, text in LAYOUTS.items():
            self.cb_layout.addItem(tr(text), key)
        # Anordnung der Diagramme innerhalb einer Seite (leer = automatisch) und Spaltenzahl des Rasters.
        self.cb_page = QComboBox()
        self.cb_page.addItem(tr("Automatisch (wie Standard-Anordnung)"), "")
        for key, text in PAGE_LAYOUTS.items():
            self.cb_page.addItem(tr(text), key)
        self.sp_cols = QSpinBox(); self.sp_cols.setRange(0, 12); self.sp_cols.setSpecialValueText(tr("automatisch"))
        self.sp_cols.setToolTip(tr("Anzahl der Spalten bei der Anordnung „Raster“ (0 = automatisch aus der Diagrammzahl)"))
        self.chk_bars = QCheckBox(tr("Balken für Aktualwerte anzeigen"))
        self.sp_bar_w = QSpinBox(); self.sp_bar_w.setRange(4, 40); self.sp_bar_w.setSuffix(" px")
        self.sp_bar_w.setToolTip(tr("Breite eines Balkens neben dem Diagramm (Vorgabe 14 Pixel)"))
        form_view1 = QFormLayout()
        form_view1.addRow(tr("Anzeigefenster (online):"), self.sp_win)
        form_view1.addRow(tr("Standard-Anordnung der Seiten:"), self.cb_layout)
        form_view1.addRow(tr("Diagramme auf einer Seite:"), self.cb_page)
        form_view1.addRow(tr("Raster-Spalten:"), self.sp_cols)
        form_view2 = QFormLayout()
        form_view2.addRow(tr("Logo:"), logo_row)
        form_view2.addRow(tr("Kundenlogo:"), customer_row)
        form_view2.addRow(tr("Programm-Icon:"), icon_row)
        form_view2.addRow("", self.chk_bars)
        form_view2.addRow(tr("Balkenbreite:"), self.sp_bar_w)
        tab_view = QWidget()
        vl0 = QHBoxLayout(tab_view); vl0.addLayout(form_view1, 1); vl0.addSpacing(30); vl0.addLayout(form_view2, 1)

        # ---- Reiter 4: Webserver und Headless ----
        self.chk_web = QCheckBox(tr("Webserver starten (Diagramme im Browser, z. B. mit Tablet/Smartphone)"))
        self.ed_web_host = QLineEdit()
        self.ed_web_host.setToolTip(tr("0.0.0.0 = erreichbar im ganzen Netzwerk, 127.0.0.1 = nur auf diesem Rechner"))
        self.sp_web_port = QSpinBox(); self.sp_web_port.setRange(1, 65535)
        self.ed_web_token = QLineEdit()
        self.ed_web_token.setPlaceholderText(tr("leer = ohne Zugriffsschutz"))
        self.ed_web_token.setToolTip(tr("Zugriffscode: die Seite wird mit ?token=CODE aufgerufen"))
        self.sp_web_int = QSpinBox(); self.sp_web_int.setRange(200, 60000); self.sp_web_int.setSuffix(" ms")
        self.chk_headless = QCheckBox(tr("Headless-Modus: ohne Diagramme starten, nur aufzeichnen"))
        self.chk_headless.setToolTip(tr("Der Logger läuft ohne Fenster (z. B. als Dienst); Webserver und Archivierung bleiben aktiv. "
                                     "Mit dem Startparameter --gui lässt sich trotzdem die Oberfläche öffnen."))
        form_web1 = QFormLayout()
        form_web1.addRow("", self.chk_web)
        form_web1.addRow(tr("Adresse (Host):"), self.ed_web_host)
        form_web1.addRow(tr("Port:"), self.sp_web_port)
        form_web2 = QFormLayout()
        form_web2.addRow(tr("Zugriffscode:"), self.ed_web_token)
        form_web2.addRow(tr("Aktualisierung im Browser:"), self.sp_web_int)
        form_web2.addRow("", self.chk_headless)
        # Laufende Headless-Logger anzeigen und beenden (Statusdateien im Datenordner, plc_headless).
        btn_hl = QPushButton(tr("Laufende Logger …"))
        btn_hl.setToolTip(tr("Laufende Headless-Logger anzeigen und sauber beenden"))
        btn_hl.clicked.connect(self.show_headless)
        self.lbl_headless = QLabel("")
        hl_row = QHBoxLayout(); hl_row.addWidget(btn_hl); hl_row.addWidget(self.lbl_headless, 1)
        form_web2.addRow(tr("Headless-Logger:"), hl_row)
        # OPC-UA-Server im Logger (Einstellungen im eigenen Dialog).
        self.opcua_settings = {}
        btn_ua = QPushButton(tr("OPC UA …"))
        btn_ua.setToolTip(tr("Variablen über einen OPC-UA-Server im Logger bereitstellen (Leitsystem, MES, SCADA)"))
        btn_ua.clicked.connect(self.edit_opcua_server)
        self.lbl_opcua = QLabel("")
        self.lbl_opcua.setWordWrap(True)
        ua_row = QHBoxLayout(); ua_row.addWidget(btn_ua); ua_row.addWidget(self.lbl_opcua, 1)
        form_web2.addRow(tr("OPC-UA-Server:"), ua_row)
        # HTTPS und Anmeldung (Benutzer mit Passwort; gespeichert wird nur ein Hash).
        self.chk_https = QCheckBox(tr("HTTPS (verschlüsselt)"))
        self.chk_https.setToolTip(tr("Ohne eigenes Zertifikat wird einmalig ein selbstsigniertes erzeugt (Ordner "
                                     "web_tls); der Browser fragt dann beim ersten Aufruf nach"))
        self.ed_web_cert = QLineEdit()
        self.ed_web_cert.setPlaceholderText(tr("leer = selbstsigniert"))
        self.ed_web_key = QLineEdit()
        self.ed_web_key.setPlaceholderText(tr("leer = im Zertifikat enthalten"))
        self.web_users = {}
        self.lbl_web_users = QLabel("")
        btn_users = QPushButton(tr("Benutzer …"))
        btn_users.setToolTip(tr("Anmeldung mit Benutzer und Passwort einrichten"))
        btn_users.clicked.connect(self.edit_web_users)
        users_row = QHBoxLayout(); users_row.addWidget(btn_users); users_row.addWidget(self.lbl_web_users, 1)
        self.chk_https.toggled.connect(lambda on: (self.ed_web_cert.setEnabled(on), self.ed_web_key.setEnabled(on)))
        form_web3 = QFormLayout()
        form_web3.addRow("", self.chk_https)
        form_web3.addRow(tr("Zertifikat (PEM):"), self._file_row(self.ed_web_cert, tr("Zertifikat wählen"),
                                                                tr("Zertifikat (*.pem *.crt *.cer);;Alle Dateien (*)")))
        form_web3.addRow(tr("Schlüssel (PEM):"), self._file_row(self.ed_web_key, tr("Schlüssel wählen"),
                                                               tr("Schlüssel (*.pem *.key);;Alle Dateien (*)")))
        form_web3.addRow(tr("Anmeldung:"), users_row)
        tab_web = QWidget()
        wl0 = QHBoxLayout(tab_web); wl0.addLayout(form_web1, 1); wl0.addSpacing(20); wl0.addLayout(form_web2, 1)
        wl0.addSpacing(20); wl0.addLayout(form_web3, 1)

        # Die vier Reiter bilden den oberen Fensterbereich.
        self.tabs = QTabWidget()
        self.tabs.addTab(tab_plc, tr("Projekt && Steuerungen"))
        self.tabs.addTab(tab_rec, tr("Aufzeichnung"))
        self.tabs.addTab(tab_view, tr("Anzeige"))
        self.tabs.addTab(tab_web, tr("Webserver && Headless"))
        self.tabs.addTab(self._build_db_tab(), tr("Datenbank"))
        self.tabs.addTab(self._build_trigger_tab(), tr("Trigger && Ereignisse"))
        self.tabs.addTab(self._build_report_tab(), tr("Berichte (PDF)"))
        self.tabs.setMaximumHeight(210)
        self.tabs.currentChanged.connect(lambda i: self.update_headless_label() if self.tabs.widget(i) is tab_web else None)
        # Kontexthilfe (F1): Abschnitt der Bedienungsanleitung je Reiter; in der Steuerungstabelle der Abschnitt des
        # Treibers der aktuellen Zeile.
        for i, topic in enumerate(("Projekt, Steuerungen und Einstellungen", "Projekt, Steuerungen und Einstellungen",
                                   "Projekt, Steuerungen und Einstellungen", "Webserver (Diagramme im Browser)",
                                   "Datenbank-Aufzeichnung", "Trigger und Ereignisprotokoll", "PDF-Berichte")):
            set_help(self.tabs.widget(i), topic)
        set_help(self.plc_table, self._plc_help_topic)

        # ---- Links: Zuordnungsbaum und Eigenschaften der Auswahl ----
        # ---------- Zuordnungsbaum + Eigenschaften ----------
        self.tree = AssignTree()
        self.tree.itemSelectionChanged.connect(self.on_tree_select)
        self.tree.moved.connect(self.on_moved)

        # Eigenschaften der Auswahl: Name, Seite (nur Diagramm), Auto-Skalierung und Y-Grenzen (nur Y-Achse).
        # Geändert wird erst nach Verlassen des Feldes (editingFinished) bzw. beim Umschalten des Kästchens.
        self.ed_name = QLineEdit()
        self.chk_auto = QCheckBox(tr("Auto-Skalierung"))
        self.sp_min = QDoubleSpinBox(); self.sp_min.setRange(-1e9, 1e9); self.sp_min.setDecimals(3)
        self.sp_max = QDoubleSpinBox(); self.sp_max.setRange(-1e9, 1e9); self.sp_max.setDecimals(3)
        self.ed_name.editingFinished.connect(self.apply_props)
        self.ed_page = QLineEdit()
        self.ed_page.setPlaceholderText(tr("leer = Standardseite"))
        self.ed_page.setToolTip(tr("Diagramme mit gleichem Seitennamen werden gemeinsam in einem Tab/Dock angezeigt"))
        self.ed_page.editingFinished.connect(self.apply_props)
        self.chk_auto.toggled.connect(self.apply_props)
        self.sp_min.editingFinished.connect(self.apply_props)
        self.sp_max.editingFinished.connect(self.apply_props)
        grp = QGroupBox(tr("Eigenschaften der Auswahl (Diagramm / Y-Achse)"))
        pf = QFormLayout(grp)
        pf.addRow(tr("Name:"), self.ed_name)
        pf.addRow(tr("Seite (Tab):"), self.ed_page)
        pf.addRow("", self.chk_auto)
        pf.addRow(tr("Y min:"), self.sp_min)
        pf.addRow(tr("Y max:"), self.sp_max)
        # PID-Regler-Optimierung je Diagramm (Soll-/Ist-/Stellwert festlegen; Berechnung im Logger).
        self.chk_pid = QCheckBox(tr("PID-Regler-Optimierung"))
        self.chk_pid.setToolTip(tr("Im Logger lassen sich für dieses Diagramm aus Soll-, Ist- und Stellwert die "
                                "PID-Parameter berechnen"))
        self.chk_pid.toggled.connect(self.on_pid_toggled)
        self.btn_pid = QPushButton(tr("Einstellen …"))
        self.btn_pid.clicked.connect(self.edit_pid)
        self.lbl_pid = QLabel("")
        self.lbl_pid.setStyleSheet("color:#555")
        pid_row = QHBoxLayout()
        pid_row.addWidget(self.chk_pid)
        pid_row.addWidget(self.btn_pid)
        pid_row.addWidget(self.lbl_pid, 1)
        pf.addRow(tr("Regler:"), pid_row)

        # Knöpfe unter dem Baum: Diagramm/Achse anlegen, Auswahl entfernen.
        cbtn = QHBoxLayout()
        for text, fn in [(tr("+ Diagramm"), self.add_chart), (tr("+ Y-Achse"), self.add_axis),
                         (tr("Entfernen"), self.remove_selected)]:
            b = QPushButton(text); b.clicked.connect(fn); cbtn.addWidget(b)

        left = QWidget()
        ll = QVBoxLayout(left); ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel(tr("<b>Diagramme › Y-Achsen › Variablen</b><br>"
                            "Variable auf eine Y-Achse oder auf eine andere Variable ziehen")))
        ll.addWidget(self.tree, 1)
        ll.addLayout(cbtn)
        ll.addWidget(grp)
        set_help(grp, "Eigenschaften von Diagramm und Y-Achse")

        # ---- Rechts: Variablentabelle und ihre Knöpfe ----
        # ---------- Variablen ----------
        self.table = QTableWidget(0, len(VAR_COLS))
        self.table.setHorizontalHeaderLabels(VAR_COLS)
        self.table.horizontalHeader().setSectionResizeMode(C_NAME, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # Änderung des Namens -> Baum aktualisieren; Doppelklick auf die Formelspalte -> Formeleditor.
        self.table.itemChanged.connect(self.on_var_item_changed)
        self.table.itemDoubleClicked.connect(self.on_var_double_click)
        set_help(self.table, "Variablen anlegen")
        right = QWidget()
        rl = QVBoxLayout(right); rl.setContentsMargins(0, 0, 0, 0)
        # Suchen und Filtern: Text (Name, Adresse, Formel, Zuordnung) und Steuerung; ausgeblendete Zeilen bleiben
        # erhalten und werden mitgespeichert.
        self.ed_filter = QLineEdit()
        self.ed_filter.setClearButtonEnabled(True)
        self.ed_filter.setPlaceholderText(tr("Suchen: Name, Adresse, Formel … (* ? als Platzhalter, -Wort schließt aus)"))
        self.ed_filter.setToolTip(tr("Mehrere Wörter müssen alle vorkommen; Strg+F springt hierher"))
        self.ed_filter.textChanged.connect(lambda _t: self.apply_var_filter())
        self.cb_filter_plc = QComboBox()
        self.cb_filter_plc.setToolTip(tr("Nur Variablen dieser Steuerung zeigen"))
        self.cb_filter_plc.currentIndexChanged.connect(lambda _i: self.apply_var_filter())
        self.cb_filter_kind = QComboBox()
        for text, key in ((tr("alle Arten"), ""), (tr("nur gelesene"), "plc"), (tr("nur berechnete"), "calc"),
                          (tr("ohne Adresse"), "empty")):
            self.cb_filter_kind.addItem(text, key)
        self.cb_filter_kind.currentIndexChanged.connect(lambda _i: self.apply_var_filter())
        self.lbl_filter = QLabel("")
        self.lbl_filter.setStyleSheet("color:#555")
        frow = QHBoxLayout()
        frow.addWidget(QLabel(tr("<b>Variablen</b>")))
        frow.addSpacing(12)
        frow.addWidget(self.ed_filter, 1)
        frow.addWidget(self.cb_filter_plc)
        frow.addWidget(self.cb_filter_kind)
        frow.addWidget(self.lbl_filter)
        rl.addLayout(frow)
        act_find = QAction(self)
        act_find.setShortcut(QKeySequence.StandardKey.Find)
        act_find.triggered.connect(lambda: (self.ed_filter.setFocus(), self.ed_filter.selectAll()))
        self.addAction(act_find)
        rl.addWidget(self.table, 1)
        # Aktionen rund um Variablen: Symbolbaum, Blöcke, Formeln, manuelles Anlegen, Entfernen, Test.
        vbtn = QHBoxLayout()
        for text, fn in [(tr("Aus Steuerung wählen…"), self.open_tag_browser),
                         (tr("Blöcke (Blocklesemodus)…"), self.open_block_editor),
                         (tr("Berechnete Variable…"), self.add_computed),
                         (tr("Variable hinzufügen"), lambda: self.add_row()),
                         (tr("Entfernen"), self.remove_rows),
                         (tr("Verbindung testen"), self.test_connection)]:
            b = QPushButton(text); b.clicked.connect(fn); vbtn.addWidget(b)
        # Import/Export der Variablenliste (CSV oder Excel) als Knopf mit Menü.
        b = QPushButton(tr("Import/Export"))
        m_io = QMenu(b)
        m_io.addAction(tr("Variablen importieren (CSV/Excel/ODS) …"), self.import_variables)
        m_io.addAction(tr("Variablen exportieren (CSV/Excel) …"), self.export_variables)
        b.setMenu(m_io)
        set_help(b, "Variablen importieren und exportieren")
        vbtn.addWidget(b)
        rl.addLayout(vbtn)

        # Teilbarer Bereich: links Baum + Eigenschaften, rechts Tabelle (Verhältnis 1 : 3).
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left); split.addWidget(right)
        split.setStretchFactor(0, 1); split.setStretchFactor(1, 3)

        bottom = QHBoxLayout(); bottom.addStretch(1)
        for text, fn in [(tr("Öffnen…"), self.open_file), (tr("Speichern"), self.save), (tr("Speichern unter…"), self.save_as)]:
            b = QPushButton(text); b.clicked.connect(lambda _c=False, f=fn: f()); bottom.addWidget(b)

        # Fensterinhalt: oben Einstellungen, in der Mitte der geteilte Bereich, unten Laden/Speichern.
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.addWidget(self.tabs); lay.addWidget(split, 1); lay.addLayout(bottom)
        self.setCentralWidget(central)

        # Beim Start die vorhandene Konfigurationsdatei laden (Verbindung, Diagramme, Variablen, Blöcke) und das Fenster-Icon setzen.
        self.build_menu()
        self.fill(*load_config(self.path), blocks=load_blocks(self.path), plcs=load_plcs(self.path))
        self.triggers = load_triggers(self.path)
        self._update_trigger_summary()
        if load_errors():
            QTimer.singleShot(800, lambda: self.statusBar().showMessage(
                tr("Nicht alle Treiber konnten geladen werden – Menü Treiber › Installierte Treiber"), 15000))
        self.setWindowIcon(app_icon(self.ed_icon.text(), self.ed_logo.text()))
        self.update_title()

    # ---------------------------------------------------------------------------------------
    # Menü und Fenstertitel
    # ---------------------------------------------------------------------------------------
    def build_menu(self):
        """Menü „Datei“: Neu, Öffnen, Speichern, Speichern unter, Logger starten, Beenden."""
        m = self.menuBar().addMenu(tr("&Datei"))
        std = QKeySequence.StandardKey
        entries = [(N_("&Neu"), QKeySequence(std.New), self.new_config),
                   (N_("&Öffnen …"), QKeySequence(std.Open), self.open_file),
                   (N_("&Speichern"), QKeySequence(std.Save), self.save),
                   (N_("Speichern &unter …"), QKeySequence("Ctrl+Shift+S"), self.save_as),
                   None,
                   (N_("INI-Datei &umwandeln …"), QKeySequence(), self.convert_ini),
                   (N_("Logger mit dieser Konfiguration &starten"), QKeySequence("Ctrl+R"), self.start_logger),
                   (N_("&IO-Check mit dieser Konfiguration starten"), QKeySequence(), self.start_iocheck),
                   (N_("&Headless-Logger anzeigen/beenden …"), QKeySequence(), self.show_headless),
                   None,
                   (N_("&Beenden"), QKeySequence("Ctrl+Q"), self.close)]
        for e in entries:
            if e is None:
                m.addSeparator()
                continue
            text, key, fn = e
            act = QAction(tr(text), self)
            act.setShortcut(key)
            act.triggered.connect(lambda _c=False, f=fn: f())
            m.addAction(act)
        # Menü „Treiber“: geladene Treiber, Ordner für eigene Treiber
        m_drv = self.menuBar().addMenu(tr("Treiber"))
        a = m_drv.addAction(tr("Installierte Treiber …"))
        a.triggered.connect(self.show_drivers)
        a = m_drv.addAction(tr("Ordner für eigene Treiber öffnen …"))
        a.triggered.connect(self.open_driver_folder)
        # Menü „Sprache“ (Umschalten mit Neustart)
        from plc_i18n import fill_language_menu
        fill_language_menu(self.menuBar().addMenu(tr("Sprache")), self,
                           lambda: program_command("config", self.path) if self.path else program_command("config"))
        # Menü „Hilfe“: Bedienungsanleitung (F1) und Dialog „Über …“ (Version, Lizenz, Bibliotheken)
        from plc_about import add_help_menu
        add_help_menu(self)

    def _plc_help_topic(self, _widget):
        """Kontexthilfe der Steuerungstabelle: Abschnitt des Treibers in der aktuellen Zeile."""
        r = self.plc_table.currentRow()
        combo = self.plc_table.cellWidget(r, P_DRV) if r >= 0 else None
        return "Treiber {0} –…".format(combo.currentData()) if combo is not None and combo.currentData() else None

    def show_drivers(self):
        """Übersicht: geladene Treiber mit Bibliothekszustand, Ladefehler eigener Treiber, Ordner für Erweiterungen."""
        rows = []
        for ident, d in drivers().items():
            try:
                d.check_library()
                lib = "<span style='color:#27ae60'>✓</span>"
            except Exception as e:
                lib = "<span style='color:#c0392b'>✗ " + str(e).splitlines()[0][:120] + "</span>"
            rows.append(f"<tr><td><b>{ident}</b></td><td>{d.name}</td><td>{d.library or '–'}</td><td>{lib}</td></tr>")
        html = ("<table cellspacing=6><tr><th align=left>" + tr("Kürzel") + "</th><th align=left>" + tr("Treiber")
                + "</th><th align=left>" + tr("Bibliothek") + "</th><th></th></tr>" + "".join(rows) + "</table>")
        errs = load_errors()
        if errs:
            html += "<p><b>" + tr("Nicht geladen:") + "</b><br>" + "<br>".join(f"{m}: {e}" for m, e in errs) + "</p>"
        html += "<p>" + tr("Eigene Treiber (Python-Datei, Vorlage plc_treiber/_vorlage.py) in diesen Ordner legen; "
                           "sie werden beim nächsten Start geladen:") + "<br><code>{0}</code></p>".format(os.path.join(BASE_DIR, 'treiber'))
        box = QMessageBox(self)
        box.setWindowTitle(tr("Installierte Treiber"))
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(html)
        box.exec()

    def open_driver_folder(self):
        """Ordner für eigene Treiber (``<Datenordner>/treiber``) anlegen und öffnen; die Treibervorlage ``_vorlage.py``
        wird hineinkopiert, falls sie dort fehlt.
        """
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        folder = os.path.join(BASE_DIR, "treiber")
        os.makedirs(folder, exist_ok=True)
        tpl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plc_treiber", "_vorlage.py")
        tpl = tpl if os.path.exists(tpl) else os.path.join(getattr(sys, "_MEIPASS", ""), "plc_treiber", "_vorlage.py")
        target = os.path.join(folder, "_vorlage.py")
        if os.path.exists(tpl) and not os.path.exists(target):
            try:
                import shutil
                shutil.copy(tpl, target)
            except OSError:
                pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def update_title(self):
        """Fenstertitel: Projektname und Dateiname der Konfiguration."""
        proj = self.ed_project.text().strip() or tr("ohne Projektname")
        name = os.path.basename(self.path) if self.path else tr("neu, nicht gespeichert")
        self.setWindowTitle(tr("PLC Konfiguration – {0} – {1}").format(proj, name))

    # ---------------------------------------------------------------------------------------
    # Steuerungen (SPS)
    # ---------------------------------------------------------------------------------------
    def add_plc_row(self, p: Plc):
        """Eine Steuerung als Zeile an die Steuerungen-Tabelle anhängen."""
        t = self.plc_table
        r = t.rowCount()
        t.blockSignals(True)
        t.insertRow(r)
        t.setItem(r, P_NAME, QTableWidgetItem(p.name))
        # Treiber: Auswahl aller geladenen Treiber (unbekannte bleiben als eigener Eintrag sichtbar).
        drv = QComboBox()
        for ident, d in drivers().items():
            drv.addItem(d.name, ident)
        if drv.findData(p.driver) < 0:
            drv.addItem(get_driver(p.driver).name, p.driver)
        drv.setCurrentIndex(drv.findData(p.driver))
        drv.setToolTip(tr("Protokoll bzw. Steuerungsfamilie"))
        drv.currentIndexChanged.connect(lambda _i, w=drv: self.on_driver_changed(w))
        conn = QTableWidgetItem("")
        conn.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        conn.setData(ROLE_PARAMS, dict(p.params))
        conn.setToolTip(tr("Doppelklick oder „…“: Verbindungsparameter bearbeiten"))
        t.setItem(r, P_CONN, conn)
        btn = QPushButton("…")
        btn.setFixedWidth(30)
        btn.setToolTip(tr("Verbindungsparameter bearbeiten"))
        btn.clicked.connect(lambda _c=False, w=btn: self.edit_plc_params(self._plc_row_of(w, P_SET)))
        # Abtastintervall 10 ms ... 60 s; die tatsächlich erreichbare Rate hängt von Steuerung und Netz ab.
        iv = QSpinBox(); iv.setRange(10, 60000); iv.setSuffix(" ms"); iv.setValue(p.intervall_ms)
        for col, w in ((P_DRV, drv), (P_SET, btn), (P_INT, iv)):
            t.setCellWidget(r, col, w)
        on = QTableWidgetItem()
        on.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        on.setCheckState(Qt.CheckState.Checked if p.enabled else Qt.CheckState.Unchecked)
        t.setItem(r, P_ON, on)
        t.blockSignals(False)
        self._update_conn_text(r)
        self._fit_driver_column()

    def _fit_driver_column(self):
        """Spalte „Treiber“ so breit, dass die gewählten Treibernamen ganz lesbar sind (höchstens 420 Pixel); die
        Auswahlliste selbst zeigt alle Namen in voller Länge."""
        t = self.plc_table
        need = 160
        for r in range(t.rowCount()):
            combo = t.cellWidget(r, P_DRV)
            if combo is None:
                continue
            fm = combo.fontMetrics()
            need = max(need, fm.horizontalAdvance(combo.currentText()) + 48)
            combo.view().setMinimumWidth(max(fm.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())) + 32)
        t.setColumnWidth(P_DRV, min(need, 420))

    def _plc_row_of(self, widget, col):
        """Zeile der Steuerungen-Tabelle, in der das Widget ``widget`` in Spalte ``col`` steckt (-1 = nicht gefunden).

        Nötig, weil die Auswahllisten/Zahlenfelder der Tabelle nur sich selbst melden, nicht ihre Zeile.
        """
        for r in range(self.plc_table.rowCount()):
            if self.plc_table.cellWidget(r, col) is widget:
                return r
        return -1

    def _plc_of_table_row(self, r):
        """Zeile r der Steuerungen-Tabelle als Plc-Objekt (Parameter stehen als Datenrolle im Verbindungsfeld)."""
        t = self.plc_table
        return Plc(name=t.item(r, P_NAME).text().strip() or f"SPS {r + 1}",
                   driver=t.cellWidget(r, P_DRV).currentData(),
                   params=dict(t.item(r, P_CONN).data(ROLE_PARAMS) or {}),
                   intervall_ms=t.cellWidget(r, P_INT).value(),
                   enabled=t.item(r, P_ON).checkState() == Qt.CheckState.Checked)

    def _update_conn_text(self, r):
        """Kurzbeschreibung der Verbindung (z. B. IP, Rack/Slot) in Zeile r neu anzeigen, ohne Änderungssignale
        auszulösen.
        """
        p = self._plc_of_table_row(r)
        item = self.plc_table.item(r, P_CONN)
        self.plc_table.blockSignals(True)
        item.setText(p.summary())
        self.plc_table.blockSignals(False)

    def on_driver_changed(self, combo):
        """Anderer Treiber: Parameter auf dessen Vorgaben setzen (IP-Adresse bleibt), Typlisten der Variablen anpassen."""
        r = self._plc_row_of(combo, P_DRV)
        if r < 0:
            return
        d = get_driver(combo.currentData())
        old = dict(self.plc_table.item(r, P_CONN).data(ROLE_PARAMS) or {})
        new = d.default_params()
        if "ip" in new and old.get("ip"):
            new["ip"] = old["ip"]
        self.plc_table.item(r, P_CONN).setData(ROLE_PARAMS, new)
        self._update_conn_text(r)
        self._fit_driver_column()
        self.refresh_plc_combos()
        self.sync_block_drivers()
        self.refresh_tree()

    def edit_plc_params(self, r):
        """Dialog mit den Verbindungsparametern des Treibers für die Steuerung in Zeile r öffnen und das Ergebnis
        übernehmen.
        """
        if r < 0:
            return
        from plc_treiber.ui import PlcSettingsDialog
        p = self._plc_of_table_row(r)
        dlg = PlcSettingsDialog(self, p.name, get_driver(p.driver), p.params)
        if dlg.exec() and dlg.result is not None:
            self.plc_table.item(r, P_CONN).setData(ROLE_PARAMS, get_driver(p.driver).normalize_params(dlg.result))
            self._update_conn_text(r)

    def collect_plcs(self):
        """Steuerungen aus der Tabelle als Plc-Objekte (leere Namen werden zu „SPS n“)."""
        return [self._plc_of_table_row(r) for r in range(self.plc_table.rowCount())]

    def driver_of_plc(self, idx):
        """Treiber der Steuerung mit dem Index ``idx`` (auf den gültigen Bereich begrenzt)."""
        plcs = self.collect_plcs()
        return get_driver(plcs[min(max(idx, 0), len(plcs) - 1)].driver) if plcs else get_driver("s7")

    def sync_block_drivers(self):
        """Treiber der Blöcke an ihre Steuerung angleichen (bestimmt die Elementadressen)."""
        plcs = self.collect_plcs()
        for b in self.blocks:
            b.driver = plcs[min(max(b.plc, 0), len(plcs) - 1)].driver if plcs else "s7"

    def plc_names(self):
        """Namen aller Steuerungen (für die Auswahllisten der Variablen)."""
        return [p.name for p in self.collect_plcs()]

    def plc_at(self, idx):
        """Steuerung idx (Plc) – für Verbindungstest, Blocktest und Auswahldialog."""
        plcs = self.collect_plcs()
        return plcs[min(max(idx, 0), len(plcs) - 1)]

    def plc_of_row(self, r):
        """Index der Steuerung der Variablenzeile r."""
        return max(self.table.cellWidget(r, C_PLC).currentIndex(), 0)

    def refresh_plc_combos(self, vals=None):
        """Auswahllisten „Steuerung“ aller Variablenzeilen neu füllen (nach Umbenennen/Hinzufügen/Entfernen).
        vals: neue Indizes je Zeile; ohne Angabe bleiben die bisherigen erhalten."""
        names = self.plc_names()
        if vals is None:
            vals = [self.plc_of_row(r) for r in range(self.table.rowCount())]
        for r, i in enumerate(vals):
            cb = self.table.cellWidget(r, C_PLC)
            cb.blockSignals(True)
            cb.clear()
            cb.addItems(names)
            cb.setCurrentIndex(min(max(i, 0), len(names) - 1))
            cb.blockSignals(False)
            self.update_row_driver(r)
        if hasattr(self, "cb_filter_plc"):
            self._fill_filter_plcs()
            self.apply_var_filter()

    def on_plc_item_changed(self, item):
        """Name einer Steuerung geändert: Auswahllisten der Variablen und Blöcke aktualisieren."""
        if item.column() == P_NAME:
            self.refresh_plc_combos()

    def add_plc(self):
        """Neue Steuerung anhängen – mit dem Treiber der markierten bzw. letzten Steuerung."""
        n = self.plc_table.rowCount()
        # Neue Steuerung: Treiber wie die markierte bzw. letzte Steuerung
        r = self.plc_table.currentRow() if self.plc_table.currentRow() >= 0 else n - 1
        drv = self.plc_table.cellWidget(r, P_DRV).currentData() if r >= 0 else "s7"
        self.add_plc_row(Plc(name=f"SPS {n + 1}", driver=drv))
        self.refresh_plc_combos()

    def scan_network(self):
        """Netzwerk nach Steuerungen durchsuchen (plc_netscan_dialog) und die gewählten als Steuerungen anhängen."""
        from plc_netscan_dialog import NetScanDialog
        plcs = self.collect_plcs()
        known = {str(p.params.get("ip", "")) for p in plcs}
        known |= {str(p.params.get("endpoint", "")).split("//")[-1].split(":")[0] for p in plcs}
        dlg = NetScanDialog(self, known)
        if not dlg.exec() or not dlg.result:
            return
        names = {p.name for p in plcs}
        for f in dlg.result:
            try:
                drv = get_driver(f.driver)
            except Exception:
                continue
            base = (f.device or f"{f.driver.upper()} {f.ip}").strip()
            name, k = base, 2
            while name in names:
                name, k = f"{base} ({k})", k + 1
            names.add(name)
            self.add_plc_row(Plc(name=name, driver=f.driver, params=drv.normalize_params(f.params)))
        self.refresh_plc_combos()
        self.statusBar().showMessage(tr("{0} Steuerungen aus der Netzwerksuche übernommen").format(len(dlg.result)), 8000)

    def remove_plc(self):
        """Markierte Steuerung entfernen. Variablen und Blöcke, die zu ihr gehörten, wandern zur ersten Steuerung."""
        r = self.plc_table.currentRow()
        if r < 0 or self.plc_table.rowCount() < 2:
            QMessageBox.information(self, tr("Steuerung entfernen"),
                                    tr("Bitte eine Steuerung markieren; mindestens eine muss bleiben."))
            return

        def fn(old):
            """Neuer Index einer Steuerung nach dem Entfernen von Zeile r (die entfernte wird zu 0, dahinter rücken alle
            auf).
            """
            return 0 if old == r else (old - 1 if old > r else old)
        vals = [fn(self.plc_of_row(k)) for k in range(self.table.rowCount())]
        for b in self.blocks:
            b.plc = fn(b.plc)
        self.plc_table.removeRow(r)
        self.refresh_plc_combos(vals)
        self.sync_block_drivers()
        self.statusBar().showMessage(tr("Steuerung entfernt – ihre Variablen und Blöcke gehören jetzt zur ersten Steuerung."), 8000)

    def _build_trigger_tab(self):
        """Reiter „Trigger & Ereignisse“: Trigger bearbeiten, Ereignisdatei wählen, Ereignisprotokoll anzeigen."""
        self.lbl_triggers = QLabel("")
        btn_edit = QPushButton(tr("Trigger bearbeiten …"))
        btn_edit.setToolTip(tr("Bedingungen festlegen, bei denen ein Eintrag ins Ereignisprotokoll geschrieben wird"))
        btn_edit.clicked.connect(self.edit_triggers)
        btn_view = QPushButton(tr("Ereignisprotokoll anzeigen …"))
        btn_view.setToolTip(tr("Ereignisse anzeigen und quittieren"))
        btn_view.clicked.connect(self.show_events)
        self.ed_event_file = QLineEdit()
        self.ed_event_file.setPlaceholderText(tr("leer = <CSV-Ordner>/<CSV-Name>_ereignisse.csv"))
        self.ed_event_file.setToolTip(tr("Textdatei (CSV, Semikolon) mit allen Ereignissen und Quittierungen"))
        btn_file = QPushButton("…")
        btn_file.setFixedWidth(30)

        def pick():
            """Ereignisdatei wählen (Speichern-Dialog ohne Überschreib-Rückfrage: die Datei wird nur fortgeschrieben).
            """
            start = self.ed_event_file.text() or event_log_path(self.collect_conn())
            p, _ = QFileDialog.getSaveFileName(self, tr("Ereignisdatei"), start, tr("Ereignisprotokoll (*.csv)"),
                                               options=QFileDialog.Option.DontConfirmOverwrite)
            if p:
                self.ed_event_file.setText(p if p.lower().endswith(".csv") else p + tr(".csv"))
        btn_file.clicked.connect(pick)
        file_row = QHBoxLayout()
        file_row.addWidget(self.ed_event_file)
        file_row.addWidget(btn_file)
        form = QFormLayout()
        form.addRow(tr("Trigger:"), self.lbl_triggers)
        row = QHBoxLayout()
        row.addWidget(btn_edit)
        row.addWidget(btn_view)
        row.addStretch(1)
        form.addRow("", row)
        form.addRow(tr("Ereignisdatei:"), file_row)
        self.notify_settings = {}
        btn_notify = QPushButton(tr("Benachrichtigungen …"))
        btn_notify.setToolTip(tr("Bei Ereignissen E-Mail, Teams-/Slack-Nachricht oder Push aufs Handy (ntfy, Telegram)"))
        btn_notify.clicked.connect(self.edit_notify)
        self.lbl_notify = QLabel("")
        notify_row = QHBoxLayout()
        notify_row.addWidget(btn_notify)
        notify_row.addWidget(self.lbl_notify, 1)
        form.addRow(tr("Melden:"), notify_row)
        info = QLabel(tr("Ein Trigger schreibt einen Eintrag mit Zeitstempel ins Ereignisprotokoll, sobald seine Bedingung "
                      "erfüllt ist (z. B. <code>{Temperatur} &gt; 80</code>). Offene Ereignisse zeigt der Logger in der "
                      "Statusleiste an; quittiert wird im Ereignis-Viewer."))
        info.setWordWrap(True)
        info.setStyleSheet("color:#555")
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.addLayout(form, 1)
        lay.addSpacing(30)
        lay.addWidget(info, 1)
        return w

    def _build_report_tab(self):
        """Reiter „Berichte (PDF)“: automatische Berichte je Schicht, Tag, Woche oder Monat."""
        from plc_report import PERIODS
        self.chk_report = QCheckBox(tr("PDF-Bericht automatisch erstellen"))
        self.chk_report.setToolTip(tr("Am Ende jedes Zeitraums: Kennwerte, Verlauf aller Diagramme und Ereignisse; "
                                      "beim Stoppen ein Teilbericht"))
        self.cb_report_period = QComboBox()
        for key, text in PERIODS.items():
            self.cb_report_period.addItem(tr(text), key)
        self.ed_report_shifts = QLineEdit()
        self.ed_report_shifts.setPlaceholderText("06:00,14:00,22:00")
        self.ed_report_shifts.setToolTip(tr("Beginn der Schichten (Uhrzeiten, durch Komma getrennt)"))
        self.ed_report_start = QLineEdit()
        self.ed_report_start.setPlaceholderText("00:00")
        self.ed_report_start.setToolTip(tr("Uhrzeit, zu der Tag, Woche (Montag) und Monat beginnen, z. B. 06:00"))
        self.ed_report_dir = QLineEdit()
        self.ed_report_dir.setPlaceholderText("berichte")
        btn = QPushButton("…")
        btn.setFixedWidth(30)
        btn.clicked.connect(lambda: self.ed_report_dir.setText(
            QFileDialog.getExistingDirectory(self, tr("Ordner für Berichte"), self.ed_report_dir.text() or BASE_DIR)
            or self.ed_report_dir.text()))
        dir_row = QHBoxLayout(); dir_row.addWidget(self.ed_report_dir); dir_row.addWidget(btn)
        self.cb_report_period.currentIndexChanged.connect(lambda _i: self._update_report_fields())
        self.chk_report.toggled.connect(lambda _on: self._update_report_fields())
        form = QFormLayout()
        form.addRow("", self.chk_report)
        form.addRow(tr("Zeitraum:"), self.cb_report_period)
        form.addRow(tr("Schichtbeginne:"), self.ed_report_shifts)
        form.addRow(tr("Tagesbeginn:"), self.ed_report_start)
        form2 = QFormLayout()
        form2.addRow(tr("Ordner:"), dir_row)
        info = QLabel(tr("Der Bericht enthält Minimum, Maximum, Mittelwert und Streuung je Variable, den Verlauf jedes "
                         "Diagramms und die Ereignisse des Zeitraums. Von Hand: Logger › Analyse › PDF-Bericht."))
        info.setWordWrap(True)
        info.setStyleSheet("color:#555")
        form2.addRow(info)
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.addLayout(form, 1)
        lay.addSpacing(30)
        lay.addLayout(form2, 1)
        return w

    def _update_report_fields(self):
        """Felder der PDF-Berichte passend zu „aktiv“ und Zeitraum freigeben (Schichtzeiten nur bei „Schicht“)."""
        on = self.chk_report.isChecked()
        kind = self.cb_report_period.currentData()
        self.cb_report_period.setEnabled(on)
        self.ed_report_shifts.setEnabled(on and kind == "schicht")
        self.ed_report_start.setEnabled(on and kind != "schicht")
        self.ed_report_dir.setEnabled(on)

    def _update_trigger_summary(self):
        """Zusammenfassung der Trigger neben dem Knopf (Anzahl, aktive, erste Namen)."""
        n = len(self.triggers)
        active = sum(1 for t in self.triggers if t.aktiv)
        if not n:
            self.lbl_triggers.setText(tr("keine Trigger angelegt"))
        else:
            names = ", ".join(t.name for t in self.triggers[:6]) + (" …" if n > 6 else "")
            self.lbl_triggers.setText(tr("{0} Trigger, davon {1} aktiv ({2})").format(n, active, names))

    def edit_triggers(self):
        """Trigger-Editor öffnen; die Trigger werden mit der Konfiguration gespeichert und gelten ab dem nächsten Start
        der Aufzeichnung.
        """
        from plc_trigger_dialog import TriggerEditor
        dlg = TriggerEditor(self, self.triggers, self.available_names())
        if dlg.exec():
            self.triggers = dlg.result_triggers
            self._update_trigger_summary()
            self.statusBar().showMessage(tr("Trigger geändert – wirksam nach dem Speichern und Neustart der Aufzeichnung."),
                                         8000)

    def show_events(self):
        """Ereignis-Viewer für die Ereignisdatei der aktuellen Einstellungen öffnen."""
        from plc_event_viewer import EventViewer
        dlg = EventViewer(EventLog(event_log_path(self.collect_conn())), self)
        dlg.exec()

    def _build_db_tab(self):
        """Reiter „Datenbank“: Aufzeichnung zusätzlich (oder statt CSV) in SQLite, MariaDB, TimescaleDB oder QuestDB."""
        self.cb_db = QComboBox()
        for key, text in DB_TYPES.items():
            self.cb_db.addItem(tr(text), key)
        self.cb_db.currentIndexChanged.connect(lambda _i: self._update_db_fields())
        self.ed_db_host = QLineEdit()
        self.sp_db_port = QSpinBox(); self.sp_db_port.setRange(0, 65535); self.sp_db_port.setSpecialValueText(tr("Standard"))
        self.sp_db_port.setToolTip(tr("0 = Standard (MariaDB 3306, PostgreSQL/TimescaleDB 5432, QuestDB 9000, "
                                      "InfluxDB 3 8181, VictoriaMetrics 8428)"))
        self.ed_db_host.setToolTip(tr("Rechnername oder IP-Adresse; bei QuestDB, InfluxDB und VictoriaMetrics auch "
                                      "eine URL (z. B. https://server:8181)"))
        self.ed_db_name = QLineEdit()
        self.ed_db_user = QLineEdit()
        self.ed_db_pw = QLineEdit(); self.ed_db_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_db_pw.setToolTip(tr("Wird im Klartext in der Konfigurationsdatei gespeichert"))
        self.ed_db_table = QLineEdit()
        self.ed_db_table.setToolTip(tr("Tabellenname (Buchstaben, Ziffern, _); wird bei Bedarf angelegt"))
        self.ed_db_file = QLineEdit()
        self.ed_db_file.setToolTip(tr("SQLite-Datei; relativ = im Datenordner des Programms"))
        btn_file = QPushButton("…"); btn_file.setFixedWidth(30)

        def pick_db_file():
            """SQLite-Datei wählen oder neu benennen."""
            path, _ = QFileDialog.getSaveFileName(self, tr("SQLite-Datenbank"), self.ed_db_file.text() or BASE_DIR,
                                                  tr("SQLite (*.db *.sqlite *.sqlite3);;Alle Dateien (*)"))
            if path:
                self.ed_db_file.setText(path)
        btn_file.clicked.connect(pick_db_file)
        file_row = QWidget(); fr = QHBoxLayout(file_row); fr.setContentsMargins(0, 0, 0, 0)
        fr.addWidget(self.ed_db_file); fr.addWidget(btn_file)
        self.chk_db_changes = QCheckBox(tr("Nur Änderungen schreiben (spätestens jede Minute)"))
        self.chk_db_changes.setToolTip(tr("Spart Platz: ein Wert wird nur geschrieben, wenn er sich geändert hat"))
        self.sp_db_clean_days = self._days_spin(tr("Werte löschen, die älter sind (0 = nie). TimescaleDB: ganze "
                                                   "Zeitabschnitte, QuestDB: ganze Tage. InfluxDB 3 und VictoriaMetrics: "
                                                   "Aufbewahrungsdauer am Server einstellen"))
        self.sp_db_clean_mb = self._mb_spin(tr("Nur SQLite: belegen die Werte mehr Platz, werden die ältesten Tage "
                                               "gelöscht (0 = unbegrenzt). Die Datei schrumpft nicht, wächst aber "
                                               "nicht weiter"))
        btn_test = QPushButton(tr("Datenbank testen"))
        btn_test.setToolTip(tr("Verbindung prüfen und die Tabelle anlegen"))
        btn_test.clicked.connect(self.test_database)
        f1 = QFormLayout()
        f1.addRow(tr("Datenbank:"), self.cb_db)
        f1.addRow(tr("Server / Port:"), self._hbox(self.ed_db_host, self.sp_db_port))
        f1.addRow(tr("Datenbankname:"), self.ed_db_name)
        f1.addRow(tr("SQLite-Datei:"), file_row)
        f2 = QFormLayout()
        f2.addRow(tr("Benutzer / Passwort:"), self._hbox(self.ed_db_user, self.ed_db_pw))
        f2.addRow(tr("Tabelle:"), self.ed_db_table)
        f2.addRow("", self.chk_db_changes)
        f2.addRow(tr("Löschen nach:"), self.sp_db_clean_days)
        f2.addRow(tr("Höchstens belegen:"), self.sp_db_clean_mb)
        f2.addRow("", btn_test)
        w = QWidget()
        lay = QHBoxLayout(w); lay.addLayout(f1, 1); lay.addSpacing(30); lay.addLayout(f2, 1)
        self._db_server_widgets = [self.ed_db_host, self.sp_db_port, self.ed_db_name, self.ed_db_user, self.ed_db_pw]
        self._db_widgets = self._db_server_widgets + [self.ed_db_table, self.ed_db_file, btn_file,
                                                      self.chk_db_changes, self.sp_db_clean_days, btn_test]
        return w

    @staticmethod
    def _days_spin(tip):
        """Eingabe „Löschen nach … Tagen“ (0 = nie)."""
        sp = QSpinBox()
        sp.setRange(0, 36500)
        sp.setSuffix(tr(" Tagen"))
        sp.setSpecialValueText(tr("nie"))
        sp.setToolTip(tip)
        return sp

    @staticmethod
    def _mb_spin(tip):
        """Eingabe „Höchstens … MB“ (0 = unbegrenzt)."""
        sp = QSpinBox()
        sp.setRange(0, 100_000_000)
        sp.setSingleStep(100)
        sp.setSuffix(" MB")
        sp.setSpecialValueText(tr("unbegrenzt"))
        sp.setToolTip(tip)
        return sp

    def _update_db_fields(self):
        """Felder je nach Datenbanktyp freigeben (Server-Felder für MariaDB/TimescaleDB/QuestDB, Datei für SQLite)."""
        typ = self.cb_db.currentData() or ""
        for wdg in self._db_widgets:
            wdg.setEnabled(bool(typ))
        for wdg in self._db_server_widgets:
            wdg.setEnabled(typ in ("mariadb", "timescale") + HTTP_TYPES)
        # QuestDB, VictoriaMetrics und Prometheus: eine Datenbank je Server
        self.ed_db_name.setEnabled(typ in ("mariadb", "timescale", "influxdb3"))
        plain = tr("Wird im Klartext in der Konfigurationsdatei gespeichert")
        self.ed_db_pw.setToolTip(tr("Ohne Benutzer gilt das Passwort als Token (InfluxDB 3, QuestDB Enterprise, "
                                    "VictoriaMetrics hinter vmauth, Prometheus hinter einem Proxy)") + "\n" + plain
                                 if typ in HTTP_TYPES else plain)
        self.ed_db_table.setToolTip(tr("VictoriaMetrics/Prometheus: Name der Metrik = Tabelle + _wert") + "\n"
                                    + tr("Tabellenname (Buchstaben, Ziffern, _); wird bei Bedarf angelegt")
                                    if typ in METRIC_TYPES
                                    else tr("Tabellenname (Buchstaben, Ziffern, _); wird bei Bedarf angelegt"))
        if typ == "prometheus":
            self.cb_db.setToolTip(tr("Prometheus nimmt Werte per Remote Write an: den Server mit "
                                     "--web.enable-remote-write-receiver starten. Werte älter als etwa eine Stunde "
                                     "lehnt Prometheus ab (out_of_order_time_window)."))
        else:
            self.cb_db.setToolTip("")
        self.ed_db_file.setEnabled(typ == "sqlite")
        self.sp_db_clean_mb.setEnabled(typ == "sqlite")
        self.sp_db_clean_days.setEnabled(typ not in ("", "influxdb3") + METRIC_TYPES)
        self.sp_db_port.setSpecialValueText(tr("Standard ({0})").format(DEFAULT_PORTS[typ]) if typ in DEFAULT_PORTS else tr("Standard"))

    def test_database(self):
        """Verbindung zur gewählten Datenbank prüfen und die Tabelle anlegen."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            text = test_db(self.collect_conn())
        except ImportError as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, tr("Datenbank"), tr('Der Datenbanktreiber fehlt:\n{0}\n\nMariaDB: pip install PyMySQL\nTimescaleDB/PostgreSQL: pip install "psycopg[binary]"').format(e))
            return
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, tr("Datenbank"), tr("Verbindung fehlgeschlagen:\n{0}").format(e))
            return
        QApplication.restoreOverrideCursor()
        QMessageBox.information(self, tr("Datenbank"), text)

    def _file_row(self, edit, title, filt=None):
        """Zeile mit Eingabefeld und '…'-Knopf zur Auswahl einer Datei (Standard: Bilddatei für Logo/Icon)."""
        btn = QPushButton("…")
        btn.setFixedWidth(30)

        # Dateiauswahl für ein Eingabefeld (Logo/Icon): Dialog öffnen und den gewählten Pfad eintragen.
        def pick():
            p, _ = QFileDialog.getOpenFileName(
                self, title, edit.text() or BASE_DIR,
                filt or tr("Bilder (*.png *.svg *.ico *.jpg *.jpeg *.bmp);;Alle Dateien (*)"))
            if p:
                edit.setText(p)
        btn.clicked.connect(pick)
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(edit)
        h.addWidget(btn)
        return w

    @staticmethod
    def _hbox(*widgets):
        """Mehrere Widgets nebeneinander in einem Container (ohne Rand)."""
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0)
        for x in widgets:
            h.addWidget(x)
        return w

    # ---------------------------------------------------------------------------------------
    # Struktur-Hilfen: Diagramme und Achsen als flache Liste, Zuordnung der Variablen
    # ---------------------------------------------------------------------------------------
    # ---------- Struktur-Hilfen ----------
    # Alle wählbaren Ziele als Liste von (Diagramm-Index, Achsen-Index); die Reihenfolge entspricht den Auswahllisten.
    def flat(self):
        return [(ci, ai) for ci, c in enumerate(self.charts) for ai, _ in enumerate(c.axes)]

    # Beschriftungen zu flat(): 'Diagramm › Achse'.
    def flat_labels(self):
        return [f"{c.name} › {a.name}" for c in self.charts for a in c.axes]

    @staticmethod
    # Text im Baum: Achsenname und Skalierung ('Auto' oder 'min … max').
    def axis_label(a: Axis):
        """Text einer Y-Achse im Baum: Name und Skalierung (Auto bzw. min … max)."""
        return f"{a.name} – " + (tr("Auto") if a.auto else f"{a.y_min:g} … {a.y_max:g}")

    # Ziel (Diagramm, Achse) der Tabellenzeile r aus der Auswahlliste.
    def assign_of_row(self, r):
        idx = self.table.cellWidget(r, C_AXIS).currentIndex()
        flat = self.flat()
        return flat[idx] if 0 <= idx < len(flat) else (0, 0)

    # Zuordnungen aller Variablen (in Tabellenreihenfolge) gefolgt von denen der Blöcke. Wird vor jeder Strukturänderung
    # gesichert und danach mit set_assignments() wieder gesetzt.
    def target_slots(self):
        """Alle Element-Ziele der Blöcke als Liste (Blockindex, Elementindex) in fester Reihenfolge."""
        return [(bi, idx) for bi, b in enumerate(self.blocks) for idx in sorted(b.targets)]

    def assignments(self):
        """Alle Zuordnungen (Diagramm, Achse) sichern: Variablen in Tabellenreihenfolge, dann Blöcke, dann abweichende
        Ziele einzelner Blockelemente – Gegenstück zu ``set_assignments``.
        """
        return ([self.assign_of_row(r) for r in range(self.table.rowCount())]
                + [(b.chart, b.axis) for b in self.blocks]
                + [self.blocks[bi].targets[idx] for bi, idx in self.target_slots()])

    def set_assignments(self, assigns):
        """Auswahllisten neu füllen und die Zuordnungen (Diagramm, Achse) wiederherstellen."""
        labels, flat = self.flat_labels(), self.flat()
        n = self.table.rowCount()
        # Blöcke folgen den Tabellenzeilen in der Liste; ein Ziel, das es nicht mehr gibt, fällt auf Diagramm 1 / Achse 1 zurück.
        nb = len(self.blocks)
        slots = self.target_slots()
        for b, key in zip(self.blocks, assigns[n:n + nb]):      # Blöcke folgen den Tabellenzeilen
            b.chart, b.axis = key if key in flat else (0, 0)
        # Ziele einzelner Block-Elemente: ungültige oder dem Block gleiche Ziele entfallen.
        for (bi, idx), key in zip(slots, assigns[n + nb:]):
            b = self.blocks[bi]
            if key in flat and key != (b.chart, b.axis):
                b.targets[idx] = key
            else:
                b.targets.pop(idx, None)
        # Variablenzeilen: Auswahlliste neu füllen (Texte können sich geändert haben) und Auswahl wiederherstellen.
        for r, key in enumerate(assigns[:n]):
            cb = self.table.cellWidget(r, C_AXIS)
            cb.blockSignals(True)
            cb.clear()
            cb.addItems(labels)
            cb.setCurrentIndex(flat.index(key) if key in flat else 0)
            cb.blockSignals(False)

    # Tabellenzeile zur Variablen-ID suchen (-1: Zeile existiert nicht mehr).
    def row_of_uid(self, uid):
        for r in range(self.table.rowCount()):
            if self.table.item(r, C_NAME).data(ROLE_UID) == uid:
                return r
        return -1

    # ---------------------------------------------------------------------------------------
    # Zuordnungsbaum
    # ---------------------------------------------------------------------------------------
    # ---------- Baum ----------
    def refresh_tree(self):
        # Baum komplett neu aufbauen: Diagramme > Achsen > Variablen/Blöcke. Die Auswahl (Diagramm/Achse) wird gemerkt
        # und danach wiederhergestellt; Signale ruhen während des Aufbaus.
        key = self.prop_key
        self.tree.blockSignals(True)
        self.tree.clear()
        axis_items = {}
        chart_items = []
        # Ebene 1: Diagramme (mit Hinweis auf die Seite, falls eine gesetzt ist). Sie nehmen abgelegte Variablen entgegen.
        for ci, c in enumerate(self.charts):
            it = QTreeWidgetItem([c.name + (f"   · Seite: {c.page}" if c.page else "")])
            it.setData(0, ROLE_KIND, "chart"); it.setData(0, ROLE_CI, ci)
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                        | Qt.ItemFlag.ItemIsDropEnabled)
            self.tree.addTopLevelItem(it)
            chart_items.append(it)
            # Ebene 2: Y-Achsen des Diagramms (nehmen ebenfalls abgelegte Variablen entgegen).
            for ai, a in enumerate(c.axes):
                ax = QTreeWidgetItem([self.axis_label(a)])
                ax.setData(0, ROLE_KIND, "axis"); ax.setData(0, ROLE_CI, ci); ax.setData(0, ROLE_AI, ai)
                ax.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                            | Qt.ItemFlag.ItemIsDropEnabled)
                it.addChild(ax)
                axis_items[(ci, ai)] = ax
        # Ebene 3: Variablen aus der Tabelle, unterhalb der Achse, der sie zugeordnet sind (ziehbar und als Ziel zulässig).
        for r in range(self.table.rowCount()):
            parent = axis_items.get(self.assign_of_row(r)) or axis_items[(0, 0)]
            name_item = self.table.item(r, C_NAME)
            child = QTreeWidgetItem([name_item.text()])
            child.setData(0, ROLE_KIND, "var")
            child.setData(0, ROLE_UID, name_item.data(ROLE_UID))
            child.setIcon(0, swatch(self.table.cellWidget(r, C_COLOR).property("color")))
            child.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                           | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled)
            parent.addChild(child)
        # Blöcke erscheinen als eine Zeile unter ihrer Achse (nur Anzeige, nicht ziehbar).
        for bi, b in enumerate(self.blocks):       # Blöcke (nur Anzeige)
            parent = axis_items.get((b.chart, b.axis)) or axis_items[(0, 0)]
            extra = tr(" ({0} in anderen Diagrammen)").format(len(b.targets)) if b.targets else ""
            if b.ring:
                extra = tr(", Ringpuffer {0} Datensätze").format(b.ring) + extra
            it = QTreeWidgetItem([f"▦ Block {b.name}: {b.count} × {b.dtype}{extra}"])
            it.setData(0, ROLE_KIND, "block")
            it.setData(0, ROLE_UID, bi)
            it.setIcon(0, swatch(b.color))
            it.setToolTip(0, b.address_range())
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            parent.addChild(it)
            # Elemente mit eigenem Ziel erscheinen zusätzlich unter der Achse, in der sie dargestellt werden.
            groups = {}
            # (eigene Namen – „key“ ist oben die gemerkte Auswahl und wird unten noch gebraucht)
            for idx, target in sorted(b.targets.items()):
                groups.setdefault(target, []).append(idx)
            for target, idxs in groups.items():
                p2 = axis_items.get(target)
                if p2 is None:
                    continue
                shown = ", ".join(f"[{i}]" for i in idxs[:8]) + (" …" if len(idxs) > 8 else "")
                part = QTreeWidgetItem([f"▦ Block {b.name}: Elemente {shown}"])
                part.setData(0, ROLE_KIND, "blockpart")
                part.setData(0, ROLE_UID, bi)
                part.setIcon(0, swatch(b.color))
                part.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                p2.addChild(part)
        self.tree.expandAll()
        # Auswahl (Diagramm/Achse) wiederherstellen, damit das Eigenschaftenfeld nicht leer wird.
        if key:  # Auswahl (Diagramm/Achse) wiederherstellen
            kind, ci, ai = key
            sel = chart_items[ci] if kind == "chart" else axis_items.get((ci, ai))
            if sel is not None:
                sel.setSelected(True)
        self.tree.blockSignals(False)

    # Auswahl im Baum geändert: merken, ob ein Diagramm oder eine Achse gewählt ist, und die Eigenschaftenfelder laden.
    def on_tree_select(self):
        items = self.tree.selectedItems()
        it = items[0] if items else None
        kind = it.data(0, ROLE_KIND) if it else None
        if kind == "chart":
            self.prop_key = ("chart", it.data(0, ROLE_CI), 0)
        elif kind == "axis":
            self.prop_key = ("axis", it.data(0, ROLE_CI), it.data(0, ROLE_AI))
        else:
            self.prop_key = None
        self.load_props()

    # Variablen wurden auf ein Ziel gezogen: Zuordnung in die Tabelle schreiben (Auswahllisten sind die Datenquelle).
    def on_moved(self, uids, ci, ai):
        flat = self.flat()
        for uid in uids:
            r = self.row_of_uid(uid)
            if r >= 0 and (ci, ai) in flat:
                cb = self.table.cellWidget(r, C_AXIS)
                cb.blockSignals(True)
                cb.setCurrentIndex(flat.index((ci, ai)))
                cb.blockSignals(False)
        # Baum erst nach Ende des Drag-Vorgangs neu aufbauen (nicht innerhalb des Ablegen-Ereignisses).
        QTimer.singleShot(30, self.refresh_tree)  # erst nach Ende des Drag-Vorgangs neu aufbauen

    # ---------------------------------------------------------------------------------------
    # Eigenschaften der Auswahl (Name, Seite, Skalierung)
    # ---------------------------------------------------------------------------------------
    # ---------- Eigenschaften ----------
    # Eigenschaftenfelder mit den Werten des ausgewählten Diagramms/der Y-Achse füllen (und ein-/ausschalten).
    def load_props(self):
        self._loading = True
        k = self.prop_key
        # Y-Achsen-Felder (Auto/min/max) sind nur bei einer Y-Achse bedienbar, min/max nur ohne Auto-Skalierung.
        is_axis = bool(k and k[0] == "axis")
        auto = True
        self.ed_page.setText("")
        if k is None:
            self.ed_name.setText("")
        elif k[0] == "chart":
            self.ed_name.setText(self.charts[k[1]].name)
            self.ed_page.setText(self.charts[k[1]].page)
        else:
            a = self.charts[k[1]].axes[k[2]]
            self.ed_name.setText(a.name)
            self.chk_auto.setChecked(a.auto)
            self.sp_min.setValue(a.y_min)
            self.sp_max.setValue(a.y_max)
            auto = a.auto
        self.ed_name.setEnabled(k is not None)
        self.ed_page.setEnabled(bool(k and k[0] == "chart"))
        is_chart = bool(k and k[0] == "chart")
        self.chk_pid.setChecked(is_chart and self.charts[k[1]].pid)
        self.chk_pid.setEnabled(is_chart)
        self._update_pid_label()
        self.chk_auto.setEnabled(is_axis)
        self.sp_min.setEnabled(is_axis and not auto)
        self.sp_max.setEnabled(is_axis and not auto)
        self._loading = False

    # ---- PID-Regler-Optimierung des ausgewählten Diagramms
    def _pid_chart(self):
        k = self.prop_key
        return self.charts[k[1]] if k and k[0] == "chart" else None

    def _update_pid_label(self):
        """Knopf und Kurztext der PID-Optimierung für das gewählte Diagramm aktualisieren."""
        c = self._pid_chart()
        on = bool(c and c.pid)
        self.btn_pid.setEnabled(on)
        if on and c.pid_iw and c.pid_stw:
            self.lbl_pid.setText(tr("{0}: Ist {1}, Stell {2}").format(c.pid_typ, c.pid_iw, c.pid_stw)
                                 + (tr(", Soll {0}").format(c.pid_sw) if c.pid_sw else ""))
        else:
            self.lbl_pid.setText("")

    def on_pid_toggled(self, on):
        """PID-Optimierung für das gewählte Diagramm ein-/ausschalten; ohne festgelegte Variablen öffnet sich zuerst der
        Einstellungsdialog (Abbrechen schaltet wieder aus).
        """
        c = self._pid_chart()
        if self._loading or c is None:
            return
        c.pid = on
        if on and not (c.pid_iw and c.pid_stw) and not self.edit_pid():
            c.pid = False                               # Einstellungen abgebrochen: wieder aus
            self.chk_pid.blockSignals(True)
            self.chk_pid.setChecked(False)
            self.chk_pid.blockSignals(False)
        self._update_pid_label()

    def edit_pid(self):
        """Soll-/Ist-/Stellwert und Reglertyp des Diagramms festlegen. Rückgabe: True bei OK."""
        c = self._pid_chart()
        if c is None:
            return False
        from plc_pid_dialog import PidSetupDialog
        ci = self.prop_key[1]
        in_chart = [v.name for v in self.collect() if v.chart == ci]
        ok = bool(PidSetupDialog(self, c, in_chart, self.available_names()).exec())
        self._update_pid_label()
        return ok

    # Eingabe aus den Feldern in das Datenmodell (self.charts) übernehmen.
    def apply_props(self, *_):
        if self._loading or self.prop_key is None:
            return
        kind, ci, ai = self.prop_key
        name = self.ed_name.text().strip()
        if kind == "chart":
            self.charts[ci].name = name or f"Diagramm {ci + 1}"
            self.charts[ci].page = self.ed_page.text().strip()
        else:
            a = self.charts[ci].axes[ai]
            a.name = name or f"Achse {ai + 1}"
            a.auto = self.chk_auto.isChecked()
            a.y_min = self.sp_min.value()
            a.y_max = self.sp_max.value()
            self.sp_min.setEnabled(not a.auto)
            self.sp_max.setEnabled(not a.auto)
        self.set_assignments(self.assignments())  # Texte der Auswahllisten aktualisieren
        self.refresh_tree()

    # Diagramm, in das eine neue Y-Achse eingefügt werden soll (Auswahl; sonst das letzte Diagramm).
    def selected_chart_index(self):
        items = self.tree.selectedItems()
        if not items:
            return len(self.charts) - 1
        it = items[0]
        if it.data(0, ROLE_KIND) in ("var", "block", "blockpart"):
            it = it.parent().parent()
        return it.data(0, ROLE_CI)

    # Neues Diagramm mit einer Y-Achse anhängen. Zuordnungen vorher sichern und danach neu setzen.
    def add_chart(self):
        assigns = self.assignments()
        self.charts.append(Chart(name=f"Diagramm {len(self.charts) + 1}", axes=[Axis()]))
        self.set_assignments(assigns)
        self.refresh_tree()

    # Neue Y-Achse im ausgewählten Diagramm anlegen.
    def add_axis(self):
        assigns = self.assignments()
        c = self.charts[self.selected_chart_index()]
        c.axes.append(Axis(name=f"Achse {len(c.axes) + 1}"))
        self.set_assignments(assigns)
        self.refresh_tree()

    # Auswahl entfernen: Block, Variable, Y-Achse oder Diagramm.
    def remove_selected(self):
        items = self.tree.selectedItems()
        if not items:
            return
        it = items[0]
        kind = it.data(0, ROLE_KIND)
        if kind == "blockpart":        # Teil eines Blocks: über den Blockeditor ändern
            self.statusBar().showMessage(tr("Zuordnung einzelner Block-Elemente: „Blöcke (Blocklesemodus)…“."), 6000)
            return
        if kind == "block":
            bi = it.data(0, ROLE_UID)
            if 0 <= bi < len(self.blocks):
                del self.blocks[bi]
            self.refresh_tree()
            return
        if kind == "var":
            r = self.row_of_uid(it.data(0, ROLE_UID))
            if r >= 0:
                self.table.removeRow(r)
            self.refresh_tree()
            return
        # Diagramm/Achse: Zuordnungen betroffener Variablen und Blöcke verschieben (entfernte Achse -> erste Achse des Diagramms;
        # entferntes Diagramm -> Diagramm 1) und Indizes nachfolgender Achsen/Diagramme um 1 verringern.
        assigns = self.assignments()
        ci = it.data(0, ROLE_CI)
        if kind == "chart":
            # Das letzte Diagramm und die letzte Achse eines Diagramms können nicht entfernt werden.
            if len(self.charts) < 2:
                return
            new = [(0, 0) if c == ci else ((c - 1, a) if c > ci else (c, a)) for c, a in assigns]
            del self.charts[ci]
        else:
            ai = it.data(0, ROLE_AI)
            if len(self.charts[ci].axes) < 2:
                return
            new = []
            for c, a in assigns:
                if c == ci:
                    a = 0 if a == ai else (a - 1 if a > ai else a)
                new.append((c, a))
            del self.charts[ci].axes[ai]
        self.prop_key = None
        self.set_assignments(new)
        self.load_props()
        self.refresh_tree()

    # ---------------------------------------------------------------------------------------
    # Variablentabelle
    # ---------------------------------------------------------------------------------------
    # ---------- Variablen ----------
    def add_row(self, v: Variable = None, refresh=True):
        """Neue Variable als Zeile an die Tabelle anhängen. v=None: Standardvariable; refresh=False beim Laden vieler Zeilen
        (der Baum wird dann einmal am Ende aufgebaut).
        """
        r = self.table.rowCount()
        # Neue Zeile ohne Vorlage: Standardname VarN und reihum eine Farbe aus der Palette.
        if v is None:
            v = Variable(name=f"Var{r + 1}", color=PALETTE[r % len(PALETTE)])
        # Eindeutige ID der Variable (bleibt auch beim Löschen/Verschieben anderer Zeilen gleich); liegt im Namen-Element.
        self._uid += 1
        # Signale blockieren, solange die Zeile aufgebaut wird (sonst würde z. B. der Baum mit halben Zeilen neu aufgebaut).
        self.table.blockSignals(True)
        self.table.insertRow(r)
        name = QTableWidgetItem(v.name)
        name.setData(ROLE_UID, self._uid)
        self.table.setItem(r, C_NAME, name)

        # Steuerung, aus der die Variable gelesen wird.
        plc = QComboBox()
        names = self.plc_names()
        plc.addItems(names)
        plc.setCurrentIndex(min(max(v.plc, 0), len(names) - 1))
        # Zuordnungsliste: alle 'Diagramm › Y-Achse'-Kombinationen; die Wahl ordnet die Variable zu.
        axis = QComboBox()
        axis.addItems(self.flat_labels())
        flat = self.flat()
        axis.setCurrentIndex(flat.index((v.chart, v.axis)) if (v.chart, v.axis) in flat else 0)
        axis.currentIndexChanged.connect(lambda _i: self.refresh_tree())
        # Adresse (Text, Schreibweise des Treibers) und Datentyp (Auswahl des Treibers).
        typ = QComboBox()
        typ.setProperty("dtype", v.dtype)
        typ.currentTextChanged.connect(lambda t, w=typ: w.setProperty("dtype", t) if t else None)
        for col, w in [(C_PLC, plc), (C_AXIS, axis), (C_TYPE, typ)]:
            self.table.setCellWidget(r, col, w)
        tag = QTableWidgetItem(v.address)
        self.table.setItem(r, C_TAG, tag)
        plc.currentIndexChanged.connect(lambda _i, w=plc: self.update_row_driver(self._var_row_of(w)))

        # Farbe: Knopf mit Farbhintergrund; der Wert steht in der Eigenschaft 'color' (siehe pick_color).
        btn = QPushButton()
        btn.setProperty("color", v.color)
        btn.setStyleSheet(f"background-color: {v.color}")
        btn.clicked.connect(lambda _=False, b=btn: self.pick_color(b))
        self.table.setCellWidget(r, C_COLOR, btn)

        # Kontrollkästchen 'Werteanzeige' und 'Balken'.
        for col, state in ((C_SHOW, v.show_value), (C_BAR, v.bar)):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            chk.setCheckState(Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)
            self.table.setItem(r, col, chk)

        # Berechnete Variable: keine SPS-Adresse, deshalb die Adressfelder sperren; die Formel steht in der letzten Spalte.
        if v.formula:      # berechnete Variable: keine SPS-Adresse
            for w in (plc, typ):
                w.setEnabled(False)
            tag.setFlags(Qt.ItemFlag.ItemIsEnabled)
        fit = QTableWidgetItem(v.formula)
        fit.setFlags(Qt.ItemFlag.ItemIsEnabled)
        fit.setToolTip(tr("Berechnete Variable – Doppelklick zum Bearbeiten") if v.formula else "")
        self.table.setItem(r, C_FORMULA, fit)

        # Spalte 'Testwert' wird von 'Verbindung testen' gefüllt (bei berechneten Variablen: 'berechnet').
        test = QTableWidgetItem(tr("berechnet") if v.formula else "")
        test.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.setItem(r, C_TEST, test)
        self.table.blockSignals(False)
        self.update_row_driver(r)
        if refresh:
            self.refresh_tree()
            self.apply_var_filter()
            if self.table.isRowHidden(r):           # neue Zeile passt nicht zum Filter: Filter zurücksetzen
                self.ed_filter.clear()
                self.cb_filter_plc.setCurrentIndex(0)
                self.cb_filter_kind.setCurrentIndex(0)
            self.table.scrollToItem(self.table.item(r, C_NAME))

    def _var_row_of(self, widget):
        """Zeile der Variablentabelle, in der die Steuerungsauswahl ``widget`` steckt (-1 = nicht gefunden)."""
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, C_PLC) is widget:
                return r
        return -1

    def update_row_driver(self, r):
        """Typauswahl und Hinweis zur Adresse einer Variablenzeile an den Treiber ihrer Steuerung anpassen."""
        if r < 0 or r >= self.table.rowCount():
            return
        d = self.driver_of_plc(self.plc_of_row(r))
        typ = self.table.cellWidget(r, C_TYPE)
        cur = typ.property("dtype") or typ.currentText() or d.default_type
        typ.blockSignals(True)
        typ.clear()
        typ.addItems(d.types)
        if cur not in d.types:
            typ.addItem(cur)                         # nicht unterstützt: sichtbar lassen (Prüfung beim Speichern)
        typ.setCurrentText(cur)
        typ.blockSignals(False)
        typ.setProperty("dtype", cur)
        item = self.table.item(r, C_TAG)
        if item is not None:
            self.table.blockSignals(True)
            item.setToolTip(f"{tr(d.address_label)} ({d.name}): {tr(d.address_hint)}" if d.address_hint else d.name)
            self.table.blockSignals(False)

    # ---------------------------------------------------------------------------------------
    # Blöcke (Blocklesemodus)
    # ---------------------------------------------------------------------------------------
    # ---------- Blöcke (Blocklesemodus) ----------
    def block_names(self):
        """Namen aller Block-Elemente (Standard: Name[0] … Name[n-1], oder eigene Namen)."""
        self.sync_block_drivers()
        return [v.name for b in self.blocks for v in b.variables()]

    # Blockeditor öffnen; bei OK die Blöcke übernehmen und den Baum aktualisieren.
    def open_block_editor(self):
        # Namen, die für Block-Elemente nicht mehr in Frage kommen (vorhandene Variablen).
        taken = {self.table.item(r, C_NAME).text() for r in range(self.table.rowCount())}
        flat = self.flat()
        sel = self.selected_target()
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        self.sync_block_drivers()
        dlg = BlockEditor(self, self.blocks, flat, self.flat_labels(), self.plc_at, taken,
                          flat.index(sel) if sel in flat else 0,
                          plc_names=self.plc_names(), default_plc=self.plc_of_row(rows[0]) if rows else 0)
        if dlg.exec():
            self.blocks = dlg.result_blocks
            self.refresh_tree()
            n = sum(b.count for b in self.blocks)
            self.statusBar().showMessage(
                tr("{0} Blöcke mit {1} Variablen – werden mit je einer Anfrage gelesen.").format(len(self.blocks), n), 8000)

    # ---------------------------------------------------------------------------------------
    # Berechnete Variablen (Formeln)
    # ---------------------------------------------------------------------------------------
    # ---------- Berechnete Variablen ----------
    def available_names(self, row=None):
        """Namen, die in der Formel der Zeile row verwendbar sind (echte Variablen und früher
        definierte berechnete); row=None: neue Variable am Ende."""
        # Verfügbar sind alle Variablen außer der bearbeiteten selbst; berechnete Variablen weiter unten in der Tabelle
        # nicht (sie sind zur Laufzeit noch nicht ausgewertet).
        names = []
        for r in range(self.table.rowCount()):
            if r == row:
                continue
            if row is not None and r > row and self.table.item(r, C_FORMULA).text():
                continue
            names.append(self.table.item(r, C_NAME).text())
        return names + self.block_names()   # Block-Elemente stehen immer zur Verfügung

    # Neue berechnete Variable: Editor öffnen; bei OK als neue Zeile (im ausgewählten Diagramm/der Achse) anlegen.
    def add_computed(self):
        taken = ({self.table.item(r, C_NAME).text() for r in range(self.table.rowCount())}
                 | set(self.block_names()))
        dlg = FormulaEditor(self, self.available_names(), taken=taken)
        if dlg.exec():
            ci, ai = self.selected_target()
            self.add_row(Variable(name=dlg.result_name, dtype="REAL",
                                  color=PALETTE[self.table.rowCount() % len(PALETTE)],
                                  chart=ci, axis=ai, formula=dlg.result_formula))

    # Vorhandene berechnete Variable bearbeiten (Name und Formel).
    def edit_computed(self, row):
        old = self.table.item(row, C_NAME).text()
        taken = ({self.table.item(r, C_NAME).text() for r in range(self.table.rowCount())}
                 | set(self.block_names())) - {old}
        dlg = FormulaEditor(self, self.available_names(row), old,
                            self.table.item(row, C_FORMULA).text(), taken)
        if dlg.exec():
            self.table.item(row, C_NAME).setText(dlg.result_name)   # aktualisiert auch den Baum
            self.table.item(row, C_FORMULA).setText(dlg.result_formula)
            self.refresh_tree()

    # Doppelklick auf die Formel einer berechneten Variable öffnet den Editor.
    def on_var_double_click(self, item):
        if item.column() == C_FORMULA and item.text():
            self.edit_computed(item.row())

    # Namensänderung -> Baum neu aufbauen (zeigt den Namen).
    def on_var_item_changed(self, item):
        if item.column() == C_NAME:
            self.refresh_tree()
        if item.column() in (C_NAME, C_TAG, C_FORMULA):
            self.apply_var_filter()

    # ---------- Suchen und Filtern ----------
    def _fill_filter_plcs(self):
        """Auswahl „Steuerung“ des Filters an die Steuerungen anpassen (Auswahl bleibt, soweit möglich)."""
        cb = self.cb_filter_plc
        cur = cb.currentData()
        cb.blockSignals(True)
        cb.clear()
        cb.addItem(tr("alle Steuerungen"), -1)
        for i, n in enumerate(self.plc_names()):
            cb.addItem(n, i)
        k = cb.findData(cur if cur is not None else -1)
        cb.setCurrentIndex(max(k, 0))
        cb.blockSignals(False)

    def var_row_matches(self, r):
        """Passt die Variablenzeile r zu Suchtext, Steuerung und Art?"""
        from plc_util import text_filter
        t = self.table
        name = t.item(r, C_NAME).text() if t.item(r, C_NAME) else ""
        addr = t.item(r, C_TAG).text() if t.item(r, C_TAG) else ""
        formula = t.item(r, C_FORMULA).text() if t.item(r, C_FORMULA) else ""
        axis = t.cellWidget(r, C_AXIS).currentText() if t.cellWidget(r, C_AXIS) else ""
        typ = t.cellWidget(r, C_TYPE).currentText() if t.cellWidget(r, C_TYPE) else ""
        plc = t.cellWidget(r, C_PLC).currentText() if t.cellWidget(r, C_PLC) else ""
        want_plc = self.cb_filter_plc.currentData()
        if want_plc not in (None, -1) and not formula and self.plc_of_row(r) != want_plc:
            return False
        kind = self.cb_filter_kind.currentData() or ""
        if (kind == "plc" and formula) or (kind == "calc" and not formula) or \
                (kind == "empty" and (formula or addr.strip())):
            return False
        return text_filter(self.ed_filter.text())(name, addr, formula, axis, typ, plc)

    def apply_var_filter(self):
        """Nicht passende Zeilen ausblenden (sie bleiben in der Konfiguration)."""
        if not hasattr(self, "ed_filter"):
            return
        if self.cb_filter_plc.count() != len(self.plc_names()) + 1:
            self._fill_filter_plcs()
        n = self.table.rowCount()
        shown = 0
        for r in range(n):
            ok = self.var_row_matches(r)
            self.table.setRowHidden(r, not ok)
            shown += ok
        active = shown != n or bool(self.ed_filter.text().strip())
        self.lbl_filter.setText(tr("{0} von {1}").format(shown, n) if active else tr("{0} Variablen").format(n))
        self.ed_filter.setStyleSheet("QLineEdit{background:#fff8c4}" if self.ed_filter.text().strip() else "")

    # Markierte Zeilen von unten nach oben löschen (bei aktivem Filter nur die sichtbaren).
    def remove_rows(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes() if not self.table.isRowHidden(i.row())},
                      reverse=True)
        for r in rows:
            self.table.removeRow(r)
        self.refresh_tree()
        self.apply_var_filter()

    # Farbe per Farbdialog ändern; Knopf und Baumsymbol werden aktualisiert.
    def pick_color(self, btn):
        c = QColorDialog.getColor(QColor(btn.property("color")), self)
        if c.isValid():
            btn.setProperty("color", c.name())
            btn.setStyleSheet(f"background-color: {c.name()}")
            self.refresh_tree()

    def _update_web_users(self):
        """Anzeige der Web-Benutzer neben dem Knopf „Benutzer …“."""
        n = len(self.web_users)
        self.lbl_web_users.setText(tr("keine (ohne Anmeldung)") if not n else
                                   tr("{0} Benutzer: {1}").format(n, ", ".join(sorted(self.web_users))[:60]))

    def _update_notify(self):
        """Kurztext der Benachrichtigungen neben dem Knopf (aus bzw. ab welcher Priorität über welche Kanäle)."""
        import plc_notify as nf
        s = nf.settings(self.notify_settings)
        ch = [tr(nf.CHANNELS[c]) for c in nf.active_channels(s)]
        self.lbl_notify.setText(tr("aus") if not s["aktiv"] or not ch else
                                tr("ab {0} über {1}").format(tr(s["prio_min"]), ", ".join(ch)))

    def _update_opcua(self):
        """Kurztext des OPC-UA-Servers neben dem Knopf (Endpunkt, Sicherheit, Zugriff)."""
        import plc_opcua_server as us
        self.lbl_opcua.setText(us.describe(self.opcua_settings))

    def edit_opcua_server(self):
        """Dialog OPC-UA-Server öffnen und die Einstellungen übernehmen (gespeichert mit der Konfiguration)."""
        from plc_opcua_dialog import OpcUaServerDialog
        dlg = OpcUaServerDialog(self, self.opcua_settings, len(self.web_users))
        if dlg.exec():
            self.opcua_settings = dlg.settings
            self._update_opcua()

    def edit_notify(self):
        """Dialog Benachrichtigungen öffnen und die Einstellungen übernehmen."""
        from plc_notify_dialog import NotifyDialog
        dlg = NotifyDialog(self, self.notify_settings, self.ed_project.text().strip()
                           if hasattr(self, "ed_project") else "")
        if dlg.exec():
            self.notify_settings = dlg.settings
            self._update_notify()

    def edit_web_users(self):
        """Benutzer des Webservers bearbeiten; ohne HTTPS ein Hinweis, dass Passwörter dann unverschlüsselt übertragen
        werden.
        """
        from plc_web_dialog import WebUsersDialog
        dlg = WebUsersDialog(self, self.web_users)
        if dlg.exec():
            self.web_users = dlg.users
            self._update_web_users()
            if self.web_users and not self.chk_https.isChecked():
                self.statusBar().showMessage(tr("Tipp: HTTPS einschalten, sonst werden Passwörter unverschlüsselt "
                                                "übertragen."), 10000)

    def _update_rec_mode(self):
        """Felder der Aufzeichnung per Trigger nur bei diesem Modus freigeben."""
        on = self.cb_rec_mode.currentData() == "trigger"
        for w in (self.ed_rec_cond, self.sp_pre, self.sp_post, self.sp_max):
            w.setEnabled(on)

    def edit_rec_condition(self):
        """Startbedingung der Aufzeichnung per Trigger im Formeleditor bearbeiten (wie berechnete Variablen)."""
        dlg = FormulaEditor(self, self.available_names(), tr("Startbedingung"), self.ed_rec_cond.text(), set())
        dlg.setWindowTitle(tr("Startbedingung der Aufzeichnung"))
        if dlg.exec():
            self.ed_rec_cond.setText(dlg.result_formula)

    def pick_arch_dir(self):
        """Archiv-Ordner wählen."""
        d = QFileDialog.getExistingDirectory(self, tr("Archiv-Ordner wählen"), self.ed_arch.text() or BASE_DIR)
        if d:
            self.ed_arch.setText(d)

    def pick_dir(self):
        """CSV-Ordner wählen."""
        d = QFileDialog.getExistingDirectory(self, tr("CSV-Ordner wählen"), self.ed_dir.text() or BASE_DIR)
        if d:
            self.ed_dir.setText(d)

    # ---------------------------------------------------------------------------------------
    # Daten <-> Oberfläche
    # ---------------------------------------------------------------------------------------
    # ---------- Daten <-> UI ----------
    # Oberfläche mit einer geladenen Konfiguration füllen.
    def fill(self, conn, charts, variables, blocks=None, plcs=None):
        self._loading = True
        self.ed_project.setText(conn.get("projekt", ""))
        # Steuerungen zuerst: die Variablenzeilen brauchen deren Namen für ihre Auswahlliste.
        self.plc_table.setRowCount(0)
        for p in (plcs or [Plc()]):
            self.add_plc_row(p)
        self.store = driver_store(conn)
        self.sp_win.setValue(conn["fenster_s"])
        self.ed_dir.setText(conn["csv_ordner"])
        self.ed_csvname.setText(conn["csv_name"])
        self.sp_maxrec.setValue(conn["max_records"])
        self.ed_arch.setText(conn["archiv_ordner"])
        self.chk_arch_end.setChecked(bool(conn.get("archiv_beenden", 1)))
        self.chk_csv.setChecked(bool(int(conn.get("csv_aktiv", 1))))
        self.cb_db.setCurrentIndex(max(self.cb_db.findData(conn.get("db_typ", "")), 0))
        self.ed_db_host.setText(conn.get("db_host", "localhost"))
        self.sp_db_port.setValue(int(conn.get("db_port", 0)))
        self.ed_db_name.setText(conn.get("db_name", "datenlogger"))
        self.ed_db_user.setText(conn.get("db_user", ""))
        self.ed_db_pw.setText(conn.get("db_passwort", ""))
        self.ed_db_table.setText(conn.get("db_tabelle", "messwerte"))
        self.ed_db_file.setText(conn.get("db_datei", "datenlogger.db"))
        self.chk_db_changes.setChecked(bool(int(conn.get("db_nur_aenderungen", 0))))
        self.sp_clean_days.setValue(int(conn.get("aufr_csv_tage", 0) or 0))
        self.sp_clean_mb.setValue(int(conn.get("aufr_csv_mb", 0) or 0))
        self.sp_db_clean_days.setValue(int(conn.get("aufr_db_tage", 0) or 0))
        self.sp_db_clean_mb.setValue(int(conn.get("aufr_db_mb", 0) or 0))
        self.ed_event_file.setText(conn.get("ereignis_datei", ""))
        self.chk_report.setChecked(bool(int(conn.get("bericht_aktiv", 0) or 0)))
        self.cb_report_period.setCurrentIndex(max(self.cb_report_period.findData(conn.get("bericht_zeitraum", "tag")), 0))
        self.ed_report_shifts.setText(conn.get("bericht_schichten", "06:00,14:00,22:00"))
        self.ed_report_start.setText(conn.get("bericht_beginn", "00:00"))
        self.ed_report_dir.setText(conn.get("bericht_ordner", "berichte"))
        self._update_report_fields()
        self.cb_rec_mode.setCurrentIndex(max(self.cb_rec_mode.findData(conn.get("aufz_modus", "dauernd")), 0))
        self.ed_rec_cond.setText(conn.get("aufz_bedingung", ""))
        self.sp_pre.setValue(float(conn.get("aufz_vorlauf_s", 10.0)))
        self.sp_post.setValue(float(conn.get("aufz_nachlauf_s", 10.0)))
        self.sp_max.setValue(float(conn.get("aufz_max_s", 0.0)))
        self._update_rec_mode()
        self._update_db_fields()
        self.ed_logo.setText(conn.get("logo", ""))
        self.ed_customer_logo.setText(conn.get("kundenlogo", ""))
        self.ed_icon.setText(conn.get("icon", ""))
        self.cb_layout.setCurrentIndex(max(self.cb_layout.findData(conn["anordnung"]), 0))
        self.cb_page.setCurrentIndex(max(self.cb_page.findData(conn.get("seite_anordnung", "")), 0))
        self.sp_cols.setValue(int(conn.get("raster_spalten", 0)))
        self.chk_bars.setChecked(bool(conn["balken"]))
        self.sp_bar_w.setValue(int(conn.get("balken_breite", 14) or 14))
        self.chk_web.setChecked(bool(conn.get("web_aktiv", 0)))
        self.ed_web_host.setText(conn.get("web_host", "0.0.0.0"))
        self.sp_web_port.setValue(int(conn.get("web_port", 8080)))
        self.ed_web_token.setText(conn.get("web_token", ""))
        self.sp_web_int.setValue(int(conn.get("web_intervall_ms", 1000)))
        self.chk_headless.setChecked(bool(conn.get("headless", 0)))
        from plc_webauth import parse_users
        self.chk_https.setChecked(bool(int(conn.get("web_https", 0) or 0)))
        self.ed_web_cert.setText(conn.get("web_zertifikat", ""))
        self.ed_web_key.setText(conn.get("web_schluessel", ""))
        self.ed_web_cert.setEnabled(self.chk_https.isChecked())
        self.ed_web_key.setEnabled(self.chk_https.isChecked())
        self.web_users = parse_users(conn.get("web_benutzer", ""))
        self._update_web_users()
        import plc_notify as nf
        self.notify_settings = nf.settings(conn.get("benachrichtigung", ""))
        self._update_notify()
        import plc_opcua_server as us
        self.opcua_settings = us.settings(conn.get("opcua_server", ""))
        self._update_opcua()
        self.charts = charts
        self.prop_key = None
        self.table.setRowCount(0)
        self.blocks = list(blocks or [])
        # Nur echte und berechnete Variablen kommen in die Tabelle; Block-Elemente (v.block) werden aus self.blocks erzeugt.
        for v in variables:
            if not v.block:        # Block-Elemente entstehen aus den Blöcken
                self.add_row(v, refresh=False)
        self._loading = False
        self.load_props()
        self.refresh_tree()
        self._fill_filter_plcs()
        self.apply_var_filter()
        self.update_title()

    # Verbindungs- und Anzeigeeinstellungen aus den Feldern als Wörterbuch (für die Konfigurationsdatei und für Tests).
    # Die Steuerungen stehen getrennt in collect_plcs(); ip/pfad/cpu/intervall_ms spiegeln die erste Steuerung.
    def collect_conn(self):
        import json
        return {"projekt": self.ed_project.text().strip(),
                "treiberdaten": json.dumps(self.store, ensure_ascii=False) if self.store else "",
                "csv_ordner": self.ed_dir.text().strip() or "logs",
                "fenster_s": self.sp_win.value(),
                "anordnung": self.cb_layout.currentData(),
                "seite_anordnung": self.cb_page.currentData() or "",
                "raster_spalten": self.sp_cols.value(),
                "balken": 1 if self.chk_bars.isChecked() else 0, "balken_breite": self.sp_bar_w.value(),
                "csv_name": self.ed_csvname.text().strip() or "log",
                "max_records": self.sp_maxrec.value(),
                "archiv_ordner": self.ed_arch.text().strip() or "archiv",
                "archiv_beenden": 1 if self.chk_arch_end.isChecked() else 0,
                "csv_aktiv": 1 if self.chk_csv.isChecked() else 0,
                "db_typ": self.cb_db.currentData() or "",
                "db_host": self.ed_db_host.text().strip() or "localhost",
                "db_port": self.sp_db_port.value(),
                "db_name": self.ed_db_name.text().strip() or "datenlogger",
                "db_user": self.ed_db_user.text().strip(),
                "db_passwort": self.ed_db_pw.text(),
                "db_tabelle": self.ed_db_table.text().strip() or "messwerte",
                "db_datei": self.ed_db_file.text().strip() or "datenlogger.db",
                "db_nur_aenderungen": 1 if self.chk_db_changes.isChecked() else 0,
                "aufr_csv_tage": self.sp_clean_days.value(), "aufr_csv_mb": self.sp_clean_mb.value(),
                "aufr_db_tage": self.sp_db_clean_days.value(), "aufr_db_mb": self.sp_db_clean_mb.value(),
                "logo": self.ed_logo.text().strip(), "kundenlogo": self.ed_customer_logo.text().strip(),
                "icon": self.ed_icon.text().strip(),
                "web_aktiv": 1 if self.chk_web.isChecked() else 0,
                "web_host": self.ed_web_host.text().strip() or "0.0.0.0",
                "web_port": self.sp_web_port.value(),
                "web_token": self.ed_web_token.text().strip(),
                "web_intervall_ms": self.sp_web_int.value(),
                "headless": 1 if self.chk_headless.isChecked() else 0,
                "web_https": 1 if self.chk_https.isChecked() else 0,
                "web_zertifikat": self.ed_web_cert.text().strip(),
                "web_schluessel": self.ed_web_key.text().strip(),
                "web_benutzer": json.dumps(self.web_users, ensure_ascii=False) if self.web_users else "",
                "benachrichtigung": json.dumps(self.notify_settings, ensure_ascii=False)
                if self.notify_settings and self.notify_settings.get("aktiv") or any(
                    (self.notify_settings or {}).get(k, {}).get("aktiv") for k in ("email", "webhook", "ntfy",
                                                                                     "telegram")) else "",
                "opcua_server": json.dumps(self.opcua_settings, ensure_ascii=False)
                if self.opcua_settings and self.opcua_settings != __import__("plc_opcua_server").settings({}) else "",
                "ereignis_datei": self.ed_event_file.text().strip(),
                "bericht_aktiv": 1 if self.chk_report.isChecked() else 0,
                "bericht_zeitraum": self.cb_report_period.currentData() or "tag",
                "bericht_schichten": self.ed_report_shifts.text().strip() or "06:00,14:00,22:00",
                "bericht_beginn": self.ed_report_start.text().strip() or "00:00",
                "bericht_ordner": self.ed_report_dir.text().strip() or "berichte",
                "aufz_modus": self.cb_rec_mode.currentData() or "dauernd",
                "aufz_bedingung": " ".join(self.ed_rec_cond.text().split()),
                "aufz_vorlauf_s": self.sp_pre.value(),
                "aufz_nachlauf_s": self.sp_post.value(),
                "aufz_max_s": self.sp_max.value()}

    # Alle Tabellenzeilen als Variable-Objekte einsammeln (einschließlich Zuordnung und Formel).
    def collect(self):
        t = self.table
        out = []
        for r in range(t.rowCount()):
            ci, ai = self.assign_of_row(r)
            out.append(Variable(
                name=t.item(r, C_NAME).text().strip(),
                plc=t.cellWidget(r, C_PLC).currentIndex(),
                address=t.item(r, C_TAG).text().strip(),
                dtype=t.cellWidget(r, C_TYPE).currentText(),
                color=t.cellWidget(r, C_COLOR).property("color"),
                show_value=t.item(r, C_SHOW).checkState() == Qt.CheckState.Checked,
                chart=ci, axis=ai,
                bar=t.item(r, C_BAR).checkState() == Qt.CheckState.Checked,
                formula=t.item(r, C_FORMULA).text(),
            ))
        return out

    # ---------------------------------------------------------------------------------------
    # Variablenliste exportieren / importieren (CSV oder Excel)
    # ---------------------------------------------------------------------------------------
    def export_variables(self):
        """Variablen der Tabelle (ohne Block-Elemente) als CSV- oder Excel-Datei speichern."""
        from plc_export import write_table
        stem = os.path.splitext(os.path.basename(self.path))[0] if self.path else "variablen"
        path, flt = QFileDialog.getSaveFileName(self, tr("Variablen exportieren"),
                                                os.path.join(BASE_DIR, f"{stem}_variablen.xlsx"),
                                                tr("Excel-Datei (*.xlsx);;CSV-Datei (*.csv)"))
        if not path:
            return
        if os.path.splitext(path)[1].lower() not in (".xlsx", ".csv"):
            path += ".csv" if "csv" in flt.lower() else ".xlsx"
        plcs = self.plc_names()
        rows = []
        for v in self.collect():
            chart = self.charts[v.chart] if 0 <= v.chart < len(self.charts) else self.charts[0]
            axis = chart.axes[v.axis] if 0 <= v.axis < len(chart.axes) else chart.axes[0]
            rows.append([v.name, plcs[v.plc] if 0 <= v.plc < len(plcs) else "", chart.name, axis.name,
                         "" if v.formula else v.address, "" if v.formula else v.dtype, v.color,
                         "ja" if v.show_value else "nein", "ja" if v.bar else "nein", v.formula])
        try:
            write_table(path, VAR_IO_COLS, rows, sheet="Variablen")
        except Exception as e:
            QMessageBox.warning(self, tr("Variablen exportieren"), tr("Die Datei konnte nicht geschrieben werden:\n{0}").format(e))
            return
        self.statusBar().showMessage(tr("{0} Variablen exportiert: {1}").format(len(rows), path), 8000)

    def import_variables(self):
        """Variablen aus einer CSV- oder Excel-Datei übernehmen (Spalten wie beim Export; Pflicht ist nur „Name“).

        Fehlende Diagramme und Y-Achsen werden angelegt; unbekannte Steuerungen fallen auf die erste zurück."""
        from plc_export import read_table
        path, _ = QFileDialog.getOpenFileName(self, tr("Variablen importieren"), BASE_DIR,
                                              tr("Excel, ODS oder CSV (*.xlsx *.ods *.csv);;Alle Dateien (*)"))
        if not path:
            return
        try:
            header, rows = read_table(path)
        except Exception as e:
            QMessageBox.warning(self, tr("Variablen importieren"), tr("Die Datei konnte nicht gelesen werden:\n{0}").format(e))
            return
        col = {h.casefold(): i for i, h in enumerate(header)}
        if "name" not in col:
            QMessageBox.warning(self, tr("Variablen importieren"),
                                tr("Die erste Zeile muss die Spaltennamen enthalten, mindestens „Name“.\n"
                                   "Erwartete Spalten: {0}").format(", ".join(VAR_IO_COLS)))
            return

        def cell(row, key):
            """Zelle der Spalte ``key`` (Spaltenname, Groß-/Kleinschreibung egal) als Text; ganze Zahlen aus Excel ohne
            „.0“.
            """
            i = col.get(key.casefold())
            if i is None or i >= len(row) or row[i] is None:
                return ""
            v = row[i]
            if isinstance(v, float) and v.is_integer():          # Excel liefert Zahlen (z. B. Adresse 40001)
                v = int(v)
            return str(v).strip()

        def flag(text, default):
            """Ja/Nein-Zelle auswerten (ja, yes, true, 1, x …); leer = Vorgabe."""
            return default if not text else text.casefold() in ("ja", "j", "yes", "y", "true", "wahr", "1", "x", "on")

        # Ersetzen oder anhängen, wenn schon Variablen da sind.
        replace = True
        if self.table.rowCount():
            box = QMessageBox(QMessageBox.Icon.Question, tr("Variablen importieren"),
                              tr("{0} Variablen in der Datei. Die vorhandenen {1} Variablen ersetzen oder die neuen "
                                 "anhängen (gleiche Namen werden dann übersprungen)?").format(len(rows), self.table.rowCount()),
                              parent=self)
            b_rep = box.addButton(tr("Ersetzen"), QMessageBox.ButtonRole.DestructiveRole)
            b_add = box.addButton(tr("Anhängen"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            if box.clickedButton() not in (b_rep, b_add):
                return
            replace = box.clickedButton() is b_rep
        if replace:
            self.table.setRowCount(0)
        taken = {self.table.item(r, C_NAME).text() for r in range(self.table.rowCount())} | set(self.block_names())
        plcs = [n.casefold() for n in self.plc_names()]
        # 1. Durchgang: Variablen bilden, fehlende Diagramme/Achsen anlegen (Zuordnungen der übrigen bleiben erhalten).
        assigns = self.assignments()
        new, skipped, unknown_plc = [], [], set()
        for row in rows:
            name = cell(row, "Name")
            if not name or name in taken:
                if name:
                    skipped.append(name)
                continue
            taken.add(name)
            plc_name = cell(row, "Steuerung")
            plc = plcs.index(plc_name.casefold()) if plc_name.casefold() in plcs else 0
            if plc_name and plc_name.casefold() not in plcs:
                unknown_plc.add(plc_name)
            ci, ai = self._chart_axis_by_name(cell(row, "Diagramm"), cell(row, "Y-Achse"))
            formula = cell(row, "Formel")
            color = cell(row, "Farbe")
            if not QColor(color).isValid():
                color = PALETTE[(self.table.rowCount() + len(new)) % len(PALETTE)]
            new.append(Variable(name=name, plc=plc, address="" if formula else cell(row, "Adresse"),
                                dtype=cell(row, "Typ") or self.driver_of_plc(plc).default_type, color=color,
                                show_value=flag(cell(row, "Werteanzeige"), True), bar=flag(cell(row, "Balken"), True),
                                chart=ci, axis=ai, formula=formula))
        self.set_assignments(assigns)
        # 2. Durchgang: Zeilen anlegen und den Baum einmal neu aufbauen.
        for v in new:
            self.add_row(v, refresh=False)
        self.refresh_tree()
        msg = tr("{0} Variablen importiert.").format(len(new))
        if skipped:
            msg += "\n" + tr("Übersprungen (Name schon vorhanden): {0}").format(", ".join(skipped[:20])
                                                                               + (" …" if len(skipped) > 20 else ""))
        if unknown_plc:
            msg += "\n" + tr("Unbekannte Steuerung (erste Steuerung verwendet): {0}").format(", ".join(sorted(unknown_plc)))
        QMessageBox.information(self, tr("Variablen importieren"), msg)

    def _chart_axis_by_name(self, chart_name, axis_name):
        """(Diagramm, Achse) zu den Namen; fehlende werden angelegt. Leere Namen: erstes Diagramm bzw. erste Achse."""
        if not chart_name:
            ci = 0
        else:
            ci = next((k for k, c in enumerate(self.charts) if c.name.casefold() == chart_name.casefold()), None)
            if ci is None:
                self.charts.append(Chart(name=chart_name, axes=[Axis(name=axis_name or "Achse 1")]))
                ci = len(self.charts) - 1
        axes = self.charts[ci].axes
        if not axis_name:
            return ci, 0
        ai = next((k for k, a in enumerate(axes) if a.name.casefold() == axis_name.casefold()), None)
        if ai is None:
            axes.append(Axis(name=axis_name))
            ai = len(axes) - 1
        return ci, ai

    # ---------------------------------------------------------------------------------------
    # Variablen aus SPS-Symbolen
    # ---------------------------------------------------------------------------------------
    # ---------- Variablen aus SPS-Symbolen ----------
    def selected_target(self):
        """(Diagramm, Achse) der aktuellen Baumauswahl als Vorgabe für neue Variablen."""
        items = self.tree.selectedItems()
        if items:
            it = items[0]
            kind = it.data(0, ROLE_KIND)
            if kind in ("var", "block", "blockpart") and it.parent() is not None:
                it = it.parent()
                kind = "axis"
            if kind == "axis":
                return it.data(0, ROLE_CI), it.data(0, ROLE_AI)
            if kind == "chart":
                return it.data(0, ROLE_CI), 0
        return 0, 0

    # Auswahldialog des Treibers öffnen; gewählte Werte werden Variablen, gewählte Arrays/Bereiche Blöcke.
    def open_tag_browser(self):
        """Auswahldialog des Treibers öffnen; gewählte Werte werden Variablen, gewählte Arrays/Bereiche Blöcke."""
        flat = self.flat()
        sel = self.selected_target()
        default = flat.index(sel) if sel in flat else 0
        # Bei mehreren Steuerungen zuerst die Steuerung wählen (Vorgabe: Steuerung der markierten Zeile).
        names = self.plc_names()
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        plc = self.plc_of_row(rows[0]) if rows else 0
        if len(names) > 1:
            name, ok = QInputDialog.getItem(self, tr("Steuerung wählen"), tr("Variablen aus Steuerung:"), names,
                                            min(plc, len(names) - 1), False)
            if not ok:
                return
            plc = names.index(name)
        p = self.plc_at(plc)
        d = get_driver(p.driver)
        if not d.browse_label:
            QMessageBox.information(self, tr("Aus Steuerung wählen"),
                                    tr("Der Treiber „{0}“ bietet keine Auswahl aus der Steuerung – bitte die "
                                       "Adressen in der Tabelle eintragen.\n\n{1}").format(d.name, tr(d.address_hint)))
            return
        # Adressen, die für diese Steuerung schon angelegt sind (auch als Block-Element), werden im Dialog gesperrt.
        self.sync_block_drivers()
        existing = {self.table.item(r, C_TAG).text().strip() for r in range(self.table.rowCount())
                    if not self.table.item(r, C_FORMULA).text() and self.plc_of_row(r) == plc}
        existing |= {v.address for b in self.blocks if b.plc == plc for v in b.variables()}
        ctx = BrowseContext(plc=p, existing=existing, target_labels=self.flat_labels(), default_target=default,
                            store=dict(self.store.get(p.driver, {})))
        try:
            res = d.browse(self, ctx)
        except ImportError as e:
            QMessageBox.critical(self, tr("Aus Steuerung wählen"),
                                 tr("Für den Treiber „{0}“ fehlt eine Bibliothek ({1}):\n{2}").format(d.name, d.library, e))
            return
        if res is None:
            return
        if res.store:
            self.store.setdefault(p.driver, {}).update(res.store)
        if not res.variables and not res.blocks:
            return
        taken = ({self.table.item(r, C_NAME).text() for r in range(self.table.rowCount())}
                 | set(self.block_names()))
        ci, ai = flat[res.target_index] if 0 <= res.target_index < len(flat) else (0, 0)
        # Neue Variablen: Name = Vorschlag des Treibers (bei Gleichheit mit _2, _3 … eindeutig gemacht).
        for suggestion, address, dtype in res.variables:
            name, k = suggestion, 2
            while name in taken:
                name, k = f"{suggestion}_{k}", k + 1
            taken.add(name)
            self.add_row(Variable(name=name, plc=plc, address=address, dtype=dtype,
                                  color=PALETTE[self.table.rowCount() % len(PALETTE)],
                                  chart=ci, axis=ai), refresh=False)
        bnames = {b.name for b in self.blocks}
        for suggestion, address, start, count, dtype in res.blocks:
            base = re.sub(r"[^\w]+", "_", suggestion).strip("_") or "Block"
            bname, k = base, 2
            while bname in bnames or any(f"{bname}[{i}]" in taken for i in range(count)):
                bname, k = f"{base}_{k}", k + 1
            bnames.add(bname)
            self.blocks.append(Block(name=bname, address=address, start=start, count=count, dtype=dtype, plc=plc,
                                     driver=p.driver, chart=ci, axis=ai,
                                     color=PALETTE[len(self.blocks) % len(PALETTE)]))
        self.refresh_tree()
        self.statusBar().showMessage(
            tr("{0} Variablen und {1} Blöcke übernommen – mit „Verbindung testen“ prüfen.").format(len(res.variables), len(res.blocks)), 8000)

    # ---------------------------------------------------------------------------------------
    # Aktionen (Speichern, Laden, Test)
    # ---------------------------------------------------------------------------------------
    # ---------- Aktionen ----------
    # Konfiguration prüfen und in 'path' schreiben. Rückgabe: True bei Erfolg.
    def _write(self, path):
        # CSV-Name wird Teil von Dateinamen und Ordnern: keine unzulässigen Zeichen.
        if re.search(r'[\\/:*?"<>|]', self.ed_csvname.text()):
            QMessageBox.warning(self, tr("CSV-Name"),
                                tr('Der CSV-Name darf keines der Zeichen \\ / : * ? " < > | enthalten.'))
            return False
        # Steuerungen: eindeutige Namen (Parameter prüft der Treiber, siehe unten).
        plcs = self.collect_plcs()
        pnames = [p.name for p in plcs]
        if len(set(pnames)) != len(pnames) or any(";" in n or "[" in n or "]" in n for n in pnames):
            QMessageBox.warning(self, tr("Steuerungen prüfen"),
                                tr("Die Namen der Steuerungen müssen eindeutig sein und dürfen kein ; [ ] enthalten."))
            return False
        variables = self.collect()
        # Namen müssen eindeutig sein; Block-Elemente zählen mit.
        names = [v.name for v in variables] + self.block_names()
        if any(not n or ";" in n for n in names) or len(set(names)) != len(names):
            QMessageBox.warning(self, tr("Namen prüfen"),
                                tr("Variablennamen müssen eindeutig, nicht leer und ohne ';' sein."))
            return False
        # Steuerungen, Adressen und Blöcke formal prüfen (ob es sie gibt, zeigt erst „Verbindung testen“).
        bad = []
        for p in plcs:
            err = get_driver(p.driver).check_params(p.params)
            if err:
                bad.append(f"{p.name}: {err}")
        for v in variables:
            if not v.formula:
                err = self.driver_of_plc(v.plc).check_address(v.address, v.dtype)
                if err:
                    bad.append(f"{v.name}: {err}")
        self.sync_block_drivers()
        for b in self.blocks:
            err = self.driver_of_plc(b.plc).check_block(b)
            if err:
                bad.append(tr("Block {0}: {1}").format(b.name, err))
        if bad:
            QMessageBox.warning(self, tr("Adressen prüfen"),
                                tr("Ungültige Einstellungen oder Adressen:\n") + "\n".join(bad[:20])
                                + ("\n…" if len(bad) > 20 else ""))
            return False
        # Formeln prüfen: Syntax und Variablen. Verfügbar sind alle echten Variablen (auch Block-Elemente) und berechnete,
        # die weiter oben in der Tabelle definiert wurden.
        avail, problems = {v.name for v in variables if not v.formula} | set(self.block_names()), []
        for v in variables:                      # Formeln prüfen (Syntax, bekannte/frühere Variablen)
            # Berechnete Variablen werden nicht aus der SPS gelesen.
            if v.formula:
                f, err = check_formula(v.formula)
                if f is None:
                    problems.append(f"{v.name}: {err}")
                else:
                    missing = [n for n in f.refs if n not in avail]
                    if missing:
                        problems.append(tr("{0}: unbekannte oder später definierte Variablen: ").format(v.name)
                                        + ", ".join(missing))
                avail.add(v.name)
        if problems:
            QMessageBox.warning(self, tr("Formeln prüfen"), "\n".join(problems))
            return False
        for c in self.charts:
            for a in c.axes:
                if not a.auto and a.y_max <= a.y_min:
                    QMessageBox.warning(self, tr("Y-Skalierung"),
                                        tr("{0} › {1}: Y max muss größer als Y min sein.").format(c.name, a.name))
                    return False
        # Aufzeichnungsziele: Tabellenname prüfen; ohne CSV und ohne Datenbank wird nichts gespeichert.
        if self.cb_db.currentData() and not check_table_name(self.ed_db_table.text().strip() or "messwerte"):
            QMessageBox.warning(self, tr("Datenbank"), tr("Der Tabellenname darf nur Buchstaben, Ziffern und _ enthalten "
                                "und muss mit einem Buchstaben beginnen."))
            return False
        if not self.chk_csv.isChecked() and not self.cb_db.currentData():
            if QMessageBox.question(self, tr("Aufzeichnung"),
                                    tr("Weder CSV-Datei noch Datenbank sind eingeschaltet – die Messwerte werden nur "
                                    "angezeigt, aber nicht gespeichert. Trotzdem speichern?")) != QMessageBox.StandardButton.Yes:
                return False
        # PID-Optimierung: die gewählten Variablen müssen existieren (z. B. nach Umbenennen).
        avail_pid = {v.name for v in variables} | set(self.block_names())
        bad_pid = [f"{c.name}: " + ", ".join(n for n in (c.pid_sw, c.pid_iw, c.pid_stw) if n and n not in avail_pid)
                   for c in self.charts if c.pid and any(n and n not in avail_pid
                                                         for n in (c.pid_sw, c.pid_iw, c.pid_stw))]
        if bad_pid and QMessageBox.question(
                self, tr("PID-Optimierung"), tr("Unbekannte Variablen in der PID-Optimierung:\n\n") + "\n".join(bad_pid)
                + tr("\n\nTrotzdem speichern?")) != QMessageBox.StandardButton.Yes:
            return False
        # Trigger: aktive Trigger müssen zu den (evtl. umbenannten) Variablen passen.
        avail_all = {v.name for v in variables} | set(self.block_names())
        bad = [f"{t.name}: {err}" for t in self.triggers if t.aktiv for err in [check_trigger(t, avail_all)] if err]
        if bad:
            if QMessageBox.question(self, tr("Trigger prüfen"), tr("Fehlerhafte Trigger (werden beim Aufzeichnen "
                                    "übersprungen):\n\n") + "\n".join(bad) + tr("\n\nTrotzdem speichern?")) \
                    != QMessageBox.StandardButton.Yes:
                return False
        # Berichte: Uhrzeiten prüfen.
        if self.chk_report.isChecked():
            for label, text in ((tr("Schichtbeginne"), self.ed_report_shifts.text()),
                                (tr("Tagesbeginn"), self.ed_report_start.text())):
                parts = [x.strip() for x in text.replace(";", ",").split(",") if x.strip()]
                if any(not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", x) for x in parts):
                    QMessageBox.warning(self, tr("Berichte"), tr("{0}: Uhrzeiten bitte als hh:mm, durch Komma getrennt "
                                                                "(z. B. 06:00,14:00,22:00).").format(label))
                    self.tabs.setCurrentIndex(6)
                    return False
        # Aufzeichnung per Trigger: Startbedingung prüfen.
        if self.cb_rec_mode.currentData() == "trigger":
            cond = self.ed_rec_cond.text().strip()
            f, err = check_formula(cond) if cond else (None, tr("keine Startbedingung angegeben"))
            if f is not None:
                missing = [n for n in f.refs if n not in avail_all]
                err = (tr("unbekannte Variablen: ") + ", ".join(missing)) if missing else ""
            if err:
                QMessageBox.warning(self, tr("Aufzeichnung per Trigger"), tr("Startbedingung: {0}").format(err))
                self.tabs.setCurrentIndex(1)
                return False
        # Datei schreiben (Verbindung, Steuerungen, Diagramme/Achsen, Variablen, Blöcke, danach die Trigger).
        try:
            save_config(self.collect_conn(), self.charts, variables, path, blocks=self.blocks, plcs=plcs)
            save_triggers(path, self.triggers)
        except OSError as e:
            QMessageBox.critical(self, tr("Speichern"), tr("Die Datei konnte nicht geschrieben werden:\n{0}").format(e))
            return False
        self.path = path
        remember_config_path(path)          # Logger und Konfiguration öffnen beim nächsten Start dieselbe Datei
        self.update_title()
        self.statusBar().showMessage(tr("Gespeichert: {0}").format(path), 5000)
        return True

    # Speichern in die aktuelle Datei; ohne Dateinamen (neue Konfiguration) wie „Speichern unter“.
    def save(self):
        return self._write(self.path) if self.path else self.save_as()

    # „Speichern unter“: beliebiger Dateiname; die Endung ist immer .json.
    def save_as(self):
        start = self.path or os.path.join(BASE_DIR, "plc_config.json")
        p, _ = QFileDialog.getSaveFileName(self, tr("Konfiguration speichern unter"), start, FILE_FILTER)
        if not p:
            return False
        base, ext = os.path.splitext(p)
        if ext.lower() != CONFIG_EXT:
            p = (base if ext.lower() in (".ini", ".txt", ".cfg") else p) + CONFIG_EXT
        return self._write(os.path.abspath(p))

    # Konfiguration aus Datei p laden (JSON, beliebiger Name). Rückgabe: True bei Erfolg.
    def load_path(self, p):
        try:
            read_config_store(p)
        except ConfigFormatError as e:
            # ältere INI-Datei: Umwandlung anbieten (die INI bleibt unverändert)
            if open(p, encoding="utf-8-sig", errors="replace").read(4096).lstrip().startswith("["):
                return self.convert_ini(p)
            QMessageBox.critical(self, tr("Konfiguration laden"), str(e))
            return False
        except OSError:
            pass
        try:
            data = (load_config(p), load_blocks(p), load_plcs(p))
        except Exception as e:
            QMessageBox.critical(self, tr("Konfiguration laden"), tr("{0}\n\nDie Datei konnte nicht gelesen werden:\n{1}").format(p, e))
            return False
        (conn, charts, variables), blocks, plcs = data
        self.path = os.path.abspath(p)
        self.fill(conn, charts, variables, blocks=blocks, plcs=plcs)
        try:
            self.triggers = load_triggers(self.path)
        except Exception as e:
            self.triggers = []
            QMessageBox.warning(self, tr("Trigger"), tr("Die Trigger konnten nicht gelesen werden:\n{0}").format(e))
        self._update_trigger_summary()
        remember_config_path(self.path)
        self.setWindowIcon(app_icon(self.ed_icon.text(), self.ed_logo.text()))
        self.update_title()
        self.statusBar().showMessage(tr("Geladen: {0}").format(self.path), 5000)
        return True

    # Ältere INI-Konfiguration(en) einmalig in JSON umwandeln (die INI-Dateien bleiben unverändert).
    def convert_ini(self, path=None):
        if path:
            paths = [path]
            ask = tr("„{0}“ ist eine Konfiguration im alten INI-Format.\n\nJetzt in eine JSON-Datei umwandeln und öffnen?\n"
                     "(Die INI-Datei bleibt unverändert.)").format(os.path.basename(path))
            if QMessageBox.question(self, tr("INI-Datei umwandeln"), ask) != QMessageBox.StandardButton.Yes:
                return False
        else:
            start = os.path.dirname(self.path) if self.path else BASE_DIR
            paths, _ = QFileDialog.getOpenFileNames(self, tr("INI-Datei(en) umwandeln"), start,
                                                    tr("INI-Konfiguration (*.ini *.txt *.cfg);;Alle Dateien (*)"))
            if not paths:
                return False
        done, errors = [], []
        for p in paths:
            target = os.path.splitext(p)[0] + CONFIG_EXT
            if os.path.exists(target) and QMessageBox.question(
                    self, tr("INI-Datei umwandeln"),
                    tr("„{0}“ existiert bereits. Überschreiben?").format(os.path.basename(target))) \
                    != QMessageBox.StandardButton.Yes:
                continue
            try:
                done.append(convert_ini(p, target))
            except Exception as e:
                errors.append(f"{os.path.basename(p)}: {e}")
        if errors:
            QMessageBox.warning(self, tr("INI-Datei umwandeln"), "\n".join(errors))
        if not done:
            return False
        if len(done) == 1:
            return self.load_path(done[0])
        QMessageBox.information(self, tr("INI-Datei umwandeln"),
                                tr("Umgewandelt:\n{0}").format("\n".join(done)))
        return True

    # „Öffnen“: Dateidialog für eine Konfigurationsdatei mit beliebigem Namen.
    def open_file(self):
        start = os.path.dirname(self.path) if self.path else BASE_DIR
        p, _ = QFileDialog.getOpenFileName(self, tr("Konfiguration öffnen"), start, FILE_FILTER)
        if p:
            self.load_path(p)

    # „Neu“: leere Konfiguration mit einer Steuerung; der Dateiname wird beim ersten Speichern gefragt.
    def new_config(self):
        self.path = ""
        conn, plc = default_connection(), Plc()
        self.fill(conn, [Chart()], [], blocks=[], plcs=[plc])
        self.triggers = []
        self._update_trigger_summary()
        self.update_title()

    # Logger mit dieser Konfiguration starten (nach dem Speichern).
    def start_logger(self):
        if not self.save():
            return
        from plc_branding import launch
        if not launch(self, "logger", self.path, title=tr("Logger starten")):
            return
        self.statusBar().showMessage(tr("Logger gestartet."), 5000)

    def start_iocheck(self):
        """IO-Check (eigenes Programm) mit den Steuerungen dieser Konfiguration starten (vorher speichern)."""
        if not self.save():
            return
        from plc_branding import launch
        if not launch(self, "iocheck", self.path, title=tr("IO-Check")):
            return
        self.statusBar().showMessage(tr("IO-Check gestartet."), 5000)

    def show_headless(self):
        """Laufende Headless-Logger anzeigen und beenden (plc_headless_dialog)."""
        from plc_headless_dialog import HeadlessDialog
        dlg = HeadlessDialog(self)
        dlg.exec()
        dlg.timer.stop()
        dlg.deleteLater()
        self.update_headless_label()

    def update_headless_label(self):
        """Anzahl laufender Headless-Logger im Reiter „Webserver & Headless“."""
        try:
            import plc_headless
            n = len(plc_headless.running_loggers())
        except Exception:
            n = 0
        self.lbl_headless.setText(tr("{0} laufen").format(n) if n else tr("keiner läuft"))

    # Verbindung zu jeder Steuerung aufbauen und deren Variablen einmal lesen; das Ergebnis (oder die Fehlermeldung)
    # steht in der Spalte 'Testwert'.
    def test_connection(self):
        plcs = self.collect_plcs()
        variables = self.collect()
        errors = []
        # Sanduhr-Cursor, solange verbunden/gelesen wird.
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for r, v in enumerate(variables):
                if v.formula:
                    self.table.item(r, C_TEST).setText(tr("berechnet"))
            for pi, p in enumerate(plcs):
                rows = [r for r, v in enumerate(variables)
                        if not v.formula and min(v.plc, len(plcs) - 1) == pi]
                if not rows:
                    continue
                d = get_driver(p.driver)
                try:
                    d.check_library()
                    values, errs = d.read_once(p, [variables[r] for r in rows])
                except Exception as e:
                    errors.append(f"{p.name} ({p.summary()}): {e}")
                    for r in rows:
                        self.table.item(r, C_TEST).setText(tr("Fehler: keine Verbindung"))
                    continue
                for r, val in zip(rows, values):
                    err = errs.get(variables[r].address)
                    self.table.item(r, C_TEST).setText(tr("Fehler: {0}").format(err) if err else f"{val:g}")
        finally:
            QApplication.restoreOverrideCursor()
        if errors:
            QMessageBox.critical(self, tr("Verbindung fehlgeschlagen"), "\n".join(errors))


# Programmstart: eigene Taskleisten-ID (Windows), Anwendung und Fenster erzeugen, Icon setzen, Ereignisschleife starten.
def main(argv=None):
    """Konfigurationsprogramm starten: Startbild (Auswahl der Datei), dann das Hauptfenster."""
    argv = sys.argv[1:] if argv is None else list(argv)
    set_windows_app_id("PLCDatenlogger.Konfiguration")
    from plc_common import qt_platform_setup
    qt_platform_setup()                      # Linux/Wayland: über XWayland (siehe dort)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from plc_i18n import install_qt
    install_qt(app)
    from plc_splash import choose
    explicit = argv[0] if argv else None
    current = os.path.abspath(explicit) if explicit else last_config_path()
    splash, res = choose("config", current, explicit=bool(explicit))
    if res is None:
        return 0
    w = ConfigWindow(res["path"] or None)
    if res["new"]:
        w.new_config()
    app.setWindowIcon(w.windowIcon())
    w.show()
    splash.close()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
