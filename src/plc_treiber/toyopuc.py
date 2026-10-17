# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Treiber „toyopuc“: JTEKT TOYOPUC (PC10G, PC10, PC3J/PC3JG, Nano 10GX, TOYOPUC-Plus) über Computer Link per Ethernet.

In der Steuerung (PCwin) am Ethernet-Modul bzw. der eingebauten Schnittstelle einen Port für „Computer Link“
(TCP, passiv) einrichten. Adressen sind hexadezimal wie in PCwin:

    D0100   R0010   S0020   N0005   B0000              Register (Wort)          D0100.F   Bit F eines Registers
    M0010   X0007   Y0020   K0001   L0100   V0000      Relais (Bit, Typ BOOL)    M010W     16 Relais als Wort
    T0005   C0003   P0000                              Timer-/Zähler-Kontakte, Flanken (Bit)
    U00100  EN0010  H0000  ES0000  EB00000             erweiterte Register
    EM0010  EX0007  EY0007  EK0000  EV0000  EL0000  ET0000  EC0000  EP0000  GX0000  GY0000  GM0000   erweiterte Relais
    P1-D0100   P2-M0010   P3-R0000                     Programmbereiche 1–3 (PC3J im 3-Programm-Modus, PC10)

DINT/REAL/LREAL belegen 2 bzw. 4 Wörter, niederwertiges Wort zuerst. Wortadressen der Bereiche nach dem
JTEKT-Handbuch „Computer Link“ (Befehl 1C: Grundbereich, Befehl 94: erweiterter Bereich/Programmbereich).
"""
import re
import socket
import struct
import threading

from plc_i18n import N_, tr
from plc_treiber.base import Driver, Param
from plc_treiber.word_common import TYPES, WORD_TYPES, DeviceError, WordReader, recv_exact

# Grundbereich (Befehl 1C): Wortadresse = Basis + Nummer (Register) bzw. Basis + Nummer // 16 (Relais)
BASIC_WORD = {"S": (0x0200, 0x03FF), "N": (0x0600, 0x01FF), "R": (0x0800, 0x07FF), "D": (0x1000, 0x2FFF),
              "B": (0x6000, 0x1FFF)}
BASIC_BIT = {"P": (0x0000, 0x01FF), "K": (0x0020, 0x02FF), "V": (0x0050, 0x00FF), "T": (0x0060, 0x01FF),
             "C": (0x0060, 0x01FF), "L": (0x0080, 0x07FF), "X": (0x0100, 0x07FF), "Y": (0x0100, 0x07FF),
             "M": (0x0180, 0x07FF)}
# Erweiterter Bereich (Befehl 94): (Nr., Wortbasis, höchste Nummer)
EXT_BIT = {"EP": (0x00, 0x0000, 0x0FFF), "EK": (0x00, 0x0100, 0x0FFF), "EV": (0x00, 0x0200, 0x0FFF),
           "ET": (0x00, 0x0300, 0x07FF), "EC": (0x00, 0x0300, 0x07FF), "EL": (0x00, 0x0380, 0x1FFF),
           "EX": (0x00, 0x0580, 0x07FF), "EY": (0x00, 0x0580, 0x07FF), "EM": (0x00, 0x0600, 0x1FFF),
           "GX": (0x07, 0x0000, 0xFFFF), "GY": (0x07, 0x0000, 0xFFFF), "GM": (0x07, 0x1000, 0xFFFF)}
EXT_WORD = {"ES": (0x00, 0x0800, 0x07FF), "EN": (0x00, 0x1000, 0x07FF), "H": (0x00, 0x1800, 0x07FF),
            "U": (0x08, 0x0000, 0x7FFF)}
# Programmbereiche P1-/P2-/P3- (Befehl 94, Nr. 0D/0E/0F): Segmente (erste Nr., letzte Nr., Wortbasis)
PROGRAM_NO = {"P1": 0x0D, "P2": 0x0E, "P3": 0x0F}
PROGRAM_WORD = {"S": [(0x0000, 0x03FF, 0x0200), (0x1000, 0x13FF, 0x6400)],
                "N": [(0x0000, 0x01FF, 0x0600), (0x1000, 0x17FF, 0x6800)],
                "R": [(0x0000, 0x07FF, 0x0800)],
                "D": [(0x0000, 0x0FFF, 0x1000), (0x1000, 0x2FFF, 0x2000)]}
PROGRAM_BIT = {"P": [(0x000, 0x1FF, 0x0000), (0x1000, 0x17FF, 0x6000)], "K": [(0x000, 0x2FF, 0x0020)],
               "V": [(0x000, 0x0FF, 0x0050), (0x1000, 0x17FF, 0x6080)],
               "T": [(0x000, 0x1FF, 0x0060), (0x1000, 0x17FF, 0x6100)],
               "C": [(0x000, 0x1FF, 0x0060), (0x1000, 0x17FF, 0x6100)],
               "L": [(0x000, 0x7FF, 0x0080), (0x1000, 0x2FFF, 0x6200)], "X": [(0x000, 0x7FF, 0x0100)],
               "Y": [(0x000, 0x7FF, 0x0100)], "M": [(0x000, 0x7FF, 0x0180), (0x1000, 0x17FF, 0x6180)]}
_AREAS = sorted(set(BASIC_WORD) | set(BASIC_BIT) | set(EXT_BIT) | set(EXT_WORD) | {"EB"}, key=len, reverse=True)
_RE = re.compile(r"^(?:(P[123])-)?(" + "|".join(_AREAS) + r")([0-9A-F]+)(W)?(?:\.([0-9A-F]))?$")
ERRORS = {0x11: N_("CPU-Modul-Fehler"), 0x20: N_("Relaisbefehl: falsche Länge"), 0x21: N_("Befehl nicht unterstützt"),
          0x23: N_("Zugriff verweigert (Schlüssel/Modus)"), 0x24: N_("Programmnummer/Bereich fehlt"),
          0x25: N_("Antwortdaten zu lang"), 0x31: N_("Schreibschutz"), 0x40: N_("Adresse außerhalb des Bereichs"),
          0x41: N_("Anzahl außerhalb des Bereichs"), 0x42: N_("Adresse + Anzahl außerhalb des Bereichs"),
          0x43: N_("Adresse ungerade"), 0x52: N_("Programmnummer ungültig"), 0x66: N_("keine Antwort vom Link-Modul"),
          0x72: N_("keine Antwort vom Link-Modul"), 0x73: N_("Befehl nicht ausführbar")}


def _segment(segments, n):
    for start, end, base in segments:
        if start <= n <= end:
            return base, start
    return None


def parse(address):
    """Adresse -> (Bereich (Befehl, Nr.), Wortadresse, Bit|None, ist_Relais)."""
    a = (address or "").strip().upper().replace(" ", "")
    m = _RE.match(a)
    if not m:
        raise ValueError(tr("Ungültige TOYOPUC-Adresse „{0}“ (z. B. D0100, R0010, M0010, X0007, U00100, P1-D0100)")
                         .format(address))
    prog, area, num, packed, bit = m.groups()
    n = int(num, 16)
    bitno = int(bit, 16) if bit is not None else None
    is_bit_area = area in BASIC_BIT or area in EXT_BIT
    if packed and not is_bit_area:
        raise ValueError(tr("„W“ (Wortzugriff) nur bei Relais: {0}").format(address))
    if bitno is not None and is_bit_area:
        raise ValueError(tr("Relais haben keine Bitnummer: {0}").format(address))
    relay_bit = None
    if is_bit_area and not packed:                       # einzelnes Relais: Wort = Nummer // 16
        relay_bit, n = n % 16, n // 16
    wn = n                                               # Wortnummer innerhalb des Bereichs
    if prog:
        if area in PROGRAM_WORD and not packed:
            seg = _segment(PROGRAM_WORD[area], wn)
            if seg is None:
                raise ValueError(tr("Adresse außerhalb des Bereichs: {0}").format(address))
            return ("94", PROGRAM_NO[prog]), seg[0] + wn - seg[1], bitno, False
        if area in PROGRAM_BIT:
            full = wn * 16
            seg = _segment(PROGRAM_BIT[area], full)
            if seg is None:
                raise ValueError(tr("Adresse außerhalb des Bereichs: {0}").format(address))
            return ("94", PROGRAM_NO[prog]), seg[0] + (full - seg[1]) // 16, relay_bit, relay_bit is not None
        raise ValueError(tr("{0} ist kein Programmbereich (P1-/P2-/P3- nur bei D, R, S, N und Relais)").format(area))
    if area in BASIC_WORD:
        base, last = BASIC_WORD[area]
        if wn > last:
            raise ValueError(tr("Adresse außerhalb des Grundbereichs: {0} (bis {1}{2:04X}; sonst P1-…)")
                             .format(address, area, last))
        return ("1C", 0), base + wn, bitno, False
    if area in BASIC_BIT:
        base, last = BASIC_BIT[area]
        if wn > last // 16:
            raise ValueError(tr("Adresse außerhalb des Grundbereichs: {0} (größere Nummern über P1-…)").format(address))
        return ("1C", 0), base + wn, relay_bit, relay_bit is not None
    if area in EXT_WORD:
        no, base, last = EXT_WORD[area]
        if wn > last:
            raise ValueError(tr("Adresse außerhalb des Bereichs: {0}").format(address))
        return ("94", no), base + wn, bitno, False
    if area in EXT_BIT:
        no, base, last = EXT_BIT[area]
        if wn > last // 16:
            raise ValueError(tr("Adresse außerhalb des Bereichs: {0}").format(address))
        return ("94", no), base + wn, relay_bit, relay_bit is not None
    if area == "EB":
        if wn > 0x1FFFF:
            raise ValueError(tr("Adresse außerhalb des Bereichs: {0}").format(address))
        return ("94", 0x09 + wn // 0x8000), wn % 0x8000, bitno, False
    raise ValueError(tr("Unbekannter Bereich: {0}").format(address))


class ComputerLinkClient:
    def __init__(self, params):
        self.host, self.port = str(params.get("ip", "")), int(params.get("port", 1025))
        self.udp = str(params.get("protokoll", "tcp")) == "udp"
        self.timeout = int(params.get("timeout_ms", 2000)) / 1000.0
        self.sock = None
        self.lock = threading.Lock()

    def connect(self):
        self.close()
        if self.udp:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((self.host, self.port))
        else:
            s = socket.create_connection((self.host, self.port), timeout=self.timeout)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.settimeout(self.timeout)
        self.sock = s

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def exchange(self, cmd, data):
        if self.sock is None:
            raise ConnectionError(tr("nicht verbunden"))
        frame = bytes([0x00, 0x00]) + struct.pack("<H", 1 + len(data)) + bytes([cmd]) + data
        with self.lock:
            if self.udp:
                self.sock.send(frame)
                resp = self.sock.recv(8192)
            else:
                self.sock.sendall(frame)
                head = recv_exact(self.sock, 4)
                resp = head + recv_exact(self.sock, struct.unpack_from("<H", head, 2)[0])
        if len(resp) < 5 or resp[0] != 0x80:
            raise ConnectionError(tr("Ungültige Antwort (TOYOPUC)"))
        if resp[1] != 0x00:
            code = resp[-1] if len(resp) > 5 else resp[4]
            raise DeviceError(tr("TOYOPUC-Fehler 0x{0:02X}: {1}").format(code, tr(ERRORS.get(code, "siehe Handbuch"))))
        return resp[5:]

    def read_words(self, area, addr, count):
        kind, no = area
        if kind == "1C":
            data = self.exchange(0x1C, struct.pack("<HH", addr, count))
        else:
            data = self.exchange(0x94, bytes([no]) + struct.pack("<HH", addr, count))
        if len(data) < 2 * count:
            raise ConnectionError(tr("TOYOPUC-Antwort zu kurz"))
        return list(struct.unpack_from(f"<{count}H", data))


class ToyopucReader(WordReader):
    default_max_words = 512
    default_gap = 16

    def parse(self, address, dtype):
        area, word, bit, relay = parse(address)
        if relay and dtype != "BOOL":
            raise ValueError(tr("Einzelne Relais haben den Typ BOOL (16 Relais als Wort: z. B. M010W)"))
        return area, word, bit

    def area_limit(self, area):
        return min(512, int(self.plc.params.get("max_woerter", 512)))

    def open(self):
        self.client = ComputerLinkClient(self.plc.params)
        self.client.connect()

    def close_transport(self):
        if getattr(self, "client", None) is not None:
            self.client.close()

    def read_words(self, area, start, count):
        return self.client.read_words(area, start, count)


class ToyopucDriver(Driver):
    id = "toyopuc"
    name = tr("JTEKT TOYOPUC (Computer Link)")
    description = tr("PC10G/PC10, PC3J, Nano 10GX, TOYOPUC-Plus über Ethernet (Computer-Link-Protokoll)")
    params = [
        Param("ip", tr("IP-Adresse"), "text", "192.168.0.10"),
        Param("port", tr("Port"), "int", 1025, minimum=1, maximum=65535,
              tip=tr("In PCwin für Computer Link eingestellter Port")),
        Param("protokoll", tr("Protokoll"), "choice", "tcp", choices=[("tcp", "TCP"), ("udp", "UDP")]),
        Param("max_woerter", tr("Wörter je Anfrage"), "int", 512, minimum=1, maximum=512, advanced=True),
        Param("luecke", tr("Lücke zusammenfassen bis"), "int", 16, minimum=0, maximum=500, advanced=True,
              suffix=tr(" Wörter")),
        Param("timeout_ms", tr("Zeitlimit"), "int", 2000, minimum=100, maximum=60000, suffix=" ms", advanced=True),
    ]
    types = TYPES
    address_label = tr("Adresse")
    address_hint = tr("TOYOPUC-Adresse (hex): D0100, R0010, S0020, N0005, U00100; Relais: M0010, X0007, Y0020, "
                      "K0001, L0100; Wort aus Relais: M010W; Bit: D0100.F; Programmbereich: P1-D0100")
    block_hint = tr("Startadresse, z. B. D0100 (Elemente folgen lückenlos)")
    block_uses_index = False

    def summary(self, plc):
        p = plc.params
        return f"{p.get('ip', '')}:{p.get('port', 1025)} {str(p.get('protokoll', 'tcp')).upper()}"

    def check_address(self, address, dtype):
        try:
            _area, _w, bit, relay = parse(address)
        except ValueError as e:
            return str(e)
        if dtype not in TYPES:
            return tr("Typ {0} wird nicht unterstützt").format(dtype)
        if relay and dtype != "BOOL":
            return tr("Einzelne Relais haben den Typ BOOL (16 Relais als Wort: z. B. M010W)")
        if bit is not None and dtype != "BOOL":
            return tr("Bitnummer nur beim Typ BOOL")
        return ""

    def normalize_address(self, address, dtype):
        return (address or "").strip().upper().replace(" ", "")

    def block_element_address(self, block, i):
        a = (block.address or "").strip().upper()
        m = _RE.match(a)
        if not m:
            return f"{block.address}+{i}"
        prog, area, num, packed, bit = m.groups()
        pre = f"{prog}-" if prog else ""
        width = len(num)
        n = int(num, 16)
        if (area in BASIC_BIT or area in EXT_BIT) and not packed:
            return f"{pre}{area}{n + i:0{width}X}"
        if block.dtype == "BOOL" and not packed:
            pos = int(bit or "0", 16) + i
            return f"{pre}{area}{n + pos // 16:0{width}X}.{pos % 16:X}"
        step = WORD_TYPES.get(block.dtype, (1,))[0]
        return f"{pre}{area}{n + i * step:0{width}X}" + ("W" if packed else "")

    def check_block(self, block):
        return self.check_address(block.address, block.dtype) or super().check_block(block)

    def create_reader(self, plc, variables):
        return ToyopucReader(self, plc, variables)


DRIVER = ToyopucDriver()
