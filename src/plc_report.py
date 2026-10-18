# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""PDF-Berichte (Schicht, Tag, Woche, Monat) – ohne Oberfläche und ohne Zusatzbibliotheken.

Inhalt eines Berichts
---------------------
* Kopf: Projekt, Zeitraum, Erstellungszeit, Datenbasis (Anzahl Messzeilen, erste/letzte Messung).
* Kennwerte je Variable: Minimum, Maximum, Mittelwert, Standardabweichung, letzter Wert, Anzahl gültiger Werte;
  bei BOOL-Variablen zusätzlich der Anteil der Zeit mit Wert 1 (Einschaltdauer) und die Anzahl der Einschaltvorgänge.
* Je Diagramm der Konfiguration ein Verlauf (alle Variablen, Y-Achsen wie konfiguriert; BOOL als Spuren darunter).
* Ereignisse und Notizen des Zeitraums aus dem Ereignisprotokoll.

Automatisch (Einstellung „bericht_aktiv“): der Recorder sammelt während der Aufzeichnung für den laufenden Zeitraum
die Kennwerte und eine verdichtete Fassung des Verlaufs (``ReportAccumulator``: je Variable Minimum/Maximum/Mittel in
bis zu 1500 Zeitabschnitten – unabhängig davon, wie viele Messwerte im Speicher gehalten werden). Ist der Zeitraum
vorbei, wird der Bericht in einem eigenen Thread geschrieben (Ordner ``berichte``, Name <CSV-Name>_bericht_<Beginn>.pdf).
Beim Beenden des Programms entsteht ein Teilbericht für den angefangenen Zeitraum.

Von Hand: Logger › Analyse › „PDF-Bericht erstellen …“ für einen Zeitbereich der angezeigten Daten.

