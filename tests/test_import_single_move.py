# -*- coding: utf-8 -*-
"""Tests for single-row right-click mark-ready & move to Invoices tab."""
from __future__ import annotations

import os
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


_SUPPLIERS = [
    {"name": "Annan AB"},
    {"name": "Testbolaget AB"},
]


class _Core:
    def __init__(self):
        self.created: list[dict] = []

    def get_suppliers(self):
        return list(_SUPPLIERS)

    def get_invoices(self):
        return list(self.created)

    def add_invoice(self, data):
        record = dict(data, id=f"inv-{len(self.created) + 1}")
        self.created.append(record)
        return record

    def get_setting(self, key, default=None):
        return default


@pytest.fixture(autouse=True)
def _isolated_i18n():
    from ui import i18n

    i18n.set_language("sv")
    yield
    i18n.set_language("sv")


def _view(tmp_path):
    from ui.scan_import_view import ScanImportView

    core = _Core()
    view = ScanImportView(app=core)
    view._templates_file = lambda: tmp_path / "invoice_templates.json"
    view._learning_file = lambda: tmp_path / "match_learning.json"
    view._parked_file = lambda: tmp_path / "parked_invoices.json"
    return view, core


def _ready_row(**overrides):
    base = {
        "file": "f1.pdf",
        "_path": "",
        "_text": "Fakturanr F-101 Belopp 500,00 SEK",
        "supplier": "Testbolaget AB",
        "invoice_number": "F-101",
        "date": "2026-10-01",
        "due_date": "2026-10-31",
        "ocr": "101",
        "total_amount": 500.0,
        "method": "ocr",
        "status": "redo",
        "missing": [],
    }
    base.update(overrides)
    return base


def test_context_menu_includes_single_move_action_sv_and_en(
    tmp_path, monkeypatch
):
    _qapp()
    from ui import i18n
    import ui.scan_import_view as sv

    menus = []

    class FakeMenu:
        def __init__(self, parent=None):
            self.labels = []
            menus.append(self)

        def addAction(self, label, slot=None):  # noqa: N802
            self.labels.append(str(label))
            return None

        def addSeparator(self):  # noqa: N802
            pass

        def exec(self, pos):  # noqa: A003
            pass

    monkeypatch.setattr(sv, "QMenu", FakeMenu)
    view, _core = _view(tmp_path)
    try:
        view._rows = [_ready_row()]
        view._refresh_table()

        i18n.set_language("sv")
        view._table_context_menu(view._tbl.viewport().rect().center())
        assert any(
            "Markera klar" in x and "Fakturor" in x
            for x in menus[-1].labels
        ), menus[-1].labels

        i18n.set_language("en")
        view._table_context_menu(view._tbl.viewport().rect().center())
        assert any(
            "Mark ready" in x and "Invoices" in x
            for x in menus[-1].labels
        ), menus[-1].labels
    finally:
        view.close()


def test_mark_ready_moves_only_single_clicked_row_keeps_others(
    tmp_path, monkeypatch
):
    _qapp()
    view, core = _view(tmp_path)
    calls = {"refresh_only": 0, "switch_tab": 0, "next_batch": 0}
    monkeypatch.setattr(
        view,
        "_refresh_invoices_view_only",
        lambda: calls.__setitem__("refresh_only", calls["refresh_only"] + 1),
    )
    monkeypatch.setattr(
        view,
        "_show_invoices_tab",
        lambda: calls.__setitem__("switch_tab", calls["switch_tab"] + 1),
    )
    monkeypatch.setattr(
        view,
        "_maybe_load_next_scan_batch",
        lambda: calls.__setitem__("next_batch", calls["next_batch"] + 1),
    )
    try:
        r0 = _ready_row(file="first.pdf", invoice_number="F-100", total_amount=100.0)
        r1 = _ready_row(file="second.pdf", invoice_number="F-200", total_amount=200.0)
        r2 = _ready_row(file="third.pdf", invoice_number="F-300", total_amount=300.0)
        view._rows = [r0, r1, r2]
        view._refresh_table()

        # Select all 3 rows, then move ONLY row_index=1 (as right-click does).
        view._tbl.selectAll()
        ok = view._mark_ready_and_move_selected(row_index=1)
        assert ok is True

        assert len(core.created) == 1
        assert core.created[0]["invoice_number"] == "F-200"
        assert [r["file"] for r in view._rows] == ["first.pdf", "third.pdf"]
        assert calls["refresh_only"] == 1
        assert calls["switch_tab"] == 0
        assert calls["next_batch"] == 1
        assert "second.pdf" in view._lbl_status.text()
    finally:
        view.close()


