# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Tests ohne Oberfläche: IO-Check, Berichte, Analyse, CSV, Webserver, Sprachdateien, Anleitung, Version."""
import os
import re
import subprocess
import sys

import numpy as np
import pytest

from conftest import ROOT


# ---- IO-Check ---------------------------------------------------------------------------------------------------
def test_iocheck_import_and_kinds():
    import plc_iocheck as io
    hdr = ["Name", "Data Type", "Logical Address", "Comment", "Messbereich", "Schrank"]
    rows = [["B1", "Bool", "%I0.0", "Endlage", "", "+S1"], ["Y1", "Bool", "%Q4.0", "Ventil", "", "+S2"],
            ["PT1", "Int", "%IW256", "Druck", "0 … 10 bar", "+S2"], ["", "", "", "Überschrift", "", ""],
            ["dup", "Bool", "I0.0", "", "", ""]]
    sigs, warnings = io.import_rows(hdr, rows)
    assert [(s.address, s.kind, s.dtype) for s in sigs] == [("I0.0", "DI", "BOOL"), ("Q4.0", "DO", "BOOL"),
                                                           ("IW256", "AI", "INT")]
    assert sigs[2].eng_max == 10 and sigs[2].unit == "bar"
    assert len(warnings) == 1                                        # E0.0 = I0.0 doppelt
    assert io.driver_address("PIW256", "s7") == "EW256"
    assert io.driver_address("Q4.0", "ads") == "%QX4.0"


def test_iocheck_column_aliases():
    """Eigene Spaltenüberschriften ersetzen die Vorgabe; ein leeres Feld wird nicht eingelesen."""
    import plc_iocheck as io
    hdr = ["E/A", "Klartext", "Kommentar", "Ort"]
    rows = [["E0.0", "Endlage", "wird ignoriert", "+S1"]]
    with pytest.raises(ValueError):
        io.import_rows(hdr, rows, aliases={})                            # „E/A“ ist kein bekannter Name
    aliases = {"address": ["E/A"], "comment": ["Klartext"], "group": []}
    sigs, _w = io.import_rows(hdr, rows, aliases=aliases)
    assert sigs[0].address == "E0.0" and sigs[0].comment == "Endlage" and sigs[0].group == ""
    assert io.disabled_fields(aliases) == {"group"}
    assert io.map_columns(["Logische Adresse"], {}) == {"address": 0}  # Vorgabe ohne eigene Namen


def test_s7_source_array_as_block(tmp_path):
    """S7-DB-Quelle: eindimensionales Array als Block – Startadresse des gewählten Elements, Anzahl begrenzt."""
    from plc_treiber.s7_symbols import SymbolSet, block_spec
    src = tmp_path / "m.db"
    src.write_text('DATA_BLOCK "Messwerte"\nVERSION : 0.1\n   VAR\n      Zaehler : Int;\n'
                   '      Werte : Array[1..20] of Real;\n      Bits : Array[0..15] of Bool;\n   END_VAR\n'
                   'BEGIN\nEND_DATA_BLOCK\n', encoding="utf-8")
    ss = SymbolSet()
    ss.load(str(src) + "#10")
    roots, errors = ss.build()
    assert not errors
    werte, bits = roots[0].children[1], roots[0].children[2]
    assert werte.block_ok and not roots[0].children[0].block_ok
    assert block_spec(werte, 3, 5) == ("Messwerte.Werte", "DB10.DBD10", 0, 5, "REAL")
    assert block_spec(bits, 10, 99) == ("Messwerte.Bits", "DB10.DBX83.2", 0, 6, "BOOL")


