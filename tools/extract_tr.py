# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Alle übersetzbaren Texte (tr("…"), N_("…")) sammeln und Sprachdateien schreiben.

python extract_tr.py PFX ORDNER [--json ausgabe.json]   -> ORDNER/sprachen/de.txt (Vorlage)
Vorhandene Sprachdateien (z. B. en.txt) werden ergänzt: neue Texte kommen mit leerer Übersetzung hinzu,
vorhandene Übersetzungen bleiben erhalten, nicht mehr benutzte Texte werden entfernt.
Liegen die Programmdateien in ORDNER/src, werden sie dort gesucht (PLC-Datenlogger: python tools/extract_tr.py plc .)."""
import ast, glob, json, os, sys

def code_dir(folder):
    src = os.path.join(folder, "src")
    return src if os.path.isdir(src) else folder

sys.path.insert(0, code_dir(sys.argv[2]))

def escape(s):
    return s.replace("\\", "\\\\").replace("\n", "\\n")

def collect(pfx, folder):
    keys, where = [], {}
    paths = sorted(glob.glob(os.path.join(folder, f"{pfx}_*.py")))
    paths += sorted(glob.glob(os.path.join(folder, f"{pfx}_treiber", "*.py")))   # Treiber (PLC-Datenlogger)
    for path in paths:
        if path.endswith("_i18n.py"):
            continue
        tree = ast.parse(open(path, encoding="utf-8").read())
        nodes = sorted((n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                        and n.func.id in ("tr", "N_") and n.args), key=lambda n: (n.lineno, n.col_offset))
        for n in nodes:
            a = n.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.strip():
                if a.value not in where:
                    where[a.value] = os.path.relpath(path, folder).replace(os.sep, "/")
                    keys.append(a.value)
    # Texte aus dem Sprachmodul selbst
    i18n = os.path.join(folder, f"{pfx}_i18n.py")
    for n in ast.walk(ast.parse(open(i18n, encoding="utf-8").read())):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "tr" and n.args \
                and isinstance(n.args[0], ast.Constant) and n.args[0].value not in where:
            where[n.args[0].value] = os.path.basename(i18n)
            keys.append(n.args[0].value)
    return keys, where

HEAD = """# {app} – Sprachdatei
# Sprache: {lang}
#
# Neue Sprache: diese Datei kopieren und nach dem Sprachkürzel benennen (z. B. fr.txt, it.txt, es.txt),
# oben hinter "Sprache:" den Namen der Sprache eintragen und hinter jedem ">" die Übersetzung schreiben.
#   @ = deutscher Originaltext (nicht ändern)     > = Übersetzung (leer lassen = deutscher Text bleibt)
#   \\n = Zeilenumbruch. Platzhalter wie {{0}} oder {{1:.1f}} müssen in der Übersetzung erhalten bleiben.
#   & vor einem Buchstaben = Tastenkürzel im Menü (Alt + Buchstabe); && = ein einzelnes &-Zeichen.
# Die Datei muss UTF-8 kodiert bleiben. Gesucht wird im Ordner "sprachen" im Datenordner und im Programmordner.
# Umschalten: Menü "Sprache" (gilt nach einem Neustart).
"""

def write(path, app, lang, keys, where, table):
    out = [HEAD.format(app=app, lang=lang)]
    cur = None
    for k in keys:
        if where[k] != cur:
            cur = where[k]
            out.append(f"\n# ---------------- {cur}\n")
        out.append(f"\n@ {escape(k)}\n> {escape(table.get(k, ''))}\n")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(out))

def main():
    pfx, folder = sys.argv[1], sys.argv[2]
    app = {"s7": "S7 Datenlogger", "clx": "CLX Datenlogger", "tia": "TIA Datenlogger",
           "plc": "PLC Datenlogger"}.get(pfx, pfx)
    keys, where = collect(pfx, code_dir(folder))
    lang_dir = os.path.join(folder, "sprachen")
    os.makedirs(lang_dir, exist_ok=True)
    write(os.path.join(lang_dir, "de.txt"), app, "Deutsch", keys, where, {})
    i18n = __import__(f"{pfx}_i18n")
    for fn in sorted(os.listdir(lang_dir)):
        if fn.endswith(".txt") and fn != "de.txt":
            name, table, _w = i18n.parse_file(os.path.join(lang_dir, fn))
            write(os.path.join(lang_dir, fn), app, name or fn[:-4], keys, where, table)
    if "--json" in sys.argv:
        json.dump(keys, open(sys.argv[sys.argv.index("--json") + 1], "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(pfx, len(keys), "Texte")

main()
