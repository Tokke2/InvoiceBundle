# -*- coding: utf-8 -*-
"""Felsökningspaketet visar VARFÖR bevakade filer inte läses in.

Tidigare bestod paketet av senaste 15 fel (en WinError-storm
kunde dränka allt) + loggsvans full av UI-klick/scroll. Nu:
bevakat-mapp-sektion med orsak per parkerad fil, SCAN_WATCH-
sektion på INFO-nivå, sammanslagen felstorm och brusfri svans.
Dessutom tål filskrivningen (os.replace) tillfälliga
WinError 5-låsningar från antivirus på Windows.
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
        "appmod_diag_test", ROOT / "app.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_package_shows_watch_reasons_and_collapses_storm():
    from ui.log_view import format_diagnostics

    entries = []
    for i in range(5):
        entries.append({
            "ts": f"2026-10-19T17:07:3{i}", "level": "ERROR",
            "logger": "FakturaApp", "action": "",
            "msg": "JSON save error (D:\\data\\changelog.json): "
                   f"[WinError 5] Åtkomst nekad: '.chg.aa{i}.tmp'",
        })
    entries.append({
        "ts": "2026-10-19T17:08:00", "level": "INFO",
        "logger": "ScanImport", "action": "",
        "msg": "SCAN_WATCH skanning: 0 nya, 3 parkerade, "
               "49 redan bearbetade",
    })
    for i in range(4):
        entries.append({
            "ts": f"2026-10-19T17:09:0{i}", "level": "INFO",
            "logger": "QtUI", "action": "UI_WHEEL",
            "msg": "Scroll ner på QWindow",
        })
    entries.append({
        "ts": "2026-10-19T17:09:09", "level": "INFO",
        "logger": "App", "action": "TAB_CHANGED",
        "msg": "Flik bytt → [7] Logg",
    })

    text = format_diagnostics(entries, {
        "app": "Fakturabunten 1.0.0", "invoices": 236,
        "invoices_active": 12, "invoices_archived": 224,
        "watch_folders": 1,
        "watch_lines": [
            "• D:\\gewgg (leverantör Martin G Anderson) — 49 "
            "fakturafil(er) sedda av skanningen, 1 parkerade här",
            "    parkerad: fil2024.pdf — saknar uppgifter: "
            "total_amount (sedan 2026-10-19T16:00)",
        ],
    })
    # Felstormen = EN rad med ×5, inte fem rader
    assert text.count("JSON save error") >= 2  # felr + svans
    errors_section = text.split("── Bevakade mappar ──")[0]
    assert "samma fel ×5" in errors_section
    # Bevakningssektionen med ORSAKEN
    assert "── Bevakade mappar ──" in text
    assert "saknar uppgifter: total_amount" in text
    # Skanningsrader på INFO-nivå syns
    assert "── Skanning bevakade mappar (SCAN_WATCH) ──" in text
    assert "49 redan bearbetade" in text
    # Arkivuppdelningen efter leverantörsarkivet
    assert "invoices_archived: 224" in text
    # Svansen saknar UI-brus men har riktiga rader
    tail = text.split("── Loggens slut", 1)[1]
    assert "UI_WHEEL" not in tail
    assert "Flik bytt" in tail


def test_watch_diagnostic_lines_explain_everything(tmp_path):
    from ui.watch_folders import (
        file_hash, watch_diagnostic_lines,
    )

    folder = tmp_path / "gewgg"
    folder.mkdir()
    seen = folder / "faktura2024.pdf"
    seen.write_bytes(b"%PDF-1.4 fake")
    parked_file = folder / "ofullstandig.pdf"
    parked_file.write_bytes(b"%PDF-1.4 annan")

    config = {
        "folders": [
            {"path": str(folder), "supplier": "Martin G Anderson"},
            {"path": str(tmp_path / "saknas"), "supplier": "X"},
        ],
        "auto_create": True,
        "processed": {},
        "parked": [{
            "hash": file_hash(parked_file),
            "path": str(parked_file),
            "file": "ofullstandig.pdf",
            "reason": "missing: total_amount",
            "ts": "2026-10-19T16:00:00",
        }],
    }
    lines = watch_diagnostic_lines(
        config,
        {"imported": 0, "duplicate": 0, "parked": 1, "already": 0},
    )
    text = "\n".join(lines)
    assert "senaste skanning:" in text
    assert "MAPPEN SAKNAS" in text
    assert "2 fakturafil(er) sedda" in text
    assert "saknar uppgifter: total_amount" in text
    assert "ej inläst ännu: faktura2024.pdf" in text


def test_save_json_recovers_from_transient_access_denied(
        tmp_path, monkeypatch):
    """WinError 5 (antivirus håller destinationen en stund)
    får inte kosta en skrivning: bytet försöks om."""
    appmod = _load_appmod()
    target = tmp_path / "data.json"
    real_replace = appmod.os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(5, "Åtkomst nekad")
        return real_replace(src, dst)

    monkeypatch.setattr(appmod.os, "replace", flaky)
    assert appmod._save_json(target, {"a": 1}) is True
    assert calls["n"] == 3
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "a": 1
    }
