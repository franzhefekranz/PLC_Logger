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

* **Anleitung:** Neues Kapitel „Referenz: alle Menüs, Fenster und Bedienelemente“ (englisch „Reference: all menus,
  windows and controls“): je Menü, Werkzeugleiste, Reiter und Dialog eine Tabelle mit Tastenkürzel und Bedeutung und
  Verweisen auf die ausführlichen Abschnitte. Bezeichnungen und Tooltips stammen aus dem Programm selbst (Workflow
  *UI-Referenz*, `tools/make_referenz.py`).

### Behoben

* **Wiki:** Verweise auf eine Sprungmarke vor einem Absatz (z. B. „Zoomen und Zeitachsen“) führten von anderen
  Wiki-Seiten ins Leere – sie zeigen jetzt auf die Seite des Kapitels mit dem passenden Anker.
* **Übersetzung:** Ersatztexte für unbekannte Fehlercodes der Treiber („siehe Handbuch“, „unbekannt“ …) erschienen
  auch in der englischen Oberfläche auf Deutsch. `tools/extract_tr.py` erfasst jetzt Ersatztexte in
  `tr(TABELLE.get(code, "…"))` und warnt bei `tr(f"…")`, das sich nicht übersetzen lässt.
* **Versionswechsel:** `bump_version.py --tag` committet nur noch `plc_common.py` und `CHANGELOG.md` (bisher auch alles
  andere schon Vorgemerkte); `--check-tag` ohne Tag gibt eine klare Meldung.
* **Treiber s5as511:** Nach dem Nachladen eines Datenbausteins aus dem PG las der Logger unbemerkt die alte, ungültige
  Kopie weiter (Werte eingefroren), nach dem Komprimieren fremden Speicher (Unsinnswerte). Die Adressen der
  Datenbausteine werden jetzt alle 30 s neu erfragt; ändern sie sich, wird der Leseplan neu gebildet und eine Meldung
  ausgegeben. Ein DB, der beim Verbinden fehlte, wird so auch später gefunden.
* **Ringpuffer:** War der Puffer in der Steuerung dauerhaft zu klein, entstand bei jeder Abholung eine eigene
  Meldung „… Datensätze verloren“ (bei 250 ms Abholintervall vier je Sekunde). Jetzt kommt die erste Meldung sofort,
  danach höchstens eine je Minute mit der Summe.
* **Treiber pccc:** Lag ein Element hinter dem Dateiende (z. B. `N7:12` bei einer Datei mit 10 Elementen), meldeten
  alle Elemente seiner Gruppe dauerhaft „Lesefehler“ – jetzt werden sie einzeln gelesen, nur das fehlende meldet ihn.
* **Treiber mqtt:** Verweigerte der Broker das Abonnement eines Topics (z. B. fehlende Zugriffsrechte), blieb die
  Variable ohne Wert und ohne Meldung – jetzt meldet sie „Broker verweigert das Abonnement“.
* **Treiber logo:** Lehnte die LOGO! einen zusammengefassten VM-Bereich ab (Zugriffsrechte, Speicherende), meldeten
  alle Variablen darin dauerhaft den Fehler – jetzt werden sie einzeln gelesen. Variablen, die über das Ende des
  Variablenspeichers reichen (z. B. `VD1468`), werden bei der Prüfung abgewiesen.
* **Treiber slmp:** Zu große Gerätenummern (z. B. `D99999999`) und ein Ziel-Modul über `FFFF` bestanden die Prüfung
  und führten in jedem Zyklus zu einer Neuverbindung, bei der auch alle übrigen Variablen ausfielen – sie werden jetzt
  bei der Prüfung abgewiesen.
* **Treiber fins, slmp, toyopuc, kvhostlink:** Lag ein nicht vorhandener oder geschützter Bereich in der Lücke
  zwischen zusammengefassten Variablen, meldeten alle Variablen der Anfrage dauerhaft den Fehler – jetzt werden sie
  einzeln gelesen, nur die wirklich fehlende meldet ihn. Eine zu kurze Antwort führte in jedem Zyklus zu einer
  Neuverbindung; jetzt ist sie ein Fehler dieser Anfrage mit Hinweis auf „Wörter je Anfrage“.
* **Treiber modbus / modbus_rtu:** Lag eine nicht belegte Adresse in der Lücke zwischen zusammengefassten Variablen,
  lehnte das Gerät die ganze Anfrage ab und alle Variablen darin meldeten dauerhaft „ungültige Adresse“ – jetzt werden
  sie einzeln gelesen, und nur die wirklich fehlende meldet den Fehler. Eine zu kurze Antwort (Gerät liefert weniger
  Register als angefragt) führte in jedem Zyklus zu einer Neuverbindung; jetzt ist sie ein Fehler dieser Anfrage mit
  Hinweis auf „Register je Anfrage“. Adressen jenseits von 65535 werden bei der Prüfung abgewiesen (bisher endloses
  Neuverbinden).
