# -*- coding: utf-8 -*-
"""
Tester: bevakade leverantörsmappar + valbara original i betal-PDF:en.

En mapp per leverantör bevakas; nya fakturafiler tolkas och kan
registreras automatiskt (kompletta) eller parkeras (ofullständiga/
dubbletter). Vid lyckad registrering flyttas originalet till en
undermapp med fakturans år och register-/bevakningssökvägar hålls
synkroniserade. PDF-exporten kan ta med alla original, första PDF-sidan
eller inga original alls.
"""
from __future__ import annotations

import logging
import os
import sys
import time
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


def _await_scan(mgr, timeout_ms: int = 15000) -> bool:
    """Kör händelseloopen tills en pågående bakgrundsskanning är klar.

    Automatiska skanningar går i bakgrunden (tolkningen sker i en
    arbetstråd) och behöver därför en snurrande händelseloop även i test.
    """
    from PySide6.QtCore import QEventLoop, QTimer

    finished: list[bool] = []

    def _on_finished(_stats):
        finished.append(True)
        # En skanning som coalescats medan den pågick startar om direkt;
        # vänta tills kön är tom så testet ser slutresultatet.
        if not mgr.is_scanning:
            loop.quit()

    if not getattr(mgr, "is_scanning", False):
        return False
    loop = QEventLoop()
    mgr.scan_finished.connect(_on_finished)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    mgr.scan_finished.disconnect(_on_finished)
    return bool(finished)


TEXT = """\
PILKINGTON GLAS AB
Fakturanr: 9911
Utfärdad: 2026-09-01
Senast: 2026-10-01
SUMMA: 1 250,00
"""

TEMPLATES = {
    "Pilkington": {"fields": {
        "invoice_number": {"label": "Fakturanr"},
        "total_amount": {"label": "SUMMA"},
        "date": {"label": "Utfärdad"},
        "due_date": {"label": "Senast"},
    }},
}


class FakeApp:
    def __init__(self, invoices=None):
        self._invoices = invoices or []

    def get_suppliers(self):
        return [{"name": "Pilkington", "short_name": "Pilkington"}]

    def get_invoices(self):
        return self._invoices


def _manager(tmp_path, invoices=None, auto=True, text=TEXT):
    import scan_import as si
    from ui.watch_folders import WatchManager
    folder = tmp_path / "PilkingtonIn"
    folder.mkdir(parents=True, exist_ok=True)
    learning = {}
    si.record_template_confirmation(
        learning, "Pilkington", "Pilkington", TEMPLATES["Pilkington"],
        confirmation_id="test-watch-template-confirmed",
        template_fields=list(TEMPLATES["Pilkington"]["fields"]),
    )
    mgr = WatchManager(
        tmp_path / "watch_folders.json",
        app=FakeApp(invoices),
        extract_fn=lambda path: (text, "test"),
        templates_provider=lambda: TEMPLATES,
        learning_provider=lambda: learning,
    )
    mgr.set_folders([{"supplier": "Pilkington", "path": str(folder)}])
    if not auto:
        mgr.set_auto_create(False)
    return mgr, folder


def _persist_emitted(mgr):
    """Simulerar appens registrering: en emitterad faktura hamnar
    i fejk-registret precis som _on_watch_invoice gör via
    app-kärnan. Utan detta ser självläkningen (med rätta) ut som
    att registreringen försvann."""
    def _save(row, path):
        mgr._app._invoices.append({
            "supplier": row.get("supplier", ""),
            "invoice_number": row.get("invoice_number", ""),
            "attachment": str(path),
            "status": "Obetald",
        })
    mgr.invoice_ready.connect(_save)


def _persist_and_archive_emitted(mgr):
    """Mirror the successful registration path for watched-folder tests."""
    def _save(row, path):
        final_path = mgr.archive_processed_file(path, row.get("date", ""))
        mgr._app._invoices.append({
            "supplier": row.get("supplier", ""),
            "invoice_number": row.get("invoice_number", ""),
            "date": row.get("date", ""),
            "attachment": final_path,
            "status": "Obetald",
        })
    mgr.invoice_ready.connect(_save)


def test_watch_summary_not_repeated_for_unchanged_poll(tmp_path, caplog):
    """A 30-second poll must not repeat an unchanged parked-file summary."""
    _qapp()
    mgr, _folder = _manager(tmp_path)
    state = {
        "waiting": 203,
        "already": 35,
        "reasons": {"missing": 88, "unknown-format": 8, "uncertain-match": 107},
    }

    def fake_scan(_entry, force=False):
        mgr._scan_stats.update(
            imported=0, duplicate=0, parked=0,
            already=state["already"], waiting=state["waiting"],
            errors=0, changed=0,
        )
        mgr._waiting_reasons.update(state["reasons"])

    mgr.scan_folder = fake_scan
    with caplog.at_level(logging.INFO, logger="WatchFolders"):
        caplog.clear()
        mgr.scan_all()
        mgr.scan_all()
        summaries = [
            record for record in caplog.records
            if record.getMessage().startswith("SCAN_WATCH skanning:")
        ]
        assert len(summaries) == 1
        assert "203 väntar i parkering" in summaries[0].getMessage()

        state["waiting"] = 204
        state["reasons"]["missing"] = 89
        mgr.scan_all()
        summaries = [
            record for record in caplog.records
            if record.getMessage().startswith("SCAN_WATCH skanning:")
        ]
        assert len(summaries) == 2
        assert "204 väntar i parkering" in summaries[-1].getMessage()


def test_watch_complete_invoice_ready_once(tmp_path):
    _qapp()
    mgr, folder = _manager(tmp_path)
    ready, parked = [], []
    mgr.invoice_ready.connect(lambda row, path: ready.append((row, path)))
    _persist_emitted(mgr)
    mgr.file_parked.connect(lambda info: parked.append(info))
    (folder / "f1.pdf").write_bytes(b"%PDF-fake-1")
    mgr.scan_all()
    assert len(ready) == 1 and not parked
    row, _path = ready[0]
    assert row["supplier"] == "Pilkington"      # mappens leverantör
    assert row["invoice_number"] == "9911"
    assert row["total_amount"] == 1250.0
    # Samma fil igen → hash-skyddet stoppar dubbletten
    mgr.scan_all()
    assert len(ready) == 1


def test_watch_duplicate_and_incomplete_parked(tmp_path):
    _qapp()
    mgr, folder = _manager(
        tmp_path,
        invoices=[{"supplier": "Pilkington", "invoice_number": "9911"}],
    )
    ready = []
    mgr.invoice_ready.connect(lambda row, path: ready.append(row))
    (folder / "dup.pdf").write_bytes(b"%PDF-dup")
    mgr.scan_all()
    # Dubblett registreras ALDRIG igen — filen markeras bearbetad
    assert not ready
    import json as _json
    cfg = _json.loads(
        (tmp_path / "watch_folders.json").read_text(encoding="utf-8")
    )
    results = [v.get("result") for v in cfg["processed"].values()]
    assert results == ["duplicate-invoice"]

    # Ofullständig tolkning parkeras också (aldrig tyst tappad)
    mgr2, folder2 = _manager(
        tmp_path / "b", text="tomt dokument utan fält"
    )
    parked2 = []
    mgr2.file_parked.connect(lambda info: parked2.append(info))
    (folder2 / "tom.pdf").write_bytes(b"%PDF-tom")
    mgr2.scan_all()
    assert len(parked2) == 1
    assert parked2[0]["parsed"]["missing"]


