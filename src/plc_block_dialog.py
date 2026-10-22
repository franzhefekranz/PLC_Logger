# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Editor für Blöcke (Blocklesemodus): zusammenhängende Werte gleichen Formats, gemeinsam gelesen.

Ein Block ist ein Bereich der Steuerung – je nach Treiber ab einer Startadresse (z. B. ``DB10.DBD0`` … oder
``40001`` …) oder ein Ausschnitt eines Arrays (z. B. ``Messwerte[10]`` … ``Messwerte[29]``). Er wird gemeinsam
gelesen (meist mit EINER Anfrage); jedes Element wird zu einer Variable ``<n>[i]`` (Steuerung, Farbe, Werteanzeige
und Balken gelten für den ganzen Block). Diagramm und Y-Achse gelten zunächst ebenfalls für den ganzen Block, lassen
sich aber im Baum für jedes Element einzeln ändern.

Aufbau des Dialogs
------------------
* Oben eine Tabelle mit einer Zeile je Block (Name, Steuerung, Startadresse/Array, erster Index, Format, Anzahl,
  Zuordnung, Farbe, Anzeigeoptionen). Die Spalte "Bereich" wird automatisch berechnet.
* Unten ein Baum "Block > Elemente": hier lassen sich die Namen und das Ziel (Diagramm › Y-Achse)
  einzelner Elemente ändern.
  Die Elemente eines Blocks werden erst beim Aufklappen erzeugt (große Blöcke bleiben schnell).
* Schaltfläche "Markierten Block testen": liest den Block einmal aus der Steuerung und zeigt die Lesezeit.

