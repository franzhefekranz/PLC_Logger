# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Gemeinsame Grundlage für Treiber wortorientierter Steuerungen (SLMP/MELSEC, KV Host Link, TOYOPUC).

Variablen werden auf Wortbereiche abgebildet (Bereich, Wortnummer, Bit), je Bereich sortiert und – solange die Lücke
klein genug ist – zu möglichst wenigen Leseanfragen zusammengefasst. Werte über mehrere Wörter: niederwertiges Wort
zuerst (übliche Ablage bei MELSEC, KEYENCE und TOYOPUC), Wörter selbst als vorzeichenlose 16-Bit-Zahlen.

Ein Treiber leitet ``WordReader`` ab und implementiert ``parse()`` (Adresse -> Bereich, Wortnummer, Bit), ``open()``,
``close_transport()`` und ``read_words(Bereich, Start, Anzahl)``. Gerätefehler (z. B. Adresse außerhalb des Bereichs)
als ``DeviceError`` melden – sie betreffen nur die Variablen dieser Anfrage; Verbindungsfehler als ConnectionError/OSError.
Eine zu kurze Antwort (Rahmen in Ordnung, weniger Wörter als angefragt) ist ein Gerätefehler: ``short_answer()``.

Lehnt die Steuerung eine zusammengefasste Anfrage ab (Lücke oder geschützter Bereich dazwischen, zu kurze Antwort),
werden deren Variablen einzeln gelesen – im selben Zyklus und für den Rest der Sitzung.
"""
import struct

from plc_i18n import tr
from plc_treiber.base import NAN, Reader

# Datentyp -> (Anzahl Wörter, struct-Format für die Bytes in Little-Endian-Folge)
WORD_TYPES = {
    "BOOL": (1, None), "INT": (1, "<h"), "UINT": (1, "<H"), "WORD": (1, "<H"),
    "DINT": (2, "<i"), "UDINT": (2, "<I"), "DWORD": (2, "<I"), "REAL": (2, "<f"),
    "LINT": (4, "<q"), "ULINT": (4, "<Q"), "LWORD": (4, "<Q"), "LREAL": (4, "<d"),
}
TYPES = list(WORD_TYPES)


class DeviceError(Exception):
    """Fehlerantwort der Steuerung für eine Anfrage (Verbindung besteht weiter)."""


def short_answer(got_words, count):
    """DeviceError „Antwort zu kurz“ (die Steuerung lieferte ``got_words`` statt ``count`` Wörter)."""
    return DeviceError(tr("Antwort zu kurz ({0} statt {1} Wörter) – „Wörter je Anfrage“ verkleinern")
                       .format(got_words, count))


def decode(words, offset, dtype, bit=None):
    """Wert aus der Wortliste ab ``offset`` lesen (niederwertiges Wort zuerst)."""
    n, fmt = WORD_TYPES[dtype]
    if dtype == "BOOL":
        return float((words[offset] >> (bit or 0)) & 1)
    # Wörter in Bytes zurückverwandeln (je Wort Little Endian, niederwertiges Wort zuerst) und als Zieltyp lesen – so
    # werden DINT/REAL/LREAL über Wortgrenzen richtig zusammengesetzt
    raw = b"".join(int(w & 0xFFFF).to_bytes(2, "little") for w in words[offset:offset + n])
    return float(struct.unpack(fmt, raw)[0])


class _Item:
    """Eine zu lesende Variable: Position im Ergebnis, Bereich, Wortnummer, Bit, Typ, Anzahl Wörter, Adresse."""
    # __slots__: viele kleine Objekte ohne eigenes __dict__ (spart Speicher bei langen Variablenlisten)
    __slots__ = ("pos", "area", "word", "bit", "dtype", "words", "address")


class WordReader(Reader):
    """Planung, Zusammenfassen und Dekodieren; die Übertragung liefert die Unterklasse."""
    default_max_words = 480
    default_gap = 16

    def parse(self, address, dtype):
        """-> (Bereichsschlüssel, Wortnummer, Bit oder None). ValueError bei ungültiger Adresse."""
        raise NotImplementedError

    def claim(self, pos, variable):
        """True: diese Variable liest die Unterklasse selbst (z. B. Bitgeräte); ValueError = ungültig."""
        return False

    def area_limit(self, area):
        """Höchstzahl Wörter einer Anfrage in diesem Bereich."""
        return int(self.plc.params.get("max_woerter", self.default_max_words))

    def open(self):
        """Verbindung zur Steuerung öffnen (Unterklasse)."""
        raise NotImplementedError

    def close_transport(self):
        """Verbindung schließen (Unterklasse)."""
        pass

    def read_words(self, area, start, count):
        """``count`` Wörter ab ``start`` im Bereich ``area`` lesen -> Liste von Zahlen 0 … 65535 (Unterklasse)."""
        raise NotImplementedError

    def endpoint(self):
        """„IP:Port“ für Fehlermeldungen."""
        p = self.plc.params
        return f"{p.get('ip', '')}:{p.get('port', '')}"

    # ------------------------------------------------------------------ Planung
    def __init__(self, driver, plc, variables):
        """Leseplan aufstellen: Variablen prüfen, je Bereich nach Wortnummer sortieren und benachbarte (Lücke höchstens
        ``luecke`` Wörter, Länge höchstens ``area_limit``) zu einer Anfrage zusammenfassen.
        """
        super().__init__(driver, plc, variables)
        self.requests = []
        self._open = False
        items = []
        for pos, v in enumerate(self.vars):
            try:
                if self.claim(pos, v):          # vom Treiber gesondert gelesen
                    continue
                if v.dtype not in WORD_TYPES:
                    raise ValueError(tr("Typ {0} wird nicht unterstützt").format(v.dtype))
                area, word, bit = self.parse(v.address, v.dtype)
                if bit is not None and v.dtype != "BOOL":
                    raise ValueError(tr("Bitnummer nur beim Typ BOOL"))
            except ValueError as e:
                self.errors[v.address] = str(e)
                continue
            it = _Item()
            it.pos, it.area, it.word, it.bit, it.dtype, it.address = pos, area, word, bit, v.dtype, v.address
            it.words = WORD_TYPES[v.dtype][0]
            items.append(it)
        gap = int(plc.params.get("luecke", self.default_gap))
        areas = []
        for it in items:
            if it.area not in areas:
                areas.append(it.area)
        for area in areas:
            limit = max(1, self.area_limit(area))
            cur = None
            for it in sorted((i for i in items if i.area == area), key=lambda i: i.word):
                end = it.word + it.words
                # An die laufende Anfrage anhängen, wenn die Lücke klein genug ist und die Anfrage nicht zu lang wird;
                # cur = [Bereich, Start, Anzahl Wörter, Variablen]
                if cur and it.word - (cur[1] + cur[2]) <= gap and end - cur[1] <= limit:
                    cur[2] = max(cur[2], end - cur[1])
                    cur[3].append(it)
                else:
                    cur = [area, it.word, it.words, [it]]
                    self.requests.append(cur)

    # ------------------------------------------------------------------ Reader
    def connect(self):
        """Verbindung öffnen und einmal lesen -> Anzahl lesbarer Variablen."""
        self.close()
        try:
            self.open()
        except (OSError, ConnectionError, DeviceError) as e:
            raise ConnectionError(f"{self.endpoint()}: {e}") from None
        self._open = True
        self.read()
        return max(0, len(self.vars) - len(self.errors))

    def read(self):
        """Ein Messzyklus: alle Anfragen senden und die Werte dekodieren. Gerätefehler betreffen nur die Variablen der
        Anfrage, Übertragungsfehler gelten als Verbindungsabbruch.
        """
        if not self._open:
            raise ConnectionError(tr("nicht verbunden"))
        out = [NAN] * len(self.vars)
        split = []
        for k, (area, start, count, items) in enumerate(self.requests):
            try:
                words = self._fetch(area, start, count)
            # Fehlerantwort der Steuerung (z. B. Adresse gibt es nicht): nur diese Variablen ohne Wert, die Verbindung
            # bleibt. Mehrere Variablen: vielleicht nur eine Lücke dazwischen – einzeln lesen, künftig einzeln anfragen
            except DeviceError as e:
                if len(items) > 1:
                    split.append(k)
                    for it in items:
                        try:
                            self._decode_into(self._fetch(area, it.word, it.words), it.word, it, out)
                        except DeviceError as e1:
                            self.errors[it.address] = str(e1)
                else:
                    self.errors[items[0].address] = str(e)
                continue
            for it in items:
                self._decode_into(words, start, it, out)
        for k in reversed(split):
            area, _s, _c, items = self.requests[k]
            self.requests[k:k + 1] = [[area, it.word, it.words, [it]] for it in items]
        return out

    def _fetch(self, area, start, count):
        """``read_words`` mit einheitlicher Fehlerbehandlung: DeviceError bleibt (Fehler der Anfrage), Übertragungsfehler
        oder kaputte Antwort -> ConnectionError (der Logger verbindet neu)."""
        try:
            return self.read_words(area, start, count)
        except DeviceError:
            raise
        except (OSError, ConnectionError, struct.error, IndexError, ValueError) as e:
            raise ConnectionError(str(e) or type(e).__name__) from None

    def _decode_into(self, words, start, it, out):
        """Wert der Variable ``it`` aus den Wörtern einer Anfrage ab ``start`` in ``out`` eintragen."""
        try:
            out[it.pos] = decode(words, it.word - start, it.dtype, it.bit)
            self.errors.pop(it.address, None)
        except (IndexError, struct.error):
            self.errors[it.address] = tr("Antwort zu kurz")

    def close(self):
        """Verbindung schließen (Fehler beim Schließen werden ignoriert)."""
        if self._open:
            self._open = False
        try:
            self.close_transport()
        except Exception:
            pass


def recv_exact(sock, n):
    """Genau n Bytes von einem TCP-Socket lesen."""
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError(tr("Verbindung von der Steuerung getrennt"))
        buf += chunk
    return buf
