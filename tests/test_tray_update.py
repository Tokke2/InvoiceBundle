# -*- coding: utf-8 -*-
"""
Tray-menyn (högerklick på ikonen i systemfältet) ska kunna
starta uppdateringen: 🔄 Sök ny version finns där och tar
först fram fönstret, sedan öppnas samma uppdateringsdialog
som via Hjälp-menyn.

MainWindow instansieras aldrig i tester — menybygget körs på
en fejk-self som bara erbjuder metoderna menyn kopplar mot.
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


def _tray_menu_with_spy():
    _qapp()
    from PySide6.QtWidgets import QWidget

    from ui.main_window import MainWindow

    called: list[str] = []

    class _Self(QWidget):
        def _bring_to_front(self):
            called.append("front")

        def _tray_new_supplier(self):
            pass

        def _tray_new_invoice(self):
            pass

        def _apply_theme(self, k):
            pass

        def _read_autostart_status(self):
            return False

        def _tray_autostart_toggled(self, c):
            pass

        def _manual_backup(self):
            pass

        def _open_export_folder(self):
            pass

        def _force_exit(self):
            pass

        def _check_updates(self):
            called.append("check")

    fake = _Self()
    # Riktiga handlern, men på fejk-objektet (öppnar ingen dialog)
    fake._tray_check_updates = (
        lambda: MainWindow._tray_check_updates(fake)
    )
    return MainWindow._build_tray_menu(fake), called


def test_tray_menu_has_check_for_updates():
    menu, _called = _tray_menu_with_spy()
    texts = [a.text() for a in menu.actions() if a.text()]
    assert any("Sök ny version" in t for t in texts), texts


def test_tray_update_brings_window_front_then_opens_dialog():
    menu, called = _tray_menu_with_spy()
    act = [
        a for a in menu.actions()
        if "Sök ny version" in (a.text() or "")
    ][0]
    act.trigger()
    # Fönstret fram FÖRST (dialogen behöver synlig förälder),
    # sedan samma uppdateringsflöde som Hjälp-menyn.
    assert called == ["front", "check"]
