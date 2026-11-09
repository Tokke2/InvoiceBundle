# -*- coding: utf-8 -*-
"""Per-leverantör-arkiv för exporterade/betalda fakturor.

En egen JSON-fil per leverantör i data/betalda/ i stället för allt
i en enda invoices.json. Fakturor-fliken läser bara huvudfilen;
Historik-fliken arkivet. Vid import/skanning söks BÅDA registren
igenom (dubblettskyddet gäller även redan betalda).
"""
import importlib.util
import json
import sys
from pathlib import Path



ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_appmod():
    spec = importlib.util.spec_from_file_location(
        "appmod_archive_test", ROOT / "app.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


appmod = _load_appmod()


def _engine(tmp_path):
    """Motor på tmp-disk: huvudstore + riktigt filarkiv."""
    db = tmp_path / "db"
    db.mkdir()
    changelog = appmod.ChangeLog(db / "changelog.json")
    store = appmod.DataStore(
        "invoices", db, appmod.INVOICE_SCHEMA, changelog
    )
    archive = appmod.SupplierArchiveStore(db / "betalda", changelog)
    return appmod.InvoiceEngine(store, archive), store, archive, db


def test_archive_move_on_export_status(tmp_path):
    eng, store, archive, db = _engine(tmp_path)
    inv = eng.add({
        "supplier": "Martin G Anderson",
        "invoice_number": "906178",
        "total_amount": 3491.0,
        "date": "2023-06-16",
        "due_date": "2023-07-16",
    })
    assert store.count() == 1 and archive.count() == 0

    out = eng.update(
        inv["id"],
        {"status": "Arkiverad", "payment_date": "2023-08-01"},
    )
    assert out is not None and out["status"] == "Arkiverad"
    # Övriga fält i samma anrop tappas inte i arkivflytten
    assert out["payment_date"] == "2023-08-01"
    # Posten har FLYTTAT: huvudfilen tom, arkivet har den
    assert store.count() == 0
    assert archive.count() == 1
    assert store.all() == []
    assert len(eng.main_records()) == 0
    assert len(eng.archived_records()) == 1
    # Filen på disk: en per leverantör, slugifierat namn
    path = db / "betalda" / "martin-g-anderson.json"
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert [r["invoice_number"] for r in on_disk] == ["906178"]
    # Båda registren läsbara genom motorn (import/dubblettsyn)
    assert eng.get(inv["id"])["invoice_number"] == "906178"
    assert len(eng.all()) == 1
    assert eng.count() == 1
    # Dubblettkontrollen hittar den arkiverade
    hits = eng.check_duplicate_number("906178", "Martin G Anderson")
    assert len(hits) == 1
    # ATT BETALA påverkas aldrig av arkivet
    assert eng.att_betala() == 0.0


def test_mark_paid_stays_in_main_until_export(tmp_path):
    """Beslutad semantik: Markera betald ensam flyttar INTE;
    flytten till leverantörsfilen sker först vid export
    (status Arkiverad)."""
    eng, store, archive, db = _engine(tmp_path)
    a = eng.add({"supplier": "Pilkington", "invoice_number": "1",
                 "total_amount": 100.0})
    b = eng.add({"supplier": "Pilkington", "invoice_number": "2",
                 "total_amount": 200.0})
    assert eng.mark_paid([a["id"]], "2026-01-15") == 1
    # Betald-markeringen stannar i huvudfilen
    assert store.count() == 2
    assert archive.count() == 0
    rec = eng.get(a["id"])
    assert rec["status"] == "Betald"
    assert rec["payment_date"] == "2026-01-15"
    # Först vid export flyttar posterna
    assert eng.mark_archived([a["id"], b["id"]]) == 2
    assert store.count() == 0
    assert archive.count() == 2
    by_nr = {
        r["invoice_number"]: r for r in eng.archived_records()
    }
    assert by_nr["1"]["status"] == "Arkiverad"
    assert by_nr["1"]["payment_date"] == "2026-01-15"
    files = {p.name for p in (db / "betalda").glob("*.json")}
    assert files == {"pilkington.json"}


def test_mark_exported_paid_moves_as_paid_with_date(tmp_path):
    """Exporterade fakturor: status Betald + exportens
    betalningsdatum, flyttade till leverantörens JSON i
    data/betalda/ — borta ur huvudregistret (exporteras aldrig
    igen) men fortfarande synliga för dubblettskyddet."""
    import json as _json

    eng, store, archive, db = _engine(tmp_path)
    a = eng.add({"supplier": "Pilkington", "invoice_number": "1",
                 "total_amount": 100.0})
    b = eng.add({"supplier": "Pilkington", "invoice_number": "2",
                 "total_amount": -40.0})
    assert eng.mark_exported_paid(
        [a["id"], b["id"]], "2026-09-18"
    ) == 2
    assert store.count() == 0
    assert archive.count() == 2
    assert eng.main_records() == []
    by_nr = {
        r["invoice_number"]: r for r in eng.archived_records()
    }
    assert by_nr["1"]["status"] == "Betald"
    assert by_nr["1"]["payment_date"] == "2026-09-18"
    assert by_nr["2"]["status"] == "Betald"
    # Filen på disk: en per leverantör, status Betald
    path = db / "betalda" / "pilkington.json"
    assert path.is_file()
    on_disk = _json.loads(path.read_text(encoding="utf-8"))
    assert {r["status"] for r in on_disk} == {"Betald"}
    # Dubblettskyddet hittar de exporterade — ingen omregistrering
    assert len(eng.check_duplicate_number("1", "Pilkington")) == 1
    assert eng.att_betala() == 0.0


def test_restore_from_archive_returns_to_main(tmp_path):
    eng, store, archive, db = _engine(tmp_path)
    inv = eng.add({"supplier": "AAG Automotive AB",
                   "invoice_number": "1019", "total_amount": 6344.0})
    eng.mark_archived([inv["id"]])
    assert store.count() == 0 and archive.count() == 1
    assert eng.restore_from_archive([inv["id"]]) == 1
    assert store.count() == 1 and archive.count() == 0
    rec = eng.get(inv["id"])
    assert rec["status"] == "Obetald"
    # Tom leverantörsfil tas bort
    assert not list((db / "betalda").glob("*.json"))


def test_archive_update_in_place_and_delete(tmp_path):
    eng, store, archive, db = _engine(tmp_path)
    inv = eng.add({"supplier": "Direktglas", "invoice_number": "77",
                   "total_amount": 500.0})
    eng.mark_archived([inv["id"]])
    upd = eng.update(inv["id"], {"payment_date": "2026-02-01"})
    assert upd["payment_date"] == "2026-02-01"
    assert archive.count() == 1 and store.count() == 0
    assert eng.delete(inv["id"]) is True
    assert archive.count() == 0
    assert eng.get(inv["id"]) is None


def test_archive_search_covers_both_registers(tmp_path):
    eng, store, archive, db = _engine(tmp_path)
    a = eng.add({"supplier": "Swede Glass United",
                 "invoice_number": "19072", "total_amount": 706.0})
    eng.add({"supplier": "Swede Glass United",
             "invoice_number": "19073", "total_amount": 100.0})
    eng.mark_archived([a["id"]])
    hits = eng.search("19072")
    assert [r["invoice_number"] for r in hits] == ["19072"]
    assert len(eng.search("1907")) == 2


def test_migration_moves_existing_paid_and_exported(tmp_path):
    """Befintliga Arkiverad/Betald i huvudfilen flyttas till
    leverantörsfiler; obetalda stannar. Samma loop som
    FakturaApp._migrate_invoice_archive kör vid start."""
    eng, store, archive, db = _engine(tmp_path)
    eng.add({"supplier": "Martin G Anderson", "invoice_number": "U1",
             "total_amount": 10.0, "status": "Obetald"})
    # Lägg betalda/exporterade direkt i huvudstoren (gammalt läge)
    store.add({"supplier": "Martin G Anderson",
               "invoice_number": "E1", "total_amount": 20.0,
               "status": "Arkiverad"})
    store.add({"supplier": "Pilkington", "invoice_number": "B1",
               "total_amount": 30.0, "status": "Betald"})
    main = [
        r for r in store.all()
        if r.get("status") in appmod.ARCHIVE_STATUSES
    ]
    assert len(main) == 2
    for rec in main:
        archive.move_in(dict(rec))
        store.delete(str(rec.get("id", "")))
    assert store.count() == 1  # bara den obetalda kvar
    assert archive.count() == 2
    by_sup = {}
    for r in archive.all():
        by_sup.setdefault(r["supplier"], []).append(r["invoice_number"])
    assert by_sup == {
        "Martin G Anderson": ["E1"], "Pilkington": ["B1"],
    }
    # ATT BETALA = bara den obetalda
    assert eng.att_betala() == 10.0


def test_unreadable_archive_file_never_overwritten(tmp_path):
    eng, store, archive, db = _engine(tmp_path)
    arc_dir = db / "betalda"
    broken = arc_dir / "trasig.json"
    broken.write_text("{inte json", encoding="utf-8")
    archive2 = appmod.SupplierArchiveStore(arc_dir)
    # Oläsbar fil: inga poster läses in, filen rörs inte
    assert archive2.by_supplier("Trasig") == []
    assert broken.read_text(encoding="utf-8") == "{inte json"
    # Skrivning till just den leverantören blockeras av skyddet
    archive2.move_in({
        "id": "x1", "supplier": "Trasig", "invoice_number": "9",
        "status": "Arkiverad",
    })
    assert broken.read_text(encoding="utf-8") == "{inte json"


def test_slugify_supplier_names():
    assert appmod._slugify_supplier("Martin G Anderson") == \
        "martin-g-anderson"
    assert appmod._slugify_supplier("AAG Automotive AB") == \
        "aag-automotive-ab"
    assert appmod._slugify_supplier("Årsta Glas Öland") == \
        "arsta-glas-oland"
    assert appmod._slugify_supplier("") == "okand-leverantor"
    assert appmod._slugify_supplier("  ") == "okand-leverantor"


def test_history_filter_and_paid_total():
    from ui.history_view import filter_history, paid_total
    records = [
        {"supplier": "Martin G Anderson", "invoice_number": "1",
         "total_amount": 100.0, "status": "Arkiverad"},
        {"supplier": "Martin G Anderson", "invoice_number": "2",
         "total_amount": -30.0, "status": "Betald"},
        {"supplier": "Pilkington", "invoice_number": "3",
         "total_amount": 50.0, "status": "Arkiverad", "ocr": "12345"},
    ]
    assert len(filter_history(records)) == 3
    assert len(filter_history(records, supplier="Pilkington")) == 1
    assert [r["invoice_number"] for r in
            filter_history(records, query="12345")] == ["3"]
    assert paid_total(records) == 120.0
    assert paid_total(filter_history(records, supplier="Pilkington")) == 50.0


def test_history_view_populates_from_app(tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from ui.history_view import HistoryView

    class _FakeApp:
        def get_archived_invoices(self):
            return [{
                "supplier": "Martin G Anderson",
                "invoice_number": "906178",
                "total_amount": 3491.0, "status": "Arkiverad",
                "date": "2023-06-16", "payment_date": "2023-07-16",
            }]

    view = HistoryView(app=_FakeApp())
    assert view._table.rowCount() == 1
    assert view._table.item(0, 1).text() == "Martin G Anderson"
    assert view._table.item(0, 2).text() == "906178"
    assert not view._lbl_empty.isVisible()
