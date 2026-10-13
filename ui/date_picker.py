# -*- coding: utf-8 -*-
"""
Fakturabunten — bättre datumväljare (kalender-drop)
===================================================
Qt:s inbyggda kalender-drop (QDateEdit + calendarPopup) är liten,
engelsk och svårläst. Den här modulen gör den ordentlig:

• Stor kalender (min 340×300) med rutnät och ISO-veckonummer
• Måndag som första veckodag, svenska/engelska namn (följer appens språk)
• Helger i dämpad röd ton, DAGENS datum markerat med guld
• Snabbval: Idag · Imorgon · +7 · +14 · +30 dagar · Månadsslut
• Levande förhandsvisning: "fredag 2 oktober 2026 · om 12 dagar"
  (eller varning om datumet redan passerat)

Används vid PDF-exportens betalningsdatum (huvuddialogen i
plugins/pdf_export_helpers.py + fallbacken i invoices_view.py)
och i alla datumfält som skapas via invoices_helpers.make_date_edit().
"""

from __future__ import annotations

import datetime
import logging

from PySide6.QtCore import QDate, QLocale, Qt
from PySide6.QtGui import QColor, QFont, QTextCharFormat
from PySide6.QtWidgets import (
    QCalendarWidget, QDateEdit, QHBoxLayout, QLabel, QPushButton,
    QWidget,
)

log = logging.getLogger("DatePicker")

try:
    from ui.i18n import language as _app_language, tr
except Exception:  # pragma: no cover - fristående körning
    try:
        from i18n import language as _app_language, tr  # type: ignore
    except Exception:
        def _app_language() -> str:  # type: ignore
            return "sv"

        def tr(key: str, **_fmt: object) -> str:  # type: ignore
            return key

ACCENT = "#2f6fb4"
GOLD = "#e8b030"
WEEKEND_FG = "#d4736a"

_CALENDAR_QSS = f"""
QCalendarWidget {{
    font-size: 13px;
    border: 1px solid {ACCENT};
    border-radius: 10px;
    background: palette(base);
}}
QCalendarWidget QToolButton {{
    background: {ACCENT};
    color: #ffffff;
    font-weight: 700;
    font-size: 13px;
    border: none;
    border-radius: 6px;
    padding: 6px 10px;
    margin: 2px;
    min-height: 26px;
}}
QCalendarWidget QToolButton:hover {{ background: #3d8bfd; }}
QCalendarWidget QToolButton::menu-indicator {{ width: 0; height: 0; }}
QCalendarWidget QSpinBox {{
    background: {ACCENT};
    color: #ffffff;
    font-weight: 700;
    border: none;
    selection-background-color: #3d8bfd;
}}
QCalendarWidget QAbstractItemView {{
    font-size: 13px;
    font-weight: 600;
    outline: none;
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}
QCalendarWidget QAbstractItemView:enabled:hover {{
    background: rgba(61, 139, 253, 0.25);
}}
"""


def calendar_locale() -> QLocale:
    """Svensk (mån–sön) eller engelsk kalender efter appens språk."""
    if _app_language() == "en":
        return QLocale(QLocale.Language.English, QLocale.Country.UnitedKingdom)
    return QLocale(QLocale.Language.Swedish, QLocale.Country.Sweden)


def polish_calendar(cal: QCalendarWidget) -> QCalendarWidget:
    """
    Gör en QCalendarWidget stor, läsbar och lokaliserad.

    • Måndag först, ISO-veckonummer i kanten, rutnät
    • Helgdagar dämpat röda, dagens datum guldfärgat och fetstilt
    • Accentfärgad navigationsrad (månad/år + pilar)
    """
    cal.setLocale(calendar_locale())
    cal.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
    cal.setGridVisible(True)
    cal.setVerticalHeaderFormat(
        QCalendarWidget.VerticalHeaderFormat.ISOWeekNumbers
    )
    cal.setHorizontalHeaderFormat(
        QCalendarWidget.HorizontalHeaderFormat.ShortDayNames
    )
    cal.setNavigationBarVisible(True)
    cal.setMinimumSize(340, 300)

    # Helger (lör/sön) i dämpad röd ton
    weekend = QTextCharFormat()
    weekend.setForeground(QColor(WEEKEND_FG))
    cal.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, weekend)
    cal.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, weekend)

    # Dagens datum: guld + fetstil (så man alltid hittar hem)
    today_fmt = QTextCharFormat()
    today_fmt.setBackground(QColor(GOLD))
    today_fmt.setForeground(QColor("#231a00"))
    f = QFont()
    f.setBold(True)
    today_fmt.setFont(f)
    cal.setDateTextFormat(QDate.currentDate(), today_fmt)

    cal.setStyleSheet(_CALENDAR_QSS)
    return cal


