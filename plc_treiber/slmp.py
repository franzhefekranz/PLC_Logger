"""Treiber „slmp“: Mitsubishi MELSEC über SLMP (MC-Protokoll, 3E-Rahmen, binär) per Ethernet.

iQ-R, iQ-F (FX5), Q-Serie (QnU, QnUDE …) und L-Serie mit eingebautem Ethernet oder Ethernet-Modul. In der Steuerung
(GX Works) eine SLMP-Verbindung (bzw. „MC-Protokoll“, binär, TCP oder UDP) mit Port einrichten; „Schreiben im
RUN“ ist nicht nötig, der Logger liest nur.

Adressen in MELSEC-Schreibweise; X, Y, B, W, SB, SW sind hexadezimal, alle übrigen dezimal:

    D100   W1A   R200   ZR1000   SD10   TN5 (Timer-Istwert)   CN3 (Zähler-Istwert)   Z0     Wortgeräte
    M10    X1F   Y20    B3       L5    F0    SM400   TS5   CS3                                  Bitgeräte (Typ BOOL)
    D100.3                                                                                       Bit 3 eines Wortes

DINT/REAL/LREAL belegen 2 bzw. 4 aufeinanderfolgende Wörter (niederwertiges Wort zuerst, wie in GX Works).
Bitgeräte werden wortweise (16 Bits je Wort) mitgelesen; benachbarte Adressen ergeben eine Anfrage.
"""
import re
import socket
import struct
import threading

from plc_i18n import N_, tr
from plc_treiber.base import Driver, Param
from plc_treiber.word_common import TYPES, DeviceError, WordReader, recv_exact

# Gerät -> (Gerätecode, Zahlenbasis, Bitgerät)   (Quelle: SLMP-Handbuch SH080956, binärer Gerätecode)
DEVICES = {
    "SM": (0x91, 10, True), "SD": (0xA9, 10, False), "X": (0x9C, 16, True), "Y": (0x9D, 16, True),
    "M": (0x90, 10, True), "L": (0x92, 10, True), "F": (0x93, 10, True), "V": (0x94, 10, True),
    "B": (0xA0, 16, True), "D": (0xA8, 10, False), "W": (0xB4, 16, False),
    "TS": (0xC1, 10, True), "TC": (0xC0, 10, True), "TN": (0xC2, 10, False),
    "SS": (0xC7, 10, True), "SC": (0xC6, 10, True), "SN": (0xC8, 10, False),
    "CS": (0xC4, 10, True), "CC": (0xC3, 10, True), "CN": (0xC5, 10, False),
    "SB": (0xA1, 16, True), "SW": (0xB5, 16, False), "DX": (0xA2, 16, True), "DY": (0xA3, 16, True),
    "Z": (0xCC, 10, False), "R": (0xAF, 10, False), "ZR": (0xB0, 10, False),
}
_NAMES = sorted(DEVICES, key=len, reverse=True)
_RE = re.compile(r"^(" + "|".join(_NAMES) + r")([0-9A-F]+)(?:\.([0-9A-F]))?$")
END_CODES = {
    0xC050: N_("ASCII-Daten nicht wandelbar"), 0xC051: N_("Anzahl Punkte zu groß"), 0xC052: N_("Anzahl Punkte zu groß"),
    0xC053: N_("Anzahl Punkte zu groß"), 0xC054: N_("Anzahl Punkte zu groß"), 0xC056: N_("Adresse außerhalb des Bereichs"),
    0xC058: N_("Datenlänge passt nicht"), 0xC059: N_("Befehl/Unterbefehl nicht unterstützt (Serie Q/L bzw. iQ-R prüfen?)"),
    0xC05B: N_("Gerät nicht lesbar"), 0xC05C: N_("Anfrage fehlerhaft (Gerät/Adresse)"), 0xC061: N_("Anfragelänge passt nicht"),
    0x4031: N_("Gerät/Adresse außerhalb des Bereichs"), 0x4030: N_("Gerät existiert nicht"),
}


def parse(address):
    """'D100' -> ('D', 100, None); 'X1F' -> ('X', 31, None); 'D100.3' -> ('D', 100, 3)."""
    a = (address or "").strip().upper().replace(" ", "")
    m = _RE.match(a)
    if not m:
        raise ValueError(tr("Ungültige MELSEC-Adresse „{0}“ (z. B. D100, M10, X1F, W1A, ZR1000, D100.3)").format(address))
    dev, num, bit = m.group(1), m.group(2), m.group(3)
    code, radix, is_bit = DEVICES[dev]
    try:
        n = int(num, radix)
    except ValueError:
        raise ValueError(tr("„{0}“: {1} wird {2} gezählt").format(address, dev,
                                                                tr("dezimal") if radix == 10 else tr("hexadezimal"))) from None
    if bit is not None and is_bit:
        raise ValueError(tr("Bitgeräte haben keine Bitnummer: {0}").format(address))
    return dev, n, (int(bit, 16) if bit is not None else None)


