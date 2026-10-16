"""Lesen von Tags aus Logix-Steuerungen (ControlLogix, CompactLogix, Micro800) mit libplctag.

libplctag ist eine C-Bibliothek für EtherNet/IP (CIP). Dieses Modul spricht ihre stabile C-Schnittstelle direkt über
``ctypes`` an. Es gibt dafür kein pip-Paket: Die Bibliothek (``plctag.dll`` unter Windows, ``libplctag.so`` unter
Linux) stammt aus dem offiziellen Release (https://github.com/libplctag/libplctag/releases, Paket
``libplctag_<Version>_windows_x64.zip``) und liegt neben den Programmdateien; alternativ kann ihr Pfad in der
Umgebungsvariablen ``CLX_PLCTAG_LIB`` stehen (siehe find_library). Die Windows-DLL braucht nur Systembibliotheken.

Warum direkt die C-Schnittstelle?
---------------------------------
* Sie ist seit Jahren stabil und genau dokumentiert (plc_tag_create/read/status/get_*), unabhängig davon, welche
  Version des Python-Wrappers installiert ist.
* Asynchrones Lesen: Für jeden Messzyklus werden ALLE Tags einer Steuerung zugleich angestoßen
  (``plc_tag_read(tag, 0)``); libplctag fasst die Anfragen selbstständig zu CIP-"Multiple Service Packets" zusammen.
  Danach wird gewartet, bis alle fertig sind. Das ist deutlich schneller als Tag für Tag nacheinander.
* ctypes gibt während der C-Aufrufe die Python-Sperre (GIL) frei; die Lese-Threads mehrerer Steuerungen und die
  Oberfläche laufen dadurch wirklich parallel.

Blocklesemodus
--------------
Ein Block ist ein Ausschnitt eines Array-Tags. Er wird als EIN libplctag-Tag mit ``elem_count = Anzahl`` und dem
Namen des ersten Elements (z. B. ``Messwerte[10]``) angelegt und mit einer Anfrage gelesen; die Werte stehen dann
im Abstand der Elementgröße hintereinander im Puffer.

Klassen
-------
* ``PlcTagLib``  – dünne ctypes-Hülle um die C-Funktionen (eine Instanz je Prozess, siehe ``get_lib``).
* ``TagReader``  – liest die Variablen EINER Steuerung (wird vom Lese-Thread des Recorders benutzt).
* ``FakeLib``    – Ersatz ohne Steuerung (simulierte Werte) für Tests.
"""
import ctypes
import ctypes.util
import glob
import math
import os
import sys
import threading
import time

from clx_common import BASE_DIR, TYPES, Plc
from clx_i18n import tr

# Statuscodes von libplctag (Auszug aus libplctag.h).
PLCTAG_STATUS_PENDING = 1
PLCTAG_STATUS_OK = 0
PLCTAG_ERR_TIMEOUT = -32
# Fehler, bei denen die Verbindung als gestört gilt (statt nur ein einzelner Tag fehlerhaft).
# ABORT -1, BAD_CONNECTION -3, BAD_GATEWAY -6, CLOSE -10, OPEN -26, READ -28, TIMEOUT -32, WINSOCK -36, WRITE -37.
CONNECTION_ERRORS = {-1, -3, -6, -10, -26, -28, -32, -36, -37}

# Getter-Funktion von libplctag je Datentyp (Wert an Byte-Offset lesen).
GETTERS = {
    "SINT": "plc_tag_get_int8", "INT": "plc_tag_get_int16", "DINT": "plc_tag_get_int32",
    "LINT": "plc_tag_get_int64", "USINT": "plc_tag_get_uint8", "UINT": "plc_tag_get_uint16",
    "UDINT": "plc_tag_get_uint32", "ULINT": "plc_tag_get_uint64", "REAL": "plc_tag_get_float32",
    "LREAL": "plc_tag_get_float64", "BOOL": "plc_tag_get_uint8",
}
_CTYPES = {
    "plc_tag_get_int8": ctypes.c_int8, "plc_tag_get_int16": ctypes.c_int16, "plc_tag_get_int32": ctypes.c_int32,
    "plc_tag_get_int64": ctypes.c_int64, "plc_tag_get_uint8": ctypes.c_uint8, "plc_tag_get_uint16": ctypes.c_uint16,
    "plc_tag_get_uint32": ctypes.c_uint32, "plc_tag_get_uint64": ctypes.c_uint64,
    "plc_tag_get_float32": ctypes.c_float, "plc_tag_get_float64": ctypes.c_double,
}