* **Treiber opcua:** Der private Schlüssel des selbst erzeugten Client-Zertifikats ist nur noch für den Benutzer des
  Loggers lesbar (0600). Kürzt ein Server die Antwort einer Leseanfrage, statt einen Fehler zu melden, werden die
  fehlenden Knoten mit dem Hinweis gemeldet, „Knoten je Anfrage“ zu verkleinern (bisher still NaN). Bei einem
  Rechnernamen mit mehr als 48 Zeichen ließ sich das selbstsignierte Zertifikat (Treiber und OPC-UA-Server des Loggers)
  nicht erzeugen – der Name im Zertifikat wird jetzt auf die erlaubten 64 Zeichen gekürzt.
* **Treiber ads:** Nach einem Download oder Online-Change, der die Speicheraufteilung änderte, las der Logger über
  die beim Verbinden ermittelten Offsets unbemerkt andere Variablen. Jetzt wird die Symbolversion in jeder
  Summenanfrage mitgelesen; ändert sie sich, verbindet der Treiber neu und löst die Symbole neu auf. Ein Typ, dessen
  Größe nicht zum Symbol passt (z. B. `REAL` für eine `LREAL`-Variable), wird gemeldet statt teilweise gelesen.
* **Treiber clx:** Ein Tag, der beim Verbinden nicht antwortete (CPU im Hochlauf, Programm-Download), blieb bis zum
  nächsten Verbindungsabbruch ungelesen, solange die übrigen Tags liefen. Er wird jetzt alle 30 s im Hintergrund neu
  angelegt und danach wieder mitgelesen.
* **Treiber tia:** War eine Variable nicht mehr lesbar (z. B. nach einer Programmänderung), wurden in jedem Zyklus
  alle Variablen ihrer Anfrage einzeln nachgelesen – bei 50 Variablen je Anfrage 51 statt 1 Anfrage. Jetzt bleibt die
  fehlerhafte Variable aus den Sammelanfragen heraus und wird alle 30 s einzeln probiert. In der Steuerung neu
  angelegte Variablen werden nach einer Neuverbindung gefunden (bisher erst nach einem Neustart des Loggers).
* **Treiber s7:** Einzelvariablen (außerhalb von Blöcken) kosteten je eine Anfrage – 60 Variablen in einem DB
  brauchten 60 Rundreisen je Zyklus. Benachbarte Variablen desselben DBs bzw. Bereichs (Lücke bis 16 Bytes) werden jetzt
  mit einer Anfrage gelesen; schlägt eine solche Gruppe fehl, wird einzeln weitergelesen. Bitnummern 8 und 9
  (z. B. `DB10.DBX0.8`) werden als ungültig gemeldet statt stillschweigend 0 zu liefern.
* **Eigene Treiber:** Ein Treiber mit `@dataclass` (und `from __future__ import annotations`) ließ sich nicht laden.
  Der Treiberordner stand vor den Systemmodulen im Suchpfad – eine Hilfsdatei wie `socket.py` oder `csv.py` ersetzte
  das gleichnamige Modul im ganzen Programm. `sys.exit()` in einem Treiber beendete das Programm. Gleichzeitiges Laden
  (z. B. Webserver und Lese-Thread) konnte kurz „Treiber nicht installiert“ melden.
* **Treiber:** „Verbindung testen“ und der Ringpuffer-Test im Blockeditor zeigten bei einem Fehler beim Schließen der
  Verbindung diesen statt des eigentlichen Ergebnisses bzw. Fehlers. Ein Verbindungsparameter mit „inf“ oder NaN ließ
  das Laden der Konfiguration abbrechen bzw. umging die Grenzen (z. B. Zeitlimit); jetzt gilt die Vorgabe. Auswahlwerte
  werden auch erkannt, wenn sie als Zahl statt als Text gespeichert sind.
* **SVG-Screenshots:** Über mehrere Tage war jeder Teilstrich der Zeitachse mit „00:00“ beschriftet – jetzt mit dem
  Datum (bei Tagesschritten „TT.MM.“). Nach einer Zeitumstellung liegen die Striche wieder auf vollen Stunden. Zeitachse
  von PDF-Bericht und SVG-Export nutzen dieselbe Teilung.
* **Startbild:** Mit einer zuletzt benutzten Konfiguration auf einem nicht erreichbaren Server (`\\Server\…`) erschien
  das Startbild erst nach dem Zeitlimit des Netzwerks je Eintrag – die Änderungszeit wird bei Netzpfaden nicht mehr
  gelesen („Netzlaufwerk“). „Starte …“ und „Lade …“ werden übersetzt.
