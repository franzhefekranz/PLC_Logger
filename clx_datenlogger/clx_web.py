"""Webserver des CLX-Datenloggers: Diagramme online im Browser ansehen (PC, Tablet, Smartphone).

Der Server läuft in einem eigenen Thread neben der Aufzeichnung (im Logger mit Oberfläche genauso wie im
Headless-Modus) und liest die Messwerte aus dem Recorder (clx_recorder.py). Er verwendet

* Flask       – für die Adressen (Routen) und die JSON-Schnittstelle,
* Chart.js    – für die Diagramme im Browser (Datei ``web_static/chart.umd.js``; fehlt sie, lädt die Seite
                Chart.js ersatzweise aus dem Internet, siehe CDN_URL).

Adressen
--------
``/``             die Seite (eine Seite je „Seite/Tab“ der Konfiguration, Diagramme als Kacheln)
``/api/config``   Struktur: Projekt, Seiten, Diagramme, Y-Achsen, Variablen
``/api/data``     Messdaten eines Zeitfensters (Parameter: window = Sekunden, end = Endzeit, max = Punkte je Kurve)
``/api/status``   Zustand der Steuerungen und letzte Werte

Zugriffsschutz: Ist in der Konfiguration ein Zugriffscode (web_token) eingetragen, müssen alle Aufrufe ihn als
``?token=...`` mitschicken (die Seite übernimmt ihn aus ihrer Adresse). Die Verbindung ist unverschlüsselt (HTTP)
– nur in vertrauenswürdigen Netzen verwenden.
"""
import gzip
import json
import os
import socket
import sys
import threading

from flask import Flask, Response, abort, request, send_from_directory
from werkzeug.serving import make_server

from clx_common import BASE_DIR
from clx_util import decimate_minmax

# Ersatzquelle für Chart.js, falls web_static/chart.umd.js fehlt (benötigt Internet auf dem Anzeigegerät).
CDN_URL = "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.js"


def static_dirs():
    """Ordner, in denen web_static/chart.umd.js gesucht wird (zuerst der des Benutzers, dann der mitgelieferte)."""
    dirs = []
    if os.environ.get("CLX_WEB_STATIC"):
        dirs.append(os.environ["CLX_WEB_STATIC"])
    dirs.append(os.path.join(BASE_DIR, "web_static"))
    dirs.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_static"))
    if getattr(sys, "frozen", False):                   # PyInstaller: mitgelieferte Dateien
        dirs.append(os.path.join(getattr(sys, "_MEIPASS", ""), "web_static"))
        dirs.append(os.path.join(os.path.dirname(sys.executable), "web_static"))
    return [d for d in dirs if os.path.isdir(d)]


def page_groups(charts):
    """Seiten bestimmen: [(Seitenname, [Diagramm-Indizes])] – wie im Logger: gleicher Seitenname = gleiche Seite;
    ohne Seitenangaben liegen alle Diagramme auf einer Seite."""
    if not any(c.page for c in charts):
        return [("Diagramme", list(range(len(charts))))]
    groups = {}
    for ci, c in enumerate(charts):
        groups.setdefault(c.page or c.name, []).append(ci)
    return list(groups.items())


def _clean(arr, digits=5):
    """numpy-Feld -> Liste für JSON; NaN wird zu null (Lücke in der Linie)."""
    return [None if v != v else round(v, digits) for v in arr.tolist()]


