# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Versionsnummer des PLC Datenloggers verwalten (einzige Quelle: APP_VERSION in src/plc_common.py).

    python tools/bump_version.py                     aktuelle Version anzeigen
    python tools/bump_version.py neben               3.0.0 -> 3.1.0  (haupt: 4.0.0, fehler: 3.0.1; auch major/minor/patch)
    python tools/bump_version.py 3.2.0               bestimmte Nummer setzen
    python tools/bump_version.py fehler --tag        zusätzlich Commit "Version x.y.z" und Tag vx.y.z anlegen
    python tools/bump_version.py neben --dry-run     nur anzeigen, was geändert würde

    python tools/bump_version.py --notes [VERSION]   Abschnitt der Version aus CHANGELOG.md ausgeben (Release-Text)
    python tools/bump_version.py --check-tag TAG     Fehler, wenn der Tag (z. B. v3.0.0) nicht zu APP_VERSION passt

Beim Erhöhen wird der Abschnitt "## [Unveröffentlicht]" in CHANGELOG.md zum Abschnitt der neuen Version (mit
Datum), darüber entsteht ein neuer, leerer Abschnitt "Unveröffentlicht"; die Verweise am Dateiende werden ergänzt.
Der Tag wird nur lokal angelegt – hochladen mit  git push && git push origin vX.Y.Z  (startet die Release-Workflows).
"""
import datetime
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMON = os.path.join(ROOT, "src", "plc_common.py")
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")
VERSION_RE = re.compile(r'^APP_VERSION = "(\d+)\.(\d+)\.(\d+)"$', re.M)
UNRELEASED = "## [Unveröffentlicht]"
STEPS = {"haupt": 0, "major": 0, "neben": 1, "minor": 1, "fehler": 2, "patch": 2, "bugfix": 2}


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def current_version():
    m = VERSION_RE.search(read(COMMON))
    if not m:
        sys.exit(f"FEHLER: APP_VERSION in {os.path.relpath(COMMON, ROOT)} nicht gefunden.")
    return tuple(int(x) for x in m.groups())


def fmt(v):
    return ".".join(str(x) for x in v)


def next_version(cur, arg):
    if arg.lower() in STEPS:
        i = STEPS[arg.lower()]
        return tuple(list(cur[:i]) + [cur[i] + 1] + [0] * (2 - i))
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", arg)
    if not m:
        sys.exit(f"FEHLER: '{arg}' ist weder haupt/neben/fehler noch eine Nummer wie 3.1.0.")
    new = tuple(int(x) for x in m.groups())
    if new <= cur:
        sys.exit(f"FEHLER: {fmt(new)} ist nicht größer als die aktuelle Version {fmt(cur)}.")
    return new


def section(text, version):
    """Text des Abschnitts '## [version]' (ohne Überschrift), sonst None."""
    m = re.search(r"^## \[" + re.escape(version) + r"\][^\n]*\n(.*?)(?=^## |^\[[^\]]+\]: |\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else None


def update_changelog(text, old, new, date):
    if UNRELEASED not in text:
        sys.exit(f"FEHLER: Abschnitt '{UNRELEASED}' fehlt in CHANGELOG.md.")
    if f"## [{new}]" in text:
        sys.exit(f"FEHLER: CHANGELOG.md enthält bereits einen Abschnitt [{new}].")
    pending = section(text, "Unveröffentlicht")
    text = text.replace(UNRELEASED + "\n", f"{UNRELEASED}\n\n## [{new}] – {date}\n", 1)
    text = re.sub(r"^\[Unveröffentlicht\]: .*$", f"[Unveröffentlicht]: ../../compare/v{new}...HEAD", text, count=1, flags=re.M)
    text = re.sub(r"^(\[Unveröffentlicht\]: .*\n)", rf"\1[{new}]: ../../releases/tag/v{new}\n", text, count=1, flags=re.M)
    return text, bool(pending)


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def main(argv):
    if "--notes" in argv:
        i = argv.index("--notes")
        version = argv[i + 1].lstrip("v") if len(argv) > i + 1 else fmt(current_version())
        notes = section(read(CHANGELOG), version)
        if notes is None:
            sys.exit(f"FEHLER: kein Abschnitt [{version}] in CHANGELOG.md.")
        print(notes or f"Version {version}")
        return 0
    if "--check-tag" in argv:
        tag = argv[argv.index("--check-tag") + 1]
        tag = tag.rsplit("/", 1)[-1]                          # auch refs/tags/v3.0.0
        version = fmt(current_version())
        if tag.lower() != "v" + version:                     # auch "V3.0.0" (Großbuchstabe beim Anlegen auf GitHub)
            sys.exit(f"FEHLER: Tag {tag} passt nicht zu APP_VERSION {version} (erwartet v{version}). "
                     f"Erst  python tools/bump_version.py {tag.lstrip('v')}  ausführen.")
        print(f"[OK] Tag {tag} = APP_VERSION {version}")
        return 0

    args = [a for a in argv if not a.startswith("--")]
    cur = current_version()
    if not args:
        print(fmt(cur))
        return 0
    new = next_version(cur, args[0])
    old_s, new_s = fmt(cur), fmt(new)
    date = datetime.date.today().isoformat()
    common = VERSION_RE.sub(f'APP_VERSION = "{new_s}"', read(COMMON), 1)
    changelog, has_notes = update_changelog(read(CHANGELOG), old_s, new_s, date)
    print(f"Version {old_s} -> {new_s} ({date})")
    if not has_notes:
        print("[HINWEIS] Der Abschnitt 'Unveröffentlicht' in CHANGELOG.md ist leer – bitte Änderungen nachtragen.")
    if "--dry-run" in argv:
        print("(--dry-run: nichts geändert)")
        return 0
    write(COMMON, common)
    write(CHANGELOG, changelog)
    print("[OK] src/plc_common.py und CHANGELOG.md aktualisiert")
    if "--tag" in argv:
        git("add", COMMON, CHANGELOG)
        git("commit", "-q", "-m", f"Version {new_s}")
        git("tag", "-a", f"v{new_s}", "-m", f"PLC Datenlogger {new_s}")
        print(f"[OK] Commit und Tag v{new_s} angelegt. Hochladen (startet die Release-Workflows):\n"
              f"     git push && git push origin v{new_s}")
    else:
        print(f"Weiter: Änderungen prüfen, committen und mit  git tag -a v{new_s} -m 'PLC Datenlogger {new_s}'  "
              f"markieren (oder gleich mit --tag).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
