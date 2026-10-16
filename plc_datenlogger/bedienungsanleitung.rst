======================================================================
PLC Datenlogger – Bedienungsanleitung
======================================================================

.. contents:: Inhalt
   :depth: 2
   :local:


Überblick
======================================================================

Der PLC Datenlogger liest zyklisch Variablen aus einer oder **mehreren**
Steuerungen **unterschiedlicher Hersteller gleichzeitig**, speichert alle Messwerte
in einer gemeinsamen CSV-Datei (und/oder Datenbank) und zeigt sie als
y-t-Diagramm an – in der Oberfläche, im Browser (Webserver) oder gar nicht
(Headless-Betrieb, nur Aufzeichnung).

Er vereint die Einzelprogramme *S7 Datenlogger*, *TIA Datenlogger* und
*PLC Datenlogger* in einer Anwendung. Die Kommunikation mit den Steuerungen
übernehmen **Treiber**; jede Steuerung der Konfiguration bekommt ihren eigenen
Treiber. Eingebaut sind:

.. list-table::
   :header-rows: 1
   :widths: 12 38 50

   * - Treiber
     - Steuerungen / Protokoll
     - Bibliothek, Adressierung
   * - ``s7``
     - Siemens S7-300/400/1200/1500 über S7-Kommunikation (PUT/GET)
     - python-snap7; absolute Adressen wie ``DB10.DBD4``, ``M5.0``, ``EW64``
   * - ``tia``
     - Siemens S7-1200/1500 symbolisch über S7CommPlus (wie TIA Portal/HMI),
       auch optimierte Bausteine, ohne PUT/GET
     - s7commplus; symbolische Namen wie ``Anlage_DB.Motor[2].Drehzahl``
   * - ``clx``
     - Allen-Bradley ControlLogix, CompactLogix, Micro800 über EtherNet/IP (CIP)
     - libplctag (+ pycomm3 für die Tag-Liste); Tag-Namen wie ``Program:Main.Druck``
   * - ``modbus``
     - Modbus TCP (Wago, Schneider, Beckhoff, Phoenix Contact, Umrichter,
       Energiezähler, Gateways …)
     - keine Zusatzbibliothek; ``40001``, ``30001``, ``00001``, ``10001`` bzw.
       ``HR0``, ``IR0``, ``C0``, ``DI0``

Weitere Treiber lassen sich **ohne Änderung des Programms** ergänzen: Eine
Python-Datei im Ordner ``treiber`` des Datenordners genügt (siehe
:ref:`treiber-entwickeln`).

Das Programm besteht aus mehreren Dateien, die im selben Ordner liegen müssen:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Datei
     - Aufgabe
   * - ``plc_config.py``
     - Konfigurationsprogramm: Projekt, Steuerungen und Treiber, Diagramme,
       Y-Achsen und Variablen festlegen. Speichert in eine JSON-Datei mit beliebigem
       Namen (Standard ``plc_config.json``).
   * - ``plc_logger.py``
     - Startprogramm des Loggers: wählt anhand der Konfiguration bzw. der
       Parameter die Betriebsart (Oberfläche oder Headless).
   * - ``plc_gui.py``
     - Oberfläche des Loggers: Diagramme, Online-/Offline-Modus, Lineale,
       Status-LEDs. Wird von ``plc_logger.py`` geladen.
   * - ``plc_headless.py``
     - Betrieb ohne Oberfläche (nur Aufzeichnung, benötigt kein Qt).
   * - ``plc_recorder.py``
     - Aufzeichnungskern ohne Oberfläche: je Steuerung ein Lese-Thread (mit dem
       Leser ihres Treibers), ein Sammler-Thread für Zusammenführung, Formeln,
       Datenpuffer, CSV und Archiv.
   * - ``plc_treiber/``
     - Die Treiber: ``base.py`` (Schnittstelle), ``__init__.py`` (Verzeichnis,
       lädt eingebaute und eigene Treiber), ``ui.py`` (Einstellungsdialog der
       Verbindung), ``s7.py``/``s7_symbols.py``/``s7_browser.py``,
       ``tia.py``/``tia_io.py``/``tia_taglist.py``/``tia_browser.py``,
       ``clx.py``/``plc_io.py``/``plc_taglist.py``/``plc_browser.py``,
       ``modbus.py`` und ``_vorlage.py`` (Vorlage für eigene Treiber).
   * - ``plc_web.py``
     - Webserver (Flask) mit Chart.js-Seite zum Ansehen der Diagramme im Browser.
   * - ``plc_svg.py``
     - SVG-Export eines Diagramms (unabhängig von Qt).
   * - ``plc_util.py``
     - Kleine Hilfsfunktionen (Formatierung, Achsenteilung, Datenreduktion).
   * - ``plc_db.py``
     - Aufzeichnung in SQLite, MariaDB oder TimescaleDB/PostgreSQL (eigener Schreib-Thread).
   * - ``plc_db_dialog.py``
     - Lesemodus: Zeitraum aus der Datenbank wählen und im Logger anzeigen.
   * - ``plc_events.py``
     - Trigger und Ereignisprotokoll (Auswertung, Datei, Quittierung).
   * - ``plc_event_viewer.py``
     - Ereignis-Viewer (Anzeigen und Quittieren); auch allein startbar.
   * - ``plc_trigger_dialog.py``
     - Trigger-Editor des Konfigurationsprogramms.
   * - ``plc_pid.py``
     - PID-Regler-Optimierung: Streckenmodell, Einstellregeln, Simulation (ohne Oberfläche).
   * - ``plc_pid_dialog.py``
     - Fenster der PID-Optimierung (Logger) und Einstellungen dazu (Konfigurationsprogramm).
   * - ``plc_i18n.py``, ``sprachen/``
     - Sprachumschaltung und Sprachdateien (``de.txt`` = Vorlage, ``en.txt`` = Englisch).
   * - ``plc_splash.py``
     - Startbild (Auswahl der Konfiguration, Lade-Anzeige).
   * - ``build_appimage.sh``, ``tools/extract_tr.py``
     - Linux-AppImage bauen; Sprachdateien nach Programmänderungen aktualisieren.
   * - ``plc_common.py``
     - Datenmodell und Konfigurationsdatei (JSON) (inkl. Übernahme der Konfigurationen der
       Einzelprogramme). Wird nicht direkt gestartet.
   * - ``build.bat``, ``installer.iss``, ``make_icon.py``, ``requirements.txt``
     - Erzeugung der Windows-Installationsdatei (siehe :ref:`installer`).
   * - ``plctag.dll``
     - libplctag für Windows (64 Bit), vom Treiber ``clx`` benötigt.
   * - ``plc_block_dialog.py``
     - Editor für Blöcke (Blocklesemodus), vom Konfigurationsprogramm geöffnet.
   * - ``plc_formula.py``
     - Auswertung der Formeln berechneter Variablen. Wird nicht direkt gestartet.
   * - ``plc_formula_dialog.py``
     - Editor für berechnete Variablen (vom Konfigurationsprogramm geöffnet).
   * - ``plc_branding.py``
     - Programm-Icon und Logo. Wird nicht direkt gestartet.

Funktionsumfang:

* **Steuerungen verschiedener Hersteller in einer Aufzeichnung**, z. B. eine
  S7-1500 (symbolisch), eine S7-300 (PUT/GET), eine ControlLogix und einen
  Modbus-Energiezähler – mit gemeinsamer Zeitachse, gemeinsamen Diagrammen und
  Formeln über Steuerungsgrenzen hinweg
* **Erweiterbar** um eigene Treiber (Python-Datei in einen Ordner legen, fertig)
* Je Steuerung ein eigener Lese-Thread mit eigenem Abtastintervall; eine
  langsame oder ausgefallene Steuerung bremst die anderen nicht
* **Status-LEDs** für jede Verbindung (grau, gelb, grün, rot)
* Variablenauswahl direkt aus der Steuerung (TIA: Variablenliste der CPU, CLX:
  Tag-Liste) bzw. aus exportierten DB-Quellen (S7)
* Blocklesemodus: viele Werte mit einer Anfrage lesen (Array-Ausschnitte,
  zusammenhängende Adressbereiche)
* Konfigurationen der Einzelprogramme (S7, TIA, CLX) werden übernommen; ältere
  INI-Dateien einmalig umgewandelt
* Projektname und Konfigurationsdateien mit beliebigem Namen (Öffnen-Dialog)
* **Webserver** zum Ansehen der Diagramme im Browser (Tablet, Smartphone)
* **Headless-Betrieb** (ohne Diagramme, nur Aufzeichnung)
* CSV-Protokoll mit Zeitstempel in Millisekunden, Begrenzung der Dateigröße mit
  automatischer ZIP-Archivierung (Name/Jahr/Monat/Tag), Datenbank-Aufzeichnung mit
  Lesemodus (Zeitraum aus der Datenbank wählen und anzeigen)
* Berechnete Variablen aus Formeln (z. B. Mittelwert, Differenz, Integral)
* Trigger und Ereignisprotokoll mit Quittierung und eigenen Notizen
* PID-Regler-Optimierung aus aufgezeichneten Sprungantworten
* Mehrere Diagramme, je Diagramm mehrere Y-Achsen; Seiten/Tabs, Raster-Anordnung
* Legende mit Livewerten, Online-/Offline-Modus mit Linealen, Balken für Aktualwerte
* Screenshots einzelner Diagramme als PNG oder SVG
* Sprachumschaltung (Deutsch, Englisch, eigene Sprachdateien)
* Demo-Modus mit simulierten Werten (ohne SPS)


Installation und Start
======================================================================

Voraussetzungen
----------------------------------------------------------------------

