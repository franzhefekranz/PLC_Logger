# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Gemeinsame Vorbereitung der Tests: Programmdateien aus src/, eigener Datenordner, Qt ohne Bildschirm,
keine blockierenden Dialoge (Meldungen werden in qt_log gesammelt, Dateidialoge liefern vorgegebene Pfade)."""
import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PLC_BASE_DIR"] = tempfile.mkdtemp(prefix="plc_test_")       # Datenordner: nicht der Projektordner


def pytest_configure(config):
    config.addinivalue_line("markers", "gui: Test mit Qt-Oberfläche (PySide6, ohne Bildschirm)")


def pytest_collection_modifyitems(config, items):
    """GUI-Tests überspringen, wenn PySide6 fehlt (z. B. in einer Umgebung nur für die Logik)."""
    try:
        import PySide6  # noqa: F401
    except ImportError:
        skip = pytest.mark.skip(reason="PySide6 nicht installiert")
        for item in items:
            if "gui" in item.keywords:
                item.add_marker(skip)


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(["test"])
    yield app


class QtLog:
    """Ersatz für modale Dialoge: Meldungen werden gesammelt, Dateidialoge geben ``file`` zurück."""

    def __init__(self):
        self.messages = []
        self.file = ""
        self.files = []
        self.text = ("", False)
        self.opened = []

    def last(self):
        return self.messages[-1] if self.messages else None


@pytest.fixture
def qt_log(qapp, monkeypatch):
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMenu, QMessageBox
    log = QtLog()

    def msg(kind):
        def f(parent, title, text, *a, **k):
            log.messages.append((kind, title, text))
            return QMessageBox.StandardButton.Discard if kind == "question" else QMessageBox.StandardButton.Ok
        return staticmethod(f)
    for kind in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(QMessageBox, kind, msg(kind))
    monkeypatch.setattr(QMessageBox, "exec", lambda self: log.messages.append(("box", self.windowTitle(), self.text())) or 0)
    monkeypatch.setattr(QDialog, "exec", lambda self: 0)
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **k: None)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (log.file, "")))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (log.file, "")))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: (log.files, "")))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: log.file))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: log.text))

    def get_item(parent, title, label, items, current=0, editable=True, *a, **k):
        items = list(items)
        return (items[current] if items else "", bool(items))
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(get_item))
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: log.opened.append(url.toString()) or True))
    return log


def wait(ms):
    """Qt-Ereignisse verarbeiten (Timer, Signale) für ms Millisekunden."""
    from PySide6.QtTest import QTest
    QTest.qWait(ms)


@pytest.fixture
def demo_config(tmp_path):
    """Konfiguration mit den Demo-Diagrammen, einer Steuerung und freiem Webserver-Port."""
    import socket
    from plc_common import Plc, default_connection, save_config
    from plc_recorder import demo_config as demo
    charts, variables = demo()
    for k, v in enumerate(variables):                        # Adressen, damit die Konfiguration gültig ist
        if not v.formula:
            v.address = f"DB1.DBX100.{k % 8}" if v.dtype == "BOOL" else f"DB1.DBD{4 * k}"
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    conn = default_connection()
    conn.update(csv_ordner=str(tmp_path), projekt="Testanlage", web_port=port, web_host="127.0.0.1")
    path = tmp_path / "test.json"
    save_config(conn, charts, variables, str(path), plcs=[Plc(name="SPS 1")])
    return str(path)
