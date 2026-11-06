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

* **Dateidialoge merken sich den Ordner:** Speichern-, Öffnen- und Ordnerdialoge aller Programme öffnen im zuletzt
  benutzten Ordner (je Dialog, sonst der zuletzt überhaupt benutzte) statt immer im Programm- bzw. Datenordner.
  Wunsch aus dem SPS-Forum.

## [3.14.1] – 2026-11-06

### Geändert

* **Anleitung, Treiber `tia`:** Abschnitt *Rolle* (HMI, Engineering, PG) – was die Einstellung bewirkt
  (Verbindungsressourcen der CPU) und wann man sie ändert; Tooltip im Konfigurationsprogramm.

### Behoben

* **Webserver:** belegter Port beendete das Programm ohne Meldung (Werkzeug ruft dann `sys.exit` auf) – betroffen
  waren *Mobil …* im IO-Check (z. B. wenn ein Logger den Port schon nutzt; jetzt wird wie vorgesehen der nächste freie
  Port genommen) sowie der Start des Webservers im Logger und im Headless-Betrieb (jetzt Meldung „Port … belegt“).

## [3.14.0] – 2026-11-06

### Neu

* **IO-Check:** Prüfer änderbar – **Prüfer: …** in der Werkzeugleiste nimmt einen Klartextnamen oder ein Kürzel auf
  (Vorgabe weiterhin der angemeldete Windows-/Linux-Benutzer). Vorschlag aus dem SPS-Forum.
* **IO-Check:** Abnahmeprotokoll wahlweise im **Querformat** (Pfeil am Knopf *Protokoll (PDF) …*, gemerkt, gilt auch
  für die Mobilseite).

### Geändert

* **IO-Check-Protokoll:** Kommentar und Bemerkung werden mehrzeilig gedruckt statt abgeschnitten; „Geprüft am“ zeigt
  nur das Datum.

### Behoben

* **IO-Check:** markierte offene Zeile kaum zu erkennen (blasse Markierung mancher Stile, z. B. Windows 11, vor allem
  ohne Fokus) – die Markierung wird jetzt selbst gezeichnet: offene Zeilen voll in der Markierungsfarbe, geprüfte
  Zeilen mit kräftigerer Überlagerung und Rahmenlinien.

## [3.13.0] – 2026-11-06

### Neu

* **Farbschema** *Wie das System / Hell / Dunkel* im Menü *Sprache › Farbschema* – wirkt sofort und gilt für alle
  Programme (Logger, Konfiguration, IO-Check, Ereignis-Viewer, Netzwerk-Panel).
* **IO-Check:** Ergebnis-Export nach Excel mit den Farben der Signalliste (Zeilen je Status, Status fett in Farbe).

### Geändert

* **Teststand:** Treiber `ads` mit TwinCAT 3.1.4026.25 auf demselben Rechner erfolgreich (Symbolauswahl, Lesen,
  Aufzeichnen, auch großes Projekt) und mit einer entfernten Steuerung über eine Route (Rückmeldungen aus dem
  SPS-Forum).
* **Teststand:** Treiber `tia` auch an einer S7-1511F-1 PN (Firmware 2.9, Windows 11) erfolgreich – Variablen aus optimierten
  DBs lesen und aufzeichnen; nur das F-Programm mit Passwort (Rückmeldung aus dem SPS-Forum).

### Behoben

* **IO-Check:** markierte Zeile auf grünen, roten und grauen (geprüften) Zeilen nicht zu erkennen – die Markierung wird
  jetzt darübergelegt; Status „offen“ im dunklen Farbschema hell statt dunkelgrau.

### Build

* `tools/ads_diagnose.py`: ADS-Verbindung Schritt für Schritt prüfen (nur Standardbibliothek) – für Rückmeldungen.

## [3.12.2] – 2026-11-06

### Neu

* **ADS: TwinCAT auf demselben Rechner** – mit IP-Adresse `127.0.0.1` (oder der eigenen) und leerer eigener AMS-Net-ID
  meldet sich der Treiber beim lokalen AMS-Router an (AMS/TCP „Port verbinden“), eine Route ist nicht nötig.
  Voraussetzung: AMS TCP Loopback (ab TwinCAT 3.1.4024.5 Standard).

