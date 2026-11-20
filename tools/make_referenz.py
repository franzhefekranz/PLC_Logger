# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Kapitel „Referenz: alle Menüs, Fenster und Bedienelemente“ in beiden Anleitungen erzeugen.

Grundlage ist die Mitschrift der Fenster (``doc/referenz/referenz_de.json`` und ``referenz_en.json``, erzeugt vom
Workflow *UI-Referenz*, siehe ``tools/ui_dump.py``) und die Beschreibungen in ``tools/referenz_texte.py``.
Bezeichnungen, Tastenkürzel und Tooltips kommen aus der Mitschrift, d. h. aus dem Programm selbst; wo ein Tooltip
fehlt, steht die Beschreibung in ``referenz_texte.py``.

Neu erzeugen, wenn Menüs oder Dialoge dazukommen::

    # Workflow „UI-Referenz“ starten, dann
    git fetch origin +ui-referenz:refs/remotes/origin/ui-referenz
    git checkout origin/ui-referenz -- referenz && mv referenz/referenz_*.json doc/referenz/ && rm -r referenz
    python tools/make_referenz.py          # meldet Elemente ohne Beschreibung

Das Kapitel steht in beiden Anleitungen zwischen ``.. referenz-anfang`` und ``.. referenz-ende`` und wird dort
ersetzt (beim ersten Mal vor „Hilfe und Kontexthilfe (F1)“ eingefügt).
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import referenz_texte as T  # noqa: E402

START, END = ".. referenz-anfang", ".. referenz-ende"
FILES = {"de": os.path.join(ROOT, "doc", "bedienungsanleitung.rst"),
         "en": os.path.join(ROOT, "doc", "user_manual.rst")}
BEFORE = {"de": "Hilfe und Kontexthilfe (F1)", "en": "Help and context help (F1)"}
UNDER = {"=": "=" * 70, "-": "-" * 70, "~": "~" * 70}

MISSING = []                      # (Klasse, deutscher Text) ohne Beschreibung


def esc(text):
    """Text aus dem Programm für RST maskieren (keine Auszeichnung)."""
    text = " ".join((text or "").split())
    text = text.replace("\\", "\\\\")
    for ch in "*`|":
        text = text.replace(ch, "\\" + ch)
    text = re.sub(r"(\w)_(?=\W|$)", r"\1\\_", text)
    return re.sub(r"^([-+#•]) ", r"\\\1 ", text)


def esc_link(text):
    """Überschrift als Verweistext: ``code`` -> code, keine spitzen Klammern."""
    return text.replace("``", "").replace("<", "").replace(">", "")


def _same(a, b):
    """Tooltip sagt nichts anderes als der Text (z. B. „Öffnen“ zu „Öffnen …“)."""
    def n(s):
        return re.sub(r"[\s.…:]+$", "", " ".join((s or "").split())).lower()
    return n(a) == n(b)


class Win:
    """Ein Fenster der Mitschrift in beiden Sprachen; liefert Beschreibungen (Tooltip bzw. referenz_texte)."""

    def __init__(self, de, en, cls=None):
        self.de, self.en, self.cls = de, en, cls or de["class"]
        self.count = {}

    def desc(self, de_text, de_tip, en_tip, cls=None):
        """(Beschreibung de, en) – aus referenz_texte, sonst Tooltip; None = nicht aufführen."""
        cls = cls or self.cls
        n = self.count.get((cls, de_text), 0)
        self.count[(cls, de_text)] = n + 1
        table = T.D.get(cls, {})
        if de_text in table:
            v = table[de_text]
            if isinstance(v, list):
                v = v[min(n, len(v) - 1)]
            return v
        if de_tip and not _same(de_tip, de_text):
            return esc(de_tip), esc(en_tip)
        MISSING.append((cls, de_text))
        return "", ""


def rename(cls, de_text, en_text):
    """Angezeigter Text (dynamische Teile wie Zahlen ersetzt) – (de, en), schon maskiert bzw. ausgezeichnet."""
    r = T.RENAME.get(cls, {}).get(de_text)
    return r if r else (esc(de_text), esc(en_text))


