# PLC Logger

**PLC Datenlogger** – liest zyklisch Werte aus Steuerungen vieler Hersteller, zeichnet sie als CSV und/oder in einer
Datenbank (SQLite, MariaDB, TimescaleDB, QuestDB, InfluxDB 3, VictoriaMetrics) auf und zeigt sie als y-t-Diagramme an: in der Oberfläche (PySide6, pyqtgraph), im Browser (Webserver) oder
ohne Oberfläche (Headless). Mit Trigger und Ereignisprotokoll (Marken an der Zeitachse), Aufzeichnung per Trigger
mit Vor- und Nachlauf, PID-Regler-Optimierung, XY-Diagramm und FFT, PDF-Berichten je Schicht/Tag/Woche/Monat,
Lesemodus für die Datenbank, Webserver mit HTTPS und Anmeldung, Sprachumschaltung (Deutsch/Englisch).

Steuerungen verschiedener Hersteller lassen sich in **einer** Aufzeichnung mischen. Eingebaute Treiber:

| Treiber | Steuerungen / Protokoll |
|---|---|
| `s7` | Siemens S7-300/400/1200/1500, PUT/GET (python-snap7) |
| `tia` | Siemens S7-1200/1500 symbolisch, auch optimierte Bausteine (s7commplus) |
| `logo` | Siemens LOGO! 0BA7/0BA8 (python-snap7) |
| `clx` | Allen-Bradley ControlLogix, CompactLogix, Micro800 (libplctag, pycomm3) |
| `pccc` | Allen-Bradley MicroLogix 1100/1400, SLC 500 (pycomm3) |
| `modbus` | Modbus TCP |
| `modbus_rtu` | Modbus RTU seriell, mehrere Geräte je Schnittstelle (pymodbus) |
| `opcua` | OPC UA – Beckhoff, B&R, Codesys, Siemens, Omron, Kepware … (asyncua), zyklisch oder Subscription |
| `ads` | Beckhoff TwinCAT 2/3 über ADS, mit Symbolauswahl |
| `slmp` | Mitsubishi MELSEC iQ-R, iQ-F, Q, L (SLMP/MC-Protokoll) |
| `fins` | Omron CJ, CS, CP, NJ/NX (FINS/TCP, FINS/UDP) |
| `kvhostlink` | KEYENCE KV (Host Link) |
| `toyopuc` | JTEKT TOYOPUC (Computer Link) |
| `s5as511` | Siemens S5 über die PG-Schnittstelle (AS511) |

Weitere Treiber: eine Python-Datei im Ordner `treiber` des Datenordners genügt (Vorlage `src/plc_treiber/_vorlage.py`,
Kapitel „Treiber entwickeln“ der Anleitung).

## Ordner

| Ordner | Inhalt |
|---|---|
| `src/` | Programmdateien (`plc_*.py`) und das Treiberpaket `plc_treiber/` |
| `doc/` | Bedienungsanleitung (`bedienungsanleitung.rst`) und ihre Bilder (`images/`) |
| `sprachen/` | Sprachdateien |
| `tools/` | Hilfsprogramme (Sprachdateien, Wiki, Icon, INI-Umwandlung) |
| `docker/` | Testumgebung mit TimescaleDB, QuestDB, InfluxDB 3, VictoriaMetrics und Grafana |

Im Projektordner liegen außerdem Icon, Logo, `plctag.dll` und die Build-Skripte. Beim Start aus dem Quelltext
ist der Projektordner der Datenordner (Konfiguration, Aufzeichnungen, Logdatei).

## Start

```console
pip install -r requirements.txt     # nur die Bibliotheken der benötigten Treiber sind nötig
python src/plc_config.py            # Konfiguration
python src/plc_logger.py            # Logger  (--demo: ohne Steuerung)
```

Ausführliche Anleitung: im [Wiki](../../wiki) (wird automatisch aus [`doc/bedienungsanleitung.rst`](doc/bedienungsanleitung.rst) erzeugt).

## Bauen

* **Windows:** `build.bat` → `.exe`, Installer (Inno Setup 7 oder 6) und portables ZIP.
* **Linux:** `build_appimage.sh` → AppImage für x86_64 bzw. arm64.
* **Anleitung als PDF:** `pip install -r doc/requirements.txt`, dann `python tools/build_doc.py`
  → `dist/PLC_Datenlogger_Bedienungsanleitung_<Version>.pdf` (Sphinx mit rinohtype, kein LaTeX nötig).
* **GitHub Actions:** *Actions › Windows* bzw. *Actions › AppImages › Run workflow*, oder ein Tag `v*`
  (dann zusätzlich als GitHub-Release).

Die früheren Einzelprogramme (S7, TIA und CLX Datenlogger) liegen im Branch
[`einzelanwendungen`](../../tree/einzelanwendungen).

## Lizenz

Copyright (C) 2026 Michael Taxis. Der PLC Datenlogger steht unter der
[GNU Lesser General Public License v3.0 oder später](LICENSE) (`LGPL-3.0-or-later`; die LGPL v3 baut auf der
[GPL v3](COPYING) auf). Die Lizenzen der mitgelieferten Komponenten (u. a. Qt/PySide6, asyncua und psycopg unter
LGPL-3.0, libplctag unter MPL-2.0/LGPL-2.0, die übrigen unter MIT/BSD/Apache) stehen in
[`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).