def test_watch_manual_mode_parks_everything(tmp_path):
    _qapp()
    mgr, folder = _manager(tmp_path, auto=False)
    ready, parked = [], []
    mgr.invoice_ready.connect(lambda row, path: ready.append(row))
    mgr.file_parked.connect(lambda info: parked.append(info))
    (folder / "f.pdf").write_bytes(b"%PDF-x")
    mgr.scan_all()
    assert not ready and len(parked) == 1
    # Inställningen överlever omstart (sparad i json)
    from ui.watch_folders import WatchManager
    again = WatchManager(tmp_path / "watch_folders.json")
    assert again.auto_create is False
    assert again.folders[0]["supplier"] == "Pilkington"


def test_watch_registration_references_original_no_copy(tmp_path):
    """Auto-registrering från bevakad mapp pekar på ORIGINALET.

    Ingen kopia i data/attachments/: fakturans attachment-fält i
    JSON ska vara sökvägen till filen i användarens egen mapp,
    och originalfilen där ska vara orörd.
    """
    _qapp()
    from ui.scan_import_view import ScanImportView

    folder = tmp_path / "PilkingtonIn"
    folder.mkdir(parents=True)
    src = folder / "f1.pdf"
    src.write_bytes(b"%PDF-original-i-egen-mapp")

    saved = {}

    class _Label:
        def setText(self, _text):
            pass

    view = ScanImportView.__new__(ScanImportView)
    view._lbl_status = _Label()

    def _fake_save(data, source="", silent=False):
        saved.update(data)
        return True

    view._save_invoice = _fake_save
    row = {
        "supplier": "Pilkington", "invoice_number": "9911",
        "ocr": "99118", "date": "2026-09-01",
        "due_date": "2026-10-01", "total_amount": 1250.0,
        "file": "f1.pdf", "method": "test", "_path": str(src),
    }
    view._on_watch_invoice(row, str(src))

    # JSON pekar på originalet i användarens egen mapp
    assert saved.get("attachment") == str(src)
    # Ingen kopia hamnade i data/attachments/
    assert not (tmp_path / "data").exists()
    # Originalfilen orörd
    assert src.read_bytes() == b"%PDF-original-i-egen-mapp"


def _base_pdf(path: Path) -> None:
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path))
    c.drawString(72, 720, "Betal-PDF")
    c.save()


def test_merge_originals_appends_without_divider(tmp_path):
    from PIL import Image
    from pypdf import PdfReader
    from plugins.pdf_export_helpers import merge_originals
    base = tmp_path / "betal.pdf"
    _base_pdf(base)
    img = tmp_path / "orig.png"
    Image.new("RGB", (60, 40), (200, 30, 30)).save(img)
    result = merge_originals(
        base, [("Pilkington · 9911 · orig.png", img)],
        "Originalfaktura",
    )
    # Ingen avdelarsida: bara originalets egen sida läggs till
    assert result == {"included": 1, "missing": 0, "pages_added": 1}
    reader = PdfReader(str(base))
    assert len(reader.pages) == 2  # bas+bild
    all_text = "\n".join(
        (p.extract_text() or "") for p in reader.pages
    )
    assert "Originalfaktura" not in all_text  # ingen avdelarsida
    saknas = merge_originals(
        base, [("x", tmp_path / "finns_inte.pdf")], "Originalfaktura"
    )
    assert saknas["missing"] == 1 and saknas["included"] == 0


def test_exporter_original_inclusion_modes(tmp_path):
    """Exports honor all-pages, first-page-only, and no-original modes."""
    from PIL import Image
    from pypdf import PdfReader
    from reportlab.pdfgen import canvas
    from plugins.pdf_export_helpers import PDFExporter

    img = tmp_path / "orig.png"
    Image.new("RGB", (60, 40), (30, 60, 200)).save(img)
    inv = [{
        "supplier": "Pilkington", "invoice_number": "9911",
        "ocr": "9911", "total_amount": 1250.0,
        "due_date": "2026-10-01", "attachment": str(img),
    }]
    exporter = PDFExporter(tmp_path, tmp_path)
    without_attachment = exporter.export_invoice_list(
        [dict(inv[0], attachment="")], filename="export.pdf",
        ask_payment_date=False, payment_date="2026-09-15",
        mark_exported=False,
    )
    assert without_attachment["success"]
    base_pages = len(PdfReader(without_attachment["file_path"]).pages)
    assert without_attachment["attachments_missing"] == 1

    all_pages = exporter.export_invoice_list(
        [dict(inv[0])], filename="export.pdf", ask_payment_date=False,
        payment_date="2026-09-15", mark_exported=False,
    )
    assert all_pages["success"] and all_pages["attachments_included"] == 1
    assert len(PdfReader(all_pages["file_path"]).pages) == base_pages + 1

    disabled = exporter.export_invoice_list(
        [dict(inv[0])], filename="export.pdf", ask_payment_date=False,
        payment_date="2026-09-15", mark_exported=False,
        include_originals=False,
    )
    assert disabled["success"] and disabled["attachments_included"] == 0
    assert disabled["attachments_missing"] == 0
    assert len(PdfReader(disabled["file_path"]).pages) == base_pages

    multipage = tmp_path / "two-pages.pdf"
    c = canvas.Canvas(str(multipage))
    c.drawString(72, 720, "Original page one")
    c.showPage()
    c.drawString(72, 720, "Original page two")
    c.save()
    pdf_invoice = dict(inv[0], attachment=str(multipage))
    all_pdf_pages = exporter.export_invoice_list(
        [pdf_invoice], filename="export.pdf", ask_payment_date=False,
        payment_date="2026-09-15", mark_exported=False,
        include_originals=True, original_first_page_only=False,
    )
    assert all_pdf_pages["attachments_included"] == 1
    assert len(PdfReader(all_pdf_pages["file_path"]).pages) == base_pages + 2

    first_page = exporter.export_invoice_list(
        [pdf_invoice], filename="export.pdf", ask_payment_date=False,
        payment_date="2026-09-15", mark_exported=False,
        include_originals=True, original_first_page_only=True,
    )
    assert first_page["attachments_included"] == 1
    assert first_page["original_first_page_only"] is True
    assert len(PdfReader(first_page["file_path"]).pages) == base_pages + 1


