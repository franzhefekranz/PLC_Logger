# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Auswahldialog des Treibers „ads“: Symboltabelle der TwinCAT-Steuerung lesen und Variablen übernehmen.

``AdsBrowseModel`` (ohne Qt) liefert die aufzeichenbaren Symbole; der Dialog zeigt sie als Baum (gegliedert nach den
Namensteilen, z. B. MAIN › Pumpe › fDruck) mit Filter. Arrays aus Zahlen lassen sich per Doppelklick als Block
übernehmen.
"""
from plc_i18n import tr
from plc_treiber.ads import AdsClient, classify_symbol


class AdsBrowseModel:
    """Symbole lesen: [{name, dtype, kind ("var"/"array"), lo, hi, comment}] (sortiert)."""

    def __init__(self, params):
        """``params``: Verbindungsparameter der Steuerung (wie beim Treiber)."""
        self.params = params

    def load(self):
        """Verbinden, Symboltabelle lesen, nur aufzeichenbare Symbole (Zahlen, Arrays aus Zahlen) behalten."""
        c = AdsClient(self.params)
        try:
            c.connect()
            raw = c.symbols()
        finally:
            c.close()
        out = []
        for name, typ, size, comment in raw:
            cls = classify_symbol(name, typ, size)
            if cls is None:
                continue
            item = {"name": name, "type": typ, "dtype": cls[1], "kind": cls[0], "comment": comment, "lo": 0, "hi": 0}
            if cls[0] == "array":
                item["lo"], item["hi"] = cls[2], cls[3]
            out.append(item)
        return sorted(out, key=lambda o: o["name"].lower())


try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHeaderView, QLabel,
                                   QLineEdit, QMessageBox, QPushButton, QSpinBox, QTreeWidget, QTreeWidgetItem,
                                   QVBoxLayout, QHBoxLayout)
except ImportError:                    # ohne Qt nur das Modell (Tests, Headless)
    QDialog = object

ROLE = 0x0100 + 7                      # Qt.ItemDataRole.UserRole + 7


class AdsBrowserDialog(QDialog):
    """Dialog „TwinCAT – Variablen wählen“: Symbolbaum mit Filter, Häkchen für Variablen, Doppelklick für Blöcke.

    Ergebnis nach OK: ``result_vars`` [(Name, Symbol, Typ)], ``result_blocks`` [(Name, Symbol, Start, Anzahl, Typ)] und
    ``target_index`` (Zieldiagramm).
    """
    def __init__(self, parent, plc, existing, target_labels, default_target=0):
        """Oberfläche aufbauen und die Symboltabelle lesen; ``existing`` = schon angelegte Symbole (werden ausgegraut).
        """
        super().__init__(parent)
        self.setWindowTitle(tr("TwinCAT – Variablen wählen ({0})").format(plc.params.get("ip", "")))
        self.existing = set(existing)
        self.result_vars, self.result_blocks = [], []
        self.target_index = default_target
        lay = QVBoxLayout(self)
        self.lbl = QLabel(tr("Lese Symboltabelle …"))
        lay.addWidget(self.lbl)
        self.ed_filter = QLineEdit()
        self.ed_filter.setClearButtonEnabled(True)
        self.ed_filter.setPlaceholderText(tr("Filter (Name, Typ, Kommentar) …"))
        self.ed_filter.textChanged.connect(self.apply_filter)
        lay.addWidget(self.ed_filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Name"), tr("Typ"), tr("Kommentar")])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self.add_block(it))
        lay.addWidget(self.tree, 1)
        row = QHBoxLayout()
        btn_block = QPushButton(tr("Markiertes Array als Block …"))
        btn_block.clicked.connect(lambda: self.add_block(self.tree.currentItem()))
        row.addWidget(btn_block)
        row.addStretch(1)
        lay.addLayout(row)
        form = QFormLayout()
        self.cb_target = QComboBox()
        self.cb_target.addItems(list(target_labels))
        self.cb_target.setCurrentIndex(max(0, min(default_target, len(target_labels) - 1)))
        form.addRow(tr("Neue Variablen anlegen in:"), self.cb_target)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        bb.addButton(tr("Auswahl übernehmen"), QDialogButtonBox.ButtonRole.AcceptRole)
        bb.accepted.connect(self.take)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(860, 640)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            symbols = AdsBrowseModel(plc.params).load()
            self._fill(symbols)
            self.lbl.setText(tr("{0} aufzeichenbare Symbole. Variablen anhaken; Arrays per Doppelklick als Block.").format(
                len(symbols)))
        except Exception as e:
            self.lbl.setText("<span style='color:#c0392b'>" + tr("Symboltabelle nicht lesbar: {0}").format(e) + "</span>")
        finally:
            QApplication.restoreOverrideCursor()

    def _fill(self, symbols):
        """Symbole in den Baum eintragen; Ordner entstehen aus den Namensteilen (MAIN › Pumpe › fDruck)."""
        folders = {}

        def folder(path):
            """Ordnerknoten zum Pfad (samt übergeordneten Ordnern) holen oder anlegen."""
            if not path:
                return self.tree.invisibleRootItem()
            if path in folders:
                return folders[path]
            parent = folder(path.rsplit(".", 1)[0] if "." in path else "")
            it = QTreeWidgetItem([path.rsplit(".", 1)[-1], "", ""])
            parent.addChild(it)
            folders[path] = it
            return it
        for o in symbols:
            name = o["name"]
            parent_path = name.rsplit(".", 1)[0] if "." in name.lstrip(".") else ""
            leaf = name[len(parent_path) + 1:] if parent_path else name
            it = QTreeWidgetItem([leaf, o["type"], o["comment"]])
            it.setData(0, ROLE, o)
            it.setToolTip(0, name)
            if o["kind"] == "var":
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                done = name in self.existing
                it.setCheckState(0, Qt.CheckState.Checked if done else Qt.CheckState.Unchecked)
                if done:
                    it.setDisabled(True)
                    it.setToolTip(0, tr("bereits in der Liste"))
            folder(parent_path).addChild(it)
        self.tree.expandToDepth(0)

    def apply_filter(self):
        """Nur Einträge zeigen, deren Name, Typ oder Kommentar zum Filter passt (samt ihren Ordnern)."""
        from plc_util import text_filter
        match = text_filter(self.ed_filter.text())

        def walk(it):
            """Rekursiv: Eintrag sichtbar, wenn er selbst oder ein Kind passt."""
            o = it.data(0, ROLE) or {}
            visible = bool(o) and match(o.get("name", ""), o.get("type", ""), o.get("comment", ""))
            for i in range(it.childCount()):
                visible = walk(it.child(i)) or visible
            it.setHidden(not visible)
            return visible
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            walk(root.child(i))
        if self.ed_filter.text().strip():
            self.tree.expandAll()

    def add_block(self, item):
        """Markiertes Array als Block vormerken (erster Index und Anzahl im kleinen Dialog)."""
        if item is None:
            return
        o = item.data(0, ROLE) or {}
        if o.get("kind") != "array":
            if not o or o.get("kind") == "var":
                return
            QMessageBox.information(self, tr("Block"), tr("Bitte ein Array aus Zahlen markieren."))
            return
        d = QDialog(self)
        d.setWindowTitle(tr("Array als Block – {0}").format(o["name"]))
        fl = QFormLayout(d)
        sp_start, sp_n = QSpinBox(), QSpinBox()
        sp_start.setRange(o["lo"], o["hi"])
        sp_n.setRange(1, min(1000, o["hi"] - o["lo"] + 1))
        sp_n.setValue(min(10, o["hi"] - o["lo"] + 1))
        fl.addRow(tr("Erster Index:"), sp_start)
        fl.addRow(tr("Anzahl:"), sp_n)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        fl.addRow(bb)
        if d.exec():
            n = min(sp_n.value(), o["hi"] - sp_start.value() + 1)
            self.result_blocks.append((o["name"].split(".")[-1], o["name"], sp_start.value(), n, o["dtype"]))
            item.setText(1, item.text(1) + "  ▦")

    def take(self):
        """OK: alle angehakten, noch nicht vorhandenen Variablen einsammeln und den Dialog schließen."""
        def walk(it):
            """Rekursiv angehakte Variablen sammeln (Name = Symbol mit „_“ statt Punkten)."""
            for i in range(it.childCount()):
                ch = it.child(i)
                o = ch.data(0, ROLE) or {}
                if o.get("kind") == "var" and ch.isEnabled() and ch.checkState(0) == Qt.CheckState.Checked:
                    self.result_vars.append((o["name"].lstrip(".").replace(".", "_"), o["name"], o["dtype"]))
                walk(ch)
        walk(self.tree.invisibleRootItem())
        self.target_index = self.cb_target.currentIndex()
        self.accept()
