# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Ringpuffer in der Steuerung lesen – zyklussynchrone Aufzeichnung ohne Lücken (ohne Oberfläche).

Warum?
------
Beim normalen Lesen fragt der Logger die Steuerung im eingestellten Takt ab. Wann eine Anfrage beantwortet wird,
schwankt mit dem Netzwerk und der Last der Steuerung; einzelne Zyklen gehen verloren, und der Zeitstempel ist die
Ankunftszeit am PC. Für eine **zyklussynchrone** Aufzeichnung schreibt die Steuerung selbst in jedem Zyklus (bzw.
Weckalarm, z. B. alle 10 oder 50 ms) einen Datensatz in einen Ringpuffer. Der Logger holt den Puffer in Ruhe ab
(z. B. alle 250 ms) und macht aus jedem Datensatz eine eigene Messzeile mit dem Zeitpunkt aus der Steuerung.

Aufbau des Puffers in der Steuerung
-----------------------------------
::

    Zaehler      DINT                     Anzahl der bisher geschriebenen Datensätze (1, 2, 3, …)
    Daten[0..N-1]  Datensatz              N = Anzahl Datensätze ("Ringpuffer" im Blockeditor)
        Seq      DINT                     Nummer dieses Datensatzes (= Zaehler beim Schreiben)
        Zeit     DINT                     Zeit in ms: S7-300/400 TIME_TCK, S7-1200/1500 und Logix ms seit Mitternacht
        Werte[0..M-1]  INT/DINT/REAL/…    M = Anzahl Werte ("Anzahl" im Blockeditor)

Datensatz Nummer ``n`` steht in ``Daten[n MOD N]``. Die Steuerung schreibt in dieser Reihenfolge: Werte, Zeit, Seq,
zuletzt Zaehler (Vorlagen im Ordner ``vorlagen``). S7/TIA: Puffer in einem *nicht optimierten* Datenbaustein, die
Adresse im Blockeditor ist die des Zählers (z. B. ``DB100.DBX0.0``); Logix: Tag eines UDT mit den Elementen
``Zaehler`` und ``Daten``.

Ablauf je Abholung (``RingSupport.read_rings``)
------------------------------------------------
1. Zähler lesen (``c1``). Neu sind die Datensätze ``letzter+1 … c1`` – höchstens die letzten N (ältere sind schon
   überschrieben und werden als verloren gemeldet).
2. Diese Datensätze lesen (bei einem Umlauf in zwei Teilen) und den Zähler noch einmal lesen (``c2``).
3. Gültig ist ein Datensatz, wenn sein Feld Seq die erwartete Nummer hat und er während des Lesens nicht
   überschrieben werden konnte (Nummer > ``c2 - N``). Alles andere zählt als verloren.
4. Zeitstempel: Die Zeit aus der Steuerung (ms, mit Überlauf um Mitternacht bzw. bei 2^31/2^32) wird fortlaufend
   gemacht und an die PC-Uhr gehängt: Der neueste Datensatz der ersten Abholung bekommt die aktuelle Zeit, alle
   anderen ihren Abstand dazu. Weicht die Uhr der Steuerung ab, wird der Bezug langsam nachgeführt.