def test_cleanup_csv_and_sqlite(tmp_path):
    """Aufräumen: CSV/Archiv nach Alter und Gesamtgröße (aktuelle Datei bleibt), SQLite nach Alter und Größe."""
    import datetime as dt
    import time as _t
    import plc_cleanup as cl
    import plc_db
    csv_dir, arch = tmp_path / "logs", tmp_path / "archiv"
    (arch / "log" / "2026" / "01" / "02").mkdir(parents=True)
    csv_dir.mkdir()
    now = _t.time()
    files = {csv_dir / "log_alt.csv": 40, csv_dir / "log_neu.csv": 1, csv_dir / "log_aktuell.csv": 0,
             csv_dir / "anderer_1.csv": 99, arch / "log" / "2026" / "01" / "02" / "log_a.zip": 30}
    for f, age_days in files.items():
        f.write_bytes(b"x" * 600_000)
        os.utime(f, (now - age_days * 86400, now - age_days * 86400))
    n, freed, err = cl.clean_csv(str(csv_dir), str(arch), "log", days=10, keep=[str(csv_dir / "log_aktuell.csv")])
    assert n == 2 and not err and not (arch / "log" / "2026").exists()          # alte Datei + ZIP, leere Ordner weg
    assert (csv_dir / "anderer_1.csv").exists() and (csv_dir / "log_aktuell.csv").exists()
    n, _f, _e = cl.clean_csv(str(csv_dir), str(arch), "log", max_mb=1, keep=[str(csv_dir / "log_aktuell.csv")])
    assert n == 1 and not (csv_dir / "log_neu.csv").exists()                   # 2 × 0,6 MB > 1 MB
    s = plc_db.db_settings({"db_typ": "sqlite", "db_datei": str(tmp_path / "w.db")})
    b = plc_db.SqliteBackend(s)
    b.connect()
    utc = dt.timezone.utc
    old = dt.datetime.now(utc) - dt.timedelta(days=40)
    b.insert([(old + dt.timedelta(seconds=k), "", "A", 1.0) for k in range(100)]
             + [(dt.datetime.now(utc), "", "A", 2.0)])
    assert "100" in b.cleanup(days=30)
    assert b.con.execute("SELECT COUNT(*) FROM messwerte").fetchone()[0] == 1
    b.insert([(old + dt.timedelta(days=d, seconds=k), "", "B" * 50, float(k)) for d in range(5) for k in range(3000)])
    b.cleanup(max_mb=1)
    assert b.used_bytes() <= 1024 * 1024
    assert b.con.execute("SELECT COUNT(*) FROM messwerte").fetchone()[0] > 0     # nur die ältesten Tage gelöscht
    b.close()
    assert cl.settings({"aufr_csv_tage": "7", "aufr_db_mb": None}) == {"csv_tage": 7, "csv_mb": 0, "db_tage": 0,
                                                                       "db_mb": 0}


def test_iocheck_tracker_digital_and_swap():
    """Digitalsignal: Wechsel 0-1-0 ergibt automatisch „ok“; reagiert ein anderes als das erwartete Signal
    (vertauschte Verdrahtung), wird das erwartete Signal beim Wechsel vermerkt."""
    import plc_iocheck as io
    t = io.IoTracker()
    t.auto_ok = True
    a, b = io.IoSignal("E0.0"), io.IoSignal("E0.1")
    for v, ts in ((0, 1), (1, 2), (0, 3)):
        t.feed(a, v, ts)
    assert a.status == "ok"
    t.feed(b, 0, 1)
    t.expected = b
    ch = t.feed(a, 1, 10)
    assert ch.expected is b and "B" not in ch.note[:0]


def test_iocheck_wire_break():
    """Analogsignal: Wert am Anschlag gilt als Drahtbruch, die Rückkehr in den Messbereich als „ok“."""
    import plc_iocheck as io
    t = io.IoTracker()
    t.auto_ok = True
    s = io.IoSignal("EW256", kind="AI", dtype="INT")
    t.feed(s, 13824, 1)
    t.feed(s, 32767, 2)
    assert s.seen & io.SEEN_BREAK
    t.feed(s, 13800, 3)
    assert s.seen & io.SEEN_BACK and s.status == "ok"
    assert not io.analog_broken(s, -100) and io.analog_broken(s, -6912)


def test_iocheck_project_roundtrip_and_protocol(tmp_path):
    """Prüfprojekt speichern und wieder laden (Status, Bemerkung, Prüfer bleiben erhalten); Excel-Ergebnis und
    PDF-Protokoll entstehen.
    """
    import plc_iocheck as io
    sigs = [io.IoSignal(f"E0.{k}", symbol=f"B{k}", group="+S1") for k in range(8)]
    io.set_status(sigs[0], "ok", checker="tablet1")
    io.set_status(sigs[1], "fehler", remark="Kabel", checker="tablet1")
    p = io.IoProject(signals=sigs, scans=[io.ScanRange("E1.0", 16)])
    p.save(str(tmp_path / "x.iocheck.json"))
    q = io.IoProject.load(str(tmp_path / "x.iocheck.json"))
    assert [s.status for s in q.signals[:2]] == ["ok", "fehler"] and q.scans[0].count == 16
    pdf = io.write_protocol(str(tmp_path / "p.pdf"), q.signals, "Anlage")
    assert open(pdf, "rb").read(5) == b"%PDF-"
    io.write_result(str(tmp_path / "r.csv"), q.signals)
    assert "Kabel" in open(tmp_path / "r.csv", encoding="utf-8-sig").read()
    rows = io.matrix_rows(q.signals)
    assert rows[0][1] == "E0" and rows[0][2][1] is q.signals[1]


