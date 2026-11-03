# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Konfigurationsprogramm: Benutzer des Webservers verwalten (Name, Passwort und Schreibrecht).

Gespeichert wird je Benutzer nur ein Hash des Passworts (plc_web.hash_password); das Passwort selbst lässt sich aus
der Konfigurationsdatei nicht zurückgewinnen. Vergessene Passwörter werden deshalb einfach neu gesetzt.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout)

from plc_i18n import tr

MIN_LEN = 8


class PasswordDialog(QDialog):
    """Neues Passwort (zweimal) eingeben."""

    def __init__(self, parent, user):
        """Zwei verdeckte Eingabefelder für das neue Passwort von ``user``; Ergebnis in ``password``."""
        super().__init__(parent)
        self.setWindowTitle(tr("Passwort für {0}").format(user))
        self.ed1, self.ed2 = QLineEdit(), QLineEdit()
        for e in (self.ed1, self.ed2):
            e.setEchoMode(QLineEdit.EchoMode.Password)
        form = QFormLayout(self)
        form.addRow(tr("Neues Passwort:"), self.ed1)
        form.addRow(tr("Wiederholen:"), self.ed2)
        form.addRow(QLabel(tr("Mindestens {0} Zeichen.").format(MIN_LEN)))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.check)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.password = ""

    def check(self):
        """OK nur bei ausreichender Länge und zwei gleichen Eingaben."""
        a, b = self.ed1.text(), self.ed2.text()
        if len(a) < MIN_LEN:
            QMessageBox.warning(self, tr("Passwort"), tr("Das Passwort ist zu kurz (mindestens {0} Zeichen).").format(MIN_LEN))
            return
        if a != b:
            QMessageBox.warning(self, tr("Passwort"), tr("Die beiden Eingaben stimmen nicht überein."))
            return
        self.password = a
        self.accept()


class WebUsersDialog(QDialog):
    """Liste der Benutzer: hinzufügen, Passwort setzen, entfernen, Schreibrecht (Häkchen). Ergebnis: ``users``
    {Name: Hash} und ``rights`` {Name: "lesen"|"schreiben"}."""

    def __init__(self, parent, users, rights=None):
        """Liste der Benutzer mit Knöpfen Hinzufügen, Passwort ändern, Entfernen. ``users``: {Name: Passwort-Hash},
        ``rights``: {Name: Recht} (ohne Eintrag: Schreibrecht)."""
        from plc_webauth import parse_rights
        super().__init__(parent)
        self.setWindowTitle(tr("Webserver – Benutzer"))
        self.resize(460, 360)
        self.users = dict(users)
        self.rights = parse_rights(rights or {}, self.users)
        self.lst = QListWidget()
        self.lst.setToolTip(tr("Häkchen = Schreibrecht: Ereignisse quittieren, Notizen eintragen, Prozessbild "
                               "bearbeiten. Ohne Häkchen nur ansehen und exportieren."))
        self.lst.itemChanged.connect(self._right_changed)
        self._fill()
        btns = QVBoxLayout()
        for text, fn in ((tr("Hinzufügen …"), self.add), (tr("Passwort ändern …"), self.change),
                         (tr("Entfernen"), self.remove)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch(1)
        row = QHBoxLayout()
        row.addWidget(self.lst, 1)
        row.addLayout(btns)
        info = QLabel(tr("Häkchen = Schreibrecht (Ereignisse quittieren, Notizen, Prozessbild bearbeiten); ohne Häkchen "
                         "nur ansehen und exportieren. Ohne Benutzer ist keine Anmeldung nötig (nur der Zugriffscode "
                         "schützt, falls eingetragen). Für Anmeldungen über das Netz HTTPS einschalten, sonst ist das "
                         "Passwort mitlesbar."))
        info.setWordWrap(True)
        info.setStyleSheet("color:#555")
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(row, 1)
        lay.addWidget(info)
        lay.addWidget(bb)

    def _fill(self):
        """Liste alphabetisch neu füllen (Häkchen = Schreibrecht)."""
        from plc_webauth import WRITE
        self.lst.blockSignals(True)
        self.lst.clear()
        for n in sorted(self.users, key=str.lower):
            it = QListWidgetItem(n)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if self.rights.get(n, WRITE) == WRITE else Qt.CheckState.Unchecked)
            self.lst.addItem(it)
        self.lst.blockSignals(False)

    def _right_changed(self, item):
        from plc_webauth import READ, WRITE
        self.rights[item.text()] = WRITE if item.checkState() == Qt.CheckState.Checked else READ

    def _current(self):
        """Name des markierten Benutzers oder ""."""
        it = self.lst.currentItem()
        return it.text() if it is not None else ""

    def _set_password(self, name):
        """Passwort für ``name`` abfragen und als Hash speichern -> True bei OK."""
        from plc_webauth import hash_password
        dlg = PasswordDialog(self, name)
        if dlg.exec():
            self.users[name] = hash_password(dlg.password)
            return True
        return False

    def add(self):
        """Neuen Benutzer anlegen (Name abfragen, dann Passwort); doppelte Namen werden abgelehnt."""
        name, ok = QInputDialog.getText(self, tr("Benutzer hinzufügen"), tr("Benutzername:"))
        name = (name or "").strip()
        if not ok or not name:
            return
        if name in self.users:
            QMessageBox.information(self, tr("Benutzer"), tr("Den Benutzer gibt es schon."))
            return
        if self._set_password(name):
            from plc_webauth import READ
            self.rights[name] = READ                 # neue Benutzer: nur ansehen (Schreibrecht per Häkchen)
            self._fill()

    def change(self):
        """Passwort des markierten Benutzers neu setzen."""
        name = self._current()
        if name:
            self._set_password(name)

    def remove(self):
        """Markierten Benutzer nach Rückfrage entfernen."""
        name = self._current()
        if name and QMessageBox.question(self, tr("Benutzer entfernen"), tr("Benutzer „{0}“ entfernen?").format(name)) \
                == QMessageBox.StandardButton.Yes:
            self.users.pop(name, None)
            self.rights.pop(name, None)
            self._fill()