* **PDF-Berichte:** Die Standardabweichung großer Werte mit kleiner Schwankung (z. B. Zählerstand 10 000 000 ± 0,01)
  war durch Rundungsfehler falsch. In Wochen- und Monatsberichten über die Zeitumstellung lagen die Teilstriche danach
  eine Stunde daneben (ein Tag doppelt beschriftet). Zeichen wie „Δ“, „≥“, „→“ oder „Ω“ erschienen als „?“ – sie
  werden jetzt ersetzt (auch im IO-Check-Protokoll). PNG-Logos mit Transparenz werden deutlich schneller geladen und
  nur einmal je Programmlauf.
* **Aufzeichnung:** Ein Schreibfehler der CSV-Datei (Platte voll, USB-Stick gezogen, Netzlaufwerk weg) oder ein Fehler
  in OPC UA, MQTT oder einem Trigger hielt die ganze Aufzeichnung an – ohne Meldung, die Diagramme froren ein. Jetzt
  kommt eine Meldung, Anzeige und Datenbank laufen weiter, und nach 30 s wird eine neue CSV-Datei angelegt. Verworfene
  Messzyklen (Verarbeitung kommt nicht nach) werden gemeldet. Ein Fehler des Treibers beim Schließen der Verbindung
  beendete das Lesen dieser Steuerung bis zum Neustart. Misslingt das Archivieren, bleibt kein unvollständiges ZIP im
  Archiv liegen. Beim Beenden wartet der Logger bis zu 60 s (bisher 10 s) auf noch nicht gespeicherte Werte.
* **PID-Optimierung:** Der Vorschlag für Soll-, Ist- und Stellwert vergleicht ganze Wörter des Variablennamens – bisher
  wurden z. B. „Spannung“ als Sollwert und „Distanz“ als Istwert vorgeschlagen.
* **OPC-UA-Server:** Der private Schlüssel des selbstsignierten Zertifikats ist nur noch für den Benutzer des Loggers
  lesbar (0600). Dialog und Protokoll weisen darauf hin, wenn sich Web-Benutzer nur über Endpunkte ohne Sicherheit
  anmelden können – die Passwörter gingen dann im Klartext über das Netz.
* **Benachrichtigungen:** Ein fehlgeschlagener Kanal (Netz kurz weg, Mailserver nicht erreichbar) wird nach 30 s, 2 min
  und 10 min erneut versucht, statt die Meldung zu verlieren; die übrigen Kanäle warten nicht darauf. Slack: `<`, `>` und
  `&` im Meldetext werden maskiert (bisher z. B. `<!channel>` als Erwähnung aller). „Testnachricht senden“ läuft im
  Hintergrund (bisher bis zu einer Minute eingefrorenes Fenster).
* **Netzwerk durchsuchen:** Bereiche mit Leerzeichen um den Bindestrich („192.168.0.10 - 50“) werden angenommen;
  „Abbrechen“ wirkt auch während der Gerätekennung (S7-Baugruppe, EtherNet/IP) – bisher lief sie vollständig weiter.
