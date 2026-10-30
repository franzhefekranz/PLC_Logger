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


def test_read_ods(tmp_path):
    """ODS-Tabelle (LibreOffice) ohne Zusatzbibliothek lesen: Zahlen, Text mit Leerzeichen, Wiederholungen."""
    import zipfile
    import plc_export
    import plc_iocheck as io
    t, o, x = ("urn:oasis:names:tc:opendocument:xmlns:table:1.0", "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
               "urn:oasis:names:tc:opendocument:xmlns:text:1.0")

    def cell(v, n=1):
        rep = f' table:number-columns-repeated="{n}"' if n > 1 else ""
        if not v:
            return f"<table:table-cell{rep}/>"
        typ = f'office:value-type="float" office:value="{v}"' if isinstance(v, float) else 'office:value-type="string"'
        return f"<table:table-cell {typ}{rep}><text:p>{v}</text:p></table:table-cell>"
    rows = [["Adresse", "Symbol", "Kommentar", "Messbereich"], ["E0.0", "B1", "Endlage<text:s text:c=\"2\"/>vorn", ""],
            ["EW256", "PT1", "Druck", "0 … 10 bar"], ["AW272", "SV1", 12.0, ""]]
    body = "".join("<table:table-row>" + "".join(cell(v) for v in r) + cell("", 1000) + "</table:table-row>"
                   for r in rows)
    body += '<table:table-row table:number-rows-repeated="1048570">' + cell("", 1024) + "</table:table-row>"
    xml = (f'<?xml version="1.0" encoding="UTF-8"?><office:document-content xmlns:office="{o}" xmlns:table="{t}" '
           f'xmlns:text="{x}"><office:body><office:spreadsheet><table:table table:name="IO">{body}</table:table>'
           "</office:spreadsheet></office:body></office:document-content>")
    path = tmp_path / "io.ods"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        z.writestr("content.xml", xml)
    header, data = plc_export.read_table(str(path))
    assert header == ["Adresse", "Symbol", "Kommentar", "Messbereich"] and len(data) == 3
    assert data[0][2] == "Endlage  vorn" and data[2][2] == 12.0
    sigs, _w = io.import_file(str(path), aliases={})
    assert [s.address for s in sigs] == ["E0.0", "EW256", "AW272"] and sigs[1].unit == "bar"


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
    import plc_i18n
    plc_i18n.load("en")                                                        # Webseiten in der Programmsprache
    try:
        page = c.get("/login").get_data(as_text=True)
        assert '<html lang="en">' in page and ">Log in</button>" in page and "{{" not in page
    finally:
        plc_i18n.load("de")
    assert ">Anmelden</button>" in c.get("/login").get_data(as_text=True)
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


def test_child_env_frozen(monkeypatch):
    """Programmdatei (PyInstaller/AppImage): zweites Programm startet mit bereinigter Umgebung."""
    import plc_common
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "/tmp/.mount_x/usr/lib/PLCDatenlogger")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/.mount_x/usr/lib/PLCDatenlogger/_internal")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/opt/lib")
    monkeypatch.setenv("QT_PLUGIN_PATH", "/tmp/.mount_x/plugins")
    env = plc_common.child_env()
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1" and "_PYI_APPLICATION_HOME_DIR" not in env
    assert env["LD_LIBRARY_PATH"] == "/opt/lib" and "LD_LIBRARY_PATH_ORIG" not in env and "QT_PLUGIN_PATH" not in env


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


