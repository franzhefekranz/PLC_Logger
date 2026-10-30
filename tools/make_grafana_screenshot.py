# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Bild der Anleitung „Grafana-Dashboard“ erzeugen: Demo-Daten in VictoriaMetrics, Dashboard-Export importieren und
mit Playwright fotografieren (Workflow „Screenshots“, Linux mit Grafana und VictoriaMetrics in Docker).

    python tools/make_grafana_screenshot.py --grafana http://127.0.0.1:3000 --vm http://127.0.0.1:8428 --out doc/images

Grafana muss anonymen Zugriff mit Admin-Rechten erlauben (GF_AUTH_ANONYMOUS_ENABLED=true,
GF_AUTH_ANONYMOUS_ORG_ROLE=Admin) – nur für diesen Testaufbau.
"""
import argparse
import json
import os
import shutil
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from demo_db import ROOT, demo_charts, fill  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "src"))


def api(base, path, body=None):
    """Grafana-API (ohne Anmeldung, anonymer Admin)."""
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode() or "{}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grafana", default="http://127.0.0.1:3000")
    ap.add_argument("--vm", default="http://127.0.0.1:8428")
    ap.add_argument("--out", default=os.path.join(ROOT, "doc", "images"))
    a = ap.parse_args()
    import plc_grafana
    vm = urllib.parse.urlparse(a.vm)
    conn = {"db_typ": "victoriametrics", "db_host": vm.hostname, "db_port": vm.port or 8428, "db_tabelle": "messwerte",
            "projekt": "Kesselhaus", "anordnung": "untereinander", "seite_anordnung": "raster", "raster_spalten": 2,
            "fenster_s": 300}
    print("Werte geschrieben:", fill(conn, seconds=1800), flush=True)
    urllib.request.urlopen(a.vm + "/internal/force_flush").read()
    ds = api(a.grafana, "/api/datasources", {"name": "VictoriaMetrics", "type": "prometheus", "access": "proxy",
                                             "url": a.vm, "jsonData": {"timeInterval": "1s"}})["datasource"]
    charts, variables = demo_charts()
    d = plc_grafana.dashboard(conn, charts, variables, title="Kesselhaus")
    res = api(a.grafana, "/api/dashboards/import", {"dashboard": d, "overwrite": True, "inputs": [
        {"name": "DS_PLC", "type": "datasource", "pluginId": "prometheus", "value": ds["uid"]}]})
    uid = res.get("uid") or d["uid"]
    end = int((time.time() - 60) * 1000)
    url = f"{a.grafana}/d/{uid}?orgId=1&from={end - 300_000}&to={end}&var-projekt=Kesselhaus&theme=light"
    from playwright.sync_api import sync_playwright
    os.makedirs(os.path.join(a.out, "en"), exist_ok=True)
    path = os.path.join(a.out, "grafana_dashboard.png")
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1600, "height": 900})
        page.add_init_script("try { localStorage.setItem('grafana.navigation.docked', 'false'); } catch (e) {}")
        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(4000)                        # Panels zeichnen
        page.screenshot(path=path)
        b.close()
    shutil.copy(path, os.path.join(a.out, "en", "grafana_dashboard.png"))   # Grafana-Oberfläche ist englisch
    print("Bild: grafana_dashboard.png", flush=True)


if __name__ == "__main__":
    main()
