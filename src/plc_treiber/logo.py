# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Treiber „logo“: Siemens LOGO! 0BA7 und 0BA8 (LOGO! 8, 8.FS4, 8.3, 8.4) über S7-Kommunikation mit python-snap7.

In LOGO!Soft Comfort unter „Online-Einstellungen“ bzw. „Ethernet-Verbindungen“ eine Server-Verbindung (S7) anlegen
und „Zugriff für HMI/Lesen“ erlauben; die TSAP-Werte müssen zu den Einstellungen hier passen (LOGO! 8 ohne eigene
Verbindung: TSAP LOGO 02.00, TSAP Logger 01.00).

Adressen: Variablenspeicher (VM) direkt oder die LOGO!-Operanden, die der Treiber passend zur Gerätegeneration auf
den VM abbildet:

    V10   VB10   VW12   VD20   V10.3              Variablenspeicher: Byte, Wort, Doppelwort, Bit
    I1 … I24   Q1 … Q20   M1 … M64                Eingänge, Ausgänge, Merker (BOOL)
    NI1   NQ1                                     Netzwerkeingänge/-ausgänge (BOOL)
    AI1 … AI8   AQ1 … AQ8   AM1 … AM64   NAI1     Analogwerte (INT, 16 Bit)

Werte im VM sind wie bei S7 „Big Endian“. Benachbarte Adressen werden zu einer Anfrage zusammengefasst.
"""
import re
import struct

from plc_i18n import tr
from plc_treiber.base import NAN, Driver, Param, Reader

LOGO_TYPES = {"BOOL": (1, None), "BYTE": (1, ">B"), "USINT": (1, ">B"), "SINT": (1, ">b"), "WORD": (2, ">H"),
              "UINT": (2, ">H"), "INT": (2, ">h"), "DWORD": (4, ">I"), "UDINT": (4, ">I"), "DINT": (4, ">i"),
              "REAL": (4, ">f")}
# Abbildung der Operanden auf den VM: Operand -> (VM-Startadresse, Anzahl, Bitoperand?)
VM_MAP = {
    "0BA8": {"I": (1024, 24, True), "AI": (1032, 8, False), "Q": (1064, 20, True), "AQ": (1072, 8, False),
             "M": (1104, 64, True), "AM": (1118, 64, False), "NI": (1246, 64, True), "NAI": (1262, 32, False),
             "NQ": (1390, 64, True), "NAQ": (1406, 16, False)},
    "0BA7": {"I": (923, 24, True), "AI": (926, 8, False), "Q": (942, 16, True), "AQ": (944, 2, False),
             "M": (948, 27, True), "AM": (952, 16, False)},
}
_VM = re.compile(r"^V([BWD]?)(\d+)(?:\.([0-7]))?$")
_OP = re.compile(r"^(NAI|NAQ|NI|NQ|AI|AQ|AM|I|Q|M)(\d+)$")


def vm_address(address, generation="0BA8"):
    """LOGO!-Adresse -> (VM-Byte, Bit oder None, empfohlener Typ). ValueError bei ungültiger Adresse."""
    a = (address or "").strip().upper().replace(" ", "")
    m = _VM.match(a)
    if m:
        size, byte, bit = m.group(1), int(m.group(2)), m.group(3)
        if byte > 1469:
            raise ValueError(tr("VM-Adresse größer als 1469: {0}").format(address))
        if bit is not None:
            if size:
                raise ValueError(tr("Bitadresse ohne B/W/D schreiben, z. B. V10.3: {0}").format(address))
            return byte, int(bit), "BOOL"
        return byte, None, {"": "BYTE", "B": "BYTE", "W": "INT", "D": "DINT"}[size]
    m = _OP.match(a)
    if m:
        op, n = m.group(1), int(m.group(2))
        table = VM_MAP.get(generation, VM_MAP["0BA8"])
        if op not in table:
            raise ValueError(tr("{0} gibt es bei der LOGO! {1} nicht im VM").format(op, generation))
        start, count, is_bit = table[op]
        if not 1 <= n <= count:
            raise ValueError(tr("{0}: Nummer 1 … {1} erwartet").format(address, count))
        if is_bit:
            return start + (n - 1) // 8, (n - 1) % 8, "BOOL"
        return start + 2 * (n - 1), None, "INT"
    raise ValueError(tr("Ungültige LOGO!-Adresse „{0}“ (z. B. VW10, V2.3, I1, Q2, M5, AI1, AM3)").format(address))


def parse_tsap(text):
    """'02.00' oder '0x0200' oder '512' -> Zahl."""
    t = str(text or "").strip()
    m = re.fullmatch(r"([0-9A-Fa-f]{1,2})\.([0-9A-Fa-f]{1,2})", t)
    if m:
        return int(m.group(1), 16) << 8 | int(m.group(2), 16)
    return int(t, 0)


class _Item:
    __slots__ = ("pos", "byte", "bit", "dtype", "address")


class LogoReader(Reader):
    """Liest zusammenhängende VM-Bereiche (db_read auf DB 1) und dekodiert die Variablen daraus."""
    MAX_BYTES = 200
    GAP = 32

    def __init__(self, driver, plc, variables):
        super().__init__(driver, plc, variables)
        self.client = None
        gen = str(plc.params.get("generation", "0BA8"))
        items = []
        for pos, v in enumerate(self.vars):
            try:
                if v.dtype not in LOGO_TYPES:
                    raise ValueError(tr("Typ {0} wird nicht unterstützt").format(v.dtype))
                byte, bit, _t = vm_address(v.address, gen)
                if bit is not None and v.dtype != "BOOL":
                    raise ValueError(tr("Bitadresse nur mit Typ BOOL"))
                if v.dtype == "BOOL" and bit is None:
                    bit = 0
            except ValueError as e:
                self.errors[v.address] = str(e)
                continue
            it = _Item()
            it.pos, it.byte, it.bit, it.dtype, it.address = pos, byte, bit, v.dtype, v.address
            items.append(it)
        self.ranges = []                                  # [[start, end, [items]]]
        for it in sorted(items, key=lambda i: i.byte):
            end = it.byte + LOGO_TYPES[it.dtype][0]
            cur = self.ranges[-1] if self.ranges else None
            if cur and it.byte - cur[1] <= self.GAP and end - cur[0] <= self.MAX_BYTES:
                cur[1] = max(cur[1], end)
                cur[2].append(it)
            else:
                self.ranges.append([it.byte, end, [it]])

    def connect(self):
        self.close()
        from snap7.logo import Logo
        p = self.plc.params
        c = Logo()
        try:
            c.connect(str(p.get("ip", "")), parse_tsap(p.get("tsap_logger", "01.00")), parse_tsap(p.get("tsap_logo", "02.00")))
            if hasattr(c, "get_connected") and not c.get_connected():
                raise ConnectionError(tr("keine Verbindung"))
        except Exception as e:
            try:
                c.disconnect()
            except Exception:
                pass
            raise ConnectionError(f"{p.get('ip', '')}: {e}") from None
        self.client = c
        self.read()
        return max(0, len(self.vars) - len(self.errors))

    def read(self):
        if self.client is None:
            raise ConnectionError(tr("nicht verbunden"))
        out = [NAN] * len(self.vars)
        for start, end, items in self.ranges:
            try:
                raw = bytes(self.client.db_read(1, start, end - start))
            except Exception as e:
                try:
                    alive = bool(self.client.get_connected())
                except Exception:
                    alive = False
                if not alive:
                    raise ConnectionError(str(e)) from None
                for it in items:
                    self.errors[it.address] = str(e)
                continue
            for it in items:
                off = it.byte - start
                try:
                    if it.dtype == "BOOL":
                        out[it.pos] = float((raw[off] >> it.bit) & 1)
                    else:
                        out[it.pos] = float(struct.unpack_from(LOGO_TYPES[it.dtype][1], raw, off)[0])
                    self.errors.pop(it.address, None)
                except (IndexError, struct.error):
                    self.errors[it.address] = tr("Antwort zu kurz")
        return out

    def close(self):
        if self.client is not None:
            try:
                self.client.disconnect()
            except Exception:
                pass
            self.client = None


class LogoDriver(Driver):
    id = "logo"
    name = tr("Siemens LOGO! (0BA7/0BA8)")
    description = tr("LOGO! 7 und 8 über S7-Kommunikation (python-snap7); VM-Adressen oder I/Q/M/AI/AQ/AM")
    params = [
        Param("ip", tr("IP-Adresse"), "text", "192.168.0.3"),
        Param("generation", tr("Gerät"), "choice", "0BA8",
              choices=[("0BA8", tr("LOGO! 8 (0BA8, 8.FS4, 8.3, 8.4)")), ("0BA7", tr("LOGO! 7 (0BA7)"))],
              tip=tr("Bestimmt, wo I/Q/M/AI/AQ/AM im Variablenspeicher liegen")),
        Param("tsap_logo", tr("TSAP der LOGO!"), "text", "02.00",
              tip=tr("Wie in LOGO!Soft bei der Server-Verbindung („Lokaler TSAP“), z. B. 02.00 oder 20.00")),
        Param("tsap_logger", tr("TSAP des Loggers"), "text", "01.00",
              tip=tr("Wie in LOGO!Soft bei der Server-Verbindung („Entfernter TSAP“), z. B. 01.00 oder 10.00")),
    ]
    types = list(LOGO_TYPES)
    default_type = "INT"
    address_label = tr("Adresse")
    address_hint = tr("LOGO!: VW10, VD20, V2.3, VB5, I1, Q2, M5, NI1, AI1, AQ1, AM3")
    block_hint = tr("Startadresse im VM, z. B. VW100 (Elemente folgen lückenlos)")
    block_uses_index = False
    library = "python-snap7"

    def summary(self, plc):
        p = plc.params
        return f"{p.get('ip', '')}, LOGO! {p.get('generation', '0BA8')}, TSAP {p.get('tsap_logo', '02.00')}"

    def check_params(self, params):
        err = super().check_params(params)
        if err:
            return err
        for key in ("tsap_logo", "tsap_logger"):
            try:
                v = parse_tsap(params.get(key, ""))
                if not 0 <= v <= 0xFFFF:
                    raise ValueError
            except (TypeError, ValueError):
                return tr("TSAP als hh.hh (z. B. 02.00) oder Zahl angeben")
        return ""

    def check_address(self, address, dtype):
        try:
            _byte, bit, _t = vm_address(address)
        except ValueError as e:
            return str(e)
        if dtype not in LOGO_TYPES:
            return tr("Typ {0} wird nicht unterstützt").format(dtype)
        if bit is not None and dtype != "BOOL":
            return tr("Bitadresse nur mit Typ BOOL")
        return ""

    def normalize_address(self, address, dtype):
        return (address or "").strip().upper().replace(" ", "")

    def block_element_address(self, block, i):
        try:
            byte, bit, _t = vm_address(block.address)
        except ValueError:
            return f"{block.address}+{i}"
        if block.dtype == "BOOL":
            pos = (bit or 0) + i
            return f"V{byte + pos // 8}.{pos % 8}"
        size = LOGO_TYPES.get(block.dtype, (2,))[0]
        prefix = {1: "VB", 2: "VW", 4: "VD"}[size]
        return f"{prefix}{byte + i * size}"

    def check_block(self, block):
        err = self.check_address(block.address, block.dtype)
        return err or super().check_block(block)

    def check_library(self):
        import snap7.logo  # noqa: F401
        return True

    def create_reader(self, plc, variables):
        return LogoReader(self, plc, variables)


DRIVER = LogoDriver()
