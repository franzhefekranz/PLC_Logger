# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Kleiner MQTT-3.1.1-Broker für die Tests (ohne Zusatzbibliothek, läuft unter Windows, Linux, macOS).

Kann: CONNECT (optional mit Benutzer/Passwort), SUBSCRIBE mit „+“/„#“, PUBLISH QoS 0/1 (an Abonnenten mit QoS 0),
gespeicherte Nachrichten (retain, leere Nachricht löscht), letzter Wille bei Verbindungsabbruch, PING, DISCONNECT.
``log`` sammelt alle eingegangenen Nachrichten (Topic, Nachricht, retain).
"""
import socket
import struct
import threading


def _match(flt, topic):
    f, t = flt.split("/"), topic.split("/")
    for i, part in enumerate(f):
        if part == "#":
            return True
        if i >= len(t) or (part != "+" and part != t[i]):
            return False
    return len(f) == len(t)


def _remaining(n):
    out = bytearray()
    while True:
        b = n % 128
        n //= 128
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


class Broker:
    def __init__(self, users=None):
        self.users = users or {}                  # {Name: Passwort}; leer = ohne Anmeldung
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(20)
        self.port = self.srv.getsockname()[1]
        self.lock = threading.Lock()
        self.clients = {}                         # Socket -> [Filter]
        self.retained = {}
        self.log = []
        self.running = True
        self.conns = []
        threading.Thread(target=self._accept, daemon=True).start()

    def close(self):
        self.running = False
        try:
            self.srv.close()
        except OSError:
            pass
        for s in list(self.conns):
            try:
                s.close()
            except OSError:
                pass

    def drop_all(self):
        """Alle Verbindungen hart trennen (Test: Wiederverbinden, letzter Wille)."""
        for s in list(self.conns):
            try:
                s.shutdown(socket.SHUT_RDWR)
                s.close()
            except OSError:
                pass

    def messages(self, topic):
        with self.lock:
            return [p for t, p, _r in self.log if t == topic]

    def publish(self, topic, payload, retain=False):
        """Nachricht wie von einem Client verteilen (Test: Sender spielen)."""
        if isinstance(payload, str):
            payload = payload.encode()
        self._deliver(topic, payload, retain)

    # -----------------------------------------------------------------------------------------------------------------
    def _accept(self):
        while self.running:
            try:
                s, _a = self.srv.accept()
            except OSError:
                return
            self.conns.append(s)
            threading.Thread(target=self._serve, args=(s,), daemon=True).start()

    @staticmethod
    def _recv(s, n):
        buf = b""
        while len(buf) < n:
            chunk = s.recv(n - len(buf))
            if not chunk:
                raise ConnectionError
            buf += chunk
        return buf

    def _packet(self, s):
        head = self._recv(s, 1)[0]
        n, mult = 0, 1
        while True:
            b = self._recv(s, 1)[0]
            n += (b & 0x7F) * mult
            mult *= 128
            if not b & 0x80:
                break
        return head, self._recv(s, n) if n else b""

    @staticmethod
    def _send(s, ptype, body=b""):
        s.sendall(bytes([ptype]) + _remaining(len(body)) + body)

    def _deliver(self, topic, payload, retain):
        with self.lock:
            self.log.append((topic, payload, retain))
            if retain:
                if payload:
                    self.retained[topic] = payload
                else:
                    self.retained.pop(topic, None)
            targets = [s for s, flts in self.clients.items() if any(_match(f, topic) for f in flts)]
        t = topic.encode()
        body = struct.pack("!H", len(t)) + t + payload
        for s in targets:
            try:
                self._send(s, 0x30, body)
            except OSError:
                pass

    def _serve(self, s):
        will = None
        clean = False
        try:
            head, body = self._packet(s)
            if head >> 4 != 1:
                return
            pos = 2 + struct.unpack("!H", body[:2])[0]
            flags = body[pos + 1]
            pos += 4
            fields = []
            n = 1 + (2 if flags & 0x04 else 0) + (1 if flags & 0x80 else 0) + (1 if flags & 0x40 else 0)
            for _i in range(n):
                ln = struct.unpack("!H", body[pos:pos + 2])[0]
                fields.append(body[pos + 2:pos + 2 + ln])
                pos += 2 + ln
            k = 1
            if flags & 0x04:
                will = (fields[1].decode(), fields[2], bool(flags & 0x20))
                k = 3
            user = fields[k].decode() if flags & 0x80 else None
            pw = fields[k + 1].decode() if flags & 0x40 else None
            if self.users and self.users.get(user) != pw:
                self._send(s, 0x20, b"\x00\x05")          # nicht berechtigt
                return
            self._send(s, 0x20, b"\x00\x00")
            with self.lock:
                self.clients[s] = []
            while True:
                head, body = self._packet(s)
                ptype = head >> 4
                if ptype == 3:                               # PUBLISH
                    qos = (head >> 1) & 3
                    ln = struct.unpack("!H", body[:2])[0]
                    topic = body[2:2 + ln].decode()
                    pos = 2 + ln
                    if qos:
                        pid = body[pos:pos + 2]
                        pos += 2
                        self._send(s, 0x40 if qos == 1 else 0x50, pid)
                    self._deliver(topic, body[pos:], bool(head & 1))
                elif ptype == 6:                             # PUBREL (QoS 2)
                    self._send(s, 0x70, body[:2])
                elif ptype == 8:                             # SUBSCRIBE
                    pid, pos, flts = body[:2], 2, []
                    while pos < len(body):
                        ln = struct.unpack("!H", body[pos:pos + 2])[0]
                        flts.append(body[pos + 2:pos + 2 + ln].decode())
                        pos += 3 + ln
                    with self.lock:
                        self.clients[s] += flts
                        keep = [(t, p) for t, p in self.retained.items() if any(_match(f, t) for f in flts)]
                    self._send(s, 0x90, pid + bytes(len(flts)))
                    for t, p in keep:
                        tb = t.encode()
                        self._send(s, 0x31, struct.pack("!H", len(tb)) + tb + p)
                elif ptype == 12:                            # PINGREQ
                    self._send(s, 0xD0)
                elif ptype == 14:                            # DISCONNECT
                    clean = True
                    return
        except (OSError, ConnectionError, IndexError, struct.error):
            pass
        finally:
            with self.lock:
                self.clients.pop(s, None)
            try:
                s.close()
            except OSError:
                pass
            if will and not clean and self.running:
                self._deliver(*will)
