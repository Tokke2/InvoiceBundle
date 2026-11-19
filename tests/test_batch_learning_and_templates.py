# -*- coding: utf-8 -*-
"""Tester för:
1. Alla matchade mallar (1–flersidiga, rutor + etiketter + hybrid + from_end + reader fallback)
2. Skanningsbatcher: max 10 fakturor åt gången, sedan automatiskt 10 nya efter matchning/flytt till Fakturor
3. Kontinuerligt självlärande från både manuella matchningar och redigerade automatchningar
4. Avancerad självlärandeloggning (JSONL/text + textbevis + LogView-export till chatten)
5. Ta bort/rensa enskilda markeringar, sidor och logotyper i fakturamallar
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "plugins") not in sys.path:
    sys.path.insert(0, str(ROOT / "plugins"))

from plugins import learning_logger as ll
from plugins import scan_import as si


@pytest.fixture(autouse=True)
def _isolated_learning_logs(tmp_path):
    ll.set_learning_log_dir(tmp_path / "logs")
    yield
    ll.set_learning_log_dir(None)


def _qt_app():
    app = QApplication.instance()
    return app or QApplication([])


class _FakeApp:
    def __init__(self, data_dir: Path, suppliers=None):
        self.settings = {"db_path": str(data_dir)}
        self._suppliers = list(suppliers or [])
        self._invoices: list[dict] = []
        self._seq = 0

    def get_setting(self, key: str, default=None):
        return self.settings.get(key, default)

    def get_suppliers(self):
        return list(self._suppliers)

    def get_invoices(self):
        return list(self._invoices)

    def get_active_invoices(self):
        return list(self._invoices)

    def get_archived_invoices(self):
        return []

    def add_invoice(self, data: dict):
        self._seq += 1
        rec = dict(data)
        rec["id"] = f"inv-{self._seq}"
        self._invoices.append(rec)
        return rec

    def update_invoice(self, inv_id: str, patch: dict):
        for rec in self._invoices:
            if rec.get("id") == inv_id:
                rec.update(patch)
                return True
        return False


def test_multipage_from_end_and_hybrid_and_reader_fallback(tmp_path, monkeypatch):
    # 1) TemplateDialog-regel sparas med page_count + from_end på flersidig faktura
    p = tmp_path / "f1.pdf"
    p.write_bytes(b"%PDF-1.4 dummy")
    monkeypatch.setattr(si, "page_image_count", lambda _p: 4)

    calls: list[tuple[int, tuple]] = []

    def _fake_read_page(_p, page_idx: int, rect: tuple) -> str:
        calls.append((page_idx, rect))
        # Sida 3 (index 3, sista av 4) håller slutbeloppet; sparat på 3-sidig index 2 (from_end=0)
        if page_idx == 3:
            return "4 800,00"
        return ""

    monkeypatch.setattr(si, "_read_region_text_on_page", _fake_read_page)
    tpl = {
        "fields": {
            "invoice_number": {"label": "Fakturanr"},
            "total_amount": {
                "region": [0.5, 0.8, 0.95, 0.92],
                "page": 2,
                "page_count": 3,
                "from_end": 0,
            },
        }
    }
    rt = si.extract_region_texts(p, tpl)
    assert rt["total_amount"] == "4 800,00"
    assert calls[0][0] == 3  # 4 - 1 - 0 = index 3 (sista sidan)

    # 2) Hybridmall (etikett + region) i parse_invoice_text
    parsed_hybrid = si.parse_invoice_text(
        "Lev Alpha\nFakturanr: H-99\nDelsumma 100,00",
        [{"name": "Lev Alpha"}],
        templates={"Lev Alpha": tpl},
        region_texts_by_template={"Lev Alpha": rt},
    )
    assert parsed_hybrid["template"] == "Lev Alpha"
    assert parsed_hybrid["invoice_number"] == "H-99"
    assert parsed_hybrid["total_amount"] == pytest.approx(4800.0)

    # 3) Även om annan leverantör har regionsmall körs reader-fallback för övriga!
    p2 = tmp_path / "f2.pdf"
    p2.write_bytes(b"%PDF-1.4 alt")
    monkeypatch.setattr(
        si, "extract_pdf_texts",
        lambda _p: [("Lev Beta\nFakturanr: B-77\nAtt betala: 950,00", "alt_reader")],
    )
    templates = {
        "Lev Alpha": {
            "fields": {
                "invoice_number": {"region": [0.1, 0.1, 0.3, 0.2], "page": 0},
                "total_amount": {"region": [0.5, 0.8, 0.9, 0.9], "page": 0},
            }
        },
        "Lev Beta": {
            "fields": {
                "invoice_number": {"label": "Fakturanr"},
                "total_amount": {"label": "Att betala"},
            }
        },
    }
    monkeypatch.setattr(si, "extract_region_texts", lambda _p, _t: {})
    res2 = si.parse_invoice_file(
        p2, "oläsligt första uttag",
        [{"name": "Lev Alpha"}, {"name": "Lev Beta"}],
        templates=templates,
    )
    assert res2["template"] == "Lev Beta"
    assert res2["invoice_number"] == "B-77"
    assert res2["total_amount"] == pytest.approx(950.0)

    # Kontrollera att malljämförelsen loggades i självlärandeloggen
    events = ll.read_recent_events()
    eval_events = [e for e in events if e["event"] == "scan_template_eval"]
    assert eval_events
    last_ev = eval_events[-1]
    assert last_ev["reader"] == "fallback:alt_reader"
    assert len(last_ev["templates_checked"]) == 2


def test_template_dialog_rules_saves_multipage_from_end(tmp_path):
    _qt_app()
    import fitz
    from ui.scan_import_view import TemplateDialog

    pdf = tmp_path / "multi.pdf"
    doc = fitz.open()
    for pg in range(1, 4):
        page = doc.new_page()
        page.insert_text((50, 80), f"Sida {pg}\nFakturanr 123\nAtt betala 500,00")
    doc.save(str(pdf))
    doc.close()

    dlg = TemplateDialog(
        None, "Sida 1\nFakturanr 123\nAtt betala 500,00",
        supplier="Multi AB", path=str(pdf),
    )
    try:
        dlg._regions["total_amount"] = (2, (0.5, 0.8, 0.9, 0.95))
        rules = dlg._rules()
        assert rules["total_amount"]["page"] == 2
        assert rules["total_amount"]["page_count"] == 3
        assert rules["total_amount"]["from_end"] == 0
    finally:
        dlg.close()


def test_scan_import_view_batches_10_then_refills_10(tmp_path, monkeypatch):
    _qt_app()
    import fitz
    from ui.scan_import_view import ScanImportView, SCAN_INITIAL_BATCH_SIZE, SCAN_REFILL_BATCH_SIZE

    assert SCAN_INITIAL_BATCH_SIZE == 10
    assert SCAN_REFILL_BATCH_SIZE == 10

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    app = _FakeApp(data_dir, suppliers=[{"name": "Batch AB"}])
    # Spara verifierad mall + 5 bekräftelser för Batch AB så alla 28 fakturor
    # tolkas som kompletta och kan flyttas till Fakturor
    tpl = {
        "fields": {
            "invoice_number": {"label": "Fakturanr"},
            "date": {"label": "Fakturadatum"},
            "total_amount": {"label": "Att betala"},
        }
    }
    si.save_templates(data_dir / "invoice_templates.json", {"Batch AB": tpl})
    learning_data: dict = {}
    for k in range(si.LEARNED_SUPPLIER_CONFIRMATIONS):
        si.record_match_confirmation(
            learning_data, "Batch AB",
            text=f"Batch AB\nFakturanr: SEED-{k}\nFakturadatum: 2026-10-01\nAtt betala: 100,00",
            template_name="Batch AB", template=tpl,
            template_fields=["invoice_number", "date", "total_amount"],
        )
    si.save_match_learning(data_dir / "match_memory.json", learning_data)
    # Skapa 28 äkta läsbara PDF-fakturor
    files_dir = tmp_path / "inbox"
    files_dir.mkdir()
    paths = []
    for idx in range(1, 29):
        fp = files_dir / f"inv_{idx:02d}.pdf"
        doc = fitz.open()
        pg = doc.new_page()
        pg.insert_text(
            (50, 80),
            f"Batch AB\nFakturanr: B-{idx:02d}\nFakturadatum: 2026-10-01\nAtt betala: {100 + idx},00",
        )
        doc.save(str(fp))
        doc.close()
        paths.append(fp)

    # Undvik modal dialog efter varje batch
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: QMessageBox.StandardButton.Yes)

    view = ScanImportView(app=app, templates_path=data_dir / "invoice_templates.json")
    try:
        # Stoppa auto-registrering så raderna stannar i Import tills vi skapar fakturorna
        monkeypatch.setattr(view, "_ask_uncertain_rows", lambda *_a, **_kw: None)
        monkeypatch.setattr(view, "_open_template_for_unmatched", lambda *_a, **_kw: None)
        monkeypatch.setattr(view, "_show_invoices_tab", lambda: None)
        view._paths = list(paths)
        view._scan_files()

        # Max 10 inlästa först, resterande 18 i kö
        assert len(view._rows) == 10
        assert len(view._pending_scan_queue) == 18

        # Flytta dessa 10 till Fakturor -> laddar 10 nya automatiskt!
        view._tbl.selectAll()
        view._create_invoices()
        assert len(app._invoices) == 10
        for _ in range(10):
            QApplication.processEvents()
            if len(view._rows) == 10:
                break
            import time
            time.sleep(0.02)
        assert len(view._rows) == 10
        assert len(view._pending_scan_queue) == 8

        # Flytta nästa 10 -> resterande 8 laddas
        view._tbl.selectAll()
        view._create_invoices()
        assert len(app._invoices) == 20
        for _ in range(10):
            QApplication.processEvents()
            if len(view._rows) == 8:
                break
            import time
            time.sleep(0.02)
        assert len(view._rows) == 8
        assert len(view._pending_scan_queue) == 0
    finally:
        if getattr(view, "_watch", None) is not None:
            view._watch._poll.stop()
        view.close()


def test_watch_manager_batches_10_then_10(tmp_path, monkeypatch):
    _qt_app()
    from ui.watch_folders import WatchManager, WATCH_INITIAL_BATCH_SIZE, WATCH_REFILL_BATCH_SIZE

    assert WATCH_INITIAL_BATCH_SIZE == 10
    assert WATCH_REFILL_BATCH_SIZE == 10

    wdir = tmp_path / "watched"
    wdir.mkdir()
    for i in range(1, 23):
        (wdir / f"doc_{i:02d}.pdf").write_bytes(f"%PDF-1.4 doc {i}".encode())

    monkeypatch.setattr("ui.watch_folders.FILE_STABILITY_SECONDS", 0.0)
    app = _FakeApp(tmp_path / "data", suppliers=[{"name": "Okänd AB"}])
    mgr = WatchManager(
        tmp_path / "watch_folders.json",
        app=app,
        extract_fn=lambda p: (f"Okänd leverantör\nFakturanr: U-{p.stem}\nAtt betala: 500,00", "mock"),
    )
    mgr._poll.stop()
    done_stats: list[dict] = []
    mgr.scan_finished.connect(done_stats.append)
    mgr.set_folders([{"path": str(wdir), "supplier": ""}])
    if not mgr.is_scanning and not done_stats:
        mgr.start_scan()
    for _ in range(120):
        QApplication.processEvents()
        if done_stats:
            break
        import time
        time.sleep(0.01)

    assert done_stats
    assert mgr.deferred_file_count == 12  # 22 total - 10 i batch 1 = 12 köade
    assert len(mgr.parked) == 10

    # Bakgrundspoll får INTE fylla på fler medan batchen ligger kvar parkerad
    mgr._on_poll_scan()
    assert not mgr.is_scanning

    # Matcha/flytta de 10 parkerade -> nästa 10 läses in automatiskt!
    done_stats.clear()
    for p_item in list(mgr.parked):
        mgr._config.setdefault("processed", {})[p_item["hash"]] = {
            "path": p_item["path"],
            "file": p_item["file"],
        }
        mgr.remove_parked(p_item["hash"])
    for _ in range(120):
        QApplication.processEvents()
        if done_stats:
            break
        import time
        time.sleep(0.01)
    assert done_stats
    assert mgr.deferred_file_count == 2
    assert len(mgr.parked) == 10

    # Matcha nästa 10 -> sista 2 läses in!
    done_stats.clear()
    for p_item in list(mgr.parked):
        mgr._config.setdefault("processed", {})[p_item["hash"]] = {
            "path": p_item["path"],
            "file": p_item["file"],
        }
        mgr.remove_parked(p_item["hash"])
    for _ in range(120):
        QApplication.processEvents()
        if done_stats:
            break
        import time
        time.sleep(0.01)
    assert done_stats
    assert mgr.deferred_file_count == 0
    assert len(mgr.parked) == 2


def test_continuous_learning_from_edited_auto_matches_in_import_and_invoices(tmp_path, monkeypatch):
    _qt_app()
    from ui.scan_import_view import ScanImportView
    from ui.invoices_view import InvoicesView
    from ui.log_view import LogView, format_diagnostics

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    app = _FakeApp(
        data_dir,
        suppliers=[{"name": "Fel Leverantör AB"}, {"name": "Rätt Leverantör AB"}],
    )
    # Bygg upp 5 bekräftelser för Fel Leverantör AB så den är automatchad
    learning_file = data_dir / "match_memory.json"
    tpl_file = data_dir / "invoice_templates.json"
    learning: dict = {}
    for k in range(si.LEARNED_SUPPLIER_CONFIRMATIONS):
        si.record_match_confirmation(
            learning, "Fel Leverantör AB",
            text=f"Bankgiro 111-2222\nFakturanr F-{k}\nAtt betala 200,00",
        )
    si.save_match_learning(learning_file, learning)

    view = ScanImportView(app=app, templates_path=tpl_file)
    try:
        # 1) Rätta en automatchad rad direkt i Import-tabellen: ändra leverantör
        sample_text = (
            "Bankgiro 111-2222\nFakturanr: R-101\nFakturadatum: 2026-10-05\n"
            "Förfallodatum: 2026-11-04\nSlutsumma att erlägga: 2 500,00"
        )
        row = {
            "file": "r101.pdf",
            "supplier": "Fel Leverantör AB",
            "invoice_number": "R-101",
            "date": "2026-10-05",
            "due_date": "2026-11-04",
            "ocr": "",
            "total_amount": 100.0,
            "missing": [],
            "status": "redo",
            "method": "mock",
            "_text": sample_text,
            "_path": "",
            "supplier_match": {
                "status": "matched",
                "supplier": "Fel Leverantör AB",
                "reason": "learned",
                "uncertain": False,
            },
        }
        view._rows = [row]
        view._refresh_table()

        # Ändra leverantör i kolumn 1 via itemChanged
        view._tbl.item(0, 1).setText("Rätt Leverantör AB")
        reloaded = si.load_match_learning(learning_file)
        assert reloaded["Fel Leverantör AB"]["confirmed"] == 0
        assert reloaded["Rätt Leverantör AB"]["confirmed"] == 1

        # Rätta även totalbelopp i kolumn 6 till 2500.00 -> lär sig dynamisk etikett "Slutsumma att erlägga" + datum!
        view._tbl.item(0, 6).setText("2 500,00")
        tpls = si.load_templates(tpl_file)
        assert "Rätt Leverantör AB" in tpls
        parsed_new = si.apply_template(sample_text, tpls["Rätt Leverantör AB"])
        assert parsed_new["invoice_number"] == "R-101"
        assert parsed_new["total_amount"] == pytest.approx(2500.0)
        assert parsed_new.get("date") == "2026-10-05"
        assert parsed_new.get("due_date") == "2026-11-04"

        # 2) Kontrollera också redigering i Fakturor-fliken (_learn_from_edited_invoice)
        inv = app.add_invoice({
            "supplier": "Rätt Leverantör AB",
            "invoice_number": "R-102",
            "date": "2026-10-06",
            "due_date": "2026-11-05",
            "total_amount": 300.0,
            "ocr": "",
        })
        txt_file = tmp_path / "r102.txt"
        txt_file.write_text(
            "Fakturanr: R-102\nFakturadatum: 2026-10-06\nAtt betala: 1 990,00",
            encoding="utf-8",
        )
        inv["attachment"] = str(txt_file)
        inv_view = InvoicesView(app)
        try:
            note = inv_view._learn_from_edited_invoice(
                inv,
                {
                    "supplier": "Rätt Leverantör AB",
                    "invoice_number": "R-102",
                    "date": "2026-10-06",
                    "due_date": "2026-11-05",
                    "total_amount": 1990.0,
                    "ocr": "",
                    "attachment": str(txt_file),
                },
            )
            assert "självlärande uppdaterat" in note
        finally:
            inv_view.close()

        # 3) Kontrollera avancerad självlärandelogg + LogView-knapp + diagnospaket
        events = ll.read_recent_events()
        edit_events = [e for e in events if e["event"] == "auto_match_edit"]
        assert len(edit_events) >= 2
        assert any("total_amount" in e.get("field_diffs", {}) for e in edit_events)
        assert any("text_evidence" in e and e["text_evidence"] for e in edit_events)

        log_view = LogView(app, log_file=tmp_path / "logs" / "app.jsonl")
        try:
            log_view._copy_learning_log()
            clip = QApplication.clipboard().text()
            assert "SJÄLVLÄRANDERAPPORT FÖR CHATT" in clip
            assert "RÄTTAD AUTOMATCH" in clip
            assert "Slutsumma att erlägga" in clip or "2 500,00" in clip

            diag = format_diagnostics([], {"learning_lines": clip.splitlines()})
            assert "── Självlärande & malljämförelse ──" in diag
        finally:
            log_view._timer.stop()
            log_view.close()
    finally:
        if getattr(view, "_watch", None) is not None:
            view._watch._poll.stop()
        view.close()


def test_open_row_dialog_learns_from_edited_auto_match(tmp_path, monkeypatch):
    _qt_app()
    from ui.scan_import_view import ScanImportView
    from ui import invoices_helpers as ih

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    app = _FakeApp(
        data_dir,
        suppliers=[{"name": "DialogLev A"}, {"name": "DialogLev B"}],
    )
    learning_file = data_dir / "match_memory.json"
    tpl_file = data_dir / "invoice_templates.json"
    learning: dict = {}
    for k in range(si.LEARNED_SUPPLIER_CONFIRMATIONS):
        si.record_match_confirmation(
            learning, "DialogLev A",
            text=f"Org.nr 556000-0018\nFakturanr A-{k}\nAtt betala 200,00",
        )
    si.save_match_learning(learning_file, learning)

    class _FakeInvoiceDialog:
        def __init__(self, *a, **kw):
            from PySide6.QtWidgets import QDoubleSpinBox, QLineEdit, QDateEdit
            from PySide6.QtCore import QDate
            self.f_total = QDoubleSpinBox()
            self.f_total.setMaximum(1e9)
            self.f_inv_nr = QLineEdit()
            self.f_ocr = QLineEdit()
            self.f_date = QDateEdit()
            self.f_date.setDate(QDate(2026, 10, 1))
            self.f_due_date = QDateEdit()
            self.f_due_date.setDate(QDate(2026, 10, 31))

        def exec(self):
            return 1

        def get_data(self):
            return {
                "supplier": "DialogLev B",
                "invoice_number": "DB-900",
                "ocr": "",
                "date": "2026-10-08",
                "due_date": "2026-11-07",
                "payment_date": "",
                "total_amount": 3450.0,
                "vat_amount": 0.0,
                "amount_ex_vat": 3450.0,
                "vat_percent": 0,
                "currency": "SEK",
            }

    monkeypatch.setattr(ih, "InvoiceDialog", _FakeInvoiceDialog)
    view = ScanImportView(app=app, templates_path=tpl_file)
    try:
        monkeypatch.setattr(view, "_show_invoices_tab", lambda: None)
        monkeypatch.setattr(view, "_rescan_everything_after_learning", lambda *a, **kw: "")
        view._rows = [{
            "file": "db900.pdf",
            "supplier": "DialogLev A",
            "invoice_number": "DA-001",
            "date": "2026-10-08",
            "due_date": "2026-11-07",
            "ocr": "",
            "total_amount": 100.0,
            "missing": [],
            "status": "redo",
            "method": "mock",
            "_text": "Org.nr 556000-0018\nFakturanr: DB-900\nFakturadatum: 2026-10-08\nSlutsumma att erlägga: 3 450,00",
            "_path": "",
            "supplier_match": {
                "status": "matched",
                "supplier": "DialogLev A",
                "reason": "learned",
                "uncertain": False,
            },
        }]
        view._refresh_table()
        view._tbl.selectRow(0)
        view._open_row_dialog()

        reloaded = si.load_match_learning(learning_file)
        assert reloaded["DialogLev A"]["confirmed"] == 0
        assert reloaded["DialogLev B"]["confirmed"] == 1
        assert "DialogLev B" in si.load_templates(tpl_file)
        events = [e for e in ll.read_recent_events() if e["event"] == "auto_match_edit"]
        assert events and events[-1]["counter_reset"] is True
    finally:
        if getattr(view, "_watch", None) is not None:
            view._watch._poll.stop()
        view.close()


def test_open_template_dialog_saves_without_unboundlocal(tmp_path, monkeypatch):
    _qt_app()
    import fitz
    import ui.scan_import_view as sv
    from ui.scan_import_view import ScanImportView

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    app = _FakeApp(data_dir, suppliers=[{"name": "Alpha Mall AB"}])
    pdf = tmp_path / "alpha.pdf"
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_text((50, 80), "Alpha Mall AB\nFakturanr: AM-42\nAtt betala: 1 200,00")
    doc.save(str(pdf))
    doc.close()

    class _FakeTmplDlg:
        def __init__(self, *a, **kw):
            self.result_template = {
                "supplier": "Alpha Mall AB",
                "fields": {
                    "invoice_number": {"label": "Fakturanr"},
                    "total_amount": {"label": "Att betala"},
                },
            }

        def exec(self):
            return 1

    monkeypatch.setattr(sv, "TemplateDialog", _FakeTmplDlg)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: QMessageBox.StandardButton.No)

    tpl_file = data_dir / "invoice_templates.json"
    view = ScanImportView(app=app, templates_path=tpl_file)
    try:
        monkeypatch.setattr(view, "_rescan_everything_after_learning", lambda *a, **kw: "")
        monkeypatch.setattr(view, "_auto_register_matched_rows", lambda *a, **kw: 0)
        view._rows = [{
            "file": "alpha.pdf",
            "supplier": "",
            "invoice_number": "",
            "date": "",
            "due_date": "",
            "ocr": "",
            "total_amount": 0.0,
            "missing": ["belopp", "fakturanummer", "leverantör"],
            "status": "saknas: belopp, fakturanummer, leverantör",
            "method": "pymupdf",
            "_text": "Alpha Mall AB\nFakturanr: AM-42\nAtt betala: 1 200,00",
            "_path": str(pdf),
        }]
        view._refresh_table()
        view._tbl.selectRow(0)
        view._open_template_dialog()

        saved = si.load_templates(tpl_file)
        assert "Alpha Mall AB" in saved
        assert view._rows[0]["supplier"] == "Alpha Mall AB"
        assert view._rows[0]["invoice_number"] == "AM-42"
        assert view._rows[0]["total_amount"] == pytest.approx(1200.0)
    finally:
        if getattr(view, "_watch", None) is not None:
            view._watch._poll.stop()
        view.close()


def test_contradicting_variant_pruned_and_invoices_syncs_import_rescan(tmp_path, monkeypatch):
    _qt_app()
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    from ui.scan_import_view import ScanImportView
    from ui.invoices_view import InvoicesView

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    app = _FakeApp(data_dir, suppliers=[{"name": "Krock AB"}])
    tpl_file = data_dir / "invoice_templates.json"
    learning_file = data_dir / "match_memory.json"

    # Befintlig mall med 2 varianter:
    # - fel_variant ("Summa") läser delsumma 857,25 i stället för Att betala 13 480,00
    # - annan_layout_variant ("Kundfakturabelopp") tillhör helt annat fakturaformat
    fel_variant = {
        "fields": {
            "invoice_number": {"label": "Fakturanr"},
            "total_amount": {"label": "Summa"},
        }
    }
    annan_variant = {
        "fields": {
            "invoice_number": {"label": "Dokumentnr"},
            "total_amount": {"label": "Kundfakturabelopp"},
        }
    }
    templates = {
        "Krock AB": {
            "fields": dict(fel_variant["fields"]),
            "variants": [annan_variant, fel_variant],
        }
    }
    si.save_templates(tpl_file, templates)
    learning: dict = {}
    for k in range(si.LEARNED_SUPPLIER_CONFIRMATIONS):
        si.record_match_confirmation(
            learning, "Krock AB",
            text=f"Krock AB\nFakturanr K-{k}\nSumma 100,00",
            confirmation_id=f"k-{k}",
            template_name="Krock AB",
            template=fel_variant,
            template_fields=["invoice_number", "total_amount"],
        )
    si.save_match_learning(learning_file, learning)

    invoice_text = (
        "Krock AB\n"
        "Fakturanr: K-900\n"
        "Summa 857,25\n"
        "Att betala: 13 480,00\n"
    )
    import fitz
    pdf_file = tmp_path / "k900.pdf"
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_text((50, 80), invoice_text)
    doc.save(str(pdf_file))
    doc.close()

    inv = app.add_invoice({
        "supplier": "Krock AB",
        "invoice_number": "K-900",
        "date": "2026-10-10",
        "due_date": "2026-11-10",
        "total_amount": 857.25,
        "ocr": "",
        "attachment": str(pdf_file),
    })

    host = QWidget()
    layout = QVBoxLayout(host)
    import_view = ScanImportView(app=app, templates_path=tpl_file, parent=host)
    invoices_view = InvoicesView(app, parent=host)
    layout.addWidget(import_view)
    layout.addWidget(invoices_view)
    try:
        rescan_calls: list[str] = []
        monkeypatch.setattr(
            import_view, "_rescan_everything_after_learning",
            lambda *a, **kw: rescan_calls.append("rescan") or "omläst",
        )
        # Användaren rättar beloppet från 857,25 -> 13 480,00 i Fakturor-fliken
        note = invoices_view._learn_from_edited_invoice(
            inv,
            {
                "supplier": "Krock AB",
                "invoice_number": "K-900",
                "date": "2026-10-10",
                "due_date": "2026-11-10",
                "total_amount": 13480.0,
                "ocr": "",
                "attachment": str(pdf_file),
            },
        )
        assert "ersatte 1 krockande mallvariant" in note
        assert rescan_calls == ["rescan"]

        updated_tpls = si.load_templates(tpl_file)
        variants = si.template_variants(updated_tpls["Krock AB"])
        # Genuina alternativa layoutvarianten bevaras, motstridiga "Summa"-varianten ersattes
        labels = [
            (v["fields"].get("total_amount") or {}).get("label")
            for v in variants
        ]
        assert "Summa" not in labels
        assert "Kundfakturabelopp" in labels
        assert "Att betala" in labels

        # Nästa faktura med samma layout får nu rätt belopp direkt utan template_ambiguous!
        parsed_next = si.parse_invoice_text(
            "Krock AB\nFakturanr: K-901\nSumma 400,00\nAtt betala: 9 990,00\n",
            [{"name": "Krock AB"}],
            templates=updated_tpls,
            match_learning=si.load_match_learning(learning_file),
        )
        assert not parsed_next.get("match_uncertain")
        assert parsed_next["total_amount"] == pytest.approx(9990.0)
        assert parsed_next["invoice_number"] == "K-901"

        # Loggen dokumenterar den ersatta krockande varianten
        events = [e for e in ll.read_recent_events() if e["event"] == "auto_match_edit"]
        assert events and len(events[-1]["replaced_variants"]) == 1
        report = ll.format_learning_report(
            si.load_match_learning(learning_file),
            updated_tpls,
            [{"name": "Krock AB"}],
        )
        assert "ersatte=1" in report
    finally:
        if getattr(import_view, "_watch", None) is not None:
            import_view._watch._poll.stop()
        host.close()


def test_region_variant_unconfirmed_when_edit_has_no_label_replacement(tmp_path):
    templates = {
        "RutBolaget AB": {
            "fields": {
                "invoice_number": {"region": [0.1, 0.1, 0.3, 0.2], "page": 0},
                "total_amount": {"region": [0.5, 0.8, 0.9, 0.9], "page": 0},
            }
        }
    }
    tpl = templates["RutBolaget AB"]
    learning: dict = {}
    for k in range(si.LEARNED_SUPPLIER_CONFIRMATIONS):
        si.record_match_confirmation(
            learning, "RutBolaget AB",
            text=f"RutBolaget AB\nFaktnr {k}\nBelopp 100",
            confirmation_id=f"r-{k}",
            template_name="RutBolaget AB",
            template=tpl,
            template_fields=["invoice_number", "total_amount"],
        )
    # Fakturan har bara regionvärden som avviker och saknar härledningsbar etikett
    # Simulera via befintlig label-variant utan ersättningsbar textetikett -> prune=False
    bad_pdf = tmp_path / "rut.pdf"
    bad_pdf.write_bytes(b"%PDF")
    old_sig = si.template_confirmation_signature(tpl)
    # Rensa/spara utan matchande textetiketter genom att sätta oigenkännlig text + region-läsare
    templates["RutBolaget AB"] = {
        "fields": {
            "invoice_number": {"label": "RefNr"},
            "total_amount": {"label": "NettoPris"},
        }
    }
    tpl2 = templates["RutBolaget AB"]
    sig2 = si.template_confirmation_signature(tpl2)
    si.record_match_confirmation(
        learning, "RutBolaget AB",
        confirmation_id="r-extra",
        template_name="RutBolaget AB",
        template=tpl2,
        template_fields=["invoice_number", "total_amount"],
    )
    assert si.template_confirmation_entry(learning, "RutBolaget AB", tpl2)["confirmed"] == 1
    res = si.learn_from_edited_auto_match(
        templates, learning, "RutBolaget AB",
        {"supplier": "RutBolaget AB", "invoice_number": "10", "total_amount": 500.0},
        {"supplier": "RutBolaget AB", "invoice_number": "10", "total_amount": 625.0},
        text="RutBolaget AB\nRefNr 10\nNettoPris 500,00\nSumman blev sexhundratjugofem utan siffror",
    )
    assert res["changed"] is True
    assert sig2 in res["unconfirmed_variants"]
    assert si.template_confirmation_entry(learning, "RutBolaget AB", tpl2)["confirmed"] == 0


def test_user_choice_not_reset_and_manager_edit_rescan_paths(tmp_path, monkeypatch):
    _qt_app()
    from ui.scan_import_view import ScanImportView
    from ui.invoices_view import InvoicesView

    # 1. user_choice ska aldrig nollställa leverantörsbekräftelser vid ändring
    templates: dict = {}
    learning: dict = {}
    for k in range(si.LEARNED_SUPPLIER_CONFIRMATIONS):
        si.record_match_confirmation(learning, "ManualLev AB", confirmation_id=f"m-{k}")
    assert learning["ManualLev AB"]["confirmed"] == si.LEARNED_SUPPLIER_CONFIRMATIONS

    res = si.learn_from_edited_auto_match(
        templates,
        learning,
        "ManualLev AB",
        {
            "supplier": "ManualLev AB",
            "invoice_number": "1",
            "total_amount": 100.0,
            "supplier_match": {"status": "matched", "supplier": "ManualLev AB", "reason": "user_choice", "uncertain": False},
        },
        {"supplier": "AnnanLev AB", "invoice_number": "1", "total_amount": 100.0},
    )
    assert res["counter_reset"] is False
    assert learning["ManualLev AB"]["confirmed"] == si.LEARNED_SUPPLIER_CONFIRMATIONS

    # 2. _rescan_invoice tar med match_learning
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    app = _FakeApp(data_dir, suppliers=[{"name": "ScanLev AB"}])
    tpl_file = data_dir / "invoice_templates.json"
    learning_file = data_dir / "match_memory.json"
    si.save_match_learning(learning_file, {"ScanLev AB": {"confirmed": 5}})
    pdf_stub = tmp_path / "scan.txt"
    pdf_stub.write_text("ScanLev AB\nFakturanr S-1\nAtt betala 200,00", encoding="utf-8")
    inv = app.add_invoice({
        "supplier": "ScanLev AB",
        "invoice_number": "S-1",
        "date": "2026-10-10",
        "due_date": "2026-11-10",
        "total_amount": 200.0,
        "ocr": "",
        "attachment": str(pdf_stub),
    })
    invoices_view = InvoicesView(app)
    import ui.scan_import_view as sv
    si_ui = sv._scan_module()
    captured_ml: list = []
    monkeypatch.setattr(invoices_view, "_selected_invoice", lambda: inv)
    monkeypatch.setattr(
        si_ui, "parse_invoice_file",
        lambda *a, **kw: captured_ml.append(kw.get("match_learning")) or {
            "supplier": "ScanLev AB",
            "invoice_number": "S-1",
            "date": "2026-10-10",
            "due_date": "2026-11-10",
            "ocr": "",
            "total_amount": 200.0,
        },
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.No)
    invoices_view._rescan_invoice()
    assert captured_ml and captured_ml[0].get("ScanLev AB", {}).get("confirmed") == 5
    invoices_view.close()

    # 3. _manager_edit_template loggar och _on_table_item_changed triggar omskanning
    view = ScanImportView(app=app, templates_path=tpl_file)
    try:
        import ui.scan_import_view as sv

        class _FakeDlg:
            def __init__(self, *a, **kw):
                self.result_template = {
                    "supplier": "ScanLev AB",
                    "fields": {"invoice_number": {"label": "Fakturanr"}, "total_amount": {"label": "Att betala"}},
                }

            def exec(self):
                return 1

        monkeypatch.setattr(sv, "TemplateDialog", _FakeDlg)
        rescan_args: list = []
        monkeypatch.setattr(
            view, "_rescan_everything_after_learning",
            lambda *a, **kw: rescan_args.append((a, kw)) or "",
        )
        view._templates_cache = {"ScanLev AB": {"fields": {"invoice_number": {"label": "Fakturanr"}}}}
        view._manager_edit_template("ScanLev AB")
        man_events = [e for e in ll.read_recent_events() if e["event"] == "manual_match" and e.get("source") == "template_manager_edit"]
        assert len(man_events) == 1

        # Redigering i Import-tabellen triggar bakgrunds-omskanning
        view._rows = [{
            "file": "s1.pdf",
            "supplier": "ScanLev AB",
            "invoice_number": "S-1",
            "date": "2026-10-10",
            "due_date": "2026-11-10",
            "ocr": "",
            "total_amount": 100.0,
            "missing": [],
            "status": "redo",
            "method": "mock",
            "_text": "ScanLev AB\nFakturanr S-1\nAtt betala 200,00",
            "_path": "",
            "supplier_match": {"status": "matched", "supplier": "ScanLev AB", "reason": "learned", "uncertain": False},
        }]
        view._refresh_table()
        rescan_args.clear()
        view._tbl.item(0, 6).setText("200,00")
        assert any(kw.get("exclude") is view._rows[0] for _, kw in rescan_args)
    finally:
        if getattr(view, "_watch", None) is not None:
            view._watch._poll.stop()
        view.close()


def _make_logo_pdf(
    path: Path, text_lines: list[str], *, logo_png: bytes | None = None,
    rect: tuple[float, float, float, float] = (36.0, 24.0, 176.0, 82.0),
) -> Path:
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    if logo_png is not None:
        page.insert_image(fitz.Rect(*rect), stream=logo_png)
    y = 140.0
    for line in text_lines:
        page.insert_text((36.0, y), line, fontsize=11)
        y += 18.0
    doc.save(str(path))
    doc.close()
    return path


def _make_distinct_logo_png(seed: int = 1) -> bytes:
    import io
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (180, 72), "white")
    draw = ImageDraw.Draw(img)
    if seed == 1:
        draw.rectangle((8, 8, 56, 64), fill=(25, 65, 140))
        draw.ellipse((70, 14, 122, 58), fill=(220, 120, 20))
        draw.line((132, 16, 170, 56), fill=(20, 20, 20), width=5)
    else:
        draw.polygon([(12, 60), (48, 10), (84, 60)], fill=(15, 130, 85))
        draw.rectangle((96, 14, 168, 58), outline=(180, 30, 60), width=6)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_auto_learns_real_pdf_logo_after_two_confirmations_and_connects_after_five(
    tmp_path,
):
    """Punkt 3: Riktig PDF-logotyp lärs automatiskt efter 2 observationer (ej text-only)
    och kopplar faktura automatiskt först efter 5 bekräftelser — utan att stjälas."""
    logo_a = _make_distinct_logo_png(1)
    templates: dict = {}
    learning: dict = {}
    suppliers = [{"name": "BildLogo AB"}, {"name": "Konkurrent AB"}]

    # 1) Text-only PDF utan embedded_image/vector_art -> får ALDRIG auto-spara header_area
    text_only_pdf = _make_logo_pdf(
        tmp_path / "text_only.pdf",
        ["BildLogo AB", "Fakturanr: T-1", "Att betala: 500,00"],
        logo_png=None,
    )
    for k in range(2):
        sig, saved = si.observe_confirmed_supplier_logo(
            learning, templates, "BildLogo AB", text_only_pdf,
            confirmation_id=f"txt-{k}", suppliers=suppliers,
        )
        assert sig == ""
        assert saved is False
    assert "BildLogo AB" not in templates

    # 2) Två riktiga PDF-fakturor med embedded_image-logotyp
    inv1 = _make_logo_pdf(
        tmp_path / "inv1.pdf",
        ["Fakturanr: L-101", "Att betala: 900,00"],
        logo_png=logo_a,
    )
    inv2 = _make_logo_pdf(
        tmp_path / "inv2.pdf",
        ["Fakturanr: L-102", "Att betala: 1 100,00"],
        logo_png=logo_a,
    )
    inv3_logo_only = _make_logo_pdf(
        tmp_path / "inv3.pdf",
        ["Fakturanr: L-103", "Att betala: 1 350,00"],
        logo_png=logo_a,
    )

    # Bekräftelse 1: sparas bara som logo_candidates[count=1]
    sig1, saved1 = si.observe_confirmed_supplier_logo(
        learning, templates, "BildLogo AB", inv1,
        confirmation_id=si.match_confirmation_id("BildLogo AB", "L-101", path=str(inv1)),
        suppliers=suppliers,
    )
    assert sig1 == ""
    assert saved1 is False
    assert len(learning["BildLogo AB"]["logo_candidates"]) == 1
    assert "BildLogo AB" not in templates
    si.record_match_confirmation(
        learning, "BildLogo AB",
        text="Fakturanr: L-101\nAtt betala: 900,00",
        logo_signature=sig1,
        confirmation_id=si.match_confirmation_id("BildLogo AB", "L-101", path=str(inv1)),
        source_path=inv1,
    )

    # Bekräftelse 2: riktig logotyp befordras automatiskt till mallen!
    templates["BildLogo AB"] = {
        "fields": {
            "invoice_number": {"label": "Fakturanr"},
            "total_amount": {"label": "Att betala"},
        }
    }
    cid2 = si.match_confirmation_id("BildLogo AB", "L-102", path=str(inv2))
    sig2, saved2 = si.observe_confirmed_supplier_logo(
        learning, templates, "BildLogo AB", inv2,
        confirmation_id=cid2, suppliers=suppliers,
    )
    assert sig2
    assert saved2 is True
    assert templates["BildLogo AB"]["supplier_logo"]["source"] == "embedded_image"
    assert templates["BildLogo AB"]["supplier_logo"]["auto"] is True
    assert learning["BildLogo AB"].get("logo_candidates") == {}
    si.record_match_confirmation(
        learning, "BildLogo AB",
        text="Fakturanr: L-102\nAtt betala: 1 100,00",
        logo_signature=sig2,
        confirmation_id=cid2,
        source_path=inv2,
    )
    assert learning["BildLogo AB"]["logos"][sig2] == 2

    # Säkerhetsregel: vid < 5 bekräftelser får loggan INTE autokoppla ännu — måste bli osäker kandidat
    early = si.parse_invoice_file(
        inv3_logo_only, "Fakturanr: L-103\nAtt betala: 1 350,00",
        suppliers=suppliers, templates=templates, match_learning=learning,
    )
    assert early.get("supplier", "") == ""
    assert early.get("match_uncertain") is True
    assert early.get("supplier_match", {}).get("reason") == "supplier_logo"

    # Krockskydd: en annan leverantör med samma bild i PDF:en får INTE stjäla loggan
    theft_pdf = _make_logo_pdf(
        tmp_path / "theft.pdf",
        ["Konkurrent AB", "Fakturanr: K-1", "Att betala: 100,00"],
        logo_png=logo_a,
    )
    for k in range(2):
        ksig, ksaved = si.observe_confirmed_supplier_logo(
            learning, templates, "Konkurrent AB", theft_pdf,
            confirmation_id=f"k-{k}", suppliers=suppliers,
        )
        assert ksig == ""
        assert ksaved is False
    assert "Konkurrent AB" not in templates

    # Efter 5 bekräftelser: ren logotyp-PDF (utan leverantörstext) kopplas automatiskt!
    for k in range(3, 6):
        si.record_match_confirmation(
            learning, "BildLogo AB",
            text=f"Fakturanr: L-10{k}\nAtt betala: 200,00",
            logo_signature=sig2,
            confirmation_id=f"c-{k}",
        )
    assert learning["BildLogo AB"]["confirmed"] == si.LEARNED_SUPPLIER_CONFIRMATIONS

    inv6_logo_only = _make_logo_pdf(
        tmp_path / "inv6.pdf",
        ["Fakturanr: L-600", "Att betala: 2 450,00"],
        logo_png=logo_a,
    )
    parsed = si.parse_invoice_file(
        inv6_logo_only, "Fakturanr: L-600\nAtt betala: 2 450,00",
        suppliers=suppliers, templates=templates, match_learning=learning,
    )
    assert parsed["supplier"] == "BildLogo AB"
    assert not parsed.get("match_uncertain")
    assert parsed["supplier_match"]["reason"] == "learned_logo"
    assert parsed["invoice_number"] == "L-600"
    assert parsed["total_amount"] == pytest.approx(2450.0)


def test_logo_match_respects_aliases_and_blocks_org_conflict(tmp_path):
    """Punkt 3: _apply_supplier_logo_match känner igen registeralias utan falsk logo_conflict
    och stoppar auto-koppling om fakturan trycker ett annat giltigt org.nr."""
    logo_b = _make_distinct_logo_png(2)
    ref_pdf = _make_logo_pdf(
        tmp_path / "ref.pdf",
        ["Nordisk Tech", "Fakturanr: N-1", "Att betala: 100,00"],
        logo_png=logo_b,
    )
    sig = si.supplier_logo_signature(ref_pdf, 0, [0.05, 0.02, 0.32, 0.12])
    assert sig
    templates = {
        "Nordisk Tech": {
            "supplier_logo": {"page": 0, "region": [0.05, 0.02, 0.32, 0.12], "dhash": sig},
            "fields": {
                "invoice_number": {"label": "Fakturanr"},
                "total_amount": {"label": "Att betala"},
            },
        }
    }
    suppliers = [{"name": "Nordisk Teknik AB", "aliases": ["Nordisk Tech"], "org": "5568245806"}]
    learning = {"Nordisk Teknik AB": {"confirmed": 5, "logos": {sig: 2}}}

    # 1) Text säger "Nordisk Teknik AB" och loggan är sparad som alias "Nordisk Tech" -> ingen falsk logo_conflict!
    alias_pdf = _make_logo_pdf(
        tmp_path / "alias.pdf",
        ["Nordisk Teknik AB", "Org.nr 556824-5806", "Fakturanr: N-2", "Att betala: 450,00"],
        logo_png=logo_b,
    )
    res_alias = si.parse_invoice_file(
        alias_pdf,
        "Nordisk Teknik AB\nOrg.nr 556824-5806\nFakturanr: N-2\nAtt betala: 450,00",
        suppliers=suppliers, templates=templates, match_learning=learning,
    )
    assert not res_alias.get("match_uncertain")
    assert res_alias["supplier"] == "Nordisk Teknik AB"

    # 2) Utan textnamn, bara inlärd logotyp under aliasnyckeln -> kopplar till registrerad kanonisk leverantör + mall
    only_logo_pdf = _make_logo_pdf(
        tmp_path / "only_logo.pdf",
        ["Fakturanr: N-3", "Att betala: 750,00"],
        logo_png=logo_b,
    )
    res_only = si.parse_invoice_file(
        only_logo_pdf, "Fakturanr: N-3\nAtt betala: 750,00",
        suppliers=suppliers, templates=templates, match_learning=learning,
    )
    assert not res_only.get("match_uncertain")
    assert res_only["supplier"] == "Nordisk Teknik AB"
    assert res_only["supplier_match"]["reason"] == "learned_logo"
    assert res_only["invoice_number"] == "N-3"
    assert res_only["total_amount"] == pytest.approx(750.0)

    # 3) Tryckt annat giltigt org.nr (556703-7485) -> får INTE tyst koppla via inlärd logga!
    conflict_pdf = _make_logo_pdf(
        tmp_path / "conflict.pdf",
        ["Org.nr 556703-7485", "Fakturanr: N-4", "Att betala: 990,00"],
        logo_png=logo_b,
    )
    res_conflict = si.parse_invoice_file(
        conflict_pdf, "Org.nr 556703-7485\nFakturanr: N-4\nAtt betala: 990,00",
        suppliers=suppliers, templates=templates, match_learning=learning,
    )
    assert res_conflict.get("match_uncertain") is True
    assert res_conflict.get("supplier", "") == ""
    assert res_conflict["supplier_match"]["reason"] == "identifier_conflict"


def test_learns_vat_se01_pg_and_iban_identifiers_and_rejects_short_pg():
    """Punkt 3: Svenskt momsreg SE...01, Plusgiro och verifierat IBAN extraheras och
    lärs in för automatisk koppling, medan sidnummer ('pg. 12') och ogiltiga checksums ignoreras."""
    ids = si._invoice_identifiers(
        "Momsreg.nr SE556824-5806-01\n"
        "Plusgiro: 12 34 56-7\n"
        "IBAN: SE45 5000 0000 0583 9825 7466\n"
        "See pg. 12 for terms\n"
        "IBAN: SE99 5000 0000 0583 9825 7466\n"
    )
    assert ids["org"] == {"5568245806"}
    assert ids["pg"] == {"1234567"}
    assert ids["iban"] == {"SE4550000000058398257466"}

    # Träna 5 bekräftelser med PG/IBAN/SE-momsnr och verifiera automatchning på ensam identifierare
    learning: dict = {}
    for k in range(si.LEARNED_SUPPLIER_CONFIRMATIONS):
        txt = (
            f"Fakturanr: P-{k}\nAtt betala: 300,00\n"
            + ("Plusgiro: 12 34 56-7\n" if k < 2 else "")
            + ("IBAN: SE45 5000 0000 0583 9825 7466\n" if 2 <= k < 4 else "")
            + ("VAT SE556824580601\n" if k >= 3 else "")
        )
        si.record_match_confirmation(learning, "MomsPgIban AB", text=txt, confirmation_id=f"p-{k}")

    assert si.learned_supplier_candidates("Plusgiro 12 34 56-7", learning) == ["MomsPgIban AB"]
    assert si.learned_supplier_candidates("IBAN SE4550000000058398257466", learning) == ["MomsPgIban AB"]
    assert si.learned_supplier_candidates("Momsregnr SE556824580601", learning) == ["MomsPgIban AB"]


def test_derive_template_handles_credit_notes_and_multicolumn_headers():
    """Punkt 3: Kreditfakturor (< 0) och uppdelade flerkolumnsrubriker härleder korrekta mallar."""
    text = (
        "Leverans AB\n"
        "Ordernr    Fakturanummer    Förfallodatum    Slutsumma att reglera\n"
        "ORD-55     KR-2026-8        2026-11-30       1 250,00\n"
        "Kreditfaktura\n"
    )
    col_cands = si._candidate_labels_from_text(
        text, "invoice_number", "token", "KR-2026-8", 1250.0,
    )
    assert "Fakturanummer" in col_cands
    tot_cands = si._candidate_labels_from_text(
        text, "total_amount", "amount", "KR-2026-8", 1250.0,
    )
    assert "Slutsumma att reglera" in tot_cands

    derived = si.derive_template_from_confirmation(
        text, "KR-2026-8", -1250.0, due_date="2026-11-30",
    )
    assert derived is not None
    assert "invoice_number" in derived["fields"]
    assert "total_amount" in derived["fields"]

    parsed = si.parse_invoice_text(
        text,
        suppliers=[{"name": "Leverans AB"}],
        templates={"Leverans AB": derived},
    )
    assert parsed["invoice_number"] == "KR-2026-8"
    assert parsed["total_amount"] == pytest.approx(-1250.0)


def test_correction_resets_wrong_logo_and_ui_learns_logo_end_to_end(
    tmp_path, monkeypatch,
):
    """Punkt 3: Felaktigt automatchad logotyp stryks vid korrigering och både
    ScanImportView samt InvoicesView lär in riktig fakturalogotyp efter 2 bekräftelser."""
    from PySide6.QtWidgets import QApplication, QMessageBox
    QApplication.instance() or QApplication([])
    import ui.scan_import_view as sv
    import ui.invoices_view as iv
    from ui.invoices_view import InvoicesView
    from ui.scan_import_view import ScanImportView
    from plugins import learning_logger as ll

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(sv.QMessageBox, "information", lambda *_a, **_k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *_a, **_k: None)

    logo = _make_distinct_logo_png(1)
    pdf1 = _make_logo_pdf(tmp_path / "f1.pdf", ["Fakturanr: E-1", "Att betala: 400,00"], logo_png=logo)
    pdf2 = _make_logo_pdf(tmp_path / "f2.pdf", ["Fakturanr: E-2", "Att betala: 600,00"], logo_png=logo)
    sig = si.supplier_logo_signature(pdf1, 0, [0.05, 0.02, 0.32, 0.12])
    assert sig

    # 1) Korrigering i learn_from_edited_auto_match rensar kolliderande logga från Fel AB
    tpls = {
        "Fel AB": {
            "supplier_logo": {"page": 0, "region": [0.05, 0.02, 0.32, 0.12], "dhash": sig},
            "fields": {"invoice_number": {"label": "Fakturanr"}, "total_amount": {"label": "Att betala"}},
        }
    }
    mem = {"Fel AB": {"confirmed": 5, "logos": {sig: 3}}}
    res = si.learn_from_edited_auto_match(
        tpls, mem, "Fel AB",
        {"supplier": "Fel AB", "invoice_number": "E-1", "total_amount": 400.0,
         "supplier_match": {"status": "matched", "supplier": "Fel AB", "reason": "learned_logo"}},
        {"supplier": "Rätt AB", "invoice_number": "E-1", "total_amount": 400.0},
        text="Fakturanr: E-1\nAtt betala: 400,00",
        path=str(pdf1),
    )
    assert res["counter_reset"] is True
    assert mem["Fel AB"]["confirmed"] == 0
    assert sig not in (mem["Fel AB"].get("logos") or {})

    # 2) End-to-end i ScanImportView + InvoicesView: 2 bekräftelser av samma PDF-logotyp lär in logotypen
    app = _FakeApp(data_dir, suppliers=[{"name": "Rätt AB"}])
    tpl_file = data_dir / "invoice_templates.json"
    learn_file = data_dir / "match_memory.json"

    scan_view = ScanImportView(app=app, templates_path=tpl_file)
    try:
        row1 = {
            "file": "f1.pdf", "_path": str(pdf1),
            "_text": "Fakturanr: E-1\nAtt betala: 400,00", "pages": 1,
            "invoice_number": "E-1", "total_amount": 400.0,
            "date": "", "due_date": "", "ocr": "", "supplier": "", "missing": ["leverantör"],
        }
        scan_view._rows = [row1]
        note1 = scan_view._apply_manual_match(row1, "Rätt AB")
        assert note1
        assert "supplier_logo" not in (si.load_templates(tpl_file).get("Rätt AB") or {})
    finally:
        if getattr(scan_view, "_watch", None) is not None:
            scan_view._watch._poll.stop()
        scan_view.close()

    inv_view = InvoicesView(app)
    try:
        note2 = inv_view._learn_manual_match(
            sv._scan_module(),
            "Rätt AB",
            "Fakturanr: E-2\nAtt betala: 600,00",
            "E-2",
            600.0,
            1,
            path=str(pdf2),
        )
        assert note2
    finally:
        inv_view.close()

    saved_tpls = si.load_templates(tpl_file)
    assert saved_tpls.get("Rätt AB", {}).get("supplier_logo", {}).get("source") == "embedded_image"
    saved_mem = si.load_match_learning(learn_file)
    assert saved_mem["Rätt AB"]["confirmed"] == 2
    assert len(saved_mem["Rätt AB"].get("logos") or {}) == 1
    events = ll.read_recent_events()
    assert any(ev.get("logo_auto_saved") is True for ev in events)


def test_template_dialog_and_store_can_remove_individual_and_all_marks(tmp_path):
    _qt_app()
    import fitz
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    from ui.scan_import_view import TemplateDialog

    pdf = tmp_path / "marks.pdf"
    doc = fitz.open()
    for pg in range(1, 3):
        page = doc.new_page()
        page.insert_text((50, 80), f"Mark AB Sida {pg}\nFakturanr M-{pg}\nAtt betala 900,00")
    doc.save(str(pdf))
    doc.close()

    logo_hash = "dhash128-v1:" + "a" * 32
    existing_tpl = {
        "fields": {
            "invoice_number": {"region": [0.1, 0.1, 0.3, 0.2], "page": 0},
            "date": {"region": [0.1, 0.2, 0.3, 0.3], "page": 0},
            "total_amount": {"region": [0.5, 0.7, 0.9, 0.8], "page": 1},
        },
        "supplier_logo": {"region": [0.05, 0.05, 0.2, 0.12], "page": 0, "dhash": logo_hash},
        "supplier_logos": [{"region": [0.05, 0.05, 0.2, 0.12], "page": 0, "dhash": logo_hash}],
    }

    dlg = TemplateDialog(
        None,
        "Mark AB Sida 1\nFakturanr M-1\nAtt betala 900,00",
        supplier="Mark AB",
        existing=existing_tpl,
        path=str(pdf),
    )
    try:
        # 1) Ta bort ett fält via ✖-hjälparen och ett annat med Delete-tangenten
        assert "date" in dlg._regions
        dlg._remove_field_mark("date")
        assert "date" not in dlg._regions
        assert dlg._fields_removed is True

        dlg._set_active("total_amount")
        ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
        dlg.keyPressEvent(ev)
        assert "total_amount" not in dlg._regions

        # 2) Ta bort logomarkering och spara -> store_supplier_template tar bort både fälten och logon!
        dlg._clear_logo_marks()
        assert dlg._logo_removed is True
        assert dlg._logo_specs == []

        dlg._save()
        assert dlg.result_template is not None
        assert dlg.result_template["replace_logos"] is True
        assert list(dlg.result_template["fields"].keys()) == ["invoice_number"]

        tpl_store = {"Mark AB": existing_tpl}
        cand = {k: v for k, v in dlg.result_template.items() if k != "supplier"}
        rep_logos = bool(cand.pop("replace_logos", False))
        si.store_supplier_template(
            tpl_store, "Mark AB", cand,
            replace_primary=True, replace_logos=rep_logos,
        )
        saved = tpl_store["Mark AB"]
        assert set(saved["fields"].keys()) == {"invoice_number"}
        assert "supplier_logo" not in saved
        assert "supplier_logos" not in saved
    finally:
        dlg.close()

    # 3) Rensa enskild sida vs rensa alla markeringar
    dlg2 = TemplateDialog(
        None,
        "Mark AB Sida 1\nFakturanr M-1\nAtt betala 900,00",
        supplier="Mark AB",
        existing=existing_tpl,
        path=str(pdf),
    )
    try:
        dlg2._page_idx = 0
        dlg2._clear_page_marks()
        assert "invoice_number" not in dlg2._regions
        assert "date" not in dlg2._regions
        assert "total_amount" in dlg2._regions  # låg på sida 1, orörd!
        assert dlg2._logo_specs == []

        dlg2._clear_marks()
        assert dlg2._regions == {}
        assert dlg2._existing_fields == {}
        assert dlg2._logo_specs == []
    finally:
        dlg2.close()



