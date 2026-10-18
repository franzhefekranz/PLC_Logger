# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Treiber „fins“: Omron über FINS per Ethernet (FINS/TCP oder FINS/UDP).

CJ1/CJ2, CS1, CP1L/CP1H (Ethernet-Option), CP2E, NJ/NX (mit eingerichteter FINS-Verbindung bzw. Kompatibilitäts-
speicher). Port 9600. Bei UDP müssen FINS-Knotennummern passen: Zielknoten = Knotennummer der Steuerung (meist das
letzte Byte ihrer IP-Adresse), Quellknoten = eigene Knotennummer (0 = letztes Byte der eigenen IP-Adresse). Bei TCP
vergibt die Steuerung die Knotennummern selbst.

Adressen in Omron-Schreibweise (dezimal), Bits mit Punkt und zweistelliger Bitnummer 00 … 15:

    D100   DM100        Datenspeicher             W10  WR10   Arbeitsbereich
    100    CIO100       E/A-Bereich (CIO)         H20  HR20   Haltebereich
    A300   AR300        Hilfsbereich              E0_100      Erweiterter Datenspeicher Bank 0 (E0 … E18)
    T5     C3           Timer-/Zähler-Istwert     D100.05  CIO0.01  W3.15                Bits (Typ BOOL)

