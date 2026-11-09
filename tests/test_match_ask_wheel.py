# -*- coding: utf-8 -*-
"""
Tester: osäker leverantörs-/mallmatchning frågar användaren +
dropdownfält ignorerar mushjulet när de är stängda.

Regeln (2026-10-27): vid minsta osäkerhet om vilken leverantör
eller mall en faktura tillhör ska appen FRÅGA användaren — aldrig
gissa, aldrig parkera tyst och aldrig auto-registrera. Och: scroll
över ett stängt dropdownfält får aldrig ändra dess värde.
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


# ── Tolkningsmotorn: svagt/tvetydigt = osäkert, aldrig gissat ──

def test_weak_first_name_hit_is_uncertain_not_guessed():
    sups = [{"name": "Pilkington Sverige AB"}]
    text = "Pilkington\nFakturanr: 9911\nAtt betala: 1 250,00\n"
    parsed = si.parse_invoice_text(text, sups)
    assert si.match_supplier(text, sups) == ""
    assert parsed["supplier"] == ""
    assert parsed["match_uncertain"] is True
    assert parsed["match_kind"] == "supplier"
    assert parsed["match_candidates"] == ["Pilkington Sverige AB"]
    assert "leverantör" in parsed["missing"]


def test_two_strong_suppliers_are_ambiguous():
    sups = [{"name": "Alpha Energi AB"}, {"name": "Beta Energi AB"}]
    text = (
        "Alpha Energi AB\nBeta Energi AB\n"
        "Fakturanr: 9911\nAtt betala: 1 250,00\n"
    )
    parsed = si.parse_invoice_text(text, sups)
    assert parsed["supplier"] == ""
    assert parsed["match_uncertain"] is True
    assert set(parsed["match_candidates"]) == {
        "Alpha Energi AB", "Beta Energi AB",
    }


def test_unique_strong_hit_still_chosen_automatically():
    sups = [{"name": "Nordlys Energi AB"}, {"name": "Annan AB"}]
    text = "NORDLYS ENERGI AB\nFakturanr: 9911\nAtt betala: 1 250,00\n"
    parsed = si.parse_invoice_text(text, sups)
    assert parsed["supplier"] == "Nordlys Energi AB"
    assert not parsed.get("match_uncertain")


def test_two_template_keys_for_supplier_are_uncertain():
    sups = [{"name": "Martin G Anderson AB"}]
    templates = {
        "Martin G": {"fields": {}},
        "Martin G Anderson": {"fields": {}},
    }
    text = "Martin G Anderson AB\nFakturanr: 9911\nAtt betala: 1 250,00\n"
    parsed = si.parse_invoice_text(text, sups, templates=templates)
    assert parsed["match_uncertain"] is True
    assert parsed["match_kind"] == "template"
    assert set(parsed["match_candidates"]) == {
        "Martin G", "Martin G Anderson",
    }
    assert not parsed.get("template")


# ── Bevakade mappar: osäkert parkeras, registreras aldrig ──────

class _FakeApp:
    def get_suppliers(self):
        return [
            {"name": "Pilkington Sverige AB"},
            {"name": "Pilkington Glas AB"},
        ]

    def get_invoices(self):
        return []


def test_watch_uncertain_match_parked_not_registered(tmp_path):
    _qapp()
    from ui.watch_folders import WatchManager, _park_reason_sv

    folder = tmp_path / "In"
    folder.mkdir()
    text = "Pilkington\nFakturanr: 9911\nAtt betala: 1 250,00\n"
    mgr = WatchManager(
        tmp_path / "watch_folders.json",
        app=_FakeApp(),
        extract_fn=lambda path: (text, "test"),
        templates_provider=lambda: {},
    )
    mgr.set_folders([{"supplier": "", "path": str(folder)}])
    ready, parked = [], []
    mgr.invoice_ready.connect(lambda row, path: ready.append(row))
    mgr.file_parked.connect(lambda info: parked.append(info))
    (folder / "f1.pdf").write_bytes(b"%PDF-fake")
    mgr.scan_all()
    assert ready == []
    assert len(parked) == 1
    assert parked[0]["reason"] == "uncertain-supplier"
    assert parked[0]["parsed"]["match_uncertain"] is True
    assert "osäker" in _park_reason_sv("uncertain-supplier")


# ── Import-vyn: olöst osäkerhet registreras aldrig ─────────────

class _FakeMsgBox:
    @staticmethod
    def warning(*args, **kwargs):
        return None

    @staticmethod
    def information(*args, **kwargs):
        return None

    @staticmethod
    def question(*args, **kwargs):
        return None


def test_create_invoices_never_registers_unresolved_match(
        tmp_path, monkeypatch):
    _qapp()
    import ui.scan_import_view as sv
    from ui.scan_import_view import ScanImportView

    created = []

    class FakeCore:
        def get_suppliers(self):
            return [{"name": "Alpha Energi AB"}]

        def get_setting(self, key, default=None):
            return default

        def add_invoice(self, data):
            created.append(data)
            return {"id": "x"}

    monkeypatch.setattr(sv, "QMessageBox", _FakeMsgBox)
    view = ScanImportView(
        app=FakeCore(), templates_path=tmp_path / "templates.json"
    )
    try:
        view._rows.append({
            "file": "f1.pdf", "_path": "", "_text": "text",
            "supplier": "Alpha Energi AB", "invoice_number": "9911",
            "total_amount": 1250.0, "missing": [],
            "match_uncertain": True, "match_kind": "template",
            "match_candidates": ["Alpha Energi AB", "Beta Energi AB"],
            "status": "redo",
        })
        view._refresh_table()
        view._tbl.selectRow(0)
        # Användaren avbryter frågan → raden registreras INTE.
        monkeypatch.setattr(
            view, "_ask_user_for_match", lambda row: False
        )
        view._create_invoices()
        assert created == []
        assert len(view._rows) == 1
    finally:
        view.close()


def test_match_candidate_names_handles_dicts_and_dupes():
    from ui.scan_import_view import ScanImportView

    names = ScanImportView._match_candidate_names({
        "match_candidates": [
            {"name": "Alpha AB"}, "Beta AB", {"name": "alpha ab"},
            "", {"supplier": "Gamma AB"},
        ],
    })
    assert names == ["Alpha AB", "Beta AB", "Gamma AB"]


# ── Mushjul: stängd dropdown sväljer, öppen lista scrollar ────

class _Wheel:
    def type(self):
        from PySide6.QtCore import QEvent
        return QEvent.Type.Wheel


def test_closed_combo_swallows_wheel_open_popup_does_not(monkeypatch):
    _qapp()
    from PySide6.QtWidgets import QComboBox
    import ui.letter_jump as lj

    combo = QComboBox()
    combo.addItems(["Alpha", "Beta", "Gamma"])
    combo.setCurrentIndex(1)
    try:
        assert lj.handle_wheel(combo, _Wheel()) is True
        monkeypatch.setattr(lj, "_combo_popup_open", lambda c: True)
        assert lj.handle_wheel(combo, _Wheel()) is False
    finally:
        combo.close()
