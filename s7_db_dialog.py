"""Lesemodus für die Datenbank: Zeitraum und Variablen wählen, Werte laden und im Logger offline anzeigen.

Geöffnet im Logger über Datei › Aus Datenbank laden … . Alle Datenbankzugriffe laufen in einem Hintergrund-Thread, damit
das Fenster bedienbar bleibt (Abbrechen jederzeit möglich). Ergebnis nach OK: ``result`` = (Zeiten, Namen, Spalten,
Beschreibung) – dasselbe Format wie beim Laden einer CSV-Datei.
"""
import os
import threading
import time
from datetime import datetime, timedelta

from PyQt6.QtCore import QDateTime, Qt, QTimer
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                             QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                             QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from s7_common import BASE_DIR, load_settings, save_settings
from s7_db import AUTO_POINTS, DbReader, LoadCancelled, db_settings, nice_raster
from s7_i18n import N_, tr

ALL_PROJECTS = "\x00alle"
# Auflösung: Schlüssel -> (Text, Raster in s; -1 = automatisch, 0 = Rohdaten)
RESOLUTIONS = [("auto", N_("Automatisch (höchstens {0} Punkte je Variable)"), -1),
               ("roh", N_("Rohdaten (jeder gespeicherte Wert)"), 0),
               ("1s", N_("Mittelwert je 1 s"), 1), ("10s", N_("Mittelwert je 10 s"), 10),
               ("1m", N_("Mittelwert je 1 min"), 60), ("10m", N_("Mittelwert je 10 min"), 600),
               ("1h", N_("Mittelwert je 1 h"), 3600), ("1d", N_("Mittelwert je Tag"), 86400)]
FMT = "%d.%m.%Y %H:%M:%S"


def _fmt(ts):
    try:
        return datetime.fromtimestamp(ts).strftime(FMT)
    except (OverflowError, OSError, ValueError):
        return "?"


def _span_text(s):
    s = abs(float(s))
    if s < 60:
        return tr("{0:g} s").format(round(s, 1))
    if s < 3600:
        return tr("{0:g} min").format(round(s / 60, 1))
    if s < 86400:
        return tr("{0:g} h").format(round(s / 3600, 1))
    return tr("{0:g} Tage").format(round(s / 86400, 1))


def _num(n):
    return f"{int(n):,}".replace(",", ".")


