# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Tests des Ringpuffers (zyklussynchrone Aufzeichnung): Tracker, Treiber s7/tia/clx mit simulierter Steuerung,
Recorder (Reihenfolge der Zeilen), Konfiguration und Prüfungen."""
import struct
import threading
import time

import numpy as np
import pytest

from plc_common import Axis, Block, Chart, Plc


class FakePlc:
    """Simulierte Steuerung: schreibt Datensätze wie die Vorlagen (Werte, Zeit, Seq, zuletzt Zähler) in einen Speicher.

    ``order``: ">" (S7) oder "<" (Logix); ``base``: Byte-Adresse des Zählers; Werte = (Nummer, Zeit, 1,5 …)."""

    def __init__(self, records, count, dtype="REAL", order=">", base=0, ms0=0, wrap=2 ** 31):
        self.records, self.count, self.order, self.base = records, count, order, base
        self.fmt = {"REAL": "f", "DINT": "i", "INT": "h", "LREAL": "d"}[dtype]
        self.vs = struct.calcsize(self.fmt)
        size = 8 + count * self.vs
        self.rs = size + (size & 1)
        self.mem = bytearray(base + 4 + records * self.rs)
        self.n, self.ms, self.wrap = 0, ms0, wrap
        self.lock = threading.Lock()

    def write(self, k=1, step_ms=10):
        """``k`` Datensätze im Abstand ``step_ms`` schreiben."""
        o = self.order
        with self.lock:
            for _ in range(k):
                self.n += 1
                self.ms = (self.ms + step_ms) % self.wrap
                off = self.base + 4 + (self.n % self.records) * self.rs
                vals = [float(self.n), float(self.ms)] + [1.5] * (self.count - 2)
                if self.fmt in "ih":
                    vals = [int(v) % 30000 for v in vals]
                struct.pack_into(o + self.fmt * self.count, self.mem, off + 8, *vals[:self.count])
                struct.pack_into(o + "i", self.mem, off + 4, self.ms if self.ms < 2 ** 31 else self.ms - 2 ** 32)
                struct.pack_into(o + "i", self.mem, off, self.n)
                struct.pack_into(o + "i", self.mem, self.base, self.n)

    def read(self, start, size):
        with self.lock:
            return bytes(self.mem[start:start + size])


# ---- Tracker ------------------------------------------------------------------------------------------------------
def test_tracker_sequence_loss_and_restart():
    from plc_treiber.ringbuffer import RingTracker
    t = RingTracker(10)
    assert t.wanted(0) == (1, 0, 0)                       # leer
    assert t.wanted(4) == (1, 4, 0)                       # erste Abholung: alles im Puffer
    rows, lost = t.accept([(s, s * 10, [s]) for s in range(1, 5)], 1, 4, 4, now=100.0)
    assert lost == 0 and [r[1][0] for r in rows] == [1, 2, 3, 4]
    assert rows[-1][0] == pytest.approx(100.0) and rows[0][0] == pytest.approx(99.97)
    lo, hi, skipped = t.wanted(20)                        # 16 neue, nur die letzten 10 noch im Puffer
    assert (lo, hi, skipped) == (11, 20, 6)
    recs = [(s, s * 10, [s]) for s in range(11, 21)]
    recs[0] = (21, 210, [21])                             # Platz von 11 wurde schon überschrieben
    rows, lost = t.accept(recs, lo, hi, 21, now=100.2)   # Zähler nach dem Lesen 21: Nummer 11 kann zerrissen sein
    assert lost == 1 and [r[1][0] for r in rows] == list(range(12, 21))
    # Abstände der Zeitstempel = Abstände der SPS-Zeit (10 ms)
    assert np.allclose(np.diff([r[0] for r in rows]), 0.01)
    assert t.wanted(3)[:2] == (1, 3) and t.restarts == 1  # Zähler kleiner: Neustart der Steuerung


def test_tracker_time_wraps_and_alignment():
    from plc_treiber.ringbuffer import RingTracker
    t = RingTracker(100)
    day = 86_400_000
    ms = [day - 20, day - 10, 0, 10]                      # Mitternacht
    rows, _ = t.accept([(i + 1, m, [0]) for i, m in enumerate(ms)], 1, 4, 4, now=50.0)
    assert np.allclose(np.diff([r[0] for r in rows]), 0.01)
    ms = [2 ** 31 - 5, 5]                                 # TIME_TCK-Überlauf
    rows, _ = t.accept([(5, ms[0], [0]), (6, ms[1], [0])], 5, 6, 6, now=50.2)
    assert rows[1][0] - rows[0][0] == pytest.approx(0.010, abs=1e-6)
    # Uhr der Steuerung springt (unplausibel): neu ausrichten, jüngster Datensatz = jetzt
    rows, _ = t.accept([(7, 123456789, [0])], 7, 7, 7, now=60.0)
    assert rows[0][0] == pytest.approx(60.0)
    # nie in der Zukunft: SPS-Uhr läuft vor -> Bezug wird nachgezogen
    rows, _ = t.accept([(8, 123456789 + 5000, [0])], 8, 8, 8, now=60.1)
    assert rows[0][0] <= 60.1 + 1e-9


# ---- Treiber s7 ---------------------------------------------------------------------------------------------------
class _Snap7Client:
    """Ersatz für snap7.client.Client: liest aus dem Speicher der simulierten Steuerung (DB100)."""

    def __init__(self, plc):
        self.plc, self.calls = plc, 0

    def read_area(self, area, db, start, size):
        assert db == 100
        self.calls += 1
        return bytearray(self.plc.read(start, size))

    def get_connected(self):
        return True


def _ring_vars(driver, address, records=50, count=3, dtype="REAL"):
    return Block(name="P", address=address, dtype=dtype, count=count, ring=records, driver=driver).variables()


def test_s7_reader_ring():
    from plc_treiber.s7 import S7Reader, DRIVER
    sim = FakePlc(records=50, count=3, base=10)
    plc = Plc(name="SPS", driver="s7")
    variables = [__import__("plc_common").Variable("T", "DB100.DBD0", "REAL")] + _ring_vars("s7", "DB100.DBX10.0")
    r = S7Reader(DRIVER, plc, variables)
    r.client, r.areas = _Snap7Client(sim), {"DB": 0x84}
    assert r.read_rings() == []                           # Puffer leer
    sim.write(7)
    rows = r.read_rings(now=1000.0)
    assert [int(v[0]) for _p, _t, v in rows] == list(range(1, 8))
    assert rows[0][0] == [1, 2, 3]                        # Positionen der Ringpuffer-Elemente
    sim.write(120)                                        # mehr als der Puffer fasst -> Verluste
    rows = r.read_rings(now=1001.0)
    assert [int(v[0]) for _p, _t, v in rows] == list(range(78, 128))
    assert any("verloren" in n for n in r.take_ring_notes())
    # normale Variable wird weiter gelesen, die Ringpuffer-Elemente nicht
    out = r.read()
    assert len(out) == 4 and all(np.isnan(out[1:]))


def test_s7_ring_checks():
    from plc_treiber.s7 import DRIVER
    from plc_common import get_driver
    ok = Block(name="P", address="DB100.DBX0.0", dtype="REAL", count=4, ring=100, driver="s7")
    assert DRIVER.check_block(ok) == ""
    assert "Datenbaustein" in DRIVER.check_block(Block(name="P", address="MW10", dtype="REAL", count=4, ring=100))
    assert "Format" in DRIVER.check_block(Block(name="P", address="DB1.DBX0.0", dtype="BOOL", count=4, ring=100))
    assert "Ringpuffer" in get_driver("modbus").check_block(Block(name="P", address="40001", count=4, ring=10))
    assert get_driver("clx").check_block(Block(name="P", address="Puffer", dtype="REAL", count=4, ring=100)) == ""
    assert get_driver("tia").check_block(ok) == ""


# ---- Treiber tia (s7commplus: db_read) --------------------------------------------------------------------------
def test_tia_reader_ring():
    from plc_treiber.tia_io import TagReader
    sim = FakePlc(records=20, count=2)

    class Client:
        def connect(self, ip, **kw):
            pass

        def db_read(self, db, start, size):
            assert db == 7
            return sim.read(start, size)

        def disconnect(self):
            pass

    plc = Plc(name="S7-1500", driver="tia")
    r = TagReader(plc, _ring_vars("tia", "DB7.DBX0.0", records=20, count=2), client_factory=Client)
    sim.write(5)
    assert r.connect() == 2
    rows = r.read_rings(now=10.0)
    assert [int(v[0]) for _p, _t, v in rows] == [1, 2, 3, 4, 5]
    sim.write(3)
    assert [int(v[0]) for _p, _t, v in r.read_rings(now=10.03)] == [6, 7, 8]


# ---- Treiber clx (libplctag) ------------------------------------------------------------------------------------
class _PlcTagFake:
    """Ersatz für libplctag: Tags <Puffer>.Zaehler und <Puffer>.Daten auf dem Speicher der simulierten Steuerung."""

    def __init__(self, sim):
        self.sim, self.tags, self.next = sim, {}, 1

    def create(self, attrs, timeout_ms):
        a = dict(p.split("=", 1) for p in attrs.split("&"))
        h, self.next = self.next, self.next + 1
        self.tags[h] = a
        return h

    def destroy(self, h):
        self.tags.pop(h, None)

    def read(self, h, timeout_ms=0):
        return 0

    def status(self, h):
        return 0 if self.tags[h]["name"].startswith("Puffer.") else -19

    def abort(self, h):
        return 0

    def decode(self, err):
        return f"Fehler {err}"

    def elem_size(self, h, default):
        return self.sim.rs

    def get(self, h, dtype, offset):
        name = self.tags[h]["name"]
        base = 0 if name.endswith(".Zaehler") else 4
        fmt = {"DINT": "<i", "REAL": "<f", "INT": "<h"}[dtype]
        return float(struct.unpack_from(fmt, self.sim.read(base + offset, 8))[0])


def test_clx_reader_ring():
    from plc_treiber.clx_io import TagReader
    sim = FakePlc(records=30, count=4, order="<")
    plc = Plc(name="Logix", driver="clx")
    r = TagReader(plc, _ring_vars("clx", "Puffer", records=30, count=4), lib=_PlcTagFake(sim))
    sim.write(12)
    assert r.connect() == 4
    rows = r.read_rings(now=5.0)
    assert [int(v[0]) for _p, _t, v in rows] == list(range(1, 13))
    assert rows[-1][2][2] == 1.5
    r.close()


# ---- Recorder: Datensätze aus der Vergangenheit werden zeitlich einsortiert ----------------------------------------
def test_recorder_orders_ring_records(tmp_path):
    from plc_common import Variable
    from plc_recorder import Recorder
    sim = FakePlc(records=200, count=2)

    class Reader:
        """Normale Variable (Zeitpunkt des Lesens) plus Ringpuffer der simulierten Steuerung."""

        def __init__(self, plc, variables):
            from plc_treiber.ringbuffer import RingSupport
            self.vars, self.errors = variables, {}
            self.ring = type("R", (RingSupport,), {})()
            self.ring.errors = self.errors
            self.ring._setup_rings(variables)
            ring = self.ring.rings[0]
            self.ring._ring_counter = lambda _r: struct.unpack(">i", sim.read(0, 4))[0]
            self.ring._ring_bytes = lambda _r, slot, n: sim.read(4 + slot * ring.record_size, n * ring.record_size)
            self.rings = self.ring.rings

        def connect(self):
            return len(self.vars)

        def read(self):
            return [42.0] + [float("nan")] * (len(self.vars) - 1)

        def read_rings(self):
            return self.ring.read_rings()

        def take_ring_notes(self):
            return self.ring.take_ring_notes()

        def close(self):
            pass

    stop = threading.Event()

    def writer():
        while not stop.is_set():
            sim.write(1, step_ms=10)
            time.sleep(0.01)

    variables = [Variable("Normal", "DB1.DBD0", "REAL")] + _ring_vars("s7", "DB100.DBX0.0", records=200, count=2)
    conn = {"csv_ordner": str(tmp_path), "csv_name": "ring", "csv_aktiv": 1}
    rec = Recorder(conn, [Plc(name="SPS", driver="s7", intervall_ms=100)], [Chart(axes=[Axis()])], variables)
    rec.reader_factory = Reader
    assert rec.reorder_s == pytest.approx(0.7)
    th = threading.Thread(target=writer, daemon=True)
    th.start()
    rec.start()
    time.sleep(2.0)
    rec.stop()
    stop.set()
    t = rec.tbuf[:rec.n]
    assert rec.n > 30 and np.all(np.diff(t) >= 0)           # Zeilen zeitlich geordnet (langsame Rechner: wenige)
    seq = rec.ybuf[1, :rec.n]
    seq = seq[~np.isnan(seq)]
    assert np.all(np.diff(np.unique(seq)) == 1)              # kein Datensatz verloren
    assert not np.all(np.isnan(rec.ybuf[0, :rec.n]))         # normale Variable ebenfalls aufgezeichnet
    with open(rec.csv_path, encoding="utf-8") as f:
        assert len(f.read().splitlines()) == rec.n + 1


# ---- Konfiguration ------------------------------------------------------------------------------------------------
def test_ring_block_config_roundtrip(tmp_path):
    from plc_common import load_blocks, load_config, save_config
    path = str(tmp_path / "ring.json")
    blk = Block(name="Puffer", address="DB100.DBX0.0", dtype="REAL", count=5, ring=250, driver="s7")
    save_config({"projekt": "x"}, [Chart(axes=[Axis()])], [], path, blocks=[blk], plcs=[Plc(driver="s7")])
    b2 = load_blocks(path)[0]
    assert b2.ring == 250 and b2.count == 5
    _conn, _charts, variables = load_config(path)
    assert len(variables) == 5 and all(v.ring is not None and v.ring.ring == 250 for v in variables)
    assert variables[2].address == "DB100.DBX0.0 › Werte[2]"
    assert b2.size_bytes() == 4 + 250 * (8 + 5 * 4)


def test_tia_reader_symbolic_ring():
    """tia: Ringpuffer über seinen symbolischen Namen (auch optimierter DB): Zaehler, Daten[i].Seq/.Zeit/.Werte[j]."""
    pytest.importorskip("s7commplus")
    from s7commplus import SymbolicTag
    from plc_treiber.tia_io import TagReader
    records, count = 20, 2
    names = ["Puffer_DB.Zaehler"]
    for k in range(1, records + 1):                              # Array[1..20], Werte Array[0..1] (Untergrenzen)
        names += [f"Puffer_DB.Daten[{k}].Seq", f"Puffer_DB.Daten[{k}].Zeit"]
        names += [f"Puffer_DB.Daten[{k}].Werte[{j}]" for j in range(count)]
    items = [{"name": n, "access_sequence": f"8A0E0001.{i + 1:X}",
              "data_type": "REAL" if ".Werte[" in n else "DINT"} for i, n in enumerate(names)]
    tags = {n: SymbolicTag.from_browse(it) for n, it in zip(names, items)}
    by_lid = {t.lids: n for n, t in tags.items()}
    mem = {n: 0 for n in names}
    state = {"n": 0, "requests": 0}

    def plc_write(k):
        for _ in range(k):
            state["n"] += 1
            n = state["n"]
            d = f"Puffer_DB.Daten[{n % records + 1}]"
            mem[d + ".Werte[0]"], mem[d + ".Werte[1]"] = float(n), 0.5 * n
            mem[d + ".Zeit"], mem[d + ".Seq"] = 1000 + 10 * n, n
            mem["Puffer_DB.Zaehler"] = n

    class Client:
        def connect(self, ip, **kw):
            pass

        def read_symbolic_multi(self, req):
            state["requests"] += 1
            out = []
            for _area, lids, _x in req:
                name = by_lid[tuple(lids)]
                v = mem[name]
                out.append(tags[name].encode_value(float(v) if ".Werte[" in name else int(v)))
            return out

        def db_read(self, *a):
            raise AssertionError("symbolischer Puffer darf nicht byteweise gelesen werden")

        def disconnect(self):
            pass

    from plc_common import get_driver
    plc = Plc(name="S7-1500", driver="tia", params=get_driver("tia").normalize_params({"ip": "10.0.0.1"}))
    blk = Block(name="P", address="Puffer_DB", dtype="REAL", count=count, ring=records, driver="tia")
    assert get_driver("tia").check_block(blk) == ""
    r = TagReader(plc, blk.variables(), client_factory=Client, catalog_items=items)
    plc_write(5)
    assert r.connect() == 2 and not r.errors
    rows = r.read_rings(now=10.0)
    assert [v for _p, _t, v in rows] == [[float(n), 0.5 * n] for n in range(1, 6)]
    assert rows[1][1] - rows[0][1] == pytest.approx(0.010)
    plc_write(25)                                                # mehr als der Puffer fasst
    rows = r.read_rings(now=10.3)
    assert [int(v[0]) for _p, _t, v in rows] == list(range(11, 31))
    assert any("verloren" in n for n in r.take_ring_notes())
    # zu klein eingestellter Puffer in der Steuerung bzw. falscher Name: verständlicher Fehler
    big = Block(name="Q", address="Puffer_DB", dtype="REAL", count=count, ring=50, driver="tia")
    r2 = TagReader(plc, big.variables(), client_factory=Client, catalog_items=items)
    r2.connect()
    assert "weniger als 50" in r2.errors[r2.rings[0].label]
    wrong = Block(name="W", address="Anderer_DB", dtype="REAL", count=count, ring=records, driver="tia")
    r3 = TagReader(plc, wrong.variables(), client_factory=Client, catalog_items=items)
    r3.connect()
    assert "Anderer_DB.Zaehler" in r3.errors[r3.rings[0].label]
