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


def _cleanup_exported_file(path_str: str) -> None:
    p = Path(path_str)
    if p.is_file():
        p.unlink()
    try:
        if p.parent.is_dir() and not any(p.parent.iterdir()):
            p.parent.rmdir()
    except OSError:
        pass


def test_pdf_has_hierarchical_bookmarks_and_clickable_links(tmp_path):
    """Exporterad PDF får bokmärken (outline), internlänkar och mailto-länkar."""
    from PIL import Image
    from pypdf import PdfReader
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as rl_canvas

    pymupdf = pytest.importorskip("pymupdf")
    ex = _exporter(tmp_path, theme="dark", language="sv")
    _require_reportlab(ex)

    orig_pdf = tmp_path / "direktglas_orig.pdf"
    c = rl_canvas.Canvas(str(orig_pdf), pagesize=A4)
    c.drawString(72, 740, "Direktglas Original Sida 1")
    c.addOutlineEntry("External Junk Outline", "junk_p1", level=0)
    c.bookmarkPage("junk_p1")
    c.showPage()
    c.drawString(72, 740, "Direktglas Original Sida 2")
    c.showPage()
    c.save()

    orig_png = tmp_path / "akeri_orig.png"
    Image.new("RGB", (320, 200), (220, 230, 255)).save(orig_png)

    suppliers = [
        {
            "name": "Direktglas AB",
            "org_number": "556123-4567",
            "bg": "555-1234",
            "email": "ekonomi@direktglas.se",
        },
        {
            "name": "Åkeri & Co",
            "org_number": "556999-8888",
            "pg": "12 34 56-7",
            "email": "faktura@akeri.se",
        },
    ]
    # Osorterad inmatning — PDF och bilagor följer _display_order
    invoices = [
        {
            "supplier": "Åkeri & Co",
            "invoice_number": "AK-202",
            "ocr": "20200",
            "due_date": "2026-10-15",
            "total_amount": 4500.0,
            "attachment": str(orig_png),
        },
        {
            "supplier": "Direktglas AB",
            "invoice_number": "DG-101",
            "ocr": "10100",
            "due_date": "2026-10-10",
            "total_amount": 3200.0,
            "attachment": str(orig_pdf),
        },
        {
            "supplier": "Direktglas AB",
            "invoice_number": "DG-102",
            "invoice_type": "Kreditfaktura",
            "ocr": "",
            "due_date": "2026-10-20",
            "total_amount": -500.0,
            "attachment": "",
        },
    ]

    r = ex.export_invoice_list(
        invoices,
        filename=str(tmp_path / "bunt_bokmarken.pdf"),
        title="Betalunderlag Bokmärken",
        suppliers_list=suppliers,
        payment_date="2026-10-14",
        ask_payment_date=False,
        check_duplicates=False,
        mark_exported=False,
    )
    try:
        assert r["success"], r
        assert r["attachments_included"] == 2
        assert r["attachments_missing"] == 1
        assert r["bookmarks_count"] >= 9
        assert r["links_count"] >= 6

        reader = PdfReader(r["file_path"])
        assert len(reader.outline) >= 4

        doc = pymupdf.open(r["file_path"])
        try:
            assert len(doc) == 4
            toc = doc.get_toc()
            titles = [title for _lvl, title, _page in toc]
            assert "Översikt" in titles
            assert "Leverantörsuppgifter" in titles
            assert "Fakturor" in titles
            assert "Bifogade original" in titles
            assert "External Junk Outline" not in titles

            by_title = {title: page for _lvl, title, page in toc}
            assert any(
                "Direktglas AB" in t and "DG-101" in t and p == 2
                for _lvl, t, p in toc
            )
            assert any(
                "Åkeri & Co" in t and "AK-202" in t and p == 4
                for _lvl, t, p in toc
            )
            assert by_title["Bifogade original"] == 2

            links = doc[0].get_links()
            target_pages = {lnk["page"] for lnk in links if lnk.get("kind") == 1}
            uris = {lnk.get("uri", "") for lnk in links if lnk.get("kind") == 2}
            assert {0, 1, 3}.issubset(target_pages)
            assert "mailto:ekonomi@direktglas.se" in uris
            assert "mailto:faktura@akeri.se" in uris
        finally:
            doc.close()
    finally:
        _cleanup_exported_file(r["file_path"])


def test_pdf_bookmarks_and_links_english_without_originals(tmp_path):
    """Engelsk export utan original skapar engelska bokmärken och länkar."""
    pymupdf = pytest.importorskip("pymupdf")
    ex = _exporter(tmp_path, theme="light", language="en", include_originals=False)
    _require_reportlab(ex)

    r = ex.export_invoice_list(
        [
            {
                "supplier": "Nordic Supply",
                "invoice_number": "NS-1",
                "ocr": "9988",
                "due_date": "2026-10-20",
                "total_amount": 1500.0,
            },
        ],
        filename=str(tmp_path / "en_outline.pdf"),
        title="Payment Batch",
        suppliers_list=[
            {"name": "Nordic Supply", "email": "ap@nordicsupply.example"},
        ],
        payment_date="2026-10-15",
        ask_payment_date=False,
        check_duplicates=False,
        mark_exported=False,
    )
    try:
        assert r["success"], r
        assert r["bookmarks_count"] >= 5
        assert r["links_count"] >= 2

        doc = pymupdf.open(r["file_path"])
        try:
            titles = [title for _lvl, title, _page in doc.get_toc()]
            assert "Overview" in titles
            assert "Supplier details" in titles
            assert "Invoices" in titles
            assert "Attached originals" not in titles
            uris = {lnk.get("uri", "") for lnk in doc[0].get_links()}
            assert "mailto:ap@nordicsupply.example" in uris
        finally:
            doc.close()
    finally:
        _cleanup_exported_file(r["file_path"])


def test_pdf_missing_and_corrupt_attachments_have_no_broken_links(tmp_path):
    """Saknade eller trasiga bilagor skapar inga trasiga sidlänkar."""
    pymupdf = pytest.importorskip("pymupdf")
    ex = _exporter(tmp_path, theme="light", language="sv")
    _require_reportlab(ex)

    corrupt = tmp_path / "trasig.pdf"
    corrupt.write_bytes(b"not a real pdf file")

    r = ex.export_invoice_list(
        [
            {
                "supplier": "Test AB",
                "invoice_number": "T-1",
                "due_date": "2026-10-20",
                "total_amount": 100.0,
                "attachment": str(tmp_path / "finns_inte.pdf"),
            },
            {
                "supplier": "Test AB",
                "invoice_number": "T-2",
                "due_date": "2026-10-21",
                "total_amount": 200.0,
                "attachment": str(corrupt),
            },
        ],
        filename=str(tmp_path / "broken_att.pdf"),
        payment_date="2026-10-15",
        ask_payment_date=False,
        check_duplicates=False,
        mark_exported=False,
    )
    try:
        assert r["success"], r
        assert r["attachments_included"] == 0
        assert r["attachments_missing"] == 2
        doc = pymupdf.open(r["file_path"])
        try:
            titles = [title for _lvl, title, _page in doc.get_toc()]
            assert "Bifogade original" not in titles
            for lnk in doc[0].get_links():
                if lnk.get("kind") == 1:
                    assert 0 <= lnk["page"] < len(doc)
        finally:
            doc.close()
    finally:
        _cleanup_exported_file(r["file_path"])
