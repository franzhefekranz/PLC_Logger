# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Tests der Netzwerksuche: Bereiche, EtherNet/IP List Identity, Portsuche gegen lokale Testserver, Vorschläge."""
import socket
import struct
import threading

import pytest


def test_parse_targets_and_broadcasts():
    import plc_netscan as ns
    assert ns.parse_targets("192.168.0.10-12, 10.0.0.1") == ["192.168.0.10", "192.168.0.11", "192.168.0.12",
                                                             "10.0.0.1"]
    assert len(ns.parse_targets("192.168.5.0/24")) == 254
    assert ns.parse_targets("192.168.0.250-192.168.1.1")[-1] == "192.168.1.1"
    for bad in ("192.168.0.300", "10.0.0.0/8", "1.2.3.9-1", "abc"):
        with pytest.raises(ValueError):
            ns.parse_targets(bad)
    assert ns.broadcasts("192.168.5.0/24, 10.1.1.1") == ["192.168.5.255"]
    assert ns.broadcasts("10.1.1.1") == ["255.255.255.255"]


def _identity_reply(ip, name, vendor=1):
    """Antwort auf List Identity wie von einer CompactLogix."""
    sock = struct.pack(">hH4s8s", 2, 44818, socket.inet_aton(ip), b"\0" * 8)
    body = struct.pack("<H", 1) + sock + struct.pack("<HHHBBHI", vendor, 14, 96, 33, 11, 0x30, 0x60C2F1A5)
    body += bytes([len(name)]) + name.encode() + b"\x03"
    item = struct.pack("<HH", 0x0C, len(body)) + body
    data = struct.pack("<H", 1) + item
    return struct.pack("<HHII8sI", 0x63, len(data), 0, 0, b"PLCSCAN\0", 0) + data


def test_list_identity_parse_and_unicast():
    import plc_netscan as ns
    info = ns.parse_list_identity(_identity_reply("192.168.1.20", "1769-L33ER/A LOGIX5333ER"))
    assert info["ip"] == "192.168.1.20" and info["name"] == "1769-L33ER/A LOGIX5333ER"
    assert info["revision"] == "33.011" and info["serial"] == "60C2F1A5"
    assert ns.parse_list_identity(b"\x00" * 10) is None
    # Antwortender Testserver auf UDP 44818 (lokal)
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        srv.bind(("127.0.0.1", ns.ENIP_PORT))
    except OSError:
        pytest.skip("UDP-Port 44818 belegt")
    srv.settimeout(3)

    def answer():
        try:
            data, addr = srv.recvfrom(100)
            if struct.unpack_from("<H", data)[0] == 0x63:
                srv.sendto(_identity_reply("127.0.0.1", "1756-L83E/B"), addr)
        except OSError:
            pass
    th = threading.Thread(target=answer, daemon=True)
    th.start()
    found = ns.enip_discover([], timeout=1.0, unicast=["127.0.0.1"])
    srv.close()
    assert found["127.0.0.1"]["name"] == "1756-L83E/B"
    f = ns.suggest(ns.Found(ip="127.0.0.1", ports=[44818]), enip=found["127.0.0.1"])
    assert f.driver == "clx" and f.params["cpu"] == "controllogix" and "Rockwell" in f.details


def test_port_scan_and_suggestions():
    import plc_netscan as ns
    lsock = socket.socket()
    lsock.bind(("127.0.0.1", 0))
    lsock.listen(16)
    port = lsock.getsockname()[1]
    threading.Thread(target=lambda: [lsock.accept()[0].close() for _ in range(8)], daemon=True).start()
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    free = closed.getsockname()[1]
    closed.close()
    res = ns.scan("127.0.0.1", ports=[port, free], timeout=0.5, identify=False)
    lsock.close()
    assert [f.ip for f in res] == ["127.0.0.1"] and res[0].ports == [port]
    # Vorschläge je Protokoll
    s = ns.suggest(ns.Found(ip="10.0.0.5", ports=[4840, 102]), s7={"device": "CPU 1516-3 PN/DP", "slot": 1})
    assert s.driver == "tia" and s.device == "CPU 1516-3 PN/DP"
    s = ns.suggest(ns.Found(ip="10.0.0.6", ports=[102]), s7={"device": "CPU 315-2 PN/DP", "slot": 2})
    assert s.driver == "s7" and s.params == {"ip": "10.0.0.6", "rack": 0, "slot": 2}
    assert ns.suggest(ns.Found(ip="10.0.0.7", ports=[4840])).params == {"endpoint": "opc.tcp://10.0.0.7:4840"}
    assert ns.suggest(ns.Found(ip="10.0.0.8", ports=[48898])).params["ams_netid"] == "10.0.0.8.1.1"
    assert ns.suggest(ns.Found(ip="10.0.0.9", ports=[502])).driver == "modbus"
