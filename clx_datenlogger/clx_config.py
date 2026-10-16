"""Konfigurationsprogramm: Projekt, Steuerungen, Diagramme, Y-Achsen & Variablen -> INI-Datei

Struktur: Diagramm > Y-Achse(n) > Variablen.
Variablen können über die Auswahlliste "Diagramm › Y-Achse" ODER per Drag & Drop im
Zuordnungsbaum (links) zugewiesen werden:
  * auf eine Y-Achse ziehen        -> Variable gehört zu dieser Achse
  * auf eine andere Variable ziehen -> Variable übernimmt deren Y-Achse
  * auf ein Diagramm ziehen         -> erste Y-Achse des Diagramms

Überblick über das Fenster
--------------------------
* Oben: Reiter für Projektname und Steuerungen (mehrere Logix-Steuerungen mit Name, IP, CIP-Pfad, Typ, Intervall),
  Aufzeichnung
  (CSV/Archiv), Anzeige (Fenster, Anordnung, Raster, Logo/Icon) sowie Webserver und Headless-Modus.
* Links: der Zuordnungsbaum (Diagramme > Y-Achsen > Variablen/Blöcke) mit den Eigenschaften der
  Auswahl (Name, Seite/Tab, Auto-Skalierung bzw. feste Grenzen der Y-Achse).
* Rechts: die Variablentabelle (Tag-Name, Typ, Farbe, Anzeigeoptionen, Formel) mit den Knöpfen
  für die Tag-Liste der Steuerung, Blöcke, berechnete Variablen und Verbindungstest.
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
import subprocess
import sys

# Qt-Grundbausteine: Qt (Konstanten), QTimer (verzögerte Aktionen), pyqtSignal (eigene Ereignisse).
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QKeySequence, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QColorDialog, QComboBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

# Eigene Module: Branding, Dialoge (Tag-Liste, Blöcke, Formeln), Datenmodell/INI, Formelprüfung.
# libplctag (clx_io) und pycomm3 (clx_taglist) werden erst bei Bedarf geladen: das Programm startet auch ohne sie.
from clx_branding import app_icon, set_windows_app_id
from clx_browser import TagBrowser
from clx_block_dialog import BlockEditor
from clx_common import (BASE_DIR, CPUS, LAYOUTS, PAGE_LAYOUTS, PALETTE, TYPES,
                       Axis, Block, Chart, Plc, Variable, check_tag_name, default_connection,
                       last_config_path, load_blocks, load_config, load_plcs,
                       remember_config_path, save_config,
                        program_command)
from clx_formula import check as check_formula
from clx_formula_dialog import FormulaEditor
from clx_events import EventLog, check_trigger, event_log_path, load_triggers, save_triggers
from clx_db import DB_TYPES, DEFAULT_PORTS, check_table_name, test_connection as test_db
from clx_i18n import N_, tr

# Benutzerdefinierte Datenrollen der Baumeinträge (QTreeWidgetItem.setData): ID der Variable, Art des Knotens,
# Diagramm- und Achsenindex. Der Wert von UserRole ist die erste freie Rolle.
ROLE_UID = Qt.ItemDataRole.UserRole.value
ROLE_KIND = ROLE_UID + 1   # "chart" | "axis" | "var"
ROLE_CI = ROLE_UID + 2     # Diagramm-Index
ROLE_AI = ROLE_UID + 3     # Achsen-Index

# Spalten der Variablentabelle (Nummern) und ihre Überschriften.
# Spalten der Variablentabelle
(C_NAME, C_PLC, C_AXIS, C_TAG, C_TYPE, C_COLOR, C_SHOW, C_BAR, C_TEST, C_FORMULA) = range(10)
VAR_COLS = [tr("Name"), tr("Steuerung"), tr("Diagramm › Y-Achse"), tr("Tag-Name"), tr("Typ"),
            tr("Farbe"), tr("Werteanzeige"), tr("Balken"), tr("Testwert"), tr("Formel")]

# Spalten der Steuerungen-Tabelle (Reiter „Projekt & Steuerungen“).
PLC_COLS = [tr("Name"), tr("IP-Adresse"), tr("CIP-Pfad"), tr("Typ"), tr("Intervall"), tr("Aktiv")]
(P_NAME, P_IP, P_PATH, P_CPU, P_INT, P_ON) = range(6)

# Dateifilter für die Dateidialoge: beliebige Dateinamen sind erlaubt.
FILE_FILTER = tr("Konfiguration (*.ini *.txt *.cfg);;Alle Dateien (*)")


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
    moved = pyqtSignal(list, int, int)   # uids, Diagramm-Index, Achsen-Index

    def __init__(self):
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
    """Konfigurationsfenster: bearbeitet die INI-Datei von clx_logger.py."""
    def __init__(self, path=None):
        super().__init__()
        self.resize(1300, 820)
        # Pfad der aktuell bearbeiteten INI-Datei: Startparameter, sonst die zuletzt benutzte Datei ('' = neu, ungespeichert).
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

        # ---- Reiter 1: Projekt und Steuerungen ----
        self.ed_project = QLineEdit()
        self.ed_project.setPlaceholderText(tr("z. B. Prüfstand 3"))
        self.ed_project.setToolTip(tr("Projektname: erscheint in den Fenstertiteln, im Webserver und in der Logdatei"))
        self.ed_project.textChanged.connect(lambda _t: self.update_title())
        # Tabelle der Steuerungen: jede Zeile = eine SPS mit eigenem Lese-Thread und eigenem Abtastintervall.
        self.plc_table = QTableWidget(0, len(PLC_COLS))
        self.plc_table.setHorizontalHeaderLabels(PLC_COLS)
        self.plc_table.horizontalHeader().setSectionResizeMode(P_NAME, QHeaderView.ResizeMode.Stretch)
        self.plc_table.horizontalHeader().setSectionResizeMode(P_IP, QHeaderView.ResizeMode.Stretch)
        self.plc_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.plc_table.itemChanged.connect(self.on_plc_item_changed)
        plc_btns = QHBoxLayout()
        for text, fn in [(tr("+ Steuerung"), self.add_plc), (tr("Steuerung entfernen"), self.remove_plc)]:
            bt = QPushButton(text); bt.clicked.connect(fn); plc_btns.addWidget(bt)
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
        tab_rec = QWidget()
        rl0 = QHBoxLayout(tab_rec); rl0.addLayout(form_rec1, 1); rl0.addSpacing(30); rl0.addLayout(form_rec2, 1)

        # ---- Reiter 3: Anzeige ----
        # Logo und Programm-Icon: Dateiauswahl mit Durchsuchen-Knopf (siehe _file_row).
        self.ed_logo = QLineEdit()
        self.ed_logo.setToolTip(tr("Bilddatei (PNG/SVG/JPG), wird im Logger rechts oben angezeigt"))
        self.ed_icon = QLineEdit()
        self.ed_icon.setToolTip(tr("Programm-Icon (PNG/ICO/SVG); leer = Logo bzw. Standard-Icon"))
        logo_row = self._file_row(self.ed_logo, tr("Logo wählen"))
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
        form_view1 = QFormLayout()
        form_view1.addRow(tr("Anzeigefenster (online):"), self.sp_win)
        form_view1.addRow(tr("Standard-Anordnung der Seiten:"), self.cb_layout)
        form_view1.addRow(tr("Diagramme auf einer Seite:"), self.cb_page)
        form_view1.addRow(tr("Raster-Spalten:"), self.sp_cols)
        form_view2 = QFormLayout()
        form_view2.addRow(tr("Logo (rechts oben):"), logo_row)
        form_view2.addRow(tr("Programm-Icon:"), icon_row)
        form_view2.addRow("", self.chk_bars)
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
        tab_web = QWidget()
        wl0 = QHBoxLayout(tab_web); wl0.addLayout(form_web1, 1); wl0.addSpacing(30); wl0.addLayout(form_web2, 1)

        # Die vier Reiter bilden den oberen Fensterbereich.
        self.tabs = QTabWidget()
        self.tabs.addTab(tab_plc, tr("Projekt && Steuerungen"))
        self.tabs.addTab(tab_rec, tr("Aufzeichnung"))
        self.tabs.addTab(tab_view, tr("Anzeige"))
        self.tabs.addTab(tab_web, tr("Webserver && Headless"))
        self.tabs.addTab(self._build_db_tab(), tr("Datenbank"))
        self.tabs.addTab(self._build_trigger_tab(), tr("Trigger && Ereignisse"))
        self.tabs.setMaximumHeight(210)

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

        # ---- Rechts: Variablentabelle und ihre Knöpfe ----
        # ---------- Variablen ----------
        self.table = QTableWidget(0, len(VAR_COLS))
        self.table.setHorizontalHeaderLabels(VAR_COLS)
        self.table.horizontalHeader().setSectionResizeMode(C_NAME, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # Änderung des Namens -> Baum aktualisieren; Doppelklick auf die Formelspalte -> Formeleditor.
        self.table.itemChanged.connect(self.on_var_item_changed)
        self.table.itemDoubleClicked.connect(self.on_var_double_click)
        right = QWidget()
        rl = QVBoxLayout(right); rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel(tr("<b>Variablen</b>")))
        rl.addWidget(self.table, 1)
        # Aktionen rund um Variablen: Symbolbaum, Blöcke, Formeln, manuelles Anlegen, Entfernen, Test.
        vbtn = QHBoxLayout()
        for text, fn in [(tr("Aus Tag-Liste wählen…"), self.open_tag_browser),
                         (tr("Blöcke (Blocklesemodus)…"), self.open_block_editor),
                         (tr("Berechnete Variable…"), self.add_computed),
                         (tr("Variable hinzufügen"), lambda: self.add_row()),
                         (tr("Entfernen"), self.remove_rows),
                         (tr("Verbindung testen"), self.test_connection)]:
            b = QPushButton(text); b.clicked.connect(fn); vbtn.addWidget(b)
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

        # Beim Start die vorhandene INI-Datei laden (Verbindung, Diagramme, Variablen, Blöcke) und das Fenster-Icon setzen.
        self.build_menu()
        self.fill(*load_config(self.path), blocks=load_blocks(self.path), plcs=load_plcs(self.path))
        self.triggers = load_triggers(self.path)
        self._update_trigger_summary()
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
                   (N_("Logger mit dieser Konfiguration &starten"), QKeySequence("Ctrl+R"), self.start_logger),
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
        # Menü „Sprache“ (Umschalten mit Neustart)
        from clx_i18n import fill_language_menu
        fill_language_menu(self.menuBar().addMenu(tr("Sprache")), self,
                           lambda: program_command("config", self.path) if self.path else program_command("config"))

    def update_title(self):
        """Fenstertitel: Projektname und Dateiname der Konfiguration."""
        proj = self.ed_project.text().strip() or tr("ohne Projektname")
        name = os.path.basename(self.path) if self.path else tr("neu, nicht gespeichert")
        self.setWindowTitle(tr("CLX Konfiguration – {0} – {1}").format(proj, name))

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
        t.setItem(r, P_IP, QTableWidgetItem(p.ip))
        # CIP-Pfad vom Ethernet-Modul zur CPU, z. B. 1,0 = Backplane, Steckplatz 0 (Micro800: leer).
        path = QTableWidgetItem(p.pfad)
        path.setToolTip(tr("CIP-Pfad zur CPU: 1,<Steckplatz> (Backplane-Port 1). CompactLogix: 1,0. Micro800: leer."))
        t.setItem(r, P_PATH, path)
        cpu = QComboBox()
        for key, text in CPUS.items():
            cpu.addItem(tr(text), key)
        cpu.setCurrentIndex(max(cpu.findData(p.cpu), 0))
        # Abtastintervall 10 ms ... 60 s; die tatsächlich erreichbare Rate hängt von Steuerung und Netz ab.
        iv = QSpinBox(); iv.setRange(10, 60000); iv.setSuffix(" ms"); iv.setValue(p.intervall_ms)
        iv.setProperty("timeout_ms", p.timeout_ms)     # Zeitlimit wird unverändert durchgereicht
        for col, w in ((P_CPU, cpu), (P_INT, iv)):
            t.setCellWidget(r, col, w)
        on = QTableWidgetItem()
        on.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        on.setCheckState(Qt.CheckState.Checked if p.enabled else Qt.CheckState.Unchecked)
        t.setItem(r, P_ON, on)
        t.blockSignals(False)

    def collect_plcs(self):
        """Steuerungen aus der Tabelle als Plc-Objekte (leere Namen werden zu „SPS n“)."""
        t = self.plc_table
        return [Plc(name=t.item(r, P_NAME).text().strip() or f"SPS {r + 1}",
                    ip=t.item(r, P_IP).text().strip(),
                    pfad=t.item(r, P_PATH).text().strip().replace(" ", ""),
                    cpu=t.cellWidget(r, P_CPU).currentData(),
                    intervall_ms=t.cellWidget(r, P_INT).value(),
                    timeout_ms=int(t.cellWidget(r, P_INT).property("timeout_ms") or 2000),
                    enabled=t.item(r, P_ON).checkState() == Qt.CheckState.Checked)
                for r in range(t.rowCount())]

    def plc_names(self):
        return [p.name for p in self.collect_plcs()]

    def plc_at(self, idx):
        """Steuerung idx (Plc) – für Verbindungstest, Blocktest und Tag-Liste."""
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

    def on_plc_item_changed(self, item):
        if item.column() == P_NAME:
            self.refresh_plc_combos()

    def add_plc(self):
        n = self.plc_table.rowCount()
        self.add_plc_row(Plc(name=f"SPS {n + 1}"))
        self.refresh_plc_combos()

    def remove_plc(self):
        """Markierte Steuerung entfernen. Variablen und Blöcke, die zu ihr gehörten, wandern zur ersten Steuerung."""
        r = self.plc_table.currentRow()
        if r < 0 or self.plc_table.rowCount() < 2:
            QMessageBox.information(self, tr("Steuerung entfernen"),
                                    tr("Bitte eine Steuerung markieren; mindestens eine muss bleiben."))
            return

        def fn(old):
            return 0 if old == r else (old - 1 if old > r else old)
        vals = [fn(self.plc_of_row(k)) for k in range(self.table.rowCount())]
        for b in self.blocks:
            b.plc = fn(b.plc)
        self.plc_table.removeRow(r)
        self.refresh_plc_combos(vals)
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
            start = self.ed_event_file.text() or event_log_path(self.collect_conn())
            p, _ = QFileDialog.getSaveFileName(self, tr("Ereignisdatei"), start, tr("Ereignisprotokoll (*.csv)"),
                                               options=QFileDialog.Option.DontConfirmOverwrite)
            if p:
                self.ed_event_file.setText(p if p.lower().endswith(".csv") else p + ".csv")
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

    def _update_trigger_summary(self):
        n = len(self.triggers)
        active = sum(1 for t in self.triggers if t.aktiv)
        if not n:
            self.lbl_triggers.setText(tr("keine Trigger angelegt"))
        else:
            names = ", ".join(t.name for t in self.triggers[:6]) + (" …" if n > 6 else "")
            self.lbl_triggers.setText(tr("{0} Trigger, davon {1} aktiv ({2})").format(n, active, names))

    def edit_triggers(self):
        from clx_trigger_dialog import TriggerEditor
        dlg = TriggerEditor(self, self.triggers, self.available_names())
        if dlg.exec():
            self.triggers = dlg.result_triggers
            self._update_trigger_summary()
            self.statusBar().showMessage(tr("Trigger geändert – wirksam nach dem Speichern und Neustart der Aufzeichnung."),
                                         8000)

    def show_events(self):
        from clx_event_viewer import EventViewer
        dlg = EventViewer(EventLog(event_log_path(self.collect_conn())), self)
        dlg.exec()

    def _build_db_tab(self):
        """Reiter „Datenbank“: Aufzeichnung zusätzlich (oder statt CSV) in SQLite, MariaDB oder TimescaleDB."""
        self.cb_db = QComboBox()
        for key, text in DB_TYPES.items():
            self.cb_db.addItem(tr(text), key)
        self.cb_db.currentIndexChanged.connect(lambda _i: self._update_db_fields())
        self.ed_db_host = QLineEdit()
        self.sp_db_port = QSpinBox(); self.sp_db_port.setRange(0, 65535); self.sp_db_port.setSpecialValueText(tr("Standard"))
        self.sp_db_port.setToolTip(tr("0 = Standard (MariaDB 3306, PostgreSQL/TimescaleDB 5432)"))
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
            path, _ = QFileDialog.getSaveFileName(self, tr("SQLite-Datenbank"), self.ed_db_file.text() or BASE_DIR,
                                                  tr("SQLite (*.db *.sqlite *.sqlite3);;Alle Dateien (*)"))
            if path:
                self.ed_db_file.setText(path)
        btn_file.clicked.connect(pick_db_file)
        file_row = QWidget(); fr = QHBoxLayout(file_row); fr.setContentsMargins(0, 0, 0, 0)
        fr.addWidget(self.ed_db_file); fr.addWidget(btn_file)
        self.chk_db_changes = QCheckBox(tr("Nur Änderungen schreiben (spätestens jede Minute)"))
        self.chk_db_changes.setToolTip(tr("Spart Platz: ein Wert wird nur geschrieben, wenn er sich geändert hat"))
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
        f2.addRow("", btn_test)
        w = QWidget()
        lay = QHBoxLayout(w); lay.addLayout(f1, 1); lay.addSpacing(30); lay.addLayout(f2, 1)
        self._db_server_widgets = [self.ed_db_host, self.sp_db_port, self.ed_db_name, self.ed_db_user, self.ed_db_pw]
        self._db_widgets = self._db_server_widgets + [self.ed_db_table, self.ed_db_file, btn_file,
                                                      self.chk_db_changes, btn_test]
        return w

    def _update_db_fields(self):
        """Felder je nach Datenbanktyp freigeben (Server-Felder für MariaDB/TimescaleDB, Datei für SQLite)."""
        typ = self.cb_db.currentData() or ""
        for wdg in self._db_widgets:
            wdg.setEnabled(bool(typ))
        for wdg in self._db_server_widgets:
            wdg.setEnabled(typ in ("mariadb", "timescale"))
        self.ed_db_file.setEnabled(typ == "sqlite")
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

    def _file_row(self, edit, title):
        """Zeile mit Eingabefeld und '…'-Knopf zur Auswahl einer Bilddatei (Logo/Icon)."""
        btn = QPushButton("…")
        btn.setFixedWidth(30)

        # Dateiauswahl für ein Eingabefeld (Logo/Icon): Dialog öffnen und den gewählten Pfad eintragen.
        def pick():
            p, _ = QFileDialog.getOpenFileName(
                self, title, edit.text() or BASE_DIR,
                tr("Bilder (*.png *.svg *.ico *.jpg *.jpeg *.bmp);;Alle Dateien (*)"))
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
            it = QTreeWidgetItem([f"▦ Block {b.name}: {b.count} × {b.dtype}{extra}"])
            it.setData(0, ROLE_KIND, "block")
            it.setData(0, ROLE_UID, bi)
            it.setIcon(0, swatch(b.color))
            it.setToolTip(0, b.address_range())
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            parent.addChild(it)
            # Elemente mit eigenem Ziel erscheinen zusätzlich unter der Achse, in der sie dargestellt werden.
            groups = {}
            for idx, key in sorted(b.targets.items()):
                groups.setdefault(key, []).append(idx)
            for key, idxs in groups.items():
                p2 = axis_items.get(key)
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
        c = self._pid_chart()
        on = bool(c and c.pid)
        self.btn_pid.setEnabled(on)
        if on and c.pid_iw and c.pid_stw:
            self.lbl_pid.setText(tr("{0}: Ist {1}, Stell {2}").format(c.pid_typ, c.pid_iw, c.pid_stw)
                                 + (tr(", Soll {0}").format(c.pid_sw) if c.pid_sw else ""))
        else:
            self.lbl_pid.setText("")

    def on_pid_toggled(self, on):
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
        from clx_pid_dialog import PidSetupDialog
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
        # Tag-Name (Text) und Datentyp.
        typ = QComboBox(); typ.addItems(list(TYPES)); typ.setCurrentText(v.dtype)
        typ.setToolTip(tr("Datentyp des Tags; für ein Bit eines Integers (z. B. Status.3) BOOL wählen"))
        for col, w in [(C_PLC, plc), (C_AXIS, axis), (C_TYPE, typ)]:
            self.table.setCellWidget(r, col, w)
        tag = QTableWidgetItem(v.tag)
        tag.setToolTip(tr("Tag-Name wie in Studio 5000, z. B. Temp, Program:Main.Druck, Motor[2].Drehzahl, Status.3"))
        self.table.setItem(r, C_TAG, tag)

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
        if refresh:
            self.refresh_tree()

    # ---------------------------------------------------------------------------------------
    # Blöcke (Blocklesemodus)
    # ---------------------------------------------------------------------------------------
    # ---------- Blöcke (Blocklesemodus) ----------
    def block_names(self):
        """Namen aller Block-Elemente (Standard: Name[0] … Name[n-1], oder eigene Namen)."""
        return [v.name for b in self.blocks for v in b.variables()]

    # Blockeditor öffnen; bei OK die Blöcke übernehmen und den Baum aktualisieren.
    def open_block_editor(self):
        # Namen, die für Block-Elemente nicht mehr in Frage kommen (vorhandene Variablen).
        taken = {self.table.item(r, C_NAME).text() for r in range(self.table.rowCount())}
        flat = self.flat()
        sel = self.selected_target()
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
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

    # Markierte Zeilen von unten nach oben löschen.
    def remove_rows(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
        self.refresh_tree()

    # Farbe per Farbdialog ändern; Knopf und Baumsymbol werden aktualisiert.
    def pick_color(self, btn):
        c = QColorDialog.getColor(QColor(btn.property("color")), self)
        if c.isValid():
            btn.setProperty("color", c.name())
            btn.setStyleSheet(f"background-color: {c.name()}")
            self.refresh_tree()

    def pick_arch_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("Archiv-Ordner wählen"), self.ed_arch.text() or BASE_DIR)
        if d:
            self.ed_arch.setText(d)

    def pick_dir(self):
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
        for p in (plcs or [Plc(ip=conn["ip"], pfad=conn.get("pfad", "1,0"), cpu=conn.get("cpu", "controllogix"),
                               intervall_ms=conn["intervall_ms"])]):
            self.add_plc_row(p)
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
        self.ed_event_file.setText(conn.get("ereignis_datei", ""))
        self._update_db_fields()
        self.ed_logo.setText(conn.get("logo", ""))
        self.ed_icon.setText(conn.get("icon", ""))
        self.cb_layout.setCurrentIndex(max(self.cb_layout.findData(conn["anordnung"]), 0))
        self.cb_page.setCurrentIndex(max(self.cb_page.findData(conn.get("seite_anordnung", "")), 0))
        self.sp_cols.setValue(int(conn.get("raster_spalten", 0)))
        self.chk_bars.setChecked(bool(conn["balken"]))
        self.chk_web.setChecked(bool(conn.get("web_aktiv", 0)))
        self.ed_web_host.setText(conn.get("web_host", "0.0.0.0"))
        self.sp_web_port.setValue(int(conn.get("web_port", 8080)))
        self.ed_web_token.setText(conn.get("web_token", ""))
        self.sp_web_int.setValue(int(conn.get("web_intervall_ms", 1000)))
        self.chk_headless.setChecked(bool(conn.get("headless", 0)))
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
        self.update_title()

    # Verbindungs- und Anzeigeeinstellungen aus den Feldern als Wörterbuch (für die INI-Datei und für Tests).
    # Die Steuerungen stehen getrennt in collect_plcs(); ip/pfad/cpu/intervall_ms spiegeln die erste Steuerung.
    def collect_conn(self):
        first = self.collect_plcs()[0]
        return {"ip": first.ip, "pfad": first.pfad, "cpu": first.cpu, "intervall_ms": first.intervall_ms,
                "projekt": self.ed_project.text().strip(),
                "csv_ordner": self.ed_dir.text().strip() or "logs",
                "fenster_s": self.sp_win.value(),
                "anordnung": self.cb_layout.currentData(),
                "seite_anordnung": self.cb_page.currentData() or "",
                "raster_spalten": self.sp_cols.value(),
                "balken": 1 if self.chk_bars.isChecked() else 0,
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
                "logo": self.ed_logo.text().strip(),
                "icon": self.ed_icon.text().strip(),
                "web_aktiv": 1 if self.chk_web.isChecked() else 0,
                "web_host": self.ed_web_host.text().strip() or "0.0.0.0",
                "web_port": self.sp_web_port.value(),
                "web_token": self.ed_web_token.text().strip(),
                "web_intervall_ms": self.sp_web_int.value(),
                "headless": 1 if self.chk_headless.isChecked() else 0,
                "ereignis_datei": self.ed_event_file.text().strip()}

    # Alle Tabellenzeilen als Variable-Objekte einsammeln (einschließlich Zuordnung und Formel).
    def collect(self):
        t = self.table
        out = []
        for r in range(t.rowCount()):
            ci, ai = self.assign_of_row(r)
            out.append(Variable(
                name=t.item(r, C_NAME).text().strip(),
                plc=t.cellWidget(r, C_PLC).currentIndex(),
                tag=t.item(r, C_TAG).text().strip(),
                dtype=t.cellWidget(r, C_TYPE).currentText(),
                color=t.cellWidget(r, C_COLOR).property("color"),
                show_value=t.item(r, C_SHOW).checkState() == Qt.CheckState.Checked,
                chart=ci, axis=ai,
                bar=t.item(r, C_BAR).checkState() == Qt.CheckState.Checked,
                formula=t.item(r, C_FORMULA).text(),
            ))
        return out

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

    # Tag-Liste der Steuerung öffnen; gewählte Tags werden Variablen, gewählte Arrays Blöcke.
    def open_tag_browser(self):
        flat = self.flat()
        sel = self.selected_target()
        default = flat.index(sel) if sel in flat else 0
        # Bei mehreren Steuerungen zuerst die Steuerung wählen (Vorgabe: Steuerung der markierten Zeile).
        names = self.plc_names()
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        plc = self.plc_of_row(rows[0]) if rows else 0
        if len(names) > 1:
            name, ok = QInputDialog.getItem(self, tr("Steuerung wählen"), tr("Tags aus Steuerung:"), names,
                                            min(plc, len(names) - 1), False)
            if not ok:
                return
            plc = names.index(name)
        # Tags, die für diese Steuerung schon angelegt sind (auch als Block-Element), werden im Dialog gesperrt.
        existing = {self.table.item(r, C_TAG).text().strip() for r in range(self.table.rowCount())
                    if not self.table.item(r, C_FORMULA).text() and self.plc_of_row(r) == plc}
        existing |= {v.tag for b in self.blocks if b.plc == plc for v in b.variables()}
        dlg = TagBrowser(self, self.plc_at(plc), existing, self.flat_labels(), default)
        if not dlg.exec():
            return
        taken = ({self.table.item(r, C_NAME).text() for r in range(self.table.rowCount())}
                 | set(self.block_names()))
        ci, ai = flat[dlg.target_index] if 0 <= dlg.target_index < len(flat) else (0, 0)
        # Neue Variablen: Name = Tag-Name (bei Gleichheit mit _2, _3 … eindeutig gemacht).
        for path, dtype in dlg.result_tags:
            name, k = path, 2
            while name in taken:
                name, k = f"{path}_{k}", k + 1
            taken.add(name)
            self.add_row(Variable(name=name, plc=plc, tag=path, dtype=dtype,
                                  color=PALETTE[self.table.rowCount() % len(PALETTE)],
                                  chart=ci, axis=ai), refresh=False)
        # Arrays als Blöcke: Blockname aus dem letzten Teil des Tag-Namens.
        bnames = {b.name for b in self.blocks}
        for path, dtype, start, count in dlg.result_blocks:
            base = re.sub(r"[^\w]+", "_", path.split(".")[-1]).strip("_") or "Block"
            bname, k = base, 2
            while bname in bnames or any(f"{bname}[{i}]" in taken for i in range(count)):
                bname, k = f"{base}_{k}", k + 1
            bnames.add(bname)
            self.blocks.append(Block(name=bname, tag=path, start=start, count=count, dtype=dtype, plc=plc,
                                     chart=ci, axis=ai, color=PALETTE[len(self.blocks) % len(PALETTE)]))
        self.refresh_tree()
        self.statusBar().showMessage(
            tr("{0} Variablen und {1} Blöcke übernommen – mit „Verbindung testen“ prüfen.").format(len(dlg.result_tags), len(dlg.result_blocks)), 8000)

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
        # Steuerungen: eindeutige Namen, IP-Adresse vorhanden.
        plcs = self.collect_plcs()
        pnames = [p.name for p in plcs]
        if len(set(pnames)) != len(pnames) or any(";" in n or "[" in n or "]" in n for n in pnames):
            QMessageBox.warning(self, tr("Steuerungen prüfen"),
                                tr("Die Namen der Steuerungen müssen eindeutig sein und dürfen kein ; [ ] enthalten."))
            return False
        if any(not p.ip for p in plcs):
            QMessageBox.warning(self, tr("Steuerungen prüfen"), tr("Jede Steuerung braucht eine IP-Adresse."))
            return False
        variables = self.collect()
        # Namen müssen eindeutig sein; Block-Elemente zählen mit.
        names = [v.name for v in variables] + self.block_names()
        if any(not n or ";" in n for n in names) or len(set(names)) != len(names):
            QMessageBox.warning(self, tr("Namen prüfen"),
                                tr("Variablennamen müssen eindeutig, nicht leer und ohne ';' sein."))
            return False
        # Tag-Namen formal prüfen (ob es sie gibt, zeigt erst „Verbindung testen“).
        bad = [f"{v.name}: „{v.tag}“" for v in variables if not v.formula and not check_tag_name(v.tag)]
        bad += [f"Block {b.name}: „{b.tag}“" for b in self.blocks if not check_tag_name(b.tag)]
        if bad:
            QMessageBox.warning(self, tr("Tag-Namen prüfen"),
                                tr("Ungültige oder leere Tag-Namen:\n") + "\n".join(bad[:20])
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

    # „Speichern unter“: beliebiger Dateiname; fehlt die Endung, wird .ini angehängt.
    def save_as(self):
        start = self.path or os.path.join(BASE_DIR, "clx_config.ini")
        p, _ = QFileDialog.getSaveFileName(self, tr("Konfiguration speichern unter"), start, FILE_FILTER)
        if not p:
            return False
        if not os.path.splitext(p)[1]:
            p += ".ini"
        return self._write(os.path.abspath(p))

    # Konfiguration aus Datei p laden (INI oder TXT, beliebiger Name). Rückgabe: True bei Erfolg.
    def load_path(self, p):
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
        try:
            subprocess.Popen(program_command("logger", self.path))
        except OSError as e:
            QMessageBox.critical(self, tr("Logger starten"), tr("Der Logger konnte nicht gestartet werden:\n{0}").format(e))
            return
        self.statusBar().showMessage(tr("Logger gestartet."), 5000)

    # Verbindung zu jeder Steuerung aufbauen und deren Variablen einmal lesen; das Ergebnis (oder die Fehlermeldung)
    # steht in der Spalte 'Testwert'.
    def test_connection(self):
        try:
            from clx_io import read_once
            from clx_io import get_lib
            get_lib()
        except Exception as e:
            QMessageBox.critical(self, tr("libplctag"), tr("Die Bibliothek libplctag konnte nicht geladen werden:\n{0}").format(e))
            return
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
                try:
                    values, errs = read_once(p, [variables[r] for r in rows])
                except Exception as e:
                    errors.append(f"{p.name} ({p.ip}, Pfad {p.pfad or '–'}): {e}")
                    for r in rows:
                        self.table.item(r, C_TEST).setText(tr("Fehler: keine Verbindung"))
                    continue
                for r, val in zip(rows, values):
                    err = errs.get(variables[r].tag)
                    self.table.item(r, C_TEST).setText(tr("Fehler: {0}").format(err) if err else f"{val:g}")
        finally:
            QApplication.restoreOverrideCursor()
        if errors:
            QMessageBox.critical(self, tr("Verbindung fehlgeschlagen"), "\n".join(errors))


# Programmstart: eigene Taskleisten-ID (Windows), Anwendung und Fenster erzeugen, Icon setzen, Ereignisschleife starten.
def main(argv=None):
    """Konfigurationsprogramm starten: Startbild (Auswahl der Datei), dann das Hauptfenster."""
    argv = sys.argv[1:] if argv is None else list(argv)
    set_windows_app_id("CLXDatenlogger.Konfiguration")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from clx_i18n import install_qt
    install_qt(app)
    from clx_splash import choose
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
