# -*- coding: utf-8 -*-
"""
Tester: fokuspaketet — appen ska bara räkna ihop fakturor
som ska betalas, så snabbt och säkert som möjligt.

Täcker: OCR-kontrollsiffra (Luhn), dubblettkoll i realtid,
betalinfotext till urklipp, "Betala idag"-urvalet, beständig
summarad, ångra statusändring (Ctrl+Z) och Dashboard-flaggan
för gamla okvittade krediter.
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
from ui.dashboard_view import summarize  # noqa: E402
from ui.invoices_helpers import (  # noqa: E402
    due_within,
    find_invoice_duplicate,
    ocr_luhn_status,
    payment_info_text,
)


@pytest.fixture(autouse=True)
def _sv():
    i18n.set_language("sv", notify=False)
    yield
    i18n.set_language("sv", notify=False)


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ── OCR-kontrollsiffra (Luhn) ────────────────────────────────────────

def test_ocr_luhn_known_numbers():
    # Klassiskt Luhn-exempel (Wikipedia) + en svensk-lik OCR.
    assert ocr_luhn_status("79927398713") == "ok"
    assert ocr_luhn_status("79927398710") == "bad_check"
    assert ocr_luhn_status("24465149") in ("ok", "bad_check")  # ingen krasch


def test_ocr_luhn_constructed_and_tampered():
    payload = "9911001"
    full = next(
        payload + str(d) for d in range(10)
        if ocr_luhn_status(payload + str(d)) == "ok"
    )
    assert len(full) == 8
    tampered = full[:-1] + str((int(full[-1]) + 1) % 10)
    assert ocr_luhn_status(tampered) == "bad_check"


def test_ocr_luhn_uncheckable_inputs():
    assert ocr_luhn_status("") == "empty"
    assert ocr_luhn_status(None) == "empty"
    assert ocr_luhn_status("1") == "invalid_format"
    assert ocr_luhn_status("REF-123") == "invalid_format"  # referens, ej OCR


# ── Dubblettkoll ─────────────────────────────────────────────────────

ROWS = [
    {"id": "9", "supplier": "Pilkington", "invoice_number": "9901"},
    {"id": "10", "supplier": "Direktglas AB", "invoice_number": "DG-1"},
]


def test_find_invoice_duplicate_case_insensitive():
    hit = find_invoice_duplicate(ROWS, " 9901 ", "pilkington")
    assert hit is not None and hit["id"] == "9"
    assert find_invoice_duplicate(ROWS, "9902", "Pilkington") is None
    assert find_invoice_duplicate(ROWS, "9901", "Direktglas AB") is None


def test_find_invoice_duplicate_excludes_self_when_editing():
    assert find_invoice_duplicate(
        ROWS, "9901", "Pilkington", exclude_id="9"
    ) is None
    assert find_invoice_duplicate(
        ROWS, "9901", "Pilkington", exclude_id="10"
    ) is not None


# ── Betalinfo till urklipp ───────────────────────────────────────────

def test_payment_info_text_bankgiro_ocr_amount():
    inv = {"supplier": "Pilkington", "invoice_number": "9901",
           "ocr": "99110015", "due_date": "2026-09-11",
           "total_amount": 1250.0}
    sup = {"name": "Pilkington", "bg": "5050-1055", "pg": ""}
    text = payment_info_text(inv, sup).replace("\u2009", " ")
    assert "Bankgiro: 5050-1055" in text
    assert "OCR: 99110015" in text
    assert "1 250,00 SEK" in text
    assert "Plusgiro" not in text


def test_payment_info_text_reference_fallback():
    inv = {"supplier": "Direktglas AB", "invoice_number": "DG-9",
           "ocr": "", "reference": "Kund 114", "total_amount": -500.0}
    text = payment_info_text(inv, None)
    assert "Referens: Kund 114" in text
    assert "OCR:" not in text


# ── Betala idag-urvalet ──────────────────────────────────────────────

def test_due_within_includes_overdue_today_tomorrow():
    today = datetime.date(2026, 9, 8)

    def inv(rid, due, status="Obetald", amount=100.0):
        return {"id": rid, "due_date": due, "status": status,
                "total_amount": amount}

    rows = [
        inv("a", "2026-09-01"),                    # förfallen → med
        inv("b", "2026-09-08"),                    # idag → med
        inv("c", "2026-09-09"),                    # i morgon → med
        inv("d", "2026-09-10"),                    # +2 dagar → ute
        inv("e", "2026-09-08", status="Betald"),   # betald → ute
        inv("f", "2026-09-05", amount=-500.0),     # kredit → med
        inv("g", ""),                              # utan datum → ute
    ]
    hits = due_within(rows, today, horizon_days=1)
    assert [i["id"] for i in hits] == ["a", "f", "b", "c"]  # sorterat


# ── Dashboard: gamla okvittade krediter ──────────────────────────────

def test_summarize_flags_stale_credits_only():
    today = datetime.date(2026, 9, 8)
    rows = [
        {"id": "1", "supplier": "Pilkington", "invoice_type": "Kreditfaktura",
         "invoice_number": "K-1", "due_date": "2026-07-01",
         "total_amount": -500.0, "status": "Obetald"},       # gammal → flagga
        {"id": "2", "supplier": "Pilkington", "invoice_type": "Kreditfaktura",
         "invoice_number": "K-2", "due_date": "2026-09-05",
         "total_amount": -300.0, "status": "Obetald"},       # färsk → ej
        {"id": "3", "supplier": "Pilkington", "invoice_type": "Kreditfaktura",
         "invoice_number": "K-3", "due_date": "2026-06-01",
         "total_amount": -900.0, "status": "Betald"},        # betald → ej
        {"id": "4", "supplier": "Pilkington", "invoice_type": "Faktura",
         "invoice_number": "F-4", "due_date": "2026-06-01",
         "total_amount": 2000.0, "status": "Obetald"},       # vanlig → ej
    ]
    stats = summarize(rows, today)
    assert [i["id"] for i in stats["stale_credits"]] == ["1"]
    assert stats["stale_credits_sum"] == 500.0


# ── Vyn: Betala idag + ångra + dialogvarningar ───────────────────────

class _Store:
    def on_change(self, _cb):
        pass


def _fake_app(tmp_path, invoices, suppliers=None):
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
            return suppliers or [
                {"id": "s1", "name": "Pilkington", "bg": "5050-1055"}
            ]

        def get_setting(self, key, default=None):
            return default

        def set_setting(self, key, value):
            pass

        def update_invoice(self, rid, data):
            for inv in invoices:
                if inv["id"] == rid:
                    inv.update(data)
                    return inv
            return None

    return FakeApp()


def _mk_invoice(rid, due, nr=None, amount=100.0, status="Obetald"):
    return {"id": rid, "supplier": "Pilkington",
            "invoice_number": nr or f"F-{rid}",
            "invoice_type": "Faktura", "date": "2026-09-01",
            "due_date": due, "total_amount": amount,
            "ocr": "", "status": status}


def test_pay_today_selects_due_only(tmp_path, monkeypatch):
    _qapp()
    from ui.invoices_view import InvoicesView

    today = datetime.date.today()
    iso = (today + datetime.timedelta(days=0)).isoformat()
    tomorrow = (today + datetime.timedelta(days=1)).isoformat()
    later = (today + datetime.timedelta(days=5)).isoformat()
    overdue = (today - datetime.timedelta(days=3)).isoformat()
    invs = [
        _mk_invoice("1", iso), _mk_invoice("2", tomorrow),
        _mk_invoice("3", later), _mk_invoice("4", overdue),
        _mk_invoice("5", iso, status="Betald"),
    ]
    view = InvoicesView(_fake_app(tmp_path, invs))
    opened = []
    monkeypatch.setattr(
        view, "_show_combine_dialog", lambda: opened.append(True)
    )
    view._pay_today()
    picked = {i["id"] for i in view._selected_invoices()}
    assert picked == {"1", "2", "4"}
    assert opened == [True]  # ≥2 träffar → sammanställningen öppnas
    # Den beständiga summaraden visar markeringen
    assert "Markerat: 3 st" in view._lbl_selection.text()


def test_undo_restores_status_and_payment_date(tmp_path):
    _qapp()
    from PySide6.QtCore import QItemSelectionModel

    from ui.invoices_view import InvoicesView

    invs = [_mk_invoice("1", "2026-09-11"), _mk_invoice("2", "2026-09-12"),
            _mk_invoice("3", "2026-09-13")]
    app = _fake_app(tmp_path, invs)
    view = InvoicesView(app)
    model = view._table.selectionModel()
    for row in (0, 1):
        idx = view._table.model().index(row, 0)
        model.select(
            idx,
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows,
        )
    view._set_status_selected("Betald")
    state = {i["id"]: i["status"] for i in invs}
    assert state == {"1": "Betald", "2": "Betald", "3": "Obetald"}

    view._undo_last_status()
    state = {i["id"]: i["status"] for i in invs}
    assert state == {"1": "Obetald", "2": "Obetald", "3": "Obetald"}
    assert invs[0]["payment_date"] == ""

    # Tom stack → ingen krasch, inget ändras
    view._undo_last_status()
    assert {i["id"]: i["status"] for i in invs}["1"] == "Obetald"


def test_dialog_live_warnings_luhn_and_duplicate(tmp_path):
    _qapp()
    from ui.invoices_helpers import InvoiceDialog

    app = _fake_app(
        tmp_path,
        [{"id": "9", "supplier": "Pilkington", "invoice_number": "9901",
          "total_amount": 100.0, "status": "Obetald", "due_date": ""}],
    )
    dlg = InvoiceDialog(
        parent=None, supplier_name="Pilkington",
        supplier_names=["Pilkington"], app_core=app,
    )
    dlg.show()

    dlg.f_ocr.setText("79927398710")   # fel kontrollsiffra
    assert dlg._warn_ocr_check.isVisible()
    dlg.f_ocr.setText("79927398713")   # rätt kontrollsiffra
    assert not dlg._warn_ocr_check.isVisible()

    dlg.f_inv_nr.setText("9901")       # finns redan för leverantören
    assert dlg._warn_dup.isVisible()
    dlg.f_inv_nr.setText("9902")
    assert not dlg._warn_dup.isVisible()
    dlg.close()