def test_mark_ready_without_row_index_still_moves_only_one_row(
    tmp_path, monkeypatch
):
    _qapp()
    view, core = _view(tmp_path)
    monkeypatch.setattr(view, "_refresh_invoices_view_only", lambda: None)
    monkeypatch.setattr(view, "_maybe_load_next_scan_batch", lambda: None)
    try:
        r0 = _ready_row(file="a.pdf", invoice_number="A-1")
        r1 = _ready_row(file="b.pdf", invoice_number="B-2")
        view._rows = [r0, r1]
        view._refresh_table()
        view._tbl.selectAll()
        view._tbl.setCurrentCell(1, 0)

        assert view._mark_ready_and_move_selected() is True
        assert [rec["invoice_number"] for rec in core.created] == ["B-2"]
        assert [r["file"] for r in view._rows] == ["a.pdf"]
    finally:
        view.close()


def test_mark_ready_incomplete_row_opens_row_dialog(tmp_path, monkeypatch):
    _qapp()
    view, core = _view(tmp_path)
    opened = []
    monkeypatch.setattr(
        view, "_open_row_dialog", lambda: opened.append(view._selected_rows())
    )
    try:
        r0 = _ready_row(file="ok.pdf", invoice_number="OK-1")
        r1 = _ready_row(
            file="incomplete.pdf",
            invoice_number="",
            missing=["fakturanr"],
            status="saknas: fakturanr",
        )
        view._rows = [r0, r1]
        view._refresh_table()

        assert view._mark_ready_and_move_selected(row_index=1) is False
        assert opened == [[1]]
        assert len(core.created) == 0
        assert len(view._rows) == 2
    finally:
        view.close()


def test_mark_ready_uncertain_row_aborts_if_user_declines(
    tmp_path, monkeypatch
):
    _qapp()
    view, core = _view(tmp_path)
    asked = []
    monkeypatch.setattr(
        view,
        "_ask_user_for_match",
        lambda row: asked.append(row["file"]) or False,
    )
    try:
        r0 = _ready_row(file="uncertain.pdf", match_uncertain=True)
        r1 = _ready_row(file="other.pdf", invoice_number="F-999")
        view._rows = [r0, r1]
        view._refresh_table()

        assert view._mark_ready_and_move_selected(row_index=0) is False
        assert asked == ["uncertain.pdf"]
        assert len(core.created) == 0
        assert len(view._rows) == 2
    finally:
        view.close()


def test_mark_ready_possible_duplicate_respects_user_choice(
    tmp_path, monkeypatch
):
    _qapp()
    import ui.scan_import_view as sv

    view, core = _view(tmp_path)
    monkeypatch.setattr(view, "_refresh_invoices_view_only", lambda: None)
    monkeypatch.setattr(view, "_maybe_load_next_scan_batch", lambda: None)
    try:
        # First invoice already exists in registry.
        existing = _ready_row(file="dup.pdf", invoice_number="F-101")
        core.add_invoice(view._invoice_data_from_row(existing))
        view._rows = [dict(existing), _ready_row(file="other.pdf", invoice_number="F-202")]
        view._refresh_table()

        monkeypatch.setattr(
            sv.QMessageBox,
            "question",
            lambda *a, **kw: sv.QMessageBox.StandardButton.No,
        )
        assert view._mark_ready_and_move_selected(row_index=0) is False
        assert len(core.created) == 1
        assert len(view._rows) == 2

        monkeypatch.setattr(
            sv.QMessageBox,
            "question",
            lambda *a, **kw: sv.QMessageBox.StandardButton.Yes,
        )
        assert view._mark_ready_and_move_selected(row_index=0) is True
        assert len(core.created) == 2
        assert [r["file"] for r in view._rows] == ["other.pdf"]
    finally:
        view.close()


def test_mark_ready_scan_error_warns_and_does_not_move(tmp_path, monkeypatch):
    _qapp()
    import ui.scan_import_view as sv

    view, core = _view(tmp_path)
    warned = []
    monkeypatch.setattr(
        sv.QMessageBox,
        "warning",
        lambda *a, **kw: warned.append(a[1:]),
    )
    try:
        view._rows = [_ready_row(file="broken.pdf", _scan_error="read failed")]
        view._refresh_table()

        assert view._mark_ready_and_move_selected(row_index=0) is False
        assert warned
        assert len(core.created) == 0
        assert len(view._rows) == 1
    finally:
        view.close()
