# -*- coding: utf-8 -*-
"""
Tester: Import-tabellen byggs i omgångar.

Loggen från en riktig körning visade 1 216 parkerade original som
lades in på en gång: fönstret stod still i nästan tre minuter
(GUI_FREEZE). Inläsningen ska nu ske i små omgångar via
händelseslingan, så fönstret förblir svarande, och bara de nya
raderna ska ritas om.
"""
from __future__ import annotations

import os
import sys
import time
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

from ui import i18n  # noqa: E402


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
        self.created: list = []

    def get_suppliers(self):
        return [{"name": "Testbolaget AB"}]

    def get_invoices(self):
        return list(self.created)

    def add_invoice(self, data):
        self.created.append(dict(data))
        return data

    def get_setting(self, key, default=None):
        return default


class _Watch:
    folders: list = []

    def __init__(self, parked):
        self.parked = list(parked)
        self.last_scan_stats: dict = {}
        self.removed: list[str] = []

    def reprocess_parked(self, entry=None, background=False):
        return 0

    def remove_parked(self, digest):
        self.removed.append(str(digest))


TEXT = "Testbolaget AB\nFakturanummer: 921040\nAtt betala: 857,25"


def _parked(n: int) -> list[dict]:
    entries = []
    for index in range(n):
        entries.append({
            "hash": f"H{index}",
            "path": f"/tmp/x/parkerad-{index}.pdf",
            "file": f"parkerad-{index}.pdf",
            "reason": "uncertain-supplier",
            "text": TEXT,
            "method": "test",
            "parsed": {
                "supplier": "",
                "invoice_number": "921040",
                "total_amount": 857.25,
                "date": "2024-12-05",
                "due_date": "",
                "ocr": "",
                "missing": ["leverantör"],
                "match_uncertain": True,
                "match_candidates": ["Testbolaget AB"],
            },
        })
    return entries


def _view(tmp_path, parked):
    from ui.scan_import_view import ScanImportView

    view = ScanImportView(
        app=_Core(), templates_path=tmp_path / "invoice_templates.json"
    )
    view._templates_cache = {}
    view._watch = _Watch(parked)
    return view


def _pump(app, view=None, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if view is not None and view._pending_parked_inserts() == 0:
            # En sista runda så att sista omgångens uppritning hinner med.
            app.processEvents()
            return
        time.sleep(0.002)


def test_large_lot_is_loaded_in_batches_and_window_stays_responsive(
    tmp_path,
):
    app = _qapp()
    parked = _parked(120)
    view = _view(tmp_path, parked)
    try:
        started = time.perf_counter()
        returned = view._add_parked_rows_to_table(list(parked))
        first_call = time.perf_counter() - started

        # Anropet återvänder direkt med en kö — inget lass byggs i
        # GUI-tråden på en gång.
        assert returned == []
        assert view._pending_parked_inserts() > 0
        assert first_call < 2.0, f"anropet tog {first_call:.2f} s"
        assert view._rows == []

        _pump(app, view)

        assert view._pending_parked_inserts() == 0
        assert len(view._rows) == 120
        # Tabellen är byggd och stämmer med raderna.
        assert view._tbl.rowCount() == len(view._rows)
        assert "120" in view._lbl_sum.text()
    finally:
        view.close()


def test_batches_call_the_finish_callback_with_every_row(tmp_path):
    app = _qapp()
    parked = _parked(90)
    view = _view(tmp_path, parked)
    done: list[list[dict]] = []
    try:
        view._add_parked_rows_to_table(
            list(parked), on_done=lambda added: done.append(added)
        )
        assert done == []
        _pump(app, view)
        assert len(done) == 1
        assert len(done[0]) == 90
    finally:
        view.close()


def test_small_lot_is_still_immediate(tmp_path):
    _qapp()
    parked = _parked(3)
    view = _view(tmp_path, parked)
    try:
        added = view._add_parked_rows_to_table(list(parked))
        assert len(added) == 3
        assert view._rows == added
        assert view._tbl.rowCount() == 3
    finally:
        view.close()


def test_only_new_rows_are_painted_when_appending(tmp_path):
    _qapp()
    view = _view(tmp_path, [])
    try:
        view._rows = [{"file": "a.pdf", "status": "redo"}]
        view._refresh_table()
        painted: list[int] = []
        original = view._fill_table_row
        view._fill_table_row = (
            lambda r, row: (painted.append(r), original(r, row))[1]
        )
        view._rows.append({"file": "b.pdf", "status": "redo"})
        view._append_table_rows([view._rows[-1]])
        # Bara den nya raden ritades — inte de 1 216 befintliga.
        assert painted == [1]
    finally:
        view.close()


def test_parked_question_storm_is_capped(tmp_path, monkeypatch):
    _qapp()
    parked = _parked(30)
    view = _view(tmp_path, parked)
    asked: list[str] = []
    try:
        view._rows = [
            dict(entry["parsed"], file=entry["file"],
                 _path=entry["path"], _text=TEXT)
            for entry in parked
        ]
        monkeypatch.setattr(
            view, "_ask_user_for_match",
            lambda row: asked.append(row.get("file", "")) or False,
        )
        view._ask_uncertain_rows(view._rows)
        from ui.scan_import_view import PARKED_ASK_LIMIT

        assert len(asked) == PARKED_ASK_LIMIT
        # Resten ligger kvar i tabellen och antalet syns i statusraden.
        assert "22" in view._lbl_status.text()
    finally:
        view.close()