def is_bit_tag(tag: str) -> bool:
    """True für Bit-Zugriffe wie ``Status.3`` (letztes Glied ist eine Zahl)."""
    last = tag.rsplit(".", 1)
    return len(last) == 2 and last[1].isdigit()


# ---------------------------------------------------------------------------------------
# Bibliothek finden und laden
# ---------------------------------------------------------------------------------------
_LIB_NAMES = ("plctag.dll", "libplctag.dll", "libplctag.so", "libplctag.so.*", "libplctag.dylib", "libplctag*.dylib")


def find_library():
    """Pfad der nativen libplctag-Bibliothek suchen (oder None).

    Reihenfolge: Umgebungsvariable CLX_PLCTAG_LIB, Ordner eines evtl. installierten Python-Wrappers ``libplctag``, Programmordner
    bzw. Ordner der .exe/PyInstaller-Dateien, zuletzt die Systemsuche (ctypes.util.find_library)."""
    env = os.environ.get("CLX_PLCTAG_LIB")
    if env and os.path.exists(env):
        return env
    dirs = []
    try:
        import importlib.util
        spec = importlib.util.find_spec("libplctag")
        if spec and spec.submodule_search_locations:
            dirs.extend(spec.submodule_search_locations)
    except (ImportError, ValueError):
        pass
    dirs += [BASE_DIR, os.path.dirname(os.path.abspath(__file__))]
    if getattr(sys, "frozen", False):
        dirs += [getattr(sys, "_MEIPASS", ""), os.path.dirname(sys.executable)]
    # Nur Dateien des eigenen Betriebssystems (unter Linux z. B. nicht die mitgelieferte Windows-DLL).
    ext = ".dll" if sys.platform == "win32" else (".dylib" if sys.platform == "darwin" else ".so")
    names = [n for n in _LIB_NAMES if ext in n]
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for pattern in names:
            hits = glob.glob(os.path.join(d, pattern))
            if not hits and d != BASE_DIR:          # im Datenordner (CSV, Archiv) nicht rekursiv suchen
                hits = glob.glob(os.path.join(d, "**", pattern), recursive=True)
            if hits:
                return sorted(hits)[0]
    return ctypes.util.find_library("plctag")


