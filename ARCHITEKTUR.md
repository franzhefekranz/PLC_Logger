# Aufbau des PLC Datenloggers

Überblick für alle, die am Programm arbeiten wollen: welche Datei was tut, wie die Messwerte fließen und welche
Threads beteiligt sind. Einzelheiten stehen in den Docstrings der Module (jede Datei beginnt mit einer Beschreibung);
die Bedienung beschreibt `doc/bedienungsanleitung.rst`.

## Programme und Start

Ein Startprogramm, mehrere Fenster bzw. Betriebsarten:

| Aufruf | Modul | Zweck |
|---|---|---|
| `plc_logger.py [KONFIG]` | `plc_logger` → `plc_gui` | Logger mit Oberfläche (Diagramme, online/offline, Lineale, Analyse) |
| `plc_logger.py --headless` | `plc_logger` → `plc_headless` | nur Aufzeichnung, ohne Qt (Server, Dienst) |
| `plc_logger.py --konfig` | `plc_config` | Konfigurationsprogramm |
| `plc_logger.py --ereignisse` | `plc_event_viewer` | Ereignis-Viewer (z. B. neben einem Headless-Logger) |
| `plc_logger.py --iocheck` | `plc_iocheck_dialog` | IO-Check für die Inbetriebnahme |
| `plc_iocheck_start.py` (`PLCIOCheck.exe`) | `plc_iocheck_dialog` | IO-Check als eigenes Programm mit Startbild |

`plc_logger` lädt bewusst noch kein Qt: Erst nach der Entscheidung GUI/Headless werden die schweren Bibliotheken
importiert. Alle Betriebsarten benutzen dieselbe Konfigurationsdatei (JSON).

## Schichten

```
Oberfläche (PySide6)     plc_gui, plc_config, plc_*_dialog, plc_event_viewer, plc_iocheck_dialog, plc_splash, plc_about
                                │  liest Kopien der Puffer, startet/stoppt
Kern (ohne Qt)           plc_recorder ── plc_events (Trigger) ── plc_formula (berechnete Variablen)
                                │
Ausgänge / Dienste       CSV (plc_recorder) · plc_db · plc_web (+ plc_web_prozess, plc_iocheck_web)
                         plc_opcua_server · plc_notify · plc_report
                                │
Treiber                  plc_treiber/ (base + je Protokoll ein Modul, optional Auswahldialog)
                                │
Grundlagen               plc_common (Datenmodell, Konfiguration), plc_util, plc_i18n, plc_webauth
```

Regel: Module ohne `_dialog`/`_gui`/`_config` im Namen importieren kein Qt (manche nur optional). Dadurch laufen
Headless-Betrieb und die Logik-Tests ohne PySide6.

## Module

**Grundlagen**

* `plc_common` – Datenmodell (`Plc`, `Chart`, `Axis`, `Variable`, `Block`), Laden/Speichern der Konfiguration,
  Umwandlung alter INI-Dateien, `APP_VERSION` (einzige Quelle der Versionsnummer).
* `plc_util` – kleine Hilfen (Textfilter, Zeitformate, Dateinamen …).
* `plc_i18n` – `tr("…")`: Übersetzung über `sprachen/<kürzel>.txt`; deutsche Texte sind die Schlüssel.
* `plc_formula` – sichere Auswertung von Formeln berechneter Variablen (die Formel wird als Syntaxbaum geprüft, nur erlaubte
  Elemente werden zugelassen).
* `plc_webauth` – Benutzer und Passwort-Hashes des Webservers.

**Aufzeichnung**

* `plc_recorder` – Kern: Lese-Threads je Steuerung, Sammler, Puffer, CSV mit Rotation/Archiv, Demo-Werte,
  Aufzeichnung per Trigger mit Vor-/Nachlauf (`CaptureGate`).
* `plc_events` – Trigger (Bedingung, Priorität, Verzögerung), `TriggerEngine` und Ereignisprotokoll (CSV).
* `plc_db` – Schreiben in Datenbanken (SQLite, MariaDB, PostgreSQL/TimescaleDB, QuestDB, InfluxDB, VictoriaMetrics,
  Prometheus) in eigenem Thread mit Puffer bei Verbindungsausfall; Lesemodus (`create_reader`).
* `plc_headless` – Aufzeichnung ohne Oberfläche, Meldungen auf die Konsole/ins Log.
* `plc_cleanup` – Aufräumen alter CSV-/Archivdateien nach Alter oder Gesamtgröße (Datenbank: `cleanup` der
  Backends in `plc_db`, ausgeführt vom Schreib-Thread).