### Geändert

* **Teststand:** unter Linux (Ubuntu Studio) erfolgreich mit ControlLogix sowie S7 mit PLCSIM über NetToPLCsim.
* **Teststand:** macOS-App auf einem Mac Neo mit einer ControlLogix erfolgreich getestet – nicht mehr „Vorschau“.
* **Teststand:** Treiber `tia` an einer echten S7-1516-3 PN/DP (Firmware 2.9) erfolgreich getestet, Merker gelesen
  (Rückmeldung aus dem SPS-Forum).
* **Teststand** in Anleitung, README und Webseite: Treiber `opcua` und der OPC-UA-Server im Netz erprobt (Raspberry Pi
  als Server, PC als Client: Lesen, Subscription, Wiederverbinden, Basic256Sha256 mit Anmeldung).

### Behoben

* **ADS:** große Symboltabellen im Auswahldialog – Zeitlimit beim Lesen der Tabelle mindestens 30 s; Meldungen des
  Routers zwischen den Antworten werden übersprungen; „Port gesperrt“ mit Hinweis auf Route bzw. 127.0.0.1.

## [3.12.1] – 2026-11-05

### Behoben

* **Aus Steuerung wählen (OPC UA, Beckhoff ADS):** „Auswahl übernehmen“ tat nichts – die angehakten Variablen
  wurden wegen eines Programmfehlers (AttributeError) nicht übernommen.
* **OPC-UA-Server startete nicht**, wenn ein Variablen- oder Steuerungsname einen Doppelpunkt enthält (Allen-Bradley
  `Program:Main.x`): „Error parsing string …“. Browse-Namen werden jetzt immer im eigenen Namensraum angelegt.
* **Netzwerk-Panel:** Docker-Netze (`veth…`) und andere virtuelle Schnittstellen werden nicht mehr als Ethernet
  angezeigt; das Ein/Aus-Symbol ist gezeichnet (das Zeichen ⏻ fehlte in der Schrift des Raspberry Pi).
* **Netzwerk-Panel ohne root:** „System policy prevents Wi-Fi scans“ – statt eines Fehlers zeigt die WLAN-Seite die
  zuletzt bekannten Netze; fehlende Berechtigungen erklärt ein Hinweis (Dienst/sudo oder polkit-Regel, siehe Anleitung).

### Build

* **Projekt-Webseite** auf GitHub Pages (Startseite und Anleitung als HTML, deutsch/englisch; Workflow *Webseite*),
  englisches README (deutsches in `README.de.md`), Vorlagen für Issues, Vorschaubild `doc/site/social.png`.

## [3.12.0] – 2026-11-04

### Neu

* **Ereignisse in der Datenbank** – Trigger-Ereignisse (kommt, geht, quittiert mit Benutzer) und Notizen werden
  zusätzlich in die Datenbank geschrieben (Einstellung *Ereignisse und Notizen mitschreiben*, Standard ein):
  SQLite, MariaDB, PostgreSQL/TimescaleDB, QuestDB und InfluxDB 3 in die Tabelle `<Tabelle>_ereignisse` (ein Datensatz
  je Ereignis, wird bei Gehen/Quittieren aktualisiert; beim Start Abgleich des ganzen Protokolls), VictoriaMetrics und
  Prometheus als Metriken `<Tabelle>_ereignisse_aktiv` / `_quittiert`. Das exportierte Grafana-Dashboard zeigt sie als
  Markierungen *Ereignisse* in allen Diagrammen.

### Build

* Workflow *Tests*: zusätzlich MariaDB, PostgreSQL/TimescaleDB, QuestDB und InfluxDB 3 als echte Server (Linux).

## [3.11.2] – 2026-11-04

### Behoben

* **Startbild:** Knöpfe in zwei Reihen – „Demo“ und „Mit Logger verbinden …“ waren abgeschnitten.

## [3.11.1] – 2026-11-04

### Neu

* **Netzwerk-Panel:** zeigt oben die installierte Version (z. B. vor einem Update oder für die Betriebsart Client
  prüfen).
