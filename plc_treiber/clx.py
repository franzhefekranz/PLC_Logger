"""Treiber „clx“: Allen-Bradley ControlLogix, CompactLogix und Micro800 über EtherNet/IP (CIP).

Gelesen wird mit der Bibliothek libplctag (plctag.dll bzw. libplctag.so, über ctypes), die Tag-Liste für den
Auswahldialog liefert pycomm3. Adressen sind Tag-Namen wie in Studio 5000:

    Temp_Kessel   Program:Main.Druck   Anlage.Motor[2].Drehzahl   Status.3 (Bit 3 eines Integers, Typ BOOL)

Blöcke: Array-Tag ohne Index + erster Index + Anzahl, gelesen mit einer Anfrage.
"""
from plc_i18n import tr
from plc_treiber.base import BrowseResult, Driver, Param
from plc_treiber.clx_common import BLOCK_TYPES, CPUS, TYPES, check_tag_name


class ClxDriver(Driver):
    id = "clx"
    name = tr("Allen-Bradley Logix (EtherNet/IP, libplctag)")
    description = tr("ControlLogix, CompactLogix, Micro800; Tag-Namen wie in Studio 5000")
    params = [
        Param("ip", tr("IP-Adresse"), "text", "192.168.1.10"),
        Param("pfad", tr("CIP-Pfad"), "text", "1,0",
              tip=tr("CIP-Pfad zur CPU: 1,<Steckplatz> (Backplane-Port 1). CompactLogix: 1,0. Micro800: leer.")),
        Param("cpu", tr("Steuerungstyp"), "choice", "controllogix", choices=[(k, v) for k, v in CPUS.items()]),
        Param("timeout_ms", tr("Zeitlimit"), "int", 2000, minimum=100, maximum=60000, suffix=" ms", advanced=True,
              tip=tr("Zeitlimit je Lesezyklus")),
    ]
    types = list(TYPES)
    block_types = BLOCK_TYPES
    address_label = tr("Tag-Name")
    address_hint = tr("Tag-Name wie in Studio 5000, z. B. Temp, Program:Main.Druck, Motor[2].Drehzahl, Status.3")
    block_hint = tr("Array-Tag ohne Index, z. B. Messwerte, Program:Main.Temp oder Motor[1].Historie")
    block_uses_index = True
    browse_label = tr("Aus Tag-Liste wählen…")
    library = "libplctag (plctag.dll / libplctag.so), pycomm3"

    def summary(self, plc):
        p = plc.params
        cpu = tr(CPUS.get(p.get("cpu"), p.get("cpu", "")))
        return f"{p.get('ip', '')}" + (f", Pfad {p.get('pfad')}" if p.get("pfad") else "") + f", {cpu}"

    def normalize_params(self, raw):
        out = super().normalize_params(raw)
        out["pfad"] = str(out.get("pfad", "")).replace(" ", "")
        out["cpu"] = str(out.get("cpu", "controllogix")).lower()
        if out["cpu"] not in CPUS:
            out["cpu"] = "controllogix"
        return out

    def check_address(self, address, dtype):
        if not check_tag_name(address):
            return tr("Ungültiger Tag-Name „{0}“").format(address)
        if dtype not in TYPES:
            return tr("Typ {0} wird nicht unterstützt").format(dtype)
        return ""

    def check_block(self, block):
        if not check_tag_name(block.address) or "[" in block.address.rsplit(".", 1)[-1]:
            return tr("Array-Tag „{0}“ ist leer oder ungültig (ohne Index angeben).").format(block.address)
        return super().check_block(block)

    def check_library(self):
        from plc_treiber.clx_io import get_lib
        get_lib()
        return True

    def create_reader(self, plc, variables):
        from plc_treiber.clx_io import TagReader
        return TagReader(plc, variables)

    def browse(self, parent, ctx):
        from plc_treiber.clx_browser import TagBrowser
        dlg = TagBrowser(parent, ctx.plc, set(ctx.existing), ctx.target_labels, ctx.default_target)
        if not dlg.exec():
            return None
        res = BrowseResult(target_index=dlg.target_index)
        res.variables = [(path, path, dtype) for path, dtype in dlg.result_tags]
        res.blocks = [(path.split(".")[-1], path, start, count, dtype) for path, dtype, start, count in dlg.result_blocks]
        return res


DRIVER = ClxDriver()
