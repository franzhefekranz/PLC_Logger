======================================================================
TIA Datenlogger – Bedienungsanleitung
======================================================================

.. contents:: Inhalt
   :depth: 2
   :local:


Überblick
======================================================================

Der TIA Datenlogger liest zyklisch Variablen aus einer oder **mehreren**
Siemens-Steuerungen **S7-1200** und **S7-1500** (TIA Portal) über das Protokoll
**S7CommPlus**, speichert alle Messwerte in einer CSV-Datei und zeigt sie als
y-t-Diagramm an – in der Oberfläche, im Browser (Webserver) oder gar nicht
(Headless-Betrieb, nur Aufzeichnung).

* S7CommPlus ist das Protokoll, mit dem auch TIA Portal und Siemens-HMIs mit der
  CPU sprechen. Variablen werden **symbolisch** über ihren Namen gelesen – auch aus
  Datenbausteinen mit **„Optimiertem Bausteinzugriff“** und **ohne PUT/GET-Freigabe**.
* Die Kommunikation übernimmt die Python-Bibliothek **s7commplus** (reines Python,
  inoffizielle Implementierung; unterstützt S7CommPlus V1, V2 mit TLS und V3).
* Die **Variablenliste** (Datenbausteine, Strukturen, Arrays, Merker, Ein-/Ausgänge)
  liest das Programm direkt aus der Steuerung – ein Export aus TIA Portal ist nicht
  nötig.

Das Programm besteht aus mehreren Dateien, die im selben Ordner liegen müssen:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Datei
     - Aufgabe
   * - ``tia_config.py``
     - Konfigurationsprogramm: Projekt, Steuerungen, Diagramme, Y-Achsen und
       Variablen festlegen. Speichert in eine JSON-Datei mit beliebigem Namen
       (Standard ``tia_config.json``).
   * - ``tia_logger.py``
     - Startprogramm des Loggers: wählt anhand der Konfiguration bzw. der
       Parameter die Betriebsart (Oberfläche oder Headless).
   * - ``tia_gui.py``
     - Oberfläche des Loggers: Diagramme, Online-/Offline-Modus, Lineale,
       Status-LEDs. Wird von ``tia_logger.py`` geladen.
   * - ``tia_headless.py``
     - Betrieb ohne Oberfläche (nur Aufzeichnung, benötigt kein Qt).
   * - ``tia_recorder.py``
     - Aufzeichnungskern ohne Oberfläche: je Steuerung ein Lese-Thread, ein
       Sammler-Thread für Zusammenführung, Formeln, Datenpuffer, CSV und Archiv.
   * - ``tia_web.py``
     - Webserver (Flask) mit Chart.js-Seite zum Ansehen der Diagramme im Browser.
   * - ``tia_svg.py``
     - SVG-Export eines Diagramms (unabhängig von Qt).
   * - ``tia_util.py``
     - Kleine Hilfsfunktionen (Formatierung, Achsenteilung, Datenreduktion).
   * - ``tia_db.py``
     - Aufzeichnung in SQLite, MariaDB oder TimescaleDB/PostgreSQL (eigener Schreib-Thread).
   * - ``tia_db_dialog.py``
     - Lesemodus: Zeitraum aus der Datenbank wählen und im Logger anzeigen.
   * - ``tia_events.py``
     - Trigger und Ereignisprotokoll (Auswertung, Datei, Quittierung).
   * - ``tia_event_viewer.py``
     - Ereignis-Viewer (Anzeigen und Quittieren); auch allein startbar.
   * - ``tia_trigger_dialog.py``
     - Trigger-Editor des Konfigurationsprogramms.
   * - ``tia_pid.py``
     - PID-Regler-Optimierung: Streckenmodell, Einstellregeln, Simulation (ohne Oberfläche).
   * - ``tia_pid_dialog.py``
     - Fenster der PID-Optimierung (Logger) und Einstellungen dazu (Konfigurationsprogramm).
   * - ``tia_i18n.py``, ``sprachen/``
     - Sprachumschaltung und Sprachdateien (``de.txt`` = Vorlage, ``en.txt`` = Englisch).
   * - ``tia_splash.py``
     - Startbild (Auswahl der Konfiguration, Lade-Anzeige).
   * - ``build_appimage.sh``, ``tools/extract_tr.py``
     - Linux-AppImage bauen; Sprachdateien nach Programmänderungen aktualisieren.
   * - ``tia_common.py``
     - Datenmodell und Konfigurationsdatei (JSON). Wird nicht direkt gestartet.
   * - ``tia_io.py``
     - Lesen der Variablen über S7CommPlus (Bibliothek s7commplus), mehrere Werte je Anfrage.
   * - ``tia_taglist.py``
     - Variablenliste der Steuerung (mit Zwischenspeicher) und Baum für die Auswahl.
   * - ``build.bat``, ``installer.iss``, ``make_icon.py``, ``requirements.txt``
     - Erzeugung der Windows-Installationsdatei (siehe :ref:`installer`).
   * - ``tia_block_dialog.py``
     - Editor für Blöcke (Blocklesemodus), vom Konfigurationsprogramm geöffnet.
   * - ``tia_formula.py``
     - Auswertung der Formeln berechneter Variablen. Wird nicht direkt gestartet.
   * - ``tia_formula_dialog.py``
     - Editor für berechnete Variablen (vom Konfigurationsprogramm geöffnet).
   * - ``tia_branding.py``
     - Programm-Icon und Logo. Wird nicht direkt gestartet.
   * - ``tia_browser.py``
     - Dialog zur Auswahl von Variablen aus der Variablenliste der Steuerung. Wird vom
       Konfigurationsprogramm geöffnet.

Funktionsumfang:

* Aufzeichnung beliebig vieler Variablen in einstellbarem Abtastintervall
* **Mehrere Steuerungen gleichzeitig:** je Steuerung ein eigener Lese-Thread mit
  eigenem Abtastintervall; die Oberfläche bleibt dadurch flüssig
* **Status-LEDs** für jede Verbindung (grau, gelb, grün, rot)
* Projektname und Konfigurationsdateien mit beliebigem Namen (Öffnen-Dialog)
* **Webserver** zum Ansehen der Diagramme im Browser (Tablet, Smartphone)
* **Headless-Betrieb** (ohne Diagramme, nur Aufzeichnung), in der Konfiguration
  einstellbar
* Beim Beenden wird die aktuelle CSV-Datei archiviert
* Diagramme einer Seite untereinander, nebeneinander oder als **Raster (Grid)**
* Elemente eines Blocks können auf verschiedene Diagramme verteilt werden
* CSV-Protokoll mit Zeitstempel in Millisekunden
* Begrenzung der CSV-Dateigröße (Datensätze) mit automatischer ZIP-Archivierung
  in einer Verzeichnisstruktur Name/Jahr/Monat/Tag
* Variablenauswahl aus der Variablenliste der Steuerung (Datenbausteine, Strukturen,
  Arrays, Merker, Ein-/Ausgänge), mit Filter
* Berechnete Variablen aus Formeln (z. B. Mittelwert, Differenz, Integral)
* Blöcke: Ausschnitte von Arrays (erster Index, Anzahl) als Gruppe übernehmen
* Mehrere Diagramme, je Diagramm mehrere Y-Achsen mit eigener Skalierung;
  mehrere Diagramme je Seite/Tab mit Mindesthöhe und Scrollleiste
* Legende mit Livewerten; Kurven per Rechtsklick auf den Namen ausblenden
* Eigenes Logo (rechts oben) und Programm-Icon
* Online-Modus (fortlaufende Anzeige) und Offline-Modus (zurückscrollen, Lineale)
* Schmale Balken für Aktualwerte, optionale Werteanzeige
* Screenshots einzelner Diagramme als PNG oder SVG
* Demo-Modus mit simulierten Werten (ohne SPS)


Installation und Start
======================================================================

Voraussetzungen
----------------------------------------------------------------------

* Python 3.9 oder neuer
* Bibliotheken installieren (Python **3.10 oder neuer**):

  .. code-block:: console

     pip install s7commplus PyQt6 pyqtgraph numpy Flask

  Der Headless-Betrieb braucht kein PyQt6 und kein pyqtgraph; Flask wird nur für
  den Webserver benötigt. ``s7commplus`` ist reines Python (einzige Abhängigkeit:
  ``cryptography``).

Programme starten
----------------------------------------------------------------------

.. code-block:: console

   python tia_config.py [datei.json]     # Konfiguration
   python tia_logger.py [datei.json]     # Logger (Oberfläche oder Headless)

Ohne Dateiangabe wird die **zuletzt benutzte** Konfigurationsdatei geöffnet
(Standard: ``tia_config.json``). Der Name der Datei ist beliebig. Weitere Parameter
des Loggers:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Parameter
     - Wirkung
   * - ``datei.json`` oder ``--config datei.json``
     - Konfigurationsdatei, die verwendet wird (und beim nächsten Start ohne
       Angabe wieder geöffnet wird).
   * - ``--headless``
     - Ohne Oberfläche starten, nur aufzeichnen (überstimmt die Konfiguration).
   * - ``--gui``
     - Oberfläche öffnen, auch wenn die Konfiguration *Headless* verlangt.
   * - ``--demo``
     - Simulierte Werte statt SPS-Verbindung (siehe :ref:`demo-modus`).

Der Logger kann das Konfigurationsprogramm auch selbst öffnen
(**Konfig-Editor** in der Werkzeugleiste), und das Konfigurationsprogramm kann den
Logger starten (**Datei › Logger mit dieser Konfiguration starten**).

Vorbereitung der Steuerung
----------------------------------------------------------------------

Der Logger liest nur. In TIA Portal sind im Normalfall keine Einstellungen nötig:

* **PUT/GET muss nicht freigegeben** und optimierte Datenbausteine müssen nicht
  umgestellt werden – S7CommPlus greift symbolisch zu.
* Die Firewall des PCs muss Verbindungen zur Steuerung auf **TCP-Port 102**
  (ISO-on-TCP) zulassen.
* **Schutzstufe / Zugriffsstufe:** Ist in den CPU-Eigenschaften der lesende
  Zugriff durch ein Passwort geschützt (z. B. Stufe „Lesezugriff“ nur mit
  Passwort), tragen Sie das Passwort in der Steuerungstabelle ein.
* **Sichere PG/HMI-Kommunikation (TLS):** Neuere Firmware (S7-1500 ab V3.1,
  S7-1200 ab V4.7, Projekte ab TIA V19) kann nur verschlüsselt kommunizieren. Die
  Einstellung *TLS: Automatisch* versucht zuerst TLS und fällt sonst auf eine
  unverschlüsselte Verbindung zurück; *An* erzwingt TLS.
* Damit Variablen in der Variablenliste erscheinen, müssen sie im Programm
  „Erreichbar aus HMI/OPC UA/Web API“ sein (Standard in TIA Portal).
* Jede CPU erlaubt nur eine begrenzte Zahl gleichzeitiger HMI-Verbindungen; der
  Logger belegt eine je Steuerung.

.. warning::

   ``s7commplus`` ist eine **inoffizielle** Implementierung, nicht von Siemens. Testen
   Sie neue Konfigurationen zuerst an einer nicht sicherheitsrelevanten Anlage. Der
   Logger liest ausschließlich und schreibt nichts in die Steuerung.


.. _startbild:

Startbild
----------------------------------------------------------------------

Beim Start von Logger und Konfigurationsprogramm erscheint das **Startbild**:

.. figure:: images/startbild.png
   :alt: Startbild
   :width: 80%
   :align: center

   Startbild mit den zuletzt benutzten Konfigurationen.

* **Zuletzt benutzt**: die zuletzt geöffneten Konfigurationen mit Ordner und Änderungsdatum.
  Doppelklick oder **Öffnen** (Eingabetaste) startet mit der markierten Datei.
* **Durchsuchen …**: beliebige Konfigurationsdatei wählen.
* **Neue Konfiguration …**: im Logger wird nach einem Dateinamen gefragt, eine leere
  Konfiguration angelegt und zusätzlich das Konfigurationsprogramm geöffnet; im
  Konfigurationsprogramm beginnt eine neue, noch ungespeicherte Konfiguration.
* **Demo** (nur Logger): mit simulierten Werten starten.
* **Beim Start nicht mehr anzeigen**: künftig sofort mit der zuletzt benutzten Datei
  starten. Wieder einschalten: im Logger **Datei → Startbild beim Programmstart zeigen**.

Nach der Auswahl zeigt das Startbild den Ladefortschritt, bis das Hauptfenster bereit ist.
Wird beim Aufruf eine Konfigurationsdatei angegeben (z. B. ``S7Logger.exe anlage.json``),
entfällt die Auswahl. Das Fenster lässt sich mit der Maus verschieben; **Esc** oder ✕ beendet.


Schnellstart
======================================================================

#. ``tia_config.py`` starten.
#. Im Reiter *Projekt & Steuerungen* einen Projektnamen vergeben und die
   Steuerung(en) eintragen (Name, IP-Adresse; Port, TLS und Passwort meist unverändert).
#. Mit **Aus Variablenliste wählen…** Variablen aus der Steuerung übernehmen (oder
   mit **Variable hinzufügen** den Namen von Hand eintragen).
#. Mit **Verbindung testen** prüfen, ob die Werte korrekt gelesen werden.
#. **Speichern** (bzw. **Speichern unter…** mit eigenem Dateinamen) und das
   Konfigurationsprogramm schließen.
#. ``tia_logger.py`` starten und **▶ Start** drücken.

.. tip::

   Ohne SPS können Sie das Programm mit dem **Demo**-Modus ausprobieren
   (siehe :ref:`demo-modus`).


Konfigurationsprogramm (``tia_config.py``)
======================================================================

.. figure:: images/config_gesamt.png
   :alt: Konfigurationsprogramm
   :width: 90%
   :align: center

   Das Konfigurationsprogramm: Reiter oben, Zuordnungsbaum links, Variablentabelle rechts.

Projekt, Steuerungen und Einstellungen
----------------------------------------------------------------------

Der obere Fensterbereich ist in vier Reiter gegliedert.

**Reiter „Projekt & Steuerungen“**

