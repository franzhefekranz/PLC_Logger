"""Editor für berechnete Variablen (wird vom Konfigurationsprogramm geöffnet).

Der Dialog bearbeitet Name und Formel einer berechneten Variable. Er bietet

* ein Formelfeld mit Listen zum Einfügen von Variablen und Funktionen (Doppelklick),
* eine laufende Prüfung der Formel (Syntax, unbekannte Variablen) mit Rückmeldung,
* eine Testtabelle: für jede in der Formel verwendete Variable lässt sich ein Testwert eingeben;
  das Ergebnis wird sofort berechnet (die eigentliche Auswertung macht s7_formula.Formula).

Ergebnis nach OK: ``result_name`` und ``result_formula``.
"""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFontDatabase
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from s7_formula import CONSTANTS, FUNCTIONS, check
from s7_i18n import tr

# Hilfetext unter dem Formelfeld (HTML, wird in einem QLabel angezeigt).
HELP = (
    tr("<b>Variablen</b> in geschweiften Klammern: <code>{Name}</code> (Doppelklick in der Liste fügt ein). "
    "Operatoren: <code>+ - * / // % **</code>, Vergleiche <code>&lt; &gt; == !=</code>, "
    "<code>and or not</code>, Bedingung: <code>a if {x} &gt; 5 else b</code>. "
    "Konstanten: ") + ", ".join(CONSTANTS) + tr(". Berechnete Variablen dürfen früher definierte "
    "berechnete Variablen verwenden.")
)