* **Netzwerk-Panel: Ausschalten** – Knopf ⏻ mit *Neu starten* und *Herunterfahren* (Logger-Dienst wird dabei
  ordnungsgemäß beendet).

### Behoben

* **Client:** Adresse mit Zugriffscode (`…/?token=…`, wie *Webserver-Adresse …* sie kopiert) wird angenommen; ein
  Logger mit älterer Version am Server ergibt eine verständliche Meldung statt „404“.

## [3.11.0] – 2026-11-03

### Neu

* **Betriebsart Client** – der Logger zeigt die Aufzeichnung eines anderen Loggers an (z. B. headless auf einem
  Raspberry Pi), ohne eigene Konfiguration und ohne Steuerung: Diagramme, Variablen, Anordnung und Steuerungs-LEDs kommen
  über dessen Webserver. Live-Anzeige mit allen Auswertungen des Loggers (Lineale, Zoom, Analyse, Bericht, Export),
  Ereignisse quittieren und Notizen (mit Schreibrecht), ältere Zeiträume aus Speicher und Datenbank des Servers
  („Aus Datenbank laden …“, „Im Diagramm zeigen“). Start über *Mit Logger verbinden …* im Startbild, *Datei › Mit Logger
  verbinden (Client) …* (Strg+K) oder `--client [ADRESSE] [--benutzer NAME]`. Selbstsignierte HTTPS-Zertifikate nach
  Bestätigen des Fingerabdrucks; Adresse und Benutzer werden gemerkt (nie das Passwort). Startet der Server eine neue
  Aufzeichnung, verbindet sich der Client neu. Neue Schnittstellen `/api/konfig`, `/api/zeilen`, `/api/verlauf`.

## [3.10.0] – 2026-11-03

### Neu

* **Web-Client: Auswerten im Browser** – Zoom je Diagramm (Mausrad, Bereich aufziehen mit Y-Zoom, zwei Finger auf dem
  Tablet) mit „Angleichen“ und „Zoom zurücksetzen“; zwei Lineale mit Werten und Differenz; Verlauf vor dem Speicher
  des Loggers aus der Datenbank (Zeitfenster bis 7 Tage, Sprung zu Datum/Uhrzeit, Lücken bleiben offen); Export des
  Zeitbereichs als Excel/CSV und PDF-Bericht; Ereignisliste mit Sprung ins Diagramm, Quittieren und Notizen,
  Ereignis-Marken in den Diagrammen. Neue Schnittstellen `/api/export`, `/api/bericht`, `/api/ereignisse`.
* **Schreibrecht je Web-Benutzer** (Häkchen im Dialog *Benutzer …*, Einstellung `web_rechte`): Quittieren, Notizen und
  Prozessbild bearbeiten nur mit Schreibrecht, sonst ansehen und exportieren. Neue Benutzer zunächst ohne, bisherige
  Benutzer behalten es; der Zugriffscode allein gibt nur Leserecht, sobald Benutzer eingerichtet sind.

## [3.9.0] – 2026-11-03

### Neu

* **Netzwerk-Panel: Logger starten/stoppen** – Konfigurationsdatei aus einer Liste wählen und headless starten; mit
  eingerichtetem Dienst stellt das Panel ihn auf die gewählte Datei um (startet dann auch nach dem Booten), sonst
  startet es den Logger direkt. Statt „Aktualisieren“ (die Übersicht erneuert sich ohnehin alle 5 s) gibt es den Knopf
  „Logger“.

### Geändert

* Anleitung Raspberry Pi, Daten auf der SSD: Ordner mit `sudo` anlegen und dem Benutzer übergeben (vorher „Keine
  Berechtigung“), vorhandenen `~/PLCDatenlogger` umziehen, Logger-Dienst mit `RequiresMountsFor=/data`.

## [3.8.0] – 2026-11-03

### Neu

* **Netzwerk-Panel: Display abdunkeln** nach einstellbaren Minuten ohne Berührung (Hintergrundbeleuchtung über
  `/sys/class/backlight`, Helligkeit im Betrieb und abgedunkelt einstellbar, sonst schwarzes Bild); die erste Berührung
  schaltet nur wieder ein.

