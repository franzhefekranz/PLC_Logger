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

### Neu

* **QR-Code** für die Adresse der Webseite: im IO-Check (*📱 Mobil …*) und im Logger (*Datei › Webserver-Adresse …*);
  mit der Kamera des Smartphones scannen statt tippen. Eigener QR-Encoder, keine Zusatzbibliothek.
* **Vom Ereignis zur Stelle im Diagramm:** Im Ereignis-Viewer *Im Diagramm zeigen* (Knopf oder Rechtsklick) zeigt den
  Zeitraum um das Ereignis im Logger (offline), Lineal 1 auf dem Beginn, Lineal 2 auf dem Ende. Liegen die Werte nicht
  mehr im Speicher, wird die passende CSV-Datei bzw. das Archiv geladen.
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

### Build

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

[Unveröffentlicht]: ../../compare/v3.1.2...HEAD
[3.1.2]: ../../releases/tag/v3.1.2
[3.1.1]: ../../releases/tag/v3.1.1
[3.1.0]: ../../releases/tag/v3.1.0
[3.0.0]: ../../releases/tag/v3.0.0
[2.1.0]: ../../commit/1a833dc
