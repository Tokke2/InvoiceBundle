# -*- coding: utf-8 -*-
"""Bankgiro/Plusgiro/IBAN-varningar vid fakturainläsning."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "ui"),
           str(PROJECT_DIR / "plugins")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

import scan_import as si


SUPPLIER = {
    "name": "Alpha AB",
    "bg": "123-4567",
    "pg": "7654321",
    "iban": "GB82 WEST 1234 5698 7654 32",
}


INVOICE_TEXT = """\
Alpha AB
Fakturanr: A-1
Att betala: 100,00
Bankgiro nr: 999-9999
Plusgiro: 7654321
IBAN: GB82 WEST 1234 5698 7654 32
OCR: 1234567890
Kundnummer: 87654321
"""


def test_extracts_only_values_with_payment_labels():
    details = si.extract_invoice_payment_details(INVOICE_TEXT)
    assert details == {
        "bg": ["9999999"],
        "pg": ["7654321"],
        "iban": ["GB82WEST12345698765432"],
    }
    # Account labels may put the value on the immediately following line.
    assert si.extract_invoice_payment_details(
        "Bankgiro:\n123-4567\nPlusgiro nr\n7654321"
    ) == {
        "bg": ["1234567"], "pg": ["7654321"], "iban": [],
    }
    # Unlabelled numbers are deliberately not guessed as payment accounts.
    assert si.extract_invoice_payment_details(
        "1234567\nRef 7654321\nOCR 1234567890"
    ) == {"bg": [], "pg": [], "iban": []}


def test_compares_normalized_values_only_with_exact_saved_supplier():
    matching_text = """\
Bankgiro: 123 4567
Plusgiro: 7654321
IBAN: GB82 WEST 1234 5698 7654 32
"""
    assert si.payment_detail_warnings(
        matching_text, "alpha ab", [SUPPLIER]
    ) == []

    warnings = si.payment_detail_warnings(
        INVOICE_TEXT, "Alpha AB", [SUPPLIER]
    )
    assert warnings == [{
        "field": "bg",
        "registered": "1234567",
        "invoice_values": ["9999999"],
    }]
    # A different/ambiguous supplier is not guessed; blank saved fields
    # cannot trigger a mismatch warning.
    assert si.payment_detail_warnings(
        INVOICE_TEXT, "Alpha", [SUPPLIER]
    ) == []
    assert si.payment_detail_warnings(
        "Bankgiro: 9999999", "Alpha AB", [{"name": "Alpha AB"}]
    ) == []


def test_plusgiro_and_iban_changes_are_reported():
    text = "Plusgiro: 7654322\nIBAN: DE89 3704 0044 0532 0130 00"
    warnings = si.payment_detail_warnings(text, "Alpha AB", [SUPPLIER])
    assert [item["field"] for item in warnings] == ["pg", "iban"]
    assert warnings[0]["invoice_values"] == ["7654322"]
    assert warnings[1]["invoice_values"] == ["DE89370400440532013000"]


def test_payment_warning_is_separate_from_supplier_match_uncertainty():
    parsed = {
        "supplier": "Alpha AB",
        "match_uncertain": True,
        "match_kind": "supplier",
        "supplier_match": {"status": "uncertain", "uncertain": True},
    }
    unresolved = si.assess_invoice_payment_details(
        parsed, INVOICE_TEXT, [SUPPLIER]
    )
    assert unresolved["invoice_payment_details"]["bg"] == ["9999999"]
    assert "payment_details_warning" not in unresolved

    confirmed = si.assess_invoice_payment_details(
        parsed, INVOICE_TEXT, [SUPPLIER], supplier_name="Alpha AB"
    )
    assert confirmed["match_uncertain"] is True
    assert confirmed["payment_details_warning"][0]["field"] == "bg"

    multipage = si.assess_invoice_payment_details({
        "supplier": "Alpha AB", "match_uncertain": True,
        "match_kind": "multipage",
        "supplier_match": {
            "status": "uncertain", "uncertain": True,
            "reason": "multipage",
        },
    }, INVOICE_TEXT, [SUPPLIER])
    assert multipage["match_uncertain"] is True
    assert multipage["payment_details_warning"][0]["field"] == "bg"


def test_parse_result_includes_payment_warning_without_changing_match_state():
    parsed = si.parse_invoice_text(
        INVOICE_TEXT, [SUPPLIER],
        templates={"Alpha AB": {"fields": {
            "invoice_number": {"label": "Fakturanr"},
            "total_amount": {"label": "Att betala"},
        }}},
    )
    assert parsed["supplier"] == "Alpha AB"
    assert not parsed.get("match_uncertain")
    assert parsed["payment_details_warning"][0]["field"] == "bg"
    assert parsed["invoice_payment_details"]["pg"] == ["7654321"]


def test_watch_folder_parks_payment_mismatch_then_rechecks_on_reprocess(
    tmp_path,
):
    try:
        from PySide6.QtWidgets import QApplication
    except (ImportError, OSError) as exc:
        pytest.skip(f"Qt runtime is unavailable: {exc}")

    QApplication.instance() or QApplication([])
    from ui.watch_folders import WatchManager

    text = """\
