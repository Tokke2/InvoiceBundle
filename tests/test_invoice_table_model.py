# -*- coding: utf-8 -*-
"""Regression tests for the model-backed Invoices table."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_invoice_model_exposes_rows_sort_values_and_export_checks():
    _qapp()
    from PySide6.QtCore import Qt, QAbstractTableModel
    from ui.invoice_table_model import InvoiceTableModel, SORT_ROLE
    from ui.invoices_helpers import COL_KEYS
    from ui.typography import DEFAULT_FONT_SIZE, set_current_font_size

    model = InvoiceTableModel()
    model.set_rows([
        {"id": "b", "supplier": "Beta", "invoice_number": "2",
         "total_amount": 10.0, "status": "Obetald"},
        {"id": "a", "supplier": "Alpha", "invoice_number": "1",
         "total_amount": 125.0, "status": "Förfallen"},
    ])

    assert isinstance(model, QAbstractTableModel)
    assert model.rowCount() == 2
    assert model.columnCount() > 2
    amount_col = 1 + COL_KEYS.index("total_amount")
    amount_index = model.index(0, amount_col)
    assert amount_index.data(Qt.ItemDataRole.DisplayRole)
    assert amount_index.data(SORT_ROLE) == 10.0
    number_index = model.index(0, 1 + COL_KEYS.index("invoice_number"))
    try:
        assert number_index.data(Qt.ItemDataRole.FontRole).pointSize() == 12
        set_current_font_size(17)
        assert number_index.data(Qt.ItemDataRole.FontRole).pointSize() == 16
    finally:
        set_current_font_size(DEFAULT_FONT_SIZE)

    check_index = model.index(0, 0)
    assert check_index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked
    assert model.setData(
        check_index, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole
    )
    assert check_index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
    assert check_index.data(Qt.ItemDataRole.UserRole) == "b"


def test_supplier_count_and_density_controls_preserve_canonical_name(tmp_path):
    _qapp()
    from PySide6.QtCore import Qt
    from ui.design import TABLE_ROW_HEIGHT_COMPACT, TABLE_ROW_HEIGHT_COMFORTABLE
    from ui.invoices_view import InvoicesView
    from ui.typography import apply_font_size

    rows = [
        {"id": "p1", "supplier": "Pilkington", "invoice_number": "P-1",
         "total_amount": 10.0, "status": "Obetald"},
        {"id": "p2", "supplier": "Pilkington", "invoice_number": "P-2",
         "total_amount": 20.0, "status": "Obetald"},
        {"id": "d1", "supplier": "Direktglas", "invoice_number": "D-1",
         "total_amount": 30.0, "status": "Obetald"},
    ]

    class Store:
        def on_change(self, _callback):
            pass

    class App:
        settings = {"db_path": str(tmp_path)}
        invoices_store = Store()
        suppliers_store = Store()
        session_due_date = None
        session_due_date_str = ""

        def __init__(self):
            self.saved = {}

        def get_invoices(self):
            return [dict(row) for row in rows]

        def get_suppliers(self):
            return [{"name": "Pilkington"}, {"name": "Direktglas"}]

        def get_setting(self, key, default=None):
            return self.saved.get(key, default)

        def set_setting(self, key, value):
            self.saved[key] = value

    app = App()
    view = InvoicesView(app)
    try:
        supplier_index = view._sup_selector.findData("Pilkington")
        assert supplier_index >= 0
        assert view._sup_selector.itemText(supplier_index).endswith("(2)")
        count_tip = view._sup_selector.itemData(
            supplier_index, Qt.ItemDataRole.ToolTipRole
        )
        assert "2" in count_tip

        assert view._row_density == "comfortable"
        assert view._table.verticalHeader().defaultSectionSize() == TABLE_ROW_HEIGHT_COMFORTABLE
        compact = view._density_selector.findData("compact")
        view._density_selector.setCurrentIndex(compact)
        assert view._row_density == "compact"
        assert view._table.verticalHeader().defaultSectionSize() == TABLE_ROW_HEIGHT_COMPACT
        assert app.saved["invoice_table_density"] == "compact"

        view._sup_selector.setCurrentIndex(supplier_index)
        assert view._selected_supplier == "Pilkington"
        assert {row["id"] for row in view._apply_filters()} == {"p1", "p2"}

        qt_app = _qapp()
        apply_font_size(qt_app, 17)
        assert view._table.verticalHeader().defaultSectionSize() == round(
            TABLE_ROW_HEIGHT_COMPACT * 17 / 13
        )
        apply_font_size(qt_app, 13)
        assert view._table.verticalHeader().defaultSectionSize() == TABLE_ROW_HEIGHT_COMPACT
    finally:
        view.close()
