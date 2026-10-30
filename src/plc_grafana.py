# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Grafana-Dashboard aus der Konfiguration erzeugen – mit derselben Anordnung wie im Logger (ohne Oberfläche).

Abbildung
---------
* **Seite** (Diagramme mit gleichem Seitennamen) -> Zeile (``row``) im Dashboard; Seitenanordnung *Tabs* -> nur die
  erste Zeile aufgeklappt. Ohne Seitennamen und nicht im Tab-Modus: alle Diagramme ohne Zeile.
* **Anordnung innerhalb der Seite** (untereinander / nebeneinander / Raster mit Spaltenzahl) -> Breite und Position der
  Panels im 24-Spalten-Raster von Grafana (wie ``ChartPage.n_cols`` im Logger).
* **Diagramm** -> Panel *Time series*; **Variable** -> Abfrage mit Farbe, Name und Y-Achse aus der Konfiguration.
  Achse 0 links, weitere rechts; feste Grenzen (min/max) und Achsenname werden übernommen. Damit Grafana jede Achse
  getrennt skaliert, bekommt jede weitere Achse eine eigene (unsichtbare) Einheit. BOOL als Treppenlinie.
* **Projekt** -> Dashboard-Variable ``projekt`` (Auswahl aus der Datenbank, vorbelegt mit dem Projekt der
  Konfiguration): ein Dashboard für mehrere Kunden/Anlagen mit gleicher Konfiguration.
* Zeitbereich = Anzeigefenster des Loggers (``fenster_s``), Aktualisierung alle 5 s.

