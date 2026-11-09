# -*- coding: utf-8 -*-
"""Tester för den förbättrade datumväljaren (ui/date_picker.py)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "ui")):
    if _d not in sys.path:
        sys.path.insert(0, _d)


def _qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_calendar_is_bigger_and_swedish_by_default():
    _qapp()
    from PySide6.QtCore import Qt
    from ui.date_picker import NiceDateEdit

    edit = NiceDateEdit()
    cal = edit.calendarWidget()
    # Stor, läsbar kalender — inte Qt:s lilla standard-drop
    assert cal.minimumSize().width() >= 340
    assert cal.minimumSize().height() >= 300
    # Måndag först + ISO-veckonummer + rutnät
    assert cal.firstDayOfWeek() == Qt.DayOfWeek.Monday
    assert cal.isGridVisible()
    assert "ISOWeekNumbers" in str(cal.verticalHeaderFormat())


def test_human_date_text_sv_and_en():
    _qapp()
    from PySide6.QtCore import QDate
    from ui import i18n
    from ui.date_picker import human_date_text

    today = QDate(2026, 10, 13)  # tisdag
    i18n.set_language("sv")
    assert "idag" in human_date_text(today, today)
    assert "om 12 dagar" in human_date_text(today.addDays(12), today)
    past = human_date_text(today.addDays(-3), today)
    assert "för 3 dagar sedan" in past and "⚠" in past
    i18n.set_language("en")
    assert "today" in human_date_text(today, today)
    assert "in 5 days" in human_date_text(today.addDays(5), today)
    i18n.set_language("sv")


def test_quick_picks_set_dates():
    _qapp()
    from PySide6.QtCore import QDate
    from PySide6.QtWidgets import QPushButton
    from ui.date_picker import NiceDateEdit, month_end, quick_pick_row

    edit = NiceDateEdit()
    row = quick_pick_row(edit)
    buttons = {b.text(): b for b in row.findChildren(QPushButton)}
    today = QDate.currentDate()
    buttons["+7"].click()
    assert edit.date() == today.addDays(7)
    buttons["+30"].click()
    assert edit.date() == today.addDays(30)
    assert month_end(QDate(2026, 2, 5)) == QDate(2026, 2, 28)
    assert month_end(QDate(2024, 2, 5)) == QDate(2024, 2, 29)  # skottår


def test_preview_label_follows_edit():
    _qapp()
    from PySide6.QtCore import QDate
    from ui.date_picker import NiceDateEdit, date_preview_label

    edit = NiceDateEdit()
    edit.setDate(QDate.currentDate())
    lbl = date_preview_label(edit)
    assert "idag" in lbl.text()
    edit.setDate(QDate.currentDate().addDays(1))
    assert "imorgon" in lbl.text()
