# -*- coding: utf-8 -*-
"""
Tester: max 10 fakturarader per exportfil + original vid export.

Reglerna (önskade uttryckligen):
  * Varje faktura är en egen rad i betal-PDF:en.
  * EN exportfil får innehålla högst 10 fakturor — fler delas
    i flera filer (…-del1avN.pdf, …-del2avN.pdf, …), både vid
    manuell export och i autoexportens batcher.
  * Originalfakturorna bifogas ALLTID i PDF:en (går inte stänga av).
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


def _row(i, supplier="Pilkington", due=None, amount=100.0):
    return {
        "id": str(i), "supplier": supplier,
        "invoice_number": f"F-{i:03d}", "ocr": "12345",
        "date": "2026-09-01",
        "due_date": due or f"2026-09-{(i % 27) + 1:02d}",
        "total_amount": amount, "status": "Obetald",
        "attachment": "",
    }


# ── Chunk-hjälparen ─────────────────────────────────────────────

def test_chunk_rows_caps_at_ten_and_keeps_suppliers_together():
    from ui.invoices_helpers import chunk_export_rows

    rows = ([_row(i, "Pilkington") for i in range(14)]
            + [_row(100 + i, "Direktglas") for i in range(9)])
    chunks = chunk_export_rows(list(reversed(rows)))
    assert [len(c) for c in chunks] == [10, 10, 3]
    flat = [r["id"] for c in chunks for r in c]
    assert sorted(flat, key=int) == sorted(
        [r["id"] for r in rows], key=int
    )
    # Leverantörsblocken hålls ihop: Direktglas (9) fyller nästan
    # första filen ensamma innan Pilkington börjar.
    first_suppliers = {r["supplier"] for r in chunks[0]}
    assert first_suppliers == {"Direktglas", "Pilkington"}
    assert sum(1 for r in chunks[0]
               if r["supplier"] == "Direktglas") == 9


def test_chunk_rows_small_and_empty():
    from ui.invoices_helpers import chunk_export_rows

    assert chunk_export_rows([]) == []
    assert [len(c) for c in chunk_export_rows([_row(1)])] == [1]
    assert [len(c) for c in
            chunk_export_rows([_row(i) for i in range(10)])] == [10]


# ── Autoexportens batcher ───────────────────────────────────────

def test_plan_batches_splits_supplier_over_ten():
    import datetime

    from ui.auto_batch import plan_batches

    today = datetime.date(2026, 9, 10)

    def _due(i):
        return (today + datetime.timedelta(days=1 + i)).isoformat()

    rows = [
        {"id": str(i), "supplier": "Pilkington",
         "invoice_number": f"F-{i:03d}", "total_amount": 100.0,
         "due_date": _due(i), "status": "Obetald"}
        for i in range(23)
    ]
    batches = plan_batches(rows, today)
    assert [len(b["invoices"]) for b in batches] == [10, 10, 3]
    assert all(b["reason"] == "count" for b in batches)
    # Betalningsdatum = tidigaste förfallet i VARJE delfil
    assert batches[0]["payment_date"] == _due(0)
    assert batches[1]["payment_date"] == _due(10)
    assert batches[2]["payment_date"] == _due(20)
    ids = [r["id"] for b in batches for r in b["invoices"]]
    assert sorted(ids, key=int) == [str(i) for i in range(23)]


# ── Original vid export: ALLTID PÅ ──────────────────────────────

def test_include_originals_default_on(tmp_path):
    """Originalfakturan följer ALLTID med (användarregel
    2026-10-30) — inte ens en avstängd gammal inställning kan
    stoppa det, och Inställningar-menyn har ingen avstängning."""
    _qapp()
    from ui.invoices_view import InvoicesView

    app = _export_app(tmp_path, [], _Exporter())
    view = InvoicesView(app)
    try:
        assert view._include_originals() is True
        app.get_setting = lambda key, default=None: False
        assert view._include_originals() is True  # går INTE stänga av
    finally:
        view.close()
    mw_src = (PROJECT_DIR / "ui" / "main_window.py").read_text(
        encoding="utf-8"
    )
    assert "_toggle_include_originals" not in mw_src


# ── Manuell export: flera filer, arkivering per fil ─────────────

class _Store:
    def on_change(self, _cb):
        pass


class _Exporter:
    def __init__(self):
        self.calls = []

    def export_invoice_list(self, rows, filename="", **kw):
        self.calls.append((list(rows), filename, kw))
        return {
            "success": True, "file_path": filename,
            "payment_date": kw.get("payment_date", ""),
            "attachments_included": len(rows),
        }


class _History:
    def __init__(self):
        self.calls = []

    def record_export(self, **kw):
        self.calls.append(kw)

    def count(self):
        return len(self.calls)


def _export_app(tmp_path, rows, exporter):
    class FakeApp:
        settings = {"db_path": str(tmp_path)}
        invoices_store = _Store()
        suppliers_store = _Store()
        session_due_date = None
        session_due_date_str = ""
        pdf_exporter = exporter
        archived: list = []

        def get_invoices(self):
            return [dict(r) for r in rows]

        def get_suppliers(self):
            return [{"id": "s1", "name": "Pilkington"}]

        def get_setting(self, key, default=None):
            return default

        def set_setting(self, key, value):
            pass

        def update_invoice(self, rid, fields):
            self.archived.append((rid, fields))

    return FakeApp()


_DIALOG = {"text": ""}


def _fake_box():
    """QMessageBox-subklass som aldrig blockerar i testerna.

    OBS: patcha ALDRIG metoder på själva Qt-klassen (Shiboken
    tål inte monkeypatch-återställning av klassmetoder) — byt i
    stället modulens namn till denna subklass.
    """
    from PySide6.QtWidgets import QMessageBox

    class _FakeBox(QMessageBox):
        def exec(self):
            return 0

        def clickedButton(self):
            return None

        def setText(self, t):
            _DIALOG["text"] = t
            super().setText(t)

    return _FakeBox


def _run_export(tmp_path, monkeypatch, rows, force_split=False):
    _qapp()
    import ui.invoices_view as iv
    from ui.invoices_view import InvoicesView

    exporter = _Exporter()
    app = _export_app(tmp_path, rows, exporter)
    view = InvoicesView(app)
    try:
        view._export_history = _History()
        view._ask_payment_date_for_export = (
            lambda **kw: ("2026-09-18", True)
        )
        _DIALOG["text"] = ""
        monkeypatch.setattr(iv, "QMessageBox", _fake_box())
        if force_split:
            # Sandbox-miljöns stub-Qt orkar inte många rader i en
            # vy vid nedstängning — tvinga därför två delfiler med
            # RIKTIGA hjälparen (storlek 2) på få rader här. Att
            # taket är 10 bevisas av hjälpartesterna ovan.
            from ui.invoices_helpers import chunk_export_rows as _rc

            monkeypatch.setattr(
                iv, "chunk_export_rows",
                lambda r: _rc(r, 2),
            )
        monkeypatch.setattr(
            iv, "build_export_path",
            lambda suppliers: (tmp_path, "fakturalista_120000.pdf"),
        )
        view._export_invoices(rows, confirm=False)
        return app, exporter, view
    finally:
        view.close()


def test_export_over_ten_rows_splits_files(tmp_path, monkeypatch):
    # Fler rader än taket → flera filer. (Vy-testet tvingar
    # splitten vid 2/fil av sandbox-skäl — se _run_export.)
    rows = [_row(i + 1) for i in range(4)]
    app, exporter, view = _run_export(
        tmp_path, monkeypatch, rows, force_split=True
    )

    assert [len(c[0]) for c in exporter.calls] == [2, 2]
    names = [Path(c[1]).name for c in exporter.calls]
    assert names == [
        "fakturalista_120000-del1av2.pdf",
        "fakturalista_120000-del2av2.pdf",
    ]
    # Originalen följde med i varje fil (standard PÅ)
    assert all(
        c[2]["include_originals"] is True for c in exporter.calls
    )
    # Allt arkiverat exakt en gång + en historikpost per fil
    assert len(app.archived) == 4
    assert len({rid for rid, _f in app.archived}) == 4
    assert all(
        f.get("status") == "Betald" for _r, f in app.archived
    )
    assert len(view._export_history.calls) == 2
    assert "4 poster exporterade och markerade som Betald" \
        in _DIALOG["text"]
    assert "fakturalista_120000-del2av2.pdf" in _DIALOG["text"]


def test_export_4_rows_keeps_single_plain_filename(
        tmp_path, monkeypatch):
    import json

    # En av fakturorna har originalet i en undermapp (2023/)
    # under en bevakad mapp — där användaren själv lagt det.
    # Exporten får ALDRIG flytta originalet; det ligger kvar
    # exakt där det ligger. Betalt-spårning sker i registret
    # (JSON), inte i mappstrukturen.
    wf = tmp_path / "PilkingtonIn"
    (wf / "2023").mkdir(parents=True)
    src = wf / "2023" / "fk-1001.pdf"
    src.write_bytes(b"%PDF-original")
    (tmp_path / "watch_folders.json").write_text(
        json.dumps({"folders": [
            {"supplier": "Pilkington", "path": str(wf)}
        ]}),
        encoding="utf-8",
    )

    rows = [_row(i + 1) for i in range(4)]
    rows[0]["attachment"] = str(src)
    app, exporter, view = _run_export(tmp_path, monkeypatch, rows)

    assert len(exporter.calls) == 1
    assert Path(exporter.calls[0][1]).name == "fakturalista_120000.pdf"
    status_updates = [
        (rid, f) for rid, f in app.archived
        if f.get("status") == "Betald"
    ]
    assert len(status_updates) == 4
    assert len(view._export_history.calls) == 1

    # Originalet ligger KVAR i årsmappen, orört; inga
    # sökvägsuppdateringar alls vid exporten
    assert src.exists()
    assert not (wf / "Arkiv").exists()
    att_updates = [
        (rid, f) for rid, f in app.archived if f.get("attachment")
    ]
    assert att_updates == []


def test_export_watched_folder_original_stays_put(tmp_path, monkeypatch):
    """Användarregel 2026-10-30: originalet i BEVAKADE mappen
    ligger kvar exakt där vid export — bara en kopia följer med
    i PDF:en. JSON-posten blir samtidigt Betald/historik."""
    import json

    wf = tmp_path / "PilkingtonIn"
    wf.mkdir(parents=True)
    src = wf / "fk-2001.pdf"
    src.write_bytes(b"%PDF-original")
    (tmp_path / "watch_folders.json").write_text(
        json.dumps({"folders": [
            {"supplier": "Pilkington", "path": str(wf)}
        ]}),
        encoding="utf-8",
    )

    rows = [_row(1)]
    rows[0]["attachment"] = str(src)
    app, exporter, view = _run_export(tmp_path, monkeypatch, rows)

    # Exporten kördes med original påslaget (kopian i PDF:en)
    assert len(exporter.calls) == 1
    assert exporter.calls[0][2]["include_originals"] is True
    # JSON-posten sparades som Betald/exporterad …
    status_updates = [
        (rid, f) for rid, f in app.archived
        if f.get("status") == "Betald"
    ]
    assert len(status_updates) == 1
    # … men originalfilen ligger kvar i bevakade mappen, orörd:
    # ingen flytt, ingen årsmapp, inget Arkiv, ingen ny sökväg.
    assert src.exists()
    assert src.read_bytes() == b"%PDF-original"
    assert not (wf / "2023").exists()
    assert not (wf / "Arkiv").exists()
    att_updates = [
        (rid, f) for rid, f in app.archived if f.get("attachment")
    ]
    assert att_updates == []


# ── Konfigurationsläsaren för bevakade mappar ─────────────────

def test_read_watch_folders_tolerant(tmp_path):
    import json

    from ui.invoices_helpers import read_watch_folders

    cfg = tmp_path / "watch_folders.json"
    folders = [{"supplier": "Pilkington", "path": "x"}]
    cfg.write_text(json.dumps({"folders": folders}),
                   encoding="utf-8")
    assert read_watch_folders(cfg) == folders
    assert read_watch_folders(tmp_path / "saknas.json") == []