.. figure:: images/config_projekt_steuerungen.png
   :alt: Reiter Projekt und Steuerungen
   :width: 80%
   :align: center

   Reiter „Projekt & Steuerungen“.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Feld
     - Bedeutung
   * - Projektname
     - Frei wählbarer Name des Projekts. Er erscheint in den Fenstertiteln, im
       Webserver und im Log.
   * - Steuerungen (Tabelle)
     - Eine Zeile je Steuerung: **Name** (eindeutig, auch für die Status-LED),
       **IP-Adresse**, **Port** (Standard 102), **TLS** (*Automatisch*, *Aus*,
       *An*), **Passwort** (Zugriffsstufe der CPU, leer = ohne; wird im Klartext in
       der Konfigurationsdatei gespeichert), **Rolle** (Anmeldung als *HMI*, sonst
       *Engineering* oder *PG* versuchen), **Intervall** (Zeit zwischen zwei Messungen dieser Steuerung, 10 bis
       60000 ms) und **Aktiv** (abgeschaltete Steuerungen werden nicht gelesen).
       Mit **+ Steuerung** und **Steuerung entfernen** ändern Sie die Liste; beim
       Entfernen wandern deren Variablen und Blöcke zur ersten Steuerung.

Jede Steuerung wird im Logger von einem **eigenen Thread** gelesen. Das
Intervall gilt je Steuerung; eine langsame oder ausgefallene Steuerung bremst
die anderen nicht. Die Messwerte aller Steuerungen werden in einer gemeinsamen
CSV-Datei zusammengeführt (eine Spalte je Variable).

**Reiter „Aufzeichnung“**

.. figure:: images/config_aufzeichnung.png
   :alt: Reiter Aufzeichnung
   :width: 80%
   :align: center

   Reiter „Aufzeichnung“.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Feld
     - Bedeutung
   * - CSV-Datei schreiben
     - Schaltet die CSV-Datei ein oder aus (z. B. aus, wenn nur in eine Datenbank
       aufgezeichnet werden soll; siehe :ref:`datenbank`).
   * - CSV-Ordner
     - Zielordner für die Protokolldateien. Ein relativer Pfad bezieht sich
       auf den Programmordner.
   * - CSV-Name
     - Name der Aufzeichnung. Er ist Präfix der Dateinamen und Name des
       Archiv-Unterordners (Standard: ``log``). Die Zeichen
       ``\ / : * ? " < > |`` sind nicht erlaubt.
   * - Max. Datensätze je Datei
     - Obergrenze für die Anzahl der Datensätze (Zeilen) je CSV-Datei.
       ``0`` = unbegrenzt. Ist die Zahl erreicht, wird die Datei gepackt und
       archiviert (siehe :ref:`csv-archiv`).
   * - Archiv-Ordner
     - Basisordner des Archivs (Standard: ``archiv``). Ein relativer Pfad
       bezieht sich auf den Programmordner.
   * - Beim Beenden archivieren
     - Ist das Häkchen gesetzt (Standard), wird beim Beenden des Loggers auch die
       aktuelle, noch nicht volle CSV-Datei gepackt und archiviert.

**Reiter „Anzeige“**

.. figure:: images/config_anzeige.png
   :alt: Reiter Anzeige
   :width: 80%
   :align: center

   Reiter „Anzeige“.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Feld
     - Bedeutung
   * - Anzeigefenster (online)
     - Breite des sichtbaren Zeitfensters im Online-Modus in Sekunden.
   * - Standard-Anordnung der Seiten
     - Anordnung beim Start: *Untereinander*, *Nebeneinander* oder *Tabs*.
   * - Diagramme auf einer Seite
     - *Automatisch* (wie die Standard-Anordnung), *Untereinander*,
       *Nebeneinander* oder *Raster (Grid)*.
   * - Raster-Spalten
     - Spaltenzahl bei *Raster*; *automatisch* wählt sie aus der Diagrammzahl.
   * - Balken für Aktualwerte anzeigen
     - Schaltet die schmalen Balken neben den Diagrammen standardmäßig ein.
   * - Logo (rechts oben)
     - Bilddatei (PNG, SVG, JPG), die im Logger rechts oben in der Menüleiste
       angezeigt wird (auf 28 Pixel Höhe skaliert). Ein relativer Pfad bezieht
       sich auf den Programmordner. Ohne Angabe wird ein Standard-Symbol gezeigt.
   * - Programm-Icon
     - Icon für Fenster und Taskleiste (PNG, ICO oder SVG). Ohne Angabe wird das
       Logo bzw. das Standard-Symbol verwendet.

**Reiter „Datenbank“**

Auswahl und Zugangsdaten einer Datenbank, in die zusätzlich oder statt der
CSV-Datei aufgezeichnet wird (SQLite, MariaDB/MySQL, TimescaleDB/PostgreSQL), mit
dem Knopf **Datenbank testen**. Einzelheiten im Kapitel :ref:`datenbank`.

**Reiter „Webserver & Headless“**

.. figure:: images/config_web_headless.png
   :alt: Reiter Webserver und Headless
   :width: 80%
   :align: center

   Reiter „Webserver & Headless“.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Feld
     - Bedeutung
   * - Webserver starten
     - Startet mit dem Logger einen Webserver (siehe :ref:`webserver`).
   * - Adresse (Host) / Port
     - ``0.0.0.0`` macht den Server im ganzen Netzwerk erreichbar, ``127.0.0.1``
       nur auf dem eigenen Rechner. Standard-Port: 8080.
   * - Zugriffscode
     - Optional. Ist ein Code gesetzt, muss er beim Aufruf mit ``?token=CODE``
       angegeben werden.
   * - Aktualisierung im Browser
     - Wie oft die Browserseite neue Daten abholt (200 bis 60000 ms).
   * - Headless-Modus
     - Der Logger startet ohne Oberfläche und zeichnet nur auf (siehe
       :ref:`headless`).

Aufbau: Diagramme, Y-Achsen und Variablen
----------------------------------------------------------------------

Die Anzeige ist hierarchisch aufgebaut:

.. code-block:: text

   Diagramm
   ├── Y-Achse 1 (links)
   │   ├── Variable A
   │   └── Variable B
   └── Y-Achse 2 (rechts)
       └── Variable C

* Jedes **Diagramm** erscheint im Logger als eigenes, verschiebbares Fenster.
* Jedes Diagramm hat mindestens eine **Y-Achse**. Die erste Achse liegt links,
  alle weiteren liegen rechts. Jede Achse skaliert unabhängig.
* Jede **Variable** gehört zu genau einer Y-Achse eines Diagramms.

Der Baum auf der linken Seite zeigt diese Struktur. Darunter befinden sich die
Schaltflächen:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Schaltfläche
     - Wirkung
   * - **+ Diagramm**
     - Legt ein neues Diagramm mit einer Y-Achse an.
   * - **+ Y-Achse**
     - Fügt dem ausgewählten Diagramm (bzw. dem Diagramm der Auswahl) eine
       weitere Y-Achse hinzu.
   * - **Entfernen**
     - Entfernt das ausgewählte Diagramm, die ausgewählte Y-Achse oder die
       ausgewählte Variable. Betroffene Variablen wandern dabei auf die erste
       Achse bzw. das erste Diagramm. Das letzte Diagramm und die letzte Achse
       eines Diagramms können nicht entfernt werden.

Eigenschaften von Diagramm und Y-Achse
----------------------------------------------------------------------

.. figure:: images/config_eigenschaften.png
   :alt: Eigenschaften von Diagramm und Y-Achse
   :width: 90%
   :align: center

   Eigenschaften des gewählten Diagramms bzw. der gewählten Y-Achse.

Wählen Sie im Baum ein Diagramm oder eine Y-Achse aus. Im Bereich
*Eigenschaften* darunter können Sie ändern:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Feld
     - Bedeutung
   * - Name
     - Bezeichnung des Diagramms bzw. der Y-Achse (wird als Titel bzw.
       Achsenbeschriftung angezeigt).
   * - Seite (Tab)
     - *Nur bei Diagrammen.* Diagramme mit gleichem Seitennamen werden
       gemeinsam auf einer Seite (Tab bzw. Dock) angezeigt, z. B. ``Prozess``
       oder ``Alarme``. Leer = Standardseite (siehe :ref:`seiten`).
   * - Regler
     - *Nur bei Diagrammen.* Haken **PID-Regler-Optimierung** und **Einstellen …**:
       Soll-, Ist- und Stellwert für die Berechnung der Reglerparameter im Logger
       festlegen (siehe :ref:`pid-optimierung`).
   * - Auto-Skalierung
     - *Nur bei Y-Achsen.* Aktiv: Die Achse passt sich automatisch an die
       sichtbaren Daten an. Inaktiv: Es gelten die festen Grenzen
       *Y min* und *Y max*.
   * - Y min / Y max
     - Feste Achsengrenzen. *Y max* muss größer als *Y min* sein.

Variablen anlegen
----------------------------------------------------------------------

.. figure:: images/config_variablen.png
   :alt: Variablentabelle
   :width: 90%
   :align: center

   Die Variablentabelle mit Steuerung, Tag-Name, Typ, Farbe und Formel.

Jede Zeile der Variablentabelle beschreibt einen Tag der Steuerung:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Spalte
     - Bedeutung
   * - Name
     - Eindeutiger Name (wird auch als CSV-Spaltenüberschrift verwendet).
       Das Zeichen ``;`` ist nicht erlaubt.
   * - Steuerung
     - Steuerung, aus der die Variable gelesen wird (Auswahl aus der Tabelle der
       Steuerungen).
   * - Diagramm › Y-Achse
     - Zuordnung der Variablen (Auswahlliste oder Drag & Drop, siehe unten).
   * - Variable in der Steuerung
     - Symbolischer Name, wie ihn die Variablenliste zeigt:
       ``<Datenbaustein>.<Variable>``, Strukturglieder mit Punkt, Array-Elemente mit
       Index, z. B. ``Anlage_DB.Motor[2].Drehzahl``. PLC-Variablen (Merker, Ein-,
       Ausgänge) stehen unter ``MArea``, ``IArea`` bzw. ``QArea``. Am sichersten
       übernehmen Sie die Namen aus der Variablenliste.
   * - Typ
     - Datentyp: ``BOOL``, ``BYTE``, ``WORD``, ``DWORD``, ``LWORD``, ``SINT``,
       ``INT``, ``DINT``, ``LINT``, ``USINT``, ``UINT``, ``UDINT``, ``ULINT``,
       ``REAL``, ``LREAL``, ``TIME``, ``LTIME``, ``S5TIME``, ``CHAR``, ``WCHAR``.
       Er bestimmt die Anzeige (Nachkommastellen); dekodiert wird nach dem Typ, den
       die Steuerung meldet. Zeiten werden in Millisekunden aufgezeichnet.
   * - Farbe
     - Linienfarbe; Klick öffnet die Farbauswahl.
   * - Werteanzeige
     - Aktiv: Die Variable erscheint in der Werte-/Lineal-Tabelle des Loggers.
   * - Balken
     - Aktiv: Für die Variable wird ein schmaler Balken neben dem Diagramm
       angezeigt.
   * - Testwert
     - Ergebnis von **Verbindung testen**.
   * - Formel
     - Nur bei berechneten Variablen: die Formel (Doppelklick öffnet den Editor).

Zuordnung per Drag & Drop
----------------------------------------------------------------------

.. figure:: images/config_dragdrop.png
   :alt: Drag & Drop im Zuordnungsbaum
   :width: 90%
   :align: center

   Variablen im Baum auf eine Y-Achse ziehen.

Variablen können im Baum mit der Maus verschoben werden:

* **Auf eine Y-Achse ziehen:** Die Variable gehört danach zu dieser Achse.
* **Auf eine andere Variable ziehen:** Die Variable übernimmt die Y-Achse (und
  damit das Diagramm) der Zielvariable.
* **Auf ein Diagramm ziehen:** Die Variable wird der ersten Y-Achse dieses
  Diagramms zugeordnet.

Die Auswahlliste *Diagramm › Y-Achse* in der Tabelle und der Baum sind immer
synchron.

.. _berechnete-variablen:

Berechnete Variablen (Formeln)
----------------------------------------------------------------------

.. figure:: images/formeleditor.png
   :alt: Formeleditor
   :width: 90%
   :align: center

   Der Editor für berechnete Variablen.

Neben den aus der SPS gelesenen Variablen können Sie **berechnete Variablen**
anlegen, deren Werte der Logger bei jeder Messung aus anderen Variablen
berechnet. Sie erscheinen wie normale Variablen in Diagrammen, Balken,
Legende, Wertetabelle und in der CSV-Datei.

Mit **Berechnete Variable…** öffnet sich der Editor:

* **Name** der neuen Variable.
* **Formel** im Textfeld. Variablen werden in geschweiften Klammern
  angegeben, z. B. ``({Temp_Vorlauf} + {Temp_Ruecklauf}) / 2``. Ein
  Doppelklick in der Variablenliste fügt den Namen ein, ein Doppelklick in
  der Funktionsliste die Funktion.
* **Prüfen / Berechnen:** Der Editor prüft die Formel (Syntax, bekannte
  Variablen) und berechnet sie mit frei eingebbaren **Testwerten**. Das
  Ergebnis erscheint direkt darunter.

Die neue Variable wird dem ausgewählten Diagramm bzw. der ausgewählten Y-Achse
zugeordnet (änderbar wie bei jeder Variable). Ein Doppelklick auf die Spalte
*Formel* öffnet den Editor erneut.

Erlaubt sind:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Element
     - Beispiel / Bedeutung
   * - Rechenoperatoren
     - ``+  -  *  /  //  %  **``
   * - Vergleiche, Logik
     - ``<  >  <=  >=  ==  !=``, ``and``, ``or``, ``not``
   * - Bedingung
     - ``100 if {Druck} > 5 else 0``
   * - Konstanten
     - ``pi``, ``e``, ``tau``
   * - Mathematik
     - ``abs, min, max, sqrt, sin, cos, tan, asin, acos, atan, atan2, exp, ln,
       log10, log, floor, ceil, round, hypot, radians, degrees, sign, clamp``
   * - Zeitfunktionen
     - ``ddt(x)`` Ableitung pro Sekunde, ``integ(x)`` Integral (x · s),
       ``avg(x, n)`` gleitender Mittelwert über *n* Messwerte

Beispiele:

.. code-block:: text

   {Prozess.Temperatur} * 1.8 + 32               Umrechnung °C in °F
   {Druck_Ein} - {Druck_Aus}                     Differenzdruck
   avg({Durchfluss}, 20)                         geglätteter Durchfluss
   integ({Durchfluss}) / 3600                    Summenmenge (bei Durchfluss in 1/h)
   clamp({Fuellstand}, 0, 100)                   auf 0 bis 100 begrenzt

Hinweise:

* Ist ein Wert nicht berechenbar (Division durch 0, fehlende Messung,
  ungültiger Bereich wie ``sqrt`` einer negativen Zahl), ist das Ergebnis
  *kein Wert* (leeres CSV-Feld, Lücke in der Kurve).