# --------------------------------------------------------------------------------------------- RST-Bausteine
def heading(text, level):
    return [text, UNDER[level][:max(len(text), 10)] if level == "~" else UNDER[level], ""]


def table(rows, cols, widths):
    """list-table; rows = Listen von Zellen (schon RST)."""
    out = [".. list-table::", "   :header-rows: 1", "   :widths: " + " ".join(map(str, widths)), ""]
    seen = set()
    for r in [cols] + rows:
        if tuple(r) in seen:
            continue
        seen.add(tuple(r))
        for i, c in enumerate(r):
            out.append(("   * - " if i == 0 else "     - ") + (c or " "))
    return out + [""]


TITLES = {}                     # Sprache -> {Sprungmarke: Überschrift}


def titles(lang):
    """Sprungmarken der Anleitung mit der Überschrift dahinter (Text der Verweise „Mehr dazu“)."""
    if lang not in TITLES:
        lines = open(FILES[lang], encoding="utf-8").read().split("\n")
        found = {}
        for i, line in enumerate(lines):
            m = re.fullmatch(r"\.\. _([\w-]+):", line)
            if m:
                j = i + 1
                while j < len(lines) and (not lines[j].strip() or lines[j].startswith(".. _")):
                    j += 1
                text = lines[j].strip()
                if not (j + 1 < len(lines) and re.fullmatch(r"[=\-~]{5,}", lines[j + 1])):
                    text = re.sub(r"\*\*(.+?)\*\*.*", r"\1", text)     # Absatz mit fettem Anfang
                found[m.group(1)] = text.rstrip(":")
        TITLES[lang] = found
    return TITLES[lang]


def more(label, lang):
    if not label:
        return []
    labels = label if isinstance(label, (list, tuple)) else [label]
    word = "Mehr dazu" if lang == "de" else "More"
    for lb in labels:
        if lb not in titles(lang):
            raise SystemExit(f"Sprungmarke {lb} fehlt in {FILES[lang]}")
    links = ", ".join(f"`{esc_link(titles(lang)[lb])} <{lb}_>`__" for lb in labels)
    return [f"*{word}:* {links}", ""]


def keys(item, lang):
    ks = item.get("keys", [])
    return ", ".join(f"``{k}``" for k in ks)


# --------------------------------------------------------------------------------------------- Menüs
def menu_rows(w, de_items, en_items, prefix=("", ""), cls=None):
    """Zeilen (Menüpunkt, Taste, Funktion) beider Sprachen."""
    rows = {"de": [], "en": []}

    def add(de_cell, en_cell, k_de, k_en, d):
        rows["de"].append([de_cell, k_de, d[0]])
        rows["en"].append([en_cell, k_en, d[1]])

    for a, b in zip(de_items, en_items):
        if a.get("sep") or a["text"] in T.SKIP:
            continue
        ta, tb = rename(cls or w.cls, a["text"], b["text"])
        ta, tb = prefix[0] + ta, prefix[1] + tb
        sub_a, sub_b = a.get("sub"), b.get("sub")
        if sub_a and all(s.get("check") and not s.get("tip") and not s.get("sub") for s in sub_a if not s.get("sep")):
            # ankreuzbare Auswahl -> eine Zeile „Anordnung › A / B / C“
            ja = " / ".join(esc(s["text"]) for s in sub_a if not s.get("sep"))
            jb = " / ".join(esc(s["text"]) for s in sub_b if not s.get("sep"))
            d = w.desc(a["text"], a.get("tip"), b.get("tip"), cls)
            if d is not None:
                add(f"{ta} › {ja}", f"{tb} › {jb}", "", "", d)
            continue
        if sub_a:
            # Untermenü: eigene Zeile nur, wenn der Eintrag selbst beschrieben ist
            if a["text"] in T.D.get(cls or w.cls, {}) or (a.get("tip") and not _same(a["tip"], a["text"])):
                d = w.desc(a["text"], a.get("tip"), b.get("tip"), cls)
                if d is not None:
                    add(ta, tb, keys(a, "de"), keys(b, "en"), d)
            r = menu_rows(w, sub_a, sub_b, (ta + " › ", tb + " › "), cls)
            rows["de"] += r["de"]
            rows["en"] += r["en"]
            continue
        d = w.desc(a["text"], a.get("tip"), b.get("tip"), cls)
        if d is not None:
            add(ta, tb, keys(a, "de"), keys(b, "en"), d)
    return rows