def test_watch_untaught_supplier_parked_until_taught(tmp_path):
    """Ingen inlärd mall → aldrig auto, hur komplett allt ser ut.

    Alla leverantörer har egen layout: först när användaren lärt
    appen leverantören (mall sparad och träffar) registrerar
    mappen automatiskt.
    """
    _qapp()
    from ui.watch_folders import WatchManager

    import scan_import as si
    holder = {"templates": {}}
    learning = {}
    folder = tmp_path / "PilkingtonIn"
    folder.mkdir(parents=True, exist_ok=True)
    mgr = WatchManager(
        tmp_path / "watch_folders.json",
        app=FakeApp(),
        extract_fn=lambda path: (TEXT, "test"),
        templates_provider=lambda: holder["templates"],
        learning_provider=lambda: learning,
    )
    mgr.set_folders([{"supplier": "Pilkington", "path": str(folder)}])
    ready, parked = [], []
    mgr.invoice_ready.connect(lambda row, path: ready.append(row))
    _persist_emitted(mgr)
    mgr.file_parked.connect(lambda info: parked.append(info))

    (folder / "f1.pdf").write_bytes(b"%PDF-fake-1")
    mgr.scan_all()
    # Heuristiken hittar allt — men utan inlärd mall: parkera
    assert not ready
    assert len(parked) == 1
    assert parked[0]["reason"] == "no-template"
    assert parked[0]["parsed"]["invoice_number"] == "9911"

    # Vanliga skanningar läser ALDRIG om parkerade tolkningsfiler
    # — inte ens när en mall dykt upp. Filen är redan importerad
    # för tolkning och ska ligga still tills användaren agerar.
    holder["templates"] = TEMPLATES
    mgr.scan_all()
    assert not ready
    assert len(mgr.parked) == 1

    # Att spara mallen räcker inte: första omläsningen ska visa
    # raden i Import som osäker, inte registrera den automatiskt.
    entry = {"supplier": "Pilkington", "path": str(folder)}
    assert mgr.reprocess_parked(entry) == 1
    assert not ready
    assert len(mgr.parked) == 1
    assert mgr.parked[0]["parsed"]["match_reason"] == (
        "template_unconfirmed"
    )

    # Först en uttrycklig verifiering gör att samma mallversion får
    # registrera kompletta kommande fakturor automatiskt.
    si.record_template_confirmation(
        learning, "Pilkington", "Pilkington", TEMPLATES["Pilkington"],
        confirmation_id="user-verified-pilkington-template",
        template_fields=list(TEMPLATES["Pilkington"]["fields"]),
    )
    assert mgr.reprocess_parked(entry) == 1
    assert len(ready) == 1
    assert ready[0]["template"] == "Pilkington"
    assert not mgr.parked
    (folder / "f2.pdf").write_bytes(b"%PDF-fake-2")
    mgr.scan_all()
    # f2 är en kopia av samma faktura (samma filinnehåll)
    # — den registreras aldrig en andra gång;
    # dubblettskyddet stoppar den.
    assert len(ready) == 1


# ── Inbyggt verifierat format: ingen inlärning krävs ────────

MARTIN_TEXT = """\
MARTIN G ANDERSON
Samlad FAKTURA
Fakturanr. 906178
Fakturadatum 2023-06-16
Kundnr. 103
Förfallodatum: 2023-07-16
001 Härdad float 4 mm 2 552 x 1692 1,88 18,68 430,61 861,22
Fakturanr: 906178
Summa netto 2 793,03 Moms 698,26 Öresavrundning 0,29 Att betala SEK 3 491,00
Org nr 556824-5806 Bankgiro: 728-0811
"""


def test_watch_folder_short_name_resolves_to_register(tmp_path):
    """Mappen heter "Martin G" men registerposten "AB Martin G
    Anderson" — bevakningen ska ändå registrera (användaren
    har pekat ut leverantören; exakt namnmatchning får inte
    stoppa med "leverantör saknas")."""
    _qapp()
    from ui.watch_folders import WatchManager

    class MartinApp(FakeApp):
        def get_suppliers(self):
            return [{
                "name": "AB Martin G Anderson",
                "org_number": "556824-5806", "bg": "728-0811",
            }]

    folder = tmp_path / "MartinIn"
    folder.mkdir(parents=True, exist_ok=True)
    mgr = WatchManager(
        tmp_path / "watch_folders.json",
        app=MartinApp(),
        extract_fn=lambda path: (MARTIN_TEXT, "test"),
        templates_provider=lambda: {},
    )
    mgr.set_folders([{"supplier": "Martin G", "path": str(folder)}])
    ready, parked = [], []
    mgr.invoice_ready.connect(lambda row, path: ready.append(row))
    _persist_emitted(mgr)
    mgr.file_parked.connect(lambda info: parked.append(info))

    (folder / "m1.pdf").write_bytes(b"%PDF-fake-m1")
    mgr.scan_all()
    assert len(ready) == 1 and not parked
    assert ready[0]["supplier"] == "AB Martin G Anderson"


def test_watch_builtin_format_registers_without_teaching(tmp_path):
    """Martin G:s format är inbyggt efter manuell verifiering
    mot riktiga exempelfakturor — bevakningen registrerar
    direkt, utan inlärd mall i appen."""
    _qapp()
    from ui.watch_folders import WatchManager

    class MartinApp(FakeApp):
        def get_suppliers(self):
            return [{
                "name": "AB Martin G Anderson",
                "org_number": "556824-5806", "bg": "728-0811",
            }]

    folder = tmp_path / "MartinIn"
    folder.mkdir(parents=True, exist_ok=True)
    mgr = WatchManager(
        tmp_path / "watch_folders.json",
        app=MartinApp(),
        extract_fn=lambda path: (MARTIN_TEXT, "test"),
        templates_provider=lambda: {},
    )
    mgr.set_folders([{
        "supplier": "AB Martin G Anderson", "path": str(folder),
    }])
    ready, parked = [], []
    mgr.invoice_ready.connect(lambda row, path: ready.append(row))
    _persist_emitted(mgr)
    mgr.file_parked.connect(lambda info: parked.append(info))

    (folder / "m1.pdf").write_bytes(b"%PDF-fake-m1")
    mgr.scan_all()
    assert len(ready) == 1 and not parked
    assert ready[0]["invoice_number"] == "906178"
    assert ready[0]["total_amount"] == 3491.00
    assert ready[0]["supplier"] == "AB Martin G Anderson"
    assert ready[0]["template"]


# ── Årsarkivering efter import, aldrig vid betalning/export ───
# Bekräftat registrerade original sorteras efter fakturadatum.
# Ofullständiga filer och orelaterade dubblettkopior lämnas kvar;
# årsmappen skannas fortfarande och Arkiv/ skannas aldrig.

class _YearApp(FakeApp):
    """FakeApp som kan ta emot registry-uppdateringar."""

    def __init__(self, invoices=None):
        super().__init__(invoices)
        self.updated = []

    def update_invoice(self, rid, fields):
        self.updated.append((rid, fields))
        for inv in self._invoices:
            if inv.get("id") == rid:
                inv.update(fields)


YEAR_TEXT = """\
Pilkington Automotive Sweden AB / AGR
Fakturanr 9911
Fakturadatum 2023-06-16
Utfärdad 2023-06-16
Senast 2023-07-16
SUMMA 1 250,00
"""


def _year_manager(tmp_path, app):
    import scan_import as si
    from ui.watch_folders import WatchManager

    learning = {}
    si.record_template_confirmation(
        learning, "Pilkington", "Pilkington", TEMPLATES["Pilkington"],
        confirmation_id="test-year-template-confirmed",
        template_fields=list(TEMPLATES["Pilkington"]["fields"]),
    )
    folder = tmp_path / "PilkingtonIn"
    folder.mkdir(parents=True, exist_ok=True)
    mgr = WatchManager(
        tmp_path / "watch_folders.json",
        app=app,
        extract_fn=lambda path: (YEAR_TEXT, "test"),
        templates_provider=lambda: TEMPLATES,
        learning_provider=lambda: learning,
    )
    mgr.set_folders([{"supplier": "Pilkington", "path": str(folder)}])
    return mgr, folder