Eigene Elementnamen werden je Zeile in ``names_of`` gesammelt (Zeilen-ID -> {Index: Name}), abweichende
Ziele in ``targets_of`` (Zeilen-ID -> {Index: (Diagramm, Achse)}); beim Schließen landen sie in
``Block.names`` bzw. ``Block.targets``. Ergebnis nach OK: ``result_blocks``.
"""


import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QPushButton, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

# Gemeinsames Datenmodell: Block (mit variables()); gelesen wird mit dem Treiber der Steuerung (plc_treiber).
from plc_common import PALETTE, Block, get_driver
from plc_i18n import tr

# Spaltenüberschriften der Blocktabelle und zugehörige Spaltennummern (C_...).
COLS = [tr("Name"), tr("Steuerung"), tr("Startadresse / Array"), tr("Erster Index"), tr("Format"), tr("Anzahl"),
        tr("Diagramm › Y-Achse"), tr("Farbe"), tr("Werteanzeige"), tr("Balken"), tr("Bereich")]
(C_NAME, C_PLC, C_TAG, C_START, C_TYPE, C_COUNT, C_AXIS, C_COLOR, C_SHOW, C_BAR, C_INFO) = range(11)
# Spalten des Elementbaums: Nummer, Name, Adresse, Format, Ziel (Diagramm › Y-Achse; Auswahlliste).
T_NAME, T_ADDR, T_TYPE, T_TARGET = 1, 2, 3, 4

# Hilfetext oben im Dialog (HTML).
HELP = (
    tr("Ein <b>Block</b> liest <i>Anzahl</i> zusammenhängende Werte gleichen <i>Formats</i> gemeinsam (meist mit einer "
       "einzigen Anfrage, schneller als einzelne Variablen). Je nach Treiber der Steuerung ist die <b>Startadresse</b> "
       "die Adresse des ersten Werts (z. B. <code>DB10.DBD0</code>, <code>40001</code>; die Elemente folgen lückenlos) "
       "oder der Name eines <b>Arrays</b> ohne Index (z. B. <code>Messwerte</code>, <code>Mess_DB.Werte</code>) mit dem "
       "<i>ersten Index</i>. Jedes Element wird zur Variable <code>Name[0]</code>, <code>Name[1]</code>, … und kann in "
       "Formeln verwendet werden. Im <b>Baum</b> unten lassen sich die <b>Namen der einzelnen Elemente</b> per Doppelklick "
       "ändern (leer = Standardname <code>Name[i]</code>) und einzelne Elemente einem <b>anderen Diagramm bzw. einer "
       "anderen Y-Achse</b> zuordnen (<i>wie Block</i> = Ziel des Blocks).")
)


class BlockEditor(QDialog):
    """Dialog zum Bearbeiten aller Blöcke (Blocklesemodus) samt Namen der Elemente."""
    # blocks: bestehende Blöcke; flat/labels: wählbare Ziele (Diagramm, Achse) samt Beschriftung;
    # get_conn(plc_index): Funktion, die die Steuerung (plc_common.Plc) liefert (für den Test); taken: schon vergebene
    # Variablennamen; default_target: Vorauswahl für neue Blöcke; plc_names: Namen der Steuerungen; default_plc: Vorauswahl.
    def __init__(self, parent, blocks, flat, labels, get_conn, taken, default_target=0,
                 plc_names=None, default_plc=0):
        """flat: Liste (Diagramm, Achse); labels: Beschriftungen dazu; get_conn: liefert die
        Verbindungsdaten einer Steuerung; taken: bereits vergebene Variablennamen."""
        super().__init__(parent)
        self.setWindowTitle(tr("Blöcke (Blocklesemodus)"))
        self.resize(1300, 760)
        self.flat, self.labels = list(flat), list(labels)
        self.get_conn = get_conn
        self.taken = set(taken)
        self.default_target = default_target
        self.plc_names = list(plc_names or ["SPS 1"])
        self.default_plc = default_plc
        self.result_blocks = []
        # Eigene Elementnamen je Tabellenzeile, über eine stabile Zeilen-ID erreichbar (Zeilennummern ändern sich beim Löschen).
        self.names_of = {}        # Zeilen-ID -> eigene Elementnamen {Index: Name}
        self.targets_of = {}      # Zeilen-ID -> abweichende Ziele einzelner Elemente {Index: (Diagramm, Achse)}
        self._uid = 0             # Zähler für Zeilen-IDs
        # Während der Baum programmatisch gefüllt wird, sollen Änderungssignale nichts bewirken.
        self._filling = False     # True, solange der Baum befüllt wird (Änderungssignale ignorieren)

        info = QLabel(HELP)
        info.setWordWrap(True)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.horizontalHeader().setSectionResizeMode(C_NAME, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(C_INFO, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self.expand_selected)

        # Baum unten: Block -> Elemente. Spalte 1 (Name) der Elemente ist editierbar.
        # Baum: Block > Elemente mit editierbarem Namen (Kinder werden erst beim Aufklappen erzeugt)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels([tr("Block / Element"), tr("Name (Doppelklick = ändern)"), tr("Adresse"), tr("Format"),
                                   tr("Diagramm › Y-Achse")])
        self.tree.setColumnWidth(0, 200)
        self.tree.setColumnWidth(1, 320)
        self.tree.setColumnWidth(2, 160)
        self.tree.setColumnWidth(3, 80)
        self.tree.itemExpanded.connect(self.populate)
        self.tree.itemChanged.connect(self.on_name_edited)
        # Der Baum wird nicht bei jeder Änderung sofort neu aufgebaut, sondern 300 ms nach der letzten (Timer).
        self.timer = QTimer(self)                 # Baum erst kurz nach der letzten Änderung neu aufbauen
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.rebuild_tree)

        b_add = QPushButton(tr("Block hinzufügen"))
        b_add.clicked.connect(lambda: self.add_row(None))
        b_del = QPushButton(tr("Entfernen"))
        b_del.clicked.connect(self.remove_rows)
        b_test = QPushButton(tr("Markierten Block testen"))
        b_test.setToolTip(tr("Liest den Block einmal aus der SPS und zeigt die ersten Werte und die Lesezeit"))
        b_test.clicked.connect(self.test_block)
        btns = QHBoxLayout()
        for b in (b_add, b_del, b_test):
            btns.addWidget(b)
        btns.addStretch(1)

        # Standardknöpfe OK/Abbrechen; OK läuft über accept_checked(), das die Eingaben prüft.
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept_checked)
        box.rejected.connect(self.reject)

        # Fensteraufbau: oben Hilfetext, in der Mitte ein teilbarer Bereich (Tabelle | Baum), unten OK/Abbrechen.
        lay = QVBoxLayout(self)
        lay.addWidget(info)
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(self.table, 1)
        tl.addLayout(btns)
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(QLabel(tr("<b>Elemente der Blöcke</b> – Namen und Ziel (Diagramm › Y-Achse) der einzelnen Werte bearbeiten")))
        bl.addWidget(self.tree, 1)
        # Alle Elemente des markierten Blocks auf einmal einem Ziel zuordnen (oder zurück auf 'wie Block').
        self.cb_all = QComboBox()
        self.cb_all.addItem(tr("(wie Block)"))
        self.cb_all.addItems(self.labels)
        b_all = QPushButton(tr("Für alle Elemente des markierten Blocks setzen"))
        b_all.clicked.connect(self.set_all_targets)
        row_all = QHBoxLayout()
        row_all.addWidget(QLabel(tr("Ziel:")))
        row_all.addWidget(self.cb_all, 1)
        row_all.addWidget(b_all)
        bl.addLayout(row_all)
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(top)
        split.addWidget(bottom)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        lay.addWidget(split, 1)
        lay.addWidget(box)
        # Vorhandene Blöcke als Tabellenzeilen anlegen und den Baum aufbauen.
        for b in blocks:
            self.add_row(b)
        self.rebuild_tree()

    # ---------------- Zeilen ----------------
    # Eine Zeile (Block) hinzufügen. b=None: neuer Standardblock mit freiem Namen und den Vorgaben des gewählten Ziels.
    def add_row(self, b):
        """Neue Tabellenzeile für Block b anlegen (b=None: neuer Standardblock)."""
        r = self.table.rowCount()
        if b is None:
            ci, ai = self.flat[self.default_target] if self.flat else (0, 0)
            b = Block(name=self.unique_name(), chart=ci, axis=ai, plc=self.default_plc,
                      color=PALETTE[r % len(PALETTE)])
        # Signale blockieren, solange die Zeile aufgebaut wird (sonst würden halbfertige Zeilen ausgewertet).
        self.table.blockSignals(True)
        self.table.insertRow(r)
        # Name als Tabellenelement; in UserRole steht die stabile Zeilen-ID, unter der die eigenen Elementnamen liegen.
        name_item = QTableWidgetItem(b.name)
        self._uid += 1
        name_item.setData(Qt.ItemDataRole.UserRole, self._uid)       # stabile ID der Zeile
        self.names_of[self._uid] = dict(b.names)
        self.targets_of[self._uid] = dict(b.targets)
        self.table.setItem(r, C_NAME, name_item)
        # Steuerung, aus der der Block gelesen wird.
        plc = QComboBox(); plc.addItems(self.plc_names)
        plc.setCurrentIndex(min(max(b.plc, 0), len(self.plc_names) - 1))
        plc.currentIndexChanged.connect(lambda _i, w=plc: self.update_row_driver(self._row_of(w)))

        # Je Spalte ein passendes Eingabeelement: Text für Startadresse/Array, Auswahllisten für Format/Ziel, Zahlenfelder.
        tag = QTableWidgetItem(b.address)
        self.table.setItem(r, C_TAG, tag)
        start = QSpinBox(); start.setRange(0, 1_000_000); start.setValue(b.start)
        # Formate: die Blockformate des Treibers der Steuerung (siehe update_row_driver).
        typ = QComboBox(); typ.setProperty("dtype", b.dtype)
        # Mindestens 1, höchstens 1000 Elemente je Block.
        count = QSpinBox(); count.setRange(1, 1000); count.setValue(b.count)
        axis = QComboBox(); axis.addItems(self.labels)
        axis.setCurrentIndex(self.flat.index((b.chart, b.axis)) if (b.chart, b.axis) in self.flat else 0)
        axis.currentIndexChanged.connect(lambda _i: self.schedule_tree())
        # Farbe: Knopf, dessen Hintergrund die Farbe zeigt; der Wert steht in der Eigenschaft 'color'.
        btn = QPushButton()
        btn.setProperty("color", b.color)
        btn.setStyleSheet(f"background-color: {b.color}")
        btn.clicked.connect(lambda _=False, x=btn: self.pick_color(x))
        # Änderungen von Format und Zahlenfeldern aktualisieren den berechneten Bereich.
        typ.currentTextChanged.connect(lambda _t: self.update_info(self._row_of(typ)))
        for w in (start, count):
            w.valueChanged.connect(lambda _v, x=w: self.update_info(self._row_of(x)))

        # Widgets in die Zellen setzen.
        for col, w in [(C_PLC, plc), (C_START, start), (C_TYPE, typ), (C_COUNT, count), (C_AXIS, axis),
                       (C_COLOR, btn)]:
            self.table.setCellWidget(r, col, w)
        # Werteanzeige/Balken: Kontrollkästchen als Tabellenelement.
        for col, state in ((C_SHOW, b.show_value), (C_BAR, b.bar)):
            it = QTableWidgetItem()
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)
            self.table.setItem(r, col, it)
        # Berechnete, nur lesbare Spalte 'Adressbereich'.
        info = QTableWidgetItem("")
        info.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.setItem(r, C_INFO, info)
        # Signale wieder freigeben, Treiberangaben setzen und die Info berechnen.
        self.table.blockSignals(False)
        self.update_row_driver(r)

    def driver_of_row(self, r):
        """Treiber der Steuerung, die in Zeile r ausgewählt ist (bestimmt Adressformat und Datentypen)."""
        return get_driver(self.get_conn(self.table.cellWidget(r, C_PLC).currentIndex()).driver)

    def update_row_driver(self, r):
        """Formate, Hinweis und „Erster Index“ an den Treiber der gewählten Steuerung anpassen."""
        if r < 0:
            return
        d = self.driver_of_row(r)
        typ = self.table.cellWidget(r, C_TYPE)
        cur = typ.currentText() or typ.property("dtype") or d.default_type
        types = list(d.block_types or d.types)
        typ.blockSignals(True)
        typ.clear()
        typ.addItems(types)
        typ.setCurrentText(cur if cur in types else (d.default_type if d.default_type in types else types[0]))
        typ.blockSignals(False)
        self.table.cellWidget(r, C_START).setEnabled(d.block_uses_index)
        self.table.cellWidget(r, C_START).setToolTip(
            tr("Erster Array-Index") if d.block_uses_index else tr("Bei diesem Treiber ohne Bedeutung (Startadresse)"))
        item = self.table.item(r, C_TAG)
        self.table.blockSignals(True)
        item.setToolTip(f"{d.name}: {tr(d.block_hint)}" if d.block_hint else d.name)
        self.table.blockSignals(False)
        self.update_info(r)

    def _on_item_changed(self, item):
        """Text in der Tabelle geändert: beim Array-Tag den Bereich neu berechnen, sonst nur den Baum."""
        if item.column() == C_TAG:
            self.update_info(item.row())
        elif item.column() != C_INFO:
            self.schedule_tree()

    # Zeile finden, in der das Zellen-Widget 'widget' steht (die Signale der Widgets kennen ihre Zeile nicht).
    def _row_of(self, widget):
        """Nummer der Tabellenzeile, in der das Zellen-Widget steht (-1: nicht gefunden)."""
        for r in range(self.table.rowCount()):
            for c in range(self.table.columnCount()):
                if self.table.cellWidget(r, c) is widget:
                    return r
        return -1

    # Freien Standardnamen finden: Block1, Block2, ...
    def unique_name(self):
        """Freien Blocknamen 'BlockN' finden."""
        used = {self.table.item(r, C_NAME).text() for r in range(self.table.rowCount())}
        k = 1
        while f"Block{k}" in used:
            k += 1
        return f"Block{k}"

    # Markierte Zeilen von unten nach oben löschen (damit die Zeilennummern gültig bleiben).
    def remove_rows(self):
        """Markierte Blöcke löschen."""
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    # Farbdialog; die gewählte Farbe wird im Knopf (Eigenschaft + Hintergrund) gespeichert.
    def pick_color(self, btn):
        """Farbe des Blocks per Farbdialog wählen."""
        c = QColorDialog.getColor(QColor(btn.property("color")), self)
        if c.isValid():
            btn.setProperty("color", c.name())
            btn.setStyleSheet(f"background-color: {c.name()}")

    # Aus den Widgets einer Tabellenzeile ein Block-Objekt bauen (einschließlich eigener Elementnamen).
    def block_of_row(self, r):
        """Block-Objekt aus Tabellenzeile r erzeugen."""
        t = self.table
        # Ziel (Diagramm, Achse) aus dem Index der Auswahlliste ableiten.
        ci, ai = self.flat[t.cellWidget(r, C_AXIS).currentIndex()] if self.flat else (0, 0)
        return Block(
            name=t.item(r, C_NAME).text().strip(),
            plc=t.cellWidget(r, C_PLC).currentIndex(),
            targets=self.targets_for_row(r, (ci, ai)),
            address=t.item(r, C_TAG).text().strip(),
            start=t.cellWidget(r, C_START).value(),
            driver=self.get_conn(t.cellWidget(r, C_PLC).currentIndex()).driver,
            dtype=t.cellWidget(r, C_TYPE).currentText(),
            count=t.cellWidget(r, C_COUNT).value(),
            chart=ci, axis=ai,
            color=t.cellWidget(r, C_COLOR).property("color"),
            show_value=t.item(r, C_SHOW).checkState() == Qt.CheckState.Checked,
            bar=t.item(r, C_BAR).checkState() == Qt.CheckState.Checked,
            names=self.names_for_row(r))

    # Info-Spalte aktualisieren (Adressbereich + Größe) und den Baum zur Neuerstellung vormerken.
    def update_info(self, r):
        """Info-Spalte der Zeile r (Adressbereich, Größe) neu berechnen."""
        # Zeile existiert nicht (mehr) oder ist noch im Aufbau.
        if r < 0 or self.table.item(r, C_INFO) is None:
            return
        b = self.block_of_row(r)
        size = b.count * get_driver(b.driver).type_size(b.dtype)
        self.table.item(r, C_INFO).setText(tr("{0}   ({1} Bytes)").format(b.address_range(), size) if b.address else "")
        self.schedule_tree()

    # ---------------- Baum mit editierbaren Elementnamen ----------------
    # Stabile ID der Zeile r (siehe add_row).
    def row_uid(self, r):
        """Zeilen-ID der Zeile r."""
        return self.table.item(r, C_NAME).data(Qt.ItemDataRole.UserRole)

    # Zeilennummer zur ID suchen (-1, wenn die Zeile gelöscht wurde).
    def row_of_uid(self, uid):
        """Zeilennummer zu einer Zeilen-ID."""
        for r in range(self.table.rowCount()):
            if self.row_uid(r) == uid:
                return r
        return -1

    def names_for_row(self, r):
        """Eigene Elementnamen der Zeile r (nur gültige Indizes, nur abweichende Namen)."""
        # Die Anzahl begrenzt die gültigen Indizes (wurde der Block verkleinert, verfallen überzählige Namen).
        count = self.table.cellWidget(r, C_COUNT).value() if self.table.cellWidget(r, C_COUNT) else 0
        return {i: n for i, n in self.names_of.get(self.row_uid(r), {}).items() if 0 <= i < count and n}

    def targets_for_row(self, r, block_target):
        """Abweichende Ziele einzelner Elemente der Zeile r (nur gültige Indizes und gültige Ziele, die nicht
        dem Ziel des Blocks entsprechen)."""
        count = self.table.cellWidget(r, C_COUNT).value() if self.table.cellWidget(r, C_COUNT) else 0
        return {i: t for i, t in self.targets_of.get(self.row_uid(r), {}).items()
                if 0 <= i < count and t in self.flat and t != block_target}

    def schedule_tree(self):
        """Baum nach einer Änderung verzögert neu aufbauen (fasst schnelle Änderungen zusammen)."""
        self.timer.start(300)

    def rebuild_tree(self):
        """Baum neu aufbauen; bisher aufgeklappte Blöcke bleiben aufgeklappt."""
        # Aufgeklappte Blöcke merken (anhand der Zeilen-ID), damit der Baum nach dem Neuaufbau gleich aussieht.
        expanded = {self.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                    for i in range(self.tree.topLevelItemCount())
                    if self.tree.topLevelItem(i).isExpanded()}
        self._filling = True
        self.tree.clear()
        # Für jede Tabellenzeile einen Block-Knoten erzeugen (noch ohne Elemente).
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, C_COUNT) is None:      # Zeile noch im Aufbau
                continue
            b = self.block_of_row(r)
            top = QTreeWidgetItem([b.name, "", b.address_range(), f"{b.count} × {b.dtype}"])
            top.setData(0, Qt.ItemDataRole.UserRole, self.row_uid(r))
            # Ohne Kind-Element würde kein Aufklapp-Pfeil angezeigt; der leere Platzhalter wird beim Aufklappen ersetzt.
            top.addChild(QTreeWidgetItem())                    # Platzhalter: zeigt den Aufklapp-Pfeil
            self.tree.addTopLevelItem(top)
        self._filling = False
        # Zuvor aufgeklappte Blöcke wieder aufklappen (das löst populate() aus).
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.data(0, Qt.ItemDataRole.UserRole) in expanded:
                it.setExpanded(True)                           # löst populate() aus

    def expand_selected(self):
        """Markierter Block wird im Baum aufgeklappt."""
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            return
        uid = self.row_uid(rows[0])
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.data(0, Qt.ItemDataRole.UserRole) == uid and not it.isExpanded():
                it.setExpanded(True)

    def populate(self, top):
        """Elemente eines Blocks beim Aufklappen erzeugen."""
        # Nur Block-Knoten mit unberührtem Platzhalter befüllen (Platzhalter erkennt man am leeren Text).
        if top.parent() is not None or top.childCount() != 1 or top.child(0).text(0):
            return                                             # schon befüllt (oder kein Block)
        r = self.row_of_uid(top.data(0, Qt.ItemDataRole.UserRole))
        if r < 0:
            return
        # Block aus der Tabellenzeile bauen und seine Elemente (mit eigenen oder Standardnamen) als Kinder anlegen.
        b = self.block_of_row(r)
        self._filling = True
        top.takeChild(0)                                       # Platzhalter entfernen
        uid = top.data(0, Qt.ItemDataRole.UserRole)
        for i, v in enumerate(b.variables()):
            child = QTreeWidgetItem([f"[{i}]", v.name, v.address, v.dtype])
            child.setData(0, Qt.ItemDataRole.UserRole, i)
            # Nur Spalte 1 (Name) ist editierbar; Spalte 0 zeigt die Nummer [i].
            child.setFlags(child.flags() | Qt.ItemFlag.ItemIsEditable)   # Spalte 1 ist editierbar
            top.addChild(child)
            # Spalte 'Diagramm › Y-Achse': Auswahlliste; Eintrag 0 = wie der Block, sonst ein eigenes Ziel des Elements.
            combo = QComboBox()
            combo.addItem(tr("(wie Block)"))
            combo.addItems(self.labels)
            tgt = self.targets_of.get(uid, {}).get(i)
            combo.setCurrentIndex(self.flat.index(tgt) + 1 if tgt in self.flat else 0)
            combo.currentIndexChanged.connect(lambda ix, u=uid, k=i: self.on_target_changed(u, k, ix))
            self.tree.setItemWidget(child, T_TARGET, combo)
        self._filling = False

    def on_target_changed(self, uid, idx, combo_index):
        """Ziel eines Elements wurde gewählt: 0 = wie der Block (Abweichung entfernen), sonst merken."""
        targets = self.targets_of.setdefault(uid, {})
        if combo_index <= 0:
            targets.pop(idx, None)
        else:
            targets[idx] = self.flat[combo_index - 1]

    def set_all_targets(self):
        """Ziel aus der Auswahlliste unter dem Baum für ALLE Elemente des markierten Blocks setzen."""
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows or not self.flat:
            QMessageBox.information(self, tr("Ziel setzen"), tr("Bitte zuerst einen Block markieren."))
            return
        r, ix = rows[0], self.cb_all.currentIndex()
        uid, count = self.row_uid(r), self.table.cellWidget(r, C_COUNT).value()
        targets = self.targets_of.setdefault(uid, {})
        targets.clear()
        if ix > 0:
            for i in range(count):
                targets[i] = self.flat[ix - 1]
        self.rebuild_tree()
        self.expand_selected()

    def on_name_edited(self, item, col):
        """Name eines Elements wurde geändert: leer oder Standardname = Standard wiederherstellen."""
        # Nur Änderungen des Namens eines Elements (Kind, Spalte 1) interessieren, nicht das programmgesteuerte Befüllen.
        if self._filling or col != 1 or item.parent() is None:
            return
        uid = item.parent().data(0, Qt.ItemDataRole.UserRole)
        r = self.row_of_uid(uid)
        if r < 0:
            return
        idx = item.data(0, Qt.ItemDataRole.UserRole)
        # Standardname eines Elements: <Blockname>[<Index>]
        default = f"{self.table.item(r, C_NAME).text().strip()}[{idx}]"
        text = " ".join(item.text(1).split())
        names = self.names_of.setdefault(uid, {})
        # Leer oder gleich dem Standardnamen: eigenen Namen entfernen (Standard gilt wieder).
        if not text or text == default:
            names.pop(idx, None)
            text = default
        else:
            names[idx] = text
        # Normalisierten Text zurück in den Baum schreiben (ohne erneut auszulösen).
        self._filling = True
        item.setText(1, text)
        self._filling = False

    # ---------------- Test ----------------
    # Block testen: einmalig aus der SPS lesen; zeigt Anzahl, Lesezeit und die ersten Werte.
    def test_block(self):
        """Markierten Block einmal aus der SPS lesen und das Ergebnis anzeigen."""
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            QMessageBox.information(self, tr("Block testen"), tr("Bitte zuerst einen Block markieren."))
            return
        b = self.block_of_row(rows[0])
        # get_conn(Index) liefert die Steuerung (plc_common.Plc); gelesen wird mit ihrem Treiber.
        plc = self.get_conn(b.plc)
        drv = get_driver(plc.driver)
        try:
            drv.check_library()
        except Exception as e:
            QMessageBox.critical(self, tr("Block testen"), tr("Die Bibliothek des Treibers fehlt ({0}):\n{1}").format(drv.library, e))
            return
        variables = b.variables()
        # Sanduhr-Cursor, solange die Verbindung aufgebaut wird (kann einige Sekunden dauern).
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            t0 = time.perf_counter()
            vals, errs = drv.read_once(plc, variables)
            ms = (time.perf_counter() - t0) * 1000
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, tr("Block testen"), tr("Lesen fehlgeschlagen:\n{0}").format(e))
            return
        QApplication.restoreOverrideCursor()
        if errs:
            QMessageBox.critical(self, tr("Block testen"), tr("{0} (Anzahl {1}):\n").format(b.address_range(), b.count)
                                 + "\n".join(errs.values()))
            return
        first = ", ".join(f"{v:g}" for v in vals[:8]) + (" …" if len(vals) > 8 else "")
        QMessageBox.information(
            self, tr("Block testen"),
            tr("{0}: {1} Werte ({2} Bytes) in {3:.1f} ms gelesen (einschließlich Verbindungsaufbau).\n\nErste Werte: {4}").format(b.name, len(vals), b.count * drv.type_size(b.dtype), ms, first))

    # ---------------- OK ----------------
    # OK gedrückt: Eingaben prüfen; bei Fehlern bleibt der Dialog offen.
    def accept_checked(self):
        blocks = [self.block_of_row(r) for r in range(self.table.rowCount())]
        names = [b.name for b in blocks]
        problems = []
        for b in blocks:
            err = get_driver(b.driver).check_block(b)
            if err:
                problems.append(f"„{b.name}“: {err}")
            if not b.name or any(ch in b.name for ch in ";{}[]"):
                problems.append(tr("„{0}“: Name darf nicht leer sein und keines der Zeichen ; {{ }} [ ] enthalten.").format(b.name))
        if len(set(names)) != len(names):
            problems.append(tr("Blocknamen müssen eindeutig sein."))
        # Elementnamen über alle Blöcke auf Eindeutigkeit und unerlaubte Zeichen prüfen
        # (; ist das CSV-Trennzeichen, { } begrenzen Variablen in Formeln).
        seen = set()
        for b in blocks:
            for v in b.variables():
                if any(ch in v.name for ch in ";{}"):
                    problems.append(tr("{0}: Elementname „{1}“ darf keines der Zeichen ; {{ }} enthalten.").format(b.name, v.name))
                if v.name in seen:
                    problems.append(tr("Elementname „{0}“ kommt mehrfach vor.").format(v.name))
                seen.add(v.name)
        for b in blocks:
            # Kollision mit vorhandenen (normalen oder berechneten) Variablen verhindern.
            clash = [v.name for v in b.variables() if v.name in self.taken]
            if clash:
                problems.append(tr("{0}: Name kollidiert mit vorhandenen Variablen ({1}).").format(b.name, clash[0]))
        if problems:
            QMessageBox.warning(self, tr("Blöcke prüfen"), "\n".join(problems))
            return
        self.result_blocks = blocks
        self.accept()
