# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Gemeinsame Definitionen des Treibers „tia“ (Siemens S7-1200/1500 symbolisch über S7CommPlus).

Stellt den aus dem TIA-Datenlogger übernommenen Modulen (tia_io, tia_taglist, tia_browser) die Namen bereit, die
dort aus tia_common kamen."""
from plc_common import BASE_DIR, Plc  # noqa: F401  (Weitergabe an tia_io/tia_taglist)
from plc_i18n import N_

TYPES = {
    "BOOL": 1, "BYTE": 1, "WORD": 2, "DWORD": 4, "LWORD": 8,
    "SINT": 1, "INT": 2, "DINT": 4, "LINT": 8,
    "USINT": 1, "UINT": 2, "UDINT": 4, "ULINT": 8,
    "REAL": 4, "LREAL": 8,
    "TIME": 4, "LTIME": 8, "S5TIME": 2, "CHAR": 1, "WCHAR": 2,
}
BLOCK_TYPES = list(TYPES)
TLS_MODES = {"auto": N_("Automatisch"), "aus": N_("Aus"), "an": N_("An (TLS erzwingen)")}
ROLES = {"hmi": N_("HMI (Standard)"), "es": N_("Engineering"), "pg": N_("PG")}


def check_tag_name(tag: str) -> bool:
    """True, wenn der Variablenname formal brauchbar ist: nicht leer, ohne Steuerzeichen und ';', Klammern
    ausgeglichen. TIA-Namen dürfen fast alle Zeichen enthalten; ob es die Variable gibt, prüft erst die Steuerung."""
    if not tag or tag != tag.strip() or ";" in tag or any(ord(ch) < 32 for ch in tag):
        return False
    depth = 0
    for ch in tag:
        depth += 1 if ch == "[" else -1 if ch == "]" else 0
        if depth < 0:
            return False
    return depth == 0 and not tag.startswith(".") and not tag.endswith(".") and ".." not in tag
