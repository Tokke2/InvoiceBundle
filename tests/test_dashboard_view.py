# -*- coding: utf-8 -*-
"""
Tester: Dashboard-fliken (nyckeltal + förfaller snart).

Reglerna ska vara desamma som i Fakturor-fliken: Betald/Makulerad/
Arkiverad räknas inte som obetalt; förfallet = status Förfallen
eller passerat förfallodatum.
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "ui")):
    if _d not in sys.path:
        sys.path.insert(0, _d)


def _invoices(today: date) -> list[dict]:
    iso = lambda d: d.isoformat()  # noqa: E731
    return [
        {"id": "1", "supplier": "A AB", "invoice_number": "F-1",
         "total_amount": 1000.0, "status": "Obetald",
         "due_date": iso(today + timedelta(days=3))},
        {"id": "2", "supplier": "B AB", "invoice_number": "F-2",
         "total_amount": 500.0, "status": "Obetald",
         "due_date": iso(today - timedelta(days=2))},
        {"id": "3", "supplier": "C AB", "invoice_number": "F-3",
         "total_amount": 700.0, "status": "Betald",
         "due_date": iso(today - timedelta(days=9))},
        {"id": "4", "supplier": "A AB", "invoice_number": "F-4",
         "total_amount": 300.0, "status": "Obetald",
         "due_date": iso(today + timedelta(days=30))},
        {"id": "5", "supplier": "D AB", "invoice_number": "F-5",
         "total_amount": -200.0, "status": "Förfallen",
         "due_date": iso(today + timedelta(days=60))},
    ]


def test_summarize_rules():
    from ui.dashboard_view import summarize

    today = date(2026, 10, 14)
    stats = summarize(_invoices(today), today)
    # Obetalda: F-1, F-2, F-4, F-5 (kredit) → 1000+500+300−200
    assert stats["unpaid_count"] == 4
    assert stats["to_pay"] == 1600.0
    # Förfallna: F-2 (passerad) + F-5 (status Förfallen)
    assert [i["invoice_number"] for i in stats["overdue"]] == ["F-2", "F-5"]
    assert stats["overdue_sum"] == 300.0
    # Inom 7 dagar: bara F-1
    assert [i["invoice_number"] for i in stats["upcoming"]] == ["F-1"]
    assert stats["upcoming_7d_sum"] == 1000.0


class _FakeApp:
    def __init__(self, invoices):
        self._inv = invoices

    def get_invoices(self):
        return list(self._inv)

    def get_suppliers(self):
        return [{"id": "1", "name": "A AB"}, {"id": "2", "name": "B AB"}]

    def get_setting(self, key, default=None):
        return default


def test_dashboard_view_builds_both_languages():
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from ui import i18n
    from ui.dashboard_view import DashboardView

    view = DashboardView(_FakeApp(_invoices(date.today())))
    try:
        assert "1 600" in view._card_pay._value.text().replace("\u2009", " ")
        assert view._card_suppliers._value.text() == "2"
        assert view._table.rowCount() == 3  # F-2, F-5, F-1
        i18n.set_language("en")
        view.retranslate()
        assert view._card_pay._title.text() == "TO PAY"
        assert view._lbl_upcoming.text() == "Due soon"
        i18n.set_language("sv")
        view.retranslate()
        assert view._card_pay._title.text() == "ATT BETALA"
    finally:
        view.close()
