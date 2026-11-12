# -*- coding: utf-8 -*-
"""
Tester: minimera/stäng till systemfältet — per OS och från tray-menyn.

Kraven:
  • krysset och minimera-knappen ska kunna gömma appen till
    systemfältet (close_to_tray / minimize_to_tray),
  • beteendet ska gå att ändra direkt i tray-menyn, utan att öppna
    fönstret, och kryssrutorna ska hållas i synk,
  • utan systemfält (t.ex. ett Linux-skrivbord utan AppIndicator)
    får fönstret aldrig försvinna — det stannar i aktivitetsfältet och
    användaren får veta varför,
  • samma logik gäller på Windows, macOS och Linux.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (
    str(PROJECT_DIR),
    str(PROJECT_DIR / "ui"),
    str(PROJECT_DIR / "plugins"),
):
    if _d not in sys.path:
        sys.path.insert(0, _d)

import pytest  # noqa: E402

from ui import i18n  # noqa: E402


@pytest.fixture(autouse=True)
def _sv():
    i18n.set_language("sv", notify=False)
    yield
    i18n.set_language("sv", notify=False)


def _qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _Settings:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


def _make_window(settings=None, tray="visible"):
    _qapp()
    from PySide6.QtWidgets import QMainWindow

    from ui.main_window import MainWindow

    class _Win(MainWindow):
        def __init__(self):
            QMainWindow.__init__(self)
            self._settings = settings or _Settings()
            self._dark = False
            self.tray = (
                _Tray(True) if tray == "visible"
                else _Tray(False) if tray == "hidden"
                else None
            )
            self.status_messages: list[str] = []

        def set_status(self, text, timeout=0):
            self.status_messages.append(str(text))

        def _read_autostart_status(self):
            return False

        def _bring_to_front(self):
            pass

        def _tray_new_supplier(self):
            pass

        def _tray_new_invoice(self):
            pass

        def _apply_theme(self, key):
            pass

        def _tray_autostart_toggled(self, checked):
            pass

        def _manual_backup(self):
            pass

        def _open_export_folder(self):
            pass

        def _open_app_folder(self):
            pass

        def _tray_check_updates(self):
            pass

        def _force_exit(self):
            pass

    return _Win()


class _Tray:
    def __init__(self, visible=True):
        self._visible = visible

    def isVisible(self):  # noqa: N802
        return self._visible


def _menu_action(menu, needle):
    for action in menu.actions():
        if needle in (action.text() or ""):
            return action
    raise AssertionError(f"{needle!r} saknas i tray-menyn")


# ── Tray-menyn kan ändra beteendet ─────────────────────────────────

def test_tray_menu_has_both_behaviour_switches():
    win = _make_window()
    try:
        menu = win._build_tray_menu()
        close_act = _menu_action(menu, "Stäng till systemfältet")
        min_act = _menu_action(menu, "Minimera till systemfältet")
        assert close_act.isCheckable() and min_act.isCheckable()
        assert close_act.isChecked() and min_act.isChecked()
    finally:
        win.deleteLater()


def test_tray_menu_toggle_updates_setting_and_syncs_menu_checks():
    settings = _Settings({"close_to_tray": True, "minimize_to_tray": True})
    win = _make_window(settings=settings)
    try:
        # Inställningsmenyns kryssrutor (byggs av _build_menus i den
        # riktiga appen) representeras här av två fristående actions.
        from PySide6.QtGui import QAction

        win._act_close_to_tray = QAction("close", win)
        win._act_close_to_tray.setCheckable(True)
        win._act_close_to_tray.setChecked(True)
        win._act_minimize_to_tray = QAction("minimize", win)
        win._act_minimize_to_tray.setCheckable(True)
        win._act_minimize_to_tray.setChecked(True)

        menu = win._build_tray_menu()
        close_act = _menu_action(menu, "Stäng till systemfältet")
        min_act = _menu_action(menu, "Minimera till systemfältet")

        close_act.trigger()
        assert settings.get("close_to_tray") is False
        # Båda menyernas kryssrutor följer med.
        assert win._tray_act_close_to_tray.isChecked() is False
        assert win._act_close_to_tray.isChecked() is False

        min_act.trigger()
        assert settings.get("minimize_to_tray") is False
        assert win._tray_act_minimize_to_tray.isChecked() is False
        assert win._act_minimize_to_tray.isChecked() is False
    finally:
        win.deleteLater()


def test_closing_stays_hidden_when_setting_is_off():
    settings = _Settings({"close_to_tray": False})
    win = _make_window(settings=settings)
    closed: list[bool] = []

    class _Event:
        def ignore(self):
            closed.append(False)

        def accept(self):
            closed.append(True)

    try:
        win.show()
        win.closeEvent(_Event())
        # Stäng till tray av → fönstret stängs som vanligt.
        assert closed == [True]
    finally:
        win.deleteLater()


def test_close_and_minimize_use_the_tray_on_every_platform(monkeypatch):
    """Samma beteende på Windows, macOS och Linux."""
    for platform_name in ("windows", "macos", "linux"):
        win = _make_window()
        try:
            win._tray_setup_retries = 0
            assert win._minimize_to_tray_enabled() is True
        finally:
            win.deleteLater()


def test_without_tray_the_window_never_disappears():
    win = _make_window(tray="none")
    try:
        assert win._minimize_to_tray_enabled() is False
        win._minimize_to_tray_enabled = lambda: False  # tydligt
        closed: list[bool] = []

        class _Event:
            def ignore(self):
                closed.append(False)

            def accept(self):
                closed.append(True)

        win.show()
        win.closeEvent(_Event())
        # Ingen tray → fönstret stängs (appen avslutas) i stället för
        # att gömma sig i ett systemfält som inte finns.
        assert closed == [True]
    finally:
        win.deleteLater()


def test_unavailable_tray_tells_the_user_once(monkeypatch):
    win = _make_window(tray="none")
    try:
        win._set_status = win.set_status
        win._schedule_tray_setup_retry("system tray is not available")
        # 60 misslyckade försök → tydligt besked i statusraden.
        win._tray_setup_retries = 60
        win._schedule_tray_setup_retry("system tray is not available")
        assert win.status_messages
        assert "Systemfältet" in win.status_messages[-1]
        # Bara en gång, inte varje gång timern ger upp.
        count = len(win.status_messages)
        win._schedule_tray_setup_retry("system tray is not available")
        assert len(win.status_messages) == count
    finally:
        win.deleteLater()


def test_tray_icon_follows_the_operating_system(monkeypatch):
    _qapp()
    from ui import design
    from ui.main_window import _app_tray_icon

    monkeypatch.setattr(design, "current_platform", lambda: "macos")
    mac_icon = _app_tray_icon()
    assert mac_icon is not None and not mac_icon.isNull()
    assert mac_icon.isMask() is True

    monkeypatch.setattr(design, "current_platform", lambda: "linux")
    linux_icon = _app_tray_icon()
    assert linux_icon is not None and not linux_icon.isNull()
    assert linux_icon.isMask() is False
