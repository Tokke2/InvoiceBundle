# -*- coding: utf-8 -*-
"""Regression tests: no silent watch skips, safer matching, non-blocking scans, progress bars."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "ui"), str(PROJECT_DIR / "plugins")):
    if _d not in sys.path:
        sys.path.insert(0, _d)


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _fake_core(suppliers=None, invoices=None):
    suppliers = list(suppliers or [])
    invoices = list(invoices or [])

    class FakeCore:
        def get_suppliers(self):
            return list(suppliers)

        def get_invoices(self):
            return list(invoices)

        def add_invoice(self, data):
            rec = dict(data, id=f"inv-{len(invoices) + 1}")
            invoices.append(rec)
            return rec

        def get_setting(self, key, default=None):
            return default

    return FakeCore()


# ── 1. Bevakade mappar skippas inte ──────────────────────────────────────

def test_heal_recovers_legacy_unverified_duplicate_and_missing_import(tmp_path):
    _qapp()
    from ui.watch_folders import WatchManager, file_hash

    folder = tmp_path / "In"
    folder.mkdir()
    missing_imp = folder / "lost_import.pdf"
    missing_imp.write_bytes(b"%PDF-lost-import")
    false_dup = folder / "false_dup.pdf"
    false_dup.write_bytes(b"%PDF-false-dup")
    real_dup = folder / "real_dup.pdf"
    real_dup.write_bytes(b"%PDF-real-dup")

    h_lost = file_hash(missing_imp)
    h_false = file_hash(false_dup)
    h_real = file_hash(real_dup)

    cfg_path = tmp_path / "watch.json"
    cfg_path.write_text(json.dumps({
        "folders": [{"supplier": "Testbolaget AB", "path": str(folder)}],
        "auto_create": True,
        "processed": {
            h_lost: {"path": str(missing_imp), "file": missing_imp.name, "result": "imported", "invoice_number": "101"},
            h_false: {"path": str(false_dup), "file": false_dup.name, "result": "duplicate-invoice"},
            h_real: {"path": str(real_dup), "file": real_dup.name, "result": "duplicate-invoice", "verified_duplicate": True},
        },
        "parked": [],
    }), encoding="utf-8")

    core = _fake_core(
        suppliers=[{"name": "Testbolaget AB"}],
        invoices=[],
    )
    mgr = WatchManager(cfg_path, app=core)
    mgr._heal_missing_imports()

    proc = mgr.processed
    assert h_lost not in proc
    assert h_false not in proc
    assert h_real in proc


def test_reprocess_parked_only_stale_context_skips_unchanged_no_template_and_retries_others(tmp_path, monkeypatch):
    _qapp()
    from ui.watch_folders import WatchManager

    folder = tmp_path / "In"
    folder.mkdir()
    holder = {"templates": {}, "suppliers": [{"name": "Alpha AB"}]}
    core = _fake_core(suppliers=holder["suppliers"])
    core.get_suppliers = lambda: list(holder["suppliers"])
    mgr = WatchManager(
        tmp_path / "watch.json",
        app=core,
        extract_fn=lambda _p: ("Fakturanr: 99\nAtt betala: 100,00", "test"),
        templates_provider=lambda: holder["templates"],
    )
    mgr.set_folders([{"supplier": "Alpha AB", "path": str(folder)}])
    fp = mgr._context_fingerprint()

    f_nt = folder / "no_tpl.pdf"
    f_miss = folder / "missing.pdf"
    f_dup = folder / "dup.pdf"
    for f in (f_nt, f_miss, f_dup):
        f.write_bytes(b"%PDF-" + f.name.encode())

    mgr._config["parked"] = [
        {"hash": "h1", "path": str(f_nt), "file": f_nt.name, "reason": "no-template", "context_fp": fp, "parsed": {}},
        {"hash": "h2", "path": str(f_miss), "file": f_miss.name, "reason": "missing: belopp", "context_fp": fp, "parsed": {}},
        {"hash": "h3", "path": str(f_dup), "file": f_dup.name, "reason": "possible-duplicate: faktura 1", "context_fp": fp, "parsed": {}},
    ]
    mgr._save()

    monkeypatch.setattr(mgr, "start_scan", lambda force=False: None)
    retried = mgr.reprocess_parked(background=True, only_stale_context=True)
    # Missing & possible-duplicate are retried even with unchanged context; unchanged no-template stays put.
    assert retried == 2
    assert [p["file"] for p in mgr.parked] == ["no_tpl.pdf"]

    # As soon as templates/suppliers change, no-template has stale context_fp and IS retried!
    holder["templates"] = {"Alpha AB": {"fields": {"invoice_number": {"label": "Fakturanr"}, "total_amount": {"label": "Att betala"}}}}
    retried_after = mgr.reprocess_parked(background=True, only_stale_context=True)
    assert retried_after == 1
    assert mgr.parked == []


def test_review_parked_large_batch_preserves_possible_duplicates_and_loads_all_rows(tmp_path, monkeypatch):
    _qapp()
    import ui.scan_import_view as sv
    from ui.scan_import_view import PARKED_INSERT_CHUNK, ScanImportView

    monkeypatch.setattr(sv.QTimer, "singleShot", lambda _ms, fn: fn())

    core = _fake_core(suppliers=[{"name": "Alpha AB"}])
    view = ScanImportView(app=core, templates_path=tmp_path / "templates.json")
    try:
        total = PARKED_INSERT_CHUNK + 7
        parked = []
        for idx in range(total):
            reason = "possible-duplicate: faktura 1" if idx == 0 else "missing: belopp"
            parked.append({
                "hash": f"hash-{idx}",
                "path": str(tmp_path / f"f{idx}.pdf"),
                "file": f"f{idx}.pdf",
                "reason": reason,
                "text": "Alpha AB\nAtt betala 100,00",
                "method": "test",
                "parsed": {
                    "supplier": "Alpha AB",
                    "invoice_number": f"INV-{idx}",
                    "total_amount": 100.0 if idx == 0 else 0.0,
                    "missing": [] if idx == 0 else ["belopp"],
                },
            })
        view._watch._config["parked"] = parked
        view._ask_uncertain_rows = lambda _rows: 0
        view._offer_template_repairs = lambda _rows: None

        view._review_parked()
        assert len(view._rows) == total
        dup_row = next(r for r in view._rows if r.get("file") == "f0.pdf")
        assert dup_row.get("_possible_duplicate") == "possible-duplicate: faktura 1"
        assert sv.ScanImportView._display_status(dup_row).find("dubblett") >= 0
        assert any(p.get("hash") == "hash-0" for p in view._watch.parked)
    finally:
        view.close()


# ── 2. Säkrare matchning ─────────────────────────────────────────────────

def test_safer_supplier_matching_blocks_short_tokens_and_org_conflicts():
    import scan_import as si

    suppliers = [
        {"name": "Nord", "org_number": "556111-1111"},
        {"name": "Stor Leverantör AB", "org_number": "556222-2222"},
    ]
    # 4-char single token "Nord" must never auto-match on bare word alone
    weak_short = si.assess_supplier_match(
        "Faktura till kund\nNord gatan 12\nAtt betala: 500,00", suppliers
    )
    assert weak_short["supplier"] == ""

    # 5+ char unique name matches if no conflicting org.nr or competitor
    clear_text = "Stor Leverantör AB\nOrg.nr 556222-2222\nAtt betala: 500,00"
    ok_res = si.assess_supplier_match(clear_text, suppliers)
    assert ok_res["status"] == "matched" and ok_res["supplier"] == "Stor Leverantör AB"

    # Conflicting valid Swedish org number blocks weak name match -> identifier_conflict
    alf_suppliers = [{"name": "Alfakom", "org_number": "556703-7485"}]
    conflict_res = si.assess_supplier_match(
        "Alfakom division\nOrg.nr 556016-0680\nAtt betala: 500,00",
        alf_suppliers,
    )
    assert conflict_res["uncertain"] is True
    assert conflict_res["reason"] == "identifier_conflict"


def test_parse_watched_file_flags_identifier_conflict_instead_of_forcing_folder():
    import scan_import as si
    from ui.watch_folders import parse_watched_file

    suppliers = [{"name": "Alpha AB", "org_number": "556123-4567"}]
    # Invoice prints a completely different valid org number (556987-6543 -> Luhn check: 556000-0001? let's compute real valid Swedish org.nr)
    # Valid Luhn 10 digits: 5560000018 -> 5+5*2=10->1,6,0,0,0,0,0,0*2=0,1*2=2 -> wait use existing valid number 556703-7485 (Spotify) vs 556016-0680 (Volvo)
    suppliers = [{"name": "Alpha AB", "org_number": "556703-7485"}]
    text = "Fakturanr: A-55\nOrg.nr 556016-0680\nAtt betala: 900,00"
    _t, _m, parsed = parse_watched_file(
        si,
        Path("faktura.pdf"),
        "Alpha AB",
        suppliers,
        templates={},
        learning={},
        extract_fn=lambda _p: (text, "test"),
    )
    assert parsed["supplier"] == ""
    assert parsed["match_uncertain"] is True
    assert parsed["match_reason"] == "identifier_conflict"
    assert "Alpha AB" in parsed["match_candidates"]
    assert "leverantör" in parsed["missing"]


def test_apply_template_to_row_uses_select_supplier_template_and_flags_ambiguity(tmp_path):
    _qapp()
    from ui.scan_import_view import ScanImportView

    templates = {
        "Alpha AB": {
            "variants": [
                {"fields": {"invoice_number": {"label": "Faktnr"}, "total_amount": {"label": "Summa"}}},
                {"fields": {"invoice_number": {"label": "Refnr"}, "total_amount": {"label": "Total"}}},
            ]
        }
    }
    view = ScanImportView(app=_fake_core(suppliers=[{"name": "Alpha AB"}]), templates_path=tmp_path / "tpl.json")
    view._templates_cache = templates
    try:
        # Unambiguous match via single matching variant
        row = {"supplier": "Alpha AB", "invoice_number": "", "total_amount": 0.0, "missing": ["fakturanummer", "belopp"]}
        view._apply_template_to_row(row, "Alpha AB\nFaktnr: 777\nSumma: 1 500,00")
        assert row["invoice_number"] == "777"
        assert float(row["total_amount"]) == 1500.0
        assert not row.get("match_uncertain")

        # Disagreeing variants -> template_ambiguous (never silent guess)
        amb = {"supplier": "Alpha AB", "invoice_number": "", "total_amount": 0.0, "missing": ["fakturanummer", "belopp"]}
        view._apply_template_to_row(amb, "Faktnr: 777\nSumma: 1 500,00\nRefnr: 888\nTotal: 2 000,00")
        assert amb["match_uncertain"] is True
        assert amb["match_reason"] == "template_ambiguous"
    finally:
        view.close()


# ── 3 & 4. Låsningsfri körning + Progress bar ───────────────────────────

def test_watch_background_scan_emits_progress_updates_view_and_isolates_slow_file(tmp_path):
    app = _qapp()
    from ui.scan_import_view import ScanImportView
    from ui.watch_folders import WatchManager

    folder = tmp_path / "In"
    sub = folder / "2026"
    sub.mkdir(parents=True)
    f1 = folder / "ok1.pdf"
    f2 = sub / "ok2.pdf"
    f1.write_bytes(b"%PDF-1")
    f2.write_bytes(b"%PDF-2")

    core = _fake_core(suppliers=[{"name": "Alpha AB"}])
    view = ScanImportView(app=core, templates_path=tmp_path / "tpl.json")
    mgr: WatchManager = view._watch
    mgr._extract_fn = lambda p: (f"Alpha AB\nFakturanr: {p.stem}\nAtt betala: 100,00", "test")

    progress_events: list[tuple[int, int, str]] = []
    finished_events: list[dict] = []
    mgr.scan_progress.connect(lambda d, t, n: progress_events.append((d, t, n)))
    mgr.scan_finished.connect(finished_events.append)

    try:
        mgr.set_folders([{"supplier": "Alpha AB", "path": str(folder)}])
        deadline = time.monotonic() + 5.0
        while not finished_events and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)

        assert finished_events, "Background watch scan did not complete"
        # Discovery emits (0, 0, ""), scanning emits (done, total, name) up to (2, 2, ...)
        assert (0, 0, "") in progress_events
        assert any(total == 2 and done == 2 for done, total, _n in progress_events)
        assert not view._watch_progress.isVisible()

        # Verify watchdog timeout isolates only the stuck file instead of killing scan
        mgr._scan_running = True
        mgr._scan_current_file = "stuck.pdf"
        mgr._scan_generator = (x for x in ())  # exhaustible dummy generator
        mgr._on_scan_watchdog()
        assert mgr._scan_pending_token == 0
    finally:
        mgr._abort_async_scan()
        view.close()


def test_manual_scan_files_runs_in_background_shows_progress_and_supports_cancel(tmp_path, monkeypatch):
    _qapp()
    import scan_import as si
    import ui.scan_import_view as sv
    from ui.scan_import_view import ScanImportView

    files = []
    for i in range(4):
        p = tmp_path / f"inv{i}.pdf"
        p.write_bytes(b"%PDF-" + str(i).encode())
        files.append(p)

    core = _fake_core(suppliers=[{"name": "Alpha AB"}])
    view = ScanImportView(app=core, templates_path=tmp_path / "tpl.json")
    seen_progress_ranges: list[tuple[int, int]] = []
    monkeypatch.setattr(si, "page_image_count", lambda _p: 1)

    def _extract(path):
        # Record progress visibility while worker executes
        seen_progress_ranges.append((view._scan_progress.minimum(), view._scan_progress.maximum()))
        if path.name == "inv1.pdf":
            view._cancel_scan_files()
        return f"Alpha AB\nFakturanr: {path.stem}\nAtt betala: 100,00", "test"

    monkeypatch.setattr(si, "extract_text", _extract)
    view._ask_uncertain_rows = lambda _rows: 0
    opened_unmatched = []
    view._open_template_for_unmatched = lambda rows: opened_unmatched.append(rows)

    try:
        view._txt_paths.setPlainText("\n".join(str(p) for p in files))
        view._scan_files()

        assert seen_progress_ranges and seen_progress_ranges[0] == (0, 4)
        # Cancelled after 2nd file -> did not parse all 4 and did not nag unmatched template dialog
        assert len(view._rows) == 2
        assert opened_unmatched == []
        assert not view._scan_progress.isVisible()
        assert not view._btn_cancel_scan.isVisible()
        assert sv.tr("scan.cancelled", done=2, total=4) in view._lbl_status.text()
    finally:
        view.close()


def test_display_status_does_not_mutate_row_dict_and_new_i18n_keys_exist():
    from ui import i18n
    from ui.scan_import_view import ScanImportView

    row = {
        "file": "f.pdf", "supplier": "Alpha AB", "invoice_number": "1",
        "date": "2026-01-01", "due_date": "", "ocr": "",
        "total_amount": 100.0, "status": "redo", "missing": [], "_path": "",
    }
    before = dict(row)
    _ = ScanImportView._display_status(row)
    assert row == before

    for lang in ("sv", "en"):
        i18n.set_language(lang)
        for key in (
            "scan.match_reason_identifier_conflict",
            "scan.possible_dup_status",
            "scan.progress_files",
            "scan.progress_reread",
            "scan.cancel",
            "scan.cancelled",
            "watch.progress_discovering",
            "watch.progress_scanning",
        ):
            assert i18n.tr(key, done=1, total=2, pct=50, file="a.pdf") != key
    i18n.set_language("sv")