def chart_entries(items_de, items_en, kind):
    """Einträge je Diagramm (Screenshot, PID) zu einer Zeile zusammenfassen: (übrige de, übrige en, gefunden)."""
    keep_de, keep_en, found = [], [], False
    for a, b in zip(items_de, items_en):
        per_chart = (not a.get("sep") and not a.get("check") and not a.get("sub")
                     and _same(a.get("tip", ""), a["text"])
                     and (kind == "screenshot" or a["text"].startswith("PID-Optimierung:")))
        if per_chart:
            if not found:
                keep_de.append({"chart": kind})
                keep_en.append({"chart": kind})
            found = True
            continue
        keep_de.append(a)
        keep_en.append(b)
    return keep_de, keep_en


def menu_table(w, m_de, m_en, lang_rows=None, cls=None, kind=None):
    items_de, items_en = m_de["sub"], m_en["sub"]
    if kind:
        items_de, items_en = chart_entries(items_de, items_en, kind)
    rows = {"de": [], "en": []}
    plain_de, plain_en = [], []

    def flush():
        r = menu_rows(w, plain_de, plain_en, cls=cls)
        rows["de"].extend(r["de"])
        rows["en"].extend(r["en"])
        plain_de.clear()
        plain_en.clear()
    for a, b in zip(items_de, items_en):
        if a.get("chart"):
            flush()
            (cde, cen), (dde, den) = T.CHART_ENTRY[a["chart"]]
            rows["de"].append([cde, "", dde])
            rows["en"].append([cen, "", den])
        else:
            plain_de.append(a)
            plain_en.append(b)
    flush()
    return rows


def lang_menu(w, m_de, m_en):
    """Menü Sprache: Sprachen zu einer Zeile zusammenfassen."""
    langs_de = [a for a in m_de["sub"] if a.get("check") and not a.get("sub")]
    langs_en = [b for a, b in zip(m_de["sub"], m_en["sub"]) if a.get("check") and not a.get("sub")]
    rest_de = [a for a in m_de["sub"] if a not in langs_de]
    rest_en = [b for a, b in zip(m_de["sub"], m_en["sub"]) if a not in langs_de]
    d = w.desc(langs_de[0]["text"], "", "", "Common")
    rows = {"de": [[" / ".join(esc(a["text"]) for a in langs_de) + " / …", "", d[0]]],
            "en": [[" / ".join(esc(b["text"]) for b in langs_en) + " / …", "", d[1]]]}
    r = menu_rows(w, rest_de, rest_en, cls="Common")
    rows["de"] += r["de"]
    rows["en"] += r["en"]
    return rows


# --------------------------------------------------------------------------------------------- Bedienelemente
KEY_IN_TIP = re.compile(r"^(.*?)\s*\(((?:Ctrl|Strg)\+[^)]+)\)$")


def control_rows(w, ctl_de, ctl_en, with_tabs=False):
    """Zeilen (Element, Funktion) beider Sprachen."""
    rows = {"de": [], "en": []}
    for a, b in zip(ctl_de, ctl_en):
        if a["text"] in T.SKIP or not a["text"]:
            continue
        tip_a, tip_b, key_a, key_b = a.get("tip", ""), b.get("tip", ""), "", ""
        ma, mb = KEY_IN_TIP.match(tip_a), KEY_IN_TIP.match(tip_b)
        if ma and mb:
            tip_a, key_a = ma.group(1), ma.group(2).replace("Ctrl", "Strg")
            tip_b, key_b = mb.group(1), mb.group(2).replace("Strg", "Ctrl")
        if a["kind"] == "gruppe" and a["text"] not in T.D.get(w.cls, {}):
            continue                            # Gruppenüberschrift ohne eigene Funktion
        d = w.desc(a["text"], tip_a, tip_b)
        if d is None:
            continue
        ta, tb = rename(w.cls, a["text"], b["text"])
        if a["kind"] == "tabelle":
            ta, tb = ("Tabelle: " + ta, "Table: " + tb) if a["text"] not in T.RENAME.get(w.cls, {}) else (ta, tb)
        if key_a:
            ta, tb = f"{ta} (``{key_a}``)", f"{tb} (``{key_b}``)"
        if with_tabs and a["tabs"]:
            ta = "*" + esc(" › ".join(a["tabs"])) + ":* " + ta
            tb = "*" + esc(" › ".join(b["tabs"])) + ":* " + tb
        rows["de"].append([ta, d[0]])
        rows["en"].append([tb, d[1]])
    return rows