def test_iocheck_scan_addresses():
    """Adressbereich: 10 Bits ab E0.0 enden bei E1.1."""
    import plc_iocheck as io
    assert io.ScanRange("E0.0", 10).addresses("s7")[-1] == "E1.1"


# ---- Berichte, Analyse, CSV ---------------------------------------------------------------------------------------
def test_report_pdf(tmp_path):
    import plc_report
    from plc_recorder import demo_config
    charts, variables = demo_config()
    vs = [v for v in variables if not v.formula]
    t = np.arange(0.0, 3600.0, 5.0) + 1.79e9
    y = np.array([np.sin(t / (100 + k)) * 10 + k for k in range(len(vs))])
    acc = plc_report.ReportAccumulator([v.name for v in vs], [v.dtype for v in vs], t[0], t[-1], kind="tag")
    acc.add_many(t, y)
    xs, ys = acc.series(0)                         # 5-s-Abtastung, Abschnitte 2,4 s: keine Unterbrechungen
    assert len(xs) > 500 and not np.isnan(ys).any()
    path = plc_report.write_report(str(tmp_path / "b.pdf"), acc, charts, vs, project="Test")
    assert os.path.getsize(path) > 2000
    # Logos im Seitenkopf: PNG mit Transparenz (logo.png) und JPEG; nicht lesbare Dateien entfallen still
    import zlib
    jpg = bytes.fromhex("ffd8ffc0000b080002000301011100ffd9")                  # nur Kopf: 3 x 2 Pixel, grau
    (tmp_path / "k.jpg").write_bytes(jpg)
    img = plc_report.load_image(str(tmp_path / "k.jpg"))
    assert (img.w, img.h) == (3, 2) and b"/DCTDecode" in img.obj
    png = plc_report.load_image(os.path.join(ROOT, "logo.png"))
    assert png is not None and png.w > png.h
    raw = b"".join(b"\x00" + bytes([200, 10, 10, 128] * 4) for _ in range(2))  # 4 x 2 RGBA, halb durchsichtig
    chunk = lambda t, d: len(d).to_bytes(4, "big") + t + d + zlib.crc32(t + d).to_bytes(4, "big")  # noqa: E731
    (tmp_path / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", bytes.fromhex("0000000400000002080600000"
                                     "0")) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    a = plc_report.load_image(str(tmp_path / "a.png"))
    assert zlib.decompress(a.obj.split(b"stream\n", 1)[1].rsplit(b"\nendstream", 1)[0])[:3] == bytes([227, 132, 132])
    path = plc_report.write_report(str(tmp_path / "c.pdf"), acc, charts, vs, project="Test",
                                   logos=[str(tmp_path / "a.png"), os.path.join(ROOT, "logo.png"), "fehlt.png"])
    data = open(path, "rb").read()
    assert data.count(b"/Subtype /Image") == 2 and b"/XObject << /Im0" in data


def test_analysis_spectrum():
    """Frequenzanalyse: ein Sinus mit 0,5 Hz ergibt die Spitze bei 0,5 Hz."""
    import plc_analysis as an
    t = np.arange(0, 100, 0.1)
    y = 3 * np.sin(2 * np.pi * 0.5 * t)
    res = an.spectrum(t, y, window="flattop" if "flattop" in an.WINDOWS else "hann")
    peaks = an.find_peaks(res["f"], res["amp"])
    assert abs(peaks[0][0] - 0.5) < 0.02