* **Netzwerk-Panel:** Konfigurationen mit `%`, `$` oder `\` im Pfad starten auch als Dienst (systemd las sie bisher als
  Platzhalter bzw. Variablen). Mehrere gleichzeitige Vorgänge (z. B. WLAN-Suche und „WLAN aus“, Logger starten und
  stoppen) melden jeweils ihr Ergebnis – bisher ging das des ersten verloren.
* **MQTT:** Im Format JSON wird ein Wert `inf` (z. B. Division durch 0) als `null` gesendet – bisher blieb die ganze
  Nachricht aus, und jede Sekunde erschien eine Fehlermeldung. Dauerhafte Fehler werden nur noch einmal gemeldet.
  „Verbindung testen“ im MQTT-Dialog läuft im Hintergrund (Fortschrittsanzeige statt eingefrorenem Fenster) und meldet
  eine Zeitüberschreitung als solche.
* **Neue Konfiguration** (Startbild) über eine vorhandene Datei: übernimmt nicht mehr deren Trigger und unbekannte
  Abschnitte – die neue Konfiguration ist wirklich leer.
* **IO-Check auf Smartphone/Tablet:** Die Einheit aus der IO-Liste wird auf der Seite maskiert (bisher konnte ein Eintrag
  mit `<` die Anzeige zerlegen bzw. HTML einschleusen). Die Version der Signalliste ist über alle IO-Check-Fenster
  eindeutig – eine Seite mit der Liste eines anderen Fensters kann keinen Status mehr an ein falsches Signal senden.
* **IO-Check-Fenster:** Kommentare, Symbole und andere Texte aus der IO-Liste mit `<` oder `&` (z. B. „Druck < 5 bar“)
  erscheinen in Tooltips, „zuletzt bewegt“ und Vertauschungshinweis vollständig. Lesen stoppen bzw. nach einer
  Filteränderung neu starten wartet höchstens 0,5 s statt bis zu 2 s je nicht erreichbarer Steuerung.
* **IO-Check, Analog-Prüfpunkte:** Ein Signal wird nur noch automatisch OK, wenn alle drei Punkte 0/50/100 % in Toleranz
  liegen – bisher reichte es, dass sie eingetragen waren (auch ein von Hand übernommener Punkt außerhalb der Toleranz).
  Ein solcher Punkt wird ersetzt, sobald der Wert stabil in Toleranz liegt.
* **IO-Check:** Prüfstand wird mit `fsync` und eigener Temp-Datei gespeichert (Stromausfall); ein Fehler beim Trennen
  beendet den Lese-Thread nicht mehr (bisher wurde danach nie wieder verbunden); die Webseite bekommt die Messpunkte
  als Kopie (gelegentlicher Fehler 500).
* **Sprache wechseln mit Neustart:** Das Programm startet erst neu, nachdem das alte Fenster geschlossen ist (Aufzeichnung
  beendet, Ports frei); wird das Schließen abgelehnt, startet kein zweites Programm mehr.
* **Farbschema:** Zurück auf „Wie das System“ stellt den Stil des Systems sofort wieder her (bisher blieb die Oberfläche
  nach „Dunkel“ bis zum Neustart dunkel, wenn Qt das Schema nicht selbst umschalten konnte).
* **Im Diagramm zeigen** (Ereignisprotokoll): CSV- und Archivdateien werden auch gefunden, wenn der CSV-Name Leerzeichen,
  Umlaute, Punkte oder Klammern enthält, und auch Dateien mit Zusatz `_1` (zwei Aufzeichnungen in derselben Sekunde).
* **PDF-Bericht** aus dem Hauptfenster: wird im Hintergrund erstellt (Fortschrittsanzeige statt eingefrorenem Fenster).
* **Hauptfenster:** Stoppen der Aufzeichnung, Laden von CSV/ZIP und aus der Datenbank sowie Export und Speichern laufen
  im Hintergrund mit Fortschrittsanzeige – das Fenster friert nicht mehr ein („Keine Rückmeldung“). Lineale ziehen
  ruckelt bei vielen Messpunkten nicht mehr (Kennwerte gebündelt berechnet). Geladene Daten werden auch ohne lesbare
  Konfigurationsdatei angezeigt.
* **Aufzeichnung starten:** Scheitert der Start mittendrin (z. B. OPC-UA-Server, Benachrichtigungen), werden bereits
  gestartete Teile (Datenbank-Thread, CSV-Datei) wieder beendet und der Fehler gemeldet; bisher blieben sie offen und
  das Fenster zeigte „Stop“.
* **Datenbank:** Beim Stoppen nicht geschriebene Werte werden nur noch einmal gemeldet.
* **Grafana-Dashboard:** Tabellennamen mit Großbuchstaben funktionieren bei TimescaleDB und InfluxDB 3 (bisher „Tabelle
  nicht gefunden“); bei QuestDB und InfluxDB 3 zeigen Aufzeichnungen ohne Projektnamen wieder Werte; ein `'` im
  Projektnamen zerlegt die SQL-Abfragen nicht mehr. Die Projektauswahl durchsucht bei SQL-Datenbanken nur noch den
  angezeigten Zeitraum statt bei jedem Öffnen die ganze Tabelle. Bereits importierte Dashboards bitte neu erzeugen.
* **Formeleditor:** Fehlermeldungen und Variablennamen mit `<` oder `&` werden korrekt angezeigt. Variablennamen
  mit `{` oder `}` werden abgelehnt (im Formeleditor und beim Speichern der Konfiguration) – solche Variablen ließen
  sich in Formeln, Triggern und Meldetexten nicht ansprechen.
* **Datei- und Ordnerdialoge:** Ein vorgeschlagener oder gemerkter Ordner auf einem nicht erreichbaren Netzlaufwerk
  lässt den Dialog nicht mehr bis zum Zeitlimit warten; beim Kürzen der gemerkten Ordner bleiben die zuletzt benutzten.
* **Formeln:** Sehr lange bzw. tief verschachtelte Formeln (z. B. Summe aus Hunderten Gliedern) ergeben eine Meldung statt
  eines Absturzes im Formeleditor bzw. beim Start der Aufzeichnung. `avg(x, n)` rechnet mit laufender Summe – große
  Fenster kosten keine Rechenzeit mehr je Takt.
* **Berechnete Variablen** werden immer als REAL gespeichert. Bisher konnten sie den Typ einer Steuerungsvariable
  tragen (z. B. INT nach dem Import der Variablenliste bei LOGO/PCCC) – die Aufzeichnungs-CSV und der Export schnitten
  dann die Nachkommastellen ab, beim Downsampling zählte eine Formel mit Typ BOOL als Schaltsignal.
* **Werte exportieren:** `inf` (z. B. Division durch 0 in einer Formel) bleibt in Excel leer – die Datei galt sonst als
  beschädigt; bei Ganzzahltypen bricht auch die CSV nicht mehr ab. Downsampling „Erster/Letzter Wert“ übergeht
  fehlende Werte im Intervall.