* Python 3.9 oder neuer (64 Bit)
* Bibliotheken installieren (alle auf einmal):

  .. code-block:: console

     pip install -r requirements.txt

  bzw. einzeln:

  .. code-block:: console

     pip install PyQt6 pyqtgraph numpy Flask          # Oberfläche, Webserver
     pip install python-snap7                         # Treiber s7
     pip install s7commplus                           # Treiber tia
     pip install pycomm3                              # Treiber clx (Tag-Liste)

  Benötigt werden nur die Bibliotheken der Treiber, die Sie tatsächlich
  verwenden. Fehlt eine, wird der Treiber trotzdem angezeigt; der
  Einstellungsdialog der Steuerung und **Treiber › Installierte Treiber …**
  zeigen dann „✗ Bibliothek fehlt“. Der Treiber ``modbus`` braucht keine
  Bibliothek. Der Headless-Betrieb braucht kein PyQt6 und kein pyqtgraph.
* **libplctag** (nur Treiber ``clx``) ist kein pip-Paket. Benötigt wird
  ``plctag.dll`` (Windows, 64 Bit); sie liegt dem Programm bei. Sonst aus
  https://github.com/libplctag/libplctag/releases das Paket
  ``libplctag_<Version>_windows_x64.zip`` laden und ``plctag.dll`` **neben die
  Programmdateien** legen, oder ihren Pfad in der Umgebungsvariablen
  ``CLX_PLCTAG_LIB`` angeben. Unter Linux wird ``libplctag.so`` verwendet.
  libplctag steht unter MPL 2.0 bzw. LGPL 2; bei Weitergabe die Lizenzhinweise
  beachten.

Programme starten
----------------------------------------------------------------------

.. code-block:: console

   python plc_config.py [datei.json]     # Konfiguration
   python plc_logger.py [datei.json]     # Logger (Oberfläche oder Headless)

Ohne Dateiangabe wird die **zuletzt benutzte** Konfigurationsdatei geöffnet
(Standard: ``plc_config.json``). Der Name der Datei ist beliebig. Weitere Parameter
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

Vorbereitung der Steuerungen
----------------------------------------------------------------------

Der Logger liest nur; er schreibt nichts in die Steuerungen. Was in den
Steuerungen einzurichten ist, hängt vom Treiber ab und steht im Kapitel
:ref:`treiber` beim jeweiligen Treiber. Kurz:

* ``s7``: Bei S7-1200/1500 *PUT/GET-Kommunikation vom Partner erlauben* und nur
  **nicht optimierte** Datenbausteine lesen. TCP-Port 102.
* ``tia``: Nichts einzurichten; ggf. Passwort der Zugriffsstufe und TLS. TCP-Port 102.
* ``clx``: *External Access* der Tags *Read/Write* oder *Read Only*. TCP-Port 44818.
* ``modbus``: Modbus TCP im Gerät eingeschaltet, Register laut Gerätehandbuch.
  TCP-Port 502.

Die Firewall des PCs muss die Verbindungen auf den genannten Ports zulassen.

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
Wird beim Aufruf eine Konfigurationsdatei angegeben (z. B. ``PLCLogger.exe anlage.json``),
entfällt die Auswahl. Das Fenster lässt sich mit der Maus verschieben; **Esc** oder ✕ beendet.


Schnellstart
======================================================================

#. ``plc_config.py`` starten.
#. Im Reiter *Projekt & Steuerungen* einen Projektnamen vergeben und die
   Steuerung(en) eintragen: **Name**, **Treiber** wählen, mit **…** die
   Verbindung einstellen (IP-Adresse und die Parameter des Treibers), Intervall.
#. Mit dem Auswahlknopf des Treibers (z. B. **Aus Variablenliste wählen…**,
   **Aus Tag-Liste wählen…**, **Aus DB-Quelle wählen…**) Variablen aus der
   Steuerung übernehmen, oder mit **Variable hinzufügen** die Adresse von Hand
   eintragen.
#. Mit **Verbindung testen** prüfen, ob die Werte korrekt gelesen werden.
#. **Speichern** (bzw. **Speichern unter…** mit eigenem Dateinamen) und das
   Konfigurationsprogramm schließen.
#. ``plc_logger.py`` starten und **▶ Start** drücken.

.. tip::

   Eine vorhandene Konfiguration des S7-, TIA- oder CLX-Datenloggers öffnen Sie
   einfach mit **Datei › Öffnen…** (siehe :ref:`uebernahme`). Ohne SPS können Sie
   das Programm mit dem **Demo**-Modus ausprobieren (siehe :ref:`demo-modus`).


Konfigurationsprogramm (``plc_config.py``)
======================================================================

.. figure:: images/config_gesamt.png
   :alt: Konfigurationsprogramm
   :width: 90%
   :align: center

   Das Konfigurationsprogramm: Reiter oben, Zuordnungsbaum links, Variablentabelle rechts.

Projekt, Steuerungen und Einstellungen
----------------------------------------------------------------------

Der obere Fensterbereich ist in mehrere Reiter gegliedert.

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
     - Eine Zeile je Steuerung mit den Spalten:

       * **Name** – eindeutig, auch für die Status-LED.
       * **Treiber** – Auswahl aus allen geladenen Treibern (``s7``, ``tia``,
         ``clx``, ``modbus`` und eigene). Beim Wechsel des Treibers werden die
         Verbindungsparameter auf dessen Standardwerte gesetzt; die IP-Adresse
         bleibt erhalten. Die Typlisten der Variablen dieser Steuerung
         passen sich an.
       * **Verbindung** – Kurzbeschreibung der Verbindung, z. B.
         ``192.168.0.1, Rack 0/Slot 1`` oder ``192.168.0.10:502, Unit 1``.
       * **…** – öffnet den **Einstellungsdialog** der Verbindung (siehe unten).
         Doppelklick auf *Verbindung* hat dieselbe Wirkung.
       * **Intervall** – Zeit zwischen zwei Messungen dieser Steuerung, 10 bis
         60000 ms.
       * **Aktiv** – abgeschaltete Steuerungen werden nicht gelesen.

       Mit **+ Steuerung** und **Steuerung entfernen** ändern Sie die Liste; beim
       Entfernen wandern deren Variablen und Blöcke zur ersten Steuerung.

**Einstellungsdialog der Verbindung.** Der Dialog wird aus den Parametern des
Treibers aufgebaut (Textfelder, Zahlen, Auswahllisten, Passwortfelder).
Selten benötigte Parameter stehen im Bereich *Erweitert*. Unten zeigt der Dialog,
ob die benötigte Bibliothek installiert ist (✓ bzw. ✗ mit Fehlermeldung). Beim
**OK** prüft der Treiber die Eingaben (z. B. leere IP-Adresse). Die Parameter
der eingebauten Treiber sind im Kapitel :ref:`treiber` beschrieben.

Jede Steuerung wird im Logger von einem **eigenen Thread** gelesen. Das
Intervall gilt je Steuerung; eine langsame oder ausgefallene Steuerung bremst
die anderen nicht. Die Messwerte aller Steuerungen – gleich welchen Treibers –
werden in einer gemeinsamen CSV-Datei zusammengeführt (eine Spalte je Variable).

**Menü „Treiber“**

* **Installierte Treiber …** – Übersicht aller geladenen Treiber mit Kürzel,
  Name, benötigter Bibliothek und deren Zustand; darunter Treiber, die nicht
  geladen werden konnten (mit Fehlermeldung), und der Ordner für eigene Treiber.
* **Ordner für eigene Treiber öffnen …** – legt den Ordner ``treiber`` im
  Datenordner an (falls nötig), kopiert die Vorlage ``_vorlage.py`` hinein und
  öffnet ihn im Dateimanager (siehe :ref:`treiber-entwickeln`).

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

.. figure:: images/config_datenbank.png
   :alt: Reiter Datenbank
   :width: 80%
   :align: center

   Reiter „Datenbank“.

Auswahl und Zugangsdaten einer Datenbank, in die zusätzlich oder statt der
CSV-Datei aufgezeichnet wird (SQLite, MariaDB/MySQL, TimescaleDB/PostgreSQL), mit
dem Knopf **Datenbank testen**. Einzelheiten im Kapitel :ref:`datenbank`.

**Reiter „Trigger & Ereignisse“**

.. figure:: images/config_trigger_ereignis.png
   :alt: Reiter Trigger und Ereignisse
   :width: 80%
   :align: center

   Reiter „Trigger & Ereignisse“.

Zeigt die Zahl der angelegten Trigger. **Trigger bearbeiten …** öffnet den
Trigger-Editor, **Ereignisprotokoll anzeigen …** den Ereignis-Viewer, und unter
*Ereignisdatei* lässt sich der Speicherort des Ereignisprotokolls wählen (leer =
neben der CSV-Datei). Einzelheiten im Kapitel :ref:`ereignisse`.

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

   Die Variablentabelle mit Steuerung, Adresse, Typ, Farbe und Formel.

Jede Zeile der Variablentabelle beschreibt einen Wert einer Steuerung:

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
       Steuerungen). Sie bestimmt den Treiber und damit Schreibweise der Adresse
       und mögliche Typen.
   * - Diagramm › Y-Achse
     - Zuordnung der Variablen (Auswahlliste oder Drag & Drop, siehe unten).
   * - Adresse
     - Adresse in der Schreibweise des Treibers, z. B. ``DB10.DBD4`` (``s7``),
       ``Anlage_DB.Motor[2].Drehzahl`` (``tia``), ``Program:Main.Druck``
       (``clx``) oder ``40001`` (``modbus``). Der Tooltip der Zelle zeigt
       Beispiele für den Treiber der gewählten Steuerung. Einzelheiten im Kapitel
       :ref:`treiber`.
   * - Typ
     - Datentyp, Auswahl aus den Typen, die der Treiber lesen kann (z. B. ``BOOL``,
       ``INT``, ``DINT``, ``REAL``, ``LREAL`` …). Wird die Steuerung einer
       Variable geändert und kennt der neue Treiber den Typ nicht, bleibt er
       sichtbar stehen und wird beim Speichern als Fehler gemeldet.
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

