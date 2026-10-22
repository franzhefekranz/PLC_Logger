# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Benachrichtigungen bei Ereignissen der Trigger: E-Mail, Microsoft Teams / Slack / Webhook, ntfy (Push aufs Handy)
und Telegram.

Einstellung ``benachrichtigung`` der Konfiguration (JSON): aktiv, Mindestpriorität, nur bestimmte Trigger, auch beim
Gehen, Sperrzeit je Trigger (gegen Meldungsfluten) und die Kanäle. Gesendet wird in einem eigenen Thread; die Messung
wird nicht aufgehalten. Fehler meldet der Notifier über ``emit`` (Statuszeile bzw. Logdatei).
"""
import json
import queue
import smtplib
import socket
import ssl
import threading
import time
import urllib.request
from datetime import datetime
from email.message import EmailMessage

from plc_i18n import N_, tr

PRIO_ORDER = {"Info": 0, "Warnung": 1, "Alarm": 2}
CHANNELS = {"email": N_("E-Mail"), "webhook": N_("Teams / Slack / Webhook"), "ntfy": N_("ntfy (Push)"),
            "telegram": N_("Telegram")}
WEBHOOK_KINDS = {"teams": N_("Microsoft Teams (Workflows)"), "slack": N_("Slack"), "json": N_("Allgemein (JSON)")}
SMTP_MODES = {"starttls": "STARTTLS", "ssl": "SSL/TLS", "keine": N_("unverschlüsselt")}
TIMEOUT_S = 15

DEFAULTS = {"aktiv": False, "prio_min": "Warnung", "trigger": "", "gehen": False, "sperre_s": 300,
            "email": {"aktiv": False, "server": "", "port": 587, "modus": "starttls", "benutzer": "", "passwort": "",
                      "von": "", "an": ""},
            "webhook": {"aktiv": False, "art": "teams", "url": ""},
            "ntfy": {"aktiv": False, "url": "https://ntfy.sh/", "token": ""},
            "telegram": {"aktiv": False, "token": "", "chat": ""}}


def settings(raw) -> dict:
    """Einstellung ``benachrichtigung`` (dict oder JSON-Text) mit Vorgabewerten ergänzt."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except ValueError:
            raw = {}
    out = json.loads(json.dumps(DEFAULTS))
    for k, v in (raw or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        elif k in out:
            out[k] = v
    return out


def active_channels(s) -> list:
    return [k for k in CHANNELS if s.get(k, {}).get("aktiv")]


# ---- Nachricht ----------------------------------------------------------------------------------------------------
class Message:
    def __init__(self, kind, trigger, prio, text, ts, project=""):
        self.kind, self.trigger, self.prio, self.text, self.ts, self.project = kind, trigger, prio, text, ts, project
        self.host = socket.gethostname()

    @property
    def title(self):
        state = tr("gegangen") if self.kind == "GEHT" else ""
        head = f"[{tr(self.prio)}] {self.trigger}" + (f" ({state})" if state else "")
        return f"{head} – {self.project}" if self.project else head

    @property
    def body(self):
        when = datetime.fromtimestamp(self.ts).strftime("%d.%m.%Y %H:%M:%S")
        lines = [self.text or self.trigger, "", tr("Zeit: {0}").format(when), tr("Trigger: {0}").format(self.trigger),
                 tr("Priorität: {0}").format(tr(self.prio))]
        if self.kind == "GEHT":
            lines.append(tr("Das Ereignis ist gegangen (Bedingung nicht mehr erfüllt)."))
        if self.project:
            lines.append(tr("Projekt: {0}").format(self.project))
        lines.append(tr("Rechner: {0}").format(self.host))
        lines += ["", tr("– PLC Datenlogger")]
        return "\n".join(lines)


# ---- Kanäle -------------------------------------------------------------------------------------------------------
def _post(url, data: bytes, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT_S, context=ssl.create_default_context()) as r:
        return r.status


def send_email(c, msg: Message):
    if not c.get("server") or not c.get("an"):
        raise ValueError(tr("SMTP-Server und Empfänger angeben"))
    m = EmailMessage()
    m["Subject"] = msg.title
    m["From"] = c.get("von") or c.get("benutzer") or "plc-datenlogger@localhost"
    m["To"] = ", ".join(a.strip() for a in c["an"].replace(";", ",").split(",") if a.strip())
    m.set_content(msg.body)
    port = int(c.get("port") or (465 if c.get("modus") == "ssl" else 587))
    if c.get("modus") == "ssl":
        smtp = smtplib.SMTP_SSL(c["server"], port, timeout=TIMEOUT_S, context=ssl.create_default_context())
    else:
        smtp = smtplib.SMTP(c["server"], port, timeout=TIMEOUT_S)
    try:
        if c.get("modus") == "starttls":
            smtp.starttls(context=ssl.create_default_context())
        if c.get("benutzer"):
            smtp.login(c["benutzer"], c.get("passwort", ""))
        smtp.send_message(m)
    finally:
        try:
            smtp.quit()
        except Exception:
            pass


def webhook_payload(kind, msg: Message) -> dict:
    if kind == "teams":                     # Teams-Workflow „Bei Empfang einer Webhookanforderung posten“
        color = {"Alarm": "Attention", "Warnung": "Warning"}.get(msg.prio, "Default")
        return {"type": "message", "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [{"type": "TextBlock", "text": msg.title, "weight": "Bolder", "size": "Medium",
                                  "color": color, "wrap": True},
                                 {"type": "TextBlock", "text": msg.body.replace("\n", "\n\n"), "wrap": True}]}}]}
    if kind == "slack":
        return {"text": f"*{msg.title}*\n{msg.body}"}
    return {"titel": msg.title, "text": msg.text, "trigger": msg.trigger, "prioritaet": msg.prio, "art": msg.kind,
            "zeit": datetime.fromtimestamp(msg.ts).isoformat(timespec="seconds"), "projekt": msg.project,
            "rechner": msg.host}


