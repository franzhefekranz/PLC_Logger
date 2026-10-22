# Hinweise für die Arbeit am PLC Datenlogger

* Sprache im Projekt: Deutsch (Code-Kommentare, Commit-Nachrichten, Anleitung). Oberflächentexte mit `tr("…")`;
  neue Texte in `sprachen/en.txt` übersetzen (`python tools/extract_tr.py plc .`).
* Prüfen: `ruff check --select F --select E9 src tools tests` und `python -m pytest tests` (GUI-Tests brauchen PySide6,
  `QT_QPA_PLATFORM=offscreen`). Der Workflow *Tests* läuft bei jedem Push (Linux und Windows); neue Fenster/Dialoge in
  `tests/test_gui.py` aufnehmen.

## Versionierung

* Einzige Quelle der Versionsnummer: `APP_VERSION` in `src/plc_common.py` (SemVer `HAUPT.NEBEN.FEHLER`).
  Build-Skripte, Installer, PDF-Anleitung und Workflows lesen sie von dort – nirgends sonst eine Nummer eintragen.
* Jede nennenswerte Änderung (neue Funktion, Treiber, Fehlerbehebung, inkompatible Änderung) im selben Commit unter
  `## [Unveröffentlicht]` in `CHANGELOG.md` eintragen (Gruppen: Inkompatibel, Neu, Geändert, Behoben, Build).
* Neue Version: `python tools/bump_version.py haupt|neben|fehler [--tag]`. Ein Tag `vX.Y.Z` (push) startet die
  Release-Workflows; sie brechen ab, wenn der Tag nicht zu `APP_VERSION` passt. Tags nur nach Rücksprache pushen.

## Anleitung

* `doc/bedienungsanleitung.rst` (deutsch) und `doc/user_manual.rst` (englisch) haben dieselbe Gliederung
  (gleiche Überschriften in gleicher Reihenfolge, gleiche Sprungmarken): die Kontexthilfe (F1) der englischen Fassung
  ordnet Abschnitte über ihre Position zu. Änderungen immer in beiden Dateien vornehmen.