* **Tabellen importieren (CSV):** Dateien, die Excel unter Windows als „CSV (Trennzeichen-getrennt)“ speichert
  (Windows-1252), werden gelesen; Felder mit Zeilenumbruch bleiben ganz.
* **Ereignisprotokoll:** Schreiben Logger und Viewer (anderer Prozess oder Rechner) in dieselbe Datei, entstehen keine
  doppelten IDs mehr, und eine fremde Quittierung geht durch einen eigenen Eintrag nicht mehr verloren; fremde
  Änderungen werden auch innerhalb derselben Zeitstempel-Auflösung erkannt. Die Datei wird nur noch nach fremden
  Änderungen neu eingelesen (bisher bei jedem Abruf – träge bei großen Protokollen, vor allem auf dem Pi).
* **Trigger:** Ist das Ereignisprotokoll nicht beschreibbar, erscheint die Meldung höchstens einmal je Minute (bisher bei
  jeder Messzeile), und die übrigen Trigger werden weiter ausgewertet. Eine ungültige Verzögerung in der
  Konfigurationsdatei verhindert nicht mehr das Laden.
* **Ereignis-Viewer:** Spaltenbreiten werden nur aus den neuesten 300 Zeilen bestimmt – kein Stocken mehr bei großen
  Protokollen; Spaltenkopf „Nr.“ wird übersetzt.
* **Datenbank (MariaDB, TimescaleDB):** Zeitlimit je Anfrage (120 s) und TCP-Keepalive – ein hängender Server oder
  eine still abgerissene Verbindung hielt den Schreib-Thread bisher unbegrenzt fest (Anzeige weiter „Verbunden“, Puffer
  lief voll).
* **Datenbank:** Schreibdurchlauf auf 50 Stapel begrenzt, damit Ereignisse und Aufräumen auch bei großem Rückstand
  drankommen; beim Beenden nicht mehr geschriebene Werte werden gemeldet. Pufferobergrenze auf Rechnern mit wenig
  Hauptspeicher (Raspberry Pi) höchstens etwa 10 % des RAM.
* **SQLite:** `synchronous=NORMAL` im WAL-Modus – kein fsync bei jedem Commit (schont die SD-Karte).
* **Aus Datenbank laden:** Werte in kompakten Feldern gesammelt (bisher rund 120 Byte je Wert – der Speicherschutz griff
  zu spät); „Abbrechen“ unterbricht bei SQLite und PostgreSQL auch eine laufende Abfrage; Schließen während des Ladens
  lässt keine späten Meldungen mehr erscheinen und schließt die Verbindung; SQLite-Dateien in Ordnern mit `%` oder `#`
  im Namen werden gefunden.
* **CSV/ZIP zusammenfügen:** Dateien werden blockweise in numpy-Felder gelesen (etwa ein Viertel des Speichers – große
  Tagesdateien führten auf dem Pi zum Speichermangel); bei gleichem Zeitpunkt in mehreren Dateien bleiben die Werte
  aller Variablen erhalten (bisher nur die der ersten Datei).
* **Konfiguration speichern:** Einstellungen, Steuerungen, Variablen, Blöcke **und Trigger** in einem Schreibvorgang
  (bisher zwei – ein Abbruch dazwischen verlor die Trigger); unbekannte Abschnitte und Einstellungen (z. B. aus einer
  neueren Version) bleiben erhalten; Schreiben mit `fsync` und eigener Temp-Datei (Stromausfall am Pi, mehrere
  Programme gleichzeitig); neue Dateien nur für den Besitzer lesbar (Passwörter für Datenbank/MQTT).
* **Persönliche Einstellungen:** gleichzeitiges Schreiben mehrerer Programme konnte die Datei zerstören – danach waren
  alle Einstellungen weg; jetzt atomar, eine beschädigte Datei wird als `.defekt` beiseitegelegt.
* **Konfigurationsprogramm:** „Verbindung testen“ liest im Hintergrund (das Fenster fror bei nicht erreichbaren
  Steuerungen ein); Speichern mit eingeschaltetem Webserver ohne Benutzer und Zugriffscode fragt nach und bietet einen
  zufälligen Zugriffscode an; eine ungültige Zahl in der Konfiguration nennt den Schlüssel.
* **Client:** Verbinden im Hintergrund – der Dialog friert bei falscher Adresse nicht mehr ein.
* **Startbild:** zuletzt benutzte Dateien auf nicht erreichbaren Netzlaufwerken verzögern den Start nicht mehr.
* **Aufräumen (CSV/Archiv):** löscht nur noch Dateien mit dem eigenen Namensschema `<CSV-Name>_JJJJMMTT_hhmmss…` –
  ein Logger „Anlage“ traf bisher auch die Dateien eines Loggers „Anlage_Halle2“ im selben Ordner; ungültiger CSV-Name
  oder leerer Ordner löscht nichts; ganz frische Dateien bleiben; wären nach Alter alle Dateien fällig (Uhr vorgestellt,
  Logger lange aus), bleibt die jüngste.
