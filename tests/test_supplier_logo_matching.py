# -*- coding: utf-8 -*-
"""Bankgiro- och PDF-logotypmatchning får aldrig gissa vid osäkerhet."""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_DIR = Path(__file__).resolve().parent.parent
for _directory in (
    str(PROJECT_DIR), str(PROJECT_DIR / "ui"),
    str(PROJECT_DIR / "plugins"),
):
    if _directory not in sys.path:
        sys.path.insert(0, _directory)

import scan_import as si


LOGO_HASH = "dhash128-v1:" + "0123456789abcdef" * 2


def test_bankgiro_matching_requires_an_exact_labeled_number():
    text = "Betalning till bankgiro: 123-4567\nTelefon 7654321"
    assert si.invoice_bankgiro_values(text) == ["1234567"]
    suppliers = [
        {"name": "Alpha AB", "bankgiro": "123-4567"},
        {"name": "Beta AB", "bankgiro": "000-0000"},
    ]
    assert si.suppliers_matching_bankgiro(text, suppliers) == [
        {"name": "Alpha AB", "bankgiro": "1234567"}
    ]
    # Samma sifferrad utan BG-etikett är inte ett säkert kännetecken.
    assert si.invoice_bankgiro_values("Telefon 123-4567") == []
    assert si.suppliers_matching_bankgiro("Telefon 123-4567", suppliers) == []


def test_bankgiro_conflicts_are_returned_as_multiple_choices():
    text = "Bankgiro 1234567"
    suppliers = [
        {"name": "Alpha AB", "bankgiro": "1234567"},
        {"name": "Beta AB", "bg": "123-4567"},
    ]
    assert si.suppliers_matching_bankgiro(text, suppliers) == [
        {"name": "Alpha AB", "bankgiro": "1234567"},
        {"name": "Beta AB", "bankgiro": "1234567"},
    ]


def _logo_png() -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (200, 160), "white")
    draw = ImageDraw.Draw(image)
    # En detaljrik, riktig bildyta i testfilen (inte en monogramtile).
    draw.rounded_rectangle((24, 32, 116, 126), radius=13, fill="#157a58")
    draw.polygon(((42, 99), (70, 47), (97, 99)), fill="#f3d35c")
    draw.ellipse((70, 68, 106, 104), fill="#234a83")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_logo_signature_hashes_the_marked_pdf_image_region():
    png = _logo_png()
    region = (0.10, 0.15, 0.62, 0.85)
    signature = si._supplier_logo_hash_from_png(png, region)
    assert signature.startswith("dhash128-v1:")
    assert len(signature.split(":", 1)[1]) == 32
    assert si.supplier_logo_distance(signature, signature) == 0
    # Tom vit yta blir inte en igenkänningssignatur.
    assert si._supplier_logo_hash_from_png(
        png, (0.75, 0.05, 0.98, 0.25)
    ) == ""


def test_logo_signature_and_matching_run_on_a_real_pdf_page(tmp_path):
    import fitz

    path = tmp_path / "invoice.pdf"
    document = fitz.open()
    page = document.new_page(width=400, height=300)
    page.draw_rect(
        fitz.Rect(40, 40, 180, 160),
        color=(0.08, 0.35, 0.25), fill=(0.08, 0.35, 0.25),
    )
    page.draw_circle((110, 100), 38, color=(1, 1, 1), fill=(1, 1, 1))
    page.draw_line((84, 116), (110, 68), color=(0.85, 0.65, 0.1), width=9)
    page.draw_line((110, 68), (136, 116), color=(0.85, 0.65, 0.1), width=9)
    document.save(path)
    document.close()

    region = (0.10, 0.13, 0.46, 0.55)
    signature = si.supplier_logo_signature(path, 0, region)
    assert signature.startswith("dhash128-v1:")
    matches = si.supplier_logo_match_candidates(path, {
        "Alpha AB": {"supplier_logo": {
            "page": 0, "region": region, "dhash": signature,
        }},
    })
    assert matches == [{
        "name": "Alpha AB", "distance": 0, "dhash": signature,
    }]


