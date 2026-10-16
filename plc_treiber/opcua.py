"""Treiber „opcua“: OPC UA mit der Bibliothek asyncua – für Steuerungen und Server vieler Hersteller.

Beckhoff TwinCAT, B&R, Codesys-Steuerungen (Wago, Festo, Schneider M2xx …), Siemens S7-1500/WinCC, Rockwell (über
FactoryTalk Linx Gateway), Omron NX/NJ, Mitsubishi iQ-R (OPC-UA-Modul), Kepware/KEPServerEX u. v. m.

Adresse = NodeId in der üblichen Schreibweise:

    ns=4;s=|var|CODESYS Control.Application.GVL.Temperatur      (Codesys)
    ns=3;s="DB_Prozess"."Temperatur"                             (S7-1500)
    ns=4;s=MAIN.fTemperatur                                      (TwinCAT)
    ns=2;i=1001                                                  (numerische Kennung)

Werte werden mit ihrem OPC-UA-Datentyp geliefert; die Spalte „Typ“ dient nur der Anzeige. Blöcke: Array-Knoten (ohne
Index) + erster Index + Anzahl – der Ausschnitt wird mit einem Indexbereich in EINER Anfrage gelesen. Der
Auswahldialog durchsucht den Adressraum des Servers.

Sicherheit: ohne, oder Signieren/Verschlüsseln (Basic256Sha256, Aes128Sha256RsaOaep, Aes256Sha256RsaPss). Ohne eigenes
Zertifikat erzeugt der Treiber beim ersten Verbinden ein selbstsigniertes (Ordner ``opcua`` im Datenordner); es muss
im Server ggf. als vertrauenswürdig freigegeben werden.
"""
import math
import os
import re
import socket
import threading

from plc_i18n import tr
from plc_treiber.base import NAN, BrowseResult, Driver, Param, Reader

APP_URI = "urn:plc-datenlogger:client"
SECURITY = [("none", tr("Keine")),
            ("Basic256Sha256,Sign", "Basic256Sha256 – " + tr("Signieren")),
            ("Basic256Sha256,SignAndEncrypt", "Basic256Sha256 – " + tr("Signieren und verschlüsseln")),
            ("Aes128Sha256RsaOaep,SignAndEncrypt", "Aes128Sha256RsaOaep – " + tr("Signieren und verschlüsseln")),
            ("Aes256Sha256RsaPss,SignAndEncrypt", "Aes256Sha256RsaPss – " + tr("Signieren und verschlüsseln"))]
# OPC-UA-Grunddatentyp (NodeId i=…) -> Datentyp des Loggers
UA_TYPES = {1: "BOOL", 2: "SINT", 3: "USINT", 4: "INT", 5: "UINT", 6: "DINT", 7: "UDINT", 8: "LINT", 9: "ULINT",
            10: "REAL", 11: "LREAL", 29: "DINT"}         # 29 = Enumeration
_INDEX_RE = re.compile(r"^(.*)\[(\d+)\]$")
_CERT_LOCK = threading.Lock()