def test_watch_archive_requires_invoice_year(tmp_path):
    _qapp()
    app = _YearApp()
    mgr, folder = _year_manager(tmp_path, app)
    src = folder / "no-date.pdf"
    src.write_bytes(b"%PDF-no-date")

    assert mgr.archive_processed_file(src, "") == str(src)
    assert src.is_file()
    assert not (folder / "2023").exists()


def test_scan_import_prompts_fallback_after_successful_registration(
    tmp_path, monkeypatch,
):
    """Missing/invalid dates ask even in silent import, after DB save."""
    _qapp()
    from types import SimpleNamespace

    from ui.scan_import_view import QInputDialog, ScanImportView

    folder = tmp_path / "watched"
    folder.mkdir()
    events = []
    prompt_calls = []

    class App:
        def add_invoice(self, data):
            events.append("register")
            self.record = {"id": "scan-1", **data}
            return dict(self.record)

        def update_invoice(self, record_id, patch):
            assert record_id == "scan-1"
            events.append("update")
            self.record.update(patch)
            return dict(self.record)

        def get_invoice(self, record_id):
            return dict(self.record) if record_id == "scan-1" else None

    class Archive:
        folders = [{"path": str(folder)}]

        @staticmethod
        def archive_processed_file(path, invoice_date):
            events.append("archive")
            if not invoice_date:
                return str(path)
            target = folder / invoice_date[:4] / Path(path).name
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(str(path), str(target))
            return str(target)

    def _ask(*args):
        events.append("prompt")
        prompt_calls.append(args)
        return 2024, True

    monkeypatch.setattr(QInputDialog, "getInt", _ask)
    app = App()
    view = SimpleNamespace(_app=app, _watch=Archive())

    for index, invalid_date in enumerate(("", "not-a-date")):
        source = folder / f"invoice-{index}.pdf"
        source.write_bytes(b"original")
        data = {
            "supplier": "Pilkington",
            "invoice_number": str(index),
            "date": invalid_date,
            "attachment": str(source),
        }
        start = len(events)
        assert ScanImportView._save_invoice(
            view, data, source=str(source), silent=True
        )
        assert events[start:] == ["register", "prompt", "archive", "update"]
        assert app.record["date"] == ""
        assert app.record["attachment"] == str(
            folder / "2024" / source.name
        )
        assert not source.exists()
        assert Path(app.record["attachment"]).is_file()
        assert data["attachment"] == app.record["attachment"]

    assert len(prompt_calls) == 2


def test_scan_import_failed_registration_does_not_prompt_or_archive(
    tmp_path, monkeypatch,
):
    """A failed save leaves the original untouched and never prompts."""
    _qapp()
    from types import SimpleNamespace

    from ui.scan_import_view import QInputDialog, ScanImportView

    folder = tmp_path / "watched"
    folder.mkdir()
    source = folder / "invoice.pdf"
    source.write_bytes(b"original")
    calls = []

    class App:
        def add_invoice(self, _data):
            raise RuntimeError("registration failed")

    class Archive:
        folders = [{"path": str(folder)}]

        @staticmethod
        def archive_processed_file(*args):
            calls.append("archive")
            return ""

    monkeypatch.setattr(
        QInputDialog, "getInt",
        lambda *_args: calls.append("prompt") or (2024, True),
    )
    view = SimpleNamespace(_app=App(), _watch=Archive())
    assert not ScanImportView._save_invoice(
        view,
        {"date": "", "attachment": str(source)},
        source=str(source),
        silent=True,
    )
    assert source.is_file()
    assert calls == []


def test_watch_original_moves_to_invoice_year_on_import(tmp_path):
    """A saved watched invoice is sorted by its invoice date."""
    _qapp()
    app = _YearApp()
    mgr, folder = _year_manager(tmp_path, app)
    ready = []
    mgr.invoice_ready.connect(lambda row, path: ready.append((row, path)))
    _persist_and_archive_emitted(mgr)
    src = folder / "f2023.pdf"
    archived = folder / "2023" / src.name
    src.write_bytes(b"%PDF-2023")
    mgr.scan_all()
    assert len(ready) == 1
    row, emitted = ready[0]
    assert not src.exists()
    assert archived.is_file()
    assert emitted == str(src)
    assert row["_path"] == str(src)
    assert app._invoices[0]["attachment"] == str(archived)
    processed = next(iter(mgr._config["processed"].values()))
    assert processed["path"] == str(archived)
    # Hash-skyddet gäller fortfarande (ingen dubblett)
    mgr.scan_all()
    assert len(ready) == 1


def test_watch_parked_untouched(tmp_path):
    """Parkerade (olärd leverantör) lämnas alltid orörda."""
    _qapp()
    from ui.watch_folders import WatchManager

    folder = tmp_path / "PilkingtonIn"
    folder.mkdir(parents=True, exist_ok=True)
    mgr = WatchManager(
        tmp_path / "watch_folders.json",
        app=_YearApp(),
        extract_fn=lambda path: (YEAR_TEXT, "test"),
        templates_provider=lambda: {},  # ingen mall → parkering
    )
    mgr.set_folders([{"supplier": "Pilkington", "path": str(folder)}])
    parked = []
    mgr.file_parked.connect(lambda info: parked.append(info))
    (folder / "p1.pdf").write_bytes(b"%PDF-parked")
    mgr.scan_all()
    assert len(parked) == 1
    assert (folder / "p1.pdf").exists()  # kvar överst, orörd
    assert not (folder / "2023").exists()


def test_watch_backlog_exact_registered_original_is_year_sorted(tmp_path):
    """A previously registered attachment is safely back-sorted once."""
    _qapp()
    src = tmp_path / "PilkingtonIn" / "gammal.pdf"
    inv = {
        "id": "7", "supplier": "Pilkington",
        "invoice_number": "9911", "date": "2023-06-16",
        "attachment": str(src),
    }
    app = _YearApp([inv])
    mgr, folder = _year_manager(tmp_path, app)
    # set_folders skannar direkt, men filen fanns inte då —
    # lägg den nu och skanna igen.
    src.write_bytes(b"%PDF-old")
    mgr.scan_all()
    archived = folder / "2023" / src.name
    assert not src.exists()
    assert archived.is_file()
    assert inv["attachment"] == str(archived)
    assert app.updated == [("7", {"attachment": str(archived)})]
    # Andra svepet: fortfarande ingenting (idempotent)
    mgr.scan_all()
    assert archived.is_file()
    assert len(app.updated) == 1


def test_watch_backlog_missing_invoice_date_prompts_for_archive_year(
    tmp_path, monkeypatch,
):
    """An exact registered original still asks before fallback sorting."""
    _qapp()
    from ui.watch_folders import QInputDialog

    src = tmp_path / "PilkingtonIn" / "okand.pdf"
    inv = {
        "id": "10", "supplier": "Pilkington",
        "invoice_number": "9911", "date": "not-a-date",
        "attachment": str(src),
    }
    app = _YearApp([inv])
    mgr, folder = _year_manager(tmp_path, app)
    src.write_bytes(b"%PDF-old-invalid-date")
    prompts = []
    monkeypatch.setattr(
        QInputDialog, "getInt",
        lambda *args: prompts.append(args) or (2024, True),
    )

    mgr.scan_all()

    archived = folder / "2024" / src.name
    assert len(prompts) == 1
    assert not src.exists()
    assert archived.is_file()
    assert inv["attachment"] == str(archived)
    assert app.updated == [("10", {"attachment": str(archived)})]


