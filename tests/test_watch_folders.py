# -*- coding: utf-8 -*-
"""
Tester: bevakade leverantörsmappar + original i betal-PDF:en.

En mapp per leverantör bevakas; nya fakturafiler tolkas och kan
registreras automatiskt (kompletta) eller parkeras (ofullständiga/
dubbletter). Samma filinnehåll importeras aldrig två gånger.
Vid PDF-export kan originalfakturorna läggas efter betal-listan.
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
    from ui.watch_folders import WatchManager
    folder = tmp_path / "PilkingtonIn"
    folder.mkdir(parents=True, exist_ok=True)
    mgr = WatchManager(
        tmp_path / "watch_folders.json",
        app=FakeApp(invoices),
        extract_fn=lambda path: (text, "test"),
        templates_provider=lambda: TEMPLATES,
    )
    mgr.set_folders([{"supplier": "Pilkington", "path": str(folder)}])
    if not auto:
        mgr.set_auto_create(False)
    return mgr, folder


def test_watch_complete_invoice_ready_once(tmp_path):
    _qapp()
    mgr, folder = _manager(tmp_path)
    ready, parked = [], []
    mgr.invoice_ready.connect(lambda row, path: ready.append((row, path)))
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


def test_merge_originals_appends_with_divider(tmp_path):
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
    assert result == {"included": 1, "missing": 0, "pages_added": 2}
    assert len(PdfReader(str(base)).pages) == 3  # bas+avdelare+bild
    saknas = merge_originals(
        base, [("x", tmp_path / "finns_inte.pdf")], "Originalfaktura"
    )
    assert saknas["missing"] == 1 and saknas["included"] == 0


def test_exporter_include_originals_flag(tmp_path):
    from PIL import Image
    from pypdf import PdfReader
    from plugins.pdf_export_helpers import PDFExporter
    img = tmp_path / "orig.png"
    Image.new("RGB", (60, 40), (30, 60, 200)).save(img)
    inv = [{
        "supplier": "Pilkington", "invoice_number": "9911",
        "ocr": "9911", "total_amount": 1250.0,
        "due_date": "2026-10-01", "attachment": str(img),
    }]
    exporter = PDFExporter(tmp_path, tmp_path)
    plain = exporter.export_invoice_list(
        [dict(inv[0])], filename="export.pdf", ask_payment_date=False,
        payment_date="2026-09-15", mark_exported=False,
    )
    assert plain["success"]
    pdf_path = plain["file_path"]
    n_plain = len(PdfReader(pdf_path).pages)
    assert not plain.get("attachments_included")
    med = exporter.export_invoice_list(
        [dict(inv[0])], filename="export.pdf", ask_payment_date=False,
        payment_date="2026-09-15", mark_exported=False,
        include_originals=True,
    )
    assert med["success"] and med["attachments_included"] == 1
    assert len(PdfReader(med["file_path"]).pages) == n_plain + 2


def test_watch_untaught_supplier_parked_until_taught(tmp_path):
    """Ingen inlärd mall → aldrig auto, hur komplett allt ser ut.

    Alla leverantörer har egen layout: först när användaren lärt
    appen leverantören (mall sparad och träffar) registrerar
    mappen automatiskt.
    """
    _qapp()
    from ui.watch_folders import WatchManager

    holder = {"templates": {}}
    folder = tmp_path / "PilkingtonIn"
    folder.mkdir(parents=True, exist_ok=True)
    mgr = WatchManager(
        tmp_path / "watch_folders.json",
        app=FakeApp(),
        extract_fn=lambda path: (TEXT, "test"),
        templates_provider=lambda: holder["templates"],
    )
    mgr.set_folders([{"supplier": "Pilkington", "path": str(folder)}])
    ready, parked = [], []
    mgr.invoice_ready.connect(lambda row, path: ready.append(row))
    mgr.file_parked.connect(lambda info: parked.append(info))

    (folder / "f1.pdf").write_bytes(b"%PDF-fake-1")
    mgr.scan_all()
    # Heuristiken hittar allt — men utan inlärd mall: parkera
    assert not ready
    assert len(parked) == 1
    assert parked[0]["reason"] == "no-template"
    assert parked[0]["parsed"]["invoice_number"] == "9911"

    # Användaren lär appen (mall sparas) → nästa fil blir auto
    holder["templates"] = TEMPLATES
    (folder / "f2.pdf").write_bytes(b"%PDF-fake-2")
    mgr.scan_all()
    assert len(ready) == 1
    assert ready[0]["template"] == "Pilkington"
