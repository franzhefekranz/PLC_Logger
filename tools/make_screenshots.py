# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Alle Bilder der Bedienungsanleitung automatisch erzeugen (Fenster im Demo-Modus öffnen und abfotografieren).

Aufruf:  python tools/make_screenshots.py [--lang de|en] [--out ORDNER] [--only name1,name2]

Deutsch landet in ``doc/images``, Englisch in ``doc/images/en``. Der Workflow *Screenshots* führt das Skript unter
Windows aus (Bilder wie im echten Programm) und legt das Ergebnis im Zweig ``bilder`` ab.

Ablauf
------
1. Demo-Konfiguration im temporären Ordner: zwei Steuerungen, Diagramme Prozess/Regelkreis/Zustände, ein BOOL-Block,
   Trigger, Webserver (HTTPS, Benutzer „franz“), OPC-UA-Server, SQLite-Datenbank, Logo.
2. Logger im Demo-Modus 75 s aufzeichnen lassen; danach die Bilder des Loggers (online, offline, Lineale, Analyse,
   Ereignisse, Berichte …), dann Konfigurationsprogramm, IO-Check, Startbild und zuletzt die Webseiten.
3. Modale Dialoge: ``QDialog.exec`` ist ersetzt – steht ein Auftrag in ``JOBS``, wird der Dialog gezeigt, vorbereitet
   und fotografiert (wahlweise über dem Elternfenster), sonst sofort geschlossen. Datei- und Meldungsdialoge liefern
   vorgegebene Antworten.
4. Webseiten (Diagramme, Anmeldung, Prozessbild, IO-Check mobil) mit Playwright/Chromium, PDF-Seiten mit PyMuPDF – fehlt
   eines davon, entfallen nur diese Bilder.

Jedes Bild ist eine eigene Funktion (``@shot``); schlägt eine fehl, laufen die übrigen weiter, am Ende steht die Liste
der Fehler. Die Webseiten sind deutsch (sie haben keine Übersetzung) und erscheinen in beiden Sprachen gleich.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

SHOTS = []          # [(Name, Funktion)] in Aufrufreihenfolge
JOBS = []           # Aufträge für den nächsten modalen Dialog (siehe fake_exec)
FILES = []          # Antworten der Dateidialoge (der Reihe nach)
CTX = {}            # gemeinsame Objekte: Logger, Konfigurationsprogramm, IO-Check, Pfade …
WEB_USER, WEB_PW = "franz", "geheim123"


def shot(name):
    """Bildfunktion registrieren; ``name`` ohne .png (mehrere Bilder einer Funktion: Name des ersten)."""
    def deco(fn):
        SHOTS.append((name, fn))
        return fn
    return deco


# ---------------------------------------------------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------------------------------------------------
def wait(ms):
    """Qt-Ereignisse verarbeiten (Zeichnen, Timer) für ms Millisekunden."""
    from PySide6.QtTest import QTest
    QTest.qWait(ms)


def save(name, what, crop=None):
    """Widget oder QPixmap als <name>.png speichern; ``crop`` = (x, y, w, h) schneidet aus."""
    from PySide6.QtCore import QRect
    pm = what if hasattr(what, "copy") and not hasattr(what, "grab") else what.grab()
    if crop:
        pm = pm.copy(QRect(*crop))
    path = os.path.join(CTX["out"], name + ".png")
    pm.save(path)
    print(f"Bild: {name}.png ({pm.width()} x {pm.height()})", flush=True)