def test_pdf_logo_region_suggestions_find_embedded_images_and_vectors(
    tmp_path,
):
    import fitz

    png = _logo_png()
    path = tmp_path / "embedded-logo.pdf"
    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_image(fitz.Rect(36, 28, 170, 112), stream=png)
    # Vector artwork (as used by many PDF/SVG logos) is not a separate
    # SVG file; it is drawn into the PDF page as paths.
    page.draw_rect(
        fitz.Rect(370, 34, 500, 105),
        color=(0.05, 0.3, 0.5), fill=(0.05, 0.3, 0.5),
    )
    page.draw_circle(
        (435, 69), 20, color=(1, 1, 1), fill=(1, 1, 1),
    )
    page.draw_line((420, 78), (435, 48), color=(0.9, 0.7, 0.1), width=5)
    page.draw_line((435, 48), (450, 78), color=(0.9, 0.7, 0.1), width=5)
    document.save(path)
    document.close()

    candidates = si.supplier_logo_region_candidates(path)
    assert any(item["source"] == "embedded_image" for item in candidates)
    assert any(item["source"] == "vector_art" for item in candidates)
    assert all(
        0 <= item["region"][0] < item["region"][2] <= 1
        and 0 <= item["region"][1] < item["region"][3] <= 1
        for item in candidates
    )
    assert si.supplier_logo_region_candidates(
        tmp_path / "not-a-pdf.png"
    ) == []


def test_full_page_scan_only_suggests_header_areas_for_review(tmp_path):
    import fitz

    path = tmp_path / "scanned.pdf"
    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_image(page.rect, stream=_logo_png())
    document.save(path)
    document.close()

    candidates = si.supplier_logo_region_candidates(path)
    assert len(candidates) == 2
    assert {item["source"] for item in candidates} == {"header_area"}
    assert all(item["page"] == 0 for item in candidates)


def test_template_dialog_previews_selected_pdf_logo_candidate_before_save(
    tmp_path, monkeypatch,
):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    import fitz
    import ui.scan_import_view as scan_ui
    from ui.scan_import_view import TemplateDialog

    path = tmp_path / "invoice.pdf"
    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_image(fitz.Rect(36, 28, 170, 112), stream=_logo_png())
    document.save(path)
    document.close()

    candidates = si.supplier_logo_region_candidates(path)
    assert candidates
    monkeypatch.setattr(
        scan_ui.QInputDialog, "getItem",
        lambda _parent, _title, _prompt, labels, *_args: (labels[0], True),
    )
    dialog = TemplateDialog(
        None, "", supplier="Alpha AB", existing=None, path=path,
        suppliers=[{"name": "Alpha AB"}], templates={},
        logo_only=True, suggest_logo_match=False,
    )
    try:
        dialog._suggest_logo_regions()
        assert dialog._pending_logo_candidate is not None
        assert dialog._logo_region == (
            candidates[0]["page"], tuple(candidates[0]["region"])
        )
        # Merely selecting a suggestion neither saves a template nor
        # confirms the invoice; the user still has to press Save.
        assert dialog.result_template is None
        dialog._save()
        saved = si.supplier_logo_specs(dialog.result_template)
        assert saved
        assert saved[-1]["dhash"] == dialog._logo_hash
    finally:
        dialog.close()


def test_logo_mark_dialog_exposes_an_explicit_supplier_dropdown():
    from PySide6.QtWidgets import QApplication, QComboBox

    QApplication.instance() or QApplication([])
    from ui.scan_import_view import TemplateDialog

    dialog = TemplateDialog(
        None, "", supplier="Alpha AB", path=None,
        suppliers=[{"name": "Alpha AB"}, {"name": "Beta AB"}],
        templates={"Alpha AB": {}, "Beta AB": {}},
        logo_only=True, suggest_logo_match=False,
    )
    try:
        assert isinstance(dialog._supplier_edit, QComboBox)
        assert not dialog._supplier_edit.isEditable()
        assert dialog._supplier_edit.currentText() == "Alpha AB"
        beta_index = dialog._supplier_edit.findText("Beta AB")
        assert beta_index >= 0
        dialog._supplier_edit.setCurrentIndex(beta_index)
        assert dialog._supplier_edit.currentText() == "Beta AB"
    finally:
        dialog.close()