DINT/REAL/LREAL belegen 2 bzw. 4 aufeinanderfolgende Wörter (niederwertiges Wort zuerst, wie in CX-Programmer).
Bits werden wortweise mitgelesen; benachbarte Adressen ergeben eine Anfrage (Befehl 0101, höchstens 999 Wörter).
"""
import re
import socket
import struct
import threading

from plc_i18n import N_, tr
from plc_treiber.base import Driver, Param
from plc_treiber.word_common import TYPES, DeviceError, WordReader, recv_exact

# Bereich -> FINS-Bereichscode für Wortzugriff (CS/CJ/CP/NJ)
AREAS = {"CIO": 0xB0, "W": 0xB1, "H": 0xB2, "A": 0xB3, "D": 0x82, "T": 0x89, "C": 0x89}
ALIASES = {"DM": "D", "WR": "W", "HR": "H", "AR": "A", "TIM": "T", "CNT": "C", "": "CIO", "EM": "E"}
LIMITS = {"CIO": 6143, "W": 511, "H": 1535, "A": 1471, "D": 32767, "T": 4095, "C": 4095, "E": 32767}
_RE = re.compile(r"^(CIO|DM|WR|HR|AR|TIM|CNT|EM|D|W|H|A|T|C|E)?(?:(\d{1,2})_)?(\d+)(?:\.(\d{1,2}))?$")
END_CODES = {
    0x0101: N_("lokaler Knoten nicht im Netz"), 0x0102: N_("Token-Zeitüberschreitung"), 0x0201: N_("Zielknoten nicht im Netz"),
    0x0202: N_("Zieleinheit fehlt"), 0x0205: N_("Antwort-Zeitüberschreitung"), 0x0401: N_("Befehl nicht unterstützt"),
    0x0501: N_("Zieladresse falsch (Knoten/Netz)"), 0x1001: N_("Befehl zu lang"), 0x1002: N_("Befehl zu kurz"),
    0x1003: N_("Anzahl Elemente passt nicht"), 0x1101: N_("Bereich existiert nicht"), 0x1103: N_("Adresse außerhalb des Bereichs"),
    0x1104: N_("Adressbereich überschritten"), 0x110B: N_("Antwort zu lang (weniger Wörter je Anfrage)"),
    0x2002: N_("Bereich geschützt"),
}


def parse(address):
    """'D100' -> ('D', 100, None); 'E2_50' -> ('E2', 50, None); 'CIO0.05' -> ('CIO', 0, 5); '100.01' -> ('CIO', 100, 1)."""
    a = (address or "").strip().upper().replace(" ", "")
    m = _RE.match(a)
    if not m:
        raise ValueError(tr("Ungültige Omron-Adresse „{0}“ (z. B. D100, W10, H5, CIO0.05, E0_100, T5)").format(address))
    area = ALIASES.get(m.group(1) or "", m.group(1))
    bank, num, bit = m.group(2), int(m.group(3)), m.group(4)
    if bank is not None and area != "E":
        raise ValueError(tr("Bank nur beim erweiterten Datenspeicher (E0_100): {0}").format(address))
    if area == "E":
        if bank is None:
            raise ValueError(tr("Erweiterter Datenspeicher mit Bank angeben, z. B. E0_100: {0}").format(address))
        if int(bank) > 0x18:
            raise ValueError(tr("Bank 0 … 24 erwartet: {0}").format(address))
        area = f"E{int(bank)}"
    limit = LIMITS["E" if area.startswith("E") else area]
    if num > limit:
        raise ValueError(tr("„{0}“: Adresse größer als {1}").format(address, limit))
    if bit is not None:
        bit = int(bit)
        if bit > 15:
            raise ValueError(tr("Bitnummer 00 … 15 erwartet: {0}").format(address))
        if area in ("T", "C"):
            raise ValueError(tr("Timer/Zähler: nur der Istwert (ohne Bit) ist lesbar: {0}").format(address))
    return area, num, bit


def area_code(area):
    if area.startswith("E"):
        bank = int(area[1:])
        return 0xA0 + bank if bank < 16 else 0x60 + (bank - 16)
    return AREAS[area]


class FinsClient:
    """FINS-Client (TCP mit Knotennummern-Austausch oder UDP), Befehl 0101 (Speicherbereich lesen)."""

    def __init__(self, params):
        p = params
        self.host, self.port = str(p.get("ip", "")), int(p.get("port", 9600))
        self.udp = str(p.get("protokoll", "tcp")) == "udp"
        self.dna, self.da1 = int(p.get("ziel_netz", 0)), int(p.get("ziel_knoten", 0))
        self.sna, self.sa1 = int(p.get("quell_netz", 0)), int(p.get("quell_knoten", 0))
        self.timeout = int(p.get("timeout_ms", 2000)) / 1000.0
        self.sock = None
        self.sid = 0
        self.lock = threading.Lock()

    def connect(self):
        self.close()
        if self.udp:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(self.timeout)
            s.connect((self.host, self.port))
            self.sock = s
            if not self.da1:                       # Zielknoten: letztes Byte der IP-Adresse der Steuerung
                self.da1 = int(socket.gethostbyname(self.host).split(".")[-1])
            if not self.sa1:                       # Quellknoten: letztes Byte der eigenen IP-Adresse
                self.sa1 = int(s.getsockname()[0].split(".")[-1]) or 1
            return
        s = socket.create_connection((self.host, self.port), timeout=self.timeout)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.settimeout(self.timeout)
        self.sock = s
        # Knotennummern austauschen: Anfrage mit Knoten 0 = automatisch vergeben
        s.sendall(b"FINS" + struct.pack(">IIII", 12, 0, 0, self.sa1 if self.sa1 else 0))
        head = recv_exact(s, 8)
        if head[:4] != b"FINS":
            raise ConnectionError(tr("Keine FINS/TCP-Antwort"))
        body = recv_exact(s, struct.unpack_from(">I", head, 4)[0])
        cmd, err = struct.unpack_from(">II", body, 0)
        if err:
            raise ConnectionError(tr("FINS/TCP abgelehnt (Fehler 0x{0:08X}) – Knotennummer belegt?").format(err))
        if cmd != 1 or len(body) < 16:
            raise ConnectionError(tr("Unerwartete FINS/TCP-Antwort"))
        self.sa1, server = struct.unpack_from(">II", body, 8)
        self.sa1 &= 0xFF
        if not self.da1:
            self.da1 = server & 0xFF

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def exchange(self, command, data):
        if self.sock is None:
            raise ConnectionError(tr("nicht verbunden"))
        with self.lock:
            self.sid = (self.sid + 1) & 0xFF
            frame = bytes([0x80, 0x00, 0x02, self.dna, self.da1, 0x00, self.sna, self.sa1, 0x00, self.sid]) + command + data
            if self.udp:
                self.sock.send(frame)
                while True:
                    resp = self.sock.recv(4096)
                    if len(resp) >= 10 and resp[9] == self.sid:
                        break
            else:
                self.sock.sendall(b"FINS" + struct.pack(">III", 8 + len(frame), 2, 0) + frame)
                while True:
                    head = recv_exact(self.sock, 16)
                    if head[:4] != b"FINS":
                        raise ConnectionError(tr("Ungültige FINS/TCP-Antwort"))
                    length, cmd, err = struct.unpack_from(">III", head, 4)
                    resp = recv_exact(self.sock, length - 8)
                    if err:
                        raise ConnectionError(tr("FINS/TCP-Fehler 0x{0:08X}").format(err))
                    if len(resp) >= 10 and resp[9] == self.sid:
                        break
        if len(resp) < 14 or resp[10:12] != command:
            raise ConnectionError(tr("Ungültige FINS-Antwort"))
        end = struct.unpack_from(">H", resp, 12)[0] & 0x7F3F       # Relais-/Fehlerkennzeichen ausblenden
        if end not in (0x0000, 0x0040):                            # 0x0040: nur Warnung (z. B. Batterie)
            raise DeviceError(tr("FINS-Fehler 0x{0:04X}: {1}").format(end, tr(END_CODES.get(end, "siehe Handbuch W342"))))
        return resp[14:]

    def read_words(self, area, start, count):
        data = self.exchange(b"\x01\x01", struct.pack(">BHBH", area_code(area), start, 0, count))
        if len(data) < 2 * count:
            raise ConnectionError(tr("FINS-Antwort zu kurz"))
        return list(struct.unpack_from(f">{count}H", data))


class FinsReader(WordReader):
    default_max_words = 999
    default_gap = 16

    def parse(self, address, dtype):
        area, n, bit = parse(address)
        if area == "C":                                  # Zähler-Istwerte liegen ab 8000 hinter den Timern
            n += 0x8000
        return area, n, bit

    def area_limit(self, area):
        return min(999, int(self.plc.params.get("max_woerter", 999)))

    def open(self):
        self.client = FinsClient(self.plc.params)
        self.client.connect()

    def close_transport(self):
        if getattr(self, "client", None) is not None:
            self.client.close()

    def read_words(self, area, start, count):
        return self.client.read_words("T" if area == "C" else area, start, count)

    def endpoint(self):
        p = self.plc.params
        return f"{p.get('ip', '')}:{p.get('port', 9600)}"


class FinsDriver(Driver):
    id = "fins"
    name = tr("Omron (FINS)")
    description = tr("CJ, CS, CP, NJ/NX über Ethernet; FINS/TCP oder FINS/UDP, Port 9600")
    params = [
        Param("ip", tr("IP-Adresse"), "text", "192.168.250.1"),
        Param("port", tr("Port"), "int", 9600, minimum=1, maximum=65535),
        Param("protokoll", tr("Protokoll"), "choice", "tcp", choices=[("tcp", "FINS/TCP"), ("udp", "FINS/UDP")]),
        Param("ziel_knoten", tr("Zielknoten"), "int", 0, minimum=0, maximum=254, advanced=True,
              tip=tr("FINS-Knotennummer der Steuerung (0 = automatisch: TCP von der Steuerung, UDP letztes IP-Byte)")),
        Param("quell_knoten", tr("Quellknoten"), "int", 0, minimum=0, maximum=254, advanced=True,
              tip=tr("Eigene FINS-Knotennummer (0 = automatisch)")),
        Param("ziel_netz", tr("Zielnetz"), "int", 0, minimum=0, maximum=127, advanced=True),
        Param("quell_netz", tr("Quellnetz"), "int", 0, minimum=0, maximum=127, advanced=True),
        Param("max_woerter", tr("Wörter je Anfrage"), "int", 999, minimum=1, maximum=999, advanced=True,
              tip=tr("Ältere CPUs/CP1 über UDP: ggf. kleiner (z. B. 500)")),
        Param("luecke", tr("Lücke zusammenfassen bis"), "int", 16, minimum=0, maximum=500, advanced=True,
              suffix=tr(" Wörter")),
        Param("timeout_ms", tr("Zeitlimit"), "int", 2000, minimum=100, maximum=60000, suffix=" ms", advanced=True),
    ]
    types = TYPES
    address_label = tr("Adresse")
    address_hint = tr("Omron-Adresse: D100, W10, H5, A300, CIO100 (oder 100), E0_100, T5, C3; Bits: D100.05, 0.01")
    block_hint = tr("Startadresse, z. B. D100 (Elemente folgen lückenlos)")
    block_uses_index = False

    def summary(self, plc):
        p = plc.params
        return f"{p.get('ip', '')}:{p.get('port', 9600)} {'UDP' if p.get('protokoll') == 'udp' else 'TCP'}"

    def check_address(self, address, dtype):
        try:
            _area, _n, bit = parse(address)
        except ValueError as e:
            return str(e)
        if dtype not in TYPES:
            return tr("Typ {0} wird nicht unterstützt").format(dtype)
        if bit is not None and dtype != "BOOL":
            return tr("Bitnummer nur beim Typ BOOL")
        return ""

    def normalize_address(self, address, dtype):
        try:
            area, n, bit = parse(address)
        except ValueError:
            return address.strip()
        prefix = f"E{area[1:]}_" if area.startswith("E") else area
        return f"{prefix}{n}" + (f".{bit:02d}" if bit is not None else "")

    def block_element_address(self, block, i):
        try:
            area, n, bit = parse(block.address)
        except ValueError:
            return f"{block.address}+{i}"
        prefix = f"E{area[1:]}_" if area.startswith("E") else area
        if block.dtype == "BOOL":
            pos = (bit or 0) + i
            return f"{prefix}{n + pos // 16}.{pos % 16:02d}"
        from plc_treiber.word_common import WORD_TYPES
        return f"{prefix}{n + i * WORD_TYPES.get(block.dtype, (1,))[0]}"

    def check_block(self, block):
        err = self.check_address(block.address, block.dtype)
        return err or super().check_block(block)

    def create_reader(self, plc, variables):
        return FinsReader(self, plc, variables)


DRIVER = FinsDriver()