def test_csv_join(tmp_path):
    """Zwei CSV-Dateien zusammenfügen: nach Zeit sortiert, mit Lücke (NaN) dazwischen."""
    import plc_csvjoin
    for name, t0 in (("a.csv", 0), ("b.csv", 100)):
        with open(tmp_path / name, "w", encoding="utf-8") as f:
            f.write("Zeit;Epoch;A\n")
            for k in range(5):
                f.write(f"x;{1.79e9 + t0 + k:.3f};{k}\n")
    names, t, y, errors = plc_csvjoin.read_and_join([str(tmp_path / "b.csv"), str(tmp_path / "a.csv")])
    assert names == ["A"] and not errors
    assert np.all(np.diff(t[np.isfinite(t)]) > 0)              # nach Zeit sortiert
    assert np.isnan(np.asarray(y)).any()                       # Lücke zwischen den Dateien


# ---- Webserver ----------------------------------------------------------------------------------------------------
def test_web_login_and_iocheck_api():
    import plc_iocheck as io
    import plc_web
    from plc_webauth import hash_password
    app = plc_web.create_app(lambda: None, users={"tablet1": hash_password("geheim123")},
                             logos=[os.path.join(ROOT, "logo.png")])
    c = app.test_client()
    assert c.get("/api/io").status_code == 401
    assert 'src="logo/0"' in c.get("/login").get_data(as_text=True)            # Logo auf der Anmeldeseite …
    assert c.get("/logo/0").data[:4] == b"\x89PNG" and c.get("/logo/1").status_code == 404   # … frei abrufbar
    assert c.post("/login", data={"benutzer": "tablet1", "passwort": "geheim123"}).status_code == 302
    br = io.IoWebBridge()
    sigs = [io.IoSignal("E0.0"), io.IoSignal("E0.1")]
    br.publish(sigs, io.IoTracker(), "Test", io.matrix_rows(sigs))
    plc_web.set_io_bridge(br)
    try:
        j = c.get("/api/io?ver=-1").get_json()
        assert j["active"] and j["user"] == "tablet1" and len(j["static"]["sig"]) == 2
        r = c.post("/api/io/cmd", json={"ver": j["ver"], "cmd": "status", "i": 1, "status": "ok"})
        assert r.status_code == 200
        cmd = br.commands.get_nowait()
        assert cmd[0] == "status" and cmd[1] is sigs[1] and cmd[3] == "tablet1"
        assert c.post("/api/io/cmd", data="x").status_code == 415
        assert c.get("/api/io/protokoll.pdf").data[:5] == b"%PDF-"
        assert "IO-Check" in c.get("/io").get_data(as_text=True)
    finally:
        plc_web.set_io_bridge(None)


# ---- Sprachdateien, Anleitung, Version --------------------------------------------------------------------------
def _entries(path):
    text = open(path, encoding="utf-8").read()
    return re.findall(r"^@ (.*)\n> ?(.*)$", text, re.M)


def test_english_translation_complete_and_placeholders():
    """Jeder Text in sprachen/en.txt ist übersetzt, und die Übersetzung hat dieselben Platzhalter ({0}, {1:.1f} …) wie
    das Original.
    """
    entries = _entries(os.path.join(ROOT, "sprachen", "en.txt"))
    missing = [k for k, v in entries if not v.strip()]
    assert not missing, f"{len(missing)} Texte ohne Übersetzung, z. B. {missing[:3]}"
    import string

    def fields(text):                                   # Namen der Platzhalter ({0}, {1:%H:%M} -> 0, 1); {{ }} zählt nicht
        """Namen der Platzhalter eines Textes (sortiert; "?" bei ungültiger Formatangabe)."""
        try:
            return sorted({f for _l, f, _s, _c in string.Formatter().parse(text.replace("\\n", "\n")) if f is not None})
        except ValueError:
            return ["?"]
    bad = [k for k, v in entries if fields(k) != fields(v)]
    assert not bad, f"Platzhalter passen nicht: {bad[:3]}"


def test_all_tr_texts_in_language_file():
    """Alle tr()-Texte des Programms stehen in de.txt (sonst: python tools/extract_tr.py plc .)."""
    import ast
    import glob
    keys = {k for k, _v in _entries(os.path.join(ROOT, "sprachen", "de.txt"))}
    unknown = []
    for path in glob.glob(os.path.join(ROOT, "src", "plc_*.py")) + glob.glob(os.path.join(ROOT, "src", "plc_treiber", "*.py")):
        tree = ast.parse(open(path, encoding="utf-8").read())
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("tr", "N_") and n.args \
                    and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                text = n.args[0].value.replace("\\", "\\\\").replace("\n", "\\n")
                if text not in keys:
                    unknown.append((os.path.basename(path), n.args[0].value[:50]))
    assert not unknown, f"{len(unknown)} Texte fehlen in sprachen/de.txt: {unknown[:5]}"


