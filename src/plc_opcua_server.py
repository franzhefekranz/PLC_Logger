# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""OPC-UA-Server im Logger: stellt die gelesenen und berechneten Variablen anderen Systemen bereit (Leitsystem, MES,
SCADA, Excel-Add-in, Node-RED …) – nur lesend.

Adressraum (Namensraum ``urn:plc-datenlogger``)::

    Objects / PLC Datenlogger
        <Steuerung 1> / <Variable> …        ns=<i>;s=<Variablenname>
        Berechnet / <Variable> …
        Ereignisse / <Trigger>              Boolean: Ereignis steht an
        Status / <Steuerung>                Boolean: verbunden; …_Text: Zustandstext
        Status / Zeitstempel                Zeit der letzten Messzeile
        Status / Aufzeichnung               Boolean: Aufzeichnung läuft

Werte ohne Messung (NaN, Verbindung gestört) tragen den Status ``BadNoCommunication``; der Quellzeitstempel ist die
Zeit der Messzeile. Der Server läuft, solange die Aufzeichnung läuft (auch im Headless-Betrieb) – in einem eigenen
Thread mit asyncio; die Messung wird nicht aufgehalten.

Einstellung ``opcua_server`` (JSON): aktiv, host, port, intervall_ms (wie oft Werte veröffentlicht werden),
sicherheit (Liste, z. B. ["none", "Basic256Sha256,SignAndEncrypt"]), anonym (Zugriff ohne Anmeldung), benutzer
("web" = Benutzer des Webservers), zertifikat/schluessel (leer = selbstsigniert, Ordner ``opcua`` im Datenordner).
"""
import asyncio
import json
import math
import os
import socket
import threading
from datetime import datetime, timezone

from plc_i18n import N_, tr

APP_URI = "urn:plc-datenlogger:server"
NS_URI = "urn:plc-datenlogger"
SECURITY = {"none": N_("Keine"),
            "Basic256Sha256,Sign": N_("Signieren"),
            "Basic256Sha256,SignAndEncrypt": N_("Signieren und verschlüsseln"),
            "Aes128Sha256RsaOaep,SignAndEncrypt": N_("Signieren und verschlüsseln"),
            "Aes256Sha256RsaPss,SignAndEncrypt": N_("Signieren und verschlüsseln")}
DEFAULTS = {"aktiv": False, "host": "0.0.0.0", "port": 4840, "intervall_ms": 500, "sicherheit": ["none"],
            "anonym": True, "benutzer": "web", "zertifikat": "", "schluessel": ""}


def settings(raw) -> dict:
    """Einstellung ``opcua_server`` (dict oder JSON-Text) mit Vorgabewerten ergänzt."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except ValueError:
            raw = {}
    out = json.loads(json.dumps(DEFAULTS))
    for k, v in (raw or {}).items():
        if k in out:
            out[k] = v
    if isinstance(out["sicherheit"], str):
        out["sicherheit"] = [p for p in out["sicherheit"].split(";") if p]
    out["sicherheit"] = [p for p in out["sicherheit"] if p in SECURITY] or ["none"]
    return out


def security_label(key):
    """Anzeigetext einer Sicherheitsstufe, z. B. „Basic256Sha256 – Signieren und verschlüsseln“."""
    return tr(SECURITY[key]) if key == "none" else f"{key.split(',')[0]} – {tr(SECURITY[key])}"


def endpoint_url(s, host=None):
    h = host or s.get("host") or "0.0.0.0"
    if h in ("0.0.0.0", "::", ""):
        h = socket.gethostname()
    return f"opc.tcp://{h}:{int(s.get('port') or 4840)}/plc-datenlogger/"


def describe(s) -> str:
    s = settings(s)
    if not s["aktiv"]:
        return tr("aus")
    sec = ", ".join(tr("ohne Sicherheit") if p == "none" else p.replace(",", " ") for p in s["sicherheit"])
    who = tr("anonym") if s["anonym"] else tr("mit Anmeldung")
    return f"{endpoint_url(s)}  ({sec}; {who})"