def test_qt_platform_setup_wayland(monkeypatch):
    """Linux mit Wayland und XWayland: Qt über xcb; eigene Einstellung und PLC_WAYLAND=1 haben Vorrang."""
    import plc_common
    monkeypatch.setattr(plc_common.sys, "platform", "linux")
    for k in ("QT_QPA_PLATFORM", "PLC_WAYLAND", "XDG_SESSION_TYPE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("DISPLAY", ":0")
    plc_common.qt_platform_setup()
    assert os.environ["QT_QPA_PLATFORM"] == "xcb"
    monkeypatch.setenv("QT_QPA_PLATFORM", "wayland")
    plc_common.qt_platform_setup()
    assert os.environ["QT_QPA_PLATFORM"] == "wayland"
    monkeypatch.delenv("QT_QPA_PLATFORM")
    monkeypatch.setenv("PLC_WAYLAND", "1")
    plc_common.qt_platform_setup()
    assert "QT_QPA_PLATFORM" not in os.environ
    monkeypatch.delenv("PLC_WAYLAND")
    monkeypatch.delenv("DISPLAY")                       # kein XWayland: bei Wayland bleiben
    plc_common.qt_platform_setup()
    assert "QT_QPA_PLATFORM" not in os.environ


def test_manual_no_figures_in_tables():
    """Keine Abbildungen in Tabellenzellen: rinohtype (PDF) kann Tabellenzeilen nicht umbrechen und bricht ab, wenn eine
    Zeile mit Bild höher als eine Seite wird (AssertionError in flow_inner)."""
    for name in ("bedienungsanleitung", "user_manual"):
        lines = open(os.path.join(ROOT, "doc", f"{name}.rst"), encoding="utf-8").read().splitlines()
        in_table = False
        for no, line in enumerate(lines, 1):
            if line.startswith(".. list-table::"):
                in_table = True
            elif line and not line[0].isspace():
                in_table = False
            elif in_table and re.match(r"\s+\.\. (figure|image)::", line):
                raise AssertionError(f"{name}.rst Zeile {no}: Abbildung in einer Tabellenzelle")


def test_headless_status_and_stop_request(tmp_path, demo_config, monkeypatch):
    """Headless-Logger: Statusdatei beim Start, Beenden über eine Beenden-Datei (wie im Konfigurationsprogramm),
    danach abgemeldet; Statusdateien ohne Lebenszeichen werden aufgeräumt."""
    import threading
    import time
    import plc_headless as hl
    run_dir = str(tmp_path / "laufend")
    monkeypatch.setattr(hl, "RUN_DIR", run_dir)
    hl.write_status({"pid": 99999, "projekt": "alt", "start": 0}, run_dir)
    assert [i["pid"] for i in hl.running_loggers(run_dir)] == [99999]
    assert hl.running_loggers(run_dir, now=time.time() + hl.STALE_S + 1) == []      # abgestürzt: aufgeräumt
    assert not os.listdir(run_dir)
    result = {}
    th = threading.Thread(target=lambda: result.setdefault("rc", hl.run(demo_config, demo=True)), daemon=True)
    th.start()
    deadline = time.time() + 20
    while time.time() < deadline and not hl.running_loggers(run_dir):
        time.sleep(0.1)
    found = hl.running_loggers(run_dir)
    assert len(found) == 1 and found[0]["pid"] == os.getpid() and not found[0]["stop"]
    assert found[0]["config"] == os.path.abspath(demo_config)
    hl.request_stop(found[0]["pid"], run_dir)
    assert hl.running_loggers(run_dir)[0]["stop"]
    th.join(20)
    assert not th.is_alive() and result.get("rc") == 0
    assert hl.running_loggers(run_dir) == [] and not os.listdir(run_dir)


def test_program_icons_present():
    """Je Programm ein Icon (ICO mit 16 bis 256 Pixeln, PNG); Build-Skripte und Installer verwenden sie."""
    import struct
    for name in ("logger", "konfiguration", "iocheck", "ereignisse", "headless"):
        data = open(os.path.join(ROOT, "icons", name + ".ico"), "rb").read()
        count = struct.unpack("<HHH", data[:6])[2]
        sizes = {data[6 + 16 * i] or 256 for i in range(count)}
        assert {16, 24, 32, 48, 256} <= sizes, (name, sizes)
        assert open(os.path.join(ROOT, "icons", name + ".png"), "rb").read(8) == b"\x89PNG\r\n\x1a\n"
    bat = open(os.path.join(ROOT, "build.bat"), encoding="utf-8").read()
    assert "--icon icons\\konfiguration.ico" in bat and "--icon icons\\iocheck.ico" in bat
    iss = open(os.path.join(ROOT, "installer.iss"), encoding="utf-8").read()
    assert "icons\\ereignisse.ico" in iss and "icons\\headless.ico" in iss
    for script in ("build_appimage.sh", "build_macos.sh"):
        assert "icons:icons" in open(os.path.join(ROOT, script), encoding="utf-8").read(), script


def test_logo_default_is_manufacturer_logo():
    """Leeres Logo-Feld: Herstellerlogo logo.png; „-“: kein Logo; eingetragene Datei bleibt."""
    from plc_common import logo_file, logo_paths
    assert os.path.basename(logo_file({"logo": ""})) == "logo.png" and os.path.isfile(logo_file({}))
    assert logo_file({"logo": "-"}) == "" and logo_paths({"logo": "-"}) == []
    assert [os.path.basename(p) for p in logo_paths({"kundenlogo": "kunde.png"})] == ["kunde.png", "logo.png"]
    assert logo_file({"logo": "firma.svg"}) == "firma.svg"


def test_self_signed_cert_long_hostname(tmp_path, monkeypatch):
    """Selbstsigniertes Zertifikat auch bei Rechnernamen über 64 Zeichen (Common Name ist darauf begrenzt)."""
    pytest.importorskip("cryptography")
    import socket
    import plc_web
    long_name = "rechner-" + "x" * 70 + ".local"
    monkeypatch.setattr(socket, "gethostname", lambda: long_name)
    cert, key = plc_web.ensure_self_signed(str(tmp_path / "c.pem"), str(tmp_path / "k.pem"))
    from cryptography import x509
    c = x509.load_pem_x509_certificate(open(cert, "rb").read())
    assert long_name in c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(
        x509.DNSName)


def test_db_storage_info_sqlite_and_metrics(tmp_path):
    """Speicherplatz: SQLite (Datei, Tabelle, Anzahl Werte), Kennzahlen aus /metrics, Größenangaben."""
    import datetime as dt
    import plc_db
    conn = {"db_typ": "sqlite", "db_datei": str(tmp_path / "w.db"), "db_tabelle": "werte", "projekt": "A"}
    b = plc_db.SqliteBackend(plc_db.db_settings(conn))
    b.connect()
    z = dt.datetime(2026, 10, 30, tzinfo=dt.timezone.utc)
    b.insert([(z + dt.timedelta(seconds=k), "A", "Druck", float(k)) for k in range(1234)])
    st = b.storage()
    b.close()
    assert st.zeilen == 1234 and st.gesamt > 0 and (st.tabelle is None or 0 < st.tabelle <= st.gesamt)
    text = plc_db.storage_info(conn)
    assert "Werte: 1.234" in text and "Datenbank gesamt:" in text
    assert plc_db.storage_info({"db_typ": ""}) == "Keine Datenbank gewählt."
    metrics = ('# HELP x\nvm_data_size_bytes{type="indexdb/file"} 1000\nvm_data_size_bytes{type="storage/small"} 2.5e3\n'
               'other_metric 7\nprometheus_tsdb_wal_storage_size_bytes 300\n')
    assert plc_db._metric_sum(metrics, {"vm_data_size_bytes"}) == 3500
    assert plc_db._metric_sum(metrics, {"fehlt"}) is None
    assert plc_db.fmt_bytes(512) == "512 B" and plc_db.fmt_bytes(3_400_000) == "3,4 MB"
    assert plc_db.fmt_bytes(None) == "–"


def test_victoriametrics_storage_helpers():
    """VictoriaMetrics: Aufbewahrung als Zeitraum, Tage, gespeicherte Werte aus /metrics."""
    import plc_db
    assert plc_db._vm_range("") == "31d" and plc_db._vm_range("3") == "93d" and plc_db._vm_range("90d") == "90d"
    assert plc_db._range_days("90d") == 90 and plc_db._range_days("1y") == 365 and plc_db._range_days("x") == 0
    text = 'vm_rows{type="storage/small"} 100\nvm_rows{type="storage/big"} 50\nvm_rows{type="indexdb/file"} 9\n'
    assert plc_db._vm_rows(text) == 150 and plc_db._vm_rows("") is None


@pytest.mark.skipif(not os.environ.get("PLC_TEST_VICTORIAMETRICS"), reason="kein VictoriaMetrics-Server")
def test_victoriametrics_real_server_storage():
    """Echter VictoriaMetrics-Server (Workflow „Tests“ unter Linux): schreiben, Speicherplatz je Projekt abfragen."""
    import time
    import urllib.parse
    import urllib.request
    import plc_db
    url = urllib.parse.urlparse(os.environ["PLC_TEST_VICTORIAMETRICS"])
    table = f"plc_test_{os.getpid()}"
    now = time.time()
    for proj, n in (("Kunde A", 120), ("Kunde B", 60)):
        conn = {"db_typ": "victoriametrics", "db_host": url.hostname, "db_port": url.port or 8428,
                "db_tabelle": table, "projekt": proj}
        w = plc_db.DbWriter(conn, ["Druck", "Temp"], interval_s=0.1)
        w.start()
        for k in range(n):
            w.put(now - 300 + k, [float(k), 20.0])
        time.sleep(1.0)
        w.stop()
        assert w.written == 2 * n, w.status()
    urllib.request.urlopen(os.environ["PLC_TEST_VICTORIAMETRICS"] + "/internal/force_flush").read()
    text = plc_db.storage_info(conn)
    assert "Aufbewahrung: 90d" in text and "Datenbank gesamt:" in text
    assert "Kunde A: 240 Werte, 2 Variablen" in text and "Kunde B: 120 Werte, 2 Variablen" in text, text


def test_grafana_dashboard_layout():
    """Grafana-Dashboard: Anordnung wie im Logger (Seiten -> Zeilen, Raster), Achsen, Farben, Abfragen je Datenbank."""
    import plc_grafana
    from plc_common import Axis, Chart, Variable
    charts = [Chart("A", [Axis("Druck bar"), Axis("Temp", auto=False, y_min=0, y_max=200)], page="Seite 1"),
              Chart("B", page="Seite 1"), Chart("C", page="Seite 1"), Chart("D", page="Seite 2"), Chart("leer")]
    variables = [Variable("Druck", color="#ff0000", chart=0), Variable("Temp", chart=0, axis=1),
                 Variable("Ein", dtype="BOOL", chart=1), Variable("Ven'til[0]", chart=2), Variable("X", chart=3)]
    conn = {"db_typ": "victoriametrics", "db_tabelle": "anlage", "projekt": "Kunde A", "anordnung": "tabs",
            "seite_anordnung": "raster", "raster_spalten": 2, "fenster_s": 60}
    d = plc_grafana.dashboard(conn, charts, variables)
    rows = [p for p in d["panels"] if p["type"] == "row"]
    assert [r["title"] for r in rows] == ["Seite 1", "Seite 2"] and rows[1]["collapsed"]   # Tabs: nur die erste offen
    top = [p for p in d["panels"] if p["type"] == "timeseries"]
    assert [(p["title"], p["gridPos"]["x"], p["gridPos"]["w"]) for p in top] == [("A", 0, 12), ("B", 12, 12),
                                                                                  ("C", 0, 24)]
    assert [p["title"] for p in rows[1]["panels"]] == ["D"]                   # Diagramm ohne Variablen fehlt
    a = top[0]
    assert a["targets"][0]["expr"] == 'anlage_wert{projekt="$projekt",variable="Druck"}'
    ov = {o["matcher"]["options"]: {p["id"]: p["value"] for p in o["properties"]} for o in a["fieldConfig"]["overrides"]}
    assert ov["Druck"]["color"]["fixedColor"] == "#ff0000" and ov["Druck"]["custom.axisPlacement"] == "left"
    assert ov["Temp"]["custom.axisPlacement"] == "right" and ov["Temp"]["max"] == 200 and "unit" in ov["Temp"]
    assert d["time"]["from"] == "now-60s" and d["templating"]["list"][0]["current"]["value"] == "Kunde A"
    ids = [p["id"] for p in d["panels"]] + [q["id"] for r in rows for q in r["panels"]]
    assert len(ids) == len(set(ids))
    sql = plc_grafana.dashboard(dict(conn, db_typ="timescale"), charts, variables)
    q = [p for p in sql["panels"] if p["type"] == "timeseries"][2]["targets"][0]["rawSql"]
    assert "variable = 'Ven''til[0]'" in q and "$__timeFilter(zeit)" in q
    with pytest.raises(ValueError):
        plc_grafana.dashboard(dict(conn, db_typ="sqlite"), charts, variables)


@pytest.mark.skipif(not (os.environ.get("PLC_TEST_GRAFANA") and os.environ.get("PLC_TEST_VICTORIAMETRICS")),
                    reason="kein Grafana/VictoriaMetrics (PLC_TEST_GRAFANA, PLC_TEST_VICTORIAMETRICS)")
def test_grafana_dashboard_import_real(tmp_path):
    """Echtes Grafana (Workflow „Tests“ unter Linux): Dashboard importieren, Datenquelle zuordnen, Abfragen ausführen."""
    import base64
    import json
    import time
    import urllib.parse
    import urllib.request
    import plc_db
    import plc_grafana
    from plc_recorder import demo_config
    g = urllib.parse.urlparse(os.environ["PLC_TEST_GRAFANA"])
    base = f"{g.scheme}://{g.hostname}:{g.port}"
    auth = "Basic " + base64.b64encode(f"{g.username}:{g.password}".encode()).decode()

    def api(path, body=None):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": auth, "Content-Type": "application/json"},
                                     method="POST" if body is not None else "GET")
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode() or "{}")
    vm = urllib.parse.urlparse(os.environ["PLC_TEST_VICTORIAMETRICS"])
    table = f"grafana_{os.getpid()}"
    charts, variables = demo_config()
    conn = {"db_typ": "victoriametrics", "db_host": vm.hostname, "db_port": vm.port, "db_tabelle": table,
            "projekt": "Kunde A", "seite_anordnung": "raster"}
    w = plc_db.DbWriter(conn, [v.name for v in variables], interval_s=0.1)
    w.start()
    now = time.time()
    for k in range(120):
        w.put(now - 200 + k, [float(k % 2) if v.dtype == "BOOL" else 10.0 + k for v in variables])
    time.sleep(1.0)
    w.stop()
    urllib.request.urlopen(os.environ["PLC_TEST_VICTORIAMETRICS"] + "/internal/force_flush").read()
    ds = api("/api/datasources", {"name": f"VM {table}", "type": "prometheus", "access": "proxy",
                                   "url": os.environ["PLC_TEST_VICTORIAMETRICS"]})["datasource"]
    path = tmp_path / "dashboard.json"
    plc_grafana.export(str(path), conn, charts, variables)
    d = json.loads(path.read_text(encoding="utf-8"))
    res = api("/api/dashboards/import", {"dashboard": d, "overwrite": True, "inputs": [
        {"name": "DS_PLC", "type": "datasource", "pluginId": "prometheus", "value": ds["uid"]}]})
    got = api(f"/api/dashboards/uid/{res.get('uid') or d['uid']}")["dashboard"]
    panels = [p for p in got["panels"] if p["type"] == "timeseries"]
    assert len(panels) == len(charts) and all(p["datasource"]["uid"] == ds["uid"] for p in panels)
    found = set()
    for p in panels:
        queries = [{"refId": t["refId"], "datasource": {"uid": ds["uid"]}, "expr": t["expr"].replace("$projekt", "Kunde A"),
                    "range": True} for t in p["targets"]]
        r = api("/api/ds/query", {"queries": queries, "from": str(int((now - 600) * 1000)), "to": str(int(now * 1000))})
        for ref in r["results"].values():
            for frame in ref.get("frames", []):
                for f in frame["schema"]["fields"]:
                    if f.get("labels", {}).get("variable"):
                        found.add(f["labels"]["variable"])
    assert found == {v.name for v in variables}, found
    values = api(f"/api/datasources/uid/{ds['uid']}/resources/api/v1/label/projekt/values")
    assert "Kunde A" in values.get("data", []), values