def _headings(path):
    """Überschriften-Ebenen der RST-Datei in Reihenfolge (Zeichen der Unterstreichung, z. B. "=" oder "-")."""
    lines = open(path, encoding="utf-8").read().split("\n")
    return [lines[i][0] for i in range(1, len(lines)) if re.fullmatch(r"[=\-]{5,}", lines[i])
            and lines[i - 1].strip() and not re.fullmatch(r"[=\-]{5,}", lines[i - 1])]


def test_manuals_same_structure_and_images():
    """Deutsche und englische Anleitung sind gleich gegliedert (Kontexthilfe F1), und alle eingebundenen Bilder
    existieren.
    """
    de = os.path.join(ROOT, "doc", "bedienungsanleitung.rst")
    en = os.path.join(ROOT, "doc", "user_manual.rst")
    assert _headings(de) == _headings(en), "Deutsche und englische Anleitung müssen gleich gegliedert sein (F1)"
    for path in (de, en):
        for img in re.findall(r"^\.\. (?:figure|image):: (\S+)", open(path, encoding="utf-8").read(), re.M):
            assert os.path.exists(os.path.join(ROOT, "doc", img)), f"Bild fehlt: {img}"
    assert "images/en/" in open(en, encoding="utf-8").read()


def test_manual_html_builds_without_messages(tmp_path):
    """Beide Anleitungen lassen sich mit docutils ohne Warnungen nach HTML umwandeln."""
    docutils = pytest.importorskip("docutils.core")
    for name in ("bedienungsanleitung", "user_manual"):
        out = tmp_path / f"{name}.html"
        docutils.publish_file(source_path=os.path.join(ROOT, "doc", f"{name}.rst"), destination_path=str(out),
                              writer_name="html5", settings_overrides={"input_encoding": "utf-8",
                                                                      "output_encoding": "utf-8",
                                                                      "syntax_highlight": "none",
                                                                      "report_level": 2, "halt_level": 5,
                                                                      "warning_stream": open(os.devnull, "w")})
        html = out.read_text(encoding="utf-8")
        assert 'class="system-message"' not in html, f"Fehlermeldung in {name}.html"


def test_program_command_iocheck():
    """Befehlszeilen für Logger, Konfiguration und IO-Check (Start aus dem Quelltext)."""
    from plc_common import program_command
    assert program_command("iocheck", "a.json")[1:] == [os.path.join(ROOT, "src", "plc_logger.py"), "--iocheck",
                                                         "a.json"]
    assert program_command("config")[1].endswith("plc_config.py")
    assert program_command("logger", "a.json")[2:] == ["a.json"]
    import plc_iocheck_start                                             # Startprogramm PLCIOCheck.exe
    assert callable(plc_iocheck_start.main)


def test_version_consistent():
    """CHANGELOG.md hat einen Abschnitt für die aktuelle APP_VERSION."""
    out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "bump_version.py")], capture_output=True,
                         text=True, check=True).stdout.strip()
    changelog = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    assert f"## [{out}]" in changelog, f"CHANGELOG.md hat keinen Abschnitt [{out}]"


def test_qr_code():
    """QR-Code: quadratisch, Größe 17 + 4·Version, Suchmuster oben links; mit OpenCV (falls installiert) lesbar."""
    import plc_qr
    url = "https://192.168.0.20:8080/io?token=abcdef123456"
    m = plc_qr.encode(url)
    n = len(m)
    assert (n - 17) % 4 == 0 and all(len(r) == n for r in m)
    assert all(m[0][x] for x in range(7)) and not m[1][1] and m[2][2]          # Suchmuster oben links
    cv2 = pytest.importorskip("cv2")
    img = np.full(((n + 8) * 6, (n + 8) * 6), 255, np.uint8)
    for y, row in enumerate(m):
        for x, v in enumerate(row):
            if v:
                img[(y + 4) * 6:(y + 5) * 6, (x + 4) * 6:(x + 5) * 6] = 0
    assert cv2.QRCodeDetector().detectAndDecode(img)[0] == url


