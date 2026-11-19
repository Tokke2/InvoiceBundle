# -*- coding: utf-8 -*-
"""Tests for UI improvements 1.1–1.4:
1.1: Empty placeholder tabs (Betalningar/Rapporter) removed.
1.2: Embedded preview side-panel and Ctrl+Return move shortcut in Import.
1.3: Toggleable & compact columns with persistence in Invoices & Suppliers.
1.4: Complete sv/en translation coverage across main window, dialogs & views.
"""
from __future__ import annotations

import ast
import os
import string
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (
    str(PROJECT_DIR),
    str(PROJECT_DIR / "ui"),
    str(PROJECT_DIR / "plugins"),
):
    if _d not in sys.path:
        sys.path.insert(0, _d)


def _qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _Store:
    def on_change(self, _cb):
        pass

    def all(self):
        return []


class _FakeApp:
    def __init__(self, tmp_path: Path, lang: str = "sv"):
        self._data_dir = tmp_path
        self.settings = {
            "theme": "dark",
            "language": lang,
            "font_size": 13,
            "db_path": str(tmp_path),
            "autostart": False,
        }
        self.invoices_store = _Store()
        self.suppliers_store = _Store()
        self.session_due_date = None
        self.session_due_date_str = ""
        self._invoices: list[dict] = [
            {
                "id": "inv-1",
                "supplier": "Pilkington Floatglas AB",
                "invoice_number": "F-1001",
                "invoice_type": "Faktura",
                "ocr": "1001",
                "date": "2026-10-01",
                "due_date": "2026-10-31",
                "payment_date": "",
                "total_amount": 2500.0,
                "currency": "SEK",
                "status": "Obetald",
                "category": "Glas",
                "reference": "Ref 1",
                "note": "Anteckning",
                "attachment": "",
            }
        ]
        self._suppliers: list[dict] = [
            {
                "id": "sup-1",
                "name": "Pilkington Floatglas AB",
                "org_number": "556123-4567",
                "bg": "512-3456",
                "pg": "123456-7",
                "iban": "SE4550000000058398257466",
                "bic": "ESSESESS",
                "payment_terms": 30,
                "ocr_same_as_invoice_number": False,
                "contact_person": "Anna",
                "email": "anna@example.com",
                "phone": "070-1234567",
                "address": "Gatan 1",
                "note": "Test",
            }
        ]

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)

    def set_setting(self, key, value):
        self.settings[key] = value

    def get_invoices(self):
        return [dict(r) for r in self._invoices]

    def get_active_invoices(self):
        return [dict(r) for r in self._invoices]

    def get_suppliers(self):
        return [dict(s) for s in self._suppliers]

    def get_archived_invoices(self):
        return []

    def add_invoice(self, data):
        rec = dict(data, id=f"inv-{len(self._invoices) + 1}")
        self._invoices.append(rec)
        return rec

    def data_load_summary(self):
        return "Redo"


@pytest.fixture(autouse=True)
def _reset_language():
    from ui import i18n

    i18n.set_language("sv")
    yield
    i18n.set_language("sv")


def test_1_1_empty_placeholder_tabs_hidden_and_shortcuts_contiguous(tmp_path):
    from app import DEFAULT_SHORTCUTS, SHORTCUT_LABELS
    from ui.main_window import MainWindow

    app_qt = _qapp()
    fake = _FakeApp(tmp_path)
    mw = MainWindow(fake)
    try:
        assert "payments" not in mw._tab_map
        assert "reports" not in mw._tab_map
        keys = [k for k, *_ in mw._TAB_DEFS]
        assert keys == [
            "dashboard",
            "invoices",
            "history",
            "suppliers",
            "import_tab",
            "log_tab",
            "settings_tab",
        ]
        assert mw.tabs.count() == 7
        assert "tab_betalningar" not in DEFAULT_SHORTCUTS
        assert "tab_rapporter" not in DEFAULT_SHORTCUTS
        assert "tab_betalningar" not in SHORTCUT_LABELS
        assert "tab_rapporter" not in SHORTCUT_LABELS
        assert [DEFAULT_SHORTCUTS[f"tab_{n}"] for n in (
            "dashboard", "fakturor", "historik", "leverantorer",
            "import", "logg", "installningar",
        )] == [f"Ctrl+{i}" for i in range(1, 8)]
    finally:
        mw.close()
        mw.deleteLater()
        app_qt.processEvents()