class PlcTagLib:
    """ctypes-Hülle der benötigten libplctag-Funktionen."""

    def __init__(self, path=None):
        path = path or find_library()
        if not path:
            raise RuntimeError(tr("libplctag wurde nicht gefunden: plctag.dll (64 Bit, aus "
                               "https://github.com/libplctag/libplctag/releases, Paket ..._windows_x64.zip) neben die "
                               "Programmdateien legen oder ihren Pfad in CLX_PLCTAG_LIB angeben."))
        self.path = path
        self.dll = dll = ctypes.CDLL(path)
        i32, cp = ctypes.c_int32, ctypes.c_char_p
        self._sig("plc_tag_create", i32, [cp, ctypes.c_int])
        self._sig("plc_tag_destroy", ctypes.c_int, [i32])
        self._sig("plc_tag_read", ctypes.c_int, [i32, ctypes.c_int])
        self._sig("plc_tag_status", ctypes.c_int, [i32])
        self._sig("plc_tag_abort", ctypes.c_int, [i32])
        self._sig("plc_tag_decode_error", cp, [ctypes.c_int])
        self._sig("plc_tag_get_size", ctypes.c_int, [i32])
        self._sig("plc_tag_get_bit", ctypes.c_int, [i32, ctypes.c_int])
        self._sig("plc_tag_get_int_attribute", ctypes.c_int, [i32, cp, ctypes.c_int])
        for name, ct in _CTYPES.items():
            self._sig(name, ct, [i32, ctypes.c_int])
        # Versionsnummer der Bibliothek (Attribute des "Tags" 0), nur zur Anzeige.
        self.version = ""
        try:
            v = [dll.plc_tag_get_int_attribute(0, k.encode(), 0)
                 for k in ("version_major", "version_minor", "version_patch")]
            self.version = ".".join(str(x) for x in v)
        except Exception:
            pass

    def _sig(self, name, restype, argtypes):
        f = getattr(self.dll, name)
        f.restype, f.argtypes = restype, argtypes

    # --- dünne Aufrufe (Namen wie in C ohne Präfix)
    def create(self, attrs: str, timeout_ms: int) -> int:
        return self.dll.plc_tag_create(attrs.encode("utf-8"), timeout_ms)

    def destroy(self, h):
        return self.dll.plc_tag_destroy(h)

    def read(self, h, timeout_ms=0):
        return self.dll.plc_tag_read(h, timeout_ms)

    def status(self, h):
        return self.dll.plc_tag_status(h)

    def abort(self, h):
        return self.dll.plc_tag_abort(h)

    def decode(self, err) -> str:
        s = self.dll.plc_tag_decode_error(err)
        return s.decode("utf-8", "replace") if s else f"Fehler {err}"

    def elem_size(self, h, default):
        v = self.dll.plc_tag_get_int_attribute(h, b"elem_size", 0)
        return v if v > 0 else default

    def get(self, h, dtype, offset):
        return float(getattr(self.dll, GETTERS[dtype])(h, offset))

    def get_bit(self, h, bit):
        return float(self.dll.plc_tag_get_bit(h, bit) > 0)


_lib = None
_lib_lock = threading.Lock()


def get_lib():
    """Gemeinsame PlcTagLib-Instanz (wird beim ersten Aufruf geladen)."""
    global _lib
    with _lib_lock:
        if _lib is None:
            _lib = PlcTagLib()
        return _lib


def tag_attrs(plc: Plc, name: str, elem_count: int = 1) -> str:
    """Attribut-Text für plc_tag_create, z. B.
    ``protocol=ab-eip&gateway=192.168.1.10&path=1,0&plc=controllogix&name=Temp&elem_count=1``."""
    parts = ["protocol=ab-eip", f"gateway={plc.ip}"]
    if plc.pfad.strip():
        parts.append(f"path={plc.pfad.strip()}")
    parts += [f"plc={plc.cpu}", f"name={name}", f"elem_count={max(1, int(elem_count))}"]
    return "&".join(parts)


# ---------------------------------------------------------------------------------------
# Lesen der Variablen einer Steuerung
# ---------------------------------------------------------------------------------------
class _Entry:
    """Ein libplctag-Tag des Leseplans: eine Einzelvariable oder ein ganzer Block."""
    __slots__ = ("name", "handle", "dtype", "count", "items", "bit", "esize", "error")

    def __init__(self, name, dtype, count, items, bit):
        self.name, self.dtype, self.count, self.items, self.bit = name, dtype, count, items, bit
        self.handle, self.esize, self.error = None, TYPES[dtype][0], ""