Datenquelle
-----------
Die Datei enthält einen Platzhalter (``__inputs``): Beim Import in Grafana (*Dashboards › New › Import*) wird die
Datenquelle ausgewählt. Abfragen je Datenbanktyp: VictoriaMetrics/Prometheus PromQL auf ``<tabelle>_wert``,
TimescaleDB/PostgreSQL und MariaDB SQL mit Zeitraster (``$__timeGroupAlias``), QuestDB SQL über die
PostgreSQL-Schnittstelle, InfluxDB 3 SQL (``$__dateBin``). SQLite wird nicht unterstützt (kein eingebautes Grafana-Plugin).
"""
import hashlib
import json
import math

from plc_db import vm_metric
from plc_i18n import tr

# Datenbanktyp -> (Grafana-Plugin der Datenquelle, Name in der Auswahl)
DS_PLUGINS = {
    "victoriametrics": ("prometheus", "Prometheus"),
    "prometheus": ("prometheus", "Prometheus"),
    "timescale": ("grafana-postgresql-datasource", "PostgreSQL"),
    "questdb": ("grafana-postgresql-datasource", "PostgreSQL"),
    "mariadb": ("mysql", "MySQL"),
    "influxdb3": ("influxdb", "InfluxDB"),
}
DS = "${DS_PLC}"
PANEL_H = 9                       # Höhe eines Diagramms in Rasterzeilen (etwa 30 Pixel je Zeile)
ZWSP = "​"                   # unsichtbares Zeichen: eigene Einheit je weiterer Y-Achse (getrennte Skalierung)


def supported(db_type):
    """Kann für diesen Datenbanktyp ein Dashboard erzeugt werden?"""
    return db_type in DS_PLUGINS


def _sql_str(text):
    """Text als SQL-Literal in einfachen Hochkommas."""
    return "'" + str(text).replace("'", "''") + "'"


def _prom_str(text):
    """Text als PromQL-Labelwert in doppelten Anführungszeichen."""
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _query(db_type, table, var_name):
    """Abfrage (Grafana-Target ohne refId/datasource) für eine Variable."""
    if db_type in ("victoriametrics", "prometheus"):
        expr = f'{vm_metric(table)}{{projekt="$projekt",variable={_prom_str(var_name)}}}'
        return {"expr": expr, "legendFormat": var_name, "range": True, "instant": False}
    name = var_name.replace('"', "'")
    where = f"variable = {_sql_str(var_name)} AND projekt = '$projekt'"
    if db_type == "influxdb3":
        sql = (f'SELECT $__dateBin(time) AS time, avg(wert) AS "{name}" FROM {table} '
               f"WHERE {where} AND $__timeFilter(time) GROUP BY 1 ORDER BY 1")
        return {"query": sql, "rawQuery": True, "rawSql": sql, "resultFormat": "time_series", "format": "time_series"}
    if db_type == "questdb":
        sql = f'SELECT zeit AS time, wert AS "{name}" FROM {table} WHERE {where} AND $__timeFilter(zeit) ORDER BY 1'
    else:                                                    # timescale/postgres und mariadb
        q = "`" if db_type == "mariadb" else '"'
        sql = (f"SELECT $__timeGroupAlias(zeit, $__interval), avg(wert) AS {q}{name}{q} FROM {table} "
               f"WHERE {where} AND $__timeFilter(zeit) GROUP BY 1 ORDER BY 1")
    return {"rawSql": sql, "rawQuery": True, "format": "time_series", "editorMode": "code"}


def _project_variable(db_type, table, project):
    """Dashboard-Variable ``projekt`` (Werte aus der Datenbank, vorbelegt mit dem Projekt der Konfiguration)."""
    if db_type in ("victoriametrics", "prometheus"):
        q = f"label_values({vm_metric(table)}, projekt)"
        query = {"query": q, "refId": "projekt", "qryType": 1}
    else:
        col = "projekt"
        q = f"SELECT DISTINCT {col} FROM {table}"
        query = q
    return {"name": "projekt", "label": tr("Projekt"), "type": "query", "datasource": {"type": DS_PLUGINS[db_type][0],
            "uid": DS}, "query": query, "definition": q, "refresh": 1, "sort": 1, "includeAll": False,
            "multi": False, "current": {"text": project, "value": project}, "options": [], "hide": 0}


def _columns(mode, n, columns):
    """Spalten einer Seite wie im Logger (ChartPage.n_cols)."""
    n = max(n, 1)
    if mode == "nebeneinander":
        return n
    if mode == "raster":
        return min(columns if columns > 0 else math.ceil(math.sqrt(n)), n)
    return 1


def _panel(db_type, table, chart, cvars, pid, grid):
    """Panel *Time series* für ein Diagramm mit seinen Variablen."""
    targets, overrides = [], []
    for k, v in enumerate(cvars):
        t = _query(db_type, table, v.name)
        t.update(refId=_ref(k), datasource={"type": DS_PLUGINS[db_type][0], "uid": DS})
        targets.append(t)
        ai = min(max(v.axis, 0), max(len(chart.axes) - 1, 0))
        axis = chart.axes[ai] if chart.axes else None
        props = [{"id": "color", "value": {"mode": "fixed", "fixedColor": v.color}},
                 {"id": "custom.axisPlacement", "value": "left" if ai == 0 else "right"}]
        if ai > 0:
            props.append({"id": "unit", "value": "suffix:" + ZWSP * ai})
        if axis is not None:
            props.append({"id": "custom.axisLabel", "value": axis.name})
            if not axis.auto:
                props += [{"id": "min", "value": axis.y_min}, {"id": "max", "value": axis.y_max}]
        if v.dtype == "BOOL":
            props += [{"id": "custom.lineInterpolation", "value": "stepAfter"},
                      {"id": "custom.fillOpacity", "value": 25}]
        overrides.append({"matcher": {"id": "byName", "options": v.name}, "properties": props})
    return {"id": pid, "type": "timeseries", "title": chart.name, "gridPos": grid,
            "datasource": {"type": DS_PLUGINS[db_type][0], "uid": DS}, "targets": targets,
            "fieldConfig": {"defaults": {"custom": {"drawStyle": "line", "lineWidth": 2, "fillOpacity": 0,
                                                    "showPoints": "never", "spanNulls": True,
                                                    "lineInterpolation": "linear"},
                                         "color": {"mode": "palette-classic"}, "unit": "none"},
                            "overrides": overrides},
            "options": {"legend": {"showLegend": True, "displayMode": "table", "placement": "right",
                                   "calcs": ["lastNotNull", "min", "max"]},
                        "tooltip": {"mode": "multi", "sort": "none"}}}


def _ref(k):
    """refId A, B, … Z, AA, AB, …"""
    s = ""
    k += 1
    while k:
        k, r = divmod(k - 1, 26)
        s = chr(65 + r) + s
    return s


def pages(charts, layout):
    """Seiten wie im Logger (MainWindow.page_groups) -> [(Name, [Diagramm-Indizes])]."""
    if not any(c.page for c in charts):
        if layout == "tabs":
            return [(c.name, [ci]) for ci, c in enumerate(charts)]
        return [("", list(range(len(charts))))]
    groups = {}
    for ci, c in enumerate(charts):
        groups.setdefault(c.page or c.name, []).append(ci)
    return list(groups.items())


def dashboard(conn, charts, variables, title=""):
    """Dashboard (dict, Format von Grafana 10/11/12) für die Konfiguration. ValueError bei nicht unterstütztem Typ."""
    db_type = conn.get("db_typ") or ""
    if not supported(db_type):
        raise ValueError(tr("Für die Datenbank „{0}“ kann kein Grafana-Dashboard erzeugt werden (unterstützt: "
                            "VictoriaMetrics, Prometheus, TimescaleDB/PostgreSQL, MariaDB, QuestDB, InfluxDB 3).")
                         .format(db_type or tr("keine")))
    table = conn.get("db_tabelle") or "messwerte"
    project = conn.get("projekt") or ""
    layout = conn.get("anordnung") or "untereinander"
    mode = conn.get("seite_anordnung") or "untereinander"
    cols_cfg = int(conn.get("raster_spalten", 0) or 0)
    by_chart = {}
    for v in variables:
        by_chart.setdefault(v.chart, []).append(v)
    panels, pid, y = [], 1, 0
    groups = pages(charts, layout)
    use_rows = len(groups) > 1 or bool(groups and groups[0][0])
    for gi, (name, members) in enumerate(groups):
        members = [ci for ci in members if by_chart.get(ci)]       # Diagramme ohne Variablen weglassen
        if not members:
            continue
        ncol = _columns(mode, len(members), cols_cfg)
        inner = []
        for k, ci in enumerate(members):
            row, col = divmod(k, ncol)
            w = 24 // ncol
            if k == len(members) - 1 and mode == "raster":           # letztes Diagramm füllt die Zeile (wie im Logger)
                w = 24 - col * w
            grid = {"x": col * (24 // ncol), "y": y + 1 + row * PANEL_H if use_rows else y + row * PANEL_H,
                    "w": w, "h": PANEL_H}
            inner.append(_panel(db_type, table, charts[ci], by_chart[ci], pid + 1 + k if use_rows else pid + k, grid))
        n_rows = math.ceil(len(members) / ncol)
        if use_rows:
            collapsed = layout == "tabs" and gi > 0
            row_panel = {"id": pid, "type": "row", "title": name or tr("Diagramme"), "collapsed": collapsed,
                         "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": inner if collapsed else []}
            panels.append(row_panel)
            if not collapsed:
                panels.extend(inner)
            y += 1 + (0 if collapsed else n_rows * PANEL_H)
            pid += 1 + len(inner)
        else:
            panels.extend(inner)
            y += n_rows * PANEL_H
            pid += len(inner)
    plugin, plugin_name = DS_PLUGINS[db_type]
    title = title or project or tr("PLC Datenlogger")
    window = max(10, int(conn.get("fenster_s", 300) or 300))
    uid = "plc-" + hashlib.sha1(f"{title}|{table}|{db_type}".encode("utf-8")).hexdigest()[:12]
    return {
        "__inputs": [{"name": "DS_PLC", "label": tr("Datenquelle"), "description": tr("Datenbank des PLC-Datenloggers"),
                      "type": "datasource", "pluginId": plugin, "pluginName": plugin_name}],
        "__requires": [{"type": "grafana", "id": "grafana", "name": "Grafana", "version": "10.0.0"},
                       {"type": "panel", "id": "timeseries", "name": "Time series", "version": ""},
                       {"type": "datasource", "id": plugin, "name": plugin_name, "version": ""}],
        "uid": uid, "title": title, "tags": ["PLC Datenlogger"], "timezone": "browser", "editable": True,
        "schemaVersion": 39, "version": 1, "refresh": "5s", "graphTooltip": 1,
        "time": {"from": f"now-{window}s", "to": "now"},
        "templating": {"list": [_project_variable(db_type, table, project)]},
        "annotations": {"list": []}, "panels": panels,
    }


def export(path, conn, charts, variables, title=""):
    """Dashboard als JSON-Datei schreiben (für *Dashboards › New › Import* in Grafana) -> Anzahl Panels."""
    d = dashboard(conn, charts, variables, title)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    return sum(1 for p in d["panels"] if p["type"] == "timeseries") + sum(
        len(p.get("panels", [])) for p in d["panels"] if p["type"] == "row")
