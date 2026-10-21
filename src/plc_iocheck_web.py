# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""IO-Check auf Smartphone/Tablet: Seite /io des Webservers (HTML, CSS und JavaScript in einer Datei).

Die Seite liest /api/io (Signale, Werte, Status, letzte Wechsel) und sendet Prüfstatus, Bemerkungen und
Analog-Prüfpunkte an /api/io/cmd. Prüfer ist der Anmeldename im Webserver. Mehrere Geräte können gleichzeitig prüfen;
das IO-Check-Fenster am PC übernimmt die Änderungen und speichert sie.
"""

IO_HTML = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>IO-Check – PLC Datenlogger</title>
<style>
:root{--bg:#10151b;--card:#18202a;--fg:#dfe6ee;--mute:#8b98a7;--line:#2a3544;--accent:#4aa3ff;--in:#2ecc71;--out:#f5a623;
 --off:#5d6875;--nan:#e5484d;--okbg:#1d3b24;--errbg:#47201f;--skbg:#2a2f36;--fl:#fbc02d;color-scheme:dark}
@media (prefers-color-scheme:light){:root{--bg:#f2f4f7;--card:#fff;--fg:#1b2430;--mute:#5b6878;--line:#d5dbe3;
 --accent:#0a6fd6;--off:#b7c0ca;--okbg:#c8e6c9;--errbg:#ffcdd2;--skbg:#e0e0e0;color-scheme:light}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.35 system-ui,"Segoe UI",Roboto,Arial,sans-serif;
 padding-bottom:calc(var(--sheet,0px) + env(safe-area-inset-bottom))}
header{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line);padding:8px 10px 0}
.row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
h1{font-size:17px;margin:0;font-weight:600}
.sub{color:var(--mute);font-size:13px;flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.lnk{color:var(--mute);text-decoration:none;font-size:13px;border:1px solid var(--line);border-radius:6px;padding:3px 7px}
.bar{height:16px;border-radius:8px;background:var(--bg);border:1px solid var(--line);overflow:hidden;margin:7px 0 3px;
 position:relative}
.bar i{display:block;height:100%;background:var(--in);width:0}
.bar span{position:absolute;inset:0;font-size:11px;line-height:14px;text-align:center;color:var(--fg)}
.plcs{font-size:12px;color:var(--mute);display:flex;gap:10px;flex-wrap:wrap}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--off);margin-right:4px}
.dot.ok{background:var(--in)}.dot.fehler{background:var(--nan)}.dot.verbinde{background:var(--fl)}
nav{display:flex;gap:4px;margin-top:6px}
nav button{flex:1;background:none;border:0;border-bottom:3px solid transparent;color:var(--mute);padding:8px 4px;
 font:inherit;font-weight:600}
nav button.on{color:var(--accent);border-color:var(--accent)}
#swap{display:none;position:sticky;top:var(--hh,120px);z-index:4;background:#c62828;color:#fff;font-weight:700;
 padding:10px 12px}
main{padding:8px}
.filt{display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap}
.filt input,.filt select{flex:1;min-width:110px;background:var(--card);color:var(--fg);border:1px solid var(--line);
 border-radius:6px;padding:8px;font:inherit}
.r{display:flex;align-items:center;gap:10px;background:var(--card);border:1px solid var(--line);border-radius:8px;
 padding:8px 10px;margin-bottom:5px;cursor:pointer}
.r.st-ok{background:var(--okbg)}.r.st-fehler{background:var(--errbg)}.r.st-uebersprungen{background:var(--skbg)}
.r.sel{outline:2px solid var(--accent)}
.r.fl .v{background:var(--fl);color:#000;border-radius:4px}
.led{flex:none;width:18px;height:18px;border-radius:50%;background:var(--off);box-shadow:0 0 0 1px rgba(0,0,0,.3) inset}
.led.in{background:var(--in);box-shadow:0 0 8px var(--in)}.led.out{background:var(--out);box-shadow:0 0 8px var(--out)}
.led.nan{background:transparent;border:2px solid var(--nan)}.led.an{border-radius:4px;background:var(--accent);opacity:.6}
.t{flex:1;min-width:0}.t b{font-weight:600}
.c{color:var(--mute);font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.v{flex:none;font-variant-numeric:tabular-nums;padding:0 4px;min-width:2ch;text-align:right}
.st{flex:none;width:22px;text-align:center;font-weight:700;font-size:17px}
.st.ok{color:#2e9d4b}.st.fehler{color:#e5484d}.st.uebersprungen{color:var(--mute)}
.sec{font-weight:700;margin:12px 0 4px}
.grid{display:grid;grid-template-columns:58px repeat(8,minmax(0,46px));gap:4px;align-items:center}
.grid .lb{font-size:12.5px;color:var(--mute);text-align:right;padding-right:4px}
.grid .hd{font-size:11px;color:var(--mute);text-align:center}
.cell{aspect-ratio:1;border:1px solid var(--line);border-radius:6px;background:var(--card);position:relative;
 display:flex;align-items:center;justify-content:center;cursor:pointer}
.cell .led{width:58%;height:58%}
.cell.st-ok{background:var(--okbg)}.cell.st-fehler{background:var(--errbg)}.cell.st-uebersprungen{background:var(--skbg)}
.cell b{position:absolute;right:2px;bottom:0;font-size:11px}
.cell.seen::after{content:"";position:absolute;right:3px;top:3px;width:6px;height:6px;border-radius:50%;background:#1e88e5}
.cell.fl{box-shadow:0 0 0 3px var(--fl) inset}.cell.sel{outline:2px solid var(--accent);outline-offset:1px}
.big{font-size:24px;font-weight:700;margin:6px 0 2px}
.ch{display:flex;gap:10px;padding:7px 4px;border-bottom:1px solid var(--line);cursor:pointer}
.ch .tm{color:var(--mute);font-variant-numeric:tabular-nums;flex:none;width:52px}
.ch .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ch.swap{background:var(--errbg)}
.msg{padding:40px 16px;text-align:center;color:var(--mute)}
#sheet{display:none;position:fixed;left:0;right:0;bottom:0;z-index:6;background:var(--card);border-top:2px solid var(--accent);
 padding:10px 12px calc(10px + env(safe-area-inset-bottom));max-height:70vh;overflow:auto;box-shadow:0 -6px 20px rgba(0,0,0,.35)}
#sheet .x{float:right;background:none;border:0;color:var(--mute);font-size:22px;line-height:1;padding:0 4px}
.sv{font-size:28px;font-weight:700;margin:4px 0}
.btns{display:grid;grid-template-columns:1fr 1fr 1.5fr 1fr;gap:6px;margin:8px 0}
.btns button{font-size:13.5px!important;padding:10px 2px!important;white-space:nowrap}
.btns button,.pt button,.rm button{font:inherit;font-weight:600;border-radius:8px;border:1px solid var(--line);
 background:var(--bg);color:var(--fg);padding:12px 4px;min-height:46px}
.btns .ok{background:#2e7d32;color:#fff;border-color:#2e7d32}.btns .fehler{background:#c62828;color:#fff;border-color:#c62828}
.rm{display:flex;gap:6px}.rm input{flex:1;min-width:0;background:var(--bg);color:var(--fg);border:1px solid var(--line);
 border-radius:8px;padding:10px;font:inherit}
.pt{display:grid;grid-template-columns:44px 1.3fr 1fr 22px auto;gap:6px;align-items:center;margin-top:6px;font-size:14px}
.pt button{padding:8px 4px;min-height:38px}
.fault{color:var(--nan);font-weight:700}
.wb{margin:8px 0 2px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;line-height:1.7}
.okm{color:#2e9d4b;font-weight:700}
.muted{color:var(--mute);font-size:12.5px}
</style>
</head>
<body>
<header id="hdr">
 <div class="row"><h1>IO-Check</h1><span class="sub" id="title"></span>
  <a class="lnk" id="pdf" href="api/io/protokoll.pdf" target="_blank" title="Abnahmeprotokoll als PDF">PDF</a>__LOGOUT__</div>
 <div class="bar"><i id="barv"></i><span id="bart"></span></div>
 <div class="plcs" id="plcs"></div>
 <nav><button data-t="list" class="on">Liste</button><button data-t="matrix">Matrix</button>
  <button data-t="moved">Bewegt</button></nav>
</header>
<div id="swap"></div>
<main>
 <section id="list">
  <div class="filt"><input id="q" type="search" placeholder="Suchen …" autocomplete="off">
   <select id="fg"></select><select id="fs"><option value="">Alle Status</option><option value="offen">offen</option>
   <option value="ok">OK</option><option value="fehler">Fehler</option><option value="uebersprungen">übersprungen</option></select></div>
  <div id="rows"><div class="msg">Verbinde …</div></div>
 </section>
 <section id="matrix" hidden><div id="mx"></div></section>
 <section id="moved" hidden><div class="muted">Zuletzt gewechselt</div><div class="big" id="last">–</div>
  <div class="muted" id="lastc"></div><div id="chs" style="margin-top:10px"></div></section>
</main>
<div id="sheet"><button class="x" onclick="pick(-1)" aria-label="Schließen">×</button><div id="sh"></div></div>
<script>
var TOKEN=new URLSearchParams(location.search).get('token')||'';
function api(u){return TOKEN?u+(u.indexOf('?')<0?'?':'&')+'token='+encodeURIComponent(TOKEN):u;}
document.getElementById('pdf').href=api('api/io/protokoll.pdf');
var SWAPS={},S=null,VER=-1,D=[],SEL=-1,TAB='list',lastSeq=-1,TOL=1,rowEl=[],cellEl=[],swapUntil=0,remarkDirty=false;
var ST={offen:'offen',ok:'OK',fehler:'Fehler',uebersprungen:'übersprungen'},MK={offen:'',ok:'✓',fehler:'✗',uebersprungen:'–'};
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function bin(i){var k=S.sig[i][5];return k=='DI'||k=='DO';}
function isIn(i){var k=S.sig[i][5];return k=='DI'||k=='AI';}
function lbl(i){return S.sig[i][1]||S.sig[i][0];}
function scale(i,raw){var s=S.sig[i],sp=s[10]-s[9];if(raw==null||!sp)return null;return s[7]+(raw-s[9])*(s[8]-s[7])/sp;}
function fmt(x){if(x==null)return '–';var a=Math.abs(x);return a>=1000?x.toFixed(0):a>=100?x.toFixed(1):a>=10?x.toFixed(2):x.toFixed(3);}
function vtext(i){var d=D[i];if(d[1]==null)return d[2]?'⚠':'–';if(bin(i))return d[1]?'1':'0';
 var u=S.sig[i][6];return fmt(scale(i,d[1]))+(u?' '+u:'');}
function ledcls(i){var d=D[i];if(bin(i)){if(d[1]==null)return d[2]?'led nan':'led';return d[1]?(isIn(i)?'led in':'led out'):'led';}
 return d[1]==null&&d[2]?'led nan':'led an';}
function target(i,p){var s=S.sig[i];return s[7]+(s[8]-s[7])*p/100;}
function inTol(i,p,v){var s=S.sig[i];return v!=null&&Math.abs(v-target(i,p))<=Math.abs(s[8]-s[7]||1)*TOL/100;}
function fault(i,raw){var s=S.sig[i];if(raw==null)return '';if(s[10]==27648&&(s[9]==0||s[9]==-27648)){
 if(raw>=32767)return 'Überlauf bzw. Drahtbruch (32767)';if(raw<=-32768)return 'Unterlauf bzw. Drahtbruch (-32768)';
 if(raw>32511)return 'Überlauf';if(raw>27648)return 'Übersteuerungsbereich (> 100 %)';
 if(s[9]==0&&raw<-4864)return 'Unterlauf (Drahtbruch bei 4 … 20 mA?)';if(s[9]==0&&raw<0)return 'Untersteuerungsbereich (< 0 %)';return '';}
 var sp=s[10]-s[9];return sp&&(raw>s[10]+.176*sp||raw<s[9]-.176*sp)?'Außerhalb des Messbereichs':'';}

function build(){
 var h='';S.sig.forEach(function(s,i){h+='<div class="r" id="r'+i+'" onclick="pick('+i+')"><span class="led"></span><div class="t"><b>'+esc(s[0])+
  '</b> '+esc(s[1])+'<div class="c">'+esc(s[2])+(s[3]?' · '+esc(s[3]):'')+'</div></div><div class="v"></div><div class="st"></div></div>';});
 document.getElementById('rows').innerHTML=h||'<div class="msg">Keine Signale – im Programm eine IO-Liste importieren.</div>';
 rowEl=S.sig.map(function(_s,i){var e=document.getElementById('r'+i);return {e:e,led:e.children[0],v:e.children[2],st:e.children[3],k:''};});
 var fg=document.getElementById('fg'),cur=fg.value;fg.innerHTML='<option value="">Alle Gruppen</option>'+S.groups.map(function(g){return '<option>'+esc(g)+'</option>';}).join('');
 fg.value=cur;
 var m='',last=null;S.matrix.forEach(function(r){if(r[0]!==last){if(last!==null)m+='</div>';last=r[0];
   m+='<div class="sec">'+esc(r[0])+'</div><div class="grid"><span></span>';for(var b=0;b<r[2].length;b++)m+='<span class="hd">'+b+'</span>';}
  m+='<span class="lb">'+esc(r[1])+'</span>';r[2].forEach(function(i){m+=i<0?'<span></span>':'<div class="cell" id="m'+i+'" onclick="pick('+i+')"><span class="led"></span><b></b></div>';});});
 if(last!==null)m+='</div>';
 document.getElementById('mx').innerHTML=m||'<div class="msg">Keine Binärsignale.</div>';
 cellEl=[];S.sig.forEach(function(_s,i){var e=document.getElementById('m'+i);if(e)cellEl[i]={e:e,led:e.children[0],b:e.children[1],k:''};});
 filter();}

function filter(){if(!S)return;var q=document.getElementById('q').value.toLowerCase().split(/\s+/).filter(Boolean),
 g=document.getElementById('fg').value,st=document.getElementById('fs').value;
 S.sig.forEach(function(s,i){var ok=(!g||s[4]==g)&&(!st||(D[i]&&D[i][0]==st));if(ok&&q.length){var hay=(s[0]+' '+s[1]+' '+s[2]+' '+s[3]).toLowerCase();
  ok=q.every(function(w){return hay.indexOf(w)>=0;});}rowEl[i].e.style.display=ok?'':'none';});}

function update(){
 var now=Date.now();S.sig.forEach(function(_s,i){var d=D[i];if(!d)return;var fl=d[3]>=0&&d[3]<1.5,
  k=d[0]+'|'+d[1]+'|'+d[2]+'|'+fl+'|'+(SEL==i)+'|'+d[4];var r=rowEl[i];
  if(r.k!==k){r.k=k;r.e.className='r st-'+d[0]+(SEL==i?' sel':'')+(fl?' fl':'');r.led.className=ledcls(i);
   r.v.textContent=vtext(i);r.st.textContent=MK[d[0]];r.st.className='st '+d[0];}
  var c=cellEl[i];if(c){var kc=k;if(c.k!==kc){c.k=kc;c.e.className='cell st-'+d[0]+(d[0]=='offen'&&(d[4]&1)?' seen':'')+(fl?' fl':'')+(SEL==i?' sel':'');
   c.led.className=ledcls(i);c.b.textContent=MK[d[0]];}}});
 var st=document.getElementById('fs').value;if(st)filter();}

function moved(chs){
 var box=document.getElementById('chs'),h='';chs.forEach(function(c){var i=c[2];
  h+='<div class="ch'+(SWAPS[c[0]]?' swap':'')+'" onclick="pick('+i+')"><span class="tm">-'+c[1].toFixed(1)+' s</span><span class="nm"><b>'+esc(S.sig[i][0])+'</b> '+esc(S.sig[i][1])+
   '</span><span>'+chg(c)+'</span></div>';});box.innerHTML=h||'<div class="msg">Noch keine Wechsel.</div>';
 if(chs.length){var c=chs[0];document.getElementById('last').innerHTML=esc(lbl(c[2]))+': '+chg(c);
  document.getElementById('lastc').textContent=S.sig[c[2]][2];}}
function chg(c){var i=c[2];if(bin(i))return (c[3]?1:0)+' → '+(c[4]?1:0);var u=S.sig[i][6];return fmt(scale(i,c[3]))+' → '+fmt(scale(i,c[4]))+(u?' '+u:'');}

function swapCheck(chs){var fresh=chs.filter(function(c){return c[0]>lastSeq;});
 if(lastSeq<0){lastSeq=chs.length?chs[0][0]:0;return;}if(chs.length)lastSeq=Math.max(lastSeq,chs[0][0]);
 if(SEL<0||!bin(SEL))return;var selAge=D[SEL]?D[SEL][3]:-1;
 fresh.forEach(function(c){if(c[2]!=SEL&&S.sig[c[2]][5]=='DI'&&(selAge<0||selAge>3)){SWAPS[c[0]]=1;
  var b=document.getElementById('swap');b.textContent='⚠ Vertauschung? Erwartet '+lbl(SEL)+', gekommen '+lbl(c[2]);
  b.style.display='block';swapUntil=Date.now()+10000;if(navigator.vibrate)navigator.vibrate([200,100,200]);}});
 if(Date.now()>swapUntil)document.getElementById('swap').style.display='none';}

function sheet(){var sh=document.getElementById('sheet');if(SEL<0||!S||!S.sig[SEL]){sh.style.display='none';
  document.body.style.setProperty('--sheet','0px');return;}
 var s=S.sig[SEL],d=D[SEL]||[],h='<div><b>'+esc(s[0])+'</b> '+esc(s[1])+' <span class="muted">'+esc(s[5])+(s[3]?' · '+esc(s[3]):'')+'</span></div>'+
  '<div class="muted">'+esc(s[2])+'</div><div class="sv"><span class="'+ledcls(SEL)+'" style="display:inline-block;vertical-align:-2px"></span> '+esc(vtext(SEL))+'</div>';
 if(!bin(SEL)){var f=fault(SEL,d[1]);h+='<div class="muted">Rohwert '+(d[1]==null?'–':d[1])+(f?' · <span class="fault">'+esc(f)+'</span>':'')+'</div>';
  if(isIn(SEL)){var sn=d[4]||0;h+='<div class="wb"><b>Drahtbruchprüfung</b><div>'+(sn&4?'<span class="okm">✓</span>':'○')+' 1. Verdrahtung öffnen → Fehlerwert erkannt</div><div>'+
   (sn&8?'<span class="okm">✓</span>':'○')+' 2. Wieder schließen → Wert gültig</div></div><div class="muted" style="margin-top:8px"><b>Prüfpunkte</b> (optional, z. B. mit Kalibrator)</div>';}
  var eng=scale(SEL,d[1]),u=s[6]?' '+s[6]:'',pts=d[8]||{};
  [0,50,100].forEach(function(p){var got=pts[p];h+='<div class="pt"><b>'+p+' %</b><span>Soll '+fmt(target(SEL,p))+u+'</span><span>'+
   (got==null?(inTol(SEL,p,eng)?'<i class="muted">in Toleranz …</i>':''):fmt(got)+u)+'</span><span>'+(got==null?'':(inTol(SEL,p,got)?'✓':'✗'))+
   '</span><button onclick="cmd(\'point\',{pct:'+p+'})">Übernehmen</button></div>';});
  h+='<div class="muted" style="margin-top:6px">Wert 1 s lang in Toleranz (±'+TOL+' %) → Messpunkt wird automatisch übernommen.</div>';}
 h+='<div class="btns"><button class="ok" onclick="setst(\'ok\')">✓ OK</button><button class="fehler" onclick="setst(\'fehler\')">✗ Fehler</button>'+
  '<button onclick="setst(\'uebersprungen\')">– Übersprungen</button><button onclick="setst(\'offen\')">↺ Zurück</button></div>'+
  '<div class="muted">Status: <b>'+ST[d[0]||'offen']+'</b>'+(d[5]?' · '+esc(d[5])+' · '+esc(d[6]):'')+'</div>'+
  '<div class="rm" style="margin-top:6px"><input id="rmk" placeholder="Bemerkung" value="'+esc(d[7])+'" oninput="remarkDirty=true">'+
  '<button onclick="cmd(\'remark\',{remark:document.getElementById(\'rmk\').value});remarkDirty=false">Speichern</button></div>';
 var active=document.activeElement&&document.activeElement.id=='rmk';
 if(!active){document.getElementById('sh').innerHTML=h;}
 sh.style.display='block';document.body.style.setProperty('--sheet',sh.offsetHeight+'px');}

function pick(i){SEL=i;remarkDirty=false;if(i>=0&&rowEl[i]&&TAB=='list')rowEl[i].e.scrollIntoView({block:'nearest'});
 update();sheet();}
function setst(st){var extra={status:st};if(st=='fehler'){var r=prompt('Bemerkung (z. B. Verdrahtung, Sensor defekt):',(D[SEL]||[])[7]||'');
 if(r===null)return;extra.remark=r;}cmd('status',extra);}
function cmd(c,extra){if(SEL<0)return;var body={ver:VER,cmd:c,i:SEL};for(var k in extra)body[k]=extra[k];
 fetch(api('api/io/cmd'),{method:'POST',headers:{'Content-Type':'application/json','X-Token':TOKEN},body:JSON.stringify(body)})
 .then(function(r){if(r.status==409)VER=-1;if(r.status==401)location.href='login';});}

function poll(){fetch(api('api/io?ver='+VER+'&sel='+SEL),{cache:'no-store'}).then(function(r){if(r.status==401){location.href='login';throw 0;}return r.json();})
 .then(function(j){if(!j.active){document.getElementById('rows').innerHTML='<div class="msg">Kein IO-Check geöffnet – am PC <b>Analyse › IO-Check</b> öffnen.</div>';VER=-1;S=null;return;}
  if(j.static){S=j.static;VER=j.ver;D=j.dyn;build();}D=j.dyn;TOL=j.tol;
  document.getElementById('title').textContent=j.title+(j.user?' · '+j.user:'');
  var p=j.progress,done=p.ok+p.fehler+p.uebersprungen;document.getElementById('barv').style.width=(100*done/Math.max(1,p.gesamt))+'%';
  document.getElementById('bart').textContent=done+' / '+p.gesamt+' geprüft · '+p.ok+' OK · '+p.fehler+' Fehler';
  document.getElementById('plcs').innerHTML=j.plcs.map(function(x){return '<span title="'+esc(x[2])+'"><span class="dot '+esc(x[1])+'"></span>'+esc(x[0])+'</span>';}).join('');
  swapCheck(j.changes);update();if(TAB=='moved')moved(j.changes);else window._chs=j.changes;sheet();})
 .catch(function(){}).then(function(){setTimeout(poll,700);});}

document.querySelectorAll('nav button').forEach(function(b){b.onclick=function(){TAB=b.dataset.t;
 document.querySelectorAll('nav button').forEach(function(x){x.classList.toggle('on',x===b);});
 ['list','matrix','moved'].forEach(function(t){document.getElementById(t).hidden=t!==TAB;});
 if(TAB=='moved'&&window._chs&&S)moved(window._chs);};});
['q','fg','fs'].forEach(function(id){document.getElementById(id).addEventListener('input',filter);});
function hh(){document.documentElement.style.setProperty('--hh',document.getElementById('hdr').offsetHeight+'px');}
window.addEventListener('resize',hh);hh();
poll();
</script>
</body>
</html>
"""
