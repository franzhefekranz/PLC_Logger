# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Netzwerk nach erreichbaren Steuerungen durchsuchen (ohne Oberfläche).

Gesucht wird in einem Adressbereich (Standard: das /24-Netz des eigenen Rechners) auf zwei Wegen:

1. **EtherNet/IP „List Identity“** als Rundruf (UDP 44818): Allen-Bradley-Steuerungen und andere EtherNet/IP-Geräte
   melden sich mit Produktname, Hersteller und Seriennummer.
2. **TCP-Verbindungsversuch** auf die typischen Ports der Treiber – viele Adressen gleichzeitig, mit kurzem Zeitlimit:

   =====  =========================  ==============
   Port   Protokoll                  Treiber
   =====  =========================  ==============
   102    S7 / ISO-on-TCP (+ LOGO!)  s7 (bzw. tia)
   502    Modbus TCP                 modbus
   44818  EtherNet/IP                clx
   4840   OPC UA                     opcua
   48898  Beckhoff ADS               ads
   9600   Omron FINS                 fins
   5007   Mitsubishi SLMP            slmp
   8501   Keyence KV Host Link       kvhostlink
   =====  =========================  ==============

Antwortet Port 102, liest die Suche – falls python-snap7 vorhanden ist – die Kennung der CPU (Baugruppentyp, Name der
Station; Rack 0, Steckplatz 1, 2 oder 3). S7-1200/1500 werden dann für den Treiber ``tia`` vorgeschlagen.

Das Ergebnis sind ``Found``-Einträge mit einem Vorschlag für Treiber und Verbindungsparameter, die das
Konfigurationsprogramm als neue Steuerungen übernimmt. Geräte hinter Routern werden nur gefunden, wenn ihr Bereich
angegeben ist; der Rundruf erreicht nur das eigene Netz. Ein Port, der nicht antwortet, kann auch durch eine Firewall
gesperrt sein.
"""
import ipaddress
import socket
import struct
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from plc_i18n import tr

# Port -> (Protokoll, Treiber)
PORTS = {
    102: ("S7 / ISO-on-TCP", "s7"),
    502: ("Modbus TCP", "modbus"),
    44818: ("EtherNet/IP", "clx"),
    4840: ("OPC UA", "opcua"),
    48898: ("Beckhoff ADS", "ads"),
    9600: ("Omron FINS", "fins"),
    5007: ("Mitsubishi SLMP", "slmp"),
    8501: ("Keyence KV", "kvhostlink"),
}
# Reihenfolge für den Treibervorschlag, wenn ein Gerät mehrere Ports anbietet (z. B. S7-1500 mit OPC-UA-Server)
PRIORITY = (102, 44818, 48898, 9600, 5007, 8501, 502, 4840)


def _prio(port):
    """Rang eines Ports für den Treibervorschlag (unbekannte Ports zuletzt)."""
    return PRIORITY.index(port) if port in PRIORITY else len(PRIORITY) + port
MAX_HOSTS = 4096
ENIP_PORT = 44818


@dataclass
class Found:
    """Ein gefundenes Gerät."""
    ip: str
    ports: list = field(default_factory=list)       # offene Ports (aus PORTS)
    device: str = ""                                 # Produktname / Baugruppentyp, falls ermittelt
    details: str = ""                                # weitere Angaben (Hersteller, Seriennummer, Station …)
    driver: str = ""                                 # vorgeschlagener Treiber
    params: dict = field(default_factory=dict)       # vorgeschlagene Verbindungsparameter

    @property
    def protocols(self):
        """Protokolle als Text, z. B. „S7 / ISO-on-TCP, OPC UA“."""
        return ", ".join(PORTS[p][0] for p in sorted(self.ports, key=_prio) if p in PORTS)


# ---------------------------------------------------------------------------------------
# Adressbereich
# ---------------------------------------------------------------------------------------
def local_ipv4():
    """IPv4-Adresse des Rechners in Richtung Netzwerk (ohne Daten zu senden) oder ""."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            return "" if ip.startswith("127.") else ip
    except OSError:
        return ""


def default_range():
    """Vorschlag für den Suchbereich: das /24-Netz der eigenen Adresse (z. B. 192.168.0.0/24)."""
    ip = local_ipv4()
    if not ip:
        return "192.168.0.0/24"
    return str(ipaddress.ip_network(ip + "/24", strict=False))


