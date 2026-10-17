# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Bedienungsanleitung (doc/bedienungsanleitung.rst) mit Sphinx als PDF bauen – ohne LaTeX (rinohtype).

    python tools/build_doc.py            PDF -> dist/PLC_Datenlogger_Bedienungsanleitung_<Version>.pdf
    python tools/build_doc.py --html     zusätzlich HTML-Vorschau -> build/doc/html/bedienungsanleitung.html
    python tools/build_doc.py --copy-to DATEI   das PDF zusätzlich unter festem Namen ablegen (build.bat, Installer)

Benötigt: pip install -r doc/requirements.txt  (Konfiguration: doc/conf.py, Layout: doc/pdf.rtt und doc/pdf.rts)
"""
import glob
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "doc")
OUT = os.path.join(ROOT, "build", "doc")
DIST = os.path.join(ROOT, "dist")


def sphinx(builder, target):
    # -E: Umgebung neu lesen (Änderungen an conf.py/Stylesheet wirken sicher), -q: nur Warnungen und Fehler
    return subprocess.call([sys.executable, "-m", "sphinx", "-b", builder, "-E", "-q", DOC, target])


def main():
    try:
        import rinoh  # noqa: F401
        import sphinx as _sphinx  # noqa: F401
    except ImportError as e:
        print(f"FEHLER: {e.name} fehlt. Bitte installieren:  pip install -r doc/requirements.txt")
        return 1
    pdf_dir = os.path.join(OUT, "pdf")
    if sphinx("rinoh", pdf_dir) != 0:
        print("FEHLER: PDF konnte nicht erzeugt werden (siehe Meldungen oben).")
        return 1
    pdfs = sorted(glob.glob(os.path.join(pdf_dir, "*.pdf")), key=os.path.getmtime)
    if not pdfs:
        print("FEHLER: keine PDF-Datei entstanden.")
        return 1
    # Ziel: mit --copy-to nur diese Datei (build.bat), sonst dist/ mit dem Namen samt Version
    if "--copy-to" in sys.argv:
        dest = os.path.abspath(sys.argv[sys.argv.index("--copy-to") + 1])
    else:
        dest = os.path.join(DIST, os.path.basename(pdfs[-1]))
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(pdfs[-1], dest)
    except OSError as e:
        print(f"FEHLER: {dest} kann nicht geschrieben werden ({e.strerror}) – ist die Datei in einem PDF-Programm "
              f"geöffnet? Das neue PDF liegt in {os.path.relpath(pdfs[-1], ROOT)}.")
        return 1
    print(f"[OK] PDF: {os.path.relpath(dest, ROOT)}")
    if "--html" in sys.argv:
        html_dir = os.path.join(OUT, "html")
        if sphinx("html", html_dir) != 0:
            return 1
        print(f"[OK] HTML: {os.path.relpath(os.path.join(html_dir, 'bedienungsanleitung.html'), ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
