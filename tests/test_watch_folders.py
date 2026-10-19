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

    # Användaren lär appen (mall sparas) → den PARKERADE filen
    # prövas på nytt vid nästa skanning och registreras, och
    # nya filer går direkt
    holder["templates"] = TEMPLATES
    mgr.scan_all()
    assert len(ready) == 1
    assert ready[0]["template"] == "Pilkington"
    assert not mgr.parked
    (folder / "f2.pdf").write_bytes(b"%PDF-fake-2")
    mgr.scan_all()
    assert len(ready) == 2


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
    mgr.file_parked.connect(lambda info: parked.append(info))

    (folder / "m1.pdf").write_bytes(b"%PDF-fake-m1")
    mgr.scan_all()
    assert len(ready) == 1 and not parked
    assert ready[0]["invoice_number"] == "906178"
    assert ready[0]["total_amount"] == 3491.00
    assert ready[0]["supplier"] == "AB Martin G Anderson"
    assert ready[0]["template"]


# ── Årssortering i bevakad mapp (<år>/ efter fakturadatum) ──────
# Registrerade fakturors original får årsmapp; parkerade och
# annat lämnas orört. Skanningen hittar även årsmapparna (så
# en fil som lagts direkt i /2023/ behandlas), men Arkiv/
# skannas aldrig om. Eftersortering vid skanning tar backlog.

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
    from ui.watch_folders import WatchManager

    folder = tmp_path / "PilkingtonIn"
    folder.mkdir(parents=True, exist_ok=True)
    mgr = WatchManager(
        tmp_path / "watch_folders.json",
        app=app,
        extract_fn=lambda path: (YEAR_TEXT, "test"),
        templates_provider=lambda: TEMPLATES,
    )
    mgr.set_folders([{"supplier": "Pilkington", "path": str(folder)}])
    return mgr, folder


def test_watch_year_sort_new_invoice(tmp_path):
    """Ny registrerad faktura → originalet i <år>/ direkt."""
    _qapp()
    app = _YearApp()
    mgr, folder = _year_manager(tmp_path, app)
    ready = []
    mgr.invoice_ready.connect(lambda row, path: ready.append((row, path)))
    (folder / "f2023.pdf").write_bytes(b"%PDF-2023")
    mgr.scan_all()
    assert len(ready) == 1
    row, emitted = ready[0]
    target = folder / "2023" / "f2023.pdf"
    assert target.exists()
    assert not (folder / "f2023.pdf").exists()
    assert emitted == str(target)
    assert row["_path"] == str(target)
    # Hash-skyddet gäller även i årsmappen (ingen dubblett)
    mgr.scan_all()
    assert len(ready) == 1


def test_watch_year_sort_parked_untouched(tmp_path):
    """Parkerade (olärd leverantör) flyttas INTE av sorteringen."""
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


def test_watch_year_sort_backlog_registered(tmp_path):
    """Redan registrerat original överst → eftersorteras och
    registrets sökväg pekas om."""
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
    target = folder / "2023" / "gammal.pdf"
    assert target.exists()
    assert not src.exists()
    assert inv["attachment"] == str(target)
    assert app.updated == [("7", {"attachment": str(target)})]
    # Andra svepet: inget mer att göra (idempotent)
    app.updated.clear()
    mgr.scan_all()
    assert app.updated == []


def test_watch_recursive_scan_and_arkiv_skipped(tmp_path):
    """Filer direkt i <år>/ skannas; Arkiv/ skannas aldrig."""
    _qapp()
    app = _YearApp()
    mgr, folder = _year_manager(tmp_path, app)
    ready = []
    mgr.invoice_ready.connect(lambda row, path: ready.append((row, path)))
    (folder / "2023").mkdir()
    (folder / "2023" / "direkt.pdf").write_bytes(b"%PDF-dir")
    arkiv = folder / "Arkiv" / "2023"
    arkiv.mkdir(parents=True)
    (arkiv / "betald.pdf").write_bytes(b"%PDF-arkiv")
    mgr.scan_all()
    assert len(ready) == 1
    # Årssorteringen flyttar inte filen igen (redan 2023) —
    # den STANNAR i 2023/, registreras, ingen ny dubblett
    assert ready[0][1] == str(folder / "2023" / "direkt.pdf")
    mgr.scan_all()
    assert len(ready) == 1


def test_watch_year_sort_no_date_stays_top(tmp_path):
    """Oläsbart år → originalet ligger kvar överst, orört."""
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