def test_watch_backlog_separator_variant_year_sorted(tmp_path):
    """Slash variants still identify the registered attachment safely."""
    _qapp()
    src = tmp_path / "PilkingtonIn" / "gammal.pdf"
    inv = {
        "id": "9", "supplier": "Pilkington",
        "invoice_number": "9911", "date": "2023-06-16",
        # Som från en Windows-fil dialog: framåtsnedstreck
        "attachment": str(src).replace("\\", "/"),
    }
    app = _YearApp([inv])
    mgr, folder = _year_manager(tmp_path, app)
    src.write_bytes(b"%PDF-old")
    mgr.scan_all()
    archived = folder / "2023" / src.name
    assert not src.exists()
    assert archived.is_file()
    assert inv["attachment"] == str(archived)
    assert app.updated == [("9", {"attachment": str(archived)})]


def test_watch_recursive_scan_and_arkiv_skipped(tmp_path):
    """Filer direkt i <år>/ skannas; Arkiv/ skannas aldrig."""
    _qapp()
    app = _YearApp()
    mgr, folder = _year_manager(tmp_path, app)
    ready = []
    mgr.invoice_ready.connect(lambda row, path: ready.append((row, path)))
    _persist_and_archive_emitted(mgr)
    (folder / "2023").mkdir()
    (folder / "2023" / "direkt.pdf").write_bytes(b"%PDF-dir")
    arkiv = folder / "Arkiv" / "2023"
    arkiv.mkdir(parents=True)
    (arkiv / "betald.pdf").write_bytes(b"%PDF-arkiv")
    mgr.scan_all()
    assert len(ready) == 1
    # Redan rätt årsmapp: registreringen behåller samma sökväg.
    assert ready[0][1] == str(folder / "2023" / "direkt.pdf")
    assert app._invoices[0]["attachment"] == str(
        folder / "2023" / "direkt.pdf"
    )
    mgr.scan_all()
    assert len(ready) == 1


def test_watch_waits_for_file_writes_to_finish(tmp_path, monkeypatch):
    """Growing/replaced files are retried only after a quiet interval."""
    _qapp()
    import ui.watch_folders as watch_ui

    monkeypatch.setattr(watch_ui, "FILE_STABILITY_SECONDS", 0.05)
    mgr, folder = _manager(tmp_path)
    ready = []
    mgr.invoice_ready.connect(lambda row, path: ready.append((row, path)))
    source = folder / "still-copying.pdf"

    source.write_bytes(b"%PDF-partial")
    mgr.scan_all()
    assert ready == []
    assert mgr.last_scan_stats["settling"] == 1

    # A change starts a fresh quiet window; no partial version is parsed.
    source.write_bytes(b"%PDF-complete-invoice")
    mgr.scan_all()
    assert ready == []
    assert mgr.last_scan_stats["settling"] == 1

    time.sleep(0.06)
    mgr.scan_all()
    assert len(ready) == 1
    assert mgr.last_scan_stats["settling"] == 0
    assert mgr.last_scan_at


def test_watch_recursively_registers_subfolder_watchers(tmp_path):
    """New nested folders get event watchers as well as recursive polling."""
    _qapp()
    mgr, folder = _manager(tmp_path)
    nested = folder / "incoming" / "2026"
    nested.mkdir(parents=True)

    mgr._rewatch()
    watched = {Path(path) for path in mgr._watcher.directories()}
    assert folder in watched
    assert nested in watched
    status = mgr.folder_watch_statuses[0]
    assert status["exists"] is True
    assert status["directories"] == 3
    assert status["watched"] == 3


def test_watch_no_date_stays_top(tmp_path):
    """Utan läsbart datum ligger originalet kvar överst, orört."""
    _qapp()
    from ui.watch_folders import WatchManager

    no_date = """\
Pilkington Automotive Sweden AB / AGR
Fakturanr 9911
SUMMA 1 250,00
"""
    folder = tmp_path / "PilkingtonIn"
    folder.mkdir(parents=True, exist_ok=True)
    mgr = WatchManager(
        tmp_path / "watch_folders.json",
        app=_YearApp(),
        extract_fn=lambda path: (no_date, "test"),
        templates_provider=lambda: TEMPLATES,
    )
    mgr.set_folders([{"supplier": "Pilkington", "path": str(folder)}])
    ready, parked = [], []
    mgr.invoice_ready.connect(lambda row, path: ready.append((row, path)))
    _persist_and_archive_emitted(mgr)
    (folder / "f0.pdf").write_bytes(b"%PDF-nodate")
    mgr.scan_all()
    # Utan datum saknas "belopp"? Nej — SUMMA ger belopp; utan
    # datum kan filen ändå sakna fält → allt hanteras som förut.
    if ready:
        _row, emitted = ready[0]
        assert emitted == str(folder / "f0.pdf")
        assert (folder / "f0.pdf").exists()


# ── Kopplingsdialogen: leverantör väljs, skrivs inte ────────

def test_watch_dialog_supplier_picked_not_typed(tmp_path):
    """Leverantören i bevaka-mapp-dialogen ska VÄLJAS ur
    registret — fri text ("AAG Automotive" i stället för
    registerpostens "AAG Automotive AB") gjorde att
    kopplingen aldrig tog. Mappens namn spelar ingen roll,
    bara registerposten man kopplar till."""
    _qapp()
    from ui.watch_folders import WatchFolderDialog

    dlg = WatchFolderDialog(
        None, ["AAG Automotive AB", "Pilkington"]
    )
    try:
        assert not dlg._cmb_supplier.isEditable()
        dlg._cmb_supplier.setCurrentText("AAG Automotive AB")
        dlg._edit_path.setText(str(tmp_path))
        dlg._accept()
        assert dlg.result_data == {
            "supplier": "AAG Automotive AB",
            "path": str(tmp_path),
        }
    finally:
        dlg.close()


def test_save_never_clobbers_folders_with_empty(tmp_path):
    """En WatchManager som aldrig satt mappar själv får inte
    skriva över mappar på disk med tom lista (skyddet mot att
    bevakningen "tappade" mappen mellan sessioner). Uttrycklig
    borttagning via set_folders gäller däremot alltid."""
    import json

    cfg = tmp_path / "watch_folders.json"
    folder = tmp_path / "MartinIn"
    folder.mkdir()
    cfg.write_text(json.dumps({
        "folders": [{"supplier": "Pilkington",
                     "path": str(folder)}],
        "auto_create": True, "processed": {}, "parked": [],
    }), encoding="utf-8")

    mgr, _f = _manager(tmp_path)
    # _manager skapar en manager mot ny config — bygg vår egen
    from ui.watch_folders import WatchManager
    mgr = WatchManager(
        cfg, app=FakeApp(),
        extract_fn=lambda path: (TEXT, "test"),
        templates_provider=lambda: TEMPLATES,
    )
    assert mgr.folders  # mappen laddades från disk
    # Spara utan att ha rört mapparna → de blir kvar
    mgr._save()
    on_disk = json.loads(cfg.read_text(encoding="utf-8"))
    assert on_disk["folders"], "mapparna skrevs över med tom lista!"
    # Uttrycklig borttagning gäller
    mgr.set_folders([])
    on_disk = json.loads(cfg.read_text(encoding="utf-8"))
    assert on_disk["folders"] == []