### Geändert

* Anleitung Raspberry Pi, System auf SD-Karte: Daten von VictoriaMetrics auf die SSD (Bind-Mount in
  `docker-compose.override.yml`, Docker wartet mit `RequiresMountsFor` auf die SSD, vorhandene Daten umziehen).

### Behoben

* Netzwerk-Panel: ein von Hand gestarteter Headless-Logger wurde als „gestoppt“ angezeigt (geprüft wurde nur der
  Dienst); jetzt zählen auch die Statusdateien laufender Headless-Logger („läuft (headless) – Projekt“).

## [3.7.1] – 2026-11-02

### Behoben

* Netzwerk-Panel: aus einem Terminal im Remotedesktop gestartet, versuchte `plc-netzwerk` sich in der Remotesitzung zu
  öffnen statt auf dem Display des Pi; jetzt immer auf dem Display (ohne Grafiktreiber automatisch `linuxfb`), als
  Fenster nur mit `--fenster`.
* Logger: ohne grafische Sitzung (systemd-Dienst, SSH) startet er headless, auch wenn der Headless-Modus in der
  Konfiguration aus ist (vorher Abbruch). Der Dienst in der Raspberry-Anleitung braucht kein `--headless` mehr – der
  Schalter in der Konfiguration entscheidet.
* Netzwerk-Panel: `sudo plc-netzwerk --fenster` in einer (Remote-)Desktop-Sitzung scheiterte mit „Authorization
  required“ – das Panel verwendet jetzt die X-Anmeldedaten des aufrufenden Benutzers.

### Geändert

* Anleitung Raspberry Pi: Datenbankzugriff vom PC und Absichern von VictoriaMetrics; Remotedesktop ausführlich (XFCE
  ohne Anmeldebildschirm mit `--no-install-recommends`, xrdp mit `xorgxrdp`, Polkit-Regel gegen die colord-Rückfrage,
  Fehlersuche).

## [3.7.0] – 2026-11-01

### Neu

* **Netzwerk-Panel: Datum und Uhrzeit** – von Hand stellen, Internetzeit (NTP) ein/aus, Zeitzone wählen; Uhrzeit
  einer Steuerung lesen und auf den Pi übernehmen, auf Wunsch automatisch (beim Start und stündlich, solange keine
  Internetzeit synchronisiert ist). Treiber mit Uhrzeit: `s7`, `clx` (Systemuhr), `opcua` (Serverzeit);
  neue Treiberschnittstelle `Driver.read_clock`.
* **Aufzeichnen und Anzeigen je Variable:** Neue Spalten *Aufzeichnen* und *Anzeigen* in der Variablentabelle.
  Nicht aufgezeichnete Variablen bleiben in der Konfiguration, werden aber nicht gelesen; angezeigt (Diagramme,
  Wertetabelle, Webserver, Bericht, Grafana-Dashboard) werden nur aufgezeichnete Variablen mit *Anzeigen*. Bei Blöcken
  lässt sich das je Element wählen (Blockeditor, auch für alle Elemente auf einmal); der Block wird weiterhin immer
  vollständig gelesen, nicht aufgezeichnete Elemente stehen für Formeln und Trigger bereit. Filter „nicht
  aufgezeichnet“/„nicht angezeigt“, graue Einträge im Variablenbaum, Spalten auch im Variablen-Export/-Import.
* **Netzwerk-Panel für einen Touchscreen** (`plc-netzwerk` bzw. `--netzwerk`): bildschirmfüllend ohne Desktop (Qt eglfs),
  zeigt Rechnername, IP-Adressen von Ethernet und WLAN, Zustand des Logger-Dienstes und die Webserver-Adresse mit
  QR-Code; stellt über NetworkManager DHCP oder feste Adresse und WLAN (Suche, Passwort per Bildschirmtastatur) ein.