* Eine berechnete Variable darf nur Variablen verwenden, die **weiter oben**
  in der Tabelle stehen (echte Variablen immer, berechnete nur wenn früher
  definiert). Das wird beim Speichern geprüft.
* Wird eine Variable umbenannt, müssen Formeln, die sie verwenden, angepasst
  werden. Der Name in der Formel muss exakt übereinstimmen.
* Aus Sicherheitsgründen wird kein beliebiger Programmcode ausgeführt, nur die
  oben aufgeführten Elemente.
* ``ddt``, ``integ`` und ``avg`` merken sich ihren Zustand während der
  Aufzeichnung und beginnen bei jedem **▶ Start** neu.
* Berechnete Variablen werden nicht aus der SPS gelesen und fehlen beim
  **Verbindung testen**.

.. _blocklesemodus:

Blocklesemodus
----------------------------------------------------------------------

.. figure:: images/blockeditor.png
   :alt: Blockeditor
   :width: 90%
   :align: center

   Der Blockeditor mit Blocktabelle und Elementbaum (Namen und Ziel je Element).

Alle Variablen einer Steuerung werden je Messzyklus in wenigen gemeinsamen Anfragen
gelesen (je Anfrage höchstens 50 Variablen, einstellbar über ``tags_je_anfrage`` in
der Konfigurationsdatei). Ein **Block** fasst die Elemente eines Arrays bequem zusammen: Statt
jedes Element einzeln anzulegen, geben Sie das Array, den ersten Index und die Anzahl
an.

Mit **Blöcke (Blocklesemodus)…** öffnet sich der Editor. Jede Zeile ist ein
Block mit folgenden Angaben:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Feld
     - Bedeutung
   * - Name
     - Name des Blocks. Jedes Element wird zur Variable ``Name[0]``,
       ``Name[1]``, …, ``Name[n-1]``. Nicht erlaubt: ``; { } [ ]``.
   * - Steuerung
     - Steuerung, aus der der Block gelesen wird.
   * - Array
     - Name des Arrays **ohne Index**, z. B. ``Mess_DB.Werte`` oder
       ``Anlage_DB.Motor[1].Historie``.
   * - Erster Index
     - Index des ersten gelesenen Elements, wie in TIA Portal (bei
       ``Array[1..100]`` also ab 1).
   * - Format
     - Datentyp der Array-Elemente (für die Anzeige; dekodiert wird nach dem Typ,
       den die Steuerung meldet).
   * - Anzahl
     - Anzahl der Werte (1 bis 1000).
   * - Diagramm › Y-Achse
     - Zuordnung aller Elemente des Blocks (einzelne Elemente lassen sich im Baum
       abweichend zuordnen, siehe unten).
   * - Farbe
     - Das erste Element erhält diese Farbe, die weiteren unterscheiden sich
       im Farbton.
   * - Werteanzeige / Balken
     - Gilt für alle Elemente des Blocks (Balken sind standardmäßig aus).
   * - Bereich
     - Berechnete Anzeige, z. B. ``Mess_DB.Werte[1] … Mess_DB.Werte[20] (80 Bytes)``.

Beispiel: Array ``Mess_DB.Werte`` (``Array[1..100] of Real``), erster Index 1,
Anzahl 20 liest ``Mess_DB.Werte[1]`` bis ``Mess_DB.Werte[20]`` und erzeugt die
Variablen ``Block[0]`` bis ``Block[19]`` (Name des Blocks mit Elementnummer ab 0).

Arrays lassen sich auch direkt im Dialog **Aus Variablenliste wählen…** als Block
übernehmen (Array markieren, **Markiertes Array als Block…** oder Doppelklick).

**Markierten Block testen** liest den Block einmal aus der Steuerung und zeigt die
ersten Werte sowie die Lesezeit an.

Hinweise:

* Die Block-Elemente sind normale Variablen: Sie erscheinen in Diagrammen,
  Legende, Wertetabelle, Balken und CSV-Datei und können in **Formeln**
  verwendet werden, z. B. ``{Messwerte[3]} - {Messwerte[4]}``.
* **Elementnamen ändern:** Im unteren Teil des Blockeditors zeigt ein **Baum**
  alle Blöcke mit ihren Elementen (Block aufklappen; ein markierter Block wird
  automatisch aufgeklappt). Per Doppelklick auf die Spalte *Name* erhält ein
  Element einen eigenen Namen, z. B. ``Druck Vorlauf`` statt ``Messwerte[1]``.
  Ein leerer Name stellt den Standardnamen wieder her. Die Namen müssen
  eindeutig sein und dürfen ``; { }`` nicht enthalten. In der Konfigurationsdatei stehen
  sie unter ``elementnamen`` des Blocks.
* **Elemente in verschiedenen Diagrammen:** Im Baum des Blockeditors hat jedes
  Element in der letzten Spalte *Diagramm › Y-Achse* eine Auswahlliste. Der Eintrag
  *(wie Block)* verwendet das Ziel des Blocks, jeder andere Eintrag stellt dieses
  Element in einem anderen Diagramm bzw. an einer anderen Y-Achse dar. Mit
  **Für alle Elemente des markierten Blocks setzen** wird das gewählte Ziel für
  alle Elemente auf einmal übernommen. Gelesen wird der Block weiterhin mit
  **einer** Anfrage; in der Konfigurationsdatei stehen abweichende Ziele unter
  ``elementziele`` (Index: [Diagramm, Achse]). Im Variablenbaum der Konfiguration
  erscheinen die abweichend zugeordneten Elemente zusätzlich unter der Achse, in
  der sie dargestellt werden.
* Im Variablenbaum der Konfiguration erscheint jeder Block als eine Zeile
  (``▦ Block …``) unter seiner Y-Achse. Mit **Entfernen** wird der markierte
  Block gelöscht. Wird ein Diagramm oder eine Y-Achse entfernt, wandern die
  zugehörigen Blöcke wie Variablen auf die erste Achse.
* Elemente, die es nicht gibt (Ausschnitt reicht über das Array hinaus), bleiben
  ohne Wert und werden gemeldet; die übrigen werden weiter gelesen.
* Viele Elemente bedeuten viele Kurven: Teilen Sie große Blöcke auf mehrere
  Diagramme bzw. Y-Achsen auf oder schalten Sie *Werteanzeige* ab.

Variablen aus der Steuerung wählen
----------------------------------------------------------------------

.. figure:: images/symbolbaum.png
   :alt: Variablenliste
   :width: 90%
   :align: center

   Auswahl von Variablen aus der Variablenliste der Steuerung.

Mit **Aus Variablenliste wählen…** öffnet sich die Variablenliste der Steuerung (bei
mehreren Steuerungen wird zuerst gefragt, welche). Sie wird über S7CommPlus direkt
aus der CPU gelesen – mit Datenbausteinen, Strukturen (UDTs), Arrays sowie Merkern,
Ein- und Ausgängen.

#. **Variablenliste laden.** Beim ersten Öffnen wird die Liste automatisch aus der
   Steuerung gelesen, später mit **Variablenliste aus Steuerung laden** aktualisiert
   (nach einer Programmänderung). Das dauert je nach Projekt einige Sekunden bis
   Minuten und läuft im Hintergrund.
#. **Suchen.** Der Baum zeigt die Datenbausteine und darunter *Merker (MArea)*,
   *Eingänge (IArea)* und *Ausgänge (QArea)*. Strukturen und Arrays lassen sich
   aufklappen. Ab zwei Zeichen im **Filter** erscheint eine Trefferliste aller
   passenden Namen.
#. **Auswählen.** Lesbare Werte anhaken. Bereits angelegte Variablen sind angehakt
   und ausgegraut. Die Auswahl bleibt beim Filtern erhalten.
#. **Arrays als Block.** Ein Array markieren und **Markiertes Array als Block…**
   wählen (oder doppelklicken), dann ersten Index und Anzahl festlegen.
#. **Übernehmen.** Unter *Neue Variablen anlegen in* das Diagramm bzw. die Y-Achse
   wählen und **Auswahl übernehmen** drücken. Name der neuen Variablen ist der
   Variablenname der Steuerung; Blöcke erhalten den Namen des Arrays.
#. **Prüfen.** Mit **Verbindung testen** die gelesenen Werte kontrollieren.

Hinweise:

* Die Liste wird je Steuerung zwischengespeichert (Ordner ``taglisten`` im
  Datenordner). Auch der Logger verwendet sie, um Namen den internen Kennungen der
  CPU zuzuordnen; findet er einen Namen nicht, liest er die Liste beim Verbinden
  selbstständig neu.
* Texte, Datum/Uhrzeit und andere nicht als Zahl darstellbare Typen sind grau
  dargestellt.
* Von großen Arrays werden höchstens 500 Elemente einzeln aufgeführt; größere
  Bereiche übernehmen Sie als Block.

Verbindung testen
----------------------------------------------------------------------

**Verbindung testen** verbindet sich nacheinander mit jeder Steuerung, liest
deren Variablen einmal und trägt das Ergebnis in die Spalte *Testwert* ein.
Fehler einzelner Variablen werden dort angezeigt (z. B. *Variable in der Steuerung
nicht gefunden*); kann eine Steuerung nicht erreicht werden, meldet das ein
Hinweisfenster mit Name, IP-Adresse und Port. Beim ersten Test liest das Programm
dazu einmal die Variablenliste der Steuerung, falls sie noch nicht vorliegt.

Beim Speichern werden die Variablennamen formal geprüft (nicht leer, kein ``;``,
Klammern vollständig). Ob es eine Variable tatsächlich gibt, zeigt erst der
Verbindungstest.

Speichern und Laden
----------------------------------------------------------------------

Das Menü **Datei** des Konfigurationsprogramms enthält:

* **Neu** – leere Konfiguration mit einer Steuerung; der Dateiname wird beim
  ersten Speichern abgefragt.
* **Öffnen…** (``Strg+O``) – lädt eine Konfigurationsdatei (JSON) mit **beliebigem
  Namen**. Ältere Konfigurationen mit nur einer Steuerung und ohne Y-Achsen
  werden übernommen.
* **Speichern** (``Strg+S``) und **Speichern unter…** (``Strg+Umschalt+S``) –
  schreiben in die aktuelle bzw. eine neue Datei (die Endung ist immer ``.json``). Vor dem Speichern wird geprüft, dass Steuerungs- und
  Variablennamen eindeutig und nicht leer sind, jede Steuerung eine
  IP-Adresse hat, die Formeln gültig sind und bei festen Y-Achsen *Y max* größer
  als *Y min* ist.
* **INI-Datei umwandeln …** – ältere INI-Konfigurationen einmalig in JSON umwandeln
  (siehe :ref:`ini-umwandeln`).
* **Logger mit dieser Konfiguration starten** (``Strg+R``) – speichert und
  startet den Logger mit dieser Datei.

Der Titel des Fensters zeigt Projektname und Dateiname. Die zuletzt benutzte
Datei wird gemerkt (Datei ``tia_last.txt``); Logger und Konfigurationsprogramm
öffnen sie beim nächsten Start ohne Parameter wieder.

.. note::

   Der Logger liest die Konfiguration bei jedem **Start**. Änderungen wirken
   daher erst nach erneutem Drücken von **▶ Start**.

Aufbau der Konfigurationsdatei (JSON)
----------------------------------------------------------------------

Die Konfiguration wird als **JSON-Datei** gespeichert (UTF-8, eingerückt) und kann bei Bedarf auch von Hand
bearbeitet werden – mit jedem Texteditor, besser mit einem, der JSON prüft (z. B. Notepad++,
Visual Studio Code). Beispiel:

.. code-block:: json

   {
     "format": "TIA Datenlogger Konfiguration",
     "version": 1,
     "einstellungen": {
       "projekt": "Prüfstand 3",
       "ip": "192.168.0.1",
       "port": 102,
       "intervall_ms": 200,
       "csv_ordner": "logs",
       "csv_name": "log",
       "max_records": 100000,
       "archiv_ordner": "archiv",
       "fenster_s": 60,
       "anordnung": "untereinander",
       "balken": true,
       "logo": "C:/Firma/logo.png",
       "icon": "C:/Firma/icon.ico",
       "archiv_beenden": true,
       "seite_anordnung": "raster",
       "raster_spalten": 2,
       "web_aktiv": true,
       "web_host": "0.0.0.0",
       "web_port": 8080,
       "web_token": "geheim",
       "web_intervall_ms": 1000,
       "headless": false
     },
     "steuerungen": [
       {
         "name": "Kessel",
         "ip": "192.168.0.1",
         "port": 102,
         "tls": "auto",
         "passwort": "",
         "rolle": "hmi",
         "intervall_ms": 200,
         "tags_je_anfrage": 50,
         "aktiv": true
       },
       {
         "name": "Pumpe",
         "ip": "192.168.0.2",
         "port": 102,
         "tls": "an",
         "passwort": "geheim",
         "rolle": "hmi",
         "intervall_ms": 500,
         "tags_je_anfrage": 50,
         "aktiv": true
       }
     ],
     "diagramme": [
       {
         "name": "Prozess",
         "seite": "Prozess",
         "achsen": [
           {
             "name": "Temperatur",
             "auto": true,
             "y_min": 0.0,
             "y_max": 100.0
           },
           {
             "name": "Druck",
             "auto": false,
             "y_min": 0.0,
             "y_max": 10.0
           }
         ]
       }
     ],
     "variablen": [
       {
         "name": "Temperatur_Kessel",
         "tag": "Kessel_DB.Temperatur",
         "typ": "REAL",
         "farbe": "#d62728",
         "wert_anzeigen": true,
         "diagramm": 1,
         "achse": 1,
         "balken": true,
         "formel": "",
         "steuerung": 1
       }
     ],
     "bloecke": [
       {
         "name": "Messwerte",
         "tag": "Mess_DB.Werte",
         "start": 1,
         "typ": "REAL",
         "anzahl": 20,
         "diagramm": 1,
         "achse": 1,
         "farbe": "#1f77b4",
         "wert_anzeigen": true,
         "balken": false,
         "steuerung": 2,
         "elementziele": {
           "3": [
             2,
             1
           ]
         }
       }
     ]
   }