# ---- Benachrichtigungen -----------------------------------------------------------------------------------------
def _local_servers():
    """HTTP-Server (sammelt POSTs) und minimaler SMTP-Server auf zufälligen Ports -> (http_port, smtp_port, Liste)."""
    import socketserver
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    got = []

    class H(BaseHTTPRequestHandler):
        """HTTP-Empfänger: merkt sich jeden POST (Teams, ntfy, Webhook) in ``got``."""
        def do_POST(self):
            """Anfrage samt Kopfzeilen und Inhalt merken und mit 200 beantworten."""
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            got.append(("http", self.path, dict(self.headers), body))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            """Keine Ausgabe auf der Konsole."""
            pass

    class S(socketserver.StreamRequestHandler):
        """Minimaler SMTP-Server: beantwortet die Befehle eines Mail-Clients und merkt sich die Nachricht."""
        def handle(self):
            """Ein SMTP-Gespräch: Befehle zeilenweise beantworten, zwischen DATA und „.“ die Nachricht sammeln."""
            w = lambda t: self.wfile.write((t + "\r\n").encode())       # noqa: E731
            w("220 test")
            data = False
            lines = []
            for raw in self.rfile:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if data:
                    if line == ".":
                        data = False
                        got.append(("smtp", "\n".join(lines)))
                        w("250 ok")
                    else:
                        lines.append(line)
                    continue
                cmd = line[:4].upper()
                if cmd in ("EHLO", "HELO"):
                    w("250 test")
                elif cmd == "DATA":
                    data = True
                    w("354 go")
                elif cmd == "QUIT":
                    w("221 bye")
                    return
                else:
                    w("250 ok")
    http = HTTPServer(("127.0.0.1", 0), H)
    smtp = socketserver.ThreadingTCPServer(("127.0.0.1", 0), S)
    for srv in (http, smtp):
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    return http, smtp, got


def test_notify_channels_and_engine(tmp_path):
    """Benachrichtigungen: Teams, ntfy und E-Mail kommen bei den lokalen Testservern an; mit Triggern gelten Sperrzeit
    und „Gehen nur nach gemeldetem Kommen“.
    """
    import plc_notify as nf
    from plc_events import EventLog, Trigger, TriggerEngine
    http, smtp, got = _local_servers()
    try:
        hp, sp = http.server_address[1], smtp.server_address[1]
        s = nf.settings({"aktiv": True, "gehen": True, "sperre_s": 60,
                         "email": {"aktiv": True, "server": "127.0.0.1", "port": sp, "modus": "keine",
                                   "an": "a@test.de"},
                         "webhook": {"aktiv": True, "art": "teams", "url": f"http://127.0.0.1:{hp}/teams"},
                         "ntfy": {"aktiv": True, "url": f"http://127.0.0.1:{hp}/thema"}})
        res = nf.send_all(s, nf.test_message("Anlage"))
        assert all(not err for _c, err in res), res
        kinds = sorted(g[0] + (g[1] if g[0] == "http" else "") for g in got)
        assert kinds == ["http/teams", "http/thema", "smtp"]
        teams = next(g for g in got if g[0] == "http" and g[1] == "/teams")
        assert b"AdaptiveCard" in teams[3]
        # Trigger -> Notifier mit Sperrzeit; Gehen nur nach gemeldetem Kommen
        sent = []
        nt = nf.Notifier({"benachrichtigung": s}, "Anlage", sender=lambda _s, m: sent.append((m.kind, m.ts)) or [])
        eng = TriggerEngine([Trigger("A", "{T} > 80", "", "Alarm"), Trigger("I", "{T} > 0", "", "Info")],
                            EventLog(str(tmp_path / "ev.csv")), notify=nt.event)
        for ts, v in ((1, 70), (2, 85), (3, 70), (4, 90), (5, 70), (100, 95)):
            eng.evaluate(ts, {"T": v})
        nt.stop()
        assert sent == [("KOMMT", 2), ("GEHT", 3), ("KOMMT", 100)]
    finally:
        http.shutdown()
        smtp.shutdown()