Startet die Steuerung neu (Zähler kleiner als zuvor), beginnt die Zählung von vorn.
"""
import collections
import struct

from plc_i18n import tr

# Datentypen der Werte im Ringpuffer und ihre Größe in Bytes. Bits und Bytes fehlen bewusst: Sie würden die Ausrichtung
# der Datensätze in der Steuerung verschieben (Binärsignale als INT 0/1 ablegen).
RING_TYPES = {"INT": 2, "WORD": 2, "UINT": 2, "DINT": 4, "DWORD": 4, "UDINT": 4, "REAL": 4, "LREAL": 8}
_FMT = {"INT": "h", "WORD": "H", "UINT": "H", "DINT": "i", "DWORD": "I", "UDINT": "I", "REAL": "f", "LREAL": "d"}
HEADER_BYTES = 4                    # Zaehler (DINT) vor dem ersten Datensatz
RECORD_HEAD = 8                     # Seq + Zeit (je DINT) am Anfang jedes Datensatzes
MS_WRAPS = (86_400_000, 2 ** 31, 2 ** 32)   # Überlauf der SPS-Zeit: Mitternacht, TIME_TCK, vorzeichenlos
MAX_STEP_MS = 3_600_000             # größter plausibler Abstand zweier aufeinanderfolgender Datensätze
MAX_RECORDS = 100_000
MAX_COUNTER = 2 ** 31 - 1


class Ring:
    """Ein Ringpuffer einer Steuerung, wie ihn ein Leser abholt.

    ``block``: Blockdefinition (``plc_common.Block`` mit ``ring`` > 0); ``positions``: Positionen der Elemente in der
    Variablenliste des Lesers (nach Element-Index geordnet). ``order``: Byte-Reihenfolge der Steuerung (">" S7, "<"
    Logix). Treiber legen hier ihre Angaben ab (z. B. ``db``/``byte`` bzw. Tag-Handles)."""

    def __init__(self, block, positions, order=">"):
        """Angaben aus der Blockdefinition übernehmen und den Tracker anlegen."""
        self.block = block
        self.name, self.address, self.dtype = block.name, block.address, block.dtype
        self.count, self.records = int(block.count), int(block.ring)
        self.positions = list(positions)
        self.order = order
        self.value_size = RING_TYPES.get(self.dtype, 4)
        self.tracker = RingTracker(self.records)
        self.lost = 0                                  # verlorene Datensätze seit dem Start
        self.error = ""                                # fester Fehler (z. B. ungültige Adresse)

    @property
    def label(self):
        """Schlüssel für Fehlermeldungen (``errors`` des Lesers)."""
        return tr("Ringpuffer {0}").format(self.name)

    @property
    def record_size(self):
        """Größe eines Datensatzes in Bytes (Seq, Zeit, Werte); in S7-Strukturen immer gerade."""
        size = RECORD_HEAD + self.count * self.value_size
        return size + (size & 1)

    def slot_ranges(self, lo, hi):
        """Plätze der Datensätze ``lo … hi`` als zusammenhängende Stücke -> [(erster Platz, Anzahl, erste Nummer)]."""
        out, seq = [], lo
        while seq <= hi:
            slot = seq % self.records
            n = min(hi - seq + 1, self.records - slot)
            out.append((slot, n, seq))
            seq += n
        return out

    def decode(self, raw, n, offset=0):
        """``n`` Datensätze aus den Bytes ``raw`` (ab ``offset``) -> [(Seq, Zeit, [Werte])]."""
        o, rs = self.order, self.record_size
        head = struct.Struct(o + "ii")
        vals = struct.Struct(o + _FMT.get(self.dtype, "f") * self.count)
        out = []
        for k in range(n):
            base = offset + k * rs
            seq, ms = head.unpack_from(raw, base)
            out.append((seq, ms, [float(v) for v in vals.unpack_from(raw, base + RECORD_HEAD)]))
        return out


class RingTracker:
    """Merkt sich, welche Datensätze schon abgeholt sind, erkennt Verluste und rechnet die Zeitstempel.

    Ohne Kommunikation testbar: ``wanted(c1)`` sagt, welche Nummern zu lesen sind, ``accept(...)`` prüft die gelesenen
    Datensätze und liefert [(Zeitstempel, Werte)]."""

    def __init__(self, records):
        """Neuer Tracker für einen Puffer mit ``records`` Plätzen."""
        self.records = max(1, int(records))
        self.reset()

    def reset(self):
        """Zustand löschen (erste Abholung bzw. Neustart der Steuerung)."""
        self.last = None                # zuletzt abgeholte Nummer
        self.prev_ms = None             # SPS-Zeit des zuletzt abgeholten Datensatzes
        self.u = 0.0                    # fortlaufende SPS-Zeit in ms (ohne Überläufe)
        self.t0 = None                  # PC-Zeit (s), die zur fortlaufenden SPS-Zeit u0 gehört
        self.u0 = 0.0
        self.lags = collections.deque(maxlen=40)
        self.restarts = 0

    def wanted(self, counter):
        """Zu lesende Nummern für den Zählerstand ``counter`` -> (lo, hi, übersprungen).

        hi < lo bedeutet: nichts Neues. „übersprungen“ sind Datensätze, die schon überschrieben waren."""
        counter = int(counter)
        if counter <= 0:
            if self.last:                               # Zähler auf 0: Steuerung neu gestartet
                self.reset()
                self.restarts += 1
            return 1, 0, 0
        if self.last is not None and counter < self.last:
            self.reset()                                # Zähler kleiner als zuvor: Neustart der Steuerung
            self.restarts += 1
        lo = 1 if self.last is None else self.last + 1
        first_kept = max(1, counter - self.records + 1)
        skipped = max(0, first_kept - lo) if self.last is not None else 0
        return max(lo, first_kept), counter, skipped

    def accept(self, recs, lo, hi, counter_after, now):
        """Gelesene Datensätze prüfen -> ([(Zeitstempel, Werte)], verloren).

        ``recs``: [(Seq, Zeit, Werte)] für die Nummern lo … hi in dieser Reihenfolge; ``counter_after``: Zähler nach
        dem Lesen; ``now``: PC-Zeit (s) der Abholung."""
        if hi < lo:
            return [], 0
        limit = int(counter_after) - self.records       # Nummern <= limit können beim Lesen überschrieben worden sein
        good, lost = [], 0
        for expected, rec in zip(range(lo, hi + 1), recs):
            seq, ms, values = rec
            if seq != expected or expected <= limit:
                lost += 1
                continue
            good.append((ms, values))
        lost += max(0, (hi - lo + 1) - len(recs))
        self.last = hi
        if not good:
            return [], lost
        stamps = self._stamp([ms for ms, _v in good], now)
        return [(ts, values) for ts, (_ms, values) in zip(stamps, good)], lost

    def _stamp(self, ms_list, now):
        """SPS-Zeiten (ms) -> PC-Zeitstempel (s); siehe Modulbeschreibung."""
        segments = [[]]                                  # neu ausrichten nach unplausiblen Sprüngen
        for ms in ms_list:
            if self.prev_ms is None:
                self.u = 0.0
            else:
                d = ms - self.prev_ms
                if d < 0:                               # Überlauf der SPS-Zeit
                    for m in MS_WRAPS:
                        if 0 <= d + m <= MAX_STEP_MS:
                            d += m
                            break
                    else:
                        d = None
                elif d > MAX_STEP_MS:
                    d = None
                if d is None:                           # Zeit unplausibel (z. B. Uhr verstellt): neu ausrichten
                    self.t0, self.u = None, 0.0
                    if segments[-1]:
                        segments.append([])
                else:
                    self.u += d
            self.prev_ms = ms
            segments[-1].append(self.u)
        out = []
        for k, seg in enumerate(segments):
            if not seg:
                continue
            if self.t0 is None or k > 0:                # Bezug: jüngster Datensatz dieses Stücks = jetzt
                self.t0, self.u0 = now, seg[-1]
            out.extend(self.t0 + (u - self.u0) / 1000.0 for u in seg)
        # Nachführen: Der jüngste Datensatz kann nicht in der Zukunft liegen …
        lag = now - out[-1]
        if lag < 0:
            self.t0 += lag
            out = [t + lag for t in out]
            lag = 0.0
        # … und liegt bei regelmäßiger Abholung meist knapp vor jetzt. Ist der kleinste Abstand der letzten Abholungen
        # deutlich größer, geht die Uhr der Steuerung nach: Bezug vorziehen (wirkt ab der nächsten Abholung).
        self.lags.append(lag)
        if len(self.lags) == self.lags.maxlen and min(self.lags) > 0.25:
            self.t0 += min(self.lags) - 0.05
            self.lags.clear()
        return out


class RingSupport:
    """Mischklasse für Leser mit Ringpuffern. Der Leser ruft ``_setup_rings`` im Konstruktor auf und setzt
    ``_ring_counter`` und ``_ring_bytes`` (bzw. ``_ring_fetch``) um; der Lese-Thread holt mit ``read_rings`` ab."""

    ring_order = ">"                                     # Byte-Reihenfolge der Steuerung

    def _setup_rings(self, variables):
        """Ringpuffer-Elemente der Variablenliste zu Ringen zusammenfassen -> Menge ihrer Positionen."""
        groups = {}
        for pos, v in enumerate(variables):
            blk = getattr(v, "ring", None)
            if blk is not None:
                groups.setdefault(blk.name, (blk, []))[1].append((v.block_idx, pos))
        self.rings = [Ring(blk, [p for _i, p in sorted(items)], self.ring_order) for blk, items in groups.values()]
        self.ring_notes = []                             # Meldungen für den Lese-Thread (z. B. Verluste)
        return {p for r in self.rings for p in r.positions}

    def _ring_is_connection_error(self, exc):
        """True, wenn nach diesem Fehler neu verbunden werden muss (Treiber überschreiben bei Bedarf)."""
        return isinstance(exc, (ConnectionError, TimeoutError))

    def _ring_counter(self, ring):
        """Zählerstand des Puffers lesen (Treiber)."""
        raise NotImplementedError

    def _ring_bytes(self, ring, slot, n):
        """Bytes von ``n`` Datensätzen ab Platz ``slot`` lesen (Treiber mit Byte-Zugriff)."""
        raise NotImplementedError

    def _ring_fetch(self, ring, lo, hi):
        """Datensätze ``lo … hi`` lesen -> [(Seq, Zeit, Werte)] in dieser Reihenfolge."""
        out = []
        for slot, n, _seq in ring.slot_ranges(lo, hi):
            out.extend(ring.decode(self._ring_bytes(ring, slot, n), n))
        return out

    def check_rings(self):
        """Nach dem Verbinden: Zähler jedes Puffers einmal lesen (Fehler stehen danach in ``errors``) -> Anzahl
        lesbarer Puffer. Verbindungsfehler lösen ConnectionError aus."""
        ok = 0
        for ring in getattr(self, "rings", []):
            if ring.error:
                self.errors[ring.label] = ring.error
                continue
            try:
                self._ring_counter(ring)
                self.errors.pop(ring.label, None)
                ok += 1
            except ConnectionError:
                raise
            except Exception as e:
                if self._ring_is_connection_error(e):
                    raise ConnectionError(str(e)) from None
                self.errors[ring.label] = str(e)
        return ok

    def read_rings(self, now=None):
        """Alle Ringpuffer abholen -> [(Positionen, Zeitstempel, Werte)], nach Zeit geordnet je Puffer."""
        import time
        out = []
        for ring in getattr(self, "rings", []):
            if ring.error:
                continue
            try:
                c1 = self._ring_counter(ring)
                lo, hi, skipped = ring.tracker.wanted(c1)
                recs = self._ring_fetch(ring, lo, hi) if hi >= lo else []
                c2 = self._ring_counter(ring) if recs else c1
            except ConnectionError:
                raise
            except Exception as e:
                if self._ring_is_connection_error(e):
                    raise ConnectionError(str(e)) from None
                self.errors[ring.label] = str(e)
                continue
            self.errors.pop(ring.label, None)
            restarts = ring.tracker.restarts
            rows, lost = ring.tracker.accept(recs, lo, hi, c2, time.time() if now is None else now)
            lost += skipped
            if lost:
                ring.lost += lost
                self.ring_notes.append(tr("Ringpuffer {0}: {1} Datensätze verloren (Puffer vergrößern oder Leseintervall "
                                          "verkleinern)").format(ring.name, lost))
            if restarts:
                ring.tracker.restarts = 0
                self.ring_notes.append(tr("Ringpuffer {0}: Zähler zurückgesetzt (Neustart der Steuerung?)").format(ring.name))
            out.extend((ring.positions, ts, vals) for ts, vals in rows)
        return out

    def take_ring_notes(self):
        """Gesammelte Meldungen abholen (und löschen)."""
        notes, self.ring_notes = getattr(self, "ring_notes", []), []
        return notes


def check_ring_block(block, types):
    """Gemeinsame Prüfungen eines Ringpuffers (Größe, Datentyp) -> Fehlertext oder ""."""
    if block.dtype not in types:
        return tr("Format {0} ist im Ringpuffer nicht möglich (erlaubt: {1})").format(block.dtype, ", ".join(types))
    if not 2 <= int(block.ring) <= MAX_RECORDS:
        return tr("Ringpuffer: 2 bis {0} Datensätze").format(MAX_RECORDS)
    return ""