class SlmpClient:
    """SLMP-Client, 3E-Rahmen binär, Befehl 0401 (Lesen, Worteinheiten)."""

    def __init__(self, params):
        p = params
        self.host, self.port = str(p.get("ip", "")), int(p.get("port", 5007))
        self.udp = str(p.get("protokoll", "tcp")) == "udp"
        self.iqr = str(p.get("serie", "ql")) == "iqr"
        self.network, self.station = int(p.get("netzwerk", 0)), int(p.get("station", 0xFF))
        self.module_io = int(str(p.get("modul_io", "03FF")), 16)
        self.timeout = int(p.get("timeout_ms", 2000)) / 1000.0
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

    def frame(self, command, subcommand, data):
        timer = max(1, min(0xFFFF, int(self.timeout * 4)))          # Überwachungszeit in 250-ms-Schritten
        body = struct.pack("<HHH", timer, command, subcommand) + data
        return (b"\x50\x00" + struct.pack("<BBHB", self.network, self.station, self.module_io, 0)
                + struct.pack("<H", len(body)) + body)

    def exchange(self, req):
        if self.sock is None:
            raise ConnectionError(tr("nicht verbunden"))
        with self.lock:
            if self.udp:
                self.sock.send(req)
                resp = self.sock.recv(8192)
            else:
                self.sock.sendall(req)
                head = recv_exact(self.sock, 9)
                resp = head + recv_exact(self.sock, struct.unpack_from("<H", head, 7)[0])
        if len(resp) < 11 or resp[:2] != b"\xD0\x00":
            raise ConnectionError(tr("Ungültige SLMP-Antwort"))
        end = struct.unpack_from("<H", resp, 9)[0]
        if end:
            raise DeviceError(tr("SLMP-Fehler 0x{0:04X}: {1}").format(end, tr(END_CODES.get(end, "siehe Handbuch"))))
        return resp[11:]

    def read_words(self, dev, start, count):
        code = DEVICES[dev][0]
        if self.iqr:
            spec = struct.pack("<IH", start, code)
            sub = 0x0002
        else:
            spec = start.to_bytes(3, "little") + bytes([code])
            sub = 0x0000
        data = self.exchange(self.frame(0x0401, sub, spec + struct.pack("<H", count)))
        if len(data) < 2 * count:
            raise ConnectionError(tr("SLMP-Antwort zu kurz"))
        return list(struct.unpack_from(f"<{count}H", data))


class SlmpReader(WordReader):
    """Wortgeräte: Wortnummer = Gerätenummer. Bitgeräte: Wortnummer = Gerätenummer // 16 (16 Bits je Wort)."""
    default_max_words = 960
    default_gap = 16

    def parse(self, address, dtype):
        dev, n, bit = parse(address)
        if DEVICES[dev][2]:
            if dtype == "BOOL":
                return dev, n // 16, n % 16
            if n % 16:
                raise ValueError(tr("Wortzugriff auf Bitgeräte nur ab einem Vielfachen von 16, z. B. M0, M16, X10"))
            return dev, n // 16, None
        return dev, n, bit

    def area_limit(self, area):
        return min(960, int(self.plc.params.get("max_woerter", 960)))

    def open(self):
        self.client = SlmpClient(self.plc.params)
        self.client.connect()

    def close_transport(self):
        if getattr(self, "client", None) is not None:
            self.client.close()

    def read_words(self, dev, start, count):
        head = start * 16 if DEVICES[dev][2] else start      # Bitgerät: Kopfgerät = Wortnummer · 16
        return self.client.read_words(dev, head, count)

    def endpoint(self):
        p = self.plc.params
        return f"{p.get('ip', '')}:{p.get('port', 5007)}"