def by_tab(win_de, win_en, split=False):
    """Bedienelemente nach Reitern gruppieren: [(Reiter de, Reiter en, Elemente de, Elemente en)], Reiter in der
    Reihenfolge des Fensters, Elemente ohne Reiter danach (``split``: die vor dem ersten Reiter-Element davor)."""
    pages_de = [p for t in win_de.get("tabwidgets", []) if not t["tabs"] for p in t["pages"]]
    pages_en = [p for t in win_en.get("tabwidgets", []) if not t["tabs"] for p in t["pages"]]
    groups, seen_tab = {}, False
    for a, b in zip(win_de["controls"], win_en["controls"]):
        seen_tab = seen_tab or bool(a["tabs"])
        k = a["tabs"][0] if a["tabs"] else ("" if seen_tab or not split else " ")
        g = groups.setdefault(k, ([], []))
        g[0].append(a)
        g[1].append(b)
    out = [("", "") + groups[" "]] if " " in groups else []
    out += [(p, q) + groups[p] for p, q in zip(pages_de, pages_en) if p in groups]
    if "" in groups:
        out.append(("", "") + groups[""])
    return out


def find(data, cls, title=None, last=False):
    ws = [i for i, w in enumerate(data["de"]["windows"]) if w["class"] == cls
          and (title is None or w["title"].startswith(title))]
    if not ws:
        raise SystemExit(f"Fenster {cls} {title or ''} nicht in der Mitschrift")
    i = ws[-1] if last else ws[0]
    return data["de"]["windows"][i], data["en"]["windows"][i]