def test_1_2_scan_preview_panel_and_ctrl_return_shortcut(
    tmp_path, monkeypatch
):
    from PIL import Image, ImageDraw
    from ui.scan_import_view import ScanImportView

    app_qt = _qapp()
    fake = _FakeApp(tmp_path)
    img_path = tmp_path / "sample_inv.png"
    im = Image.new("RGB", (320, 460), "white")
    ImageDraw.Draw(im).rectangle((20, 20, 280, 100), fill="#0a4a7a")
    im.save(img_path)

    # Create 2-page PDF as well as PNG image
    pdf_path = tmp_path / "multipage_inv.pdf"
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    p1 = doc.new_page(width=400, height=600)
    p1.insert_text((40, 60), "Sida 1 - Fakturanr F-100")
    p2 = doc.new_page(width=400, height=600)
    p2.insert_text((40, 60), "Sida 2 - Specifikation")
    doc.save(str(pdf_path))
    doc.close()

    view = ScanImportView(app=fake)
    monkeypatch.setattr(view, "_refresh_invoices_view_only", lambda: None)
    monkeypatch.setattr(view, "_maybe_load_next_scan_batch", lambda: None)
    try:
        view.resize(1100, 760)
        view.show()
        app_qt.processEvents()

        # Preview starts visible and defaults to empty placeholder
        assert view._preview_panel.isVisible() is True
        assert view._preview_stack.currentIndex() == 0

        # Selecting 2-page PDF loads page 1/2, supports next/prev & zoom
        row_pdf = {
            "file": "multipage_inv.pdf",
            "_path": str(pdf_path),
            "_text": "Fakturanr F-100 Belopp 300 kr",
            "supplier": "Pilkington Floatglas AB",
            "invoice_number": "F-100",
            "date": "2026-10-01",
            "due_date": "2026-10-31",
            "ocr": "100",
            "total_amount": 300.0,
            "method": "ocr",
            "status": "redo",
            "missing": [],
        }
        row_img = {
            "file": "sample_inv.png",
            "_path": str(img_path),
            "_text": "Fakturanr F-150 Belopp 350 kr",
            "supplier": "Pilkington Floatglas AB",
            "invoice_number": "F-150",
            "date": "2026-10-01",
            "due_date": "2026-10-31",
            "ocr": "150",
            "total_amount": 350.0,
            "method": "ocr",
            "status": "redo",
            "missing": [],
        }
        row_txt = {
            "file": "(inklistrad text)",
            "_path": "",
            "_text": "Fakturanr F-200\nAtt betala: 450,00",
            "supplier": "Pilkington Floatglas AB",
            "invoice_number": "F-200",
            "date": "2026-10-01",
            "due_date": "2026-10-31",
            "ocr": "200",
            "total_amount": 450.0,
            "method": "manuell text",
            "status": "redo",
            "missing": [],
        }
        view._rows = [row_pdf, row_img, row_txt]
        view._refresh_table()

        view._tbl.selectRow(0)
        view._tbl.setCurrentCell(0, 0)
        app_qt.processEvents()
        assert view._preview_stack.currentIndex() == 1
        assert "multipage_inv.pdf" in view._lbl_preview_file.text()
        assert "1 / 2" in view._lbl_preview_page.text()
        assert view._btn_next_page.isEnabled() is True
        view._btn_next_page.click()
        app_qt.processEvents()
        assert "2 / 2" in view._lbl_preview_page.text()
        view._btn_prev_page.click()
        app_qt.processEvents()
        assert "1 / 2" in view._lbl_preview_page.text()
        view._btn_zoom_in.click()
        app_qt.processEvents()
        assert "%" in view._lbl_zoom_pct.text()
        view._btn_zoom_fit.click()
        app_qt.processEvents()

        # Selecting PNG image row loads image preview
        view._tbl.selectRow(1)
        view._tbl.setCurrentCell(1, 0)
        app_qt.processEvents()
        assert view._preview_stack.currentIndex() == 1
        assert "sample_inv.png" in view._lbl_preview_file.text()
        assert view._btn_preview_open.isEnabled() is True

        # Selecting text-only row falls back to text preview (stack index 2)
        view._tbl.selectRow(2)
        view._tbl.setCurrentCell(2, 0)
        app_qt.processEvents()
        assert view._preview_stack.currentIndex() == 2
        assert "F-200" in view._preview_text.toPlainText()

        # Toggle button collapses preview and persists setting
        view._btn_toggle_preview.click()
        app_qt.processEvents()
        assert view._preview_panel.isVisible() is False
        assert fake.settings["import_preview_visible"] is False

        # Ctrl+Return / Ctrl+Enter shortcuts are wired to single-row move
        assert view._sc_move_ready.key().toString() == "Ctrl+Return"
        assert view._sc_move_ready_numpad.key().toString() == "Ctrl+Enter"
        view._tbl.selectRow(0)
        view._tbl.setCurrentCell(0, 0)
        view._sc_move_ready.activated.emit()
        app_qt.processEvents()
        assert any(r["invoice_number"] == "F-100" for r in fake._invoices)
        assert [r["invoice_number"] for r in view._rows] == ["F-150", "F-200"]
    finally:
        view.close()
        view.deleteLater()
        app_qt.processEvents()