Alpha AB
Fakturanr: A-1
Att betala: 100,00
Bankgiro: 999-9999
"""
    template = {"Alpha AB": {"fields": {
        "invoice_number": {"label": "Fakturanr"},
        "total_amount": {"label": "Att betala"},
    }}}

    class FakeApp:
        suppliers = [{"name": "Alpha AB", "bg": "1234567"}]

        def get_suppliers(self):
            return self.suppliers

        def get_invoices(self):
            return []

    app = FakeApp()
    folder = tmp_path / "watched"
    folder.mkdir()
    invoice = folder / "a.pdf"
    manager = WatchManager(
        tmp_path / "watch.json", app=app,
        extract_fn=lambda _path: (text, "test"),
        templates_provider=lambda: template,
    )
    ready: list[dict] = []
    parked: list[dict] = []
    manager.invoice_ready.connect(lambda row, _path: ready.append(row))
    manager.file_parked.connect(parked.append)
    manager.set_folders([{"supplier": "Alpha AB", "path": str(folder)}])
    invoice.write_bytes(b"%PDF-test-invoice")

    manager.scan_all()
    assert ready == []
    assert len(parked) == 1
    assert parked[0]["reason"] == "payment-details"
    assert parked[0]["parsed"]["payment_details_warning"][0]["field"] == "bg"
    assert manager._should_retry_parked(parked[0], parked[0]["hash"]) is False

    # Reprocessing is explicit. When the supplier's saved account now agrees,
    # the payment warning clears and the file follows the normal watch path.
    app.suppliers = [{"name": "Alpha AB", "bg": "9999999"}]
    manager.reprocess_parked()
    assert len(ready) == 1
    assert not ready[0].get("payment_details_warning")
    assert manager.parked == []


def test_payment_mismatch_never_auto_registers_and_needs_explicit_yes(
    tmp_path, monkeypatch,
):
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except (ImportError, OSError) as exc:
        pytest.skip(f"Qt runtime is unavailable: {exc}")

    QApplication.instance() or QApplication([])
    import ui.scan_import_view as scan_ui
    from ui.scan_import_view import ScanImportView

    class FakeApp:
        def get_suppliers(self):
            return [{"name": "Alpha AB", "bg": "1234567"}]

        def get_setting(self, key, default=None):
            return default

    view = ScanImportView(
        app=FakeApp(), templates_path=tmp_path / "templates.json"
    )
    row = {
        "file": "a.pdf", "_path": "", "_text": INVOICE_TEXT,
        "supplier": "Alpha AB", "invoice_number": "A-1",
        "total_amount": 100.0, "missing": [], "status": "redo",
        "payment_details_warning": [{
            "field": "bg", "registered": "1234567",
            "invoice_values": ["9999999"],
        }],
    }
    view._rows = [row]
    view._selected_rows = lambda: [0]
    view._possible_duplicates_for_rows = lambda _ready: []
    saved: list[dict] = []
    view._save_invoice = lambda data, **_kwargs: saved.append(data) or True
    view._unpark_row = lambda _row: None
    view._show_invoices_tab = lambda: None
    view._record_confirmed_template_row = lambda _row: ""
    prompts: list[tuple] = []

    def answer(_parent, _title, body, *args, **kwargs):
        prompts.append((body, args, kwargs))
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(scan_ui.QMessageBox, "warning", answer)
    monkeypatch.setattr(scan_ui.QMessageBox, "information", lambda *a: None)
    try:
        assert view._auto_register_matched_rows([row]) == 0
        view._create_invoices()
        assert len(prompts) == 1
        assert saved == []
        assert view._rows == [row]

        monkeypatch.setattr(
            scan_ui.QMessageBox, "warning",
            lambda *a, **k: QMessageBox.StandardButton.Yes,
        )
        view._create_invoices()
        assert len(saved) == 1
        # Invoice account details are not written into the supplier or invoice
        # record as an automatic profile change.
        assert not {"bg", "pg", "iban"}.intersection(saved[0])
    finally:
        view.close()
