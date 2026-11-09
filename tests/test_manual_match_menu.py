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

import pytest

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
    def __init__(self):
        self.created = []

    def get_suppliers(self):
        return list(_SUPPLIERS)

    def get_invoices(self):
        return list(self.created)

    def add_invoice(self, data):
        record = dict(data, id=f"fake-{len(self.created) + 1}")
        self.created.append(record)
        return record

    def get_setting(self, key, default=None):
        return default


@pytest.fixture(autouse=True)
def _no_success_dialogs(monkeypatch):
    import ui.scan_import_view as sv

    monkeypatch.setattr(
        sv.QMessageBox, "information", lambda *_a, **_k: None
    )


def _stub_message_boxes(monkeypatch, question_answer=None):
    """Replace only this view's QMessageBox calls with non-modal stubs."""
    import ui.scan_import_view as sv
    from PySide6.QtWidgets import QMessageBox as QtMessageBox

    class StubMessageBox:
        StandardButton = QtMessageBox.StandardButton

        @staticmethod
        def information(*_args, **_kwargs):
            return None

        @staticmethod
        def warning(*_args, **_kwargs):
            return None

        @staticmethod
        def question(*_args, **_kwargs):
            if question_answer is not None:
                return question_answer
            return QtMessageBox.StandardButton.Yes

    monkeypatch.setattr(sv, "QMessageBox", StubMessageBox)
    return StubMessageBox


def _view(tmp_path, templates=None, parent=None):
    from ui.scan_import_view import ScanImportView

    view = ScanImportView(
        app=_Core(), parent=parent,
        templates_path=tmp_path / "invoice_templates.json"
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


def test_uncertain_match_can_mark_logo_on_original_and_learn_it(
    tmp_path, monkeypatch,
):
    """Loggan kan markeras direkt i frågan och räknas först när
    användaren sedan bekräftar leverantören."""
    _qapp()
    from PIL import Image, ImageDraw
    from PySide6.QtWidgets import QComboBox, QDialog, QLabel, QLineEdit, QPushButton

    import scan_import as si
    import ui.scan_import_view as sv

    image_path = tmp_path / "uncertain-invoice.png"
    image = Image.new("RGB", (500, 700), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 35, 190, 135), fill="#146b54")
    draw.ellipse((75, 52, 155, 118), fill="#e4c64f")
    image.save(image_path)

    signature = "dhash128-v1:" + "abcdef01" * 4
    monkeypatch.setattr(
        si, "supplier_logo_signature", lambda *_args: signature,
    )
    view = _view(tmp_path, templates={})
    row = _row(
        file="uncertain-invoice.png", _path=str(image_path),
        supplier="", match_uncertain=True, match_kind="supplier",
        match_reason="weak", match_candidates=["Testbolaget AB"],
    )
    view._rows = [row]

    class FakeLogoDialog:
        def __init__(
            self, parent, text, supplier, existing, path, suppliers,
            templates, logo_only, suggest_logo_match,
        ):
            assert supplier == "Testbolaget AB"
            assert logo_only is True
            assert suggest_logo_match is False
            self.result_template = {
                "supplier": supplier, "fields": {},
                "supplier_logo": {
                    "page": 0,
                    "region": [0.08, 0.05, 0.39, 0.20],
                    "dhash": signature,
                },
            }
            self._supplier_edit = QLineEdit(supplier)
            self._btn_match_bg = QPushButton()

        def setWindowTitle(self, _title):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(sv, "TemplateDialog", FakeLogoDialog)

    def _accept_after_marking(dialog):
        combo = dialog.findChild(QComboBox)
        assert combo is not None
        combo.setCurrentIndex(combo.findText("Testbolaget AB"))
        mark_button = dialog.findChild(
            QPushButton, "matchMarkInvoiceLogo"
        )
        assert mark_button is not None
        mark_button.click()
        note = dialog.findChild(QLabel, "supplierLogoNote")
        assert note is not None and note.text()
        dialog.accept()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", _accept_after_marking)
    try:
        assert view._ask_user_for_match(row) is True
        saved = si.load_templates(tmp_path / "invoice_templates.json")
        assert saved["Testbolaget AB"]["supplier_logo"]["dhash"] == signature
        learning = si.load_match_learning(tmp_path / "match_memory.json")
        assert learning["Testbolaget AB"]["confirmed"] == 1
        assert learning["Testbolaget AB"]["logos"][signature] == 1
    finally:
        view.close()


