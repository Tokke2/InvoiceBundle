# -*- coding: utf-8 -*-
"""
Tester: leverantörer som använder fakturanumret som OCR-nummer.

Vissa leverantörer trycker samma nummer som fakturanummer och OCR.
Kryssrutan i leverantörsregistret gör att ett TOMT OCR-fält fylls
med fakturanumret vid tolkning (Import, inklistrad text, bevakade
mappar) och i registreringsdialogen. Ett OCR-nummer som står på
fakturan — eller som användaren skrivit — skrivs aldrig över, och
regeln gissar aldrig en leverantör.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (
    str(PROJECT_DIR),
    str(PROJECT_DIR / "ui"),
    str(PROJECT_DIR / "plugins"),
):
    if _d not in sys.path:
        sys.path.insert(0, _d)

import pytest  # noqa: E402

from ui import i18n  # noqa: E402

TEXT_UTAN_OCR = (
    "Pilkington Sverige AB\n"
    "Fakturanummer: 2026-144\n"
    "Fakturadatum: 2026-08-17\n"
    "Förfallodatum: 2026-09-16\n"
    "Att betala: 1 000,00\n"
)

TEXT_MED_OCR = (
    "Pilkington Sverige AB\n"
    "Fakturanummer: 2026-144\n"
    "OCR-nummer: 99110015\n"
    "Fakturadatum: 2026-08-17\n"
    "Förfallodatum: 2026-09-16\n"
    "Att betala: 1 000,00\n"
)


@pytest.fixture(autouse=True)
def _sv():
    i18n.set_language("sv", notify=False)
    yield
    i18n.set_language("sv", notify=False)


def _qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _supplier(**extra):
    sup = {
        "id": "s1",
        "name": "Pilkington Sverige AB",
        "org_number": "556114-4949",
    }
    sup.update(extra)
    return sup


# ── Tolkningen (Import / bevakade mappar) ───────────────────────────

def test_ocr_filled_from_invoice_number_when_supplier_opted_in():
    import scan_import as si

    suppliers = [_supplier(ocr_same_as_invoice_number=True)]
    parsed = si.parse_invoice_text(TEXT_UTAN_OCR, suppliers)

    assert parsed["supplier"] == "Pilkington Sverige AB"
    assert parsed["invoice_number"] == "2026-144"
    assert parsed["ocr"] == "2026-144"
    assert parsed["ocr_source"] == "supplier_rule"


def test_rule_is_off_by_default_and_never_guesses_supplier():
    import scan_import as si

    # Ingen kryssruta → OCR förblir tomt (ingen gissning)
    parsed = si.parse_invoice_text(TEXT_UTAN_OCR, [_supplier()])
    assert parsed["ocr"] == ""
    assert "ocr_source" not in parsed

    # Okänd leverantör trots flaggan → ingen regel
    parsed = si.parse_invoice_text(
        TEXT_UTAN_OCR,
        [_supplier(name="Annan Leverantör AB",
                   ocr_same_as_invoice_number=True)],
    )
    assert parsed["supplier"] == ""
    assert parsed["ocr"] == ""


def test_printed_ocr_wins_over_invoice_number_rule():
    import scan_import as si

    suppliers = [_supplier(ocr_same_as_invoice_number=True)]
    parsed = si.parse_invoice_text(TEXT_MED_OCR, suppliers)

    assert parsed["ocr"] == "99110015"
    assert "ocr_source" not in parsed


def test_rule_accepts_alias_names():
    import scan_import as si

    suppliers = [_supplier(aliases=["Pilkington"],
                           ocr_same_as_invoice_number=True)]
    parsed = si.parse_invoice_text(TEXT_UTAN_OCR, suppliers)
    assert parsed["ocr"] == "2026-144"


def test_rule_does_not_touch_uncertain_matches():
    import scan_import as si

    parsed = {
        "supplier": "Pilkington Sverige AB",
        "invoice_number": "2026-144",
        "ocr": "",
        "match_uncertain": True,
    }
    result = si.apply_supplier_ocr_rule(
        parsed, [_supplier(ocr_same_as_invoice_number=True)]
    )
    assert result["ocr"] == ""


# ── Registreringsdialogen ───────────────────────────────────────────

def test_invoice_dialog_fills_ocr_from_invoice_number(tmp_path):
    from types import SimpleNamespace

    from ui.invoices_helpers import InvoiceDialog

    _qapp()
    suppliers = [_supplier(ocr_same_as_invoice_number=True)]

    class FakeCore:
        has_session_due_date = False
        session_due_date = None
        invoices_store = SimpleNamespace(_file=tmp_path / "invoices.json")

        def get_suppliers(self):
            return [dict(s) for s in suppliers]

        def get_invoices(self):
            return []

    dlg = InvoiceDialog(
        supplier_name="Pilkington Sverige AB",
        supplier_names=["Pilkington Sverige AB"],
        app_core=FakeCore(),
    )
    try:
        dlg.f_inv_nr.setText("2026-144")
        assert dlg.f_ocr.text() == "2026-144"

        # Användarens eget OCR-nummer skrivs aldrig över
        dlg.f_ocr.setText("99110015")
        dlg.f_inv_nr.setText("2026-145")
        assert dlg.f_ocr.text() == "99110015"

        # Tömmer användaren fältet fylls det igen från numret
        dlg.f_ocr.setText("")
        dlg._apply_supplier_ocr_rule()
        assert dlg.f_ocr.text() == "2026-145"

        # Värdet följer med i det som sparas
        assert dlg.get_data()["ocr"] == "2026-145"
    finally:
        dlg.close()


def test_invoice_dialog_leaves_ocr_empty_without_rule(tmp_path):
    from types import SimpleNamespace

    from ui.invoices_helpers import InvoiceDialog

    _qapp()

    class FakeCore:
        has_session_due_date = False
        session_due_date = None
        invoices_store = SimpleNamespace(_file=tmp_path / "invoices.json")

        def get_suppliers(self):
            return [{"name": "Pilkington Sverige AB"}]

        def get_invoices(self):
            return []

    dlg = InvoiceDialog(
        supplier_name="Pilkington Sverige AB",
        supplier_names=["Pilkington Sverige AB"],
        app_core=FakeCore(),
    )
    try:
        dlg.f_inv_nr.setText("2026-144")
        assert dlg.f_ocr.text() == ""
    finally:
        dlg.close()


# ── Leverantörsregistret ────────────────────────────────────────────

def test_supplier_dialog_roundtrips_the_checkbox(tmp_path):
    from PySide6.QtWidgets import QDialog

    from ui.suppliers_view import SupplierDialog

    _qapp()
    existing = _supplier(ocr_same_as_invoice_number=True)
    dlg = SupplierDialog(existing=existing)
    try:
        assert dlg.f_ocr_rule.isChecked()
        assert dlg.get_data()["ocr_same_as_invoice_number"] is True
        dlg.f_ocr_rule.setChecked(False)
        assert dlg.get_data()["ocr_same_as_invoice_number"] is False
    finally:
        dlg.done(QDialog.DialogCode.Rejected)


def test_supplier_schema_has_the_setting():
    from ui.core.storage import get_schema

    assert get_schema("suppliers")["ocr_same_as_invoice_number"] is False


def test_suppliers_table_shows_the_setting():
    from ui.suppliers_view import COL_KEYS

    assert "ocr_same_as_invoice_number" in COL_KEYS
    assert i18n.tr("suppliers.ocr_same_mark")
