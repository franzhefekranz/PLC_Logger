"""SVG-Export eines Diagramms – unabhängig von Qt und pyqtgraph.

Warum ein eigener Export?
-------------------------
Der Weg über ``QSvgGenerator`` + ``widget.render()`` gibt pyqtgraph-Diagramme nicht zuverlässig wieder: Kurven
(gecachte Pfade) fehlen, und verschobene Elemente wie die Lineale landen weit außerhalb. Dieses Modul zeichnet das
Diagramm deshalb selbst aus den Messdaten: Hintergrund, Raster, Zeit- und Y-Achsen (auch mehrere), Kurven,
BOOL-Verläufe, Lineale und Legende mit den Werten. Das Ergebnis ist eine reine, gut skalierbare SVG-Datei.

Verwendung (siehe ChartPanel.export_svg im Logger): ``build_svg(...)`` liefert den SVG-Text.
"""
from datetime import datetime
from xml.sax.saxutils import escape

import numpy as np

from tia_util import decimate_minmax, nice_ticks, time_ticks

# Farben des dunklen und des hellen Themas.
THEMES = {
    "dark": {"bg": "#000000", "fg": "#d0d0d0", "grid": "#ffffff", "grid_a": 0.12, "frame": "#808080",
             "legend_bg": "#000000"},
    "light": {"bg": "#ffffff", "fg": "#000000", "grid": "#000000", "grid_a": 0.12, "frame": "#606060",
              "legend_bg": "#ffffff"},
}

FONT = "font-family=\"Segoe UI, Arial, sans-serif\""


def _num(v):
    """Zahl kompakt für SVG-Koordinaten (1 Nachkommastelle)."""
    return f"{v:.1f}"


def _tick_text(v):
    """Beschriftung eines Y-Teilstrichs ohne überflüssige Nullen."""
    if v == 0:
        return "0"
    return f"{v:.6g}"


def _segments(px, py):
    """Zerlegt die Punktfolge an NaN-Stellen in zusammenhängende Teilstücke [(x[], y[])]."""
    ok = np.isfinite(py) & np.isfinite(px)
    if ok.all():
        return [(px, py)]
    out, start = [], None
    for i, flag in enumerate(ok):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            out.append((px[start:i], py[start:i]))
            start = None
    if start is not None:
        out.append((px[start:], py[start:]))
    return out


