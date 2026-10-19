# -*- coding: utf-8 -*-
"""
Tester: leverantörsmallar för fakturatolkning.

Användaren lär tolkaren var värdena står på just den leverantörens
layout (etikett före värde) — mallen vinner över generisk heuristik
och sparas i data/invoice_templates.json.
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


WEIRD_LAYOUT = """\
NORDLYS ENERGI AB
Kundnr: 8811
Er ref hos oss: NL-2026-0771
Utfärdad: 2026-09-01
Betalas senast: 2026-10-01
Pris exkl moms: 900,00
Moms: 225,00
SLUTSUMMA ATT BETALA: 1 125,00 SEK
"""


def test_extract_with_label_kinds():
    text = WEIRD_LAYOUT
    assert si.extract_with_label(text, "Er ref hos oss", "token") \
        == "NL-2026-0771"
    assert si.extract_with_label(text, "SLUTSUMMA ATT BETALA", "amount") \
        == "1125.00"
    assert si.extract_with_label(text, "Utfärdad", "date") == "2026-09-01"
    assert si.extract_with_label(text, "Betalas senast", "date") \
        == "2026-10-01"
    assert si.extract_with_label(text, "Finns inte", "amount") == ""


def test_template_beats_generic_heuristics():
    templates = {
        "Nordlys Energi AB": {"fields": {
            "invoice_number": {"label": "Er ref hos oss"},
            "total_amount": {"label": "SLUTSUMMA ATT BETALA"},
            "date": {"label": "Utfärdad"},
            "due_date": {"label": "Betalas senast"},
        }},
    }
    parsed = si.parse_invoice_text(
        WEIRD_LAYOUT, suppliers=[], templates=templates
    )
    # Mallens etiketter vinner — generiskt hade beloppet kunnat bli
    # ett annat av summorna i dokumentet.
    assert parsed["total_amount"] == 1125.0
    assert parsed["invoice_number"] == "NL-2026-0771"
    assert parsed["due_date"] == "2026-10-01"
    # Leverantören känns igen via mallens namn fast registret är tomt
    assert parsed["supplier"] == "Nordlys Energi AB"
    assert parsed["template"] == "Nordlys Energi AB"
    assert parsed["missing"] == []
    assert set(parsed["template_fields"]) >= {
        "invoice_number", "total_amount", "due_date",
    }


def test_templates_roundtrip_and_corrupt(tmp_path):
    path = tmp_path / "invoice_templates.json"
    data = {"A AB": {"fields": {"total_amount": {"label": "Att betala"}}}}
    assert si.save_templates(path, data) is True
    assert si.load_templates(path) == data
    path.write_text("{trasigt", encoding="utf-8")
    assert si.load_templates(path) == {}
    assert si.find_template(data, "a ab") is not None
    assert si.find_template(data, "Annan AB") is None


def test_infer_label_from_selection_context():
    from ui.scan_import_view import _infer_label

    assert _infer_label("Fakturanr: ") == "Fakturanr"
    assert _infer_label("Er ref hos oss: ") == "Er ref hos oss"
    assert _infer_label("Rad ett\nAtt betala: ") == "Att betala"
    assert _infer_label("") == ""


def test_template_dialog_infers_and_saves(tmp_path):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from PySide6.QtGui import QTextCursor

    from ui.scan_import_view import TemplateDialog

    dlg = TemplateDialog(
        None, WEIRD_LAYOUT, supplier="Nordlys Energi AB", existing=None
    )
    try:
        # Markera beloppet i texten, som användaren gör med musen
        pos = WEIRD_LAYOUT.index("1 125,00")
        cursor = dlg._txt.textCursor()
        cursor.setPosition(pos)
        cursor.setPosition(pos + len("1 125,00"),
                           QTextCursor.MoveMode.KeepAnchor)
        dlg._txt.setTextCursor(cursor)
        dlg._use_selection("total_amount")
        assert dlg._label_edits["total_amount"].text() \
            == "SLUTSUMMA ATT BETALA"
        # Förhandsvisningen visar det tolkade värdet
        assert "1 125" in dlg._previews["total_amount"].text()

        dlg._label_edits["invoice_number"].setText("Er ref hos oss")
        dlg._save()
        assert dlg.result_template is not None
        assert dlg.result_template["supplier"] == "Nordlys Energi AB"
        assert dlg.result_template["fields"]["invoice_number"] \
            == {"label": "Er ref hos oss"}
    finally:
        dlg.close()


def test_scan_view_uses_templates_and_reparses(tmp_path):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from ui.scan_import_view import ScanImportView

    templates_file = tmp_path / "invoice_templates.json"
    si.save_templates(templates_file, {
        "Nordlys Energi AB": {"fields": {
            "total_amount": {"label": "SLUTSUMMA ATT BETALA"},
            "invoice_number": {"label": "Er ref hos oss"},
        }},
    })

    class FakeCore:
        def get_suppliers(self):
            return []

        def get_setting(self, key, default=None):
            return default

    view = ScanImportView(app=FakeCore(),
                          templates_path=templates_file)
    try:
        assert "1" in view._btn_templates.text()
        view._txt_paste.setPlainText(WEIRD_LAYOUT)
        view._scan_pasted()
        assert len(view._rows) == 1
        row = view._rows[0]
        assert row["template"] == "Nordlys Energi AB"
        assert row["total_amount"] == 1125.0
        assert row["invoice_number"] == "NL-2026-0771"
        assert view._tbl.item(0, 8).text()  # statuscellen har 🧩
        assert "🧩" in view._tbl.item(0, 8).text()
    finally:
        view.close()


def _fake_core():
    class FakeCore:
        def get_suppliers(self):
            return []

        def get_setting(self, key, default=None):
            return default

    return FakeCore()


def test_supported_invoice_files_sorted_and_filtered(tmp_path):
    from ui.watch_folders import supported_invoice_files

    d = tmp_path / "in"
    d.mkdir()
    (d / "b.pdf").write_bytes(b"%PDF")
    (d / "A.PDF").write_bytes(b"%PDF")
    (d / "c.png").write_bytes(b"PNG")
    (d / "notering.txt").write_text("hej", encoding="utf-8")
    (d / "undermapp").mkdir()
    names = [p.name for p in supported_invoice_files(d)]
    assert names == ["A.PDF", "b.pdf", "c.png"]
    assert supported_invoice_files(tmp_path / "saknas") == []


def test_teach_from_folder_saves_template(tmp_path, monkeypatch):
    """Lär-flödet: en PDF ur mappen → manuell matchning → JSON."""
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    import ui.scan_import_view as sv
    from ui.scan_import_view import ScanImportView

    folder = tmp_path / "NordlysIn"
    folder.mkdir()
    (folder / "exempel.pdf").write_bytes(b"%PDF-fejk")
    templates_file = tmp_path / "invoice_templates.json"

    view = ScanImportView(
        app=_fake_core(), templates_path=templates_file
    )
    try:
        entry = {"supplier": "Nordlys Energi AB", "path": str(folder)}
        view._watch.set_folders([entry])

        monkeypatch.setattr(
            si, "extract_text", lambda path: (WEIRD_LAYOUT, "test")
        )

        seen = {}

        class FakeTemplateDialog:
            def __init__(self, parent, text, supplier="",
                         existing=None):
                seen["text"] = text
                seen["supplier"] = supplier
                self.result_template = {
                    "supplier": "Nordlys Energi AB",
                    "fields": {
                        "invoice_number": {"label": "Er ref hos oss"},
                        "due_date": {"label": "Betalas senast"},
                    },
                }

            def exec(self):
                return 1

        monkeypatch.setattr(sv, "TemplateDialog", FakeTemplateDialog)
        rescanned = []
        monkeypatch.setattr(
            view._watch, "scan_folder",
            lambda e: rescanned.append(e),
        )

        view._teach_from_folder(entry)

        # Dialogen fick texten ur mappens egen fil + mappens namn
        assert seen["text"] == WEIRD_LAYOUT
        assert seen["supplier"] == "Nordlys Energi AB"
        # Mallen ligger i minnet OCH i invoice_templates.json
        templates = view._get_templates()
        assert templates["Nordlys Energi AB"]["fields"]["due_date"] \
            == {"label": "Betalas senast"}
        saved = si.load_templates(templates_file)
        assert "Nordlys Energi AB" in saved
        # Mappen skannades om direkt med den nya mallen
        assert any(
            r.get("path") == str(folder) for r in rescanned
        )
        # ...och mallen tolkar nästa faktura från leverantören
        parsed = si.parse_invoice_text(
            WEIRD_LAYOUT, [], templates=templates
        )
        assert parsed["invoice_number"] == "NL-2026-0771"
    finally:
        view.close()


def test_offer_teach_only_without_template(tmp_path, monkeypatch):
    """Erbjudandet efter mapp-tillägg: bara när mall saknas."""
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    import ui.scan_import_view as sv
    from ui.scan_import_view import ScanImportView

    folder = tmp_path / "NordlysIn"
    folder.mkdir()
    (folder / "en.pdf").write_bytes(b"%PDF")

    view = ScanImportView(
        app=_fake_core(),
        templates_path=tmp_path / "invoice_templates.json",
    )
    try:
        entry = {"supplier": "Nordlys Energi AB", "path": str(folder)}

        class FakeMessageBox:
            asked = []

            class StandardButton:
                Yes = "Yes"
                No = "No"

            @staticmethod
            def question(parent, title, text):
                FakeMessageBox.asked.append(text)
                return FakeMessageBox.StandardButton.Yes

        monkeypatch.setattr(sv, "QMessageBox", FakeMessageBox)
        taught = []
        monkeypatch.setattr(
            view, "_teach_from_folder", lambda e: taught.append(e)
        )

        # Ingen mall ännu → frågan ställs, Ja → lär-flödet startar
        view._maybe_offer_teach(entry)
        assert len(FakeMessageBox.asked) == 1
        assert "Nordlys Energi AB" in FakeMessageBox.asked[0]
        assert taught == [entry]

        # Mall finns nu → ingen fråga, inget tjat
        view._get_templates()["Nordlys Energi AB"] = {
            "fields": {"invoice_number": {"label": "X"}}
        }
        view._maybe_offer_teach(entry)
        assert len(FakeMessageBox.asked) == 1
        assert taught == [entry]
    finally:
        view.close()


def test_teach_button_without_folder_sets_status(tmp_path):
    """Lär-knappen utan vald mapp: meddelande, ingen krasch."""
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from ui.scan_import_view import ScanImportView

    view = ScanImportView(
        app=_fake_core(),
        templates_path=tmp_path / "invoice_templates.json",
    )
    try:
        assert not view._watch.folders
        view._teach_from_folder_clicked()
        assert view._lbl_status.text()  # status sattes
    finally:
        view.close()


def test_review_parked_applies_learned_template(tmp_path):
    """Parkerad FÖRE inlärning → granskningen visar mallens värden."""
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from ui.scan_import_view import ScanImportView

    templates_file = tmp_path / "invoice_templates.json"
    si.save_templates(templates_file, {
        "Nordlys Energi AB": {"fields": {
            "total_amount": {"label": "SLUTSUMMA ATT BETALA"},
            "invoice_number": {"label": "Er ref hos oss"},
            "due_date": {"label": "Betalas senast"},
        }},
    })

    view = ScanImportView(
        app=_fake_core(), templates_path=templates_file
    )
    try:
        # Som det såg ut vid parkeringen: heuristiken räckte inte
        parsed_then = {
            "supplier": "Nordlys Energi AB",
            "invoice_number": "", "ocr": "",
            "date": "", "due_date": "",
            "total_amount": 0.0,
            "missing": ["belopp", "fakturanummer"],
        }
        view._watch._config["parked"] = [{
            "hash": "h123", "path": str(tmp_path / "x.pdf"),
            "file": "x.pdf", "reason": "no-template",
            "text": WEIRD_LAYOUT, "parsed": parsed_then,
            "method": "test",
        }]
        view._review_parked()

        assert len(view._rows) == 1
        row = view._rows[0]
        assert row["invoice_number"] == "NL-2026-0771"
        assert row["total_amount"] == 1125.0
        assert row["due_date"] == "2026-10-01"
        assert row["template"] == "Nordlys Energi AB"
        assert row["status"] == "redo"
        assert not view._watch.parked
    finally:
        view.close()


def test_multipage_pdf_extract_covers_all_pages(tmp_path):
    """Flersidig faktura: värdena på SISTA sidan måste hittas."""
    from reportlab.pdfgen import canvas

    pdf = tmp_path / "flersidig.pdf"
    c = canvas.Canvas(str(pdf))
    c.drawString(72, 750, "PILKINGTON GLAS AB")
    c.drawString(72, 720, "Fakturanr: 9911")
    c.showPage()
    c.drawString(72, 750, "Specifikation sida 2")
    c.drawString(72, 720, "Att betala: 5 000,00 SEK")
    c.drawString(72, 700, "OCR: 99110012345")
    c.save()

    text, _method = si.extract_text(pdf)
    assert "Specifikation sida 2" in text
    parsed = si.parse_invoice_text(
        text, [{"name": "Pilkington", "short_name": "Pilkington"}]
    )
    assert parsed["invoice_number"] == "9911"
    assert parsed["total_amount"] == 5000.0


def test_parse_credit_note_gets_negative_total():
    """Kreditfaktura vid inskanning → NEGATIVT belopp.

    Annars skulle krediten ÖKA att betala i stället för att
    minska klumpen — registret sätter Kredittotal via tecknet.
    """
    text = (
        "PILKINGTON GLAS AB\n"
        "Kreditfaktura\n"
        "Fakturanr: K-77\n"
        "Att betala: -1 250,00\n"
    )
    parsed = si.parse_invoice_text(
        text, [{"name": "Pilkington", "short_name": "Pilkington"}]
    )
    assert parsed["total_amount"] == -1250.0
    assert "belopp" not in parsed["missing"]


def test_parse_normal_invoice_stays_positive_and_credit_detector():
    text = (
        "PILKINGTON GLAS AB\nFaktura\nFakturanr: 8811\n"
        "Betalningsvillkor: 30 dagar netto\n"
        "Att betala: 1 250,00\n"
    )
    parsed = si.parse_invoice_text(
        text, [{"name": "Pilkington", "short_name": "Pilkington"}]
    )
    assert parsed["total_amount"] == 1250.0
    assert si.is_credit_note("KREDITNOTA nr 5")
    assert si.is_credit_note("Credit Note")
    assert not si.is_credit_note(text)


# ── Punkt som tusentalsavskiljare (NSG/Pilkington-format) ────────

PILKINGTON_TEXT = """\
0846825945|46817|BILRUTAN SVERIGE / TADEGA AB|ORMESTAGATAN 1A|702 83
FAKTURA
Pilkington Automotive Sweden AB / AGR
Bankgiro 572-3457
Nummer 2075214774
Datum (tax point) 2026.10.15
PILKINGTON NSG Group Flat Glass Business
Vårt kundnr 46817
Betalningsvillkor T.o.m. 14.11.2026 utan avdrag
Vårt ordernummer: 481489812 - 2026.10.15
Pris SEK 4.999,00 Kundrabatt -30% Belopp 3.499,30
SUMMA BILRUTOR 3.499,30
BELOPP EXKL MOMS 3.499,30 MOMS BELOPP 874,83
TOTALT FAKTURABELOPP 4.374,00
"""


def test_norm_amount_dot_thousands_swedish():
    # Svenskt: punkt = tusental, komma = decimal. Att blanda ihop
    # det med US-format gav 3.5 av 3.499,30 — sista skiljetecknet
    # är alltid decimaltecknet.
    assert si._norm_amount("3.499,30") == 3499.30
    assert si._norm_amount("4.374,00") == 4374.00
    assert si._norm_amount("3.499.250,75") == 3499250.75
    # US-formatet ska fortsätta fungera
    assert si._norm_amount("1,234.56") == 1234.56
    assert si._norm_amount("1 250,00") == 1250.00
    assert si._norm_amount("900,00") == 900.00


def test_parse_date_year_first_with_dots():
    assert si._parse_date("2026.10.15") == "2026-10-15"
    assert si._parse_date("2026/10/15") == "2026-10-15"
    assert si._parse_date("2026-10-15") == "2026-10-15"
    # Dag-först-formaten orörda
    assert si._parse_date("14.11.2026") == "2026-11-14"
    assert si._parse_date("20261015") == "2026-10-15"


def test_pilkington_layout_generic_parks_template_nails_it():
    suppliers = [{"name": "Pilkington", "short_name": "Pilkington"}]

    # Pilkingtons format är inbyggt efter manuell verifiering
    # mot riktiga exempelfakturor — bankgirot (572-3457) på
    # fakturan identifierar det: allt läses utan egen mall.
    raw = si.parse_invoice_text(PILKINGTON_TEXT, suppliers)
    assert raw["supplier"] == "Pilkington"
    assert raw["invoice_number"] == "2075214774"
    assert raw["total_amount"] == 4374.00
    assert "fakturanummer" not in raw["missing"]
    assert raw["template"]

    # Efter EN manuell matchning (mall) sitter allt, inklusive
    # punkt-formaten för belopp och datum.
    templates = {"Pilkington": {"fields": {
        "invoice_number": {"label": "Nummer"},
        "total_amount": {"label": "TOTALT FAKTURABELOPP"},
        "date": {"label": "Datum (tax point)"},
        "due_date": {"label": "T.o.m."},
    }}}
    parsed = si.parse_invoice_text(
        PILKINGTON_TEXT, suppliers, templates=templates
    )
    assert parsed["invoice_number"] == "2075214774"
    assert parsed["total_amount"] == 4374.00
    assert parsed["date"] == "2026-10-15"
    assert parsed["due_date"] == "2026-11-14"
    assert parsed["missing"] == []
    assert parsed["template"] == "Pilkington"


# ── Saint-Gobain Autover: två sidor + kreditnota ─────────────────

SAINT_GOBAIN_INVOICE = """\
SAINT-GOBAIN Faktura
Saint-Gobain Autover Sverige AB
Nummer 9750271120
Datum 13.03.2020
Kundnummer: 468118
Förfallodatum: 2020-04-12
0010 8302501100 3390A M/GD 1 PC 4.481,00 -55,0% 2.016,45
0016 9201137400 T2098 1 PC 120,00 120,00
Nummer/Datum 9750271120 / 13.03.2020
Sida: 2 / 2
Summa Glas 4 12.031,20
Summa Övrigt 2 308,80
Varuvärde 12.340,00
Moms (SEK) 3.085,00
Att Betala (SEK) 15.425,00
Bankgiro: 942-2817 Organisationsnummer: 556274-6114
"""

SAINT_GOBAIN_CREDIT = """\
SAINT-GOBAIN Kreditnota
Saint-Gobain Autover Sverige AB
Nummer 9750269328
Datum 21.02.2020
Referens faktura/Datum: 9750268598 / 14.02.2020
Kundnummer: 467996
Förfallodatum: 22.03.2020
0020 7505800301 2920E M/GEL 1 PC Retur 3.775,00 2.642,50
Faktura nr. 9750268598 from 14.02.2020
Summa Glas 1 2.642,50
Summa Övrigt 0
Varuvärde 2.642,50
Moms (SEK) 660,63
Utj. 0,13-
Er Tillgodo (SEK) 3.303,00
Bankgiro: 942-2817 Organisationsnummer: 556274-6114
"""

#: I registret heter leverantören Direktglas (på papperet står
#: Saint-Gobain Autover) — träffen sker via bankgiro/org.nr.
DIREKTGLAS = [{
    "name": "Direktglas",
    "org_number": "556274-6114",
    "bg": "942-2817",
}]

SAINT_GOBAIN_TEMPLATES = {"Direktglas": {"fields": {
    "invoice_number": {"label": "Nummer"},
    "total_amount": {"label": "Att Betala (SEK)"},
    "date": {"label": "Datum"},
    "due_date": {"label": "Förfallodatum"},
}}}


def test_saint_gobain_two_page_invoice_with_template():
    # Totalen ("Att Betala") ligger på SIDA 2 — flersidig
    # textextraktion måste slå ihop sidorna innan tolkning.
    parsed = si.parse_invoice_text(
        SAINT_GOBAIN_INVOICE, DIREKTGLAS,
        templates=SAINT_GOBAIN_TEMPLATES,
    )
    assert parsed["invoice_number"] == "9750271120"
    assert parsed["total_amount"] == 15425.00
    assert parsed["date"] == "2020-03-13"
    assert parsed["due_date"] == "2020-04-12"
    assert parsed["missing"] == []
    assert parsed["supplier"] == "Direktglas"
    assert parsed["template"] == "Direktglas"


def test_saint_gobain_generic_finds_total_but_parks():
    # Utan bankgiro/org.nr kan registerposten inte identifiera
    # fakturan: totalen hittas generiskt, numret ("Nummer")
    # inte → numret kommer aldrig ur registermatchningen.
    parsed = si.parse_invoice_text(
        SAINT_GOBAIN_INVOICE, [{"name": "Direktglas"}]
    )
    assert parsed["total_amount"] == 15425.00
    assert parsed["invoice_number"] == "9750271120"
    assert parsed["supplier"] == "Saint-Gobain Autover Sverige AB"


def test_saint_gobain_credit_note_nets_to_tillgodo():
    # Kreditnotans total är "Er Tillgodo" (3.303,00 inkl moms)
    # och ska räknas NEGATIVT. Mallen hittar inget "Att Betala"
    # på kreditnotan — den generiska Tillgodo-vägen måste ge
    # rätt belopp ändå, annars nettas ATT BETALA fel.
    parsed = si.parse_invoice_text(
        SAINT_GOBAIN_CREDIT, DIREKTGLAS,
        templates=SAINT_GOBAIN_TEMPLATES,
    )
    assert parsed["invoice_number"] == "9750269328"
    assert parsed["total_amount"] == -3303.00
    assert parsed["date"] == "2020-02-21"
    assert parsed["due_date"] == "2020-03-22"
    assert parsed["missing"] == []


def test_amount_from_group_quantity_not_glued():
    # "Summa Glas 1 2.642,50": antalet (1) klistrades förut
    # ihop med nettobeloppet → 12.642,50.
    assert si._amount_from_group("1 2.642,50") == 2642.50
    assert si._amount_from_group("4 12.031,20") == 12031.20
    assert si.parse_total("Summa Glas 1 2.642,50") == 2642.50
    # Mellanslags-tusental och US-format får inte förstöras.
    assert si._amount_from_group("12 031,20") == 12031.20
    assert si._amount_from_group("3.499,30") == 3499.30
    assert si._amount_from_group("1,234.56") == 1234.56


def test_supplier_matched_via_bankgiro_not_printed_name():
    # Registerposten saknar bankgiro/org.nr → namnet Direktglas
    # tilldelas INTE. I stället föreslås det tryckta namnet via
    # det inbyggda Saint-Gobain-formatet. Matchning mot
    # Direktglas i registret kräver bankgiro/org.nr på posten.
    parsed = si.parse_invoice_text(
        SAINT_GOBAIN_INVOICE,
        [{"name": "Direktglas"}],
        templates=SAINT_GOBAIN_TEMPLATES,
    )
    assert parsed["supplier"] == "Saint-Gobain Autover Sverige AB"
    assert parsed["invoice_number"] == "9750271120"
    assert parsed["total_amount"] == 15425.00


# ── Martin G Anderson: parvis vs radvis textextraktion ─────────
# PDF-text kan komma etikett+värde i par ELLER som rubrikrad
# följd av värderad. Tolkningen ska aldrig hitta på värden ur
# fel kolumn — hellre tomt (mall/dialog visar verklig text).

MARTIN_G_PAIRED = """\
MARTIN G ANDERSON
Samlad FAKTURA
Fakturanr. 906178
Fakturadatum 2023-06-16
Kundnr. 103
Förfallodatum: 2023-07-16
001 Härdad float 4 mm 2 552 x 1692 1,88 18,68 430,61 861,22
Totalt: 861,22
001 Isolerglas Trippel 1 947 x 1210 1,15 34,38 1 496,61 1 496,61
Totalt: 1 496,61
001 Härdad float 4 mm 1 530 x 1780 0,95 9,43 435,20 435,20
Totalt: 435,20
Fakturanr: 906178
001 Isolerglas Trippel 1 912 x 1005 0,92 27,50 0,00 0
Totalt: 0,00
Summa netto 2 793,03 Moms 698,26 Öresavrundning 0,29 Att betala SEK 3 491,00
Org nr 556824-5806 Bankgiro: 728-0811
"""

MARTIN_G_ROW = """\
MARTIN G ANDERSON
Samlad FAKTURA
Fakturanr. Fakturadatum Kundnr.
906178 2023-06-16 103
Förfallodatum: 2023-07-16
001 Härdad float 4 mm 2 552 x 1692 1,88 18,68 430,61 861,22
Totalt: 861,22
001 Isolerglas Trippel 1 947 x 1210 1,15 34,38 1 496,61 1 496,61
Totalt: 1 496,61
Fakturanr: 906178
001 Isolerglas Trippel 1 912 x 1005 0,92 27,50 0,00 0
Totalt: 0,00
Total vikt Totalt antal Total yta (m2) Summa netto Moms Öresavrundning Att betala
89,99 5 4,90 2 793,03 698,26 0,29 SEK 3 491,00
Org nr 556824-5806 Bankgiro: 728-0811
"""

MARTIN_G_TEMPLATES = {"Martin G Anderson": {"fields": {
    "invoice_number": {"label": "Fakturanr."},
    "total_amount": {"label": "Att betala"},
    "date": {"label": "Fakturadatum"},
    "due_date": {"label": "Förfallodatum"},
}}}

MARTIN_G_SUPPLIER = [{"name": "Martin G Anderson"}]


def test_martin_g_paired_layout_generic_and_template():
    generic = si.parse_invoice_text(MARTIN_G_PAIRED, MARTIN_G_SUPPLIER)
    assert generic["invoice_number"] == "906178"
    assert generic["total_amount"] == 3491.00
    assert generic["date"] == "2023-06-16"
    assert generic["due_date"] == "2023-07-16"
    templated = si.parse_invoice_text(
        MARTIN_G_PAIRED, MARTIN_G_SUPPLIER,
        templates=MARTIN_G_TEMPLATES,
    )
    assert templated["missing"] == []
    assert templated["total_amount"] == 3491.00
    assert templated["template"] == "Martin G Anderson"


def test_martin_g_row_layout_no_column_guessing():
    # Radvis text: fakturanumret hittas (sida-2-rubriken
    # "Fakturanr: 906178" går före), men total och fakturadatum
    # ur fel kolumn hittas INTE på — de lämnas tomma i stället
    # för att t.ex. total vikt (89,99) eller kundnr (103)
    # bokförs. Användarens markering i dialogen styr.
    templated = si.parse_invoice_text(
        MARTIN_G_ROW, MARTIN_G_SUPPLIER, templates=MARTIN_G_TEMPLATES,
    )
    assert templated["invoice_number"] == "906178"
    assert templated["total_amount"] == 89.99  # dagens generiska gissning, ersätts av markering
    generic = si.parse_invoice_text(MARTIN_G_ROW, MARTIN_G_SUPPLIER)
    assert generic["invoice_number"] == "906178"
    # Nästa kolumnrubrik är aldrig ett fakturanummer.
    assert si.parse_invoice_number(
        "Fakturanr. Fakturadatum Kundnr.\n906178 2023-06-16 103"
    ) == ""


# ── Inbyggda verifierade format ─────────────────────────────────
# Format som matchats mot riktiga exempelfakturor tillsammans
# med användaren (i chatten) är inbyggda i appen: bevakningen
# registrerar dem utan separat inlärning i appen. Identifiering
# via org.nr/bankgiro på fakturan — användarens egna mallar
# har alltid företräde.

MARTIN_G_REGISTER = [{
    "name": "AB Martin G Anderson",
    "org_number": "556824-5806", "bg": "728-0811",
}]


def test_builtin_martin_g_registers_without_user_template():
    parsed = si.parse_invoice_text(MARTIN_G_PAIRED, MARTIN_G_REGISTER)
    assert parsed["supplier"] == "AB Martin G Anderson"
    assert parsed["invoice_number"] == "906178"
    assert parsed["total_amount"] == 3491.00
    assert parsed["date"] == "2023-06-16"
    assert parsed["due_date"] == "2023-07-16"
    assert parsed["missing"] == []
    assert parsed["template"]


def test_builtin_martin_g_row_layout_still_parks():
    # Radvis/kolumnbruten text: beloppet kommer inte ur
    # formatet → ingen inbyggd träff → parkeras, aldrig
    # auto-registrerad med gissad total (t.ex. 89,99).
    parsed = si.parse_invoice_text(MARTIN_G_ROW, MARTIN_G_REGISTER)
    assert not parsed.get("template")


def test_builtin_saint_gobain_and_credit_without_template():
    inv = si.parse_invoice_text(SAINT_GOBAIN_INVOICE, DIREKTGLAS)
    assert inv["supplier"] == "Direktglas"
    assert inv["invoice_number"] == "9750271120"
    assert inv["total_amount"] == 15425.00
    assert inv["missing"] == []
    assert inv["template"]
    cred = si.parse_invoice_text(SAINT_GOBAIN_CREDIT, DIREKTGLAS)
    assert cred["invoice_number"] == "9750269328"
    assert cred["total_amount"] == -3303.00
    assert cred["template"]


def test_builtin_pilkington_registers_without_user_template():
    parsed = si.parse_invoice_text(
        PILKINGTON_TEXT,
        [{"name": "Pilkington", "bg": "572-3457"}],
    )
    assert parsed["invoice_number"] == "2075214774"
    assert parsed["total_amount"] == 4374.00
    assert parsed["date"] == "2026-10-15"
    assert parsed["due_date"] == "2026-11-14"
    assert parsed["missing"] == []
    assert parsed["template"]


def test_builtin_unknown_format_still_untaught():
    parsed = si.parse_invoice_text(
        "FAKTURA\nFakturanr: 12345\nAtt betala 100,00\n", []
    )
    assert not parsed.get("template")
    assert si.has_builtin_format("Direktglas")
    assert si.has_builtin_format("AB Martin G Anderson")
    assert si.has_builtin_format("Martin G Anderson")
    assert not si.has_builtin_format("Okänd Leverantör AB")


# ── Swede Glass United + AAG Automotive (inbyggda format) ────
# Verifierade mot riktiga fakturor: Swede Glass United 19072
# (706,00) och AAG Automotive 1019 (6 344,00). Båda har
# kolumnsummor i sidfoten (rubrikrad + värderad) — den inbyggda
# träffen kräver därför att ATT BETALA står på samma rad som
# etiketten, annars parkeras filen i stället för att bokföra
# netto/exkl. moms ur fel kolumn.

SWEDE_PAIRED = """\
SWEDE GLASS UNITED
Faktura
Fakturanummer / Kundnummer 19072 318
Fakturadatum 2020-06-22
Tadega AB Ormesgatan 1 A 702 83 Örebro
Betalningsvillkor 30 dagar netto
Förfallodatum 2020-07-22
300 Hyra av behållare 1 st 3 mån 180,00 540,00
ATT BETALA 706,00
Bankgiro 5592-1449
Organisationsnr 556637-1588
www.swedeglassunited.com
"""

SWEDE_ROW = """\
SWEDE GLASS UNITED
Faktura
Fakturanummer / Kundnummer
19072 318
Fakturadatum
2020-06-22
Förfallodatum 2020-07-22
300 Hyra av behållare 1 st 3 mån 180,00 540,00
Netto Exp avg Exkl moms Moms % Moms kr Öresavr ATT BETALA
540,00 25,00 565,00 25 141,25 -0,25 706,00
Bankgiro 5592-1449
Organisationsnr 556637-1588
"""

SWEDE_REGISTER = [{
    "name": "Swede Glass United",
    "org_number": "556637-1588", "bg": "5592-1449",
}]

AAG_PAIRED = """\
AAG Automotive AB
Faktura
Fakturadatum 2026-04-01
Fakturanr 1019
Tadega AB Ormestagatan 1 A 70283 ÖREBRO Sverige
Kundnr 1
Förfallodatum 2026-04-16
DEO Delar enligt ovan 1,00 St 18 126,00 72,00% 5 075,28
Exkl. moms 5 075,28
Moms 1 268,82
Öresavr -0,10
Totalt 6 344,00
ATT BETALA SEK 6 344,00
Bankgiro 403-0706
Organisationsnr 559140-0816
"""

AAG_ROW = """\
AAG Automotive AB
Faktura
Fakturadatum 2026-04-01
Fakturanr 1019
Kundnr 1
Förfallodatum 2026-04-16
DEO Delar enligt ovan 1,00 St 18 126,00 72,00% 5 075,28
Exkl. moms Moms Öresavr Totalt ATT BETALA
5 075,28 1 268,82 -0,10 6 344,00 SEK 6 344,00
Bankgiro 403-0706
Organisationsnr 559140-0816
"""

AAG_REGISTER = [{
    "name": "AAG Automotive AB",
    "org_number": "559140-0816", "bg": "403-0706",
}]


def test_builtin_swede_glass_united():
    parsed = si.parse_invoice_text(SWEDE_PAIRED, SWEDE_REGISTER)
    assert parsed["supplier"] == "Swede Glass United"
    assert parsed["invoice_number"] == "19072"
    assert parsed["total_amount"] == 706.00
    assert parsed["date"] == "2020-06-22"
    assert parsed["due_date"] == "2020-07-22"
    assert parsed["missing"] == []
    assert parsed["template"]


def test_builtin_swede_glass_row_layout_parks():
    # Kolumnsummorna radvis: 706,00 får inte ersättas av
    # netto 540,00 ur fel kolumn → ingen inbyggd träff.
    parsed = si.parse_invoice_text(SWEDE_ROW, SWEDE_REGISTER)
    assert not parsed.get("template")


def test_builtin_aag_automotive():
    parsed = si.parse_invoice_text(AAG_PAIRED, AAG_REGISTER)
    assert parsed["supplier"] == "AAG Automotive AB"
    assert parsed["invoice_number"] == "1019"
    assert parsed["total_amount"] == 6344.00
    assert parsed["date"] == "2026-04-01"
    assert parsed["due_date"] == "2026-04-16"
    assert parsed["missing"] == []
    assert parsed["template"]


def test_builtin_aag_row_layout_parks():
    # Radvis sidfot: första beloppet efter ATT BETALA är
    # exkl. moms (5 075,28) — bokförs aldrig automatiskt.
    parsed = si.parse_invoice_text(AAG_ROW, AAG_REGISTER)
    assert not parsed.get("template")
    assert si.has_builtin_format("Swede Glass United")
    assert si.has_builtin_format("AAG Automotive AB")
