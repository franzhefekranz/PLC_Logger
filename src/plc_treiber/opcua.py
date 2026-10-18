# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
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

Betriebsart: zyklisch lesen (Read-Anfragen im Takt der Steuerung, Standard) oder Subscription – der Server meldet
nur Änderungen (Abtastrate und Meldeintervall einstellbar); der Treiber hält die zuletzt gemeldeten Werte und liefert
sie im Takt der Steuerung. Spart bei vielen, selten wechselnden Werten Netzlast und Serverleistung. Die Verbindung wird
dabei alle paar Sekunden mit einer kleinen Leseanfrage geprüft.

Sicherheit: ohne, oder Signieren/Verschlüsseln (Basic256Sha256, Aes128Sha256RsaOaep, Aes256Sha256RsaPss). Ohne eigenes
Zertifikat erzeugt der Treiber beim ersten Verbinden ein selbstsigniertes (Ordner ``opcua`` im Datenordner); es muss
im Server ggf. als vertrauenswürdig freigegeben werden.
"""
import math
import os
import re
import socket
import threading
import time

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


MODES = [("lesen", tr("Zyklisch lesen (Read)")), ("abo", tr("Subscription (Server meldet Änderungen)"))]
_ALIVE_S = 5.0                                    # Subscription: Verbindung so oft mit einer Leseanfrage prüfen


class _SubHandler:
    """Empfängt die Änderungsmeldungen der Subscription (im Thread von asyncua) und legt sie im Leser ab."""

    def __init__(self, reader):
        self.reader = reader

    def datachange_notification(self, node, val, data):
        try:
            handle = data.subscription_data.client_handle
            dv = data.monitored_item.Value
        except AttributeError:
            return
        self.reader._on_change(handle, val, getattr(dv, "StatusCode", None) if dv is not None else None)

    def event_notification(self, event):
        pass

    def status_change_notification(self, status):
        self.reader._sub_failed = str(getattr(status, "Status", status))


class OpcUaReader(Reader):
    """Liest alle Knoten einer Steuerung mit möglichst wenigen Read-Anfragen (Fehler je Knoten getrennt)."""

    def __init__(self, driver, plc, variables):
        super().__init__(driver, plc, variables)
        self.client = None
        self.requests = []
        self._plan_done = False
        # Subscription: letzte Meldung je Anfrage {Index: (Wert, Status)}; Zuordnung Client-Handle -> Index.
        self.mode = str(plc.params.get("modus", "lesen"))
        self.sub = None
        self._cache, self._handles = {}, {}
        self._lock = threading.Lock()
        self._sub_failed = None
        self._alive_t = 0.0

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
        if self.mode == "abo":
            # Anfangswerte einmal lesen (liefert auch Fehler je Knoten), danach nur noch Änderungen empfangen.
            out = self._read_all()
            with self._lock:
                self._cache = {i: v for i, v in enumerate(self._first) if v is not None}
            try:
                self._subscribe()
            except Exception as e:
                self.close()
                raise ConnectionError(tr("Subscription fehlgeschlagen: {0}: {1}").format(type(e).__name__, e)) from None
            del out
        else:
            self.read()
        return max(0, len(self.vars) - len(self.errors))

    # ---- Subscription
    def _subscribe(self):
        from asyncua import ua
        p = self.plc.params
        period = float(p.get("melde_ms", 0) or 0) or float(self.plc.intervall_ms)
        sampling = float(p.get("abtast_ms", 0) or 0) or period
        self._sub_failed = None
        self.sub = self.client.create_subscription(period, _SubHandler(self))
        mirs, self._handles = [], {}
        for k, r in enumerate(self.requests):
            # direkt am asyncio-Objekt: die Sync-Hülle älterer asyncua-Versionen kennt die Abtastrate nicht
            mir = self.sub.aio_obj._make_monitored_item_request(self.client.get_node(r.nodeid), ua.AttributeIds.Value,
                                                               None, 0, ua.MonitoringMode.Reporting, sampling)
            if r.index_range:
                mir.ItemToMonitor.IndexRange = r.index_range
            self._handles[mir.RequestedParameters.ClientHandle] = k
            mirs.append(mir)
        chunk = max(1, int(p.get("knoten_je_anfrage", 500)))
        for i in range(0, len(mirs), chunk):
            results = self.sub.create_monitored_items(mirs[i:i + chunk])
            for mir, res in zip(mirs[i:i + chunk], results):
                if isinstance(res, ua.StatusCode):           # Knoten lässt sich nicht beobachten
                    r = self.requests[self._handles[mir.RequestedParameters.ClientHandle]]
                    for _p, _i, addr in r.items:
                        self.errors[addr] = tr("Subscription: {0}").format(getattr(res, "name", res))
        self._alive_t = time.monotonic()

    def _on_change(self, handle, val, status):
        k = self._handles.get(handle)
        if k is not None:
            with self._lock:
                self._cache[k] = (val, status)

    def _check_alive(self):
        """Subscription: Verbindung regelmäßig mit einer kleinen Leseanfrage prüfen (Serverzustand)."""
        if self._sub_failed:
            raise ConnectionError(tr("Subscription beendet: {0}").format(self._sub_failed))
        now = time.monotonic()
        if now - self._alive_t < _ALIVE_S:
            return
        self._alive_t = now
        try:
            self.client.get_node("i=2259").read_value()        # Server_ServerStatus_State
        except Exception as e:
            raise ConnectionError(f"{type(e).__name__}: {e}") from None

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
        if self.client is None:
            raise ConnectionError(tr("nicht verbunden"))
        if self.mode != "abo" or self.sub is None:
            return self._read_all()
        self._check_alive()
        out = [NAN] * len(self.vars)
        with self._lock:
            cache = dict(self._cache)
        for k, r in enumerate(self.requests):
            if k in cache:
                val, status = cache[k]
                self._apply(r, val, status, out)
        return out

    def _read_all(self):
        """Alle Knoten mit Read-Anfragen lesen (zyklischer Betrieb; bei Subscription für die Anfangswerte)."""
        out = [NAN] * len(self.vars)
        self._first = [None] * len(self.requests)
        chunk = max(1, int(self.plc.params.get("knoten_je_anfrage", 500)))
        for i in range(0, len(self.requests), chunk):
            reqs = self.requests[i:i + chunk]
            try:
                results = self._read_chunk(reqs)
            except Exception as e:
                raise ConnectionError(f"{type(e).__name__}: {e}") from None
            for k, (r, dv) in enumerate(zip(reqs, results)):
                val = dv.Value.Value if dv.Value is not None else None
                self._first[i + k] = (val, dv.StatusCode)
                self._apply(r, val, dv.StatusCode, out)
        return out

    def _apply(self, r, val, status, out):
        """Wert (bzw. Array-Ausschnitt) einer Anfrage in die Ausgabeliste übertragen; Fehler je Variable merken."""
        if status is not None and not status.is_good() and not getattr(status, "is_uncertain", lambda: False)():
            text = status.name if hasattr(status, "name") else str(status)
            for _p, _i, addr in r.items:
                self.errors[addr] = text
            return
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

    def close(self):
        if self.sub is not None:
            try:
                self.sub.delete()
            except Exception:
                pass
            self.sub = None
        with self._lock:
            self._cache = {}
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
        Param("modus", tr("Betriebsart"), "choice", "lesen", choices=MODES,
              tip=tr("Subscription: der Server meldet nur Änderungen (weniger Netzlast bei vielen Werten)")),
        Param("sicherheit", tr("Sicherheit"), "choice", "none", choices=SECURITY),
        Param("benutzer", tr("Benutzer"), "text", "", tip=tr("Leer = anonym")),
        Param("passwort", tr("Passwort"), "password", "",
              tip=tr("Hinweis: Es wird im Klartext in der Konfigurationsdatei gespeichert.")),
        Param("zertifikat", tr("Client-Zertifikat"), "text", "", advanced=True,
              tip=tr("Zertifikatsdatei (.der/.pem). Leer = selbstsigniertes Zertifikat wird automatisch erzeugt.")),
        Param("schluessel", tr("Privater Schlüssel"), "text", "", advanced=True,
              tip=tr("Schlüsseldatei (.pem) zum Client-Zertifikat")),
        Param("timeout_s", tr("Zeitlimit"), "float", 4.0, minimum=0.5, maximum=120, suffix=" s", advanced=True),
        Param("melde_ms", tr("Meldeintervall (Subscription)"), "int", 0, minimum=0, maximum=3_600_000, suffix=" ms",
              advanced=True, tip=tr("So oft schickt der Server gesammelte Änderungen (0 = Intervall der Steuerung)")),
        Param("abtast_ms", tr("Abtastrate (Subscription)"), "int", 0, minimum=0, maximum=3_600_000, suffix=" ms",
              advanced=True, tip=tr("So oft prüft der Server die Werte auf Änderung (0 = wie das Meldeintervall)")),
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
        return (str(p.get("endpoint", "")) + ("" if sec == "none" else f" ({sec.split(',')[0]})")
                + (", Subscription" if p.get("modus") == "abo" else ""))

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
