"""Treiber „modbus“: Modbus TCP (Wago, Schneider, Beckhoff, Phoenix Contact, Frequenzumrichter, Energiezähler …).

Ohne Zusatzbibliothek (eigene, kleine Umsetzung des Protokolls). Gelesen werden die vier Modbus-Tabellen; benachbarte
Adressen werden automatisch zu möglichst wenigen Anfragen zusammengefasst. Adressen:

    40001 … 49999 (oder 400001 …)   Holding-Register        HR0  … (Zählung ab 0)
    30001 … 39999 (oder 300001 …)   Input-Register          IR0  …
    00001 … 09999 (oder 1 …)        Coils                   C0   …
    10001 … 19999 (oder 100001 …)   Discrete Inputs         DI0  …
    40001.3  bzw.  HR0.3            Bit 3 eines Registers (Typ BOOL)

Typen über mehrere Register (DINT, REAL, LREAL …) belegen 2 bzw. 4 aufeinanderfolgende Register; die Reihenfolge
der Wörter/Bytes stellt der Parameter „Byte-/Wortfolge“ ein (Standard ABCD = Big Endian).
"""
import re
import socket
import struct
import threading

from plc_i18n import tr
from plc_treiber.base import NAN, Driver, Param, Reader

HR, IR, CO, DI = "HR", "IR", "C", "DI"
FUNCTION = {CO: 1, DI: 2, HR: 3, IR: 4}
MODICON = {CO: 0, DI: 1, IR: 3, HR: 4}
REG_TYPES = {  # Typ -> (Anzahl Register, struct-Format für Big Endian)
    "INT": (1, ">h"), "UINT": (1, ">H"), "WORD": (1, ">H"),
    "DINT": (2, ">i"), "UDINT": (2, ">I"), "DWORD": (2, ">I"), "REAL": (2, ">f"),
    "LINT": (4, ">q"), "ULINT": (4, ">Q"), "LWORD": (4, ">Q"), "LREAL": (4, ">d"),
}
EXCEPTIONS = {1: tr("Funktion nicht unterstützt"), 2: tr("ungültige Adresse"), 3: tr("ungültiger Wert"),
              4: tr("Gerätefehler"), 6: tr("Gerät beschäftigt"), 10: tr("Gateway: kein Pfad"), 11: tr("Gateway: Gerät antwortet nicht")}

_RE_PREFIX = re.compile(r"^(HR|IR|C|DI|%MW|%IW)\s*(\d+)(?:\.(\d{1,2}))?$", re.I)
_RE_NUM = re.compile(r"^(\d{1,6})(?:\.(\d{1,2}))?$")


def parse(address: str):
    """'40001' / 'HR0' / '40001.3' -> (Tabelle, Offset ab 0, Bit oder None, modicon: bool)."""
    a = (address or "").strip().upper().replace(" ", "")
    m = _RE_PREFIX.match(a)
    if m:
        table = {"%MW": HR, "%IW": IR}.get(m.group(1), m.group(1))
        return table, int(m.group(2)), (int(m.group(3)) if m.group(3) is not None else None), False
    m = _RE_NUM.match(a)
    if m:
        digits, n = m.group(1), int(m.group(1))
        bit = int(m.group(2)) if m.group(2) is not None else None
        if len(digits) == 6:
            kind, number = int(digits[0]), int(digits[1:])
        elif len(digits) == 5:
            kind, number = int(digits[0]), int(digits[1:])
        else:                                    # 1 … 9999: Coil
            kind, number = 0, n
        table = {0: CO, 1: DI, 3: IR, 4: HR}.get(kind)
        if table is None or number < 1:
            raise ValueError(tr("Ungültige Modbus-Adresse „{0}“").format(address))
        return table, number - 1, bit, True
    raise ValueError(tr("Ungültige Modbus-Adresse „{0}“ (z. B. 40001, 30001, 00001, 10001, HR0, 40001.3)")
                     .format(address))


def fmt(table, offset, bit, modicon) -> str:
    b = f".{bit}" if bit is not None else ""
    if modicon:
        if offset + 1 > 9999:
            return f"{MODICON[table]}{offset + 1:05d}{b}"
        return f"{MODICON[table]}{offset + 1:04d}{b}"
    return f"{table}{offset}{b}"


def reorder(raw: bytes, order: str) -> bytes:
    """Bytes eines Mehrregisterwerts aus der Gerätefolge in Big Endian (ABCD) bringen."""
    if order == "ABCD" or len(raw) < 4:
        if order in ("BADC", "DCBA") and len(raw) == 2:
            return raw[::-1]
        return raw
    words = [raw[i:i + 2] for i in range(0, len(raw), 2)]
    if order == "CDAB":
        words = words[::-1]
    elif order == "BADC":
        words = [w[::-1] for w in words]
    elif order == "DCBA":
        return raw[::-1]
    return b"".join(words)


