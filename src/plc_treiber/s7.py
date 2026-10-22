# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Treiber „s7“: Siemens S7-300/400/1200/1500 über S7-Kommunikation (PUT/GET) mit python-snap7.

Adressen in Siemens-Schreibweise (deutsch oder englisch), der Datentyp kommt aus der Spalte „Typ“:

    DB10.DBX4.2   DB10.DBB4   DB10.DBW4   DB10.DBD4      Datenbaustein (Bit, Byte, Wort, Doppelwort)
    DB10.4        DB10.4.2                               Kurzform: DB-Nummer, Byte[, Bit]
    M5.0  MB5  MW10  MD20                                Merker
    E0.1  EB0  EW64  /  I0.1  IB0  IW64                  Eingänge
    A1.0  AB1  AW2   /  Q1.0  QB1  QW2                   Ausgänge

S7-1200/1500: PUT/GET muss in der CPU erlaubt sein, gelesen werden nur nicht optimierte Datenbausteine. Für
optimierte Bausteine den Treiber „tia“ verwenden. Blöcke (Startadresse + Anzahl) werden mit EINER Anfrage gelesen.
Der Auswahldialog übernimmt Variablen aus importierten DB-Quellen (TIA Portal/STEP 7), da die SPS über
S7-Kommunikation keine Namen liefert.
"""
import re
import struct

from plc_common import s7_address
from plc_i18n import tr
from plc_treiber.base import NAN, BrowseResult, Driver, Param, Reader

# Datentyp -> (Größe in Bytes, struct-Format; Big Endian wie in der S7)
S7_TYPES = {
    "BOOL": (1, None), "BYTE": (1, ">B"), "USINT": (1, ">B"), "SINT": (1, ">b"), "CHAR": (1, ">B"),
    "WORD": (2, ">H"), "UINT": (2, ">H"), "INT": (2, ">h"),
    "DWORD": (4, ">I"), "UDINT": (4, ">I"), "DINT": (4, ">i"), "REAL": (4, ">f"), "TIME": (4, ">i"),
    "LWORD": (8, ">Q"), "ULINT": (8, ">Q"), "LINT": (8, ">q"), "LREAL": (8, ">d"),
}

_RE_DB = re.compile(r"^DB(\d+)\.DB([XBWDL]?)(\d+)(?:\.(\d))?$", re.I)
_RE_DB_SHORT = re.compile(r"^DB(\d+)\.(\d+)(?:\.(\d))?$", re.I)
_RE_AREA = re.compile(r"^([MEAIQ])([XBWDL]?)(\d+)(?:\.(\d))?$", re.I)
_AREA_KEY = {"M": "MK", "E": "PE", "I": "PE", "A": "PA", "Q": "PA", "DB": "DB"}


def parse(address: str):
    """'DB10.DBD4' -> (Bereich, DB, Byte, Bit, Bereichsbuchstabe). ValueError bei ungültiger Adresse."""
    a = (address or "").strip().replace(" ", "")
    m = _RE_DB.match(a)
    if m:
        return "DB", int(m.group(1)), int(m.group(3)), int(m.group(4) or 0), "DB"
    m = _RE_DB_SHORT.match(a)
    if m:
        return "DB", int(m.group(1)), int(m.group(2)), int(m.group(3) or 0), "DB"
    m = _RE_AREA.match(a)
    if m:
        letter = m.group(1).upper()
        return _AREA_KEY[letter], 0, int(m.group(3)), int(m.group(4) or 0), letter
    raise ValueError(tr("Ungültige S7-Adresse „{0}“ (z. B. DB10.DBD4, M5.0, EW64)").format(address))


def fmt(letter, db, byte, bit, dtype) -> str:
    """Adresse in einheitlicher deutscher Schreibweise (z. B. DB10.DBD4, MW10, E0.1) aus ihren Teilen."""
    return s7_address("DB" if letter == "DB" else letter, db, byte, bit, dtype)


def _areas():
    """snap7-Konstanten der Speicherbereiche (Name je nach python-snap7-Version unterschiedlich)."""
    try:
        from snap7.type import Area as A
    except ImportError:
        try:
            from snap7.type import Areas as A
        except ImportError:
            from snap7.types import Areas as A
    return {"DB": A.DB, "MK": A.MK, "PE": A.PE, "PA": A.PA}


def _block_db_type():
    """snap7-Konstante für den Bausteintyp DB (Name je nach python-snap7-Version) oder None."""
    for mod, attr in (("snap7.type", "Block"), ("snap7.types", "Block"), ("snap7.type", "Blocks"), ("snap7.types", "Blocks")):
        try:
            m = __import__(mod, fromlist=[attr])
            return getattr(getattr(m, attr), "DB")
        except Exception:
            continue
    return None


def list_plc_dbs(client) -> dict:
    """{DB-Nummer: Größe in Bytes oder None} der Datenbausteine in der SPS (für den Abgleich im Auswahldialog)."""
    db_type = _block_db_type()
    if db_type is None:
        raise RuntimeError(tr("Die installierte python-snap7-Version unterstützt keine Bausteinliste."))
    result = {}
    for n in [int(x) for x in client.list_blocks_of_type(db_type, 2000)]:
        try:
            result[n] = int(client.get_block_info(db_type, n).MC7Size)
        except Exception:
            result[n] = None
    return result


class _Item:
    """Eine zu lesende Variable mit zerlegter Adresse: Position in der Ergebnisliste, Bereich, DB, Byte, Bit, Typ."""
    __slots__ = ("pos", "area", "db", "byte", "bit", "dtype", "address")


class S7Reader(Reader):
    """Liest mit snap7: Blöcke mit einer Anfrage je Block, Einzelvariablen einzeln."""

    def __init__(self, driver, plc, variables):
        """Leseplan aufstellen: Variablen eines Blocks werden zu EINER Anfrage über den ganzen Bytebereich
        zusammengefasst, alle übrigen einzeln gelesen. Ungültige Adressen stehen gleich in ``errors``.
        """
        super().__init__(driver, plc, variables)
        self.client = None
        self.plan = []           # [("block", area, db, start, nbytes, [items]) | ("single", item)]
        self.bad = {}            # pos -> Fehlertext (ungültige Adresse)
        blocks = {}
        for pos, v in enumerate(self.vars):
            it = _Item()
            it.pos, it.dtype, it.address = pos, v.dtype, v.address
            try:
                it.area, it.db, it.byte, it.bit, _letter = parse(v.address)
                if v.dtype not in S7_TYPES:
                    raise ValueError(tr("Typ {0} wird nicht unterstützt").format(v.dtype))
            except ValueError as e:
                self.bad[pos] = str(e)
                self.errors[v.address] = str(e)
                continue
            if v.block:
                blocks.setdefault((v.block, it.area, it.db), []).append(it)
            else:
                self.plan.append(("single", it))
        for (_name, area, db), items in blocks.items():
            start = min(i.byte for i in items)
            end = max(i.byte + (1 if i.dtype == "BOOL" else S7_TYPES[i.dtype][0]) for i in items)
            self.plan.append(("block", area, db, start, end - start, items))

    def connect(self):
        """Mit Rack/Slot verbinden und einmal lesen (erst ein erfolgreicher Lesezyklus beweist die Verbindung) -> Anzahl
        lesbarer Variablen.
        """
        from snap7.client import Client
        self.close()
        self.areas = _areas()
        c = Client()
        try:
            c.connect(self.plc.ip, int(self.plc.rack), int(self.plc.slot))
        except Exception as e:
            raise ConnectionError(f"{self.plc.ip}: {e}") from None
        self.client = c
        self.read()                      # erst ein Lesezyklus beweist die Verbindung
        return max(0, len(self.vars) - len(self.errors))

    @staticmethod
    def _decode(raw, it, base):
        """Wert einer Variable aus den gelesenen Bytes (``base`` = erstes gelesenes Byte): BOOL als Bit, sonst struct
        (Big Endian).
        """
        off = it.byte - base
        if it.dtype == "BOOL":
            return float((raw[off] >> it.bit) & 1)
        return float(struct.unpack_from(S7_TYPES[it.dtype][1], raw, off)[0])

    def _failed(self, exc, addr):
        """Fehler einer Anfrage: Verbindung weg -> Ausnahme, sonst Fehler dieser Adresse merken."""
        try:
            alive = bool(self.client.get_connected())
        except Exception:
            alive = False
        if not alive:
            raise ConnectionError(str(exc))
        self.errors[addr] = str(exc)

    def read(self):
        """Ein Messzyklus nach dem Leseplan. Fehler einer Anfrage betreffen nur ihre Variablen – außer die Verbindung
        ist weg (siehe ``_failed``).
        """
        out = [NAN] * len(self.vars)
        c = self.client
        for entry in self.plan:
            if entry[0] == "block":
                _k, area, db, start, nbytes, items = entry
                label = items[0].address
                try:
                    raw = bytes(c.read_area(self.areas[area], db, start, nbytes))
                except Exception as e:
                    self._failed(e, label)
                    continue
                self.errors.pop(label, None)
                for it in items:
                    out[it.pos] = self._decode(raw, it, start)
            else:
                it = entry[1]
                size = S7_TYPES[it.dtype][0]
                try:
                    raw = bytes(c.read_area(self.areas[it.area], it.db, it.byte, size))
                except Exception as e:
                    self._failed(e, it.address)
                    continue
                self.errors.pop(it.address, None)
                out[it.pos] = self._decode(raw, it, it.byte)
        return out

    def close(self):
        """Verbindung trennen."""
        if self.client is not None:
            try:
                self.client.disconnect()
            except Exception:
                pass
            self.client = None


class S7Driver(Driver):
    """Treiber „s7“ (siehe Modulbeschreibung)."""
    id = "s7"
    name = tr("Siemens S7 (PUT/GET, snap7)")
    description = tr("S7-300/400/1200/1500 über S7-Kommunikation; absolute Adressen, nicht optimierte Bausteine")
    params = [
        Param("ip", tr("IP-Adresse"), "text", "192.168.0.1"),
        Param("rack", tr("Rack"), "int", 0, minimum=0, maximum=7),
        Param("slot", tr("Slot"), "int", 1, minimum=0, maximum=31,
              tip=tr("S7-300: 2, S7-400: laut Hardware, S7-1200/1500: 1 (bzw. 0)")),
    ]
    types = list(S7_TYPES)
    address_label = tr("Adresse")
    address_hint = tr("Siemens-Adresse, z. B. DB10.DBD4, DB10.DBX0.3, M5.0, MW10, EW64, A1.0")
    block_hint = tr("Startadresse, z. B. DB10.DBD0 (Elemente folgen lückenlos)")
    block_uses_index = False
    browse_label = tr("Aus DB-Quelle wählen…")
    library = "python-snap7"

    def summary(self, plc):
        """„IP, Rack r/Slot s“."""
        return f"{plc.params.get('ip', '')}, Rack {plc.params.get('rack', 0)}/Slot {plc.params.get('slot', 1)}"

    def check_address(self, address, dtype):
        """Adresse zerlegbar und Datentyp bekannt? -> Fehlertext oder ""."""
        try:
            parse(address)
        except ValueError as e:
            return str(e)
        if dtype not in S7_TYPES:
            return tr("Typ {0} wird nicht unterstützt").format(dtype)
        return ""

    def normalize_address(self, address, dtype):
        """Einheitliche Schreibweise (englische Bereichsbuchstaben und Kurzformen werden umgesetzt)."""
        try:
            area, db, byte, bit, letter = parse(address)
        except ValueError:
            return address.strip()
        return fmt(letter, db, byte, bit, dtype)

    def block_element_address(self, block, i):
        """Adresse des i-ten Elements: BOOL zählt Bits weiter (über Bytegrenzen), sonst um die Typgröße in Bytes."""
        try:
            area, db, byte, bit, letter = parse(block.address)
        except ValueError:
            return f"{block.address}+{i}"
        if block.dtype == "BOOL":
            pos = bit + i
            return fmt(letter, db, byte + pos // 8, pos % 8, "BOOL")
        return fmt(letter, db, byte + i * S7_TYPES.get(block.dtype, (4,))[0], 0, block.dtype)

    def check_block(self, block):
        """Startadresse gültig und Format für Blöcke erlaubt?"""
        try:
            parse(block.address)
        except ValueError as e:
            return str(e)
        return super().check_block(block)

    def check_library(self):
        """python-snap7 vorhanden? (ImportError sonst)"""
        import snap7  # noqa: F401
        return True

    def create_reader(self, plc, variables):
        """Leser für eine Steuerung (siehe S7Reader)."""
        return S7Reader(self, plc, variables)

    # ------------------------------------------------------------------ Auswahldialog
    def browse(self, parent, ctx):
        """Auswahldialog aus importierten DB-Quellen (S7 liefert über PUT/GET keine Namen); bereits vorhandene Adressen
        werden markiert. Die Liste der Quellen wird in den Treiberdaten der Konfiguration gespeichert.
        """
        from plc_treiber.s7_browser import SymbolBrowser
        from plc_treiber.s7_symbols import config_type
        existing = set()
        for a in ctx.existing:
            try:
                area, db, byte, bit, _l = parse(a)
            except ValueError:
                continue
            if area == "DB":
                existing.add((db, byte, bit))
                existing.add((db, byte, 0))
        sources = [e for e in str(ctx.store.get("symbolquellen", "")).split("|") if e]
        p = ctx.plc.params
        dlg = SymbolBrowser(parent, lambda: {"ip": p.get("ip"), "rack": int(p.get("rack", 0)),
                                             "slot": int(p.get("slot", 1))},
                            sources, existing, ctx.target_labels, ctx.default_target)
        dlg.exec()
        res = BrowseResult(target_index=dlg.target_index, store={"symbolquellen": "|".join(dlg.entries())})
        for n in dlg.result_nodes:
            ct = config_type(n.dtype) or "REAL"
            res.variables.append((n.path, s7_address("DB", n.db, n.byte, n.bit, ct), ct))
        res.blocks = list(dlg.result_blocks)          # Arrays im Blocklesemodus (Startadresse, Anzahl)
        return res


DRIVER = S7Driver()