def test_marked_logo_dropdown_reassigns_candidate_and_preserves_variants(
    tmp_path, monkeypatch,
):
    from PySide6.QtWidgets import (
        QApplication, QComboBox, QDialog, QLabel, QPushButton, QWidget,
    )

    QApplication.instance() or QApplication([])
    import ui.scan_import_view as scan_ui

    def logo_spec(hex_digit: str, page: int = 0) -> dict:
        return {
            "page": page,
            "region": [0.1, 0.1, 0.4, 0.4],
            "dhash": "dhash128-v1:" + hex_digit * 32,
        }

    alpha_logo = logo_spec("a")
    beta_logo_1 = logo_spec("1")
    beta_logo_2 = logo_spec("2", page=1)
    new_beta_logo = logo_spec("b", page=2)
    original_templates = {
        "Alpha AB": {
            "fields": {},
            "supplier_logo": alpha_logo,
        },
        "Beta AB": {
            "fields": {"due_date": {"label": "Förfallodatum"}},
            "supplier_logo": beta_logo_1,
            "supplier_logos": [beta_logo_1, beta_logo_2],
        },
    }
    saved_path = tmp_path / "invoice_templates.json"

    class FakeTemplateDialog:
        def __init__(self, *_args, suppliers, **_kwargs):
            self._supplier_edit = QComboBox()
            self._supplier_edit.addItems([
                str(item["name"]) for item in suppliers
            ])
            self._supplier_edit.setCurrentIndex(
                self._supplier_edit.findText("Beta AB")
            )
            self._btn_match_bg = QPushButton()
            self.result_template = {
                "supplier": "Beta AB",
                "fields": {},
                "supplier_logo": new_beta_logo,
                "supplier_logos": [new_beta_logo],
            }

        def setWindowTitle(self, _title):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

    class ViewHarness:
        _templates_cache = None

        def _get_templates(self):
            return original_templates

        def _suppliers(self):
            return [{"name": "Alpha AB"}, {"name": "Beta AB"}]

        def _templates_file(self):
            return saved_path

        def _refresh_templates_btn(self):
            self.refreshed = True

    monkeypatch.setattr(scan_ui, "TemplateDialog", FakeTemplateDialog)
    monkeypatch.setattr(scan_ui, "_scan_module", lambda: si)
    monkeypatch.setattr(si, "page_image_count", lambda _path: 1)

    match_combo = QComboBox()
    match_combo.addItem("Alpha AB")
    row = {
        "_path": "invoice.pdf", "_text": "", "file": "invoice.pdf",
        "match_uncertain": True,
    }
    row_before = dict(row)
    parent = QWidget()
    note = QLabel()
    view = ViewHarness()
    try:
        assert scan_ui.ScanImportView._mark_supplier_logo_for_match(
            view, row, match_combo, parent, note
        )

        saved = si.load_templates(saved_path)
        beta_specs = si.supplier_logo_specs(saved["Beta AB"])
        assert beta_specs == [beta_logo_1, beta_logo_2, new_beta_logo]
        assert saved["Beta AB"]["fields"] == original_templates[
            "Beta AB"
        ]["fields"]
        assert saved["Alpha AB"] == original_templates["Alpha AB"]
        assert match_combo.currentText() == "Beta AB"
        # Marking/saving the logo only changes supplier-template state;
        # it does not apply or confirm the invoice row.
        assert row == row_before
        assert view.refreshed
    finally:
        parent.close()


def test_multiple_saved_logo_variants_match_once_per_supplier(monkeypatch):
    png = _logo_png()
    region_a = (0.10, 0.15, 0.62, 0.85)
    region_b = (0.12, 0.17, 0.65, 0.87)
    signature_a = si._supplier_logo_hash_from_png(png, region_a)
    signature_b = si._supplier_logo_hash_from_png(png, region_b)
    assert signature_a and signature_b
    rendered_pages = []

    def render(_path, page, dpi=150):
        rendered_pages.append(page)
        return png if page == 1 else None

    monkeypatch.setattr(si, "render_page_image", render)
    logo_a = {
        "page": 0, "region": list(region_a), "dhash": signature_a,
    }
    logo_b = {
        "page": 1, "region": list(region_b), "dhash": signature_b,
    }
    templates = {
        "Alpha AB": {
            "supplier_logo": logo_a,
            "supplier_logos": [logo_a, logo_b],
        },
        "Beta AB": {"supplier_logo": {
            "page": 0, "region": region_a,
            "dhash": "dhash128-v1:" + "f" * 32,
        }},
    }
    assert len(si.supplier_logo_specs(templates["Alpha AB"])) == 2
    matches = si.supplier_logo_match_candidates("invoice.pdf", templates)
    assert rendered_pages == [0, 1]
    assert len(matches) == 1
    assert matches[0]["name"] == "Alpha AB"
    assert matches[0]["distance"] == 0
    assert matches[0]["dhash"] == signature_b


