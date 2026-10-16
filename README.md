# PLC Logger

Datenlogger für speicherprogrammierbare Steuerungen in Python (PyQt6, pyqtgraph): zyklisches Lesen,
Aufzeichnung in CSV/Datenbank, y-t-Diagramme online und offline, Webserver, Headless-Betrieb, Trigger und
Ereignisprotokoll, PID-Regler-Optimierung, Sprachumschaltung (Deutsch/Englisch).

| Programm | Ordner | Steuerungen |
|---|---|---|
| **PLC Datenlogger** | [`plc_datenlogger/`](plc_datenlogger) | alle Treiber in einer Anwendung, mischbar, erweiterbar um eigene Treiber |
| S7 Datenlogger | `/` (oberster Ordner, `s7_*.py`) | Siemens S7 über PUT/GET (python-snap7) |
| TIA Datenlogger | [`tia_datenlogger/`](tia_datenlogger) | Siemens S7-1200/1500 symbolisch (S7CommPlus) |
| CLX Datenlogger | [`clx_datenlogger/`](clx_datenlogger) | Allen-Bradley ControlLogix/CompactLogix/Micro800 (libplctag) |

Treiber des PLC Datenloggers: `s7`, `tia`, `clx`, `modbus` (Modbus TCP) – weitere als Python-Datei im Ordner
`treiber` (Vorlage: `plc_datenlogger/plc_treiber/_vorlage.py`).

## Start

```console
cd plc_datenlogger
pip install -r requirements.txt
python plc_config.py      # Konfiguration
python plc_logger.py      # Logger  (--demo: ohne Steuerung)
```

Die Einzelprogramme entsprechend mit `s7_*.py`, `tia_*.py`, `clx_*.py` im jeweiligen Ordner.
Ausführliche Anleitung: `bedienungsanleitung.rst` in jedem Programmordner.

## Bauen

* **Windows:** `build.bat` im Programmordner → `.exe`, Installer (Inno Setup 6) und portables ZIP.
* **Linux:** `build_appimage.sh` → AppImage für x86_64 bzw. arm64.
* **GitHub Actions:** *Actions › AppImages › Run workflow* oder ein Tag `v*` baut die AppImages aller vier
  Programme für x86_64 und arm64.
