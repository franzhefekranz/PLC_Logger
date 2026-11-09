# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""ADS-Verbindung Schritt für Schritt prüfen – für Rückmeldungen, wenn der Treiber „ads“ keine Verbindung bekommt.

Nur Python-Standardbibliothek, läuft ohne den Logger:

    python ads_diagnose.py                        # TwinCAT auf diesem Rechner (127.0.0.1, AMS-Net-ID vom Router)
    python ads_diagnose.py 172.22.15.10.1.1       # AMS-Net-ID der Steuerung angeben
    python ads_diagnose.py 172.22.15.10.1.1 851 192.168.0.20   # Port und IP einer entfernten Steuerung

Schritte: TCP-Verbindung zum AMS-Router (Port 48898) – bei 127.0.0.1 Anmeldung beim lokalen Router (0x1000) –
ADS ReadState an die SPS-Laufzeit – Größe der Symboltabelle. Jede Antwort wird ausgegeben (auch als Hex).
"""
import socket
import struct
import sys

AMS_TCP_PORT = 48898


def hexdump(b):
    """Bytes als Hex-Text (höchstens 64 Bytes, danach „…“)."""
    return " ".join(f"{x:02x}" for x in b[:64]) + (" …" if len(b) > 64 else "")


def netid(text):
    """AMS-Net-ID als Text (6 Zahlen 0…255, durch Punkte getrennt) -> 6 Bytes."""
    parts = [int(p) for p in text.split(".")]
    if len(parts) != 6 or not all(0 <= p <= 255 for p in parts):
        raise SystemExit(f"Ungültige AMS-Net-ID: {text}")
    return bytes(parts)


def recv_exact(s, n):
    """Genau ``n`` Bytes empfangen (TCP liefert ggf. in Teilen)."""
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Verbindung vom Router getrennt")
        buf += chunk
    return buf


def recv_frame(s):
    """Ein AMS/TCP-Paket empfangen: 2 Byte Befehl, 4 Byte Länge, dann die Daten -> (Befehl, Daten)."""
    cmd, length = struct.unpack("<HI", recv_exact(s, 6))
    return cmd, recv_exact(s, length)


def main():
    """Schritte nacheinander ausführen und jedes Ergebnis ausgeben; bricht beim ersten Fehler mit Hinweis ab."""
    target_text = sys.argv[1] if len(sys.argv) > 1 else ""
    ams_port = int(sys.argv[2]) if len(sys.argv) > 2 else 851
    host = sys.argv[3] if len(sys.argv) > 3 else "127.0.0.1"
    print(f"Python {sys.version.split()[0]}, Ziel {host}:{AMS_TCP_PORT}, AMS-Port {ams_port}")
    s = socket.create_connection((host, AMS_TCP_PORT), timeout=5)
    s.settimeout(5)
    print(f"1. TCP verbunden: lokal {s.getsockname()}, Gegenstelle {s.getpeername()}")
    if host in ("127.0.0.1", "localhost", "::1"):
        # Befehl 0x1000 (PORT_CONNECT) mit Wunschport 0: der lokale Router teilt Net-ID und einen freien Port zu
        s.sendall(struct.pack("<HIH", 0x1000, 2, 0))
        print("2. Anmeldung beim lokalen Router gesendet (0x1000) …")
        try:
            cmd, body = recv_frame(s)
        except (OSError, ConnectionError) as e:
            raise SystemExit(f"   KEINE Antwort: {e}  -> AMS TCP Loopback aktiv? TwinCAT nach dem Registry-Eintrag "
                             "neu gestartet (System-Dienst bzw. Rechner)?")
        print(f"   Antwort: Befehl 0x{cmd:04x}, {len(body)} Bytes: {hexdump(body)}")
        if cmd != 0x1000 or len(body) < 8:
            raise SystemExit("   Unerwartete Antwort")
        source, source_port = body[:6], struct.unpack_from("<H", body, 6)[0]
        print(f"   Zugeteilt: AMS-Net-ID {'.'.join(map(str, source))}, Port {source_port}")
        target = netid(target_text) if target_text else source
    else:
        local = s.getsockname()[0]
        source, source_port = netid(f"{local}.1.1"), 32905
        target = netid(target_text or f"{host}.1.1")
        print(f"2. Entfernte Steuerung, Absender {local}.1.1:32905 (Route in TwinCAT nötig)")
    print(f"3. ADS ReadState an {'.'.join(map(str, target))}:{ams_port} …")
    # AMS-Kopf: Ziel-Net-ID und -Port, Absender-Net-ID und -Port, Befehl 4 = ReadState, Status 0x0004 = Anfrage,
    # Datenlänge 0, Fehler 0, Rufnummer 1
    hdr = target + struct.pack("<H", ams_port) + source + struct.pack("<H", source_port) + \
        struct.pack("<HHIII", 4, 0x0004, 0, 0, 1)
    s.sendall(struct.pack("<HI", 0, len(hdr)) + hdr)
    while True:
        try:
            cmd, body = recv_frame(s)
        except (OSError, ConnectionError) as e:
            raise SystemExit(f"   KEINE Antwort: {e}")
        print(f"   Antwort: Befehl 0x{cmd:04x}, {len(body)} Bytes: {hexdump(body)}")
        if cmd == 0 and len(body) >= 32:
            break
    err = struct.unpack_from("<I", body, 24)[0]
    if err:
        raise SystemExit(f"   ADS-Fehler im Kopf: 0x{err:x}")
    res, ads_state, dev_state = struct.unpack_from("<IHH", body, 32)
    print(f"   Ergebnis 0x{res:x}, ADS-Zustand {ads_state} (5 = RUN), Gerätezustand {dev_state}")
    print("4. Symboltabelle: Größe abfragen …")
    # ADS Read: Index-Gruppe 0xF00F (Symbol-Upload-Info), Offset 0, 24 Byte -> Zahl und Größe der Symbole
    req = struct.pack("<III", 0xF00F, 0, 24)
    hdr = target + struct.pack("<H", ams_port) + source + struct.pack("<H", source_port) + \
        struct.pack("<HHIII", 2, 0x0004, len(req), 0, 2)
    s.sendall(struct.pack("<HI", 0, len(hdr) + len(req)) + hdr + req)
    while True:
        cmd, body = recv_frame(s)
        if cmd == 0 and len(body) >= 32:
            break
    res = struct.unpack_from("<I", body, 32)[0]
    if res:
        raise SystemExit(f"   ADS-Fehler 0x{res:x}")
    n_sym, size = struct.unpack_from("<II", body, 40)
    print(f"   {n_sym} Symbole, {size} Bytes – Verbindung in Ordnung.")
    if host in ("127.0.0.1", "localhost", "::1"):
        # Befehl 0x0001 (PORT_CLOSE): zugeteilten Port beim lokalen Router wieder freigeben
        s.sendall(struct.pack("<HIH", 0x0001, 2, source_port))
    s.close()


if __name__ == "__main__":
    main()
