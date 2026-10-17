# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""VORLAGE für einen eigenen Treiber des PLC-Datenloggers.

So wird daraus ein Treiber:
  1. Datei kopieren, z. B. nach  <Datenordner>/treiber/meine_sps.py
     (Datenordner: Windows %APPDATA%\\PLCDatenlogger, Linux ~/PLCDatenlogger, portabel: Programmordner;
     Konfigurationsprogramm › Treiber › Ordner für eigene Treiber öffnen). Dateien mit „_“ am Anfang werden NICHT
     geladen.
  2. ``id`` (eindeutig, steht in der Konfigurationsdatei), ``name`` und die Parameter anpassen.
  3. In ``SimReader.connect/read/close`` das Protokoll der Steuerung umsetzen.
  4. Programm neu starten: der Treiber erscheint in der Auswahl „Treiber“ der Steuerungen
     (Ladefehler: Konfigurationsprogramm › Treiber › Installierte Treiber).

Als Beispiel ist dieser Treiber eine kleine **Simulation** („sim“): Adressen ``sinus:<Periode s>``,
``rampe:<Periode s>``, ``rechteck:<Periode s>`` und ``zufall:<Bereich>`` erzeugen Testwerte – unverändert kopiert
läuft er sofort.

Schnittstelle (Einzelheiten in plc_treiber/base.py):
  Driver.params            Verbindungsparameter -> Eingabefelder im Konfigurationsprogramm (Param)
  Driver.types             lesbare Datentypen (aus BOOL, BYTE, WORD, DWORD, LWORD, SINT, INT, DINT, LINT, USINT,
                           UINT, UDINT, ULINT, REAL, LREAL, TIME, LTIME, S5TIME, CHAR, WCHAR)
  Driver.check_address()   formale Prüfung einer Adresse (Text) -> Fehlertext oder ""
  Driver.block_element_address()  Adresse des i-ten Elements eines Blocks (Blocklesemodus)
  Driver.create_reader()   -> Reader mit connect() -> Anzahl lesbarer Variablen, read() -> [float], close()
  Driver.browse()          optional: Auswahldialog (Qt) -> BrowseResult
  Reader.errors            {Adresse: Fehlertext} für einzelne nicht lesbare Variablen
Verbindungsfehler in connect()/read() als Ausnahme melden (z. B. ConnectionError) – der Logger verbindet neu.
"""
import math
import random
import time

from plc_treiber.base import NAN, Driver, Param, Reader

WAVES = ("sinus", "rampe", "rechteck", "zufall")


def parse(address):
    """'sinus:20' -> ('sinus', 20.0)"""
    kind, _sep, arg = (address or "").strip().lower().partition(":")
    if kind not in WAVES:
        raise ValueError(f"Unbekannte Adresse „{address}“ (sinus:<s>, rampe:<s>, rechteck:<s>, zufall:<Bereich>)")
    try:
        value = float(arg) if arg else 10.0
    except ValueError:
        raise ValueError(f"Zahl erwartet in „{address}“") from None
    return kind, max(value, 0.001)


class SimReader(Reader):
    def connect(self):
        # Hier: Verbindung zur Steuerung aufbauen (Socket, Bibliothek …). Bei Fehlern eine Ausnahme auslösen.
        self.t0 = time.time()
        self.items = []
        for v in self.vars:
            try:
                self.items.append(parse(v.address))
            except ValueError as e:
                self.items.append(None)
                self.errors[v.address] = str(e)
        return sum(1 for it in self.items if it)

    def read(self):
        # Hier: alle Variablen lesen (möglichst mit wenigen Anfragen) und als float zurückgeben, NaN = kein Wert.
        el = time.time() - self.t0
        amp = float(self.plc.params.get("amplitude", 100.0))
        out = []
        for it in self.items:
            if it is None:
                out.append(NAN)
                continue
            kind, arg = it
            if kind == "sinus":
                out.append(amp * math.sin(2 * math.pi * el / arg))
            elif kind == "rampe":
                out.append(amp * ((el % arg) / arg))
            elif kind == "rechteck":
                out.append(1.0 if (el % arg) < arg / 2 else 0.0)
            else:
                out.append(random.uniform(0, arg))
        return out

    def close(self):
        # Hier: Verbindung schließen.
        pass


class SimDriver(Driver):
    id = "sim"
    name = "Simulation (Vorlage)"
    description = "Testwerte ohne Steuerung – Beispiel für einen eigenen Treiber"
    params = [
        Param("amplitude", "Amplitude", "float", 100.0, minimum=0, maximum=1e9,
              tip="Größe von Sinus und Rampe"),
    ]
    types = ["BOOL", "INT", "DINT", "REAL", "LREAL"]
    address_hint = "sinus:20 (Periode 20 s), rampe:10, rechteck:4, zufall:50"
    block_hint = "z. B. sinus:10 (Elemente: Perioden 10, 11, 12 … s)"

    def summary(self, plc):
        return f"Simulation, Amplitude {plc.params.get('amplitude', 100)}"

    def check_address(self, address, dtype):
        try:
            parse(address)
        except ValueError as e:
            return str(e)
        return ""

    def block_element_address(self, block, i):
        try:
            kind, arg = parse(block.address)
        except ValueError:
            return block.address
        return f"{kind}:{arg + i:g}"

    def create_reader(self, plc, variables):
        return SimReader(self, plc, variables)


DRIVER = SimDriver()