* **Client:** Ereignisse werden im Abfrage-Thread geladen statt in der Oberfläche (die bei nicht erreichbarem Server bis
  zu 10 s hing); Schließen wartet nicht mehr bis zu 12 s; nach drei fehlgeschlagenen Anmeldungen endet die Abfrage;
  Umleitungen auf andere Adressen werden abgelehnt (Zugriffscode); Benutzer:Passwort aus der Adresse erscheint nicht
  mehr in Titel und Statuszeile; Antworten sind auf 256 MB begrenzt; Hinweis im Dialog, wenn Anmeldedaten ohne HTTPS
  übertragen würden.
* **Block testen:** liest im Hintergrund – der Dialog friert bei nicht erreichbarer Steuerung nicht mehr ein; lange
  Fehlerlisten werden gekürzt; gelöschte Blöcke verschwinden sofort aus dem Baum; im Baum ist nur der Name änderbar.
* **XY/FFT:** „Werte speichern“ schreibt keine Werte einer früheren Auswahl mehr; Zeiten in der CSV auf die Millisekunde
  genau (bisher 9 Stellen); „Alle Daten“ + „Aktualisieren“ holt auch neu aufgezeichnete Werte; FFT sortiert Zeiten,
  wertet bei Lücken den längsten lückenlosen Abschnitt aus und begrenzt die Punktzahl (Speicher auf dem Pi); große
  Spektren werden ausgedünnt gezeichnet; Dialoge werden beim Schließen freigegeben.
* **Hilfe/Über:** Lizenzdateien in anderer Kodierung verhindern den Dialog nicht mehr; F1-Weiterleitung je Benutzer;
  neueste Anleitung nach Versionsnummer (3.10 nach 3.9); „Über …“ und Fenster mit F1 werden freigegeben.
* **Gebündelte Linux-Fassungen:** Links, Anleitung und Ordner öffnen über `xdg-open` mit bereinigter Umgebung – Browser
  und PDF-Anzeige erbten sonst die mitgelieferten Bibliotheken; die Startprotokoll-Datei eines aus einem anderen
  Programm gestarteten Programms wächst nicht mehr (Ausgabe nach 10 s umgeleitet), kein Zombie-Prozess.

## [3.24.0] – 2026-11-17

### Neu

* **IO-Check:** Spalte **Ort** (Import aus „Ort“, „Ortskennzeichen“, „Einbauort“, „Location“ …; bearbeitbar, im
  Ergebnis-Export, in der Zusammenfassung des Protokolls und am Smartphone).
* **IO-Check:** Spalten der Signalliste per Haken **ein- und ausblenden** (Pfeil am Knopf *Spalten …* oder Rechtsklick
  auf die Überschrift; persönliche Einstellung).
* **IO-Check:** **Kurzbericht (PDF)** – nur die Zusammenfassung mit Fortschrittsbalken gesamt, je Signalart, Gruppe und
  Ort (Pfeil am Knopf *Protokoll (PDF) …*).
* **IO-Check:** Signalton wahlweise als **Dauerton bei 1** wie ein Durchgangsprüfer – am PC (Seitenleiste
  *Signalton*: aus / bei richtigem Wechsel / Dauerton) und auf dem Smartphone (🔕 → 🔔 → 🔊).

### Geändert

* **IO-Check:** Die Importspalten „Ort“ und „Ortskennzeichen“ füllen jetzt das neue Feld *Ort* statt *Gruppe*; das
  Ergebnis-Export (CSV/Excel) hat die zusätzliche Spalte *Ort*.
* **Anleitung, Raspberry Pi:** Hinweis zur Stromversorgung, wenn der Touch nicht reagiert oder zeitweise ausfällt
  (Netzteil 5,1 V/3 A, Prüfen mit `vcgencmd get_throttled`).

## [3.23.0] – 2026-11-13

### Neu

* **IO-Check:** Tag-Export aus **Studio 5000** (CSV) direkt als IO-Liste importieren – Alias-Tags auf E/A-Kanäle
  werden Signale (Adresse = Kanal, Symbol = Alias, Kommentar = Beschreibung des Alias, Gruppe = Baugruppe); Diagnose-
  Aliase und interne Tags entfallen.

### Geändert

* **IO-Check:** Analogsignale mit Datentyp REAL/LREAL ohne Rohwert-Umrechnung (Rohwert = technischer Wert) statt
  0 … 27648.

## [3.22.0] – 2026-11-13

### Neu