def test_1_3_invoices_and_suppliers_column_toggle_and_persistence(tmp_path):
    from ui.invoices_helpers import COL_KEYS as INV_COL_KEYS
    from ui.invoices_view import (
        INVOICE_COMPACT_HIDDEN_KEYS,
        InvoicesView,
    )
    from ui.suppliers_view import (
        COL_KEYS as SUP_COL_KEYS,
        SUPPLIER_COMPACT_HIDDEN_KEYS,
        SuppliersView,
    )

    app_qt = _qapp()
    fake = _FakeApp(tmp_path)

    iv = InvoicesView(fake)
    sv = SuppliersView(fake)
    try:
        iv.resize(1000, 720)
        sv.resize(1000, 720)
        iv.show()
        sv.show()
        app_qt.processEvents()

        # Default: all columns visible
        assert all(
            not iv._table.isColumnHidden(i)
            for i in range(iv._table.model().columnCount())
        )
        assert all(
            not sv._table.isColumnHidden(i)
            for i in range(sv._table.columnCount())
        )

        # Compact preset hides secondary columns & persists
        iv._set_compact_columns(True)
        sv._set_compact_columns(True)
        assert set(fake.settings["invoice_hidden_columns"]) == set(
            INVOICE_COMPACT_HIDDEN_KEYS
        )
        assert set(fake.settings["supplier_hidden_columns"]) == set(
            SUPPLIER_COMPACT_HIDDEN_KEYS
        )
        for idx, key in enumerate(INV_COL_KEYS, start=1):
            assert iv._table.isColumnHidden(idx) == (
                key in INVOICE_COMPACT_HIDDEN_KEYS
            )
        for idx, key in enumerate(SUP_COL_KEYS):
            assert sv._table.isColumnHidden(idx) == (
                key in SUPPLIER_COMPACT_HIDDEN_KEYS
            )

        # Locked core columns cannot be hidden
        iv._set_column_visible("supplier", False)
        iv._set_column_visible("total_amount", False)
        sv._set_column_visible("name", False)
        assert "supplier" not in iv._hidden_columns
        assert "total_amount" not in iv._hidden_columns
        assert "name" not in sv._hidden_columns

        # New view instance restores saved hidden columns
        iv2 = InvoicesView(fake)
        sv2 = SuppliersView(fake)
        try:
            assert iv2._hidden_columns == set(INVOICE_COMPACT_HIDDEN_KEYS)
            assert sv2._hidden_columns == set(SUPPLIER_COMPACT_HIDDEN_KEYS)
        finally:
            iv2.close()
            sv2.close()
            iv2.deleteLater()
            sv2.deleteLater()
            app_qt.processEvents()
    finally:
        iv.close()
        sv.close()
        iv.deleteLater()
        sv.deleteLater()
        app_qt.processEvents()


