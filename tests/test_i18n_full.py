# -*- coding: utf-8 -*-
"""
Regressionstester: FULL tvåspråkighet (sv/en) — fakturadialog,
filter/summor, skanningsimport och PDF-innehåll.

Designprincip som testerna skyddar: lagrade datavärden (status/typ)
är ALLTID svenska internt; bara visningen översätts.
"""
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


class _Store:
    def on_change(self, _cb):
        pass


class FakeApp:
    settings = {"db_path": "data"}
    invoices_store = _Store()
    suppliers_store = _Store()
    session_due_date = None
    session_due_date_str = ""
    pdf_exporter = None

    def __init__(self):
        self._invs = [
            {"id": "i1", "supplier": "Elgiganten AB",
             "invoice_number": "F-1", "invoice_type": "Faktura",
             "date": "2026-09-01", "due_date": "2026-10-01",
             "total_amount": 1200.0, "ocr": "123", "status": "Obetald"},
            {"id": "i2", "supplier": "Elgiganten AB",
             "invoice_number": "K-1", "invoice_type": "Kreditfaktura",
             "date": "2026-09-02", "due_date": "2026-08-01",
             "total_amount": -200.0, "ocr": "", "status": "Förfallen"},
        ]
        self._sups = [{"id": "1", "name": "Elgiganten AB",
                       "org_number": "556471-4471", "bg": "190-1090",
                       "payment_terms": 30}]

    def get_invoices(self):
        return list(self._invs)

    def get_suppliers(self):
        return list(self._sups)

    def get_setting(self, key, default=None):
        return {"language": "en"}.get(key, default)

    def set_setting(self, key, value):
        pass


def test_all_i18n_keys_have_sv_and_en():
    from ui import i18n

    missing = [
        k for k, v in i18n._STRINGS.items()
        if not v.get("sv") or not v.get("en")
    ]
    assert missing == []


def test_status_type_labels_translate_display_only():
    from ui import i18n

    i18n.set_language("sv")
    assert i18n.tr_status("Obetald") == "Obetald"
    assert i18n.tr_type("Kreditfaktura") == "Kreditfaktura"
    i18n.set_language("en")
    assert i18n.tr_status("Obetald") == "Unpaid"
    assert i18n.tr_status("Förfallen") == "Overdue"
    assert i18n.tr_type("Faktura") == "Invoice"
    assert i18n.tr_type("Kreditfaktura") == "Credit note"
    i18n.set_language("sv")


def test_invoice_dialog_english_but_canonical_data():
    _qapp()
    from ui import i18n

    i18n.set_language("en")
    try:
        from ui.invoices_helpers import InvoiceDialog

        dlg = InvoiceDialog(
            parent=None, supplier_name="Elgiganten AB",
            supplier_names=["Elgiganten AB"], app_core=None,
        )
        assert dlg.windowTitle() == "➕  Register invoice"
        labels = [
            dlg.f_status.itemText(i) for i in range(dlg.f_status.count())
        ]
        assert "Unpaid" in labels and "Obetald" not in labels
        # Data förblir kanoniskt svensk (lagring/filer oförändrade)
        dlg.f_inv_nr.setText("F-99")
        dlg.f_total.setValue(100)
        data = dlg.get_data()
        assert data["status"] == "Obetald"
        assert data["invoice_type"] == "Faktura"
        dlg.close()
    finally:
        i18n.set_language("sv")


def test_invoices_view_english_filters_sums_cells():
    _qapp()
    from ui import i18n

    i18n.set_language("en")
    try:
        from ui.invoices_view import InvoicesView

        view = InvoicesView(FakeApp())
        headers = [
            view._table.horizontalHeaderItem(i).text()
            for i in range(view._table.columnCount())
        ]
        assert "Due" in headers and "Förfaller" not in headers
        cells = [
            view._table.item(r, c).text()
            for r in range(view._table.rowCount())
            for c in range(view._table.columnCount())
            if view._table.item(r, c)
        ]
        assert "Unpaid" in cells and "Overdue" in cells
        assert "Invoice" in cells and "Credit note" in cells
        assert "Unpaid:" in view._lbl_unpaid.text()
        assert view._lbl_history_count.text() == "(0 exports)"
        # Statusfiltret: engelsk visning, svenskt datavärde
        idx = view._filter_status.findText("Unpaid")
        assert idx >= 0
        assert view._filter_status.itemData(idx) == "Obetald"
        view.close()
    finally:
        i18n.set_language("sv")


def test_scan_view_english_headers_sum_status():
    _qapp()
    from ui import i18n

    i18n.set_language("en")
    try:
        from ui.scan_import_view import ScanImportView

        class FakeCore:
            def get_suppliers(self):
                return []

            def get_setting(self, key, default=None):
                return default

        view = ScanImportView(app=FakeCore())
        headers = [
            view._tbl.horizontalHeaderItem(i).text()
            for i in range(view._tbl.columnCount())
        ]
        assert headers[0] == "File" and headers[1] == "Supplier"
        view._rows = [{
            "file": "f.pdf", "supplier": "El", "invoice_number": "1",
            "date": "2026-01-01", "due_date": "", "ocr": "",
            "total_amount": 100.0, "method": "ocr",
            "status": "saknas: belopp, leverantör",
            "missing": ["belopp", "leverantör"],
        }]
        view._refresh_table()
        assert view._tbl.item(0, 8).text() == "missing: amount, supplier"
        assert "total" in view._lbl_sum.text()
        view.close()
    finally:
        i18n.set_language("sv")


def test_pdf_labels_follow_language(tmp_path):
    from plugins.pdf_export_helpers import PDFExporter

    en = PDFExporter(
        export_dir=tmp_path, data_dir=tmp_path,
        company="Test", language="en", theme="light",
    )
    cols_en = [c[0] for c in en._columns()]
    assert "Due date" in cols_en and en._t("to_pay") == "TO PAY:"

    sv = PDFExporter(
        export_dir=tmp_path, data_dir=tmp_path,
        company="Test", language="sv", theme="light",
    )
    cols_sv = [c[0] for c in sv._columns()]
    assert "Forfallodatum" in cols_sv
    assert sv._t("to_pay") == "ATT BETALA:"