def test_manual_match_rereads_other_rows_and_leaves_uncertain_in_import(
    tmp_path, monkeypatch,
):
    """Ny bekräftad kunskap prövas på övriga rader; bara kompletta,
    säkra träffar går till registrering och osäkra stannar kvar."""
    _qapp()
    import scan_import as si

    view = _view(tmp_path)
    current = _row(
        supplier="Testbolaget AB", supplier_match={
            "status": "matched", "supplier": "Testbolaget AB",
            "reason": "user_choice", "uncertain": False,
        },
    )
    newly_matched = _row(
        file="second.pdf", _text="newly-matchable",
        match_uncertain=True, match_kind="supplier",
        match_reason="weak", match_candidates=["Testbolaget AB"],
    )
    still_uncertain = _row(
        file="third.pdf", _text="still-uncertain",
        match_uncertain=True, match_kind="supplier",
        match_reason="ambiguous", match_candidates=["Annan AB", "Testbolaget AB"],
    )
    already_safe = _row(
        file="already-safe.pdf", _text="already-safe",
        supplier="Testbolaget AB", invoice_number="OLD-1",
        total_amount=100.0, missing=[], status="redo",
        supplier_match={
            "status": "matched", "supplier": "Testbolaget AB",
            "uncertain": False,
        },
        template_match={"status": "none", "uncertain": False},
    )
    view._rows = [current, newly_matched, still_uncertain, already_safe]
    view._refresh_table()
    parsed_texts = []
    learning_at_read = []
    registered = []

    def _parse(text, _suppliers, _templates, match_learning=None):
        parsed_texts.append(text)
        learning_at_read.append(dict(match_learning or {}))
        if text in {"newly-matchable", "already-safe"}:
            invoice_number = (
                "B-2" if text == "newly-matchable" else "OLD-1"
            )
            return {
                "supplier": "Testbolaget AB",
                "invoice_number": invoice_number,
                "total_amount": 250.0, "missing": [], "status": "redo",
                "supplier_match": {
                    "status": "matched", "supplier": "Testbolaget AB",
                    "reason": "learned", "uncertain": False,
                },
                "template_match": {
                    "status": "none", "template": "",
                    "candidates": [], "uncertain": False,
                },
            }
        return {
            "supplier": "", "invoice_number": "C-3",
            "total_amount": 300.0, "missing": ["leverantör"],
            "match_uncertain": True, "match_kind": "supplier",
            "match_reason": "ambiguous",
            "match_candidates": ["Annan AB", "Testbolaget AB"],
            "supplier_match": {
                "status": "uncertain", "supplier": "",
                "candidates": ["Annan AB", "Testbolaget AB"],
                "uncertain": True, "reason": "ambiguous",
            },
            "template_match": {
                "status": "none", "template": "",
                "candidates": [], "uncertain": False,
            },
        }

    monkeypatch.setattr(si, "parse_invoice_text", _parse)
    view._auto_register_matched_rows = lambda rows: (
        registered.extend(rows) or len(rows)
    )
    try:
        view._apply_manual_match(current, "Testbolaget AB")
        assert set(parsed_texts) == {
            "newly-matchable", "still-uncertain", "already-safe",
        }
        assert all(
            memory["Testbolaget AB"]["confirmed"] == 1
            for memory in learning_at_read
        )
        assert newly_matched["supplier"] == "Testbolaget AB"
        assert not newly_matched.get("match_uncertain")
        assert registered == [newly_matched]
        assert already_safe in view._rows
        assert already_safe not in registered
        assert still_uncertain in view._rows
        assert still_uncertain["match_uncertain"] is True
        assert still_uncertain["supplier"] == ""
    finally:
        view.close()


# ── Manuell matchning tillämpas ─────────────────────────────

def test_manual_match_registers_invoice_and_opens_invoices_tab(tmp_path):
    """Ett uttryckligt val matchar, skapar och visar fakturan i
    Fakturor när de obligatoriska fälten finns."""
    _qapp()
    from PySide6.QtWidgets import QWidget
    from ui.scan_import_view import ScanImportView

    class _InvoicesView:
        def __init__(self):
            self.refreshes = 0

        def refresh(self):
            self.refreshes += 1

    class _Host(QWidget):
        def __init__(self):
            super().__init__()
            self._invoices_view = _InvoicesView()
            self.destination = None

        def _tab_title(self, key):
            return "Fakturor" if key == "invoices" else key

        def _goto_tab(self, key, title):
            self.destination = (key, title)

    host = _Host()
    view = _view(tmp_path, parent=host)
    original = tmp_path / "original.pdf"
    original.write_bytes(b"original invoice bytes")
    try:
        row = _row(_path=str(original))
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
        assert view._rows == []
        assert len(view._app.created) == 1
        assert view._app.created[0]["supplier"] == "Testbolaget AB"
        assert view._app.created[0]["invoice_number"] == "777"
        assert view._app.created[0]["total_amount"] == 1500.0
        assert view._app.created[0]["attachment"] == str(original)
        assert original.read_bytes() == b"original invoice bytes"
        assert "registrerad i Fakturor" in view._lbl_status.text()
        assert host.destination == ("invoices", "Fakturor")
        assert host._invoices_view.refreshes == 1
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
        assert view._rows == []
        assert len(view._app.created) == 1
        assert view._app.created[0]["supplier"] == "Annan AB"
        assert view._app.created[0]["invoice_number"] == "555"
        assert view._app.created[0]["total_amount"] == 200.0
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
        assert view._rows == []
        assert len(view._app.created) == 1
    finally:
        view.close()


