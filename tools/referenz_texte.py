# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Texte des Kapitels „Referenz“ der Bedienungsanleitung (siehe ``tools/make_referenz.py``).

Die Bezeichnungen der Bedienelemente und ihre Tooltips stammen aus der Mitschrift der Fenster (``doc/referenz/``,
erzeugt vom Workflow *UI-Referenz*) – hier stehen nur die Abschnitte und die Beschreibungen für Elemente ohne (oder mit
zu knappem) Tooltip, jeweils deutsch und englisch. Schlüssel ist der deutsche Text des Elements.

``D[Klasse][deutscher Text] = (deutsch, englisch)`` – ``None`` = Element nicht aufführen. Kommt derselbe Text in einem
Fenster mehrfach vor, darf der Wert eine Liste mit je einem Paar je Vorkommen sein.
"""

# Überall ausgelassen (selbsterklärend bzw. in den Feldern beschrieben)
SKIP = {"OK", "Abbrechen", "Schließen", "…"}

# Zusammenfassen: ankreuzbare Untermenüs ohne Tooltip werden zu einer Zeile („Anordnung › A / B / C“)

D = {}

D["MainWindow"] = {
    "Konfiguration neu laden": ("Konfigurationsdatei neu einlesen und die Diagramme neu aufbauen; eine laufende "
                                "Aufzeichnung wird vorher beendet",
                                "Read the configuration file again and rebuild the charts; a running recording is "
                                "stopped first"),
    "Verbindung trennen (eigene Konfiguration)": ("Betriebsart Client beenden und wieder die eigene Konfiguration "
                                                  "verwenden",
                                                  "Leave client mode and use the own configuration again"),
    "CSV laden": ("Eine oder mehrere Aufzeichnungen (CSV/ZIP) offline anzeigen; mehrere Dateien werden nach der Zeit "
                  "aneinandergehängt",
                  "Show one or more recordings (CSV/ZIP) offline; several files are joined by time"),
    "Webserver-Adresse …": ("Adresse des Webservers mit QR-Code anzeigen (zum Öffnen am Smartphone oder Tablet)",
                            "Show the web server address with a QR code (to open it on a smartphone or tablet)"),
    "Startbild beim Programmstart zeigen": ("Beim nächsten Start das Startbild mit den zuletzt benutzten "
                                            "Konfigurationen zeigen",
                                            "Show the start screen with the recently used configurations at the "
                                            "next start"),
    "Beenden": ("Logger schließen; eine laufende Aufzeichnung wird beendet (und bei gesetzter Option archiviert)",
                "Close the logger; a running recording is stopped (and archived if the option is set)"),
    "Anordnung": ("Anordnung der Seiten im Fenster", "Arrangement of the pages in the window"),
    "Diagramme auf der Seite": ("Anordnung der Diagramme innerhalb einer Seite", "Arrangement of the charts on a page"),
    "Raster-Spalten": ("Spaltenzahl bei der Anordnung „Raster“ (automatisch aus der Zahl der Diagramme oder fest)",
                       "Number of columns for the “Grid” arrangement (automatic from the number of charts, or fixed)"),
    "Seiten / Diagramme": ("Einzelne Seiten ein- oder ausblenden", "Show or hide individual pages"),
    "Werteanzeige": ("Wertetabelle rechts ein- oder ausblenden", "Show or hide the value table on the right"),
    "Balken": ("Balken für die Aktualwerte neben den Diagrammen ein- oder ausblenden",
               "Show or hide the bars with the current values next to the charts"),
    "Heller Hintergrund (für Berichte/Druck)": ("Screenshots mit weißem Hintergrund und dunkler Schrift",
                                                "Screenshots with a white background and dark text"),
    "▶ Start": ("Aufzeichnung starten; während sie läuft: **■ Stop** beendet sie",
                "Start the recording; while it runs, **■ Stop** ends it"),
    "Offline": ("Anzeige einfrieren und in der Aufzeichnung zurückblättern (Lineale, Kennwerte); erneut drücken: "
                "wieder online",
                "Freeze the display and scroll back through the recording (rulers, statistics); press again to go "
                "back online"),
    "Lineale zurücksetzen": ("Beide Lineale auf ein und zwei Drittel des sichtbaren Zeitbereichs setzen",
                             "Put both rulers at one and two thirds of the visible time range"),
}
# Menü Screenshot / Analyse: Einträge je Diagramm (werden im Generator zu einer Zeile zusammengefasst)
CHART_ENTRY = {"screenshot": (("*Diagramm* …", "*Chart* …"),
                              ("Dieses Diagramm als PNG oder SVG speichern", "Save this chart as PNG or SVG")),
               "pid": (("PID-Optimierung: *Diagramm* …", "PID tuning: *chart* …"),
                       ("PID-Parameter für den Regelkreis dieses Diagramms berechnen (im Konfigurationsprogramm beim "
                        "Diagramm eingeschaltet)",
                        "Calculate PID parameters for the control loop of this chart (enabled for the chart in the "
                        "configuration program)"))}

# Weitere Bedienelemente des Hauptfensters (nicht in der Mitschrift: Eingabefelder, Statusleiste, Maus)
MAIN_EXTRA = [
    (("Fenster [s]", "Window [s]"),
     ("Breite des sichtbaren Zeitbereichs in Sekunden (1 bis 604800)",
      "Width of the visible time range in seconds (1 to 604800)")),
    (("Zeit-Scrollleiste", "Time scroll bar"),
     ("Offline: durch die Aufzeichnung blättern (verschiebt alle Diagramme gemeinsam)",
      "Offline: scroll through the recording (moves all charts together)")),
    (("Statusleiste", "Status bar"),
     ("Je Steuerung eine LED mit dem Verbindungszustand (Tooltip: Meldung und Zykluszeit), Meldungen und Pfad der "
      "CSV-Datei",
      "One LED per PLC with the connection state (tooltip: message and cycle time), messages and path of the CSV "
      "file")),
]
MOUSE = [
    (("Mausrad", "Mouse wheel"),
     ("Zeitachse des Diagramms unter dem Mauszeiger zoomen", "Zoom the time axis of the chart under the mouse "
                                                             "pointer")),
    (("Linke Maustaste ziehen", "Drag with the left mouse button"),
     ("Zeitachse verschieben; mit **Zoom-Rechteck**: Bereich aufziehen und vergrößern",
      "Move the time axis; with **Zoom rectangle**: drag a range and zoom in")),
    (("Rechte Maustaste ziehen", "Drag with the right mouse button"),
     ("Zoomen (Zeit- bzw. Y-Achse)", "Zoom (time or Y axis)")),
    (("Lineal ziehen (offline)", "Drag a ruler (offline)"),
     ("Zeitpunkt der Lineale 1 und 2 verschieben; die Wertetabelle zeigt die Werte und die Kennwerte dazwischen",
      "Move rulers 1 and 2; the value table shows the values and the statistics between them")),
    (("Rechtsklick auf einen Namen der Legende", "Right-click on a name in the legend"),
     ("Kurve aus- bzw. einblenden; alle Kurven des Diagramms wieder einblenden",
      "Hide or show the curve; show all curves of the chart again")),
    (("Rechtsklick im Diagramm", "Right-click in the chart"),
     ("Menü des Diagramms (Achsen, Export); bei eingeschalteter PID-Optimierung auch **PID-Regler optimieren …**",
      "Chart menu (axes, export); with PID tuning enabled also **Tune PID controller …**")),
]
D["MainWindow"]["Variable, Lineal 1, Lineal 2, Δ (L2 − L1), Minimum, Maximum, Mittelwert, Std.-Abw."] = (
    "Wertetabelle: online der aktuelle Wert, offline die Werte an beiden Linealen, ihre Differenz und Minimum, "
    "Maximum, Mittelwert und Standardabweichung dazwischen",
    "Value table: online the current value, offline the values at both rulers, their difference and minimum, "
    "maximum, mean and standard deviation between them")
D["MainWindow"]["🔔 4 offen"] = ("Zahl der offenen (nicht quittierten) Ereignisse; Klicken öffnet das Ereignisprotokoll",
                                 "Number of open (unacknowledged) events; click to open the event log")

D["Common"] = {
    "Deutsch (de)": ("Sprache der Oberfläche; das Programm startet dafür neu",
                     "Language of the user interface; the program restarts for this"),
    "Farbschema": ("Hell, dunkel oder wie das System", "Light, dark or like the system"),
    "Bedienungsanleitung": ("Diese Anleitung öffnen; **F1** öffnet sie an der Stelle, die zum aktuellen Fenster passt",
                            "Open this manual; **F1** opens it at the section that matches the current window"),
    "Über PLC Datenlogger …": ("Version, Copyright, Lizenz, Lizenzen der Drittkomponenten und Versionen der "
                               "Bibliotheken",
                               "Version, copyright, licence, third-party licences and library versions"),
}

D["StartWindow"] = {
    "Öffnen": ("Markierte, zuletzt benutzte Konfiguration öffnen", "Open the selected, recently used configuration"),
    "Durchsuchen …": ("Konfigurationsdatei auswählen", "Choose a configuration file"),
    "Neue Konfiguration …": ("Dateinamen wählen, eine leere Konfiguration anlegen und das Konfigurationsprogramm "
                             "öffnen",
                             "Choose a file name, create an empty configuration and open the configuration program"),
    "Beim Start nicht mehr anzeigen (zuletzt benutzte Datei öffnen)": (
        "Startbild künftig überspringen (wieder einschalten: Logger › Datei › Startbild beim Programmstart zeigen)",
        "Skip the start screen from now on (switch it on again: logger › File › Show start screen at program "
        "start)"),
}

D["ConfigWindow"] = {
    "Neu": ("Neue, leere Konfiguration (ungespeicherte Änderungen werden vorher abgefragt)",
            "New, empty configuration (unsaved changes are asked about first)"),
    "Öffnen …": ("Konfigurationsdatei öffnen", "Open a configuration file"),
    "Speichern": [("Konfiguration speichern", "Save the configuration"),
                  ("Wie Menü Datei › Speichern", "Same as File › Save")],
    "Speichern unter …": ("Unter neuem Namen speichern", "Save under a new name"),
    "INI-Datei umwandeln …": ("Konfiguration einer älteren Version (INI) in das JSON-Format umwandeln",
                              "Convert a configuration of an older version (INI) to the JSON format"),
    "Logger mit dieser Konfiguration starten": ("Logger mit der gespeicherten Konfiguration starten",
                                                "Start the logger with the saved configuration"),
    "IO-Check mit dieser Konfiguration starten": ("IO-Check mit den Steuerungen dieser Konfiguration öffnen",
                                                  "Open the IO check with the PLCs of this configuration"),
    "Headless-Logger anzeigen/beenden …": ("Laufende Headless-Logger anzeigen und sauber beenden",
                                           "Show running headless loggers and stop them cleanly"),
    "Grafana-Dashboard exportieren …": ("Dashboard für Grafana (JSON) passend zu Diagrammen und Datenbank erzeugen",
                                        "Create a Grafana dashboard (JSON) matching the charts and the database"),
    "Beenden": ("Konfigurationsprogramm schließen (ungespeicherte Änderungen werden abgefragt)",
                "Close the configuration program (unsaved changes are asked about)"),
    "Installierte Treiber …": ("Liste der Treiber mit Zustand (z. B. fehlende Bibliothek)",
                               "List of drivers with their state (e.g. missing library)"),
    "Ordner für eigene Treiber öffnen …": ("Ordner öffnen, in den eigene Treiberdateien gelegt werden",
                                           "Open the folder for your own driver files"),
    # Projekt & Steuerungen
    "Name, Treiber, Verbindung, Intervall, Aktiv": (
        "Steuerungen: Name, Treiber, Verbindung (**…** öffnet die Verbindungseinstellungen), Leseintervall und ob sie "
        "gelesen wird",
        "PLCs: name, driver, connection (**…** opens the connection settings), read interval and whether it is read"),
    "+ Steuerung": ("Weitere Steuerung anlegen", "Add another PLC"),
    "Steuerung entfernen": ("Markierte Steuerung löschen", "Delete the selected PLC"),
    # Aufzeichnung
    "CSV-Ordner": ("Ordner für die CSV-Dateien der Aufzeichnung", "Folder for the CSV files of the recording"),
    "Archiv-Ordner": ("Ordner für die gepackten (ZIP) älteren Dateien", "Folder for the packed (ZIP) older files"),
    "Startbedingung": ("Bedingung für „Aufzeichnung per Trigger“ (Formel; **…** öffnet den Formeleditor), dazu "
                       "Vor- und Nachlaufzeit",
                       "Condition for “recording by trigger” (formula; **…** opens the formula editor), plus pre- and "
                       "post-trigger time"),
    "Beim Beenden des Loggers die aktuelle CSV-Datei archivieren": (
        "Beim Beenden die laufende CSV-Datei packen und ins Archiv verschieben",
        "On exit, pack the current CSV file and move it to the archive"),
    # Anzeige
    "Anzeigefenster (online)": ("Breite des sichtbaren Zeitbereichs nach dem Start in Sekunden",
                                "Width of the visible time range after the start, in seconds"),
    "Standard-Anordnung der Seiten": ("Untereinander, nebeneinander oder als Tabs (im Logger über Ansicht änderbar)",
                                      "Stacked, side by side or as tabs (changeable in the logger via View)"),
    "Diagramme auf einer Seite": ("Anordnung der Diagramme einer Seite: untereinander, nebeneinander oder Raster",
                                  "Arrangement of the charts on a page: stacked, side by side or grid"),
    "Logo": ("Eigenes Logo für Berichte und Fenster (Bilddatei)", "Own logo for reports and windows (image file)"),
    "Kundenlogo": ("Zweites Logo (z. B. des Kunden) für Berichte", "Second logo (e.g. of the customer) for reports"),
    "Programm-Icon": ("Eigenes Symbol für Fenster und Taskleiste", "Own icon for windows and the taskbar"),
    "Balken für Aktualwerte anzeigen": ("Balken neben den Diagrammen beim Start einblenden",
                                        "Show the bars next to the charts at the start"),
    # Webserver & Headless
    "Webserver starten (Diagramme im Browser, z. B. mit Tablet/Smartphone)": (
        "Webserver während der Aufzeichnung starten", "Start the web server during the recording"),
    "Port": ("TCP-Port des Webservers (z. B. 8080)", "TCP port of the web server (e.g. 8080)"),
    "Aktualisierung im Browser": ("Wie oft der Browser neue Werte holt", "How often the browser fetches new values"),
    "Headless-Logger": ("Laufende Headless-Logger anzeigen und beenden", "Show and stop running headless loggers"),
    "OPC-UA-Server": ("Zustand und Einstellungen des OPC-UA-Servers (Knopf **OPC UA …**)",
                      "State and settings of the OPC UA server (button **OPC UA …**)"),
    "MQTT": ("Zustand und Einstellungen von MQTT (Knopf **MQTT …**)",
             "State and settings of MQTT (button **MQTT …**)"),
    "Zertifikat (PEM)": ("Eigenes Zertifikat für HTTPS (leer = selbstsigniert)", "Own certificate for HTTPS (empty = "
                                                                                 "self-signed)"),
    "Schlüssel (PEM)": ("Privater Schlüssel zum Zertifikat", "Private key of the certificate"),
    "Anmeldung": ("Benutzer mit Passwort (Knopf **Benutzer …**) oder Zugriffscode",
                  "Users with password (button **Users …**) or access code"),
    # Datenbank
    "Datenbank": ("Art der Datenbank (keine, SQLite, MariaDB, TimescaleDB, QuestDB, InfluxDB 3, VictoriaMetrics, "
                  "Prometheus)",
                  "Type of database (none, SQLite, MariaDB, TimescaleDB, QuestDB, InfluxDB 3, VictoriaMetrics, "
                  "Prometheus)"),
    "Server / Port": ("Adresse und Port des Datenbankservers", "Address and port of the database server"),
    "Datenbankname": ("Name der Datenbank auf dem Server", "Name of the database on the server"),
    "SQLite-Datei": ("Datei der SQLite-Datenbank", "File of the SQLite database"),
    "Benutzer / Passwort": ("Anmeldung am Datenbankserver", "Login to the database server"),
    # Trigger & Ereignisse
    "Trigger": ("Zahl der eingerichteten Trigger", "Number of configured triggers"),
    "Ereignisdatei": ("CSV-Datei des Ereignisprotokolls (leer = neben der Konfiguration)",
                      "CSV file of the event log (empty = next to the configuration)"),
    "Melden": ("Eingeschaltete Benachrichtigungen", "Enabled notifications"),
    # Berichte
    "Zeitraum": ("Zeitraum eines automatischen Berichts: Schicht, Tag, Woche oder Monat",
                 "Period of an automatic report: shift, day, week or month"),
    "Ordner": ("Ordner für die PDF-Berichte", "Folder for the PDF reports"),
    # Variablen und Diagramme
    "Name, Steuerung, Diagramm › Y-Achse, Adresse, Typ, Farbe, Aufzeichnen, Anzeigen, Werteanzeige, Balken, "
    "Testwert, Formel": (
        "Variablen: je Zeile Name, Steuerung, Diagramm und Y-Achse, Adresse, Datentyp, Farbe, Schalter für "
        "Aufzeichnung und Anzeige, Testwert und Formel (berechnete Variable)",
        "Variables: per row name, PLC, chart and Y axis, address, data type, colour, switches for recording and "
        "display, test value and formula (calculated variable)"),
    "Aus Steuerung wählen…": ("Variablen aus der Steuerung auswählen (Symbole, Tags, Knoten – je nach Treiber)",
                              "Choose variables from the PLC (symbols, tags, nodes – depending on the driver)"),
    "Blöcke (Blocklesemodus)…": ("Zusammenhängende Bereiche bzw. Arrays mit einer Anfrage lesen",
                                 "Read contiguous areas or arrays with one request"),
    "Berechnete Variable…": ("Variable aus einer Formel anderer Variablen anlegen",
                             "Create a variable from a formula of other variables"),
    "Variable hinzufügen": ("Leere Zeile für eine neue Variable", "Empty row for a new variable"),
    "Entfernen": [("Markierte Variablen löschen", "Delete the selected variables"),
                  ("Markiertes Diagramm bzw. markierte Y-Achse löschen", "Delete the selected chart or Y axis")],
    "Verbindung testen": ("Markierte Variablen einmal aus der Steuerung lesen und anzeigen",
                          "Read the selected variables once from the PLC and show them"),
    "Import/Export": ("Variablenliste als CSV, Excel oder ODS importieren bzw. exportieren",
                      "Import or export the variable list as CSV, Excel or ODS"),
    "+ Diagramm": ("Neues Diagramm anlegen", "Add a new chart"),
    "+ Y-Achse": ("Weitere Y-Achse im markierten Diagramm", "Add another Y axis to the selected chart"),
    "Name": ("Name von Diagramm bzw. Y-Achse", "Name of the chart or Y axis"),
    "Y min": ("Untere Grenze der Y-Achse", "Lower limit of the Y axis"),
    "Y max": ("Obere Grenze der Y-Achse", "Upper limit of the Y axis"),
    "Regler": ("Soll-, Ist- und Stellwert für die PID-Optimierung", "Setpoint, process value and output for PID "
                                                                    "tuning"),
    "Auto-Skalierung": ("Y-Achse automatisch an die Werte anpassen", "Scale the Y axis automatically to the values"),
    "Einstellen …": ("Soll-, Ist- und Stellwert und Reglertyp wählen", "Choose setpoint, process value, output and "
                                                                       "controller type"),
    "Öffnen…": ("Wie Menü Datei › Öffnen", "Same as File › Open"),
    "Speichern unter…": ("Wie Menü Datei › Speichern unter", "Same as File › Save as"),
}

D["IoCheckWindow"] = {
    "Speichern unter …": ("Prüfstand unter neuem Namen speichern", "Save the test under a new name"),
    "Querformat": ("Protokoll im Querformat statt Hochformat", "Report in landscape instead of portrait"),
    "Fotos anhängen": ("Fotos der Signale ans Protokoll anhängen", "Attach the photos of the signals to the report"),
    "Zeit, Signal, Wechsel": ("Seitenleiste „Was hat sich bewegt?“: zuletzt gewechselte Signale, neueste oben; Klicken "
                              "wählt das Signal",
                              "Side panel “What moved?”: recently changed signals, newest at the top; click to select "
                              "the signal"),
    "Nr., Status, Wert, Adresse, Symbol, Kommentar, BMK, Gruppe, Ort, Typ, Steuerung, Geprüft am, Prüfer, Fotos, "
    "Bemerkung": (
        "Signalliste: Klick auf eine Überschrift sortiert, Rechtsklick filtert die Spalte; Doppelklick auf eine Zeile "
        "setzt OK bzw. nimmt es zurück",
        "Signal list: click a heading to sort, right-click to filter the column; double-click a row to set or undo "
        "OK"),
    "✓ OK": ("Markierte Signale als geprüft und in Ordnung eintragen", "Mark the selected signals as checked and OK"),
    "✗ Fehler …": ("Als fehlerhaft eintragen, mit Bemerkung", "Mark as faulty, with a remark"),
    "– Übersprungen": ("Nicht prüfen (z. B. Reserve)", "Do not check (e.g. spare)"),
    "↻ Wiederholen": ("Erneut prüfen; die Bemerkung bleibt", "Check again; the remark is kept"),
    "Zurücksetzen": ("Wieder offen; die Bemerkung wird gelöscht", "Open again; the remark is deleted"),
    "Rohwert bei 0 %": ("Rohwert der Steuerung am Messbereichsanfang (z. B. 0)", "Raw PLC value at the start of the "
                                                                                 "range (e.g. 0)"),
    "Rohwert bei 100 %": ("Rohwert am Messbereichsende (z. B. 27648)", "Raw value at the end of the range (e.g. "
                                                                       "27648)"),
    "Messbereich von": ("Physikalischer Wert bei 0 %", "Physical value at 0 %"),
    "Messbereich bis": ("Physikalischer Wert bei 100 %", "Physical value at 100 %"),
    "Einheit": ("Einheit des Messbereichs (z. B. bar)", "Unit of the range (e.g. bar)"),
    "Übernehmen": ("Aktuellen Wert als Prüfpunkt 0 / 50 / 100 % übernehmen", "Take the current value as test point 0 "
                                                                              "/ 50 / 100 %"),
    "Messpunkte löschen": ("Eingetragene Prüfpunkte des Signals löschen", "Delete the test points of the signal"),
}
IO_EXTRA = [
    (("Rechtsklick in die Signalliste", "Right-click in the signal list"),
     ("Alle markieren (``Strg+A``), Status setzen, Signal hinzufügen, gescannte Signale in die IO-Liste übernehmen, "
      "Signale aus der IO-Liste entfernen",
      "Select all (``Ctrl+A``), set the status, add a signal, take scanned signals into the IO list, remove signals "
      "from the IO list")),
    (("Rechtsklick auf eine Spaltenüberschrift", "Right-click on a column heading"),
     ("Filter der Spalte: Text („enthält …“) oder einzelne Werte ankreuzen",
      "Column filter: text (“contains …”) or tick individual values")),
    (("Matrix: Klick / Doppelklick / Rechtsklick", "Matrix: click / double-click / right-click"),
     ("Signal wählen / OK setzen bzw. zurücknehmen / Status wählen",
      "Select the signal / set or undo OK / choose the status")),
]

D["EventViewer"] = {
    "nur offene": ("Nur nicht quittierte Ereignisse zeigen", "Show only unacknowledged events"),
    "Nr., Kommt, Geht, Priorität, Trigger, Meldung, Quittiert": (
        "Ereignisse, neueste oben; Doppelklick quittiert, Rechtsklick: Im Diagramm zeigen, Quittieren",
        "Events, newest at the top; double-click to acknowledge, right-click: show in chart, acknowledge"),
    "Alle quittieren (4)": ("Alle offenen Ereignisse quittieren", "Acknowledge all open events"),
}

D["NoteDialog"] = {"Verfasser": ("Name, der beim Eintrag gespeichert wird (Vorgabe: angemeldeter Benutzer)",
                                 "Name stored with the entry (default: logged-in user)")}

D["ExportDialog"] = {
    "Zwischen Lineal 1 und Lineal 2": ("Nur den Bereich zwischen den Linealen (offline)",
                                       "Only the range between the rulers (offline)"),
    "Sichtbarer Ausschnitt": ("Den angezeigten Zeitbereich", "The displayed time range"),
    "Alle Daten (20.11.2026 20:33:27.720 bis 20.11.2026 20:34:53.523)": ("Die ganze geladene bzw. aufgezeichnete Zeit",
                                                                       "The whole loaded or recorded time"),
    "Nur eingeblendete Variablen (15 von 17)": ("Ausgeblendete Kurven nicht exportieren", "Do not export hidden "
                                                                                          "curves"),
    "Downsampling (Werte auf ein Zeitraster verdichten)": ("Werte auf ein festes Zeitraster verdichten",
                                                           "Condense the values to a fixed time grid"),
    "Raster": ("Abstand des Zeitrasters", "Interval of the time grid"),
    "Verfahren": ("Wert je Intervall: Mittelwert, Minimum, Maximum, erster oder letzter Wert",
                  "Value per interval: mean, minimum, maximum, first or last value"),
    "Speichern …": ("Dateinamen wählen (CSV oder Excel) und speichern", "Choose a file name (CSV or Excel) and save"),
}

D["XYDialog"] = {
    "Zeitbereich": ("Lineale, sichtbarer Ausschnitt oder alle Daten", "Rulers, visible range or all data"),
    "X-Achse": ("Variable für die X-Achse; die übrigen gewählten werden darüber gezeichnet",
                "Variable for the X axis; the other selected ones are plotted against it"),
    "Darstellung": ("Punkte oder Linie", "Points or line"),
    "Ausgleichsgerade und Korrelation": ("Ausgleichsgerade und Korrelationskoeffizient zeigen",
                                         "Show the regression line and the correlation coefficient"),
    "Bild speichern …": ("Diagramm als PNG oder SVG speichern", "Save the chart as PNG or SVG"),
    "Werte speichern (CSV) …": ("Wertepaare als CSV-Datei speichern", "Save the value pairs as a CSV file"),
}
D["FftDialog"] = {
    "Zeitbereich": ("Lineale, sichtbarer Ausschnitt oder alle Daten", "Rulers, visible range or all data"),
    "Variable": ("Variable, deren Spektrum berechnet wird", "Variable whose spectrum is calculated"),
    "Fenster": ("Fensterfunktion (Hann, Hamming, Blackman, Rechteck, Flat-Top)",
                "Window function (Hann, Hamming, Blackman, rectangle, flat-top)"),
    "Vorbehandlung": ("Mittelwert oder linearen Trend abziehen", "Subtract the mean or a linear trend"),
    "X-Achse": ("Frequenz oder Periodendauer", "Frequency or period"),
    "Amplitude logarithmisch": ("Amplitudenachse logarithmisch", "Logarithmic amplitude axis"),
    "Bild speichern …": ("Diagramm als PNG oder SVG speichern", "Save the chart as PNG or SVG"),
    "Werte speichern (CSV) …": ("Spektrum als CSV-Datei speichern", "Save the spectrum as a CSV file"),
}
D["PidTuneDialog"] = {
    "Sollwert": ("Variable mit dem Sollwert (optional)", "Variable with the setpoint (optional)"),
    "Istwert": ("Variable mit dem Istwert (Regelgröße)", "Variable with the process value"),
    "Stellwert": ("Variable mit dem Stellwert (Reglerausgang)", "Variable with the controller output"),
    "Zeitbereich": ("Bereich mit Stellwert- oder Sollwertsprung", "Range with a step of the output or setpoint"),
    "Reglertyp": ("PI oder PID", "PI or PID"),
    "Regelverhalten": ("Schnell, normal oder robust", "Fast, normal or robust"),
    "Strecke bestimmen und berechnen": ("Streckenmodell bestimmen, Parameter aller Einstellregeln berechnen und "
                                        "simulieren",
                                        "Identify the process model, calculate and simulate the parameters of all "
                                        "tuning rules"),
    "Einstellregel, Kp, Ti [s], Td [s], Ki [1/s], Kd [s], Überschwingen, Ausregelzeit, Hinweis": (
        "Ergebnis je Einstellregel mit Überschwingen und Ausregelzeit aus der Simulation",
        "Result per tuning rule with overshoot and settling time from the simulation"),
}
D["DbLoadDialog"] = {
    "Datenbank der Konfiguration": ("Wieder die Datenbank der Konfiguration lesen", "Read the database of the "
                                                                                     "configuration again"),
    "Alle": ("Alle Variablen ankreuzen", "Tick all variables"),
    "Keine": ("Keine Variable ankreuzen", "Untick all variables"),
    "Wie Konfiguration": ("Die Variablen der aktuellen Konfiguration ankreuzen", "Tick the variables of the current "
                                                                                 "configuration"),
    "Heute": ("Heute ab 0 Uhr", "Today from midnight"),
    "Gestern": ("Der ganze gestrige Tag", "The whole of yesterday"),
    "Laden und anzeigen": ("Werte laden und offline anzeigen", "Load the values and show them offline"),
}
D["QDialog"] = {"Adresse kopieren": ("Adresse in die Zwischenablage kopieren", "Copy the address to the clipboard")}
D["PidSetupDialog"] = {
    "Sollwert": ("Variable mit dem Sollwert (optional)", "Variable with the setpoint (optional)"),
    "Istwert (Regelgröße)": ("Variable mit dem Istwert", "Variable with the process value"),
    "Stellwert (Reglerausgang)": ("Variable mit dem Stellwert", "Variable with the controller output"),
    "Reglertyp": ("PI oder PID", "PI or PID"),
    "Regelverhalten": ("Schnell, normal oder robust", "Fast, normal or robust"),
}
D["PlcSettingsDialog"] = {
    "Eigener AMS-Port": ("AMS-Port dieses Rechners (Vorgabe 32905)", "AMS port of this computer (default 32905)"),
    "TCP-Port": ("TCP-Port des ADS-Routers (Vorgabe 48898)", "TCP port of the ADS router (default 48898)"),
    "Zeitlimit": ("Wartezeit auf eine Antwort, danach gilt die Verbindung als gestört",
                  "Time to wait for an answer; after that the connection counts as faulty"),
    "Sicherheit": ("Sicherheitsrichtlinie: keine, signieren oder signieren und verschlüsseln (Basic256Sha256, "
                   "Aes128Sha256RsaOaep, Aes256Sha256RsaPss)",
                   "Security policy: none, sign, or sign and encrypt (Basic256Sha256, Aes128Sha256RsaOaep, "
                   "Aes256Sha256RsaPss)"),
}
D["BlockEditor"] = {
    "Für alle Elemente des markierten Blocks setzen": None,
    "Name, Steuerung, Startadresse / Array, Erster Index, Format, Anzahl, Ringpuffer, Diagramm › Y-Achse, Farbe, "
    "Werteanzeige, Balken, Bereich": (
        "Blöcke: Startadresse bzw. Array, Format und Anzahl der Elemente, optional als Ringpuffer, Ziel im Diagramm",
        "Blocks: start address or array, format and number of elements, optionally as ring buffer, target in the "
        "chart"),
    "Block hinzufügen": ("Neuen Block anlegen", "Add a new block"),
    "Entfernen": ("Markierten Block löschen", "Delete the selected block"),
}
D["FormulaEditor"] = {
    "Verwendete Variable, Testwert": ("Variablen der Formel mit Testwerten für die Probe", "Variables of the formula "
                                                                                          "with test values"),
    "Prüfen / Berechnen": ("Formel prüfen und mit den Testwerten berechnen", "Check the formula and calculate it with "
                                                                             "the test values"),
}
D["TriggerEditor"] = {
    "Aktiv, Name, Bedingung, Meldetext, Priorität, Verzögerung, Gehen, Quittieren": (
        "Trigger: Bedingung, Meldetext, Priorität, Verzögerung, ob „Gehen“ gemeldet und ob quittiert werden muss",
        "Triggers: condition, message, priority, delay, whether “going” is logged and whether acknowledgement is "
        "required"),
}
D["WebUsersDialog"] = {
    "Hinzufügen …": ("Benutzer mit Passwort anlegen", "Add a user with password"),
    "Passwort ändern …": ("Neues Passwort für den markierten Benutzer", "New password for the selected user"),
    "Entfernen": ("Markierten Benutzer löschen", "Delete the selected user"),
}
D["MqttDialog"] = {
    "Werte an einen MQTT-Broker senden (während der Aufzeichnung)": ("MQTT einschalten", "Switch MQTT on"),
    "Port": ("Port des Brokers (1883, mit TLS meist 8883)", "Port of the broker (1883, with TLS usually 8883)"),
    "Passwort": ("Passwort zum Benutzer", "Password of the user"),
    "TLS (verschlüsselt, meist Port 8883)": ("Verbindung zum Broker verschlüsseln", "Encrypt the connection to the "
                                                                                    "broker"),
    "Senden": ("Bei Änderung oder zyklisch", "On change or cyclically"),
    "Format": ("Ein Topic je Variable, eine JSON-Nachricht oder beides", "One topic per variable, one JSON message or "
                                                                         "both"),
    "QoS": ("Dienstgüte 0, 1 oder 2", "Quality of service 0, 1 or 2"),
    "Discovery-Präfix": ("Präfix der Home-Assistant-Discovery (meist homeassistant)", "Prefix of the Home Assistant "
                                                                                      "discovery (usually "
                                                                                      "homeassistant)"),
    "Home-Assistant-Discovery (Variablen erscheinen dort als Sensoren)": (
        "Variablen in Home Assistant automatisch als Sensoren anlegen",
        "Create the variables automatically as sensors in Home Assistant"),
    "Verbindung testen": ("Anmeldung am Broker prüfen", "Check the login to the broker"),
}
D["HeadlessDialog"] = {
    "Projekt, Konfiguration, Gestartet, Rechner, PID, Webserver, Zustand": (
        "Laufende Headless-Logger auf diesem Rechner", "Headless loggers running on this computer"),
}
D["TagBrowser"] = {
    "Tag-Liste aus Steuerung laden": ("Tags der Steuerung lesen und anzeigen", "Read and show the tags of the PLC"),
    "Auswahl übernehmen": ("Markierte Tags als Variablen übernehmen", "Take the selected tags as variables"),
}
D["NetScanDialog"] = {
    "Suchen": ("Adressbereich nach Steuerungen durchsuchen", "Search the address range for PLCs"),
    "Übernehmen, Adresse, Gefunden, Gerät, Angaben, Treiber": ("Gefundene Geräte mit offenen Ports und Kennung",
                                                               "Devices found with open ports and identification"),
    "Als Steuerung übernehmen": ("Angekreuzte Geräte als Steuerungen anlegen", "Add the ticked devices as PLCs"),
}
D["AddSignalDialog"] = {
    "Symbol": ("Symbolname", "Symbol name"), "Kommentar": ("Kommentar", "Comment"),
    "BMK": ("Betriebsmittelkennzeichen", "Equipment identifier"),
    "Gruppe": ("Gruppe in der Liste (z. B. Schrank)", "Group in the list (e.g. cabinet)"),
    "Typ": ("Signalart (wird aus der Adresse vorgeschlagen)", "Signal type (suggested from the address)"),
    "Steuerung": ("Steuerung, von der gelesen wird", "PLC to read from"),
}
D["PhotoDialog"] = {
    "Hinzufügen …": ("Fotos auswählen und zum Signal ablegen", "Choose photos and store them with the signal"),
    "Öffnen": ("Markiertes Foto mit dem Bildbetrachter öffnen", "Open the selected photo in the image viewer"),
    "Entfernen": ("Markiertes Foto löschen", "Delete the selected photo"),
}
D["ScanDialog"] = {
    "Steuerung, Startadresse, Anzahl Bits": ("Bereiche: Steuerung, erste Adresse und Anzahl Bits",
                                             "Ranges: PLC, first address and number of bits"),
    "Hinzufügen": ("Weiteren Bereich anlegen", "Add another range"),
    "Entfernen": ("Markierten Bereich löschen", "Delete the selected range"),
}
D["NotifyDialog"] = {
    "Bei Ereignissen benachrichtigen": ("Benachrichtigungen einschalten", "Switch notifications on"),
    "Priorität": ("Ab welcher Priorität gemeldet wird", "From which priority messages are sent"),
    "Auch melden, wenn ein Ereignis geht": ("Auch das Gehen eines gemeldeten Ereignisses melden",
                                            "Also report when a reported event goes"),
    "Bot-Token": ("Token des Telegram-Bots", "Token of the Telegram bot"),
    "Chat-ID": ("Chat, in den der Bot schreibt (z. B. 123456789)", "Chat the bot writes to (e.g. 123456789)"),
    "Adresse mit Thema": ("Server und Thema, z. B. https://ntfy.sh/mein-geheimes-thema",
                          "Server and topic, e.g. https://ntfy.sh/my-secret-topic"),
    "Webhook-Adresse": ("Adresse des eingehenden Webhooks (aus Teams bzw. Slack)",
                        "Address of the incoming webhook (from Teams or Slack)"),
    "SMTP-Server": ("Mailserver für den Versand, z. B. smtp.firma.de", "Mail server for sending, e.g. smtp.company.com"),
    "Absender": ("Absenderadresse der E-Mails", "Sender address of the e-mails"),
    "Empfänger": ("Empfängeradressen, durch Komma getrennt", "Recipient addresses, separated by commas"),
    "Zugriffstoken": ("Token für ein geschütztes ntfy-Thema", "Token for a protected ntfy topic"),
    "Art": ("Microsoft Teams (Workflows), Slack oder allgemeines JSON", "Microsoft Teams (workflows), Slack or "
                                                                        "generic JSON"),
    "Port": ("Port des SMTP-Servers (587, SSL meist 465)", "Port of the SMTP server (587, SSL usually 465)"),
    "Verschlüsselung": ("STARTTLS, SSL/TLS oder unverschlüsselt", "STARTTLS, SSL/TLS or unencrypted"),
    "Benutzer": ("Anmeldung am SMTP-Server (leer = ohne)", "Login to the SMTP server (empty = none)"),
    "Passwort": ("Passwort zum Benutzer", "Password of the user"),
    "Telegram verwenden": ("Kanal einschalten", "Enable the channel"),
    "ntfy (Push) verwenden": ("Kanal einschalten", "Enable the channel"),
    "Teams / Slack / Webhook verwenden": ("Kanal einschalten", "Enable the channel"),
    "E-Mail verwenden": ("Kanal einschalten", "Enable the channel"),
}
D["OpcUaServerDialog"] = {
    "Port": ("TCP-Port (Standard 4840)", "TCP port (default 4840)"),
    "Endpunkt": ("Adresse, unter der Clients den Server erreichen", "Address at which clients reach the server"),
    "OPC-UA-Server starten (während der Aufzeichnung)": ("Server einschalten", "Switch the server on"),
    "Keine": ("Endpunkt ohne Sicherheit", "Endpoint without security"),
    "Basic256Sha256 – Signieren": ("Endpunkt mit signierten Nachrichten", "Endpoint with signed messages"),
    "Basic256Sha256 – Signieren und verschlüsseln": ("Endpunkt mit signierten und verschlüsselten Nachrichten",
                                                     "Endpoint with signed and encrypted messages"),
    "Aes128Sha256RsaOaep – Signieren und verschlüsseln": ("Wie oben, neueres Verfahren", "As above, newer method"),
    "Aes256Sha256RsaPss – Signieren und verschlüsseln": ("Wie oben, neuestes Verfahren", "As above, newest method"),
    "Anmeldung mit den Benutzern des Webservers (2 eingerichtet)": (
        "Clients melden sich mit Benutzer und Passwort des Webservers an (Konfigurationsprogramm › Webserver & "
        "Headless › **Benutzer …**)",
        "Clients log in with user and password of the web server (configuration › Web server & headless › "
        "**Users …**)"),
    "Anonym (ohne Anmeldung)": ("Zugriff ohne Anmeldung erlauben", "Allow access without login"),
}

# Abschnitte des Kapitels: (Überschrift de, Überschrift en, Sprungmarke für „Mehr dazu“ oder "")
TITLE = ("Referenz: alle Menüs, Fenster und Bedienelemente", "Reference: all menus, windows and controls")
INTRO = ("Dieses Kapitel listet die Menüs, Werkzeugleisten, Reiter, Knöpfe und Felder der Programme und Dialoge mit "
         "ihrer Bedeutung auf. Ausführliche Erklärungen mit Beispielen stehen in den vorigen Kapiteln; der Verweis "
         "*Mehr dazu* führt jeweils dorthin. Die Tastenkürzel gelten unter Windows und Linux; auf dem Mac steht "
         "``⌘`` statt ``Strg``.",
         "This chapter lists the menus, toolbars, tabs, buttons and fields of the programs and dialogs with their "
         "meaning. Detailed explanations with examples are in the previous chapters; *More* leads there. The "
         "shortcuts apply to Windows and Linux; on the Mac, ``⌘`` replaces ``Ctrl``.")

# Angezeigter Text statt des mitgeschriebenen (dynamische Teile, Zahlen aus dem Beispiel); schon RST
RENAME = {
    "MainWindow": {"🔔 4 offen": ("🔔 *n* offen", "🔔 *n* open"),
                   "▶ Start": ("▶ Start / ■ Stop", "▶ Start / ■ Stop")},
    "EventViewer": {"Alle quittieren (4)": ("Alle quittieren (*n*)", "Acknowledge all (*n*)")},
    "ExportDialog": {"Alle Daten (20.11.2026 20:33:27.720 bis 20.11.2026 20:34:53.523)": (
        "Alle Daten (*von* bis *bis*)", "All data (*from* to *to*)"),
        "Nur eingeblendete Variablen (15 von 17)": ("Nur eingeblendete Variablen (*n* von *m*)",
                                                    "Only visible variables (*n* of *m*)")},
    "IoCheckWindow": {"Prüfer: M. Mustermann": ("Prüfer: *Name*", "Tester: *name*"),
                      "■ Lesen stoppen": ("▶ Lesen / ■ Lesen stoppen", "▶ Read / ■ Stop reading")},
    "OpcUaServerDialog": {"Anmeldung mit den Benutzern des Webservers (2 eingerichtet)": (
        "Anmeldung mit den Benutzern des Webservers (*n* eingerichtet)",
        "Login with the users of the web server (*n* configured)")},
}

# Überschriften der Abschnitte (de, en)
S = {
    "logger_menus": ("Logger: Menüs", "Logger: menus"),
    "common": ("Logger und Konfigurationsprogramm: Sprache und Hilfe",
               "Logger and configuration program: language and help"),
    "logger_window": ("Logger: Werkzeugleiste und Fenster", "Logger: toolbar and window"),
    "toolbar": ("Werkzeugleiste des Loggers", "Toolbar of the logger"),
    "main_controls": ("Fenster und Statusleiste", "Window and status bar"),
    "mouse": ("Maus in den Diagrammen", "Mouse in the charts"),
    "start": ("Startbild: Bedienelemente", "Start screen: controls"),
    "config_menus": ("Konfigurationsprogramm: Menüs", "Configuration program: menus"),
    "config_tabs": ("Konfigurationsprogramm: Reiter und Variablen", "Configuration program: tabs and variables"),
    "config_vars": ("Variablen und Diagramme", "Variables and charts"),
    "io": ("IO-Check: Fenster", "IO check: window"),
    "io_toolbar": ("Werkzeugleiste des IO-Checks", "Toolbar of the IO check"),
    "io_side": ("Optionen und Seitenleiste", "Options and side panel"),
    "events": ("Fenster Ereignisprotokoll", "Event log window"),
    "netpanel": ("Netzwerk-Panel (Raspberry Pi)", "Network panel (Raspberry Pi)"),
    "dlg_logger": ("Dialoge des Loggers", "Dialogs of the logger"),
    "dlg_config": ("Dialoge des Konfigurationsprogramms", "Dialogs of the configuration program"),
    "dlg_io": ("Dialoge des IO-Checks", "Dialogs of the IO check"),
}

# Einleitende Sätze (de, en)
P = {
    "logger_menus": ("Menüleiste des Loggers (``plc_logger.py``). Die Menüs *Sprache* und *Hilfe* stehen im nächsten "
                     "Abschnitt.",
                     "Menu bar of the logger (``plc_logger.py``). The menus *Language* and *Help* are in the next "
                     "section."),
    "common": ("Beide Programme haben die Menüs *Sprache* und *Hilfe*; der IO-Check übernimmt Sprache und Farbschema "
               "vom Programm, aus dem er gestartet wird.",
               "Both programs have the menus *Language* and *Help*; the IO check takes language and colour scheme "
               "from the program it is started from."),
    "config_common": ("Die Menüs *Sprache* und *Hilfe* sind dieselben wie im Logger.",
                      "The menus *Language* and *Help* are the same as in the logger."),
    "config_tabs": ("Oben stehen die Reiter mit den Einstellungen des Projekts, darunter die Variablen und der Baum mit "
                    "Diagrammen und Y-Achsen. Die Verbindungseinstellungen einer Steuerung (Knopf **…** in der Tabelle) "
                    "hängen vom Treiber ab, siehe *Dialoge des Konfigurationsprogramms*.",
                    "At the top are the tabs with the project settings, below them the variables and the tree with "
                    "charts and Y axes. The connection settings of a PLC (button **…** in the table) depend on the "
                    "driver, see *Dialogs of the configuration program*."),
    "netpanel": ("Bildschirmfüllende Oberfläche für den Touchscreen am Raspberry Pi (``plc-netzwerk``). Eingaben über "
                 "die Bildschirmtastatur; **Zurück** führt auf jeder Seite zur Übersicht.",
                 "Full-screen user interface for the touchscreen of the Raspberry Pi (``plc-netzwerk``). Input via "
                 "the on-screen keyboard; **Back** returns to the overview on every page."),
}

# „Mehr dazu“ je Reiter (Konfigurationsprogramm, IO-Check)
TAB_LINKS = {
    "Projekt & Steuerungen": ["konfig-projekt", "treiber"],
    "Aufzeichnung": ["csv-archiv", "aufraeumen", "trigger-aufzeichnung"],
    "Anzeige": ["seiten"],
    "Webserver & Headless": ["webserver", "https-anmeldung", "headless", "opcua-server", "mqtt"],
    "Datenbank": ["datenbank"],
    "Trigger & Ereignisse": ["ereignisse", "benachrichtigungen"],
    "Berichte (PDF)": ["pdf-berichte"],
    "": "",
    "Signalliste": ["io-signalliste"],
    "Matrix": ["io-matrix"],
}

# Netzwerk-Panel: Seiten und Knöpfe (die Mitschrift enthält nur einzelne Knöpfe ohne Zusammenhang)
NETPANEL = [
    (("Übersicht", "Overview"),
     ("Rechnername, Version, Uhrzeit, Ethernet und WLAN mit IP-Adressen, Zustand des Logger-Dienstes, Adresse des "
      "Webservers mit QR-Code",
      "Host name, version, time, Ethernet and Wi-Fi with IP addresses, state of the logger service, web server "
      "address with QR code")),
    (("Ethernet / WLAN", "Ethernet / Wi-Fi"),
     ("DHCP oder feste Adresse (IP/Präfix, Gateway, DNS); WLAN suchen und mit Passwort verbinden",
      "DHCP or static address (IP/prefix, gateway, DNS); search for Wi-Fi networks and connect with password")),
    (("Logger", "Logger"),
     ("Konfiguration wählen, **Starten (headless)** bzw. **Stoppen** (stellt den Dienst um)",
      "Choose a configuration, **Start (headless)** or **Stop** (switches the service)")),
    (("Display", "Display"),
     ("Zeit bis zum Abdunkeln, Helligkeit im Betrieb und abgedunkelt; **Jetzt abdunkeln**",
      "Time until dimming, brightness in operation and dimmed; **Dim now**")),
    (("Uhrzeit", "Time"),
     ("Datum und Uhrzeit mit ▲/▼ und **Uhr stellen**, **Zeitzone**, **Internetzeit (NTP)**; Uhrzeit der Steuerung "
      "**Lesen**, **Übernehmen**, **UTC**, **Automatisch**",
      "Date and time with ▲/▼ and **Set clock**, **Time zone**, **Internet time (NTP)**; **Read** the PLC time, "
      "**Apply**, **UTC**, **Automatic**")),
    (("⏻", "⏻"),
     ("Seite *Ausschalten*: **Neu starten**, **Herunterfahren** (beendet den Logger-Dienst ordnungsgemäß)",
      "Page *Power*: **Restart**, **Shut down** (stops the logger service properly)")),
]

# Dialoge: (Abschnitt, [(Klasse, Titelanfang oder None, (Überschrift de, en), Sprungmarke(n))])
DIALOGS = [
    ("dlg_logger", [
        ("QDialog", "Webserver", ("Webserver-Adresse", "Web server address"), "webserver"),
        ("DbLoadDialog", None, ("Aus Datenbank laden", "Load from database"), "db-lesen"),
        ("ExportDialog", None, ("Werte exportieren", "Export values"), "werte-exportieren"),
        ("NoteDialog", None, ("Notiz ins Ereignisprotokoll", "Note to the event log"), "notizen"),
        ("XYDialog", None, ("XY-Diagramm", "XY chart"), "analyse"),
        ("FftDialog", None, ("Frequenzanalyse (FFT)", "Frequency analysis (FFT)"), "analyse"),
        ("PidTuneDialog", None, ("PID-Regler-Optimierung", "PID controller tuning"), "pid-optimierung"),
    ]),
    ("dlg_config", [
        ("PlcSettingsDialog", "Verbindung – SPS 1 (Beckhoff", ("Verbindungseinstellungen (Beispiel TwinCAT ADS)",
                                                               "Connection settings (example TwinCAT ADS)"),
         "treiber"),
        ("PlcSettingsDialog", "Verbindung – SPS 1 (OPC UA", ("Verbindungseinstellungen (Beispiel OPC UA)",
                                                             "Connection settings (example OPC UA)"), "treiber"),
        ("NetScanDialog", None, ("Netzwerk durchsuchen", "Scan network"), "konfig-projekt"),
        ("TagBrowser", None, ("Tags aus der Steuerung wählen", "Select tags from the controller"), "tags-waehlen"),
        ("BlockEditor", None, ("Blöcke (Blocklesemodus)", "Blocks (block read mode)"), ["blocklesemodus", "ringpuffer"]),
        ("FormulaEditor", "Berechnete", ("Berechnete Variable (Formeleditor)", "Calculated variable (formula editor)"),
         "berechnete-variablen"),
        ("PidSetupDialog", None, ("PID-Optimierung einstellen", "Set up PID tuning"), "pid-optimierung"),
        ("TriggerEditor", None, ("Trigger (Ereignisse)", "Triggers (events)"), "ereignisse"),
        ("NotifyDialog", None, ("Benachrichtigungen", "Notifications"), "benachrichtigungen"),
        ("WebUsersDialog", None, ("Webserver – Benutzer", "Web server – users"), "https-anmeldung"),
        ("OpcUaServerDialog", None, ("OPC-UA-Server", "OPC UA server"), "opcua-server"),
        ("MqttDialog", None, ("MQTT", "MQTT"), "mqtt"),
        ("HeadlessDialog", None, ("Laufende Headless-Logger", "Running headless loggers"), "headless"),
    ]),
    ("dlg_io", [
        ("AddSignalDialog", None, ("Signal hinzufügen", "Add signal"), "io-check"),
        ("PhotoDialog", None, ("Fotos", "Photos"), "io-protokoll"),
        ("ScanDialog", None, ("Bereiche scannen", "Scan ranges"), "io-matrix"),
    ]),
]