**Dienste**

* `plc_web` – Flask-Webserver: Diagramme im Browser (`/`), Prozessbild (`/prozess`), IO-Check mobil (`/io`),
  JSON-Schnittstelle (`/api/...`), Anmeldung, HTTPS mit selbst erzeugtem Zertifikat.
* `plc_web_prozess`, `plc_iocheck_web` – HTML/CSS/JavaScript der Browserseiten (je eine Zeichenkette).
* `plc_opcua_server` – OPC-UA-Server (asyncua) mit allen Variablen, Status und Ereignissen.
* `plc_notify` – Benachrichtigungen (E-Mail, Teams/Slack/Webhook, ntfy) mit Sperrzeit, Versand im eigenen Thread.
* `plc_report` – PDF-Berichte (Schicht/Tag/Woche/Monat) ohne Zusatzbibliothek.
* `plc_qr`, `plc_svg` – QR-Code und SVG-Export, beide ohne Zusatzbibliothek.

**Auswertung** – `plc_analysis` (XY, FFT), `plc_pid` (Regleroptimierung), `plc_export` (CSV/Excel),
`plc_csvjoin` (Aufzeichnungen zusammenfügen), `plc_iocheck` (Logik des IO-Checks). Die zugehörigen Fenster liegen
in den `*_dialog`-Modulen.

**Oberfläche** – `plc_gui` (Hauptfenster des Loggers), `plc_config` (Konfigurationsprogramm mit Reitern), die
Dialoge `plc_*_dialog`, `plc_event_viewer`, `plc_splash`, `plc_about`, `plc_branding`.

## Datenfluss einer Messung

```
Steuerung ──► PlcSampler (Thread je Steuerung)                       Treiber: Reader.connect/read/close
                 │  (Zeitstempel, Werte, Steuerung) in die Warteschlange
                 ▼
             Recorder._collector (ein Thread)
                 │  1. Zeile bilden: letzte Werte aller Steuerungen + diese Messung
                 │  2. berechnete Variablen (plc_formula)
                 │  3. Trigger prüfen (TriggerEngine) ──► Ereignisprotokoll, Notifier, OPC-UA-Ereignis
                 │  4. CaptureGate (nur bei Aufzeichnung per Trigger)
                 ├──► Puffer im Speicher  ──► GUI (QTimer holt window/snapshot), Webserver (/api/data)
                 ├──► CSV-Datei (gesammelt geschrieben, Rotation, Archiv-ZIP im eigenen Thread)
                 ├──► DbWriter (Warteschlange, eigener Thread)
                 └──► OpcUaServer.update (Werte für den Server-Thread)
```

Mehrere Steuerungen liefern zu eigenen Zeitpunkten; der Sammler schreibt bei jeder eintreffenden Messung eine
vollständige Zeile, in der die übrigen Steuerungen ihren letzten Wert behalten.

**Ringpuffer (zyklussynchron):** Blöcke mit `ring > 0` liest der Treiber nicht im Takt, sondern holt die von der
Steuerung gesammelten Datensätze ab (`plc_treiber/ringbuffer.py`: `RingSupport.read_rings`, Folgenummern,
Verlusterkennung, SPS-Zeit → PC-Zeit). Der `PlcSampler` stellt jeden Datensatz mit seinem Zeitstempel einzeln in die
Warteschlange (`put_sample(..., gidx)`); der Sammler hält dann alle Messzyklen `reorder_s` Sekunden zurück und
verarbeitet sie nach Zeit sortiert.

## Threads

| Thread | Wo | Aufgabe |
|---|---|---|
| Oberfläche | Qt-Hauptthread | Fenster, Diagramme; holt Daten per Timer, nie blockierende Netzwerkzugriffe |
| `PlcSampler` (je Steuerung) | `plc_recorder` | verbinden, zyklisch lesen, bei Fehlern neu verbinden |
| `collector` | `plc_recorder` | Zeilen bilden, Formeln, Trigger, Puffer, CSV |
| Archivierung | `plc_recorder` | volle CSV-Datei zippen, prüfen, Original löschen |
| `aufraeumen` | `plc_cleanup` | beim Start und stündlich alte CSV-/Archivdateien löschen |
| `db-writer` | `plc_db` | Datenbank schreiben (Lesen im Lesemodus: Thread `db-lesen` in `plc_db_dialog`) |
| `webserver` | `plc_web` | Flask/werkzeug, jede Anfrage in eigenem Thread |
| `opcua-server` | `plc_opcua_server` | asyncio-Schleife des OPC-UA-Servers |
| `benachrichtigung` | `plc_notify` | Nachrichten versenden (SMTP/HTTP mit Zeitlimit) |
| `bericht` | `plc_report` | PDF-Bericht erzeugen |
| Auswahldialoge | `plc_treiber/*_browser` | Variablenliste aus der Steuerung laden, Fortschritt per Timer |