class SlmpDriver(Driver):
    id = "slmp"
    name = tr("Mitsubishi MELSEC (SLMP / MC-Protokoll)")
    description = tr("iQ-R, iQ-F, Q, L über Ethernet; SLMP 3E-Rahmen binär, TCP oder UDP")
    params = [
        Param("ip", tr("IP-Adresse"), "text", "192.168.3.39"),
        Param("port", tr("Port"), "int", 5007, minimum=1, maximum=65535,
              tip=tr("In GX Works eingestellter SLMP-Port (z. B. 5007, 5000, 1025)")),
        Param("protokoll", tr("Protokoll"), "choice", "tcp", choices=[("tcp", "TCP"), ("udp", "UDP")]),
        Param("serie", tr("Serie"), "choice", "ql",
              choices=[("ql", tr("Q/L/iQ-F (Standard)")), ("iqr", tr("iQ-R (erweiterte Gerätenummern)"))],
              tip=tr("iQ-R: erweitertes Format (4-Byte-Gerätenummer). Q/L/iQ-F: Standardformat; iQ-R versteht beide.")),
        Param("netzwerk", tr("Netzwerk-Nr."), "int", 0, minimum=0, maximum=255, advanced=True),
        Param("station", tr("Station (PC-Nr.)"), "int", 255, minimum=0, maximum=255, advanced=True,
              tip=tr("255 = eigene Station")),
        Param("modul_io", tr("Ziel-Modul (E/A-Nr., hex)"), "text", "03FF", advanced=True,
              tip=tr("03FF = eigene CPU; Multi-CPU: 03E0 … 03E3")),
        Param("max_woerter", tr("Wörter je Anfrage"), "int", 960, minimum=1, maximum=960, advanced=True),
        Param("luecke", tr("Lücke zusammenfassen bis"), "int", 16, minimum=0, maximum=500, advanced=True,
              suffix=tr(" Wörter")),
        Param("timeout_ms", tr("Zeitlimit"), "int", 2000, minimum=100, maximum=60000, suffix=" ms", advanced=True),
    ]
    types = TYPES
    address_label = tr("Gerät")
    address_hint = tr("MELSEC-Gerät: D100, W1A (hex), R200, ZR1000, TN5, CN3; Bits: M10, X1F (hex), Y20, B3, "
                      "SM400; Bit im Wort: D100.3")
    block_hint = tr("Startgerät, z. B. D100 (Elemente folgen lückenlos)")
    block_uses_index = False

    def summary(self, plc):
        p = plc.params
        return f"{p.get('ip', '')}:{p.get('port', 5007)} {str(p.get('protokoll', 'tcp')).upper()}" + \
               (" iQ-R" if p.get("serie") == "iqr" else "")

    def check_params(self, params):
        err = super().check_params(params)
        if err:
            return err
        try:
            int(str(params.get("modul_io", "03FF")), 16)
        except ValueError:
            return tr("Ziel-Modul: hexadezimale Zahl erwartet, z. B. 03FF")
        return ""

    def check_address(self, address, dtype):
        try:
            dev, n, bit = parse(address)
        except ValueError as e:
            return str(e)
        if dtype not in TYPES:
            return tr("Typ {0} wird nicht unterstützt").format(dtype)
        if bit is not None and dtype != "BOOL":
            return tr("Bitnummer nur beim Typ BOOL")
        if DEVICES[dev][2] and dtype != "BOOL" and n % 16:
            return tr("Wortzugriff auf Bitgeräte nur ab einem Vielfachen von 16, z. B. M0, M16, X10")
        return ""

    def normalize_address(self, address, dtype):
        try:
            dev, n, bit = parse(address)
        except ValueError:
            return address.strip()
        num = format(n, "X") if DEVICES[dev][1] == 16 else str(n)
        return f"{dev}{num}" + (f".{bit:X}" if bit is not None else "")

    def block_element_address(self, block, i):
        try:
            dev, n, bit = parse(block.address)
        except ValueError:
            return f"{block.address}+{i}"
        radix16 = DEVICES[dev][1] == 16
        if DEVICES[dev][2]:
            step = 1 if block.dtype == "BOOL" else 16 * _words(block.dtype)
        elif block.dtype == "BOOL":
            pos = (bit or 0) + i
            num = n + pos // 16
            return f"{dev}{format(num, 'X') if radix16 else num}.{pos % 16:X}"
        else:
            step = _words(block.dtype)
        num = n + i * step
        return f"{dev}{format(num, 'X') if radix16 else num}"

    def check_block(self, block):
        err = self.check_address(block.address, block.dtype)
        return err or super().check_block(block)

    def create_reader(self, plc, variables):
        return SlmpReader(self, plc, variables)


def _words(dtype):
    from plc_treiber.word_common import WORD_TYPES
    return WORD_TYPES.get(dtype, (1,))[0]


DRIVER = SlmpDriver()
