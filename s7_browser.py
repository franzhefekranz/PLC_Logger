"""Dialog "Variablen aus SPS-Symbolen wählen" (wird vom Konfigurationsprogramm geöffnet).

Zeigt die Datenbausteine als Baum (DB > Struktur > Variable). Die Struktur stammt aus den
importierten DB-/UDT-Quellen, optional werden DB-Nummern und -Größen mit der SPS abgeglichen.
Variablen werden per Häkchen zum Aufzeichnen ausgewählt.

Ablauf
------
1. Beim Öffnen werden die gespeicherten Quellen (Pfade) erneut eingelesen (``SymbolSet.load``).
2. ``refresh`` baut aus ``SymbolSet.build()`` den Baum auf (``_make_item`` rekursiv je Knoten).
3. Häkchen: ein Häkchen an einem Elternknoten setzt alle auswählbaren Nachfahren; Elternknoten
   zeigen den Mischzustand (teilweise angehakt). Bereits vorhandene Variablen sind angehakt und gesperrt.
4. "Auswahl übernehmen" sammelt die angehakten Blätter (``take_selection``); das Konfigurationsprogramm
   legt daraus Variablen an (Name = Symbolpfad, Adresse aus der Quelle).

Die SPS selbst liefert nur DB-Nummern und -Größen (``compare_plc``); Namen und Strukturen kommen aus den
Quelldateien (siehe s7_symbols.py).
"""


import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout,
)
from snap7.client import Client

# Variable: zur Adressdarstellung; list_plc_dbs: DB-Liste der SPS.
from s7_common import Variable, list_plc_dbs
from s7_symbols import SymbolSet, config_type
from s7_i18n import tr

# Im Baum hängt am ersten Eintrag jeder Zeile der zugehörige SymNode (UserRole).
ROLE_NODE = Qt.ItemDataRole.UserRole
# Flag 'Kästchen anklickbar' (wird gesetzt/entfernt, um Einträge wählbar bzw. gesperrt zu machen).
CHECKABLE = Qt.ItemFlag.ItemIsUserCheckable