def test_manual_match_missing_fields_stays_in_interpreted_table(tmp_path):
    """En matchning får inte skapa en faktura förrän belopp och
    fakturanummer är kompletta."""
    _qapp()
    view = _view(tmp_path, templates={})
    try:
        row = _row(
            invoice_number="555", total_amount=0.0,
            missing=["belopp", "leverantör"],
            _text="text utan läsbart belopp eller fakturanummer",
        )
        view._rows = [row]
        view._refresh_table()
        view._tbl.selectRow(0)
        _choose_in_dialog("Annan AB")
        view._manual_match_row()

        assert row["supplier"] == "Annan AB"
        assert row["missing"] == ["belopp"]
        assert view._rows == [row]
        assert view._app.created == []
        assert "belopp" in view._lbl_status.text()
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


def test_manual_match_declined_duplicate_stays_in_import(tmp_path, monkeypatch):
    """Att tacka nej till dubblettregistrering lämnar raden kvar."""
    _qapp()
    from PySide6.QtWidgets import QMessageBox as QtMessageBox

    _stub_message_boxes(
        monkeypatch, QtMessageBox.StandardButton.No
    )
    view = _view(tmp_path)
    navigations = []
    view._show_invoices_tab = lambda: navigations.append(True)
    try:
        existing = {
            "id": "existing", "supplier": "Testbolaget AB",
            "invoice_number": "777", "total_amount": 1500.0,
        }
        view._app.created.append(existing)
        row = _row()
        view._rows = [row]
        view._refresh_table()
        view._tbl.selectRow(0)

        _choose_in_dialog("Testbolaget AB")
        view._manual_match_row()

        assert view._rows == [row]
        assert view._app.created == [existing]
        assert navigations == []
    finally:
        view.close()


def test_manual_match_unknown_supplier_stays_in_import(tmp_path, monkeypatch):
    """En mall som saknar registerleverantör får inte registreras."""
    _qapp()
    import ui.scan_import_view as sv
    from ui.scan_import_view import ScanImportView

    _stub_message_boxes(monkeypatch)

    class CoreWithoutTemplateSupplier(_Core):
        def get_suppliers(self):
            return [{"name": "Annan AB"}]

    view = ScanImportView(
        app=CoreWithoutTemplateSupplier(),
        templates_path=tmp_path / "invoice_templates.json",
    )
    view._templates_cache = dict(_TEMPLATES)
    navigations = []
    view._show_invoices_tab = lambda: navigations.append(True)
    try:
        row = _row()
        view._rows = [row]
        view._refresh_table()
        view._tbl.selectRow(0)

        _choose_in_dialog("Testbolaget AB")
        view._manual_match_row()

        assert row["supplier"] == "Testbolaget AB"
        assert view._rows == [row]
        assert view._app.created == []
        assert navigations == []
    finally:
        view.close()


def test_manual_match_storage_failure_stays_in_import(tmp_path, monkeypatch):
    """Skrivfel lämnar original och import-rad på plats."""
    _qapp()
    _stub_message_boxes(monkeypatch)
    view = _view(tmp_path)
    navigations = []
    view._show_invoices_tab = lambda: navigations.append(True)
    original = tmp_path / "original.pdf"
    original.write_bytes(b"original invoice bytes")

    def fail_save(_data):
        raise OSError("disk full")

    view._app.add_invoice = fail_save
    try:
        row = _row(_path=str(original))
        view._rows = [row]
        view._refresh_table()
        view._tbl.selectRow(0)

        _choose_in_dialog("Testbolaget AB")
        view._manual_match_row()

        assert view._rows == [row]
        assert original.read_bytes() == b"original invoice bytes"
        assert navigations == []
    finally:
        view.close()
