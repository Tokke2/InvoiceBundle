"""Layout — Fakturor-sidan: knappar till vänster, fakturor till höger.

Tvåspaltslayouten ska aldrig låta kontrollerna klämma ihop eller
täcka fakturatabellen: i ett smalt fönster ska vänsterspalten ha
fast bredd (och egen rullning), tabellen få resten av bredden och
kolumnerna förbli läsbara med horisontell rullning.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "ui"),
           str(PROJECT_DIR / "plugins")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QScrollArea

from ui.i18n import set_language
from ui.invoices_helpers import (
    COL_KEYS,
    COL_WIDTHS,
    DATE_COLUMN_KEYS,
    date_column_width,
)
from ui.invoices_view import InvoicesView


def _qapp():
    return QApplication.instance() or QApplication([])


def _row(i, status="Obetald"):
    return {
        "id": str(i), "supplier": "Pilkington",
        "invoice_number": f"F-{i:03d}", "ocr": "12345",
        "date": "2026-09-01", "due_date": "2026-09-15",
        "total_amount": 100.0, "status": status,
        "attachment": "",
    }


class _Store:
    def on_change(self, _cb):
        pass


class _FakeApp:
    def __init__(self, tmp_path, rows):
        self._rows = rows
        self.settings = {"db_path": str(tmp_path)}
        self.invoices_store = _Store()
        self.suppliers_store = _Store()
        self.session_due_date = None
        self.session_due_date_str = ""

    def get_invoices(self):
        return [dict(r) for r in self._rows]

    def get_suppliers(self):
        return [{"id": "s1", "name": "Pilkington"}]

    def get_setting(self, key, default=None):
        return default

    def set_setting(self, key, value):
        pass


def _make_view(tmp_path):
    set_language("sv")
    rows = [_row(1), _row(2), _row(3)]
    view = InvoicesView(_FakeApp(tmp_path, rows))
    view.setWindowTitle("Fakturor")
    return view


def _rect_in(widget, view):
    """(topp-vänster, botten-höger) för widget mätt i view-koordinater."""
    parent = widget.parentWidget()
    if parent is view or parent is None:
        geo = widget.geometry()
        return geo.topLeft(), geo.bottomRight()
    p_tl, _p_br = _rect_in(parent, view)
    geo = widget.geometry()
    return p_tl + geo.topLeft(), p_tl + geo.bottomRight()


def test_buttons_left_table_right_no_overlap(tmp_path):
    app = _qapp()
    view = _make_view(tmp_path)
    view.resize(1600, 900)
    view.show()
    app.processEvents()
    try:
        scroll = view.findChild(QScrollArea, "SideScroll")
        assert scroll is not None
        s_tl, s_br = _rect_in(scroll, view)
        t_tl, _t_br = _rect_in(view._table, view)
        assert s_br.x() < t_tl.x()
        assert view._right_pane is not None
        assert t_tl.x() >= _rect_in(view._right_pane, view)[0].x()

        right_left = _rect_in(view._right_pane, view)[0].x()
        for btn in (view._btn_add, view._btn_edit,
                    view._btn_export_selected, view._btn_export_all):
            _b_tl, b_br = _rect_in(btn, view)
            assert b_br.x() <= right_left, btn.text()
    finally:
        view.close()


def test_narrow_window_keeps_columns_readable_and_scrollable(tmp_path):
    app = _qapp()
    view = _make_view(tmp_path)
    view.resize(760, 700)  # smalt fönster, som bredvid annat program
    view.show()
    app.processEvents()
    try:
        scroll = view.findChild(QScrollArea, "SideScroll")
        assert scroll is not None
        # Vänsterspalten får inte växa över tabellen.
        assert scroll.width() <= 372
        assert (_rect_in(scroll, view)[1].x()
                < _rect_in(view._table, view)[0].x())

        # Kolumnerna kläms INTE: föredragna bredder behålls, och den
        # horisontella rullisten finns där för smala fönster.
        widths = [view._table.columnWidth(i)
                  for i in range(view._table.model().columnCount())]
        assert widths[0] == 44
        # Datumskolumnerna är bredare än sina grundvikter: annars
        # klipptes datumet till bara årtalet ("2021-…").
        expected = [
            max(width, date_column_width()) if key in DATE_COLUMN_KEYS
            else width
            for key, width in zip(COL_KEYS, COL_WIDTHS)
        ]
        assert widths[1:] == expected
        assert view._table.horizontalScrollBarPolicy() == (
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        assert sum(widths) >= 1186
    finally:
        view.close()


def test_date_columns_show_the_whole_date(tmp_path):
    """Datum och Förfaller får aldrig visas som bara "2021-…"."""
    from PySide6.QtGui import QFontMetrics

    from ui.typography import make_tabular_font, scaled_point_size

    app = _qapp()
    view = _make_view(tmp_path)
    view.resize(760, 700)
    view.show()
    app.processEvents()
    try:
        metrics = QFontMetrics(
            make_tabular_font(scaled_point_size(12), bold=True)
        )
        sample = "2021-05-03"
        needed = metrics.horizontalAdvance(sample) + 8
        for column, key in enumerate(COL_KEYS, start=1):
            if key not in DATE_COLUMN_KEYS:
                continue
            width = view._table.columnWidth(column)
            assert width >= needed, (
                f"{key}: {width} px räcker inte för {sample!r} "
                f"({needed} px) — datumet kapas till årtalet"
            )
            elided = metrics.elidedText(
                sample, Qt.TextElideMode.ElideRight, width
            )
            assert elided == sample
    finally:
        view.close()


def test_manual_add_opens_dialog_without_top_supplier_selection(
        tmp_path, monkeypatch):
    _qapp()
    import ui.invoices_view as invoices_module

    app = _FakeApp(tmp_path, [])
    added = []
    app.add_invoice = lambda data: added.append(dict(data))
    captured = {}

    class _AcceptedDialog:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def exec(self):
            from PySide6.QtWidgets import QDialog
            return QDialog.DialogCode.Accepted

        def get_data(self):
            return {
                "invoice_number": "MANUAL-1",
                "supplier": "Pilkington",
                "total_amount": 100.0,
            }

    monkeypatch.setattr(invoices_module, "InvoiceDialog", _AcceptedDialog)
    view = InvoicesView(app)
    try:
        assert view._selected_supplier == ""
        view._add_invoice()
        assert captured["supplier_name"] == ""
        assert captured["supplier_names"] == ["Pilkington"]
        assert added and added[0]["supplier"] == "Pilkington"
    finally:
        view.close()


def test_table_gets_remaining_width(tmp_path):
    app = _qapp()
    view = _make_view(tmp_path)
    view.resize(1800, 900)
    view.show()
    app.processEvents()
    try:
        scroll = view.findChild(QScrollArea, "SideScroll")
        assert scroll is not None
        # Tabellen är bredare än vänsterspalten och tar resten.
        assert view._table.width() > scroll.width()
        assert view._table.width() > 900
    finally:
        view.close()
