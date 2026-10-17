# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Treiber „modbus_rtu“: Modbus RTU über eine serielle Schnittstelle (RS-485/RS-232) mit pymodbus.

Für Frequenzumrichter, Energiezähler, Temperaturregler, Kompaktsteuerungen usw. am RS-485-Bus (USB-Adapter oder
eingebaute Schnittstelle). Adressen, Datentypen, Byte-/Wortfolge und das Zusammenfassen benachbarter Adressen sind
dieselben wie beim Treiber „modbus“ (Modbus TCP):

    40001 / HR0   Holding-Register      30001 / IR0   Input-Register      40001.3   Bit eines Registers
    00001 / C0    Coils                 10001 / DI0   Discrete Inputs

Mehrere Geräte an einem Bus: je Gerät eine Steuerung mit gleicher Schnittstelle und eigener Geräteadresse anlegen.
Der Treiber sorgt dafür, dass sich diese Steuerungen die Schnittstelle teilen (Anfragen nacheinander).
Bibliothek: ``pip install pymodbus pyserial`` (pymodbus 3.x oder 4.x).
"""
import threading

from plc_i18n import tr
from plc_treiber.base import Param
from plc_treiber.modbus import CO, DI, HR, IR, ModbusDriver, ModbusError, ModbusReader, EXCEPTIONS

# Je Schnittstelle EIN pymodbus-Client, gemeinsam für alle Steuerungen (Geräte) an diesem Bus.
_PORTS = {}                       # Schnittstelle -> [Client, Sperre, Nutzer, Einstellungen]
_PORTS_LOCK = threading.Lock()


def _call(fn, start, count, unit):
    """pymodbus-Lesefunktion mit der je nach Version richtigen Benennung der Geräteadresse aufrufen."""
    for key in ("device_id", "slave", "unit"):
        try:
            return fn(start, count=count, **{key: unit})
        except TypeError as e:
            if key not in str(e):
                raise
    raise RuntimeError(tr("Unbekannte pymodbus-Version"))


class SerialBusClient:
    """Übertragung für ModbusReader: Modbus RTU über pymodbus, Schnittstelle von mehreren Geräten geteilt."""

    def __init__(self, params):
        self.p = params
        self.port = str(params.get("schnittstelle", "")).strip()
        self.unit = int(params.get("unit", 1))
        self.entry = None

    def _line(self):
        """Leitungsparameter – müssen für alle Geräte an einer Schnittstelle gleich sein."""
        p = self.p
        return (int(p.get("baud", 19200)), str(p.get("paritaet", "E")), int(p.get("stoppbits", 1)),
                int(p.get("datenbits", 8)))

    def connect(self):
        from pymodbus.client import ModbusSerialClient
        if not self.port:
            raise ConnectionError(tr("Keine Schnittstelle eingestellt"))
        baud, parity, stop, bits = self._line()
        tmo, retries = int(self.p.get("timeout_ms", 1000)), int(self.p.get("wiederholungen", 1))
        with _PORTS_LOCK:
            entry = _PORTS.get(self.port)
            if entry is not None and entry[3] != self._line():
                raise ConnectionError(tr("Schnittstelle {0} wird von einer anderen Steuerung mit anderen Einstellungen "
                                         "benutzt (Baudrate/Parität/Stoppbits müssen gleich sein)").format(self.port))
            if entry is None:
                kw = dict(port=self.port, baudrate=baud, parity=parity, stopbits=stop, bytesize=bits,
                          timeout=tmo / 1000.0, retries=retries)
                try:
                    client = ModbusSerialClient(**kw)
                except TypeError:                       # sehr alte Versionen: Methode statt Framer
                    kw.pop("retries", None)
                    client = ModbusSerialClient(method="rtu", **kw)
                if not client.connect():
                    raise ConnectionError(tr("Schnittstelle {0} lässt sich nicht öffnen").format(self.port))
                entry = [client, threading.Lock(), 0, self._line()]
                _PORTS[self.port] = entry
            entry[2] += 1
            self.entry = entry

    def close(self):
        if self.entry is None:
            return
        with _PORTS_LOCK:
            self.entry[2] -= 1
            if self.entry[2] <= 0:
                try:
                    self.entry[0].close()
                except Exception:
                    pass
                if _PORTS.get(self.port) is self.entry:
                    del _PORTS[self.port]
            self.entry = None

    def request(self, fc, start, count):
        if self.entry is None:
            raise ConnectionError(tr("nicht verbunden"))
        client, lock = self.entry[0], self.entry[1]
        fn = {1: client.read_coils, 2: client.read_discrete_inputs, 3: client.read_holding_registers,
              4: client.read_input_registers}[fc]
        with lock:                                       # ein Telegramm zur Zeit auf dem Bus
            try:
                rr = _call(fn, start, count, self.unit)
            except Exception as e:                       # pymodbus: ModbusIOException, ConnectionException …
                name = type(e).__name__
                if "IO" in name or "Connection" in name or isinstance(e, OSError):
                    raise ConnectionError(tr("Gerät {0} antwortet nicht: {1}").format(self.unit, e)) from None
                raise
        if rr is None:
            raise ConnectionError(tr("Gerät {0} antwortet nicht").format(self.unit))
        if rr.isError():
            code = getattr(rr, "exception_code", None)
            if code:
                raise ModbusError(tr("Modbus-Ausnahme {0} ({1})").format(code, tr(EXCEPTIONS.get(code, "unbekannt"))))
            raise ConnectionError(tr("Gerät {0} antwortet nicht: {1}").format(self.unit, rr))
        if fc in (1, 2):                                 # Bits wie im Telegramm packen (LSB = erstes Bit)
            bits = list(rr.bits)[:count]
            out = bytearray((count + 7) // 8)
            for i, b in enumerate(bits):
                if b:
                    out[i // 8] |= 1 << (i % 8)
            return bytes(out)
        return b"".join(int(r & 0xFFFF).to_bytes(2, "big") for r in list(rr.registers)[:count])


class ModbusRtuReader(ModbusReader):
    def make_client(self):
        return SerialBusClient(self.plc.params)

    def endpoint(self):
        p = self.plc.params
        return f"{p.get('schnittstelle', '')}, Gerät {p.get('unit', 1)}"


class ModbusRtuDriver(ModbusDriver):
    id = "modbus_rtu"
    name = tr("Modbus RTU (seriell, pymodbus)")
    description = tr("RS-485/RS-232: Umrichter, Zähler, Regler; mehrere Geräte an einer Schnittstelle möglich")
    params = [
        Param("schnittstelle", tr("Schnittstelle"), "text", "COM3",
              tip=tr("Windows: COM3 …, Linux: /dev/ttyUSB0, /dev/ttyAMA0 …")),
        Param("unit", tr("Geräteadresse"), "int", 1, minimum=0, maximum=247, tip=tr("Modbus-Slave-Adresse 1–247")),
        Param("baud", tr("Baudrate"), "choice", "19200",
              choices=[(b, b) for b in ("1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200")]),
        Param("paritaet", tr("Parität"), "choice", "E",
              choices=[("E", tr("gerade (Even)")), ("O", tr("ungerade (Odd)")), ("N", tr("keine (None)"))]),
        Param("stoppbits", tr("Stoppbits"), "choice", "1", choices=[("1", "1"), ("2", "2")]),
        Param("wortfolge", tr("Byte-/Wortfolge"), "choice", "ABCD",
              choices=[("ABCD", tr("ABCD – Big Endian (Standard)")), ("CDAB", tr("CDAB – Wörter getauscht")),
                       ("BADC", tr("BADC – Bytes getauscht")), ("DCBA", tr("DCBA – Little Endian"))],
              tip=tr("Reihenfolge bei Werten über mehrere Register (DINT, REAL …); laut Gerätehandbuch")),
        Param("datenbits", tr("Datenbits"), "choice", "8", choices=[("8", "8"), ("7", "7")], advanced=True),
        Param("max_register", tr("Register je Anfrage"), "int", 60, minimum=1, maximum=125, advanced=True,
              tip=tr("Kleinere Werte entlasten langsame Geräte")),
        Param("luecke", tr("Lücke zusammenfassen bis"), "int", 4, minimum=0, maximum=100, advanced=True,
              suffix=tr(" Register")),
        Param("timeout_ms", tr("Zeitlimit"), "int", 1000, minimum=50, maximum=60000, suffix=" ms", advanced=True),
        Param("wiederholungen", tr("Wiederholungen"), "int", 1, minimum=0, maximum=10, advanced=True,
              tip=tr("Erneute Versuche, wenn ein Gerät nicht antwortet")),
    ]
    library = "pymodbus, pyserial"

    def summary(self, plc):
        p = plc.params
        return f"{p.get('schnittstelle', '')} {p.get('baud', 19200)} {p.get('paritaet', 'E')}{p.get('stoppbits', 1)}, " \
               f"Gerät {p.get('unit', 1)}"

    def check_params(self, params):
        if not str(params.get("schnittstelle", "")).strip():
            return tr("Schnittstelle fehlt")
        return ""

    def check_library(self):
        import pymodbus  # noqa: F401
        import serial  # noqa: F401
        return True

    def create_reader(self, plc, variables):
        return ModbusRtuReader(self, plc, variables)


DRIVER = ModbusRtuDriver()
__all__ = ["DRIVER", "HR", "IR", "CO", "DI"]