Austausch zwischen den Threads nur über Warteschlangen und Sperren (`Recorder.lock`); Leser von außen bekommen
Kopien (`window`, `slice_time`, `snapshot`, `status_list`, `drain_messages`). Qt-Objekte werden nur im
Hauptthread angefasst.

## Konfigurationsdatei

JSON mit den Gruppen `einstellungen` (Projekt, CSV, Webserver, Datenbank, Benachrichtigung, OPC-UA-Server …;
verschachtelte Einstellungen als JSON-Text), `steuerungen` (Treiber und Parameter), `diagramme` (mit Y-Achsen),
`variablen`, `bloecke` und `trigger`. Lesen/Schreiben: `plc_common.load_config`/`save_config`, Trigger:
`plc_events.load_triggers`/`save_triggers`. Persönliche Einstellungen (zuletzt benutzte Datei, Sprache, Fenster)
liegen getrennt im Datenordner (`plc_common._app_dir`: beim Entwickeln der Projektordner, installiert
`%APPDATA%\PLCDatenlogger` bzw. `~/PLCDatenlogger`, portabel mit `portable.txt` der Programmordner).

## Treiber

`plc_treiber/base.py` beschreibt die Schnittstelle:

* `Driver` – Kennung, Name, Parameter (`Param` → Eingabefelder in `plc_treiber/ui.py`), lesbare Datentypen,
  `check_address`, `block_element_address`, `create_reader`, optional `browse` (Auswahldialog).
* `Reader` – `connect()` → Anzahl lesbarer Variablen, `read()` → Liste von float (NaN = kein Wert), `close()`,
  `errors` für einzelne nicht lesbare Variablen. Verbindungsfehler als Ausnahme; der `PlcSampler` verbindet neu.

Ringpuffer: Treiber mit `ring_types` (s7, tia, clx) mischen `RingSupport` in ihren Leser und setzen
`_ring_counter` und `_ring_bytes` (bzw. `_ring_fetch`) um; SPS-Bausteine dazu liegen im Ordner `vorlagen`.

`plc_treiber/__init__.py` sammelt die eingebauten Treiber und lädt eigene aus dem Ordner `treiber` im Datenordner.
Vorlage für eigene Treiber: `plc_treiber/_vorlage.py`. Größere Treiber sind aufgeteilt in Protokoll
(`*_io.py`), Variablenliste (`*_taglist.py`) und Auswahldialog (`*_browser.py`).

## Übersetzung

Texte der Oberfläche stehen deutsch in `tr("…")` (bzw. `N_("…")` für Texte in Tabellen). `python
tools/extract_tr.py plc .` sammelt sie in `sprachen/de.txt` und gleicht `sprachen/en.txt` ab; ein Test prüft, dass
alles übersetzt ist und die Platzhalter stimmen.

## Werkzeuge, Tests, Workflows

* `tools/bump_version.py` – Version erhöhen, CHANGELOG umstellen, Tag prüfen (Release-Workflows).
* `tools/build_doc.py` – Anleitung als PDF (Sphinx + rinohtype), `tools/make_wiki.py` – Anleitung als Wiki-Seiten.
* `tools/make_screenshots.py` – Bilder der Anleitung im Demo-Modus erzeugen (Workflow *Screenshots*).
* `tools/ini2json.py`, `tools/make_icon.py` – Umwandlung alter Konfigurationen, Programm-Icon.
* `tests/test_logic.py` – Logik ohne Oberfläche (IO-Check, Analyse, Übersetzung, Anleitungen, Version, QR-Code,
  Benachrichtigungen mit lokalen Testservern, OPC-UA-Server, Prozessbild-API).
* `tests/test_gui.py` – Fenster im Demo-Modus ohne Bildschirm (`QT_QPA_PLATFORM=offscreen`); modale Dialoge ersetzt
  `tests/conftest.py`.
* `.github/workflows/` – *Tests* (jeder Push, Linux und Windows), *Windows* (Installer), *AppImage* (Linux: AppImages und .deb-Pakete),
  *Anleitung* (PDF), *Wiki*, *Screenshots*.
