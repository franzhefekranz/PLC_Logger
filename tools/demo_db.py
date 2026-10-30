# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Demo-Aufzeichnung rückwirkend in eine Datenbank schreiben (für die Bilder der Anleitung: Speicherplatz, Grafana).

Gleiche Variablen und Signale wie der Demo-Modus des Loggers (plc_recorder.demo_config, demo_value, DemoLoop):

    from demo_db import fill
    fill({"db_typ": "victoriametrics", "db_host": "127.0.0.1", "db_port": 8428, "db_tabelle": "messwerte",
          "projekt": "Kesselhaus"}, seconds=3600)
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))


def fill(conn, seconds, step=1.0, end=None):
    """``seconds`` Sekunden Demo-Werte im Abstand ``step`` bis ``end`` (Standard: vor 40 s) schreiben -> Anzahl Werte."""
    from plc_db import DbWriter
    from plc_recorder import DemoLoop, demo_config, demo_value
    _charts, variables = demo_config()
    names = [v.name for v in variables]
    end = (time.time() - 40) if end is None else end
    t0 = end - seconds
    loop = DemoLoop()
    w = DbWriter(conn, names, interval_s=0.2)
    w.start()
    n = int(seconds / step)
    for i in range(n):
        el = i * step
        vals = {v.name: demo_value(k, v, el) for k, v in enumerate(variables) if not v.formula}
        vals["Sollwert"], vals["Istwert"], vals["Stellwert"] = loop.step(el)
        vals["Mittel"] = (vals["Sinus"] + vals["Temperatur"]) / 2
        w.put(t0 + el, [vals[nm] for nm in names])
        if i % 5000 == 4999:
            time.sleep(0.3)                              # Schreib-Thread aufholen lassen
    time.sleep(1.0)
    w.stop()
    return w.written


def demo_charts():
    """Diagramme und Variablen der Demo (für den Grafana-Export)."""
    from plc_recorder import demo_config
    return demo_config()
