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

def test_identifiers_need_valid_org_checksum():
    assert si._org_nr_checksum_ok(ORG_A)
    bad = ORG_A[:9] + str((int(ORG_A[9]) + 1) % 10)
    assert not si._org_nr_checksum_ok(bad)
    ids = si._invoice_identifiers(_text(ORG_A))
    assert ids["org"] == {ORG_A}
    assert ids["bg"] == {"9991234"}
    # Ogiltig kontrollsiffra = inget kännetecken alls.
    assert si._invoice_identifiers(_text(bad))["org"] == set()


def test_identifier_counts_accumulate_per_supplier():
    learning: dict = {}
    _learn(learning, "Okanda AB", _text(ORG_A), 2)
    entry = si.learning_entry(learning, "Okanda AB")
    assert entry["identifiers"]["org"][ORG_A] == 2
    assert entry["identifiers"]["bg"]["9991234"] == 2


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

    class Core:
        def get_suppliers(self):
            return [{"name": "Okanda AB"}]

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
