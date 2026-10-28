# -*- coding: utf-8 -*-
"""
Tester: alla OSÄKRA fakturor i Import-tabellen + logotypval.

Användarens krav (2026-10-28): fakturor som är osäkra ska
läggas direkt i Import-tabellen (inte bara ligga i bevakningens
parkering), och man ska kunna välja leverantör via logotyp —
klickbara logotyp-rutor (monogram-märken) i matchningsdialogen.
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


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class _Core:
    def get_suppliers(self):
        return [{"name": "Testbolaget AB"}, {"name": "Annan AB"}]

    def get_setting(self, key, default=None):
        return default


_TEXT = "Testbolaget AB\nFaktnr 921040\nSumma 857,25"


def _parsed(**kw):
    parsed = {
        "supplier": "", "invoice_number": "921040",
        "total_amount": 857.25, "date": "2024-12-05",
        "due_date": "", "ocr": "", "missing": ["leverantör"],
        "match_uncertain": True, "match_kind": "multipage",
        "match_reason": "multipage",
        "match_candidates": ["Testbolaget AB"], "pages": 3,
    }
    parsed.update(kw)
    return parsed


class _FakeWatch:
    def __init__(self, parked):
        self.folders: list = []
        self.parked = list(parked)
        self.removed: list[str] = []

    def remove_parked(self, digest):
        self.removed.append(str(digest))
        self.parked = [
            p for p in self.parked
            if str(p.get("hash", "")) != str(digest)
        ]


def _parked_entry(**kw):
    entry = {
        "hash": "H1", "path": "/tmp/x/osaker.pdf",
        "file": "osaker.pdf", "reason": "uncertain-supplier",
        "text": _TEXT, "method": "test", "parsed": _parsed(),
    }
    entry.update(kw)
    return entry


def _view(tmp_path, watch=None):
    from ui.scan_import_view import ScanImportView

    view = ScanImportView(
        app=_Core(), templates_path=tmp_path / "invoice_templates.json"
    )
    view._templates_cache = {}
    if watch is not None:
        view._watch = watch
    return view


# ── Osäkra parkerade hamnar i tabellen ──────────────────────

def test_uncertain_parked_goes_to_table_and_unparks_on_match(
    tmp_path, monkeypatch
):
    _qapp()
    import ui.scan_import_view as siv

    monkeypatch.setattr(
        siv.QMessageBox, "warning", lambda *_a, **_k: None
    )
    watch = _FakeWatch([_parked_entry()])
    view = _view(tmp_path, watch)
    try:
        from PySide6.QtCore import QTimer

        # Frågan öppnas av _show_parked_dialog — välj
        # Testbolaget i dropdownen programmatiskt.
        def _choose():
            from PySide6.QtWidgets import (
                QApplication, QComboBox, QDialog,
            )
            dlg = QApplication.activeModalWidget()
            assert isinstance(dlg, QDialog)
            combo = dlg.findChild(QComboBox)
            idx = combo.findText("Testbolaget AB")
            assert idx >= 0
            combo.setCurrentIndex(idx)
            dlg.accept()

        QTimer.singleShot(60, _choose)
        view._parked_notify = [{
            "file": "osaker.pdf", "path": "/tmp/x/osaker.pdf",
            "hash": "H1", "reason": "uncertain-supplier",
        }]
        view._show_parked_dialog()
        assert len(view._rows) == 1
        row = view._rows[0]
        assert row["supplier"] == "Testbolaget AB"
        assert row["_parked_hash"] == "H1"
        # Bekräftad i tabellen = borta ur parkeringen.
        assert watch.removed == ["H1"]
        assert watch.parked == []
    finally:
        view.close()


def test_cancelled_question_keeps_row_in_table_and_parked(tmp_path, monkeypatch):
    _qapp()
    import ui.scan_import_view as siv

    monkeypatch.setattr(
        siv.QMessageBox, "warning", lambda *_a, **_k: None
    )
    watch = _FakeWatch([_parked_entry()])
    view = _view(tmp_path, watch)
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QDialog

        def _cancel():
            dlg = QApplication.activeModalWidget()
            assert isinstance(dlg, QDialog)
            dlg.reject()

        QTimer.singleShot(60, _cancel)
        view._parked_notify = [{
            "file": "osaker.pdf", "path": "/tmp/x/osaker.pdf",
            "hash": "H1", "reason": "uncertain-supplier",
        }]
        view._show_parked_dialog()
        # Raden ligger kvar i tabellen i sikte (röd/osäker) och
        # parkeringen har kvar posten — inget försvinner tyst.
        assert len(view._rows) == 1
        assert view._rows[0].get("match_uncertain")
        assert watch.removed == []
        assert len(watch.parked) == 1
    finally:
        view.close()


def test_uncertain_rows_never_duplicated(tmp_path):
    _qapp()
    watch = _FakeWatch([_parked_entry()])
    view = _view(tmp_path, watch)
    try:
        infos = [{
            "file": "osaker.pdf", "path": "/tmp/x/osaker.pdf",
            "hash": "H1", "reason": "uncertain-supplier",
        }]
        added = view._add_parked_rows_to_table(infos)
        assert len(added) == 1
        assert view._add_parked_rows_to_table(infos) == []
        assert len(view._rows) == 1
        # Granska-knappen får inte heller lägga in den igen.
        view._review_parked()
        assert len(view._rows) == 1
    finally:
        view.close()


def test_non_uncertain_parked_not_forced_into_table(tmp_path):
    """Bara OSÄKRA läggs in automatiskt — okänt format (ingen
    matchning alls) hanteras av mallvägen som förut."""
    _qapp()
    entry = _parked_entry(
        hash="H2", path="/tmp/x/okand.pdf", file="okand.pdf",
        reason="no-template",
        parsed=_parsed(match_uncertain=False, match_kind="",
                       match_reason="", match_candidates=[]),
    )
    watch = _FakeWatch([entry])
    view = _view(tmp_path, watch)
    try:
        assert view._add_parked_rows_to_table([entry]) == []
        assert view._rows == []
    finally:
        view.close()


def test_collect_uncertain_parked_at_start(tmp_path):
    """Osäkra parkeringar från tidigare körningar läggs i
    tabellen direkt — utan dialog."""
    _qapp()
    watch = _FakeWatch([_parked_entry()])
    view = _view(tmp_path, watch)
    try:
        view._collect_uncertain_parked()
        assert len(view._rows) == 1
        assert view._rows[0].get("match_uncertain")
    finally:
        view.close()


def test_remove_row_also_unparks(tmp_path):
    _qapp()
    watch = _FakeWatch([_parked_entry()])
    view = _view(tmp_path, watch)
    try:
        view._add_parked_rows_to_table([watch.parked[0]])
        view._refresh_table()
        view._tbl.selectRow(0)
        view._remove_row()
        assert view._rows == []
        assert watch.removed == ["H1"]
    finally:
        view.close()


def test_created_invoice_also_unparks(tmp_path, monkeypatch):
    _qapp()
    import ui.scan_import_view as siv

    monkeypatch.setattr(
        siv.QMessageBox, "information", lambda *_a, **_k: None
    )
    watch = _FakeWatch([_parked_entry()])
    view = _view(tmp_path, watch)
    try:
        row = _parsed(
            supplier="Testbolaget AB", missing=[],
            _parked_hash="H1", file="osaker.pdf",
            _path="/tmp/x/osaker.pdf", _text=_TEXT,
            status="redo",
        )
        row.pop("match_uncertain")
        view._rows = [row]
        view._refresh_table()
        view._tbl.selectRow(0)
        saved: list = []
        monkeypatch.setattr(
            view, "_save_invoice",
            lambda data, source="": saved.append(data) or True,
        )
        view._create_invoices()
        assert len(saved) == 1
        assert view._rows == []
        assert watch.removed == ["H1"]
    finally:
        view.close()


# ── Logotypvalet ────────────────────────────────────────────

def test_supplier_monograms():
    from ui.scan_import_view import _supplier_monogram

    assert _supplier_monogram("Martin G Anderson") == "MG"
    assert _supplier_monogram("Pilkington") == "P"
    assert _supplier_monogram("Testbolaget AB") == "TA"
    assert _supplier_monogram("") == "?"


def test_choose_supplier_by_clicking_logo_tile(tmp_path):
    """Matchningsdialogen: klick på leverantörens logotyp-ruta
    väljer den (dropdownen följer med) och valet tillämpas."""
    _qapp()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import (
        QApplication, QComboBox, QDialog, QPushButton,
    )

    view = _view(tmp_path)
    try:
        row = {
            "file": "f.pdf", "supplier": "",
            "invoice_number": "921040", "total_amount": 857.25,
            "date": "", "due_date": "", "ocr": "",
            "method": "pdf", "status": "saknas: leverantör",
            "missing": ["leverantör"], "_path": "", "pages": 1,
            "_text": _TEXT,
        }
        view._rows = [row]
        view._refresh_table()
        view._tbl.selectRow(0)

        def _act():
            dlg = QApplication.activeModalWidget()
            assert isinstance(dlg, QDialog)
            tiles = [
                b for b in dlg.findChildren(QPushButton)
                if b.toolTip() == "Testbolaget AB"
            ]
            assert tiles, "ingen logotyp-ruta för Testbolaget AB"
            tiles[0].click()
            combo = dlg.findChild(QComboBox)
            assert combo.currentText() == "Testbolaget AB"
            dlg.accept()

        QTimer.singleShot(60, _act)
        view._manual_match_row()
        assert row["supplier"] == "Testbolaget AB"
    finally:
        view.close()
