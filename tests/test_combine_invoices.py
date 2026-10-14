# -*- coding: utf-8 -*-
"""
Tester: Slå ihop markerade fakturor.

Markerade fakturor läggs ihop (fakturor +, krediter −) och
förfallodatumet tas från den faktura som förfaller först —
det datumet förifylls också som betalningsdatum vid export
av just de markerade.
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

from ui.invoices_helpers import combine_invoices


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


ROWS = [
    {"id": "1", "supplier": "Pilkington", "invoice_number": "9911",
     "total_amount": 1250.0, "due_date": "2026-10-05"},
    {"id": "2", "supplier": "Pilkington", "invoice_number": "9912",
     "total_amount": 2500.0, "due_date": "2026-09-18"},
    {"id": "3", "supplier": "Direktglas", "invoice_number": "D-7",
     "total_amount": -500.0, "due_date": "2026-09-20"},
    {"id": "4", "supplier": "Direktglas", "invoice_number": "D-8",
     "total_amount": 750.0, "due_date": ""},
    {"id": "5", "supplier": "Nordlys", "invoice_number": "N-1",
     "total_amount": 100.0, "due_date": "skräp"},
]


def test_combine_sums_and_earliest_due():
    s = combine_invoices(ROWS)
    assert s["count"] == 5
    assert s["n_invoices"] == 4 and s["n_credits"] == 1
    assert s["total_invoices"] == 4600.0
    assert s["total_credits"] == -500.0
    assert s["net"] == 4100.0
    # Tidigaste giltiga datumet vinner — krediten räknas med
    assert s["earliest_due"] == "2026-09-18"
    assert s["earliest_invoice"]["invoice_number"] == "9912"
    # Tomt + ogiltigt datum = 2 saknade
    assert s["missing_due"] == 2
    assert s["suppliers"] == ["Direktglas", "Nordlys", "Pilkington"]


def test_combine_empty_and_no_dates():
    s = combine_invoices([])
    assert s["count"] == 0 and s["net"] == 0.0
    assert s["earliest_due"] == "" and s["earliest_invoice"] is None
    s2 = combine_invoices([{"total_amount": 10.0, "due_date": ""}])
    assert s2["earliest_due"] == "" and s2["missing_due"] == 1


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
            return list(invoices)

        def get_suppliers(self):
            return [{"id": "1", "name": "Pilkington"}]

        def get_setting(self, key, default=None):
            return default

        def set_setting(self, key, value):
            pass

    return FakeApp()


def test_view_selection_enables_combine(tmp_path):
    _qapp()
    from PySide6.QtCore import QItemSelectionModel
    from ui.invoices_view import InvoicesView

    invs = [
        {"id": f"i{n}", "supplier": "Pilkington",
         "invoice_number": f"F-{n}", "invoice_type": "Faktura",
         "date": "2026-09-01",
         "due_date": f"2026-09-{10 + n:02d}",
         "total_amount": 100.0 * n, "ocr": "", "status": "Obetald"}
        for n in range(1, 11)
    ]
    view = InvoicesView(_fake_app(tmp_path, invs))
    assert len(view._selected_invoices()) == 0
    assert not view._btn_combine.isEnabled()

    model = view._table.selectionModel()
    for row in range(10):
        idx = view._table.model().index(row, 0)
        model.select(
            idx,
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows,
        )
    selected = view._selected_invoices()
    assert len(selected) == 10
    assert view._btn_combine.isEnabled()
    summary = combine_invoices(selected)
    assert summary["net"] == 5500.0          # 100+200+…+1000
    assert summary["earliest_due"] == "2026-09-11"   # den som förfaller först

    # Relativ datumtext
    today = datetime.date.today()
    assert "idag" in view._due_relative(today.isoformat())
    future = (today + datetime.timedelta(days=5)).isoformat()
    assert "5" in view._due_relative(future)
    past = (today - datetime.timedelta(days=3)).isoformat()
    assert "3" in view._due_relative(past)
