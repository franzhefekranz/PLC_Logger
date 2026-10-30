# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Tests der Prometheus-Anbindung: Snappy, Protobuf (Remote Write), Schreiben an einen Testserver, abgelehnte
Stapel, Lesen in Stücken. Mit der Umgebungsvariablen PLC_TEST_PROMETHEUS (z. B. http://127.0.0.1:9090) zusätzlich
gegen einen echten Prometheus-Server (im Workflow „Tests“ unter Linux)."""
import datetime
import os
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pytest


def unsnappy(b):
    """Referenz-Dekoder für das Snappy-Blockformat."""
    i, n, shift = 0, 0, 0
    while True:
        c = b[i]
        i += 1
        n |= (c & 0x7F) << shift
        shift += 7
        if not c & 0x80:
            break
    out = bytearray()
    while i < len(b):
        tag = b[i]
        i += 1
        kind = tag & 3
        if kind == 0:
            ln = tag >> 2
            if ln >= 60:
                k = ln - 59
                ln = int.from_bytes(b[i:i + k], "little")
                i += k
            ln += 1
            out += b[i:i + ln]
            i += ln
            continue
        if kind == 1:
            ln, off = ((tag >> 2) & 7) + 4, ((tag >> 5) << 8) | b[i]
            i += 1
        elif kind == 2:
            ln, off = (tag >> 2) + 1, int.from_bytes(b[i:i + 2], "little")
            i += 2
        else:
            ln, off = (tag >> 2) + 1, int.from_bytes(b[i:i + 4], "little")
            i += 4
        for _ in range(ln):
            out.append(out[-off])
    assert len(out) == n
    return bytes(out)


def pb_fields(buf):
    """Protobuf-Nachricht in [(Feld, Wert)] zerlegen (Varint, fixed64, Länge)."""
    out, i = [], 0
    while i < len(buf):
        key, shift = 0, 0
        while True:
            c = buf[i]
            i += 1
            key |= (c & 0x7F) << shift
            shift += 7
            if not c & 0x80:
                break
        field, wt = key >> 3, key & 7
        if wt == 0:
            v, shift = 0, 0
            while True:
                c = buf[i]
                i += 1
                v |= (c & 0x7F) << shift
                shift += 7
                if not c & 0x80:
                    break
        elif wt == 1:
            v = struct.unpack_from("<d", buf, i)[0]
            i += 8
        elif wt == 2:
            ln, shift = 0, 0
            while True:
                c = buf[i]
                i += 1
                ln |= (c & 0x7F) << shift
                shift += 7
                if not c & 0x80:
                    break
            v = buf[i:i + ln]
            i += ln
        else:
            raise AssertionError(wt)
        out.append((field, v))
    return out


def decode_write_request(body):
    """WriteRequest -> [({Label: Wert}, [(ms, Wert)])]."""
    series = []
    for f, ts in pb_fields(unsnappy(body)):
        assert f == 1
        labels, samples = {}, []
        for g, v in pb_fields(ts):
            if g == 1:
                d = dict(pb_fields(v))
                labels[d[1].decode()] = d[2].decode()
            else:
                d = dict(pb_fields(v))
                samples.append((d[2], d[1]))
        assert list(labels) == sorted(labels)
        series.append((labels, samples))
    return series


def test_snappy_roundtrip():
    from plc_db import snappy_compress
    for data in (b"", b"x", b"abcd" * 500, os.urandom(70_000), bytes(100_000)):
        packed = snappy_compress(data)
        assert unsnappy(packed) == data
    assert len(snappy_compress(b"variable=Temperatur" * 200)) < 300          # 3800 Bytes -> etwa 200


def _server(status=204):
    got = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"success","data":{"version":"test"}}')

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            got.append((self.path, dict(self.headers), body))
            self.send_response(status)
            self.end_headers()
            if status >= 400:
                self.wfile.write(b"out of order sample")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, got


def _conn(port):
    return {"db_typ": "prometheus", "db_host": "127.0.0.1", "db_port": port, "db_tabelle": "anlage", "projekt": "Kessel"}


def test_prometheus_remote_write():
    from plc_db import BACKENDS, db_settings
    srv, got = _server()
    b = BACKENDS["prometheus"](db_settings(_conn(srv.server_port)))
    b.connect()
    z = datetime.datetime(2026, 10, 26, 12, 0, tzinfo=datetime.timezone.utc)
    dt = datetime.timedelta(milliseconds=50)
    b.insert([(z, "Kessel", "Temp", 20.5), (z, "Kessel", "Druck", 1.0), (z + dt, "Kessel", "Temp", 21.0)])
    path, headers, body = got[0]
    assert path == "/api/v1/write"
    assert headers["Content-Encoding"] == "snappy" and headers["Content-Type"] == "application/x-protobuf"
    series = {s[0]["variable"]: s for s in decode_write_request(body)}
    ms = int(z.timestamp() * 1000)
    assert series["Temp"][0] == {"__name__": "anlage_wert", "projekt": "Kessel", "variable": "Temp"}
    assert series["Temp"][1] == [(ms, 20.5), (ms + 50, 21.0)]
    assert series["Druck"][1] == [(ms, 1.0)]
    srv.shutdown()


def test_prometheus_rejected_batch_is_dropped():
    from plc_db import DbWriter
    srv, got = _server(status=400)
    msgs = []
    w = DbWriter(_conn(srv.server_port), ["A", "B"], msgs.append, interval_s=0.05)
    w.start()
    w.put(time.time(), [1.0, 2.0])
    time.sleep(0.6)
    w.stop()
    assert w.rejected == 2 and not w.buf and len(got) == 1      # nicht endlos wiederholt
    assert any("abgelehnt" in m for m in msgs)
    srv.shutdown()


def test_prom_reader_raw_chunks(monkeypatch):
    """Rohdaten werden stundenweise als Bereichsabfrage geholt; Zeiten bleiben unverändert."""
    from plc_db import PromReader
    r = PromReader(_conn(9090))
    calls = []

    def fake_data(path, params):
        calls.append((path, params))
        end = float(params["time"])
        span = float(params["query"].rsplit("[", 1)[1].rstrip("ms]")) / 1000
        pts = [[t, str(t % 7)] for t in np.arange(np.ceil(end - span), end + 1e-9, 600.0) if t > end - span]
        return {"result": [{"metric": {"variable": "Temp"}, "values": pts}]}

    monkeypatch.setattr(r, "_data", fake_data)
    t, names, cols = r.load(["Temp"], 0.0, 3 * 3600.0)
    assert len(calls) == 4 and all(p == "/api/v1/query" for p, _ in calls)   # 3 h + Rest durch die Verschiebung
    assert t[0] == 0.0 and t[-1] == 3 * 3600.0 and len(t) == 19 and np.all(np.diff(t) == 600)
    assert 'variable=~"^(?:Temp)$"' in calls[0][1]["query"]


@pytest.mark.skipif(not os.environ.get("PLC_TEST_PROMETHEUS"), reason="kein Prometheus-Server (PLC_TEST_PROMETHEUS)")
def test_prometheus_real_server():
    """Schreiben per Remote Write und Lesen über die HTTP-Schnittstelle eines echten Prometheus-Servers."""
    import urllib.parse
    from plc_db import DbWriter, create_reader
    url = urllib.parse.urlparse(os.environ["PLC_TEST_PROMETHEUS"])
    conn = {"db_typ": "prometheus", "db_host": url.hostname, "db_port": url.port or 9090,
            "db_tabelle": f"plc_test_{os.getpid()}", "projekt": "Test"}
    w = DbWriter(conn, ["Temp", "Druck[0]"], interval_s=0.1)
    w.start()
    now = time.time()
    t0 = now - 120
    for k in range(121):
        w.put(t0 + k, [20 + k * 0.1, float(k % 2)])
    time.sleep(1.0)
    w.stop()
    assert w.written == 242 and not w.rejected, w.status()
    r = create_reader(conn).connect()
    assert "Test" in r.projects()
    info = {n: (first, last, count) for n, first, last, count in r.variables("Test")}
    assert set(info) == {"Temp", "Druck[0]"} and info["Temp"][2] == 121
    t, names, cols = r.load(["Temp", "Druck[0]"], t0 - 1, now + 1, project="Test")
    assert len(t) == 121 and np.allclose(cols[0], 20 + np.arange(121) * 0.1)
    assert r.count(["Temp"], t0 - 1, now + 1, project="Test") == 121
    t, names, cols = r.load(["Temp"], t0, now, project="Test", raster_s=10)
    assert 10 <= len(t) <= 14 and np.nanmax(cols[0]) <= 32.1
    from plc_db import storage_info
    assert "Datenbank gesamt:" in storage_info(conn)          # Kennzahlen des Servers (/metrics)
