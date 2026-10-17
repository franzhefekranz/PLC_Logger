# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Dialog "Variablen aus der Steuerung wählen" (wird vom Konfigurationsprogramm geöffnet).

Die Variablenliste kommt direkt aus der S7-1200/1500 (S7CommPlus browse, siehe tia_taglist.py) und wird
zwischengespeichert, so dass der Baum auch ohne Verbindung durchsucht werden kann.

Bedienung
---------
* **Variablenliste laden**: liest alle Datenbausteine sowie Merker, Ein- und Ausgänge aus der Steuerung. Das läuft
  in einem eigenen Thread; der Dialog bleibt bedienbar.
* Baum: Datenbausteine und Bereiche > Variablen > Strukturglieder > Array-Elemente. Kinder werden erst beim
  Aufklappen erzeugt (große Arrays und Strukturen).
* Häkchen an lesbaren Werten (atomare Typen) wählen Variablen aus. Bereits angelegte Tags sind angehakt und gesperrt.
* **Filter**: ab zwei Zeichen zeigt der Baum eine Trefferliste aller passenden Tag-Namen (auch in Strukturen).
* **Als Block übernehmen**: ein markiertes Array aus Zahlen (z. B. ``Array[1..100] of Real``) wird als Block
  übernommen (erster Index und Anzahl wählbar); seine Elemente werden gemeinsam gelesen.