def build(data):
    out = {"de": [], "en": []}

    def emit(lines_de, lines_en):
        out["de"].extend(lines_de)
        out["en"].extend(lines_en)

    def head(pair, level):
        emit(heading(pair[0], level), heading(pair[1], level))

    def tables(rows, kind):
        if not rows["de"]:
            return
        if kind == "toolbar":
            emit(table(rows["de"], ["Knopf", "Taste", "Funktion"], [32, 16, 52]),
                 table(rows["en"], ["Button", "Key", "Function"], [32, 16, 52]))
        elif kind == "menu":
            emit(table(rows["de"], ["Menüpunkt", "Taste", "Funktion"], [32, 16, 52]),
                 table(rows["en"], ["Menu item", "Key", "Function"], [32, 16, 52]))
        else:
            emit(table(rows["de"], ["Element", "Funktion"], [35, 65]),
                 table(rows["en"], ["Element", "Function"], [35, 65]))

    def para(pair):
        emit([pair[0], ""], [pair[1], ""])

    def link(label):
        emit(more(label, "de"), more(label, "en"))

    emit([START, "", ".. _referenz:", ""], [START, "", ".. _referenz:", ""])
    head(T.TITLE, "=")
    para(T.INTRO)

    # ---- Logger: Menüs
    mw_de, mw_en = find(data, "MainWindow")
    w = Win(mw_de, mw_en)
    menus = {m["text"]: (m, n) for m, n in zip(mw_de["menus"], mw_en["menus"])}
    head(T.S["logger_menus"], "-")
    para(T.P["logger_menus"])
    for name, kind, label in (("Datei", None, ["webserver", "db-lesen", "werte-exportieren", "notizen"]),
                              ("Ansicht", None, ["seiten", "trigger-marken"]),
                              ("Screenshot", "screenshot", "screenshots"),
                              ("Analyse", "pid", ["analyse", "pid-optimierung", "pdf-berichte", "io-check"])):
        m, n = menus[name]
        head((f"Menü {m['text']} (Logger)", f"Menu {n['text']} (logger)"), "~")
        tables(menu_table(w, m, n, kind=kind), "menu")
        link(label)

    # ---- Sprache und Hilfe
    head(T.S["common"], "-")
    para(T.P["common"])
    m, n = menus["Sprache"]
    head((f"Menü {m['text']}", f"Menu {n['text']}"), "~")
    tables(lang_menu(w, m, n), "menu")
    link("sprache")
    m, n = menus["Hilfe"]
    head((f"Menü {m['text']}", f"Menu {n['text']}"), "~")
    tables(menu_table(w, m, n, cls="Common"), "menu")

    # ---- Logger: Werkzeugleiste und Fenster
    head(T.S["logger_window"], "-")
    head(T.S["toolbar"], "~")
    menu_texts = {}
    for m, n in zip(mw_de["menus"], mw_en["menus"]):
        for a, b in zip(m["sub"], n["sub"]):
            if not a.get("sep"):
                menu_texts.setdefault(a["text"], (m["text"], n["text"], b["text"]))
    rows = {"de": [], "en": []}
    for a, b in zip(mw_de["toolbars"][0]["sub"], mw_en["toolbars"][0]["sub"]):
        if a["text"] in menu_texts and a["text"] not in T.D["MainWindow"]:
            mde, men, ben = menu_texts[a["text"]]
            d = (f"Wie Menü *{esc(mde)} › {esc(a['text'])}*", f"Same as menu *{esc(men)} › {esc(ben)}*")
            if a.get("tip") and not _same(a["tip"], a["text"]):
                d = (esc(a["tip"]), esc(b["tip"]))
            rows["de"].append([esc(a["text"]), keys(a, "de"), d[0]])
            rows["en"].append([esc(b["text"]), keys(b, "en"), d[1]])
            continue
        r = menu_rows(w, [a], [b])
        rows["de"] += r["de"]
        rows["en"] += r["en"]
    tables(rows, "toolbar")
    link(["bedienelemente", "demo-modus", "zoomen"])
    head(T.S["main_controls"], "~")
    rows = control_rows(w, mw_de["controls"], mw_en["controls"])
    for (de_el, en_el), (de_d, en_d) in T.MAIN_EXTRA:
        rows["de"].append([de_el, de_d])
        rows["en"].append([en_el, en_d])
    tables(rows, "ctl")
    link(["status-led", "ereignisse"])
    head(T.S["mouse"], "~")
    tables({"de": [[a[0], b[0]] for a, b in T.MOUSE], "en": [[a[1], b[1]] for a, b in T.MOUSE]}, "ctl")
    link(["zoomen", "seiten"])

    # ---- Startbild
    s_de, s_en = find(data, "StartWindow")
    head(T.S["start"], "-")
    tables(control_rows(Win(s_de, s_en), s_de["controls"], s_en["controls"]), "ctl")
    link(["startbild", "logger-client"])

    # ---- Konfigurationsprogramm
    c_de, c_en = find(data, "ConfigWindow")
    wc = Win(c_de, c_en)
    head(T.S["config_menus"], "-")
    for m, n in zip(c_de["menus"], c_en["menus"]):
        if m["text"] in ("Sprache", "Hilfe"):
            continue
        head((f"Menü {m['text']} (Konfigurationsprogramm)", f"Menu {n['text']} (configuration program)"), "~")
        tables(menu_table(wc, m, n), "menu")
    para(T.P["config_common"])
    link(["ini-umwandeln", "headless", "treiber", "treiber-entwickeln"])
    head(T.S["config_tabs"], "-")
    para(T.P["config_tabs"])
    for p, q, ca, cb in by_tab(c_de, c_en):
        head((f"Reiter {p}", f"Tab {q}") if p else T.S["config_vars"], "~")
        tables(control_rows(wc, ca, cb), "ctl")
        link(T.TAB_LINKS.get(p, ""))

    # ---- IO-Check
    i_de, i_en = find(data, "IoCheckWindow", last=True)
    wi = Win(i_de, i_en)
    head(T.S["io"], "-")
    head(T.S["io_toolbar"], "~")
    rows = {"de": [], "en": []}
    for tb_de, tb_en in zip(i_de["toolbars"], i_en["toolbars"]):
        r = menu_rows(wi, tb_de["sub"], tb_en["sub"])
        rows["de"] += r["de"]
        rows["en"] += r["en"]
    tables(rows, "toolbar")
    link(["io-check", "io-protokoll", "io-mobil"])
    for p, q, ca, cb in by_tab(i_de, i_en):
        head((f"Reiter {p} (IO-Check)", f"Tab {q} (IO check)") if p else T.S["io_side"], "~")
        rows = control_rows(wi, ca, cb)
        if p == "Signalliste":
            for (de_el, en_el), (de_d, en_d) in T.IO_EXTRA:
                rows["de"].append([de_el, de_d])
                rows["en"].append([en_el, en_d])
        tables(rows, "ctl")
        link(T.TAB_LINKS.get(p, ""))

    # ---- Ereignisprotokoll
    e_de, e_en = find(data, "EventViewer")
    head(T.S["events"], "-")
    tables(control_rows(Win(e_de, e_en), e_de["controls"], e_en["controls"]), "ctl")
    link(["ereignisse", "notizen"])

    # ---- Netzwerk-Panel (Seiten statt Einzelknöpfe)
    head(T.S["netpanel"], "-")
    para(T.P["netpanel"])
    tables({"de": [[a[0], b[0]] for a, b in T.NETPANEL], "en": [[a[1], b[1]] for a, b in T.NETPANEL]}, "ctl")
    link("raspberry")

    # ---- Dialoge
    for sec, dialogs in T.DIALOGS:
        head(T.S[sec], "-")
        for cls, title, (hde, hen), label in dialogs:
            d_de, d_en = find(data, cls, title)
            head((f"Dialog „{hde}“", f"Dialog “{hen}”"), "~")
            wd = Win(d_de, d_en)
            ca = [c for g in by_tab(d_de, d_en, split=True) for c in g[2]]
            cb = [c for g in by_tab(d_de, d_en, split=True) for c in g[3]]
            tables(control_rows(wd, ca, cb, with_tabs=True), "ctl")
            link(label)

    emit([END, ""], [END, ""])
    return out


