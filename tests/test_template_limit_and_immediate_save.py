# -*- coding: utf-8 -*-
"""Tests for immediate template saving on match and max 15 templates/supplier."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (
    str(PROJECT_DIR),
    str(PROJECT_DIR / "ui"),
    str(PROJECT_DIR / "plugins"),
):
    if _d not in sys.path:
        sys.path.insert(0, _d)

import pytest  # noqa: E402

import scan_import as si  # noqa: E402
from ui import i18n  # noqa: E402


@pytest.fixture(autouse=True)
def _sv():
    i18n.set_language("sv", notify=False)
    yield
    i18n.set_language("sv", notify=False)


def _qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _Core:
    def __init__(self, suppliers=None):
        self._suppliers = list(suppliers or [{"name": "Nordic Widget AB"}])
        self.created: list[dict] = []

    def get_suppliers(self):
        return list(self._suppliers)

    def get_invoices(self):
        return list(self.created)

    def add_invoice(self, data):
        record = dict(data, id=f"inv-{len(self.created) + 1}")
        self.created.append(record)
        return record

    def get_setting(self, _key, default=None):
        return default


class _Watch:
    folders: list = []

    def __init__(self):
        self.parked: list = []

    def reprocess_parked(self, entry=None, background=False):
        return 0

    def remove_parked(self, digest):
        self.parked = [
            entry for entry in self.parked
            if str(entry.get("hash", "")) != str(digest)
        ]


def _make_variant(idx: int) -> dict:
    return {
        "fields": {
            "invoice_number": {"label": f"FakturaRef_{idx}"},
            "total_amount": {"label": f"TotalAttBetala_{idx}"},
        }
    }


def _view(tmp_path, suppliers=None, templates=None):
    from ui.scan_import_view import ScanImportView

    templates_path = tmp_path / "invoice_templates.json"
    if templates:
        si.save_templates(templates_path, dict(templates))
    view = ScanImportView(
        app=_Core(suppliers), templates_path=templates_path,
    )
    view._watch = _Watch()
    return view


def test_immediate_template_save_on_match_before_invoice_creation(
    tmp_path, monkeypatch,
):
    """Matching saves a verified template right away even when row stays uncreated."""
    _qapp()
    import ui.scan_import_view as sv

    monkeypatch.setattr(sv.QMessageBox, "information", lambda *_a, **_k: None)
    view = _view(tmp_path)
    try:
        text = "Nordic Widget AB\nFakturanr NW-101\nAtt betala 1 250,00"
        row = {
            "file": "nw-101.pdf",
            "supplier": "",
            "invoice_number": "NW-101",
            "date": "2026-10-05",
            "due_date": "2026-11-05",
            "ocr": "",
            "total_amount": 1250.0,
            "method": "pdf",
            "status": "saknas: leverantör",
            "missing": ["leverantör"],
            "ocr_warning": "kontrollera ocr",
            "_path": str(tmp_path / "nw-101.pdf"),
            "_text": text,
            "pages": 1,
        }
        view._rows = [row]
        note = view._apply_manual_match(row, "Nordic Widget AB")
        view._refresh_table()

        saved_templates = si.load_templates(tmp_path / "invoice_templates.json")
        assert "Nordic Widget AB" in saved_templates
        found = si.apply_template(text, saved_templates["Nordic Widget AB"])
        assert found["invoice_number"] == "NW-101"
        assert found["total_amount"] == 1250.0
        assert view._app.created == []
        assert row.get("template") == "Nordic Widget AB"
        assert row.get("status") == "redo"
        assert "🧩" in view._tbl.item(0, 8).text()
        assert "mall" in note.lower()

        learning = si.load_match_learning(tmp_path / "match_memory.json")
        entry = si.learning_entry(learning, "Nordic Widget AB")
        assert entry["confirmed"] == 1
        assert entry["template_learned"] is True
        tmpl_conf = si.template_confirmation_entry(
            learning, "Nordic Widget AB", saved_templates["Nordic Widget AB"]
        )
        assert tmpl_conf["confirmed"] == 1

        # Later registration of the same row must not double-count confirmations.
        row.pop("ocr_warning", None)
        assert view._record_confirmed_template_row(row) == ""
        learning_after = si.load_match_learning(tmp_path / "match_memory.json")
        assert si.learning_entry(learning_after, "Nordic Widget AB")["confirmed"] == 1
        assert si.template_confirmation_entry(
            learning_after, "Nordic Widget AB", saved_templates["Nordic Widget AB"]
        )["confirmed"] == 1
    finally:
        view.close()


def test_matching_rescan_immediately_uses_newly_saved_template(
    tmp_path, monkeypatch,
):
    """Other pending rows parse immediately with the template saved on match."""
    _qapp()
    import ui.scan_import_view as sv

    monkeypatch.setattr(sv.QMessageBox, "information", lambda *_a, **_k: None)
    view = _view(tmp_path)
    try:
        t1 = "Nordic Widget AB\nEr ref hos oss: NW-1\nSlutsumma: 400,00"
        t2 = "Nordic Widget AB\nEr ref hos oss: NW-2\nSlutsumma: 800,00"
        row1 = {
            "file": "nw1.pdf", "supplier": "", "invoice_number": "NW-1",
            "date": "2026-10-05", "due_date": "", "ocr": "",
            "total_amount": 400.0, "missing": ["leverantör"],
            "ocr_warning": "review", "_path": str(tmp_path / "nw1.pdf"),
            "_text": t1, "pages": 1,
        }
        # row2 could not be parsed accurately before matching; once NW learns
        # the new layout on row1, row2 gets parsed with the saved template.
        # Derive uses _REPAIR_LABELS; test with known repair labels!
        t1_known = "Nordic Widget AB\nFakturanr NW-1\nAtt betala 400,00"
        t2_known = (
            "Nordic Widget AB\n"
            "Delsumma 50,00\n"
            "Fakturanr NW-2\n"
            "Att betala 800,00"
        )
        row1["_text"] = t1_known
        row2 = {
            "file": "nw2.pdf", "supplier": "", "invoice_number": "",
            "date": "", "due_date": "", "ocr": "",
            "total_amount": 0.0, "missing": ["belopp", "fakturanummer", "leverantör"],
            "_path": str(tmp_path / "nw2.pdf"), "_text": t2_known, "pages": 1,
            "match_uncertain": True, "match_candidates": ["Nordic Widget AB"],
        }
        view._rows = [row1, row2]
        view._apply_manual_match(row1, "Nordic Widget AB")

        assert row2["supplier"] == "Nordic Widget AB"
        assert row2["template"] == "Nordic Widget AB"
        assert row2["invoice_number"] == "NW-2"
        assert row2["total_amount"] == 800.0
    finally:
        view.close()


def test_matching_new_layout_adds_variant_without_losing_existing(
    tmp_path, monkeypatch,
):
    """Matching a second layout saves a second variant and avoids duplicates."""
    _qapp()
    import ui.scan_import_view as sv

    monkeypatch.setattr(sv.QMessageBox, "information", lambda *_a, **_k: None)
    initial = {
        "Nordic Widget AB": {
            "fields": {
                "invoice_number": {"label": "Faktnr"},
                "total_amount": {"label": "Summa"},
            }
        }
    }
    view = _view(tmp_path, templates=initial)
    try:
        layout2_text = "Nordic Widget AB\nFakturanr V2-77\nAtt betala 950,00"
        row = {
            "file": "v2.pdf", "supplier": "", "invoice_number": "V2-77",
            "date": "2026-10-06", "due_date": "", "ocr": "",
            "total_amount": 950.0, "missing": ["leverantör"],
            "ocr_warning": "wait",
            "_path": str(tmp_path / "v2.pdf"),
            "_text": layout2_text, "pages": 1,
        }
        view._rows = [row]
        view._apply_manual_match(row, "Nordic Widget AB")

        saved = si.load_templates(tmp_path / "invoice_templates.json")
        variants = si.template_variants(saved["Nordic Widget AB"])
        assert len(variants) == 2

        # Matching the exact same layout again does NOT create a 3rd variant.
        row_dup = {
            "file": "v2-dup.pdf", "supplier": "", "invoice_number": "V2-88",
            "date": "2026-10-07", "due_date": "", "ocr": "",
            "total_amount": 320.0, "missing": ["leverantör"],
            "ocr_warning": "wait",
            "_path": str(tmp_path / "v2-dup.pdf"),
            "_text": "Nordic Widget AB\nFakturanr V2-88\nAtt betala 320,00",
            "pages": 1,
        }
        view._rows.append(row_dup)
        view._apply_manual_match(row_dup, "Nordic Widget AB")
        saved_again = si.load_templates(tmp_path / "invoice_templates.json")
        assert len(si.template_variants(saved_again["Nordic Widget AB"])) == 2

        # Both old and new layouts parse cleanly via parse_invoice_text.
        p1 = si.parse_invoice_text(
            "Nordic Widget AB\nFaktnr V1-10\nSumma 500,00",
            [{"name": "Nordic Widget AB"}],
            saved_again,
        )
        p2 = si.parse_invoice_text(
            "Nordic Widget AB\nFakturanr V2-99\nAtt betala 640,00",
            [{"name": "Nordic Widget AB"}],
            saved_again,
        )
        assert p1["invoice_number"] == "V1-10" and p1["total_amount"] == 500.0
        assert p2["invoice_number"] == "V2-99" and p2["total_amount"] == 640.0
    finally:
        view.close()


def test_max_15_templates_per_supplier_and_oldest_eviction():
    """Suppliers hold at most 15 variants; the 16th evicts the oldest unused one."""
    assert si.MAX_TEMPLATES_PER_SUPPLIER == 15

    templates: dict = {}
    for idx in range(1, 16):
        si.store_supplier_template(templates, "Alpha AB", _make_variant(idx))
    assert len(si.template_variants(templates["Alpha AB"])) == 15

    # Every one of the 15 variants parses its layout cleanly.
    for idx in range(1, 16):
        parsed = si.parse_invoice_text(
            f"Alpha AB\nFakturaRef_{idx} A-{idx}\nTotalAttBetala_{idx} {idx * 10},00",
            [{"name": "Alpha AB"}],
            templates,
        )
        assert parsed["invoice_number"] == f"A-{idx}"
        assert parsed["total_amount"] == float(idx * 10)

    # Touch variant #1 so #2 becomes the oldest unused, then add #16.
    si.store_supplier_template(templates, "Alpha AB", _make_variant(1))
    si.store_supplier_template(templates, "Alpha AB", _make_variant(16))
    variants = si.template_variants(templates["Alpha AB"])
    assert len(variants) == 15

    labels = [
        v["fields"]["invoice_number"]["label"] for v in variants
    ]
    assert "FakturaRef_2" not in labels
    assert "FakturaRef_1" in labels
    assert "FakturaRef_16" in labels


def test_max_15_caps_in_match_memory_and_supplier_logos():
    """Match memory template entries and supplier_logos are also capped at 15."""
    learning: dict = {}
    for idx in range(1, 18):
        si.record_template_confirmation(
            learning,
            "Beta AB",
            "Beta AB",
            _make_variant(idx),
            confirmation_id=f"c-{idx}",
            template_fields=["invoice_number", "total_amount"],
        )
    assert len(learning["Beta AB"]["templates"]) == 15

    templates: dict = {}
    for idx in range(1, 18):
        si.store_supplier_template(
            templates,
            "Beta AB",
            {
                "fields": {"invoice_number": {"label": "Faktnr"}, "total_amount": {"label": "Summa"}},
                "supplier_logo": {
                    "page": 0,
                    "region": [0.1, 0.1, 0.2, 0.2],
                    "dhash": f"dhash128-v1:{idx:032x}",
                },
            },
        )
    assert len(si.supplier_logo_specs(templates["Beta AB"])) == 15


def test_conflicting_variants_for_same_supplier_are_flagged_ambiguous():
    """Conflicting variants on the same text set template_ambiguous."""
    templates: dict = {}
    si.store_supplier_template(templates, "Alpha AB", {
        "fields": {
            "invoice_number": {"label": "Ref A"},
            "total_amount": {"label": "Total A"},
        }
    })
    si.store_supplier_template(templates, "Alpha AB", {
        "fields": {
            "invoice_number": {"label": "Ref B"},
            "total_amount": {"label": "Total B"},
        }
    })
    parsed = si.parse_invoice_text(
        "Alpha AB\nRef A 111\nTotal A 100,00\nRef B 222\nTotal B 200,00",
        [{"name": "Alpha AB"}],
        templates,
    )
    assert parsed["match_uncertain"] is True
    assert parsed["match_reason"] == "template_ambiguous"


def test_templates_manager_displays_variant_count_sv_and_en(tmp_path):
    """TemplatesManagerDialog shows N/15 mallar/templates when >1 variants exist."""
    _qapp()
    from ui.scan_import_view import TemplatesManagerDialog

    templates: dict = {}
    si.store_supplier_template(templates, "Alpha AB", _make_variant(1))
    si.store_supplier_template(templates, "Alpha AB", _make_variant(2))
    si.store_supplier_template(templates, "Alpha AB", _make_variant(3))
    si.store_supplier_template(templates, "Beta AB", _make_variant(1))

    dlg = TemplatesManagerDialog(None, templates, lambda _name: None)
    try:
        items_sv = [dlg._list.item(i).text() for i in range(dlg._list.count())]
        assert any("3/15 mallar" in t for t in items_sv)
        assert not any("1/15" in t for t in items_sv)

        i18n.set_language("en", notify=False)
        dlg._refresh_list()
        items_en = [dlg._list.item(i).text() for i in range(dlg._list.count())]
        assert any("3/15 templates" in t for t in items_en)
    finally:
        dlg.close()


def test_invoices_view_learn_manual_match_adds_variant_up_to_15(tmp_path):
    """InvoicesView manual match derives a new variant when existing doesn't fit."""
    _qapp()
    from ui.invoices_view import InvoicesView

    class _InvCore:
        data_dir = tmp_path

        def get_suppliers(self):
            return [{"name": "Alpha AB"}]

        def get_invoices(self):
            return []

        def get_setting(self, _k, default=None):
            return default

    templates_file = tmp_path / "invoice_templates.json"
    si.save_templates(templates_file, {
        "Alpha AB": {"fields": {
            "invoice_number": {"label": "Faktnr"},
            "total_amount": {"label": "Summa"},
        }}
    })
    view = InvoicesView(_InvCore())
    view._scan_data_dir = lambda: tmp_path  # type: ignore[method-assign]
    try:
        note = view._learn_manual_match(
            si,
            "Alpha AB",
            "Alpha AB\nFakturanr A-90\nAtt betala 750,00",
            "A-90",
            750.0,
            1,
        )
        saved = si.load_templates(templates_file)
        assert len(si.template_variants(saved["Alpha AB"])) == 2
        assert "mall" in note.lower() or "template" in note.lower()
    finally:
        view.close()
