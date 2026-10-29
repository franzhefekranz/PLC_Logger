# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Treiber „tia“: Siemens S7-1200/S7-1500 symbolisch über S7CommPlus (Bibliothek s7commplus).

S7CommPlus ist das Protokoll von TIA Portal und Siemens-HMIs: Variablen werden über ihren symbolischen Namen
gelesen – auch in Datenbausteinen mit „Optimiertem Bausteinzugriff“, ohne PUT/GET. Die Variablenliste liest der
Auswahldialog direkt aus der Steuerung. Adressen:

    Anlage_DB.Motor[2].Drehzahl     Mess_DB.Temp     MArea.Start_Merker     IArea.Taster_1     QArea.Lampe

Blöcke: Array ohne Index + erster Index (wie in TIA, z. B. 1 bei Array[1..100]) + Anzahl.
Ringpuffer (zyklussynchron): symbolischer Name des Puffers (z. B. ``PLC_Ringpuffer`` oder ``Cycl_Rec_DB``, auch in
optimierten Bausteinen) oder absolute Adresse des Zählers in einem nicht optimierten DB (``DB100.DBX0.0``).
"""
from plc_i18n import tr
from plc_treiber.base import BrowseResult, Driver, Param
from plc_treiber.ringbuffer import RING_TYPES
from plc_treiber.tia_common import BLOCK_TYPES, ROLES, TLS_MODES, TYPES, check_tag_name


class TiaDriver(Driver):
    """Treiber „tia“ (siehe Modulbeschreibung); gelesen wird mit s7commplus (tia_io.TagReader)."""
    id = "tia"
    name = tr("Siemens S7-1200/1500 (S7CommPlus, symbolisch)")
    description = tr("Symbolischer Zugriff wie TIA Portal, auch optimierte Bausteine; ohne PUT/GET")
    params = [
        Param("ip", tr("IP-Adresse"), "text", "192.168.0.1"),
        Param("port", tr("Port"), "int", 102, minimum=1, maximum=65535,
              tip=tr("ISO-on-TCP-Port der Steuerung (Standard 102)")),
        Param("tls", tr("TLS"), "choice", "auto", choices=list(TLS_MODES.items()),
              tip=tr("Automatisch: TLS verwenden, wenn die Steuerung es anbietet (ab TIA V17 / Firmware mit "
                     "PG/HMI-Kommunikation über TLS); An: nur mit TLS; Aus: ohne TLS")),
        Param("passwort", tr("Passwort"), "password", "",
              tip=tr("Passwort der Zugriffsstufe, falls die CPU lesenden Zugriff schützt. "
                     "Hinweis: Es wird im Klartext in der Konfigurationsdatei gespeichert.")),
        Param("rolle", tr("Rolle"), "choice", "hmi", choices=list(ROLES.items()), advanced=True),
        Param("tags_je_anfrage", tr("Variablen je Anfrage"), "int", 50, minimum=1, maximum=1000, advanced=True,
              tip=tr("Höchstzahl Variablen je Leseanfrage (größere Mengen werden aufgeteilt)")),
    ]
    types = list(TYPES)
    block_types = BLOCK_TYPES
    address_label = tr("Variable in der Steuerung")
    address_hint = tr("Symbolischer Name: Datenbaustein.Variable, z. B. Anlage_DB.Motor[2].Drehzahl; "
                      "Merker/Ein-/Ausgänge: MArea.<Name>, IArea.<Name>, QArea.<Name>")
    block_hint = tr("Array ohne Index, z. B. Mess_DB.Werte oder Anlage_DB.Motor[1].Historie")
    block_uses_index = True
    browse_label = tr("Aus Variablenliste wählen…")
    library = "s7commplus"
    ring_types = list(RING_TYPES)
    ring_hint = tr("Name des Ringpuffers (DB oder Struktur mit Zaehler und Daten), z. B. PLC_Ringpuffer oder "
                   "Cycl_Rec_DB – auch optimiert; oder Adresse des Zählers in einem nicht optimierten DB, z. B. "
                   "DB100.DBX0.0 (schneller bei großen Puffern)")

    def summary(self, plc):
        """„IP:Port, TLS Modus“."""
        p = plc.params
        return f"{p.get('ip', '')}:{p.get('port', 102)}, TLS {tr(TLS_MODES.get(p.get('tls'), p.get('tls', '')))}"

    def check_address(self, address, dtype):
        """Symbolischer Name formal gültig?"""
        if not check_tag_name(address):
            return tr("Ungültiger Variablenname „{0}“").format(address)
        return ""

    def check_ring(self, block):
        """Ringpuffer: symbolischer Name oder absolute Adresse im nicht optimierten Datenbaustein."""
        from plc_treiber.tia_io import ring_is_symbolic
        if ring_is_symbolic(block.address):
            if not check_tag_name(block.address.strip()) or block.address.strip().endswith("]"):
                return tr("Ungültiger Variablenname „{0}“").format(block.address)
            return super().check_ring(block)
        from plc_treiber.s7 import parse_ring
        try:
            parse_ring(block.address)
        except ValueError as e:
            return str(e)
        return super().check_ring(block)

    def check_block(self, block):
        """Blöcke: Array ohne Index."""
        if block.ring:
            return self.check_ring(block)
        if not check_tag_name(block.address) or block.address.endswith("]"):
            return tr("Array „{0}“ ist leer oder ungültig (ohne Index angeben).").format(block.address)
        return super().check_block(block)

    def check_library(self):
        """s7commplus vorhanden (und Python-Version ausreichend)?"""
        from plc_treiber.tia_io import check_library
        return check_library()

    def create_reader(self, plc, variables):
        """Leser für eine Steuerung (tia_io.TagReader)."""
        from plc_treiber.tia_io import TagReader
        return TagReader(plc, variables)

    def browse(self, parent, ctx):
        """Auswahldialog mit der Variablenliste aus der Steuerung; Arrays als Blöcke."""
        from plc_treiber.tia_browser import TagBrowser
        dlg = TagBrowser(parent, ctx.plc, set(ctx.existing), ctx.target_labels, ctx.default_target)
        if not dlg.exec():
            return None
        res = BrowseResult(target_index=dlg.target_index)
        res.variables = [(path, path, dtype) for path, dtype in dlg.result_tags]
        res.blocks = [(path.split(".")[-1], path, start, count, dtype) for path, dtype, start, count in dlg.result_blocks]
        return res


DRIVER = TiaDriver()