Ergebnis (nach "Auswahl übernehmen"): ``result_tags`` = [(Tag-Name, Typ)], ``result_blocks`` = [(Array-Tag, Typ,
Start, Anzahl)], ``target_index`` = gewähltes Diagramm › Y-Achse.
"""
import threading
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from plc_treiber.tia_common import TLS_MODES
from plc_treiber.tia_taglist import MAX_ELEMENTS, TagTree, fetch_tag_list, load_cache, readable_type
from plc_i18n import tr

ROLE_NODE = Qt.ItemDataRole.UserRole
CHECKABLE = Qt.ItemFlag.ItemIsUserCheckable


class BlockSpecDialog(QDialog):
    """Kleiner Dialog: Startindex und Anzahl für die Übernahme eines Arrays als Block."""

    def __init__(self, parent, node):
        super().__init__(parent)
        self.setWindowTitle(tr("Array als Block übernehmen"))
        n, lo = node.length, node.lower
        hi = lo + n - 1                              # größter Index (TIA: Array[lo..hi])
        self.sp_start = QSpinBox()
        self.sp_start.setRange(lo, max(hi, lo))
        self.sp_start.setValue(lo)
        self.sp_count = QSpinBox()
        self.sp_count.setRange(1, max(1, min(n, 1000)))
        self.sp_count.setValue(min(n, 1000))
        # Die Anzahl darf nicht über das Ende des Arrays hinausreichen.
        self.sp_start.valueChanged.connect(lambda v: self.sp_count.setMaximum(max(1, min(hi - v + 1, 1000))))
        form = QFormLayout(self)
        form.addRow(QLabel(tr("<b>{0}</b> (Array[{1}..{2}] of {3})").format(node.path, lo, hi, node.type)))
        form.addRow(tr("Erster Index:"), self.sp_start)
        form.addRow(tr("Anzahl (max. 1000):"), self.sp_count)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        form.addRow(box)


class TagBrowser(QDialog):
    """Auswahl von Variablen aus der Variablenliste einer Steuerung."""

    def __init__(self, parent, plc, existing, targets, default_target):
        """plc: Steuerung (plc_common.Plc); existing: Menge bereits angelegter Tag-Namen; targets: Beschriftungen
        "Diagramm › Y-Achse"; default_target: vorausgewählter Eintrag."""
        super().__init__(parent)
        self.setWindowTitle(tr("Variablen aus der Steuerung wählen – {0}").format(plc.name))
        self.resize(1100, 740)
        self.plc = plc
        self.existing = {e.lower() for e in existing}
        self.checked = {}                 # Tag-Name -> Typ der angehakten Werte (bleibt beim Filtern erhalten)
        self.result_tags, self.result_blocks = [], []
        self.target_index = default_target
        self._busy = False                # True, solange der Baum programmatisch gefüllt wird
        self._job = None                  # laufender Ladevorgang: dict(thread, result, error, t0)
        self.tree_data = TagTree(None)

        info = QLabel(tr("Steuerung <b>{0}</b> – {1}:{2}, TLS {3}").format(plc.name, plc.ip, plc.port, TLS_MODES.get(plc.tls, plc.tls))
                      + tr(". Variablennamen und Datentypen kommen direkt aus der Steuerung (S7CommPlus); "
                      "optimierte Datenbausteine werden symbolisch gelesen."))
        info.setWordWrap(True)

        # ---- Knopfleiste oben ----
        self.btn_load = QPushButton(tr("Variablenliste aus Steuerung laden"))
        self.btn_load.setToolTip(tr("Nach einer Programmänderung in der Steuerung neu laden (dauert einige Sekunden)"))
        self.btn_load.clicked.connect(self.load_from_plc)
        self.btn_block = QPushButton(tr("Markiertes Array als Block…"))
        self.btn_block.setToolTip(tr("Array aus Zahlen mit einer einzigen Leseanfrage übernehmen (auch per Doppelklick)"))
        self.btn_block.clicked.connect(self.take_block)
        self.ed_filter = QLineEdit()
        self.ed_filter.setPlaceholderText(tr("Filter (Name, ab 2 Zeichen)…"))
        self.ed_filter.setClearButtonEnabled(True)
        # Filtern erst 300 ms nach der letzten Eingabe (große Tag-Listen).
        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.timeout.connect(self.refresh)
        self.ed_filter.textChanged.connect(lambda _t: self.filter_timer.start(300))
        top = QHBoxLayout()
        for w in (self.btn_load, self.btn_block):
            top.addWidget(w)
        top.addStretch(1)
        top.addWidget(self.ed_filter, 1)

        # ---- Baum: Name | Datentyp | Tag-Name | Hinweis ----
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels([tr("Name"), tr("Datentyp"), tr("Variablenname"), tr("Hinweis")])
        self.tree.setColumnWidth(0, 330)
        self.tree.setColumnWidth(1, 120)
        self.tree.setColumnWidth(2, 380)
        self.tree.itemExpanded.connect(self.populate)
        self.tree.itemChanged.connect(self.on_item_changed)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._double_click(it))

        self.status = QLabel("")
        self.status.setWordWrap(True)

        # ---- Unten: Ziel für die neuen Variablen und Knöpfe ----
        self.cb_target = QComboBox()
        self.cb_target.addItems(targets)
        if 0 <= default_target < len(targets):
            self.cb_target.setCurrentIndex(default_target)
        self.lbl_count = QLabel("")
        btn_ok = QPushButton(tr("Auswahl übernehmen"))
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self.take_selection)
        btn_close = QPushButton(tr("Schließen"))
        btn_close.clicked.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel(tr("Neue Variablen anlegen in:")))
        bottom.addWidget(self.cb_target, 1)
        bottom.addWidget(self.lbl_count)
        bottom.addWidget(btn_ok)
        bottom.addWidget(btn_close)

        lay = QVBoxLayout(self)
        lay.addWidget(info)
        lay.addLayout(top)
        lay.addWidget(self.tree, 1)
        lay.addWidget(self.status)
        lay.addLayout(bottom)

        self.poll = QTimer(self)
        self.poll.timeout.connect(self._poll)
        # Zwischengespeicherte Liste sofort anzeigen; ohne sie gleich aus der Steuerung laden.
        cached = load_cache(plc)
        if cached:
            self.set_data(cached, tr("zwischengespeicherte Liste – mit „Variablenliste laden“ aktualisieren"))
        else:
            self.status.setText(tr("Noch keine Variablenliste vorhanden – sie wird aus der Steuerung geladen …"))
            QTimer.singleShot(100, self.load_from_plc)

    # ---------------- Laden (im Hintergrund) ----------------
    def load_from_plc(self):
        """Variablenliste in einem eigenen Thread laden; ein Zeitgeber fragt das Ende ab (keine Qt-Aufrufe im Thread)."""
        if self._job:
            return
        job = {"result": None, "error": None, "t0": time.time()}

        def work():
            try:
                job["result"] = fetch_tag_list(self.plc)     # speichert die Liste auch zwischen
            except Exception as e:          # Verbindung, fehlendes s7commplus …
                job["error"] = e

        job["thread"] = threading.Thread(target=work, daemon=True)
        self._job = job
        self.btn_load.setEnabled(False)
        self.status.setText(tr("Lade Variablenliste von {0} …").format(self.plc.ip))
        job["thread"].start()
        self.poll.start(150)

    def _poll(self):
        job = self._job
        if job is None:
            self.poll.stop()
            return
        if job["thread"].is_alive():
            self.status.setText(tr("Lade Variablenliste von {0} … {1:.0f} s").format(self.plc.ip, time.time() - job['t0']))
            return
        self.poll.stop()
        self._job = None
        self.btn_load.setEnabled(True)
        if job["error"] is not None:
            e = job["error"]
            hint = (tr("\n\nDas Python-Paket s7commplus fehlt (pip install s7commplus).")
                    if isinstance(e, ImportError) else
                    tr("\n\nIP-Adresse, Port, TLS-Einstellung und Passwort prüfen (TCP-Port 102 muss erreichbar sein)."))
            self.status.setText(tr("Variablenliste konnte nicht geladen werden: {0}").format(e))
            QMessageBox.warning(self, tr("Variablenliste"), f"{e}{hint}")
            return
        self.set_data(job["result"], tr("aus der Steuerung geladen"))

    def set_data(self, data, origin):
        """Neue Tag-Liste übernehmen und anzeigen."""
        self.tree_data = TagTree(data)
        inf = data.get("info", {})
        parts = [tr("Protokoll V{0}").format(inf['protokoll']) if inf.get("protokoll") else "",
                 f"TLS {inf['tls']}" if inf.get("tls") else ""]
        extra = " · ".join(x for x in parts if x)
        self.status.setText(tr("{0} Variablen ({1})").format(len(data.get('items', [])), origin) + (f" – {extra}" if extra else ""))
        self.refresh()

    # ---------------- Baum ----------------
    def refresh(self):
        """Baum neu aufbauen: hierarchisch oder (mit Filter) als Trefferliste."""
        self._busy = True
        self.tree.clear()
        text = self.ed_filter.text().strip()
        if len(text) >= 2:
            hits = self.tree_data.search(text)
            for n in hits:
                self.tree.addTopLevelItem(self._item(n, label=n.path))
            if len(hits) >= 2000:
                self.status.setText(tr("Mehr als 2000 Treffer – bitte den Filter verfeinern."))
        else:
            for n in self.tree_data.roots():
                self.tree.addTopLevelItem(self._item(n))
        self._busy = False
        if not text and self.tree.topLevelItemCount():
            self.tree.topLevelItem(0).setExpanded(True)      # löst populate() aus
        self._update_count()

    def _item(self, n, label=None):
        """Baumeintrag zum Knoten n (Kinder kommen erst beim Aufklappen)."""
        typ = n.type
        if n.kind == "array":
            typ = f"{n.type}[{','.join(str(d) for d in n.dims)}]"
        scope = n.kind == "scope"
        it = QTreeWidgetItem([label or n.label, "" if scope else typ, "" if scope else n.path, ""])
        it.setData(0, ROLE_NODE, n)
        if n.kind in ("scope", "struct", "array"):
            it.addChild(QTreeWidgetItem())             # Platzhalter für den Aufklapp-Pfeil
            if n.can_block:
                it.setText(3, tr("als Block lesbar (Doppelklick)"))
            elif n.kind == "array" and n.length > MAX_ELEMENTS:
                it.setText(3, tr("zeigt die ersten {0} Elemente").format(MAX_ELEMENTS))
        elif n.dtype:
            if n.path.lower() in self.existing:
                it.setCheckState(0, Qt.CheckState.Checked)
                it.setFlags(it.flags() & ~CHECKABLE)
                it.setText(3, tr("bereits in der Liste"))
            else:
                it.setFlags(it.flags() | CHECKABLE)
                it.setCheckState(0, Qt.CheckState.Checked if n.path in self.checked else Qt.CheckState.Unchecked)
        else:
            it.setText(3, tr("Typ wird nicht aufgezeichnet"))
            it.setForeground(0, self.palette().placeholderText())
        return it

    def populate(self, item):
        """Kinder beim ersten Aufklappen erzeugen."""
        if item.childCount() != 1 or item.child(0).data(0, ROLE_NODE) is not None:
            return
        n = item.data(0, ROLE_NODE)
        if n is None:
            return
        self._busy = True
        item.takeChild(0)
        for c in self.tree_data.children(n):
            item.addChild(self._item(c))
        self._busy = False

    def _double_click(self, item):
        n = item.data(0, ROLE_NODE)
        if n is not None and n.can_block:
            self.take_block()

    # ---------------- Häkchen ----------------
    def on_item_changed(self, item, col):
        if col != 0 or self._busy:
            return
        n = item.data(0, ROLE_NODE)
        if n is None or not n.dtype or not (item.flags() & CHECKABLE):
            return
        if item.checkState(0) == Qt.CheckState.Checked:
            self.checked[n.path] = n.dtype
        else:
            self.checked.pop(n.path, None)
        self._update_count()

    def _update_count(self):
        nb = len(self.result_blocks)
        self.lbl_count.setText(tr("{0} Variablen").format(len(self.checked)) + (tr(", {0} Blöcke").format(nb) if nb else "") + tr(" gewählt"))

    # ---------------- Übernahme ----------------
    def take_block(self):
        """Markiertes Array als Block vormerken (Startindex und Anzahl im Dialog)."""
        it = self.tree.currentItem()
        n = it.data(0, ROLE_NODE) if it is not None else None
        if n is None or not n.can_block:
            QMessageBox.information(self, tr("Als Block übernehmen"),
                                    tr("Bitte ein eindimensionales Array aus Zahlen oder BOOL markieren "
                                    "(z. B. Array[1..100] of Real)."))
            return
        dlg = BlockSpecDialog(self, n)
        if dlg.exec():
            self.result_blocks.append((n.path, readable_type(n.type), dlg.sp_start.value(), dlg.sp_count.value()))
            it.setText(3, tr("als Block vorgemerkt ({0} Elemente ab [{1}])").format(dlg.sp_count.value(), dlg.sp_start.value()))
            self._update_count()

    def take_selection(self):
        if not self.checked and not self.result_blocks:
            QMessageBox.information(self, tr("Auswahl"), tr("Es sind keine neuen Variablen angehakt und keine Blöcke vorgemerkt."))
            return
        self.result_tags = sorted(self.checked.items(), key=lambda kv: kv[0].lower())
        self.target_index = self.cb_target.currentIndex()
        self.accept()