def to_float(value):
    """Gelesenen OPC-UA-Wert in float wandeln (bool -> 0/1, Datum -> Unix-Zeit, sonst NaN)."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if hasattr(value, "timestamp"):
        try:
            return float(value.timestamp())
        except (OverflowError, OSError, ValueError):
            return NAN
    if hasattr(value, "value") and isinstance(getattr(value, "value"), (int, float)):   # Enum
        return float(value.value)
    return NAN


def client_certificate(params):
    """(Zertifikat, Schlüssel) – angegebene Dateien oder ein automatisch erzeugtes, selbstsigniertes Paar."""
    cert = str(params.get("zertifikat", "")).strip()
    key = str(params.get("schluessel", "")).strip()
    if cert and key:
        return cert, key
    from plc_common import BASE_DIR
    folder = os.path.join(BASE_DIR, "opcua")
    cert, key = os.path.join(folder, "client_cert.der"), os.path.join(folder, "client_key.pem")
    with _CERT_LOCK:
        if not (os.path.exists(cert) and os.path.exists(key)):
            import asyncio
            from pathlib import Path

            from asyncua.crypto.cert_gen import setup_self_signed_certificate
            from cryptography.x509.oid import ExtendedKeyUsageOID
            os.makedirs(folder, exist_ok=True)
            host = socket.gethostname()
            asyncio.run(setup_self_signed_certificate(
                Path(key), Path(cert), APP_URI, host, [ExtendedKeyUsageOID.CLIENT_AUTH],
                {"countryName": "DE", "organizationName": "PLC Datenlogger", "commonName": f"PLC Datenlogger@{host}"}))
    return cert, key


def make_client(params):
    """Verbundener asyncua-Client (sync-Schnittstelle) mit den Einstellungen der Steuerung."""
    from asyncua.sync import Client
    url = str(params.get("endpoint", "")).strip()
    client = Client(url, timeout=float(params.get("timeout_s", 4)))
    client.application_uri = APP_URI
    user = str(params.get("benutzer", "")).strip()
    if user:
        client.set_user(user)
        client.set_password(str(params.get("passwort", "")))
    sec = str(params.get("sicherheit", "none"))
    if sec and sec != "none":
        cert, key = client_certificate(params)
        client.set_security_string(f"{sec},{cert},{key}")
    try:
        client.connect()
    except BaseException:
        try:
            client.tloop.stop()
        except Exception:
            pass
        raise
    return client


def close_client(client):
    if client is None:
        return
    try:
        client.disconnect()
    except Exception:
        try:
            client.tloop.stop()
        except Exception:
            pass


class _Request:
    __slots__ = ("nodeid", "index_range", "items", "lo", "n")


class OpcUaReader(Reader):
    """Liest alle Knoten einer Steuerung mit möglichst wenigen Read-Anfragen (Fehler je Knoten getrennt)."""

    def __init__(self, driver, plc, variables):
        super().__init__(driver, plc, variables)
        self.client = None
        self.requests = []
        self._plan_done = False

    def _plan(self):
        from asyncua import ua
        blocks = {}
        for pos, v in enumerate(self.vars):
            addr = (v.address or "").strip()
            base, idx = addr, None
            if v.block:
                m = _INDEX_RE.match(addr)
                if m:
                    base, idx = m.group(1), int(m.group(2))
            try:
                nid = ua.NodeId.from_string(base)
            except Exception as e:
                self.errors[v.address] = tr("Ungültige NodeId: {0}").format(e)
                continue
            if idx is not None:
                blocks.setdefault((v.block, base), [nid, []])[1].append((pos, idx, v.address))
                continue
            r = _Request()
            r.nodeid, r.index_range, r.items, r.lo, r.n = nid, None, [(pos, None, v.address)], 0, 1
            self.requests.append(r)
        for (_name, _base), (nid, items) in blocks.items():
            lo, hi = min(i for _p, i, _a in items), max(i for _p, i, _a in items)
            r = _Request()
            r.nodeid, r.index_range, r.items = nid, (f"{lo}:{hi}" if hi > lo else str(lo)), list(items)
            r.lo, r.n = lo, hi - lo + 1
            self.requests.append(r)
        self._plan_done = True

    def connect(self):
        self.close()
        if not self._plan_done:
            self._plan()
        p = self.plc.params
        try:
            self.client = make_client(p)
        except Exception as e:
            raise ConnectionError(f"{p.get('endpoint', '')}: {type(e).__name__}: {e}") from None
        self.read()
        return max(0, len(self.vars) - len(self.errors))

    def _read_chunk(self, reqs):
        from asyncua import ua
        params = ua.ReadParameters()
        params.TimestampsToReturn = ua.TimestampsToReturn.Neither
        for r in reqs:
            rv = ua.ReadValueId()
            rv.NodeId = r.nodeid
            rv.AttributeId = ua.AttributeIds.Value
            if r.index_range:
                rv.IndexRange = r.index_range
            params.NodesToRead.append(rv)
        aio = self.client.aio_obj
        return self.client.tloop.post(aio.uaclient.read(params))

    def read(self):
        out = [NAN] * len(self.vars)
        if self.client is None:
            raise ConnectionError(tr("nicht verbunden"))
        chunk = max(1, int(self.plc.params.get("knoten_je_anfrage", 500)))
        for i in range(0, len(self.requests), chunk):
            reqs = self.requests[i:i + chunk]
            try:
                results = self._read_chunk(reqs)
            except Exception as e:
                raise ConnectionError(f"{type(e).__name__}: {e}") from None
            for r, dv in zip(reqs, results):
                status = dv.StatusCode
                if status is not None and not status.is_good() and not getattr(status, "is_uncertain", lambda: False)():
                    text = status.name if hasattr(status, "name") else str(status)
                    for _p, _i, addr in r.items:
                        self.errors[addr] = text
                    continue
                val = dv.Value.Value if dv.Value is not None else None
                for pos, sub, addr in r.items:
                    if sub is None:
                        f = to_float(val) if not isinstance(val, (list, tuple)) else NAN
                        if isinstance(val, (list, tuple)):
                            self.errors[addr] = tr("Array – bitte als Block lesen")
                            continue
                    else:
                        # sub = Array-Index; manche Server ignorieren den Indexbereich und liefern das ganze Array
                        seq = val if isinstance(val, (list, tuple)) else [val]
                        k = sub - r.lo if len(seq) == r.n else sub
                        f = to_float(seq[k]) if 0 <= k < len(seq) else NAN
                    if math.isnan(f) and val is not None and not isinstance(val, float):
                        self.errors[addr] = tr("Datentyp nicht darstellbar: {0}").format(type(val).__name__)
                    else:
                        self.errors.pop(addr, None)
                    out[pos] = f
        return out

    def close(self):
        if self.client is not None:
            close_client(self.client)
            self.client = None


class OpcUaDriver(Driver):
    id = "opcua"
    name = tr("OPC UA (asyncua)")
    description = tr("Steuerungen und Server mit OPC UA: Beckhoff, B&R, Codesys, Siemens, Omron, Kepware …")
    params = [
        Param("endpoint", tr("Endpunkt"), "text", "opc.tcp://192.168.0.10:4840",
              tip=tr("Adresse des OPC-UA-Servers, z. B. opc.tcp://192.168.0.10:4840 (Codesys/TwinCAT: 4840, "
                     "S7-1500: 4840, Kepware: 49320)")),
        Param("sicherheit", tr("Sicherheit"), "choice", "none", choices=SECURITY),
        Param("benutzer", tr("Benutzer"), "text", "", tip=tr("Leer = anonym")),
        Param("passwort", tr("Passwort"), "password", "",
              tip=tr("Hinweis: Es wird im Klartext in der Konfigurationsdatei gespeichert.")),
        Param("zertifikat", tr("Client-Zertifikat"), "text", "", advanced=True,
              tip=tr("Zertifikatsdatei (.der/.pem). Leer = selbstsigniertes Zertifikat wird automatisch erzeugt.")),
        Param("schluessel", tr("Privater Schlüssel"), "text", "", advanced=True,
              tip=tr("Schlüsseldatei (.pem) zum Client-Zertifikat")),
        Param("timeout_s", tr("Zeitlimit"), "float", 4.0, minimum=0.5, maximum=120, suffix=" s", advanced=True),
        Param("knoten_je_anfrage", tr("Knoten je Anfrage"), "int", 500, minimum=1, maximum=10000, advanced=True,
              tip=tr("Höchstzahl Knoten je Read-Anfrage (Server begrenzen das teilweise, z. B. auf 100)")),
    ]
    types = ["BOOL", "SINT", "INT", "DINT", "LINT", "USINT", "UINT", "UDINT", "ULINT", "REAL", "LREAL"]
    address_label = tr("NodeId")
    address_hint = tr("NodeId, z. B. ns=4;s=MAIN.fTemperatur, ns=3;s=\"DB1\".\"Wert\" oder ns=2;i=1001")
    block_hint = tr("Array-Knoten (NodeId ohne Index), z. B. ns=4;s=MAIN.aWerte")
    block_uses_index = True
    browse_label = tr("Aus OPC-UA-Server wählen…")
    library = "asyncua"

    def summary(self, plc):
        p = plc.params
        sec = str(p.get("sicherheit", "none"))
        return str(p.get("endpoint", "")) + ("" if sec == "none" else f" ({sec.split(',')[0]})")

    def check_params(self, params):
        url = str(params.get("endpoint", "")).strip()
        if not url.lower().startswith("opc.tcp://"):
            return tr("Der Endpunkt muss mit opc.tcp:// beginnen")
        if bool(str(params.get("zertifikat", "")).strip()) != bool(str(params.get("schluessel", "")).strip()):
            return tr("Zertifikat und Schlüssel bitte beide angeben (oder beide leer lassen)")
        return ""

    def check_address(self, address, dtype):
        a = (address or "").strip()
        if not a:
            return tr("NodeId fehlt")
        if not re.match(r"^(ns=\d+;)?(i=\d+|s=.+|g=[0-9A-Fa-f-]{36}|b=.+)$", a) and not a.startswith("nsu="):
            return tr("Ungültige NodeId „{0}“ (z. B. ns=2;s=Name oder ns=2;i=1001)").format(a)
        return ""

    def check_library(self):
        import asyncua  # noqa: F401
        return True

    def create_reader(self, plc, variables):
        return OpcUaReader(self, plc, variables)

    def browse(self, parent, ctx):
        from plc_treiber.opcua_browser import OpcUaBrowserDialog
        dlg = OpcUaBrowserDialog(parent, ctx.plc, set(ctx.existing), ctx.target_labels, ctx.default_target)
        if not dlg.exec():
            return None
        res = BrowseResult(target_index=dlg.target_index)
        res.variables = list(dlg.result_vars)
        res.blocks = list(dlg.result_blocks)
        return res


DRIVER = OpcUaDriver()
