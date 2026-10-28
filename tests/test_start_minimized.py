# -*- coding: utf-8 -*-
"""
Tester: start med operativsystemet, minimerad vid start.

Användarens krav (2026-10-28): appen ska starta med OS:et och
vara minimerad vid start — autostart (--minimized) + inställningen
start_minimized + tray ⇒ fönstret visas aldrig, appen ligger i
systemfältet. Manuell start visar alltid fönstret, och utan tray
eller med inställningen av failar den aldrig bort appen.
Inställningen har fått en egen kryssruta i Inställningar-menyn.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "ui"),
           str(PROJECT_DIR / "plugins")):
    if _d not in sys.path:
        sys.path.insert(0, _d)


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class _Tray:
    def __init__(self):
        self.messages = []

    def showMessage(self, *args):  # noqa: N802
        self.messages.append(args)


class _Window:
    def __init__(self, tray=True):
        self.calls: list[str] = []
        if tray:
            self.tray = _Tray()

    def hide(self):
        self.calls.append("hide")

    def show(self):
        self.calls.append("show")

    def raise_(self):
        self.calls.append("raise")

    def activateWindow(self):  # noqa: N802
        self.calls.append("activate")


class _Core:
    def __init__(self, start_minimized=True):
        self.settings = {"start_minimized": start_minimized}


def _run(monkeypatch, window, core, autostart, tray_available=True):
    import main as app_main
    from PySide6.QtWidgets import QSystemTrayIcon

    monkeypatch.setattr(
        QSystemTrayIcon, "isSystemTrayAvailable",
        staticmethod(lambda: tray_available),
    )
    # Verifieringstimern (700 ms) ska inte störa testerna.
    monkeypatch.setattr(app_main, "_verify_window_hidden",
                        lambda w: None)
    monkeypatch.setattr(app_main, "_verify_window_visible",
                        lambda w: None)
    app_main._start_minimized_or_show(window, core, autostart)


def test_autostart_with_setting_and_tray_starts_hidden(monkeypatch):
    _qapp()
    win = _Window()
    _run(monkeypatch, win, _Core(True), autostart=True)
    assert "hide" in win.calls
    assert "show" not in win.calls
    assert win.tray.messages  # ballongtips: appen körs i tray


def test_manual_start_always_shows_window(monkeypatch):
    _qapp()
    win = _Window()
    _run(monkeypatch, win, _Core(True), autostart=False)
    assert "show" in win.calls
    assert "hide" not in win.calls


def test_setting_off_shows_window_even_at_autostart(monkeypatch):
    _qapp()
    win = _Window()
    _run(monkeypatch, win, _Core(False), autostart=True)
    assert "show" in win.calls
    assert "hide" not in win.calls


def test_no_tray_shows_window_even_at_autostart(monkeypatch):
    _qapp()
    win = _Window()
    _run(
        monkeypatch, win, _Core(True), autostart=True,
        tray_available=False,
    )
    assert "show" in win.calls
    assert "hide" not in win.calls


def test_window_without_tray_object_shows(monkeypatch):
    _qapp()
    win = _Window(tray=False)
    assert not hasattr(win, "tray")
    _run(monkeypatch, win, _Core(True), autostart=True)
    assert "show" in win.calls


def test_autostart_command_always_carries_minimized_flag():
    """OS-posten för autostart ska alltid passera --minimized —
    det är den flaggan som triggar gömd start."""
    import importlib

    app_core = importlib.import_module("app")
    mgr = app_core.AutostartManager("auto")
    assert "--minimized" in mgr._app_command()
    assert mgr.starts_minimized() is True


def test_main_reads_autostart_launch_flag():
    import main as app_main

    assert app_main.AUTOSTART_LAUNCH is ("--minimized" in sys.argv)


def test_settings_menu_has_start_minimized_toggle():
    """Kryssrutan finns i Inställningar och sparar inställningen."""
    _qapp()
    from ui.main_window import MainWindow

    captured: dict = {}

    class FakeApp:
        settings = None

        def get_suppliers(self):
            return []

    # MainWindows konstruktion är tung; bygg objektet utan __init__
    # och pröva bara togglen mot ett fejkat settings-objekt.
    win = MainWindow.__new__(MainWindow)

    class FakeSettings:
        def get(self, key, default=None):
            return {"start_minimized": True}.get(key, default)

        def set(self, key, value):
            captured[key] = value

    win._settings = FakeSettings()
    win.set_status = lambda *a, **k: None
    win._toggle_start_minimized(False)
    assert captured["start_minimized"] is False
    win._toggle_start_minimized(True)
    assert captured["start_minimized"] is True
    # Menyposten finns med i källan och läses vid menyskapandet.
    src = (
        Path(__file__).resolve().parent.parent
        / "ui" / "main_window.py"
    ).read_text(encoding="utf-8")
    assert "_act_start_minimized" in src
    assert 'self._settings.get("start_minimized", True)' in src