Die PDF-Datei wird direkt geschrieben (``PdfWriter``: Standardschriften Helvetica, Vektorgrafik, komprimiert).
"""
import math
import os
import threading
import zlib
from datetime import datetime, timedelta

import numpy as np

from plc_i18n import N_, tr
from plc_util import fmt_value, nice_ticks

PERIODS = {"schicht": N_("Schicht"), "tag": N_("Tag"), "woche": N_("Woche"), "monat": N_("Monat")}

# ---------------------------------------------------------------------------------------
# Zeiträume
# ---------------------------------------------------------------------------------------


def _parse_times(text, default="06:00,14:00,22:00"):
    """'06:00,14:00,22:00' -> sortierte Liste (Stunde, Minute)."""
    out = []
    for part in str(text or default).replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            h, m = (part.split(":") + ["0"])[:2]
            h, m = int(h), int(m)
            if 0 <= h < 24 and 0 <= m < 60:
                out.append((h, m))
        except ValueError:
            continue
    return sorted(set(out)) or [(6, 0)]


def period_bounds(ts, kind, shifts="06:00,14:00,22:00", start="00:00"):
    """Zeitraum (Beginn, Ende) als Unix-Zeit, der den Zeitpunkt ts enthält.

    kind: schicht (Schichtbeginne aus ``shifts``), tag, woche (ab Montag) oder monat; ``start``: Uhrzeit, zu der
    Tag/Woche/Monat beginnen (z. B. 06:00 für einen Produktionstag)."""
    now = datetime.fromtimestamp(ts)
    if kind == "schicht":
        times = _parse_times(shifts)
        cands = []
        for day in (-1, 0, 1):
            base = (now + timedelta(days=day)).replace(second=0, microsecond=0)
            cands += [base.replace(hour=h, minute=m) for h, m in times]
        cands.sort()
        begin = max(c for c in cands if c <= now)
        end = min(c for c in cands if c > now)
        return begin.timestamp(), end.timestamp()
    h, m = _parse_times(start, "00:00")[0]
    day0 = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if day0 > now:
        day0 -= timedelta(days=1)
    if kind == "woche":
        begin = day0 - timedelta(days=day0.weekday())
        return begin.timestamp(), (begin + timedelta(days=7)).timestamp()
    if kind == "monat":
        begin = day0.replace(day=1)
        if begin > now:
            begin = (begin - timedelta(days=1)).replace(day=1)
        nxt = (begin.replace(day=28) + timedelta(days=4)).replace(day=1)
        return begin.timestamp(), nxt.timestamp()
    return day0.timestamp(), (day0 + timedelta(days=1)).timestamp()


def period_label(kind, t0, t1, shifts="06:00,14:00,22:00"):
    """Kurzbezeichnung des Zeitraums, z. B. „Schicht 2 (14:00–22:00) am 18.10.2026“ oder „KW 42/2026“."""
    a, b = datetime.fromtimestamp(t0), datetime.fromtimestamp(t1)
    if kind == "schicht":
        times = _parse_times(shifts)
        try:
            no = times.index((a.hour, a.minute)) + 1
        except ValueError:
            no = 0
        return tr("Schicht {0} ({1:%H:%M}–{2:%H:%M}) am {1:%d.%m.%Y}").format(no, a, b) if no else \
            tr("Schicht {0:%d.%m.%Y %H:%M}–{1:%H:%M}").format(a, b)
    if kind == "woche":
        y, w, _d = a.isocalendar()
        return tr("KW {0}/{1}").format(w, y)
    if kind == "monat":
        return f"{a:%m/%Y}"
    if kind == "tag":
        return f"{a:%d.%m.%Y}"
    return f"{a:%d.%m.%Y %H:%M} – {b:%d.%m.%Y %H:%M}"


# ---------------------------------------------------------------------------------------
# Sammeln während der Aufzeichnung
# ---------------------------------------------------------------------------------------
class ReportAccumulator:
    """Kennwerte und verdichteter Verlauf eines Zeitraums (siehe Modulbeschreibung). Nicht thread-sicher: wird nur
    vom Sammler-Thread des Recorders gefüttert; ``freeze`` liefert eine unabhängige Kopie zum Schreiben."""

    def __init__(self, names, dtypes, t0, t1, buckets=1500, kind="", label=""):
        n = len(names)
        self.names, self.dtypes = list(names), list(dtypes)
        self.t0, self.t1, self.kind, self.label = float(t0), float(t1), kind, label
        self.nb = max(10, int(buckets))
        self.bmin = np.full((n, self.nb), np.nan)
        self.bmax = np.full((n, self.nb), np.nan)
        self.bsum = np.zeros((n, self.nb))
        self.bcnt = np.zeros((n, self.nb))
        self.cnt = np.zeros(n)
        self.sum = np.zeros(n)
        self.sq = np.zeros(n)
        self.min = np.full(n, np.nan)
        self.max = np.full(n, np.nan)
        self.last = np.full(n, np.nan)
        self.on_time = np.zeros(n)                       # BOOL: Zeit mit Wert 1 (s)
        self.rises = np.zeros(n)                         # BOOL: Anzahl 0 -> 1
        self.rows = 0
        self.first_ts = self.last_ts = None
        self._prev = None
        self.is_bool = np.array([d == "BOOL" for d in self.dtypes], dtype=bool)

    def add(self, ts, row):
        row = np.asarray(row, dtype=float)
        ok = np.isfinite(row)
        b = int((ts - self.t0) / (self.t1 - self.t0) * self.nb) if self.t1 > self.t0 else 0
        b = min(max(b, 0), self.nb - 1)
        self.bmin[ok, b] = np.fmin(self.bmin[ok, b], row[ok])
        self.bmax[ok, b] = np.fmax(self.bmax[ok, b], row[ok])
        self.bsum[ok, b] += row[ok]
        self.bcnt[ok, b] += 1
        self.cnt[ok] += 1
        self.sum[ok] += row[ok]
        self.sq[ok] += row[ok] ** 2
        self.min[ok] = np.fmin(self.min[ok], row[ok])
        self.max[ok] = np.fmax(self.max[ok], row[ok])
        if self._prev is not None and self.is_bool.any():
            pts, prow = self._prev
            dt = max(0.0, ts - pts)
            was = np.isfinite(prow) & (prow >= 0.5)
            self.on_time[self.is_bool & was] += dt
            now_on = ok & (row >= 0.5)
            self.rises[self.is_bool & now_on & np.isfinite(prow) & ~was] += 1
        self.last[ok] = row[ok]
        self._prev = (ts, row)
        self.rows += 1
        if self.first_ts is None:
            self.first_ts = ts
        self.last_ts = ts

    def add_many(self, t, y):
        """Viele Zeilen auf einmal (von Hand erstellte Berichte, vektorisiert): t[n], y[Variable][n]."""
        t = np.asarray(t, dtype=float)
        y = np.asarray(y, dtype=float).reshape(len(self.names), len(t))
        if not len(t):
            return
        span = self.t1 - self.t0
        b = (((t - self.t0) / span * self.nb) if span > 0 else np.zeros(len(t))).astype(int).clip(0, self.nb - 1)
        dt = np.diff(t, prepend=t[0]) if self._prev is None else np.diff(t, prepend=self._prev[0])
        for i in range(len(self.names)):
            v = y[i]
            ok = np.isfinite(v)
            if not ok.any():
                continue
            bi, vv = b[ok], v[ok]
            np.fmin.at(self.bmin[i], bi, vv)
            np.fmax.at(self.bmax[i], bi, vv)
            np.add.at(self.bsum[i], bi, vv)
            np.add.at(self.bcnt[i], bi, 1)
            self.cnt[i] += len(vv)
            self.sum[i] += vv.sum()
            self.sq[i] += (vv ** 2).sum()
            self.min[i] = np.fmin(self.min[i], vv.min())
            self.max[i] = np.fmax(self.max[i], vv.max())
            self.last[i] = vv[-1]
            if self.is_bool[i]:
                prev = np.concatenate(([self._prev[1][i] if self._prev is not None else np.nan], v[:-1]))
                was = np.isfinite(prev) & (prev >= 0.5)
                self.on_time[i] += float(dt[was].sum())
                self.rises[i] += int((ok & (v >= 0.5) & np.isfinite(prev) & ~was).sum())
        self.rows += len(t)
        if self.first_ts is None:
            self.first_ts = float(t[0])
        self.last_ts = float(t[-1])
        self._prev = (float(t[-1]), y[:, -1].copy())

    def stats(self):
        """[(Name, Typ, Anzahl, Min, Max, Mittel, Std, letzter, Einschaltanteil, Einschaltvorgänge)]"""
        out = []
        span = (self.last_ts - self.first_ts) if self.rows > 1 else 0.0
        for i, n in enumerate(self.names):
            c = self.cnt[i]
            mean = self.sum[i] / c if c else math.nan
            var = (self.sq[i] - c * mean * mean) / (c - 1) if c > 1 else math.nan
            sd = math.sqrt(max(var, 0.0)) if var == var else math.nan
            share = self.on_time[i] / span if (self.is_bool[i] and span > 0) else math.nan
            out.append((n, self.dtypes[i], int(c), self.min[i], self.max[i], mean, sd, self.last[i], share,
                        int(self.rises[i]) if self.is_bool[i] else None))
        return out

    def series(self, i):
        """Verdichteter Verlauf der Variable i -> (Zeiten, Werte) mit Minimum und Maximum je Abschnitt."""
        w = (self.t1 - self.t0) / self.nb
        xs, ys = [], []
        for b in range(self.nb):
            if self.bcnt[i, b] == 0:
                if xs and ys[-1] == ys[-1]:                  # Lücke: Linie unterbrechen
                    xs.append(self.t0 + (b + 0.5) * w)
                    ys.append(math.nan)
                continue
            lo, hi = self.bmin[i, b], self.bmax[i, b]
            x0 = self.t0 + b * w
            if lo == hi:
                xs.append(x0 + 0.5 * w)
                ys.append(lo)
            else:
                xs += [x0 + 0.25 * w, x0 + 0.75 * w]
                ys += [lo, hi]
        return np.asarray(xs), np.asarray(ys)

    def bool_segments(self, i):
        """BOOL: Abschnitte mit ihrem Anteil an Wert 1 -> [(von, bis, Anteil 0..1)] (gleiche Anteile zusammengefasst)."""
        w = (self.t1 - self.t0) / self.nb
        segs = []
        for b in range(self.nb):
            if self.bcnt[i, b] == 0:
                continue
            frac = round(float(self.bsum[i, b] / self.bcnt[i, b]), 2)
            a, e = self.t0 + b * w, self.t0 + (b + 1) * w
            if segs and segs[-1][2] == frac and abs(segs[-1][1] - a) < 1e-6:
                segs[-1] = (segs[-1][0], e, frac)
            else:
                segs.append((a, e, frac))
        return [s_ for s_ in segs if s_[2] > 0]

    def freeze(self):
        import copy
        return copy.deepcopy(self)


# ---------------------------------------------------------------------------------------
# PDF schreiben (minimal: Helvetica, Linien, Flächen, Text)
# ---------------------------------------------------------------------------------------
# Zeichenbreiten von Helvetica (1/1000 der Schriftgröße) für ASCII 32..126; übrige Zeichen ~ 556.
_HW = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556,
       556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667,
       556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556,
       556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722,
       500, 500, 500, 334, 260, 334, 584]


def text_width(text, size, bold=False):
    w = sum(_HW[ord(c) - 32] if 32 <= ord(c) <= 126 else 556 for c in text)
    return w * size / 1000.0 * (1.06 if bold else 1.0)


def _color(c):
    """'#rrggbb' -> 'r g b' (0..1)."""
    c = (c or "#000000").lstrip("#")
    try:
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except (ValueError, IndexError):
        r = g = b = 0
    return f"{r / 255:.3f} {g / 255:.3f} {b / 255:.3f}"


def _pdf_text(text):
    raw = str(text).encode("cp1252", "replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)").replace(b"\r", b"").replace(b"\n", b" ")


class PdfWriter:
    """Mehrseitiges PDF (A4 hoch, Koordinaten in Punkt, Ursprung links unten)."""
    W, H = 595.28, 841.89

    def __init__(self):
        self.pages = []
        self.cur = None

    def new_page(self):
        self.cur = []
        self.pages.append(self.cur)

    def _op(self, s):
        self.cur.append(s)

    def text(self, x, y, s, size=9, bold=False, color="#000000", align="left"):
        if align != "left":
            w = text_width(s, size, bold)
            x -= w if align == "right" else w / 2
        self._op(f"BT /{'F2' if bold else 'F1'} {size:.2f} Tf {_color(color)} rg {x:.2f} {y:.2f} Td (".encode()
                 + _pdf_text(s) + b") Tj ET")

    def line(self, x0, y0, x1, y1, color="#000000", width=0.5, dash=None):
        d = f"[{dash[0]} {dash[1]}] 0 d" if dash else "[] 0 d"
        self._op(f"{_color(color)} RG {width:.2f} w {d} {x0:.2f} {y0:.2f} m {x1:.2f} {y1:.2f} l S".encode())

    def rect(self, x, y, w, h, fill=None, stroke=None, width=0.5):
        ops = f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re"
        if fill and stroke:
            self._op(f"{_color(fill)} rg {_color(stroke)} RG {width:.2f} w [] 0 d {ops} B".encode())
        elif fill:
            self._op(f"{_color(fill)} rg {ops} f".encode())
        else:
            self._op(f"{_color(stroke or '#000000')} RG {width:.2f} w [] 0 d {ops} S".encode())

    def polyline(self, pts, color="#000000", width=0.8, clip=None):
        """Linienzug; None in pts unterbricht ihn. clip=(x, y, w, h) begrenzt die Zeichnung."""
        parts, pen = [], False
        for p in pts:
            if p is None:
                pen = False
                continue
            parts.append(f"{p[0]:.2f} {p[1]:.2f} {'l' if pen else 'm'}")
            pen = True
        if not parts:
            return
        pre = f"q {clip[0]:.2f} {clip[1]:.2f} {clip[2]:.2f} {clip[3]:.2f} re W n " if clip else "q "
        self._op((pre + f"{_color(color)} RG {width:.2f} w [] 0 d 1 j " + " ".join(parts) + " S Q").encode())

    def save(self, path, title=""):
        objs = []                                         # Inhalt der Objekte 1..n

        def add(data):
            objs.append(data)
            return len(objs)
        font1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        font2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        page_ids = []
        content_ids = []
        for ops in self.pages:
            stream = zlib.compress(b"\n".join(ops))
            content_ids.append(add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream) + stream
                                   + b"\nendstream"))
            page_ids.append(add(b""))                     # Seite: Inhalt folgt, sobald die Pages-Nummer feststeht
        pages_id = add(b"")
        for pid, cid in zip(page_ids, content_ids):
            objs[pid - 1] = (b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Contents %d 0 R "
                             b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> >>"
                             % (pages_id, self.W, self.H, cid, font1, font2))
        objs[pages_id - 1] = (b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % p for p in page_ids)
                              + b"] /Count %d >>" % len(page_ids))
        info = add(b"<< /Title (" + _pdf_text(title) + b") /Producer (PLC Datenlogger) /CreationDate (D:"
                   + datetime.now().strftime("%Y%m%d%H%M%S").encode() + b") >>")
        catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for k, data in enumerate(objs, 1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % k + data + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
        for off in offsets:
            out += b"%010d 00000 n \n" % off
        out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
            len(objs) + 1, catalog, info, xref)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(out)
        os.replace(tmp, path)


# ---------------------------------------------------------------------------------------
# Bericht gestalten
# ---------------------------------------------------------------------------------------
GRID, TXT, MUTE, HEAD = "#d0d5dc", "#1b2430", "#5b6878", "#0a4f8f"
MARGIN = 40


def _time_ticks(t0, t1, target=8):
    """Teilstriche der Zeitachse auch über mehrere Tage -> [(Zeit, Beschriftung)]."""
    span = t1 - t0
    steps = [60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400, 2 * 86400, 7 * 86400]
    step = next((s for s in steps if span / s <= target), steps[-1])
    off = datetime.fromtimestamp(t0).astimezone().utcoffset().total_seconds()
    t = math.ceil((t0 + off) / step) * step - off
    out = []
    while t <= t1 and len(out) < 60:
        d = datetime.fromtimestamp(t)
        if step >= 86400:
            lab = d.strftime("%d.%m.")
        elif span > 86400:
            lab = d.strftime("%d.%m. %H:%M") if (d.hour, d.minute) == (0, 0) else d.strftime("%H:%M")
        else:
            lab = d.strftime("%H:%M")
        out.append((t, lab))
        t += step
    return out


def _fmt(v, dtype="REAL"):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return fmt_value(float(v), dtype)


def _fmt_dur(s):
    s = int(round(s))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}"


class _Doc:
    """Seitenaufbau mit Kopf-/Fußzeile und fortlaufender Schreibposition."""

    def __init__(self, title, subtitle):
        self.pdf = PdfWriter()
        self.title, self.subtitle = title, subtitle
        self.page_no = 0
        self.y = 0
        self.new_page()

    def new_page(self):
        self.pdf.new_page()
        self.page_no += 1
        p, W, H = self.pdf, PdfWriter.W, PdfWriter.H
        p.text(MARGIN, H - 32, self.title, 11, bold=True, color=HEAD)
        p.text(W - MARGIN, H - 32, self.subtitle, 8.5, color=MUTE, align="right")
        p.line(MARGIN, H - 38, W - MARGIN, H - 38, color=HEAD, width=0.8)
        p.text(W - MARGIN, 22, tr("Seite {0}").format(self.page_no), 8, color=MUTE, align="right")
        p.text(MARGIN, 22, tr("PLC Datenlogger – erstellt {0:%d.%m.%Y %H:%M}").format(datetime.now()), 8, color=MUTE)
        self.y = H - 58

    def need(self, h):
        if self.y - h < 40:
            self.new_page()

    def heading(self, text):
        self.need(30)
        self.y -= 6
        self.pdf.text(MARGIN, self.y, text, 10.5, bold=True, color=HEAD)
        self.y -= 14


def _table(doc, cols, rows, widths, aligns, size=8):
    """Tabelle mit Kopfzeile; bricht auf neue Seiten um (Kopf wird wiederholt)."""
    p = doc.pdf
    rh = size + 5

    def header():
        x = MARGIN
        p.rect(MARGIN, doc.y - 3, sum(widths), rh, fill="#e8edf3")
        for c, w, a in zip(cols, widths, aligns):
            p.text(x + (w - 3 if a == "right" else 3), doc.y + 1, c, size, bold=True, color=TXT, align=a)
            x += w
        doc.y -= rh
    doc.need(rh * 2)
    header()
    for k, row in enumerate(rows):
        if doc.y - rh < 40:
            doc.new_page()
            header()
        if k % 2:
            p.rect(MARGIN, doc.y - 3, sum(widths), rh, fill="#f6f8fa")
        x = MARGIN
        for cell, w, a in zip(row, widths, aligns):
            text, color = cell if isinstance(cell, tuple) else (cell, TXT)
            s = str(text)
            while s and text_width(s, size) > w - 6:          # zu lang: kürzen
                s = s[:-2] + "…" if len(s) > 2 else ""
            p.text(x + (w - 3 if a == "right" else 3), doc.y + 1, s, size, color=color, align=a)
            x += w
        doc.y -= rh
    doc.y -= 6


def _chart(doc, chart, var_idx, acc, variables, height=230):
    """Ein Diagramm: Linien je Variable (Y-Achsen wie konfiguriert), BOOL als Spuren unter dem Diagramm."""
    p = doc.pdf
    analog = [i for i in var_idx if acc.dtypes[i] != "BOOL"]
    bools = [i for i in var_idx if acc.dtypes[i] == "BOOL"]
    lane_h = 11
    total = height + 18 + len(bools) * lane_h + 16 + 12 * math.ceil(len(var_idx) / 4)
    doc.need(total)
    p.text(MARGIN, doc.y, chart.name, 9.5, bold=True, color=TXT)
    doc.y -= 8
    n_ax = max(1, len(chart.axes))
    left, right = MARGIN + 46, PdfWriter.W - MARGIN - (46 if n_ax > 1 else 8)
    top, bottom = doc.y, doc.y - height
    w, h = right - left, top - bottom
    p.rect(left, bottom, w, h, stroke="#9aa5b1", width=0.6)
    t0, t1 = acc.t0, acc.t1
    sx = (lambda t: left + (t - t0) / (t1 - t0) * w) if t1 > t0 else (lambda t: left)
    for t, lab in _time_ticks(t0, t1):
        x = sx(t)
        p.line(x, bottom, x, top, color=GRID, width=0.4)
        p.text(x, bottom - 10, lab, 7, color=MUTE, align="center")
    # Y-Bereich je Achse: fest (Konfiguration) oder aus Minimum/Maximum der Variablen dieser Achse.
    ranges = []
    for ai in range(n_ax):
        a = chart.axes[ai] if ai < len(chart.axes) else None
        here = [i for i in analog if min(max(variables[i].axis, 0), n_ax - 1) == ai]
        if a is not None and not a.auto and a.y_max > a.y_min:
            lo, hi = a.y_min, a.y_max
        else:
            vals = [v for i in here for v in (acc.min[i], acc.max[i]) if v == v]
            lo, hi = (min(vals), max(vals)) if vals else (0.0, 1.0)
            if hi <= lo:
                lo, hi = lo - 1, hi + 1
            pad = (hi - lo) * 0.05
            lo, hi = lo - pad, hi + pad
        ranges.append((lo, hi))
    for ai in range(min(n_ax, 2)):
        lo, hi = ranges[ai]
        here = [i for i in analog if min(max(variables[i].axis, 0), n_ax - 1) == ai]
        col = variables[here[0]].color if here else MUTE
        for v in nice_ticks(lo, hi, 6):
            y = bottom + (v - lo) / (hi - lo) * h
            if ai == 0:
                p.line(left, y, right, y, color=GRID, width=0.4)
                p.text(left - 4, y - 2.5, f"{v:g}", 7, color=col, align="right")
            else:
                p.text(right + 4, y - 2.5, f"{v:g}", 7, color=col)
        name = chart.axes[ai].name if ai < len(chart.axes) else ""
        if name:
            p.text(left if ai == 0 else right, top + 3, name, 7, color=col, align="left" if ai == 0 else "right")
    clip = (left, bottom, w, h)
    for i in analog:
        ai = min(max(variables[i].axis, 0), n_ax - 1)
        lo, hi = ranges[ai]
        xs, ys = acc.series(i)
        pts = [None if not (yv == yv) else (sx(xv), bottom + (yv - lo) / (hi - lo) * h) for xv, yv in zip(xs, ys)]
        p.polyline(pts, color=variables[i].color, width=0.9, clip=clip)
    y = bottom - 18
    for i in bools:                                       # BOOL-Spuren: Linie = 0, Balken = 1
        col = variables[i].color
        p.text(left - 4, y + 1, variables[i].name, 6.5, color=col, align="right")
        p.line(left, y + 1, right, y + 1, color=col, width=0.5)
        for a, b, frac in acc.bool_segments(i):           # Höhe = Anteil der Zeit mit Wert 1 im Abschnitt
            p.rect(sx(a), y + 1, max(sx(b) - sx(a), 0.4), 7 * frac, fill=col)
        y -= lane_h
    # Legende
    x, y = left, y - 4
    for i in var_idx:
        v = variables[i]
        label = v.name
        lw = 14 + text_width(label, 7.5) + 14
        if x + lw > right:
            x, y = left, y - 12
        p.rect(x, y + 1, 10, 3, fill=v.color)
        p.text(x + 14, y, label, 7.5, color=TXT)
        x += lw
    doc.y = y - 18


def write_report(path, acc, charts, variables, project="", events=(), partial=False, info=""):
    """PDF-Bericht schreiben. acc: ReportAccumulator; charts/variables: Konfiguration (Farben, Achsen);
    events: [Event] des Zeitraums (plc_events); partial: Zeitraum noch nicht abgeschlossen."""
    label = acc.label or period_label(acc.kind, acc.t0, acc.t1)
    kind_txt = tr(PERIODS.get(acc.kind, "")) if acc.kind in PERIODS else tr("Zeitraum")
    title = tr("Bericht {0}: {1}").format(kind_txt, label) + (tr(" (unvollständig)") if partial else "")
    sub = project or ""
    doc = _Doc(title, sub)
    p = doc.pdf
    lines = [(tr("Projekt:"), project or "—"),
             (tr("Zeitraum:"), f"{datetime.fromtimestamp(acc.t0):%d.%m.%Y %H:%M} – {datetime.fromtimestamp(acc.t1):%d.%m.%Y %H:%M}"),
             (tr("Messdaten:"), tr("{0} Zeilen, {1} bis {2}").format(
                 acc.rows, f"{datetime.fromtimestamp(acc.first_ts):%d.%m. %H:%M:%S}" if acc.first_ts else "—",
                 f"{datetime.fromtimestamp(acc.last_ts):%d.%m. %H:%M:%S}" if acc.last_ts else "—"))]
    if info:
        lines.append((tr("Hinweis:"), info))
    for k, v in lines:
        p.text(MARGIN, doc.y, k, 9, bold=True, color=TXT)
        p.text(MARGIN + 75, doc.y, v, 9, color=TXT)
        doc.y -= 13
    doc.y -= 4
    # Kennwerte
    doc.heading(tr("Kennwerte"))
    rows = []
    for (n, dt, c, mn, mx, mean, sd, last, share, rises) in acc.stats():
        col = _var_for(variables, n).color
        if dt == "BOOL":
            on = tr("{0:.1f} % ein").format(share * 100) if share == share else ""
            rows.append([(n, col), _fmt(mn, dt), _fmt(mx, dt), on, tr("{0}× ein").format(rises), _fmt(last, dt), str(c)])
        else:
            rows.append([(n, col), _fmt(mn, dt), _fmt(mx, dt), _fmt(mean), _fmt(sd), _fmt(last, dt), str(c)])
    _table(doc, [tr("Variable"), tr("Minimum"), tr("Maximum"), tr("Mittelwert"), tr("Std.-Abw."), tr("Letzter Wert"),
                 tr("Werte")], rows, [150, 62, 62, 82, 62, 62, 35], ["left"] + ["right"] * 6)
    # Diagramme
    doc.heading(tr("Verlauf"))
    names_idx = {n: i for i, n in enumerate(acc.names)}
    for ci, ch in enumerate(charts):
        idx = [names_idx[v.name] for v in variables if v.chart == ci and v.name in names_idx]
        if idx:
            _chart(doc, ch, idx, acc, [_var_for(variables, n) for n in acc.names])
    # Ereignisse
    doc.heading(tr("Ereignisse und Notizen"))
    ev_rows = []
    for e in events:
        col = {"Alarm": "#c62828", "Warnung": "#b26a00"}.get(e.prio, TXT)
        ev_rows.append([e.zeit[:19], (tr(e.prio), col), e.trigger, e.text, e.gegangen[11:19] if e.gegangen else "",
                        (e.quittiert[11:19] + " " + e.benutzer) if e.quittiert else ""])
    if ev_rows:
        _table(doc, [tr("Zeit"), tr("Priorität"), tr("Trigger"), tr("Text"), tr("Gegangen"), tr("Quittiert")],
               ev_rows, [92, 50, 80, 158, 46, 89], ["left"] * 6, size=7.5)
    else:
        p.text(MARGIN, doc.y, tr("Keine Ereignisse im Zeitraum."), 8.5, color=MUTE)
        doc.y -= 14
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    p.save(path, title)
    return path


def _var_for(variables, name):
    from plc_common import Variable
    return next((v for v in variables if v.name == name), None) or Variable(name=name)


def events_in(log, t0, t1):
    """Ereignisse/Notizen des Zeitraums aus einem EventLog (älteste zuerst)."""
    from plc_events import parse_stamp
    try:
        evs = log.events()
    except Exception:
        return []
    out = [e for e in evs if (lambda ts: ts is not None and t0 <= ts < t1)(parse_stamp(e.zeit))]
    out.reverse()
    return out


def report_dir(conn):
    from plc_common import BASE_DIR
    d = (conn.get("bericht_ordner") or "berichte").strip()
    return d if os.path.isabs(d) else os.path.join(BASE_DIR, d)


def report_path(conn, acc, base_name, partial=False):
    stamp = datetime.fromtimestamp(acc.t0).strftime("%Y%m%d_%H%M")
    name = f"{base_name}_bericht_{acc.kind or 'zeitraum'}_{stamp}{'_teil' if partial else ''}.pdf"
    path, n = os.path.join(report_dir(conn), name), 1
    while os.path.exists(path):
        path = os.path.join(report_dir(conn), name[:-4] + f"_{n}.pdf")
        n += 1
    return path


def write_in_background(path, acc, charts, variables, project, events, partial, notify, wait=False):
    """Bericht in einem eigenen Thread schreiben (Meldung über notify). wait=True: auf das Ende warten."""
    def run():
        try:
            write_report(path, acc, charts, variables, project, events, partial)
            notify(tr("Bericht erstellt: {0}").format(path))
        except Exception as e:
            notify(tr("⚠ Bericht konnte nicht erstellt werden: {0}").format(e))
    th = threading.Thread(target=run, name="bericht", daemon=not wait)
    th.start()
    if wait:
        th.join(120)
    return th
