# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Netzwerk anzeigen und einstellen (für das Touch-Panel ``plc_netpanel`` auf Raspberry Pi & Co., ohne Oberfläche).

Gelesen und geschrieben wird über NetworkManager (Befehl ``nmcli``); ohne NetworkManager zeigt das Panel nur die
Adressen an (``ip -j addr``). Alle Befehle laufen über ``Netz.run`` – in Tests ein Ersatz, der Antworten liefert und die
Befehle mitschreibt.

    netz = Netz()
    netz.devices()                       # [Device(name="eth0", typ="ethernet", state="connected", …, ipv4=[…])]
    netz.set_ipv4("eth0", dhcp=False, address="192.168.0.50/24", gateway="192.168.0.1", dns="192.168.0.1")
    netz.wifi_list()                     # [Wifi(ssid="Büro", signal=72, security="WPA2", active=False)]
    netz.wifi_connect("Büro", "geheim")

Die Einstellungen gelten dauerhaft (Verbindungsprofil von NetworkManager, auch nach dem Neustart).
"""
import ipaddress
import json
import shutil
import socket
import subprocess
from dataclasses import dataclass, field

from plc_i18n import tr


@dataclass
class Device:
    """Eine Netzwerkschnittstelle mit Zustand und IPv4-Einstellungen."""
    name: str
    typ: str = ""                    # ethernet, wifi, …
    state: str = ""                  # connected, disconnected, unavailable, …
    connection: str = ""             # Name des aktiven Verbindungsprofils
    ipv4: list = field(default_factory=list)       # ["192.168.0.50/24"]
    gateway: str = ""
    dns: list = field(default_factory=list)
    method: str = ""                 # auto (DHCP) oder manual

    @property
    def dhcp(self):
        return self.method != "manual"


@dataclass
class Wifi:
    """Ein gefundenes WLAN."""
    ssid: str
    signal: int = 0
    security: str = ""
    active: bool = False


def _split(line):
    """Zeile der Ausgabe von ``nmcli -t`` an ``:`` trennen (``\\:`` ist ein Doppelpunkt im Wert)."""
    out, cur, esc = [], "", False
    for ch in line:
        if esc:
            cur += ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def check_ipv4(address, gateway="", dns=""):
    """Eingaben prüfen -> Fehlertext oder "". ``address`` mit Präfix (192.168.0.50/24) oder Maske (/255.255.255.0)."""
    try:
        iface = ipaddress.IPv4Interface(address.strip())
    except ValueError:
        return tr("Ungültige IP-Adresse „{0}“ (z. B. 192.168.0.50/24)").format(address)
    if "/" not in address:
        return tr("Bitte das Präfix angeben, z. B. 192.168.0.50/24")
    if iface.ip == iface.network.network_address or iface.ip == iface.network.broadcast_address:
        return tr("Die Adresse {0} ist die Netz- bzw. Broadcast-Adresse").format(iface.ip)
    if gateway.strip():
        try:
            gw = ipaddress.IPv4Address(gateway.strip())
        except ValueError:
            return tr("Ungültiges Gateway „{0}“").format(gateway)
        if gw not in iface.network:
            return tr("Das Gateway {0} liegt nicht im Netz {1}").format(gw, iface.network)
    for d in dns.replace(",", " ").split():
        try:
            ipaddress.IPv4Address(d)
        except ValueError:
            return tr("Ungültiger DNS-Server „{0}“").format(d)
    return ""


def normalize_address(address):
    """192.168.0.50/255.255.255.0 -> 192.168.0.50/24."""
    return str(ipaddress.IPv4Interface(address.strip()).with_prefixlen)


class Netz:
    """Zugriff auf NetworkManager (nmcli) bzw. ``ip`` (nur lesen)."""

    def __init__(self, run=None):
        """``run(args) -> stdout`` ersetzt den Aufruf der Befehle (Tests); Fehler als RuntimeError mit Meldung."""
        self.run = run or self._run

    @staticmethod
    def _run(args, timeout=30):
        """Befehl ausführen -> Ausgabe; bei Fehler RuntimeError mit der Meldung des Befehls."""
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            raise RuntimeError((p.stderr or p.stdout or "").strip() or f"{args[0]}: {p.returncode}")
        return p.stdout

    def has_nm(self):
        """Ist NetworkManager vorhanden und läuft?"""
        if self.run is self._run and not shutil.which("nmcli"):
            return False
        try:
            return self.run(["nmcli", "-t", "-f", "RUNNING", "general"]).strip() == "running"
        except (RuntimeError, OSError, subprocess.SubprocessError):
            return False

    # ------------------------------------------------------------------ lesen
    def devices(self):
        """Ethernet- und WLAN-Schnittstellen mit Zustand und IPv4 (ohne loopback, Docker, Brücken)."""
        if not self.has_nm():
            return self._devices_ip()
        out = []
        for line in self.run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"]).splitlines():
            parts = _split(line)
            if len(parts) < 4 or parts[1] not in ("ethernet", "wifi"):
                continue
            d = Device(parts[0], parts[1], parts[2], parts[3])
            try:
                show = self.run(["nmcli", "-t", "-f", "IP4.ADDRESS,IP4.GATEWAY,IP4.DNS", "device", "show", d.name])
            except RuntimeError:
                show = ""
            for row in show.splitlines():
                key, _, val = row.partition(":")
                if key.startswith("IP4.ADDRESS") and val:
                    d.ipv4.append(val)
                elif key == "IP4.GATEWAY" and val and val != "--":
                    d.gateway = val
                elif key.startswith("IP4.DNS") and val:
                    d.dns.append(val)
            if d.connection and d.connection != "--":
                try:
                    d.method = self.run(["nmcli", "-g", "ipv4.method", "connection", "show", d.connection]).strip()
                except RuntimeError:
                    pass
            else:
                d.connection = ""
            out.append(d)
        return out

    def _devices_ip(self):
        """Nur lesen über ``ip -j addr`` (ohne NetworkManager)."""
        try:
            data = json.loads(self.run(["ip", "-j", "-4", "addr"]) or "[]")
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError):
            return []
        out = []
        for it in data:
            name = it.get("ifname", "")
            if name == "lo" or name.startswith(("docker", "br-", "veth")):
                continue
            typ = "wifi" if name.startswith(("wl", "wlan")) else "ethernet"
            addrs = [f"{a['local']}/{a['prefixlen']}" for a in it.get("addr_info", []) if a.get("family") == "inet"]
            out.append(Device(name, typ, "connected" if addrs else "disconnected", "", addrs))
        return out

    def wifi_list(self, rescan=True):
        """Sichtbare WLANs, stärkstes zuerst, jede SSID einmal."""
        args = ["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,SECURITY", "device", "wifi", "list"]
        if rescan:
            args += ["--rescan", "yes"]
        best = {}
        for line in self.run(args).splitlines():
            parts = _split(line)
            if len(parts) < 4 or not parts[1]:
                continue
            w = Wifi(parts[1], int(parts[2] or 0), parts[3], parts[0] == "yes")
            old = best.get(w.ssid)
            if old is None or w.active or (w.signal > old.signal and not old.active):
                best[w.ssid] = w
        return sorted(best.values(), key=lambda w: (not w.active, -w.signal))

    def wifi_enabled(self):
        return self.run(["nmcli", "-t", "radio", "wifi"]).strip() == "enabled"

    # ------------------------------------------------------------------ einstellen
    def set_wifi_enabled(self, on):
        self.run(["nmcli", "radio", "wifi", "on" if on else "off"])

    def wifi_connect(self, ssid, password="", device=""):
        """Mit einem WLAN verbinden (legt ein Profil an bzw. aktualisiert es)."""
        args = ["nmcli", "device", "wifi", "connect", ssid]
        if password:
            args += ["password", password]
        if device:
            args += ["ifname", device]
        self.run(args)

    def _profile(self, dev):
        """Verbindungsprofil der Schnittstelle (aktiv oder neu angelegt) -> Name."""
        if dev.connection:
            return dev.connection
        if dev.typ != "ethernet":
            raise RuntimeError(tr("{0}: keine aktive Verbindung – zuerst ein WLAN wählen").format(dev.name))
        name = f"PLC {dev.name}"
        self.run(["nmcli", "connection", "add", "type", "ethernet", "ifname", dev.name, "con-name", name,
                  "autoconnect", "yes"])
        return name

    def set_ipv4(self, device, dhcp=True, address="", gateway="", dns=""):
        """IPv4 einer Schnittstelle: DHCP oder feste Adresse; danach die Verbindung neu aufbauen."""
        dev = next((d for d in self.devices() if d.name == device), None)
        if dev is None:
            raise RuntimeError(tr("Schnittstelle {0} nicht gefunden").format(device))
        if not dhcp:
            err = check_ipv4(address, gateway, dns)
            if err:
                raise ValueError(err)
        con = self._profile(dev)
        if dhcp:
            args = ["ipv4.method", "auto", "ipv4.addresses", "", "ipv4.gateway", "", "ipv4.dns", ""]
        else:
            args = ["ipv4.method", "manual", "ipv4.addresses", normalize_address(address),
                    "ipv4.gateway", gateway.strip(), "ipv4.dns", " ".join(dns.replace(",", " ").split())]
        self.run(["nmcli", "connection", "modify", con] + args)
        self.run(["nmcli", "connection", "up", con])


def hostname():
    return socket.gethostname()


def service_state(name="plc-datenlogger"):
    """Zustand eines systemd-Dienstes (active, inactive, failed …) oder "" ohne systemd."""
    if not shutil.which("systemctl"):
        return ""
    try:
        p = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=5)
        return p.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