def send_webhook(c, msg: Message):
    if not c.get("url"):
        raise ValueError(tr("Webhook-Adresse angeben"))
    _post(c["url"], json.dumps(webhook_payload(c.get("art", "teams"), msg)).encode("utf-8"),
          {"Content-Type": "application/json"})


def send_ntfy(c, msg: Message):
    url = (c.get("url") or "").strip()
    if not url or url.rstrip("/").endswith("ntfy.sh"):
        raise ValueError(tr("ntfy-Adresse mit Thema angeben, z. B. https://ntfy.sh/mein-thema"))
    headers = {"Title": msg.title.encode("utf-8").decode("latin-1", "replace"),
               "Priority": {"Alarm": "5", "Warnung": "4"}.get(msg.prio, "3"),
               "Tags": {"Alarm": "rotating_light", "Warnung": "warning"}.get(msg.prio, "information_source")}
    if msg.kind == "GEHT":
        headers.update(Priority="3", Tags="white_check_mark")
    if c.get("token"):
        headers["Authorization"] = f"Bearer {c['token']}"
    _post(url, msg.body.encode("utf-8"), headers)


def send_telegram(c, msg: Message):
    if not c.get("token") or not c.get("chat"):
        raise ValueError(tr("Bot-Token und Chat-ID angeben"))
    _post(f"https://api.telegram.org/bot{c['token']}/sendMessage",
          json.dumps({"chat_id": c["chat"], "text": f"{msg.title}\n\n{msg.body}"}).encode("utf-8"),
          {"Content-Type": "application/json"})


SENDERS = {"email": send_email, "webhook": send_webhook, "ntfy": send_ntfy, "telegram": send_telegram}


def send_all(s, msg: Message, channels=None):
    """Nachricht über alle (bzw. die genannten) eingeschalteten Kanäle senden -> [(Kanal, Fehlertext oder "")]."""
    out = []
    for ch in channels or active_channels(s):
        try:
            SENDERS[ch](s.get(ch, {}), msg)
            out.append((ch, ""))
        except Exception as e:                     # Netzwerk, Anmeldung, Adresse …
            out.append((ch, str(e) or type(e).__name__))
    return out


def test_message(project=""):
    return Message("KOMMT", tr("Testnachricht"), "Info",
                   tr("Testnachricht des PLC Datenloggers – die Benachrichtigung funktioniert."), time.time(), project)


# ---- Notifier (für Recorder / Headless) -------------------------------------------------------------------------
class Notifier:
    """Nimmt Ereignisse der Trigger entgegen, filtert (Priorität, Trigger, Sperrzeit) und sendet im Hintergrund."""

    def __init__(self, conn, project="", emit=None, sender=None):
        self.s = settings(conn.get("benachrichtigung", "")) if isinstance(conn, dict) else settings(conn)
        self.project = project
        self.emit = emit or (lambda _t: None)
        self.sender = sender or send_all
        self.q = queue.Queue()
        self.last = {}                             # Trigger -> Zeitpunkt der letzten Meldung
        self.suppressed = {}                       # Trigger -> Anzahl in der Sperrzeit unterdrückter Meldungen
        self.sent_open = set()                     # Trigger, deren Kommen gemeldet wurde (für die Gehen-Meldung)
        names = [n.strip() for n in str(self.s.get("trigger", "")).replace(";", ",").split(",") if n.strip()]
        self.only = set(names)
        self.thread = None
        if self:
            self.thread = threading.Thread(target=self._run, name="benachrichtigung", daemon=True)
            self.thread.start()

    def __bool__(self):
        return bool(self.s.get("aktiv")) and bool(active_channels(self.s))

    def event(self, kind, trigger, prio, text, ts):
        """kind: "KOMMT" oder "GEHT"."""
        if not self:
            return False
        if PRIO_ORDER.get(prio, 0) < PRIO_ORDER.get(self.s.get("prio_min", "Warnung"), 1):
            return False
        if self.only and trigger not in self.only:
            return False
        if kind == "GEHT":
            if not self.s.get("gehen") or trigger not in self.sent_open:
                return False                       # nur, wenn das Kommen gemeldet wurde
            self.sent_open.discard(trigger)
        if kind == "KOMMT":
            block = float(self.s.get("sperre_s") or 0)
            last = self.last.get(trigger)
            if last is not None and ts - last < block:
                self.suppressed[trigger] = self.suppressed.get(trigger, 0) + 1
                return False
            self.last[trigger] = ts
            self.sent_open.add(trigger)
            n = self.suppressed.pop(trigger, 0)
            if n:
                text = f"{text}\n" + tr("({0} weitere Meldungen in der Sperrzeit unterdrückt)").format(n)
        self.q.put(Message(kind, trigger, prio, text, ts, self.project))
        return True

    def _run(self):
        while True:
            msg = self.q.get()
            if msg is None:
                return
            for ch, err in self.sender(self.s, msg):
                if err:
                    self.emit(tr("Benachrichtigung über {0} fehlgeschlagen: {1}").format(tr(CHANNELS[ch]), err))

    def stop(self, wait_s=5.0):
        """Ausstehende Meldungen noch senden (höchstens wait_s Sekunden), dann beenden."""
        if self.thread is not None:
            self.q.put(None)
            self.thread.join(wait_s)
            self.thread = None
