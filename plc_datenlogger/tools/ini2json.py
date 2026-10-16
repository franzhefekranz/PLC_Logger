"""Ältere INI-Konfigurationen einmalig in das JSON-Format umwandeln.

    python tools/ini2json.py anlage.ini [weitere.ini …]       -> anlage.json (neben der INI-Datei)
    python tools/ini2json.py anlage.ini -o neu.json             -> anderer Zielname (nur bei einer Datei)

Die INI-Dateien bleiben unverändert. Dasselbe kann das Konfigurationsprogramm (Datei › INI-Datei umwandeln …).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from plc_common import convert_ini  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="INI-Konfiguration in JSON umwandeln")
    ap.add_argument("ini", nargs="+", help="INI-Datei(en)")
    ap.add_argument("-o", "--output", help="Zieldatei (nur bei einer INI-Datei)")
    ap.add_argument("-f", "--force", action="store_true", help="vorhandene JSON-Datei überschreiben")
    a = ap.parse_args()
    if a.output and len(a.ini) > 1:
        ap.error("-o geht nur mit einer INI-Datei")
    rc = 0
    for ini in a.ini:
        target = a.output or os.path.splitext(ini)[0] + ".json"
        if os.path.exists(target) and not a.force:
            print(f"übersprungen (existiert, -f zum Überschreiben): {target}")
            continue
        try:
            print(f"{ini} -> {convert_ini(ini, target)}")
        except Exception as e:
            print(f"FEHLER {ini}: {e}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