class DbLoadDialog(QDialog):
    def __init__(self, parent, conn, config_names=(), project=""):
        super().__init__(parent)
        self.setWindowTitle(tr("Aus Datenbank laden"))
        self.conn = dict(conn)
        self.config_names = set(config_names)
        self.project = project
        self.sqlite_file = None
        self.reader = None
        self.info = []                       # [(Name, erster, letzter, Anzahl)]
        self.result = None
        self._job = None                     # laufender Hintergrundauftrag
        self._cancel = False
        self._progress = 0
        prefs = load_settings().get("db_lesen", {}) or {}

        lay = QVBoxLayout(self)
        # ---- Quelle
        src = QHBoxLayout()
        self.lbl_db = QLabel()
        self.lbl_db.setWordWrap(True)
        src.addWidget(self.lbl_db, 1)
        btn_file = QPushButton(tr("SQLite-Datei wählen …"))
        btn_file.setToolTip(tr("Eine andere SQLite-Datei lesen (z. B. Kopie einer Aufzeichnung)"))
        btn_file.clicked.connect(self.choose_file)
        src.addWidget(btn_file)
        btn_cfg = QPushButton(tr("Datenbank der Konfiguration"))
        btn_cfg.clicked.connect(self.use_config_db)
        src.addWidget(btn_cfg)
        lay.addLayout(src)

        # ---- Projekt und Variablen
        box_v = QGroupBox(tr("Variablen"))
        lv = QVBoxLayout(box_v)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Projekt:")))
        self.cb_project = QComboBox()
        self.cb_project.setMinimumWidth(220)
        self.cb_project.currentIndexChanged.connect(lambda _i: self.load_variables())
        row.addWidget(self.cb_project)
        row.addSpacing(16)
        self.ed_filter = QLineEdit()
        self.ed_filter.setPlaceholderText(tr("Filter …"))
        self.ed_filter.textChanged.connect(self.apply_filter)
        row.addWidget(self.ed_filter, 1)
        lv.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Variable"), tr("Erster Wert"), tr("Letzter Wert"), tr("Werte")])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.itemChanged.connect(lambda _it, _c: self.update_summary())
        lv.addWidget(self.tree, 1)
        row = QHBoxLayout()
        for text, how in ((tr("Alle"), "all"), (tr("Keine"), "none"), (tr("Wie Konfiguration"), "cfg")):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, h=how: self.check(h))
            row.addWidget(b)
        row.addStretch(1)
        lv.addLayout(row)
        lay.addWidget(box_v, 1)

        # ---- Zeitraum
        box_t = QGroupBox(tr("Zeitraum"))
        lt = QGridLayout(box_t)
        self.dt_from = QDateTimeEdit()
        self.dt_to = QDateTimeEdit()
        for w in (self.dt_from, self.dt_to):
            w.setCalendarPopup(True)
            w.setDisplayFormat("dd.MM.yyyy HH:mm:ss")
            w.dateTimeChanged.connect(lambda _d: self.update_summary())
        lt.addWidget(QLabel(tr("Von:")), 0, 0)
        lt.addWidget(self.dt_from, 0, 1)
        lt.addWidget(QLabel(tr("Bis:")), 0, 2)
        lt.addWidget(self.dt_to, 0, 3)
        quick = QHBoxLayout()
        for text, key, tip in (
                (tr("Letzte Stunde"), "1h", tr("Die letzte Stunde vor dem letzten gespeicherten Wert")),
                (tr("Letzte 24 h"), "24h", tr("Die letzten 24 Stunden vor dem letzten gespeicherten Wert")),
                (tr("Heute"), "heute", ""), (tr("Gestern"), "gestern", ""),
                (tr("Letzte 7 Tage"), "7d", tr("Die letzten 7 Tage vor dem letzten gespeicherten Wert")),
                (tr("Letzte 30 Tage"), "30d", tr("Die letzten 30 Tage vor dem letzten gespeicherten Wert")),
                (tr("Alles"), "alles", tr("Vom ersten bis zum letzten Wert der gewählten Variablen"))):
            b = QPushButton(text)
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(lambda _c=False, k=key: self.quick_range(k))
            quick.addWidget(b)
        quick.addStretch(1)
        lt.addLayout(quick, 1, 0, 1, 5)
        lt.setColumnStretch(4, 1)
        lay.addWidget(box_t)

        # ---- Auflösung
        box_r = QGroupBox(tr("Darstellung"))
        lr = QFormLayout(box_r)
        self.cb_res = QComboBox()
        for key, text, _r in RESOLUTIONS:
            self.cb_res.addItem(tr(text).format(_num(AUTO_POINTS)), key)
        self.cb_res.setCurrentIndex(max(self.cb_res.findData(prefs.get("aufloesung", "auto")), 0))
        self.cb_res.currentIndexChanged.connect(lambda _i: self.update_summary())
        self.cb_res.setToolTip(tr("Mittelwerte werden von der Datenbank berechnet – für lange Zeiträume deutlich "
                                  "schneller und speichersparender als Rohdaten."))
        lr.addRow(tr("Auflösung:"), self.cb_res)
        self.chk_hold = QCheckBox(tr("Fehlende Werte mit dem letzten Wert füllen"))
        self.chk_hold.setToolTip(tr("Sinnvoll, wenn die Aufzeichnung „nur Änderungen“ schreibt: ein fehlender Wert "
                                    "bedeutet dann „unverändert“."))
        self.chk_hold.setChecked(bool(db_settings(self.conn)["nur_aenderungen"]))
        lr.addRow("", self.chk_hold)
        lay.addWidget(box_r)

        # ---- Zusammenfassung, Knöpfe
        self.lbl_sum = QLabel()
        self.lbl_sum.setWordWrap(True)
        lay.addWidget(self.lbl_sum)
        self.lbl_status = QLabel()
        self.lbl_status.setStyleSheet("color:#555")
        lay.addWidget(self.lbl_status)
        bb = QDialogButtonBox()
        self.btn_count = bb.addButton(tr("Werte zählen"), QDialogButtonBox.ButtonRole.ActionRole)
        self.btn_count.setToolTip(tr("Anzahl der Werte im gewählten Zeitraum ermitteln"))
        self.btn_count.clicked.connect(self.count_values)
        self.btn_load = bb.addButton(tr("Laden und anzeigen"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_load.clicked.connect(self.start_load)
        self.btn_cancel = bb.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.btn_cancel.clicked.connect(self.on_cancel)
        lay.addWidget(bb)

        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._poll)
        self.resize(820, 720)
        now = time.time()
        self._set_range(now - 86400, now)
        self.connect_db()

    # ------------------------------------------------------------------ Hintergrundaufträge
    def _run(self, text, fn, done):
        """fn() im Hintergrund ausführen, danach done(Ergebnis) bzw. Fehlermeldung (im Qt-Thread)."""
        if self._job is not None:
            return
        self._cancel, self._progress = False, 0
        job = {"res": None, "err": None, "done": done, "text": text, "t0": time.time()}

        def work():
            try:
                job["res"] = fn()
            except BaseException as e:          # noqa: BLE001 – auch Abbruch/Speicherfehler melden
                job["err"] = e
        job["thread"] = threading.Thread(target=work, name="db-lesen", daemon=True)
        self._job = job
        self._set_busy(True)
        self.lbl_status.setText(text)
        job["thread"].start()
        self.timer.start()

    def _poll(self):
        job = self._job
        if job is None:
            self.timer.stop()
            return
        if job["thread"].is_alive():
            extra = tr(" – {0} Werte gelesen").format(_num(self._progress)) if self._progress else ""
            self.lbl_status.setText(f"{job['text']} ({time.time() - job['t0']:.0f} s){extra}")
            return
        self.timer.stop()
        self._job = None
        self._set_busy(False)
        if job["err"] is not None:
            e = job["err"]
            if isinstance(e, LoadCancelled):
                self.lbl_status.setText(tr("Abgebrochen."))
                return
            self.lbl_status.setText(tr("Fehler: {0}").format(e))
            QMessageBox.warning(self, tr("Datenbank"), f"{type(e).__name__}: {e}" if not str(e) else str(e))
            return
        self.lbl_status.setText("")
        job["done"](job["res"])

    def _set_busy(self, busy):
        for w in (self.btn_load, self.btn_count, self.cb_project, self.tree):
            w.setEnabled(not busy)
        self.btn_cancel.setText(tr("Abbrechen") if busy else tr("Schließen"))
        if busy:
            self.setCursor(Qt.CursorShape.BusyCursor)
        else:
            self.unsetCursor()

    def on_cancel(self):
        if self._job is not None:
            self._cancel = True
            self.lbl_status.setText(tr("Breche ab …"))
            return
        self.reject()

    def closeEvent(self, ev):
        self._cancel = True
        super().closeEvent(ev)

    def done(self, r):
        self._cancel = True
        if self.reader is not None and self._job is None:
            self.reader.close()
        super().done(r)

    # ------------------------------------------------------------------ Verbindung, Projekte, Variablen
    def choose_file(self):
        start = os.path.dirname(db_settings(self.conn)["datei"]) or BASE_DIR
        path, _ = QFileDialog.getOpenFileName(self, tr("SQLite-Datei wählen"), start,
                                              tr("SQLite (*.db *.sqlite *.sqlite3);;Alle Dateien (*)"))
        if path:
            self.sqlite_file = path
            self.connect_db()

    def use_config_db(self):
        self.sqlite_file = None
        self.connect_db()

    def connect_db(self):
        if self._job is not None:
            return
        if self.reader is not None:
            self.reader.close()
            self.reader = None
        self.tree.clear()
        self.cb_project.blockSignals(True)
        self.cb_project.clear()
        self.cb_project.blockSignals(False)
        try:
            reader = DbReader(self.conn, self.sqlite_file)
        except Exception as e:
            self.lbl_db.setText("<b>" + tr("Datenbank:") + "</b> " + str(e))
            self.lbl_status.setText(tr("Mit „SQLite-Datei wählen …“ kann eine Datei direkt gelesen werden."))
            self.update_summary()
            return
        self.lbl_db.setText("<b>" + tr("Datenbank:") + "</b> " + reader.describe())

        def fn():
            reader.connect()
            return reader.projects()

        def done(projects):
            self.reader = reader
            self.cb_project.blockSignals(True)
            self.cb_project.addItem(tr("(alle Projekte)"), ALL_PROJECTS)
            for p in projects:
                self.cb_project.addItem(p or tr("(ohne Projektname)"), p)
            i = self.cb_project.findData(self.project)
            self.cb_project.setCurrentIndex(i if i >= 0 else (1 if len(projects) == 1 else 0))
            self.cb_project.blockSignals(False)
            self.load_variables()
        self._run(tr("Verbinde …"), fn, done)

    def current_project(self):
        p = self.cb_project.currentData()
        return None if p in (None, ALL_PROJECTS) else p

    def load_variables(self):
        if self.reader is None:
            return
        proj = self.current_project()

        def done(info):
            self.info = info
            self.tree.blockSignals(True)
            self.tree.clear()
            use_cfg = any(n in self.config_names for n, *_r in info)
            for name, a, b, c in info:
                it = QTreeWidgetItem([name, _fmt(a), _fmt(b), _num(c)])
                it.setData(0, Qt.ItemDataRole.UserRole, (a, b, c))
                it.setTextAlignment(3, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                on = (name in self.config_names) if use_cfg else True
                it.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
                self.tree.addTopLevelItem(it)
            for k in (1, 2, 3):
                self.tree.resizeColumnToContents(k)
            self.tree.blockSignals(False)
            self.apply_filter()
            if not info:
                self.lbl_status.setText(tr("Keine Werte in der Datenbank (Tabelle leer oder anderes Projekt)."))
            self.quick_range("24h")
        self._run(tr("Lese Variablenliste …"), lambda: self.reader.variables(proj), done)

    def apply_filter(self):
        f = self.ed_filter.text().strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            it.setHidden(bool(f) and f not in it.text(0).lower())

    def check(self, how):
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.isHidden() and how != "cfg":
                continue
            on = how == "all" or (how == "cfg" and it.text(0) in self.config_names)
            it.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.tree.blockSignals(False)
        self.update_summary()

    def selected(self):
        out = []
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.checkState(0) == Qt.CheckState.Checked:
                out.append((it.text(0),) + tuple(it.data(0, Qt.ItemDataRole.UserRole)))
        return out

    # ------------------------------------------------------------------ Zeitraum
    def _data_range(self):
        sel = self.selected() or [(n, a, b, c) for n, a, b, c in self.info]
        if not sel:
            now = time.time()
            return now - 86400, now
        return min(s[1] for s in sel), max(s[2] for s in sel)

    def _set_range(self, t0, t1):
        for w, ts in ((self.dt_from, t0), (self.dt_to, t1)):
            w.blockSignals(True)
            w.setDateTime(QDateTime.fromSecsSinceEpoch(int(ts)))
            w.blockSignals(False)
        self.update_summary()

    def quick_range(self, key):
        first, last = self._data_range()
        end = int(last) + 1
        if key == "alles":
            self._set_range(int(first), end)
        elif key in ("heute", "gestern"):
            day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            if key == "gestern":
                day -= timedelta(days=1)
            self._set_range(day.timestamp(), (day + timedelta(days=1)).timestamp() - 1)
        else:
            span = {"1h": 3600, "24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400}[key]
            self._set_range(max(int(first), end - span), end)

    def time_range(self):
        t0 = self.dt_from.dateTime().toSecsSinceEpoch()
        t1 = self.dt_to.dateTime().toSecsSinceEpoch() + 0.999
        return float(t0), float(t1)

    def raster(self):
        key = self.cb_res.currentData()
        return next(r for k, _t, r in RESOLUTIONS if k == key)

    def update_summary(self):
        sel = self.selected()
        t0, t1 = self.time_range()
        if t1 <= t0:
            self.lbl_sum.setText("<span style='color:#c0392b'>" + tr("„Bis“ muss nach „Von“ liegen.") + "</span>")
            return
        r = self.raster()
        res = tr("Rohdaten") if r == 0 else (tr("automatisch") if r < 0 else tr("Mittelwert je {0}").format(_span_text(r)))
        # grobe Schätzung aus der Variablenliste (gleichmäßige Verteilung angenommen)
        est = 0
        for _n, a, b, c in sel:
            overlap = max(0.0, min(b, t1) - max(a, t0))
            est += c * (overlap / (b - a) if b > a else (1 if a >= t0 and a <= t1 else 0))
        self.lbl_sum.setText(tr("{0} Variablen, Zeitraum {1} ({2}), Auflösung: {3}, geschätzt ca. {4} Werte")
                             .format(len(sel), _span_text(t1 - t0), f"{_fmt(t0)} – {_fmt(t1)}", res, _num(est)))

    # ------------------------------------------------------------------ Zählen, Laden
    def count_values(self):
        sel = self.selected()
        if self.reader is None or not sel:
            return
        names, (t0, t1), proj = [s[0] for s in sel], self.time_range(), self.current_project()

        def done(n):
            self.lbl_status.setText(tr("{0} Werte im gewählten Zeitraum ({1} je Variable im Mittel).")
                                    .format(_num(n), _num(n / max(len(names), 1))))
        self._run(tr("Zähle Werte …"), lambda: self.reader.count(names, t0, t1, proj), done)

    def start_load(self):
        sel = self.selected()
        if self.reader is None:
            return
        if not sel:
            QMessageBox.information(self, tr("Aus Datenbank laden"), tr("Bitte mindestens eine Variable wählen."))
            return
        t0, t1 = self.time_range()
        if t1 <= t0:
            return
        names, proj, raster, hold = [s[0] for s in sel], self.current_project(), self.raster(), self.chk_hold.isChecked()
        save_settings(db_lesen={"aufloesung": self.cb_res.currentData()})

        def progress(n):
            self._progress = n

        def fn():
            r = raster
            if r < 0:                                    # automatisch: Rohdaten, solange es nicht zu viele sind
                n = self.reader.count(names, t0, t1, proj)
                r = 0 if n / max(len(names), 1) <= AUTO_POINTS else nice_raster(t1 - t0)
            data = self.reader.load(names, t0, t1, proj, raster_s=r, hold=hold,
                                    cancel=lambda: self._cancel, progress=progress)
            return data + (r,)

        def done(res):
            t, nm, cols, r = res
            if not len(t):
                QMessageBox.information(self, tr("Aus Datenbank laden"),
                                        tr("Im gewählten Zeitraum sind keine Werte vorhanden."))
                return
            how = tr("Rohdaten") if r == 0 else tr("Mittelwert je {0}").format(_span_text(r))
            label = tr("Datenbank {0}, {1} – {2}, {3}").format(self.reader.describe(), _fmt(t0), _fmt(t1), how)
            self.result = (t, nm, cols, label)
            self.accept()
        self._run(tr("Lade Werte …"), fn, done)
