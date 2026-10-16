"""Steuerungstreiber des PLC-Datenloggers: Verzeichnis aller Treiber.

Eingebaut sind
  * s7      – Siemens S7-300/400/1200/1500 über S7-Kommunikation (PUT/GET, python-snap7)
  * tia     – Siemens S7-1200/1500 symbolisch über S7CommPlus (s7commplus, auch optimierte Bausteine)
  * clx     – Allen-Bradley ControlLogix/CompactLogix/Micro800 über EtherNet/IP (libplctag, Tag-Liste mit pycomm3)
  * modbus  – Modbus TCP (Holding-/Input-Register, Coils, Discrete Inputs; ohne Zusatzbibliothek)

Weitere Treiber werden beim Start automatisch geladen aus
  * dem Ordner ``treiber`` im Datenordner des Programms (eigene Treiber, bleiben bei Updates erhalten),
  * den Ordnern in der Umgebungsvariablen ``PLC_TREIBER`` (mehrere mit ; bzw. : getrennt),
  * weiteren Modulen dieses Pakets (Dateiname ohne führenden Unterstrich).
Ein Treibermodul definiert ``DRIVER = MeinTreiber()`` (Unterklasse von plc_treiber.base.Driver); Vorlage:
``plc_treiber/_vorlage.py``.
"""
import importlib
import importlib.util
import os
import pkgutil
import sys

from plc_treiber.base import Driver, Reader
from plc_i18n import tr

BUILTIN = ("s7", "tia", "clx", "modbus")
_drivers = None          # {id: Driver}
_errors = []             # Ladefehler (Modul, Text) – werden im Konfigurationsprogramm angezeigt


class UnknownDriver(Driver):
    """Platzhalter für Steuerungen mit einem Treiber, der nicht (mehr) vorhanden ist."""

    def __init__(self, ident):
        self.id = ident
        self.name = tr("{0} (Treiber fehlt)").format(ident)

    def create_reader(self, plc, variables):
        raise RuntimeError(tr("Treiber „{0}“ ist nicht installiert").format(self.id))


def _register(mod, origin):
    drv = getattr(mod, "DRIVER", None)
    if drv is None:
        cls = getattr(mod, "Driver", None)
        if isinstance(cls, type) and issubclass(cls, Driver) and cls is not Driver:
            drv = cls()
    if drv is None:
        return
    if not isinstance(drv, Driver):
        _errors.append((origin, tr("DRIVER ist keine Unterklasse von plc_treiber.base.Driver")))
        return
    if drv.id in _drivers:
        _errors.append((origin, tr("Treiber-Kürzel „{0}“ ist bereits vergeben").format(drv.id)))
        return
    _drivers[drv.id] = drv


def _plugin_dirs():
    dirs = []
    try:
        from plc_common import BASE_DIR
        dirs.append(os.path.join(BASE_DIR, "treiber"))
    except Exception:
        pass
    env = os.environ.get("PLC_TREIBER", "")
    dirs += [d for d in env.split(os.pathsep) if d]
    return dirs


def load_all(reload=False):
    """Alle Treiber laden (einmalig; reload=True lädt neu)."""
    global _drivers
    if _drivers is not None and not reload:
        return _drivers
    _drivers, _errors[:] = {}, []
    for name in BUILTIN:
        try:
            _register(importlib.import_module(f"plc_treiber.{name}"), name)
        except Exception as e:                      # Treiber fehlerhaft: übrige weiter laden
            _errors.append((name, str(e)))
    # weitere Module im Paket (z. B. nachträglich hineinkopierte Treiber)
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        for m in pkgutil.iter_modules([here]):
            if m.name in BUILTIN or m.name.startswith("_") or m.name in ("base", "ui") or "_" in m.name:
                continue
            try:
                _register(importlib.import_module(f"plc_treiber.{m.name}"), m.name)
            except Exception as e:
                _errors.append((m.name, str(e)))
    except Exception:
        pass
    # eigene Treiber aus Ordnern (Datei-Plugins)
    for d in _plugin_dirs():
        if not os.path.isdir(d):
            continue
        if d not in sys.path:
            sys.path.insert(0, d)                   # Hilfsmodule eines Treibers neben ihm findbar
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".py") or fn.startswith("_"):
                continue
            path = os.path.join(d, fn)
            try:
                spec = importlib.util.spec_from_file_location(f"plc_treiber_ext_{fn[:-3]}", path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _register(mod, path)
            except Exception as e:
                _errors.append((path, f"{type(e).__name__}: {e}"))
    return _drivers


def drivers():
    """Alle geladenen Treiber {Kürzel: Driver} (eingebaute zuerst)."""
    return load_all()


def get_driver(ident) -> Driver:
    """Treiber zu einem Kürzel (unbekannt: Platzhalter, der beim Lesen einen Fehler meldet)."""
    d = load_all().get(ident)
    return d if d is not None else UnknownDriver(ident or "?")


def load_errors():
    """[(Modul/Datei, Fehlertext)] der Treiber, die nicht geladen werden konnten."""
    load_all()
    return list(_errors)


__all__ = ["Driver", "Reader", "drivers", "get_driver", "load_errors", "load_all"]