Aufbau:

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Schlüssel
     - Inhalt
   * - ``format``, ``version``
     - Kennung der Datei und Version des Aufbaus (derzeit 1).
   * - ``einstellungen``
     - Projekt, Aufzeichnung (CSV, Archiv, Datenbank), Anzeige, Webserver, Headless.
   * - ``steuerungen``
     - Liste der Steuerungen (Reihenfolge = Nummer, auf die ``steuerung`` verweist).
   * - ``diagramme``
     - Liste der Diagramme, je Diagramm die Liste ``achsen`` (Y-Achsen) und ggf. die
       PID-Einstellungen (``pid_…``).
   * - ``variablen``
     - Normale und berechnete Variablen (``formel`` nicht leer).
   * - ``bloecke``
     - Blöcke des Blocklesemodus; ``elementnamen`` = eigene Namen einzelner Elemente
       (``{"1": "Druck Vorlauf"}``), ``elementziele`` = abweichendes Diagramm und Achse
       einzelner Elemente (``{"3": [2, 1]}``).
   * - ``trigger``
     - Trigger des Ereignisprotokolls.

Zahlen und Wahrheitswerte stehen mit ihrem Typ in der Datei (``200``, ``1.5``,
``true``/``false``). Fehlende Schlüssel erhalten beim Laden ihren Standardwert,
unbekannte werden ignoriert. Ist die Datei kein gültiges JSON (z. B. ein vergessenes
Komma), meldet das Programm die Zeile der Fehlerstelle.

``diagramm``, ``achse`` und ``steuerung`` sind Nummern ab 1. In
``einstellungen`` spiegeln ``ip``, ``port`` und ``intervall_ms`` die erste Steuerung;
fehlt ``steuerungen``, entsteht daraus genau eine Steuerung. ``tls`` ist ``auto``,
``aus`` oder ``an``; ``rolle`` ist ``hmi``, ``es`` oder ``pg``. ``tags_je_anfrage``
begrenzt die Zahl der Variablen je Leseanfrage (Standard 50, nur in der Datei
einstellbar; bei Fehlern wie „PDU zu groß“ verkleinern). Das **Passwort steht im
Klartext** in der Datei – schützen Sie die Datei entsprechend. Bei Blöcken ist
``tag`` das Array ohne Index und ``start`` der erste Index. ``seite_anordnung`` ist leer (automatisch), ``untereinander``,
``nebeneinander`` oder ``raster``; ``raster_spalten: 0`` wählt die Spaltenzahl
automatisch. Die Variablen eines Blocks
(``Messwerte[0]`` …) werden beim Laden erzeugt und stehen nicht unter ``variablen``
in der Datei.

.. _ini-umwandeln:

Ältere INI-Dateien umwandeln
----------------------------------------------------------------------

Frühere Versionen speicherten die Konfiguration als Konfigurationsdatei. Diese werden **nicht
mehr direkt geöffnet**, sondern einmalig in eine JSON-Datei umgewandelt; die Konfigurationsdatei
selbst bleibt dabei unverändert:

* **Konfigurationsprogramm › Datei › INI-Datei umwandeln …** – eine oder mehrere
  Konfigurationsdateien wählen; neben jeder entsteht eine gleichnamige ``.json``-Datei. Bei einer
  einzelnen Datei wird das Ergebnis gleich geöffnet.
* Wird im Konfigurationsprogramm (Öffnen, Startbild) eine INI-Datei gewählt, bietet
  es die Umwandlung direkt an.
* Für viele Dateien auf einmal (Python-Quellen):

  .. code-block:: console

     python tools/ini2json.py anlage1.ini anlage2.ini        # -> anlage1.json, anlage2.json
     python tools/ini2json.py alt.ini -o neu.json -f        # anderer Name, überschreiben

Der Logger meldet beim Start mit einer Konfigurationsdatei, dass sie umgewandelt werden muss. War
zuletzt eine INI-Datei geöffnet und gibt es daneben bereits die umgewandelte
``.json``-Datei, wird diese automatisch verwendet. Alle Inhalte – auch Trigger,
PID-Einstellungen und Blöcke – werden übernommen.



Logger (``tia_logger.py``)
======================================================================

Bedienelemente
----------------------------------------------------------------------

.. figure:: images/logger_hauptfenster.png
   :alt: Hauptfenster des Loggers
   :width: 90%
   :align: center

   Das Hauptfenster des Loggers mit Werkzeugleiste, Diagrammen, Wertetabelle und Statusleiste.

Werkzeugleiste (oben):

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Element
     - Funktion
   * - **▶ Start / ■ Stop**
     - Startet bzw. beendet Aufzeichnung und CSV-Logging.
   * - **Online / Offline**
     - Schaltet zwischen fortlaufender Anzeige und Rückblick um.
   * - **CSV laden**
     - Öffnet eine gespeicherte CSV-Datei zur Ansicht (Offline-Modus).
   * - **Konfiguration**
     - Startet das Konfigurationsprogramm.
   * - **Werteanzeige**
     - Blendet die Wertetabelle (rechts) ein oder aus.
   * - **Balken**
     - Blendet die schmalen Balken neben den Diagrammen ein oder aus.
   * - **Y-Auto**
     - Aktiv: alle Y-Achsen werden automatisch skaliert und überschreiben feste
       Bereiche. Inaktiv: Es gelten die Einstellungen der Konfiguration.
   * - **Bool im Diagramm**
     - Zeichnet BOOL-Variablen zusätzlich als gefüllte Treppenlinie im Diagramm
       (abhängig von der Y-Achse). Standard: aus, BOOLs erscheinen nur als
       Streifen in der Legende.
   * - **Lineale zurücksetzen**
     - Setzt die beiden Lineale (Offline) auf ein Drittel und zwei Drittel des
       sichtbaren Zeitbereichs.
   * - **Demo**
     - Simulierte Werte statt SPS (siehe :ref:`demo-modus`).
   * - **Screenshot**
     - Öffnet eine Liste der Diagramme; das gewählte Diagramm wird als PNG
       oder SVG gespeichert (siehe :ref:`screenshots`).
   * - **Fenster [s]**
     - Breite des sichtbaren Zeitfensters in Sekunden (1 bis 604800).

Am unteren Fensterrand befindet sich die **Zeit-Scrollleiste** (nur im
Offline-Modus aktiv). Die Statuszeile zeigt Verbindungsmeldungen und den
Pfad der gespeicherten CSV-Datei.

Das Menü **Ansicht** enthält die Anordnung der Diagramme, eine Liste zum
Ein- und Ausblenden einzelner Diagramme sowie die Schalter für Werteanzeige
und Balken.

Aufzeichnung starten und beenden
----------------------------------------------------------------------

#. **▶ Start** drücken. Der Logger lädt die Konfiguration neu, baut die
   Diagramme auf und verbindet sich mit den Steuerungen.
#. Jede Steuerung wird in ihrem eigenen Intervall gelesen. Die Messwerte werden
   zu Zeilen zusammengeführt und in die CSV-Datei geschrieben.
#. **■ Stop** beendet die Aufzeichnung und schließt die Datei. Beim Beenden des
   Programms wird automatisch gestoppt und – bei gesetzter Option – die
   aktuelle CSV-Datei archiviert (siehe :ref:`csv-archiv`).

Bei Verbindungsverlust versucht der Logger selbstständig, die Verbindung
wiederherzustellen, und meldet dies in der Statuszeile. Während der Pause
entstehen Lücken in den Daten – nur bei den Variablen der betroffenen
Steuerung, die übrigen laufen weiter.

Das Lesen, die Berechnung der Formeln und das Schreiben der CSV-Datei laufen in
eigenen Threads, getrennt von der Oberfläche. Die Anzeige holt sich nur etwa
zehnmal pro Sekunde einen Ausschnitt der Daten und zeichnet unsichtbare Kurven
nicht neu; dadurch bleibt die Bedienung auch bei vielen Variablen flüssig.

Menü **Datei** des Loggers: **Config laden …** (``Strg+O``, Dateidialog für eine
beliebig benannte Konfigurationsdatei), **Konfiguration neu laden** (``F5``),
**Konfig-Editor**, **CSV laden**, **Webserver-Adresse …** und **Beenden**.
Der Fenstertitel zeigt den Projektnamen und die Konfigurationsdatei.

.. _status-led:

Status-LEDs der Verbindungen
----------------------------------------------------------------------

.. figure:: images/status_leds.png
   :alt: Status-LEDs
   :width: 70%
   :align: center

   Status-LEDs in der Statusleiste: grün, gelb, rot, grau.

In der Statusleiste zeigt für jede Steuerung eine **LED** mit ihrem Namen den
Verbindungszustand:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Farbe
     - Bedeutung
   * - grau
     - Steuerung nicht aktiv (abgeschaltet oder Aufzeichnung gestoppt).
   * - gelb
     - Verbindung wird aufgebaut.
   * - grün
     - Verbindung steht, es wird gelesen.
   * - rot
     - Verbindungs- oder Lesefehler; der Logger versucht es erneut.

Der Tooltip der LED zeigt die Statusmeldung (bei Fehlern den Fehlertext) und die
Zykluszeit der letzten Leseanfrage.
Im Webserver erscheinen dieselben LEDs.

Online-Modus
----------------------------------------------------------------------

.. figure:: images/logger_online.png
   :alt: Online-Modus
   :width: 90%
   :align: center

   Online-Modus: fortlaufende Anzeige der letzten Sekunden.

Im Online-Modus läuft die Zeitachse mit den neuesten Daten mit. Es werden
immer die letzten *N* Sekunden angezeigt (Einstellung **Fenster [s]**). Die
Wertetabelle zeigt in der Spalte *Aktuell* den jeweils letzten Messwert.
Die Aufzeichnung läuft unabhängig von der Anzeige weiter.

Offline-Modus
----------------------------------------------------------------------

.. figure:: images/logger_offline.png
   :alt: Offline-Modus
   :width: 90%
   :align: center

   Offline-Modus: Rückblick mit Scrollleiste.

Im Offline-Modus wird die Anzeige eingefroren, und Sie können in der Zeit
zurückblättern:

* **Zeit-Scrollleiste** unten: durch die aufgezeichneten Daten blättern.
* **Maus:** Im Diagramm mit gedrückter Maustaste ziehen, um die Zeitachse zu
  verschieben, und mit dem Mausrad zoomen. Scrollleiste und
  *Fenster [s]* folgen automatisch.
* **Fenster [s]:** Breite des sichtbaren Zeitbereichs.

.. note::

   Beim Wechsel in den Offline-Modus wird eine Momentaufnahme aller bis dahin
   gemessenen Daten erstellt. Läuft die Aufzeichnung weiter, erscheinen neuere
   Daten erst, wenn Sie erneut von *Online* auf *Offline* umschalten.

Der Speicher im Programm ist auf etwa 300 000 Messpunkte begrenzt; ältere
Punkte werden dann aus der Anzeige entfernt. Die CSV-Datei enthält immer alle
Daten.

Lineale (Offline)
----------------------------------------------------------------------

.. figure:: images/logger_lineale.png
   :alt: Lineale im Offline-Modus
   :width: 90%
   :align: center

   Zwei Lineale mit Zeit- und Differenzanzeige.

Im Offline-Modus erscheinen in allen Diagrammen zwei senkrechte Lineale:
**L1** (gelb) und **L2** (cyan). Beide lassen sich mit der Maus verschieben
und sind über alle Diagramme hinweg synchron.

Die Wertetabelle zeigt dann:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Spalte
     - Inhalt
   * - Lineal 1
     - Wert jeder Variable am Zeitpunkt von L1.
   * - Lineal 2
     - Wert jeder Variable am Zeitpunkt von L2.
   * - Δ (L2 − L1)
     - Differenz der beiden Werte.

Über der Tabelle werden die Zeitpunkte von L1 und L2 sowie die Zeitdifferenz
**Δt** in Sekunden angezeigt. Verwendet wird jeweils der zeitlich nächste
Messwert (ohne Interpolation).

.. _seiten:

Seiten, Diagramme und Anordnung
----------------------------------------------------------------------

.. figure:: images/anordnung_raster.png
   :alt: Diagramme im Raster
   :width: 90%
   :align: center

   Diagramme einer Seite als Raster (Grid) angeordnet.

Die Diagramme liegen auf **Seiten**. Eine Seite ist ein Dock-Fenster bzw. ein
Tab und kann **mehrere Diagramme** enthalten:

* Ohne Seitenangaben in der Konfiguration liegen alle Diagramme auf einer
  gemeinsamen Seite *Diagramme*. Im Modus *Tabs* erhält dann jedes Diagramm
  einen eigenen Tab.
* Mit dem Feld **Seite (Tab)** in der Konfiguration bestimmen Sie selbst, welche
  Diagramme zusammen auf einer Seite liegen (gleicher Seitenname = gleiche
  Seite). So können Sie z. B. die Tabs *Prozess* und *Alarme* mit je mehreren
  Diagrammen bilden.

**Mindesthöhe und Scrollleiste:** Jedes Diagramm hat eine Mindesthöhe. Passen
nicht alle Diagramme einer Seite ins Fenster, erscheint an der Seite eine
Scrollleiste. Im Modus *Nebeneinander* gilt entsprechend eine Mindestbreite mit
waagerechter Scrollleiste.

**Anordnung der Seiten** (Menü **Ansicht › Anordnung**):

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Modus
     - Wirkung
   * - Untereinander
     - Seiten liegen übereinander; die Diagramme einer Seite stehen
       untereinander.
   * - Nebeneinander
     - Seiten liegen nebeneinander; die Diagramme einer Seite stehen ebenfalls
       nebeneinander.
   * - Tabs
     - Jede Seite ist ein Tab; die Diagramme einer Seite stehen untereinander.

**Anordnung der Diagramme auf einer Seite** (Menü **Ansicht › Diagramme auf der
Seite**): *Automatisch* richtet sich nach der Anordnung der Seiten; *Untereinander*
und *Nebeneinander* erzwingen eine Spalte bzw. eine Zeile; **Raster (Grid)** legt
die Diagramme in Zeilen und Spalten. Die Spaltenzahl stellt **Ansicht › Raster-Spalten**
ein (*Automatisch* wählt etwa die Wurzel der Diagrammzahl, bei sechs Diagrammen
also drei Spalten). Ein letztes einzelnes Diagramm füllt die Restzeile. Die
Voreinstellung steht in der Konfiguration (Reiter *Anzeige*).

Per **Drag & Drop** lässt sich die Anordnung weiter anpassen:

* **Seiten:** An der Titelleiste einer Seite anfassen und an den Rand einer
  anderen Seite ziehen (daneben bzw. darüber) oder auf deren Mitte ziehen (als
  Tab). Ein Doppelklick auf die Titelleiste löst die Seite als frei schwebendes
  Fenster.
* **Diagramme innerhalb einer Seite:** Die Titelzeile eines Diagramms (fett,
  über dem Diagramm) fassen und auf die Titelzeile eines anderen Diagramms
  derselben Seite ziehen. Das Diagramm wird an dieser Position eingefügt.