def test_watch_scan_stats_distinguishes_new_from_duplicates(tmp_path):
    """Skanningsbeskedet måste skilja nyregistrerade från dubblettar:
    'bearbetad' ensamt säger ingenting — en faktura som redan finns
    i registret (t.ex. exporterad → Arkiverad) skapar ingen ny rad
    och ska räknas som dubblett, inte som ny faktura."""
    _qapp()
    mgr, folder = _manager(
        tmp_path,
        invoices=[{"supplier": "Pilkington", "invoice_number": "9911",
                   "status": "Arkiverad"}],
    )
    (folder / "dup.pdf").write_bytes(b"%PDF-dup")
    mgr.scan_all()
    stats = mgr.last_scan_stats
    assert stats["imported"] == 0
    assert stats["duplicate"] == 1
    assert stats["parked"] == 0
    # Samma fil igen → redan bearbetad sedan tidigare (hash-skyddet)
    mgr.scan_all()
    stats = mgr.last_scan_stats
    assert stats["duplicate"] == 0
    assert stats["already"] == 1

    # Ny komplett faktura räknas som nyregistrerad
    mgr2, folder2 = _manager(tmp_path / "b")
    (folder2 / "ny.pdf").write_bytes(b"%PDF-ny")
    mgr2.scan_all()
    stats2 = mgr2.last_scan_stats
    assert stats2["imported"] == 1
    assert stats2["duplicate"] == 0


def test_watch_file_read_error_does_not_stop_batch_or_touch_original(tmp_path):
    """One unreadable source is reported and retried; later files in the
    same watched folder still register and all source bytes stay intact."""
    _qapp()
    mgr, folder = _manager(tmp_path)
    broken = folder / "broken.pdf"
    good = folder / "good.pdf"
    broken_bytes = b"%PDF-broken-original"
    good_bytes = b"%PDF-good-original"
    broken.write_bytes(broken_bytes)
    good.write_bytes(good_bytes)

    unreadable = {broken.name}

    def extract(path):
        if path.name in unreadable:
            raise OSError("simulated unreadable PDF")
        return TEXT, "test"

    mgr._extract_fn = extract
    changes = []
    recovered = []
    mgr.changed.connect(lambda: changes.append(True))
    ready = []
    file_errors = []
    mgr.invoice_ready.connect(lambda row, path: ready.append((row, path)))
    mgr.file_error.connect(file_errors.append)
    mgr.file_recovered.connect(recovered.append)
    _persist_emitted(mgr)

    mgr.scan_all()
    stats = mgr.last_scan_stats
    assert stats["errors"] == 1
    assert stats["imported"] == 1
    assert len(file_errors) == 1
    assert file_errors[0]["parsed"]["_scan_error"] is True
    assert [row["invoice_number"] for row, _path in ready] == ["9911"]
    assert Path(ready[0][1]) == good
    assert broken.read_bytes() == broken_bytes
    assert good.read_bytes() == good_bytes
    assert all(
        info.get("path") != str(broken)
        for info in mgr.processed.values()
    )

    # The bad source is not marked processed and is retried next time.
    # Once it becomes readable, the error status is cleared; because its
    # invoice already exists, it is safely recorded as a duplicate.
    unreadable.clear()
    mgr.scan_all()
    assert mgr.last_scan_stats["errors"] == 0
    assert mgr.last_scan_stats["already"] == 1
    assert mgr.last_scan_stats["duplicate"] == 1
    assert len(ready) == 1
    assert str(broken) in recovered
    assert len(changes) >= 2


def test_watch_hash_error_isolated_from_later_files(tmp_path, monkeypatch):
    _qapp()
    import ui.watch_folders as watch_ui

    mgr, folder = _manager(tmp_path)
    broken = folder / "broken.pdf"
    good = folder / "good.pdf"
    original = b"%PDF-hash-error-original"
    broken.write_bytes(original)
    good.write_bytes(b"%PDF-good-after-hash-error")
    real_hash = watch_ui.file_hash

    def flaky_hash(path):
        if Path(path).name == broken.name:
            raise OSError("simulated hash read error")
        return real_hash(path)

    monkeypatch.setattr(watch_ui, "file_hash", flaky_hash)
    _persist_emitted(mgr)
    mgr.scan_all()
    assert mgr.last_scan_stats["errors"] == 1
    assert mgr.last_scan_stats["imported"] == 1
    assert broken.read_bytes() == original
    assert all(
        info.get("path") != str(broken)
        for info in mgr.processed.values()
    )


def test_watch_ocr_degraded_invoice_is_parked_not_auto_registered(tmp_path):
    _qapp()
    mgr, folder = _manager(tmp_path)
    source = folder / "ocr-warning.pdf"
    original = b"%PDF-ocr-warning-original"
    source.write_bytes(original)
    calls = []

    def extract(path):
        calls.append(path)
        return TEXT, "textlager-pypdf+ocr-saknas"

    mgr._extract_fn = extract
    ready, parked = [], []
    mgr.invoice_ready.connect(lambda row, path: ready.append(row))
    mgr.file_parked.connect(parked.append)

    mgr.scan_all()
    assert not ready
    assert len(parked) == 1
    assert parked[0]["reason"] == "ocr-warning"
    assert "ocr-saknas" in parked[0]["parsed"]["ocr_warning"]
    assert mgr.last_scan_stats["parked"] == 1
    assert source.read_bytes() == original

    # Ordinary scans do not OCR-loop a parked invoice.
    mgr.scan_all()
    assert mgr.last_scan_stats["waiting"] == 1
    assert len(calls) == 1


def test_watch_control_read_error_is_counted_without_changing_invoice(
    tmp_path,
):
    _qapp()
    mgr, folder = _manager(tmp_path)
    source = folder / "invoice.pdf"
    original = b"%PDF-control-original"
    source.write_bytes(original)
    _persist_emitted(mgr)
    mgr.scan_all()
    assert mgr.last_scan_stats["imported"] == 1
    before = list(mgr._app.get_invoices())

    def fail_extract(_path):
        raise OSError("simulated control read failure")

    mgr._extract_fn = fail_extract
    mgr.scan_all(force=True)
    assert mgr.last_scan_stats["errors"] == 1
    assert mgr._app.get_invoices() == before
    assert source.read_bytes() == original
    assert mgr.processed


def test_overdue_chip_shows_unpaid_overdue_only(tmp_path):
    """Förfallna-filtret: obetald + passerat datum visas; arkiverad
    (redan exporterad) visas ALDRIG — det är hela poängen med
    filtret. En skannad obetald faktura med gammalt förfallodatum
    ska alltså synas här."""
    import datetime as _dt

    from ui.invoices_helpers import due_window_filter
    today = _dt.date(2026, 10, 19)
    rows = [
        {"status": "Obetald", "due_date": "2024-05-01"},   # skannad, gammal
        {"status": "Arkiverad", "due_date": "2024-05-01"},  # exporterad
        {"status": "Betald", "due_date": "2024-05-01"},
        {"status": "Obetald", "due_date": "2026-12-01"},   # ej förfallen än
        {"status": "Obetald", "due_date": ""},             # saknar datum
    ]
    out = due_window_filter(rows, "overdue", today)
    assert out == [rows[0]]