* **IO-Check, Allen-Bradley:** Modul-Tags der E/A-Baugruppen (`Local:1:I.Data.0`, `Local:3:I.Ch0Data`,
  `Rack2:3:O.Data.5` …) werden erkannt – Eingang/Ausgang, digital/analog ergeben sich aus dem Namen.
* **IO-Check:** Rohwert von Analogsignalen auch hexadezimal (`16#6C00`) und binär (`2#0110_1100_…`) – im Feld
  *Analogwert* alle drei Darstellungen, in der Signalliste umschaltbar (*Rohwert in der Liste*); für Analogwerte mit
  Diagnosebits.

### Behoben

* **Treiber clx:** Modul-Tags mit Steckplatz (`Local:1:I.Data`, `Rack2:3:O.Ch0Data`) wurden als ungültiger Tag-Name
  abgewiesen.

## [3.21.0] – 2026-11-12

### Neu

* **IO-Check:** Spalte **Nr.** (Zeilennummer in der Reihenfolge der IO-Liste, sortierbar); **Alle markieren** im
  Rechtsklick-Menü (Strg+A); Zurücksetzen mehrerer Signale mit Rückfrage – z. B. für eine neue Prüfrunde.

### Geändert

* **IO-Check:** **Zurücksetzen** löscht auch die Bemerkung; bei **Wiederholen** bleibt sie erhalten.

## [3.20.0] – 2026-11-11

### Neu

* **IO-Check:** Signalliste nach jeder Spalte sortieren – Adressen natürlich (`E0.2` vor `E0.10`), Status in
  Prüfreihenfolge, Werte als Zahl – und filtern: Rechtsklick auf die Spaltenüberschrift (Text enthält … und/oder
  Auswahl der vorkommenden Werte); gefilterte Spalten sind markiert, der Fortschritt zeigt die Anzahl angezeigter Signale.
* **IO-Check:** **Nur angezeigte lesen** (Werkzeugleiste, im Prüfstand gespeichert) – gelesen werden nur die Signale,
  die die Filter zeigen; bei geänderten Filtern startet das Lesen mit der neuen Auswahl neu.
* **IO-Check:** neuer Status **wiederholen** (Strg+4, orange ↻) für Signale, die erneut geprüft werden müssen – zählt
  nicht als geprüft, steht im Protokoll bei den offenen Signalen, wird wieder automatisch abgehakt; auch am Smartphone.
* **IO-Check:** **＋ Signal …** legt Signale von Hand an (Adresse, Texte, Typ aus der Adresse, Messbereich).
  Rechtsklick in die Signalliste: Status, Signal hinzufügen, Scan-Signale **in die IO-Liste übernehmen**, Signale
  **aus der IO-Liste entfernen**.
* **IO-Check:** optionaler **Signalton**, wenn das gewählte Digitalsignal 0→1→0 bzw. 1→0→1 gewechselt hat – am PC
  (Seitenleiste „Was hat sich bewegt?“) und auf dem Smartphone (🔔 oben rechts).

## [3.19.0] – 2026-11-11

### Neu

* **IO-Check:** „Was hat sich bewegt?“ meldet mit **Nur offene Signale** (Vorgabe an, im Prüfstand gespeichert) keine
  Wechsel von Signalen mit Status OK, Fehler oder übersprungen mehr – z. B. ein ständig springender Analogwert stört
  nach „übersprungen“ nicht mehr. Das gewählte Signal wird immer gemeldet (Wunsch aus dem SPS-Forum).

### Geändert

* **Teststand** in Anleitung, README und Webseite: Treiber `logo` an einer echten LOGO! 8.4 erfolgreich getestet – digitale Eingänge (I3–I6, I9–I12)
  und Analogeingang AI1 (Rückmeldung aus dem SPS-Forum).

## [3.18.1] – 2026-11-09

### Behoben

* **Netzwerk-Panel:** startete auf einer frischen Ubuntu-Installation nicht („Failed to load EGL device integration
  eglfs_kms“, „Could not open display“, Abbruch in Schleife), weil libgbm/libdrm fehlten. Das Debian-Paket hängt jetzt
  von `libgbm1` und `libdrm2` ab; fehlen sie trotzdem, nimmt das Panel `linuxfb`. Ursache war auch das fehlende
  Qt-Plugin `egldeviceintegrations/libqeglfs-kms-integration.so`: es wird jetzt mit ins Paket gepackt, und fehlt es,
  nimmt das Panel ebenfalls `linuxfb`.
* **MQTT:** automatische Client-IDs mit Zufallsteil – zwei Clients desselben Rechners konnten sich beim Broker
  gegenseitig abmelden.

### Geändert

* **Anleitung, Raspberry Pi:** Remotedesktop (XFCE und xrdp) ist jetzt Schritt 3, direkt nach der Grundeinrichtung –
  die weiteren Schritte lassen sich so schon in der Remotesitzung erledigen.

## [3.18.0] – 2026-11-09

### Neu