def parse_targets(text):
    """Bereichsangabe -> Liste von IPv4-Adressen.

    Erlaubt (durch Komma oder Leerzeichen getrennt): ``192.168.0.0/24``, ``192.168.0.10-50``,
    ``192.168.0.10-192.168.0.80`` und einzelne Adressen. Höchstens ``MAX_HOSTS`` Adressen; ValueError bei Fehlern."""
    out = []
    for part in text.replace(";", ",").replace(" ", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "/" in part:
                net = ipaddress.ip_network(part, strict=False)
                if net.version != 4:
                    raise ValueError
                if net.num_addresses > MAX_HOSTS + 2:
                    raise OverflowError
                hosts = list(net.hosts()) if net.num_addresses > 2 else list(net)
                out += [str(h) for h in hosts]
            elif "-" in part:
                a, b = part.split("-", 1)
                first = ipaddress.IPv4Address(a.strip())
                b = b.strip()
                last = ipaddress.IPv4Address(b) if "." in b else ipaddress.IPv4Address(
                    ".".join(a.strip().split(".")[:3] + [b]))
                if int(last) < int(first):
                    raise ValueError
                if int(last) - int(first) >= MAX_HOSTS:
                    raise OverflowError
                out += [str(ipaddress.IPv4Address(n)) for n in range(int(first), int(last) + 1)]
            else:
                out.append(str(ipaddress.IPv4Address(part)))
        except OverflowError:
            raise ValueError(tr("Bereich zu groß (höchstens {0} Adressen)").format(MAX_HOSTS)) from None
        except ValueError:
            raise ValueError(tr("Ungültiger Bereich „{0}“ (z. B. 192.168.0.0/24 oder 192.168.0.10-50)")
                             .format(part)) from None
    out = list(dict.fromkeys(out))
    if len(out) > MAX_HOSTS:
        raise ValueError(tr("Bereich zu groß (höchstens {0} Adressen)").format(MAX_HOSTS))
    return out


def broadcasts(text):
    """Rundruf-Adressen der Netze im Bereich (nur Netzangaben wie /24) bzw. 255.255.255.255."""
    out = []
    for part in text.replace(";", ",").replace(" ", ",").split(","):
        if "/" in part:
            try:
                net = ipaddress.ip_network(part.strip(), strict=False)
                if net.version == 4 and net.prefixlen < 31:
                    out.append(str(net.broadcast_address))
            except ValueError:
                pass
    return out or ["255.255.255.255"]


# ---------------------------------------------------------------------------------------
# EtherNet/IP List Identity
# ---------------------------------------------------------------------------------------
def enip_request():
    """Anfrage „List Identity“ (Kapselungskopf, Befehl 0x63, ohne Daten)."""
    return struct.pack("<HHII8sI", 0x63, 0, 0, 0, b"PLCSCAN\0", 0)


def parse_list_identity(data):
    """Antwort auf „List Identity“ -> dict (ip, vendor, device_type, product_code, revision, serial, name) oder None."""
    try:
        cmd, length = struct.unpack_from("<HH", data, 0)
        if cmd != 0x63 or len(data) < 24 + 2:
            return None
        count = struct.unpack_from("<H", data, 24)[0]
        off = 26
        for _ in range(count):
            typ, ln = struct.unpack_from("<HH", data, off)
            item = data[off + 4:off + 4 + ln]
            off += 4 + ln
            if typ != 0x0C:
                continue
            # Protokollversion (2), Socket-Adresse (16, Big Endian), Hersteller, Gerätetyp, Produktcode, Revision (2 Bytes),
            # Status, Seriennummer, Produktname (Länge + Text), Zustand
            ip = socket.inet_ntoa(item[6:10])
            vendor, dtype, pcode, rmaj, rmin, _status, serial = struct.unpack_from("<HHHBBHI", item, 18)
            nlen = item[32]
            name = item[33:33 + nlen].decode("ascii", "replace").strip()
            return {"ip": ip, "vendor": vendor, "device_type": dtype, "product_code": pcode,
                    "revision": f"{rmaj}.{rmin:03d}", "serial": f"{serial:08X}", "name": name}
    except (struct.error, IndexError, OSError):
        return None
    return None


VENDORS = {1: "Rockwell Automation / Allen-Bradley", 47: "Omron", 161: "Mitsubishi", 283: "Hilscher",
           356: "Beckhoff", 674: "Wago", 1251: "Siemens"}


def enip_discover(targets, timeout=1.0, unicast=()):
    """List Identity an Rundruf-Adressen und einzelne Adressen senden -> {IP: Antwort}."""
    found = {}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        return found
    with s:
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError:
            pass
        s.settimeout(0.2)
        req = enip_request()
        for addr in list(targets) + list(unicast):
            try:
                s.sendto(req, (addr, ENIP_PORT))
            except OSError:
                continue
        import time
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                data, (src, _port) = s.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            info = parse_list_identity(data)
            if info:
                found[src] = info
    return found


# ---------------------------------------------------------------------------------------
# Portsuche und Kennung
# ---------------------------------------------------------------------------------------
def port_open(ip, port, timeout):
    """True, wenn eine TCP-Verbindung zu ip:port zustande kommt."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def s7_identity(ip, timeout=1.5):
    """Kennung einer S7-CPU (python-snap7): {"device", "station", "slot", "order"} oder {} (nicht lesbar)."""
    try:
        from snap7.client import Client
    except Exception:
        return {}
    for slot in (1, 2, 3, 0):
        c = Client()
        try:
            try:
                c.set_param(4, int(timeout * 1000))        # Ping-Timeout (falls die Bibliothek ihn kennt)
            except Exception:
                pass
            c.connect(ip, 0, slot)
            info = c.get_cpu_info()

            def txt(v):
                return (v.decode("ascii", "replace") if isinstance(v, bytes) else str(v or "")).strip("\x00 ")
            out = {"device": txt(getattr(info, "ModuleTypeName", "")), "station": txt(getattr(info, "ASName", "")),
                   "module": txt(getattr(info, "ModuleName", "")), "slot": slot}
            try:
                oc = c.get_order_code()
                out["order"] = txt(getattr(oc, "OrderCode", ""))
            except Exception:
                pass
            return out
        except Exception:
            continue
        finally:
            try:
                c.disconnect()
            except Exception:
                pass
    return {}


def suggest(f, s7=None, enip=None):
    """Treiber und Parameter für ein Gerät vorschlagen (setzt f.driver, f.params, f.device, f.details)."""
    ports = sorted(f.ports, key=_prio)
    if enip:
        f.device = enip.get("name") or f.device
        f.details = ", ".join(x for x in (VENDORS.get(enip.get("vendor"), ""), tr("Rev. {0}").format(enip["revision"]),
                                          tr("Serien-Nr. {0}").format(enip["serial"])) if x)
    if s7:
        f.device = s7.get("device") or s7.get("module") or f.device
        f.details = ", ".join(x for x in (s7.get("order", ""), tr("Station {0}").format(s7["station"])
                                          if s7.get("station") else "", tr("Steckplatz {0}").format(s7["slot"])) if x)
    if not ports and enip:
        ports = [ENIP_PORT]
    if not ports:
        return f
    p = ports[0]
    if p not in PORTS:
        return f
    drv = PORTS[p][1]
    params = {"ip": f.ip}
    if p == 102:
        dev = (f.device or "").upper()
        if s7 and any(k in dev for k in ("1500", "1200", "CPU 15", "CPU 12", "ET 200SP", "1510", "1511", "1512",
                                         "1513", "1515", "1516", "1517", "1518", "1211", "1212", "1214", "1215",
                                         "1217")):
            drv = "tia"                                  # S7-1200/1500: symbolisch, ohne PUT/GET
        elif s7:
            params.update(rack=0, slot=int(s7.get("slot", 2)))
        else:
            params.update(rack=0, slot=1)
    elif p == 44818:
        name = (f.device or "").upper()
        params.update(pfad="1,0", cpu="compactlogix" if "CompactLogix".upper() in name or "5069" in name
                      or "1769" in name else "controllogix")
        if "MICRO8" in name or "2080" in name:
            params.update(pfad="", cpu="micro800")
    elif p == 4840:
        params = {"endpoint": f"opc.tcp://{f.ip}:4840"}
    elif p == 48898:
        params.update(ams_netid=f"{f.ip}.1.1")
    elif p in (9600, 5007, 8501, 502):
        params.update(port=p)
    f.driver, f.params = drv, params
    return f


def scan(range_text, ports=None, timeout=0.4, workers=128, progress=None, cancel=None, identify=True):
    """Bereich durchsuchen -> Liste von ``Found`` (nach Adresse sortiert).

    ``progress(erledigt, gesamt)`` meldet den Fortschritt, ``cancel()`` -> True bricht ab. ``identify``: Kennung von
    S7-CPUs und EtherNet/IP-Geräten lesen."""
    hosts = parse_targets(range_text)
    ports = list(ports or PORTS)
    lock = threading.Lock()
    open_ports = {}
    enip = {}
    if identify and ENIP_PORT in ports:
        enip = enip_discover(broadcasts(range_text), timeout=1.0)
        enip = {ip: v for ip, v in enip.items() if ip in set(hosts)}
    jobs = [(h, p) for h in hosts for p in ports]
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as ex:
        futs = {}
        for h, p in jobs:
            if cancel is not None and cancel():
                break
            futs[ex.submit(port_open, h, p, timeout)] = (h, p)
        for fut in as_completed(futs):
            h, p = futs[fut]
            if fut.result():
                with lock:
                    open_ports.setdefault(h, []).append(p)
            done += 1
            if progress is not None and done % 32 == 0:
                progress(done, len(jobs))
            if cancel is not None and cancel():
                for f in futs:
                    f.cancel()
                break
    if progress is not None:
        progress(len(jobs), len(jobs))
    results = []
    ips = sorted(set(open_ports) | set(enip), key=lambda x: tuple(int(n) for n in x.split(".")))
    # Kennung nachlesen: EtherNet/IP ohne Rundruf-Antwort per Unicast, S7 über snap7 (parallel, mit Zeitlimit)
    if identify:
        missing = [ip for ip in ips if ENIP_PORT in open_ports.get(ip, []) and ip not in enip]
        if missing:
            enip.update(enip_discover([], timeout=0.8, unicast=missing))
    s7 = {}
    if identify:
        s7_hosts = [ip for ip in ips if 102 in open_ports.get(ip, [])]
        with ThreadPoolExecutor(max_workers=16) as ex:
            for ip, info in zip(s7_hosts, ex.map(s7_identity, s7_hosts)):
                s7[ip] = info
    for ip in ips:
        f = Found(ip=ip, ports=sorted(open_ports.get(ip, []), key=_prio))
        results.append(suggest(f, s7=s7.get(ip), enip=enip.get(ip)))
    return results
