# -*- coding: utf-8 -*-
"""
Tester: manuell matchning via högerklicksmenyn i Import.

Användarens krav (2026-10-28): lyckas den automatiska
matchningen inte ska man kunna matcha fakturan mot en
leverantör SJÄLV via högerklicksmenyn — välja leverantör ur
registret, få dess mall inläst i raden och raden godkänd som
eget val (grön), i stället för att bara kunna lära en ny mall.
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


_SUPPLIERS = [
    {"name": "Annan AB"},
    {"name": "Testbolaget AB"},
]

_TEMPLATES = {
    "Testbolaget AB": {"fields": {
        "invoice_number": {"label": "Faktnr"},
        "total_amount": {"label": "Summa"},
    }},
}


class _Core:
    def get_suppliers(self):
        return list(_SUPPLIERS)

    def get_setting(self, key, default=None):
        return default


def _view(tmp_path, templates=None):
    from ui.scan_import_view import ScanImportView

    view = ScanImportView(
        app=_Core(), templates_path=tmp_path / "invoice_templates.json"
    )
    view._templates_cache = dict(_TEMPLATES if templates is None
                                 else templates)
    return view


def _row(**kw):
    row = {
        "file": "okand.pdf", "supplier": "", "invoice_number": "",
        "date": "", "due_date": "", "ocr": "", "total_amount": 0.0,
        "method": "pdf", "status": "saknas: leverantör",
        "missing": ["leverantör"], "_path": "",
        "_text": "Faktnr 777\nSumma 1 500,00",
    }
    row.update(kw)
    return row


def _choose_in_dialog(name: str, accept: bool = True):
    """Schemalägger ett val i den modala matchningsdialogen."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QComboBox, QDialog

    def _act():
        dlg = QApplication.activeModalWidget()
        assert isinstance(dlg, QDialog), "ingen modal dialog öppen"
        if not accept:
            dlg.reject()
            return
        combo = dlg.findChild(QComboBox)
        assert combo is not None
        idx = combo.findText(name)
        assert idx >= 0, f"{name} saknas i listan"
        combo.setCurrentIndex(idx)
        dlg.accept()

    QTimer.singleShot(50, _act)


# ── Menyn innehåller manuell matchning ──────────────────────

def test_context_menu_offers_manual_match(tmp_path, monkeypatch):
    _qapp()
    import ui.scan_import_view as sv

    menus = []

    class FakeMenu:
        def __init__(self, parent=None):
            self.labels = []
            menus.append(self)

        def addAction(self, label, slot=None):  # noqa: N802
            self.labels.append(str(label))

        def addSeparator(self):  # noqa: N802
            pass

        def exec(self, pos):  # noqa: A003
            pass

    monkeypatch.setattr(sv, "QMenu", FakeMenu)
    view = _view(tmp_path)
    try:
        view._rows = [_row()]
        view._refresh_table()
        view._table_context_menu(view._tbl.viewport().rect().center())
        labels = menus[-1].labels
        assert any("Matcha mot leverantör" in x for x in labels), labels
        assert any("Öppna original" in x for x in labels), labels
    finally:
        view.close()


# ── Manuell matchning tillämpas ─────────────────────────────

def test_manual_match_sets_supplier_and_reads_template(tmp_path):
    """Omatchad rad + manuellt val: leverantören sätts, mallens
    värden läses in och raden blir redo/grön (eget val)."""
    _qapp()
    from ui.scan_import_view import ROW_BG_MATCH_SECURE, ScanImportView

    view = _view(tmp_path)
    try:
        row = _row()
        view._rows = [row]
        view._refresh_table()
        view._tbl.selectRow(0)
        # Omatchad rad är neutral före valet.
        assert ScanImportView._row_match_state(row) == ""

        _choose_in_dialog("Testbolaget AB")
        view._manual_match_row()

        assert row["supplier"] == "Testbolaget AB"
        assert row["invoice_number"] == "777"
        assert float(row["total_amount"]) == 1500.0
        assert row["template"] == "Testbolaget AB"
        assert row["missing"] == []
        assert row["status"] == "redo"
        assert row["supplier_match"]["reason"] == "user_choice"
        assert ScanImportView._row_match_state(row) == "secure"
        bg = view._tbl.item(0, 0).background().color().name()
        assert bg == ROW_BG_MATCH_SECURE[0]
        assert "Testbolaget AB" in view._lbl_status.text()
    finally:
        view.close()


def test_manual_match_without_template_keeps_parsed_values(tmp_path):
    """Leverantör utan mall: avlästa värden behålls, bara
    leverantören sätts — raden kan ändå registreras."""
    _qapp()
    view = _view(tmp_path)
    try:
        row = _row(invoice_number="555", total_amount=200.0,
                   missing=["leverantör"], _text="någon annan text")
        view._rows = [row]
        view._refresh_table()
        view._tbl.selectRow(0)
        _choose_in_dialog("Annan AB")
        view._manual_match_row()
        assert row["supplier"] == "Annan AB"
        assert row["invoice_number"] == "555"
        assert float(row["total_amount"]) == 200.0
        assert row["missing"] == []
        assert row["status"] == "redo"
    finally:
        view.close()


def test_manual_match_resolves_uncertain_row(tmp_path):
    """Osäker matchning löst för hand: flaggorna rensas och
    raden räknas inte längre som osäker (aldrig auto-vald)."""
    _qapp()
    from ui.scan_import_view import ScanImportView

    view = _view(tmp_path)
    try:
        row = _row(match_uncertain=True, match_kind="supplier",
                   match_candidates=["Annan AB", "Testbolaget AB"],
                   match_reason="ambiguous")
        view._rows = [row]
        view._refresh_table()
        view._tbl.selectRow(0)
        _choose_in_dialog("Testbolaget AB")
        view._manual_match_row()
        assert row["supplier"] == "Testbolaget AB"
        assert not row.get("match_uncertain")
        assert "match_candidates" not in row
        assert ScanImportView._row_match_state(row) == "secure"
    finally:
        view.close()


def test_manual_match_cancel_leaves_row_untouched(tmp_path):
    """Avbryt i dialogen = raden exakt som förut."""
    _qapp()
    view = _view(tmp_path)
    try:
        row = _row()
        before = dict(row)
        view._rows = [row]
        view._refresh_table()
        view._tbl.selectRow(0)
        _choose_in_dialog("", accept=False)
        view._manual_match_row()
        assert row == before
    finally:
        view.close()


def test_manual_match_no_suppliers_informs(tmp_path, monkeypatch):
    """Tomt register: klartext i stället för tom dialog."""
    _qapp()
    import ui.scan_import_view as sv

    seen = {}

    class FakeBox:
        @staticmethod
        def information(parent, title, text, *a, **k):
            seen["text"] = text

    monkeypatch.setattr(sv, "QMessageBox", FakeBox)

    class EmptyCore(_Core):
        def get_suppliers(self):
            return []

    from ui.scan_import_view import ScanImportView

    view = ScanImportView(
        app=EmptyCore(),
        templates_path=tmp_path / "invoice_templates.json",
    )
    view._templates_cache = {}
    try:
        row = _row()
        view._rows = [row]
        view._refresh_table()
        view._tbl.selectRow(0)
        view._manual_match_row()
        assert "inga leverantörer" in seen.get("text", "")
        assert row["supplier"] == ""
    finally:
        view.close()
