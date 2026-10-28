# Änderungen

Alle nennenswerten Änderungen am PLC Datenlogger. Die Versionsnummer folgt
[Semantic Versioning](https://semver.org/lang/de/) (`HAUPT.NEBEN.FEHLER`):

* **HAUPT** – inkompatible Änderung: alte Konfigurationsdateien, Aufzeichnungen oder Aufrufe funktionieren nicht mehr
  ohne Umstellung.
* **NEBEN** – neue Funktionen oder Treiber, bestehende Konfigurationen laufen unverändert weiter.
* **FEHLER** – nur Fehlerbehebungen und kleine Verbesserungen.

Die Nummer steht an genau einer Stelle: `APP_VERSION` in `src/plc_common.py`. Build-Skripte, Installer, Anleitung
und Programm lesen sie von dort. Neue Version: `python tools/bump_version.py neben` (bzw. `haupt`, `fehler` oder
eine Nummer), siehe [Versionen und Releases](#versionen-und-releases).

## [Unveröffentlicht]

## [3.4.0] – 2026-10-28

### Neu

* **Netzwerk durchsuchen** (Konfigurationsprogramm, Reiter mit den Steuerungen): findet erreichbare Steuerungen im
  eigenen Netz oder einem angegebenen Bereich (EtherNet/IP-Rundruf, Ports von S7, Modbus, EtherNet/IP, OPC UA, ADS,
  FINS, SLMP, Keyence), liest bei S7-CPUs Baugruppe und Steckplatz bzw. bei EtherNet/IP-Geräten den Produktnamen und
  übernimmt die angehakten Geräte mit passendem Treiber als Steuerungen.

* **macOS (Vorschau, noch nicht auf einem Mac getestet)**: App „PLC Datenlogger“ als `.dmg` für Apple Silicon und Intel (ab macOS 12) mit Logger,
  Konfigurationsprogramm, IO-Check, Ereignis-Viewer, Anleitung, SPS-Vorlagen und libplctag; Menüleiste oben am
  Bildschirm. Ad hoc signiert (erster Start: Rechtsklick › Öffnen). Build: `build_macos.sh`, Workflow *macOS*; die
  Tests laufen jetzt auch auf macOS.

## [3.3.2] – 2026-10-27

### Behoben

* Linux (Wayland): Absturz beim Ziehen eines Diagramm- oder Wertefensters (Dock). Unter Wayland starten die Programme
  jetzt über XWayland (eigenes `QT_QPA_PLATFORM` gilt weiter, `PLC_WAYLAND=1` erzwingt Wayland); ohne XWayland lassen
  sich die Docks nicht mehr ziehen, die Anordnung geht über das Menü *Ansicht*.

## [3.3.1] – 2026-10-27

### Neu

* Vorlagen `Ringpuffer_S7-300_400_FB.scl` und `Ringpuffer_S7-1200_1500_FB.scl` (TIA Portal, FB nicht optimiert):
  Ringpuffer als Funktionsbaustein (Puffer im Instanz-DB, 20 Eingänge, Startadresse `DBX80.0`); mehrere Instanzen
  ergeben mehrere Ringpuffer.

### Behoben

* Konfigurationsprogramm: Absturz beim Start bzw. beim Aufbau des Variablenbaums („not enough values to unpack“),
  wenn ein Block Elemente in einem anderen Diagramm hatte und eine Achse oder ein Diagramm gewählt war.

## [3.3.0] – 2026-10-27

### Neu

* **Ringpuffer – zyklussynchrone Aufzeichnung** (Treiber `s7`, `tia`, `clx`): Die Steuerung schreibt je Zyklus bzw.
  Weckalarm einen Datensatz (Nummer, Zeit, Werte) in einen Ringpuffer, der Logger holt die Datensätze im Leseintervall
  ab – lückenlos, mit dem Zeitpunkt aus der Steuerung, z. B. 10 oder 50 ms Abtastung bei 250 ms Leseintervall.
  Blockeditor: neue Spalte *Ringpuffer* (Anzahl Datensätze), Test zeigt Zähler, Abstand und jüngste Werte; verlorene
  Datensätze und Neustarts der Steuerung werden gemeldet. Fertige Bausteine im Ordner `vorlagen` (S7-300/400 SCL,
  S7-1200/1500 SCL-Quelle für TIA Portal, ControlLogix Structured Text), erreichbar über *SPS-Vorlagen …*.
* **Prometheus als Datenbank**: Schreiben per Remote Write (Protobuf + Snappy ohne Zusatzbibliothek), Lesemodus über
  die HTTP-Schnittstelle (Rohdaten und Mittelwerte). Vom Server abgelehnte Werte (zu alt, nicht in zeitlicher
  Reihenfolge) werden gemeldet statt endlos wiederholt. Docker-Testumgebung um Prometheus mit Grafana-Datenquelle
  ergänzt.

### Build

* Linux: Zusätzlich zu den AppImages entstehen **Debian-Pakete** (`plc-datenlogger_<Version>_amd64.deb` für PCs,
  `_arm64.deb` für Raspberry Pi 4/5 mit 64-Bit-System). Installation mit `sudo apt install ./….deb`; Startmenü-Einträge
  für Logger, Konfiguration und IO-Check, Befehle `plc-datenlogger`, `plc-konfiguration`, `plc-iocheck`,
  `plc-ereignisse`. Die Pakete hängen auch am GitHub-Release.

## [3.2.1] – 2026-10-23

### Behoben

* Linux: Die Menüleiste fehlte im Fenster von Logger und Konfigurationsprogramm (auf Arbeitsoberflächen mit globalem
  Menü, z. B. KDE Plasma, landete sie in der oberen Leiste). Sie steht jetzt immer im Fenster.
* Linux: **Konfig-Editor** im Logger öffnete das Konfigurationsprogramm nicht. Es öffnet sich jetzt im selben Prozess
  als eigenes Fenster (Windows unverändert: `PLCKonfiguration.exe`).
* Linux (AppImage): Programme, die aus einem anderen heraus gestartet werden (Logger bzw. IO-Check aus dem
  Konfigurationsprogramm, Neustart nach Sprachwechsel), erben nicht mehr die Umgebung des laufenden Programms und
  starten dadurch zuverlässig. Bricht ein so gestartetes Programm gleich wieder ab, erscheint eine Meldung mit der
  Fehlerausgabe.

## [3.2.0] – 2026-10-22

### Neu

* **QR-Code** für die Adresse der Webseite: im IO-Check (*📱 Mobil …*) und im Logger (*Datei › Webserver-Adresse …*);
  mit der Kamera des Smartphones scannen statt tippen. Eigener QR-Encoder, keine Zusatzbibliothek.
* **Vom Ereignis zur Stelle im Diagramm:** Im Ereignis-Viewer *Im Diagramm zeigen* (Knopf oder Rechtsklick) zeigt den
  Zeitraum um das Ereignis im Logger (offline), Lineal 1 auf dem Beginn, Lineal 2 auf dem Ende. Liegen die Werte nicht
  mehr im Speicher, werden sie aus der Datenbank der Konfiguration geladen (falls eingestellt), sonst aus der passenden
  CSV-Datei bzw. dem Archiv.
* **Benachrichtigungen bei Ereignissen** (Konfiguration › Trigger & Ereignisse › *Benachrichtigungen …*): E-Mail
  (SMTP, STARTTLS/SSL), Microsoft Teams (Workflow-Webhook), Slack, allgemeiner JSON-Webhook, ntfy (Push aufs Handy) und
  Telegram. Filter nach Mindestpriorität und Triggernamen, wahlweise auch beim Gehen, Sperrzeit je Trigger gegen
  Meldungsfluten, Testnachricht. Gesendet wird im Hintergrund, auch im Betrieb ohne Oberfläche.
* **OPC-UA-Server im Logger** (Konfiguration › Webserver & Headless › *OPC UA …*): stellt alle gelesenen und
  berechneten Variablen, die Trigger-Zustände und den Verbindungsstatus je Steuerung lesend bereit – für Leitsystem,
  MES oder SCADA. Sicherheit ohne/Signieren/Verschlüsseln (selbstsigniertes Zertifikat), anonym und/oder Anmeldung mit
  den Benutzern des Webservers. Läuft während der Aufzeichnung, auch headless.
* **Prozessbild im Browser** (Webserver, Adresse `/prozess`; Logger: *Datei › Prozessbild im Browser*): Kacheln mit
  Zahlenwert, Zeigerinstrument, Balken, Zustandslampe, Kurzverlauf und Text, frei auf einem Raster angeordnet, mehrere
  Seiten, Warn- und Alarmgrenzen färben die Kachel. Bearbeitet wird direkt in der Webseite (verschieben, Größe,
  Eigenschaften; angemeldete Benutzer); das Layout steht in `<Konfiguration>.prozessbild.json`. Auf dem Smartphone
  untereinander.
* **IO-Check: Spalten der IO-Liste festlegen** (*Spalten …*): je Feld die Spaltenüberschriften der Excel-/CSV-Liste
  (eigene Namen statt der eingebauten). Ein leeres Feld wird nicht eingelesen und in der Signalliste nicht angezeigt.
  Nach dem Import nennt die Meldung die erkannten Spalten.
* **IO-Check: „Was hat sich bewegt?“ ausblendbar** (Knopf in der Werkzeugleiste, wird gemerkt). Ausgeblendet erscheint
  der Hinweis auf vertauschte Signale in der Statuszeile.

* **Logo und Kundenlogo** (Konfiguration › Ansicht): erscheinen im Logger rechts oben, auf den Webseiten (Diagramme,
  Prozessbild, Anmeldung) und im Kopf der PDF-Berichte und IO-Check-Protokolle. PNG und JPG werden ohne
  Zusatzbibliothek in das PDF eingebettet (PNG mit Transparenz auf weißem Grund).
* **S7: Arrays aus der DB-Quelle als Block** (Variablen aus SPS-Symbolen › *Array als Block …* oder Doppelklick auf
  das Array): erster Index und Anzahl wählen, die Startadresse wird aus der Quelle berechnet; gelesen wird im
  Blocklesemodus mit einer Anfrage.
* **Aufräumen alter Aufzeichnungen** nach Zeitraum oder Speicherplatz: CSV-Dateien und Archiv dieses Loggers
  (Reiter Aufzeichnung › *Löschen nach* / *Höchstens belegen*) und Datenbank (Reiter Datenbank; Zeitraum für SQLite,
  MariaDB, PostgreSQL/TimescaleDB und QuestDB, Speicherplatz für SQLite). Geprüft wird beim Start und danach stündlich;
  die laufende CSV-Datei bleibt immer erhalten.
* **IO-Check als eigenes Programm** (Windows: `PLCIOCheck.exe`, im Startmenü und optional auf dem Desktop): Startbild
  mit den zuletzt benutzten Prüfständen und Konfigurationen (eine Konfiguration beginnt einen neuen Prüfstand), Demo.
  Aus dem Konfigurationsprogramm: *Datei › IO-Check mit dieser Konfiguration starten*.
* **Webseiten übersetzbar:** Diagramme, Anmeldung, Prozessbild und IO-Check im Browser erscheinen in der eingestellten
  Programmsprache (bisher nur deutsch). Die Texte stehen mit in den Sprachdateien.
* **ODS-Dateien lesen** (LibreOffice/OpenOffice Calc): IO-Liste im IO-Check und Variablen-Import im
  Konfigurationsprogramm nehmen neben CSV und Excel auch ``.ods`` an – ohne Zusatzbibliothek.
* **Balkenbreite einstellbar** (Konfiguration › Ansicht › *Balkenbreite*, 4 … 40 Pixel, Vorgabe 14).
* „Über PLC Datenlogger“ und das versteckte Info-Fenster zeigen das feste Herstellerlogo, dazu Links auf
  taxis-instruments.de und den Quelltext auf GitHub. Strg + Umschalt + Doppelklick auf das Logo im Dialog „Über …“
  öffnet das Info-Fenster auch ohne eigenes Logo.

### Geändert

* Logo-Feld leer = kein Logo (bisher erschien dann das Herstellerlogo im Logger); das Startbild zeigt weiterhin das
  Herstellerlogo.
* Quelltext ausführlich kommentiert: Docstrings für Module, Klassen und Funktionen (Programm, Treiber, Werkzeuge,
  Tests) und erklärende Kommentare an schwierigen Stellen; neue Übersicht [`ARCHITEKTUR.md`](ARCHITEKTUR.md) mit
  Modulen, Datenfluss, Threads und Treiber-Schnittstelle. Der Code selbst ist unverändert.
* Bedienungsanleitung: **alle 57 Bilder neu und automatisch erzeugt**, deutsch und englisch (das User Manual hatte
  bisher deutsche Bilder und Platzhalter); dazu die Bilder der neuen Funktionen.

### Build

* `build.bat` erzeugt zusätzlich `PLCIOCheck.exe` (im selben Programmordner, Installer und portables ZIP).
* Workflow *Screenshots* (`tools/make_screenshots.py`): erzeugt alle Bilder der Anleitung unter Windows im
  Demo-Modus (deutsch und englisch; Webseiten mit Playwright, PDF-Seiten mit PyMuPDF) und legt sie im Zweig `bilder`
  ab.

### Behoben

* PDF-Bericht: Bei seltener Abtastung bzw. kurzem Zeitraum erschien der Verlauf als Punkte statt als Linie.
* Automatische Tests (`tests/`, pytest): Logik, Webserver, Sprachdateien, Anleitung und die Oberfläche mit echtem
  PySide6 (ohne Bildschirm). Workflow *Tests* bei jedem Push auf Linux und Windows; Fehler erscheinen als Hinweise im
  Lauf.

## [3.1.2] – 2026-10-21

### Behoben

* IO-Check ließ sich nicht öffnen (`AttributeError: 'IoCheckWindow' object has no attribute '_apply_filter'`); die
  Filter der Signalliste (Suche, Gruppe, Typ, Status) funktionieren jetzt.

### Geändert

* Bedienungsanleitung: 20 neue Abbildungen zu den neuen Funktionen (Trigger-Aufzeichnung und -Marken, Variablenfilter,
  Export, XY/FFT, PDF-Berichte, HTTPS/Anmeldung, OPC-UA-Subscription, ADS-Auswahl, IO-Check am PC und auf dem
  Smartphone, Abnahmeprotokoll, Sprachmenü). Das User Manual verwendet eigene englische Bilder aus `doc/images/en/`
  (vorerst Kopien der deutschen bzw. Platzhalter „Screenshot to follow“).

## [3.1.1] – 2026-10-21

### Behoben

* HTML-Anleitungen (`bedienungsanleitung.html`, `user_manual.html`): Fehlermeldungen „Cannot analyze code. Pygments
  package not found.“ in den Codeblöcken – die Codeblöcke werden jetzt ohne Syntaxfärbung erzeugt (kein Pygments
  nötig).

### Build

* `build.bat`: Meldungen beim Erzeugen der PDF-Anleitungen landen in `build\doc\pdf_de.log` bzw. `pdf_en.log`; schlägt
  ein PDF fehl, werden die letzten Zeilen angezeigt. Die PDFs liegen zusätzlich mit Versionsnummer in `dist\` und
  werden an das GitHub-Release angehängt.
* Neuer Workflow *Anleitung (PDF)*: baut die PDFs für einen vorhandenen Tag und hängt sie an dessen Release.

## [3.1.0] – 2026-10-21

### Neu

* **IO-Check** für die Inbetriebnahme (*Analyse › IO-Check …* oder `--iocheck`, Startmenü *PLC IO-Check*):
  * IO-Liste aus CSV/Excel importieren (EPLAN, TIA-Portal-Variablentabelle, eigene Liste); Spalten werden an der
    Überschrift erkannt, Signalart und Datentyp aus der Adresse abgeleitet.
  * Signalliste mit Live-Werten, Prüfstatus (OK / Fehler / übersprungen) mit Zeit, Prüfer und Bemerkung, Filter
    und Fortschritt; optional automatisch abhaken (digital nach 0→1→0, analog nach bestandener Drahtbruchprüfung).
  * „Was hat sich bewegt?“: letzte Wechsel, Warnung bei Vertauschung (anderes Signal als das gewählte).
  * Analogeingänge: **Drahtbruchprüfung** (Verdrahtung öffnen → Fehlerwert erkannt, schließen → wieder gültig;
    Vertauschungswarnung, wenn ein anderer Eingang unterbrochen wird), Skalierung, Fehlerwerte; optional Prüfpunkte
    0/50/100 % mit Toleranz (Kalibrator).
  * Matrix: Binärsignale als LEDs (Byte × Bit), geprüfte abgehakt und farbig; Bereiche ohne IO-Liste scannen.
  * Prüfstand speichern (`*.iocheck.json`, danach automatisch), Ergebnis als Excel/CSV.
  * **Auf Smartphone/Tablet** über den Webserver (Seite `/io`): Liste, Matrix, letzte Wechsel, Status setzen,
    Bemerkungen, Analog-Prüfpunkte; mehrere Geräte gleichzeitig. **Prüfer = Anmeldename** im Webserver. Läuft kein
    Webserver, startet der IO-Check einen eigenen (*📱 Mobil …*).
  * **Abnahmeprotokoll (PDF)**: Zusammenfassung je Signalart und Gruppe, Prüfer, Fehler und offene Signale, alle
    Signale mit Status, Prüfzeit, Prüfer und Bemerkung/Messpunkten, Unterschriftsfelder; auch vom Smartphone abrufbar.

### Build

* Release-Workflows: Tags auch mit großem „V“ (z. B. `V3.0.0`); von Hand mit Angabe eines vorhandenen Tags
  startbar, um dessen Release nachträglich mit Installer, ZIP und AppImages zu füllen.

## [3.0.0] – 2026-10-18

Erste Version des gemeinsamen **PLC Datenloggers**; er ersetzt die Einzelprogramme S7, TIA und CLX Datenlogger.

### Inkompatibel

* Die Konfiguration wird als **JSON** statt INI gespeichert. INI-Dateien werden nicht mehr direkt geöffnet, sondern
  einmalig umgewandelt (*Datei › INI-Datei umwandeln …* oder `tools/ini2json.py`).
* Oberfläche auf **PySide6** (LGPL) statt PyQt6 umgestellt; Lizenz des Programms: LGPL-3.0-or-later.
* Neue Ordnerstruktur: Programmdateien in `src/`, Anleitung in `doc/`, Hilfsprogramme in `tools/`.

### Neu – Treiber

* `modbus_rtu`, `opcua` (Auswahldialog, Sicherheit, wahlweise **Subscription** statt zyklischem Lesen), `slmp`
  (MELSEC), `kvhostlink` (KEYENCE), `toyopuc` (JTEKT), `s5as511` (S5 über PG-Schnittstelle).
* `fins` (Omron FINS/TCP und FINS/UDP), `ads` (Beckhoff TwinCAT mit Symbolauswahl), `logo` (Siemens LOGO! 0BA7/0BA8),
  `pccc` (Allen-Bradley MicroLogix / SLC 500).
* Eigene Treiber als einzelne Python-Datei im Ordner `treiber` (Vorlage `_vorlage.py`).

### Neu – Aufzeichnung und Auswertung

* **Aufzeichnung per Trigger** mit Ringspeicher: einstellbarer Vor- und Nachlauf, maximale Dauer, je Aufnahme eine
  CSV-Datei.
* **Trigger-Marken** an der Zeitachse (Ereignisse, Aufnahmen, Notizen) in allen Diagrammen.
* **Online-Zoom** der Zeitachse mit der Maus; Werte am Mauszeiger im Online-Modus.
* **Lesemodus Datenbank**: Zeitraum aus der Datenbank laden und offline anzeigen (Rohdaten oder Mittelwerte).
* **CSV-Dateien aneinanderhängen** und als neue Datei speichern; mehrere Dateien gemeinsam laden.
* **Werte exportieren** (CSV/Excel, optional mit Downsampling); Statistik zwischen den Linealen.
* **XY-Diagramm** (mit Regressionsgerade) und **Frequenzanalyse (FFT)**.
* **PDF-Berichte** je Schicht, Tag, Woche oder Monat (automatisch, optional) oder von Hand für einen Zeitbereich.

### Neu – Webserver und Bedienung

* Webserver mit **HTTPS** (eigenes oder selbst signiertes Zertifikat) und **Anmeldung** mit Benutzer und Passwort.
* Konfigurationsprogramm: Variablen **suchen und filtern** (Strg+F), Variablenliste als CSV/Excel importieren und
  exportieren.
* Menü **Hilfe** mit Kontexthilfe (F1) und Dialog „Über …“.
* **Englische Bedienungsanleitung** (`doc/user_manual.rst`); F1 öffnet bei englischer Oberfläche die englische
  Fassung. GitHub-Wiki in beiden Sprachen.

### Build

* Windows-Workflow (portables ZIP und Installer) und AppImages für x86_64 und arm64; Anleitung als HTML und PDF.
* `build_appimage.sh` prüft die nötigen Werkzeuge vor dem Build; `SKIP_PLCTAG=1` baut ohne libplctag.

## [2.1.0] – 2026-10-16

Ausgangsstand: die Einzelprogramme S7, TIA und CLX Datenlogger und der erste PLC Datenlogger (Treiber `s7`, `tia`,
`clx`, `modbus`), Konfiguration als INI-Datei.

## Versionen und Releases

```console
python tools/bump_version.py neben          # 3.0.0 -> 3.1.0 (auch: haupt, fehler oder z. B. 3.1.0)
python tools/bump_version.py fehler --tag   # zusätzlich Commit und Tag v3.0.1 anlegen
git push && git push origin v3.0.1          # Tag hochladen: GitHub baut Installer, ZIP und AppImages als Release
```

Das Skript setzt `APP_VERSION`, macht aus dem Abschnitt *Unveröffentlicht* dieser Datei den Abschnitt der neuen
Version (mit Datum) und legt einen neuen, leeren Abschnitt *Unveröffentlicht* an. Die Workflows brechen ab, wenn der
Tag nicht zu `APP_VERSION` passt; der Text des Release kommt aus dem Abschnitt der Version in dieser Datei.

[Unveröffentlicht]: ../../compare/v3.4.0...HEAD
[3.4.0]: ../../releases/tag/v3.4.0
[3.3.2]: ../../releases/tag/v3.3.2
[3.3.1]: ../../releases/tag/v3.3.1
[3.3.0]: ../../releases/tag/v3.3.0
[3.2.1]: ../../releases/tag/v3.2.1
[3.2.0]: ../../releases/tag/v3.2.0
[3.1.2]: ../../releases/tag/v3.1.2
[3.1.1]: ../../releases/tag/v3.1.1
[3.1.0]: ../../releases/tag/v3.1.0
[3.0.0]: ../../releases/tag/v3.0.0
[2.1.0]: ../../commit/1a833dc
