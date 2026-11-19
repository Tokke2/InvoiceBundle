# -*- coding: utf-8 -*-
"""
Tester: delavräkning av kreditfakturor — kvarvarande belopp behålls.

När en kreditfaktura (t.ex. -132 000) kopplas till fakturor (t.ex. 10 st
om 53 550) ska kvarvarande kredit (-78 450) ligga kvar som obetalt på
krediten till nästa koppling — både vid export till betal-PDF,
Markera betald, Koppla kredit-dialogen och Autoexport, samt kunna
ångras och återställas via Exporthistoriken.
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

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QMessageBox, QPushButton


def _qapp():
    return QApplication.instance() or QApplication([])


def _isolated_app(data_dir: Path):
    import app as appmod

    data_dir.mkdir(parents=True, exist_ok=True)
    changelog = appmod.ChangeLog(data_dir / "changelog.json")
    inv_store = appmod.DataStore(
        "invoices", data_dir, appmod.INVOICE_SCHEMA, changelog
    )
    sup_store = appmod.DataStore(
        "suppliers", data_dir, appmod.SUPPLIER_SCHEMA, changelog
    )
    archive = appmod.SupplierArchiveStore(
        data_dir / appmod.ARCHIVE_DIR_NAME, changelog
    )
    engine = appmod.InvoiceEngine(inv_store, archive)

    class _App:
        def __init__(self) -> None:
            self.settings = {"db_path": str(data_dir)}
            self.invoices_store = inv_store
            self.suppliers_store = sup_store
            self.invoices_archive = archive
            self.invoices = engine
            self.session_due_date = None
            self.session_due_date_str = ""
            self.pdf_exporter = None

        def get_setting(self, key: str, default=None):
            return self.settings.get(key, default)

        def set_setting(self, key: str, value) -> None:
            self.settings[key] = value

        def get_suppliers(self):
            return self.suppliers_store.all()

        def add_supplier(self, data: dict):
            return self.suppliers_store.add(data)

        def get_invoices(self):
            return self.invoices.all()

        def get_active_invoices(self):
            return self.invoices.main_records()

        def get_archived_invoices(self):
            return self.invoices.archived_records()

        def add_invoice(self, data: dict):
            return self.invoices.add(data)

        def update_invoice(self, rid: str, data: dict):
            return self.invoices.update(rid, data)

    return _App()


def _build_10_invoices_and_132k_credit(engine):
    credit = engine.add({
        "supplier": "Demo Lev AB",
        "invoice_number": "K-132000",
        "invoice_type": "Kreditfaktura",
        "total_amount": -132000.0,
        "date": "2026-10-01",
        "due_date": "2026-10-05",
        "status": "Obetald",
        "note": "Reklamation order 99",
    })
    invoices = []
    for idx in range(1, 11):
        invoices.append(engine.add({
            "supplier": "Demo Lev AB",
            "invoice_number": f"F-{idx:03d}",
            "invoice_type": "Faktura",
            "total_amount": 5355.0,  # 10 * 5355 = 53 550
            "date": "2026-10-02",
            "due_date": f"2026-10-{10 + idx:02d}",
            "status": "Obetald",
        }))
    return credit, invoices


def test_plan_and_chunk_settlement_132k_against_10_invoices():
    from ui.invoices_helpers import (
        chunk_settlement_rows, plan_credit_settlement,
    )

    rows = [
        {"id": "c1", "supplier": "Lev", "invoice_number": "K-1",
         "total_amount": -132000.0, "due_date": "2026-10-01", "note": "Kredit"},
        *[
            {"id": f"i{k}", "supplier": "Lev", "invoice_number": f"F-{k:02d}",
             "total_amount": 5355.0, "due_date": f"2026-10-{10 + k:02d}"}
            for k in range(1, 11)
        ],
    ]
    plan = plan_credit_settlement(rows)
    assert plan["total_invoices"] == pytest.approx(53550.0)
    assert plan["total_credits_original"] == pytest.approx(-132000.0)
    assert plan["used_credits"] == pytest.approx(53550.0)
    assert plan["applied_credits"] == pytest.approx(-53550.0)
    assert plan["remaining_credits"] == pytest.approx(-78450.0)
    assert plan["net_to_pay"] == pytest.approx(0.0)
    assert plan["has_partial_credit"] is True
    assert len(plan["fully_settled_ids"]) == 10
    assert "c1" not in plan["fully_settled_ids"]
    assert len(plan["carryovers"]) == 1
    assert plan["carryovers"][0]["remaining_amount"] == pytest.approx(-78450.0)

    # 10 fakturor + 1 kredit = 11 rader -> delas i 2 PDF-chunks om <= 10 rader!
    chunks = chunk_settlement_rows(plan, size=10)
    assert len(chunks) == 2
    assert [len(c) for c in chunks] == [10, 2]
    assert all(len(c) <= 10 for c in chunks)
    # Chunk 1: 9 fakturor (48 195) + kreditdel (-48 195) -> netto 0
    assert sum(r["total_amount"] for r in chunks[0]) == pytest.approx(0.0)
    # Chunk 2: 1 faktura (5 355) + kreditdel (-5 355) -> netto 0
    assert sum(r["total_amount"] for r in chunks[1]) == pytest.approx(0.0)
    assert all(
        r.get("_partial_credit_carryover") is True
        for chunk in chunks for r in chunk if r["total_amount"] < 0
    )


def test_export_partial_credit_keeps_78450_then_exhausts_and_restores(
    tmp_path, monkeypatch
):
    _qapp()
    from plugins.pdf_export_helpers import InvoiceNumberGuard, PDFExporter
    import ui.invoices_view as iv
    from ui.invoices_view import InvoicesView

    class _FakeBox(QMessageBox):
        def exec(self):
            return 0

        def clickedButton(self):
            return None

    data_dir = tmp_path / "data"
    app = _isolated_app(data_dir)
    exporter = PDFExporter(
        export_dir=tmp_path / "exports",
        data_dir=data_dir,
        get_suppliers_fn=app.get_suppliers,
    )
    guard = exporter.guard
    app.pdf_exporter = exporter
    app.add_supplier({"name": "Demo Lev AB"})

    credit, invoices = _build_10_invoices_and_132k_credit(app.invoices)
    view = InvoicesView(app)
    try:
        view._ask_payment_date_for_export = lambda **_kw: ("2026-10-25", True)
        monkeypatch.setattr(iv, "QMessageBox", _FakeBox)
        monkeypatch.setattr(
            iv, "build_export_path",
            lambda _s: (tmp_path / "exports", "batch1.pdf"),
        )

        # 1) Exportera krediten (-132 000) + de 10 fakturorna (53 550)
        view._export_invoices([credit, *invoices], confirm=False)

        # De 10 fakturorna är Betald/arkiverade; krediten är KVAR som Obetald med -78 450!
        active = app.get_active_invoices()
        assert len(active) == 1
        rem_credit = active[0]
        assert rem_credit["id"] == credit["id"]
        assert rem_credit["status"] == "Obetald"
        assert rem_credit["total_amount"] == pytest.approx(-78450.0)
        assert rem_credit["original_credit_amount"] == pytest.approx(-132000.0)
        assert len(app.get_archived_invoices()) == 10
        assert not guard.is_already_exported("K-132000", "Demo Lev AB")
        assert view._export_history.count() == 2  # 2 delfiler (9+1 fakturor)

        # 2) Återställ båda delfilerna -> hela -132 000 och alla 10 fakturor kommer tillbaka!
        ids_2 = view._export_history.get_invoice_ids(0)
        carry_2 = view._export_history.get_credit_carryovers(0)
        view._export_history.remove_export(0)
        view._on_export_restored(ids_2)
        view._on_credit_carryovers_restored(carry_2)

        ids_1 = view._export_history.get_invoice_ids(0)
        carry_1 = view._export_history.get_credit_carryovers(0)
        view._export_history.remove_export(0)
        view._on_export_restored(ids_1)
        view._on_credit_carryovers_restored(carry_1)

        restored_credit = app.invoices.get(credit["id"])
        assert restored_credit["total_amount"] == pytest.approx(-132000.0)
        assert restored_credit["status"] == "Obetald"
        assert len(app.get_active_invoices()) == 11

        # 3) Exportera igen -> -78 450 kvar -> nästa faktura på 100 000 förbrukar hela krediten!
        view._export_invoices(app.get_active_invoices(), confirm=False)
        assert app.invoices.get(credit["id"])["total_amount"] == pytest.approx(-78450.0)

        next_inv = app.add_invoice({
            "supplier": "Demo Lev AB",
            "invoice_number": "F-NEXT",
            "invoice_type": "Faktura",
            "total_amount": 100000.0,
            "date": "2026-10-26",
            "due_date": "2026-11-10",
            "status": "Obetald",
        })
        rem_credit = app.invoices.get(credit["id"])
        monkeypatch.setattr(
            iv, "build_export_path",
            lambda _s: (tmp_path / "exports", "batch2.pdf"),
        )
        view._export_invoices([rem_credit, next_inv], confirm=False)

        assert app.get_active_invoices() == []
        assert app.invoices.get(credit["id"])["status"] == "Betald"
        assert guard.is_already_exported("K-132000", "Demo Lev AB")
    finally:
        view.close()


def test_mark_selected_paid_and_undo_with_partial_credit(tmp_path, monkeypatch):
    _qapp()
    from ui.invoices_view import InvoicesView

    data_dir = tmp_path / "data"
    app = _isolated_app(data_dir)
    app.add_supplier({"name": "Demo Lev AB"})
    credit, invoices = _build_10_invoices_and_132k_credit(app.invoices)

    view = InvoicesView(app)
    try:
        monkeypatch.setattr(
            QMessageBox, "question",
            lambda *a, **kw: QMessageBox.StandardButton.Yes,
        )
        view._table.selectAll()
        view._mark_selected_paid()

        # De 10 fakturorna markerade Betald; krediten ligger kvar Obetald med -78 450!
        upd_credit = app.invoices.get(credit["id"])
        assert upd_credit["status"] == "Obetald"
        assert upd_credit["total_amount"] == pytest.approx(-78450.0)
        assert all(
            app.invoices.get(inv["id"])["status"] == "Betald"
            for inv in invoices
        )

        # Ångra senaste statusändring -> återställer både status OCH -132 000!
        view._undo_last_status()
        restored = app.invoices.get(credit["id"])
        assert restored["total_amount"] == pytest.approx(-132000.0)
        assert restored["status"] == "Obetald"
        assert all(
            app.invoices.get(inv["id"])["status"] == "Obetald"
            for inv in invoices
        )
    finally:
        view.close()


def test_link_credit_dialog_settles_and_preserves_remaining_credit(
    tmp_path, monkeypatch
):
    _qapp()
    from ui.invoices_view import InvoicesView

    data_dir = tmp_path / "data"
    app = _isolated_app(data_dir)
    app.add_supplier({"name": "Demo Lev AB"})
    credit, _invoices = _build_10_invoices_and_132k_credit(app.invoices)

    view = InvoicesView(app)
    try:
        # Markera krediten + första 4 fakturorna (4 * 5355 = 21 420)
        def _fake_exec(dlg):
            boxes = dlg.findChildren(QCheckBox)
            for idx, cb in enumerate(boxes):
                cb.setChecked(idx < 4)
            buttons = [
                b for b in dlg.findChildren(QPushButton)
                if "betalda" in b.text().lower() or "paid" in b.text().lower()
            ]
            assert buttons
            buttons[0].click()
            return int(QDialog.DialogCode.Accepted)

        monkeypatch.setattr(QDialog, "exec", _fake_exec)
        view._show_link_credit_dialog(preselected_rows=[credit])

        rem = app.invoices.get(credit["id"])
        assert rem["status"] == "Obetald"
        # -132 000 + 21 420 = -110 580 kvar för nästa koppling!
        assert rem["total_amount"] == pytest.approx(-110580.0)
    finally:
        view.close()


def test_auto_batch_preserves_remaining_credit(tmp_path):
    _qapp()
    from plugins.pdf_export_helpers import InvoiceNumberGuard, PDFExporter
    from ui.auto_batch import export_batches, plan_batches
    from ui.main_window import MainWindow

    data_dir = tmp_path / "data"
    app = _isolated_app(data_dir)
    app.pdf_exporter = PDFExporter(
        export_dir=tmp_path / "exports",
        data_dir=data_dir,
        get_suppliers_fn=app.get_suppliers,
    )
    app.add_supplier({"name": "Demo Lev AB"})
    credit, _invoices = _build_10_invoices_and_132k_credit(app.invoices)

    batches = plan_batches(app.get_active_invoices(), datetime.date(2026, 10, 1))
    assert batches
    results = export_batches(
        app, batches,
        path_builder=lambda _s: (tmp_path / "exports", "autobatch.pdf"),
    )
    assert results and all(r["success"] for r in results)

    # Simulera huvudtrådens avslutning via MainWindow._on_auto_batch_done
    fake_win = MainWindow.__new__(MainWindow)
    fake_win._app = app
    fake_win._auto_batch_data_dir = lambda: data_dir
    fake_win.set_status = lambda *_a, **_kw: None
    fake_win._on_auto_batch_done(results)

    rem = app.invoices.get(credit["id"])
    assert rem["status"] == "Obetald"
    assert rem["total_amount"] == pytest.approx(-78450.0)
    assert len(app.get_archived_invoices()) == 10
