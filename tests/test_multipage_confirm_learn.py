# -*- coding: utf-8 -*-
"""
Tester: flersidiga fakturor bekräftas av användaren + inlärning.

Användarens krav (2026-10-28): vid fler än 2 sidor matchade
appen fel belopp (921040: 857,25 från sida 1 i stället för
13 480 på sida 3). Kravet: det ska vara bombsäkert — därför
flaggas flersidiga fakturor ALLTID för manuell bekräftelse
(appen ber användaren matcha och kontrollera slutsumman),
och varje manuell matchning ska lära appen något: bekräftelser
räknas i ett inlärningsminne, en leverantör som bekräftats
upprepade gånger (med avstämd total) får till slut passera
utan fråga, och saknas mall härleds en VERIFIERAD mall ur de
bekräftade värdena.
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


SUPPLIERS = [{"name": "Testbolaget AB"}]
TEMPLATES = {
    "Testbolaget AB": {"fields": {
        "invoice_number": {"label": "Faktnr"},
        "total_amount": {"label": "Summa"},
    }},
}

TEXT_3P = (
    "Testbolaget AB\nFaktnr 921040\nSumma 857,25\n"
    "Specifikation sida 2\n"
    "Summa 13 480,00"
)


def _pdf(path: Path, page_texts: list[str]) -> Path:
    import fitz
    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page(width=595, height=842)
        page.insert_text((40, 40), text, fontsize=9)
    doc.save(path)
    doc.close()
    return path


# ── Flersidighetsvakten i tolkaren ──────────────────────────

def test_multipage_file_flagged_for_user_confirmation(tmp_path):
    """3-sidig faktura: även med mallträff flaggas den —
    användaren ska bekräfta, aldrig auto-litas på."""
    pdf = _pdf(tmp_path / "t.pdf", ["s1", "s2", "s3"])
    r = si.parse_invoice_file(pdf, TEXT_3P, SUPPLIERS, TEMPLATES)
    assert r["pages"] == 3
    assert r["template"] == "Testbolaget AB"
    assert r["total_amount"] == 13480.0
    assert r["match_uncertain"] is True
    assert r["match_kind"] == "multipage"
    assert r["match_candidates"] == ["Testbolaget AB"]


def test_single_page_not_flagged(tmp_path):
    pdf = _pdf(tmp_path / "t.pdf", ["s1"])
    r = si.parse_invoice_file(pdf, TEXT_3P, SUPPLIERS, TEMPLATES)
    assert r["pages"] == 1
    assert not r.get("match_uncertain")


def test_graduated_supplier_with_agreeing_total_passes(tmp_path):
    """Inlärd leverantör (2 bekräftade flersidiga) + total som
    stäms av mot texten → ingen ny fråga. Så blir appen bättre."""
    pdf = _pdf(tmp_path / "t.pdf", ["s1", "s2", "s3"])
    learning = {"Testbolaget AB": {"multipage_confirmed": 2}}
    r = si.parse_invoice_file(
        pdf, TEXT_3P, SUPPLIERS, TEMPLATES, match_learning=learning
    )
    assert not r.get("match_uncertain")


def test_graduated_but_disagreeing_total_still_flagged(tmp_path):
    """921040-fallet på riktigt: 857,25 fångat av mallen men
    13 480 står sist i texten — även en inlärd leverantör
    flaggas när läsningarna INTE stämmer överens."""
    pdf = _pdf(tmp_path / "t.pdf", ["s1", "s2", "s3"])
    text = (
        "Testbolaget AB\nFaktnr 921040\nSumma 857,25\n"
        "Att betala 13 480,00"
    )
    learning = {"Testbolaget AB": {"multipage_confirmed": 5}}
    r = si.parse_invoice_file(
        pdf, text, SUPPLIERS, TEMPLATES, match_learning=learning
    )
    assert r["total_amount"] == 857.25
    assert r["match_uncertain"] is True
    assert r["match_kind"] == "multipage"


def test_graduated_but_math_mismatch_still_flagged(tmp_path):
    """Räknekontrollen protesterar (netto+moms ≠ total) →
    flaggas trots inlärning."""
    pdf = _pdf(tmp_path / "t.pdf", ["s1", "s2", "s3"])
    text = (
        "Testbolaget AB\nFaktnr 921040\n"
        "Netto 1 000,00\nMoms 250,00\nSumma 13 480,00"
    )
    assert si.invoice_math_check(text, 13480.0)["status"] == "mismatch"
    learning = {"Testbolaget AB": {"multipage_confirmed": 2}}
    r = si.parse_invoice_file(
        pdf, text, SUPPLIERS, TEMPLATES, match_learning=learning
    )
    assert r["match_uncertain"] is True


# ── Inlärningsminnet ────────────────────────────────────────

def test_learning_memory_counts_and_graduates(tmp_path):
    learning: dict = {}
    si.record_match_confirmation(learning, "Testbolaget AB")
    entry = si.record_match_confirmation(
        learning, "Testbolaget AB", multipage=True
    )
    assert entry["confirmed"] == 2
    assert entry["multipage_confirmed"] == 1
    assert not si.learning_graduated(learning, "Testbolaget AB")
    si.record_match_confirmation(
        learning, "testbolaget ab", multipage=True
    )
    assert si.learning_graduated(learning, "Testbolaget AB")
    path = tmp_path / "match_memory.json"
    assert si.save_match_learning(path, learning)
    loaded = si.load_match_learning(path)
    assert si.learning_graduated(loaded, "Testbolaget AB")


def test_derive_template_from_confirmed_values():
    """Mall härleds BARA ur värden etiketterna läser tillbaka."""
    text = (
        "Nya Bolaget AB\nFakturanr 55\nAtt betala 857,25\n"
        "sista sidan\nAtt betala 700,00"
    )
    # 700,00 bekräftas INTE av texten (att betala sist = 700? jo,
    # sista träffen är 700,00) — pröva i stället ett värde som
    # ingen etikett ger tillbaka:
    assert si.derive_template_from_confirmation(text, "55", 999.0) is None
    tmpl = si.derive_template_from_confirmation(text, "55", 700.0)
    assert tmpl is not None
    found = si.apply_template(text, tmpl)
    assert found["invoice_number"] == "55"
    assert found["total_amount"] == 700.0


# ── Bevakningen parkerar flersidigt ─────────────────────────

def _watch(tmp_path, learning=None):
    from ui.watch_folders import WatchManager

    class App:
        def get_suppliers(self):
            return list(SUPPLIERS)

        def get_invoices(self):
            return []

    return WatchManager(
        tmp_path / "watch_folders.json", app=App(),
        extract_fn=lambda p: (TEXT_3P, "test"),
        templates_provider=lambda: dict(TEMPLATES),
        learning_provider=(lambda: learning) if learning is not None
        else None,
    )


def test_watch_parks_multipage_instead_of_registering(tmp_path):
    _qapp()
    folder = tmp_path / "In"
    folder.mkdir()
    mgr = _watch(tmp_path)
    mgr.set_folders([{"supplier": "", "path": str(folder)}])
    ready, parked = [], []
    mgr.invoice_ready.connect(lambda row, p: ready.append(row))
    mgr.file_parked.connect(lambda info: parked.append(info))
    _pdf(folder / "f.pdf", ["s1", "s2", "s3"])
    mgr.scan_all()
    assert ready == []
    assert len(parked) == 1
    assert parked[0]["reason"] == "uncertain-supplier"
    assert parked[0]["parsed"]["match_kind"] == "multipage"


def test_watch_graduated_supplier_registers_multipage(tmp_path):
    """Efter inlärning + avstämd total registreras bevakningens
    flersidiga faktura automatiskt igen — appen blev bättre."""
    _qapp()
    folder = tmp_path / "In"
    folder.mkdir()
    learning = {"Testbolaget AB": {"multipage_confirmed": 2}}
    mgr = _watch(tmp_path, learning=learning)
    mgr.set_folders([{"supplier": "", "path": str(folder)}])
    ready, parked = [], []
    mgr.invoice_ready.connect(lambda row, p: ready.append(row))
    mgr.file_parked.connect(lambda info: parked.append(info))
    _pdf(folder / "f.pdf", ["s1", "s2", "s3"])
    mgr.scan_all()
    assert len(ready) == 1
    assert float(ready[0]["total_amount"]) == 13480.0
    assert parked == []


# ── Vyn: bekräftelse + inlärning ────────────────────────────

class _Core:
    def __init__(self, suppliers):
        self._suppliers = suppliers

    def get_suppliers(self):
        return list(self._suppliers)

    def get_setting(self, key, default=None):
        return default


def _view(tmp_path, suppliers, templates):
    from ui.scan_import_view import ScanImportView

    view = ScanImportView(
        app=_Core(suppliers),
        templates_path=tmp_path / "invoice_templates.json",
    )
    view._templates_cache = dict(templates)
    return view


def _row(**kw):
    row = {
        "file": "okand.pdf", "supplier": "", "invoice_number": "",
        "date": "", "due_date": "", "ocr": "", "total_amount": 0.0,
        "method": "pdf", "status": "saknas: leverantör",
        "missing": ["leverantör"], "_path": "", "pages": 3,
        "_text": TEXT_3P,
    }
    row.update(kw)
    return row


def _drive_dialog(choose: str, amount: str | None = None):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import (
        QApplication, QComboBox, QDialog, QLineEdit,
    )

    def _act():
        dlg = QApplication.activeModalWidget()
        assert isinstance(dlg, QDialog), "ingen modal dialog öppen"
        combo = dlg.findChild(QComboBox)
        idx = combo.findText(choose)
        assert idx >= 0, f"{choose} saknas i listan"
        combo.setCurrentIndex(idx)
        if amount is not None:
            edit = dlg.findChild(QLineEdit)
            assert edit is not None, "inget beloppsfält i dialogen"
            edit.setText(amount)
        dlg.accept()

    QTimer.singleShot(50, _act)


def test_manual_match_corrects_amount_and_learns(tmp_path):
    """921040 i praktiken: appen läste 857,25 — användaren
    matchar, rättar beloppet till sista sidans 13 480 i samma
    dialog, och bekräftelsen räknas i inlärningsminnet."""
    _qapp()
    view = _view(tmp_path, SUPPLIERS, TEMPLATES)
    try:
        row = _row(total_amount=857.25, invoice_number="921040",
                   _text="Testbolaget AB\nFaktnr 921040\n"
                         "Summa 857,25\nSumma 13 480,00")
        view._rows = [row]
        view._refresh_table()
        view._tbl.selectRow(0)
        _drive_dialog("Testbolaget AB", amount="13 480,00")
        view._manual_match_row()
        assert row["supplier"] == "Testbolaget AB"
        assert float(row["total_amount"]) == 13480.0
        learning = view._get_match_learning()
        entry = si.learning_entry(learning, "Testbolaget AB")
        assert entry.get("multipage_confirmed") == 1
        assert (tmp_path / "match_memory.json").exists()
        assert "inlärning" in view._lbl_status.text().lower() or \
            "lär" in view._lbl_status.text().lower()
    finally:
        view.close()


def test_ask_confirmation_counts_towards_learning(tmp_path):
    """Den automatiska frågan vid Skapa fakturor lär också:
    bekräftad flersidig matchning räknas i minnet."""
    _qapp()
    view = _view(tmp_path, SUPPLIERS, TEMPLATES)
    try:
        row = _row(supplier="Testbolaget AB", invoice_number="921040",
                   total_amount=13480.0, match_uncertain=True,
                   match_kind="multipage", match_reason="multipage",
                   match_candidates=["Testbolaget AB"], missing=[],
                   status="redo")
        _drive_dialog("Testbolaget AB")
        assert view._ask_user_for_match(row) is True
        assert not row.get("match_uncertain")
        entry = si.learning_entry(
            view._get_match_learning(), "Testbolaget AB"
        )
        assert entry.get("multipage_confirmed") == 1
    finally:
        view.close()


def test_manual_match_teaches_template_for_new_supplier(tmp_path):
    """Ny leverantör utan mall: matchningen lär appen en
    VERIFIERAD mall (etiketterna läser tillbaka de bekräftade
    värdena), så nästa faktura matchas automatiskt."""
    _qapp()
    suppliers = [{"name": "Nya Bolaget AB"}]
    view = _view(tmp_path, suppliers, {})
    try:
        text = ("Nya Bolaget AB\nFakturanr 55\n"
                "Att betala 857,25\nAtt betala 700,00")
        row = _row(invoice_number="55", total_amount=700.0,
                   _text=text, pages=2)
        view._rows = [row]
        view._refresh_table()
        view._tbl.selectRow(0)
        _drive_dialog("Nya Bolaget AB")
        view._manual_match_row()
        templates = view._get_templates()
        assert "Nya Bolaget AB" in templates
        found = si.apply_template(text, templates["Nya Bolaget AB"])
        assert found["invoice_number"] == "55"
        assert found["total_amount"] == 700.0
        entry = si.learning_entry(
            view._get_match_learning(), "Nya Bolaget AB"
        )
        assert entry.get("template_learned") is True
    finally:
        view.close()
