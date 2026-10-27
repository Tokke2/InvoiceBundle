# -*- coding: utf-8 -*-
"""
Tester: radfärger för matchningssäkerhet i Import-tabellen.

Användarens krav (2026-10-27): vid OSÄKRA matchningar ska raden
vara RÖD, vid SÄKRA matchningar ska raden vara GRÖN. Hela raden
färgas. Rader utan någon matchning alls (okänt format) lämnas
neutrala — de får mall-dialogen i stället, ingen färg gissas.
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


def _fake_core():
    class FakeCore:
        def get_suppliers(self):
            return []

        def get_setting(self, key, default=None):
            return default

    return FakeCore()


def _row(**kw):
    row = {
        "file": "f.pdf", "supplier": "", "invoice_number": "1",
        "date": "", "due_date": "", "ocr": "", "total_amount": 100.0,
        "method": "pdf", "status": "redo", "missing": [], "_path": "",
    }
    row.update(kw)
    return row


def _bg_names(view, r):
    from ui.scan_import_view import COLUMNS
    return [
        view._tbl.item(r, c).background().color().name()
        for c in range(len(COLUMNS))
    ]


# ── Tillståndslogiken ───────────────────────────────────────────────

def test_match_state_classification():
    _qapp()
    from ui.scan_import_view import ScanImportView

    state = ScanImportView._row_match_state
    # Osäker vinner alltid — även om ett leverantörsnamn råkar stå
    # på raden får den aldrig se säker (grön) ut.
    assert state({"match_uncertain": True, "supplier": "Alpha AB"}) \
        == "uncertain"
    assert state({"match_uncertain": True}) == "uncertain"
    assert state({"supplier": "Alpha AB"}) == "secure"
    assert state({"template": "Alpha AB"}) == "secure"
    assert state({"supplier": "  ", "template": ""}) == ""
    assert state({}) == ""
    assert state(None) == ""


# ── Radfärgerna i tabellen ──────────────────────────────────────────

def test_uncertain_row_red_secure_row_green(tmp_path):
    _qapp()
    from PySide6.QtCore import Qt
    from ui.scan_import_view import (
        ROW_BG_MATCH_SECURE,
        ROW_BG_MATCH_UNCERTAIN,
        ScanImportView,
    )

    view = ScanImportView(
        app=_fake_core(),
        templates_path=tmp_path / "invoice_templates.json",
    )
    try:
        assert view._dark is True  # standardtema i testerna
        view._rows = [
            _row(file="osaker.pdf", match_uncertain=True,
                 match_kind="supplier"),
            _row(file="saker.pdf", supplier="Alpha AB"),
            _row(file="mall.pdf", template="Alpha AB",
                 supplier="Alpha AB"),
            _row(file="okand.pdf", status="saknas: leverantör",
                 missing=["leverantör"]),
        ]
        view._refresh_table()

        red = ROW_BG_MATCH_UNCERTAIN[0]
        green = ROW_BG_MATCH_SECURE[0]
        # HELA den osäkra raden är röd, hela de säkra gröna.
        assert set(_bg_names(view, 0)) == {red}
        assert set(_bg_names(view, 1)) == {green}
        assert set(_bg_names(view, 2)) == {green}
        # Ingen träff alls → neutral, ingen bakgrundsfärg.
        for name in _bg_names(view, 3):
            assert name not in (red, green)
        item = view._tbl.item(3, 0)
        assert item.background().style() == Qt.BrushStyle.NoBrush
        # Förklarande tooltip på färgade rader.
        assert view._tbl.item(0, 0).toolTip()
        assert view._tbl.item(1, 0).toolTip()
    finally:
        view.close()


def test_row_turns_green_once_user_resolves(tmp_path):
    """Röd rad blir grön när användaren valt leverantör/mall —
    färgen följer radens aktuella matchningssäkerhet."""
    _qapp()
    from ui.scan_import_view import (
        ROW_BG_MATCH_SECURE,
        ROW_BG_MATCH_UNCERTAIN,
        ScanImportView,
    )

    view = ScanImportView(
        app=_fake_core(),
        templates_path=tmp_path / "invoice_templates.json",
    )
    try:
        row = _row(match_uncertain=True, match_kind="supplier")
        view._rows = [row]
        view._refresh_table()
        assert _bg_names(view, 0)[0] == ROW_BG_MATCH_UNCERTAIN[0]

        # Användaren väljer i frågedialogen → osäkerheten släpps
        # och leverantören sätts (samma fält som dialogen rör).
        row["supplier"] = "Alpha AB"
        row["match_uncertain"] = False
        view._refresh_table()
        assert set(_bg_names(view, 0)) == {ROW_BG_MATCH_SECURE[0]}
    finally:
        view.close()


def test_row_colors_follow_light_theme(tmp_path):
    _qapp()
    from ui.scan_import_view import (
        ROW_BG_MATCH_SECURE,
        ROW_BG_MATCH_UNCERTAIN,
        ScanImportView,
    )

    view = ScanImportView(
        app=_fake_core(),
        templates_path=tmp_path / "invoice_templates.json",
    )
    try:
        view._rows = [
            _row(match_uncertain=True),
            _row(supplier="Alpha AB"),
        ]
        view._refresh_table()
        view.apply_theme({"bg": "#ffffff"})
        assert view._dark is False
        assert _bg_names(view, 0)[0] == ROW_BG_MATCH_UNCERTAIN[1]
        assert _bg_names(view, 1)[0] == ROW_BG_MATCH_SECURE[1]
        view.apply_theme({"bg": "#0d1117"})
        assert _bg_names(view, 0)[0] == ROW_BG_MATCH_UNCERTAIN[0]
        assert _bg_names(view, 1)[0] == ROW_BG_MATCH_SECURE[0]
    finally:
        view.close()