Viele gleichartige Werte, die in der Steuerung hintereinander liegen, liest der
**Blocklesemodus** mit möglichst **einer Anfrage**; die Werte werden danach
einzeln zugewiesen. Was ein Block ist, hängt vom Treiber ab:

.. list-table::
   :header-rows: 1
   :widths: 15 85

   * - Treiber
     - Block
   * - ``s7``
     - **Startadresse** (z. B. ``DB10.DBD0``, ``MW100``) + Anzahl; die Elemente
       folgen lückenlos (``DB10.DBD0``, ``DB10.DBD4``, ``DB10.DBD8`` …; bei
       ``BOOL`` bitweise). Gelesen mit einer Anfrage.
   * - ``tia``
     - **Array ohne Index** (z. B. ``Mess_DB.Werte``) + **erster Index** (wie in
       TIA, z. B. 1 bei ``Array[1..100]``) + Anzahl.
   * - ``clx``
     - **Array-Tag ohne Index** (z. B. ``Messwerte``, ``Program:Main.Temp``) +
       **erster Index** + Anzahl. BOOL-Arrays sind bitweise gepackt und nicht als
       Block lesbar.
   * - ``modbus``
     - **Startadresse** (z. B. ``40001`` oder ``HR0``) + Anzahl; die Elemente
       folgen lückenlos (bei ``REAL`` je 2 Register: ``40001``, ``40003`` …).
       Der Treiber fasst ohnehin benachbarte Adressen zusammen; ein Block ist
       hier vor allem eine bequeme Art, viele Variablen anzulegen.

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
     - Steuerung, aus der der Block gelesen wird (bestimmt den Treiber).
   * - Startadresse / Array
     - Siehe Tabelle oben; der Tooltip zeigt die Schreibweise des Treibers.
   * - Erster Index
     - Nur bei Treibern mit Arrays (``tia``, ``clx``); sonst gesperrt.
   * - Format
     - Datentyp der Elemente (Auswahl des Treibers).
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
     - Berechnete Anzeige, z. B. ``DB10.DBD0 … DB10.DBD76 (80 Bytes)`` oder
       ``Messwerte[0] … Messwerte[19]``.

Beispiel (``clx``): Array-Tag ``Messwerte`` (``REAL[100]``), erster Index 10,
Anzahl 20 liest ``Messwerte[10]`` bis ``Messwerte[29]`` mit einer Anfrage und
erzeugt die Variablen ``Block[0]`` bis ``Block[19]``. Beispiel (``s7``):
Startadresse ``DB5.DBD0``, Format ``REAL``, Anzahl 20 liest die Bytes 0 bis 79
des DB 5.

Arrays lassen sich bei ``tia`` und ``clx`` auch direkt im Auswahldialog als
Block übernehmen (Array markieren, **Markiertes Array als Block…** oder
Doppelklick).

**Markierten Block testen** liest den Block einmal aus der Steuerung und zeigt die
ersten Werte sowie die Lesezeit an.

Hinweise:

* Die Block-Elemente sind normale Variablen: Sie erscheinen in Diagrammen,
  Legende, Wertetabelle, Balken und CSV-Datei und können in **Formeln**
  verwendet werden, z. B. ``{Messwerte[3]} - {Messwerte[4]}``.
* **Elementnamen ändern:** Im unteren Teil des Blockeditors zeigt ein **Baum**
  alle Blöcke mit ihren Elementen. Per Doppelklick auf die Spalte *Name* erhält
  ein Element einen eigenen Namen, z. B. ``Druck Vorlauf`` statt
  ``Messwerte[1]``. Ein leerer Name stellt den Standardnamen wieder her. Die
  Namen müssen eindeutig sein und dürfen ``; { }`` nicht enthalten. In der
  Konfigurationsdatei stehen sie unter ``elementnamen`` des Blocks.
* **Elemente in verschiedenen Diagrammen:** Im Baum des Blockeditors hat jedes
  Element in der letzten Spalte *Diagramm › Y-Achse* eine Auswahlliste. *(wie
  Block)* verwendet das Ziel des Blocks, jeder andere Eintrag stellt dieses
  Element in einem anderen Diagramm bzw. an einer anderen Y-Achse dar. Mit
  **Für alle Elemente des markierten Blocks setzen** wird das gewählte Ziel für
  alle Elemente übernommen. In der Konfigurationsdatei stehen abweichende Ziele
  unter ``elementziele`` (Index: [Diagramm, Achse]).
* Im Variablenbaum der Konfiguration erscheint jeder Block als eine Zeile
  (``▦ Block …``) unter seiner Y-Achse. Mit **Entfernen** wird der markierte
  Block gelöscht.
* Der Bereich muss vollständig in der Steuerung vorhanden sein (Array groß
  genug, DB lang genug, Register vorhanden), sonst schlägt das Lesen des Blocks
  fehl; die übrigen Variablen werden weiter gelesen.
* Viele Elemente bedeuten viele Kurven: Teilen Sie große Blöcke auf mehrere
  Diagramme bzw. Y-Achsen auf oder schalten Sie *Werteanzeige* ab.

Variablen aus der Steuerung wählen
----------------------------------------------------------------------

.. figure:: images/symbolbaum.png
   :alt: Auswahldialog
   :width: 90%
   :align: center

   Auswahl von Variablen aus der Steuerung.

Der Knopf über der Variablentabelle heißt je nach Treiber der gewählten
Steuerung unterschiedlich und öffnet dessen Auswahldialog (bei mehreren
Steuerungen wird zuerst gefragt, welche):

.. list-table::
   :header-rows: 1
   :widths: 15 25 60

   * - Treiber
     - Knopf
     - Herkunft der Variablen
   * - ``tia``
     - Aus Variablenliste wählen…
     - Variablenliste direkt aus der CPU (alle Datenbausteine, Merker, Ein- und
       Ausgänge mit Struktur und Typ, auch optimierte Bausteine).
   * - ``clx``
     - Aus Tag-Liste wählen…
     - Tag-Liste direkt aus der Steuerung (pycomm3): Controller- und
       Programm-Tags, UDTs, Arrays.
   * - ``s7``
     - Aus DB-Quelle wählen…
     - Exportierte DB-Quellen aus TIA Portal/STEP 7 (die SPS liefert über
       PUT/GET keine Namen); Abgleich der DB-Größen mit der SPS.
   * - ``modbus``
     - –
     - Modbus kennt keine Namen; Adressen laut Gerätehandbuch von Hand eintragen.

Allgemeines Vorgehen:

#. **Laden.** Beim ersten Öffnen wird die Liste aus der Steuerung geladen (``tia``,
   ``clx``) bzw. werden die DB-Quellen importiert (``s7``, **DB-Quelle
   importieren…**). Geladene Listen werden je Steuerung im Ordner ``taglisten``
   des Datenordners zwischengespeichert und beim nächsten Öffnen sofort angezeigt,
   auch ohne Verbindung. Die Pfade der S7-DB-Quellen werden in der Konfiguration
   gespeichert.
#. **Suchen.** Strukturen und Arrays lassen sich aufklappen; das **Filter**-Feld
   sucht nach Namen.
#. **Auswählen.** Lesbare Werte anhaken. Bereits angelegte Variablen sind
   angehakt und ausgegraut. Nicht aufzeichenbare Typen (z. B. ``STRING``) sind
   grau dargestellt.
#. **Arrays als Block** (``tia``, ``clx``): Array markieren, **Markiertes Array
   als Block…**, ersten Index und Anzahl festlegen.
#. **Übernehmen.** Unter *Neue Variablen anlegen in* das Diagramm bzw. die Y-Achse
   wählen und **Auswahl übernehmen** drücken. Adresse und Typ kommen aus der
   Steuerung bzw. Quelle.
#. **Prüfen.** Mit **Verbindung testen** die gelesenen Werte kontrollieren.

Einzelheiten zu den Dialogen stehen beim jeweiligen Treiber im Kapitel
:ref:`treiber`.

Verbindung testen
----------------------------------------------------------------------

**Verbindung testen** verbindet sich nacheinander mit jeder Steuerung
(über ihren Treiber), liest deren Variablen einmal und trägt das Ergebnis in die
Spalte *Testwert* ein. Fehler einzelner Variablen werden dort im Klartext
angezeigt (z. B. Adresse nicht vorhanden, falscher Typ, Zugriff verweigert,
Modbus-Ausnahme „ungültige Adresse“); kann eine Steuerung nicht erreicht werden,
meldet das ein Hinweisfenster mit Name und Verbindung.

Beim Speichern prüft der Treiber jeder Steuerung die Adressen formal (Schreibweise,
passender Typ, z. B. ``BOOL`` bei Coils). Ob es eine Adresse in der Steuerung
tatsächlich gibt, zeigt erst der Verbindungstest.

Speichern und Laden
----------------------------------------------------------------------

Das Menü **Datei** des Konfigurationsprogramms enthält:

* **Neu** – leere Konfiguration mit einer Steuerung; der Dateiname wird beim
  ersten Speichern abgefragt.
* **Öffnen…** (``Strg+O``) – lädt eine Konfigurationsdatei (JSON) mit **beliebigem
  Namen**, auch Konfigurationen des S7-, TIA- und CLX-Datenloggers (siehe
  :ref:`uebernahme`).
* **Speichern** (``Strg+S``) und **Speichern unter…** (``Strg+Umschalt+S``) –
  schreiben in die aktuelle bzw. eine neue Datei (die Endung ist immer ``.json``). Vor dem Speichern wird geprüft, dass Steuerungs- und
  Variablennamen eindeutig und nicht leer sind, die Verbindungsparameter und
  Adressen für den jeweiligen Treiber gültig sind, die Formeln stimmen und bei
  festen Y-Achsen *Y max* größer als *Y min* ist.
