# -*- coding: utf-8 -*-
"""
Tester: borttagning = riktig radering, ALDRIG betald/exporterad.

- Delete-tangenten tar bort markerad faktura (med fokusskydd för
  textfält — Delete i ett sökfält ska radera text, inte fakturor).
- Knappen "Rensa alla fakturor" tar bort ALLA aktiva fakturor ur
  registret via FakeApp.delete_invoice, över alla leverantörer.
- Ingen av vägarna får sätta Betald-status eller arkivera —
  borttaget är borta, inte betalt.
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


def _row(i, supplier=None):
    return {
        "id": str(i), "supplier": supplier or f"Lev-{i}",
        "invoice_number": f"F-{i:03d}", "ocr": "12345",
        "date": "2026-09-01", "due_date": "2026-09-15",
        "total_amount": 100.0 * i, "status": "Obetald",
        "attachment": "",
    }


class _Store:
    def on_change(self, _cb):
        pass


class _FakeApp:
    """Fake backend: deleted/paid spåras för att kunna bevisa
    att borttagning ALDRIG blir en betald-markering."""

    settings = {"db_path": "/tmp"}
    invoices_store = _Store()
    suppliers_store = _Store()
    session_due_date = None
    session_due_date_str = ""

    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]
        self.deleted: list = []
        self.paid: list = []

    def get_invoices(self):
        return [dict(r) for r in self.rows]

    def get_active_invoices(self):
        return [dict(r) for r in self.rows]

    def get_suppliers(self):
        return [{"id": "s1", "name": "Pilkington"}]

    def get_setting(self, key, default=None):
        return default

    def set_setting(self, key, value):
        pass

    def delete_invoice(self, rid):
        self.deleted.append(rid)
        self.rows = [r for r in self.rows if str(r["id"]) != str(rid)]
        return True

    def update_invoice(self, rid, fields):
        # En betald-/arkiv-markering skulle hamna här — får ALDRIG ske.
        if fields.get("status") in ("Betald", "Arkiverad"):
            self.paid.append((rid, fields))
        return None


def _fake_box(answer=None):
    from PySide6.QtWidgets import QMessageBox

    class _FakeBox(QMessageBox):
        def exec(self):
            return 0

        def clickedButton(self):
            return None

    if answer is not None:
        class _AnswerBox(_FakeBox):
            @staticmethod
            def question(*args, **kwargs):
                from PySide6.QtWidgets import QMessageBox as _MB
                return (
                    _MB.StandardButton.Yes
                    if answer == "yes"
                    else _MB.StandardButton.No
                )

        return _AnswerBox
    return _FakeBox


def _mk_view(tmp_path, monkeypatch, iv, answer):
    from ui.invoices_view import InvoicesView
    rows = [_row(1), _row(2), _row(3)]
    app = _FakeApp(rows)
    monkeypatch.setattr(iv, "QMessageBox", _fake_box(answer))
    view = InvoicesView(app)
    return view, app


def test_delete_all_removes_everything_without_paid(tmp_path, monkeypatch):
    """Rensa alla: alla aktiva försvinner via delete — ingen betald,
    ingen kvar i tabellen, knappen slår av sig själv i tom lista."""
    _qapp()
    import ui.invoices_view as iv

    view, app = _mk_view(tmp_path, monkeypatch, iv, "yes")
    try:
        assert view._table.rowCount() == 3
        assert view._btn_delete_all.isEnabled()
        view._delete_all_invoices()
        assert sorted(app.deleted) == ["1", "2", "3"]
        assert app.paid == []                      # aldrig Betald!
        assert app.rows == []
        assert view._table.rowCount() == 0
        assert not view._btn_delete_all.isEnabled()
    finally:
        view.close()


def test_delete_all_declined_removes_nothing(tmp_path, monkeypatch):
    """Svarar man Nej i bekräftelsen ska ingenting tas bort."""
    _qapp()
    import ui.invoices_view as iv

    view, app = _mk_view(tmp_path, monkeypatch, iv, "no")
    try:
        view._delete_all_invoices()
        assert app.deleted == []
        assert app.paid == []
        assert len(app.rows) == 3
    finally:
        view.close()


def test_delete_all_spans_all_suppliers(tmp_path, monkeypatch):
    """Rensa alla gäller hela registret — även fakturor som inte
    hör till den leverantör som råkar visas överst."""
    _qapp()
    import ui.invoices_view as iv
    from ui.invoices_view import InvoicesView

    rows = [_row(1, "Alpha"), _row(2, "Beta"), _row(3, "Gamma")]
    app = _FakeApp(rows)
    monkeypatch.setattr(iv, "QMessageBox", _fake_box("yes"))
    view = InvoicesView(app)
    try:
        view._delete_all_invoices()
        assert sorted(app.deleted) == ["1", "2", "3"]
        assert app.paid == []
    finally:
        view.close()


def test_delete_key_deletes_selected_not_paid(tmp_path, monkeypatch):
    """Delete-tangenten tar bort markerad faktura ur registret —
    den markeras inte betald och hamnar inte i någon historik."""
    _qapp()
    import ui.invoices_view as iv
    from PySide6.QtCore import Qt

    view, app = _mk_view(tmp_path, monkeypatch, iv, "yes")
    try:
        # Markera rad 2 (id "2") — radmarkering är "vald faktura"
        view._table.selectRow(1)
        assert view._selected_invoice()["id"] == "2"
        # Säkerställ att ingen dialog/fält från en tidigare test
        # äger fokus (i blandade sviter lämnas ibland dialoger kvar)
        from PySide6.QtWidgets import QApplication
        for w in QApplication.topLevelWidgets():
            if w is not view and w.isVisible() and hasattr(w, "close"):
                w.close()
        view._table.setFocus()
        QApplication.processEvents()
        view._on_delete_key()
        assert app.deleted == ["2"]
        assert app.paid == []
        assert [r["id"] for r in app.rows] == ["1", "3"]
    finally:
        view.close()


def test_delete_key_noop_inside_text_field(tmp_path, monkeypatch):
    """Fokusskydd: Delete i ett textfält får aldrig radera en faktura."""
    _qapp()
    import ui.invoices_view as iv
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLineEdit

    view, app = _mk_view(tmp_path, monkeypatch, iv, "yes")
    try:
        view.show()
        view._table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        field = QLineEdit(view)
        field.setFocus()
        # Styr focusWidget direkt: i blandade sviter kan en annan
        # tests dialoger ha fokus kvar och Qt:s focusWidget()
        # returnerar då dem — vakten ska ändå bevisas här.
        monkeypatch.setattr(
            iv.QApplication, "focusWidget", staticmethod(lambda: field)
        )
        view._on_delete_key()
        assert app.deleted == []
        assert app.paid == []
        assert len(app.rows) == 3
    finally:
        view.close()