def polish_date_edit(edit: QDateEdit) -> QDateEdit:
    """Uppgraderar en befintlig QDateEdit med den polerade kalendern."""
    edit.setCalendarPopup(True)
    cal = QCalendarWidget(edit)
    polish_calendar(cal)
    edit.setCalendarWidget(cal)
    return edit


class NiceDateEdit(QDateEdit):
    """QDateEdit (åååå-mm-dd) med den stora, lokaliserade kalendern."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDisplayFormat("yyyy-MM-dd")
        self.setMinimumHeight(38)
        polish_date_edit(self)


def human_date_text(qdate: QDate, today: QDate | None = None) -> str:
    """
    Läsbar datumtext + relativ tid:
    "fredag 2 oktober 2026 · om 12 dagar" / "… · för 3 dagar sedan ⚠"
    """
    if not qdate.isValid():
        return ""
    today = today or QDate.currentDate()
    long_form = calendar_locale().toString(
        qdate, QLocale.FormatType.LongFormat
    )
    days = today.daysTo(qdate)
    if days == 0:
        rel = tr("date.rel_today")
    elif days == 1:
        rel = tr("date.rel_tomorrow")
    elif days > 1:
        rel = tr("date.rel_in_days", n=days)
    elif days == -1:
        rel = tr("date.rel_yesterday")
    else:
        rel = tr("date.rel_days_ago", n=abs(days))
    suffix = "  ⚠" if days < 0 else ""
    return f"{long_form} · {rel}{suffix}"


def month_end(qdate: QDate) -> QDate:
    """Sista dagen i samma månad som ``qdate``."""
    return QDate(qdate.year(), qdate.month(), 1).addMonths(1).addDays(-1)


def quick_pick_row(edit: QDateEdit, parent: QWidget | None = None) -> QWidget:
    """
    Rad med snabbvalschips som sätter datumfältets datum:
    Idag · Imorgon · +7 · +14 · +30 · Månadsslut.
    """
    wrap = QWidget(parent)
    row = QHBoxLayout(wrap)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)

    specs: list[tuple[str, object]] = [
        (tr("date.today_btn"), lambda t: t),
        (tr("date.tomorrow_btn"), lambda t: t.addDays(1)),
        ("+7", lambda t: t.addDays(7)),
        ("+14", lambda t: t.addDays(14)),
        ("+30", lambda t: t.addDays(30)),
        (tr("date.month_end_btn"), month_end),
    ]
    for label, fn in specs:
        btn = QPushButton(label, wrap)
        btn.setMinimumHeight(28)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(label)
        btn.clicked.connect(
            lambda checked=False, f=fn: edit.setDate(f(QDate.currentDate()))
        )
        row.addWidget(btn)
    row.addStretch(1)
    return wrap


def date_preview_label(edit: QDateEdit, parent: QWidget | None = None) -> QLabel:
    """
    Etikett som live visar valt datum i läsbar form och uppdateras
    automatiskt när fältet ändras.
    """
    lbl = QLabel(parent)
    lbl.setWordWrap(True)
    lbl.setStyleSheet("background:transparent; font-weight:700;")

    def _update(qd: QDate) -> None:
        lbl.setText("📅  " + human_date_text(qd))
        past = QDate.currentDate().daysTo(qd) < 0
        lbl.setStyleSheet(
            "background:transparent; font-weight:700;"
            + (" color:#d4736a;" if past else "")
        )

    edit.dateChanged.connect(_update)
    _update(edit.date())
    return lbl


def suggested_payment_date(
    session_due_date: str = "", fallback_days: int = 0
) -> QDate:
    """Standarddatum: sessionens förfallodatum, annars idag (+offset)."""
    if session_due_date:
        try:
            d = datetime.date.fromisoformat(str(session_due_date).strip())
            return QDate(d.year, d.month, d.day)
        except (TypeError, ValueError):
            pass
    return QDate.currentDate().addDays(fallback_days)
