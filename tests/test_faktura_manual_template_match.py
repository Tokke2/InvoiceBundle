# -*- coding: utf-8 -*-
"""
Tester: manuell matchning mot mall i Fakturor-fliken.

Användarens krav (2026-10-28): i Fakturor-fliken fanns ingen
manuell matchning mot mall — bara "Skanna om faktura", som väljer
tolkning själv. Nu ska högerklick → "Matcha mot mall …" låta
användaren välja leverantör/mall för en redan registrerad
faktura, läsa om värdena ur originalet med den mallen (visat
gammalt → nytt för kontroll), spara vid bekräftelse — och
matchningen ska lära appen precis som i Import.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "ui"),
           str(PROJECT_DIR / "plugins")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

import scan_import as si


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _pdf(path: Path, page_texts: list[str]) -> Path:
    import fitz
    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page(width=595, height=842)
        page.insert_text((40, 40), text, fontsize=9)
    doc.save(path)
    doc.close()
    return path


class _Store:
    def on_change(self, _cb):
        pass


class _FakeApp:
    def __init__(self, rows, suppliers, data_dir: Path):
        self.rows = [dict(r) for r in rows]
        self._suppliers = list(suppliers)
        self.settings = {"db_path": str(data_dir)}
        self.invoices_store = _Store()
        self.suppliers_store = _Store()
        self.session_due_date = None
        self.session_due_date_str = ""
        self.updates: list = []

    def get_invoices(self):
        return [dict(r) for r in self.rows]

    def get_active_invoices(self):
        return [dict(r) for r in self.rows]

    def get_suppliers(self):
        return list(self._suppliers)

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)

    def set_setting(self, key, value):
        self.settings[key] = value

    def update_invoice(self, rid, fields):
        self.updates.append((rid, dict(fields)))
        for row in self.rows:
            if str(row["id"]) == str(rid):
                row.update(fields)
        return None


def _invoice(pdf: Path, **kw):
    inv = {
        "id": "1", "supplier": "Martin G",
        "invoice_number": "923682", "ocr": "",
        "date": "2024-12-05", "due_date": "2025-01-04",
        "total_amount": 2686.45, "status": "Obetald",
        "attachment": str(pdf),
    }
    inv.update(kw)
    return inv


def _view(app):
    from ui.invoices_view import InvoicesView
    view = InvoicesView(app)
    return view


def _drive_dialog(choose: str, accept: bool = True, amount=None):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import (
        QApplication, QComboBox, QDialog, QLineEdit,
    )

    def _act():
        dlg = QApplication.activeModalWidget()
        assert isinstance(dlg, QDialog), "ingen modal dialog öppen"
        if not accept:
            dlg.reject()
            return
        combo = dlg.findChild(QComboBox)
        idx = combo.findText(choose)
        assert idx >= 0, f"{choose} saknas i listan"
        combo.setCurrentIndex(idx)
        if amount is not None:
            edits = dlg.findChildren(QLineEdit)
            assert edits, "inget beloppsfält"
            edits[-1].setText(amount)
        dlg.accept()

    QTimer.singleShot(50, _act)


# ── Menyn erbjuder manuell matchning ────────────────────────

def test_context_menu_offers_manual_template_match(tmp_path, monkeypatch):
    _qapp()
    import ui.invoices_view as iv

    menus = []

    class FakeMenu:
        def __init__(self, parent=None):
            self.labels = []
            menus.append(self)

        def addAction(self, label, slot=None):  # noqa: N802
            self.labels.append(str(label))
            act = type("A", (), {"triggered": _Sig()})()
            return act

        def addMenu(self, label):  # noqa: N802
            return FakeMenu()

        def addSeparator(self):  # noqa: N802
            pass

        def exec(self, pos):  # noqa: A003
            pass

    class _Sig:
        def connect(self, _fn):
            pass

    monkeypatch.setattr(iv, "QMenu", FakeMenu)
    pdf = _pdf(tmp_path / "f.pdf", ["x"])
    app = _FakeApp([_invoice(pdf)], [], tmp_path)
    view = _view(app)
    try:
        view._table.selectRow(0)
        rect = view._table.visualItemRect(view._table.item(0, 0))
        view._context_menu(rect.center())
        labels = menus[0].labels
        assert any("Matcha mot mall" in x for x in labels), labels
        assert any("Skanna om faktura" in x for x in labels), labels
    finally:
        view.close()


# ── Matchningen tillämpas ───────────────────────────────────

def test_manual_match_rereads_with_chosen_template(tmp_path):
    """923682-fallet: fakturan står fel (2 686,45, leverantör
    'Martin G'). Användaren matchar mot Testbolagets mall —
    fakturanummer, belopp och leverantör rättas ur originalet,
    och bekräftelsen lärs in (flersidig)."""
    _qapp()
    pdf = _pdf(tmp_path / "f.pdf", [
        "Testbolaget AB\nFaktnr 921040\nSumma 857,25",
        "Testbolaget AB\nSumma 13 480,00",
    ])
    si.save_templates(tmp_path / "invoice_templates.json", {
        "Testbolaget AB": {"fields": {
            "invoice_number": {"label": "Faktnr"},
            "total_amount": {"label": "Summa"},
        }},
    })
    app = _FakeApp(
        [_invoice(pdf)], [{"name": "Testbolaget AB"}], tmp_path
    )
    view = _view(app)
    try:
        view._table.selectRow(0)
        _drive_dialog("Testbolaget AB")
        view._manual_template_match()
        assert len(app.updates) == 1
        rid, fields = app.updates[0]
        assert rid == "1"
        assert fields["supplier"] == "Testbolaget AB"
        assert fields["invoice_number"] == "921040"
        assert float(fields["total_amount"]) == 13480.0
        learning = json.loads(
            (tmp_path / "match_memory.json").read_text("utf-8")
        )
        assert learning["Testbolaget AB"]["multipage_confirmed"] == 1
    finally:
        view.close()


def test_manual_match_user_can_edit_total(tmp_path):
    """Beloppsfältet i dialogen vinner över omläsningen —
    användarens bekräftade slutsumma sparas."""
    _qapp()
    pdf = _pdf(tmp_path / "f.pdf", [
        "Testbolaget AB\nFaktnr 921040\nSumma 857,25",
    ])
    app = _FakeApp(
        [_invoice(pdf)], [{"name": "Testbolaget AB"}], tmp_path
    )
    view = _view(app)
    try:
        view._table.selectRow(0)
        _drive_dialog("Testbolaget AB", amount="13 480,00")
        view._manual_template_match()
        _rid, fields = app.updates[0]
        assert float(fields["total_amount"]) == 13480.0
    finally:
        view.close()


def test_manual_match_teaches_template_for_new_supplier(tmp_path):
    """Leverantör utan mall: matchningen i Fakturor lär appen
    en verifierad mall (samma inlärning som i Import)."""
    _qapp()
    pdf = _pdf(tmp_path / "f.pdf", [
        "Nya Bolaget AB\nFakturanr 55\nAtt betala 700,00",
    ])
    inv = _invoice(pdf, supplier="Okand Leverantor",
                   invoice_number="54", total_amount=650.0)
    app = _FakeApp([inv], [{"name": "Nya Bolaget AB"}], tmp_path)
    view = _view(app)
    try:
        view._table.selectRow(0)
        _drive_dialog("Nya Bolaget AB")
        view._manual_template_match()
        templates = si.load_templates(
            tmp_path / "invoice_templates.json"
        )
        assert "Nya Bolaget AB" in templates
        text, _m = si.extract_text(pdf)
        found = si.apply_template(text, templates["Nya Bolaget AB"])
        assert found["invoice_number"] == "55"
        assert found["total_amount"] == 700.0
        _rid, fields = app.updates[0]
        assert fields["supplier"] == "Nya Bolaget AB"
        assert float(fields["total_amount"]) == 700.0
    finally:
        view.close()


def test_manual_match_cancel_changes_nothing(tmp_path):
    """Avbryt i dialogen = fakturan orörd, ingen inlärning."""
    _qapp()
    pdf = _pdf(tmp_path / "f.pdf", ["Testbolaget AB\nFaktnr 1\n"])
    app = _FakeApp(
        [_invoice(pdf)], [{"name": "Testbolaget AB"}], tmp_path
    )
    view = _view(app)
    try:
        view._table.selectRow(0)
        _drive_dialog("", accept=False)
        view._manual_template_match()
        assert app.updates == []
        assert not (tmp_path / "match_memory.json").exists()
    finally:
        view.close()


def test_manual_match_missing_original_explains(tmp_path):
    """Saknat original: klartext i statusraden, ingen dialog."""
    _qapp()
    app = _FakeApp(
        [_invoice(tmp_path / "finns-inte.pdf")],
        [{"name": "Testbolaget AB"}], tmp_path,
    )
    view = _view(app)
    try:
        view._table.selectRow(0)
        view._manual_template_match()  # får inte öppna dialog
        assert app.updates == []
    finally:
        view.close()
