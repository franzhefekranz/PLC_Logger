# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Prozessbild im Browser (Webserver, Adresse ``/prozess``): Kacheln mit Zahlenwert, Zeigerinstrument, Balken,
Zustandslampe, Kurzverlauf und Text – frei auf einem Raster angeordnet, mehrere Seiten.

Bearbeitet wird direkt in der Webseite (Knopf *Bearbeiten*: Kacheln verschieben, Größe ändern, Eigenschaften); das
Layout steht in einer eigenen Datei neben der Konfiguration (``<Konfiguration>.prozessbild.json``), damit das
Konfigurationsprogramm es nicht überschreibt. Bearbeiten dürfen angemeldete Benutzer; ist keine Anmeldung
eingerichtet, jeder mit Zugang zur Seite (Aufruf nur mit Zugriffscode: nur ansehen).

Variablen werden über ihren Namen angesprochen – die Kacheln bleiben gültig, wenn sich die Reihenfolge der Variablen
ändert. Ohne gespeichertes Layout zeigt die Seite einen Vorschlag (je Variable eine Kachel).
"""
import json
import os
import re

TYPES = ("wert", "zeiger", "balken", "status", "trend", "text")
COLS = 12
MAX_PAGES, MAX_TILES = 20, 300
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_NUM_KEYS = ("min", "max", "ug_alarm", "ug_warn", "og_warn", "og_alarm")
_STR_KEYS = {"var": 120, "titel": 80, "einheit": 20, "text_ein": 40, "text_aus": 40}


def layout_path(config_path):
    """Datei des Prozessbilds zur Konfiguration (ohne Konfiguration: im Datenordner)."""
    if config_path:
        return os.path.splitext(config_path)[0] + ".prozessbild.json"
    from plc_common import BASE_DIR
    return os.path.join(BASE_DIR, "prozessbild.json")


def _num(v, default=None):
    """Eingabe als endliche Zahl (Text oder Zahl) oder ``default`` – NaN, unendlich und riesige Werte werden abgewiesen.
    """
    if v is None or v == "":
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if f == f and abs(f) < 1e15 else default


def _int(v, lo, hi, default):
    """Eingabe als ganze Zahl, begrenzt auf lo … hi; ungültig: ``default``."""
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def clean_tile(t) -> dict:
    """Eine Kachel prüfen und auf bekannte Felder beschränken (Eingaben aus dem Browser)."""
    if not isinstance(t, dict):
        raise ValueError("Kachel")
    typ = t.get("typ") if t.get("typ") in TYPES else "wert"
    out = {"typ": typ, "x": _int(t.get("x"), 0, COLS - 1, 0), "y": _int(t.get("y"), 0, 199, 0),
           "w": _int(t.get("w"), 1, COLS, 2), "h": _int(t.get("h"), 1, 12, 2)}
    out["w"] = min(out["w"], COLS - out["x"])
    for k, n in _STR_KEYS.items():
        v = t.get(k)
        if v not in (None, ""):
            out[k] = str(v)[:n]
    for k in _NUM_KEYS:
        v = _num(t.get(k))
        if v is not None:
            out[k] = v
    if t.get("nk") not in (None, ""):
        out["nk"] = _int(t.get("nk"), -1, 6, -1)
    if t.get("fenster_s") not in (None, ""):
        out["fenster_s"] = _int(t.get("fenster_s"), 10, 86400, 300)
    for k in ("farbe_ein", "farbe_aus", "farbe"):
        if isinstance(t.get(k), str) and _COLOR.match(t[k]):
            out[k] = t[k]
    if t.get("invert"):
        out["invert"] = True
    return out


def clean_layout(doc) -> dict:
    """Layout {"seiten": [{"name", "kacheln": [...]}]} prüfen -> bereinigte Fassung (ValueError bei Unsinn)."""
    if not isinstance(doc, dict) or not isinstance(doc.get("seiten"), list):
        raise ValueError("Layout")
    pages, n = [], 0
    for p in doc["seiten"][:MAX_PAGES]:
        if not isinstance(p, dict):
            raise ValueError("Seite")
        tiles = []
        for t in (p.get("kacheln") or [])[:MAX_TILES]:
            tiles.append(clean_tile(t))
            n += 1
            if n > MAX_TILES:
                raise ValueError("zu viele Kacheln")
        pages.append({"name": str(p.get("name") or "Seite")[:40], "kacheln": tiles})
    return {"seiten": pages or [{"name": "Übersicht", "kacheln": []}]}


def load_layout(config_path):
    """Gespeichertes Layout zur Konfiguration lesen und prüfen -> dict oder None (fehlt bzw. unlesbar)."""
    path = layout_path(config_path)
    try:
        with open(path, encoding="utf-8") as f:
            return clean_layout(json.load(f))
    except (OSError, ValueError):
        return None


def save_layout(config_path, doc):
    """Layout prüfen und speichern (erst in eine temporäre Datei, dann ersetzen) -> die bereinigte Fassung."""
    path = layout_path(config_path)
    doc = clean_layout(doc)
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return doc


def default_layout(variables) -> dict:
    """Vorschlag ohne gespeichertes Layout: BOOL als Lampe, sonst Zahlenwert; berechnete Variablen ebenso."""
    tiles, x, y = [], 0, 0
    for v in variables:
        if getattr(v, "block", "") and getattr(v, "block_idx", 0) > 7:
            continue
        typ = "status" if v.dtype == "BOOL" else "wert"
        w = 2 if typ == "status" else 3
        if x + w > COLS:
            x, y = 0, y + 2
        tiles.append({"typ": typ, "var": v.name, "x": x, "y": y, "w": w, "h": 2})
        x += w
        if len(tiles) >= 60:
            break
    return {"seiten": [{"name": "Übersicht", "kacheln": tiles}]}


PROZESS_HTML = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prozessbild – PLC Datenlogger</title>
<style>
:root{--bg:#10151b;--card:#18202a;--fg:#dfe6ee;--mute:#8b98a7;--line:#2a3544;--accent:#4aa3ff;
 --ok:#2ecc71;--err:#ff5252;--warn:#ffb300;--off:#6b7785;color-scheme:dark}
@media (prefers-color-scheme:light){:root{--bg:#eef1f5;--card:#fff;--fg:#1b2430;--mute:#5b6878;--line:#d5dbe3;
 --accent:#0a6fd6;--off:#9aa5b1;--warn:#e69500;color-scheme:light}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.35 system-ui,"Segoe UI",Roboto,Arial,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line);padding:8px 12px}
.row{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px}
h1{font-size:17px;margin:0;font-weight:600}
.leds{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:13px;color:var(--mute)}
.led{display:inline-block;width:11px;height:11px;border-radius:50%;background:var(--off);margin-right:5px;vertical-align:-1px}
.led.ok{background:var(--ok);box-shadow:0 0 6px var(--ok)}.led.error{background:var(--err)}.led.connecting{background:var(--warn)}
.lnk{color:var(--mute);text-decoration:none;font-size:13px;border:1px solid var(--line);border-radius:6px;padding:4px 8px}
button,select,input{background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:5px 9px;font:inherit}
button{min-height:32px;cursor:pointer}button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
nav{display:flex;gap:6px;overflow-x:auto;margin-top:8px}nav button{white-space:nowrap}
.info{font-size:12px;color:var(--mute)}
#grid{display:grid;grid-template-columns:repeat(12,1fr);grid-auto-rows:84px;gap:8px;padding:10px;position:relative}
@media (max-width:700px){#grid{grid-template-columns:repeat(4,1fr);grid-auto-rows:78px;grid-auto-flow:row dense}}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 10px;min-width:0;min-height:0;
 display:flex;flex-direction:column;overflow:hidden;position:relative}
.tile .t{font-size:13px;color:var(--mute);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tile .body{flex:1;min-height:0;display:flex;align-items:center;justify-content:center;position:relative}
.val{font-weight:650;font-variant-numeric:tabular-nums;white-space:nowrap;line-height:1}
.unit{font-size:.45em;color:var(--mute);margin-left:.25em;font-weight:500}
.tile.warn{border-color:var(--warn);box-shadow:0 0 0 1px var(--warn) inset}
.tile.alarm{border-color:var(--err);box-shadow:0 0 0 2px var(--err) inset}
.tile.alarm .val{color:var(--err)}.tile.warn .val{color:var(--warn)}
.tile.stale .val{color:var(--mute)}
.lamp{width:34px;height:34px;border-radius:50%;flex:none;background:var(--off);margin-right:10px}
.stxt{font-weight:600;font-size:18px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar{position:absolute;left:0;right:0;bottom:13px;height:14px;border-radius:8px;background:var(--line);overflow:hidden}
.bar i{position:absolute;left:0;top:0;bottom:0;background:var(--accent);border-radius:8px}
.bar.v{left:auto;right:auto;top:0;bottom:0;width:22px;height:auto}
.bar.v i{top:auto;right:0;width:auto;border-radius:8px}
.mm{position:absolute;bottom:0;left:0;right:0;display:flex;justify-content:space-between;font-size:11px;color:var(--mute)}
svg{display:block;width:100%;height:100%}
.txt{font-weight:600;white-space:pre-wrap;overflow:hidden}
.msg{padding:30px;text-align:center;color:var(--mute);grid-column:1/-1}
/* Bearbeiten */
body.edit #grid{background-image:linear-gradient(var(--line) 1px,transparent 1px),linear-gradient(90deg,var(--line) 1px,transparent 1px);
 background-size:calc((100% - 20px + 8px)/12) 92px;background-position:10px 10px}
body.edit .tile{cursor:move;touch-action:none;outline:1px dashed var(--mute)}
body.edit .tile.sel{outline:2px solid var(--accent)}
.rs{display:none;position:absolute;right:0;bottom:0;width:18px;height:18px;cursor:nwse-resize;touch-action:none;
 background:linear-gradient(135deg,transparent 50%,var(--accent) 50%)}
body.edit .rs{display:block}
#panel{display:none;position:fixed;right:0;top:0;bottom:0;width:300px;max-width:100%;z-index:9;background:var(--card);
 border-left:1px solid var(--line);padding:12px;overflow:auto;box-shadow:-6px 0 20px rgba(0,0,0,.3)}
body.edit #panel{display:block}
body.edit main{margin-right:300px}
#panel h3{margin:4px 0 8px;font-size:15px}
#panel label{display:block;font-size:12px;color:var(--mute);margin-top:7px}
#panel input,#panel select{width:100%}
#panel .two{display:flex;gap:6px}#panel .two>div{flex:1}
#panel .btns{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}
.hint{font-size:12px;color:var(--mute);margin-top:10px}
.err{color:var(--err)}
</style>
</head>
<body>
<header>
 <div class="row"><h1 id="proj">Prozessbild</h1><div class="leds" id="leds"></div><span class="info" id="info"></span>
  <span style="flex:1"></span><button id="edit" style="display:none">✎ Bearbeiten</button>__LINKS__</div>
 <nav id="tabs"></nav>
</header>
<main><div id="grid"><div class="msg">Lade …</div></div></main>
<div id="panel">
 <h3>Prozessbild bearbeiten</h3>
 <div class="btns"><button id="add">+ Kachel</button><button id="dup">Kopie</button><button id="del">Löschen</button></div>
 <div id="props"></div>
 <label>Seite</label>
 <div class="two"><div><input id="pname"></div><div style="flex:0 0 auto"><button id="padd" title="Neue Seite">+</button>
  <button id="pdel" title="Seite löschen">−</button></div></div>
 <div class="btns"><button id="save" class="on">Speichern</button><button id="cancel">Abbrechen</button>
  <button id="auto" title="Je Variable eine Kachel (ersetzt die Seite)">Vorschlag</button></div>
 <div class="hint">Kachel ziehen = verschieben, Ecke unten rechts = Größe. Raster 12 Spalten.</div>
 <div id="perr" class="err"></div>
</div>
<script>
(function(){
'use strict';
/* Ablauf: load() holt Layout und Variablen (/api/prozess) und baut die Kacheln (build); tick() holt im Takt der
   Webserver-Einstellung die aktuellen Werte (/api/data, für Kurzverläufe mit Verlauf) und render() trägt sie ein.
   Bearbeiten (setEdit): Kacheln ziehen/vergrößern (dragHandlers), Eigenschaften rechts (props), Speichern = POST.
   Alle Texte aus dem Layout werden mit textContent gesetzt (nie als HTML) – Titel können nichts einschleusen. */
var TOKEN=new URLSearchParams(location.search).get('token')||'';
function api(u){return TOKEN?u+(u.indexOf('?')<0?'?':'&')+'token='+encodeURIComponent(TOKEN):u;}
function $(id){return document.getElementById(id);}
function el(tag,cls,txt){var e=document.createElement(tag);if(cls)e.className=cls;if(txt!==undefined)e.textContent=txt;return e;}
var SVGNS='http://www.w3.org/2000/svg';
function sv(tag,attrs){var e=document.createElementNS(SVGNS,tag);for(var k in attrs)e.setAttribute(k,attrs[k]);return e;}
function store(k,v){try{if(v===undefined)return localStorage.getItem('plcp_'+k);localStorage.setItem('plcp_'+k,v);}catch(e){return null;}}

var TYPES=[['wert','Zahlenwert'],['zeiger','Zeigerinstrument'],['balken','Balken'],['status','Zustand (Lampe)'],
 ['trend','Kurzverlauf'],['text','Text / Überschrift']];
var vars=[], byName={}, layout=null, canEdit=false, page=parseInt(store('page')||'0',10)||0;
var editing=false, backup=null, sel=-1, tiles=[], timer=null, busy=false, lastData=null, refreshMs=1000;

function fetchJson(u,opt){return fetch(api(u),Object.assign({cache:'no-store'},opt||{})).then(function(r){
 if(r.status===401){if(r.headers.get('X-Login')){location.href='login';throw new Error('Anmeldung erforderlich');}
  throw new Error('Zugriff verweigert – Zugriffscode in der Adresse fehlt (?token=…)');}
 return r.json().then(function(j){if(!r.ok)throw new Error(j.error||('Serverfehler '+r.status));return j;});});}
function msg(t){var g=$('grid');g.innerHTML='';g.appendChild(el('div','msg',t));}

/* ---------- Werte, Grenzen, Format ---------- */
function vinfo(t){return t.var!==undefined?byName[t.var]:undefined;}
function num(x){return typeof x==='number'&&isFinite(x);}
function fmt(v,t,info){
 if(v===null||v===undefined)return '—';
 var nk=t.nk;if(nk===undefined||nk<0){
  if(info&&info.dtype!=='REAL'&&info.dtype!=='LREAL'&&!info.calc)return String(Math.round(v));
  var a=Math.abs(v);nk=a>=1000?0:a>=100?1:a>=10?2:3;}
 return v.toFixed(nk).replace('.',',');}
function fmtR(v,t){return Number.isInteger(v)&&(t.nk===undefined||t.nk<0)?String(v):fmt(v,t);}
function level(v,t){
 if(!num(v))return '';
 if((num(t.og_alarm)&&v>=t.og_alarm)||(num(t.ug_alarm)&&v<=t.ug_alarm))return 'alarm';
 if((num(t.og_warn)&&v>=t.og_warn)||(num(t.ug_warn)&&v<=t.ug_warn))return 'warn';
 return '';}
function range(t){var lo=num(t.min)?t.min:0,hi=num(t.max)?t.max:100;if(hi<=lo)hi=lo+1;return [lo,hi];}
function frac(v,t){var r=range(t);return Math.max(0,Math.min(1,(v-r[0])/(r[1]-r[0])));}
function isOn(v,t){var on=num(v)&&v!==0;return t.invert?!on:on;}

/* ---------- Kacheln aufbauen ---------- */
function curTiles(){return layout.seiten[page].kacheln;}
function title(t){return t.titel||(t.typ==='text'?'':(t.var||'?'));}
function place(node,t){
 var small=matchMedia('(max-width:700px)').matches;
 if(small){node.style.gridColumn='span '+(t.w>=3?4:2);node.style.gridRow='span '+t.h;}
 else{node.style.gridColumn=(t.x+1)+' / span '+t.w;node.style.gridRow=(t.y+1)+' / span '+t.h;}}
function build(){
 var g=$('grid');g.innerHTML='';tiles=[];
 var list=curTiles().map(function(t,i){return [t,i];});
 if(matchMedia('(max-width:700px)').matches)list.sort(function(a,b){return a[0].y-b[0].y||a[0].x-b[0].x;});
 if(!list.length)g.appendChild(el('div','msg',editing?'Leere Seite – „+ Kachel“ fügt eine hinzu.':'Keine Kacheln auf dieser Seite.'));
 list.forEach(function(p){var t=p[0],i=p[1];
  var n=el('div','tile');n.dataset.i=i;
  var hd=el('div','t',title(t));var body=el('div','body');
  if(t.typ!=='text'||t.titel)n.appendChild(hd);
  n.appendChild(body);
  var o={t:t,n:n,body:body,i:i};
  if(t.typ==='text'){n.removeChild(hd);var x=el('div','txt',t.titel||'Text');body.appendChild(x);o.txt=x;
   body.style.justifyContent='flex-start';if(t.farbe)x.style.color=t.farbe;}
  else if(t.typ==='wert'){var v=el('div','val');o.val=v;body.appendChild(v);}
  else if(t.typ==='status'){body.style.justifyContent='flex-start';o.lamp=el('div','lamp');o.stxt=el('div','stxt');
   body.appendChild(o.lamp);body.appendChild(o.stxt);}
  else if(t.typ==='balken'){var vert=t.h>t.w;o.val=el('div','val');body.appendChild(o.val);
   o.bar=el('div','bar'+(vert?' v':''));o.fill=el('i');o.bar.appendChild(o.fill);body.appendChild(o.bar);
   if(vert){body.style.justifyContent='space-around';o.bar.style.position='relative';o.bar.style.height='100%';}
   else{body.style.alignItems='flex-start';o.val.style.marginTop='4px';}
   var r=range(t);var mm=el('div','mm');mm.appendChild(el('span','',fmtR(r[0],t)));mm.appendChild(el('span','',fmtR(r[1],t)));
   if(!vert)body.appendChild(mm);}
  else if(t.typ==='zeiger'){gauge(o);}
  else if(t.typ==='trend'){o.val=el('div','val');o.val.style.cssText='position:absolute;right:4px;top:0;font-size:18px';
   o.svg=sv('svg',{preserveAspectRatio:'none',viewBox:'0 0 100 40'});o.svg.style.cssText='position:absolute;left:0;right:0;bottom:0;top:24px;width:100%;height:calc(100% - 24px)';body.appendChild(o.svg);body.appendChild(o.val);
   o.path=sv('path',{fill:'none',stroke:t.farbe||(vinfo(t)||{}).color||'#4aa3ff','stroke-width':'1.6','vector-effect':'non-scaling-stroke'});
   o.svg.appendChild(o.path);}
  if(editing){var rs=el('div','rs');n.appendChild(rs);dragHandlers(n,rs,i);if(i===sel)n.classList.add('sel');}
  place(n,t);g.appendChild(n);tiles.push(o);
 });
 var tabs=$('tabs');tabs.innerHTML='';
 layout.seiten.forEach(function(p,pi){var b=el('button',pi===page?'on':'',p.name);
  b.onclick=function(){page=pi;store('page',pi);sel=-1;build();props();render();};tabs.appendChild(b);});
 tabs.style.display=(layout.seiten.length>1||editing)?'flex':'none';
 if(editing)$('pname').value=layout.seiten[page].name;
 fitText();render();
}
/* Zeigerinstrument: 240°-Bogen mit Grenzbereichen */
function arc(cx,cy,r,a0,a1){var p0=[cx+r*Math.cos(a0),cy+r*Math.sin(a0)],p1=[cx+r*Math.cos(a1),cy+r*Math.sin(a1)];
 return 'M'+p0[0].toFixed(2)+' '+p0[1].toFixed(2)+' A'+r+' '+r+' 0 '+((a1-a0)>Math.PI?1:0)+' 1 '+p1[0].toFixed(2)+' '+p1[1].toFixed(2);}
var A0=Math.PI*5/6, A1=Math.PI*13/6;
function ang(f){return A0+(A1-A0)*f;}
function gauge(o){var t=o.t;
 var s=sv('svg',{viewBox:'0 0 100 84'});o.body.appendChild(s);
 s.appendChild(sv('path',{d:arc(50,50,38,A0,A1),fill:'none',stroke:'var(--line)','stroke-width':'9','stroke-linecap':'round'}));
 function band(a,b,col){if(!num(a)&&!num(b))return;var r=range(t);var fa=frac(num(a)?a:r[0],t),fb=frac(num(b)?b:r[1],t);
  if(fb>fa)s.appendChild(sv('path',{d:arc(50,50,38,ang(fa),ang(fb)),fill:'none',stroke:col,'stroke-width':'9','stroke-opacity':'.55'}));}
 var r=range(t);
 if(num(t.og_warn))band(t.og_warn,num(t.og_alarm)?t.og_alarm:r[1],'var(--warn)');
 if(num(t.og_alarm))band(t.og_alarm,r[1],'var(--err)');
 if(num(t.ug_warn))band(num(t.ug_alarm)?t.ug_alarm:r[0],t.ug_warn,'var(--warn)');
 if(num(t.ug_alarm))band(r[0],t.ug_alarm,'var(--err)');
 o.arc=sv('path',{d:'',fill:'none',stroke:'var(--accent)','stroke-width':'9','stroke-linecap':'round'});s.appendChild(o.arc);
 o.needle=sv('line',{x1:50,y1:50,x2:50,y2:18,stroke:'var(--fg)','stroke-width':'2.2','stroke-linecap':'round'});
 s.appendChild(o.needle);s.appendChild(sv('circle',{cx:50,cy:50,r:3.5,fill:'var(--fg)'}));
 o.gtxt=sv('text',{x:50,y:73,'text-anchor':'middle','font-size':'12','font-weight':'650',fill:'var(--fg)'});s.appendChild(o.gtxt);
 var l=sv('text',{x:16,y:82,'text-anchor':'middle','font-size':'6.5',fill:'var(--mute)'});l.textContent=fmtR(r[0],t);s.appendChild(l);
 var h=sv('text',{x:84,y:82,'text-anchor':'middle','font-size':'6.5',fill:'var(--mute)'});h.textContent=fmtR(r[1],t);s.appendChild(h);
}
function fitText(){tiles.forEach(function(o){
 if(o.val&&o.t.typ==='wert'){var h=o.body.clientHeight,w=o.body.clientWidth;o.val.style.fontSize=Math.max(14,Math.min(h*0.7,w/5.2))+'px';}
 if(o.val&&o.t.typ==='balken'){var vb=o.bar.classList.contains('v');
  o.val.style.fontSize=Math.max(13,Math.min(o.body.clientHeight*(vb?0.3:0.34),o.body.clientWidth/(vb?8:6)))+'px';}
 if(o.txt){o.txt.style.fontSize=Math.max(13,Math.min(o.body.clientHeight*0.5,28))+'px';}});}

/* ---------- Werte eintragen ---------- */
function render(){
 var d=lastData;if(!d||!layout)return;
 tiles.forEach(function(o){var t=o.t,info=vinfo(t);if(t.typ==='text')return;
  var v=info&&d.values?d.values[info.i]:null;if(v===undefined)v=null;
  var u=t.einheit||'';
  o.n.classList.toggle('stale',v===null);
  if(!info){o.n.className='tile'+(o.n.classList.contains('sel')?' sel':'');if(o.val)o.val.textContent='?';
   if(o.stxt)o.stxt.textContent='Variable fehlt';return;}
  var lv=t.typ==='status'?'':level(v,t);
  o.n.classList.toggle('warn',lv==='warn');o.n.classList.toggle('alarm',lv==='alarm');
  if(t.typ==='wert'||t.typ==='balken'||t.typ==='trend'){o.val.textContent=fmt(v,t,info);
   if(u){var s=el('span','unit',u);o.val.appendChild(s);}}
  if(t.typ==='balken'){var f=num(v)?frac(v,t):0;
   if(o.bar.classList.contains('v')){o.fill.style.height=(f*100)+'%';o.fill.style.width='100%';}else o.fill.style.width=(f*100)+'%';
   o.fill.style.background=lv==='alarm'?'var(--err)':lv==='warn'?'var(--warn)':(t.farbe||'var(--accent)');}
  if(t.typ==='status'){var on=isOn(v,t);
   o.lamp.style.background=v===null?'var(--off)':on?(t.farbe_ein||'#2ecc71'):(t.farbe_aus||'var(--off)');
   o.lamp.style.boxShadow=on&&v!==null?'0 0 12px '+(t.farbe_ein||'#2ecc71'):'none';
   o.stxt.textContent=v===null?'—':on?(t.text_ein||'EIN'):(t.text_aus||'AUS');}
  if(t.typ==='zeiger'){var f2=num(v)?frac(v,t):0;var a=ang(f2);
   o.needle.setAttribute('x2',(50+32*Math.cos(a)).toFixed(2));o.needle.setAttribute('y2',(50+32*Math.sin(a)).toFixed(2));
   o.arc.setAttribute('d',f2>0.002?arc(50,50,38,A0,a):'');
   o.arc.setAttribute('stroke',lv==='alarm'?'var(--err)':lv==='warn'?'var(--warn)':(t.farbe||'var(--accent)'));
   o.gtxt.textContent=fmt(v,t,info)+(u?' '+u:'');}
  if(t.typ==='trend'){var s2=d.series&&d.series[info.i];var pts='';
   if(s2&&s2.x.length){var win=t.fenster_s||300,x0=d.t1-d.t0-win,lo=Infinity,hi=-Infinity,k;
    for(k=0;k<s2.y.length;k++){if(s2.x[k]>=x0&&s2.y[k]!==null){lo=Math.min(lo,s2.y[k]);hi=Math.max(hi,s2.y[k]);}}
    if(num(t.min))lo=t.min;if(num(t.max))hi=t.max;if(hi<=lo){hi=lo+1;lo-=0;}
    var started=false;
    for(k=0;k<s2.x.length;k++){if(s2.x[k]<x0)continue;var yv=s2.y[k];if(yv===null){started=false;continue;}
     var px=(s2.x[k]-x0)/win*100,py=38-(Math.max(lo,Math.min(hi,yv))-lo)/(hi-lo)*36;
     pts+=(started?'L':'M')+px.toFixed(2)+' '+py.toFixed(2);started=true;}}
   o.path.setAttribute('d',pts);}
 });
 $('info').textContent=d.empty?'noch keine Daten':((d.running?'Live ':'gestoppt · ')+new Date(d.last*1000).toLocaleTimeString());
 var L=$('leds');L.innerHTML='';(d.plcs||[]).forEach(function(p){var s=el('span','',p.name);var led=el('span','led '+p.state);
  led.title=p.text;s.insertBefore(led,s.firstChild);L.appendChild(s);});
}
function trendSet(){var w=0,ids={};
 if(layout)curTiles().forEach(function(t){var i=vinfo(t);if(t.typ==='trend'&&i){w=Math.max(w,t.fenster_s||300);ids[i.i]=1;}});
 return {w:w,ids:Object.keys(ids)};}
function tick(){
 if(busy||document.hidden)return;busy=true;
 var ts=trendSet();
 var u='/api/data?window='+(ts.w||1)+'&max='+(ts.w?300:50)+'&only='+(ts.ids.join(',')||'-');
 fetchJson(u).then(function(d){busy=false;
  if(d.version===null){lastData=null;msg('Keine Aufzeichnung aktiv');return;}
  lastData=d;render();}).catch(function(e){busy=false;$('info').textContent=e.message;});
}

/* ---------- Bearbeiten ---------- */
function gridMetrics(){var g=$('grid'),cs=getComputedStyle(g);var gap=parseFloat(cs.columnGap)||8;
 var w=g.clientWidth-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight);
 return {cw:(w+gap)/12,rh:(parseFloat(cs.gridAutoRows)||84)+(parseFloat(cs.rowGap)||8)};}
function dragHandlers(n,rs,i){
 function start(ev,mode){if(!editing)return;ev.preventDefault();ev.stopPropagation();
  select(i);var t=curTiles()[i],m=gridMetrics(),sx=ev.clientX,sy=ev.clientY,o={x:t.x,y:t.y,w:t.w,h:t.h};
  function mv(e){var dx=Math.round((e.clientX-sx)/m.cw),dy=Math.round((e.clientY-sy)/m.rh);
   if(mode==='move'){t.x=Math.max(0,Math.min(12-t.w,o.x+dx));t.y=Math.max(0,o.y+dy);}
   else{t.w=Math.max(1,Math.min(12-t.x,o.w+dx));t.h=Math.max(1,Math.min(12,o.h+dy));}
   place(n,t);}
  function up(){document.removeEventListener('pointermove',mv);document.removeEventListener('pointerup',up);
   if(t.x!==o.x||t.y!==o.y||t.w!==o.w||t.h!==o.h){build();props();}}
  document.addEventListener('pointermove',mv);document.addEventListener('pointerup',up);}
 n.addEventListener('pointerdown',function(e){if(e.target!==rs)start(e,'move');});
 rs.addEventListener('pointerdown',function(e){start(e,'size');});
}
function select(i){sel=i;tiles.forEach(function(o){o.n.classList.toggle('sel',o.i===i);});props();}
function field(box,label,key,kind,opts){
 var t=curTiles()[sel];var l=el('label','',label);box.appendChild(l);var inp;
 if(kind==='select'){inp=el('select');opts.forEach(function(o){var op=el('option','',o[1]);op.value=o[0];inp.appendChild(op);});
  inp.value=key==='invert'?(t.invert?'1':''):(t[key]===undefined?'':String(t[key]));}
 else{inp=el('input');inp.type=kind==='color'?'color':(kind==='num'?'number':'text');if(kind==='num')inp.step='any';
  inp.value=t[key]===undefined?(kind==='color'?'#4aa3ff':''):t[key];}
 inp.onchange=function(){var v=inp.value;
  if(kind==='num'){if(v===''||isNaN(parseFloat(v)))delete t[key];else t[key]=parseFloat(v);}
  else if(v==='')delete t[key];else t[key]=v;
  if(key==='typ')props();build();};
 box.appendChild(inp);return inp;}
function props(){var box=$('props');box.innerHTML='';if(!editing)return;
 var t=curTiles()[sel];if(!t){box.appendChild(el('div','hint','Kachel anklicken, um sie zu bearbeiten.'));return;}
 field(box,'Art','typ','select',TYPES);
 if(t.typ!=='text')field(box,'Variable','var','select',[['','—']].concat(vars.map(function(v){return [v.name,v.name];})));
 field(box,t.typ==='text'?'Text':'Titel (leer = Name der Variable)','titel','text');
 if(t.typ==='text'){field(box,'Farbe','farbe','color');return;}
 if(t.typ==='status'){field(box,'Text bei EIN','text_ein','text');field(box,'Text bei AUS','text_aus','text');
  field(box,'Farbe EIN','farbe_ein','color');field(box,'Farbe AUS','farbe_aus','color');
  field(box,'Umkehren (0 = EIN)','invert','select',[['','nein'],['1','ja']]);return;}
 field(box,'Einheit','einheit','text');
 field(box,'Nachkommastellen (leer = automatisch)','nk','num');
 if(t.typ!=='wert'){field(box,'Minimum','min','num');field(box,'Maximum','max','num');}
 if(t.typ==='trend')field(box,'Zeitraum (s)','fenster_s','num');
 field(box,'Obere Alarmgrenze','og_alarm','num');field(box,'Obere Warngrenze','og_warn','num');
 field(box,'Untere Warngrenze','ug_warn','num');field(box,'Untere Alarmgrenze','ug_alarm','num');
 if(t.typ!=='wert')field(box,'Farbe','farbe','color');
}
function setEdit(on){
 editing=on;document.body.classList.toggle('edit',on);$('edit').classList.toggle('on',on);$('perr').textContent='';
 if(on)backup=JSON.stringify(layout);sel=-1;build();props();}
function freeY(){var y=0;curTiles().forEach(function(t){y=Math.max(y,t.y+t.h);});return y;}
function wire(){
 $('edit').onclick=function(){if(editing){if(confirmLeave())setEdit(false);}else setEdit(true);};
 $('add').onclick=function(){var v=vars[0];curTiles().push({typ:'wert',var:v?v.name:undefined,x:0,y:freeY(),w:3,h:2});
  sel=curTiles().length-1;build();props();};
 $('dup').onclick=function(){var t=curTiles()[sel];if(!t)return;var c=JSON.parse(JSON.stringify(t));c.y=freeY();
  curTiles().push(c);sel=curTiles().length-1;build();props();};
 $('del').onclick=function(){if(sel<0)return;curTiles().splice(sel,1);sel=-1;build();props();};
 $('pname').onchange=function(){layout.seiten[page].name=$('pname').value||'Seite';build();};
 $('padd').onclick=function(){layout.seiten.push({name:'Seite '+(layout.seiten.length+1),kacheln:[]});page=layout.seiten.length-1;sel=-1;build();props();};
 $('pdel').onclick=function(){if(layout.seiten.length<2)return;layout.seiten.splice(page,1);page=0;sel=-1;build();props();};
 $('auto').onclick=function(){fetchJson('/api/prozess?vorschlag=1').then(function(r){
  layout.seiten[page].kacheln=r.layout.seiten[0].kacheln;sel=-1;build();props();});};
 $('cancel').onclick=function(){layout=JSON.parse(backup);if(page>=layout.seiten.length)page=0;setEdit(false);};
 $('save').onclick=function(){$('perr').textContent='';
  fetchJson('/api/prozess',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(layout)})
   .then(function(r){layout=r.layout;setEdit(false);$('info').textContent='Gespeichert';})
   .catch(function(e){$('perr').textContent=e.message;});};
 document.addEventListener('keydown',function(e){if(!editing||sel<0||/INPUT|SELECT/.test(e.target.tagName))return;
  var t=curTiles()[sel];var d={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[e.key];
  if(e.key==='Delete'){$('del').onclick();return;}
  if(!d)return;e.preventDefault();
  if(e.shiftKey){t.w=Math.max(1,Math.min(12-t.x,t.w+d[0]));t.h=Math.max(1,Math.min(12,t.h+d[1]));}
  else{t.x=Math.max(0,Math.min(12-t.w,t.x+d[0]));t.y=Math.max(0,t.y+d[1]);}
  build();props();});
 window.addEventListener('beforeunload',function(e){if(editing&&backup!==JSON.stringify(layout)){e.preventDefault();e.returnValue='';}});
 var rt;window.addEventListener('resize',function(){clearTimeout(rt);rt=setTimeout(function(){if(layout)build();},150);});
 document.addEventListener('visibilitychange',function(){if(!document.hidden)tick();});
}
function confirmLeave(){return backup===JSON.stringify(layout)||confirm('Änderungen verwerfen?')&&(layout=JSON.parse(backup),true);}
function load(){
 fetchJson('/api/prozess').then(function(r){
  if(r.version===null){msg('Keine Aufzeichnung aktiv');setTimeout(load,3000);return;}
  vars=r.vars;byName={};vars.forEach(function(v){byName[v.name]=v;});
  layout=r.layout;canEdit=r.edit;refreshMs=r.refresh_ms||1000;
  if(page>=layout.seiten.length)page=0;
  $('proj').textContent='Prozessbild'+(r.project?' – '+r.project:'');document.title=$('proj').textContent;
  $('edit').style.display=canEdit&&!matchMedia('(max-width:700px)').matches?'':'none';
  build();tick();clearInterval(timer);timer=setInterval(tick,Math.max(refreshMs,200));
 }).catch(function(e){msg(e.message);});
}
wire();load();
})();
</script>
</body>
</html>
"""