class FormulaEditor(QDialog):
    """Dialog zum Anlegen/Bearbeiten einer berechneten Variable (Name + Formel)."""
    def __init__(self, parent, names, name="", formula="", taken=()):
        """names: Variablen, die in der Formel verwendbar sind; taken: bereits vergebene Namen."""
        # Dialog als Kind des Konfigurationsfensters (modal über exec()).
        super().__init__(parent)
        self.setWindowTitle(tr("Berechnete Variable"))
        self.resize(940, 640)
        # names: nur diese Variablen sind in der Formel erlaubt (echte + früher definierte berechnete);
        # taken: Namen, die für die neue Variable nicht mehr in Frage kommen (Kollisionen).
        self.names = list(names)
        self.taken = set(taken)
        # Ergebnis des Dialogs (wird erst nach erfolgreichem OK gesetzt).
        self.result_name = ""
        self.result_formula = ""
        # Zuletzt eingegebene Testwerte je Variablenname (bleiben beim Ändern der Formel erhalten).
        self._test = {}

        # ---- Eingabefelder links ----
        self.ed_name = QLineEdit(name)
        self.ed_name.setPlaceholderText(tr("Name der berechneten Variable"))
        self.ed_formula = QPlainTextEdit(formula)
        # Festbreitenschrift: Klammern und Operatoren sind so besser lesbar.
        self.ed_formula.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.ed_formula.setPlaceholderText(tr("z. B.  ({Temp_Vorlauf} + {Temp_Ruecklauf}) / 2"))
        self.ed_formula.setMinimumHeight(110)
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)

        # Tabelle mit den in der Formel verwendeten Variablen und je einem editierbaren Testwert.
        self.tbl = QTableWidget(0, 2)
        self.tbl.setHorizontalHeaderLabels([tr("Verwendete Variable"), tr("Testwert")])
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.setColumnWidth(0, 300)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setMaximumHeight(170)
        btn_check = QPushButton(tr("Prüfen / Berechnen"))
        btn_check.clicked.connect(self.check)

        # Kurze Syntaxhilfe unter dem Formelfeld.
        help_lbl = QLabel(HELP)
        help_lbl.setWordWrap(True)

        # ---- Listen rechts: Variablen (filterbar) und Funktionen ----
        self.ed_filter = QLineEdit()
        self.ed_filter.setPlaceholderText(tr("Variablen filtern…"))
        self.ed_filter.setClearButtonEnabled(True)
        self.ed_filter.textChanged.connect(self.filter_vars)
        self.lst_vars = QListWidget()
        for n in self.names:
            self.lst_vars.addItem(n)
        # Doppelklick fügt {Name} an der Cursorposition ein.
        self.lst_vars.itemDoubleClicked.connect(lambda it: self.insert("{" + it.text() + "}"))
        self.lst_funcs = QListWidget()
        # Funktionsliste aus der Tabelle FUNCTIONS in s7_formula (Text = Beschreibung, UserRole = Funktionsname).
        for fname, (desc, _lo, _hi) in FUNCTIONS.items():
            it = QListWidgetItem(desc)
            it.setData(Qt.ItemDataRole.UserRole, fname)
            self.lst_funcs.addItem(it)
        # Doppelklick fügt 'funktionsname(' ein; die schließende Klammer setzt der Benutzer.
        self.lst_funcs.itemDoubleClicked.connect(
            lambda it: self.insert(it.data(Qt.ItemDataRole.UserRole) + "("))

        # ---- Layout ----
        right = QVBoxLayout()
        right.addWidget(QLabel(tr("<b>Variablen</b> (Doppelklick = einfügen)")))
        right.addWidget(self.ed_filter)
        right.addWidget(self.lst_vars, 2)
        right.addWidget(QLabel(tr("<b>Funktionen</b> (Doppelklick = einfügen)")))
        right.addWidget(self.lst_funcs, 3)

        left = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Name:")))
        row.addWidget(self.ed_name, 1)
        left.addLayout(row)
        left.addWidget(QLabel(tr("<b>Formel</b>")))
        left.addWidget(self.ed_formula, 1)
        left.addWidget(help_lbl)
        left.addWidget(self.lbl_status)
        left.addWidget(self.tbl)
        left.addWidget(btn_check)

        # OK wird nicht direkt angenommen, sondern erst nach der Prüfung in accept_checked().
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept_checked)
        buttons.rejected.connect(self.reject)

        body = QHBoxLayout()
        body.addLayout(left, 3)
        body.addLayout(right, 2)
        lay = QVBoxLayout(self)
        lay.addLayout(body, 1)
        lay.addWidget(buttons)

        # Zeitverzögerte Prüfung: erst 500 ms nach der letzten Eingabe prüfen, damit nicht bei jedem Tastendruck gerechnet wird.
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.check)
        self.ed_formula.textChanged.connect(lambda: self.timer.start(500))
        # Beim Bearbeiten einer vorhandenen Formel sofort prüfen und Testtabelle füllen.
        if formula:
            self.check()

    # ---------------- Hilfen ----------------
    # Text an der Cursorposition einfügen und den Fokus zurück ins Formelfeld geben.
    def insert(self, text):
        self.ed_formula.insertPlainText(text)
        self.ed_formula.setFocus()

    # Variablenliste nach dem Suchtext filtern (Groß-/Kleinschreibung egal).
    def filter_vars(self, text):
        text = text.strip().lower()
        for i in range(self.lst_vars.count()):
            it = self.lst_vars.item(i)
            it.setHidden(bool(text) and text not in it.text().lower())

    # Testwerte aus der Tabelle in self._test übernehmen; ungültige Eingaben werden zu NaN (Komma als Dezimaltrenner erlaubt).
    def _read_test_values(self):
        for r in range(self.tbl.rowCount()):
            n = self.tbl.item(r, 0).text()
            try:
                self._test[n] = float(self.tbl.item(r, 1).text().replace(",", "."))
            except ValueError:
                self._test[n] = float("nan")

    # Tabelle für die Variablen der Formel neu aufbauen; bereits eingegebene Testwerte bleiben erhalten (Standard: 1).
    def _fill_table(self, refs):
        self._read_test_values()
        # Signale blockieren, damit das Befüllen keine Änderungsereignisse auslöst.
        self.tbl.blockSignals(True)
        self.tbl.setRowCount(0)
        for n in refs:
            r = self.tbl.rowCount()
            self.tbl.insertRow(r)
            it = QTableWidgetItem(n)
            it.setFlags(Qt.ItemFlag.ItemIsEnabled)
            # Unbekannte Variablen rot markieren.
            if n not in self.names:
                it.setForeground(QBrush(QColor("#c0392b")))
                it.setToolTip(tr("Diese Variable existiert nicht (oder ist erst später definiert)"))
            self.tbl.setItem(r, 0, it)
            self.tbl.setItem(r, 1, QTableWidgetItem(f"{self._test.get(n, 1.0):g}"))
        self.tbl.blockSignals(False)

    # ---------------- Prüfen ----------------
    def check(self):
        """Formel prüfen und mit den Testwerten berechnen. -> Formel oder None"""
        # Eigentliche Formelprüfung (Syntaxbaum, erlaubte Elemente) liegt in s7_formula.check().
        f, err = check(self.ed_formula.toPlainText())
        if f is None:
            # Fehler: Testtabelle leeren und die Meldung in Rot anzeigen (bei leerem Feld keine Meldung).
            self.tbl.setRowCount(0)
            msg = self.ed_formula.toPlainText().strip()
            self.lbl_status.setText("<span style='color:#c0392b'>✗ {0}</span>".format(err) if msg else "")
            return None
        self._fill_table(f.refs)
        self._read_test_values()
        # Testwerte als Wörterbuch {Variablenname: Wert}; fehlende Eingaben = NaN.
        vals = {n: self._test.get(n, float("nan")) for n in f.refs}
        f.evaluate(0.0, vals)               # zwei Auswertungen im Abstand von 1 s, damit
        res = f.evaluate(1.0, vals)         # ddt/integ/avg ein Ergebnis liefern
        # Variablen, die nicht zur Auswahl gehören (z. B. Tippfehler im Namen).
        unknown = [n for n in f.refs if n not in self.names]
        txt = tr("✓ Formel gültig. Ergebnis mit den Testwerten: ") + (
            tr("nicht berechenbar (z. B. Division durch 0 oder fehlender Testwert)")
            if res != res else "<b>{0:g}</b>".format(res))
        color = "#27ae60"
        if unknown:
            txt += tr("<br>⚠ Unbekannte Variablen: {0}").format(', '.join(unknown))
            color = "#d68910"
        self.lbl_status.setText("<span style='color:{0}'>{1}</span>".format(color, txt))
        return f

    # Wird bei OK aufgerufen: Name, Formel und Variablenbezüge müssen gültig sein, erst dann schließt der Dialog.
    def accept_checked(self):
        name = self.ed_name.text().strip()
        # Name: nicht leer; kein ';' (Trennzeichen der CSV-Datei).
        if not name or ";" in name:
            QMessageBox.warning(self, tr("Name"), tr("Bitte einen Namen ohne ';' eingeben."))
            return
        # Name darf nicht mit einer anderen Variablen (oder einem Block-Element) kollidieren.
        if name in self.taken:
            QMessageBox.warning(self, tr("Name"), tr("Der Name „{0}“ ist bereits vergeben.").format(name))
            return
        f = self.check()
        if f is None:
            QMessageBox.warning(self, tr("Formel"), tr("Die Formel ist ungültig oder leer."))
            return
        # Alle verwendeten Variablen müssen bekannt sein (und bei berechneten: weiter oben in der Tabelle stehen).
        unknown = [n for n in f.refs if n not in self.names]
        if unknown:
            QMessageBox.warning(
                self, tr("Formel"),
                tr("Unbekannte oder erst später definierte Variablen:\n") + "\n".join(unknown))
            return
        # Selbstbezug ausschließen (die Formel würde ihren eigenen Wert benötigen).
        if name in f.refs:
            QMessageBox.warning(self, tr("Formel"), tr("Die Formel darf sich nicht auf sich selbst beziehen."))
            return
        self.result_name = name
        self.result_formula = f.text
        self.accept()
