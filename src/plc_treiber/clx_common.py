# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Gemeinsame Definitionen des Treibers „clx“ (Allen-Bradley Logix über EtherNet/IP).

Stellt den aus dem CLX-Datenlogger übernommenen Modulen (clx_io, clx_taglist, clx_browser) die Namen bereit, die
dort aus clx_common kamen."""
import re

from plc_common import BASE_DIR, Plc  # noqa: F401  (Weitergabe an clx_io/clx_taglist)
from plc_i18n import N_

# Logix-Datentypen: Größe in Bytes und struct-Format (Little Endian).
TYPES = {
    "BOOL": (1, "<B"), "SINT": (1, "<b"), "INT": (2, "<h"), "DINT": (4, "<i"), "LINT": (8, "<q"),
    "USINT": (1, "<B"), "UINT": (2, "<H"), "UDINT": (4, "<I"), "ULINT": (8, "<Q"),
    "REAL": (4, "<f"), "LREAL": (8, "<d"),
}
# BOOL-Arrays legt die Steuerung bitweise gepackt ab; sie lassen sich nicht als Block lesen.
BLOCK_TYPES = [t for t in TYPES if t != "BOOL"]
INT_TYPES = ("SINT", "INT", "DINT", "LINT", "USINT", "UINT", "UDINT", "ULINT")
CPUS = {"controllogix": N_("ControlLogix"), "compactlogix": N_("CompactLogix"), "micro800": N_("Micro800")}


def pycomm3_path(p) -> str:
    """Verbindungspfad für pycomm3 aus IP und CIP-Pfad: ``1,0`` -> ``192.168.1.10/1/0``; ohne Pfad nur die IP."""
    parts = [x.strip() for x in (p.pfad or "").split(",") if x.strip()]
    return "/".join([p.ip] + parts)


_TAG_RE = re.compile(r"^(Program:[A-Za-z_]\w*\.)?[A-Za-z_]\w*(\[\d+(,\d+){0,2}\])?"
                     r"(\.[A-Za-z_]\w*(\[\d+(,\d+){0,2}\])?)*(\.\d{1,2})?$")


def check_tag_name(tag: str) -> bool:
    """True, wenn der Tag-Name formal gültig ist (die Existenz prüft erst die Steuerung)."""
    return bool(_TAG_RE.match(tag or ""))
