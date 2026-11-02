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