* **INI-Datei umwandeln …** – ältere INI-Konfigurationen einmalig in JSON umwandeln
  (siehe :ref:`ini-umwandeln`).
* **Logger mit dieser Konfiguration starten** (``Strg+R``) – speichert und
  startet den Logger mit dieser Datei.

Der Titel des Fensters zeigt Projektname und Dateiname. Die zuletzt benutzte
Datei wird gemerkt (Datei ``plc_last.txt``); Logger und Konfigurationsprogramm
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
     "format": "PLC Datenlogger Konfiguration",
     "version": 1,
     "einstellungen": {
       "projekt": "Prüfstand 3",
       "csv_ordner": "logs",
       "csv_name": "log",
       "max_records": 100000,
       "archiv_ordner": "archiv",
       "fenster_s": 60,
       "anordnung": "untereinander",
       "balken": true,
       "archiv_beenden": true,
       "seite_anordnung": "raster",
       "raster_spalten": 2,
       "web_aktiv": true,
       "web_host": "0.0.0.0",
       "web_port": 8080,
       "web_intervall_ms": 1000,
       "headless": false,
       "treiberdaten": {
         "s7": {
           "symbolquellen": "C:/Projekt/Mess_DB.db"
         }
       }
     },
     "steuerungen": [
       {
         "name": "Presse",
         "treiber": "tia",
         "intervall_ms": 100,
         "aktiv": true,
         "ip": "192.168.0.1",
         "port": 102,
         "tls": "auto",
         "passwort": "",
         "rolle": "hmi",
         "tags_je_anfrage": 50
       },
       {
         "name": "Altanlage",
         "treiber": "s7",
         "intervall_ms": 500,
         "aktiv": true,
         "ip": "192.168.0.20",
         "rack": 0,
         "slot": 2
       },
       {
         "name": "Kessel",
         "treiber": "clx",
         "intervall_ms": 200,
         "aktiv": true,
         "ip": "192.168.1.10",
         "pfad": "1,0",
         "cpu": "controllogix",
         "timeout_ms": 2000
       },
       {
         "name": "Zaehler",
         "treiber": "modbus",
         "intervall_ms": 1000,
         "aktiv": true,
         "ip": "192.168.0.50",
         "port": 502,
         "unit": 1,
         "wortfolge": "CDAB",
         "max_register": 120,
         "luecke": 8,
         "timeout_ms": 2000
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
             "name": "Leistung",
             "auto": false,
             "y_min": 0.0,
             "y_max": 50.0
           }
         ]
       }
     ],
     "variablen": [
       {
         "name": "Kraft",
         "adresse": "Presse_DB.Kraft",
         "typ": "REAL",
         "farbe": "#d62728",
         "wert_anzeigen": true,
         "diagramm": 1,
         "achse": 1,
         "balken": true,
         "formel": "",
         "steuerung": 1
       },
       {
         "name": "Temp_Alt",
         "adresse": "DB10.DBD4",
         "typ": "REAL",
         "steuerung": 2
       },
       {
         "name": "Temperatur_Kessel",
         "adresse": "Program:Kessel.Temperatur",
         "typ": "REAL",
         "steuerung": 3
       },
       {
         "name": "Wirkleistung",
         "adresse": "30013",
         "typ": "REAL",
         "steuerung": 4
       }
     ],
     "bloecke": [
       {
         "name": "Messwerte",
         "adresse": "Messwerte",
         "start": 0,
         "typ": "REAL",
         "anzahl": 20,
         "diagramm": 1,
         "achse": 1,
         "farbe": "#1f77b4",
         "wert_anzeigen": true,
         "balken": false,
         "steuerung": 3,
         "elementziele": {
           "3": [
             1,
             2
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

Erläuterungen:

* ``treiber`` ist das Kürzel des Treibers; die übrigen Schlüssel eines
  Eintrags in ``steuerungen`` (außer ``name``, ``intervall_ms``, ``aktiv``) sind dessen
  Verbindungsparameter (siehe :ref:`treiber`). Unbekannte Schlüssel werden
  ignoriert, fehlende erhalten den Standardwert des Treibers.
* ``adresse`` ist die Adresse in der Schreibweise des Treibers der Steuerung.
  Bei Blöcken ist ``adresse`` die Startadresse bzw. der Array-Name und ``start``
  der erste Index (nur ``tia``/``clx``).
* ``treiberdaten`` enthält treibereigene Angaben als Objekt (z. B. die Pfade der
  S7-DB-Quellen).
* ``diagramm``, ``achse`` und ``steuerung`` sind Nummern ab 1.
* ``seite_anordnung`` ist leer (automatisch), ``untereinander``,
  ``nebeneinander`` oder ``raster``; ``raster_spalten: 0`` wählt die Spaltenzahl
  automatisch.
* Die Variablen eines Blocks (``Messwerte[0]`` …) werden beim Laden erzeugt und
  stehen nicht unter ``variablen`` in der Datei.
* Das TIA-Passwort steht im **Klartext** in der Datei.

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



.. _treiber:

Steuerungen und Treiber
======================================================================

Jede Steuerung der Konfiguration hat genau einen Treiber. Er legt fest, welche
Verbindungsparameter es gibt, wie Variablen adressiert werden, welche Datentypen
lesbar sind, wie Blöcke aussehen und ob es einen Auswahldialog gibt. In einer
Konfiguration lassen sich beliebige Treiber mischen.

Treiber ``s7`` – Siemens S7 (PUT/GET, snap7)
----------------------------------------------------------------------

Für S7-300/400 und S7-1200/1500 über die klassische S7-Kommunikation mit
**absoluten Adressen**. Bibliothek: ``python-snap7``.

.. list-table:: Verbindungsparameter
   :header-rows: 1
   :widths: 20 80

   * - Parameter
     - Bedeutung
   * - IP-Adresse
     - Adresse der CPU bzw. des CP.
   * - Rack
     - Baugruppenträger, fast immer ``0``.
   * - Slot
     - Steckplatz der CPU: S7-300 ``2``, S7-1200/1500 ``1`` (bzw. ``0``),
       S7-400 laut Hardwarekonfiguration.

**Vorbereitung:** Bei S7-1200/1500 in TIA Portal in den CPU-Eigenschaften
*„PUT/GET-Kommunikation vom Partner erlauben“* aktivieren. Gelesen werden nur
Datenbausteine **ohne** „Optimierten Bausteinzugriff“ (für optimierte Bausteine
den Treiber ``tia`` verwenden). TCP-Port 102.

**Adressen** (deutsche oder englische Schreibweise; der Typ kommt aus der Spalte
*Typ*, die Größenangabe X/B/W/D in der Adresse ist nur Schreibhilfe):

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Adresse
     - Bedeutung
   * - ``DB10.DBX4.2``, ``DB10.DBB4``, ``DB10.DBW4``, ``DB10.DBD4``
     - Datenbaustein 10, Byte 4 (Bit 2)
   * - ``DB10.4``, ``DB10.4.2``
     - Kurzform: DB-Nummer, Byte[, Bit]
   * - ``M5.0``, ``MB5``, ``MW10``, ``MD20``
     - Merker
   * - ``E0.1``, ``EB0``, ``EW64`` bzw. ``I0.1``, ``IB0``, ``IW64``
     - Eingänge (Prozessabbild)
   * - ``A1.0``, ``AB1``, ``AW2`` bzw. ``Q1.0``, ``QB1``, ``QW2``
     - Ausgänge (Prozessabbild)

Beim Speichern wird die Adresse einheitlich passend zum Typ geschrieben (z. B.
``DB10.4`` mit Typ ``REAL`` → ``DB10.DBD4``).

**Typen:** ``BOOL``, ``BYTE``, ``USINT``, ``SINT``, ``CHAR``, ``WORD``, ``UINT``,
``INT``, ``DWORD``, ``UDINT``, ``DINT``, ``REAL``, ``TIME`` (ms), ``LWORD``,
``ULINT``, ``LINT``, ``LREAL``.

**Blöcke:** Startadresse + Anzahl, Elemente lückenlos; ein Block wird mit
**einer** Anfrage gelesen. Einzelvariablen werden einzeln gelesen – bei vielen
Variablen in einem DB ist ein Block deutlich schneller.

**Auswahldialog „Aus DB-Quelle wählen…“:** Die SPS liefert über
S7-Kommunikation **keine Namen und Strukturen**. Der Baum der Datenbausteine
(DB › Struktur › Variable) wird deshalb aus **DB-Quellen** aufgebaut:

#. In TIA Portal den DB (und benötigte UDTs) markieren, Rechtsklick *Quelle aus
   Bausteinen generieren*; in STEP 7 den DB als Quelle (``.db``/``.awl``)
   speichern.
#. Im Dialog **DB-Quelle importieren…** wählen (mehrere Dateien möglich). Fehlt die
   DB-Nummer in der Quelle (TIA), wird sie abgefragt.
#. Optional **Mit SPS abgleichen**: vergleicht die berechnete Größe jedes DB mit
   der Größe in der SPS (✓ bzw. ⚠ – Abweichung deutet auf einen optimierten
   Baustein oder eine veraltete Quelle hin).
#. Variablen anhaken (Häkchen an Struktur/Array/DB wählt alles darin) und
   übernehmen. Der Name der Variable ist der Symbolpfad.

Die Pfade der Quellen werden in der Konfiguration gespeichert (``treiberdaten``)
und beim nächsten Öffnen wieder gelesen.

Treiber ``tia`` – Siemens S7-1200/1500 symbolisch (S7CommPlus)
----------------------------------------------------------------------

Symbolischer Zugriff wie TIA Portal und Siemens-HMIs – auch auf **optimierte**
Datenbausteine, **ohne** PUT/GET. Bibliothek: ``s7commplus``.

.. list-table:: Verbindungsparameter
   :header-rows: 1
   :widths: 25 75

   * - Parameter
     - Bedeutung
   * - IP-Adresse
     - Adresse der CPU.
   * - Port
     - ISO-on-TCP-Port, Standard ``102``.
   * - TLS
     - *Automatisch* (TLS, wenn die CPU es anbietet), *Aus*, *An (TLS erzwingen)*.
       Neuere Firmware (S7-1500 ab V3.1, S7-1200 ab V4.7, Projekte ab TIA V19)
       kommuniziert nur verschlüsselt.
   * - Passwort
     - Passwort der Zugriffsstufe, falls die CPU lesenden Zugriff schützt
       (steht im Klartext in der Konfigurationsdatei).
   * - Rolle (Erweitert)
     - *HMI* (Standard), *Engineering*, *PG*.
   * - Variablen je Anfrage (Erweitert)
     - Höchstzahl Variablen je Leseanfrage (Standard 50); größere Mengen werden
       aufgeteilt.

**Vorbereitung:** In der Regel keine. Variablen müssen „Erreichbar aus
HMI/OPC UA/Web API“ sein (Standard). Jede CPU erlaubt nur eine begrenzte Zahl
von HMI-Verbindungen; der Logger belegt eine je Steuerung. TCP-Port 102.

**Adressen:** symbolische Namen wie in TIA Portal:

.. code-block:: text

   Mess_DB.Temp                     Variable in einem Datenbaustein
   Anlage_DB.Motor[2].Drehzahl      Strukturglied in einem Array
   MArea.Start_Merker               Merker (PLC-Variable)
   IArea.Taster_1                   Eingang
   QArea.Lampe                      Ausgang

**Typen:** ``BOOL``, ``BYTE``, ``WORD``, ``DWORD``, ``LWORD``, ``SINT``, ``INT``,
``DINT``, ``LINT``, ``USINT``, ``UINT``, ``UDINT``, ``ULINT``, ``REAL``,
``LREAL``, ``TIME``, ``LTIME``, ``S5TIME``, ``CHAR``, ``WCHAR``.

**Blöcke:** Array ohne Index + erster Index (wie in TIA, z. B. ``1`` bei
``Array[1..100]``) + Anzahl.

**Auswahldialog „Aus Variablenliste wählen…“:** lädt die Variablenliste direkt
aus der CPU (Datenbausteine, Merker, Ein-/Ausgänge mit Struktur und Typ) und
speichert sie im Ordner ``taglisten`` zwischen.

.. warning::

   ``s7commplus`` ist eine **inoffizielle** Implementierung, nicht von Siemens.
   Neue Konfigurationen zuerst an einer nicht sicherheitsrelevanten Anlage testen.

Treiber ``clx`` – Allen-Bradley Logix (EtherNet/IP)
----------------------------------------------------------------------

Für ControlLogix, CompactLogix und Micro800. Gelesen wird mit **libplctag**
(``plctag.dll`` / ``libplctag.so``); alle Tags einer Steuerung werden je Zyklus
gleichzeitig angestoßen und zu gemeinsamen CIP-Anfragen zusammengefasst. Die
Tag-Liste liefert **pycomm3**.

.. list-table:: Verbindungsparameter
   :header-rows: 1
   :widths: 25 75

   * - Parameter
     - Bedeutung
   * - IP-Adresse
     - Adresse des Ethernet-Moduls (z. B. 1756-EN2T) bzw. der CPU mit eingebautem
       Ethernet.
   * - CIP-Pfad
     - Weg zur CPU, ``Port,Adresse``; Backplane = Port 1. ControlLogix mit CPU in
       Steckplatz 0: ``1,0`` (Steckplatz 3: ``1,3``), CompactLogix: ``1,0``,
       Micro800: leer.
   * - Steuerungstyp
     - ControlLogix, CompactLogix oder Micro800.
   * - Zeitlimit (Erweitert)
     - Wartezeit je Lesezyklus (Standard 2000 ms).

**Vorbereitung:** *External Access* der Tags *Read/Write* oder *Read Only*.
TCP-Port 44818.

**Adressen:** Tag-Namen wie in Studio 5000 bzw. Connected Components Workbench:
``Temp_Kessel`` (Controller-Tag), ``Program:Main.Druck`` (Programm-Tag),
``Anlage.Motor[2].Drehzahl``, ``Status.3`` (Bit 3 eines Integers, Typ ``BOOL``).

**Typen:** ``BOOL``, ``SINT``, ``INT``, ``DINT``, ``LINT``, ``USINT``, ``UINT``,
``UDINT``, ``ULINT``, ``REAL``, ``LREAL`` (Bit-Strings ``DWORD``/``WORD`` als
``UDINT``/``UINT`` lesen).

**Blöcke:** Array-Tag ohne Index + erster Index + Anzahl; libplctag teilt große
Bereiche selbst auf. BOOL-Arrays nicht als Block.

**Auswahldialog „Aus Tag-Liste wählen…“:** Controller-Tags und (Häkchen
*Programm-Tags*) die Tags aller Programme, mit UDTs, Arrays (höchstens 500
Elemente einzeln) und Filter; Zwischenspeicher im Ordner ``taglisten``.

Treiber ``modbus`` – Modbus TCP
----------------------------------------------------------------------

Für alle Geräte mit Modbus TCP (auch Modbus-RTU-Geräte hinter einem
TCP-Gateway). Ohne Zusatzbibliothek. Benachbarte Adressen werden automatisch zu
möglichst wenigen Anfragen zusammengefasst (Funktionen 1 bis 4).

.. list-table:: Verbindungsparameter
   :header-rows: 1
   :widths: 30 70

   * - Parameter
     - Bedeutung
   * - IP-Adresse, Port
     - Adresse des Geräts bzw. Gateways, Port Standard ``502``.
   * - Geräteadresse (Unit-ID)
     - Slave-/Unit-ID (Standard 1); bei Gateways die Adresse am seriellen Bus.
   * - Byte-/Wortfolge
     - Reihenfolge bei Werten über mehrere Register (``DINT``, ``REAL`` …) laut
       Gerätehandbuch: ``ABCD`` Big Endian (Standard), ``CDAB`` Wörter getauscht
       (häufig, z. B. bei vielen Energiezählern), ``BADC`` Bytes getauscht,
       ``DCBA`` Little Endian.
   * - Register je Anfrage (Erweitert)
     - Höchstzahl Register einer Anfrage (1 bis 125, Standard 120).
   * - Lücke zusammenfassen bis (Erweitert)
     - Adressen mit kleinerem Abstand werden in einer Anfrage mitgelesen
       (Standard 8 Register; 0 = nur lückenlose).
   * - Zeitlimit (Erweitert)
     - Wartezeit auf eine Antwort (Standard 2000 ms).

**Adressen** – Modicon-Schreibweise (ab 1 gezählt) oder Tabelle + Offset (ab 0):

.. list-table::
   :header-rows: 1
   :widths: 35 30 35

   * - Modicon
     - ab 0
     - Bereich, Funktion
   * - ``40001`` … (6-stellig ``400001``)
     - ``HR0`` …
     - Holding-Register, FC 3
   * - ``30001`` … (``300001``)
     - ``IR0`` …
     - Input-Register, FC 4
   * - ``00001`` … bzw. ``1`` …
     - ``C0`` …
     - Coils, FC 1 (Typ ``BOOL``)
   * - ``10001`` … (``100001``)
     - ``DI0`` …
     - Discrete Inputs, FC 2 (Typ ``BOOL``)
   * - ``40001.3``
     - ``HR0.3``
     - Bit 3 eines Registers (Typ ``BOOL``, Bit 0–15)

``40001`` und ``HR0`` bezeichnen dasselbe Register. Steht im Gerätehandbuch
„Register 100“ ohne Zusatz, ist meist ``HR100`` (= ``40101``) gemeint – im
Zweifel mit **Verbindung testen** beide prüfen. ``%MW0`` (Schneider) wird als
``HR0`` verstanden.

**Typen:** ``BOOL``, ``INT``, ``UINT``, ``WORD`` (1 Register), ``DINT``,
``UDINT``, ``DWORD``, ``REAL`` (2 Register), ``LINT``, ``ULINT``, ``LWORD``,
``LREAL`` (4 Register).

**Blöcke:** Startadresse + Anzahl, Elemente lückenlos (bei ``REAL`` im Abstand
von 2 Registern).

**Fehler:** Antwortet das Gerät mit einer Modbus-Ausnahme (z. B. *ungültige
Adresse*), bleibt nur die betroffene Anfrage ohne Wert; die Meldung erscheint
in der Statuszeile bzw. als Testwert.


.. _uebernahme:

Übernahme von Konfigurationen der Einzelprogramme
======================================================================

Konfigurationsdateien des **S7 Datenloggers**, **TIA Datenloggers** und
**CLX Datenloggers** werden übernommen – als JSON-Datei direkt mit **Datei › Öffnen…**,
als ältere INI-Datei nach der einmaligen Umwandlung (**Datei › INI-Datei umwandeln …**,
siehe :ref:`ini-umwandeln`). Dabei gilt:

* Der Treiber jeder Steuerung wird aus ihren Einträgen erkannt: ``rack``/``slot`` →
  ``s7``, ``pfad``/``cpu`` → ``clx``, ``tls``/``rolle``/``port`` → ``tia``.
* S7-Variablen (``bereich``, ``db``, ``byte``, ``bit``) werden in Adressen
  umgerechnet, z. B. ``DB10.DBD4`` oder ``M5.0``; S7-Blöcke erhalten ihre
  Startadresse. Tag-Namen von TIA und CLX werden unverändert übernommen.
* Die Pfade der S7-DB-Quellen (``symbolquellen``) wandern nach ``treiberdaten``.
* Diagramme, Achsen, Formeln, Blöcke, Trigger, PID-Einstellungen, Datenbank,
  Webserver und Anzeige werden unverändert übernommen.

Gespeichert wird im Format des PLC Datenloggers (Schlüssel ``treiber`` und
``adresse``). Die Einzelprogramme können diese Datei danach **nicht** mehr lesen –
speichern Sie deshalb mit **Speichern unter…** unter neuem Namen, wenn die Datei
auch im Einzelprogramm weiter benutzt werden soll.

Konfigurationen mehrerer Einzelprogramme lassen sich zusammenführen, indem die
Steuerungen und Variablen im Konfigurationsprogramm neu angelegt oder die
Einträge der Listen ``steuerungen`` und ``variablen`` in der JSON-Datei von Hand
kopiert werden (``steuerung`` der Variablen anpassen).


Logger (``plc_logger.py``)
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
  Namen zeigt die Adresse (bei berechneten Variablen die Formel).
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
  ``plc_logger.log`` im Programm- bzw. Datenordner (rotierend, mehrere Dateien).
* **Beenden:** Mit ``Strg+C`` im Konsolenfenster bzw. durch das Signal SIGTERM
  (Dienst beenden, Windows: Fenster schließen) wird sauber beendet: Die
  CSV-Datei wird geschlossen und – bei gesetzter Option – archiviert.
* Die installierte Version enthält im Startmenü die Verknüpfung
  *PLC Datenlogger (Headless, nur Aufzeichnung)*.



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

.. figure:: images/datenbank.png
   :alt: Dialog Aus Datenbank laden
   :width: 85%
   :align: center

   Dialog „Aus Datenbank laden“: Variablen, Zeitraum und Auflösung wählen.

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

   PLCLogger.exe --ereignisse                        (Ereignisprotokoll der zuletzt benutzten Konfiguration)
   PLCLogger.exe --ereignisse anlage.json             (Ereignisprotokoll dieser Konfiguration)
   PLCLogger.exe --ereignisse D:\logs\log_ereignisse.csv

Die installierte Version hat dafür im Startmenü die Verknüpfung *PLC Ereignisprotokoll*.
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
* **Übernahme in die Steuerung:** *PIDE* mit unabhängigen Verstärkungen: ``PGain`` = Kp, ``IGain`` = Ki·60 [1/min], ``DGain`` = Kd/60 [min]. *PIDE* abhängige Form bzw. *PID*-Anweisung: ``Kc`` = Kp, Ti und Td in **Minuten** (Werte aus der Tabelle durch 60 teilen). *PIDE* rechnet in % der Bereiche ``PVEUMax/Min`` und ``CVEUMax/Min`` – Kp entsprechend umrechnen.


.. _sprache:

Sprache umschalten und übersetzen
======================================================================

Die Oberfläche ist auf Deutsch geschrieben und lässt sich über **Sprachdateien** in
andere Sprachen übersetzen. Mitgeliefert werden **Deutsch** und **Englisch**.

Umschalten
----------------------------------------------------------------------

Menü **Sprache** (im Logger und im Konfigurationsprogramm): Sprache wählen und die Frage
nach dem Neustart bestätigen. Die Wahl gilt für beide Programme und den Ereignis-Viewer
und wird in der Datei ``plc_einstellungen.json`` im Datenordner gespeichert. Auch die
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
(Modul ``plc_i18n.py``). Nach Programmänderungen bringt
``python tools/extract_tr.py clx .`` alle Sprachdateien auf den neuesten Stand (neue
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

.. _treiber-entwickeln:

Treiber entwickeln
======================================================================

Ein Treiber ist **eine Python-Datei**. Sie wird beim Programmstart automatisch
geladen; das Programm selbst muss weder geändert noch neu gebaut werden – auch die
installierte ``.exe`` bzw. das AppImage lädt eigene Treiber.

Wo Treiber gesucht werden
----------------------------------------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Ort
     - Hinweis
   * - Ordner ``treiber`` im **Datenordner**
     - Empfohlen. Windows installiert: ``%APPDATA%\PLCDatenlogger\treiber``,
       Linux: ``~/PLCDatenlogger/treiber``, portabel bzw. Python-Quellen: Ordner
       ``treiber`` neben den Programmdateien. Bleibt bei Updates erhalten.
       Öffnen mit **Treiber › Ordner für eigene Treiber öffnen …**.
   * - Ordner in der Umgebungsvariablen ``PLC_TREIBER``
     - Mehrere Ordner mit ``;`` (Windows) bzw. ``:`` (Linux) trennen – z. B. für
       einen gemeinsamen Netzwerkordner.
   * - Paket ``plc_treiber`` (nur Python-Quellen)
     - Datei direkt neben ``s7.py`` usw.; Dateiname **ohne** Unterstrich
       (Namen mit ``_`` gelten dort als Hilfsmodule, z. B. ``s7_browser.py``).

Dateien, deren Name mit ``_`` beginnt (z. B. ``_vorlage.py``), werden **nicht**
geladen. Hilfsmodule eines Treibers können neben ihm im selben Ordner liegen
(der Ordner wird in den Suchpfad aufgenommen). Kann ein Treiber nicht geladen
werden (Syntaxfehler, fehlende Bibliothek beim Import, doppeltes Kürzel), laufen
alle anderen weiter; die Fehlermeldung steht unter **Treiber › Installierte
Treiber …**.

In fünf Schritten zum eigenen Treiber
----------------------------------------------------------------------

#. **Treiber › Ordner für eigene Treiber öffnen …** – der Ordner enthält danach
   die Vorlage ``_vorlage.py``.
#. Die Vorlage kopieren, z. B. nach ``meine_sps.py`` (ohne ``_`` am Anfang).
   Unverändert ist sie bereits ein funktionierender Treiber „Simulation“, der
   Sinus-, Rampen-, Rechteck- und Zufallswerte liefert (Adressen ``sinus:20``,
   ``rampe:10``, ``rechteck:4``, ``zufall:50``).
#. Kürzel ``id`` (eindeutig, steht in der Konfigurationsdatei), ``name``,
   ``params`` und ``types`` anpassen.
#. In der Reader-Klasse ``connect()``, ``read()`` und ``close()`` mit dem
   Protokoll der Steuerung füllen.
#. Konfigurationsprogramm neu starten – der Treiber erscheint in der Auswahl
   *Treiber* der Steuerungstabelle.

Minimaler Treiber
----------------------------------------------------------------------

.. code-block:: python

   from plc_treiber.base import NAN, Driver, Param, Reader

   class MeinReader(Reader):
       def connect(self):
           # Verbindung aufbauen; Fehler als Ausnahme melden (z. B. ConnectionError)
           self.sock = verbinde(self.plc.params["ip"], self.plc.params["port"])
           return len(self.vars)                 # Anzahl lesbarer Variablen

       def read(self):
           # EIN Messzyklus: Werte in der Reihenfolge von self.vars, float, NaN = kein Wert
           out = []
           for v in self.vars:
               try:
                   out.append(float(lies(self.sock, v.address, v.dtype)))
                   self.errors.pop(v.address, None)
               except KeyError as e:             # nur diese Variable fehlt
                   self.errors[v.address] = str(e)
                   out.append(NAN)
           return out

       def close(self):
           self.sock.close()

   class MeinTreiber(Driver):
       id = "mein"
       name = "Meine Steuerung"
       description = "Kurzbeschreibung für den Einstellungsdialog"
       params = [
           Param("ip", "IP-Adresse", "text", "192.168.0.10"),
           Param("port", "Port", "int", 5000, minimum=1, maximum=65535),
       ]
       types = ["BOOL", "INT", "DINT", "REAL"]
       address_hint = "z. B. R100"

       def create_reader(self, plc, variables):
           return MeinReader(self, plc, variables)

   DRIVER = MeinTreiber()

Schnittstelle
----------------------------------------------------------------------

Alle Einzelheiten stehen in ``plc_treiber/base.py``. Die wichtigsten Teile:

.. list-table:: Klasse ``Driver`` – Attribute
   :header-rows: 1
   :widths: 30 70

   * - Attribut
     - Bedeutung
   * - ``id``
     - Eindeutiges Kürzel (Kleinbuchstaben), steht als ``"treiber": "…"`` in der
       Konfigurationsdatei. Nach der Einführung nicht mehr ändern.
   * - ``name``, ``description``
     - Anzeigename (Auswahlliste) und Beschreibung (Einstellungsdialog).
   * - ``params``
     - Liste von ``Param`` – daraus entsteht der Einstellungsdialog; die Werte
       stehen in der Konfigurationsdatei und im Leser in ``self.plc.params``.
   * - ``types``, ``block_types``, ``default_type``
     - Lesbare Datentypen (Auswahl aus ``BOOL, BYTE, WORD, DWORD, LWORD, SINT, INT,
       DINT, LINT, USINT, UINT, UDINT, ULINT, REAL, LREAL, TIME, LTIME, S5TIME,
       CHAR, WCHAR``), Formate für Blöcke (``None`` = wie ``types``), Vorgabe.
   * - ``address_label``, ``address_hint``, ``block_hint``
     - Bezeichnung und Tooltip-Texte für Adressen und Blöcke.
   * - ``block_uses_index``
     - ``True``: Block = Array-Name + erster Index (Elemente ``Name[i]``);
       ``False``: Block = Startadresse (Elementadresse über
       ``block_element_address``).
   * - ``browse_label``
     - Text des Auswahlknopfs; leer = kein Auswahldialog.
   * - ``library``
     - Name der benötigten Bibliothek (für Anzeigen).

.. list-table:: Klasse ``Driver`` – Methoden (alle optional außer ``create_reader``)
   :header-rows: 1
   :widths: 35 65

   * - Methode
     - Aufgabe
   * - ``create_reader(plc, variables)``
     - Liefert den ``Reader`` für eine Steuerung.
   * - ``summary(plc)``
     - Kurztext der Verbindung für Tabelle, LEDs und Meldungen.
   * - ``check_params(params)``
     - Fehlertext für ungültige Parameter oder ``""``.
   * - ``check_address(address, dtype)``
     - Formale Prüfung einer Adresse beim Speichern; Fehlertext oder ``""``.
   * - ``normalize_address(address, dtype)``
     - Einheitliche Schreibweise (z. B. Großbuchstaben).
   * - ``block_element_address(block, i)``
     - Adresse des i-ten Block-Elements (``block.address``, ``block.start``,
       ``block.dtype``).
   * - ``check_block(block)``, ``type_size(dtype)``
     - Prüfung eines Blocks; Größe eines Typs in Bytes (für die Anzeige).
   * - ``check_library()``
     - Prüft die Bibliothek (``import …``); Ausnahme mit Hinweis, wenn sie fehlt.
       Bibliotheken möglichst erst hier bzw. in ``connect()`` importieren, damit
       der Treiber auch ohne sie geladen wird.
   * - ``read_once(plc, variables)``
     - Verbindungstest; Standard: ``connect`` + ``read`` + ``close``.
   * - ``browse(parent, ctx)``
     - Auswahldialog (Qt). ``ctx``: ``BrowseContext`` mit ``plc``, ``existing``
       (vorhandene Adressen), ``target_labels``, ``default_target`` und ``store``
       (treibereigene, in der Konfiguration gespeicherte Werte). Rückgabe:
       ``BrowseResult`` mit ``variables`` = ``[(Name, Adresse, Typ)]``,
       ``blocks`` = ``[(Name, Adresse, erster Index, Anzahl, Typ)]``,
       ``target_index`` und geändertem ``store`` – oder ``None`` bei Abbruch.

.. list-table:: Klasse ``Reader``
   :header-rows: 1
   :widths: 30 70

   * - Teil
     - Bedeutung
   * - ``self.plc``, ``self.vars``, ``self.driver``
     - Steuerung (``plc.params``, ``plc.name``), zu lesende Variablen (je
       ``address``, ``dtype``, ``name``, ``block``, ``block_idx``), Treiber.
   * - ``connect()``
     - Verbindung aufbauen und prüfen; Rückgabe: Anzahl lesbarer Variablen.
   * - ``read()``
     - Ein Messzyklus; Liste von ``float`` in der Reihenfolge von ``self.vars``,
       ``NAN`` für nicht lesbare Werte. Möglichst wenige Anfragen (Variablen mit
       gleichem ``block`` gemeinsam lesen).
   * - ``close()``
     - Verbindung schließen (darf mehrfach aufgerufen werden).
   * - ``self.errors``
     - ``{Adresse: Fehlertext}`` einzelner nicht lesbarer Variablen; erscheint in
       Statuszeile und Testwert. Die übrigen Variablen werden weiter gelesen.

Regeln:

* **Verbindungsfehler** (Steuerung nicht erreichbar, Socket geschlossen) als
  Ausnahme aus ``connect()``/``read()`` melden. Der Lese-Thread zeigt die LED
  rot, schließt den Leser und verbindet nach kurzer Wartezeit neu.
* **Fehler einzelner Variablen** dagegen in ``self.errors`` eintragen und ``NAN``
  liefern – keine Ausnahme.
* Jeder Leser läuft in **seinem eigenen Thread**; er muss nicht thread-sicher
  sein, darf aber keine globalen Objekte unsynchronisiert mit anderen Lesern
  teilen.
* ``read()`` sollte deutlich kürzer dauern als das Intervall der Steuerung.
* Texte für die Oberfläche können mit ``from plc_i18n import tr`` übersetzbar
  gemacht werden (``tools/extract_tr.py`` nimmt Treiber im Paket mit auf).

Für fertige Beispiele lohnt ein Blick in ``plc_treiber/modbus.py`` (eigenes
Protokoll über Sockets, Zusammenfassen von Anfragen, eigene Adressschreibweise)
und ``plc_treiber/s7.py`` (Bibliothek, Blöcke, Auswahldialog).

Testen ohne Oberfläche
----------------------------------------------------------------------

.. code-block:: python

   import sys; sys.path.insert(0, r"C:\Pfad\zum\plc_datenlogger")
   from plc_common import Plc, Variable
   from plc_treiber import get_driver, load_errors

   print(load_errors())                                  # Ladefehler?
   d = get_driver("mein")
   plc = Plc(name="Test", driver="mein", params=d.default_params())
   werte, fehler = d.read_once(plc, [Variable("A", address="R100", dtype="INT")])
   print(werte, fehler)

Treiber in die ``.exe`` aufnehmen
----------------------------------------------------------------------

Eigene Treiber im Ordner ``treiber`` brauchen keinen Neubau. Soll ein Treiber
fest eingebaut werden, die Datei in ``plc_treiber/`` legen, ihr Kürzel in
``BUILTIN`` in ``plc_treiber/__init__.py`` eintragen (optional, legt nur die
Reihenfolge fest) und benötigte Bibliotheken in ``requirements.txt`` sowie –
falls PyInstaller sie nicht findet – als ``--collect-all`` in ``build.bat`` bzw.
``build_appimage.sh`` ergänzen. ``build.bat`` nimmt alle Module von
``plc_treiber`` automatisch auf (``--collect-submodules plc_treiber``).


Installationsdatei erstellen (Windows)
======================================================================

Aus den Python-Dateien lassen sich zwei eigenständige Programme
(``PLCLogger.exe`` und ``PLCKonfiguration.exe``) und eine Setup-Datei erzeugen.
Dazu dienen:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Datei
     - Aufgabe
   * - ``build.bat``
     - Baut mit **PyInstaller** beide Programme in *einen* gemeinsamen Ordner
       (``dist\PLCDatenlogger``) und anschließend mit **Inno Setup** den Installer.
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
      build.bat exe          nur die Programme (dist\PLCDatenlogger)
      build.bat installer    nur den Installer (benötigt vorhandenes dist\)

#. Ergebnis: ``dist\PLCDatenlogger`` (lauffähig ohne Installation) und
   ``installer\PLCDatenlogger_Setup_<Version>.exe``.

Das Skript legt eine virtuelle Umgebung ``.venv`` an, installiert die Pakete,
erzeugt bei Bedarf das Icon und baut beide Programme. Die Versionsnummer wird
oben in ``build.bat`` bei ``VERSION`` eingestellt. Ein **eigenes Icon** entsteht,
indem Sie vor dem Build eine eigene ``app.ico`` in den Ordner legen.

**Speicherort der Daten:** Die installierten Programme schreiben Konfiguration
(``plc_config.json``), CSV-Dateien und Archiv **nicht** in den Programmordner
(dieser ist meist schreibgeschützt), sondern nach
``%APPDATA%\\PLCDatenlogger``. Die Daten bleiben beim Deinstallieren und bei
Updates erhalten. Soll alles neben den Programmen liegen (portabler Betrieb auf
einem USB-Stick), legen Sie eine leere Datei ``portable.txt`` neben die
``.exe``-Dateien.

**Hinweise:**

* Die ``.exe``-Dateien enthalten Python und alle Bibliotheken (die
  ``plctag.dll`` sowie die Bibliotheken aller eingebauten Treiber – python-snap7, s7commplus, pycomm3 – werden mitgenommen; fehlt ``plctag.dll`` neben
  ``build.bat``, lädt das Skript sie einmalig aus dem GitHub-Release von libplctag); auf dem
  Zielrechner muss nichts installiert werden.
* Der Logger startet die Konfiguration über **Konfiguration** in der
  Werkzeugleiste (``PLCKonfiguration.exe`` im selben Ordner).
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

Ergebnis: ``dist\PLCDatenlogger_portable_<Version>.zip`` (``build.bat`` ohne Parameter
erzeugt das ZIP zusätzlich zum Installer). Benutzung:

#. ZIP entpacken (Rechtsklick › *Alle extrahieren*).
#. ``PLCKonfiguration.exe`` bzw. ``PLCLogger.exe`` im entpackten Ordner starten.
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


Bauen auf GitHub (ohne eigenen Windows-PC)
----------------------------------------------------------------------

Liegt das Projekt in einem GitHub-Repository, baut der Workflow
``.github/workflows/windows.yml`` (im obersten Ordner der Lieferung) für alle vier
Datenlogger das **portable ZIP** und den **Installer** auf einem Windows-Rechner von
GitHub:

* **Von Hand:** *Actions › Windows › Run workflow*. Die Dateien liegen danach in der
  Zusammenfassung des Laufs unter *Artifacts* (je Programm ``…-portable`` und
  ``…-setup``).
* **Mit einem Tag** ``v*`` (z. B. ``v2.1.0``): zusätzlich als Dateien eines
  GitHub-Release, zusammen mit den AppImages.

Gebaut wird mit ``build.bat`` wie auf dem eigenen PC; die Versionsnummer kommt aus
``VERSION`` in ``build.bat``. Bilder der Anleitung (Ordner ``images``) werden
mitgenommen, wenn sie im Repository liegen.

.. _appimage:

Linux: AppImage (x86_64 und arm64)
======================================================================

Für Linux gibt es das Programm als **AppImage**: eine einzelne Datei, die ohne Installation
läuft. Sie enthält Logger, Konfigurationsprogramm und Ereignis-Viewer.

Benutzen
----------------------------------------------------------------------

.. code-block:: console

   chmod +x PLCDatenlogger-2.1.0-x86_64.AppImage        # einmalig: ausführbar machen
   ./PLCDatenlogger-2.1.0-x86_64.AppImage               # Logger (mit Startbild)
   ./PLCDatenlogger-2.1.0-x86_64.AppImage --konfig      # Konfigurationsprogramm
   ./PLCDatenlogger-2.1.0-x86_64.AppImage --ereignisse  # Ereignis-Viewer
   ./PLCDatenlogger-2.1.0-x86_64.AppImage --headless anlage.json   # nur Aufzeichnung (z. B. als Dienst)

Auf Raspberry Pi (64-Bit-System) und anderen arm64-Rechnern entsprechend die Datei
``…-aarch64.AppImage``. Die Daten (Konfiguration, CSV, Archiv, Ereignisse, Sprachdateien)
liegen in ``~/PLCDatenlogger``; liegt neben dem AppImage eine Datei ``portable.txt``, bleiben sie
im Ordner des AppImage. Manche Systeme brauchen für AppImages das Paket ``libfuse2``
(Ubuntu 22.04: ``sudo apt install libfuse2``, Ubuntu 24.04: ``libfuse2t64``); ohne FUSE
startet es auch mit ``--appimage-extract-and-run``.

Die Bibliothek **libplctag** (``libplctag.so``) wird beim Bauen aus dem Quelltext übersetzt und ist im AppImage enthalten.

Bauen
----------------------------------------------------------------------

``build_appimage.sh`` im Programmordner baut das AppImage für die Architektur des Rechners,
auf dem es läuft:

.. code-block:: console

   sudo apt install python3-venv cmake build-essential file libxkbcommon-x11-0 libxcb-cursor0 \
        libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libegl1 libfontconfig1 libdbus-1-3
   ./build_appimage.sh
   # Ergebnis: dist/PLCDatenlogger-2.1.0-x86_64.AppImage (bzw. -aarch64)

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
  Lieferung) baut alle vier Datenlogger (S7, CLX, TIA und PLC) für x86_64 und arm64 automatisch, wenn das Projekt in
  einem GitHub-Repository liegt (Actions › AppImages › Run workflow, oder bei einem Tag ``v*``).


Fehlersuche
======================================================================

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Problem
     - Mögliche Ursache und Abhilfe
   * - „Verbindung fehlgeschlagen“ / LED rot
     - Verbindungsparameter (**…** in der Steuerungstabelle) und Netzwerk der
       betroffenen Steuerung prüfen, Firewall (``s7``/``tia`` TCP 102, ``clx``
       TCP 44818, ``modbus`` TCP 502). Die übrigen Steuerungen laufen unabhängig
       weiter.
   * - „Bibliothek fehlt“ im Einstellungsdialog bzw. unter *Installierte Treiber*
     - Bibliothek des Treibers installieren: ``pip install python-snap7``
       (``s7``), ``pip install s7commplus`` (``tia``), ``pip install pycomm3``
       und ``plctag.dll`` (``clx``).
   * - Treiber fehlt in der Auswahl / „(Treiber fehlt)“
     - Eigener Treiber nicht geladen: **Treiber › Installierte Treiber …** zeigt
       die Fehlermeldung. Dateiname darf nicht mit ``_`` beginnen; Datei liegt
       im richtigen Ordner? Steuerungen mit fehlendem Treiber bleiben in der
       Konfiguration erhalten, werden aber nicht gelesen.
   * - ``s7``: „Address out of range“ / Werte falsch
     - DB zu kurz oder **optimierter** Baustein (Offsets stimmen nicht) – Baustein
       ohne „Optimierten Bausteinzugriff“ anlegen oder Treiber ``tia`` verwenden.
       Bei S7-1200/1500 PUT/GET erlauben.
   * - ``tia``: Verbindung abgelehnt
     - TLS-Einstellung (*An* bzw. *Aus* probieren), Passwort der Zugriffsstufe,
       Zahl freier HMI-Verbindungen der CPU.
   * - ``clx``: „libplctag wurde nicht gefunden“
     - ``plctag.dll`` (64 Bit) neben die Programmdateien legen bzw. Pfad in
       ``CLX_PLCTAG_LIB`` angeben. 32-Bit-Python kann die 64-Bit-DLL nicht laden.
   * - ``clx``: „PLCTAG_ERR_NOT_FOUND“ bzw. „…BAD_PARAM“
     - Den Tag gibt es nicht (Schreibweise, Präfix ``Program:Name.``) oder
       *External Access* ist *None*. Nur dieser Tag bleibt ohne Wert.
   * - ``modbus``: „ungültige Adresse“ (Ausnahme 2)
     - Register im Gerät nicht vorhanden. Zählweise prüfen (``40001`` = ``HR0``;
       „Register 100“ im Handbuch ist oft ``HR100``). Einzelne Lücken in einem
       zusammengefassten Bereich: *Lücke zusammenfassen bis* auf ``0`` stellen.
   * - ``modbus``: Werte unsinnig groß/klein
     - Byte-/Wortfolge falsch (meist ``CDAB`` statt ``ABCD``) oder falscher Typ
       (``REAL`` statt ``DINT``). Mit **Verbindung testen** die Einstellungen
       durchprobieren.
   * - Auswahldialog lässt sich nicht laden
     - Bibliothek des Treibers fehlt (siehe oben), Verbindung prüfen. ``clx``: bei
       sehr großen Projekten *Programm-Tags* abschalten. ``s7``: DB-Quellen
       müssen am gespeicherten Pfad liegen.
   * - LED „Datenbank“ rot
     - Server, Port, Datenbankname und Zugangsdaten mit **Datenbank testen** prüfen.
       Die Datenbank muss existieren (``CREATE DATABASE datenlogger;``), der Benutzer
       braucht CREATE- und INSERT-Rechte. „Treiber fehlt“: ``pip install PyMySQL`` bzw.
       ``pip install "psycopg[binary]"``. Die Werte werden bis zur Verbindung gepuffert.
   * - Webseite nicht erreichbar
     - Webserver in der Konfiguration eingeschaltet? Port von der Firewall frei?
       Host ``0.0.0.0`` (nicht ``127.0.0.1``) für Zugriffe von anderen Geräten.
       Mit Zugriffscode: ``/?token=CODE`` anhängen.
   * - Logger startet ohne Fenster
     - In der Konfiguration ist *Headless-Modus* aktiv. Mit ``--gui`` starten oder
       die Option abschalten.
   * - Werte sind offensichtlich falsch
     - Der eingestellte Typ passt nicht zur Variable (z. B. ``INT`` statt
       ``REAL``). Mit **Verbindung testen** gegenprüfen oder die Variable aus dem
       Auswahldialog übernehmen (Typ kommt dann aus der Steuerung).
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
       bleibt im CSV-Ordner erhalten.
   * - Block lässt sich nicht lesen
     - Der Bereich (Start + Anzahl) ist in der Steuerung nicht vollständig
       vorhanden, oder das Format passt nicht. Größe, Index und Format prüfen.
   * - Berechnete Variable zeigt keine Werte
     - Formel prüfen (Editor: **Prüfen / Berechnen**). Nicht berechenbare Werte
       ergeben Lücken. Beim Start meldet der Logger Formelfehler.
   * - Logo oder Icon erscheint nicht
     - Pfad in der Konfiguration prüfen (relative Pfade gelten vom
       Programmordner). Ersatzweise PNG statt SVG verwenden.
   * - Installierte Version findet die Konfiguration nicht
     - Die Daten liegen unter ``%APPDATA%\\PLCDatenlogger`` (nicht im Programmordner).
       Mit ``portable.txt`` neben der ``.exe`` wird der Programmordner verwendet.
   * - Einzelprogramm kann die Datei nicht mehr lesen
     - Nach dem Speichern im PLC Datenlogger hat die Datei das neue Format (siehe
       :ref:`uebernahme`). Alte Datei vorher mit **Speichern unter…** sichern.
   * - Keine Millisekunden in Excel
     - Zellformat anpassen (siehe Hinweis im Abschnitt *CSV-Dateien*).


Bekannte Einschränkungen
======================================================================

* Ein Block gehört zu genau einer Steuerung; Formeln können aber Variablen
  verschiedener Steuerungen (auch verschiedener Treiber) verknüpfen – es zählt
  der jeweils letzte Wert. Die Messzeitpunkte der Steuerungen sind nicht synchron.
* Nur lesender Zugriff; der Logger schreibt nichts in die Steuerungen.
* Modbus: nur Modbus **TCP**; Modbus RTU (seriell) nur über ein TCP-Gateway.
* ``s7``: nur nicht optimierte Bausteine; Namen nur über DB-Quellen.
* ``tia``: inoffizielle Bibliothek; Funktion hängt von Firmware und
  Schutzeinstellungen der CPU ab.
* Aufgezeichnet werden Zahlen und ``BOOL``; Strings und ganze Strukturen nicht
  (deren Glieder aber schon).
* Ein Block hat höchstens 1000 Elemente und genau ein Format. Ist ein Teil des
  Bereichs nicht lesbar, schlägt der gesamte Block fehl.
* Eigene Treiber laufen mit den Rechten des Programms; nur Treiber aus
  vertrauenswürdiger Quelle in den Treiber-Ordner legen.
* Der Webserver ist nur lesend und ohne Verschlüsselung (HTTP).
* Berechnete Variablen kennen nur Werte der aktuellen Messung (außer ``ddt``,
  ``integ`` und ``avg``); beim Laden einer CSV-Datei werden sie aus der Datei
  übernommen.
* Diagramme lassen sich per Drag & Drop nur innerhalb ihrer Seite umordnen.
* Die minimale Abtastzeit hängt von der Kommunikation mit der Steuerung ab; bei
  vielen Variablen kann das eingestellte Intervall nicht eingehalten werden.
* Der Demo-Schalter und die Fensteranordnung werden nicht in der Konfigurationsdatei
  gespeichert.