* Anleitung: **Raspberry Pi als Datenlogger einrichten** – Ubuntu Server direkt auf der USB-SSD, NetworkManager,
  Logger als systemd-Dienst, VictoriaMetrics per Docker, Grafana nur bei Bedarf (`docker/grafana.sh`, Desktop-Starter
  mit `docker/desktop-starter.sh`, `docker/grafana-bei-bedarf.yml`), Netzwerk-Panel als Dienst, Remotedesktop (xrdp).

## [3.6.0] – 2026-10-30

### Neu

* Konfigurationsprogramm, Reiter *Datenbank*: **Speicherplatz …** zeigt den belegten Platz der Tabelle und der
  Datenbank sowie die Anzahl der Werte (je nach Datenbanktyp; Prometheus nur gesamt). Bei VictoriaMetrics zusätzlich
  je Projekt Werte, Variablen und ältester Wert, Byte je Wert, Aufbewahrung, freier Platz, Zuwachs der letzten
  24 Stunden und der geschätzte Platzbedarf bei voller Aufbewahrung.
* Konfigurationsprogramm: **Datei › Grafana-Dashboard exportieren …** – Dashboard mit der Anordnung des Loggers
  (Seiten als Zeilen, untereinander/nebeneinander/Raster, Farben, Y-Achsen, BOOL als Treppenlinie, Zeitbereich,
  Auswahl Projekt) für VictoriaMetrics, Prometheus, TimescaleDB/PostgreSQL, MariaDB, QuestDB und InfluxDB 3.

## [3.5.0] – 2026-10-29

### Neu

* Logger: **Zoom-Rechteck** (Werkzeugleiste) – mit der linken Maustaste einen Bereich aufziehen, Zeit und alle
  Y-Achsen des Diagramms werden vergrößert; **Zoom zurücksetzen** stellt die konfigurierte Skalierung wieder her.

### Geändert

* Logger: Mausrad, Ziehen und Zoom wirken nur auf das **Diagramm unter dem Mauszeiger** – jedes Diagramm kann eine eigene
  Zeitachse haben (online mit eigener Fensterbreite). **Zeitachsen angleichen** setzt alle wieder auf den Ausschnitt des
  zuletzt bedienten Diagramms; die Scrollleiste verschiebt alle gemeinsam.

### Behoben

* Webserver mit HTTPS: Das selbstsignierte Zertifikat ließ sich auf Rechnern mit langem Namen (über 64 Zeichen, z. B.
  manche Macs) nicht erzeugen.

## [3.4.3] – 2026-10-29

### Neu

* Treiber `tia`: Ringpuffer auch in **optimierten** Bausteinen. Als Startadresse genügt der Name des Puffers (z. B.
  `PLC_Ringpuffer`, `Cycl_Rec_DB` oder `Anlage_DB.Puffer`); gelesen werden `Zaehler` und `Daten[i].Seq/.Zeit/.Werte[j]`
  symbolisch, ohne PUT/GET. Die absolute Adresse (`DB100.DBX0.0`, nicht optimiert) geht weiterhin. Vorlagen für
  S7-1200/1500 entsprechend beschrieben.

### Geändert

* Anleitung: Treiber `tia` mit S7-PLCSIM Advanced erprobt (ohne PUT/GET, TLS, Variablenliste, optimierte DBs,
  Ringpuffer über den Namen, Zugriffsstufen ohne Passwort).

### Behoben

* Treiber `tia` mit TLS unter Windows: Absturz „OPENSSL_Uplink: no OPENSSL_Applink“ beim Verbinden (je nach Python
  bzw. OpenSSL-DLL, z. B. in lokal gebauten Programmen). Ohne Passwort wird die TLS-Schlüsseldatei von s7commplus nicht
  mehr geschrieben; sie wird nur für die Anmeldung mit Passwort gebraucht.

### Build

* `build.bat` weist darauf hin, wenn mit Python 3.14 oder neuer gebaut wird (Treiber `tia` mit TLS und Passwort bricht
  dann ab); die Release-Dateien werden mit Python 3.12 gebaut.

## [3.4.2] – 2026-10-29

### Geändert