Seiten lassen sich über **Ansicht › Seiten / Diagramme** aus- und wieder
einblenden. Die per Drag & Drop angepasste Anordnung der Seiten bleibt bei
erneutem Start innerhalb derselben Programmsitzung erhalten, solange die
Seitennamen und der Modus gleich bleiben. Nach einem Programmneustart gilt
wieder die Standard-Anordnung.

Alle Diagramme teilen sich dieselbe Zeitachse.

Legende mit Livewerten
----------------------------------------------------------------------

.. figure:: images/legende.png
   :alt: Legende
   :width: 90%
   :align: center

   Legende mit Livewerten; eine Kurve ist hervorgehoben, eine ausgeblendet.

Die Legende in jedem Diagramm zeigt hinter dem Namen jeder Variable den
**aktuellen Wert** in der Farbe der Variable, z. B. ``Temperatur: 51.234``.
Online ist das der letzte Messwert, offline der Wert am Lineal 1.

**Kurve hervorheben:** Ein **Linksklick** auf den Namen (oder das Muster) einer
Kurve in der Legende hebt sie hervor: Die Kurve wird dicker gezeichnet und liegt
im Vordergrund, der Name erscheint **fett**, alle übrigen Kurven des Diagramms
werden abgeblendet. Ein erneuter Klick auf denselben Namen hebt die Hervorhebung
wieder auf; ein Klick auf einen anderen Namen verschiebt sie.

**Kurve aus- und einblenden:** Rechtsklick auf den Namen einer Kurve in der
Legende öffnet ein Menü mit *Kurve ausblenden* bzw. *Kurve einblenden* sowie
*Alle Kurven dieses Diagramms einblenden*. Ausgeblendete Kurven erscheinen in
der Legende grau mit dem Zusatz *(aus)*. Das Häkchen in der Wertetabelle bleibt
damit synchron. Die Auswahl bleibt beim Wechseln der Anordnung erhalten.

.. _screenshots:

Screenshots von Diagrammen
----------------------------------------------------------------------

.. figure:: images/screenshot_menue.png
   :alt: Screenshot-Menü
   :width: 70%
   :align: center

   Menü „Screenshot“ mit Auswahl des Diagramms und heller Hintergrund.

Einzelne Diagramme lassen sich als Bild speichern:

#. In der Werkzeugleiste auf **Screenshot** klicken (oder im Menü
   **Screenshot**) und das gewünschte Diagramm auswählen.
#. Im Speichern-Dialog Dateinamen und Format wählen: **PNG** (Pixelbild) oder
   **SVG** (Vektorgrafik). Das Format ergibt sich aus der Dateiendung bzw.
   dem gewählten Dateityp.

Der Screenshot enthält das Diagramm genau so, wie es angezeigt wird: Kurven,
alle Y-Achsen, Legende, Balken und im Offline-Modus auch die Lineale.
PNG-Dateien werden mit doppelter Auflösung erzeugt. Die **SVG-Datei** wird aus den
Messdaten selbst gezeichnet (Achsen mit Teilung, Raster, Zeitachse, Kurven, BOOL-Verläufe,
Lineale mit Beschriftung und Legende mit Werten) und lässt sich verlustfrei
skalieren und z. B. in Inkscape oder Office-Programmen weiter bearbeiten. Liegt das Diagramm in einem verdeckten Tab, wird es dafür
automatisch in den Vordergrund geholt.

Für Berichte und Ausdrucke lässt sich im Menü **Screenshot** die Option
**Heller Hintergrund (für Berichte/Druck)** einschalten. Der Screenshot wird
dann mit weißem Hintergrund und dunkler Schrift gespeichert; Lineale werden
dafür in dunkleren Farben gezeichnet. Die Bildschirmanzeige selbst bleibt
unverändert. Die Einstellung gilt für die laufende Programmsitzung.

Wertetabelle (Werteanzeige)
----------------------------------------------------------------------

.. figure:: images/wertetabelle.png
   :alt: Wertetabelle
   :width: 90%
   :align: center

   Wertetabelle mit Aktualwerten (online) bzw. Linealwerten (offline).

Die Tabelle am rechten Rand listet alle Variablen, bei denen in der
Konfiguration *Werteanzeige* aktiviert ist.

* Der Name wird in der Variablenfarbe dargestellt. Ein Mauszeiger über dem
  Namen zeigt den Tag-Namen.
* Mit dem **Häkchen** vor dem Namen blenden Sie die Kurve der Variable im
  Diagramm aus oder ein (alternativ per Rechtsklick in der Legende).
* Die Spalten wechseln je nach Modus (*Aktuell* online, *Lineal 1 / Lineal 2 /
  Δ* offline).

Y-Achsen und Skalierung
----------------------------------------------------------------------

* Jede Y-Achse ist in der Farbe ihrer ersten Variable beschriftet.
* Achsen mit **Auto-Skalierung** passen sich an die im Zeitfenster sichtbaren
  Daten an. Achsen mit festen Grenzen behalten ihren Bereich.
* Der Schalter **Y-Auto** in der Werkzeugleiste überschreibt vorübergehend alle
  festen Bereiche. Wird er wieder ausgeschaltet, gelten die Einstellungen der
  Konfiguration.

Balken für Aktualwerte
----------------------------------------------------------------------

Neben jedem Diagramm zeigt je Variable ein schmaler Balken den aktuellen
Wert. Die Skalierung entspricht der Y-Achse der Variable. Im Offline-Modus
zeigen die Balken die Werte am Lineal 1. Fahren Sie mit der Maus über die
Balken, um Namen und Werte als Tooltip zu sehen.

BOOL-Variablen
----------------------------------------------------------------------

.. figure:: images/bool_signale.png
   :alt: BOOL-Signale
   :width: 90%
   :align: center

   BOOL-Signale: Linie bei 0, nach oben gehender Streifen bei 1, neben den Legendenzeilen.

Boolesche Variablen werden unabhängig von den Y-Achsen dargestellt:

* **In der Legende** stehen Name und Wert wie bei den analogen Kurven untereinander.
  Neben jedem BOOL-Eintrag, in der Höhe seiner Legendenzeile, läuft über die
  **Breite des Diagramms** wie bei einem digitalen Signal eine **Linie** auf der
  Grundlinie (Wert 0) bzw. ein **nach oben gehender Streifen** (Wert 1) in der
  Variablenfarbe. Wie eine Kurve deckt sie den dargestellten Zeitbereich ab
  (online die letzten *N* Sekunden, offline den sichtbaren Ausschnitt). So lassen
  sich mehrere BOOL-Variablen auf einen Blick vergleichen, ohne das Diagramm zu
  verdecken.
* **Als Kurve** werden BOOLs standardmäßig nicht gezeichnet (sie hängen sonst
  an einer Y-Achse). Mit **Bool im Diagramm** in der Werkzeugleiste erscheinen
  sie zusätzlich als transparent gefüllte Treppenlinie.
* **In der Wertetabelle** ist die Zelle bei Wert 1 in der Variablenfarbe
  **gefüllt**, bei Wert 0 leer.

Ausgeblendete BOOLs (Rechtsklick in der Legende) und hervorgehobene BOOLs
(Linksklick) werden abgeblendet bzw. mit dickerem Streifen gezeichnet. Der SVG-Export und der
Webserver (dort steht der Name in der Zeile des Streifens) zeigen die BOOL-Signale ebenso.


.. _demo-modus:

Demo-Modus
======================================================================

Der Demo-Modus erzeugt simulierte Werte, ohne dass eine SPS verbunden sein
muss:

#. In der Werkzeugleiste **Demo** aktivieren.
#. **▶ Start** drücken.

Die Variablen aus Ihrer Konfiguration werden dabei mit Testsignalen versorgt
(REAL: Sinus mit Rauschen, BOOL: Rechteck, Ganzzahlen: Sägezahn). Ist noch
nichts konfiguriert, legt der Demo-Modus zwei Beispiel-Diagramme mit mehreren
Y-Achsen und einem BOOL-Signal an. Der Schalter ist während der Aufzeichnung
gesperrt und wird nicht gespeichert. Die Demo-Daten werden als
``demo_JJJJMMTT_HHMMSS.csv`` abgelegt.


.. _webserver:

Webserver (Diagramme im Browser)
======================================================================

.. figure:: images/web_tablet.png
   :alt: Webseite auf dem Tablet
   :width: 90%
   :align: center

   Die Diagramme im Browser eines Tablets.

Mit der Option **Webserver starten** (Reiter *Webserver & Headless*) stellt der
Logger die Diagramme als Webseite bereit. Sie lässt sich mit jedem Browser im
Netzwerk öffnen, z. B. mit einem Tablet oder Smartphone – auch im Headless-Betrieb.

* **Adresse:** ``http://<IP-Adresse des Rechners>:<Port>/`` (Standard-Port 8080).
  Die Adresse zeigt im Logger **Datei › Webserver-Adresse …**; beim Start steht sie
  außerdem im Log. Gegebenenfalls muss die Firewall den Port freigeben.
* **Zugriffscode:** Ist im Reiter ein Code eingetragen, wird die Seite mit
  ``http://…:8080/?token=CODE`` aufgerufen. Ohne Code kann jeder im Netzwerk
  zusehen; die Seite ist nur lesend, es gibt keine Steuerfunktion. Für Zugriffe
  aus dem Internet gehört der Server hinter einen Reverse-Proxy mit HTTPS.
* **Darstellung:** Die Seite zeigt je Seite (Tab) die Diagramme mit Chart.js, mit
  mehreren Y-Achsen, BOOL-Signalen als Treppenlinie und Status-LEDs der
  Steuerungen. Die Anzeige passt sich der Bildschirmgröße an.
* **Bedienung:** *Live* zeigt das letzte Zeitfenster; mit **◀ ▶** blättert man in
  der Zeit zurück (Verlauf), **Pause** hält die Anzeige an. Antippen eines
  Legendeneintrags hebt eine Kurve hervor, langes Drücken oder Doppelklick blendet
  sie aus.
* **Chart.js:** Die Bibliothek wird aus ``web_static/chart.umd.js`` ausgeliefert
  (die Installationsdatei enthält sie). Fehlt die Datei, lädt der Browser sie ersatzweise
  aus dem Internet (jsdelivr); im geschlossenen Netzwerk daher die Datei
  ``chart.umd.js`` (Chart.js 4) manuell in den Ordner ``web_static`` legen.

Der Server überträgt nur die sichtbaren Daten, auf die Bildschirmbreite reduziert
(Minimum und Maximum je Abschnitt bleiben erhalten), und komprimiert sie.

.. _headless:

Headless-Betrieb (nur Aufzeichnung)
======================================================================

Ohne Oberfläche zeichnet der Logger nur auf: Lesen aus den Steuerungen, Formeln,
CSV-Datei, Archivierung und – falls aktiviert – Webserver. Das spart Ressourcen und
eignet sich für Dauerbetrieb, z. B. als Autostart-Programm auf einem Industrie-PC.

* **Einschalten:** Option *Headless-Modus* im Reiter *Webserver & Headless* der
  Konfiguration, oder Startparameter ``--headless``. Mit ``--gui`` lässt sich trotz
  eingestelltem Headless-Modus die Oberfläche öffnen.
* **Meldungen** (Verbindung, Fehler, Archivierung) stehen in der Logdatei
  ``tia_logger.log`` im Programm- bzw. Datenordner (rotierend, mehrere Dateien).
* **Beenden:** Mit ``Strg+C`` im Konsolenfenster bzw. durch das Signal SIGTERM
  (Dienst beenden, Windows: Fenster schließen) wird sauber beendet: Die
  CSV-Datei wird geschlossen und – bei gesetzter Option – archiviert.
* Die installierte Version enthält im Startmenü die Verknüpfung
  *TIA Datenlogger (Headless, nur Aufzeichnung)*.



.. _datenbank:

Datenbank (SQLite, MariaDB, TimescaleDB)
======================================================================

Die Messwerte lassen sich **zusätzlich oder statt** der CSV-Datei in eine Datenbank
schreiben – etwa zur Auswertung mit SQL oder zur Anzeige in Grafana. Die Einstellungen
stehen im Konfigurationsprogramm im Reiter **Datenbank**; die CSV-Datei schaltet der
Haken **CSV-Datei schreiben** im Reiter *Aufzeichnung* ein oder aus.

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Feld
     - Bedeutung
   * - Datenbank
     - *Keine*, *SQLite (Datei)*, *MariaDB / MySQL* oder *TimescaleDB / PostgreSQL*.
   * - Server / Port
     - Rechnername oder IP-Adresse des Datenbankservers; Port *Standard* = 3306
       (MariaDB) bzw. 5432 (PostgreSQL/TimescaleDB).
   * - Datenbankname
     - Name der Datenbank auf dem Server. Sie muss bereits existieren; die Tabelle
       legt das Programm selbst an.
   * - Benutzer / Passwort
     - Zugangsdaten. Der Benutzer braucht die Rechte CREATE (beim ersten Start) und
       INSERT. Das Passwort steht im Klartext in der Konfigurationsdatei.
   * - SQLite-Datei
     - Dateiname der SQLite-Datenbank; ein relativer Pfad gilt im Datenordner des
       Programms.
   * - Tabelle
     - Name der Tabelle (Standard ``messwerte``; Buchstaben, Ziffern, ``_``).
   * - Nur Änderungen schreiben
     - Ein Wert wird nur geschrieben, wenn er sich geändert hat, spätestens aber
       jede Minute. Spart bei langsam veränderlichen Werten viel Platz.
   * - Datenbank testen
     - Verbindet sich, legt die Tabelle an und meldet das Ergebnis.

**Tabellenaufbau** (eine Zeile je Wert, „schmales“ Format):

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Spalte
     - Typ
     - Inhalt
   * - ``zeit``
     - SQLite: Text, MariaDB: ``DATETIME(3)``, PostgreSQL: ``TIMESTAMPTZ``
     - Zeitpunkt der Messung in **UTC** mit Millisekunden
   * - ``projekt``
     - Text
     - Projektname aus der Konfiguration (mehrere Logger können eine Tabelle teilen)
   * - ``variable``
     - Text
     - Name der Variable
   * - ``wert``
     - Gleitkommazahl
     - Messwert (BOOL als 0/1)

Ungültige Werte (z. B. während eines Verbindungsausfalls) werden nicht geschrieben.
Ein Index über ``variable, zeit`` beschleunigt Abfragen einzelner Variablen. Bei
**TimescaleDB** wird die Tabelle automatisch zur *Hypertable* (zeitlich partitioniert);
ist die Erweiterung nicht installiert, entsteht eine normale PostgreSQL-Tabelle und die
Statuszeile meldet das.