def insert(path, lines, before):
    text = open(path, encoding="utf-8").read()
    block = "\n".join(lines)
    if START in text:
        a = text.index(START)
        b = text.index(END, a) + len(END)
        text = text[:a] + block.rstrip("\n") + text[b:]
    else:
        m = re.search(r"^" + re.escape(before) + r"\n=+\n", text, re.M)
        if not m:
            raise SystemExit(f"Abschnitt „{before}“ nicht gefunden: {path}")
        text = text[:m.start()] + block + "\n\n" + text[m.start():]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def main():
    data = {}
    for lang in ("de", "en"):
        with open(os.path.join(ROOT, "doc", "referenz", f"referenz_{lang}.json"), encoding="utf-8") as f:
            data[lang] = json.load(f)
    if len(data["de"]["windows"]) != len(data["en"]["windows"]):
        raise SystemExit("Mitschrift de/en passt nicht zusammen (Zahl der Fenster)")
    out = build(data)
    if "--check" not in sys.argv:
        for lang in ("de", "en"):
            insert(FILES[lang], out[lang], BEFORE[lang])
    for cls, text in dict.fromkeys(MISSING):
        print(f"ohne Beschreibung: {cls}: {text}")
    print(f"Referenz: {len(out['de'])} Zeilen je Anleitung" + (" (nur geprüft)" if "--check" in sys.argv else ""))
    return 1 if MISSING else 0


if __name__ == "__main__":
    sys.exit(main())