class _FakeNm:
    """Ersatz für nmcli: feste Antworten, Befehle werden mitgeschrieben."""

    def __init__(self):
        self.calls = []

    def __call__(self, args, timeout=30):
        self.calls.append(args)
        a = " ".join(args)
        if a == "nmcli -t -f RUNNING general":
            return "running\n"
        if a == "nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device":
            return "eth0:ethernet:connected:Wired connection 1\nwlan0:wifi:connected:Büro\nlo:loopback:unmanaged:--\n"
        if a.startswith("nmcli -t -f IP4.ADDRESS,IP4.GATEWAY,IP4.DNS device show eth0"):
            return "IP4.ADDRESS[1]:192.168.0.50/24\nIP4.GATEWAY:192.168.0.1\nIP4.DNS[1]:192.168.0.1\n"
        if a.startswith("nmcli -t -f IP4.ADDRESS,IP4.GATEWAY,IP4.DNS device show wlan0"):
            return "IP4.ADDRESS[1]:10.0.0.23/24\nIP4.GATEWAY:10.0.0.1\n"
        if a.startswith("nmcli -g ipv4.method connection show"):
            return "manual\n" if "Wired" in a else "auto\n"
        if a.startswith("nmcli -t -f ACTIVE,SSID,SIGNAL,SECURITY device wifi list"):
            return "yes:Büro:70:WPA2\nno:Gast:40:\nno:Büro:30:WPA2\nno:Mit\\:Doppelpunkt:55:WPA2\nno::20:\n"
        if a == "nmcli -t radio wifi":
            return "enabled\n"
        return ""