Beispielabfragen:

.. code-block:: sql

   -- Verlauf einer Variable der letzten Stunde (PostgreSQL/TimescaleDB)
   SELECT zeit, wert FROM messwerte
    WHERE variable = 'Temperatur' AND zeit > now() - interval '1 hour' ORDER BY zeit;

   -- Minutenmittel (TimescaleDB)
   SELECT time_bucket('1 minute', zeit) AS minute, avg(wert)
     FROM messwerte WHERE variable = 'Temperatur' GROUP BY minute ORDER BY minute;

   -- Letzte Werte aller Variablen (MariaDB / SQLite)
   SELECT variable, MAX(zeit) FROM messwerte GROUP BY variable;

**Betrieb:**

* Geschrieben wird in einem eigenen Thread etwa einmal pro Sekunde in Stapeln; die
  Anzeige und das Lesen aus der Steuerung werden dadurch nicht gebremst.
* In der Statusleiste (und im Webserver) zeigt eine eigene **LED „Datenbank“** den
  Zustand; der Tooltip nennt die Zahl der geschriebenen Werte.
* Ist die Datenbank nicht erreichbar, bleiben die Werte im Speicher (bis etwa
  2 Millionen Werte) und werden nach dem erneuten Verbinden nachgetragen. Beim
  Beenden noch nicht geschriebene Werte meldet die Statuszeile.
* **Treiber:** SQLite ist in Python enthalten. MariaDB braucht ``PyMySQL``,
  TimescaleDB/PostgreSQL ``psycopg`` (``pip install PyMySQL "psycopg[binary]"``); in
  der Installationsdatei sind beide enthalten.
* Für Grafana: Datenquelle *MySQL* bzw. *PostgreSQL* anlegen; die Zeitspalte ist
  ``zeit`` (UTC). SQLite-Dateien lassen sich mit dem SQLite-Plugin von Grafana lesen.


.. _db-lesen:

Lesemodus: Aufzeichnungen aus der Datenbank anzeigen
----------------------------------------------------------------------

Im Logger lädt **Datei › Aus Datenbank laden …** (``Strg+D``) einen frei wählbaren
Zeitraum aus der Datenbank und zeigt ihn im **Offline-Modus** an – mit Linealen,
Wertetabelle, Screenshots und PID-Optimierung wie bei einer geladenen CSV-Datei.
Gelesen wird aus der Datenbank der geladenen Konfiguration; die Datenbank wird nur
gelesen, eine laufende Aufzeichnung (auch eines anderen Loggers) kann dabei
weiterschreiben.

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Bereich
     - Bedeutung
   * - Datenbank
     - Zeigt die Quelle. **SQLite-Datei wählen …** liest stattdessen eine beliebige
       SQLite-Datei (z. B. eine Kopie von einem anderen Rechner);
       **Datenbank der Konfiguration** kehrt zurück.
   * - Projekt
     - Projektname, unter dem die Werte gespeichert wurden (Vorgabe: Projekt der
       Konfiguration). *(alle Projekte)* fasst gleichnamige Variablen aller
       Projekte zusammen.
   * - Variablen
     - Alle Variablen in der Datenbank mit erstem und letztem Zeitpunkt und Anzahl
       der Werte. Angehakt sind zunächst die Variablen der aktuellen Konfiguration.
       **Alle**, **Keine**, **Wie Konfiguration** und das Filterfeld helfen bei
       vielen Variablen.
   * - Zeitraum
     - **Von** / **Bis** (Ortszeit) mit Kalender, oder per Knopf: *Letzte Stunde*,
       *Letzte 24 h*, *Letzte 7 Tage*, *Letzte 30 Tage* (jeweils bis zum letzten
       gespeicherten Wert der gewählten Variablen), *Heute*, *Gestern*, *Alles*.
   * - Auflösung
     - *Automatisch*: Rohdaten, solange es höchstens 20 000 Punkte je Variable sind,
       sonst Mittelwerte in einem passenden Raster (1 s, 2 s, 5 s … 1 Tag).
       *Rohdaten*: jeder gespeicherte Wert. *Mittelwert je 1 s … je Tag*: feste
       Raster. Die Mittelwerte berechnet die Datenbank selbst – auch Monate an Daten
       lassen sich so schnell überblicken.
   * - Fehlende Werte mit dem letzten Wert füllen
     - Für Aufzeichnungen mit **Nur Änderungen schreiben** (dort voreingestellt):
       Ein fehlender Wert bedeutet „unverändert“, die Kurve läuft durchgehend.
       Ohne Haken erscheinen Lücken.
   * - Werte zählen
     - Ermittelt die genaue Zahl der Werte im Zeitraum (darüber steht eine
       Schätzung aus der Variablenliste).

**Laden und anzeigen** liest die Werte im Hintergrund; der Fortschritt steht unten im
Fenster, **Abbrechen** beendet das Lesen. Danach wechselt der Logger in den
Offline-Modus. Farben, Diagramme und Achsen kommen aus der Konfiguration;
Variablen, die dort fehlen, erscheinen im ersten Diagramm. Die Statuszeile nennt
Quelle, Zeitraum und Auflösung. Eine laufende Aufzeichnung wird beim Laden beendet
(wie beim Laden einer CSV-Datei); mit **▶ Start** beginnt eine neue.

Hinweise:

* Zeitstempel stehen in der Datenbank in UTC; angezeigt wird in Ortszeit.
* Beim Mittelwert liegt der Zeitstempel in der Mitte des Rasters (z. B. 10:00:30
  für 10:00:00 bis 10:00:59). Minimum und Maximum innerhalb eines Rasters sind
  nicht zu sehen – für kurze Spitzen Rohdaten oder ein feineres Raster wählen.
* Zum Schutz des Speichers liest der Logger höchstens 20 Millionen Werte auf einmal;
  darüber erscheint ein Hinweis, einen kürzeren Zeitraum oder Mittelwerte zu wählen.
* Bei MariaDB und PostgreSQL braucht der Benutzer nur das Recht SELECT.


.. _ereignisse:

Trigger und Ereignisprotokoll
======================================================================

Ein **Trigger** überwacht eine Bedingung über die Variablen, z. B.
``{Temperatur} > 80``. Sobald sie erfüllt ist, schreibt der Logger einen Eintrag
mit Zeitstempel in das **Ereignisprotokoll** (eine Textdatei). Die Zahl der noch
nicht quittierten Ereignisse steht in der Statusleiste des Loggers; quittiert wird
im **Ereignis-Viewer**.

Trigger anlegen
----------------------------------------------------------------------

Konfigurationsprogramm, Reiter **Trigger & Ereignisse** → **Trigger bearbeiten …**.

.. figure:: images/trigger_editor.png
   :alt: Trigger-Editor
   :width: 90%
   :align: center

   Der Trigger-Editor: eine Zeile je Trigger, fehlerhafte Zeilen sind rot markiert.

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Spalte
     - Bedeutung
   * - Aktiv
     - Nur aktive Trigger werden ausgewertet. Ausgeschaltete Trigger dürfen auch
       fehlerhaft sein (z. B. nach dem Umbenennen einer Variable).
   * - Name
     - Name des Triggers (eindeutig, ohne ``;``); steht im Ereignisprotokoll.
   * - Bedingung
     - Ausdruck wie bei den :ref:`berechneten Variablen <berechnete-variablen>`.
       Ergebnis ungleich 0 = erfüllt. Beispiele: ``{Temperatur} > 80``,
       ``{Druck} < 2 and {Pumpe} == 1``, ``abs(ddt({Füllstand})) > 5``,
       ``{Störung} == 1``. Variablen ohne Wert (keine Verbindung) gelten als
       *nicht erfüllt*. **Bedingung bearbeiten …** (oder Doppelklick) öffnet den
       Formeleditor mit Variablenliste und Testwerten.
   * - Meldetext
     - Text des Eintrags. ``{Name}`` wird durch den Wert der Variable zum Zeitpunkt
       des Ereignisses ersetzt, z. B. ``Temperatur zu hoch: {Temperatur} °C``.
       Leer = die Bedingung selbst.
   * - Priorität
     - *Info*, *Warnung* oder *Alarm* (Farbe im Viewer, Filter).
   * - Verzögerung
     - So viele Sekunden muss die Bedingung **ununterbrochen** erfüllt sein, bevor das
       Ereignis kommt (unterdrückt kurze Spitzen). 0 = sofort.
   * - Gehen
     - Auch das Ende des Ereignisses (Bedingung wieder falsch) eintragen.
   * - Quittieren
     - Das Ereignis muss quittiert werden und zählt bis dahin in der Statusleiste.
       Ohne Haken wird es nur protokolliert.

Ein Trigger löst **einmal je Flanke** aus: Erst wenn die Bedingung wieder falsch und
dann erneut wahr wird, entsteht ein neues Ereignis. Die Trigger werden mit jedem
Messzyklus geprüft – also auch im Headless-Betrieb – und gelten ab dem nächsten Start
der Aufzeichnung. Im Demo-Modus ohne eigene Trigger gibt es zwei Beispiel-Trigger
(*Übertemperatur*, *Druck niedrig*).

Ereignisdatei
----------------------------------------------------------------------

Feld **Ereignisdatei** im selben Reiter; leer = ``<CSV-Ordner>/<CSV-Name>_ereignisse.csv``.
Die Datei wird nur fortgeschrieben (nie geändert oder archiviert) und lässt sich mit
Excel öffnen (Semikolon, UTF-8):

.. code-block:: text

   ID;Zeit;Art;Trigger;Priorität;Text;Benutzer
   17;2026-10-15 16:20:01.250;KOMMT;Übertemperatur;Alarm;Temperatur zu hoch: 81.37 °C;
   17;2026-10-15 16:22:40.100;GEHT;Übertemperatur;Alarm;;
   17;2026-10-15 16:25:12.000;QUITTIERT;Übertemperatur;Alarm;;mmuster

*Art* ist ``KOMMT``, ``GEHT`` oder ``QUITTIERT``; Zeilen mit derselben *ID* gehören
zum selben Ereignis. Bei ``QUITTIERT`` steht in *Benutzer* der Windows-Benutzername.
``-`` in der Spalte *Benutzer* einer ``KOMMT``-Zeile bedeutet „keine Quittierung nötig“.

Anzeige in der Statusleiste
----------------------------------------------------------------------

.. figure:: images/ereignis_statusleiste.png
   :alt: Ereigniszähler in der Statusleiste
   :align: center

   Rot hinterlegt: drei Ereignisse sind noch nicht quittiert.

Rechts in der Statusleiste zeigt der Knopf **🔔** die Zahl der offenen (nicht
quittierten) Ereignisse; bei offenen Ereignissen ist er rot. Ein Klick darauf – oder
**Datei → Ereignisprotokoll …** (Strg+E) – öffnet den Viewer. Jedes neue Ereignis
erscheint außerdem als Meldung in der Statusleiste (``⚠ Alarm: …``). Der Zähler gilt
auch ohne laufende Aufzeichnung, z. B. wenn ein Headless-Logger auf demselben Rechner
in die Datei schreibt. Im Webserver steht oben „🔔 n offen“ (Tooltip: die offenen
Ereignisse); quittiert wird nur im Viewer.

Ereignis-Viewer und Quittieren
----------------------------------------------------------------------

.. figure:: images/ereignis_viewer.png
   :alt: Ereignis-Viewer
   :width: 90%
   :align: center

   Der Ereignis-Viewer: offene Ereignisse farbig nach Priorität, erledigte grau.

* Die Tabelle zeigt die neuesten Ereignisse oben: Nummer, Kommt, Geht, Priorität,
  Trigger, Meldung und Quittierung (Zeit und Benutzer bzw. **offen**).
* Filter: **nur offene**, Priorität, Suchfeld (Trigger oder Meldung).
* **Markierte quittieren** (oder Doppelklick auf eine Zeile) quittiert die
  ausgewählten Ereignisse, **Alle quittieren** alle offenen.
* Die Anzeige aktualisiert sich selbst, sobald neue Ereignisse kommen (F5 = sofort).
* **Ordner öffnen** zeigt die Ereignisdatei im Explorer.

Der Viewer lässt sich auch **allein** starten – etwa neben einem Headless-Logger oder an
einem anderen Rechner mit Zugriff auf die Datei (Netzlaufwerk):

.. code-block:: text

   TIALogger.exe --ereignisse                        (Ereignisprotokoll der zuletzt benutzten Konfiguration)
   TIALogger.exe --ereignisse anlage.json             (Ereignisprotokoll dieser Konfiguration)
   TIALogger.exe --ereignisse D:\logs\log_ereignisse.csv

Die installierte Version hat dafür im Startmenü die Verknüpfung *TIA Ereignisprotokoll*.
Im Konfigurationsprogramm öffnet **Ereignisprotokoll anzeigen …** denselben Viewer.


.. _notizen:

Notizen (eigene Einträge)
----------------------------------------------------------------------

Neben den Triggern lassen sich **Notizen von Hand** ins Ereignisprotokoll schreiben,
z. B. „Ventil V12 getauscht“ oder „Sollwert auf 65 °C geändert“ – so steht später in
derselben Datei, warum sich ein Verlauf geändert hat.

* Im Logger: **Datei → Notiz ins Ereignisprotokoll …** (Strg+M). Im Offline-Modus ist
  die Zeit von **Lineal 1** vorgegeben – so lässt sich eine Stelle im Verlauf nachträglich
  kommentieren.
* Im Ereignis-Viewer: **Notiz hinzufügen …**.

.. figure:: images/notiz.png
   :alt: Notiz eintragen
   :align: center

   Zeit, Text und Verfasser einer Notiz.

Zeit (Standard: jetzt), Text (auch mehrzeilig) und Verfasser (Standard: Windows- bzw.
Linux-Benutzername) sind frei wählbar. Notizen stehen als Art ``NOTIZ`` in der Datei,
erscheinen im Viewer grün hinterlegt mit 📝 und müssen nicht quittiert werden. Der Filter
**nur Notizen** zeigt nur sie.

.. code-block:: text

   18;2026-10-16 09:12:00.000;NOTIZ;Notiz;Notiz;Ventil V12 getauscht;mmuster


.. _pid-optimierung:

PID-Regler-Optimierung
======================================================================

Zeigt ein Diagramm einen Regelkreis – **Sollwert**, **Istwert** und **Stellwert** –,
berechnet der Logger aus den aufgezeichneten Daten passende Reglerparameter
(Kp, Ti, Td). Dazu bestimmt er zuerst ein Modell der Regelstrecke und wendet darauf
bewährte Einstellregeln an.

