(* =====================================================================================================================
   PLC Datenlogger – Ringpuffer für zyklussynchrone Aufzeichnung
   ControlLogix / CompactLogix (Studio 5000), Structured Text

   Die Steuerung schreibt bei jedem Durchlauf einen Datensatz (Nummer, Zeit, Werte) in einen Ringpuffer. Der Logger
   holt die Datensätze ab und zeichnet sie lückenlos mit der Zeit aus der Steuerung auf.

   1. Datentypen (Data Types › User-Defined) anlegen – Namen der Elemente genau so:
        PLC_Datensatz   Seq    DINT          Nummer des Datensatzes (= Zaehler beim Schreiben)
                        Zeit   DINT          Zeit in ms seit Mitternacht
                        Werte  REAL[10]      aufgezeichnete Werte ("Anzahl" im Logger)
        PLC_Ringpuffer  Zaehler DINT         Anzahl geschriebener Datensätze
                        Daten  PLC_Datensatz[100]    Datensätze ("Ringpuffer" im Logger)
   2. Controller-Tags anlegen:
        Puffer     PLC_Ringpuffer            der Ringpuffer (dieser Name gehört in den Logger)
        Messwerte  REAL[10]                  die aufzuzeichnenden Werte (vor dem Aufruf füllen)
        rp_n       DINT
        rp_slot    DINT
        rp_dt      DINT[7]
   3. Diese Routine in einer periodischen Task aufrufen (z. B. 10 ms oder 50 ms).

   Einstellungen im Logger (Konfigurationsprogramm › Blöcke): Steuerung mit Treiber "clx",
        Startadresse  Puffer     Format REAL     Anzahl 10     Ringpuffer 100
   Leseintervall der Steuerung z. B. 250 ms. Puffergröße: mindestens 3 × Leseintervall ÷ Zykluszeit
   (Beispiel: 10-ms-Task, 250 ms Leseintervall -> mindestens 75 Datensätze; 100 gewählt).
   Anpassen: Anzahl Werte (10) in PLC_Datensatz, Messwerte und COP; Anzahl Datensätze (100) in PLC_Ringpuffer und MOD.
   Andere Formate: DINT oder INT statt REAL (im Logger dasselbe Format wählen).
   ===================================================================================================================== *)

(* Reihenfolge nicht ändern: erst Werte und Zeit, dann Seq, zuletzt der Zähler. *)
rp_n := Puffer.Zaehler + 1;
IF rp_n >= 2000000000 THEN
    rp_n := 1;                                (* nach Jahren: von vorn zählen (der Logger erkennt das) *)
END_IF;
rp_slot := rp_n MOD 100;                      (* 100 = Anzahl Elemente von Puffer.Daten *)
COP(Messwerte[0], Puffer.Daten[rp_slot].Werte[0], 10);
GSV(WallClockTime, , DateTime, rp_dt[0]);     (* Jahr, Monat, Tag, Stunde, Minute, Sekunde, Mikrosekunden *)
Puffer.Daten[rp_slot].Zeit := ((rp_dt[3] * 60 + rp_dt[4]) * 60 + rp_dt[5]) * 1000 + rp_dt[6] / 1000;
Puffer.Daten[rp_slot].Seq := rp_n;
Puffer.Zaehler := rp_n;
