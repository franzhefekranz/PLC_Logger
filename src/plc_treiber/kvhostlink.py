# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Treiber „kvhostlink“: KEYENCE KV-Serie über das Host-Link-Protokoll (ASCII, Ethernet, Port 8501).

KV-8000/7000/5000/3000/Nano und KV-X mit Ethernet-Schnittstelle (eingebaut oder KV-EP21V/KV-LE21V). In KV STUDIO ist
nichts einzurichten; der Host-Link-Port ist standardmäßig 8501.

Adressen in KEYENCE-Schreibweise:

    DM100   EM0   FM0   ZF10   W1A (hex)   TM0   CM10   VM0   Z1              Wortgeräte (Lesen mit RDS … .U)
    R1000   MR500   LR0   CR3   B1F (hex)   VB0                                Bitgeräte, Typ BOOL (R1000 = Kanal 10, Bit 0)
    T10   C5                                                                    Timer/Zähler: Istwert (32 Bit)
    DM100.3                                                                     Bit 3 eines Wortes

DINT/REAL/LREAL belegen 2 bzw. 4 Wörter, niederwertiges Wort zuerst (wie in KV STUDIO). Benachbarte Wortadressen
werden mit EINEM RDS-Befehl gelesen, benachbarte Bits ebenso.
"""
import re
import socket
import threading

from plc_i18n import N_, tr
from plc_treiber.base import Driver, Param
from plc_treiber.word_common import TYPES, WORD_TYPES, DeviceError, WordReader

WORD_DEVICES = {"DM": 10, "EM": 10, "FM": 10, "ZF": 10, "W": 16, "TM": 10, "CM": 10, "VM": 10, "Z": 10}
BIT_DEVICES = {"R": 10, "MR": 10, "LR": 10, "CR": 10, "B": 16, "VB": 16}
BANK_DEVICES = {"R", "MR", "LR", "CR"}               # Nummer = Kanal * 100 + Bit (00–15)
COUNTER_DEVICES = {"T": 10, "C": 10}                 # Istwerte, 32 Bit (Format .D)
_ALL = sorted(list(WORD_DEVICES) + list(BIT_DEVICES) + list(COUNTER_DEVICES), key=len, reverse=True)
_RE = re.compile(r"^(" + "|".join(_ALL) + r")([0-9A-F]+)(?:\.([0-9A-F]{1,2}))?$")
ERRORS = {"E0": N_("Gerätenummer ungültig"), "E1": N_("Befehl ungültig"), "E2": N_("Programm nicht registriert"),
          "E4": N_("Schreibschutz"), "E5": N_("Gerätefehler"), "E6": N_("kein Kommentar")}


def parse(address):
    """-> (Gerät, Nummer, Bit|None). R1000 -> ('R', 1000, None); DM5.3 -> ('DM', 5, 3)."""
    a = (address or "").strip().upper().replace(" ", "")
    m = _RE.match(a)
    if not m:
        raise ValueError(tr("Ungültige KV-Adresse „{0}“ (z. B. DM100, EM0, W1A, R1000, MR500, T10, DM100.3)")
                         .format(address))
    dev, num, bit = m.group(1), m.group(2), m.group(3)
    radix = {**WORD_DEVICES, **BIT_DEVICES, **COUNTER_DEVICES}[dev]
    try:
        n = int(num, radix)
    except ValueError:
        raise ValueError(tr("„{0}“: {1} wird dezimal gezählt").format(address, dev)) from None
    if dev in BANK_DEVICES and n % 100 > 15:
        raise ValueError(tr("„{0}“: die letzten beiden Ziffern sind die Bitnummer 00–15").format(address))
    if bit is not None:
        if dev not in WORD_DEVICES:
            raise ValueError(tr("Bitnummer nur bei Wortgeräten: {0}").format(address))
        b = int(bit, 10) if bit.isdigit() else int(bit, 16)
        if b > 15:
            raise ValueError(tr("Bitnummer 0–15 erwartet: {0}").format(address))
        return dev, n, b
    return dev, n, None


def logical(dev, n):
    """Bitgerät -> fortlaufende Bitnummer (R1015 und R1100 sind Nachbarn)."""
    return (n // 100) * 16 + (n % 100) if dev in BANK_DEVICES else n


def device_text(dev, n):
    """Gerät als Text für den Befehl (W, B, VB hexadezimal, alle übrigen dezimal)."""
    if dev in ("W", "B", "VB"):
        return f"{dev}{n:X}"
    return f"{dev}{n}"


class HostLinkClient:
    """Host-Link-Client (ASCII-Befehle über TCP, Antwort je Zeile mit CR LF)."""
    def __init__(self, params):
        """Verbindungsdaten (IP, Port 8501, Zeitlimit); ``buf`` hält empfangene, noch nicht verarbeitete Zeichen."""
        self.host, self.port = str(params.get("ip", "")), int(params.get("port", 8501))
        self.timeout = int(params.get("timeout_ms", 2000)) / 1000.0
        self.sock = None
        self.buf = b""
        self.lock = threading.Lock()

    def connect(self):
        """TCP-Verbindung öffnen."""
        self.close()
        s = socket.create_connection((self.host, self.port), timeout=self.timeout)
        s.settimeout(self.timeout)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock, self.buf = s, b""

    def close(self):
        """Verbindung schließen."""
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def command(self, text):
        """Befehl senden, Antwortzeile (ohne CR LF) zurück; E0…E6 -> DeviceError."""
        if self.sock is None:
            raise ConnectionError(tr("nicht verbunden"))
        with self.lock:
            self.sock.sendall(text.encode("ascii") + b"\r")
            while b"\r\n" not in self.buf:
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise ConnectionError(tr("Verbindung von der Steuerung getrennt"))
                self.buf += chunk
            line, self.buf = self.buf.split(b"\r\n", 1)
        resp = line.decode("ascii", "replace").strip()
        if re.fullmatch(r"E\d", resp):
            raise DeviceError(tr("KV-Fehler {0}: {1} ({2})").format(resp, tr(ERRORS.get(resp, "unbekannt")), text))
        return resp

    def read_consecutive(self, device, count, fmt=""):
        """Befehl RDS: ``count`` aufeinanderfolgende Geräte ab ``device`` lesen (``fmt`` z. B. .U = 16 Bit
        vorzeichenlos) -> Liste von Zahlen.
        """
        resp = self.command(f"RDS {device}{fmt} {count}")
        tokens = [t for t in re.split(r"[ ,]+", resp) if t]
        if len(tokens) < count:
            raise ConnectionError(tr("KV-Antwort zu kurz: {0}").format(resp[:60]))
        return [int(t, 10) for t in tokens[:count]]


class KvReader(WordReader):
    """Wortgeräte über WordReader (RDS … .U); Bitgeräte (RDS ohne Format) und Timer/Zähler (RD … .D) gesondert."""
    default_max_words = 500
    default_gap = 16

    def __init__(self, driver, plc, variables):
        """Leseplan: Wortgeräte über WordReader; Bitgeräte je Gerät zu Gruppen fortlaufender Bits (über Kanalgrenzen,
        siehe ``logical``); Timer/Zähler einzeln.
        """
        self.bits = []          # (pos, Gerät, Nummer, Adresse)
        self.counters = []      # (pos, Gerät, Nummer, Adresse)
        super().__init__(driver, plc, variables)
        # Bitgruppen: je Gerät fortlaufende Bitnummern zusammenfassen (RDS R1000 n)
        self.bit_requests = []
        limit = max(1, int(plc.params.get("max_woerter", self.default_max_words)))
        for dev in BIT_DEVICES:
            cur = None
            for pos, d, n, addr in sorted((b for b in self.bits if b[1] == dev), key=lambda b: logical(b[1], b[2])):
                lg = logical(d, n)
                if cur and lg - cur[2] <= 1 and lg - cur[1] < limit:
                    cur[2] = max(cur[2], lg)
                    cur[3].append((pos, lg, addr))
                else:
                    cur = [dev, lg, lg, [(pos, lg, addr)], n]
                    self.bit_requests.append(cur)

    def claim(self, pos, v):
        """Bitgeräte und Timer/Zähler liest dieser Leser selbst (nicht über Wortanfragen)."""
        dev, n, _bit = parse(v.address)
        if dev in BIT_DEVICES:
            if v.dtype != "BOOL":
                raise ValueError(tr("Bitgeräte haben den Typ BOOL: {0}").format(v.address))
            self.bits.append((pos, dev, n, v.address))
            return True
        if dev in COUNTER_DEVICES:
            self.counters.append((pos, dev, n, v.address))
            return True
        return False

    def parse(self, address, dtype):
        """Adresse -> (Gerät, Nummer, Bit)."""
        return parse(address)

    def open(self):
        """Host-Link-Verbindung öffnen."""
        self.client = HostLinkClient(self.plc.params)
        self.client.connect()

    def close_transport(self):
        """Verbindung schließen."""
        if getattr(self, "client", None) is not None:
            self.client.close()

    def read_words(self, dev, start, count):
        """Wortgeräte als 16-Bit-Werte (Format .U) lesen."""
        return self.client.read_consecutive(device_text(dev, start), count, ".U")

    def read(self):
        """Ein Messzyklus: Wortgeräte (WordReader), dann die Bitgruppen (RDS ohne Format, Wert 0/1) und die Istwerte der
        Timer/Zähler (RD … .D, 32 Bit).
        """
        out = super().read()
        for dev, lo, hi, items, first in self.bit_requests:
            try:
                vals = self.client.read_consecutive(device_text(dev, first), hi - lo + 1)
            except DeviceError as e:
                for _p, _l, addr in items:
                    self.errors[addr] = str(e)
                continue
            except (OSError, ValueError) as e:
                raise ConnectionError(str(e)) from None
            for pos, lg, addr in items:
                out[pos] = float(vals[lg - lo] & 1)
                self.errors.pop(addr, None)
        for pos, dev, n, addr in self.counters:
            try:
                resp = self.client.command(f"RD {dev}{n}.D")
                out[pos] = float(int([t for t in re.split(r"[ ,]+", resp) if t][-1], 10))
                self.errors.pop(addr, None)
            except DeviceError as e:
                self.errors[addr] = str(e)
            except (OSError, ValueError, IndexError) as e:
                raise ConnectionError(str(e)) from None
        return out

    def endpoint(self):
        """„IP:Port“ für Fehlermeldungen."""
        p = self.plc.params
        return f"{p.get('ip', '')}:{p.get('port', 8501)}"


class KvDriver(Driver):
    """Treiber „kvhostlink“ (siehe Modulbeschreibung)."""
    id = "kvhostlink"
    name = tr("KEYENCE KV (Host Link)")
    description = tr("KV-8000/7000/5000/3000/Nano, KV-X über Ethernet, Host-Link-Protokoll (Port 8501)")
    params = [
        Param("ip", tr("IP-Adresse"), "text", "192.168.0.10"),
        Param("port", tr("Port"), "int", 8501, minimum=1, maximum=65535, tip=tr("Host-Link-Port, Standard 8501")),
        Param("max_woerter", tr("Wörter je Anfrage"), "int", 500, minimum=1, maximum=1000, advanced=True),
        Param("luecke", tr("Lücke zusammenfassen bis"), "int", 16, minimum=0, maximum=500, advanced=True,
              suffix=tr(" Wörter")),
        Param("timeout_ms", tr("Zeitlimit"), "int", 2000, minimum=100, maximum=60000, suffix=" ms", advanced=True),
    ]
    types = TYPES
    address_label = tr("Gerät")
    address_hint = tr("KV-Gerät: DM100, EM0, FM0, ZF10, W1A, TM0; Bits: R1000, MR500, LR0, CR3, B1F; "
                      "Timer/Zähler-Istwert: T10, C5; Bit im Wort: DM100.3")
    block_hint = tr("Startgerät, z. B. DM100 (Elemente folgen lückenlos)")
    block_uses_index = False

    def summary(self, plc):
        """„IP:Port“."""
        return f"{plc.params.get('ip', '')}:{plc.params.get('port', 8501)}"

    def check_address(self, address, dtype):
        """Adresse, Typ und Bitnummer zueinander passend? Bitgeräte nur BOOL, Timer/Zähler als Ganzzahl."""
        try:
            dev, n, bit = parse(address)
        except ValueError as e:
            return str(e)
        if dtype not in TYPES:
            return tr("Typ {0} wird nicht unterstützt").format(dtype)
        if dev in BIT_DEVICES and dtype != "BOOL":
            return tr("Bitgeräte haben den Typ BOOL")
        if bit is not None and dtype != "BOOL":
            return tr("Bitnummer nur beim Typ BOOL")
        if dev in COUNTER_DEVICES and dtype in ("BOOL", "REAL", "LREAL"):
            return tr("Timer/Zähler: Istwert als DINT/UDINT lesen")
        return ""

    def normalize_address(self, address, dtype):
        """Einheitliche Schreibweise."""
        try:
            dev, n, bit = parse(address)
        except ValueError:
            return address.strip()
        return device_text(dev, n) + (f".{bit}" if bit is not None else "")

    def block_element_address(self, block, i):
        """Adresse des i-ten Elements: Kanal-Bitgeräte zählen über die Kanalgrenze (R1015 -> R1100), übrige Geräte
        fortlaufend, BOOL in Wortgeräten bitweise.
        """
        try:
            dev, n, bit = parse(block.address)
        except ValueError:
            return f"{block.address}+{i}"
        if dev in BANK_DEVICES:
            lg = logical(dev, n) + i
            return f"{dev}{(lg // 16) * 100 + lg % 16}"
        if dev in BIT_DEVICES or dev in COUNTER_DEVICES:
            return device_text(dev, n + i)
        if block.dtype == "BOOL":
            pos = (bit or 0) + i
            return device_text(dev, n + pos // 16) + f".{pos % 16}"
        return device_text(dev, n + i * WORD_TYPES.get(block.dtype, (1,))[0])

    def check_block(self, block):
        """Startadresse und Typ wie bei einer Einzelvariable prüfen."""
        return self.check_address(block.address, block.dtype) or super().check_block(block)

    def create_reader(self, plc, variables):
        """Leser für eine Steuerung (siehe KvReader)."""
        return KvReader(self, plc, variables)


DRIVER = KvDriver()