Einschalten (Konfigurationsprogramm)
----------------------------------------------------------------------

Im Zuordnungsbaum das Diagramm auswählen und unter *Eigenschaften der Auswahl* den
Haken **PID-Regler-Optimierung** setzen. Im Fenster **Einstellen …** werden festgelegt:

.. figure:: images/pid_einstellen.png
   :alt: PID-Optimierung einstellen
   :align: center

   Soll-, Ist- und Stellwert des Diagramms zuordnen.

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Feld
     - Bedeutung
   * - Sollwert
     - Variable mit dem Sollwert (optional, nur zur Anzeige).
   * - Istwert
     - Regelgröße (Messwert), z. B. Temperatur.
   * - Stellwert
     - Reglerausgang, z. B. Ventilstellung oder Heizleistung in %.
   * - Reglertyp
     - *PI* (meist ausreichend, unempfindlich gegen Messrauschen) oder *PID*.
   * - Regelverhalten
     - *schnell* (aggressiv, kleine Reserve), *normal* oder *robust* (langsam, sicher
       auch bei schwankender Strecke).

Die Zuordnung wird anhand üblicher Namen (Soll/SP, Ist/PV, Stell/CV/Out …) vorgeschlagen.

Daten aufzeichnen
----------------------------------------------------------------------

Die Berechnung braucht einen Zeitbereich, in dem sich der **Stellwert deutlich
ändert** und der Istwert darauf reagiert:

* **Stellwertsprung im Handbetrieb** (am besten): Regler auf Hand, Prozess zur Ruhe
  kommen lassen, Stellwert um 5 … 20 % springen lassen und warten, bis der Istwert
  wieder ruhig ist.
* **Sollwertsprung im Automatikbetrieb**: geht ebenso, solange der Regler nicht zu
  träge ist und der Stellwert nicht dauerhaft an der Grenze (0 / 100 %) steht.

Der Bereich sollte mit ruhigem Prozess beginnen und keine großen Störungen enthalten.

Berechnen (Logger)
----------------------------------------------------------------------

Menü **Analyse → PID-Optimierung: <Diagramm> …** oder Rechtsklick in das Diagramm →
**PID-Regler optimieren …**.

.. figure:: images/pid_optimierung.png
   :alt: Fenster PID-Regler-Optimierung
   :width: 95%
   :align: center

   Links Modell und Parameter, rechts Messung/Modell, Stellwert und simulierter Sollwertsprung.

1. **Zeitbereich** wählen: *Zwischen Lineal 1 und 2* (Offline-Modus, Lineale vorher um
   den Sprung legen), *Sichtbarer Bereich* oder *Alle Daten*.
2. **Strecke bestimmen und berechnen** klicken. Oben steht das Streckenmodell:

   * *PT1 mit Totzeit* – Verstärkung K, Zeitkonstante T, Totzeit θ (Temperatur, Druck,
     Durchfluss, Drehzahl …);
   * *I-Strecke mit Totzeit* – Integrierbeiwert Ki (z. B. Füllstand).

   Die **Übereinstimmung** gibt an, wie gut das Modell die Messung trifft (100 % =
   perfekt). Unter etwa 50 % sind die Parameter unsicher; Hinweise darunter nennen
   mögliche Ursachen. Im Diagramm rechts liegt die Modellkurve (orange) über dem
   gemessenen Istwert (grau).
3. Die **Tabelle** zeigt die Parameter nach mehreren Einstellregeln; die erste
   (fett) ist die empfohlene:

   .. list-table::
      :header-rows: 1
      :widths: 28 72

      * - Regel
        - Eigenschaften
      * - SIMC (Skogestad)
        - Empfehlung: gute Führung und Störunterdrückung, geringes Überschwingen.
      * - IMC / Lambda
        - Ruhig, praktisch ohne Überschwingen; schont Stellglieder.
      * - AMIGO
        - Robust (Åström/Hägglund), gute Störunterdrückung.
      * - CHR (aperiodisch)
        - Chien-Hrones-Reswick, Führungsverhalten ohne Überschwingen.
      * - Ziegler-Nichols
        - Klassisch, schnell, aber schwach gedämpft – nur zum Vergleich.

   Spalten: **Kp** (Verstärkung), **Ti** und **Td** in Sekunden (Standardform
   ``u = Kp·(e + 1/Ti·∫e dt + Td·de/dt)``), dazu die Parallelform **Ki** = Kp/Ti und
   **Kd** = Kp·Td sowie **Überschwingen** und **Ausregelzeit** (2-%-Band) aus der
   Simulation.
4. Unten rechts ist der **simulierte Sollwertsprung** mit der markierten Regel zu sehen
   (rot; grau die übrigen). Reglertyp und Regelverhalten lassen sich im Fenster
   umschalten – die Tabelle wird sofort neu berechnet.
5. **Ergebnis kopieren** legt Modell und alle Parameter als Text in die Zwischenablage.

Hinweise
----------------------------------------------------------------------

* Kp gilt in den aufgezeichneten Einheiten (Stellwert-Einheit je Istwert-Einheit, z. B.
  %/°C). Rechnet der Regler in der Steuerung mit normierten Werten, umrechnen:
  ``Kp_norm = Kp · Istwert-Spanne / Stellwert-Spanne``.
* Ein **negatives Kp** bedeutet: Der Istwert sinkt bei steigendem Stellwert (z. B.
  Kühlung). In der Steuerung den Wirksinn umkehren und den Betrag eintragen.
* Die Simulation berücksichtigt keine Stellwertbegrenzung. Neue Parameter vorsichtig
  einführen und den Regelkreis beobachten.
* Im **Demo-Modus** enthält die Beispielkonfiguration das Diagramm *Regelkreis* mit
  einem simulierten, absichtlich träge eingestellten Regler (Sollwert wechselt jede
  Minute) – nach einigen Minuten Aufzeichnung lässt sich die Optimierung ausprobieren.