def test_1_4_english_ui_and_i18n_key_integrity(tmp_path):
    from ui import i18n
    from ui.invoices_helpers import ExportHistoryDialog, ExportHistoryManager
    from ui.invoices_view import InvoicesView
    from ui.main_window import MainWindow
    from ui.suppliers_view import SupplierDialog, SuppliersView

    # Verify every tr()/tr_list() call resolves and format args match
    fmt = string.Formatter()
    def _placeholders(text: str) -> set[str]:
        return {
            fname.split(".")[0].split("[")[0]
            for _, fname, _, _ in fmt.parse(text)
            if fname is not None
        }

    for key, entry in i18n._STRINGS.items():
        assert entry.get("sv", "").strip(), f"Empty sv for {key}"
        assert entry.get("en", "").strip(), f"Empty en for {key}"
        assert _placeholders(entry["sv"]) == _placeholders(entry["en"]), key

    missing_keys: list[tuple[str, int, str]] = []
    missing_kwargs: list[tuple[str, int, str, set[str]]] = []
    for py in (
        list((PROJECT_DIR / "ui").glob("*.py"))
        + list((PROJECT_DIR / "plugins").glob("*.py"))
        + [PROJECT_DIR / "app.py"]
    ):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", getattr(node.func, "attr", ""))
                if name in ("tr", "tr_list", "_tr") and node.args:
                    arg0 = node.args[0]
                    if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                        k = arg0.value
                        if k not in i18n._STRINGS:
                            missing_keys.append((py.name, node.lineno, k))
                        elif name in ("tr", "_tr"):
                            req = _placeholders(i18n._STRINGS[k]["sv"])
                            passed = {
                                kw.arg for kw in node.keywords if kw.arg
                            }
                            if req and not req.issubset(passed):
                                missing_kwargs.append(
                                    (py.name, node.lineno, k, req - passed)
                                )
    assert missing_keys == []
    assert missing_kwargs == []

    app_qt = _qapp()
    from PySide6.QtWidgets import QTableWidget

    i18n.set_language("en")
    fake = _FakeApp(tmp_path, lang="en")
    mw = MainWindow(fake)
    try:
        # English tab titles, status bar & shortcuts table headers
        assert mw.tabs.tabText(1) == "Invoices"
        assert mw.tabs.tabText(3) == "Suppliers"
        assert "InvoiceBundle" in mw._status_info_lbl.text()
        settings_scroll, _ = mw._tab_map["settings_tab"]
        sc_tbl = settings_scroll.widget().findChild(QTableWidget)
        assert sc_tbl is not None
        assert sc_tbl.horizontalHeaderItem(0).text() == "Action"
        assert sc_tbl.horizontalHeaderItem(1).text() == "Shortcut"

        # InvoicesView & SuppliersView in English + switch_to_suppliers
        iv = InvoicesView(fake)
        sv = SuppliersView(fake)
        mw.replace_tab_content("invoices", iv)
        mw.replace_tab_content("suppliers", sv)
        assert iv._btn_columns.text() == "Columns"
        assert sv._btn_columns.text() == "Columns"
        iv._switch_to_suppliers_tab()
        assert mw.tabs.tabText(mw.tabs.currentIndex()) == "Suppliers"

        sd = SupplierDialog(parent=None)
        try:
            assert sd.windowTitle() == "New supplier"
            assert sd.f_name.placeholderText() == "Required"
        finally:
            sd.close()
            sd.deleteLater()

        # ExportHistoryDialog headers in English (9 columns)
        mgr = ExportHistoryManager(tmp_path)
        hd = ExportHistoryDialog(
            parent=None, history=mgr, theme=mw.current_theme_dict()
        )
        try:
            assert hd.windowTitle() == "Export history & undo export"
            assert hd._table.columnCount() == 9
            assert hd._table.horizontalHeaderItem(0).text() == "Date"
            assert hd._table.horizontalHeaderItem(6).text() == "To pay"
            assert hd._table.horizontalHeaderItem(8).text() == "File"
        finally:
            hd.close()
            hd.deleteLater()
    finally:
        mw.close()
        mw.deleteLater()
        app_qt.processEvents()
