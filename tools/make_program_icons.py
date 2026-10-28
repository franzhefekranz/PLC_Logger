# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Programm-Icons zeichnen: das „Ti“ aus dem Firmenlogo mit einem farbigen Abzeichen je Programm.

Damit lassen sich Logger, Konfiguration, IO-Check, Ereignisprotokoll und Headless-Betrieb in Taskleiste, Startmenü und
Dock unterscheiden. Ergebnis im Ordner ``icons``: je Programm ``<name>.ico`` (16 bis 256 Pixel) und ``<name>.png``
(256 Pixel), dazu ``logger_1024.png`` (macOS); das Übersichtsbild der Anleitung entsteht als
``doc/images/programm_icons.png`` (englisch: ``doc/images/en/…``). ``app.ico`` im Projektordner wird zum
Logger-Icon (Rückfall für alles, was kein eigenes Icon hat). Die Dateien liegen im Repository – das Skript ist nur
nötig, wenn sich die Gestaltung ändert.

    python tools/make_program_icons.py      (braucht Pillow)
"""
import math
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "icons")
N = 1024                                  # Zeichengröße; verkleinert wird mit Lanczos
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]

DARK, LIGHT = (56, 56, 56, 255), (200, 200, 200, 255)          # Farben des Logos

# Name -> (Farbe des Abzeichens, Symbol, Beschreibung)
PROGRAMS = {
    "logger":        ((30, 136, 229), "kurve", "Logger"),
    "konfiguration": ((245, 124, 0), "zahnrad", "Konfiguration"),
    "iocheck":       ((46, 160, 67), "haken", "IO-Check"),
    "ereignisse":    ((211, 47, 47), "liste", "Ereignisprotokoll"),
    "headless":      ((84, 110, 122), "aufnahme", "Headless"),
}


def _u(v):
    """Logo-Einheiten (0 … 100) in Pixel der Zeichenfläche (mit 3 % Rand)."""
    return N * 0.03 + v * N * 0.94 / 100


def draw_ti(d):
    """Das „Ti“ wie im Logo: dunkles T mit rundem i-Punkt im Balken, helles i rechts neben dem T-Stamm."""
    d.rounded_rectangle([_u(0), _u(0), _u(100), _u(33)], radius=_u(6) - _u(0), fill=DARK)    # T-Balken
    d.rectangle([_u(33), _u(30), _u(66), _u(100)], fill=DARK)                                 # T-Stamm
    cx, cy, r = _u(78.5), _u(16.5), _u(17.5) - _u(0)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=LIGHT)                                    # i-Punkt
    d.rectangle([_u(66), _u(37), _u(100), _u(100)], fill=LIGHT)                               # i-Stamm


def draw_badge(d, color, symbol, small=False):
    """Rundes Abzeichen unten rechts mit weißem Rand und weißem Symbol (``small``: größer, für 16 bis 32 Pixel)."""
    r = N * (0.35 if small else 0.29)
    cx, cy = N - r, N - r
    ring = N * (0.05 if small else 0.035)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 255))
    d.ellipse([cx - r + ring, cy - r + ring, cx + r - ring, cy + r - ring], fill=color + (255,))
    w = (255, 255, 255, 255)
    s = r - ring                                    # Radius der Farbfläche
    lw = max(2, int(s * (0.24 if small else 0.17)))  # Strichstärke der Symbole
    if symbol == "kurve":                           # Messkurve
        pts = [(cx - s * 0.62 + s * 1.24 * k / 30, cy - s * 0.38 * math.sin(k / 30 * 2 * math.pi * 1.25))
               for k in range(31)]
        d.line(pts, fill=w, width=lw, joint="curve")
        for p in (pts[0], pts[-1]):
            d.ellipse([p[0] - lw / 2, p[1] - lw / 2, p[0] + lw / 2, p[1] + lw / 2], fill=w)
    elif symbol == "zahnrad":                       # Zahnrad
        teeth, ro, ri = 8, s * 0.66, s * 0.48
        poly = []
        for k in range(teeth * 4):
            a = 2 * math.pi * k / (teeth * 4)
            rr = ro if k % 4 in (1, 2) else ri
            poly.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        d.polygon(poly, fill=w)
        h = s * 0.2
        d.ellipse([cx - h, cy - h, cx + h, cy + h], fill=color + (255,))
    elif symbol == "haken":                         # Prüfhaken
        pts = [(cx - s * 0.48, cy + s * 0.02), (cx - s * 0.12, cy + s * 0.38), (cx + s * 0.52, cy - s * 0.36)]
        d.line(pts, fill=w, width=int(lw * 1.3), joint="curve")
        for p in (pts[0], pts[-1]):
            q = lw * 0.65
            d.ellipse([p[0] - q, p[1] - q, p[0] + q, p[1] + q], fill=w)
    elif symbol == "liste":                         # Protokoll: drei Zeilen mit Punkt
        for k in (-1, 0, 1):
            y = cy + k * s * 0.36
            q = lw * 0.7
            d.ellipse([cx - s * 0.52 - q, y - q, cx - s * 0.52 + q, y + q], fill=w)
            d.line([(cx - s * 0.22, y), (cx + s * 0.55, y)], fill=w, width=lw)
    elif symbol == "aufnahme":                      # Aufnahme ohne Bildschirm: gefüllter Kreis im Ring
        q = s * 0.55
        d.ellipse([cx - q, cy - q, cx + q, cy + q], outline=w, width=lw)
        q = s * 0.28
        d.ellipse([cx - q, cy - q, cx + q, cy + q], fill=w)


def render(name, small=False):
    """Icon eines Programms in der Zeichengröße (``small``: Fassung für 16 bis 32 Pixel)."""
    color, symbol, _ = PROGRAMS[name]
    im = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    draw_ti(d)
    draw_badge(d, color, symbol, small)
    return im


def sized(name, size, cache={}):
    """Icon in ``size`` Pixeln; bis 32 Pixel aus der Fassung mit größerem Abzeichen."""
    small = size <= 32
    if (name, small) not in cache:
        cache[(name, small)] = render(name, small)
    return cache[(name, small)].resize((size, size), Image.LANCZOS)


def _font(size):
    for f in ("DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "arial.ttf",
              "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


def overview(names, path):
    """Übersichtsbild: je Programm das Icon groß, darunter in Taskleistengrößen, darunter der Name."""
    cell, big = 260, 192
    sheet = Image.new("RGBA", (len(PROGRAMS) * cell, big + 120), (255, 255, 255, 255))
    d = ImageDraw.Draw(sheet)
    font = _font(22)
    for i, name in enumerate(PROGRAMS):
        x0 = i * cell
        sheet.alpha_composite(sized(name, big), (x0 + (cell - big) // 2, 8))
        sizes = (48, 32, 24, 16)
        width = sum(sizes) + 14 * (len(sizes) - 1)
        x = x0 + (cell - width) // 2
        for sz in sizes:
            sheet.alpha_composite(sized(name, sz), (x, big + 18 + (48 - sz)))
            x += sz + 14
        w = d.textlength(names[i], font=font)
        d.text((x0 + (cell - w) / 2, big + 78), names[i], fill=(30, 30, 30, 255), font=font)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sheet.convert("RGB").save(path, optimize=True)


def main():
    os.makedirs(OUT, exist_ok=True)
    for name in PROGRAMS:
        sized(name, 256).save(os.path.join(OUT, name + ".png"))
        if name == "logger":                                       # macOS-Programmsymbol (bis 1024 Pixel)
            sized(name, 1024).save(os.path.join(OUT, "logger_1024.png"))
        frames = [sized(name, s) for s in ICO_SIZES]
        targets = [os.path.join(OUT, name + ".ico")] + ([os.path.join(ROOT, "app.ico")] if name == "logger" else [])
        for t in targets:
            # Pillow schreibt die Bilder einer ICO-Datei aus append_images, wenn ihre Größen in sizes stehen.
            frames[-1].save(t, format="ICO", sizes=[(s, s) for s in ICO_SIZES], append_images=frames[:-1])
    # Übersicht für die Anleitung: alle Icons in 256, 48, 32, 24 und 16 Pixeln mit Namen (deutsch, englisch).
    labels = {"de": ["Logger", "Konfiguration", "IO-Check", "Ereignisprotokoll", "Headless"],
              "en": ["Logger", "Configuration", "IO check", "Event log", "Headless"]}
    for lang, names in labels.items():
        folder = os.path.join(ROOT, "doc", "images", *([] if lang == "de" else [lang]))
        overview(names, os.path.join(folder, "programm_icons.png"))
    print("Icons erzeugt:", ", ".join(PROGRAMS), "->", OUT)


if __name__ == "__main__":
    main()