* **Übernahme in die Steuerung:** *PID_Compact*/*PID_3Step*: ``Retain.CtrlParams.Gain`` = Kp, ``.Ti`` = Ti [s], ``.Td`` = Td [s] (PI: Td = 0), ``TdFiltRatio`` z. B. 0.2; bei negativem Kp „Regelsinn invertieren“.


.. _sprache:

Sprache umschalten und übersetzen
======================================================================

Die Oberfläche ist auf Deutsch geschrieben und lässt sich über **Sprachdateien** in
andere Sprachen übersetzen. Mitgeliefert werden **Deutsch** und **Englisch**.

Umschalten
----------------------------------------------------------------------

Menü **Sprache** (im Logger und im Konfigurationsprogramm): Sprache wählen und die Frage
nach dem Neustart bestätigen. Die Wahl gilt für beide Programme und den Ereignis-Viewer
und wird in der Datei ``tia_einstellungen.json`` im Datenordner gespeichert. Auch die
Standardtexte von Qt (Ja/Nein/Abbrechen, Dateidialoge) folgen der gewählten Sprache.

Nicht übersetzt werden Daten: Namen von Variablen, Diagrammen und Triggern, die Spalten
der CSV-Dateien und des Ereignisprotokolls (``KOMMT``, ``GEHT`` …), die Webseite des
Webservers sowie die Logdatei des Headless-Betriebs (teilweise).

Eigene Übersetzung erstellen
----------------------------------------------------------------------

1. Menü **Sprache → Ordner mit Sprachdateien öffnen …**. Der Ordner ``sprachen`` im
   Datenordner öffnet sich; die Vorlage ``de.txt`` wird dabei hineinkopiert.
2. ``de.txt`` kopieren und nach dem **Sprachkürzel** benennen, z. B. ``fr.txt``
   (Französisch), ``it.txt``, ``es.txt``, ``nl.txt``, ``pl.txt``, ``cs.txt``.
3. Die Datei mit einem Texteditor öffnen (UTF-8), oben hinter ``# Sprache:`` den Namen
   eintragen (z. B. ``Français``) und hinter jedem ``>`` die Übersetzung schreiben:

   .. code-block:: text

      # Sprache: Français

      @ Konfiguration laden
      > Charger la configuration

      @ {0} offene Ereignisse quittieren?
      > Acquitter {0} événements ouverts ?

4. Speichern – die Sprache erscheint sofort im Menü **Sprache** (nach Neustart aktiv).

Regeln:

* ``@`` = deutscher Originaltext (nicht ändern), ``>`` = Übersetzung. Leer gelassene
  Übersetzungen zeigen den deutschen Text – man kann also schrittweise übersetzen.
* ``\n`` steht für einen Zeilenumbruch.
* **Platzhalter** wie ``{0}``, ``{1}`` oder ``{2:.1f}`` müssen erhalten bleiben (die
  Reihenfolge im Satz ist frei). Fehlt einer, wird für diesen Text das Original verwendet.
* ``&`` vor einem Buchstaben markiert das Tastenkürzel im Menü (Alt + Buchstabe); ``&&``
  ergibt ein einzelnes ``&``.
* HTML-Auszeichnungen wie ``<b>…</b>`` oder ``<code>…</code>`` unverändert lassen.
* Die englische Datei ``en.txt`` kann als Beispiel dienen.

Gesucht wird zuerst im Ordner ``sprachen`` des Datenordners (eigene Dateien, bleiben bei
Updates erhalten), dann im Programmordner (mitgelieferte Dateien). Eine eigene ``en.txt``
im Datenordner ersetzt also die mitgelieferte.

Für Entwickler: Texte im Programm stehen als ``tr("…")`` bzw. ``tr("… {0} …").format(wert)``
(Modul ``tia_i18n.py``). Nach Programmänderungen bringt
``python tools/extract_tr.py tia .`` alle Sprachdateien auf den neuesten Stand (neue
Texte mit leerer Übersetzung, vorhandene Übersetzungen bleiben).


CSV-Dateien
======================================================================

Dateiname und Ort
----------------------------------------------------------------------

Für jede Aufzeichnung wird eine neue Datei im CSV-Ordner angelegt:
``<CSV-Name>_JJJJMMTT_HHMMSS.csv``, z. B. ``log_20261012_080000.csv``
(im Demo-Modus ``demo_...``).

.. _csv-archiv:

Dateigröße begrenzen und archivieren
----------------------------------------------------------------------

In der Konfiguration lässt sich die Anzahl der Datensätze je CSV-Datei
begrenzen (*Max. Datensätze je Datei*, ``0`` = unbegrenzt). Wird die Zahl
erreicht, geschieht automatisch Folgendes:

#. Die Datei wird geschlossen und als ZIP gepackt.
#. Das ZIP wird in der folgenden Verzeichnisstruktur abgelegt:

   .. code-block:: text

      <Archiv-Ordner>/<CSV-Name>/<Jahr>/<Monat>/<Tag>/<Dateiname>.zip

   Beispiel: ``archiv/log/2026/10/12/log_20261012_080000.zip``
#. Die ursprüngliche CSV-Datei wird erst gelöscht, nachdem das Archiv
   erfolgreich geprüft wurde.
#. Die Aufzeichnung läuft ohne Unterbrechung in einer neuen CSV-Datei weiter.

Hinweise:

* Für **Jahr, Monat und Tag** gilt das Datum des *ersten Datensatzes* der
  Datei. Der Ordnername ``<CSV-Name>`` ist der in der Konfiguration
  eingestellte Name (im Demo-Modus ``demo``).
* Das Packen läuft im Hintergrund und bremst die Aufzeichnung nicht. Das
  Ergebnis erscheint in der Statuszeile. Schlägt die Archivierung fehl,
  bleibt die CSV-Datei im CSV-Ordner erhalten.
* Wird die Aufzeichnung mit **■ Stop** beendet, bleibt die aktuelle Datei
  ungepackt im CSV-Ordner liegen. Nur volle Dateien werden archiviert.
* Archivierte Dateien lassen sich mit **CSV laden** direkt als ZIP öffnen.
* Die Anzeige im Logger arbeitet unabhängig von den Dateien weiter; beim
  Laden einer Datei wird nur deren Inhalt angezeigt.

Faustformel für die Dateigröße: Datensätze je Datei = Dauer ÷ Abtastintervall.
Bei 200 ms Intervall entstehen 5 Datensätze pro Sekunde, also 432 000 pro Tag;
ein Limit von 100 000 Datensätzen entspricht dann rund 5,5 Stunden je Datei.

Format
----------------------------------------------------------------------

* Trennzeichen: Semikolon (``;``), Dezimaltrennzeichen: Punkt
* Zeichensatz: UTF-8
* Erste Zeile: Spaltenüberschriften

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Spalte
     - Inhalt
   * - ``Zeit``
     - Zeitstempel mit Millisekunden, z. B. ``2026-10-11 10:59:30.927``
   * - ``Epoch``
     - Unix-Zeit in Sekunden mit drei Nachkommastellen (Millisekunden),
       z. B. ``1791716370.927``
   * - Variablen
     - Eine Spalte je Variable, benannt nach dem Variablennamen. Ein leeres
       Feld bedeutet: kein gültiger Wert.

Beispiel:

.. code-block:: text

   Zeit;Epoch;Temperatur;Pumpe
   2026-10-11 10:59:30.927;1791716370.927;51.234;1
   2026-10-11 10:59:31.127;1791716371.127;51.301;1

.. note::

   Wird die Datei in Excel geöffnet, zeigt Excel Millisekunden nur an, wenn die
   Spalte entsprechend formatiert ist (benutzerdefiniertes Zahlenformat
   ``TT.MM.JJJJ hh:mm:ss,000``). Die Werte in der Datei selbst enthalten die
   Millisekunden immer.

CSV-Datei laden
----------------------------------------------------------------------

**CSV laden** öffnet eine CSV- oder ZIP-Datei (bei ZIP-Archiven die erste
CSV im Archiv) und zeigt sie im Offline-Modus an. Eine laufende
Aufzeichnung wird dabei beendet. Zur Darstellung wird die Spalte ``Epoch``
verwendet. Variablen, deren Name in der aktuellen Konfiguration vorhanden ist,
übernehmen Farbe und Zuordnung zu Diagramm und Y-Achse; unbekannte Variablen
erscheinen auf der ersten Y-Achse des ersten Diagramms.


.. _installer:

Installationsdatei erstellen (Windows)
======================================================================

Aus den Python-Dateien lassen sich zwei eigenständige Programme
(``TIALogger.exe`` und ``TIAKonfiguration.exe``) und eine Setup-Datei erzeugen.
Dazu dienen:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Datei
     - Aufgabe
   * - ``build.bat``
     - Baut mit **PyInstaller** beide Programme in *einen* gemeinsamen Ordner
       (``dist\TIADatenlogger``) und anschließend mit **Inno Setup** den Installer.
   * - ``installer.iss``
     - Inno-Setup-Skript (Programmordner, Startmenü, optionale Desktop-Symbole,
       Deinstallation, Anleitung).
   * - ``make_icon.py``
     - Erzeugt ``app.ico`` aus dem Standard-Symbol, falls noch keine ``app.ico``
       existiert.
   * - ``requirements.txt``
     - Benötigte Python-Pakete (inkl. PyInstaller und docutils für den Build).

**Voraussetzungen:** Python 3.9 oder neuer (64 Bit), Internetzugang beim ersten
Lauf (pip) und für den Installer **Inno Setup 6**
(``https://jrsoftware.org/isinfo.php``).

**Ablauf:**

#. Alle Programmdateien (siehe Überblick) und die vier Build-Dateien liegen im
   selben Ordner.
#. In diesem Ordner ``build.bat`` starten (Doppelklick oder Eingabeaufforderung).

   .. code-block:: console

      build.bat              alles: Umgebung, Programme, Installer
      build.bat exe          nur die Programme (dist\TIADatenlogger)
      build.bat installer    nur den Installer (benötigt vorhandenes dist\)

#. Ergebnis: ``dist\TIADatenlogger`` (lauffähig ohne Installation) und
   ``installer\TIADatenlogger_Setup_<Version>.exe``.

Das Skript legt eine virtuelle Umgebung ``.venv`` an, installiert die Pakete,
erzeugt bei Bedarf das Icon und baut beide Programme. Die Versionsnummer wird
oben in ``build.bat`` bei ``VERSION`` eingestellt. Ein **eigenes Icon** entsteht,
indem Sie vor dem Build eine eigene ``app.ico`` in den Ordner legen.

**Speicherort der Daten:** Die installierten Programme schreiben Konfiguration
(``tia_config.json``), CSV-Dateien und Archiv **nicht** in den Programmordner
(dieser ist meist schreibgeschützt), sondern nach
``%APPDATA%\\TIADatenlogger``. Die Daten bleiben beim Deinstallieren und bei
Updates erhalten. Soll alles neben den Programmen liegen (portabler Betrieb auf
einem USB-Stick), legen Sie eine leere Datei ``portable.txt`` neben die
``.exe``-Dateien.

**Hinweise:**

* Die ``.exe``-Dateien enthalten Python und alle Bibliotheken (auch s7commplus und
  cryptography); auf dem
  Zielrechner muss nichts installiert werden.
* Der Logger startet die Konfiguration über **Konfiguration** in der
  Werkzeugleiste (``TIAKonfiguration.exe`` im selben Ordner).
* Schlägt der Build fehl, steht die Ursache in den Meldungen des Fensters
  (häufig: kein Internet für pip, Python nicht im PATH, Virenscanner sperrt
  ``dist``). Mit ``build.bat exe`` lässt sich der Installer-Schritt getrennt
  wiederholen.

Portable Version (ohne Installation)
----------------------------------------------------------------------

Statt des Installers lässt sich ein ZIP-Paket erzeugen, das nur entpackt wird –
z. B. auf einen USB-Stick oder in einen beliebigen Ordner:

.. code-block:: console

   build.bat portable

Ergebnis: ``dist\TIADatenlogger_portable_<Version>.zip`` (``build.bat`` ohne Parameter
erzeugt das ZIP zusätzlich zum Installer). Benutzung:

#. ZIP entpacken (Rechtsklick › *Alle extrahieren*).
#. ``TIAKonfiguration.exe`` bzw. ``TIALogger.exe`` im entpackten Ordner starten.
   Eine Installation oder Administratorrechte sind nicht nötig.

Im Paket liegt die Datei ``portable.txt``. Sie schaltet den portablen Betrieb ein:
Konfiguration, CSV-Dateien, Archiv und Logdatei liegen dann **im entpackten Ordner**
statt unter ``%APPDATA%``. Der Ordner muss deshalb beschreibbar sein (also nicht
unter ``C:\Program Files`` entpacken). Zum Entfernen genügt es, den Ordner zu
löschen. Für ein Update die neuen Programmdateien über den alten Ordner entpacken;
Konfiguration und Aufzeichnungen bleiben erhalten.

.. note::

   Beim ersten Start einer heruntergeladenen ``.exe`` kann Windows SmartScreen
   warnen (*Weitere Informationen › Trotzdem ausführen*), da die Programme nicht
   signiert sind. Unter *Eigenschaften › Zulassen* der ZIP-Datei lässt sich das
   vor dem Entpacken für alle Dateien aufheben.


.. _appimage:

Linux: AppImage (x86_64 und arm64)
======================================================================

Für Linux gibt es das Programm als **AppImage**: eine einzelne Datei, die ohne Installation
läuft. Sie enthält Logger, Konfigurationsprogramm und Ereignis-Viewer.

Benutzen
----------------------------------------------------------------------

.. code-block:: console

   chmod +x TIADatenlogger-2.1.0-x86_64.AppImage        # einmalig: ausführbar machen
   ./TIADatenlogger-2.1.0-x86_64.AppImage               # Logger (mit Startbild)
   ./TIADatenlogger-2.1.0-x86_64.AppImage --konfig      # Konfigurationsprogramm
   ./TIADatenlogger-2.1.0-x86_64.AppImage --ereignisse  # Ereignis-Viewer
   ./TIADatenlogger-2.1.0-x86_64.AppImage --headless anlage.json   # nur Aufzeichnung (z. B. als Dienst)

Auf Raspberry Pi (64-Bit-System) und anderen arm64-Rechnern entsprechend die Datei
``…-aarch64.AppImage``. Die Daten (Konfiguration, CSV, Archiv, Ereignisse, Sprachdateien)
liegen in ``~/TIADatenlogger``; liegt neben dem AppImage eine Datei ``portable.txt``, bleiben sie
im Ordner des AppImage. Manche Systeme brauchen für AppImages das Paket ``libfuse2``
(Ubuntu 22.04: ``sudo apt install libfuse2``, Ubuntu 24.04: ``libfuse2t64``); ohne FUSE
startet es auch mit ``--appimage-extract-and-run``.

Bauen
----------------------------------------------------------------------

``build_appimage.sh`` im Programmordner baut das AppImage für die Architektur des Rechners,
auf dem es läuft:

.. code-block:: console

   sudo apt install python3-venv cmake build-essential file libxkbcommon-x11-0 libxcb-cursor0 \
        libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libegl1 libfontconfig1 libdbus-1-3
   ./build_appimage.sh
   # Ergebnis: dist/TIADatenlogger-2.1.0-x86_64.AppImage (bzw. -aarch64)

* **x86_64** auf einem x86_64-Rechner bauen, **arm64** auf einem arm64-Rechner (Raspberry
  Pi 4/5 mit 64-Bit-System, Ubuntu arm64 …). PyInstaller kann nicht für eine andere
  Architektur übersetzen.
* Ohne arm64-Rechner: ``./build_appimage.sh --docker arm64`` baut in einem Docker-Container
  per QEMU-Emulation (langsam, aber auf jedem x86_64-PC mit Docker möglich).
* Das AppImage läuft auf Systemen mit **gleicher oder neuerer** glibc als das Build-System.
  Für möglichst viele Zielsysteme auf einem älteren System bauen (z. B. Ubuntu 22.04).
* Gibt es für PyQt6 auf einem älteren arm64-System kein passendes Paket, die Qt-Pakete des
  Systems verwenden: ``sudo apt install python3-pyqt6 python3-pyqt6.qtsvg`` und
  ``VENV_SYSTEM=1 ./build_appimage.sh``.
* **GitHub Actions**: Die Datei ``.github/workflows/appimage.yml`` (im obersten Ordner der
  Lieferung) baut alle drei Datenlogger für x86_64 und arm64 automatisch, wenn das Projekt in
  einem GitHub-Repository liegt (Actions › AppImages › Run workflow, oder bei einem Tag ``v*``).


Fehlersuche
======================================================================

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Problem
     - Mögliche Ursache und Abhilfe
   * - „Verbindung fehlgeschlagen“ / LED rot
     - IP-Adresse, Port und Netzwerkverbindung prüfen; Firewall (TCP 102).
       TLS-Fehler: *TLS* auf *Automatisch* oder *An* stellen (Firmware mit sicherer
       PG/HMI-Kommunikation). Anmeldung abgelehnt: Passwort der Zugriffsstufe
       eintragen bzw. prüfen; sonst *Rolle* auf *Engineering* stellen. Die übrigen
       Steuerungen laufen unabhängig weiter.
   * - „s7commplus fehlt“
     - ``pip install s7commplus`` (Python 3.10 oder neuer).
   * - Variablenliste lässt sich nicht laden oder ist leer
     - Verbindungsdaten wie oben prüfen. Variablen müssen „Erreichbar aus
       HMI/OPC UA/Web API“ sein. Große Projekte brauchen länger.
   * - LED „Datenbank“ rot
     - Server, Port, Datenbankname und Zugangsdaten mit **Datenbank testen** prüfen.
       Die Datenbank muss existieren (``CREATE DATABASE datenlogger;``), der Benutzer
       braucht CREATE- und INSERT-Rechte. „Treiber fehlt“: ``pip install PyMySQL`` bzw.
       ``pip install "psycopg[binary]"``. Die Werte werden bis zur Verbindung gepuffert.
   * - Webseite nicht erreichbar
     - Webserver in der Konfiguration eingeschaltet? Port von der Firewall frei?
       Host ``0.0.0.0`` (nicht ``127.0.0.1``) für Zugriffe von anderen Geräten.
       Mit Zugriffscode: ``/?token=CODE`` anhängen. Diagramme leer: Chart.js-Datei
       in ``web_static`` bzw. Internetzugang des Browsers prüfen.
   * - Logger startet ohne Fenster
     - In der Konfiguration ist *Headless-Modus* aktiv. Mit ``--gui`` starten oder
       die Option abschalten.
   * - „Variable … in der Steuerung nicht gefunden“
     - Schreibweise prüfen bzw. die Variable aus der Variablenliste übernehmen. Nach
       einer Programmänderung die Variablenliste neu laden. Nur diese Variable
       bleibt ohne Wert.
   * - „Lesefehler (Variable nicht lesbar oder geändert)“
     - Die Variable wurde in der Steuerung geändert oder gelöscht: Variablenliste
       neu laden und den Logger neu starten.
   * - „Keine Variablen“ beim Start
     - Zuerst im Konfigurationsprogramm Variablen anlegen und speichern, oder
       den Demo-Modus verwenden.
   * - Änderungen der Konfiguration wirken nicht
     - Der Logger lädt die Konfiguration beim Start. **■ Stop** und erneut
       **▶ Start** drücken.
   * - Diagramm ist leer
     - Aufzeichnung läuft nicht, oder die Variable ist über das Häkchen in der
       Wertetabelle ausgeblendet. Im Menü *Ansicht › Diagramme* prüfen, ob das
       Diagramm eingeblendet ist.
   * - Kurve einer Y-Achse ist nicht sichtbar
     - Feste Achsengrenzen liegen außerhalb der Werte. **Y-Auto** aktivieren
       oder die Grenzen in der Konfiguration anpassen.
   * - „⚠ Archivierung … fehlgeschlagen“
     - Archiv-Ordner nicht beschreibbar oder Datenträger voll. Die CSV-Datei
       bleibt im CSV-Ordner erhalten; Pfad und Rechte des Archiv-Ordners
       prüfen.
   * - Block lässt sich nicht lesen („Lesefehler“, **Block testen** schlägt fehl)
     - Der Ausschnitt (erster Index + Anzahl) liegt nicht vollständig im Array,
       oder das Format passt nicht zum Datentyp des Arrays. Arraygröße, Index und
       Format prüfen.
   * - Berechnete Variable zeigt keine Werte
     - Formel prüfen (Editor: **Prüfen / Berechnen**). Nicht berechenbare Werte
       (Division durch 0, fehlende Messwerte der verwendeten Variablen) ergeben
       Lücken. Beim Start meldet der Logger Formelfehler in einem Hinweisfenster.
   * - Logo oder Icon erscheint nicht
     - Pfad in der Konfiguration prüfen (relative Pfade gelten vom
       Programmordner). Bei SVG muss PyQt6 das SVG-Modul enthalten; ersatzweise
       PNG verwenden.
   * - Installierte Version findet die Konfiguration nicht
     - Die Daten liegen unter ``%APPDATA%\\TIADatenlogger`` (nicht im Programmordner).
       Mit ``portable.txt`` neben der ``.exe`` wird der Programmordner verwendet.
   * - Keine Millisekunden in Excel
     - Zellformat anpassen (siehe Hinweis im Abschnitt *CSV-Dateien*).


Bekannte Einschränkungen
======================================================================

* Ein Block gehört zu genau einer Steuerung; Formeln können aber Variablen
  verschiedener Steuerungen verknüpfen (es zählt der jeweils letzte Wert).
  Die Messzeitpunkte der Steuerungen sind nicht synchron.
* Der Webserver ist nur lesend und ohne Verschlüsselung (HTTP).
* Ein Block hat höchstens 1000 Elemente und genau ein Format.
* Berechnete Variablen kennen nur Werte der aktuellen Messung (außer den
  Zeitfunktionen ``ddt``, ``integ`` und ``avg``); beim Laden einer CSV-Datei
  werden sie nicht neu berechnet, sondern aus der Datei übernommen.
* Diagramme lassen sich per Drag & Drop nur innerhalb ihrer Seite umordnen;
  die Zuordnung zu einer Seite erfolgt in der Konfiguration.
* Aufgezeichnet werden Zahlen, BOOL und Zeiten; Texte, Datum/Uhrzeit und ganze
  Strukturen nicht (deren Glieder aber schon).
* ``s7commplus`` ist eine inoffizielle Implementierung; neue Firmwarestände können
  Anpassungen erfordern.
* Nur lesender Zugriff; der Logger schreibt nichts in die Steuerung.
* Die Y-Achsen lassen sich nicht per Maus skalieren; verwenden Sie die
  Auto-Skalierung oder feste Grenzen in der Konfiguration.
* Es wird immer nur die zeitlich nächste Messung ausgewertet; Werte zwischen
  zwei Messpunkten werden nicht interpoliert.
* Die minimale Abtastzeit hängt von der Kommunikation mit der Steuerung ab; bei
  vielen Variablen kann das eingestellte Intervall nicht eingehalten werden.
* Der Demo-Schalter und die Fensteranordnung werden nicht in der
  Konfigurationsdatei gespeichert.