* Eigene Icons je Programm: das „Ti“ des Logos mit farbigem Abzeichen für Logger (blau, Kurve), Konfiguration
  (orange, Zahnrad), IO-Check (grün, Haken), Ereignisprotokoll (rot, Liste) und Headless (grau, Aufnahme) – in
  Fenstern, Taskleiste (eigene Gruppe auch für das Ereignisprotokoll), Windows-Startmenü, Linux-Startmenü (`.deb`,
  AppImage-Aktionen) und als macOS-Programmsymbol. `app.ico` enthält jetzt alle Größen von 16 bis 256 Pixeln.
  Erzeugt mit `tools/make_program_icons.py`.
* Logo: Ohne Eintrag zeigen Logger, Webseiten, PDF-Berichte und IO-Check-Protokolle jetzt das mitgelieferte
  Herstellerlogo (`logo.png`); `-` im Feld *Logo* schaltet das Logo ab (bisher: leer = kein Logo).

### Behoben

* Datenbank (Prometheus): Die Meldung „Werte abgelehnt“ fehlte, wenn der Rechner erst weniger als eine Minute lief
  (z. B. Raspberry Pi direkt nach dem Booten).

## [3.4.1] – 2026-10-28

### Neu

* Headless-Logger aus dem Konfigurationsprogramm beenden: **Datei › Headless-Logger anzeigen/beenden …** bzw. im
  Reiter *Webserver & Headless* **Laufende Logger …** zeigt die laufenden Headless-Logger (Projekt, Konfiguration,
  Startzeit, Rechner, PID, Webserver) und beendet den gewählten sauber (CSV schließen, archivieren) – auf allen
  Systemen, auch ohne Konsole. Die Logger melden sich dazu mit einer Statusdatei im Ordner `laufend` des Datenordners
  an.

### Behoben

* Linux arm64 (Raspberry Pi): AppImage und `.deb` werden jetzt auf Ubuntu 22.04 gebaut und laufen damit auch auf
  Ubuntu 22.04, Debian 12 und Raspberry Pi OS Bookworm (bisher: `libc6 (>= 2.39)`, nur Ubuntu 24.04 bzw. Trixie).
* Konfigurationsprogramm: Spalte „Treiber“ der Steuerungen so breit, dass die Treibernamen lesbar sind; englische
  Oberfläche: „Path“ bzw. „Device“ statt „Pfad“/„Gerät“ in der Verbindungsbeschreibung (clx, modbus_rtu).

### Build

* `build.bat doc`, `./build_appimage.sh doc` und `./build_macos.sh doc` erzeugen nur die Anleitung (HTML und PDF,
  deutsch und englisch).
* Automatische Tests der Treiber gegen Simulatoren fremder Bibliotheken: `s7` gegen den S7-Server von python-snap7
  (inkl. Ringpuffer), `tia` (Ringpuffer) gegen den S7CommPlus-Emulator, `modbus` gegen pymodbus, `opcua` gegen asyncua.
  Die Anleitung zeigt je Treiber, wie er geprüft ist.

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

[Unveröffentlicht]: ../../compare/v3.14.1...HEAD
[3.14.1]: ../../releases/tag/v3.14.1
[3.14.0]: ../../releases/tag/v3.14.0
[3.13.0]: ../../releases/tag/v3.13.0
[3.12.2]: ../../releases/tag/v3.12.2
[3.12.1]: ../../releases/tag/v3.12.1
[3.12.0]: ../../releases/tag/v3.12.0
[3.11.2]: ../../releases/tag/v3.11.2
[3.11.1]: ../../releases/tag/v3.11.1
[3.11.0]: ../../releases/tag/v3.11.0
[3.10.0]: ../../releases/tag/v3.10.0
[3.9.0]: ../../releases/tag/v3.9.0
[3.8.0]: ../../releases/tag/v3.8.0
[3.7.1]: ../../releases/tag/v3.7.1
[3.7.0]: ../../releases/tag/v3.7.0
[3.6.0]: ../../releases/tag/v3.6.0
[3.5.0]: ../../releases/tag/v3.5.0
[3.4.3]: ../../releases/tag/v3.4.3
[3.4.2]: ../../releases/tag/v3.4.2
[3.4.1]: ../../releases/tag/v3.4.1
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
