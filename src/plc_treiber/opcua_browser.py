# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Auswahldialog des Treibers „opcua“: Adressraum des OPC-UA-Servers durchsuchen und Variablen übernehmen.

``OpcUaBrowseModel`` (ohne Qt) liefert die Kindknoten eines Knotens mit Datentyp und Array-Angaben; der Dialog lädt den
Baum beim Aufklappen nach (große Server bleiben dadurch schnell).
"""
from plc_i18n import tr
from plc_treiber.opcua import UA_TYPES, close_client, make_client

NODECLASS_OBJECT, NODECLASS_VARIABLE = 1, 2


class OpcUaBrowseModel:
    """Durchsuchen ohne Oberfläche: connect(), children(nodeid|None), close()."""

    def __init__(self, params):
        self.params = params
        self.client = None

    def connect(self):
        self.client = make_client(self.params)
        return self

    def close(self):
        close_client(self.client)
        self.client = None

    def children(self, nodeid=None):
        """[{nodeid, name, cls, dtype, array (Länge oder 0), scalar_ok}] der Kinder (None = Objects-Ordner)."""
        from asyncua import ua
        c = self.client
        node = c.nodes.objects if nodeid is None else c.get_node(nodeid)
        refs = node.get_children_descriptions(refs=ua.ObjectIds.HierarchicalReferences)
        out = []
        for r in refs:
            cls = int(getattr(r.NodeClass, "value", r.NodeClass))
            if cls not in (NODECLASS_OBJECT, NODECLASS_VARIABLE):
                continue
            nid = r.NodeId if not hasattr(r.NodeId, "NodeId") else r.NodeId.NodeId
            out.append({"nodeid": nid.to_string(), "name": r.DisplayName.Text or r.BrowseName.Name,
                        "cls": cls, "dtype": "", "array": 0, "scalar_ok": False, "_nid": nid})
        vars_ = [o for o in out if o["cls"] == NODECLASS_VARIABLE]
        if vars_:
            params = ua.ReadParameters()
            for o in vars_:
                for attr in (ua.AttributeIds.DataType, ua.AttributeIds.ValueRank, ua.AttributeIds.ArrayDimensions):
                    rv = ua.ReadValueId()
                    rv.NodeId, rv.AttributeId = o["_nid"], attr
                    params.NodesToRead.append(rv)
            res = c.tloop.post(c.aio_obj.uaclient.read(params))
            for k, o in enumerate(vars_):
                dt, rank, dims = (res[3 * k + j].Value.Value if res[3 * k + j].Value else None for j in range(3))
                ident = getattr(dt, "Identifier", None) if getattr(dt, "NamespaceIndex", 1) == 0 else None
                o["dtype"] = UA_TYPES.get(ident, "") if isinstance(ident, int) else ""
                if isinstance(rank, int) and rank >= 1:
                    o["array"] = int(dims[0]) if dims and dims[0] else -1
                o["scalar_ok"] = bool(o["dtype"]) and not o["array"]
        for o in out:
            o.pop("_nid", None)
        return sorted(out, key=lambda o: (o["cls"] != NODECLASS_OBJECT, o["name"].lower()))


# ---------------------------------------------------------------------------------------------------------- Dialog
try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                                   QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTreeWidget,
                                   QTreeWidgetItem, QVBoxLayout)
except ImportError:                    # ohne Qt nur das Modell (Tests, Headless)
    QDialog = object

ROLE = 0x0100 + 7                      # Qt.ItemDataRole.UserRole + 7


class OpcUaBrowserDialog(QDialog):
    def __init__(self, parent, plc, existing, target_labels, default_target=0):
        super().__init__(parent)
        self.setWindowTitle(tr("OPC UA – Variablen wählen ({0})").format(plc.params.get("endpoint", "")))
        self.existing = set(existing)
        self.result_vars, self.result_blocks = [], []
        self.target_index = default_target
        self.model = OpcUaBrowseModel(plc.params)
        lay = QVBoxLayout(self)
        self.lbl = QLabel(tr("Verbinde …"))
        lay.addWidget(self.lbl)
        row = QHBoxLayout()
        self.ed_filter = QLineEdit()
        self.ed_filter.setPlaceholderText(tr("Filter (geladene Knoten) …"))
        self.ed_filter.textChanged.connect(self.apply_filter)
        row.addWidget(self.ed_filter, 1)
        lay.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Name"), tr("Typ"), tr("NodeId")])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.itemExpanded.connect(self.on_expand)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self.add_block(it))
        lay.addWidget(self.tree, 1)
        row = QHBoxLayout()
        self.btn_block = QPushButton(tr("Markiertes Array als Block …"))
        self.btn_block.clicked.connect(lambda: self.add_block(self.tree.currentItem()))
        row.addWidget(self.btn_block)
        row.addStretch(1)
        lay.addLayout(row)
        form = QFormLayout()
        self.cb_target = QComboBox()
        self.cb_target.addItems(list(target_labels))
        self.cb_target.setCurrentIndex(max(0, min(default_target, len(target_labels) - 1)))
        form.addRow(tr("Neue Variablen anlegen in:"), self.cb_target)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.btn_ok = bb.addButton(tr("Auswahl übernehmen"), QDialogButtonBox.ButtonRole.AcceptRole)
        bb.accepted.connect(self.take)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(820, 640)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.model.connect()
            self._fill(self.tree.invisibleRootItem(), None)
            self.lbl.setText(tr("Verbunden. Ordner aufklappen, Variablen anhaken; Arrays per Doppelklick als Block."))
        except Exception as e:
            self.lbl.setText("<span style='color:#c0392b'>" + tr("Verbindung fehlgeschlagen: {0}").format(e) + "</span>")
        finally:
            QApplication.restoreOverrideCursor()

    # Baum
    def _fill(self, parent_item, nodeid):
        for o in self.model.children(nodeid):
            typ = o["dtype"] + (f"[{o['array'] if o['array'] > 0 else '?'}]" if o["array"] else "")
            it = QTreeWidgetItem([o["name"], typ, o["nodeid"]])
            it.setData(0, ROLE, o)
            if o["cls"] == 1 or o["array"]:
                it.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            if o["cls"] == 2:
                if o["scalar_ok"]:
                    it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    done = o["nodeid"] in self.existing
                    it.setCheckState(0, Qt.CheckState.Checked if done else Qt.CheckState.Unchecked)
                    if done:
                        it.setDisabled(True)
                        it.setToolTip(0, tr("bereits in der Liste"))
                elif not o["array"]:
                    it.setForeground(0, Qt.GlobalColor.gray)
                    it.setToolTip(0, tr("Datentyp nicht aufzeichenbar"))
            parent_item.addChild(it)

    def on_expand(self, item):
        o = item.data(0, ROLE) or {}
        if item.childCount() or o.get("_loaded"):
            return
        o["_loaded"] = True
        item.setData(0, ROLE, o)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._fill(item, o["nodeid"])
        except Exception as e:
            QMessageBox.warning(self, "OPC UA", str(e))
        finally:
            QApplication.restoreOverrideCursor()
        self.apply_filter()

    def apply_filter(self):
        f = self.ed_filter.text().strip().lower()

        def walk(it):
            visible = not f or f in it.text(0).lower()
            for i in range(it.childCount()):
                visible = walk(it.child(i)) or visible
            it.setHidden(not visible)
            return visible
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            walk(root.child(i))

    # Übernehmen
    def add_block(self, item):
        if item is None:
            return
        o = item.data(0, ROLE) or {}
        if not o.get("array") or not o.get("dtype"):
            if o.get("cls") == 2 and not o.get("array"):
                return
            QMessageBox.information(self, tr("Block"), tr("Bitte ein Array aus Zahlen markieren."))
            return
        d = QDialog(self)
        d.setWindowTitle(tr("Array als Block – {0}").format(o["name"]))
        fl = QFormLayout(d)
        sp_start, sp_n = QSpinBox(), QSpinBox()
        n = o["array"] if o["array"] > 0 else 1000
        sp_start.setRange(0, max(0, n - 1))
        sp_n.setRange(1, min(1000, n))
        sp_n.setValue(min(n, 10))
        fl.addRow(tr("Erster Index:"), sp_start)
        fl.addRow(tr("Anzahl:"), sp_n)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        fl.addRow(bb)
        if d.exec():
            self.result_blocks.append((o["name"], o["nodeid"], sp_start.value(), sp_n.value(), o["dtype"]))
            item.setText(1, item.text(1) + "  ▦")

    def take(self):
        def walk(it, path):
            for i in range(it.childCount()):
                ch = it.child(i)
                o = ch.data(0, ROLE) or {}
                name = f"{path}.{ch.text(0)}" if path else ch.text(0)
                if o.get("scalar_ok") and ch.isEnabled() and ch.checkState(0) == Qt.CheckState.Checked:
                    self.result_vars.append((name, o["nodeid"], o["dtype"]))
                walk(ch, name)
        walk(self.tree.invisibleRootItem(), "")
        self.target_index = self.cb_target.currentIndex()
        self.model.close()
        self.accept()

    def reject(self):
        self.model.close()
        super().reject()
