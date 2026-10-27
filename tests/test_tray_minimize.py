# -*- coding: utf-8 -*-
"""
Tester: minimera-knappen gömmer appen till systemfältet (tray).

Användarens krav (2026-10-27): appen ska stängas till systray
OCH minimeras dit — ikonen i aktivitetsfältet ska bara synas
när appen är öppen. Krysset gömde redan till tray
(close_to_tray); nu gör även minimeringen det.

MainWindow instansieras aldrig fullt i tester (samma mönster
som test_tray_update.py) — fönstret byggs som ren QMainWindow
med MainWindows händelsemetoder, fejkad inställningslagring
och fejkad tray-ikon.
"""
from __future__ import annotations

import os
import sys
import time
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


def _pump() -> None:
    """Låt uppskjutna (singleShot 0) anrop hinna köra."""
    try:
        from PySide6.QtTest import QTest
        QTest.qWait(80)
        return
    except Exception:
        pass
    app = QApplication.instance()
    for _ in range(20):
        if app is not None:
            app.processEvents()
        time.sleep(0.01)


class _Settings:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


class _Tray:
    def __init__(self, visible=True):
        self._visible = visible

    def isVisible(self):  # noqa: N802
        return self._visible


def _make_window(settings=None, tray="visible"):
    """MainWindow-logik på ett naket QMainWindow-skal."""
    _qapp()
    from PySide6.QtWidgets import QMainWindow

    from ui.main_window import MainWindow

    class _Win(MainWindow):
        def __init__(self):
            QMainWindow.__init__(self)
            self._settings = settings or _Settings()
            self.tray = (
                _Tray(True) if tray == "visible"
                else _Tray(False) if tray == "hidden"
                else None
            )
            self._min = False
            self.status_messages: list[str] = []

        def isMinimized(self):  # noqa: N802
            return self._min

        def set_status(self, text, timeout=0):
            self.status_messages.append(str(text))

    return _Win()


def _state_change_event():
    from PySide6.QtCore import QEvent
    return QEvent(QEvent.Type.WindowStateChange)


# ── Aktiveringslogiken ─────────────────────────────────────────────

def test_minimize_to_tray_enabled_by_default():
    win = _make_window()
    try:
        assert win._minimize_to_tray_enabled() is True
    finally:
        win.deleteLater()


def test_minimize_to_tray_respects_setting_and_tray():
    win = _make_window(settings=_Settings({"minimize_to_tray": False}))
    try:
        assert win._minimize_to_tray_enabled() is False
    finally:
        win.deleteLater()

    win = _make_window(tray="hidden")
    try:
        # Ingen synlig tray-ikon → fönstret får aldrig försvinna.
        assert win._minimize_to_tray_enabled() is False
    finally:
        win.deleteLater()

    win = _make_window(tray="none")
    try:
        assert win._minimize_to_tray_enabled() is False
    finally:
        win.deleteLater()


# ── Minimering gömmer fönstret ─────────────────────────────────────

def test_minimize_hides_window_to_tray():
    win = _make_window()
    try:
        win.show()
        _pump()
        assert win.isVisible()
        win._min = True
        win.changeEvent(_state_change_event())
        _pump()
        # Gömt till tray — ingen ikon i aktivitetsfältet.
        assert not win.isVisible()
    finally:
        win.deleteLater()


def test_minimize_stays_normal_when_setting_off():
    win = _make_window(settings=_Settings({"minimize_to_tray": False}))
    try:
        win.show()
        _pump()
        win._min = True
        win.changeEvent(_state_change_event())
        _pump()
        assert win.isVisible()
    finally:
        win.deleteLater()


def test_other_change_events_do_not_hide():
    from PySide6.QtCore import QEvent

    win = _make_window()
    try:
        win.show()
        _pump()
        win._min = True
        win.changeEvent(QEvent(QEvent.Type.LayoutRequest))
        _pump()
        assert win.isVisible()
    finally:
        win.deleteLater()


def test_hide_minimized_noop_when_restored():
    """Hann fönstret återställas före det uppskjutna anropet
    göms det inte."""
    win = _make_window()
    try:
        win.show()
        _pump()
        win._min = False
        win._hide_minimized_to_tray()
        assert win.isVisible()
        win._min = True
        win._hide_minimized_to_tray()
        assert not win.isVisible()
    finally:
        win.deleteLater()


# ── Inställningsväxeln ─────────────────────────────────────────────

def test_toggle_minimize_to_tray_persists():
    settings = _Settings()
    win = _make_window(settings=settings)
    try:
        win._toggle_minimize_to_tray(False)
        assert settings.data["minimize_to_tray"] is False
        assert win._minimize_to_tray_enabled() is False
        win._toggle_minimize_to_tray(True)
        assert settings.data["minimize_to_tray"] is True
        assert win._minimize_to_tray_enabled() is True
        assert win.status_messages  # statusraden bekräftar valet
    finally:
        win.deleteLater()