class TagReader:
    """Liest die Variablen EINER Steuerung. Nicht thread-sicher: jeder Lese-Thread hat seinen eigenen Reader.

    variables: Liste von Variable (ohne berechnete). ``read()`` liefert die Werte in derselben Reihenfolge;
    nicht lesbare Werte sind NaN. Fehler einzelner Tags (z. B. Name falsch geschrieben) stehen in ``errors`` und
    stören die übrigen Tags nicht. Sind ALLE Tags gestört (Verbindung weg), löst ``read()`` ConnectionError aus."""

    def __init__(self, plc: Plc, variables, lib=None):
        self.plc, self.vars = plc, list(variables)
        self.lib = lib
        self.entries = []
        blocks = {}
        for pos, v in enumerate(self.vars):
            if v.block:
                # Alle Elemente eines Blocks teilen sich einen Tag: Name des ersten Elements, elem_count = Anzahl.
                e = blocks.get(v.block)
                if e is None:
                    e = blocks[v.block] = _Entry("", v.dtype, 0, [], False)
                    self.entries.append(e)
                e.items.append((pos, v))
            else:
                self.entries.append(_Entry(v.tag, v.dtype, 1, [(pos, v)], v.dtype == "BOOL" and is_bit_tag(v.tag)))
        for e in blocks.values():
            e.items.sort(key=lambda it: it[1].block_idx)
            first = e.items[0][1]
            base = first.tag.rsplit("[", 1)[0]
            start = int(first.tag.rsplit("[", 1)[1].rstrip("]")) - first.block_idx
            e.name = f"{base}[{start}]"
            e.count = max(v.block_idx for _, v in e.items) + 1
        self.errors = {}          # Tag-Name -> Fehlertext (einzelne Tags)

    @property
    def timeout_ms(self):
        return max(100, int(self.plc.timeout_ms))

    def connect(self):
        """Alle Tags anlegen (asynchron) und warten, bis die Steuerung geantwortet hat.

        Rückgabe: Anzahl der nutzbaren Tags. ConnectionError, wenn keiner angelegt werden konnte."""
        self.close()
        lib = self.lib = self.lib or get_lib()
        self.errors = {}
        for e in self.entries:
            e.error = ""
            h = lib.create(tag_attrs(self.plc, e.name, e.count), 0)        # 0 = asynchron anlegen
            if h < 0:
                e.handle, e.error = None, lib.decode(h)
            else:
                e.handle = h
        self._wait([e for e in self.entries if e.handle is not None])
        ok = 0
        for e in self.entries:
            if e.handle is None:
                self.errors[e.name] = e.error
                continue
            st = lib.status(e.handle)
            if st != PLCTAG_STATUS_OK:
                e.error = self._text(st)
                self.errors[e.name] = e.error
                lib.destroy(e.handle)
                e.handle = None
            else:
                e.esize = lib.elem_size(e.handle, TYPES[e.dtype][0])
                ok += 1
        if self.entries and ok == 0:
            first = next(iter(self.errors.values()), tr("keine Antwort"))
            raise ConnectionError(f"{self.plc.ip}: {first}")
        # libplctag legt Tags teils ohne Rückfrage bei der Steuerung an. Erst ein erfolgreicher Lesezyklus beweist,
        # dass die Steuerung antwortet (sonst ConnectionError aus read()).
        if ok:
            try:
                self.read()
            except ConnectionError as e:
                self.close()
                raise ConnectionError(f"{self.plc.ip}: {e}") from None
        return ok - sum(1 for e in self.entries if e.handle is not None and e.name in self.errors)

    def _text(self, status):
        """Fehlertext; eine nach Ablauf der Wartezeit noch laufende Anfrage heißt 'keine Antwort'."""
        if status == PLCTAG_STATUS_PENDING:
            return tr("keine Antwort innerhalb von {0} ms").format(self.timeout_ms)
        return self.lib.decode(status)

    def _wait(self, entries):
        """Warten, bis kein Tag mehr 'in Arbeit' ist (höchstens timeout_ms); hängende Anfragen werden abgebrochen."""
        lib = self.lib
        end = time.perf_counter() + self.timeout_ms / 1000.0
        pending = [e for e in entries if e.handle is not None]
        while pending:
            pending = [e for e in pending if lib.status(e.handle) == PLCTAG_STATUS_PENDING]
            if not pending:
                break
            if time.perf_counter() >= end:
                for e in pending:
                    lib.abort(e.handle)
                break
            time.sleep(0.001)

    def read(self):
        """Ein Messzyklus: alle Tags zugleich lesen -> Liste der Werte (NaN = nicht lesbar)."""
        lib = self.lib
        out = [math.nan] * len(self.vars)
        active = [e for e in self.entries if e.handle is not None]
        for e in active:
            rc = lib.read(e.handle, 0)                                  # 0 = asynchron anstoßen
            e.error = "" if rc in (PLCTAG_STATUS_OK, PLCTAG_STATUS_PENDING) else lib.decode(rc)
        self._wait(active)
        n_conn_err = 0
        for e in active:
            st = lib.status(e.handle)
            if st != PLCTAG_STATUS_OK:
                e.error = self._text(st)
                self.errors[e.name] = e.error
                if st in CONNECTION_ERRORS or st == PLCTAG_STATUS_PENDING:
                    n_conn_err += 1
                continue
            self.errors.pop(e.name, None)
            for pos, v in e.items:
                if e.bit:
                    out[pos] = lib.get_bit(e.handle, 0)
                elif v.dtype == "BOOL":
                    out[pos] = float(lib.get(e.handle, "BOOL", 0) != 0)
                else:
                    out[pos] = lib.get(e.handle, v.dtype, v.block_idx * e.esize if v.block else 0)
        if active and n_conn_err == len(active):
            raise ConnectionError(next(iter(self.errors.values()), tr("keine Antwort")))
        return out

    def close(self):
        """Alle Tags freigeben (die Verbindung schließt libplctag, sobald kein Tag sie mehr benutzt)."""
        if self.lib is None:
            return
        for e in self.entries:
            if e.handle is not None:
                try:
                    self.lib.destroy(e.handle)
                except Exception:
                    pass
                e.handle = None


