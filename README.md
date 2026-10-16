# PLC Logger

**PLC Datenlogger** – liest zyklisch Werte aus Steuerungen vieler Hersteller, zeichnet sie als CSV und/oder in einer
Datenbank auf und zeigt sie als y-t-Diagramme an: in der Oberfläche (PyQt6, pyqtgraph), im Browser (Webserver) oder
ohne Oberfläche (Headless). Mit Trigger und Ereignisprotokoll, PID-Regler-Optimierung, Lesemodus für die Datenbank,
Sprachumschaltung (Deutsch/Englisch).

Steuerungen verschiedener Hersteller lassen sich in **einer** Aufzeichnung mischen. Eingebaute Treiber:

| Treiber | Steuerungen / Protokoll |
|---|---|
| `s7` | Siemens S7-300/400/1200/1500, PUT/GET (python-snap7) |
| `tia` | Siemens S7-1200/1500 symbolisch, auch optimierte Bausteine (s7commplus) |
| `clx` | Allen-Bradley ControlLogix, CompactLogix, Micro800 (libplctag, pycomm3) |
| `modbus` | Modbus TCP |
| `modbus_rtu` | Modbus RTU seriell, mehrere Geräte je Schnittstelle (pymodbus) |
| `opcua` | OPC UA – Beckhoff, B&R, Codesys, Siemens, Omron, Kepware … (asyncua) |
| `slmp` | Mitsubishi MELSEC iQ-R, iQ-F, Q, L (SLMP/MC-Protokoll) |
| `kvhostlink` | KEYENCE KV (Host Link) |
| `toyopuc` | JTEKT TOYOPUC (Computer Link) |
| `s5as511` | Siemens S5 über die PG-Schnittstelle (AS511) |

Weitere Treiber: eine Python-Datei im Ordner `treiber` des Datenordners genügt (Vorlage `plc_treiber/_vorlage.py`,
Kapitel „Treiber entwickeln“ der Anleitung).

## Start

```console
pip install -r requirements.txt     # nur die Bibliotheken der benötigten Treiber sind nötig
python plc_config.py                # Konfiguration
python plc_logger.py                # Logger  (--demo: ohne Steuerung)
```

Ausführliche Anleitung: [`bedienungsanleitung.rst`](bedienungsanleitung.rst).

## Bauen

* **Windows:** `build.bat` → `.exe`, Installer (Inno Setup 6) und portables ZIP.
* **Linux:** `build_appimage.sh` → AppImage für x86_64 bzw. arm64.
* **GitHub Actions:** *Actions › Windows* bzw. *Actions › AppImages › Run workflow*, oder ein Tag `v*`
  (dann zusätzlich als GitHub-Release).

Die früheren Einzelprogramme (S7, TIA und CLX Datenlogger) liegen im Branch
[`einzelanwendungen`](../../tree/einzelanwendungen).
