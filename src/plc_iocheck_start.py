# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""IO-Check als eigenes Programm (Windows: PLCIOCheck.exe).

    plc_iocheck_start.py [Prüfstand.iocheck.json | Konfiguration.json] [--demo]

Ohne Datei: Startbild mit den zuletzt benutzten Prüfständen und Konfigurationen. Gleichwertig zu
``plc_logger.py --iocheck``; die eigene Programmdatei gibt es, damit der IO-Check im Startmenü steht und sich ohne den
Logger installieren bzw. starten lässt (z. B. auf dem Laptop für die Inbetriebnahme).
"""
import sys


def main(argv=None):
    """Befehlszeile auswerten und den IO-Check starten -> Exit-Code."""
    args = list(sys.argv[1:] if argv is None else argv)
    demo = "--demo" in args
    files = [a for a in args if not a.startswith("--")]
    from plc_iocheck_dialog import run_iocheck
    return run_iocheck(files[0] if files else None, demo=demo)


if __name__ == "__main__":
    sys.exit(main())
