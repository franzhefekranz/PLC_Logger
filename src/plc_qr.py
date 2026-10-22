# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""QR-Code ohne Zusatzbibliothek (für die Adresse der Webseite auf Smartphone/Tablet).

encode(text) -> Matrix (Liste von Zeilen mit True = dunkles Modul). Byte-Modus, Fehlerkorrektur M, Version 1 … 10
(bis 213 Byte – genug für eine Adresse mit Zugriffscode). Aufbau nach ISO/IEC 18004: Datenbits, Reed-Solomon-Prüfwerte,
Funktionsmuster, die beste der acht Masken, Format- und Versionsinformation.
"""

# Version -> (Datenwörter je Block, Anzahl Blöcke in Gruppe 1, in Gruppe 2 (je ein Wort mehr), Prüfwörter je Block)
_BLOCKS_M = {1: (16, 1, 0, 10), 2: (28, 1, 0, 16), 3: (44, 1, 0, 26), 4: (32, 2, 0, 18), 5: (43, 2, 0, 24),
             6: (27, 4, 0, 16), 7: (31, 4, 0, 18), 8: (38, 2, 2, 22), 9: (36, 3, 2, 22), 10: (43, 4, 1, 26)}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42],
          9: [6, 26, 46], 10: [6, 28, 50]}
_ECL_M = 0                                  # Formatbits der Stufe M


def _data_words(version):
    """Anzahl der Datenwörter (Bytes) einer Version bei Fehlerkorrektur M."""
    k, g1, g2, _ec = _BLOCKS_M[version]
    return k * g1 + (k + 1) * g2


# ---- Reed-Solomon über GF(256), Polynom 0x11D ----------------------------------------------------------------------
_EXP, _LOG = [0] * 512, [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gf_mul(a, b):
    """Multiplikation im Galois-Feld GF(256) über die Logarithmentafeln (Grundlage von Reed-Solomon)."""
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(n):
    """Generatorpolynom für n Prüfwörter: (x − α⁰)(x − α¹)…(x − αⁿ⁻¹)."""
    g = [1]
    for i in range(n):
        g = [a ^ _gf_mul(b, _EXP[i]) for a, b in zip(g + [0], [0] + g)]
    return g                                  # höchster Koeffizient zuerst


def _rs_remainder(data, n):
    """Reed-Solomon-Prüfwörter: Rest der Polynomdivision der Daten durch das Generatorpolynom."""
    gen = _rs_generator(n)
    rem = [0] * n
    for d in data:
        factor = d ^ rem[0]
        rem = rem[1:] + [0]
        for i in range(n):
            rem[i] ^= _gf_mul(gen[i + 1], factor)
    return rem


# ---- Datenbits --------------------------------------------------------------------------------------------------
def _codewords(data: bytes, version):
    bits = []

    def put(value, n):
        """``value`` als ``n`` Bits (höchstwertiges zuerst) an die Bitfolge hängen."""
        bits.extend((value >> (n - 1 - i)) & 1 for i in range(n))
    put(0b0100, 4)                            # Byte-Modus
    put(len(data), 8 if version < 10 else 16)
    for b in data:
        put(b, 8)
    cap = _data_words(version) * 8
    put(0, min(4, cap - len(bits)))           # Abschluss
    while len(bits) % 8:
        bits.append(0)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = (0xEC, 0x11)
    while len(words) < cap // 8:
        words.append(pad[(len(words) - len(bits) // 8) % 2])
    # in Blöcke teilen, Prüfwerte anhängen, verschränken
    k, g1, g2, ec = _BLOCKS_M[version]
    blocks, pos = [], 0
    for size in [k] * g1 + [k + 1] * g2:
        blocks.append(words[pos:pos + size])
        pos += size
    ecs = [_rs_remainder(b, ec) for b in blocks]
    out = []
    for i in range(k + 1):
        for b in blocks:
            if i < len(b):
                out.append(b[i])
    for i in range(ec):
        for e in ecs:
            out.append(e[i])
    return out


# ---- Matrix -----------------------------------------------------------------------------------------------------
def _bch(value, poly, bits_poly):
    v = value << (bits_poly - 1)
    for i in range(v.bit_length() - bits_poly, -1, -1):
        if v >> (i + bits_poly - 1) & 1:
            v ^= poly << i
    return v


def _format_bits(mask):
    """15 Formatbits: Fehlerkorrekturstufe und Maske, BCH-gesichert und mit dem Muster 0x5412 verknüpft."""
    data = (_ECL_M << 3) | mask
    return ((data << 10) | _bch(data, 0x537, 11)) ^ 0x5412


def _version_bits(version):
    """18 Versionsbits (ab Version 7): Versionsnummer mit BCH-Prüfteil."""
    return (version << 12) | _bch(version, 0x1F25, 13)


class _Matrix:
    """Die Modulmatrix eines QR-Codes: ``m`` = Farbe der Module, ``fn`` = Funktionsmodul (nicht maskieren, keine Daten).
    """
    def __init__(self, version):
        """Leere Matrix der Größe 17 + 4·Version."""
        self.v = version
        self.n = 17 + 4 * version
        self.m = [[False] * self.n for _ in range(self.n)]
        self.fn = [[False] * self.n for _ in range(self.n)]       # Funktionsmodul (nicht maskieren)

    def set(self, x, y, dark, fn=True):
        """Modul (x, y) setzen und als Funktionsmodul markieren."""
        self.m[y][x] = dark
        if fn:
            self.fn[y][x] = True

    def functions(self):
        """Funktionsmuster zeichnen: Taktlinien, drei Suchmuster, Ausrichtungsmuster, Platz für Format- und
        Versionsbits.
        """
        n = self.n
        for i in range(n):                                       # Taktlinien
            self.set(6, i, i % 2 == 0)
            self.set(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):          # Suchmuster mit Rand
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        d = max(abs(dx), abs(dy))
                        self.set(x, y, d not in (2, 4))
        pos = _ALIGN[self.v]                                     # Ausrichtungsmuster
        for i, a in enumerate(pos):
            for j, b in enumerate(pos):
                if (i == 0 and j == 0) or (i == 0 and j == len(pos) - 1) or (i == len(pos) - 1 and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set(a + dx, b + dy, max(abs(dx), abs(dy)) != 1)
        self.format(0)                                           # Platz reservieren
        if self.v >= 7:
            bits = _version_bits(self.v)
            for i in range(18):
                bit = (bits >> i) & 1 == 1
                a, b = n - 11 + i % 3, i // 3
                self.set(a, b, bit)
                self.set(b, a, bit)

    def format(self, mask):
        """Formatbits für ``mask`` an beide vorgesehenen Stellen schreiben (plus das immer dunkle Modul)."""
        n, bits = self.n, _format_bits(mask)
        for i in range(6):
            self.set(8, i, (bits >> i) & 1 == 1)
        self.set(8, 7, (bits >> 6) & 1 == 1)
        self.set(8, 8, (bits >> 7) & 1 == 1)
        self.set(7, 8, (bits >> 8) & 1 == 1)
        for i in range(9, 15):
            self.set(14 - i, 8, (bits >> i) & 1 == 1)
        for i in range(8):
            self.set(n - 1 - i, 8, (bits >> i) & 1 == 1)
        for i in range(8, 15):
            self.set(8, n - 15 + i, (bits >> i) & 1 == 1)
        self.set(8, n - 8, True)                                 # immer dunkel

    def place(self, words):
        """Datenbits im Zickzack einsetzen: in Doppelspalten von rechts nach links, abwechselnd auf- und abwärts,
        Funktionsmodule überspringen (Spalte 6 ist die Taktlinie).
        """
        n, i = self.n, 0
        bits = [(w >> (7 - b)) & 1 for w in words for b in range(8)]
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = n - 1 - vert if upward else vert
                    if not self.fn[y][x] and i < len(bits):
                        self.m[y][x] = bits[i] == 1
                        i += 1
            right -= 2

    def apply_mask(self, mask):
        """Maske ``mask`` (0 … 7) auf alle Datenmodule anwenden (Funktionsmodule bleiben)."""
        f = (lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
             lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
             lambda x, y: x * y % 2 + x * y % 3 == 0, lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
             lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0)[mask]
        for y in range(self.n):
            for x in range(self.n):
                if not self.fn[y][x] and f(x, y):
                    self.m[y][x] = not self.m[y][x]

    def penalty(self):
        """Strafpunkte nach ISO/IEC 18004: lange gleichfarbige Folgen, 2×2-Blöcke, suchmusterähnliche Folgen und
        unausgeglichenes Hell/Dunkel. Die Maske mit den wenigsten Punkten wird verwendet.
        """
        m, n, p = self.m, self.n, 0
        for line in list(m) + [list(c) for c in zip(*m)]:
            run, prev = 0, None
            for v in line:
                if v == prev:
                    run += 1
                else:
                    if run >= 5:
                        p += run - 2
                    run, prev = 1, v
            if run >= 5:
                p += run - 2
            s = "".join("1" if v else "0" for v in line)
            p += 40 * (s.count("10111010000") + s.count("00001011101"))
        for y in range(n - 1):
            for x in range(n - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    p += 3
        dark = sum(v for row in m for v in row)
        p += abs(dark * 20 - n * n * 10) // (n * n) * 10
        return p


def encode(text: str):
    """Text -> QR-Matrix (Liste von Listen, True = dunkel). ValueError, wenn der Text zu lang ist."""
    data = text.encode("utf-8")
    for version in range(1, 11):
        head = 4 + (8 if version < 10 else 16)
        if head + 8 * len(data) <= _data_words(version) * 8:
            break
    else:
        raise ValueError("Text zu lang für den QR-Code")
    words = _codewords(data, version)
    best, best_p = None, None
    for mask in range(8):
        q = _Matrix(version)
        q.functions()
        q.place(words)
        q.apply_mask(mask)
        q.format(mask)
        p = q.penalty()
        if best_p is None or p < best_p:
            best, best_p = q, p
    return best.m


def to_svg(matrix, scale=6, border=4, dark="#000", light="#fff"):
    """Matrix als SVG-Bild (``scale`` Pixel je Modul, ``border`` Module Ruhezone)."""
    n = len(matrix)
    size = (n + 2 * border) * scale
    rects = "".join(f'<rect x="{(x + border) * scale}" y="{(y + border) * scale}" width="{scale}" height="{scale}"/>'
                    for y, row in enumerate(matrix) for x, v in enumerate(row) if v)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
            f'<rect width="{size}" height="{size}" fill="{light}"/><g fill="{dark}">{rects}</g></svg>')