def test_watch_unprocess_retries_after_failed_registration(tmp_path):
    """Om registreringen av en tolkad faktura misslyckas får filen
    inte bli kvar som 'importerad' i bearbetade-registret — då
    skulle fakturan vara osynlig OCH aldrig prövas igen. unprocess
    markerar om filen så nästa skanning gör ett nytt försök."""
    _qapp()
    mgr, folder = _manager(tmp_path)
    ready = []
    mgr.invoice_ready.connect(lambda row, path: ready.append(row))
    (folder / "f1.pdf").write_bytes(b"%PDF-fake-1")
    mgr.scan_all()
    assert len(ready) == 1
    assert ready[0].get("_hash")  # hash följer med för ommarkering
    digest = next(iter(mgr.processed))
    mgr.unprocess(digest)
    assert digest not in mgr.processed
    mgr.scan_all()
    assert len(ready) == 2
    assert mgr.last_scan_stats["imported"] == 1


def test_watch_heals_import_marked_file_without_invoice(tmp_path):
    """Självläkning: en fil som står som importerad i bearbetade-
    registret men saknar faktura i registret (äldre version kunde
    markera före bekräftad sparning) prövas igen vid skanning —
    den får inte vara borta för alltid. Finns fakturan däremot i
    registret med originalets sökväg rörs ingenting."""
    _qapp()
    mgr, folder = _manager(tmp_path)  # fejk-register utan fakturor
    ready = []
    mgr.invoice_ready.connect(lambda row, path: ready.append(row))
    (folder / "f1.pdf").write_bytes(b"%PDF-fake-1")
    mgr.scan_all()
    assert len(ready) == 1
    # Registret fick aldrig fakturan (fejk-appen sparar inget
    # här) → nästa skanning måste pröva registreringen igen
    mgr.scan_all()
    assert len(ready) == 2
    assert mgr.last_scan_stats["imported"] == 1

    # En separat kopia med ett redan registrerat fakturanummer får
    # inte ta över registerpostens ursprungliga attachment-sökväg.
    final = folder / "f1.pdf"
    assert final.is_file()  # första testet simulerade ingen sparning
    mgr2, _f2 = _manager(
        tmp_path / "b",
        invoices=[{"supplier": "Pilkington",
                   "invoice_number": "5555",
                   "attachment": str(final)}],
    )
    import shutil as _sh
    src_dir = tmp_path / "b" / "PilkingtonIn"
    _sh.copy(final, src_dir / "f1.pdf")
    ready2 = []
    mgr2.invoice_ready.connect(lambda row, path: ready2.append(row))
    mgr2.scan_all()
    assert len(ready2) == 1  # ny faktura (annat nummer) registreras
    mgr2.scan_all()
    assert len(ready2) == 1  # ingen omprövning — sökvägen finns ju
    assert mgr2.last_scan_stats["already"] == 1


def test_watch_review_parked_registers_when_auto_enabled(tmp_path):
    """Filer som parkerades BARA för att auto-registreringen var
    AV får inte fastna: så fort den slås PÅ prövas de och (om
    formatet läses) registreras de. Tidigare prövades parkerade
    bara vid ändrat mall-fingeravtryck — review-filer var fast
    i evighet trots att skanningarna såg helt tomma ut."""
    _qapp()
    mgr, folder = _manager(tmp_path, auto=False)
    ready, parked = [], []
    mgr.invoice_ready.connect(lambda row, path: ready.append(row))
    _persist_emitted(mgr)
    mgr.file_parked.connect(lambda info: parked.append(info))
    (folder / "f.pdf").write_bytes(b"%PDF-review")
    mgr.scan_all()
    assert not ready and len(parked) == 1
    assert parked[0]["reason"] == "review"
    # Ny skanning med auto fortfarande AV: filen ska RÄKNAS som
    # väntande (aldrig tyst hoppad över med 0 i statistiken)
    ready.clear()
    mgr.scan_all()
    assert not ready
    assert mgr.last_scan_stats["waiting"] == 1
    # Slå PÅ auto → omgården släpps (skanningen körs i bakgrunden)
    mgr.set_auto_create(True)
    assert _await_scan(mgr)
    assert len(ready) == 1
    assert not mgr.parked
    assert mgr.last_scan_stats["waiting"] == 0


TEXT_2024 = """\
MARTIN G ANDERSON
FAKTURA
Fakturanr. Fakturadatum Kundnr.
916336 2024-05-08 103
Förfallodatum: 2024-06-07
001 1 438 x 743 0,50 6,51 382,50 382,50
Total vikt Totalt antal Total yta (m2) Summa netto Moms Öresavrundning Att betala
6,51 1 0,50 382,50 95,63 0,13 SEK 478,00
Org nr 556824-5806
Bankgiro: 728-0811
"""


def test_watch_new_martin_g_layout_registers(tmp_path):
    """Hela kedjan: Martin G:s 2024-layout (916336) i bevakad
    mapp registreras automatiskt via det inbyggda formatets
    nedanläsning — fakturanummer, datum, förfallo och Att
    betala 478,00 ur sina kolumner. Status blir Obetald (inte
    betald) så användaren själv väljer ihopslagning/export."""
    from ui.watch_folders import WatchManager

    _qapp()
    folder = tmp_path / "gewgg"
    folder.mkdir()

    class App2024(FakeApp):
        def get_suppliers(self):
            return [{
                "name": "AB Martin G Anderson",
                "org_number": "556824-5806", "bg": "728-0811",
            }]

    mgr = WatchManager(
        tmp_path / "watch_folders.json",
        app=App2024(),
        extract_fn=lambda path: (TEXT_2024, "test"),
        templates_provider=lambda: {},
    )
    mgr.set_folders([{"path": str(folder), "supplier": "Martin G"}])
    ready: list[dict] = []
    mgr.invoice_ready.connect(lambda row, path: ready.append(row))
    (folder / "916336.pdf").write_bytes(b"%PDF-fake")

    mgr.scan_all()

    assert not mgr.parked
    (inv,) = ready
    assert inv["invoice_number"] == "916336"
    assert inv["total_amount"] == 478.00
    assert inv["date"] == "2024-05-08"
    assert inv["due_date"] == "2024-06-07"
    # Status sätts vid registreringen i vyn (alltid Obetald).


def test_watch_possible_duplicate_parked_not_registered(tmp_path):
    """Möjlig dubblett (9912 mot registrerad 9911, samma belopp/
    datum) parkeras med varning — registreras aldrig automatiskt."""
    _qapp()
    from ui.watch_folders import _park_reason_sv

    mgr, folder = _manager(
        tmp_path,
        invoices=[{
            "supplier": "Pilkington", "invoice_number": "9911",
            "total_amount": 1250.0, "date": "2026-09-01",
            "status": "Obetald",
        }],
        text=TEXT.replace("9911", "9912"),
    )
    ready, parked = [], []
    mgr.invoice_ready.connect(lambda row, path: ready.append(row))
    mgr.file_parked.connect(lambda info: parked.append(info))
    (folder / "igen.pdf").write_bytes(b"%PDF-igen")
    mgr.scan_all()
    assert not ready
    assert len(parked) == 1
    assert parked[0]["reason"].startswith("possible-duplicate:")
    assert "möjlig dubblett" in _park_reason_sv(parked[0]["reason"])


