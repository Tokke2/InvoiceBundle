"""Exportens markeringstak och standardval (användarkrav, besked 19).

Qt-fria tester som låser:

1. Högst 10 rader kan markeras för export samtidigt — både rad-
   kryssrutorna och "Markera valda" fyller bara upp till taket
   (EXPORT_MARK_LIMIT i ui/invoices_helpers.py) och överflödget
   sägs tydligt i statusraden.
2. "Export med original" är standardvalet: utan sparad inställning
   gäller all_pages (export_include_originals=True default), och
   komboboxen väljer alltid den sparade/beräknade moden vid start.
3. Exportfiler delas redan i högst 10 rader (MAX_PER_EXPORT_FILE).

Qt-sviterna (test_invoices_layout, test_payment_focus m.fl.) täcker
detaljbeteendet i CI med riktig Qt.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent
VIEW = PROJECT_DIR / "ui" / "invoices_view.py"
HELPERS = PROJECT_DIR / "ui" / "invoices_helpers.py"
I18N = PROJECT_DIR / "ui" / "i18n.py"


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_export_mark_limit_is_ten_and_single_sourced():
    h = _src(HELPERS)
    assert "EXPORT_MARK_LIMIT = 10" in h
    assert "MAX_PER_EXPORT_FILE = 10" in h
    view = _src(VIEW)
    # Importerad i båda importvarianterna (relativ + fallback)
    assert view.count("        EXPORT_MARK_LIMIT,\n") == 2


def test_marking_respects_the_cap():
    view = _src(VIEW)
    # Kryssruteflödet: tak kontrolleras FÖRE tillägg, avslag sägs
    assert (
        "len(self._marked_export_ids) >= EXPORT_MARK_LIMIT" in view
    )
    assert '"invoices.export_mark_limit"' in view
    # Markera-valda: fyller bara upp till rummet ([:room])
    assert "shown[:room]" in view
    assert "EXPORT_MARK_LIMIT - len(self._marked_export_ids)" in view


def test_export_with_originals_is_the_default_choice():
    view = _src(VIEW)
    # Default utan sparad inställning: original med, alla sidor
    assert '"export_include_originals", True' in view
    assert '"export_original_first_page_only", False' in view
    # Comboboxen väljer alltid den beräknade/sparade moden
    assert "findData(\n                self._original_export_mode" in view
    # all_pages är första alternativet i combon
    assert '("all_pages", "invoices.export_originals_all_pages")' in view


@pytest.mark.parametrize("key", ["invoices.export_mark_limit",
                                 "invoices.export_originals_all_pages"])
def test_i18n_keys_exist_sv_en(key):
    import importlib

    i18n = importlib.import_module("ui.i18n")
    entry = i18n._STRINGS[key]
    assert entry.get("sv") and entry.get("en"), key


def test_changed_files_still_compile():
    for path in (VIEW, HELPERS, I18N):
        compile(_src(path), str(path), "exec")
