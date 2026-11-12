# -*- coding: utf-8 -*-
"""
Tester: fem egna mallar per leverantör — och nollställning vid fel.

Regeln: appen börjar koppla en leverantör själv först efter fem egna
manuella matchningar (mallar). Räknaren fortsätter sedan växa — appen
lär hela tiden. Rättar användaren en koppling som APPEN gjorde själv
nollställs räknaren: då krävs fem nya egna matchningar, och
kännetecknen som pekade fel glöms.
"""
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

ORG = "556677-8899"
TEXT = (
    "Testbolaget AB\n"
    f"Org.nr: {ORG}\n"
    "Fakturanummer: 921040\n"
    "Fakturadatum: 2024-12-05\n"
    "Att betala: 857,25\n"
)


@pytest.fixture(autouse=True)
def _sv():
    i18n.set_language("sv", notify=False)
    yield
    i18n.set_language("sv", notify=False)


def _qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _Core:
    def __init__(self):
        self.created: list[dict] = []

    def get_suppliers(self):
        return [{"name": "Testbolaget AB"}, {"name": "Annan AB"}]

    def get_invoices(self):
        return list(self.created)

    def add_invoice(self, data):
        record = dict(data, id=f"fake-{len(self.created) + 1}")
        self.created.append(record)
        return record

    def get_setting(self, key, default=None):
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


def _view(tmp_path):
    from ui.scan_import_view import ScanImportView

    view = ScanImportView(
        app=_Core(), templates_path=tmp_path / "invoice_templates.json"
    )
    view._templates_cache = {}
    view._watch = _Watch()
    return view


def _learning(confirmations: int = 5) -> dict:
    learning: dict = {}
    for n in range(confirmations):
        si.record_match_confirmation(
            learning, "Testbolaget AB", text=TEXT,
            confirmation_id=f"tidigare-{n}",
        )
    return learning


# ── Fem egna mallar öppnar för automatisk koppling ─────────────────

def test_five_own_templates_are_needed_before_automatic_linking():
    four = _learning(4)
    assert si.learned_supplier_candidates(TEXT, four) == []

    five = _learning(5)
    assert si.learned_supplier_candidates(TEXT, five) == [
        "Testbolaget AB"
    ]


def test_learning_keeps_growing_after_the_threshold():
    learning = _learning(5)
    for n in range(5, 9):
        si.record_match_confirmation(
            learning, "Testbolaget AB", text=TEXT,
            confirmation_id=f"senare-{n}",
        )
    assert learning["Testbolaget AB"]["confirmed"] == 9
    # Samma kännetecken fortsätter stärkas — ingen "avklarad" gräns.
    assert learning["Testbolaget AB"]["identifiers"]["org"][
        "5566778899"
    ] == 9


# ── En felaktig automatkoppling nollställer räknaren ───────────────

def test_wrong_automatic_link_resets_the_counter_to_five_new():
    learning = _learning(5)
    assert si.learned_supplier_candidates(TEXT, learning)

    entry = si.record_match_correction(
        learning, "Testbolaget AB", text=TEXT
    )

    assert entry["confirmed"] == 0
    assert entry["corrections"] == 1
    # Kännetecknet som pekade fel är glömt …
    assert "5566778899" not in entry.get("identifiers", {}).get("org", {})
    # … så appen kopplar inte samma faktura fel igen innan fem nya
    # egna matchningar har gjorts.
    assert si.learned_supplier_candidates(TEXT, learning) == []
    for n in range(5):
        si.record_match_confirmation(
            learning, "Testbolaget AB", text=TEXT,
            confirmation_id=f"ny-{n}",
        )
    assert si.learned_supplier_candidates(TEXT, learning) == [
        "Testbolaget AB"
    ]


def test_correction_keeps_templates_and_other_suppliers():
    learning = _learning(5)
    si.record_match_confirmation(
        learning, "Annan AB", text="Annan AB\nBankgiro 123-4567\n",
        confirmation_id="annan-1",
    )
    si.record_match_correction(learning, "Testbolaget AB", text=TEXT)
    assert learning["Annan AB"]["confirmed"] == 1
    assert learning["Annan AB"]["identifiers"]["bg"]["1234567"] == 1


def test_correction_is_only_triggered_by_apps_own_links():
    auto = {
        "supplier": "Testbolaget AB",
        "supplier_match": {"supplier": "Testbolaget AB",
                           "reason": "learned"},
    }
    assert si.match_correction_needed(auto, "Annan AB") == (
        "Testbolaget AB"
    )
    # Samma leverantör = ingen rättelse
    assert si.match_correction_needed(auto, "Testbolaget AB") == ""

    manual = {
        "supplier": "Testbolaget AB",
        "supplier_match": {"supplier": "Testbolaget AB",
                           "reason": "user_choice"},
    }
    assert si.match_correction_needed(manual, "Annan AB") == ""

    logo = {
        "supplier": "Testbolaget AB",
        "supplier_match": {"supplier": "Testbolaget AB",
                           "reason": "learned_logo"},
    }
    assert si.match_correction_needed(logo, "Annan AB") == (
        "Testbolaget AB"
    )


# ── Rättelsen i Import nollställer och lär rätt leverantör ─────────

def test_manual_correction_in_import_resets_wrong_supplier(tmp_path):
    _qapp()
    view = _view(tmp_path)
    try:
        learning = _learning(5)
        view._learning_cache = learning
        row = {
            "file": "felkopplad.pdf",
            "supplier": "Testbolaget AB",
            "supplier_match": {
                "supplier": "Testbolaget AB",
                "reason": "learned", "status": "matched",
            },
            "invoice_number": "921040",
            "total_amount": 857.25,
            "date": "2024-12-05",
            "due_date": "",
            "ocr": "",
            "missing": [],
            "_path": "",
            "_text": TEXT,
        }
        view._rows = [row]

        note = view._apply_manual_match(row, "Annan AB")

        assert learning["Testbolaget AB"]["confirmed"] == 0
        assert learning["Testbolaget AB"]["corrections"] == 1
        # Rätt leverantör får sin första egna matchning direkt.
        assert learning["Annan AB"]["confirmed"] == 1
        assert "5 nya egna matchningar" in note
        assert "Testbolaget AB" in note
    finally:
        view.close()


def test_correcting_a_manual_choice_does_not_reset_anything(tmp_path):
    _qapp()
    view = _view(tmp_path)
    try:
        learning = _learning(5)
        view._learning_cache = learning
        row = {
            "file": "bytt-val.pdf",
            "supplier": "Testbolaget AB",
            "supplier_match": {
                "supplier": "Testbolaget AB", "reason": "user_choice",
            },
            "invoice_number": "921041",
            "total_amount": 100.0,
            "date": "2024-12-05",
            "due_date": "",
            "ocr": "",
            "missing": [],
            "_path": "",
            "_text": TEXT,
        }
        view._rows = [row]
        view._apply_manual_match(row, "Annan AB")
        # Användarens eget tidigare val räknas inte som appens fel.
        assert "corrections" not in learning["Testbolaget AB"]
        assert learning["Testbolaget AB"]["confirmed"] == 5
    finally:
        view.close()
