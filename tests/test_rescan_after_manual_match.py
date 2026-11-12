# -*- coding: utf-8 -*-
"""
Tester: efter en manuell matchning prövas ALLT om.

Kravet: när användaren matchat en faktura manuellt ska appen direkt se
om resten nu kan matchas automatiskt — Import-raderna, de parkerade
originalen och filerna i de bevakade mapparna. Vid fel matchar
användaren manuellt igen; varje bekräftelse räknas och efter fem
manuella matchningar får appen koppla leverantören själv. Skanningen
ska ske i bakgrunden så fönstret aldrig låser sig.
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
        self.created: list[dict] = []

    def get_suppliers(self):
        return [{"name": "Testbolaget AB"}]

    def get_invoices(self):
        return list(self.created)

    def add_invoice(self, data):
        record = dict(data, id=f"fake-{len(self.created) + 1}")
        self.created.append(record)
        return record

    def get_setting(self, key, default=None):
        return default


class _Watch:
    """Bevakare som bara bokför vad som efterfrågas."""

    def __init__(self, parked=None):
        self.folders: list = []
        self.parked = list(parked or [])
        self.last_scan_stats: dict = {}
        self.removed: list[str] = []
        self.reprocess_calls: list[dict] = []

    def remove_parked(self, digest):
        self.removed.append(str(digest))
        self.parked = [
            entry for entry in self.parked
            if str(entry.get("hash", "")) != str(digest)
        ]

    def reprocess_parked(self, entry=None, background=False):
        self.reprocess_calls.append(
            {"entry": entry, "background": background}
        )
        return len(self.parked)


_TEXT = "Testbolaget AB\nFaktnr 921040\nSumma 857,25"


def _parsed(**extra):
    parsed = {
        "supplier": "",
        "invoice_number": "921040",
        "total_amount": 857.25,
        "date": "2024-12-05",
        "due_date": "",
        "ocr": "",
        "missing": ["leverantör"],
        "match_uncertain": True,
        "match_candidates": ["Testbolaget AB"],
    }
    parsed.update(extra)
    return parsed


def _parked(hash_="H1", path="/tmp/x/parkerad.pdf", **extra):
    entry = {
        "hash": hash_,
        "path": path,
        "file": Path(path).name,
        "reason": "uncertain-supplier",
        "text": _TEXT,
        "method": "test",
        "parsed": _parsed(),
    }
    entry.update(extra)
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


# ── Allt prövas om ─────────────────────────────────────────────────

def test_manual_match_rescans_rows_parked_files_and_folders(tmp_path):
    _qapp()
    watch = _Watch([_parked()])
    view = _view(tmp_path, watch)
    try:
        # En annan rad som redan ligger i Import.
        other = _parsed(file="annan.pdf")
        other["_path"] = ""
        other["_text"] = _TEXT
        view._rows = [other]

        note = view._rescan_everything_after_learning()

        # 1) Parkerade original tillbaka till Import (inte tysta)
        assert len(view._rows) == 2
        assert any(
            row.get("file") == "parkerad.pdf" for row in view._rows
        )
        # 2) Mapparna läses om i BAKGRUNDEN — aldrig blockerande
        assert watch.reprocess_calls == [
            {"entry": None, "background": True}
        ]
        # 3) Statusraden berättar vad som hände
        assert "prövas om" in note
        assert "parkerade original" in note
    finally:
        view.close()


def test_rescan_note_is_empty_when_nothing_to_recheck(tmp_path):
    _qapp()
    watch = _Watch([])
    view = _view(tmp_path, watch)
    try:
        note = view._rescan_everything_after_learning()
        assert note == ""
        # Även utan rader ska mapparna få en ny chans i bakgrunden
        assert watch.reprocess_calls == [
            {"entry": None, "background": True}
        ]
    finally:
        view.close()


def test_rescan_survives_a_watcher_without_reprocess(tmp_path):
    """En äldre/avskalad bevakare får inte krascha matchningen."""
    _qapp()

    class _Bare:
        folders: list = []
        parked: list = []

    view = _view(tmp_path, _Bare())
    try:
        assert view._rescan_everything_after_learning() == ""
    finally:
        view.close()


# ── Parkerade filer läses om utan att GUI:t väntar ─────────────────

def test_reprocess_parked_background_starts_async_scan(tmp_path):
    from ui.watch_folders import WatchManager

    manager = WatchManager(tmp_path / "watch.json", app=None)
    manager._config["parked"] = [_parked()]
    started: list[bool] = []
    scanned: list[bool] = []

    manager.start_scan = lambda force=False: started.append(bool(force))
    manager.scan_all = lambda force=False: scanned.append(True)
    manager.scan_folder = lambda entry, force=False: scanned.append(True)

    released = manager.reprocess_parked(background=True)

    assert released == 1
    assert started == [False]
    assert scanned == []           # inget blockerande i GUI-tråden
    assert manager.parked == []    # posten släpps för omläsning


def test_reprocess_parked_without_background_still_scans_inline(tmp_path):
    from ui.watch_folders import WatchManager

    manager = WatchManager(tmp_path / "watch.json", app=None)
    manager._config["parked"] = [_parked()]
    scanned: list[bool] = []
    manager.scan_all = lambda force=False: scanned.append(True)
    manager.start_scan = lambda force=False: pytest.fail("fel läge")

    assert manager.reprocess_parked() == 1
    assert scanned == [True]


# ── Fem egna matchningar innan appen kopplar själv ─────────────────

def test_manual_matches_count_until_automatic_linking(tmp_path):
    import scan_import as si

    learning: dict = {}
    text = "Testbolaget AB\nOrg.nr: 556677-8899\nFaktura 921040\n857,25"
    for n in range(1, si.LEARNED_SUPPLIER_CONFIRMATIONS + 1):
        si.record_match_confirmation(
            learning, "Testbolaget AB", text=text,
            confirmation_id=f"invoice-{n}",
        )
    assert learning["Testbolaget AB"]["confirmed"] == 5
    assert si.learned_supplier_candidates(text, learning) == [
        "Testbolaget AB"
    ]

    # Samma faktura bekräftad igen räknas inte dubbelt (fusk-skydd)
    si.record_match_confirmation(
        learning, "Testbolaget AB", text=text,
        confirmation_id="invoice-1",
    )
    assert learning["Testbolaget AB"]["confirmed"] == 5


def test_status_says_how_many_manual_matches_remain(tmp_path):
    _qapp()
    view = _view(tmp_path, _Watch([]))
    try:
        row = _parsed(file="a.pdf")
        row["_path"] = ""
        row["_text"] = _TEXT
        view._rows = [row]
        view._match_learning_cache = {}
        note = view._apply_manual_match(row, "Testbolaget AB")
        assert "egna matchningar (mallar) kvar" in note
        assert "Testbolaget AB" in note
    finally:
        view.close()


def test_other_rows_are_auto_matched_after_five_manual_confirmations(
    tmp_path,
):
    """Efter fem egna matchningar matchas de andra raderna automatiskt."""
    import scan_import as si

    _qapp()
    text = (
        "Testbolaget AB\n"
        "Org.nr: 556677-8899\n"
        "Fakturanummer: 921040\n"
        "Fakturadatum: 2024-12-05\n"
        "Att betala: 857,25\n"
    )
    learning: dict = {}
    for n in range(si.LEARNED_SUPPLIER_CONFIRMATIONS):
        si.record_match_confirmation(
            learning, "Testbolaget AB", text=text,
            confirmation_id=f"tidigare-{n}",
        )
    assert si.learned_supplier_candidates(text, learning) == [
        "Testbolaget AB"
    ]

    watch = _Watch([])
    view = _view(tmp_path, watch)
    try:
        view._learning_cache = learning
        row = {
            "file": "annan.pdf",
            "supplier": "",
            "invoice_number": "",
            "total_amount": 0.0,
            "date": "",
            "due_date": "",
            "ocr": "",
            "missing": ["belopp", "fakturanummer", "leverantör"],
            "match_uncertain": True,
            "match_candidates": ["Testbolaget AB"],
            "_path": "",
            "_text": text,
        }
        view._rows = [row]

        # Registreringen i sig (dialoger, sparfiler) testas på annat
        # håll — här räcker det att raden blev komplett och säker och
        # skickades vidare automatiskt.
        ready: list[dict] = []
        view._auto_register_matched_rows = (
            lambda rows, **_kw: ready.extend(rows) or len(rows)
        )

        view._rescan_everything_after_learning()

        assert ready, "raden skulle gått vidare automatiskt"
        matched = ready[0]
        assert matched["supplier"] == "Testbolaget AB"
        assert matched["invoice_number"] == "921040"
        assert not matched.get("match_uncertain")
    finally:
        view.close()


def test_menu_can_recheck_everything_on_demand(tmp_path, monkeypatch):
    _qapp()
    import ui.scan_import_view as siv

    menu_calls: list[str] = []

    class _Menu:
        def __init__(self, *_a, **_k):
            pass

        def addAction(self, text, *_a):
            menu_calls.append(str(text))

        def addSeparator(self):
            menu_calls.append("---")

        def exec(self, *_a):
            menu_calls.append("exec")

    monkeypatch.setattr(siv, "QMenu", _Menu)
    watch = _Watch([_parked()])
    view = _view(tmp_path, watch)
    try:
        view._table_context_menu(view._tbl.rect().center())
        action = i18n.tr("scan.rescan_all_action")
        assert action in menu_calls
        assert menu_calls[-1] == "exec"

        view._rescan_all_now()
        assert watch.reprocess_calls[-1] == {
            "entry": None, "background": True
        }
    finally:
        view.close()
