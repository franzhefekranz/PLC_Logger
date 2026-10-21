"""Sphinx-Konfiguration für die Bedienungsanleitung (doc/bedienungsanleitung.rst bzw. englisch doc/user_manual.rst).

Sprache über die Umgebungsvariable PLC_DOC_LANG: "de" (Vorgabe) oder "en" (tools/build_doc.py --lang en).

PDF ohne LaTeX (rinohtype):   python -m sphinx -b rinoh doc build/doc/pdf
HTML:                         python -m sphinx -b html  doc build/doc/html
Bequemer: tools/build_doc.py (baut das PDF und legt es nach dist/).
"""
import os
import re
import sys

from docutils import nodes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _app_version():
    """Programmversion aus src/plc_common.py (APP_VERSION), ohne das Modul zu importieren."""
    try:
        with open(os.path.join(ROOT, "src", "plc_common.py"), encoding="utf-8") as f:
            m = re.search(r'^APP_VERSION = "([^"]+)"', f.read(), re.M)
        return m.group(1) if m else ""
    except OSError:
        return ""


project = "PLC Datenlogger"
author = "PLC Datenlogger"
version = release = _app_version()
language = "en" if os.environ.get("PLC_DOC_LANG", "de").lower().startswith("en") else "de"

# Je Sprache nur die eine Anleitung lesen (beide haben dieselben Sprungmarken)
if language == "en":
    root_doc, other_doc, doc_title, doc_file = "user_manual", "bedienungsanleitung", "User Manual", "User_Manual"
else:
    root_doc, other_doc, doc_title, doc_file = ("bedienungsanleitung", "user_manual", "Bedienungsanleitung",
                                                "Bedienungsanleitung")
exclude_patterns = ["_build", "images", "*.html", other_doc + ".rst"]
extensions = ["rinoh.frontend.sphinx"]

# ---- PDF (rinohtype)
rinoh_documents = [dict(
    doc=root_doc,
    target=f"PLC_Datenlogger_{doc_file}_{release}" if release else f"PLC_Datenlogger_{doc_file}",
    title="PLC Datenlogger",
    subtitle=f"{doc_title} – Version {release}" if release else doc_title,
    author="",
    logo=os.path.join(ROOT, "logo.png"),
    template="pdf.rtt",                 # Buchvorlage mit eigenem Stylesheet (pdf.rts)
)]

# ---- HTML (Vorschau im Browser)
html_title = f"{project} {release} – {doc_title}"
html_logo = os.path.join(ROOT, "logo.png")


# Emoji, für die keine PDF-Schrift ein Zeichen hat: im PDF durch Text ersetzen (HTML/Wiki zeigen sie unverändert)
PDF_EMOJI = ({"🔔": "bell", "📝": "note symbol"} if language == "en"
             else {"🔔": "Glocke", "📝": "Notiz-Symbol"})
PDF_EMOJI.update({"📱 ": "", "📱": "", "⏸ ": "", "⏺ ": ""})


def _prepare_pdf(app, doctree):
    """Nur für das PDF (rinohtype): das Inhaltsverzeichnis am Anfang der Anleitung (``.. contents::``) entfernen –
    rinohtype erzeugt ein eigenes mit Seitenzahlen – und Emoji ohne Schriftzeichen ersetzen."""
    if app.builder.name != "rinoh":
        return
    for topic in list(doctree.findall(nodes.topic)):
        if "contents" in topic["classes"]:
            topic.parent.remove(topic)
    for text in list(doctree.findall(nodes.Text)):
        new = str(text)
        for emoji, word in PDF_EMOJI.items():
            new = new.replace(emoji, word)
        if new != str(text):
            text.parent.replace(text, nodes.Text(new))


def setup(app):
    app.connect("doctree-read", _prepare_pdf)