def read_once(plc: Plc, variables, lib=None):
    """Variablen einmal lesen (Verbindungstest im Konfigurationsprogramm).

    Rückgabe: (Werte, Fehler je Tag-Name). Löst ConnectionError aus, wenn die Steuerung nicht erreichbar ist."""
    r = TagReader(plc, variables, lib)
    try:
        r.connect()
        return r.read(), dict(r.errors)
    finally:
        r.close()


# ---------------------------------------------------------------------------------------
# Ersatz-Bibliothek für Tests (ohne Steuerung)
# ---------------------------------------------------------------------------------------
class FakeLib:
    """Verhält sich wie PlcTagLib, liefert aber simulierte Werte (Sinus, Rampen, Bits).

    ``missing``: Tag-Namen, die es "nicht gibt"; ``offline=True``: Steuerung nicht erreichbar."""

    def __init__(self, missing=(), offline=False):
        self.missing, self.offline = set(missing), offline
        self.tags, self.next = {}, 1
        self.t0 = time.time()
        self.version = "fake"

    def create(self, attrs, timeout_ms):
        a = dict(p.split("=", 1) for p in attrs.split("&"))
        h, self.next = self.next, self.next + 1
        self.tags[h] = a
        return h

    def destroy(self, h):
        self.tags.pop(h, None)
        return 0

    def read(self, h, timeout_ms=0):
        return PLCTAG_STATUS_OK

    def status(self, h):
        if self.offline:
            return PLCTAG_ERR_TIMEOUT
        if self.tags[h]["name"].split("[")[0] in self.missing or self.tags[h]["name"] in self.missing:
            return -19
        return PLCTAG_STATUS_OK

    def abort(self, h):
        return 0

    def decode(self, err):
        return {-19: "PLCTAG_ERR_NOT_FOUND", -32: "PLCTAG_ERR_TIMEOUT"}.get(err, f"Fehler {err}")

    def elem_size(self, h, default):
        return default

    def get(self, h, dtype, offset):
        t = time.time() - self.t0
        k = (hash(self.tags[h]["name"]) % 7) + offset
        if dtype == "BOOL":
            return float(int(t + k) % 2)
        if dtype in ("REAL", "LREAL"):
            return 50 + 40 * math.sin(t / 3 + k)
        return float(int(t * 10 + k) % 1000)

    def get_bit(self, h, bit):
        return float(int(time.time() - self.t0) % 2)
