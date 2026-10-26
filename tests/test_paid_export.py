# -*- coding: utf-8 -*-
"""
Tester: betald-markerade fakturor ska bort ur exporten.

"Exportera alla" (och dess knappräkning) bygger på
InvoicesView._get_exportable(). Där hör Betald/Arkiverad/
Makulerad aldrig hemma — markerar man en faktura som betald
ska den inte kunna hamna i en betal-PDF av misstag.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "ui"),
           str(PROJECT_DIR / "plugins")):
    if _d not in sys.path:
        sys.path.insert(0, _d)


def _qapp():
    from PySide6.QtWidgets import QApplication
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


class _Exporter:
    def __init__(self):
        self.calls = []

    def export_invoice_list(self, rows, filename="", **kw):
        self.calls.append((list(rows), filename, kw))
        return {
            "success": True, "file_path": filename,
            "payment_date": kw.get("payment_date", ""),
            "attachments_included": 0,
        }


class _History:
    def __init__(self):
        self.calls = []

    def record_export(self, **kw):
        self.calls.append(kw)

    def count(self):
        return len(self.calls)


def _fake_box():
    from PySide6.QtWidgets import QMessageBox

    class _FakeBox(QMessageBox):
        def exec(self):
            return 0

        def clickedButton(self):
            return None

    return _FakeBox


def test_paid_and_archived_never_reach_export(tmp_path, monkeypatch):
    _qapp()
    import ui.invoices_view as iv
    from ui.invoices_view import InvoicesView

    rows = [
        _row(1),
        _row(2, status="Betald"),
        _row(3, status="Arkiverad"),
        _row(4, status="Makulerad"),
        _row(5, status="Förfallen"),
    ]

    class FakeApp:
        settings = {"db_path": str(tmp_path)}
        invoices_store = _Store()
        suppliers_store = _Store()
        session_due_date = None
        session_due_date_str = ""
        pdf_exporter = _Exporter()
        archived: list = []

        def get_invoices(self):
            return [dict(r) for r in rows]

        def get_suppliers(self):
            return [{"id": "s1", "name": "Pilkington"}]

        def get_setting(self, key, default=None):
            return default

        def set_setting(self, key, value):
            pass

        def update_invoice(self, rid, fields):
            self.archived.append((rid, fields))

    app = FakeApp()
    view = InvoicesView(app)
    try:
        # Urvalet till "Exportera alla": bara de obetalda
        assert [r["id"] for r in view._get_exportable()] == ["1", "5"]

        # ...och det är exakt det som når exportfilen
        view._export_history = _History()
        view._ask_payment_date_for_export = (
            lambda **kw: ("2026-09-18", True)
        )
        monkeypatch.setattr(iv, "QMessageBox", _fake_box())
        monkeypatch.setattr(
            iv, "build_export_path",
            lambda suppliers: (tmp_path, "fakturalista_120000.pdf"),
        )
        view._export_invoices(view._get_exportable(), confirm=False)

        sent = [r["id"] for c in app.pdf_exporter.calls for r in c[0]]
        assert sent == ["1", "5"]
        assert len(app.pdf_exporter.calls) == 1
        # Efter lyckad export: Betald (inte Arkiverad) med
        # exportens betalningsdatum — posterna hamnar i Historik
        # och leverantörens JSON i data/betalda/.
        paid_ids = {
            rid for rid, f in app.archived
            if f.get("status") == "Betald"
        }
        assert paid_ids == {"1", "5"}
        assert all(
            f.get("payment_date") == "2026-09-18"
            for _r, f in app.archived
        )
    finally:
        view.close()


def _selected_app(tmp_path, rows):
    class FakeApp:
        settings = {"db_path": str(tmp_path)}
        invoices_store = _Store()
        suppliers_store = _Store()
        session_due_date = None
        session_due_date_str = ""
        pdf_exporter = _Exporter()
        archived: list = []

        def get_invoices(self):
            return [dict(r) for r in rows]

        def get_suppliers(self):
            return [{"id": "s1", "name": "Pilkington"}]

        def get_setting(self, key, default=None):
            return default

        def set_setting(self, key, value):
            pass

        def update_invoice(self, rid, fields):
            self.archived.append((rid, fields))

    return FakeApp()


def test_export_selected_only_exports_marked_rows(
        tmp_path, monkeypatch):
    """Markerade rader exporteras — resten lämnas orörda."""
    _qapp()
    import ui.invoices_view as iv
    from PySide6.QtCore import QItemSelectionModel
    from ui.invoices_view import InvoicesView

    rows = [_row(i) for i in range(1, 6)]
    app = _selected_app(tmp_path, rows)
    view = InvoicesView(app)
    try:
        view._export_history = _History()
        view._ask_payment_date_for_export = (
            lambda **kw: ("2026-09-18", True)
        )

        class _YesBox(_fake_box()):
            @staticmethod
            def question(*args, **kwargs):
                from PySide6.QtWidgets import QMessageBox as _MB
                return _MB.StandardButton.Yes

        monkeypatch.setattr(iv, "QMessageBox", _YesBox)
        monkeypatch.setattr(
            iv, "build_export_path",
            lambda suppliers: (tmp_path, "fakturalista_120000.pdf"),
        )
        # Markera två rader (radmarkeringen ÄR exportvalet)
        view._table.selectRow(1)
        model = view._table.selectionModel()
        flags = (
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows
        )
        model.select(view._table.model().index(3, 0), flags)
        marked = set(view._selected_ids())
        assert len(marked) == 2
        assert view._btn_export_selected.isEnabled()
        assert {
            r["id"] for r in view._get_selected_exportable()
        } == marked

        view._export_selected_pdf()

        sent = {
            r["id"] for c in app.pdf_exporter.calls for r in c[0]
        }
        assert sent == marked
        paid = {
            rid for rid, f in app.archived
            if f.get("status") == "Betald"
        }
        assert paid == marked
    finally:
        view.close()


def test_marked_selection_survives_filter_and_refresh(tmp_path):
    """Exportmarkeringen bor per id: filterbyte/refresh tappar
    den inte, och valda rader förblir valda när de syns igen."""
    _qapp()
    from PySide6.QtCore import QItemSelectionModel
    from ui.invoices_view import InvoicesView

    rows = [_row(i) for i in range(1, 6)]
    app = _selected_app(tmp_path, rows)
    view = InvoicesView(app)
    try:
        view._table.selectRow(0)
        model = view._table.selectionModel()
        flags = (
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows
        )
        model.select(view._table.model().index(2, 0), flags)
        marked = set(view._selected_ids())
        assert len(marked) == 2

        # Filtrera bort allt utom en rad — markeringen behålls
        view._search.setText("F-003")
        view._do_refresh()
        assert marked <= view._marked_export_ids

        # Tillbaka till ofiltrerat: samma rader markerade igen
        view._search.setText("")
        view._do_refresh()
        assert set(view._selected_ids()) == marked
        assert {
            r["id"] for r in view._get_selected_exportable()
        } == marked
    finally:
        view.close()