def server_certificate(s):
    """(Zertifikat, Schlüssel) – angegebene Dateien oder ein automatisch erzeugtes, selbstsigniertes Paar."""
    cert, key = str(s.get("zertifikat", "")).strip(), str(s.get("schluessel", "")).strip()
    if cert and key:
        return cert, key
    from plc_common import BASE_DIR
    folder = os.path.join(BASE_DIR, "opcua")
    cert, key = os.path.join(folder, "server_cert.der"), os.path.join(folder, "server_key.pem")
    if not (os.path.exists(cert) and os.path.exists(key)):
        from pathlib import Path

        from asyncua.crypto.cert_gen import setup_self_signed_certificate
        from cryptography.x509.oid import ExtendedKeyUsageOID
        os.makedirs(folder, exist_ok=True)
        host = socket.gethostname()
        asyncio.run(setup_self_signed_certificate(
            Path(key), Path(cert), APP_URI, host, [ExtendedKeyUsageOID.SERVER_AUTH],
            {"countryName": "DE", "organizationName": "PLC Datenlogger", "commonName": f"PLC Datenlogger@{host}"}))
    return cert, key


class _Users:
    """Anmeldung am OPC-UA-Server mit den Benutzern des Webservers (Passwort-Hash, siehe plc_webauth)."""

    def __init__(self, users, anonymous):
        self.users, self.anonymous = users, anonymous

    def get_user(self, iserver, username=None, password=None, certificate=None):
        from asyncua.server.user_managers import User, UserRole       # beide asyncua-Versionen
        from plc_webauth import check_password
        if username is None:
            return User(role=UserRole.User) if self.anonymous else None
        if username in self.users and check_password(self.users[username], password or ""):
            return User(role=UserRole.User, name=username)
        return None