def test_confirmed_logo_signature_checks_all_saved_variants(monkeypatch):
    first = "dhash128-v1:" + "1" * 32
    second = "dhash128-v1:" + "2" * 32
    templates = {"Alpha AB": {
        "supplier_logo": {
            "page": 0, "region": [0.1, 0.1, 0.3, 0.3],
            "dhash": first,
        },
        "supplier_logos": [
            {"page": 0, "region": [0.1, 0.1, 0.3, 0.3],
             "dhash": first},
            {"page": 0, "region": [0.6, 0.1, 0.8, 0.3],
             "dhash": second},
        ],
    }}
    monkeypatch.setattr(
        si, "supplier_logo_signature",
        lambda _path, _page, region: (
            second if region[0] > 0.5 else "dhash128-v1:" + "f" * 32
        ),
    )
    assert si.confirmed_supplier_logo_signature(
        "invoice.pdf", "Alpha AB", templates
    ) == second


def test_confirmed_logo_signature_resolves_a_registered_alias(monkeypatch):
    signature = LOGO_HASH
    monkeypatch.setattr(
        si, "supplier_logo_signature", lambda *_args: signature,
    )
    templates = {"Alpha Trading": {"supplier_logo": {
        "page": 0, "region": [0.1, 0.1, 0.4, 0.4],
        "dhash": signature,
    }}}
    suppliers = [{"name": "Alpha Holdings AB", "aliases": ["Alpha Trading"]}]
    assert si.confirmed_supplier_logo_signature(
        "invoice.pdf", "Alpha Holdings AB", templates,
        suppliers=suppliers,
    ) == signature
    shared_alias_suppliers = suppliers + [{
        "name": "Alpha Trading AB", "aliases": ["Alpha Trading"],
    }]
    assert si.confirmed_supplier_logo_signature(
        "invoice.pdf", "Alpha Holdings AB", templates,
        suppliers=shared_alias_suppliers,
    ) == ""


def test_confirmed_logo_signature_is_counted_only_for_its_supplier(
    monkeypatch,
):
    signature = LOGO_HASH
    monkeypatch.setattr(
        si, "supplier_logo_signature", lambda *_args: signature,
    )
    templates = {"Alpha AB": {"supplier_logo": {
        "page": 0, "region": [0.1, 0.1, 0.4, 0.4],
        "dhash": signature,
    }}}
    assert si.confirmed_supplier_logo_signature(
        "invoice.pdf", "Alpha AB", templates
    ) == signature
    assert si.confirmed_supplier_logo_signature(
        "invoice.pdf", "Unknown AB", templates
    ) == ""

    monkeypatch.setattr(
        si, "supplier_logo_signature",
        lambda *_args: "dhash128-v1:" + "f" * 32,
    )
    assert si.confirmed_supplier_logo_signature(
        "invoice.pdf", "Alpha AB", templates
    ) == ""


def test_learned_match_from_alternate_pdf_text_reader_is_used(monkeypatch):
    learning = {}
    confirmed_text = "Bankgiro 999-1234\nFakturanr A-99\nAtt betala 250,00"
    for _ in range(si.LEARNED_SUPPLIER_CONFIRMATIONS):
        si.record_match_confirmation(
            learning, "Alpha AB", text=confirmed_text,
        )
    monkeypatch.setattr(
        si, "extract_pdf_texts",
        lambda _path: [(confirmed_text, "secondary-reader")],
    )
    result = si._parse_with_reader_fallback(
        "invoice.pdf", "Fakturanr A-99\nAtt betala 250,00",
        [], {}, match_learning=learning,
    )
    assert result["supplier"] == "Alpha AB"
    assert result["supplier_match"]["reason"] == "learned"


def test_logo_candidates_compare_saved_real_pdf_regions(monkeypatch):
    png = _logo_png()
    region = (0.10, 0.15, 0.62, 0.85)
    signature = si._supplier_logo_hash_from_png(png, region)
    monkeypatch.setattr(
        si, "render_page_image",
        lambda path, page, dpi=150: png if page == 0 else None,
    )
    templates = {
        "Alpha AB": {"supplier_logo": {
            "page": 0, "region": region, "dhash": signature,
        }},
        "Beta AB": {"supplier_logo": {
            "page": 0, "region": region,
            "dhash": "dhash128-v1:" + "f" * 32,
        }},
    }
    matches = si.supplier_logo_match_candidates("invoice.pdf", templates)
    assert matches == [{
        "name": "Alpha AB", "distance": 0, "dhash": signature,
    }]


