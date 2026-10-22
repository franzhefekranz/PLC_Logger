# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Treiber „s5as511“: Siemens SIMATIC S5 über die PG-Schnittstelle (AS511, seriell, 20-mA-Linienstrom).

S5-90U … 155U mit PG-Schnittstelle, angeschlossen über einen Pegelwandler (20 mA TTY ⇄ RS-232/USB, z. B. PG-Kabel
6ES5 734-1BD20 oder USB-Adapter). Schnittstelle: 9600 Baud, 8 Datenbits, gerade Parität, 1 Stoppbit.

Adressen in S5-Schreibweise (deutsch oder englisch):

    DB10.DW4    DB10.DL4  DB10.DR4    DB10.DD4    DB10.D4.3      Datenwort, linkes/rechtes Byte, Doppelwort, Bit
    EB0  EW0  ED0  E0.1    (I…)       Eingänge (Prozessabbild)
    AB0  AW0  AD0  A1.0    (Q…)       Ausgänge (Prozessabbild)
    MB10 MW10 MD10 M5.0    (F…)       Merker
    T5   Z3   (C3)                    Timer-/Zählerwort

Typen: BOOL, BYTE, WORD, INT, DWORD, DINT, REAL (= S5-Gleitpunkt „KG“), S5TIME (Timerwort -> Millisekunden).
S5-Daten liegen im Motorola-Format (höherwertiges Byte zuerst); ein Datenwort DWn belegt die Bytes 2n und 2n+1.

