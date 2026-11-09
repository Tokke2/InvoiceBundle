# -*- coding: utf-8 -*-
"""Startläge: varje normal start minimeras till systemfältet."""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "ui"),
           str(PROJECT_DIR / "plugins")):
    if _d not in sys.path:
        sys.path.insert(0, _d)


class _Tray:
    def __init__(self):
        self.messages = []

    def showMessage(self, *args):  # noqa: N802
        self.messages.append(args)

    def isVisible(self):  # noqa: N802
        return True


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
        # False deliberately simulates a legacy user settings.json.
        self.settings = {"start_minimized": start_minimized}


def _install_qt_stub(monkeypatch, tray_available=True):
    class _MessageIcon:
        Information = 1

    class _SystemTrayIcon:
        MessageIcon = _MessageIcon

        @staticmethod
        def isSystemTrayAvailable():  # noqa: N802
            return tray_available

    package = types.ModuleType("PySide6")
    package.__path__ = []
    widgets = types.ModuleType("PySide6.QtWidgets")
    widgets.QSystemTrayIcon = _SystemTrayIcon
    monkeypatch.setitem(sys.modules, "PySide6", package)
    monkeypatch.setitem(sys.modules, "PySide6.QtWidgets", widgets)


def _run(monkeypatch, window, core, autostart, tray_available=True):
    _install_qt_stub(monkeypatch, tray_available)
    import main as app_main

    # Timers are irrelevant to this unit test; exercise the startup branch.
    monkeypatch.setattr(app_main, "_verify_window_hidden", lambda _w: None)
    monkeypatch.setattr(app_main, "_verify_window_visible", lambda _w: None)
    app_main._start_minimized_or_show(window, core, autostart)


def test_manual_start_is_minimized_even_if_legacy_setting_is_false(monkeypatch):
    win = _Window()
    _run(monkeypatch, win, _Core(False), autostart=False)
    assert "hide" in win.calls
    assert "show" not in win.calls
    assert win.tray.messages


def test_autostart_is_minimized_with_tray(monkeypatch):
    win = _Window()
    _run(monkeypatch, win, _Core(True), autostart=True)
    assert "hide" in win.calls
    assert "show" not in win.calls
    assert win.tray.messages


def test_no_tray_keeps_window_visible(monkeypatch):
    win = _Window()
    _run(monkeypatch, win, _Core(False), autostart=False,
         tray_available=False)
    assert "show" in win.calls
    assert "hide" not in win.calls
    assert "activate" in win.calls


def test_window_without_tray_object_stays_visible(monkeypatch):
    win = _Window(tray=False)
    _run(monkeypatch, win, _Core(True), autostart=True)
    assert "show" in win.calls
    assert "hide" not in win.calls


def test_invisible_tray_keeps_window_visible(monkeypatch):
    win = _Window()
    win.tray.isVisible = lambda: False
    _run(monkeypatch, win, _Core(True), autostart=True)
    assert "show" in win.calls
    assert "hide" not in win.calls


def test_hidden_start_guard_does_not_hide_after_explicit_focus(monkeypatch):
    _install_qt_stub(monkeypatch)
    core = types.ModuleType("PySide6.QtCore")

    class _Timer:
        @staticmethod
        def singleShot(_delay, callback):  # noqa: N802
            callback()

    core.QTimer = _Timer
    monkeypatch.setitem(sys.modules, "PySide6.QtCore", core)
    import main as app_main
    monkeypatch.setattr(app_main, "_get_alog", lambda: None)

    class _FocusedWindow:
        _startup_hide_guard_active = False

        def isVisible(self):  # noqa: N802
            return True

        def hide(self):
            raise AssertionError("deliberately focused window was hidden")

    app_main._verify_window_hidden(_FocusedWindow())


def test_autostart_command_carries_minimized_flag():
    import app as app_core

    manager = app_core.AutostartManager("auto")
    assert "--minimized" in manager._app_command()
    assert manager.starts_minimized() is True


def test_main_keeps_autostart_flag_for_compatibility():
    import main as app_main

    assert app_main.AUTOSTART_LAUNCH is ("--minimized" in sys.argv)


def test_settings_cannot_disable_always_minimized_start():
    main_window = (PROJECT_DIR / "ui" / "main_window.py").read_text(
        encoding="utf-8"
    )
    i18n = (PROJECT_DIR / "ui" / "i18n.py").read_text(encoding="utf-8")
    assert "_act_start_minimized" not in main_window
    assert "_toggle_start_minimized" not in main_window
    assert '"menu.start_minimized"' not in i18n
    assert "Every normal launch" in (PROJECT_DIR / "README.md").read_text(
        encoding="utf-8"
    )