class ModbusClient:
    """Minimaler Modbus-TCP-Client (Funktionen 1–4)."""

    def __init__(self, host, port=502, unit=1, timeout=2.0):
        self.host, self.port, self.unit, self.timeout = host, int(port), int(unit), timeout
        self.sock = None
        self.tid = 0
        self.lock = threading.Lock()

    def connect(self):
        self.close()
        s = socket.create_connection((self.host, self.port), timeout=self.timeout)
        s.settimeout(self.timeout)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock = s

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def _recv(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError(tr("Verbindung vom Gerät getrennt"))
            buf += chunk
        return buf

    def request(self, fc, start, count):
        """Antwortdaten (Bytes) oder ModbusError bei Ausnahmeantwort; OSError/ConnectionError bei Verbindungsfehlern."""
        if self.sock is None:
            raise ConnectionError(tr("nicht verbunden"))
        with self.lock:
            self.tid = (self.tid + 1) & 0xFFFF
            pdu = struct.pack(">BHH", fc, start, count)
            self.sock.sendall(struct.pack(">HHHB", self.tid, 0, len(pdu) + 1, self.unit) + pdu)
            while True:
                tid, _pid, length, _unit = struct.unpack(">HHHB", self._recv(7))
                body = self._recv(length - 1)
                if tid == self.tid:
                    break                         # verspätete Antworten früherer Anfragen überspringen
        if body[0] & 0x80:
            code = body[1] if len(body) > 1 else 0
            raise ModbusError(tr("Modbus-Ausnahme {0} ({1})").format(code, tr(EXCEPTIONS.get(code, "unbekannt"))))
        return body[2:2 + body[1]]


class ModbusError(Exception):
    pass


class _Item:
    __slots__ = ("pos", "table", "offset", "bit", "dtype", "regs", "address")


class ModbusReader(Reader):
    def __init__(self, driver, plc, variables):
        super().__init__(driver, plc, variables)
        self.client = None
        items = []
        for pos, v in enumerate(self.vars):
            try:
                table, offset, bit, _m = parse(v.address)
                err = driver.check_address(v.address, v.dtype)
                if err:
                    raise ValueError(err)
            except ValueError as e:
                self.errors[v.address] = str(e)
                continue
            it = _Item()
            it.pos, it.table, it.offset, it.bit, it.dtype, it.address = pos, table, offset, bit, v.dtype, v.address
            it.regs = 1 if (table in (CO, DI) or v.dtype == "BOOL") else REG_TYPES[v.dtype][0]
            items.append(it)
        # Anfragen bilden: je Tabelle nach Offset sortiert, zusammenfassen bis Höchstlänge bzw. Lücke
        p = plc.params
        max_regs = int(p.get("max_register", 120))
        gap = int(p.get("luecke", 8))
        self.requests = []          # (Tabelle, Start, Anzahl, [Items])
        for table in (HR, IR, CO, DI):
            group = sorted((i for i in items if i.table == table), key=lambda i: i.offset)
            limit = max_regs if table in (HR, IR) else max_regs * 16
            cur = None
            for it in group:
                end = it.offset + it.regs
                if cur and it.offset - (cur[1] + cur[2]) <= gap and end - cur[1] <= limit:
                    cur[2] = max(cur[2], end - cur[1])
                    cur[3].append(it)
                else:
                    cur = [table, it.offset, it.regs, [it]]
                    self.requests.append(cur)

    # Übertragung (in Unterklassen austauschbar, z. B. Modbus RTU): Objekt mit connect(), close() und
    # request(Funktion, Start, Anzahl) -> Antwortdaten wie im Modbus-Telegramm (Register Big Endian, Bits gepackt).
    def make_client(self):
        p = self.plc.params
        return ModbusClient(p.get("ip"), p.get("port", 502), p.get("unit", 1), int(p.get("timeout_ms", 2000)) / 1000.0)

    def endpoint(self):
        p = self.plc.params
        return f"{p.get('ip')}:{p.get('port', 502)}"

    def connect(self):
        self.close()
        self.client = self.make_client()
        try:
            self.client.connect()
        except (OSError, ConnectionError) as e:
            raise ConnectionError(f"{self.endpoint()}: {e}") from None
        self.read()
        return max(0, len(self.vars) - len(self.errors))

    def read(self):
        out = [NAN] * len(self.vars)
        order = self.plc.params.get("wortfolge", "ABCD")
        for table, start, count, items in self.requests:
            try:
                data = self.client.request(FUNCTION[table], start, count)
            except ModbusError as e:
                for it in items:
                    self.errors[it.address] = str(e)
                continue
            except (OSError, ConnectionError, struct.error, IndexError) as e:
                raise ConnectionError(str(e)) from None
            for it in items:
                self.errors.pop(it.address, None)
                rel = it.offset - start
                if table in (CO, DI):
                    out[it.pos] = float((data[rel // 8] >> (rel % 8)) & 1)
                    continue
                raw = data[rel * 2: (rel + it.regs) * 2]
                if it.dtype == "BOOL":
                    reg = struct.unpack(">H", reorder(raw, order) if order in ("BADC", "DCBA") else raw)[0]
                    out[it.pos] = float((reg >> (it.bit or 0)) & 1)
                else:
                    out[it.pos] = float(struct.unpack(REG_TYPES[it.dtype][1], reorder(raw, order))[0])
        return out

    def close(self):
        if self.client is not None:
            self.client.close()
            self.client = None


class ModbusDriver(Driver):
    id = "modbus"
    name = tr("Modbus TCP")
    description = tr("Holding-/Input-Register, Coils, Discrete Inputs; ohne Zusatzbibliothek")
    params = [
        Param("ip", tr("IP-Adresse"), "text", "192.168.0.10"),
        Param("port", tr("Port"), "int", 502, minimum=1, maximum=65535),
        Param("unit", tr("Geräteadresse (Unit-ID)"), "int", 1, minimum=0, maximum=255,
              tip=tr("Slave-/Unit-ID; bei Gateways die Adresse des Geräts am seriellen Bus")),
        Param("wortfolge", tr("Byte-/Wortfolge"), "choice", "ABCD",
              choices=[("ABCD", tr("ABCD – Big Endian (Standard)")), ("CDAB", tr("CDAB – Wörter getauscht")),
                       ("BADC", tr("BADC – Bytes getauscht")), ("DCBA", tr("DCBA – Little Endian"))],
              tip=tr("Reihenfolge bei Werten über mehrere Register (DINT, REAL …); laut Gerätehandbuch")),
        Param("max_register", tr("Register je Anfrage"), "int", 120, minimum=1, maximum=125, advanced=True),
        Param("luecke", tr("Lücke zusammenfassen bis"), "int", 8, minimum=0, maximum=100, advanced=True,
              suffix=tr(" Register"),
              tip=tr("Adressen mit kleinerem Abstand werden in einer Anfrage gelesen (0 = nur lückenlose)")),
        Param("timeout_ms", tr("Zeitlimit"), "int", 2000, minimum=100, maximum=60000, suffix=" ms", advanced=True),
    ]
    types = ["BOOL", "INT", "UINT", "WORD", "DINT", "UDINT", "DWORD", "REAL", "LINT", "ULINT", "LWORD", "LREAL"]
    address_hint = tr("Modbus-Adresse: 40001 (Holding-Register), 30001 (Input-Register), 00001 (Coil), "
                      "10001 (Discrete Input), 40001.3 (Bit) – oder HR0, IR0, C0, DI0 (ab 0 gezählt)")
    block_hint = tr("Startadresse, z. B. 40001 oder HR0 (Elemente folgen lückenlos)")
    block_uses_index = False

    def summary(self, plc):
        p = plc.params
        return f"{p.get('ip', '')}:{p.get('port', 502)}, Unit {p.get('unit', 1)}"

    def check_address(self, address, dtype):
        try:
            table, _off, bit, _m = parse(address)
        except ValueError as e:
            return str(e)
        if table in (CO, DI):
            if dtype != "BOOL":
                return tr("Coils und Discrete Inputs haben den Typ BOOL")
            if bit is not None:
                return tr("Coils und Discrete Inputs haben keine Bitnummer")
        elif dtype == "BOOL":
            if bit is None or bit > 15:
                return tr("BOOL aus einem Register braucht eine Bitnummer 0–15, z. B. 40001.3")
        elif dtype not in REG_TYPES:
            return tr("Typ {0} wird nicht unterstützt").format(dtype)
        elif bit is not None:
            return tr("Bitnummer nur beim Typ BOOL")
        return ""

    def normalize_address(self, address, dtype):
        try:
            table, off, bit, modicon = parse(address)
        except ValueError:
            return address.strip()
        return fmt(table, off, bit, modicon)

    def block_element_address(self, block, i):
        try:
            table, off, bit, modicon = parse(block.address)
        except ValueError:
            return f"{block.address}+{i}"
        if table in (CO, DI):
            return fmt(table, off + i, None, modicon)
        if block.dtype == "BOOL":
            pos = (bit or 0) + i
            return fmt(table, off + pos // 16, pos % 16, modicon)
        return fmt(table, off + i * REG_TYPES.get(block.dtype, (1,))[0], None, modicon)

    def check_block(self, block):
        err = self.check_address(block.address, block.dtype)
        return err or super().check_block(block)

    def type_size(self, dtype):
        return 2 * REG_TYPES.get(dtype, (1,))[0]

    def create_reader(self, plc, variables):
        return ModbusReader(self, plc, variables)


DRIVER = ModbusDriver()
