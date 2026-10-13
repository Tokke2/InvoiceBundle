from __future__ import annotations

"""
FakturaRäknaren — permanent testsvit (pytest-kompatibel)
================================================================
Fil    : FakturaRäknaren_/tests/test_core.py
Författare : Rickard Längkvist
År     : Dynamiskt (auto)

Permanenta tester (idén från PDF reader Pro SPEC v2.1 §2.12).
Körs på TVÅ sätt:

    pytest tests/                  (om pytest är installerat)
    python tests/test_core.py      (alltid — ingen beroendekrav)

Testerna är hermetiska: alla filoperationer sker i temporära mappar.
Ingen riktig faktura-/leverantörsdata röras.

Copyright © dynamiskt år Rickard Längkvist
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

# Headless-läge ALLTID i tester (Qt får aldrig öppna fönster).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "ui")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

import app as appmod  # noqa: E402
from ui.contrast import (  # noqa: E402
    contrast_ratio, passes_aa, best_text_on, enforce_theme_contrast,
)
from ui.invoices_helpers import (  # noqa: E402
    round_by_mode, PDF_ROUNDING_MODES,
)


# ═════════════════════════════════════════════════════════════════════
#  ATOMÄR SKRIVNING (punkt 1 från PDF reader Pro-genomgången)
# ═════════════════════════════════════════════════════════════════════


def test_save_json_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "data.json"
    payload = {"namn": "värde med åäö", "lista": [1, 2, 3]}
    assert appmod._save_json(p, payload)
    assert json.loads(p.read_text(encoding="utf-8")) == payload


def test_save_json_leaves_no_tmp(tmp_path: Path) -> None:
    p = tmp_path / "ren.json"
    assert appmod._save_json(p, {"a": 1})
    leftovers = [f for f in tmp_path.iterdir() if f.name != "ren.json"]
    assert leftovers == [], f"temporära filer kvar: {leftovers}"


def test_save_json_overwrites_atomically(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    appmod._save_json(p, {"v": 1})
    appmod._save_json(p, {"v": 2})
    assert json.loads(p.read_text(encoding="utf-8")) == {"v": 2}


# ═════════════════════════════════════════════════════════════════════
#  SETTINGS-SCHEMA + AUTO-REPARATION (punkt 2)
# ═════════════════════════════════════════════════════════════════════


def test_validate_settings_repairs_bad_values() -> None:
    raw = {
        "theme": "rosa",           # ogiltigt värde → standard
        "window_width": "800",     # fel typ → standard
        "startup": "ja",           # fel typ (bool) → standard
        "pdf_rounding": "snabb",   # ogiltigt värde → standard
        "okänd_nyckel": 42,        # okänd → behålls
    }
    clean, repairs = appmod.validate_settings(raw)
    assert clean["theme"] == "dark"
    assert clean["window_width"] == 1280
    assert clean["startup"] is False
    assert clean["pdf_rounding"] == "exact"
    assert clean["okänd_nyckel"] == 42
    assert clean["schema_version"] == appmod.SETTINGS_SCHEMA_VERSION
    assert len(repairs) >= 4


def test_validate_settings_keeps_good_values() -> None:
    raw = {"theme": "light", "window_width": 1600, "startup": True}
    clean, repairs = appmod.validate_settings(raw)
    assert clean["theme"] == "light"
    assert clean["window_width"] == 1600
    assert clean["startup"] is True
    assert repairs == []


def test_settings_manager_corrupt_file(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    p.write_text("{ detta är inte json", encoding="utf-8")
    sm = appmod.SettingsManager(p)
    # Standardvärden gäller efter korrupt fil
    assert sm.get("theme") == "dark"
    # Den trasiga filen ska ha namnbytts (inte raderas)
    corrupts = list(tmp_path.glob("settings.json.corrupt-*"))
    assert len(corrupts) == 1
    # Ny, reparerad fil ska vara sparad med schema_version
    sm.save()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["schema_version"] == appmod.SETTINGS_SCHEMA_VERSION


def test_settings_manager_missing_file(tmp_path: Path) -> None:
    sm = appmod.SettingsManager(tmp_path / "nya_settings.json")
    assert sm.get("theme") == "dark"
    assert sm.get("archive_exports_days") == 10


# ═════════════════════════════════════════════════════════════════════
#  WCAG-KONTRAST (punkt 6)
# ═════════════════════════════════════════════════════════════════════


def test_contrast_ratio_extremes() -> None:
    assert abs(contrast_ratio("#000000", "#ffffff") - 21.0) < 0.01
    assert abs(contrast_ratio("#ffffff", "#ffffff") - 1.0) < 0.01
    # Ordningsoberoende
    assert contrast_ratio("#000", "#fff") == contrast_ratio("#fff", "#000")


def test_contrast_aa_detection() -> None:
    assert passes_aa("#0d1117", "#c9d1d9")       # mörkt tema, OK
    assert not passes_aa("#ffffff", "#d0d7de")   # för låg kontrast


def test_best_text_on() -> None:
    assert best_text_on("#0d1117") == "#ffffff"
    assert best_text_on("#ffffff") == "#000000"


def test_enforce_theme_contrast_repairs() -> None:
    theme = {"bg": "#ffffff", "text": "#d0d7de", "text_strong": "#24292f"}
    fixed = enforce_theme_contrast(theme)
    assert passes_aa("#ffffff", fixed["text"])
    assert fixed["text_strong"] == "#24292f"   # redan OK → orörd
    # Originalet orört (kopia returneras)
    assert theme["text"] == "#d0d7de"


# ═════════════════════════════════════════════════════════════════════
#  KORTKOMMANDON (punkt 7)
# ═════════════════════════════════════════════════════════════════════


def test_shortcut_defaults() -> None:
    assert appmod.DEFAULT_SHORTCUTS["ny_faktura"] == "Ctrl+N"
    assert appmod.DEFAULT_SHORTCUTS["tab_fakturor"] == "Ctrl+2"
    # Varje standardgenväg har en etikett
    for action in appmod.DEFAULT_SHORTCUTS:
        assert action in appmod.SHORTCUT_LABELS


def test_shortcut_manager_persistence(tmp_path: Path) -> None:
    p = tmp_path / "shortcuts.json"
    sm = appmod.ShortcutManager(p)
    assert sm.get("ny_faktura") == "Ctrl+N"
    sm.set("ny_faktura", "Ctrl+Shift+N")
    sm2 = appmod.ShortcutManager(p)
    assert sm2.get("ny_faktura") == "Ctrl+Shift+N"
    sm2.reset_all()
    assert sm2.get("ny_faktura") == "Ctrl+N"


def test_shortcut_manager_ignores_unknown_action(tmp_path: Path) -> None:
    sm = appmod.ShortcutManager(tmp_path / "s.json")
    sm.set("finns_inte", "Ctrl+X")        # ska ignoreras utan fel
    assert sm.get("finns_inte") == ""


# ═════════════════════════════════════════════════════════════════════
#  AVRUNDNINGSLÄGEN
# ═════════════════════════════════════════════════════════════════════


def test_round_by_mode_all_modes() -> None:
    assert set(PDF_ROUNDING_MODES) == {"exact", "hel", "50", "100"}
    assert round_by_mode(123.456, "exact") == 123.46
    assert round_by_mode(123.5, "hel") == 124.0
    assert round_by_mode(123.4, "hel") == 123.0
    assert round_by_mode(124.0, "50") == 100.0
    assert round_by_mode(126.0, "50") == 150.0
    assert round_by_mode(149.0, "100") == 100.0
    assert round_by_mode(151.0, "100") == 200.0
    # Krediter behåller tecken
    assert round_by_mode(-123.5, "hel") == -124.0
    # Okänt läge → exact
    assert round_by_mode(123.456, "okänt") == 123.46


# ═════════════════════════════════════════════════════════════════════
#  PLUGIN 3-STRIKES (punkt 11)
# ═════════════════════════════════════════════════════════════════════


def _make_settings(tmp_path: Path) -> appmod.SettingsManager:
    return appmod.SettingsManager(tmp_path / "settings.json")


def test_plugin_strikes_disable_after_three(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    plugdir = tmp_path / "plugins"
    plugdir.mkdir()
    (plugdir / "trasig.py").write_text(
        "raise RuntimeError('krasch')\n", encoding="utf-8"
    )
    loader = appmod.PluginLoader(plugdir, settings)
    loader.load_all()
    assert loader.status()["disabled"] == []
    loader.load_all()
    assert loader.status()["disabled"] == []
    loader.load_all()                            # strike 3
    assert loader.status()["disabled"] == ["trasig"]
    # Fjärde laddningen: pluginet skippar helt
    loader.load_all()
    assert loader.modules == []


def test_plugin_reenable(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    plugdir = tmp_path / "plugins"
    plugdir.mkdir()
    (plugdir / "trasig.py").write_text(
        "raise RuntimeError('x')\n", encoding="utf-8"
    )
    loader = appmod.PluginLoader(plugdir, settings)
    for _ in range(3):
        loader.load_all()
    assert loader.status()["disabled"] == ["trasig"]
    loader.reenable_all()
    status = loader.status()
    assert status["disabled"] == []
    assert status["strikes"] == {}


def test_plugin_success_resets_strikes(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    plugdir = tmp_path / "plugins"
    plugdir.mkdir()
    p = plugdir / "bra.py"
    p.write_text("raise RuntimeError('x')\n", encoding="utf-8")
    loader = appmod.PluginLoader(plugdir, settings)
    loader.load_all()                            # strike 1
    assert loader.status()["strikes"].get("bra") == 1
    p.write_text("OK = True\n", encoding="utf-8")
    loader.load_all()                            # lyckas → räknare nollad
    assert loader.status()["strikes"] == {}


def test_helpers_plugins_never_loaded(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    plugdir = tmp_path / "plugins"
    plugdir.mkdir()
    (plugdir / "pdf_export_helpers.py").write_text(
        "OK = True\n", encoding="utf-8"
    )
    loader = appmod.PluginLoader(plugdir, settings)
    loader.load_all()
    assert loader.modules == []


# ═════════════════════════════════════════════════════════════════════
#  FAKTURAMOTORER (hermetiskt via temp-DataStore)
# ═════════════════════════════════════════════════════════════════════


def _make_invoice_engine(tmp_path: Path):
    db = tmp_path / "db"
    db.mkdir()
    changelog = appmod.ChangeLog(db / "changelog.json")
    store = appmod.DataStore(
        "invoices", db, appmod.INVOICE_SCHEMA, changelog
    )
    return appmod.InvoiceEngine(store)


def test_invoice_type_sync(tmp_path: Path) -> None:
    eng = _make_invoice_engine(tmp_path)
    pos = eng.add({"supplier": "A", "total_amount": 100.0})
    neg = eng.add({"supplier": "B", "total_amount": -50.0})
    assert pos["invoice_type"] == "Faktura"
    assert neg["invoice_type"] == "Kreditfaktura"
    # Typsynk vid uppdatering
    eng.update(pos["id"], {"total_amount": -10.0})
    assert eng.get(pos["id"])["invoice_type"] == "Kreditfaktura"


def test_invoice_sums(tmp_path: Path) -> None:
    eng = _make_invoice_engine(tmp_path)
    eng.add({"supplier": "A", "total_amount": 100.0})
    eng.add({"supplier": "B", "total_amount": -40.0})
    assert eng.total_positive() == 100.0
    assert eng.total_negative() == -40.0
    assert eng.total_amount() == 60.0


def test_invoice_newest_last(tmp_path: Path) -> None:
    eng = _make_invoice_engine(tmp_path)
    r1 = eng.add({"supplier": "A", "total_amount": 1.0})
    r2 = eng.add({"supplier": "B", "total_amount": 2.0})
    order = [r["id"] for r in eng.all()]
    assert order.index(r1["id"]) < order.index(r2["id"])
    # Uppdaterad post hamnar sist (MUST-023)
    eng.update(r1["id"], {"note": "ändrad"})
    order2 = [r["id"] for r in eng.all()]
    assert order2[-1] == r1["id"]


def test_mark_paid_sets_payment_date(tmp_path: Path) -> None:
    eng = _make_invoice_engine(tmp_path)
    rec = eng.add({"supplier": "A", "total_amount": 10.0})
    eng.mark_paid([rec["id"]], payment_date="2026-09-23")
    after = eng.get(rec["id"])
    assert after["status"] == "Betald"
    assert after["payment_date"] == "2026-09-23"


def test_duplicate_detection(tmp_path: Path) -> None:
    eng = _make_invoice_engine(tmp_path)
    eng.add({"supplier": "A", "invoice_number": "123",
             "total_amount": 100.0})
    dup_number = eng.check_duplicate_number("123", "A")
    dup_amount = eng.check_duplicate_amount("A", 100.0)
    assert len(dup_number) == 1
    assert len(dup_amount) == 1


# ═════════════════════════════════════════════════════════════════════
#  STAGETIMER + FREEZEWATCHDOG (punkterna 9–10)
# ═════════════════════════════════════════════════════════════════════


def test_stage_timer_measures() -> None:
    t = appmod.StageTimer("test")
    time.sleep(0.01)
    ms = t.stop()
    assert ms >= 5.0


def test_freeze_watchdog_lifecycle() -> None:
    wd = appmod.FreezeWatchdog(interval=0.05, limit=0.2)
    wd.start()
    wd.beat()
    time.sleep(0.06)
    wd.stop()
    # Inga undantag = OK (vakten är fail-safe)


def test_empty_data_folder_imports_legacy_suppliers(tmp_path: Path) -> None:
    """Tom data/suppliers.json får inte dölja poster i ui/data."""
    (tmp_path / "data").mkdir()
    (tmp_path / "ui" / "data").mkdir(parents=True)
    (tmp_path / "data" / "suppliers.json").write_text("[]", encoding="utf-8")
    legacy = [
        {"id": "1", "name": "Hans H", "org_number": "", "bg": ""},
        {"id": "2", "name": "Swede Glas United", "org_number": "5592-1445", "bg": ""},
    ]
    (tmp_path / "ui" / "data" / "suppliers.json").write_text(
        json.dumps(legacy, ensure_ascii=False), encoding="utf-8"
    )
    report = appmod.adopt_store_file(tmp_path, "suppliers.json", "suppliers")
    assert report["count"] == 2
    assert report["wrote"] is True
    loaded = json.loads(
        (tmp_path / "data" / "suppliers.json").read_text(encoding="utf-8")
    )
    names = {row["name"] for row in loaded}
    assert names == {"Hans H", "Swede Glas United"}


def test_supplier_json_bom_and_wrapped_object(tmp_path: Path) -> None:
    path = tmp_path / "suppliers.json"
    body = json.dumps(
        {"suppliers": [{"name": "Pilkington"}, {"name": "Direktglas"}]}
    )
    path.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    data, status = appmod.read_json_any(path)
    assert status == "ok"
    recs = appmod.unwrap_records(data, "suppliers.json")
    assert [r["name"] for r in recs] == ["Pilkington", "Direktglas"]


def test_supplier_merge_does_not_duplicate_names(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "ui" / "data").mkdir(parents=True)
    (tmp_path / "data" / "suppliers.json").write_text(
        json.dumps([{"id": "a", "name": "Hans H", "bg": "111"}]),
        encoding="utf-8",
    )
    (tmp_path / "ui" / "data" / "suppliers.json").write_text(
        json.dumps([
            {"id": "b", "name": "Hans H", "bg": ""},
            {"id": "c", "name": "Arcantil", "bg": "222"},
        ]),
        encoding="utf-8",
    )
    report = appmod.adopt_store_file(tmp_path, "suppliers.json", "suppliers")
    assert report["count"] == 2
    loaded = json.loads(
        (tmp_path / "data" / "suppliers.json").read_text(encoding="utf-8")
    )
    assert {row["name"] for row in loaded} == {"Hans H", "Arcantil"}


def test_unreadable_supplier_file_is_not_wiped(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    target = tmp_path / "data" / "suppliers.json"
    target.write_text("{trasig", encoding="utf-8")
    report = appmod.adopt_store_file(tmp_path, "suppliers.json", "suppliers")
    assert report["wrote"] is False
    assert target.read_text(encoding="utf-8") == "{trasig"
    assert report["unreadable"]


def test_autostart_command_has_minimized() -> None:
    mgr = appmod.AutostartManager()
    assert mgr.starts_minimized()
    assert "--minimized" in mgr._app_command()
    assert mgr.working_directory() == appmod.BASE_DIR.resolve()
    assert "start_hidden" in mgr.build_command().replace("\\", "/")


def test_autostart_launcher_pins_cwd() -> None:
    mgr = appmod.AutostartManager()
    path = mgr._write_launcher()
    assert path.is_file()
    assert path.parent.resolve() == (appmod.BASE_DIR / "autostart").resolve()
    text = path.read_text(encoding="utf-8")
    assert "--minimized" in text
    assert str(appmod.BASE_DIR) in text
    assert "cd " in text


def test_confine_export_never_leaves_app(tmp_path: Path) -> None:
    outside = tmp_path / "skrivbord" / "lista.pdf"
    dest = appmod.confine_export_file(outside)
    root = (appmod.BASE_DIR / "exports").resolve()
    assert str(dest.resolve()).startswith(str(root))
    assert dest.parent != root or dest.name  # alltid under exports
    inside = (
        appmod.BASE_DIR / "exports" / "Pilkington" / "2026-08-17"
        / "fakturalista_101455.pdf"
    )
    kept = appmod.confine_export_file(inside)
    assert kept == inside.resolve()


def test_confine_to_app_rejects_outside(tmp_path: Path) -> None:
    fallback = (appmod.BASE_DIR / "bak").resolve()
    got = appmod.confine_to_app(tmp_path / "annanstans", fallback)
    assert got == fallback
    ok = appmod.confine_to_app("data", appmod.DATA_DIR)
    assert ok == appmod.DATA_DIR.resolve()


# ═════════════════════════════════════════════════════════════════════
#  SMART CACHE-RENSARE (tömmer cache vid avslut)
# ═════════════════════════════════════════════════════════════════════


def test_clean_caches_removes_only_cache(tmp_path: Path) -> None:
    # Bygg en fejkad appmapp med cache + riktiga filer
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "mod.cpython-314.pyc").write_bytes(
        b"cache" * 100
    )
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui" / "__pycache__").mkdir()
    (tmp_path / "ui" / "__pycache__" / "x.pyc").write_bytes(b"y" * 50)
    (tmp_path / "gammal.pyc").write_bytes(b"z" * 10)
    (tmp_path / ".settings.json.abc123.tmp").write_bytes(b"t" * 5)
    (tmp_path / "leftover.tmp").write_bytes(b"t" * 5)
    # Riktiga filer som ALDRIG får röra
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "ui" / "data.json").write_text("[]", encoding="utf-8")

    stats = appmod.clean_caches(tmp_path)
    assert stats["pycache_mappar"] == 2
    assert stats["pyc_filer"] == 1          # gammal.pyc
    assert stats["tmp_filer"] == 2
    assert stats["frigjorda_bytes"] == 500 + 50 + 10 + 5 + 5
    # Riktiga filer orörda
    assert (tmp_path / "settings.json").exists()
    assert (tmp_path / "ui" / "data.json").exists()
    # Cachen borta
    assert not (tmp_path / "__pycache__").exists()
    assert not (tmp_path / "ui" / "__pycache__").exists()
    assert not (tmp_path / "gammal.pyc").exists()
    assert not (tmp_path / "leftover.tmp").exists()


def test_clean_caches_empty_dir_is_noop(tmp_path: Path) -> None:
    stats = appmod.clean_caches(tmp_path)
    assert stats["pycache_mappar"] == 0
    assert stats["pyc_filer"] == 0
    assert stats["tmp_filer"] == 0
    assert stats["frigjorda_bytes"] == 0


def test_clean_cache_on_exit_setting_exists() -> None:
    assert appmod.DEFAULT_SETTINGS["clean_cache_on_exit"] is True
    clean, repairs = appmod.validate_settings(
        {"clean_cache_on_exit": "ja"}
    )
    assert clean["clean_cache_on_exit"] is True   # fel typ → standard
    assert len(repairs) == 1


def test_clean_caches_on_exit_disabled_via_settings(tmp_path: Path) -> None:
    sm = appmod.SettingsManager(tmp_path / "settings.json")
    sm.set("clean_cache_on_exit", False)

    class _Fake:
        settings = sm

    # Metoden anropad med fejkad app → ska hoppa över (tom dict)
    assert appmod.FakturaApp.clean_caches_on_exit(_Fake()) == {}


# ═════════════════════════════════════════════════════════════════════
#  BELOPPFÄLTET (AmountLineEdit — format + parsning)
# ═════════════════════════════════════════════════════════════════════


def test_format_amount_edit() -> None:
    from ui.invoices_helpers import format_amount_edit as fmt

    assert fmt(45546) == "45 546,00"
    assert fmt(1234.5) == "1 234,50"
    assert fmt(0.05) == "0,05"
    assert fmt(0) == ""
    assert fmt(-100) == "100,00"      # tecken hanteras utanför fältet
    assert fmt("1234.56") == "1 234,56"
    assert fmt("ogiltigt") == ""


def test_parse_amount_edit() -> None:
    from ui.invoices_helpers import parse_amount_edit as pars

    assert pars("45 546,00") == 45546.0
    assert pars("45546") == 45546.0
    assert pars("1 234,5") == 1234.5
    assert pars("1234.50") == 1234.5       # punkt fungerar
    assert pars("1\u2009234,56") == 1234.56  # tunn mellanslag
    assert pars("-100") == 100.0           # minus ignoreras (＋/− äger tecken)
    assert pars("abc") == 0.0
    assert pars("") == 0.0
    assert pars("1,2,3") == 0.0            # flera avgränsare → ogiltigt


def test_amount_line_edit_roundtrip() -> None:
    from PySide6.QtWidgets import QApplication
    from ui.invoices_helpers import AmountLineEdit

    _ = QApplication.instance() or QApplication([])
    w = AmountLineEdit()
    w.setValue(45546.0)
    assert w.text() == "45 546,00"
    assert w.value() == 45546.0
    assert w._armed is True                # helmarkerat tills man skriver

    # Användaren skriver "1" → ersätter markeringen (simuleras här
    # genom setText + textEdited-signal, som vid riktigt skrivande)
    w.setText("1")
    w.textEdited.emit("1")
    assert w._armed is False
    assert w.value() == 1.0

    # setValue armarar om
    w.setValue(99.9)
    assert w._armed is True
    assert w.text() == "99,90"


# ═════════════════════════════════════════════════════════════════════
#  KÖRNING UTAN PYTEST
# ═════════════════════════════════════════════════════════════════════


def _run_all() -> int:
    import shutil
    import traceback

    tests = [
        (name, fn)
        for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    ok = 0
    print("=" * 64)
    print("  FakturaRäknaren — tests/test_core.py")
    print("=" * 64)
    for name, fn in tests:
        needs_tmp = "tmp_path" in fn.__code__.co_varnames
        tmp = None
        try:
            if needs_tmp:
                tmp = Path(tempfile.mkdtemp(prefix="fbp_test_"))
                fn(tmp)
            else:
                fn()
            print(f"  ✔  {name}")
            ok += 1
        except Exception:
            print(f"  ✘  {name}")
            traceback.print_exc()
        finally:
            if tmp is not None:
                shutil.rmtree(tmp, ignore_errors=True)
    print("-" * 64)
    print(f"  {ok}/{len(tests)} tester OK"
          + ("" if ok == len(tests) else "  ❌"))
    print("=" * 64)
    return 0 if ok == len(tests) else 1




# ═════════════════════════════════════════════════════════════════════
#  SMART IFYLLNING (SupplierDefaults + InvoiceDialog)
# ═════════════════════════════════════════════════════════════════════


def test_supplier_defaults_roundtrip(tmp_path: Path) -> None:
    from ui.invoices_helpers import SupplierDefaults

    sd = SupplierDefaults(tmp_path)
    assert sd.get("Pilkington") == {}
    sd.remember("Pilkington", "12345678", "REF-1", "Glas")
    sd2 = SupplierDefaults(tmp_path)          # ladda om från disk
    got = sd2.get("pilkington")               # skiftlägesokänsligt
    assert got == {"ocr": "12345678", "ref": "REF-1", "category": "Glas"}
    # Tomma värden skrivs inte över minnet
    sd2.remember("Pilkington", "", "", "")
    assert sd2.get("Pilkington")["ocr"] == "12345678"


def test_invoice_dialog_smart_fill(tmp_path: Path) -> None:
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication
    from ui.invoices_helpers import InvoiceDialog

    _ = QApplication.instance() or QApplication([])
    sup = {
        "name": "SmartTest AB", "org_number": "123456-7890",
        "bg": "572-3457", "payment_terms": 14,
    }

    class FakeCore:
        has_session_due_date = False
        session_due_date = None
        invoices_store = SimpleNamespace(_file=tmp_path / "invoices.json")

        def get_suppliers(self):
            return [sup]

    # Första dialogen: förfallodatum = fakturadatum + betalvillkor (14 d)
    dlg = InvoiceDialog(
        supplier_name="SmartTest AB",
        supplier_names=["SmartTest AB"], app_core=FakeCore(),
    )
    # Övriga fält ska ALLTID vara ifyllbara (gruppen är ej checkbar)
    assert dlg.f_ocr.isEnabled()
    assert dlg.f_ref.isEnabled()
    assert dlg.f_category.isEnabled()
    assert dlg.f_note.isEnabled()
    delta = dlg.f_date.date().daysTo(dlg.f_due_date.date())
    assert delta == 14, f"förfallodatum ska vara +14 dagar, blev {delta}"
    # (isVisible() är False offscreen innan dialogen visats — kolla
    # text + att etiketten inte är gömd)
    assert not dlg._lbl_sup_info.isHidden()
    assert "Betalvillkor: 14 dagar" in dlg._lbl_sup_info.text()
    assert "Bankgiro: 572-3457" in dlg._lbl_sup_info.text()

    # Minne sparas vid registrering → nästa dialog förfylls
    dlg.f_ocr.setText("889977")
    dlg.f_ref.setText("PO-42")
    dlg._defaults.remember(
        dlg._get_supplier(), dlg.f_ocr.text(), dlg.f_ref.text(), ""
    )

    dlg2 = InvoiceDialog(
        supplier_name="SmartTest AB",
        supplier_names=["SmartTest AB"], app_core=FakeCore(),
    )
    assert dlg2.f_ocr.text() == "889977"
    assert dlg2.f_ref.text() == "PO-42"


# ═════════════════════════════════════════════════════════════════════
#  PDF — PROFFSIG DESIGN (flersidig, sidfot "Sida x av y")
# ═════════════════════════════════════════════════════════════════════


def test_pdf_pro_design_multipage(tmp_path: Path) -> None:
    try:
        import reportlab  # noqa: F401
    except ImportError:
        print("  (hoppar över: reportlab saknas)")
        return
    sys.path.insert(0, str(PROJECT_DIR / "plugins"))
    from pdf_export_helpers import PDFExporter

    exp = PDFExporter(
        export_dir=tmp_path / "exports", data_dir=tmp_path / "data",
        company="Testfirma AB", org_number="556677-8899", theme="light",
    )
    sups = [{"name": "Pilkington", "org_number": "5561144949",
             "bg": "572-3457", "payment_terms": 30}]
    invs = [
        {
            "invoice_number": f"2026-{500+i}",
            "invoice_type": "Kreditfaktura" if i % 8 == 3 else "Faktura",
            "supplier": "Pilkington",
            "date": "2026-08-17", "due_date": "2026-09-16",
            "status": "Obetald",
            "total_amount": -999.0 if i % 8 == 3 else 1500.0 + i * 50,
        }
        for i in range(30)
    ]
    res = exp.export_invoice_list(
        invs, filename="proffstest.pdf", title="Komplett fakturalista",
        check_duplicates=False, mark_exported=False,
        ask_payment_date=False, suppliers_list=sups,
        payment_date="2026-09-26",
    )
    assert res["success"], res["errors"]
    fp = Path(res["file_path"]).resolve()
    try:
        fp.relative_to((PROJECT_DIR / "exports").resolve())
        raw = fp.read_bytes()
        # Antal sidor: "/Type /Page" minus katalogen "/Type /Pages"
        pages = raw.count(b"/Type /Page") - raw.count(b"/Type /Pages")
        assert pages >= 2, f"30 rader borde bli ≥2 sidor, blev {pages}"
        assert len(raw) > 5000
    finally:
        fp.unlink(missing_ok=True)




def test_amount_autocredit_and_enter_navigation(tmp_path: Path) -> None:
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    from ui.invoices_helpers import InvoiceDialog

    _ = QApplication.instance() or QApplication([])

    class FakeCore:
        has_session_due_date = False
        session_due_date = None
        invoices_store = SimpleNamespace(_file=tmp_path / "invoices.json")

        def get_suppliers(self):
            return []

    dlg = InvoiceDialog(
        supplier_name="Test AB", supplier_names=["Test AB"],
        app_core=FakeCore(),
    )
    dlg.show()
    QApplication.processEvents()

    # ＋ är standard
    assert dlg.f_sign.currentIndex() == 0

    # Flödet: tryck - FÖRST (ensam tangent), sen beloppet.
    # Minustecknet får ALDRIG hamna i fältet (misstolkas ej).
    dlg.f_total.setFocus()
    QApplication.processEvents()
    QTest.keyClick(dlg.f_total, Qt.Key_Minus)
    assert dlg.f_sign.currentIndex() == 1, "minus ska växla till kredit"
    assert dlg.f_total.text() == "", "fältet ska vara tomt efter -"
    QTest.keyClicks(dlg.f_total, "7853")
    assert dlg.f_total.text() == "7853"     # aldrig "kr" i texten
    assert dlg.f_total.value() == 7853.0

    # "+" växlar tillbaka till faktura
    QTest.keyClick(dlg.f_total, Qt.Key_Plus)
    assert dlg.f_sign.currentIndex() == 0

    # Enter hoppar till nästa fält i kedjan
    dlg.f_inv_nr.setFocus()
    QApplication.processEvents()
    QTest.keyClick(dlg.f_inv_nr, Qt.Key_Return)
    assert QApplication.focusWidget() is dlg.f_sign
    QTest.keyClick(dlg.f_sign, Qt.Key_Return)
    assert QApplication.focusWidget() is dlg.f_total
    QTest.keyClick(dlg.f_total, Qt.Key_Return)
    assert QApplication.focusWidget() is dlg.f_ocr




# ═════════════════════════════════════════════════════════════════════
#  INLÄSNING AV SKANNADE FAKTUROR (plugins/scan_import.py)
# ═════════════════════════════════════════════════════════════════════

sys.path.insert(0, str(PROJECT_DIR / "plugins"))

_FAKTURA_TEXTA = """FAKTURA
Pilkington Sverige AB
Org.nr: 556114-4949
Bankgiro: 572-3457
Fakturanr: 2026-144
Fakturadatum: 2026-08-17
Forfallodatum: 2026-09-16
OCR: 1234 5678 9012
Belopp: 36 436,80
Moms 25%: 9 109,20
Att betala: 45 546,00
"""


def test_scan_parse_total_prefers_label() -> None:
    import scan_import as si

    # "Att betala" vinner över momsraden (annars blev det 91109.20)
    assert si.parse_total(_FAKTURA_TEXTA) == 45546.0
    # Utan etikett → största beloppet
    assert si.parse_total("Rad 1  1 200,00\nRad 2  850,50") == 1200.0
    assert si.parse_total("ingen siffra här") == 0.0


def test_scan_parse_amount_formats() -> None:
    import scan_import as si
    from ui.scan_import_view import _parse_amount

    assert si._norm_amount("45 546,00") == 45546.0
    assert si._norm_amount("1 234.50") == 1234.5
    assert si._norm_amount("999 kr") == 999.0
    assert _parse_amount("45 546,00") == 45546.0
    assert _parse_amount("234,50") == 234.5
    assert _parse_amount("skräp") == 0.0


def test_scan_parse_fields() -> None:
    import scan_import as si

    assert si.parse_invoice_number(_FAKTURA_TEXTA) == "2026-144"
    assert si.parse_ocr(_FAKTURA_TEXTA) == "123456789012"
    date, due = si.parse_dates(_FAKTURA_TEXTA)
    assert date == "2026-08-17"
    assert due == "2026-09-16"          # "Forfallodatum" (OCR-variant)


def test_scan_parse_dates_formats() -> None:
    import scan_import as si

    # Svenska format + tvåsiffrigt år
    assert si.parse_dates("Förfallodatum: 16/09/2026")[1] == "2026-09-16"
    assert si.parse_dates("Förfallodatum: 2026-09-16")[1] == "2026-09-16"
    assert si.parse_dates("Betalningsdatum: 1.9.26")[1] == "2026-09-01"
    # Ogiltigt datum → tomt (gissar inte)
    assert si.parse_dates("Förfallodatum: 9999")[1] == ""


def test_scan_supplier_match() -> None:
    import scan_import as si

    sups = [
        {"name": "Pilkington Sverige AB", "org_number": "556114-4949"},
        {"name": "Arcantil AB", "bg": "572-1111"},
    ]
    # Namnmatchning
    assert si.match_supplier(_FAKTURA_TEXTA, sups) == "Pilkington Sverige AB"
    # Orgnummer-matchning (utan namn i texten)
    txt = "Faktura\nHos oss\nOrg.nr: 556114-4949\nAtt betala: 100,00"
    assert si.match_supplier(txt, sups) == "Pilkington Sverige AB"
    # Ingen träff → tomt
    assert si.match_supplier("Ingen känd leverantör", sups) == ""


def test_scan_parse_invoice_text_missing_fields() -> None:
    import scan_import as si

    p = si.parse_invoice_text(_FAKTURA_TEXTA, [{"name": "Pilkington Sverige AB"}])
    assert p["total_amount"] == 45546.0
    assert p["invoice_number"] == "2026-144"
    assert p["supplier"] == "Pilkington Sverige AB"
    assert p["missing"] == []

    # Tom/okänd text → allt listas som saknat (inget gissas)
    tom = si.parse_invoice_text("", [])
    assert tom["total_amount"] == 0.0
    assert "belopp" in tom["missing"]
    assert "fakturanummer" in tom["missing"]
    assert "leverantör" in tom["missing"]


def test_scan_extract_text_from_pdf(tmp_path: Path) -> None:
    try:
        from reportlab.pdfgen import canvas
    except ImportError:
        print("  (hoppar över: reportlab saknas)")
        return
    import scan_import as si

    if not si.HAS_PYPDF and not si.HAS_FITZ:
        print("  (hoppar över: ingen PDF-läsare)")
        return

    pdf = tmp_path / "faktura.pdf"
    c = canvas.Canvas(str(pdf))
    y = 800
    for line in _FAKTURA_TEXTA.splitlines():
        c.drawString(50, y, line)
        y -= 18
    c.save()

    text, method = si.extract_text(pdf)
    assert text, "ingen text extraherades"
    assert "lager" in method                      # textlager, ej OCR

    parsed = si.parse_invoice_text(text, [{"name": "Pilkington Sverige AB"}])
    assert parsed["total_amount"] == 45546.0
    assert parsed["invoice_number"] == "2026-144"
    assert parsed["supplier"] == "Pilkington Sverige AB"


def test_scan_extract_unknown_filetype(tmp_path: Path) -> None:
    import scan_import as si

    p = tmp_path / "fil.docx"
    p.write_text("hej", encoding="utf-8")
    text, method = si.extract_text(p)
    assert text == ""
    assert method == "okänd-filtyp"


def test_scan_view_builds(tmp_path: Path) -> None:
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication
    from ui.scan_import_view import ScanImportView, _fmt_amount

    _ = QApplication.instance() or QApplication([])

    class FakeCore:
        def get_suppliers(self):
            return [{"name": "Pilkington Sverige AB"}]

        def add_invoice(self, data):
            return {"id": "x", **data}

    view = ScanImportView(app=FakeCore())
    assert view._tbl.columnCount() == 9
    assert view._rows == []

    # Registrera en rad via samma väg som knappen använder
    view._rows.append({
        "file": "f.pdf", "supplier": "Pilkington Sverige AB",
        "invoice_number": "2026-144", "ocr": "", "date": "2026-08-17",
        "due_date": "2026-09-16", "total_amount": 45546.0,
        "method": "textlager-pypdf", "status": "redo", "missing": [],
        "_path": "", "_text": "",
    })
    view._refresh_table()
    assert view._tbl.item(0, 6).text() == "45 546,00"
    assert "summa 45 546,00 kr" in view._lbl_sum.text()

    assert _fmt_amount(45546.0) == "45 546,00"
    assert _fmt_amount(0) == ""


if __name__ == "__main__":
    sys.exit(_run_all())
