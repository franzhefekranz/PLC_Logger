# PLC Datenlogger – Lizenzen

**PLC Datenlogger** · Copyright (C) 2026 Michael Taxis

Dieses Programm ist freie Software: Sie können es unter den Bedingungen der GNU Lesser General Public License,
wie von der Free Software Foundation veröffentlicht, weitergeben und/oder verändern, entweder gemäß Version 3
der Lizenz oder (nach Ihrer Wahl) jeder späteren Version (`SPDX-License-Identifier: LGPL-3.0-or-later`).
Lizenztext: [LICENSE](LICENSE) (LGPL v3); die LGPL v3 baut auf der GPL v3 auf: [COPYING](COPYING).

Dieses Programm wird in der Hoffnung verbreitet, dass es nützlich ist, aber OHNE JEDE GEWÄHR; sogar ohne die
implizite Gewähr der MARKTREIFE oder der EIGNUNG FÜR EINEN BESTIMMTEN ZWECK.

## Mitgelieferte Drittkomponenten

Die Programmdateien (Installer, portables ZIP, AppImage) enthalten folgende Komponenten. Sie stehen unter ihren
eigenen Lizenzen; deren Lizenztexte liegen den Paketen bei (im Programmordner unter `_internal`, meist in den
`*.dist-info`-Ordnern). Angaben geprüft mit `importlib.metadata` (Stand der Build-Umgebung).

| Komponente | Lizenz | Verwendung |
|---|---|---|
| Qt 6 (über PySide6) | LGPL-3.0 | Oberfläche |
| PySide6-Essentials, shiboken6 | LGPL-3.0 (wahlweise GPL-2.0/GPL-3.0) | Qt-Bindung für Python |
| pyqtgraph | MIT | Diagramme |
| NumPy | BSD-3-Clause (Teile 0BSD, MIT, Zlib, CC0-1.0) | Rechnen mit Messreihen |
| Flask, Werkzeug, Jinja2, click, itsdangerous, MarkupSafe | BSD-3-Clause | Webserver |
| blinker | MIT | Webserver (Flask) |
| Chart.js (`web_static`) | MIT | Diagramme im Browser |
| python-snap7 (3.x, reines Python) | MIT | Treiber `s7` |
| s7commplus (inkl. HarpoS7-Portierung) | MIT | Treiber `tia` |
| pycomm3 | MIT | Treiber `clx` (Tag-Liste) |
| libplctag (`plctag.dll` bzw. `libplctag.so`) | MPL-2.0 oder LGPL-2.0 (nach Wahl) | Treiber `clx` |
| pymodbus | BSD-3-Clause | Treiber `modbus_rtu` |
| pyserial | BSD-3-Clause | serielle Schnittstelle |
| asyncua | LGPL-3.0-or-later | Treiber `opcua` |
| cryptography | Apache-2.0 oder BSD-3-Clause | OPC UA Security |
| cffi / pycparser | MIT-0 / BSD-3-Clause | für cryptography |
| anyio, aiosqlite, pytz, six | MIT | für asyncua |
| python-dateutil | Apache-2.0 oder BSD-3-Clause | für asyncua |
| sortedcontainers, tzdata | Apache-2.0 | für asyncua |
| typing_extensions | PSF-2.0 | für asyncua |
| idna | BSD-3-Clause | Netzwerk |
| PyMySQL | MIT | MariaDB/MySQL |
| psycopg, psycopg-binary | LGPL-3.0 | PostgreSQL/TimescaleDB |
| libpq, OpenSSL (in psycopg-binary) | PostgreSQL-Lizenz, Apache-2.0 | PostgreSQL-Verbindung |
| Python | PSF-2.0 | Laufzeit |
| PyInstaller-Bootloader | GPL-2.0-or-later mit Bootloader-Ausnahme | Start der Programmdateien |

### LGPL-Komponenten

Qt/PySide6, asyncua, psycopg und libplctag stehen unter der LGPL. Die Programme werden als Ordner („onedir“)
gebaut; die Bibliotheken liegen als eigene Dateien im Programmordner (`_internal`) und können durch eigene,
kompatible Fassungen ersetzt werden. Quelltext der Bibliotheken:

* Qt: <https://code.qt.io>
* PySide6: <https://code.qt.io/pyside/pyside-setup.git>
* asyncua: <https://github.com/FreeOpcUa/opcua-asyncio>
* psycopg: <https://github.com/psycopg/psycopg>
* libplctag: <https://github.com/libplctag/libplctag>

### PyInstaller

Der PyInstaller-Bootloader steht unter GPL-2.0-or-later mit einer ausdrücklichen Ausnahme, die die Weitergabe der
damit erzeugten Programme unter beliebiger Lizenz erlaubt (<https://pyinstaller.org/en/stable/license.html>).
Die Lizenz der Programmdateien wird dadurch nicht beeinflusst.

## Werkzeuge nur für den Build (nicht im Programm enthalten)

| Werkzeug | Lizenz | Verwendung |
|---|---|---|
| PyInstaller | GPL-2.0-or-later mit Bootloader-Ausnahme | Programmdateien erzeugen |
| Sphinx | BSD-2-Clause | Bedienungsanleitung (PDF) |
| rinohtype | AGPL-3.0 | nur zum Erzeugen des PDF; das PDF selbst unterliegt nicht der AGPL |
| docutils | Public Domain / BSD-2-Clause | Bedienungsanleitung (HTML) |
| DejaVu-Schriften | freie Lizenz (Bitstream Vera/DejaVu) | im PDF eingebettet |
| Inno Setup | eigene freie Lizenz | Installer |
