# -*- coding: utf-8 -*-
"""
Tester: fönstret ska ALLTID gå att få fram via tray-ikonen.

Bakgrund (verklig bugg): användaren autostartar appen gömd i
systemfältet och dubbelklickar tray-ikonen — loggen visar
TRAY_CLICK + WINDOW_ACTIVATE men fönstret syns inte. Orsak:
fönstret låg utanför alla anslutna skärmar (extern skärm
bortkopplad), Qt ansåg det "synligt", så _bring_to_front()
gjorde varken show eller flytt — bara raise/activate mot en
fantomskärm.

Fixen: ensure_window_on_screen() i ui/main_window.py upptäcker
läget och centrerar fönstret på primärskärmen. Den anropas från
_bring_to_front() (varje tray-klick) och från startup-vakten.
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


def _primary_avail():
    from PySide6.QtWidgets import QApplication
    return QApplication.primaryScreen().availableGeometry()


def _window(off_screen: bool):
    """Ett vanligt fönster, ev. placerat långt utanför skärmen."""
    from PySide6.QtWidgets import QWidget
    w = QWidget()
    w.resize(800, 600)
    avail = _primary_avail()
    if off_screen:
        # Långt till vänster om alla skärmar (fantomskärmsläge)
        w.move(avail.x() - 10000, avail.y() - 10000)
    else:
        w.move(avail.x() + 20, avail.y() + 20)
    w.show()
    return w


def test_offscreen_window_is_moved_back():
    _qapp()
    from ui.main_window import ensure_window_on_screen
    w = _window(off_screen=True)
    moved = ensure_window_on_screen(w)
    assert moved is True
    avail = _primary_avail()
    overlap = avail.intersected(w.frameGeometry())
    # Efter flytten syns minst titelradsbredd enligt vaktens krav
    assert overlap.width() >= 100 and overlap.height() >= 40
    # Centrerat-ish: fönstrets mitt ligger på primärskärmen
    assert avail.contains(w.frameGeometry().center())
    w.close()


def test_onscreen_window_is_left_alone():
    _qapp()
    from ui.main_window import ensure_window_on_screen
    w = _window(off_screen=False)
    before = (w.x(), w.y(), w.width(), w.height())
    moved = ensure_window_on_screen(w)
    assert moved is False
    assert (w.x(), w.y(), w.width(), w.height()) == before
    w.close()


def test_partially_visible_window_is_left_alone():
    """Lite utanför kanten är okej — först helt borta åtgärdas."""
    _qapp()
    from ui.main_window import ensure_window_on_screen
    from PySide6.QtWidgets import QWidget
    w = QWidget()
    w.resize(800, 600)
    avail = _primary_avail()
    # Övre vänstra hörnet utanför, men >100x40 px syns fortfarande
    w.move(avail.x() - 400, avail.y() - 300)
    w.show()
    assert ensure_window_on_screen(w) is False
    w.close()


def test_hidden_window_is_not_disturbed_by_guard():
    """Gömd autostart ska förbli gömd — vakten flyttar bara läge,
    den visar aldrig fönstret på egen hand."""
    _qapp()
    from ui.main_window import ensure_window_on_screen
    w = _window(off_screen=True)
    w.hide()
    assert not w.isVisible()
    ensure_window_on_screen(w)  # får aldrig krascha eller visa
    assert not w.isVisible()
    w.close()