Ablauf (wie libnodave): beim Verbinden die Systemdaten (Funktion 18h: Lage von PAE, PAA, Merkern, Timern, Zählern)
lesen, Datenbaustein-Adressen bei Bedarf mit Funktion 1Ah erfragen, dann Speicherbereiche mit Funktion 04h lesen.
Bibliothek: pyserial.
"""
import re
import struct
import threading
import time

from plc_i18n import tr
from plc_treiber.base import NAN, Driver, Param, Reader

STX, ETX, EOT, ACK, DLE, NAK = 0x02, 0x03, 0x04, 0x06, 0x10, 0x15
TYPES = ["BOOL", "BYTE", "WORD", "INT", "DWORD", "DINT", "REAL", "S5TIME"]
SIZE = {"BOOL": 1, "BYTE": 1, "WORD": 2, "INT": 2, "S5TIME": 2, "DWORD": 4, "DINT": 4, "REAL": 4}
_AREA_LETTER = {"E": "E", "I": "E", "A": "A", "Q": "A", "M": "M", "F": "M"}
_RE_DB = re.compile(r"^DB(\d{1,3})\.D([WLRD]?)(\d{1,4})(?:\.(\d{1,2}))?$")
_RE_AREA = re.compile(r"^([EIAQMF])([BWD]?)(\d{1,4})(?:\.([0-7]))?$")
_RE_TZ = re.compile(r"^([TZC])(\d{1,3})$")


def parse(address):
    """-> (Bereich, DB-Nr., Byte-Offset, Bit|None, Größenbuchstabe). Bereich: DB, E, A, M, T, Z."""
    a = (address or "").strip().upper().replace(" ", "")
    m = _RE_DB.match(a)
    if m:
        db, kind, word, bit = int(m.group(1)), m.group(2), int(m.group(3)), m.group(4)
        if db > 255:
            raise ValueError(tr("DB-Nummer 0–255 erwartet: {0}").format(address))
        if bit is not None:                        # DBn.Dw.b: Bit b (0–15) des Datenworts w
            b = int(bit)
            if b > 15 or kind:
                raise ValueError(tr("Bit eines Datenworts: DB10.D4.0 … DB10.D4.15"))
            # Bit 0–7 im rechten Byte (2w+1), 8–15 im linken Byte (2w)
            return "DB", db, 2 * word + (1 if b < 8 else 0), b % 8, "X"
        if kind == "":
            raise ValueError(tr("S5-Datenwort: DB10.DW4, DB10.DL4, DB10.DR4, DB10.DD4 oder DB10.D4.3"))
        off = 2 * word + (1 if kind == "R" else 0)
        return "DB", db, off, None, {"W": "W", "L": "B", "R": "B", "D": "D"}[kind]
    m = _RE_AREA.match(a)
    if m:
        letter, kind, num, bit = _AREA_LETTER[m.group(1)], m.group(2), int(m.group(3)), m.group(4)
        if bit is not None:
            if kind:
                raise ValueError(tr("Bitadresse ohne Größenangabe, z. B. E0.1"))
            return letter, 0, num, int(bit), "X"
        if not kind:
            raise ValueError(tr("Ungültige S5-Adresse „{0}“").format(address))
        return letter, 0, num, None, kind
    m = _RE_TZ.match(a)
    if m:
        letter = "T" if m.group(1) == "T" else "Z"
        return letter, 0, 2 * int(m.group(2)), None, "W"
    raise ValueError(tr("Ungültige S5-Adresse „{0}“ (z. B. DB10.DW4, DB10.D4.3, EW0, A1.0, MW10, T5, Z3)")
                     .format(address))


def kg_to_float(raw):
    """S5-Gleitpunktzahl (KG): Byte 0 Exponent (Zweierkomplement), Bytes 1–3 Mantisse (24 Bit, Zweierkomplement)."""
    exp = struct.unpack("b", raw[0:1])[0]
    mant = int.from_bytes(raw[1:4], "big")
    if mant & 0x800000:
        mant -= 0x1000000
    return mant * 2.0 ** (exp - 23)


def s5time_ms(word):
    """S5-Timerwort: Bits 12/13 Zeitbasis (10 ms, 100 ms, 1 s, 10 s), Bits 0–11 Zeitwert BCD (3 Stellen)."""
    base = (10, 100, 1000, 10000)[(word >> 12) & 3]
    v = ((word >> 8) & 0xF) * 100 + ((word >> 4) & 0xF) * 10 + (word & 0xF)
    return float(v * base)


def decode(raw, dtype, bit=None):
    """Wert eines Datentyps aus den gelesenen Bytes (S5: Big Endian; REAL im S5-Format KG, S5TIME in ms)."""
    if dtype == "BOOL":
        return float((raw[0] >> (bit or 0)) & 1)
    if dtype == "BYTE":
        return float(raw[0])
    if dtype == "WORD":
        return float(struct.unpack(">H", raw[:2])[0])
    if dtype == "INT":
        return float(struct.unpack(">h", raw[:2])[0])
    if dtype == "S5TIME":
        return s5time_ms(struct.unpack(">H", raw[:2])[0])
    if dtype == "DWORD":
        return float(struct.unpack(">I", raw[:4])[0])
    if dtype == "DINT":
        return float(struct.unpack(">i", raw[:4])[0])
    if dtype == "REAL":
        return kg_to_float(raw[:4])
    return NAN


class AS511Error(Exception):
    """Ablauffehler im AS511-Dialog (die Steuerung hat abgewiesen oder nicht wie erwartet geantwortet)."""


class AS511:
    """AS511-Dialog über eine serielle Schnittstelle (pyserial-Objekt mit read/write)."""

    def __init__(self, port, timeout=0.5):
        """Dialog über die geöffnete Schnittstelle ``port`` (pyserial) mit Zeitlimit je Zeichen."""
        self.port = port
        self.timeout = timeout

    def _read(self, n):
        """Genau n Bytes lesen; weniger in der Zeit = Steuerung antwortet nicht."""
        data = self.port.read(n)
        if len(data) < n:
            raise ConnectionError(tr("Keine Antwort von der S5 (Zeitüberschreitung)"))
        return data

    def _expect(self, seq, what):
        """Erwartete Zeichenfolge lesen; DLE NAK oder etwas anderes -> AS511Error."""
        got = self._read(len(seq))
        if got != bytes(seq):
            if got[:2] == bytes([DLE, NAK]):
                raise AS511Error(tr("S5 lehnt ab (DLE NAK) bei {0}").format(what))
            raise AS511Error(tr("Unerwartete Antwort bei {0}: {1}").format(what, got.hex(" ")))

    def _send(self, data):
        """Bytes senden."""
        self.port.write(bytes(data))

    def _send_dup(self, payload):
        """Nutzdaten senden: jedes DLE verdoppeln (Transparenz), am Ende DLE EOT."""
        out = bytearray()
        for b in payload:
            out.append(b)
            if b == DLE:
                out.append(DLE)
        out += bytes([DLE, EOT])
        self._send(out)

    def _receive_block(self):
        """Daten bis DLE ETX lesen, verdoppelte DLE entfernen."""
        data = bytearray()
        deadline = time.monotonic() + max(2.0, self.timeout * 8)
        while True:
            b = self._read(1)[0]
            if b == DLE:
                nxt = self._read(1)[0]
                if nxt == ETX:
                    return bytes(data)
                if nxt == DLE:
                    data.append(DLE)
                    continue
                raise AS511Error(tr("Fehlerhafte DLE-Folge von der S5"))
            data.append(b)
            if time.monotonic() > deadline or len(data) > 4096:
                raise ConnectionError(tr("Antwort der S5 zu lang oder unvollständig"))

    def exchange(self, function, payload, expect_data=True):
        """Ein vollständiger AS511-Auftrag; Rückgabe: Nutzdaten der Antwort (ohne DLE ETX)."""
        try:
            self.port.reset_input_buffer()
        except Exception:
            pass
        # Ablauf eines Auftrags: STX -> DLE ACK, Funktion -> STX, DLE ACK -> 16h DLE ETX (bereit), DLE ACK + Daten ->
        # DLE ACK; dann ggf. Antwortdaten bis DLE ETX und zum Schluss 12h DLE ETX, jeweils mit DLE ACK quittiert.
        self._send([STX])
        self._expect([DLE, ACK], "STX")
        self._send([function])
        self._expect([STX], tr("Funktion {0:02X}h").format(function))
        self._send([DLE, ACK])
        self._expect([0x16, DLE, ETX], tr("Bereitschaft"))
        self._send([DLE, ACK])
        self._send_dup(payload)
        self._expect([DLE, ACK], tr("Auftrag"))
        data = b""
        if expect_data:
            self._expect([STX], tr("Datenbeginn"))
            self._send([DLE, ACK])
            data = self._receive_block()
            self._send([DLE, ACK])
        self._expect([STX], tr("Abschluss"))
        self._send([DLE, ACK])
        self._expect([0x12, DLE, ETX], tr("Abschluss"))
        self._send([DLE, ACK])
        return data

    def system_data(self):
        """Funktion 18h: Anfangsadressen von PAE, PAA, Merkern, Timern, Zählern (Motorola-Format)."""
        d = self.exchange(0x18, b"")
        if len(d) < 17:
            raise AS511Error(tr("Systemdaten zu kurz ({0} Bytes)").format(len(d)))
        return {"E": struct.unpack_from(">H", d, 5)[0], "A": struct.unpack_from(">H", d, 7)[0],
                "M": struct.unpack_from(">H", d, 9)[0], "T": struct.unpack_from(">H", d, 11)[0],
                "Z": struct.unpack_from(">H", d, 13)[0]}

    def db_address(self, db):
        """Funktion 1Ah: (Adresse von DW0, Länge in Bytes) eines Datenbausteins."""
        try:
            d = self.exchange(0x1A, bytes([0x01, db]))
        except AS511Error:
            time.sleep(0.5)                      # nach Abweisung 500 ms Pause (AS511)
            raise AS511Error(tr("DB{0} nicht vorhanden").format(db)) from None
        if len(d) < 13 or d[0] != 0 or d[3] != 0x70 or d[4] != 0x70 or d[5] != 0x41 or d[6] != db:
            raise AS511Error(tr("DB{0} nicht vorhanden").format(db))
        addr = struct.unpack_from(">H", d, 1)[0]
        length = (struct.unpack_from(">H", d, 11)[0] - 5) * 2
        return addr, max(0, length)

    def read_memory(self, start, count):
        """Funktion 04h: Bytes start … start+count-1 aus dem S5-Speicher lesen."""
        end = start + count - 1
        d = self.exchange(0x04, struct.pack(">HH", start & 0xFFFF, end & 0xFFFF))
        if len(d) < 5 + count or d[:5] != b"\x00" * 5:
            raise AS511Error(tr("Fehlerhafte Speicherdaten der S5"))
        return d[5:5 + count]


# Eine serielle Schnittstelle gehört genau einer Steuerung; Sperre gegen gleichzeitige Nutzung durch Testlesen u. Ä.
_PORT_LOCKS = {}
_PORT_LOCKS_LOCK = threading.Lock()


def _port_lock(name):
    """Sperre für eine Schnittstelle (eine Schnittstelle, ein Dialog zur Zeit)."""
    with _PORT_LOCKS_LOCK:
        return _PORT_LOCKS.setdefault(name, threading.Lock())


class _Item:
    """Eine zu lesende Variable: Position, Bereich, DB, Byte-Offset, Bit, Typ, Größe, Adresse."""
    __slots__ = ("pos", "area", "db", "off", "bit", "dtype", "size", "address")


class S5Reader(Reader):
    """Leser für die S5 über AS511: Speicherbereiche werden nach dem Verbinden in absolute Adressen umgerechnet und
    benachbarte zusammengefasst.
    """
    def __init__(self, driver, plc, variables):
        """Adressen prüfen und zerlegen; die absoluten Speicheradressen sind erst nach dem Verbinden bekannt
        (Systemdaten, DB-Adressen).
        """
        super().__init__(driver, plc, variables)
        self.serial = None
        self.as511 = None
        self.bases = {}
        self.dbs = {}
        self.items = []
        for pos, v in enumerate(self.vars):
            err = driver.check_address(v.address, v.dtype)
            if err:
                self.errors[v.address] = err
                continue
            area, db, off, bit, _k = parse(v.address)
            it = _Item()
            it.pos, it.area, it.db, it.off, it.bit, it.dtype, it.address = pos, area, db, off, bit, v.dtype, v.address
            it.size = SIZE[v.dtype]
            self.items.append(it)
        self.max_bytes = max(2, int(plc.params.get("max_bytes", 64)))
        self.gap = max(0, int(plc.params.get("luecke", 8)))

    def _requests(self):
        """Absolute Speicherbereiche bilden (erst nach dem Verbinden bekannt)."""
        reqs = []
        keyed = []
        for it in self.items:
            if it.area == "DB":
                info = self.dbs.get(it.db)
                if info is None:
                    try:
                        info = self.as511.db_address(it.db)
                    except AS511Error as e:
                        info = (None, str(e))
                    self.dbs[it.db] = info
                if info[0] is None:
                    self.errors[it.address] = info[1]
                    continue
                if it.off + it.size > info[1]:
                    self.errors[it.address] = tr("Adresse außerhalb von DB{0} ({1} Bytes)").format(it.db, info[1])
                    continue
                keyed.append((info[0] + it.off, it))
            else:
                keyed.append((self.bases[it.area] + it.off, it))
        cur = None
        for addr, it in sorted(keyed, key=lambda k: k[0]):
            end = addr + it.size
            if cur and addr - cur[1] <= self.gap and end - cur[0] <= self.max_bytes:
                cur[1] = max(cur[1], end)
                cur[2].append((addr, it))
            else:
                cur = [addr, end, [(addr, it)]]
                reqs.append(cur)
        return reqs

    def connect(self):
        """Schnittstelle öffnen (9600 Baud, 8E1), Systemdaten lesen (Anfangsadressen von E/A/M/T/Z), Leseplan bilden,
        einmal lesen.
        """
        self.close()
        import serial
        p = self.plc.params
        port = str(p.get("schnittstelle", "")).strip()
        try:
            self.serial = serial.Serial(port, baudrate=int(p.get("baud", 9600)), bytesize=8,
                                        parity={"E": serial.PARITY_EVEN, "N": serial.PARITY_NONE,
                                                "O": serial.PARITY_ODD}[str(p.get("paritaet", "E"))],
                                        stopbits=1, timeout=int(p.get("timeout_ms", 500)) / 1000.0)
        except Exception as e:
            raise ConnectionError(tr("{0}: Schnittstelle lässt sich nicht öffnen: {1}").format(port, e)) from None
        self.lock = _port_lock(port)
        self.as511 = AS511(self.serial, int(p.get("timeout_ms", 500)) / 1000.0)
        try:
            with self.lock:
                self.bases = self.as511.system_data()
                self.dbs = {}
                self.plan = self._requests()
        except (AS511Error, OSError) as e:
            self.close()
            raise ConnectionError(f"{port}: {e}") from None
        self.read()
        return max(0, len(self.vars) - len(self.errors))

    def read(self):
        """Ein Messzyklus: jeden Speicherbereich mit Funktion 04h lesen; nach einer Abweisung 500 ms Pause
        (AS511-Vorgabe).
        """
        if self.as511 is None:
            raise ConnectionError(tr("nicht verbunden"))
        out = [NAN] * len(self.vars)
        for start, end, entries in self.plan:
            try:
                with self.lock:
                    raw = self.as511.read_memory(start, end - start)
            except AS511Error as e:
                for _a, it in entries:
                    self.errors[it.address] = str(e)
                time.sleep(0.5)                  # nach Abweisung 500 ms Pause (AS511)
                continue
            except OSError as e:
                raise ConnectionError(str(e)) from None
            for addr, it in entries:
                out[it.pos] = decode(raw[addr - start: addr - start + it.size], it.dtype, it.bit)
                self.errors.pop(it.address, None)
        return out

    def close(self):
        """Schnittstelle schließen."""
        if self.serial is not None:
            try:
                self.serial.close()
            except Exception:
                pass
        self.serial = None
        self.as511 = None


class S5Driver(Driver):
    """Treiber „s5as511“ (siehe Modulbeschreibung)."""
    id = "s5as511"
    name = tr("Siemens S5 (PG-Schnittstelle AS511)")
    description = tr("S5-90U … 155U über die PG-Schnittstelle (20 mA) mit Pegelwandler an RS-232/USB")
    params = [
        Param("schnittstelle", tr("Schnittstelle"), "text", "COM1",
              tip=tr("Schnittstelle des PG-Adapters, z. B. COM1 oder /dev/ttyUSB0")),
        Param("baud", tr("Baudrate"), "choice", "9600", choices=[("9600", "9600"), ("19200", "19200")],
              tip=tr("AS511: 9600 Baud")),
        Param("paritaet", tr("Parität"), "choice", "E",
              choices=[("E", tr("gerade (Even)")), ("N", tr("keine (None)")), ("O", tr("ungerade (Odd)"))],
              advanced=True, tip=tr("AS511: gerade Parität")),
        Param("max_bytes", tr("Bytes je Anfrage"), "int", 64, minimum=2, maximum=240, advanced=True),
        Param("luecke", tr("Lücke zusammenfassen bis"), "int", 8, minimum=0, maximum=200, advanced=True,
              suffix=tr(" Bytes")),
        Param("timeout_ms", tr("Zeitlimit"), "int", 500, minimum=100, maximum=10000, suffix=" ms", advanced=True,
              tip=tr("AS511: 500 ms")),
    ]
    types = TYPES
    address_label = tr("Adresse")
    address_hint = tr("S5-Adresse: DB10.DW4, DB10.DL4/DR4, DB10.DD4, DB10.D4.3; EW0, E0.1, AB1, A1.0, MW10, "
                      "M5.0, T5, Z3")
    block_hint = tr("Startadresse, z. B. DB10.DW0 oder MW100 (Elemente folgen lückenlos)")
    block_uses_index = False
    library = "pyserial"

    def summary(self, plc):
        """„COM1 9600 8E1“."""
        p = plc.params
        return f"{p.get('schnittstelle', '')} {p.get('baud', 9600)} 8{p.get('paritaet', 'E')}1"

    def check_params(self, params):
        """Schnittstelle muss angegeben sein."""
        return "" if str(params.get("schnittstelle", "")).strip() else tr("Schnittstelle fehlt")

    def check_address(self, address, dtype):
        """Adresse gültig und Typ zur Größe passend (Bit = BOOL, Byte = BYTE, Wort = WORD/INT/S5TIME, Doppelwort =
        DWORD/DINT/REAL)?
        """
        try:
            area, _db, _off, bit, kind = parse(address)
        except ValueError as e:
            return str(e)
        if dtype not in TYPES:
            return tr("Typ {0} wird nicht unterstützt").format(dtype)
        if (kind == "X") != (dtype == "BOOL"):
            return tr("Bitadressen (E0.1, DB10.D4.3) haben den Typ BOOL – und nur sie")
        if kind == "B" and SIZE[dtype] != 1:
            return tr("Byteadresse: Typ BYTE")
        if kind == "W" and SIZE[dtype] != 2:
            return tr("Wortadresse: Typ WORD, INT oder S5TIME")
        if kind == "D" and SIZE[dtype] != 4:
            return tr("Doppelwortadresse: Typ DWORD, DINT oder REAL")
        if area in ("T", "Z") and dtype not in ("WORD", "INT", "S5TIME"):
            return tr("Timer/Zähler: Typ WORD oder S5TIME")
        return ""

    def block_element_address(self, block, i):
        """Adresse des i-ten Elements: DB in Datenwörtern (DL/DR für Bytes), Timer/Zähler fortlaufend, Bits über
        Bytegrenzen.
        """
        try:
            area, db, off, bit, kind = parse(block.address)
        except ValueError:
            return f"{block.address}+{i}"
        size = SIZE.get(block.dtype, 2)
        if area == "DB":
            if size == 1 and kind != "X":
                b = off + i
                return f"DB{db}.D{'L' if b % 2 == 0 else 'R'}{b // 2}"
            w = off // 2 + i * (size // 2)
            return f"DB{db}.D{'D' if size == 4 else 'W'}{w}"
        if area in ("T", "Z"):
            return f"{area}{off // 2 + i}"
        if kind == "X":
            pos = bit + i
            return f"{area}{off + pos // 8}.{pos % 8}"
        return f"{area}{ {1: 'B', 2: 'W', 4: 'D'}[size]}{off + i * size}"

    def check_block(self, block):
        """Wie eine Einzelvariable; Bit-Blöcke nur bei E, A und M."""
        err = self.check_address(block.address, block.dtype)
        if not err and block.dtype == "BOOL" and block.address.strip().upper().startswith("DB"):
            err = tr("Bit-Blöcke nur bei E, A und M (DB-Bits einzeln anlegen)")
        return err or super().check_block(block)

    def check_library(self):
        """pyserial vorhanden?"""
        import serial  # noqa: F401
        return True

    def create_reader(self, plc, variables):
        """Leser für eine S5 (siehe S5Reader)."""
        return S5Reader(self, plc, variables)


DRIVER = S5Driver()