def build_svg(width, height, title, x_range, axes, series, rulers=(), legend=(), light=False):
    """SVG-Text eines Diagramms.

    width, height : Gesamtgröße in Pixeln.
    title         : Diagrammname (oben links).
    x_range       : (t0, t1) Unix-Zeit des sichtbaren Bereichs.
    axes          : [{'name', 'color', 'lo', 'hi'}] – Y-Achsen; die erste links, weitere rechts.
    series        : [{'x', 'y', 'color', 'axis', 'fill', 'width', 'opacity'}] – Kurven (numpy-Felder); fill=True füllt
                    bis zur Null-Linie; width (Standard 2) und opacity (Standard 1) für Hervorhebung/Abblenden.
    rulers        : [{'x', 'color', 'label'}] – senkrechte Lineale.
    legend        : [{'text', 'color', 'strip', 'bold', 'dim'}] – Legende; 'strip' ist optional der Verlauf eines
                    BOOL-Signals (Feld aus 0/1/NaN), das als Streifen statt als Linie gezeichnet wird.
    light         : heller Hintergrund.
    """
    th = THEMES["light" if light else "dark"]
    # --- Aufteilung der Fläche: links eine Achse, rechts je weitere Achse; oben Titel, unten Zeitachse.
    ax_w = 66
    ml, mt, mb = ax_w, 30, 40
    mr = max(ax_w * max(len(axes) - 1, 0), 14)
    px, py = ml, mt
    pw, ph = max(width - ml - mr, 10), max(height - mt - mb, 10)
    x0, x1 = x_range
    if not x1 > x0:
        x1 = x0 + 1.0

    def sx(x):
        return px + (np.asarray(x, dtype=float) - x0) / (x1 - x0) * pw

    def sy(ai, y):
        a = axes[ai]
        span = (a["hi"] - a["lo"]) or 1.0
        return py + ph - (np.asarray(y, dtype=float) - a["lo"]) / span * ph

    o = []
    o.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
             f'viewBox="0 0 {width} {height}" {FONT} font-size="12">')
    o.append(f"<title>{escape(title)}</title><desc>TIA Datenlogger</desc>")
    o.append(f'<defs><clipPath id="plot"><rect x="{px}" y="{py}" width="{pw}" height="{ph}"/></clipPath></defs>')
    o.append(f'<rect width="{width}" height="{height}" fill="{th["bg"]}"/>')
    o.append(f'<text x="{px}" y="19" fill="{th["fg"]}" font-size="14" font-weight="bold">{escape(title)}</text>')

    # --- Raster und Zeitachse
    for t, label in time_ticks(x0, x1):
        x = float(sx(t))
        o.append(f'<line x1="{_num(x)}" y1="{py}" x2="{_num(x)}" y2="{py + ph}" stroke="{th["grid"]}" '
                 f'stroke-opacity="{th["grid_a"]}"/>')
        o.append(f'<line x1="{_num(x)}" y1="{py + ph}" x2="{_num(x)}" y2="{py + ph + 4}" stroke="{th["fg"]}"/>')
        o.append(f'<text x="{_num(x)}" y="{py + ph + 18}" fill="{th["fg"]}" text-anchor="middle">{label}</text>')
    day0, day1 = datetime.fromtimestamp(x0).strftime("%d.%m.%Y"), datetime.fromtimestamp(x1).strftime("%d.%m.%Y")
    o.append(f'<text x="{px + pw}" y="{py + ph + 35}" fill="{th["fg"]}" text-anchor="end">'
             f'{day0 if day0 == day1 else day0 + " – " + day1}</text>')

    # --- Y-Achsen (Raster nur von der ersten)
    for ai, a in enumerate(axes):
        left = ai == 0
        xa = px if left else px + pw + ax_w * (ai - 1)
        o.append(f'<line x1="{xa}" y1="{py}" x2="{xa}" y2="{py + ph}" stroke="{a["color"]}"/>')
        for v in nice_ticks(a["lo"], a["hi"], 6):
            y = float(sy(ai, v))
            if left:
                o.append(f'<line x1="{px}" y1="{_num(y)}" x2="{px + pw}" y2="{_num(y)}" stroke="{th["grid"]}" '
                         f'stroke-opacity="{th["grid_a"]}"/>')
            d = -4 if left else 4
            o.append(f'<line x1="{xa}" y1="{_num(y)}" x2="{xa + d}" y2="{_num(y)}" stroke="{a["color"]}"/>')
            o.append(f'<text x="{xa + d * 2}" y="{_num(y + 4)}" fill="{a["color"]}" '
                     f'text-anchor="{"end" if left else "start"}">{escape(_tick_text(v))}</text>')
        # Achsenname senkrecht neben den Zahlen.
        cx = xa - 52 if left else xa + 56
        cy = py + ph / 2
        o.append(f'<text transform="translate({cx},{_num(cy)}) rotate(-90)" fill="{a["color"]}" '
                 f'text-anchor="middle">{escape(a["name"])}</text>')
    o.append(f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" fill="none" stroke="{th["frame"]}"/>')

    # --- Kurven (auf die Breite der Fläche verkleinert; Spitzen bleiben erhalten)
    o.append('<g clip-path="url(#plot)" fill="none" stroke-linejoin="round" stroke-linecap="round">')
    for s in series:
        x = np.asarray(s["x"], dtype=float)
        y = np.asarray(s["y"], dtype=float)
        if len(x) == 0:
            continue
        lo = max(int(np.searchsorted(x, x0, side="left")) - 1, 0)
        hi = min(int(np.searchsorted(x, x1, side="right")) + 1, len(x))
        x, y = decimate_minmax(x[lo:hi], y[lo:hi], int(pw))
        ai = min(max(int(s["axis"]), 0), len(axes) - 1)
        X, Y = sx(x), sy(ai, y)
        base = float(sy(ai, 0.0))
        width, opac = s.get("width", 2), s.get("opacity", 1.0)
        for xs, ys in _segments(X, Y):
            if len(xs) == 0:
                continue
            pts = " L".join(f"{_num(a)} {_num(b)}" for a, b in zip(xs, ys))
            if s.get("fill"):
                o.append(f'<path d="M{_num(xs[0])} {_num(base)} L{pts} L{_num(xs[-1])} {_num(base)} Z" '
                         f'fill="{s["color"]}" fill-opacity="{0.25 * opac:.2f}" stroke="none"/>')
            o.append(f'<path d="M{pts}" stroke="{s["color"]}" stroke-width="{width}" stroke-opacity="{opac}"/>')
    o.append("</g>")

    # --- Lineale
    for r in rulers:
        x = float(sx(r["x"]))
        if px <= x <= px + pw:
            o.append(f'<line x1="{_num(x)}" y1="{py}" x2="{_num(x)}" y2="{py + ph}" stroke="{r["color"]}" '
                     f'stroke-width="2"/>')
            o.append(f'<text x="{_num(x + 4)}" y="{py + 14}" fill="{r["color"]}" font-weight="bold">'
                     f'{escape(r["label"])}</text>')

    # --- Legende (oben links in der Fläche): Muster + "Name: Wert" in der Farbe der Kurve
    if legend:
        row_h = 20
        lw = 40 + max(len(e["text"]) for e in legend) * 7.2
        o.append(f'<rect x="{px + 8}" y="{py + 8}" width="{_num(lw + 8)}" height="{row_h * len(legend) + 8}" '
                 f'rx="4" fill="{th["legend_bg"]}" fill-opacity="0.7"/>')
        for k, e in enumerate(legend):
            y = py + 20 + k * row_h
            op = 0.4 if e.get("dim") else 1.0
            # Muster: bei allen Einträgen (auch BOOL) ein Linienstück; der BOOL-Verlauf folgt unten neben der Legende.
            o.append(f'<line x1="{px + 14}" y1="{y - 5}" x2="{px + 42}" y2="{y - 5}" stroke="{e["color"]}" '
                     f'stroke-width="2" stroke-opacity="{op}"/>')
            weight = "bold" if e.get("bold") else "normal"
            o.append(f'<text x="{px + 48}" y="{y}" fill="{e["color"]}" fill-opacity="{op}" '
                     f'font-weight="{weight}">{escape(e["text"])}</text>')
        # --- BOOL-Verläufe: je Eintrag in der Höhe seiner Legendenzeile eine Linie (Wert 0) bzw. ein nach oben gehender Streifen (Wert 1) über die
        # Diagrammbreite, rechts neben der Legende - wie eine Kurve über den dargestellten Zeitbereich.
        x_left = px + 8 + lw + 16
        o.append('<g clip-path="url(#plot)">')
        for k, e in enumerate(legend):
            strip = e.get("strip")
            if strip is None or len(strip) < 2 or e.get("dim"):
                continue
            base = py + 20 + k * row_h          # Grundlinie am unteren Rand der Legendenzeile
            n = len(strip)
            dx = pw / (n - 1)
            on = np.where(np.isfinite(strip), strip >= 0.5, False)
            hh = 13 if e.get("bold") else 10     # Streifenhöhe, nur nach oben
            i = 0
            while i < n:
                j = i
                while j + 1 < n and on[j + 1] == on[i]:
                    j += 1
                xa, xb = max(px + i * dx, x_left), px + min((j + 1) * dx, pw)
                if xb > xa:
                    if on[i]:
                        o.append(f'<rect x="{_num(xa)}" y="{_num(base - hh)}" width="{_num(xb - xa)}" '
                                 f'height="{hh}" fill="{e["color"]}"/>')
                    else:
                        o.append(f'<line x1="{_num(xa)}" y1="{_num(base)}" x2="{_num(xb)}" y2="{_num(base)}" '
                                 f'stroke="{e["color"]}" stroke-width="{3 if e.get("bold") else 2}"/>')
                i = j + 1
        o.append("</g>")
    o.append("</svg>")
    return "\n".join(o)
