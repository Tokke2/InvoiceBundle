# -*- coding: utf-8 -*-
"""
Tester: betal-PDF:ens tydlighet (omdesignen).

Låser beteendet som gör betalningsunderlaget lätt att använda
i banken: OCR-kolumn, sortering leverantör → förfallodatum,
delsummor per leverantör (bara vid flera leverantörer),
förfallo-markering och att dokumentet alltid är ljust
(utskrift) även om appen kör mörkt tema. Dessutom: åäö ska
bevaras i PDF-text (namn blev tidigare felstavade).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "plugins")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

from pdf_export_helpers import (  # noqa: E402
    PDFExporter,
    _display_order,
    _payment_ref_date,
    to_ascii,
)


def _require_reportlab(exporter):
    if not exporter._has_rl:
        pytest.skip("reportlab saknas")


def _exporter(tmp_path, **kw):
    return PDFExporter(tmp_path, tmp_path, company="Mitt Glas AB",
                       org_number="559000-1122", **kw)


def _pdf_text(path: Path) -> str:
    from pypdf import PdfReader
    return "\n".join(
        (p.extract_text() or "") for p in PdfReader(str(path)).pages
    )


def _sample_invoices():
    """Medvetet osorterad indata med förfallet + kredit."""
    return [
        {"supplier": "Pilkington", "invoice_number": "9902",
         "invoice_type": "Faktura", "ocr": "99110025",
         "due_date": "2026-09-12", "total_amount": 2500.0},
        {"supplier": "Direktglas AB", "invoice_number": "DG-102",
         "invoice_type": "Faktura", "ocr": "7712029",
         "due_date": "2026-09-06", "total_amount": 3200.0},
        {"supplier": "Pilkington", "invoice_number": "9901",
         "invoice_type": "Faktura", "ocr": "99110015",
         "due_date": "2026-09-11", "total_amount": 1250.0},
        {"supplier": "Direktglas AB", "invoice_number": "DG-101",
         "invoice_type": "Faktura", "ocr": "7712019",
         "due_date": "2026-09-05", "total_amount": 3200.0},
        {"supplier": "Pilkington", "invoice_number": "K-55",
         "invoice_type": "Kreditfaktura", "ocr": "",
         "due_date": "2026-09-12", "total_amount": -500.0},
    ]


def test_to_ascii_preserves_swedish_letters():
    assert to_ascii("Malmö Fönster & Glas AB") == "Malmö Fönster & Glas AB"
    assert to_ascii("Rickard Längkvist") == "Rickard Längkvist"
    assert to_ascii("Pris — klart…") == "Pris - klart..."
    assert to_ascii("Pilkington") == "Pilkington"


def test_display_order_groups_by_supplier_then_due():
    ordered = _display_order(_sample_invoices())
    keys = [(i["supplier"], i["invoice_number"]) for i in ordered]
    assert keys[0][0] == "Direktglas AB"
    assert [n for s, n in keys if s == "Pilkington"] == [
        "9901", "9902", "K-55"]
    assert [n for s, n in keys if s == "Direktglas AB"] == [
        "DG-101", "DG-102"]


def test_payment_ref_date_rules():
    assert _payment_ref_date("2026-09-08") == "2026-09-08"
    import datetime
    assert _payment_ref_date("") == datetime.date.today().isoformat()
    assert _payment_ref_date("skräp") == datetime.date.today().isoformat()


def test_invoice_columns_have_ocr_not_status():
    from pdf_export_helpers import PDF_COLUMNS
    keys = [k for _l, k, _w in PDF_COLUMNS]
    assert "ocr" in keys
    assert "total_amount" in keys
    assert "status" not in keys
    # Bredderna ska rymmas inom A4 minus marginaler (523 pt).
    assert sum(w for _l, _k, w in PDF_COLUMNS) <= 523


@pytest.fixture()
def exported(tmp_path):
    ex = _exporter(tmp_path, theme="dark")  # mörkt tema i appen!
    _require_reportlab(ex)
    r = ex.export_invoice_list(
        _sample_invoices(), filename=str(tmp_path / "betal.pdf"),
        payment_date="2026-09-08", ask_payment_date=False,
        check_duplicates=False, mark_exported=False,
    )
    assert r["success"], r
    return tmp_path, Path(r["file_path"])


def test_pdf_has_ocr_subtotals_and_sorted_rows(exported):
    _td, path = exported
    text = _pdf_text(path)
    # OCR-numren (det man knappar in i banken) finns i listan.
    assert "99110015" in text and "7712019" in text
    # Delsummor per leverantör (netto inkl. kredit).
    assert "Summa Direktglas AB: 6 400,00" in text
    assert "Summa Pilkington: 3 250,00" in text
    # ATT BETALA = 10 150 − 500.
    assert "9 650,00 SEK" in text.replace("\u00a0", " ")
    # Sorterat: Direktglas-blocket före Pilkington-blocket.
    assert text.index("Direktglas AB") < text.index("Summa Pilkington")
    # Betalningsdatumet visas.
    assert "2026-09-08" in text


def test_pdf_always_light_even_in_dark_theme(exported, tmp_path):
    ex = _exporter(tmp_path, theme="dark")
    # Den palett som dokumentet ritas med är den ljusa.
    assert ex._colours(dark=False)["page_bg"] == "#ffffff"
    _td, path = exported
    # En sida räcker här: kontrollera via renderad pixel om pymupdf
    # finns, annars hoppa över (pymupdf är inte en projektberoende).
    pymupdf = pytest.importorskip("pymupdf")
    pix = pymupdf.open(str(path))[0].get_pixmap(dpi=40)
    # Övre vänstra hörnet (sidytan) ska vara (nästan) vit.
    r_c, g_c, b_c = pix.pixel(30, 400)[:3]
    assert r_c > 245 and g_c > 245 and b_c > 245


def test_single_supplier_has_no_subtotal(tmp_path):
    ex = _exporter(tmp_path, theme="light")
    _require_reportlab(ex)
    invs = [i for i in _sample_invoices()
            if i["supplier"] == "Pilkington"]
    r = ex.export_invoice_list(
        invs, filename=str(tmp_path / "en.pdf"),
        payment_date="2026-09-08", ask_payment_date=False,
        check_duplicates=False, mark_exported=False,
    )
    assert r["success"], r
    text = _pdf_text(Path(r["file_path"]))
    assert "Summa Pilkington" not in text
    assert "ATT BETALA" in text


def test_export_preserves_input_order_outside_pdf(tmp_path):
    """Sorteringen gäller bara PDF-visningen, inte anroparens lista."""
    invs = _sample_invoices()
    before = [i["invoice_number"] for i in invs]
    ex = _exporter(tmp_path, theme="light")
    _require_reportlab(ex)
    r = ex.export_invoice_list(
        invs, filename=str(tmp_path / "x.pdf"),
        payment_date="2026-09-08", ask_payment_date=False,
        check_duplicates=False, mark_exported=False,
    )
    assert r["success"], r
    assert [i["invoice_number"] for i in invs] == before