* **IO-Check:** automatisches Speichern ein-/ausschaltbar (Pfeil am Knopf *Speichern*, Vorgabe an, gemerkt);
  ausgeschaltet wird erst mit „Speichern“ gesichert, beim Schließen kommt die Rückfrage.

## [3.17.0] – 2026-11-08

### Neu

* **MQTT-Ausgang:** Werte an einen MQTT-Broker senden (wie Webserver und OPC-UA-Server optional, auch headless) –
  ein Topic je Variable und/oder ein JSON mit allen Werten, bei Änderung oder zyklisch, Ereignisse und
  Verbindungszustand, letzter Wille „offline“, TLS und Anmeldung, **Home-Assistant-Discovery**. Einstellungen im
  Konfigurationsprogramm, Reiter *Webserver & Headless*, **MQTT …** (mit „Verbindung testen“).
* **Treiber `mqtt`:** Werte von einem MQTT-Broker aufzeichnen – Topic als Adresse, Zahlen auch aus JSON-Nachrichten
  (`tele/sonoff/SENSOR|AM2301.Temperature`), „true/on/ein“ als 1, Höchstalter für ausgefallene Sender; **Topics vom
  Broker …** hört mit und bietet die empfangenen Werte zur Auswahl an. Bibliothek: paho-mqtt.

### Build

* **AppImage:** appimagetool und die AppImage-Laufzeit werden mit Wiederholung geladen (zeitweise Antwort 504 von
  GitHub ließ den Release-Build scheitern), ersatzweise eine feste appimagetool-Version; die Laufzeit wird
  appimagetool als Datei übergeben. Ein Nachbau von Hand (*AppImages › Run workflow* mit Tag) nimmt das Build-Skript
  des gestarteten Stands.

## [3.16.0] – 2026-11-08

### Neu

* **IO-Check: Fotos zu Signalen** – am Smartphone/Tablet direkt mit der Kamera (📷 Foto) oder aus der Galerie, im
  Browser auf 1600 Pixel verkleinert; am PC über **Fotos …** bzw. Doppelklick in die neue Spalte *Fotos* (hinzufügen,
  öffnen, entfernen). Die Bilder liegen im Ordner `<Prüfstand>_fotos` neben der Prüfstand-Datei (*Speichern unter*
  kopiert sie mit, *Liste aktualisieren* übernimmt sie). Das Abnahmeprotokoll verweist in der Bemerkung darauf und
  hängt sie an (*Fotos anhängen* im Menü des Protokoll-Knopfs, abschaltbar). Wunsch aus dem SPS-Forum.

### Behoben

* **IO-Check im Webserver:** Benutzer mit Recht *lesen* konnten auf der Mobilseite Status, Bemerkungen und Messpunkte
  ändern – jetzt nur noch Anzeige (Befehle und Fotos werden mit 403 abgewiesen, die Knöpfe ausgeblendet).

## [3.15.0] – 2026-11-06

### Neu

* **Dateidialoge merken sich den Ordner:** Speichern-, Öffnen- und Ordnerdialoge aller Programme öffnen im zuletzt
  benutzten Ordner (je Dialog, sonst der zuletzt überhaupt benutzte) statt immer im Programm- bzw. Datenordner.
  Wunsch aus dem SPS-Forum.
* **IO-Check:** geänderte IO-Liste **aktualisieren** – der zweite Import übernimmt neue Texte, BMK, Messbereiche, neue
  und entfallene Signale und behält Status, Prüfer, Bemerkung und Messpunkte gleicher Adressen (bisher nur Ersetzen
  ohne Prüfeinträge oder Ergänzen). Adresse, Symbol, Kommentar, BMK und Gruppe sind außerdem direkt in der Tabelle
  änderbar (neue Adresse: Prüfung auf doppelte, Frage, ob der Prüfeintrag zurückgesetzt wird).
  Wunsch aus dem SPS-Forum.

### Behoben

* **IO-Check:** bearbeitete Signale aus Scan-Bereichen (Status, Bemerkung) wurden nicht mit dem Prüfstand gespeichert
  und fehlten nach dem erneuten Öffnen.

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

[Unveröffentlicht]: ../../compare/v3.24.0...HEAD
[3.24.0]: ../../releases/tag/v3.24.0
[3.23.0]: ../../releases/tag/v3.23.0
[3.22.0]: ../../releases/tag/v3.22.0
[3.21.0]: ../../releases/tag/v3.21.0
[3.20.0]: ../../releases/tag/v3.20.0
[3.19.0]: ../../releases/tag/v3.19.0
[3.18.1]: ../../releases/tag/v3.18.1
[3.18.0]: ../../releases/tag/v3.18.0
[3.17.0]: ../../releases/tag/v3.17.0
[3.16.0]: ../../releases/tag/v3.16.0
[3.15.0]: ../../releases/tag/v3.15.0
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
