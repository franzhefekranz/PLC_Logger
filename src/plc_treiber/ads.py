# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Treiber „ads“: Beckhoff TwinCAT 2/3 über ADS (AMS/TCP, Port 48898) – ohne Zusatzbibliothek.

Variablen symbolisch (``MAIN.fTemperatur``, ``GVL.aWerte[3]``, TwinCAT 2: ``.gWert``) oder über Indexgruppe und
-offset (``0x4020:16``) bzw. in Merker-/E/A-Schreibweise (``%MW10``, ``%MD4``, ``%MX2.3``, ``%IW0``, ``%QX0.1``).
Symbolnamen werden beim Verbinden einmal in Indexgruppe/-offset aufgelöst; gelesen wird mit Summenanfragen
(viele Variablen in einer Anfrage). Blöcke: Array-Name + erster Index + Anzahl – der Ausschnitt wird am Stück gelesen.
Der Auswahldialog liest die Symboltabelle der Steuerung.

Voraussetzung: In der Steuerung (TwinCAT-Router) eine Route zu diesem Rechner anlegen – AMS-Net-ID dieses Rechners
(Einstellung „Eigene AMS-Net-ID“, Standard: eigene IP-Adresse + „.1.1“) und seine IP-Adresse. Ohne Route beantwortet
die Steuerung keine Anfragen. Port: 851 = erste SPS-Laufzeit (TwinCAT 3), 801 = TwinCAT 2.
"""
import re
import socket
import struct
import threading

from plc_i18n import N_, tr
from plc_treiber.base import NAN, BrowseResult, Driver, Param, Reader

AMS_PORT = 48898
CMD_READ, CMD_READWRITE, CMD_READSTATE = 2, 9, 4
IG_SYM_INFOBYNAMEEX, IG_SUMUP_READ = 0xF009, 0xF080
IG_SYM_UPLOAD, IG_SYM_UPLOADINFO2 = 0xF00B, 0xF00F
# Datentyp -> (Bytes, struct-Format little-endian)
ADS_TYPES = {"BOOL": (1, "<B"), "BYTE": (1, "<B"), "USINT": (1, "<B"), "SINT": (1, "<b"), "WORD": (2, "<H"),
             "UINT": (2, "<H"), "INT": (2, "<h"), "DWORD": (4, "<I"), "UDINT": (4, "<I"), "DINT": (4, "<i"),
             "REAL": (4, "<f"), "LWORD": (8, "<Q"), "ULINT": (8, "<Q"), "LINT": (8, "<q"), "LREAL": (8, "<d"),
             "TIME": (4, "<I"), "LTIME": (8, "<Q")}
TYPES = list(ADS_TYPES)
# %-Adressen: Bereich -> (Indexgruppe Byte-Zugriff, Indexgruppe Bit-Zugriff)
AREAS = {"M": (0x4020, 0x4021), "I": (0xF020, 0xF021), "Q": (0xF030, 0xF031)}
_PCT = re.compile(r"^%([MIQ])([XBWD]?)(\d+)(?:\.([0-7]))?$")
_IGIO = re.compile(r"^(0x[0-9A-Fa-f]+|\d+)\s*:\s*(0x[0-9A-Fa-f]+|\d+)$")
_SYM = re.compile(r"^\.?[A-Za-z_][A-Za-z0-9_]*(\[\d+(,\d+)*\])?(\.[A-Za-z_][A-Za-z0-9_]*(\[\d+(,\d+)*\])?)*$")
_INDEX_RE = re.compile(r"^(.*)\[(\d+)\]$")
ERRORS = {
    0x6: N_("Zielport nicht gefunden (SPS-Laufzeit gestartet? Port 851/801)"),
    0x7: N_("Zielrechner nicht gefunden – Route in TwinCAT anlegen (AMS-Net-ID und IP dieses Rechners)"),
    0x12: N_("Port gesperrt"), 0x701: N_("Dienst nicht unterstützt"), 0x702: N_("Indexgruppe ungültig"),
    0x703: N_("Indexoffset ungültig"), 0x705: N_("Datengröße passt nicht"), 0x706: N_("Daten ungültig"),
    0x710: N_("Symbol nicht gefunden"), 0x711: N_("Symbolversion ungültig (SPS neu geladen?)"),
    0x745: N_("Zeitüberschreitung"), 0x751: N_("Zu viele Unteranfragen"),
}


def ads_error(code):
    """Text zu einem ADS-Fehlercode (bekannte Codes mit Hinweis, z. B. fehlende Route)."""
    return tr("ADS-Fehler 0x{0:X}: {1}").format(code, tr(ERRORS.get(code, "siehe Beckhoff-Infosys ADS Return Codes")))


class AdsError(Exception):
    """ADS-Fehlerantwort; ``code`` = ADS-Fehlercode."""
    def __init__(self, code):
        """Fehler mit lesbarem Text und dem Code."""
        super().__init__(ads_error(code))
        self.code = code


def parse_netid(text):
    """AMS-Net-ID „a.b.c.d.e.f“ -> 6 Bytes (ValueError bei falschem Format)."""
    parts = str(text or "").strip().split(".")
    if len(parts) != 6:
        raise ValueError(tr("AMS-Net-ID mit 6 Zahlen erwartet, z. B. 5.12.34.56.1.1"))
    try:
        vals = [int(x) for x in parts]
    except ValueError:
        raise ValueError(tr("AMS-Net-ID mit 6 Zahlen erwartet, z. B. 5.12.34.56.1.1")) from None
    if any(not 0 <= v <= 255 for v in vals):
        raise ValueError(tr("AMS-Net-ID: Zahlen 0 … 255"))
    return bytes(vals)


def parse_address(address, dtype):
    """-> ("sym", Name) | ("igio", Gruppe, Offset). ValueError bei ungültiger Adresse."""
    a = (address or "").strip()
    m = _PCT.match(a.upper())
    if m:
        area, size, num, bit = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        if size == "X" or bit is not None:
            if bit is None:
                raise ValueError(tr("Bitadresse mit Bitnummer, z. B. %MX2.3"))
            return ("igio", AREAS[area][1], num * 8 + int(bit))
        return ("igio", AREAS[area][0], num)
    m = _IGIO.match(a)
    if m:
        return ("igio", int(m.group(1), 0), int(m.group(2), 0))
    if _SYM.match(a):
        return ("sym", a)
    raise ValueError(tr("Ungültige ADS-Adresse „{0}“ (z. B. MAIN.fTemperatur, GVL.aWerte[3], %MW10, 0x4020:16)").format(address))


class AdsClient:
    """AMS/TCP-Verbindung mit Read, ReadWrite und ReadState (ein Aufruf zur Zeit)."""

    def __init__(self, params):
        """Verbindungsdaten: IP, TCP-Port, AMS-Net-ID/-Port der Steuerung (Standard: IP + .1.1, 851), eigene
        AMS-Net-ID/-Port, Zeitlimit.
        """
        p = params
        self.host = str(p.get("ip", ""))
        self.port = int(p.get("tcp_port", AMS_PORT))
        self.target = parse_netid(p.get("ams_netid") or f"{self.host}.1.1")
        self.target_port = int(p.get("ams_port", 851))
        self.source_text = str(p.get("eigene_netid", "")).strip()
        self.source_port = int(p.get("eigener_port", 32905))
        self.timeout = int(p.get("timeout_ms", 2000)) / 1000.0
        self.sock = None
        self.invoke = 0
        self.lock = threading.Lock()

    def connect(self):
        """TCP-Verbindung öffnen; ohne eingestellte eigene AMS-Net-ID gilt die lokale IP-Adresse + .1.1 (sie muss zur
        Route passen).
        """
        self.close()
        s = socket.create_connection((self.host, self.port), timeout=self.timeout)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.settimeout(self.timeout)
        self.sock = s
        local = s.getsockname()[0]
        self.source = parse_netid(self.source_text or f"{local}.1.1")

    def close(self):
        """Verbindung schließen."""
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def _recv(self, n):
        """Genau n Bytes empfangen."""
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError(tr("Verbindung von der Steuerung getrennt"))
            buf += chunk
        return buf

    def request(self, cmd, data):
        """ADS-Befehl senden und Antwort lesen.

        Telegramm: AMS/TCP-Kopf (Länge) + AMS-Kopf (Ziel-/Quell-Net-ID und -Port, Befehl, Statusflags 0004 = Anfrage,
        Datenlänge, Fehler, Invoke-ID) + Daten. Antworten mit anderer Invoke-ID werden übersprungen. Fehler im AMS-Kopf
        oder im Ergebnisfeld -> AdsError.
        """
        if self.sock is None:
            raise ConnectionError(tr("nicht verbunden"))
        with self.lock:
            self.invoke = (self.invoke + 1) & 0xFFFFFFFF
            hdr = (self.target + struct.pack("<H", self.target_port) + self.source + struct.pack("<H", self.source_port)
                   + struct.pack("<HHIII", cmd, 0x0004, len(data), 0, self.invoke))
            self.sock.sendall(struct.pack("<HI", 0, len(hdr) + len(data)) + hdr + data)
            while True:
                head = self._recv(6)
                length = struct.unpack_from("<I", head, 2)[0]
                body = self._recv(length)
                if len(body) < 32:
                    raise ConnectionError(tr("Ungültige ADS-Antwort"))
                rcmd, _flags, dlen, err, inv = struct.unpack_from("<HHIII", body, 16)
                if inv == self.invoke:
                    break
        if err:
            raise AdsError(err)
        payload = body[32:32 + dlen]
        if len(payload) < 4:
            raise ConnectionError(tr("ADS-Antwort zu kurz"))
        result = struct.unpack_from("<I", payload, 0)[0]
        if result:
            raise AdsError(result)
        return payload

    def read(self, group, offset, length):
        """ADS Read: ``length`` Bytes ab Indexgruppe/-offset."""
        p = self.request(CMD_READ, struct.pack("<III", group, offset, length))
        n = struct.unpack_from("<I", p, 4)[0]
        return p[8:8 + n]

    def readwrite(self, group, offset, read_len, data):
        """ADS ReadWrite: Daten schreiben und Antwortdaten lesen (für Symbolinfo und Summenanfragen)."""
        p = self.request(CMD_READWRITE, struct.pack("<IIII", group, offset, read_len, len(data)) + data)
        n = struct.unpack_from("<I", p, 4)[0]
        return p[8:8 + n]

    def read_state(self):
        """ADS ReadState -> (ADS-Zustand, Gerätezustand) – prüft, ob die SPS-Laufzeit antwortet."""
        p = self.request(CMD_READSTATE, b"")
        return struct.unpack_from("<HH", p, 4)            # (ADS-Zustand, Gerätezustand)

    def symbol_info(self, name):
        """Symbolname -> (Indexgruppe, Indexoffset, Größe, Typname)."""
        d = self.readwrite(IG_SYM_INFOBYNAMEEX, 0, 0xFFFF, name.encode("cp1252", "replace") + b"\x00")
        _elen, ig, io, size, _dt, _flags, nlen, tlen, _clen = struct.unpack_from("<IIIIIIHHH", d, 0)
        tname = d[30 + nlen + 1:30 + nlen + 1 + tlen].decode("cp1252", "replace")
        return ig, io, size, tname

    def sum_read(self, items):
        """[(Gruppe, Offset, Länge)] in EINER Anfrage -> [(Fehlercode, Daten)]."""
        req = b"".join(struct.pack("<III", g, o, n) for g, o, n in items)
        total = sum(4 + n for _g, _o, n in items)
        d = self.readwrite(IG_SUMUP_READ, len(items), total, req)
        out, pos = [], 4 * len(items)
        for k, (_g, _o, n) in enumerate(items):
            code = struct.unpack_from("<I", d, 4 * k)[0]
            out.append((code, d[pos:pos + n]))
            pos += n
        return out

    def symbols(self):
        """Symboltabelle -> [(Name, Typ, Größe, Kommentar)]."""
        info = self.read(IG_SYM_UPLOADINFO2, 0, 24)
        n_sym, size = struct.unpack_from("<II", info, 0)
        data = self.read(IG_SYM_UPLOAD, 0, size)
        out, pos = [], 0
        for _ in range(n_sym):
            if pos + 30 > len(data):
                break
            elen, _ig, _io, sz, _dt, _fl, nlen, tlen, clen = struct.unpack_from("<IIIIIIHHH", data, pos)
            p = pos + 30
            name = data[p:p + nlen].decode("cp1252", "replace")
            p += nlen + 1
            typ = data[p:p + tlen].decode("cp1252", "replace")
            p += tlen + 1
            comment = data[p:p + clen].decode("cp1252", "replace")
            out.append((name, typ, sz, comment))
            pos += elen or (30 + nlen + tlen + clen + 3)
        return out


class _Req:
    """Eine Teilanfrage der Summenanfrage: Indexgruppe, -offset, Länge und die Variablen darin (Position, Versatz)."""
    __slots__ = ("group", "offset", "length", "items", "base")


class AdsReader(Reader):
    """Löst Symbole beim Verbinden auf und liest alles mit Summenanfragen (je höchstens ``max_unter`` Teile)."""

    def __init__(self, driver, plc, variables):
        """Leser anlegen; der Leseplan entsteht erst beim Verbinden (Symbole werden dann aufgelöst)."""
        super().__init__(driver, plc, variables)
        self.client = None
        self.requests = []

    def _plan(self):
        """Leseplan: je Variable eine Teilanfrage; Block-Elemente eines Arrays zusammen als ein Bereich."""
        self.requests = []
        blocks = {}
        for pos, v in enumerate(self.vars):
            if v.dtype not in ADS_TYPES:
                self.errors[v.address] = tr("Typ {0} wird nicht unterstützt").format(v.dtype)
                continue
            size = ADS_TYPES[v.dtype][0]
            m = _INDEX_RE.match((v.address or "").strip()) if v.block else None
            if m:
                blocks.setdefault((v.block, m.group(1)), []).append((pos, int(m.group(2)), v))
                continue
            try:
                kind = parse_address(v.address, v.dtype)
            except ValueError as e:
                self.errors[v.address] = str(e)
                continue
            try:
                if kind[0] == "sym":
                    g, o, sz, _t = self.client.symbol_info(kind[1])
                    if sz and sz < size:
                        raise AdsError(0x705)
                else:
                    g, o = kind[1], kind[2]
            except AdsError as e:
                self.errors[v.address] = str(e)
                continue
            r = _Req()
            r.group, r.offset, r.length, r.items, r.base = g, o, size, [(pos, 0, v)], None
            self.requests.append(r)
        for (_blk, base), items in blocks.items():
            lo = min(i for _p, i, _v in items)
            hi = max(i for _p, i, _v in items)
            size = ADS_TYPES[items[0][2].dtype][0]
            try:
                g, o, _sz, _t = self.client.symbol_info(f"{base}[{lo}]")
            except AdsError as e:
                for _p, _i, v in items:
                    self.errors[v.address] = str(e)
                continue
            r = _Req()
            r.group, r.offset, r.length = g, o, (hi - lo + 1) * size
            r.items = [(p, (i - lo) * size, v) for p, i, v in items]
            r.base = base
            self.requests.append(r)

    def connect(self):
        """Verbinden, Zustand der Laufzeit abfragen, Symbole auflösen (``_plan``) und einmal lesen."""
        self.close()
        self.errors = {}
        self.client = AdsClient(self.plc.params)
        p = self.plc.params
        try:
            self.client.connect()
            self.client.read_state()
        except (OSError, AdsError) as e:
            self.close()
            raise ConnectionError(f"{p.get('ip', '')} (AMS {p.get('ams_netid', '')}:{p.get('ams_port', 851)}): {e}") from None
        self._plan()
        self.read()
        return max(0, len(self.vars) - len(self.errors))

    def read(self):
        """Ein Messzyklus: Teilanfragen in Summenanfragen zu höchstens ``max_unter`` Teilen senden und dekodieren
        (Little Endian).

        Symbol- oder Versionsfehler bedeuten meist, dass die SPS neu geladen wurde: dann neu verbinden, damit die
        Symbole neu aufgelöst werden.
        """
        if self.client is None:
            raise ConnectionError(tr("nicht verbunden"))
        out = [NAN] * len(self.vars)
        chunk = max(1, min(500, int(self.plc.params.get("max_unter", 500))))
        for i in range(0, len(self.requests), chunk):
            reqs = self.requests[i:i + chunk]
            try:
                results = self.client.sum_read([(r.group, r.offset, r.length) for r in reqs])
            except AdsError as e:
                if e.code in (0x711, 0x710):          # SPS neu geladen: Symbole neu auflösen
                    raise ConnectionError(str(e)) from None
                raise ConnectionError(str(e)) from None
            except (OSError, struct.error) as e:
                raise ConnectionError(str(e) or type(e).__name__) from None
            for r, (code, data) in zip(reqs, results):
                for pos, off, v in r.items:
                    if code:
                        self.errors[v.address] = ads_error(code)
                        continue
                    size, fmt = ADS_TYPES[v.dtype]
                    try:
                        val = struct.unpack_from(fmt, data, off)[0]
                    except struct.error:
                        self.errors[v.address] = tr("Antwort zu kurz")
                        continue
                    out[pos] = float(1.0 if (v.dtype == "BOOL" and val) else val)
                    self.errors.pop(v.address, None)
        return out

    def close(self):
        """Verbindung schließen."""
        if self.client is not None:
            self.client.close()
            self.client = None


def _base_type(tname):
    """Typname der Symboltabelle -> Datentyp des Loggers (oder "")."""
    t = (tname or "").upper().strip()
    return t if t in ADS_TYPES else ""


_ARRAY = re.compile(r"^ARRAY\s*\[\s*(-?\d+)\s*\.\.\s*(-?\d+)\s*\]\s*OF\s+(\w+)$", re.I)


def classify_symbol(name, tname, size):
    """-> ("var", Typ) | ("array", Typ, erster Index, letzter Index) | None (nicht aufzeichenbar)."""
    t = _base_type(tname)
    if t:
        return ("var", t)
    m = _ARRAY.match((tname or "").strip())
    if m and _base_type(m.group(3)):
        return ("array", _base_type(m.group(3)), int(m.group(1)), int(m.group(2)))
    return None


class AdsDriver(Driver):
    """Treiber „ads“ (siehe Modulbeschreibung)."""
    id = "ads"
    name = tr("Beckhoff TwinCAT (ADS)")
    description = tr("TwinCAT 2/3 über ADS (AMS/TCP), symbolisch oder Indexgruppe/-offset; Route erforderlich")
    params = [
        Param("ip", tr("IP-Adresse"), "text", "192.168.0.10"),
        Param("ams_netid", tr("AMS-Net-ID der Steuerung"), "text", "",
              tip=tr("z. B. 5.12.34.56.1.1 (leer = IP-Adresse + .1.1)")),
        Param("ams_port", tr("AMS-Port"), "int", 851, minimum=1, maximum=65535,
              tip=tr("851 = SPS-Laufzeit 1 (TwinCAT 3), 852 … weitere; 801 = TwinCAT 2")),
        Param("eigene_netid", tr("Eigene AMS-Net-ID"), "text", "", advanced=True,
              tip=tr("Muss zur Route in der Steuerung passen (leer = eigene IP-Adresse + .1.1)")),
        Param("eigener_port", tr("Eigener AMS-Port"), "int", 32905, minimum=1, maximum=65535, advanced=True),
        Param("tcp_port", tr("TCP-Port"), "int", AMS_PORT, minimum=1, maximum=65535, advanced=True),
        Param("max_unter", tr("Variablen je Anfrage"), "int", 500, minimum=1, maximum=500, advanced=True,
              tip=tr("Höchstzahl Teile je Summenanfrage (TwinCAT: 500)")),
        Param("timeout_ms", tr("Zeitlimit"), "int", 2000, minimum=100, maximum=60000, suffix=" ms", advanced=True),
    ]
    types = TYPES
    default_type = "REAL"
    address_label = tr("Symbol")
    address_hint = tr("Symbolname (MAIN.fTemperatur, GVL.aWerte[3], .gWert), %MW10/%MD4/%MX2.3/%IW0/%QX0.1 oder "
                      "Indexgruppe:Offset (0x4020:16)")
    block_hint = tr("Array-Name ohne Index, z. B. MAIN.aWerte")
    block_uses_index = True
    browse_label = tr("Aus TwinCAT wählen…")

    def summary(self, plc):
        """„IP AMS Net-ID:Port“."""
        p = plc.params
        return f"{p.get('ip', '')} AMS {p.get('ams_netid') or str(p.get('ip', '')) + '.1.1'}:{p.get('ams_port', 851)}"

    def check_params(self, params):
        """IP vorhanden und eingetragene AMS-Net-IDs gültig?"""
        err = super().check_params(params)
        if err:
            return err
        for key in ("ams_netid", "eigene_netid"):
            if str(params.get(key, "")).strip():
                try:
                    parse_netid(params.get(key))
                except ValueError as e:
                    return str(e)
        return ""

    def check_address(self, address, dtype):
        """Adresse (Symbol, %-Adresse oder Gruppe:Offset) und Typ gültig?"""
        try:
            parse_address(address, dtype)
        except ValueError as e:
            return str(e)
        if dtype not in ADS_TYPES:
            return tr("Typ {0} wird nicht unterstützt").format(dtype)
        return ""

    def check_block(self, block):
        """Blöcke: Array-Name ohne Index (die Elemente werden über den Index adressiert)."""
        a = block.address.strip()
        if not a or not _SYM.match(a) or a.endswith("]"):
            return tr("Array-Name (Symbol ohne Index) erwartet, z. B. MAIN.aWerte")
        return super().check_block(block)

    def create_reader(self, plc, variables):
        """Leser für eine Steuerung (siehe AdsReader)."""
        return AdsReader(self, plc, variables)

    def browse(self, parent, ctx):
        """Auswahldialog mit der Symboltabelle der Steuerung (Variablen und Arrays als Blöcke)."""
        from plc_treiber.ads_browser import AdsBrowserDialog
        dlg = AdsBrowserDialog(parent, ctx.plc, set(ctx.existing), ctx.target_labels, ctx.default_target)
        if not dlg.exec():
            return None
        res = BrowseResult(target_index=dlg.target_index)
        res.variables = list(dlg.result_vars)
        res.blocks = list(dlg.result_blocks)
        return res


DRIVER = AdsDriver()
