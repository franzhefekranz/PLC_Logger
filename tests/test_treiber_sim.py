# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Treiber gegen Simulatoren aus fremden Bibliotheken (nicht gegen eigene Nachbauten der Protokolle):

* ``s7``     gegen den S7-Server von python-snap7 (Einzelwerte, Bits, Block, Ringpuffer)
* ``tia``    gegen den S7CommPlus-Emulator von s7commplus (Ringpuffer über db_read)
* ``modbus`` gegen den Modbus-TCP-Server von pymodbus (alle vier Tabellen, Bits, REAL/DINT, Wortfolge)
* ``opcua``  gegen einen asyncua-Server (Double, Int32, Boolean, Array als Block)

Fehlt eine Bibliothek bzw. ihr Server, wird der Test übersprungen. Alle Server laufen nur auf 127.0.0.1 und freien
Ports."""
import asyncio
import socket
import struct
import threading
import time

import pytest

from plc_common import Block, Plc, Variable


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _ring_writer(mem, base, records, values, n_rec, order=">", write=None):
    """Datensätze wie die SPS-Vorlagen schreiben (Werte, Zeit, Seq, Zähler) – ``values(n)`` liefert die Werte."""
    rs = 8 + 4 * len(values(1))
    for n in range(1, n_rec + 1):
        off = base + 4 + (n % records) * rs
        rec = struct.pack(order + "ii" + "f" * len(values(n)), n, 1000 + 10 * n, *values(n))
        if write:
            write(off + 8, rec[8:])
            write(off + 4, rec[4:8])
            write(off, rec[:4])
            write(base, struct.pack(order + "i", n))
        else:
            mem[off:off + len(rec)] = rec
            mem[base:base + 4] = struct.pack(order + "i", n)


# ---- s7 gegen python-snap7 -------------------------------------------------------------------------------------------
def test_s7_driver_with_snap7_server(monkeypatch):
    pytest.importorskip("snap7")
    try:
        from snap7.server import Server
        from snap7.type import SrvArea
    except Exception:
        pytest.skip("python-snap7 ohne Python-Server (Version < 3)")
    from snap7.client import Client
    from plc_treiber import get_driver
    port = _free_port()
    db10 = bytearray(64)
    struct.pack_into(">fhxx", db10, 0, 21.5, -7)
    db10[6] = 0b00001000                                            # DB10.DBX6.3
    struct.pack_into(">i", db10, 8, 123456)
    struct.pack_into(">fff", db10, 12, 1.0, 2.0, 3.0)
    db100 = bytearray(4 + 20 * 16)
    _ring_writer(db100, 0, 20, lambda n: (float(n), n * 0.5), 7)
    srv = Server()
    srv.register_area(SrvArea.DB, 10, db10)
    srv.register_area(SrvArea.DB, 100, db100)
    srv.start(tcp_port=port)
    orig = Client.connect
    monkeypatch.setattr(Client, "connect", lambda self, ip, rack, slot, tcp_port=102: orig(self, ip, rack, slot, port))
    try:
        drv = get_driver("s7")
        plc = Plc(name="S7", driver="s7", params={"ip": "127.0.0.1", "rack": 0, "slot": 1})
        vs = [Variable("T", "DB10.DBD0", "REAL"), Variable("I", "DB10.DBW4", "INT"),
              Variable("B", "DB10.DBX6.3", "BOOL"), Variable("D", "DB10.DBD8", "DINT")]
        vs += Block(name="Blk", address="DB10.DBD12", dtype="REAL", count=3, driver="s7").variables()
        values, errors = drv.read_once(plc, vs)
        assert not errors and values == [21.5, -7.0, 1.0, 123456.0, 1.0, 2.0, 3.0]
        ring = Block(name="P", address="DB100.DBX0.0", dtype="REAL", count=2, ring=20, driver="s7").variables()
        rows, errors, counters = drv.read_ring_once(plc, ring)
        assert not errors and counters == {"P": 7}
        assert [r[2] for r in rows] == [[float(n), n * 0.5] for n in range(1, 8)]
        assert rows[1][1] - rows[0][1] == pytest.approx(0.010)        # Abstand aus der SPS-Zeit (10 ms)
    finally:
        srv.stop()


# ---- tia gegen den S7CommPlus-Emulator -------------------------------------------------------------------------------
def test_tia_ring_with_s7commplus_emulator():
    pytest.importorskip("s7commplus")
    try:
        from s7commplus.server import S7CommPlusServer
    except Exception:
        pytest.skip("s7commplus ohne Emulator")
    from plc_treiber import get_driver
    port = _free_port()
    srv = S7CommPlusServer()
    db = srv.register_raw_db(100, bytearray(4 + 30 * 16))
    srv.start(host="127.0.0.1", port=port)
    try:
        _ring_writer(None, 0, 30, lambda n: (float(n), -float(n)), 12, write=db.write)
        plc = Plc(name="1500", driver="tia", params={"ip": "127.0.0.1", "port": port, "tls": "aus", "passwort": "",
                                                     "rolle": "hmi", "tags_je_anfrage": 50})
        ring = Block(name="P", address="DB100.DBX0.0", dtype="REAL", count=2, ring=30, driver="tia").variables()
        rows, errors, counters = get_driver("tia").read_ring_once(plc, ring)
        assert not errors and counters == {"P": 12}
        assert [r[2] for r in rows] == [[float(n), -float(n)] for n in range(1, 13)]
    finally:
        srv.stop()


# ---- modbus gegen pymodbus -------------------------------------------------------------------------------------------
@pytest.fixture
def modbus_server():
    """pymodbus-Server auf einem freien Port -> (Port, Register-Liste Holding, Input, Coils, Discrete Inputs).

    Die Datenblöcke beginnen bei Adresse 1 – pymodbus ordnet Protokolladresse 0 dem Blockelement 1 zu."""
    pytest.importorskip("pymodbus")
    from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext
    try:
        from pymodbus.datastore import ModbusDeviceContext as Ctx
    except ImportError:
        from pymodbus.datastore import ModbusSlaveContext as Ctx
    from pymodbus.server import StartAsyncTcpServer
    hr = [7, 0, 0, 0, 0, 0b100, 0, 0] + [0] * 20
    hr[1:3] = struct.unpack(">HH", struct.pack(">f", 21.5))           # 40002 REAL (ABCD)
    hr[3:5] = struct.unpack(">HH", struct.pack(">i", -100000))        # 40004 DINT
    cd = struct.unpack(">HH", struct.pack(">f", 3.25))
    hr[6:8] = [cd[1], cd[0]]                                            # 40007 REAL mit Wortfolge CDAB
    ir = [111, 222, 333] + [0] * 10
    co = [1, 0, 1] + [0] * 10
    di = [0, 1] + [0] * 10
    dev = Ctx(hr=ModbusSequentialDataBlock(1, hr), ir=ModbusSequentialDataBlock(1, ir),
              co=ModbusSequentialDataBlock(1, co), di=ModbusSequentialDataBlock(1, di))
    try:
        ctx = ModbusServerContext(devices=dev, single=True)
    except TypeError:
        ctx = ModbusServerContext(slaves=dev, single=True)
    port = _free_port()
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def run():
        asyncio.set_event_loop(loop)
        loop.call_soon(ready.set)
        try:
            loop.run_until_complete(StartAsyncTcpServer(context=ctx, address=("127.0.0.1", port)))
        except Exception:
            pass
    th = threading.Thread(target=run, daemon=True)
    th.start()
    ready.wait(5)
    for _ in range(50):                                                 # warten, bis der Port lauscht
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield port
    try:
        from pymodbus.server import ServerAsyncStop
        asyncio.run_coroutine_threadsafe(ServerAsyncStop(), loop).result(5)
    except Exception:
        loop.call_soon_threadsafe(loop.stop)


def test_modbus_driver_with_pymodbus(modbus_server):
    from plc_treiber import get_driver
    drv = get_driver("modbus")
    params = drv.normalize_params({"ip": "127.0.0.1", "port": modbus_server, "unit": 1})
    plc = Plc(name="MB", driver="modbus", params=params)
    vs = [Variable("H", "40001", "INT"), Variable("R", "40002", "REAL"), Variable("D", "40004", "DINT"),
          Variable("Bit", "40006.2", "BOOL"), Variable("I", "30002", "INT"), Variable("C", "00003", "BOOL"),
          Variable("DI", "10002", "BOOL")]
    values, errors = drv.read_once(plc, vs)
    assert not errors, errors
    assert values == [7.0, 21.5, -100000.0, 1.0, 222.0, 1.0, 1.0]
    plc2 = Plc(name="MB2", driver="modbus", params=dict(params, wortfolge="CDAB"))
    values, errors = drv.read_once(plc2, [Variable("R2", "40007", "REAL")])
    assert not errors and values == [3.25]


# ---- opcua gegen asyncua ---------------------------------------------------------------------------------------------
def test_opcua_driver_with_asyncua_server():
    pytest.importorskip("asyncua")
    from asyncua import ua
    from asyncua.sync import Server
    from plc_treiber import get_driver
    port = _free_port()
    srv = Server()
    srv.set_endpoint(f"opc.tcp://127.0.0.1:{port}/sim/")
    srv.set_security_policy([ua.SecurityPolicyType.NoSecurity])
    ns = srv.register_namespace("urn:plc-test")
    obj = srv.nodes.objects.add_object(ns, "Anlage")
    obj.add_variable(ua.NodeId(1001, ns), "Temp", 21.5, ua.VariantType.Double)
    obj.add_variable(ua.NodeId(1002, ns), "Zaehler", 42, ua.VariantType.Int32)
    obj.add_variable(ua.NodeId(1003, ns), "Ein", True, ua.VariantType.Boolean)
    obj.add_variable(ua.NodeId("Werte", ns), "Werte", [1.0, 2.0, 3.0, 4.0, 5.0], ua.VariantType.Double)
    srv.start()
    try:
        drv = get_driver("opcua")
        plc = Plc(name="UA", driver="opcua",
                  params=drv.normalize_params({"endpoint": f"opc.tcp://127.0.0.1:{port}/sim/"}))
        vs = [Variable("T", f"ns={ns};i=1001", "REAL"), Variable("Z", f"ns={ns};i=1002", "DINT"),
              Variable("E", f"ns={ns};i=1003", "BOOL")]
        vs += Block(name="W", address=f"ns={ns};s=Werte", start=1, dtype="REAL", count=3, driver="opcua").variables()
        values, errors = drv.read_once(plc, vs)
        assert not errors, errors
        assert values == [21.5, 42.0, 1.0, 2.0, 3.0, 4.0]
    finally:
        srv.stop()


def test_tia_tls_without_password_writes_no_keylog(tmp_path, monkeypatch):
    """tia mit TLS gegen den Emulator: Ohne Passwort wird keine TLS-Schlüsseldatei geschrieben (sie führt unter
    Windows je nach OpenSSL-DLL zum Absturz „OPENSSL_Uplink: no OPENSSL_Applink“); mit Passwort wie bisher."""
    pytest.importorskip("s7commplus")
    pytest.importorskip("cryptography")
    try:
        from s7commplus.server import S7CommPlusServer
        from s7commplus import connection as c
    except Exception:
        pytest.skip("s7commplus ohne Emulator")
    if not hasattr(c, "_tls_key_log"):
        pytest.skip("s7commplus ohne TLS-Schlüsseldatei")
    import plc_treiber.tia_io as tio
    from plc_web import ensure_self_signed
    from plc_treiber import get_driver
    cert, key = ensure_self_signed(str(tmp_path / "c.pem"), str(tmp_path / "k.pem"))
    tio._install_keylog_switch()
    calls = []
    orig = c.ssl.SSLContext.keylog_filename

    def spy_set(self, value):
        calls.append(value)
        orig.__set__(self, value)
    monkeypatch.setattr(c.ssl.SSLContext, "keylog_filename", property(orig.__get__, spy_set))
    port = _free_port()
    srv = S7CommPlusServer()
    db = srv.register_raw_db(100, bytearray(4 + 30 * 16))
    srv.start(host="127.0.0.1", port=port, use_tls=True, tls_cert=cert, tls_key=key)
    try:
        _ring_writer(None, 0, 30, lambda n: (float(n), -float(n)), 4, write=db.write)
        plc = Plc(name="1500", driver="tia", params={"ip": "127.0.0.1", "port": port, "tls": "an", "passwort": "",
                                                     "rolle": "hmi", "tags_je_anfrage": 50})
        ring = Block(name="P", address="DB100.DBX0.0", dtype="REAL", count=2, ring=30, driver="tia").variables()
        rows, errors, counters = get_driver("tia").read_ring_once(plc, ring)
        assert not errors and counters == {"P": 4}
        assert not any(calls), calls                       # keine Schlüsseldatei gesetzt
    finally:
        srv.stop()
