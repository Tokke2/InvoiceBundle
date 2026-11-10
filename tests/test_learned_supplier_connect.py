# -*- coding: utf-8 -*-
"""
Tester: appen lär sig koppla fakturor till rätt leverantör.

Användarens krav (2026-10-28): väljer man leverantör via
logotyp/manuell matchning tillräckligt många gånger (5–10
fakturor) ska appen därefter koppla nya fakturor till rätt
leverantör SJÄLV. Mekanismen: varje bekräftad matchning lär
appen leverantörens starka kännetecken (org.nr med giltig
kontrollsiffra, bankgiro). Efter 5 bekräftelser — med samma
kännetecken i minst 2 av dem — kopplas nya fakturor med det
kännetecknet automatiskt. Kännetecken hos flera leverantörer,
eller flera kvalificerade leverantörer, frågas det alltid om.
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


def _org(base9: str) -> str:
    """Giltigt svenskt org.nr (Luhn) ur 9 siffror."""
    tot = 0
    for i, ch in enumerate(base9):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        tot += d
    return base9 + str((10 - tot % 10) % 10)


ORG_A = _org("556677889")
ORG_B = _org("559988776")


def _text(org: str, bg: str = "999-1234", extra: str = "") -> str:
    return (
        f"Faktura\nOrg.nr {org[:6]}-{org[6:]}\n"
        f"Bankgiro {bg}\nFaktnr 12\nAtt betala 500,00\n" + extra
    )


def _learn(learning: dict, supplier: str, text: str, times: int):
    for _ in range(times):
        si.record_match_confirmation(learning, supplier, text=text)


# ── Kännetecknen ────────────────────────────────────────────

def test_registered_org_number_matches_without_printed_supplier_name():
    """Ett unikt, giltigt org.nr räcker även om namnet saknas på fakturan."""
    text = (
        f"Faktura\nOrg.nr {ORG_A[:6]}-{ORG_A[6:]}\n"
        "Fakturanr A-1\nAtt betala 500,00"
    )
    suppliers = [{
        "name": "Leverantör Utan Tryckt Namn AB",
        "org_number": ORG_A,
    }]

    parsed = si.parse_invoice_text(text, suppliers=suppliers)

    assert parsed["supplier"] == "Leverantör Utan Tryckt Namn AB"
    assert parsed["supplier_match"]["status"] == "matched"
    assert parsed["supplier_match"]["candidates"] == [{
        "name": "Leverantör Utan Tryckt Namn AB",
        "score": 5,
        "signals": ["org_number"],
    }]
    assert not parsed["supplier_match"]["uncertain"]


def test_ocr_reference_is_not_required_for_matching_or_registration():
    text = (
        f"Faktura\nOrg.nr {ORG_A[:6]}-{ORG_A[6:]}\n"
        "Bankgiro 999-1234\nFakturanr A-17\nAtt betala 500,00"
    )
    parsed = si.parse_invoice_text(text, suppliers=[{
        "name": "Alpha AB", "org_number": ORG_A,
        "bankgiro": "9991234",
    }])

    assert parsed["supplier"] == "Alpha AB"
    assert parsed["invoice_number"] == "A-17"
    assert parsed["total_amount"] == 500.0
    assert parsed["ocr"] == ""
    assert parsed["missing"] == []


def test_identifiers_need_valid_org_checksum():
    assert si._org_nr_checksum_ok(ORG_A)
    bad = ORG_A[:9] + str((int(ORG_A[9]) + 1) % 10)
    assert not si._org_nr_checksum_ok(bad)
    ids = si._invoice_identifiers(_text(ORG_A))
    assert ids["org"] == {ORG_A}
    assert ids["bg"] == {"9991234"}
    assert si._invoice_identifiers(
        f"Org.nr 16 {ORG_A[:6]}-{ORG_A[6:]}"
    )["org"] == {ORG_A}
    # Ogiltig kontrollsiffra = inget kännetecken alls.
    assert si._invoice_identifiers(_text(bad))["org"] == set()


def test_identifier_counts_accumulate_per_supplier():
    learning: dict = {}
    _learn(learning, "Okanda AB", _text(ORG_A), 2)
    entry = si.learning_entry(learning, "Okanda AB")
    assert entry["identifiers"]["org"][ORG_A] == 2
    assert entry["identifiers"]["bg"]["9991234"] == 2


def test_template_confirmations_are_versioned_and_deduplicated():
    learning: dict = {}
    template = {"fields": {
        "invoice_number": {"label": "Fakturanr"},
        "total_amount": {"label": "Att betala"},
    }}
    confirmation_id = si.match_confirmation_id(
        "Okända AB", "F-100", path="/tmp/f-100.pdf",
    )
    assert si.match_confirmation_id(
        "Okända AB", "F-101", path="/tmp/f-100.pdf",
        invoice_date="2026-11-03",
    ) == confirmation_id
    for _ in range(2):
        si.record_match_confirmation(
            learning, "Okända AB", text=_text(ORG_A),
            confirmation_id=confirmation_id,
            template_name="Okända AB", template=template,
            template_fields=["invoice_number", "total_amount"],
        )
    supplier_entry = si.learning_entry(learning, "Okända AB")
    template_entry = si.template_confirmation_entry(
        learning, "Okända AB", template
    )
    assert supplier_entry["confirmed"] == 1
    assert supplier_entry["identifiers"]["org"][ORG_A] == 1
    assert template_entry["confirmed"] == 1
    assert template_entry["fields"] == {
        "invoice_number": 1, "total_amount": 1,
    }

    changed_template = {"fields": {
        "invoice_number": {"label": "Fakturanummer"},
        "total_amount": {"label": "Att betala"},
    }}
    assert si.template_confirmation_entry(
        learning, "Okända AB", changed_template
    ) == {}


def test_path_confirmation_id_is_independent_of_supplier_choice():
    first = si.match_confirmation_id(
        "Alpha AB", "A-17", path="/tmp/shared-invoice.pdf",
    )
    reassigned = si.match_confirmation_id(
        "Beta AB", "B-99", path="/tmp/shared-invoice.pdf",
        invoice_date="2026-11-03",
    )
    assert first == reassigned
    assert si.match_confirmation_id(
        "Alpha AB", "A-17", invoice_date="2026-11-03"
    ) != si.match_confirmation_id(
        "Beta AB", "A-17", invoice_date="2026-11-03"
    )

    learning: dict = {}
    template_a = {"fields": {
        "invoice_number": {"label": "Fakturanr"},
        "total_amount": {"label": "Att betala"},
    }}
    template_b = {"fields": {
        "invoice_number": {"label": "Fakturanr"},
        "total_amount": {"label": "Summa"},
    }}
    si.record_match_confirmation(
        learning, "Alpha AB", text=_text(ORG_A),
        confirmation_id=first, template_name="Alpha AB",
        template=template_a, template_fields=["invoice_number"],
    )
    si.record_match_confirmation(
        learning, "Beta AB", text=_text(ORG_B),
        confirmation_id=reassigned, template_name="Beta AB",
        template=template_b, template_fields=["invoice_number"],
    )

    assert si.learning_entry(learning, "Alpha AB")["confirmed"] == 1
    assert si.learning_entry(learning, "Beta AB").get("confirmed", 0) == 0
    assert si.template_confirmation_entry(
        learning, "Beta AB", template_b
    ) == {}


def test_legacy_path_confirmation_is_migrated_without_recounting():
    path = "/tmp/legacy-invoice.pdf"
    old_id = si._legacy_path_confirmation_id("Alpha AB", path)
    template = {"fields": {
        "invoice_number": {"label": "Fakturanr"},
        "total_amount": {"label": "Att betala"},
    }}
    signature = si.template_confirmation_signature(template)
    learning = {"Alpha AB": {
        "confirmed": 1,
        "confirmation_ids": [old_id],
        "identifiers": {"org": {ORG_A: 1}},
        "templates": {signature: {
            "confirmed": 1, "confirmation_ids": [old_id],
            "fields": {"invoice_number": 1},
        }},
    }}
    new_id = si.match_confirmation_id(
        "Alpha AB", "A-17", path=path,
    )
    assert new_id != old_id
    entry = si.record_match_confirmation(
        learning, "Alpha AB", text=_text(ORG_A),
        confirmation_id=new_id, source_path=path,
        template_name="Alpha AB", template=template,
        template_fields=["invoice_number", "total_amount"],
    )
    assert entry["confirmed"] == 1
    assert entry["identifiers"]["org"][ORG_A] == 1
    assert new_id in entry["confirmation_ids"]
    template_entry = si.template_confirmation_entry(
        learning, "Alpha AB", template
    )
    assert template_entry["confirmed"] == 1
    assert template_entry["fields"] == {"invoice_number": 1}
    assert new_id in template_entry["confirmation_ids"]

    reassigned_learning = {"Alpha AB": {
        "confirmed": 1, "confirmation_ids": [old_id],
    }}
    reassigned = si.record_match_confirmation(
        reassigned_learning, "Beta AB", text=_text(ORG_B),
        confirmation_id=new_id, source_path=path,
    )
    assert reassigned.get("confirmed", 0) == 0
    assert reassigned_learning["Alpha AB"]["confirmed"] == 1


def test_unconfirmed_custom_template_stays_uncertain_until_reviewed():
    template = {"fields": {
        "invoice_number": {"label": "Fakturanr"},
        "total_amount": {"label": "Att betala"},
    }}
    suppliers = [{"name": "Alpha AB"}]
    templates = {"Alpha AB": template}
    text = "Alpha AB\nFakturanr A-17\nAtt betala 225,00"
    learning: dict = {}
    parsed = si.parse_invoice_text(
        text, suppliers, templates, match_learning=learning
    )
    guarded = si.require_template_confirmation(
        parsed, templates, learning, suppliers
    )
    assert guarded["match_uncertain"] is True
    assert guarded["match_reason"] == "template_unconfirmed"
    assert guarded["match_kind"] == "template"
    assert guarded["match_candidates"] == ["Alpha AB"]
    assert guarded["template_match"]["confirmed"] == 0

    confirmation_id = si.match_confirmation_id(
        "Alpha AB", "A-17", path="/tmp/a-17.pdf",
    )
    si.record_template_confirmation(
        learning, "Alpha AB", "Alpha AB", template,
        confirmation_id=confirmation_id,
        template_fields=["invoice_number", "total_amount"],
    )
    reviewed = si.parse_invoice_text(
        text, suppliers, templates, match_learning=learning
    )
    reviewed = si.require_template_confirmation(
        reviewed, templates, learning, suppliers
    )
    assert not reviewed.get("match_uncertain")
    assert reviewed["template_match"]["confirmed"] == 1
    # Reviewing a template does not graduate supplier auto-matching.
    assert si.learning_entry(learning, "Alpha AB").get("confirmed", 0) == 0


def test_template_field_training_requires_exact_confirmed_values():
    template = {"fields": {
        "invoice_number": {"label": "Fakturanr"},
        "total_amount": {"label": "Att betala"},
    }}
    extracted = {"invoice_number": "F-17", "total_amount": 899.0}
    confirmed = {"invoice_number": "F-17", "total_amount": 998.0}
    assert si.confirmed_template_fields(
        template, extracted, confirmed
    ) == ["invoice_number"]


def test_parser_exposes_previous_template_confirmations():
    template = {"fields": {
        "invoice_number": {"label": "Fakturanr"},
        "total_amount": {"label": "Att betala"},
    }}
    learning: dict = {}
    text = "Alpha AB\nFakturanr A-17\nAtt betala 225,00"
    confirmation_id = si.match_confirmation_id(
        "Alpha AB", "A-17", path="/tmp/a-17.pdf",
    )
    si.record_match_confirmation(
        learning, "Alpha AB", confirmation_id=confirmation_id,
        template_name="Alpha AB", template=template,
        template_fields=["invoice_number", "total_amount"],
    )
    parsed = si.parse_invoice_text(
        text, [{"name": "Alpha AB"}], {"Alpha AB": template},
        match_learning=learning,
    )
    assert parsed["template_match"]["confirmed"] == 1


# ── Trösklarna ──────────────────────────────────────────────

def test_no_auto_connect_before_five_confirmations():
    learning: dict = {}
    _learn(learning, "Okanda AB", _text(ORG_A), 4)
    assert si.learned_supplier_candidates(_text(ORG_A), learning) == []
    si.record_match_confirmation(learning, "Okanda AB", text=_text(ORG_A))
    assert si.learned_supplier_candidates(_text(ORG_A), learning) == [
        "Okanda AB"
    ]


def test_identifier_must_be_seen_twice():
    """Kännetecken i bara EN bekräftad faktura kopplar inte —
    det kan ha varit någon annans nummer i texten."""
    learning: dict = {}
    _learn(learning, "Okanda AB", _text(ORG_A), 5)
    # Bankgirot fanns bara i första fakturan:
    learning2: dict = {}
    si.record_match_confirmation(learning2, "Okanda AB", text=_text(ORG_A))
    plain = "Faktura utan nummer\nFaktnr 1\nAtt betala 10,00"
    _learn(learning2, "Okanda AB", plain, 4)
    only_bg = f"Bankgiro 999-1234\nFaktnr 7\nAtt betala 500,00"
    assert si.learned_supplier_candidates(only_bg, learning2) == []


def test_shared_identifier_never_connects():
    """Samma org.nr bekräftat för TVÅ leverantörer = förorenat,
    kopplar aldrig automatiskt."""
    learning: dict = {}
    _learn(learning, "Okanda AB", _text(ORG_A), 5)
    _learn(learning, "Andra AB", _text(ORG_A), 5)
    assert si.learned_supplier_candidates(_text(ORG_A), learning) == []


def test_two_qualified_suppliers_are_candidates_not_a_guess():
    learning: dict = {}
    _learn(learning, "Okanda AB", _text(ORG_A), 5)
    _learn(learning, "Andra AB", _text(ORG_B, bg="888-4321"), 5)
    both = _text(ORG_A) + f"\nOrg.nr {ORG_B[:6]}-{ORG_B[6:]}"
    cands = si.learned_supplier_candidates(both, learning)
    assert set(cands) == {"Okanda AB", "Andra AB"}
    r = si.parse_invoice_text(
        both, [{"name": "Okanda AB"}, {"name": "Andra AB"}], {},
        match_learning=learning,
    )
    assert r["supplier"] == ""
    assert r["match_uncertain"] is True
    assert r["match_reason"] == "learned_ambiguous"


# ── Kopplingen i tolkaren ───────────────────────────────────

def test_scan_import_passes_learning_memory_to_watcher(tmp_path):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from ui.scan_import_view import ScanImportView

    class Core:
        def get_suppliers(self):
            return [{"name": "Okanda AB"}]

        def get_setting(self, key, default=None):
            return default

    view = ScanImportView(
        app=Core(), templates_path=tmp_path / "invoice_templates.json",
    )
    try:
        assert view._watch is not None
        assert view._watch._learning_provider is not None
        assert view._watch._learning_provider() is view._get_match_learning()
    finally:
        view.close()


def test_manual_import_creation_records_confirmed_template_only_after_save(
    tmp_path, monkeypatch,
):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    import ui.scan_import_view as scan_ui
    from ui.scan_import_view import ScanImportView

    template = {"fields": {
        "invoice_number": {"label": "Fakturanr"},
        "total_amount": {"label": "Att betala"},
    }}
    templates_path = tmp_path / "invoice_templates.json"
    assert si.save_templates(templates_path, {"Alpha AB": template})

    class Core:
        def get_suppliers(self):
            return [{"name": "Alpha AB"}]

        def get_setting(self, key, default=None):
            return default

    view = ScanImportView(app=Core(), templates_path=templates_path)
    row = {
        "file": "a-17.pdf", "_path": str(tmp_path / "a-17.pdf"),
        "_text": "Alpha AB\nFakturanr A-17\nAtt betala 225,00",
        "supplier": "Alpha AB", "template": "Alpha AB",
        "invoice_number": "A-17", "total_amount": 225.0,
        "date": "2026-10-01", "due_date": "", "ocr": "",
        "missing": [], "status": "redo", "pages": 1,
        "template_match": {"status": "matched", "template": "Alpha AB"},
    }
    view._rows = [row]
    view._selected_rows = lambda: [0]
    view._possible_duplicates_for_rows = lambda _ready: []
    view._save_invoice = lambda *args, **kwargs: False
    view._unpark_row = lambda _row: None
    view._refresh_table = lambda: None
    view._show_invoices_tab = lambda: None
    monkeypatch.setattr(scan_ui.QMessageBox, "information", lambda *a: None)
    try:
        view._create_invoices()
        assert view._rows == [row]
        assert si.load_match_learning(tmp_path / "match_memory.json") == {}
        view._save_invoice = lambda *args, **kwargs: True
        view._create_invoices()
        learning = si.load_match_learning(tmp_path / "match_memory.json")
        entry = si.template_confirmation_entry(
            learning, "Alpha AB", template
        )
        assert entry["confirmed"] == 1
        assert entry["fields"] == {
            "invoice_number": 1, "total_amount": 1,
        }
        assert view._rows == []
    finally:
        view.close()


def test_automatic_registration_is_not_a_template_confirmation(
    tmp_path, monkeypatch,
):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    import ui.scan_import_view as scan_ui
    from ui.scan_import_view import ScanImportView

    template = {"fields": {
        "invoice_number": {"label": "Fakturanr"},
        "total_amount": {"label": "Att betala"},
    }}
    templates_path = tmp_path / "invoice_templates.json"
    assert si.save_templates(templates_path, {"Alpha AB": template})
    learning = {}
    si.record_template_confirmation(
        learning, "Alpha AB", "Alpha AB", template,
        confirmation_id="verified-template-before-auto-row",
        template_fields=["invoice_number", "total_amount"],
    )
    assert si.save_match_learning(
        tmp_path / "match_memory.json", learning
    )

    class Core:
        def get_suppliers(self):
            return [{"name": "Alpha AB"}]

        def get_setting(self, key, default=None):
            return default

    view = ScanImportView(app=Core(), templates_path=templates_path)
    view._rows = [{
        "file": "a-18.pdf", "_path": str(tmp_path / "a-18.pdf"),
        "_text": "Alpha AB\nFakturanr A-18\nAtt betala 125,00",
        "supplier": "Alpha AB", "template": "Alpha AB",
        "invoice_number": "A-18", "total_amount": 125.0,
        "date": "2026-10-02", "due_date": "", "ocr": "",
        "missing": [], "status": "redo", "pages": 1,
        "template_match": {"status": "matched", "template": "Alpha AB"},
    }]
    view._possible_duplicates_for_rows = lambda _ready: []
    view._save_invoice = lambda *args, **kwargs: True
    view._unpark_row = lambda _row: None
    view._show_invoices_tab = lambda: None
    monkeypatch.setattr(scan_ui.QMessageBox, "information", lambda *a: None)
    try:
        view._refresh_table()
        assert view._auto_register_matched_rows([view._rows[0]]) == 1
        learning = si.load_match_learning(tmp_path / "match_memory.json")
        assert si.learning_entry(learning, "Alpha AB").get(
            "confirmed", 0
        ) == 0
        assert si.template_confirmation_entry(
            learning, "Alpha AB", template
        )["confirmed"] == 1
    finally:
        view.close()


def test_parse_connects_learned_supplier_automatically():
    """Efter 5 bekräftade: ny faktura utan tryckt leverantörsnamn
    kopplas ändå rätt — på org.nr/bankgiro appen lärt sig."""
    learning: dict = {}
    _learn(learning, "Okanda AB", _text(ORG_A), 5)
    text = _text(ORG_A).replace("Faktnr 12", "Fakturanr: 4711")
    r = si.parse_invoice_text(
        text, [{"name": "Okanda AB"}], {}, match_learning=learning
    )
    assert r["supplier"] == "Okanda AB"
    assert r["supplier_match"]["reason"] == "learned"
    assert not r.get("match_uncertain")
    assert r["invoice_number"] == "4711"
    assert r["total_amount"] == 500.0


def test_confirmed_bankgiro_learning_connects_new_invoice_without_ocr():
    learning: dict = {}
    for number in range(5):
        si.record_match_confirmation(
            learning, "Okanda AB", text=(
                f"Bankgiro 999-1234\nFakturanr A-{number}\n"
                "Att betala 500,00"
            ),
            confirmation_id=f"confirmed-{number}",
        )

    parsed = si.parse_invoice_text(
        "Bankgiro 999-1234\nFakturanr A-99\nAtt betala 125,00",
        [{"name": "Okanda AB"}], {}, match_learning=learning,
    )

    assert parsed["supplier"] == "Okanda AB"
    assert parsed["supplier_match"]["reason"] == "learned"
    assert parsed["ocr"] == ""
    assert parsed["missing"] == []


def test_bg_abbreviation_is_learned_and_can_connect_a_new_invoice():
    learning: dict = {}
    for number in range(5):
        si.record_match_confirmation(
            learning, "Okanda AB",
            text=f"BG: 999-1234\nFakturanr B-{number}\nAtt betala 50,00",
            confirmation_id=f"bg-confirmed-{number}",
        )

    assert si.learning_entry(learning, "Okanda AB")["identifiers"]["bg"] == {
        "9991234": 5,
    }
    parsed = si.parse_invoice_text(
        "BG: 999-1234\nFakturanr B-99\nAtt betala 75,00",
        [{"name": "Okanda AB"}], {}, match_learning=learning,
    )

    assert parsed["supplier"] == "Okanda AB"
    assert parsed["supplier_match"]["reason"] == "learned"
    assert parsed["ocr"] == ""
    assert parsed["missing"] == []


def test_without_learning_nothing_connects():
    """Samma faktura UTAN inlärningsminne: ingen koppling,
    ingen gissning (oförändrat försiktigt beteende)."""
    text = _text(ORG_A)
    r = si.parse_invoice_text(text, [{"name": "Okanda AB"}], {})
    assert r["supplier"] == ""


def test_uncertain_assessment_not_silently_resolved():
    """Var den vanliga bedömningen redan osäker löses den inte
    upp av inlärningen — användaren frågas som förut."""
    learning: dict = {}
    _learn(learning, "Pilkington Sverige AB", _text(ORG_A), 5)
    sups = [
        {"name": "Pilkington Sverige AB"},
        {"name": "Pilkington Glas AB"},
    ]
    text = "Pilkington\n" + _text(ORG_A)
    r = si.parse_invoice_text(text, sups, {}, match_learning=learning)
    assert r["supplier"] == ""
    assert r["match_uncertain"] is True


# ── Vyn matar minnet med kännetecken ────────────────────────

def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_view_records_identifiers_and_announces_threshold(
    tmp_path, monkeypatch
):
    """5:e manuella matchningen: statusraden säger att appen nu
    kopplar leverantören själv, och kännetecknen finns i minnet."""
    _qapp()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QComboBox, QDialog
    from ui.scan_import_view import ScanImportView

    import ui.scan_import_view as sv
    monkeypatch.setattr(sv.QMessageBox, "information", lambda *_a, **_k: None)

    class Core:
        def __init__(self):
            self.created = []

        def get_suppliers(self):
            return [{"name": "Okanda AB"}]

        def get_invoices(self):
            return list(self.created)

        def add_invoice(self, data):
            record = dict(data, id=f"fake-{len(self.created) + 1}")
            self.created.append(record)
            return record

        def get_setting(self, key, default=None):
            return default

    view = ScanImportView(
        app=Core(), templates_path=tmp_path / "invoice_templates.json"
    )
    view._templates_cache = {}
    try:
        # Gör 4 bekräftelser direkt mot minnet (tidigare dagars
        # matchningar), sedan den 5:e via dialogen.
        learning = view._get_match_learning()
        _learn(learning, "Okanda AB", _text(ORG_A), 4)
        view._save_match_learning()

        row = {
            "file": "f.pdf", "supplier": "",
            "invoice_number": "12", "total_amount": 500.0,
            "date": "", "due_date": "", "ocr": "",
            "method": "pdf", "status": "saknas: leverantör",
            "missing": ["leverantör"], "_path": "", "pages": 1,
            "_text": _text(ORG_A),
        }
        view._rows = [row]
        view._refresh_table()
        view._tbl.selectRow(0)

        def _choose():
            dlg = QApplication.activeModalWidget()
            assert isinstance(dlg, QDialog)
            combo = dlg.findChild(QComboBox)
            combo.setCurrentIndex(combo.findText("Okanda AB"))
            dlg.accept()

        QTimer.singleShot(50, _choose)
        view._manual_match_row()
        entry = si.learning_entry(
            view._get_match_learning(), "Okanda AB"
        )
        assert entry["confirmed"] == 5
        assert entry["identifiers"]["org"][ORG_A] == 5
        assert entry["identifiers"]["bg"]["9991234"] == 5
        assert "Okanda AB" in view._lbl_status.text()
        assert "känner appen igen" in view._lbl_status.text()
        # Och nästa likadana faktura kopplas nu av sig själv:
        r = si.parse_invoice_file(
            tmp_path / "saknas.pdf", _text(ORG_A),
            [{"name": "Okanda AB"}], {},
            match_learning=view._get_match_learning(),
        )
        assert r["supplier"] == "Okanda AB"
        assert r["supplier_match"]["reason"] == "learned"
    finally:
        view.close()


def test_supplier_schema_defaults_to_an_alias_list(tmp_path):
    from ui.core.storage import DataStore, get_schema

    assert get_schema("suppliers")["aliases"] == []
    store = DataStore("suppliers", tmp_path)
    record = store.add({
        "name": "Legal Name AB", "aliases": ["Trade Name"],
    })
    assert record["aliases"] == ["Trade Name"]


def test_supplier_aliases_match_but_duplicate_aliases_stay_uncertain():
    suppliers = [
        {
            "name": "Nordlys Holding AB",
            "aliases": ["Nordlys Energi", "NE Faktura"],
        },
    ]
    result = si.assess_supplier_match(
        "NORDLYS ENERGI\nFakturanr: N-100", suppliers
    )
    assert result["status"] == "matched"
    assert result["supplier"] == "Nordlys Holding AB"
    assert "alias_full_name" in result["candidates"][0]["signals"]

    competing = suppliers + [
        {"name": "Nordlys Drift AB", "aliases": "Nordlys Energi; Drift"},
    ]
    result = si.assess_supplier_match(
        "NORDLYS ENERGI\nFakturanr: N-101", competing
    )
    assert result["status"] == "uncertain"
    assert result["reason"] in {"ambiguous", "competing"}
    assert {candidate["name"] for candidate in result["candidates"]} == {
        "Nordlys Holding AB", "Nordlys Drift AB",
    }


def test_supplier_identifier_match_requires_label_and_supports_pg_iban():
    bankgiro_supplier = {"name": "Direktglas", "bg": "942-2817"}
    # Ett oetiketterat likadant sifferblock är inte betalningsbevis.
    assert si.assess_supplier_match(
        "Fakturanummer 9422817", [bankgiro_supplier]
    )["status"] == "none"
    assert si.match_supplier(
        "Bankgiro: 942-2817", [bankgiro_supplier]
    ) == "Direktglas"
    assert si.invoice_bankgiro_values("BG 942-2817") == ["9422817"]
    assert si.suppliers_matching_bankgiro(
        "BG 942-2817", [bankgiro_supplier]
    ) == [{"name": "Direktglas", "bankgiro": "9422817"}]

    plusgiro_supplier = {"name": "Plus AB", "pg": "7654321"}
    assert si.assess_supplier_match(
        "Referens 7654321", [plusgiro_supplier]
    )["status"] == "none"
    assert si.match_supplier(
        "Plusgiro 765-4321", [plusgiro_supplier]
    ) == "Plus AB"

    iban = "SE4550000000058398257466"
    iban_supplier = {"name": "Iban AB", "iban": iban}
    assert si.assess_supplier_match(
        iban, [iban_supplier]
    )["status"] == "none"
    assert si.match_supplier(
        "IBAN: SE45 5000 0000 0583 9825 7466", [iban_supplier]
    ) == "Iban AB"


def test_competing_exact_supplier_identifiers_are_never_guessed():
    result = si.assess_supplier_match(
        "BG 123-4567",
        [
            {"name": "Alpha AB", "bg": "1234567"},
            {"name": "Beta AB", "bankgiro": "123-4567"},
        ],
    )
    assert result["status"] == "uncertain"
    assert result["reason"] == "ambiguous"