def test_unlearned_logo_is_only_a_candidate_not_an_automatic_match(monkeypatch):
    signature = LOGO_HASH
    monkeypatch.setattr(
        si, "supplier_logo_match_candidates",
        lambda path, templates: [{
            "name": "Alpha AB", "distance": 2, "dhash": signature,
        }],
    )
    result = {
        "supplier": "", "invoice_number": "A-1", "total_amount": 250.0,
        "missing": [], "supplier_match": {"status": "none"},
    }
    matched = si._apply_supplier_logo_match(
        result, "invoice.pdf", "", {"Alpha AB": {}}, {},
    )
    assert matched["supplier"] == ""
    assert matched["match_uncertain"] is True
    assert matched["match_reason"] == "supplier_logo"
    assert matched["match_candidates"][0]["name"] == "Alpha AB"


def test_competing_learned_logo_candidates_are_never_auto_selected(
    monkeypatch,
):
    signatures = {
        "Alpha AB": "dhash128-v1:" + "1" * 32,
        "Beta AB": "dhash128-v1:" + "2" * 32,
    }
    monkeypatch.setattr(
        si, "supplier_logo_match_candidates",
        lambda path, templates: [
            {"name": "Alpha AB", "distance": 1,
             "dhash": signatures["Alpha AB"]},
            {"name": "Beta AB", "distance": 2,
             "dhash": signatures["Beta AB"]},
        ],
    )
    learning = {}
    for name, signature in signatures.items():
        for _ in range(5):
            si.record_match_confirmation(
                learning, name, logo_signature=signature,
            )
    result = {
        "supplier": "", "invoice_number": "A-1", "total_amount": 250.0,
        "missing": [], "supplier_match": {"status": "none"},
    }
    matched = si._apply_supplier_logo_match(
        result, "invoice.pdf", "", {name: {} for name in signatures},
        learning,
    )
    assert matched["supplier"] == ""
    assert matched["match_uncertain"] is True
    assert {item["name"] for item in matched["match_candidates"]} == set(
        signatures
    )


def test_text_logo_supplier_conflict_becomes_a_question(monkeypatch):
    signature = LOGO_HASH
    monkeypatch.setattr(
        si, "supplier_logo_match_candidates",
        lambda path, templates: [{
            "name": "Beta AB", "distance": 1, "dhash": signature,
        }],
    )
    result = {
        "supplier": "Alpha AB", "invoice_number": "A-1",
        "total_amount": 250.0, "missing": [],
        "supplier_match": {"status": "matched", "supplier": "Alpha AB"},
    }
    matched = si._apply_supplier_logo_match(
        result, "invoice.pdf", "", {"Beta AB": {}}, {},
    )
    assert matched["supplier"] == ""
    assert matched["match_uncertain"] is True
    assert matched["match_reason"] == "logo_conflict"
    assert {item["name"] for item in matched["match_candidates"]} == {
        "Alpha AB", "Beta AB",
    }


def test_logo_auto_match_requires_five_confirmations_and_two_observations(
    monkeypatch,
):
    signature = LOGO_HASH
    templates = {"Alpha AB": {"fields": {
        "invoice_number": {"label": "Fakturanr"},
        "total_amount": {"label": "Att betala"},
    }, "supplier_logo": {"dhash": signature}}}
    monkeypatch.setattr(
        si, "supplier_logo_match_candidates",
        lambda path, _templates: [{
            "name": "Alpha AB", "distance": 1, "dhash": signature,
        }],
    )
    text = "Fakturanr A-99\nAtt betala 250,00"

    not_enough = {}
    for _ in range(5):
        si.record_match_confirmation(
            not_enough, "Alpha AB", logo_signature=signature,
        )
    # Fem confirmationer men logotyp bara sedd en gång: fortfarande osäkert.
    not_enough["Alpha AB"]["logos"][signature] = 1
    result = {
        "supplier": "", "invoice_number": "", "total_amount": 0,
        "missing": [], "supplier_match": {"status": "none"},
    }
    uncertain = si._apply_supplier_logo_match(
        result, None, text, templates, not_enough,
    )
    assert uncertain["supplier"] == ""
    assert uncertain["match_uncertain"] is True

    learned = {}
    for _ in range(5):
        si.record_match_confirmation(
            learned, "Alpha AB", logo_signature=signature,
        )
    result = {
        "supplier": "", "invoice_number": "", "total_amount": 0,
        "missing": [], "supplier_match": {"status": "none"},
    }
    matched = si._apply_supplier_logo_match(
        result, None, text, templates, learned,
    )
    assert matched["supplier"] == "Alpha AB"
    assert matched["invoice_number"] == "A-99"
    assert matched["total_amount"] == 250.0
    assert not matched.get("match_uncertain")