class OpcUaServer:
    """OPC-UA-Server für die Variablen einer Aufzeichnung. ``update`` (Sammler-Thread) übergibt jede Messzeile;
    veröffentlicht wird im Takt ``intervall_ms`` nur, was sich geändert hat."""

    def __init__(self, conn, variables, plcs, triggers=(), emit=None, status_fn=None):
        self.s = settings(conn.get("opcua_server", "")) if isinstance(conn, dict) else settings(conn)
        self.conn = conn if isinstance(conn, dict) else {}
        self.vars, self.plcs = list(variables), list(plcs)
        self.trigger_names = [t.name for t in triggers]
        self.emit = emit or (lambda _t: None)
        self.status_fn = status_fn or (lambda: [])
        self.lock = threading.Lock()
        self.latest = None                        # (ts, row) der letzten Messzeile
        self.active = {}                          # Trigger -> steht an
        self.thread = None
        self.loop = None
        self.stop_evt = None
        self.ready = threading.Event()
        self.error = ""
        self.url = endpoint_url(self.s)
        self.recording = True

    def __bool__(self):
        return bool(self.s.get("aktiv"))

    # ---- Schnittstelle zum Recorder (andere Threads) ------------------------------------------------------------
    def update(self, ts, row):
        with self.lock:
            self.latest = (ts, row)

    def event(self, kind, trigger, prio, text, ts):
        with self.lock:
            self.active[trigger] = (kind == "KOMMT")

    def start(self, wait_s=10.0):
        """Server starten (eigener Thread); wartet, bis er lauscht oder ein Fehler auftrat -> True bei Erfolg."""
        if not self or self.thread is not None:
            return False
        self.thread = threading.Thread(target=self._thread, name="opcua-server", daemon=True)
        self.thread.start()
        self.ready.wait(wait_s)
        if self.error:
            self.emit(tr("⚠ OPC-UA-Server nicht gestartet: {0}").format(self.error))
            return False
        self.emit(tr("OPC-UA-Server läuft: {0}").format(self.url))
        return True

    def stop(self, wait_s=5.0):
        if self.thread is None:
            return
        if self.loop is not None and self.stop_evt is not None:
            try:
                self.loop.call_soon_threadsafe(self.stop_evt.set)
            except RuntimeError:
                pass
        self.thread.join(wait_s)
        self.thread = None

    # ---- Server-Thread ------------------------------------------------------------------------------------------
    def _thread(self):
        try:
            asyncio.run(self._main())
        except Exception as e:                    # Port belegt, Zertifikat, fehlende Bibliothek …
            self.error = str(e) or type(e).__name__
        finally:
            self.ready.set()

    async def _main(self):
        from asyncua import Server, ua
        from plc_common import APP_VERSION
        from plc_webauth import parse_users
        s = self.s
        users = parse_users(self.conn.get("web_benutzer", "")) if s.get("benutzer") == "web" else {}
        server = Server(user_manager=_Users(users, bool(s.get("anonym"))))
        await server.init()
        project = self.conn.get("projekt", "") or ""
        server.set_server_name("PLC Datenlogger" + (f" – {project}" if project else ""))
        server.set_endpoint(f"opc.tcp://{s.get('host') or '0.0.0.0'}:{int(s.get('port') or 4840)}/plc-datenlogger/")
        await server.set_application_uri(APP_URI)
        try:
            await server.set_build_info("urn:plc-datenlogger", "PLC Datenlogger", "PLC Datenlogger", APP_VERSION,
                                        "", datetime.now(timezone.utc))
        except Exception:
            pass
        policies = []
        for p in s["sicherheit"]:
            if p == "none":
                policies.append(ua.SecurityPolicyType.NoSecurity)
            else:
                name, mode = p.split(",")
                policies.append(getattr(ua.SecurityPolicyType, f"{name}_{mode}"))
        server.set_security_policy(policies)
        if any(p != "none" for p in s["sicherheit"]):
            cert, key = await asyncio.to_thread(server_certificate, s)
            await server.load_certificate(cert)
            await server.load_private_key(key)
        tokens = ([ua.AnonymousIdentityToken] if s.get("anonym") else []) + \
                 ([ua.UserNameIdentityToken] if users else [])
        if not tokens:
            raise ValueError(tr("weder anonymer Zugriff noch Benutzer eingerichtet"))
        server.set_identity_tokens(tokens)
        idx = await server.register_namespace(NS_URI)

        # Adressraum
        root = await server.nodes.objects.add_folder(ua.NodeId("PLC Datenlogger", idx), "PLC Datenlogger")
        folders = {}

        async def folder(key, name):              # NodeId fest (Ordner:<key>), Anzeigename ggf. übersetzt
            if key not in folders:
                folders[key] = await root.add_folder(ua.NodeId(f"Ordner:{key}", idx), name)
            return folders[key]

        self.nodes = []                           # (Index der Variable, NodeId, Variant-Typ)
        used = set()
        for i, v in enumerate(self.vars):
            plc_name = self.plcs[v.plc].name if 0 <= v.plc < len(self.plcs) else f"SPS {v.plc + 1}"
            parent = await (folder("Berechnet", tr("Berechnet")) if v.formula else folder(plc_name, plc_name))
            key = v.name if v.name not in used else f"{v.name}#{i}"
            used.add(key)
            vt = ua.VariantType.Boolean if v.dtype == "BOOL" and not v.formula else ua.VariantType.Double
            node = await parent.add_variable(ua.NodeId(key, idx), v.name,
                                             ua.Variant(False if vt == ua.VariantType.Boolean else 0.0, vt))
            desc = v.formula and tr("Berechnet: {0}").format(v.formula) or f"{v.address} ({v.dtype})"
            try:
                await node.write_attribute(ua.AttributeIds.Description,
                                           ua.DataValue(ua.Variant(ua.LocalizedText(desc), ua.VariantType.LocalizedText)))
            except Exception:
                pass
            await server.write_attribute_value(node.nodeid, ua.DataValue(
                ua.Variant(False if vt == ua.VariantType.Boolean else math.nan, vt),
                ua.StatusCode(ua.StatusCodes.BadWaitingForInitialData)))
            self.nodes.append((i, node.nodeid, vt))
        ev_nodes = {}
        if self.trigger_names:
            ev_folder = await root.add_folder(ua.NodeId("Ordner:Ereignisse", idx), tr("Ereignisse"))
            for name in self.trigger_names:
                ev_nodes[name] = (await ev_folder.add_variable(ua.NodeId(f"Ereignis:{name}", idx), name, False)).nodeid
        st_folder = await root.add_folder(ua.NodeId("Ordner:Status", idx), "Status")
        st_nodes = []
        for k, plc in enumerate(self.plcs):
            ok = await st_folder.add_variable(ua.NodeId(f"Status:{k}", idx), plc.name, False)
            txt = await st_folder.add_variable(ua.NodeId(f"Status:{k}:Text", idx), f"{plc.name}_Text", "")
            st_nodes.append((ok.nodeid, txt.nodeid))
        ts_node = (await st_folder.add_variable(ua.NodeId("Status:Zeitstempel", idx), tr("Zeitstempel"),
                                                ua.Variant(datetime.now(timezone.utc), ua.VariantType.DateTime))).nodeid
        rec_node = (await st_folder.add_variable(ua.NodeId("Status:Aufzeichnung", idx), tr("Aufzeichnung"),
                                                 True)).nodeid

        self.loop = asyncio.get_running_loop()
        self.stop_evt = asyncio.Event()
        async with server:
            self.ready.set()
            last_vals, last_ev, last_st = {}, {}, {}
            self._last_ts = None
            period = max(0.05, float(s.get("intervall_ms") or 500) / 1000.0)
            failed = False
            while not self.stop_evt.is_set():
                try:
                    await self._publish(server, ua, last_vals, last_ev, last_st, ev_nodes, st_nodes, ts_node)
                    failed = False
                except Exception as e:            # nicht abbrechen: beim nächsten Takt erneut versuchen
                    if not failed:
                        self.emit(tr("⚠ OPC-UA-Server: {0}").format(e))
                    failed = True
                try:
                    await asyncio.wait_for(self.stop_evt.wait(), period)
                except asyncio.TimeoutError:
                    pass
            await server.write_attribute_value(rec_node, ua.DataValue(ua.Variant(False, ua.VariantType.Boolean)))
            await asyncio.sleep(0.05)

    async def _publish(self, server, ua, last_vals, last_ev, last_st, ev_nodes, st_nodes, ts_node):
        """Geänderte Werte, Ereignisse und Zustände in den Adressraum schreiben."""
        with self.lock:
            latest, active = self.latest, dict(self.active)
        if latest is not None and latest[0] != self._last_ts:
            ts, row = latest
            self._last_ts = ts
            when = datetime.fromtimestamp(ts, timezone.utc)
            for i, nid, vt in self.nodes:
                x = float(row[i]) if i < len(row) else math.nan
                bad = math.isnan(x)
                val = (bool(x) if vt == ua.VariantType.Boolean else x) if not bad else \
                    (False if vt == ua.VariantType.Boolean else math.nan)
                prev = last_vals.get(i)
                if prev is not None and prev[0] == bad and (bad or prev[1] == val):
                    continue
                last_vals[i] = (bad, val)
                sc = ua.StatusCode(ua.StatusCodes.BadNoCommunication if bad else ua.StatusCodes.Good)
                await server.write_attribute_value(nid, ua.DataValue(ua.Variant(val, vt), sc, when))
            await server.write_attribute_value(ts_node, ua.DataValue(ua.Variant(when, ua.VariantType.DateTime)))
        for name, on in active.items():
            if name in ev_nodes and last_ev.get(name) != on:
                last_ev[name] = on
                await server.write_attribute_value(ev_nodes[name], ua.DataValue(ua.Variant(on, ua.VariantType.Boolean)))
        for k, (state, text) in enumerate(self.status_fn() or []):
            if k < len(st_nodes) and last_st.get(k) != (state, text):
                last_st[k] = (state, text)
                await server.write_attribute_value(st_nodes[k][0], ua.DataValue(
                    ua.Variant(state == "ok", ua.VariantType.Boolean)))
                await server.write_attribute_value(st_nodes[k][1], ua.DataValue(
                    ua.Variant(str(text), ua.VariantType.String)))