# ---- OPC-UA-Server ----------------------------------------------------------------------------------------------
def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_opcua_server_with_recorder(tmp_path):
    """OPC-UA-Server mit Demo-Aufzeichnung: Anmeldung erforderlich, Werte (auch berechnete) mit passenden Typen,
    Ordnerstruktur, Status; beim Stopp wird der Server beendet.
    """
    pytest.importorskip("asyncua")
    import time

    from asyncua.sync import Client

    import plc_opcua_server as us
    from plc_common import Plc, default_connection
    from plc_recorder import Recorder, demo_config
    from plc_webauth import hash_password
    charts, variables = demo_config()
    port = _free_port()
    conn = default_connection()
    conn.update(csv_ordner=str(tmp_path), csv_aktiv=0, projekt="Testanlage",
                web_benutzer={"pruefer": hash_password("geheim", 1000)},
                opcua_server={"aktiv": True, "host": "127.0.0.1", "port": port, "intervall_ms": 100,
                              "anonym": False, "benutzer": "web"})
    rec = Recorder(conn, [Plc(name="SPS 1")], charts, variables, demo=True)
    rec.start()
    try:
        assert rec.opcua is not None, list(rec.messages)
        time.sleep(1.0)
        url = f"opc.tcp://127.0.0.1:{port}/plc-datenlogger/"
        bad = Client(url, timeout=5)                       # ohne Anmeldung: abgewiesen
        bad.set_user("pruefer")
        bad.set_password("falsch")
        with pytest.raises(Exception):
            bad.connect()
        try:
            bad.disconnect()
        except Exception:
            pass
        c = Client(url, timeout=5)
        c.set_user("pruefer")
        c.set_password("geheim")
        c.connect()
        try:
            ns = c.get_namespace_index(us.NS_URI)
            t = c.get_node(f"ns={ns};s=Temperatur").read_value()
            assert isinstance(t, float)
            assert isinstance(c.get_node(f"ns={ns};s=Pumpe").read_value(), bool)
            m = c.get_node(f"ns={ns};s=Mittel").read_value()           # berechnete Variable
            assert isinstance(m, float)
            folders = [n.read_browse_name().Name
                       for n in c.get_node(f"ns={ns};s=PLC Datenlogger").get_children()]
            assert folders[:2] == ["SPS 1", "Berechnet"] and "Status" in folders
            assert c.get_node(f"ns={ns};s=Status:0").read_value() is True
        finally:
            c.disconnect()
    finally:
        rec.stop()
    assert rec.opcua is None


# ---- Prozessbild im Browser -------------------------------------------------------------------------------------
def test_process_view_api(tmp_path):
    import types

    import plc_web
    import plc_web_prozess as wp
    from plc_recorder import demo_config
    from plc_webauth import hash_password
    _charts, variables = demo_config()
    cfg = str(tmp_path / "anlage.json")
    rec = types.SimpleNamespace(config_path=cfg, conn={"projekt": "X"}, vars=variables, charts=[],
                                last_row=lambda: (None, None), status_list=lambda: [], count=lambda: 0,
                                running=True)
    app = plc_web.create_app(lambda: rec, token="abc", users={"chef": hash_password("pw", 1000)})
    c = app.test_client()
    j = c.get("/api/prozess?token=abc").get_json()
    assert not j["saved"] and not j["edit"]                           # nur Zugriffscode: ansehen
    assert {t["var"] for t in j["layout"]["seiten"][0]["kacheln"]} >= {"Pumpe", "Mittel"}
    assert next(t for t in j["layout"]["seiten"][0]["kacheln"] if t["var"] == "Pumpe")["typ"] == "status"
    lay = {"seiten": [{"name": "A", "kacheln": [
        {"typ": "zeiger", "var": "Druck", "x": 11, "y": 0, "w": 5, "h": 2, "min": "0", "max": 10, "og_alarm": "x",
         "farbe": "red", "titel": "<b>" * 50, "boese": 1}]}]}
    assert c.post("/api/prozess?token=abc", json=lay).status_code == 403
    c.post("/login", data={"benutzer": "chef", "passwort": "pw"})
    assert c.post("/api/prozess", data="x").status_code == 415
    r = c.post("/api/prozess", json=lay).get_json()
    t = r["layout"]["seiten"][0]["kacheln"][0]
    assert t["w"] == 1 and t["min"] == 0.0 and "og_alarm" not in t and "farbe" not in t and "boese" not in t
    assert len(t["titel"]) == 80
    assert wp.load_layout(cfg) == r["layout"]
    assert c.get("/api/prozess").get_json()["saved"]
    assert c.post("/api/prozess", json={"seiten": "x"}).status_code == 400
    page = c.get("/prozess").get_data(as_text=True)
    assert "Prozessbild" in page and "Diagramme" in page