def test_watch_parked_interpretation_files_never_rescanned(tmp_path):
    """Krav: parkerade tolkningsfiler (mall saknas) tolkas EN gång.

    Hur många skanningar som än körs ska filen ligga still i
    parkeringen — ingen ny tolkning och ingen ny parkerings-
    händelse (dialog) för samma fil.
    """
    _qapp()
    from ui.watch_folders import WatchManager

    calls = {"n": 0}

    def extract(path):
        calls["n"] += 1
        return TEXT, "test"

    folder = tmp_path / "PilkingtonIn"
    folder.mkdir(parents=True, exist_ok=True)
    mgr = WatchManager(
        tmp_path / "watch_folders.json",
        app=FakeApp(),
        extract_fn=extract,
        templates_provider=lambda: {},   # ingen mall → no-template
    )
    mgr.set_folders([{"supplier": "Pilkington", "path": str(folder)}])
    parked_events = []
    mgr.file_parked.connect(lambda info: parked_events.append(info))
    (folder / "f1.pdf").write_bytes(b"%PDF-fake-1")

    mgr.scan_all()
    assert len(mgr.parked) == 1
    assert mgr.parked[0]["reason"] == "no-template"
    assert calls["n"] == 1 and len(parked_events) == 1

    mgr.scan_all()
    mgr.scan_all()
    assert calls["n"] == 1            # aldrig tolkad igen
    assert len(parked_events) == 1    # ingen ny varning för samma fil
    assert len(mgr.parked) == 1


def test_watch_control_scan_flags_diff_without_touching(tmp_path):
    """Kontrollskanning (force) läser om redan bearbetade filer:
    en faktura vars registrerade belopp avviker från originalet
    flaggas som avvikelse — men registret ändras ALDRIG av
    kontrollen, och en vanlig skanning ser den som bearbetad."""
    _qapp()
    mgr, folder = _manager(tmp_path)
    _persist_emitted(mgr)
    (folder / "f1.pdf").write_bytes(b"%PDF-fake-1")
    mgr.scan_all()
    inv = mgr._app._invoices[0]
    inv.update({
        "total_amount": 70117.0,           # felregistrerat belopp
        "date": "2026-09-01", "due_date": "2026-10-01",
    })
    # Vanlig skanning: filen är bearbetad och hoppas över
    mgr.scan_all()
    assert mgr.last_scan_stats["changed"] == 0
    assert mgr.last_scan_stats["already"] == 1
    # Kontrollskanning: tolkar om och flaggar avvikelsen
    mgr.scan_all(force=True)
    assert mgr.last_scan_stats["changed"] == 1
    diffs = mgr.last_control_diffs
    assert len(diffs) == 1
    assert diffs[0]["invoice_number"] == "9911"
    assert diffs[0]["changes"]["total_amount"] == [70117.0, 1250.0]
    # Registret orört — rättning är användarens beslut
    assert mgr._app._invoices[0]["total_amount"] == 70117.0


def test_watch_control_check_missing_invoice_unprocesses(tmp_path):
    """Kontroll av en bearbetad fil vars faktura försvunnit ur
    registret: markeringen tas bort (handled=False) så filen
    kan läsas in på nytt i stället för att vara borta för
    alltid."""
    _qapp()
    mgr, folder = _manager(tmp_path)
    _persist_emitted(mgr)
    f = folder / "f1.pdf"
    f.write_bytes(b"%PDF-fake-1")
    mgr.scan_all()
    assert len(mgr._app._invoices) == 1
    mgr._app._invoices.clear()
    digest = next(iter(mgr._config["processed"]))
    handled = mgr._control_check_file(
        mgr._scan_module(), mgr.folders[0], f, digest
    )
    assert handled is False
    assert digest not in mgr._config["processed"]


def test_watch_unchanged_files_are_not_rehashed_on_every_poll(
    tmp_path, monkeypatch,
):
    """En vanlig poll får inte hasha om tusentals oförändrade original.

    Hash-cachen är det som gör 30-sekunderspollningen billig: samma
    filversion läses en gång, därefter räcker storlek/tid.
    """
    _qapp()
    import ui.watch_folders as watch_ui

    mgr, folder = _manager(tmp_path)
    _persist_emitted(mgr)
    (folder / "f1.pdf").write_bytes(b"%PDF-fake-1")
    mgr.scan_all()
    assert mgr.last_scan_stats["imported"] == 1

    calls = {"n": 0}
    real_hash = watch_ui.file_hash

    def counting_hash(path):
        calls["n"] += 1
        return real_hash(path)

    monkeypatch.setattr(watch_ui, "file_hash", counting_hash)
    mgr.scan_all()
    first_poll = calls["n"]
    mgr.scan_all()
    assert calls["n"] == first_poll, "oförändrad fil hashas om igen"
    assert mgr.last_scan_stats["already"] == 1


def test_watch_registered_file_skips_write_settling(tmp_path, monkeypatch):
    """Ett redan inläst original ska inte räknas som 'skrivs fortfarande'.

    Stabilitetsfönstret behövs bara för filer som inte redan är
    registrerade — annars visade statusraden tusentals väntande filer
    vid varje omstart.
    """
    _qapp()
    import ui.watch_folders as watch_ui

    mgr, folder = _manager(tmp_path)
    _persist_emitted(mgr)
    src = folder / "f1.pdf"
    src.write_bytes(b"%PDF-fake-1")
    mgr.scan_all()
    assert mgr.last_scan_stats["imported"] == 1

    monkeypatch.setattr(watch_ui, "FILE_STABILITY_SECONDS", 30.0)
    mgr.scan_all()
    assert mgr.last_scan_stats["already"] == 1
    assert mgr.last_scan_stats["settling"] == 0


def test_watch_background_scan_does_not_block_caller(
    tmp_path, monkeypatch,
):
    """start_scan() ska återvända direkt; tolkningen sker i arbetstråd."""
    _qapp()
    from PySide6.QtCore import QThreadPool

    import ui.watch_folders as watch_ui

    mgr, folder = _manager(tmp_path)
    _persist_emitted(mgr)
    # Låt mappens första (automatiska) skanning bli klar först.
    _await_scan(mgr)
    (folder / "f1.pdf").write_bytes(b"%PDF-fake-1")

    def slow_parse(*_args, **_kwargs):
        time.sleep(0.35)
        return ("", "test", {
            "supplier": "Pilkington",
            "invoice_number": "9911",
            "date": "2026-09-01",
            "due_date": "2026-10-01",
            "total_amount": 1250.0,
            "missing": [],
            "template": "Pilkington",
        })

    monkeypatch.setattr(watch_ui, "parse_watched_file", slow_parse)
    finished = []
    mgr.scan_finished.connect(lambda stats: finished.append(stats))

    started = time.monotonic()
    mgr.start_scan()
    elapsed = time.monotonic() - started
    assert elapsed < 0.2, f"start_scan blockerade i {elapsed:.2f} s"
    assert mgr.is_scanning

    assert _await_scan(mgr)
    QThreadPool.globalInstance().waitForDone(5000)

    assert finished, "bakgrundsskanningen avslutades aldrig"
    assert not mgr.is_scanning
    assert finished[-1]["imported"] == 1
    assert mgr._app._invoices