def local_ip():
    """IP-Adresse des Rechners im lokalen Netz (für die Anzeige der Adresse); ohne Netz 127.0.0.1."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))            # es wird nichts gesendet; nur die Route wird bestimmt
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def create_app(get_rec, token="", refresh_ms=1000):
    """Flask-Anwendung. ``get_rec`` liefert bei jedem Aufruf den aktuellen Recorder (oder None)."""
    app = Flask(__name__, static_folder=None)    # eigene Route für statische Dateien (siehe unten)
    app.config["JSON_AS_ASCII"] = False

    def reply(obj, status=200):
        """JSON-Antwort, bei größeren Daten und gzip-fähigem Browser komprimiert (spart Mobilfunk-Datenvolumen)."""
        raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers = {"Cache-Control": "no-store"}
        if len(raw) > 1500 and "gzip" in request.headers.get("Accept-Encoding", ""):
            raw = gzip.compress(raw, 4)
            headers["Content-Encoding"] = "gzip"
        return Response(raw, status=status, mimetype="application/json", headers=headers)

    @app.before_request
    def check_token():
        """Zugriffscode prüfen (Chart.js-Datei ist frei abrufbar, sie enthält keine Daten)."""
        if token and not request.path.startswith("/static/"):
            if request.args.get("token", "") != token and request.headers.get("X-Token", "") != token:
                abort(401)

    @app.route("/")
    def index():
        return Response(INDEX_HTML.replace("__CDN__", CDN_URL), mimetype="text/html")

    @app.route("/static/<path:name>")
    def static_file(name):
        for d in static_dirs():
            if os.path.exists(os.path.join(d, name)):
                return send_from_directory(d, name, max_age=3600)
        abort(404)

    @app.route("/api/config")
    def api_config():
        rec = get_rec()
        if rec is None:
            return reply({"version": None, "message": "Keine Aufzeichnung aktiv", "refresh_ms": refresh_ms})
        charts_out = []
        for ci, ch in enumerate(rec.charts):
            vars_out = [{"i": vi, "name": v.name, "dtype": v.dtype, "color": v.color, "axis": v.axis}
                        for vi, v in enumerate(rec.vars) if v.chart == ci]
            charts_out.append({"i": ci, "name": ch.name, "vars": vars_out,
                               "axes": [{"name": a.name, "auto": a.auto, "min": a.y_min, "max": a.y_max}
                                        for a in ch.axes]})
        return reply({"version": id(rec), "project": rec.conn.get("projekt", ""), "refresh_ms": refresh_ms,
                      "pages": [{"name": n, "charts": c} for n, c in page_groups(rec.charts)],
                      "charts": charts_out})

    @app.route("/api/data")
    def api_data():
        rec = get_rec()
        if rec is None:
            return reply({"version": None})
        try:
            window = min(max(float(request.args.get("window", 60)), 1.0), 7 * 86400.0)
            maxpts = min(max(int(request.args.get("max", 400)), 50), 3000)
            end = request.args.get("end", "")
            end = float(end) if end else None
        except ValueError:
            abort(400)
        last_t, _ = rec.last_row()
        if last_t is None:
            return reply({"version": id(rec), "empty": True, "plcs": _plcs(rec)})
        t1 = end if end is not None else last_t
        t0 = t1 - window
        t, y = rec.slice_time(t0, t1)
        series = {}
        for vi in range(len(rec.vars)):
            xs, ys = decimate_minmax(t, y[vi], maxpts // 2) if len(t) else (t, t)
            # Zeit relativ zu t0 (kleinere Zahlen = weniger Daten), auf 10 ms gerundet.
            series[vi] = {"x": _clean(xs - t0, 2), "y": _clean(ys)}
        values = {vi: (None if len(t) == 0 or y[vi][-1] != y[vi][-1] else round(float(y[vi][-1]), 5))
                  for vi in range(len(rec.vars))}
        return reply({"version": id(rec), "t0": t0, "t1": t1, "last": last_t, "live": end is None,
                      "series": series, "values": values, "plcs": _plcs(rec), "rows": rec.count(),
                      "running": rec.running, "events": _events(rec)})

    @app.route("/api/status")
    def api_status():
        rec = get_rec()
        if rec is None:
            return reply({"version": None})
        return reply({"version": id(rec), "plcs": _plcs(rec), "rows": rec.count(), "running": rec.running,
                      "events": _events(rec)})

    ev_cache = {}

    def _events(rec):
        """Offene (unquittierte) Ereignisse für die Anzeige im Kopf der Seite; Quittieren nur im Viewer."""
        log = getattr(rec, "events", None)
        if log is None:
            return {"open": 0, "list": []}
        try:
            if log.changed_on_disk():
                log.reload()
            key = (id(log), log.version)
            if ev_cache.get("key") != key:
                lst = [{"zeit": e.zeit[:19], "prio": e.prio, "trigger": e.trigger, "text": e.text}
                       for e in log.events() if e.offen][:20]
                ev_cache.update(key=key, value={"open": log.open_count(), "list": lst})
            return ev_cache["value"]
        except Exception:
            return {"open": 0, "list": []}

    def _plcs(rec):
        return [{"name": n, "state": s, "text": t, "read_ms": round(ms, 1)} for n, s, t, ms in rec.status_list()]

    return app


class WebServer:
    """Startet die Flask-Anwendung in einem eigenen Thread (werkzeug-Server, mehrere Anfragen gleichzeitig)."""

    def __init__(self, get_rec, host="0.0.0.0", port=8080, token="", refresh_ms=1000):
        self.host, self.port = host, int(port)
        self.app = create_app(get_rec, token, refresh_ms)
        self.srv = None
        self.thread = None

    def start(self):
        """Server starten; wirft OSError, wenn der Port belegt ist."""
        self.srv = make_server(self.host, self.port, self.app, threaded=True)
        self.thread = threading.Thread(target=self.srv.serve_forever, name="webserver", daemon=True)
        self.thread.start()

    def stop(self):
        if self.srv:
            self.srv.shutdown()
            self.srv = None

    def url(self):
        """Adresse für Tablet/Smartphone im selben Netz."""
        host = local_ip() if self.host in ("0.0.0.0", "") else self.host
        return f"http://{host}:{self.port}/"


# ---------------------------------------------------------------------------------------
# Die Seite (HTML, CSS und JavaScript in einer Datei, damit nichts weiter ausgeliefert werden muss)
# ---------------------------------------------------------------------------------------
INDEX_HTML = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CLX Datenlogger</title>
<style>
:root{--bg:#10151b;--card:#18202a;--fg:#dfe6ee;--mute:#8b98a7;--line:#2a3544;--accent:#4aa3ff;
 --ok:#2ecc71;--err:#ff5252;--warn:#ffc107;--off:#6b7785;color-scheme:dark}
@media (prefers-color-scheme:light){:root{--bg:#f2f4f7;--card:#fff;--fg:#1b2430;--mute:#5b6878;--line:#d5dbe3;
 --accent:#0a6fd6;--off:#9aa5b1;color-scheme:light}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.4 system-ui,"Segoe UI",Roboto,Arial,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line);padding:8px 12px}
.row{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px}
h1{font-size:17px;margin:0;font-weight:600}
.leds{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:13px;color:var(--mute)}
.evbadge{background:#c62828;color:#fff;border-radius:10px;padding:0 8px;font-weight:600;cursor:help}
.led{display:inline-block;width:11px;height:11px;border-radius:50%;background:var(--off);margin-right:5px;
 vertical-align:-1px;box-shadow:0 0 0 1px rgba(0,0,0,.25) inset}
.led.ok{background:var(--ok);box-shadow:0 0 6px var(--ok)}.led.error{background:var(--err)}
.led.connecting{background:var(--warn)}
.ctrl{display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-size:14px}
button,select{background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:6px 10px;
 font:inherit;min-height:34px}
button:active{background:var(--line)}
button.on{border-color:var(--accent);color:var(--accent)}
label.chk{display:flex;gap:5px;align-items:center;color:var(--mute)}
nav{display:flex;gap:6px;overflow-x:auto;margin-top:8px}
nav button{white-space:nowrap}
nav button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
main{padding:10px;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 10px;min-width:0}
.card h2{font-size:14px;margin:0 0 6px;font-weight:600}
.cv{position:relative;height:300px}
@media (max-width:600px){.cv{height:240px}}
.legend{display:flex;flex-wrap:wrap;gap:4px 14px;margin-top:6px;font-size:13px}
.it{display:flex;align-items:center;gap:6px;cursor:pointer;user-select:none;-webkit-user-select:none}
.sw{width:16px;height:4px;border-radius:2px;flex:none}
.it canvas{flex:none}
.it.off{opacity:.4}.it.dim{opacity:.55}.it.hl .nm{font-weight:700}
.msg{padding:30px;text-align:center;color:var(--mute);grid-column:1/-1}
.info{font-size:12px;color:var(--mute)}
</style>
</head>
<body>
<header>
 <div class="row"><h1 id="proj">CLX Datenlogger</h1><div class="leds" id="leds"></div>
  <span class="info" id="info"></span></div>
 <div class="ctrl" style="margin-top:6px">
  <select id="win" title="Zeitfenster"></select>
  <button id="back" title="Zurück in der Zeit">◀</button>
  <button id="fwd" title="Vorwärts">▶</button>
  <button id="live" class="on">Live</button>
  <button id="pause" title="Anzeige anhalten">⏸</button>
  <label class="chk"><input type="checkbox" id="boolplot"> Bool im Diagramm</label>
 </div>
 <nav id="tabs"></nav>
</header>
<main id="main"><div class="msg">Lade …</div></main>
<script>
(function(){
'use strict';
var TOKEN=new URLSearchParams(location.search).get('token')||'';
function api(u){return TOKEN?u+(u.indexOf('?')<0?'?':'&')+'token='+encodeURIComponent(TOKEN):u;}
function $(id){return document.getElementById(id);}
function store(k,v){try{if(v===undefined)return localStorage.getItem('clx_'+k);localStorage.setItem('clx_'+k,v);}catch(e){return null;}}
function css(n){return getComputedStyle(document.documentElement).getPropertyValue(n).trim();}
function hexA(c,a){var m=/^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(c);
 return m?'rgba('+parseInt(m[1],16)+','+parseInt(m[2],16)+','+parseInt(m[3],16)+','+a+')':c;}
function fmtVal(v,dt){if(v===null||v===undefined)return '—';
 return (dt==='REAL'||dt==='LREAL')?v.toFixed(3):String(Math.round(v));}
function pad(n,l){n=String(n);while(n.length<(l||2))n='0'+n;return n;}
function fmtT(ms,withMs){var d=new Date(ms);var s=pad(d.getHours())+':'+pad(d.getMinutes())+':'+pad(d.getSeconds());
 return withMs?s+'.'+pad(d.getMilliseconds(),3):s;}
function fmtD(ms){var d=new Date(ms);return pad(d.getDate())+'.'+pad(d.getMonth()+1)+'.'+d.getFullYear()+' '+fmtT(ms,true);}

var cfg=null, ver=null, cos=[], curPage=0, endT=null, paused=false, lastRes=null, busy=false, timer=null;
var winS=parseInt(store('win')||'60',10), boolPlot=store('bool')==='1';
var WINS=[[10,'10 s'],[30,'30 s'],[60,'1 min'],[300,'5 min'],[900,'15 min'],[3600,'1 h'],[21600,'6 h'],[86400,'24 h']];

function msg(t){$('main').innerHTML='<div class="msg">'+t+'</div>';}

/* ---------- Chart.js laden: lokal, sonst aus dem Netz ---------- */
function loadChartJs(cb){
 if(window.Chart){cb();return;}
 var s=document.createElement('script');s.src='static/chart.umd.js';
 s.onload=cb;
 s.onerror=function(){var c=document.createElement('script');c.src='__CDN__';c.onload=cb;
  c.onerror=function(){msg('Chart.js konnte nicht geladen werden. Datei <code>web_static/chart.umd.js</code> '+
   'neben das Programm legen (siehe Bedienungsanleitung).');};document.head.appendChild(c);};
 document.head.appendChild(s);
}

/* ---------- Aufbau ---------- */
function destroyAll(){cos.forEach(function(c){if(c.chart)c.chart.destroy();});cos=[];}
function build(){
 destroyAll();
 $('proj').textContent=cfg.project?('CLX Datenlogger – '+cfg.project):'CLX Datenlogger';
 document.title=$('proj').textContent;
 var tabs=$('tabs');tabs.innerHTML='';
 cfg.pages.forEach(function(p,pi){
  var b=document.createElement('button');b.textContent=p.name;b.onclick=function(){showPage(pi);};tabs.appendChild(b);});
 tabs.style.display=cfg.pages.length>1?'flex':'none';
 var main=$('main');main.innerHTML='';
 cfg.charts.forEach(function(ch){
  var card=document.createElement('div');card.className='card';
  card.innerHTML='<h2></h2><div class="cv"><canvas></canvas></div><div class="legend"></div>';
  card.querySelector('h2').textContent=ch.name;
  main.appendChild(card);
  var co={ch:ch,card:card,hidden:{},hl:null,items:{},chart:null};
  makeChart(co);makeLegend(co);cos.push(co);
 });
 showPage(Math.min(curPage,cfg.pages.length-1));
}
function showPage(pi){
 curPage=pi;
 var tb=$('tabs').children;for(var i=0;i<tb.length;i++)tb[i].className=i===pi?'on':'';
 var vis={};cfg.pages[pi].charts.forEach(function(ci){vis[ci]=1;});
 cos.forEach(function(co){co.card.style.display=vis[co.ch.i]?'':'none';if(vis[co.ch.i]&&co.chart)co.chart.resize();});
}
function makeChart(co){
 var ch=co.ch, fg=css('--fg'), grid=hexA(fg,0.12);
 var scales={x:{type:'linear',ticks:{color:fg,maxTicksLimit:6,callback:function(v){return fmtT(v,false);}},
  grid:{color:grid}}};
 var axisColor={};
 ch.vars.forEach(function(v){if(v.dtype!=='BOOL'&&axisColor[v.axis]===undefined)axisColor[v.axis]=v.color;});
 ch.axes.forEach(function(a,k){
  var col=axisColor[k]||fg;
  var sc={type:'linear',position:k===0?'left':'right',ticks:{color:col},grid:{color:grid,drawOnChartArea:k===0},
   border:{color:col},title:{display:true,text:a.name,color:col},grace:'5%'};
  if(!a.auto){sc.min=a.min;sc.max=a.max;sc.grace=0;}
  scales['y'+k]=sc;});
 scales.yb={display:false,min:-0.05,max:1.05,position:'right',grid:{drawOnChartArea:false}};
 var ds=ch.vars.map(function(v){
  var b=v.dtype==='BOOL';
  return {label:v.name,_vi:v.i,_dt:v.dtype,data:[],borderColor:v.color,borderWidth:2,pointRadius:0,pointHitRadius:8,
   tension:0,spanGaps:false,yAxisID:b?'yb':'y'+Math.min(v.axis,ch.axes.length-1),stepped:b?'after':false,
   fill:b?'origin':false,backgroundColor:b?hexA(v.color,0.22):v.color,hidden:b&&!boolPlot};});
 co.chart=new Chart(co.card.querySelector('canvas'),{type:'line',plugins:[boolLanes],data:{datasets:ds},options:{
  animation:false,parsing:false,normalized:true,responsive:true,maintainAspectRatio:false,
  interaction:{mode:'nearest',intersect:false,axis:'x'},
  plugins:{legend:{display:false},tooltip:{callbacks:{title:function(it){return it.length?fmtD(it[0].parsed.x):'';},
   label:function(c){return c.dataset.label+': '+fmtVal(c.parsed.y,c.dataset._dt);}}}},
  scales:scales}});
}
function makeLegend(co){
 var lg=co.card.querySelector('.legend');lg.innerHTML='';
 co.ch.vars.forEach(function(v){
  var it=document.createElement('div');it.className='it';
  var vis=document.createElement('span');
  vis.className='sw';vis.style.background=v.color;
  var nm=document.createElement('span');nm.className='nm';nm.style.color=v.color;nm.textContent=v.name;
  it.appendChild(vis);it.appendChild(nm);lg.appendChild(it);
  co.items[v.i]={el:it,nm:nm,vis:vis,v:v};
  /* Tippen/Klicken: Kurve hervorheben; langes Drücken bzw. Doppelklick: ein-/ausblenden */
  var tmr=null,long=false;
  it.addEventListener('pointerdown',function(){long=false;tmr=setTimeout(function(){long=true;toggleHide(co,v.i);},600);});
  it.addEventListener('pointerup',function(){clearTimeout(tmr);if(!long)toggleHl(co,v.i);});
  it.addEventListener('pointerleave',function(){clearTimeout(tmr);});
  it.addEventListener('contextmenu',function(e){e.preventDefault();});
  it.addEventListener('dblclick',function(){toggleHide(co,v.i);});
 });
}
function toggleHl(co,vi){co.hl=co.hl===vi?null:vi;style(co);}
function toggleHide(co,vi){if(co.hidden[vi])delete co.hidden[vi];else co.hidden[vi]=1;style(co);}
function style(co){
 co.chart.data.datasets.forEach(function(d){
  var v=co.items[d._vi].v,isB=v.dtype==='BOOL';
  d.hidden=!!co.hidden[d._vi]||(isB&&!boolPlot);
  var on=co.hl===d._vi,faded=co.hl!==null&&!on;
  d.borderColor=faded?hexA(v.color,0.3):v.color;d.borderWidth=on?4:2;
  if(isB)d.backgroundColor=hexA(v.color,faded?0.08:0.22);
  d.order=on?-1:0;
 });
 Object.keys(co.items).forEach(function(k){var it=co.items[k];
  it.el.className='it'+(co.hidden[k]?' off':'')+(co.hl!==null&&co.hl!==+k?' dim':'')+(co.hl===+k?' hl':'');});
 co.chart.update('none');
}
/* BOOL-Signale: je BOOL-Variable eine Zeile im oberen Teil des Diagramms - Name links, rechts davon über die Diagrammbreite
   eine Linie auf der Grundlinie (Wert 0) bzw. ein nach oben gehender Streifen (Wert 1), wie ein digitales Signal. */
var boolLanes={id:'boolLanes',afterDatasetsDraw:function(chart){
 var co=null;cos.forEach(function(c){if(c.chart===chart)co=c;});if(!co)return;
 var rows=chart.data.datasets.filter(function(d){var it=co.items[d._vi];return it&&it.v.dtype==='BOOL'&&!co.hidden[d._vi];});
 if(!rows.length)return;
 var ctx=chart.ctx,ca=chart.chartArea,xs=chart.scales.x,rowH=20,hh=10;
 ctx.save();ctx.font='12px sans-serif';ctx.textBaseline='alphabetic';
 var lw=0;rows.forEach(function(d){lw=Math.max(lw,ctx.measureText(d.label).width);});
 var xl=ca.left+8+lw+10;
 rows.forEach(function(d,k){
  var v=co.items[d._vi].v,on=co.hl===d._vi,faded=co.hl!==null&&!on,base=ca.top+18+k*rowH;
  var col=faded?hexA(v.color,0.3):v.color,h=on?13:hh;
  ctx.fillStyle=col;ctx.fillText(d.label,ca.left+8,base);
  ctx.save();ctx.beginPath();ctx.rect(xl,ca.top,ca.right-xl,ca.bottom-ca.top);ctx.clip();
  ctx.strokeStyle=col;ctx.lineWidth=on?3:2;
  var pts=d.data;
  for(var i=0;i<pts.length;i++){
   var xa=xs.getPixelForValue(pts[i].x),xb=i+1<pts.length?xs.getPixelForValue(pts[i+1].x):ca.right;
   xa=Math.max(xa,xl);xb=Math.min(xb,ca.right);if(xb<=xa)continue;
   if(pts[i].y!==null&&pts[i].y>=0.5)ctx.fillRect(xa,base-h,xb-xa,h);
   else{ctx.beginPath();ctx.moveTo(xa,base);ctx.lineTo(xb,base);ctx.stroke();}
  }
  ctx.restore();});
 ctx.restore();}};

/* ---------- Daten ---------- */
function leds(plcs,ev){
 var h='';(plcs||[]).forEach(function(p){
  h+='<span title="'+(p.text+(p.read_ms?(' – Zyklus '+p.read_ms+' ms'):'')).replace(/"/g,'&quot;')+
   '"><i class="led '+p.state+'"></i>'+p.name.replace(/</g,'&lt;')+'</span>';});
 if(ev&&ev.open){
  var tip=ev.list.map(function(e){return e.zeit+'  '+e.prio+'  '+e.trigger+(e.text?(': '+e.text):'');}).join('\n');
  h+='<span class="evbadge" title="'+(tip+'\n(Quittieren im Ereignis-Viewer des Loggers)').replace(/"/g,'&quot;')
   .replace(/</g,'&lt;')+'">🔔 '+ev.open+' offen</span>';}
 $('leds').innerHTML=h;
}
function apply(res){
 lastRes=res;leds(res.plcs,res.events);
 if(res.empty){$('info').textContent='noch keine Daten';return;}
 $('info').textContent=(res.live?'Live ':'Verlauf ')+fmtD(res.t1*1000)+(res.running?'':' · gestoppt');
 cos.forEach(function(co){
  var sc=co.chart.options.scales;sc.x.min=res.t0*1000;sc.x.max=res.t1*1000;
  co.chart.data.datasets.forEach(function(d){
   var s=res.series[d._vi],a=[];
   if(s){for(var i=0;i<s.x.length;i++)a.push({x:(res.t0+s.x[i])*1000,y:s.y[i]});}
   d.data=a;});
  style(co);
  Object.keys(co.items).forEach(function(k){var it=co.items[k],v=it.v;
   it.nm.textContent=v.name+': '+fmtVal(res.values[k],v.dtype)+(co.hidden[k]?' (aus)':'');});
 });
}
function fetchJson(u){return fetch(api(u),{cache:'no-store'}).then(function(r){
 if(r.status===401)throw new Error('Zugriff verweigert – Zugriffscode in der Adresse fehlt (?token=…)');
 if(!r.ok)throw new Error('Serverfehler '+r.status);return r.json();});}
function loadConfig(){
 return fetchJson('/api/config').then(function(c){
  if(c.version===null){cfg=null;ver=null;destroyAll();msg(c.message||'Keine Aufzeichnung aktiv');leds([]);return;}
  cfg=c;ver=c.version;build();
  clearInterval(timer);timer=setInterval(tick,Math.max(c.refresh_ms||1000,200));});
}
function refresh(){
 if(busy)return;busy=true;
 var w=Math.max(cos.length?cos[0].card.querySelector('canvas').clientWidth:400,200);
 var u='/api/data?window='+winS+'&max='+Math.min(Math.round(w),1500)+(endT!==null?'&end='+endT:'');
 fetchJson(u).then(function(res){
  busy=false;
  if(res.version!==ver){return loadConfig();}
  apply(res);
 }).catch(function(e){busy=false;$('info').textContent='⚠ '+e.message;});
}
function tick(){
 if(!cfg){loadConfig().catch(function(e){msg('⚠ '+e.message);});return;}
 if(!paused&&endT===null)refresh();
}

/* ---------- Bedienung ---------- */
function init(){
 var sel=$('win');WINS.forEach(function(w){var o=document.createElement('option');o.value=w[0];o.textContent=w[1];
  if(w[0]===winS)o.selected=true;sel.appendChild(o);});
 if(!WINS.some(function(w){return w[0]===winS;})){winS=60;sel.value='60';}
 sel.onchange=function(){winS=+sel.value;store('win',String(winS));refresh();};
 $('back').onclick=function(){var base=endT!==null?endT:(lastRes?lastRes.t1:0);endT=base-winS/2;
  $('live').className='';refresh();};
 $('fwd').onclick=function(){if(endT===null)return;endT+=winS/2;
  if(lastRes&&endT>=lastRes.last){endT=null;$('live').className='on';}refresh();};
 $('live').onclick=function(){endT=null;paused=false;$('pause').className='';$('live').className='on';refresh();};
 $('pause').onclick=function(){paused=!paused;$('pause').className=paused?'on':'';};
 var bp=$('boolplot');bp.checked=boolPlot;
 bp.onchange=function(){boolPlot=bp.checked;store('bool',boolPlot?'1':'0');cos.forEach(style);};
 tick();
 timer=setInterval(tick,1000);
}
loadChartJs(init);
window.addEventListener('resize',function(){cos.forEach(function(c){if(c.chart)c.chart.resize();});});
})();
</script>
</body>
</html>
"""
