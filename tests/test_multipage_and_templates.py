# -*- coding: utf-8 -*-
"""
Tester: flersidiga fakturor + mallhantering + öppna original.

Användarens krav (2026-10-27):
- Flersidig faktura ska få RÄTT total (exemplet 923682: två sidor,
  delsumma 2 686,45 på ett ställe men totalen 6 176 till slut —
  appen ska ta slutsumman, aldrig delsummor).
- Sidantalet ska SYNAS för fakturor med 2+ sidor.
- Högerklick ska kunna öppna originalfakturan (Fakturor + Import).
- Kunde en importerad faktura inte matchas ska appen öppna
  mallskapandet direkt för den.
- Mallar ska kunna REDIGERAS och SKAPAS NYA i mallhanteraren.
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

import scan_import as si


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_pdf(path: Path, pages: int) -> Path:
    import fitz
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=595, height=842)
    doc.save(path)
    doc.close()
    return path


# ── Flersidig total ─────────────────────────────────────────────────

def test_parse_total_multipage_last_total_wins():
    """923682-fallet: delbelopp tidigare i dokumentet, slutsumman
    sist — appen ska ta slutsumman 6 176, inte 2 686,45."""
    text = (
        "Faktura 923682\nTestsäljaren AB\n"
        "Att betala 2 686,45\n"
        "Specifikation sida 2\n"
        "Att betala 6 176,00\n"
    )
    assert si.parse_total(text) == 6176.0


def test_parse_total_single_occurrence_unchanged():
    assert si.parse_total("Att betala 500,00\nMoms 100,00") == 500.0
    assert si.parse_total("Inga belopp alls") == 0.0


def test_below_label_amount_picks_final_total():
    """Etikett UNDER-fält i flersidigt dokument: största beloppet
    (slutsumman) vinner för beloppsfält."""
    text = "Belopp att betala\n2 686,45\nBelopp att betala\n6 176,00"
    assert si._extract_below_label(
        text, "Belopp att betala", "amount"
    ) == "6176.00"


def test_below_label_other_fields_keep_first():
    """Andra fält ändras INTE av flersidighetsregeln."""
    text = "Fakturanummer\n111\nFakturanummer\n222"
    assert si._extract_below_label(
        text, "Fakturanummer", "invoice_number"
    ) == "111"


_MARTIN_HEAD = (
    "Martin G Anderson\nOrg.nr 556824-5806 Bankgiro 728-0811\n"
)


def test_builtin_martin_multipage_paired_last_total():
    """923682 på riktigt: Martin Gs inbyggda format får INTE stanna
    på första sidans delbelopp bara för att det står parvis under
    samma etikett — slutsumman 6 176 sist i dokumentet vinner."""
    text = (
        _MARTIN_HEAD
        + "Fakturanr. 923682\nFakturadatum 2024-12-05\n"
        + "Att betala 2 686,45\n"
        + "Specifikation fortsätter på nästa sida\n"
        + "Att betala 6 176,00\n"
    )
    r = si.parse_invoice_text(
        text, [{"name": "Martin G Anderson"}], {}
    )
    assert r["total_amount"] == 6176.0
    assert r.get("template") == "Martin G Anderson"
    assert r["invoice_number"] == "923682"


def test_builtin_martin_multipage_mixed_layout():
    """Rubrikrad+värderad med delbelopp på sida 1 men parvis
    slutsumma på sista sidan — blandade layouter i samma dokument
    ska ändå ge slutsumman."""
    text = (
        _MARTIN_HEAD
        + "Fakturanr. Fakturadatum Att betala\n"
        + "923682 2024-12-05 2 686,45\n"
        + "Specifikation fortsätter på nästa sida\n"
        + "Att betala 6 176,00\n"
    )
    r = si.parse_invoice_text(
        text, [{"name": "Martin G Anderson"}], {}
    )
    assert r["total_amount"] == 6176.0
    assert r.get("template") == "Martin G Anderson"


def test_extract_amount_last_occurrence_dates_keep_first():
    """Belopp = sista förekomsten (slutsumman), datum/nummer =
    första (sidhuvuden upprepar dem oförändrade)."""
    text = (
        "Att betala 100,00\nAtt betala 250,00\n"
        "Datum 2024-01-01\nDatum 2024-02-02\n"
    )
    assert si.extract_with_label(text, "Att betala", "amount") \
        == "250.00"
    assert si.extract_with_label(text, "Datum", "date") \
        == "2024-01-01"
    assert si._label_same_line_amount(text, "Att betala") == 250.0


# ── Sidantal ────────────────────────────────────────────────────────

def test_attachment_page_count(tmp_path):
    from ui.invoices_helpers import attachment_page_count
    two = _make_pdf(tmp_path / "tva.pdf", 2)
    one = _make_pdf(tmp_path / "en.pdf", 1)
    img = tmp_path / "bild.png"
    img.write_bytes(b"\x89PNG")
    assert attachment_page_count(str(two)) == 2
    assert attachment_page_count(str(one)) == 1
    assert attachment_page_count(str(img)) == 1
    assert attachment_page_count(str(tmp_path / "saknas.pdf")) == 0
    assert attachment_page_count("") == 0


# ── Fakturor: sidkolumn + högerklicksöppning ────────────────────────

class _Store:
    def on_change(self, _cb):
        pass


class _FakeApp:
    settings = {"db_path": "/tmp"}
    invoices_store = _Store()
    suppliers_store = _Store()
    session_due_date = None
    session_due_date_str = ""

    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]

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


def _inv_row(i, attachment=""):
    return {
        "id": str(i), "supplier": "Pilkington",
        "invoice_number": f"F-{i:03d}", "ocr": "12345",
        "date": "2026-09-01", "due_date": "2026-09-15",
        "total_amount": 100.0 * i, "status": "Obetald",
        "attachment": attachment,
    }


def _pages_col(view) -> int:
    for c in range(view._table.columnCount()):
        item = view._table.horizontalHeaderItem(c)
        if item and item.text() == "Sidor":
            return c
    raise AssertionError("kolumnen Sidor saknas i Fakturor-tabellen")


def test_invoices_pages_column_and_open_original(tmp_path, monkeypatch):
    _qapp()
    import ui.invoices_view as iv
    from ui.invoices_view import InvoicesView

    two = _make_pdf(tmp_path / "tvasidig.pdf", 2)
    one = _make_pdf(tmp_path / "ensidig.pdf", 1)
    app = _FakeApp([
        _inv_row(1, str(two)), _inv_row(2, str(one)), _inv_row(3),
    ])
    view = InvoicesView(app)
    try:
        col = _pages_col(view)
        # 2+ sidor syns med siffran; ensidig visar 1; utan
        # original lämnas cellen tom (aldrig gissat sidantal).
        assert view._table.item(0, col).text() == "2"
        assert view._table.item(1, col).text() == "1"
        assert view._table.item(2, col).text() == ""
        assert "2 sidor" in view._table.item(0, col).toolTip() or \
            view._table.item(0, col).toolTip() != ""
        assert view._pages_for(app.rows[0]) == 2

        opened = []
        monkeypatch.setattr(iv, "open_file", opened.append)
        view._table.selectRow(0)
        view._open_original_invoice()
        assert opened == [str(two)]

        # Saknat original: inget öppnas, inget kraschar.
        view._table.selectRow(2)
        view._open_original_invoice()
        assert opened == [str(two)]
    finally:
        view.close()


# ── Import: sidantal i statusen ───────────────────────────────────

def test_import_status_shows_pages(tmp_path):
    _qapp()
    from ui.scan_import_view import ScanImportView
    two = _make_pdf(tmp_path / "tva.pdf", 2)
    text = ScanImportView._display_status({
        "file": "tva.pdf", "_path": str(two), "missing": [],
        "total_amount": 10.0, "invoice_number": "1",
        "supplier": "X", "method": "pdf-text",
    })
    assert "2 sidor" in text


# ── Mallhanteraren: redigera + skapa ny ─────────────────────────────

def test_templates_manager_edit_and_create_buttons():
    _qapp()
    from PySide6.QtWidgets import QPushButton
    from ui.scan_import_view import TemplatesManagerDialog

    edited, created = [], []
    templates = {
        "Alpha AB": {"fields": {}}, "Beta AB": {"fields": {}},
    }
    dlg = TemplatesManagerDialog(
        None, templates, lambda name: None,
        on_edit=edited.append, on_create=lambda: created.append(True),
    )
    try:
        texts = [b.text() for b in dlg.findChildren(QPushButton)]
        assert any("Redigera" in t for t in texts)
        assert any("Ny mall" in t for t in texts)
        dlg._list.setCurrentRow(1)
        dlg._edit_selected()
        assert edited == ["Beta AB"]
        dlg._create_new()
        assert created == [True]
    finally:
        dlg.close()


def _fake_core():
    class FakeCore:
        def get_suppliers(self):
            return []

        def get_setting(self, key, default=None):
            return default

    return FakeCore()


def test_manager_edit_opens_dialog_with_existing(tmp_path, monkeypatch):
    """Redigera i hanteraren öppnar malldialogen med de SPARADE
    markeringarna (existing) och sparar ändringen i JSON-filen."""
    _qapp()
    import ui.scan_import_view as sv
    from ui.scan_import_view import ScanImportView

    templates_file = tmp_path / "invoice_templates.json"
    si.save_templates(templates_file, {
        "Alpha AB": {"fields": {
            "total_amount": {"label": "Att betala"},
        }},
    })
    view = ScanImportView(
        app=_fake_core(), templates_path=templates_file
    )
    seen = {}

    class FakeDlg:
        def __init__(self, parent, text, supplier="",
                     existing=None, path=None):
            seen["supplier"] = supplier
            seen["existing"] = existing
            self.result_template = {
                "supplier": "Alpha AB",
                "fields": {
                    "total_amount": {"label": "Slutbelopp"},
                    "invoice_number": {"label": "Fakturanr"},
                },
            }

        def exec(self):
            return 1

    monkeypatch.setattr(sv, "TemplateDialog", FakeDlg)
    try:
        view._manager_edit_template("Alpha AB")
        assert seen["supplier"] == "Alpha AB"
        assert seen["existing"]["fields"]["total_amount"] == {
            "label": "Att betala"
        }
        saved = si.load_templates(templates_file)
        assert saved["Alpha AB"]["fields"]["total_amount"] == {
            "label": "Slutbelopp"
        }
    finally:
        view.close()


def test_manager_create_needs_example_invoice(tmp_path, monkeypatch):
    """Ny mall utan exempelfaktura: besked, ingen dialog, ingen
    gissning. Med exempelrad öppnas mallskapandet för raden."""
    _qapp()
    import ui.scan_import_view as sv
    from ui.scan_import_view import ScanImportView

    view = ScanImportView(
        app=_fake_core(),
        templates_path=tmp_path / "invoice_templates.json",
    )
    infos = []

    class FakeBox:
        @staticmethod
        def information(*args, **kwargs):
            infos.append(args)

    opened = []
    monkeypatch.setattr(sv, "QMessageBox", FakeBox)
    try:
        view._manager_create_template()
        assert infos, "användaren ska få besked om att exempel krävs"
        assert opened == []

        pdf = _make_pdf(tmp_path / "ex.pdf", 1)
        view._rows = [{
            "file": "ex.pdf", "_path": str(pdf), "_text": "x",
            "supplier": "Alpha AB", "missing": [],
            "total_amount": 1.0, "invoice_number": "1",
        }]
        monkeypatch.setattr(
            view, "_open_template_dialog",
            lambda row=None: opened.append(row),
        )
        view._manager_create_template()
        assert opened and opened[0]["file"] == "ex.pdf"
    finally:
        view.close()


# ── Omatchad import öppnar mallskapandet ───────────────────────────

def test_unmatched_import_opens_template_creation(tmp_path, monkeypatch):
    _qapp()
    import ui.scan_import_view as sv
    from ui.scan_import_view import ScanImportView

    view = ScanImportView(
        app=_fake_core(),
        templates_path=tmp_path / "invoice_templates.json",
    )
    pdf = _make_pdf(tmp_path / "okand.pdf", 1)
    calls = []
    monkeypatch.setattr(
        view, "_open_template_dialog",
        lambda row=None: calls.append(row),
    )
    try:
        unmatched = {
            "file": "okand.pdf", "_path": str(pdf), "template": "",
            "match_uncertain": False,
        }
        matched = dict(unmatched, template="Alpha AB")
        uncertain = dict(unmatched, match_uncertain=True)
        view._open_template_for_unmatched([matched, uncertain])
        assert calls == []
        view._open_template_for_unmatched([unmatched])
        assert calls == [unmatched]
    finally:
        view.close()