class SymbolBrowser(QDialog):
    """Dialog zur Auswahl von Variablen aus den Symbolen der importierten DB-Quellen."""
    def __init__(self, parent, get_conn, entries, existing, targets, default_target):
        """
        get_conn       -> Funktion, die die aktuellen Verbindungsdaten (ip, rack, slot) liefert
        entries        -> gespeicherte Quellen (Pfad oder Pfad#DB-Nummern)
        existing       -> Menge (db, byte, bit) bereits angelegter Variablen
        targets        -> Beschriftungen "Diagramm › Y-Achse" für neue Variablen
        default_target -> vorausgewählter Eintrag in targets
        """
        super().__init__(parent)
        self.setWindowTitle(tr("Variablen aus SPS-Symbolen wählen"))
        self.resize(1050, 720)
        # Der Dialog speichert nichts selbst: die Quellenliste und die Auswahl gibt er über entries() bzw.
        # result_nodes/target_index an das Konfigurationsprogramm zurück.
        self.get_conn = get_conn
        self.existing = existing
        self.symset = SymbolSet()
        # Ergebnis des SPS-Abgleichs: {DB-Nummer: Größe in Bytes}; leer, solange nicht abgeglichen wurde.
        self.plc_sizes = {}
        self.result_nodes = []
        self.target_index = default_target
        # True, solange der Baum programmatisch geändert wird (Häkchen-Signale dann ignorieren).
        self._busy = False
        self._start_dir = os.path.expanduser("~")

        info = QLabel(
            tr("Die SPS liefert über S7-Kommunikation <b>keine Variablennamen</b> – diese stehen nur im "
            "Projekt. Importieren Sie daher die DB-Quelle(n): TIA Portal: Rechtsklick auf den "
            "Baustein › <i>Quelle aus Bausteinen generieren</i> (.db/.scl); STEP 7: .db/.awl. "
            "Die Adressen werden für <b>nicht optimierte</b> Bausteine berechnet. UDTs bitte "
            "ebenfalls importieren."))
        info.setWordWrap(True)

        # ---- Knopfleiste oben ----
        self.btn_import = QPushButton(tr("DB-Quelle importieren…"))
        self.btn_import.clicked.connect(self.import_sources)
        self.btn_remove = QPushButton(tr("Quelle entfernen"))
        self.btn_remove.setToolTip(tr("Quelle des markierten DBs aus der Liste entfernen"))
        self.btn_remove.clicked.connect(self.remove_source)
        self.btn_plc = QPushButton(tr("Mit SPS abgleichen"))
        self.btn_plc.setToolTip(tr("DB-Nummern und -Größen aus der SPS lesen und vergleichen"))
        self.btn_plc.clicked.connect(self.compare_plc)
        self.ed_filter = QLineEdit()
        self.ed_filter.setPlaceholderText(tr("Filter (Name)…"))
        self.ed_filter.setClearButtonEnabled(True)
        self.ed_filter.textChanged.connect(self.apply_filter)
        top = QHBoxLayout()
        for w in (self.btn_import, self.btn_remove, self.btn_plc):
            top.addWidget(w)
        top.addStretch(1)
        top.addWidget(self.ed_filter)

        # ---- Baum: Name | Typ | Adresse | Hinweis ----
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels([tr("Name"), tr("Typ"), tr("Adresse"), tr("Hinweis")])
        self.tree.setColumnWidth(0, 360)
        self.tree.setColumnWidth(1, 100)
        self.tree.setColumnWidth(2, 140)
        self.tree.itemChanged.connect(self.on_item_changed)

        # Statuszeile unter dem Baum: Fehler der Quellen, Zahl der gefundenen SPS-Bausteine.
        self.status = QLabel("")
        self.status.setWordWrap(True)

        # ---- Unten: Ziel für die neuen Variablen und Knöpfe ----
        self.cb_target = QComboBox()
        self.cb_target.addItems(targets)
        if 0 <= default_target < len(targets):
            self.cb_target.setCurrentIndex(default_target)
        btn_ok = QPushButton(tr("Auswahl übernehmen"))
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self.take_selection)
        btn_close = QPushButton(tr("Schließen"))
        btn_close.clicked.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel(tr("Neue Variablen anlegen in:")))
        bottom.addWidget(self.cb_target, 1)
        bottom.addWidget(btn_ok)
        bottom.addWidget(btn_close)

        # Fensteraufbau von oben nach unten.
        lay = QVBoxLayout(self)
        lay.addWidget(info)
        lay.addLayout(top)
        lay.addWidget(self.tree, 1)
        lay.addWidget(self.status)
        lay.addLayout(bottom)

        # Gespeicherte Quellen laden; unlesbare (verschoben, gelöscht ...) werden in der Statuszeile gemeldet.
        problems = []
        for e in entries:
            try:
                self.symset.load(e)
            except Exception as ex:
                problems.append(f"{os.path.basename(e.split('#')[0])}: {ex}")
        self.refresh()
        if problems:
            self.status.setText(tr("Nicht lesbare Quellen: ") + "; ".join(problems))

    # ---------------- Ergebnis ----------------
    # Quellen als Konfigurationseinträge (Pfad oder Pfad#DB-Nummern) zurückgeben.
    def entries(self):
        return self.symset.entries()

    # ---------------- Baum aufbauen ----------------
    def refresh(self):
        """Baum aus den Quellen neu aufbauen (und die Statuszeile aktualisieren)."""
        # Gesamtbaum und Fehlerliste aus allen importierten Quellen berechnen.
        nodes, errors = self.symset.build()
        # Baum neu aufbauen; dabei keine Häkchen-Ereignisse verarbeiten.
        self._busy = True
        self.tree.clear()
        # DB-Nummern, zu denen eine Quelle vorliegt (der Rest wird als 'nur in der SPS' ergänzt).
        known = set()
        for n in nodes:
            known.add(n.db)
            item, _ = self._make_item(n)
            self.tree.addTopLevelItem(item)
        # DBs, die in der SPS existieren, zu denen aber keine Quelle importiert wurde.
        for db, size in sorted(self.plc_sizes.items()):
            if db not in known:
                txt = f"{size} Bytes" if size else tr("Größe unbekannt")
                it = QTreeWidgetItem([f"DB{db}", "DB", f"DB{db}",
                                      tr("nur in der SPS ({0}) – keine Symbolinformation, Quelle importieren").format(txt)])
                self.tree.addTopLevelItem(it)
        # Nur die Bausteine aufklappen; tiefere Ebenen öffnet der Benutzer bei Bedarf.
        self.tree.expandToDepth(0)
        self._busy = False
        self.apply_filter(self.ed_filter.text())
        # Statusmeldungen: Fehler der Quellen + Zahl der SPS-Bausteine.
        msgs = list(errors)
        if self.plc_sizes:
            msgs.append(tr("SPS: {0} Datenbausteine gefunden.").format(len(self.plc_sizes)))
        self.status.setText("\n".join(msgs))

    # Erzeugt rekursiv den Baumeintrag zum Knoten n (und seiner Kinder).
    def _make_item(self, n):
        """-> (QTreeWidgetItem, enthält anwählbare Variablen)"""
        # Typ-Spalte: Bausteine/Strukturen mit Sammelbegriff, Blätter mit ihrem Datentyp.
        typ = {"db": "DB", "struct": "STRUCT", "array": "ARRAY", "note": ""}.get(n.kind, n.dtype)
        # Adress- und Hinweis-Spalte (je nach Knotenart unterschiedlich befüllt).
        addr, note = "", n.note
        # Baustein: Größe aus der Quelle, bei vorhandenem Abgleich zusätzlich Vergleich mit der Größe in der SPS.
        if n.kind == "db":
            addr = f"DB{n.db}"
            txt = tr("{0} Bytes (aus Quelle)").format(n.size)
            # ✓ = Größe stimmt überein, ⚠ = weicht ab (Quelle veraltet/optimierter Baustein?).
            plc = self.plc_sizes.get(n.db)
            if self.plc_sizes:
                if n.db not in self.plc_sizes:
                    txt += tr(" · ⚠ DB in der SPS nicht gefunden")
                elif plc is not None:
                    txt += (f" · SPS: {plc} Bytes ✓" if plc == n.size
                            else tr(" · SPS: {0} Bytes ⚠ Größe weicht ab").format(plc))
            note = (note + " · " if note else "") + txt
        # Variable: Adresse in Siemens-Schreibweise, falls der Typ aufzeichenbar ist.
        elif n.kind == "leaf":
            ct = config_type(n.dtype)
            if ct:
                addr = Variable(name="", db=n.db, byte=n.byte, bit=n.bit, dtype=ct).address()
            else:
                addr = f"DB{n.db}.{n.byte}"
                note = tr("Typ wird nicht unterstützt")
        elif n.kind in ("struct", "array"):
            addr = f"Byte {n.byte}"
        # Baumeintrag anlegen und den Knoten daran hängen.
        item = QTreeWidgetItem([n.name, typ, addr, note])
        item.setData(0, ROLE_NODE, n)

        # Merker: enthält dieser Eintrag (oder seine Kinder) etwas, das man anhaken kann?
        checkable = False
        if n.kind == "leaf":
            if n.supported:
                # Schlüssel zum Erkennen bereits angelegter Variablen: DB, Byte und (bei BOOL) Bit.
                key = (n.db, n.byte, n.bit if n.dtype == "BOOL" else 0)
                # Bereits in der Liste: angehakt anzeigen, aber nicht änderbar.
                if key in self.existing:
                    item.setCheckState(0, Qt.CheckState.Checked)
                    item.setFlags(item.flags() & ~CHECKABLE)
                    item.setText(3, tr("bereits in der Liste"))
                else:
                    item.setFlags(item.flags() | CHECKABLE)
                    item.setCheckState(0, Qt.CheckState.Unchecked)
                    checkable = True
            else:
                # Nicht aufzeichenbare Typen (STRING, DTL, ...) grau darstellen.
                item.setForeground(0, self.palette().placeholderText())
        else:
            # Struktur/Array/Baustein: Kinder rekursiv erzeugen; ein Elternknoten ist nur anwählbar, wenn ein Kind es ist.
            for ch in n.children:
                c_item, c_ok = self._make_item(ch)
                item.addChild(c_item)
                checkable = checkable or c_ok
            if checkable:
                item.setFlags(item.flags() | CHECKABLE)
                item.setCheckState(0, Qt.CheckState.Unchecked)
        return item, checkable

    # ---------------- Häkchen ----------------
    # Häkchen wurde geändert: auf Nachfahren übertragen und die Elternknoten nachziehen.
    def on_item_changed(self, item, col):
        if col != 0 or self._busy:
            return
        self._busy = True
        try:
            # Elternknoten angehakt/abgehakt -> alle auswählbaren Nachfahren übernehmen den Zustand.
            if item.childCount():
                self._set_descendants(item, item.checkState(0))
            self._update_parents(item.parent())
        finally:
            self._busy = False

    # Zustand rekursiv auf alle anwählbaren Nachfahren übertragen (gesperrte bleiben unverändert).
    def _set_descendants(self, item, state):
        for i in range(item.childCount()):
            ch = item.child(i)
            if ch.flags() & CHECKABLE:
                ch.setCheckState(0, state)
            self._set_descendants(ch, state)

    # Von unten nach oben: Zustand der Elternknoten aus den Kindern berechnen (alle / keine / teilweise).
    def _update_parents(self, p):
        while p is not None:
            # Nur Kinder berücksichtigen, die überhaupt anwählbar sind.
            states = [p.child(i).checkState(0) for i in range(p.childCount())
                      if p.child(i).flags() & CHECKABLE]
            if states and all(s == Qt.CheckState.Checked for s in states):
                new = Qt.CheckState.Checked
            elif all(s == Qt.CheckState.Unchecked for s in states):
                new = Qt.CheckState.Unchecked
            else:
                new = Qt.CheckState.PartiallyChecked
            p.setCheckState(0, new)
            p = p.parent()

    # ---------------- Filter ----------------
    # Filter: blendet Einträge aus, deren Name (und dessen Kinder) den Text nicht enthalten.
    def apply_filter(self, text):
        text = text.strip().lower()

        # force=True: ein Elternknoten passt -> alle seine Nachfahren bleiben sichtbar.
        def visit(it, force):
            match = not text or text in it.text(0).lower()
            any_child = False
            for i in range(it.childCount()):
                if visit(it.child(i), force or match):
                    any_child = True
            vis = force or match or any_child
            it.setHidden(not vis)
            return vis

        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i), False)
        if text:
            self.tree.expandAll()

    # ---------------- Aktionen ----------------
    def import_sources(self):
        """Eine oder mehrere DB-/UDT-Quelldateien importieren."""
        # Quelldateien wählen (mehrere möglich).
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("DB-/UDT-Quellen importieren"), self._start_dir,
            tr("Quelldateien (*.db *.scl *.awl *.src *.udt *.txt);;Alle Dateien (*)"))
        errors = []
        for p in paths:
            self._start_dir = os.path.dirname(p)
            try:
                # Datei einlesen; Fehler (kein DATA_BLOCK/TYPE gefunden, nicht lesbar) werden gesammelt und am Ende gemeldet.
                src = self.symset.load(p)
            except Exception as e:
                errors.append(f"{os.path.basename(p)}: {e}")
                continue
            numbers = []
            # TIA-Quellen enthalten keine DB-Nummer: für jeden Baustein ohne Nummer nachfragen.
            for d in src.unnumbered():
                n, ok = QInputDialog.getInt(
                    self, tr("DB-Nummer"),
                    tr("Nummer des Datenbausteins „{0}“ in der SPS\n(TIA-Quellen enthalten keine Nummer):").format(d.name), 1, 1, 65535)
                if not ok:
                    break
                numbers.append(n)
            # Nummern zuordnen (sie werden mit dem Pfad gespeichert, sodass keine erneute Abfrage nötig ist).
            src.assign(numbers)
        self.refresh()
        if errors:
            QMessageBox.warning(self, tr("Import"), "\n".join(errors))

    def remove_source(self):
        """Quelle des markierten Bausteins aus der Liste entfernen."""
        it = self.tree.currentItem()
        # Zum Wurzelknoten (Baustein) des aktuell markierten Eintrags hochlaufen.
        while it is not None and it.parent() is not None:
            it = it.parent()
        n = it.data(0, ROLE_NODE) if it is not None else None
        if n is None or n.source is None:
            QMessageBox.information(self, tr("Quelle entfernen"),
                                    tr("Bitte zuerst einen Datenbaustein mit importierter Quelle markieren."))
            return
        self.symset.remove(n.source)
        self.refresh()

    def compare_plc(self):
        """DB-Nummern und -Größen aus der SPS lesen und im Baum gegenüberstellen."""
        conn = self.get_conn()
        # SPS-Abgleich: Verbindung aufbauen, DB-Liste lesen, in jedem Fall wieder trennen.
        client = Client()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            client.connect(conn["ip"], conn["rack"], conn["slot"])
            # {DB-Nummer: Größe}; die SPS nennt weder Namen noch Strukturen.
            sizes = list_plc_dbs(client)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(
                self, tr("SPS-Abgleich fehlgeschlagen"),
                tr("{0}\n\nHinweis: Bei S7-1200/1500 muss PUT/GET erlaubt sein; die Bausteinliste kann durch die Schutzstufe gesperrt sein.").format(e))
            return
        finally:
            try:
                client.disconnect()
            except Exception:
                pass
        QApplication.restoreOverrideCursor()
        if not sizes:
            QMessageBox.information(self, tr("SPS-Abgleich"), tr("In der SPS wurden keine Datenbausteine gefunden."))
        self.plc_sizes = sizes
        self.refresh()

    # Angehakte, aufzeichenbare, neue Blätter rekursiv einsammeln.
    def _collect(self, item, out):
        n = item.data(0, ROLE_NODE)
        if (n is not None and n.kind == "leaf" and n.supported and (item.flags() & CHECKABLE)
                and item.checkState(0) == Qt.CheckState.Checked):
            out.append(n)
        for i in range(item.childCount()):
            self._collect(item.child(i), out)

    # Auswahl übernehmen: Ergebnis merken und den Dialog schließen (accept).
    def take_selection(self):
        out = []
        for i in range(self.tree.topLevelItemCount()):
            self._collect(self.tree.topLevelItem(i), out)
        if not out:
            QMessageBox.information(self, tr("Auswahl"), tr("Es sind keine neuen Variablen angehakt."))
            return
        self.result_nodes = out
        self.target_index = self.cb_target.currentIndex()
        self.accept()