def compose(base, child, pos=None, margin=None):
    """Bild ``child`` (Widget/QPixmap) über ``base`` (Widget/QPixmap) zeichnen – mittig oder an ``pos`` – mit Rahmen.

    ``margin``: nur den Bereich um das Bild ``child`` mit diesem Rand zurückgeben (statt des ganzen Hintergrunds)."""
    from PySide6.QtGui import QColor, QPainter, QPen
    b = base.grab() if hasattr(base, "grab") else base.copy()
    c = child.grab() if hasattr(child, "grab") else child
    if pos is None:
        pos = (max(0, (b.width() - c.width()) // 2), max(0, (b.height() - c.height()) // 2))
    p = QPainter(b)
    p.fillRect(pos[0] + 4, pos[1] + 4, c.width(), c.height(), QColor(0, 0, 0, 60))     # Schatten
    p.drawPixmap(pos[0], pos[1], c)
    p.setPen(QPen(QColor("#7a8794"), 1))
    p.drawRect(pos[0], pos[1], c.width() - 1, c.height() - 1)
    p.end()
    if margin is not None:
        from PySide6.QtCore import QRect
        x0, y0 = max(0, pos[0] - margin), max(0, pos[1] - margin)
        b = b.copy(QRect(x0, y0, min(b.width() - x0, c.width() + 2 * margin), min(b.height() - y0,
                                                                                   c.height() + 2 * margin)))
    return b


def job(name, prep=None, over=None, size=None, result=0, margin=None):
    """Auftrag für den nächsten modalen Dialog: fotografieren als ``name``; ``prep(dlg)`` bereitet vor, ``over()``
    liefert das Hintergrundfenster (Bild über Fenster, mit ``margin`` nur der Ausschnitt um den Dialog), ``size`` =
    Dialoggröße."""
    JOBS.append({"name": name, "prep": prep, "over": over, "size": size, "result": result, "margin": margin})


def fake_exec(dlg):
    """Ersatz für QDialog.exec: Auftrag ausführen (zeigen, vorbereiten, fotografieren) oder sofort zurückkehren."""
    j = JOBS.pop(0) if JOBS else None
    if j is None:
        return 0
    if j["size"]:
        dlg.resize(*j["size"])
    dlg.show()
    dlg.raise_()
    wait(500)
    if j["prep"]:
        j["prep"](dlg)
        wait(400)
    if j["name"]:
        save(j["name"], compose(j["over"](), dlg, margin=j.get("margin")) if j["over"] else dlg)
    dlg.hide()
    return j["result"]


def render_pdf(pdf, name, dpi=110):
    """Erste Seite einer PDF-Datei als Bild (PyMuPDF)."""
    import fitz                                         # pip install pymupdf
    doc = fitz.open(pdf)
    doc[0].get_pixmap(dpi=dpi).save(os.path.join(CTX["out"], name + ".png"))
    print(f"Bild: {name}.png (PDF)", flush=True)


def find_top(cls_name):
    """Zuletzt geöffnetes sichtbares Fenster einer Klasse (z. B. nicht modale Analysefenster)."""
    from PySide6.QtWidgets import QApplication
    wins = [w for w in QApplication.topLevelWidgets() if type(w).__name__ == cls_name and w.isVisible()]
    return wins[-1] if wins else None


def menu_shot(name, window, menu, size=(520, 230)):
    """Geöffnetes Menü über dem linken oberen Teil des Fensters fotografieren."""
    from PySide6.QtCore import QPoint, QRect
    bar = window.menuBar()
    geo = bar.actionGeometry(menu.menuAction())
    menu.popup(bar.mapToGlobal(geo.bottomLeft()))
    wait(500)
    base = window.grab().copy(QRect(0, 0, max(size[0], geo.x() + menu.width() + 20),
                                    max(size[1], geo.bottom() + menu.height() + 20)))
    pos = window.mapFromGlobal(menu.pos()) if menu.pos() != QPoint(0, 0) else geo.bottomLeft()
    save(name, compose(base, menu, (max(0, pos.x()), max(0, pos.y()))))
    menu.hide()


# ---------------------------------------------------------------------------------------------------------------------
# Demo-Daten
# ---------------------------------------------------------------------------------------------------------------------
def demo_config(folder):
    """Demo-Konfiguration für die Bilder -> Pfad der JSON-Datei."""
    from plc_common import Block, Plc, default_connection, save_config
    from plc_recorder import demo_config as demo
    from plc_webauth import hash_password
    charts, variables = demo()
    for k, v in enumerate(variables):
        if not v.formula:
            v.address = f"DB1.DBX100.{k % 8}" if v.dtype == "BOOL" else f"DB1.DBD{4 * k}"
    conn = default_connection()
    conn.update(csv_ordner=folder, archiv_ordner=os.path.join(folder, "archiv"), projekt="Kesselhaus Linie 1",
                csv_name="kesselhaus", web_port=8080, web_host="0.0.0.0", web_aktiv=1, web_https=1,
                web_benutzer=json.dumps({WEB_USER: hash_password(WEB_PW, 1000)}), logo="logo.png",
                benachrichtigung=json.dumps({"aktiv": True, "prio_min": "Warnung",
                                             "email": {"aktiv": True, "server": "smtp.firma.de",
                                                       "an": "schicht@firma.de"},
                                             "ntfy": {"aktiv": True, "url": "https://ntfy.sh/kesselhaus-4711"}}),
                opcua_server=json.dumps({"aktiv": True, "port": 4840,
                                         "sicherheit": ["none", "Basic256Sha256,SignAndEncrypt"],
                                         "anonym": False, "benutzer": "web"}),
                db_typ="sqlite", db_datei=os.path.join(folder, "datenlogger.db"), bericht_aktiv=1,
                bericht_zeitraum="schicht", aufr_csv_tage=90, aufr_csv_mb=2000, aufr_db_tage=365)
    plc1 = Plc(name="SPS 1", driver="s7")
    plc1.params.update(ip="192.168.0.10")
    plc2 = Plc(name="SPS 2", driver="clx", intervall_ms=500)
    plc2.params.update(ip="192.168.0.20")
    blocks = [Block(name="Ventile", address="DB10.DBX0.0", dtype="BOOL", count=8, chart=2, axis=1, color="#e377c2")]
    path = os.path.join(folder, "kesselhaus.json")
    save_config(conn, charts, variables, path, blocks=blocks, plcs=[plc1, plc2])
    from plc_events import save_triggers
    from plc_recorder import demo_triggers
    save_triggers(path, demo_triggers())
    # Prozessbild mit Seite „Linie 1 – Kesselhaus“
    from plc_web_prozess import save_layout
    tiles = [{"typ": "zeiger", "var": "Temperatur", "titel": "Kesseltemperatur", "einheit": "°C", "min": 0, "max": 100,
              "og_warn": 70, "og_alarm": 80, "x": 0, "y": 0, "w": 3, "h": 3},
             {"typ": "wert", "var": "Druck", "einheit": "bar", "nk": 2, "ug_warn": 25, "x": 3, "y": 0, "w": 3, "h": 2},
             {"typ": "status", "var": "Pumpe", "titel": "Pumpe P1", "text_ein": "läuft", "text_aus": "steht",
              "x": 6, "y": 0, "w": 3, "h": 1},
             {"typ": "balken", "var": "Stellwert", "einheit": "%", "min": 0, "max": 100, "x": 6, "y": 1, "w": 3,
              "h": 1},
             {"typ": "wert", "var": "Zähler", "titel": "Stückzahl", "nk": 0, "x": 9, "y": 0, "w": 3, "h": 2},
             {"typ": "trend", "var": "Sinus", "fenster_s": 120, "x": 3, "y": 2, "w": 6, "h": 2},
             {"typ": "wert", "var": "Istwert", "titel": "Füllstand", "einheit": "%", "x": 9, "y": 2, "w": 3, "h": 2},
             {"typ": "zeiger", "var": "Mittel", "min": 0, "max": 100, "x": 0, "y": 3, "w": 3, "h": 2}]
    save_layout(path, {"seiten": [{"name": "Linie 1 – Kesselhaus", "kacheln": tiles},
                                  {"name": "Regelkreis", "kacheln": []}]})
    return path


def io_list(folder):
    """IO-Liste (CSV) für den IO-Check: Eingänge, Ausgänge, Analogwerte in zwei Schränken -> Pfad."""
    rows = ["Adresse;Symbol;Kommentar;BMK;Schrank;Messbereich"]
    for k in range(24):
        rows.append(f"E{k // 8}.{k % 8};B{k:02d};Endlage Zylinder {k:02d};-B{k:02d};+S1;")
    for k in range(8):
        rows.append(f"A4.{k};Y{k:02d};Ventil {k:02d};-Y{k:02d};+S2;")
    rows += ["EW256;PT1;Druck Vorlauf;-PT1;+S2;0 … 10 bar", "EW258;TT1;Temperatur Kessel;-TT1;+S2;0 … 150 °C",
             "EW260;FT1;Durchfluss;-FT1;+S2;0 … 50 m³/h", "AW272;SV1;Stellventil;-SV1;+S2;0 … 100 %"]
    path = os.path.join(folder, "io_liste.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    return path


def clx_tags():
    """Tag-Liste einer Logix-Steuerung in der einfachen Form (wie clx_taglist.simplify) für den Auswahldialog."""
    tags = [("K1D10_PicFirstScan_Ton", "TIMER", []), ("PicFirstScan", "BOOL", []), ("Zaehler", "DINT", []),
            ("Messwerte", "REAL", [64]), ("Program:Main.Temperatur", "REAL", []), ("Program:Main.Druck", "REAL", []),
            ("Program:Main.Pumpe_Ein", "BOOL", []), ("Program:Main.Stoerung", "BOOL", []),
            ("Program:Safety.flash2Hz", "BOOL", []), ("Program:Safety.flash4Hz", "BOOL", []),
            ("Program:Safety.zaehler2", "DINT", [])]
    return {"tags": [{"name": n, "type": t, "dims": d, "struct": t == "TIMER", "access": "Read/Write"}
                     for n, t, d in tags],
            "types": {"TIMER": [{"name": "PRE", "type": "DINT", "array": 0, "struct": False},
                                {"name": "ACC", "type": "DINT", "array": 0, "struct": False},
                                {"name": "EN", "type": "BOOL", "array": 0, "struct": False},
                                {"name": "DN", "type": "BOOL", "array": 0, "struct": False}]},
            "info": {"name": "Linie1_PLC", "product": "1756-L73/B LOGIX5573", "revision": "32.11"}}


# ---------------------------------------------------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------------------------------------------------
@shot("logger_online")
def s_logger_online():
    """Logger im Demo-Modus aufzeichnen lassen, dann online fotografieren (auch Statuszeile und Legende)."""
    import plc_gui
    w = plc_gui.MainWindow(CTX["cfg"], demo=True)
    CTX["w"] = w
    w.resize(1600, 1000)
    w.show()
    from PySide6.QtCore import Qt
    wait(300)
    w.resizeDocks([w.dock], [230], Qt.Orientation.Vertical)     # Wertetabelle: mehrere Zeilen sichtbar
    w.act_run.setChecked(True)
    t_end = time.time() + 75
    while time.time() < t_end:
        wait(200)
    w.act_marks.setChecked(True)
    wait(800)
    save("logger_online", w)
    save("trigger_marken", w, (0, 0, 1400, 830))
    sb = w.statusBar()
    pm = sb.grab()
    save("status_leds", pm, (max(0, pm.width() - 520), 0, min(520, pm.width()), pm.height()))
    save("ereignis_statusleiste", w.btn_events)
    panel = w.master
    r = panel.legend.sceneBoundingRect()
    view = panel.plot.mapFromScene(r).boundingRect()
    pm = panel.plot.grab()
    save("legende", pm, (max(0, view.x() - 6), max(0, view.y() - 6), min(view.width() + 60, pm.width()),
                         min(view.height() + 12, pm.height())))


@shot("screenshot_menue")
def s_menus():
    """Menüs „Screenshot“ und „Sprache“ geöffnet."""
    w = CTX["w"]
    menu_shot("screenshot_menue", w, w.menu_shot)
    menu_shot("sprache_menue", w, w.menu_lang, (700, 420))


@shot("xy_diagramm")
def s_analysis():
    """XY-Diagramm und Frequenzanalyse (nicht modale Fenster)."""
    w = CTX["w"]
    for kind, name, cls in (("xy", "xy_diagramm", "XYDialog"), ("fft", "fft", "FftDialog")):
        # XY: Temperatur (x) gegen Mittel (y) – die ersten beiden sichtbaren Kurven; FFT: Sinus
        keep = {"Temperatur", "Mittel"} if kind == "xy" else {"Sinus"}
        saved, w.hidden = w.hidden, {v.name for v in w.vars if v.name not in keep}
        w.open_analysis(kind)
        w.hidden = saved
        wait(1500)
        d = find_top(cls)
        if d is not None:
            d.resize(1000, 670)
            wait(800)
            save(name, d)
            d.close()


@shot("anordnung_raster")
def s_layouts():
    """Seitenanordnung: Raster bzw. Tabs (Hauptfenster mit einem Diagramm)."""
    w = CTX["w"]
    w.set_page_mode("raster")
    wait(800)
    save("anordnung_raster", w)
    w.set_page_mode("untereinander")
    w.set_layout("tabs")
    wait(800)
    save("logger_hauptfenster", w)
    w.set_layout("untereinander")
    wait(600)


@shot("logger_offline")
def s_offline():
    """Offline mit Linealen, Wertetabelle, Ausschnitte."""
    from PySide6.QtCore import Qt
    w = CTX["w"]
    w.act_run.setChecked(False)
    wait(400)
    w.act_online.setChecked(False)
    wait(800)
    t = w.t
    t0, t1 = float(t[0]), float(t[-1])
    w.set_rulers(0, t0 + (t1 - t0) * 0.35)
    w.set_rulers(1, t0 + (t1 - t0) * 0.6)
    w.update_offline_values()
    wait(600)
    save("logger_offline", w)
    save("logger_lineale", w, (0, 0, 1430, 420))
    w.resizeDocks([w.dock], [420], Qt.Orientation.Vertical)
    wait(400)
    save("wertetabelle", w.dock, (0, 0, min(760, w.dock.width()), w.dock.height()))
    w.resizeDocks([w.dock], [230], Qt.Orientation.Vertical)
    p = w.panels[2] if len(w.panels) > 2 else w.master
    pm = p.grab()
    save("bool_signale", pm, (0, max(0, pm.height() - 240), min(600, pm.width()), min(240, pm.height())))


@shot("ereignis_viewer")
def s_events():
    """Ereignis-Viewer und Notiz-Dialog."""
    w = CTX["w"]
    w.show_events()
    ev = w.event_viewer
    ev.resize(1000, 590)
    wait(800)
    save("ereignis_viewer", ev)

    def prep(d):
        d.ed_text.setPlainText("Ventil V3 von Hand geöffnet, Druck kurzzeitig zu niedrig.")
    job("notiz", prep=prep, over=lambda: ev)
    w.add_note()
    ev.hide()


@shot("ereignis_diagramm")
def s_goto():
    """„Im Diagramm zeigen“: Ereignis in der Mitte der Aufzeichnung, Lineale auf Beginn und Ende."""
    w = CTX["w"]
    t = w.rec.snapshot()[0] if w.rec is not None else w.t
    t_mid = float(t[len(t) // 2])
    w.goto_time(t_mid, t_mid + 6.0, "Übertemperatur")
    wait(800)
    save("ereignis_diagramm", w)


@shot("export_dialog")
def s_export():
    """Dialog „Werte exportieren“."""
    job("export_dialog")
    CTX["w"].export_values()


@shot("pid_optimierung")
def s_pid():
    """PID-Optimierung des Diagramms „Regelkreis“."""
    w = CTX["w"]
    w.open_pid(1)
    wait(800)
    d = w._pid_dialogs[-1]
    d.resize(1250, 830)
    d.calculate()
    wait(1500)
    save("pid_optimierung", d)
    d.close()


@shot("pdf_bericht")
def s_report():
    """PDF-Bericht des angezeigten Zeitraums, erste Seite als Bild."""
    pdf = os.path.join(CTX["folder"], "bericht.pdf")
    FILES.append(pdf)
    CTX["w"].make_report()
    render_pdf(pdf, "pdf_bericht")


@shot("datenbank")
def s_db():
    """Lesemodus Datenbank (Werte der Demo-Aufzeichnung in SQLite)."""
    def prep(d):
        wait(2500)                                        # Verbindung und Variablenliste im Hintergrund
    job("datenbank", prep=prep, size=(820, 720))
    CTX["w"].load_db()


@shot("webserver_qr")
def s_qr():
    """Webserver-Adresse mit QR-Code (gleicher Aufbau wie Logger › Datei › Webserver-Adresse …)."""
    from html import escape
    from plc_i18n import tr
    from plc_iocheck_dialog import qr_dialog
    url = "https://192.168.0.20:8080/"
    text = tr("Adresse für Tablet/Smartphone im selben Netz:\n\n{0}").format(url)
    text += "\n\n" + tr("Anmeldung erforderlich ({0} Benutzer).").format(2)
    text += "\n\n" + tr("Prozessbild: {0}").format(url + "prozess")
    text += "\n\n" + tr("(Adresse in die Zwischenablage kopiert)")
    dlg = qr_dialog(None, tr("Webserver"), url, escape(text).replace("\n", "<br>"))
    dlg.show()
    wait(400)
    save("webserver_qr", dlg)
    dlg.close()


# ---------------------------------------------------------------------------------------------------------------------
# Konfigurationsprogramm
# ---------------------------------------------------------------------------------------------------------------------
def _cw():
    """Konfigurationsprogramm (einmal geöffnet, 1600 x 900)."""
    if "cw" not in CTX:
        import plc_config
        cw = plc_config.ConfigWindow(CTX["cfg"])
        cw.resize(1600, 900)
        cw.show()
        wait(600)
        CTX["cw"] = cw
    return CTX["cw"]


def _select_tree(cw, text):
    """Eintrag im Zuordnungsbaum (Diagramm/Achse) mit diesem Text wählen."""
    from PySide6.QtWidgets import QTreeWidgetItemIterator
    it = QTreeWidgetItemIterator(cw.tree)
    while it.value():
        if it.value().text(0).strip().startswith(text):
            cw.tree.setCurrentItem(it.value())
            wait(200)
            return it.value()
        it += 1
    return None


@shot("config_gesamt")
def s_config():
    """Konfigurationsprogramm: Gesamtansicht, Variablen, Filter, Eigenschaften und die Reiter."""
    cw = _cw()
    save("config_gesamt", cw)
    save("config_variablen", cw.table.parentWidget())
    _select_tree(cw, "Regelkreis")
    save("config_eigenschaften", cw.tree.parentWidget())
    cw.ed_filter.setText("Druck")
    wait(400)
    save("config_variablen_filter", cw)
    cw.ed_filter.setText("")
    for idx, name in ((0, "config_projekt_steuerungen"), (1, "config_aufzeichnung"), (2, "config_anzeige"),
                      (3, "config_web_headless"), (4, "config_datenbank"), (5, "config_trigger_ereignis"),
                      (6, "config_berichte")):
        cw.tabs.setCurrentIndex(idx)
        wait(300)
        save(name, cw.tabs)
    cw.tabs.setCurrentIndex(1)
    cw.cb_rec_mode.setCurrentIndex(max(0, cw.cb_rec_mode.findData("trigger")))
    cw.ed_rec_cond.setText("{Temperatur} > 70 or {Pumpe} == 0")
    wait(300)
    save("config_aufzeichnung_trigger", cw.tabs)
    cw.cb_rec_mode.setCurrentIndex(max(0, cw.cb_rec_mode.findData("dauernd")))
    cw.ed_rec_cond.setText("")
    cw.tabs.setCurrentIndex(0)


@shot("pid_einstellen")
def s_config_dialogs():
    """Dialoge des Konfigurationsprogramms: PID, Blöcke, Formel, Trigger, Webbenutzer."""
    cw = _cw()
    _select_tree(cw, "Regelkreis")
    job("pid_einstellen", over=lambda: cw, margin=200)
    cw.edit_pid()
    def blocks(d):
        from plc_common import Block
        d.add_row(Block(name="Puffer", address="DB100.DBX0.0", dtype="REAL", count=10, ring=100, plc=0,
                        color="#ff7f0e", driver=d.get_conn(0).driver))      # Ringpuffer (zyklussynchron)
        d.rebuild_tree()
    job("blockeditor", prep=blocks, size=(1400, 790))
    cw.open_block_editor()

    def formula(d):
        d.ed_name.setText("Summe")
        d.ed_formula.setPlainText("{Sinus} + {Druck}")
    job("formeleditor", prep=formula, size=(940, 670))
    cw.add_computed()

    def trig(d):
        d.table.selectRow(0)
        job("trigger_editor", over=lambda: d, size=(860, 560))
        d.edit_condition()
    job("", prep=trig, size=(1220, 760))
    cw.edit_triggers()
    cw.tabs.setCurrentIndex(3)
    wait(300)
    job("web_benutzer", over=lambda: cw, size=(560, 380), margin=160)
    cw.edit_web_users()
    cw.tabs.setCurrentIndex(0)


@shot("ads_auswahl")
def s_plc_dialogs():
    """Verbindungsdialoge der Treiber ADS und OPC UA, Tag-Auswahl einer Logix-Steuerung."""
    from plc_common import Plc, get_driver
    from plc_treiber.ui import PlcSettingsDialog
    cw = _cw()
    for drv, name in (("ads", "ads_auswahl"), ("opcua", "opcua_subscription")):
        d = PlcSettingsDialog(cw, "SPS 1", get_driver(drv), {})
        d.show()
        wait(400)
        save(name, compose(cw, d, margin=140))
        d.close()
    from plc_treiber.clx_browser import TagBrowser
    TagBrowser.load_from_plc = lambda self, *a, **k: None   # keine Verbindung zur (nicht vorhandenen) Steuerung
    plc = Plc(name="SPS 2", driver="clx")
    plc.params.update(ip="192.168.0.20")
    tb = TagBrowser(cw, plc, {"Zaehler", "Program:Main.Temperatur"}, ["Prozess › Sinus", "Zustände › Analog"], 0)
    tb.set_data(clx_tags(), "zwischengespeichert")
    tb.resize(1100, 770)
    tb.show()
    wait(400)
    for k in range(tb.tree.topLevelItemCount()):        # Controller- und Programm-Tags aufklappen, Arrays nicht
        it = tb.tree.topLevelItem(k)
        it.setExpanded(True)
        for j in range(it.childCount()):
            if it.child(j).text(0).startswith("Program:"):
                it.child(j).setExpanded(True)
    wait(300)
    save("symbolbaum", tb)
    tb.close()
    # Netzwerk durchsuchen: Ergebnis einer Suche (ohne Netzwerk nachgestellt)
    import plc_netscan as ns
    from plc_netscan_dialog import NetScanDialog
    found = [
        ns.suggest(ns.Found(ip="192.168.0.1", ports=[102]),
                   s7={"device": "CPU 315-2 PN/DP", "order": "6ES7 315-2EH14-0AB0", "station": "Kesselhaus",
                       "slot": 2}),
        ns.suggest(ns.Found(ip="192.168.0.10", ports=[102, 4840]),
                   s7={"device": "CPU 1516-3 PN/DP", "order": "6ES7 516-3AN02-0AB0", "station": "Linie 2",
                       "slot": 1}),
        ns.suggest(ns.Found(ip="192.168.0.20", ports=[44818]),
                   enip={"name": "1756-L83E/B", "vendor": 1, "revision": "33.011", "serial": "60C2F1A5"}),
        ns.suggest(ns.Found(ip="192.168.0.31", ports=[48898, 4840])),
        ns.suggest(ns.Found(ip="192.168.0.40", ports=[502])),
    ]
    d = NetScanDialog(cw, known_ips={"192.168.0.1"})
    d.ed_range.setText("192.168.0.0/24")
    d.progress.setValue(100)
    d.show_results(found)
    d.resize(1100, 470)
    d.show()
    wait(400)
    save("netzwerksuche", compose(cw, d, margin=40))
    d.close()


# ---------------------------------------------------------------------------------------------------------------------
# IO-Check
# ---------------------------------------------------------------------------------------------------------------------
@shot("iocheck_fenster")
def s_iocheck():
    """IO-Check mit importierter Liste, Demo-Werten und einigen geprüften Signalen."""
    import plc_iocheck as io
    import plc_iocheck_dialog as d
    w = d.IoCheckWindow(config_path=CTX["cfg"], demo=True)
    CTX["io"] = w
    w.resize(1600, 880)
    w.show()
    FILES.append(io_list(CTX["folder"]))
    w.import_list()
    w.project.scans = [io.ScanRange("E10.0", 56)]
    w._rebuild()
    w.chk_auto.setChecked(True)
    w.start_reading()
    wait(4000)
    sigs = w.all_signals
    w.set_status(sigs[0:6], "ok")
    w.set_status(sigs[6:7], "fehler")
    w.set_status(sigs[24:27], "ok")
    wait(800)
    save("iocheck_fenster", w)
    ai = next((i for i, s in enumerate(sigs) if s.kind == "AI"), None)
    if ai is not None:
        w.view.selectRow(w.proxy.mapFromSource(w.model.index(ai, 0)).row())   # Tabelle ist sortierbar
        wait(1500)
        save("iocheck_analog", w.analog)
    w.tabs.setCurrentIndex(1)
    wait(800)
    save("iocheck_matrix", w.tabs, (0, 0, min(700, w.tabs.width()), min(420, w.tabs.height())))
    job("iocheck_scan", over=lambda: w.tabs)
    w.edit_scans()
    w.tabs.setCurrentIndex(0)
    pdf = os.path.join(CTX["folder"], "protokoll.pdf")
    from plc_common import logo_paths, load_config
    io.write_protocol(pdf, w.all_signals, "Kesselhaus Linie 1", w.project.path, w.plcs,
                      logo_paths(load_config(CTX["cfg"])[0]))
    render_pdf(pdf, "iocheck_protokoll")


# ---------------------------------------------------------------------------------------------------------------------
# Dialoge des Loggers aus der Konfiguration (Benachrichtigungen, OPC UA) und Startbild
# ---------------------------------------------------------------------------------------------------------------------
@shot("benachrichtigungen")
def s_service_dialogs():
    """Dialoge Benachrichtigungen und OPC-UA-Server (mit Beispielwerten)."""
    from plc_notify_dialog import NotifyDialog
    from plc_opcua_dialog import OpcUaServerDialog
    dlg = NotifyDialog(None, {"aktiv": True, "prio_min": "Warnung", "trigger": "", "gehen": True, "sperre_s": 300,
                              "email": {"aktiv": True, "server": "smtp.firma.de", "port": 587, "modus": "starttls",
                                        "benutzer": "datenlogger@firma.de", "passwort": "geheim",
                                        "von": "datenlogger@firma.de",
                                        "an": "schichtleiter@firma.de, instandhaltung@firma.de"},
                              "ntfy": {"aktiv": True, "url": "https://ntfy.sh/kesselhaus-4711-xyz"}},
                       "Kesselhaus Linie 1")
    dlg.resize(560, 600)
    dlg.show()
    wait(400)
    save("benachrichtigungen", dlg)
    dlg.close()
    dlg = OpcUaServerDialog(None, {"aktiv": True, "host": "0.0.0.0", "port": 4840, "intervall_ms": 500,
                                   "sicherheit": ["none", "Basic256Sha256,SignAndEncrypt"], "anonym": False,
                                   "benutzer": "web"}, 2)
    dlg.lbl_url.setText("opc.tcp://ipc-kesselhaus:4840/plc-datenlogger/")
    dlg.resize(520, 560)
    dlg.show()
    wait(400)
    save("opcua_server", dlg)
    dlg.close()


@shot("startbild")
def s_start():
    """Startbild mit zuletzt benutzten Konfigurationen."""
    import plc_common
    from plc_splash import StartWindow
    for name in ("halle2.json", "pruefstand_3.json"):
        p = os.path.join(CTX["folder"], name)
        shutil.copy(CTX["cfg"], p)
        plc_common.remember_config_path(p)
    plc_common.remember_config_path(CTX["cfg"])
    sw = StartWindow("logger", CTX["cfg"])
    sw.show()
    wait(600)
    save("startbild", sw)
    sw.close()


# ---------------------------------------------------------------------------------------------------------------------
# Webseiten (Playwright)
# ---------------------------------------------------------------------------------------------------------------------
@shot("web_tablet")
def s_web():
    """Webseiten des Loggers: Anmeldung (Smartphone), Diagramme (Tablet), Prozessbild, IO-Check mobil."""
    from playwright.sync_api import sync_playwright
    w = CTX["w"]
    w.act_online.setChecked(True)
    w.act_run.setChecked(True)                          # Live-Werte für die Webseiten
    wait(6000)
    base = "https://127.0.0.1:8080/"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        phone = browser.new_context(viewport={"width": 390, "height": 760}, device_scale_factor=2,
                                    ignore_https_errors=True, color_scheme="light", locale="de-DE")
        page = phone.new_page()
        page.goto(base + "login")
        page.wait_for_timeout(800)
        page.screenshot(path=os.path.join(CTX["out"], "web_anmeldung.png"))
        print("Bild: web_anmeldung.png", flush=True)
        page.fill("#b", WEB_USER)
        page.fill("#p", WEB_PW)
        page.click("button[type=submit]")
        page.wait_for_timeout(1500)
        page.goto(base + "io")
        page.wait_for_timeout(2500)
        page.click("#r7")
        page.wait_for_timeout(1200)
        page.screenshot(path=os.path.join(CTX["out"], "iocheck_mobil.png"))
        print("Bild: iocheck_mobil.png", flush=True)
        page.click("#sheet .x")
        page.click("nav button[data-t=matrix]")
        page.wait_for_timeout(1200)
        page.screenshot(path=os.path.join(CTX["out"], "iocheck_mobil_matrix.png"))
        print("Bild: iocheck_mobil_matrix.png", flush=True)
        tablet = browser.new_context(viewport={"width": 1280, "height": 768}, device_scale_factor=1.25,
                                     ignore_https_errors=True, color_scheme="dark", locale="de-DE")
        page = tablet.new_page()
        page.goto(base + "login")
        page.fill("#b", WEB_USER)
        page.fill("#p", WEB_PW)
        page.click("button[type=submit]")
        page.wait_for_timeout(4000)
        page.screenshot(path=os.path.join(CTX["out"], "web_tablet.png"))
        print("Bild: web_tablet.png", flush=True)
        page.set_viewport_size({"width": 1280, "height": 720})
        page.goto(base + "prozess")
        page.wait_for_timeout(3500)
        shot_path = os.path.join(CTX["out"], "prozessbild.png")
        page.screenshot(path=shot_path)
        print("Bild: prozessbild.png", flush=True)
        page.click("#edit")
        page.wait_for_timeout(600)
        page.click(".tile >> nth=1")
        page.wait_for_timeout(800)
        page.screenshot(path=os.path.join(CTX["out"], "prozessbild_bearbeiten.png"))
        print("Bild: prozessbild_bearbeiten.png", flush=True)
        browser.close()
    w.act_run.setChecked(False)


# ---------------------------------------------------------------------------------------------------------------------
# Ablauf
# ---------------------------------------------------------------------------------------------------------------------
_LOGGER = {"logger_online"}
NEEDS = {n: _LOGGER for n in ("screenshot_menue", "anordnung_raster", "logger_offline", "ereignis_viewer",
                               "ereignis_diagramm", "export_dialog", "xy_diagramm", "pid_optimierung", "pdf_bericht",
                               "datenbank")}
NEEDS["web_tablet"] = {"logger_online", "iocheck_fenster"}


def patch_dialogs():
    """Modale Dialoge ersetzen: exec über JOBS, Meldungen ohne Anzeige, Dateidialoge aus FILES, kein Browser."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMainWindow, QMessageBox, QWidget
    QDialog.exec = fake_exec
    # Fenster nicht auf den (kleinen) Bildschirm des Build-Rechners legen: sonst begrenzt Windows ihre Größe. Mit
    # WA_DontShowOnScreen gelten sie als sichtbar (Layout, Zeichnen, grab), erscheinen aber nicht auf dem Schirm.
    for cls in (QWidget, QDialog, QMainWindow):
        orig = cls.show

        def show(self, _orig=orig):
            if self.isWindow() and not isinstance(self, QMessageBox) and type(self).__name__ != "QMenu":
                self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            _orig(self)
        cls.show = show
    for kind in ("information", "warning", "critical"):
        setattr(QMessageBox, kind, staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    nxt = staticmethod(lambda *a, **k: (FILES.pop(0) if FILES else "", ""))
    QFileDialog.getSaveFileName = nxt
    QFileDialog.getOpenFileName = nxt
    QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([FILES.pop(0)] if FILES else [], ""))
    QInputDialog.getItem = staticmethod(lambda _p, _t, _l, items, current=0, *a, **k: (list(items)[current], True))
    QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))
    QDesktopServices.openUrl = staticmethod(lambda url: True)


def main():
    """Befehlszeile auswerten, Demo vorbereiten und alle (bzw. die mit --only gewählten) Bilder erzeugen."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="de")
    ap.add_argument("--out", default="")
    ap.add_argument("--only", default="", help="nur diese Bildfunktionen (Namen wie in @shot, durch Komma getrennt)")
    args = ap.parse_args()
    out = args.out or os.path.join(ROOT, "doc", "images", *([] if args.lang == "de" else ["en"]))
    os.makedirs(out, exist_ok=True)
    folder = tempfile.mkdtemp(prefix="plc_bilder_")
    if sys.platform == "win32":                          # kurzer, sprechender Pfad für die Bilder (Startbild …)
        try:
            nice = os.path.join(os.environ.get("SystemDrive", "C:") + os.sep, "Anlagen", "Kesselhaus")
            shutil.rmtree(nice, ignore_errors=True)
            os.makedirs(nice)
            folder = nice
        except OSError:
            pass
    import plc_common
    plc_common.SETTINGS_FILE = os.path.join(folder, "einstellungen.json")     # Einstellungen nicht im Projekt
    import plc_i18n
    plc_i18n.load(args.lang)
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(["PLC Datenlogger"])
    plc_i18n.install_qt(app)
    patch_dialogs()
    scr = app.primaryScreen().availableGeometry()
    print(f"Bildschirm: {scr.width()} x {scr.height()}, Stil: {app.style().name()}", flush=True)
    import warnings
    warnings.filterwarnings("ignore", category=FutureWarning)
    CTX.update(out=out, folder=folder, lang=args.lang, cfg=demo_config(folder))
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    for name in list(only):                       # Voraussetzungen: Logger-Aufzeichnung bzw. IO-Check
        only |= NEEDS.get(name, set())
    failed = []
    import socket
    real_hostname = socket.gethostname
    for name, fn in SHOTS:
        if only and name not in only:
            continue
        # neutraler Rechnername in angezeigten Adressen – nicht während der Logger mit OPC-UA-Server läuft
        socket.gethostname = (lambda: "ipc-kesselhaus") if name in ("benachrichtigungen", "config_gesamt") \
            else real_hostname
        JOBS.clear()
        try:
            fn()
        except Exception:
            failed.append(name)
            print(f"FEHLER bei {name}:\n{traceback.format_exc()}", flush=True)
        socket.gethostname = real_hostname
        wait(200)
    for key in ("io", "w", "cw"):
        win = CTX.get(key)
        if win is not None:
            try:
                if key == "io":
                    win.stop_reading()
                    win.dirty = False
                win.close()
            except Exception:
                pass
    wait(300)
    print("Fertig." if not failed else f"Fertig, Fehler bei: {', '.join(failed)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
