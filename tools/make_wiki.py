# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Bedienungsanleitung (doc/bedienungsanleitung.rst) in Seiten für das GitHub-Wiki umwandeln.

    python tools/make_wiki.py ZIELORDNER        (Repository für Bildadressen: Umgebungsvariable GITHUB_REPOSITORY)

Je Hauptkapitel entsteht eine Markdown-Seite (das Kapitel „Überblick“ wird die Startseite ``Home.md``), dazu die
Seitenleiste ``_Sidebar.md``, die Fußzeile ``_Footer.md`` und der Bilderordner ``images``. Verweise zwischen Kapiteln
werden auf die richtige Wiki-Seite umgebogen. Benötigt pandoc (https://pandoc.org).

Der Workflow .github/workflows/wiki.yml ruft das Skript bei jeder Änderung der Anleitung auf und überträgt das
Ergebnis ins Wiki des Repositorys.
"""
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "doc")
SOURCE = os.path.join(DOC, "bedienungsanleitung.rst")


def slug(text):
    """Anker, wie GitHub ihn aus einer Überschrift bildet."""
    text = re.sub(r"<[^>]+>|`", "", text).strip().lower()
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def page_name(title):
    """Dateiname der Wiki-Seite (ohne .md) aus dem Kapiteltitel; Dateinamen in Klammern entfallen."""
    t = re.sub(r"\(`[^`]*`\)", "", title)
    t = re.sub(r"[`()\[\]:/\\?#\"'*,.]", "", t).strip()
    return re.sub(r"\s+", "-", t)


def labels(rst):
    """Sprungmarken der Anleitung -> Überschrift, vor der sie stehen."""
    lines, out = rst.split("\n"), {}
    for i, line in enumerate(lines):
        m = re.match(r"^\.\. _([\w-]+):$", line)
        if m:
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].startswith(".. _")):
                j += 1
            out[m.group(1)] = lines[j].strip()
    return out


def main(target, repo):
    rst = open(SOURCE, encoding="utf-8").read()
    md = subprocess.run(["pandoc", "-f", "rst", "-t", "gfm", "--wrap=none", SOURCE], check=True,
                        capture_output=True, text=True, encoding="utf-8").stdout
    md = re.sub(r'<div class="contents"[^>]*>.*?</div>\s*', "", md, flags=re.S)
    title_m = re.match(r"# (.+)\n", md)
    title = title_m.group(1) if title_m else "Bedienungsanleitung"
    md = md[title_m.end():] if title_m else md

    # in Kapitel (## …) zerlegen
    parts = re.split(r"(?m)^## (.+)$", md)
    chapters = []                       # (Titel, Seitenname, Text)
    for k in range(1, len(parts), 2):
        head, body = parts[k].strip(), parts[k + 1]
        name = "Home" if k == 1 else page_name(head)
        chapters.append((head, name, body))

    # Überschrift -> (Seite, Anker) für alle Überschriften
    where = {}
    for head, name, body in chapters:
        where[slug(head)] = (name, "")
        for h in re.findall(r"(?m)^#{3,6} (.+)$", body):
            where.setdefault(slug(h), (name, slug(h)))
    label_to = {}
    for lab, head in labels(rst).items():
        s = slug(head.replace("``", "`"))
        if s in where:
            label_to[lab] = where[s]

    def fix_links(text, own):
        def repl(m):
            lab = m.group(2)
            page, anchor = label_to.get(lab, (None, None))
            if page is None:
                return m.group(0)
            if page == own:
                return f"[{m.group(1)}](#{anchor})" if anchor else m.group(1)
            return f"[{m.group(1)}]({page}" + (f"#{anchor}" if anchor else "") + ")"
        return re.sub(r"\[([^\]]+)\]\(#([\w-]+)\)", repl, text)

    if os.path.isdir(target):
        for fn in os.listdir(target):
            if fn.endswith(".md"):
                os.remove(os.path.join(target, fn))
    os.makedirs(target, exist_ok=True)
    for i, (head, name, body) in enumerate(chapters):
        text = re.sub(r"(?m)^(#{3,6}) ", lambda m: m.group(1)[1:] + " ", body)     # ### -> ##
        text = fix_links(text, name).strip() + "\n"
        # Bilder über die Wiki-Adresse von GitHub (relative Pfade funktionieren nicht auf allen Wiki-Seiten)
        text = text.replace('src="images/', f'src="https://raw.githubusercontent.com/wiki/{repo}/images/')
        heading = f"# {title}\n\n## {head}\n\n" if name == "Home" else f"# {head}\n\n"
        nav = []
        if i > 0:
            nav.append(f"← [{chapters[i - 1][0]}]({chapters[i - 1][1]})")
        if i + 1 < len(chapters):
            nav.append(f"[{chapters[i + 1][0]}]({chapters[i + 1][1]}) →")
        text += "\n---\n\n" + " · ".join(nav) + "\n" if nav else ""
        with open(os.path.join(target, name + ".md"), "w", encoding="utf-8") as f:
            f.write(heading + text)
    with open(os.path.join(target, "_Sidebar.md"), "w", encoding="utf-8") as f:
        f.write("**Bedienungsanleitung**\n\n")
        for head, name, _b in chapters:
            f.write(f"* [{head}]({name})\n")
    with open(os.path.join(target, "_Footer.md"), "w", encoding="utf-8") as f:
        f.write("Automatisch erzeugt aus [`doc/bedienungsanleitung.rst`](../blob/main/doc/bedienungsanleitung.rst) – "
                "Änderungen bitte dort vornehmen, nicht im Wiki.\n")
    img_src, img_dst = os.path.join(DOC, "images"), os.path.join(target, "images")
    if os.path.isdir(img_src):
        shutil.rmtree(img_dst, ignore_errors=True)
        shutil.copytree(img_src, img_dst)
    print(f"{len(chapters)} Seiten nach {target} geschrieben")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "wiki"),
         os.environ.get("GITHUB_REPOSITORY", "franzhefekranz/PLC_Logger"))
