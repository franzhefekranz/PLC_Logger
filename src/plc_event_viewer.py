# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Ereignis-Viewer: zeigt das Ereignisprotokoll der Trigger und quittiert Ereignisse.

Wird aus dem Logger geöffnet (Knopf "🔔" in der Statusleiste oder Menü Datei > Ereignisprotokoll) und lässt sich auch
allein starten, z. B. an einem zweiten Rechner oder neben einem Headless-Logger:

    plc_logger.py --ereignisse [Konfigurationsdatei | Ereignisdatei.csv]
    python plc_event_viewer.py [Konfigurationsdatei | Ereignisdatei.csv]

Ohne Angabe wird das Ereignisprotokoll der zuletzt benutzten Konfiguration geöffnet. Die Anzeige aktualisiert sich
selbst, sobald neue Ereignisse in die Datei geschrieben werden. Quittieren schreibt eine Zeile "QUITTIERT" mit Zeit
und Windows-Benutzername in die Datei; danach zählt das Ereignis nicht mehr als offen.
"""
import os
import sys

import getpass

from PySide6.QtCore import QDateTime, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QBrush, QColor, QDesktopServices, QFont, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDateTimeEdit, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QPlainTextEdit,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from plc_events import NOTE, PRIORITIES, EventLog, event_log_path
from plc_i18n import tr

MAX_ROWS = 20000                     # mehr Zeilen werden nicht angezeigt (neueste zuerst)
PRIO_COLORS = {"Alarm": "#f8d0d0", "Warnung": "#fbefc4", "Info": "#d9e8fb"}
NOTE_COLOR = "#e3f4e1"               # Hintergrund von Notizen
COLUMNS = ["Nr.", tr("Kommt"), tr("Geht"), tr("Priorität"), tr("Trigger"), tr("Meldung"), tr("Quittiert")]


def _short(stamp):
    """'2026-10-15 16:20:01.250' -> '15.10.2026 16:20:01'."""
    if not stamp or len(stamp) < 19:
        return stamp or ""
    return f"{stamp[8:10]}.{stamp[5:7]}.{stamp[0:4]} {stamp[11:19]}"


class NoteDialog(QDialog):
    """Notiz von Hand ins Ereignisprotokoll eintragen (Zeit, Text, Verfasser)."""

    def __init__(self, parent=None, when=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Notiz ins Ereignisprotokoll"))
        self.resize(520, 300)
        self.ed_time = QDateTimeEdit(QDateTime.fromSecsSinceEpoch(int(when)) if when else QDateTime.currentDateTime())
        self.ed_time.setDisplayFormat("dd.MM.yyyy HH:mm:ss")
        self.ed_time.setCalendarPopup(True)
        self.ed_time.setToolTip(tr("Zeitpunkt, auf den sich die Notiz bezieht (Standard: jetzt)"))
        self.ed_text = QPlainTextEdit()
        self.ed_text.setPlaceholderText(tr("z. B. Ventil V12 getauscht, Sollwert auf 65 °C geändert …"))
        self.ed_user = QLineEdit(getpass.getuser())
        form = QFormLayout()
        form.addRow(tr("Zeit:"), self.ed_time)
        form.addRow(tr("Notiz:"), self.ed_text)
        form.addRow(tr("Verfasser:"), self.ed_user)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._check)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form, 1)
        lay.addWidget(bb)
        self.ed_text.setFocus()

    def _check(self):
        if not self.ed_text.toPlainText().strip():
            QMessageBox.warning(self, tr("Notiz"), tr("Bitte einen Text eingeben."))
            return
        self.accept()

    def values(self):
        """(Zeit als Unix-Zeitstempel, Text, Verfasser)."""
        return (self.ed_time.dateTime().toSecsSinceEpoch(), self.ed_text.toPlainText().strip(),
                self.ed_user.text().strip() or getpass.getuser())


def add_note(parent, log: EventLog, when=None):
    """Dialog für eine Notiz zeigen und sie eintragen. Rückgabe: True, wenn eine Notiz eingetragen wurde."""
    dlg = NoteDialog(parent, when)
    if not dlg.exec():
        return False
    ts, text, user = dlg.values()
    try:
        log.note(text, ts, user)
    except (OSError, ValueError) as e:
        QMessageBox.warning(parent, tr("Notiz"), tr("Die Notiz konnte nicht gespeichert werden:\n{0}").format(e))
        return False
    return True


class EventViewer(QDialog):
    """Tabelle der Ereignisse mit Filter und Quittierung (nicht modal)."""

    def __init__(self, log: EventLog, parent=None, on_change=None, standalone=False, on_goto=None):
        super().__init__(parent)
        self.log, self.on_change, self.standalone = log, on_change, standalone
        self.on_goto = on_goto                # Rückruf (Beginn, Ende, Text): Ereignis im Diagramm zeigen (Logger)
        self._seen = None                     # (version, mtime) der zuletzt angezeigten Daten
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.resize(1000, 560)
        lay = QVBoxLayout(self)

        # Filterzeile
        top = QHBoxLayout()
        self.chk_open = QCheckBox(tr("nur offene"))
        self.chk_open.toggled.connect(self.fill)
        self.cb_prio = QComboBox()
        self.cb_prio.addItem(tr("alle Prioritäten"), "")
        for p in PRIORITIES:
            self.cb_prio.addItem(tr(p), p)
        self.cb_prio.addItem(tr("nur Notizen"), NOTE)
        self.cb_prio.currentIndexChanged.connect(self.fill)
        self.ed_find = QLineEdit()
        self.ed_find.setPlaceholderText(tr("Suchen (Trigger oder Meldung) …"))
        self.ed_find.setClearButtonEnabled(True)
        self.ed_find.textChanged.connect(self.fill)
        top.addWidget(self.chk_open)
        top.addWidget(self.cb_prio)
        top.addWidget(self.ed_find, 1)
        lay.addLayout(top)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        hh = self.table.horizontalHeader()
        for c in range(len(COLUMNS)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.doubleClicked.connect(
            lambda _i: self.ack_selected() if self.selected_ids() & self.log.open_ids else None)
        lay.addWidget(self.table, 1)

        # Knöpfe
        bot = QHBoxLayout()
        self.lbl = QLabel("")
        bot.addWidget(self.lbl, 1)
        btn_note = QPushButton(tr("Notiz hinzufügen …"))
        btn_note.setToolTip(tr("Eigenen Eintrag mit Zeitstempel ins Ereignisprotokoll schreiben"))
        btn_note.clicked.connect(self.new_note)
        bot.addWidget(btn_note)
        self.btn_goto = QPushButton(tr("Im Diagramm zeigen"))
        self.btn_goto.setToolTip(tr("Zeitraum um das markierte Ereignis im Logger anzeigen, Lineale auf Beginn und Ende "
                                    "(auch Rechtsklick auf eine Zeile)"))
        self.btn_goto.clicked.connect(self.goto_selected)
        self.btn_goto.setVisible(on_goto is not None)
        bot.addWidget(self.btn_goto)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.btn_ack = QPushButton(tr("Markierte quittieren"))
        self.btn_ack.setToolTip(tr("Ausgewählte offene Ereignisse quittieren (auch Doppelklick auf eine Zeile)"))
        self.btn_ack.clicked.connect(self.ack_selected)
        self.btn_all = QPushButton(tr("Alle quittieren"))
        self.btn_all.clicked.connect(self.ack_all)
        btn_folder = QPushButton(tr("Ordner öffnen"))
        btn_folder.setToolTip(tr("Ordner der Ereignisdatei im Explorer öffnen"))
        btn_folder.clicked.connect(self.open_folder)
        bot.addWidget(self.btn_ack)
        bot.addWidget(self.btn_all)
        bot.addWidget(btn_folder)
        if standalone:
            btn_file = QPushButton(tr("Datei öffnen …"))
            btn_file.clicked.connect(self.choose_file)
            bot.addWidget(btn_file)
        btn_close = QPushButton(tr("Schließen"))
        btn_close.clicked.connect(self.close)
        bot.addWidget(btn_close)
        lay.addLayout(bot)

        act = QAction(self)
        act.setShortcut(QKeySequence.StandardKey.Refresh)       # F5
        act.triggered.connect(lambda: self.fill(force=True))
        self.addAction(act)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(1000)
        self.set_log(log)

    # ------------------------------------------------------------------ Daten
    def set_log(self, log):
        """Anderes Ereignisprotokoll anzeigen (z. B. nach dem Laden einer anderen Konfiguration)."""
        self.log = log
        self.setWindowTitle(tr("Ereignisprotokoll – {0}").format(log.path))
        self.fill(force=True)

    def _poll(self):
        if self.isVisible():
            if self.log.changed_on_disk():
                self.log.reload()
            if self._seen != self.log.version:
                self.fill()

    def fill(self, *_args, force=False):
        """Tabelle neu füllen (Auswahl bleibt erhalten)."""
        self._seen = self.log.version
        try:
            events = self.log.events()
        except (OSError, UnicodeDecodeError) as e:
            self.table.setRowCount(0)
            self.lbl.setText(tr("Datei nicht lesbar: {0}").format(e))
            return
        total, n_open = sum(1 for e in events if not e.notiz), sum(1 for e in events if e.offen)
        n_notes = len(events) - total
        prio = self.cb_prio.currentData() or ""
        text = self.ed_find.text().strip().lower()
        shown = [e for e in events
                 if (not self.chk_open.isChecked() or e.offen) and (not prio or e.prio == prio)
                 and (not text or text in e.trigger.lower() or text in e.text.lower())]
        selected = self.selected_ids()
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(min(len(shown), MAX_ROWS))
        bold = QFont()
        bold.setBold(True)
        grey = QBrush(QColor("#808080"))
        for r, e in enumerate(shown[:MAX_ROWS]):
            if e.notiz:
                status = tr("Notiz von {0}").format(e.benutzer)
            elif e.offen:
                status = tr("offen")
            elif e.quittiert:
                status = f"{_short(e.quittiert)}  {e.benutzer}"
            else:
                status = tr("– (ohne Quittierung)")
            vals = [str(e.id), _short(e.zeit), _short(e.gegangen) or ("" if not e.pflicht else "—"),
                    tr(e.prio), ("📝 " + tr(e.trigger)) if e.notiz else e.trigger, e.text.replace("\n", " ⏎ "), status]
            bg = QBrush(QColor(PRIO_COLORS.get(e.prio, "#ffffff"))) if e.offen else None
            if e.notiz:
                bg = QBrush(QColor(NOTE_COLOR))
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 0:
                    it.setData(Qt.ItemDataRole.UserRole, e.id)
                if bg is not None:
                    it.setBackground(bg)
                    it.setForeground(QBrush(QColor("#000000")))
                    if c in (3, 6):
                        it.setFont(bold)
                elif e.quittiert or e.gegangen:
                    it.setForeground(grey)              # erledigt: grau
                self.table.setItem(r, c, it)
        self.table.setUpdatesEnabled(True)
        if selected:
            for r in range(self.table.rowCount()):
                if self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) in selected:
                    self.table.selectRow(r)
        more = tr(" (angezeigt: die neuesten {0})").format(MAX_ROWS) if len(shown) > MAX_ROWS else ""
        self.lbl.setText(tr("{0} Ereignisse, davon {1} offen · {2} Notizen · {3} nach Filter{4}").format(total, n_open, n_notes, len(shown), more))
        self._update_buttons()

    def selected_event(self):
        ids = self.selected_ids()
        if len(ids) != 1:
            return None
        i = next(iter(ids))
        return next((e for e in self.log.events() if e.id == i), None)

    def goto_selected(self):
        e = self.selected_event()
        if e is None or self.on_goto is None:
            return
        from plc_events import parse_stamp
        t0 = parse_stamp(e.zeit)
        t1 = parse_stamp(e.gegangen) if e.gegangen else None
        if t0 is not None:
            self.on_goto(t0, t1, f"{e.trigger}: {e.text}".strip(": "))

    def _context_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        self.table.selectRow(row)
        menu = QMenu(self)
        if self.on_goto is not None:
            menu.addAction(tr("Im Diagramm zeigen"), self.goto_selected)
        a = menu.addAction(tr("Quittieren"), self.ack_selected)
        a.setEnabled(bool(self.selected_ids() & self.log.open_ids))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def selected_ids(self):
        rows = {i.row() for i in self.table.selectedItems()}
        return {self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in rows if self.table.item(r, 0)}

    def _update_buttons(self):
        n_open = self.log.open_count()
        self.btn_all.setEnabled(n_open > 0)
        self.btn_all.setText(tr("Alle quittieren ({0})").format(n_open) if n_open else tr("Alle quittieren"))
        self.btn_ack.setEnabled(bool(self.selected_ids() & self.log.open_ids))
        self.btn_goto.setEnabled(len(self.selected_ids()) == 1)

    def new_note(self):
        if add_note(self, self.log):
            self.fill(force=True)
            if self.on_change:
                self.on_change()

    # ------------------------------------------------------------------ Quittieren
    def _done(self, n):
        self.fill(force=True)
        if self.on_change:
            self.on_change()
        if n == 0:
            QMessageBox.information(self, tr("Quittieren"), tr("Keine offenen Ereignisse ausgewählt."))

    def ack_selected(self):
        ids = self.selected_ids()
        if not ids:
            return
        try:
            n = self.log.acknowledge(ids)
        except OSError as e:
            QMessageBox.warning(self, tr("Quittieren"), tr("Die Ereignisdatei ist nicht beschreibbar:\n{0}").format(e))
            return
        self._done(n)

    def ack_all(self):
        n_open = self.log.open_count()
        if not n_open:
            return
        if QMessageBox.question(self, tr("Alle quittieren"), tr("{0} offene Ereignisse quittieren?").format(n_open)) \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            n = self.log.acknowledge(None)
        except OSError as e:
            QMessageBox.warning(self, tr("Quittieren"), tr("Die Ereignisdatei ist nicht beschreibbar:\n{0}").format(e))
            return
        self._done(n)

    # ------------------------------------------------------------------ Datei
    def open_folder(self):
        folder = os.path.dirname(self.log.path)
        if os.path.isdir(folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        else:
            QMessageBox.information(self, tr("Ordner"), tr("Der Ordner existiert noch nicht:\n{0}\n\nEr wird beim ersten Ereignis angelegt.").format(folder))

    def choose_file(self):
        start = os.path.dirname(self.log.path)
        path, _flt = QFileDialog.getOpenFileName(self, tr("Ereignisprotokoll öffnen"), start,
                                              tr("Ereignisprotokoll (*.csv);;Alle Dateien (*)"))
        if path:
            self.set_log(EventLog(path))


def resolve(arg=None):
    """Argument (Konfiguration oder Ereignisdatei, leer = letzte Konfiguration) -> (Ereignisdatei, Einstellungen)."""
    from plc_common import default_connection, last_config_path, load_config
    if arg and arg.lower().endswith(".csv"):
        try:
            conn = load_config(last_config_path())[0]
        except Exception:
            conn = default_connection()
        return os.path.abspath(arg), conn
    cfg = os.path.abspath(arg) if arg else last_config_path()
    try:
        conn = load_config(cfg)[0]
    except Exception:
        conn = default_connection()
    return event_log_path(conn), conn


def run_viewer(arg=None):
    """Viewer allein starten (eigenes Fenster, ohne Logger)."""
    from plc_branding import app_icon, set_windows_app_id
    set_windows_app_id()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from plc_i18n import install_qt
    install_qt(app)
    path, conn = resolve(arg)
    app.setWindowIcon(app_icon(conn.get("icon", ""), conn.get("logo", "")))
    from plc_about import install_help
    install_help()                                    # F1: Kontexthilfe
    w = EventViewer(EventLog(path), standalone=True)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run_viewer(sys.argv[1] if len(sys.argv) > 1 else None))