def test_netz_nmcli_read_and_set():
    """Netzwerk über nmcli: Schnittstellen, WLAN-Liste, feste Adresse/DHCP setzen, Eingaben prüfen."""
    import plc_netz
    fake = _FakeNm()
    n = plc_netz.Netz(run=fake)
    devs = n.devices()
    assert [(d.name, d.typ, d.ipv4, d.dhcp) for d in devs] == [
        ("eth0", "ethernet", ["192.168.0.50/24"], False), ("wlan0", "wifi", ["10.0.0.23/24"], True)]
    assert devs[0].gateway == "192.168.0.1" and devs[0].dns == ["192.168.0.1"]
    wl = n.wifi_list()
    assert [w.ssid for w in wl] == ["Büro", "Mit:Doppelpunkt", "Gast"] and wl[0].active and wl[0].signal == 70
    fake.calls.clear()
    n.set_ipv4("eth0", dhcp=False, address="192.168.0.60/255.255.255.0", gateway="192.168.0.1",
               dns="192.168.0.1, 8.8.8.8")
    mod = next(c for c in fake.calls if c[:3] == ["nmcli", "connection", "modify"])
    assert mod[3] == "Wired connection 1" and "192.168.0.60/24" in mod and "192.168.0.1 8.8.8.8" in mod
    assert ["nmcli", "connection", "up", "Wired connection 1"] in fake.calls
    fake.calls.clear()
    n.set_ipv4("eth0", dhcp=True)
    mod = next(c for c in fake.calls if c[:3] == ["nmcli", "connection", "modify"])
    assert mod[mod.index("ipv4.method") + 1] == "auto"
    n.wifi_connect("Gast", "", "wlan0")
    assert fake.calls[-1] == ["nmcli", "device", "wifi", "connect", "Gast", "ifname", "wlan0"]
    assert plc_netz.check_ipv4("192.168.0.50/24", "192.168.0.1", "1.1.1.1") == ""
    assert plc_netz.check_ipv4("192.168.0.50") and plc_netz.check_ipv4("192.168.0.0/24")
    assert plc_netz.check_ipv4("192.168.0.50/24", "10.0.0.1") and plc_netz.check_ipv4("1.2.3.4/8", "", "x")
    with pytest.raises(ValueError):
        n.set_ipv4("eth0", dhcp=False, address="300.1.1.1/24")


def test_netz_without_networkmanager():
    """Ohne NetworkManager: Adressen aus ``ip -j addr`` (nur Anzeige)."""
    import json
    import plc_netz

    def run(args, timeout=30):
        if args[0] == "nmcli":
            raise RuntimeError("nicht installiert")
        return json.dumps([{"ifname": "lo", "addr_info": [{"family": "inet", "local": "127.0.0.1", "prefixlen": 8}]},
                           {"ifname": "eth0", "addr_info": [{"family": "inet", "local": "192.168.1.9", "prefixlen": 24}]},
                           {"ifname": "docker0", "addr_info": []}, {"ifname": "wlan0", "addr_info": []}])
    devs = plc_netz.Netz(run=run).devices()
    assert [(d.name, d.typ, d.ipv4, d.state) for d in devs] == [("eth0", "ethernet", ["192.168.1.9/24"], "connected"),
                                                               ("wlan0", "wifi", [], "disconnected")]
