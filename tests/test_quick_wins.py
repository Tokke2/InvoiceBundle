# -*- coding: utf-8 -*-
"""
Tester: snabbvinsterna (omgång 2) — allt kring kärnan
"räkna ihop fakturor som ska betalas":

• due_window_filter: snabbfilter Förfallna / Idag & i morgon / 7 dagar
• att_betala_summary: kärnsiffran bakom statusrad + tray-tooltip
• Skanningslistan flaggar OCR med fel kontrollsiffra direkt
• Chipsen i Fakturor-vyn filtrerar på riktigt (och går att slå av)
"""
from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "ui"),
           str(PROJECT_DIR / "plugins")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

import pytest  # noqa: E402

from ui import i18n  # noqa: E402
from ui.invoices_helpers import (  # noqa: E402
    att_betala_summary,
    due_window_filter,
)


@pytest.fixture(autouse=True)
def _sv():
    i18n.set_language("sv", notify=False)
    yield
    i18n.set_language("sv", notify=False)


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


TODAY = datetime.date(2026, 9, 8)


def _inv(rid, due, status="Obetald", amount=100.0):
    return {"id": rid, "due_date": due, "status": status,
            "total_amount": amount}


ROWS = [
    _inv("overdue", "2026-09-01"),
    _inv("today", "2026-09-08"),
    _inv("tomorrow", "2026-09-09"),
    _inv("in5", "2026-09-13"),
    _inv("in9", "2026-09-17"),
    _inv("paid_late", "2026-09-01", status="Betald"),
    _inv("nodate", ""),
    _inv("forced", "2026-10-01", status="Förfallen"),
    _inv("credit", "2026-09-05", amount=-50.0),
]


def _ids(rows):
    return [r["id"] for r in rows]


# ── due_window_filter ────────────────────────────────────────────────

def test_due_window_overdue_includes_forced_status_and_credit():
    hits = due_window_filter(ROWS, "overdue", TODAY)
    assert set(_ids(hits)) == {"overdue", "forced", "credit"}


def test_due_window_today_and_week():
    assert set(_ids(due_window_filter(ROWS, "today", TODAY))) == {
        "today", "tomorrow"}
    assert set(_ids(due_window_filter(ROWS, "week", TODAY))) == {
        "today", "tomorrow", "in5"}


def test_due_window_unknown_mode_returns_all():
    assert _ids(due_window_filter(ROWS, "allt", TODAY)) == _ids(ROWS)


# ── att_betala_summary ───────────────────────────────────────────────

def test_att_betala_summary_net_of_credits():
    rows = [
        _inv("a", "2026-09-08", amount=1000.0),
        _inv("b", "2026-09-09", amount=-250.0),          # kredit dras av
        _inv("c", "2026-09-10", amount=500.0, status="Betald"),
        _inv("d", "2026-09-11", amount=700.0, status="Arkiverad"),
        _inv("e", "2026-09-12", amount=300.0, status="Förfallen"),
    ]
    s = att_betala_summary(rows)
    assert s == {"total": 1050.0, "count": 3}


def test_att_betala_summary_empty():
    assert att_betala_summary([]) == {"total": 0.0, "count": 0}


# ── Skanning: OCR-kontrollsiffra i listan ────────────────────────────

def test_scan_display_status_flags_bad_ocr():
    from ui.scan_import_view import ScanImportView
    bad = ScanImportView._display_status(
        {"status": "redo", "ocr": "79927398710"}  # fel kontrollsiffra
    )
    assert "OCR-kontrollsiffra" in bad
    good = ScanImportView._display_status(
        {"status": "redo", "ocr": "79927398713"}  # rätt kontrollsiffra
    )
    assert "OCR-kontrollsiffra" not in good
    missing = ScanImportView._display_status(
        {"status": "saknas: belopp", "missing": ["belopp"],
         "ocr": "79927398710"}
    )
    assert "OCR-kontrollsiffra" in missing


# ── Vyn: chipsen filtrerar ───────────────────────────────────────────

class _Store:
    def on_change(self, _cb):
        pass


def _fake_app(tmp_path, invoices):
    class FakeApp:
        settings = {"db_path": str(tmp_path)}
        invoices_store = _Store()
        suppliers_store = _Store()
        session_due_date = None
        session_due_date_str = ""
        pdf_exporter = None

        def get_invoices(self):
            return [dict(i) for i in invoices]

        def get_suppliers(self):
            return [{"id": "s1", "name": "Pilkington", "bg": "5050-1055"}]

        def get_setting(self, key, default=None):
            return default

        def set_setting(self, key, value):
            pass

    return FakeApp()


def test_chips_filter_invoices_view(tmp_path):
    _qapp()
    from ui.invoices_view import InvoicesView

    today = datetime.date.today()
    iso = (today + datetime.timedelta(days=0)).isoformat()
    rows = [
        {"id": "1", "supplier": "Pilkington", "invoice_number": "F-1",
         "invoice_type": "Faktura", "date": iso,
         "due_date": (today - datetime.timedelta(days=2)).isoformat(),
         "total_amount": 100.0, "ocr": "", "status": "Obetald"},
        {"id": "2", "supplier": "Pilkington", "invoice_number": "F-2",
         "invoice_type": "Faktura", "date": iso, "due_date": iso,
         "total_amount": 200.0, "ocr": "", "status": "Obetald"},
        {"id": "3", "supplier": "Pilkington", "invoice_number": "F-3",
         "invoice_type": "Faktura", "date": iso,
         "due_date": (today + datetime.timedelta(days=6)).isoformat(),
         "total_amount": 300.0, "ocr": "", "status": "Obetald"},
        {"id": "4", "supplier": "Pilkington", "invoice_number": "F-4",
         "invoice_type": "Faktura", "date": iso,
         "due_date": (today + datetime.timedelta(days=30)).isoformat(),
         "total_amount": 400.0, "ocr": "", "status": "Obetald"},
    ]
    view = InvoicesView(_fake_app(tmp_path, rows))
    assert {i["id"] for i in view._apply_filters()} == {"1", "2", "3", "4"}

    view._on_chip("overdue")
    assert {i["id"] for i in view._apply_filters()} == {"1"}
    assert view._chip_mode == "overdue"
    assert view._chip_btns["overdue"].isChecked()

    view._on_chip("week")
    assert {i["id"] for i in view._apply_filters()} == {"2", "3"}

    # Samma chip igen → filtret stängs av
    view._on_chip("week")
    assert view._chip_mode == ""
    assert {i["id"] for i in view._apply_filters()} == {"1", "2", "3", "4"}


def test_main_window_has_att_betala_bar_method():
    """Röktest: huvudfönstret exponerar uppdateringsmetoden och
    hjälparen ger text utan att krascha (fönstret byggs inte i test)."""
    from ui import main_window
    assert callable(main_window.MainWindow._update_att_betala_bar)
    s = att_betala_summary(ROWS)
    text = i18n.tr("main.to_pay_bar", amount="1 234,00 SEK", n=s["count"])
    assert "Att betala" in text and "obetalda" in text
    tip = i18n.tr(
        "tray.tooltip_due", app="Fakturabunten",
        amount="1 234,00 SEK", n=2,
    )
    assert "Fakturabunten" in tip and "Att betala" in tip
