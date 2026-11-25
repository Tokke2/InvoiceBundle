"""Lärandet, logotypmatchningen och kreditavräkningen — låsta kontrakt.

Qt-fria text-/AST-tester som låser att:

1. Alla bekräftade mallar (inkl. FLERSIDIGA) sparas som varianter
   (upp till 15 per leverantör) i data/invoice_templates.json, och
   att flersidiga bekräftelser räknas så leverantören gradueras
   (MULTIPAGE_CONFIRMATIONS_TO_GRADUATE = 2).
2. Logotypmarkering finns: "Markera logotyp" i mallvyn, dhash-signaturer
   (dhash128-v1) sparas som varianter, observatören sparar logotypen
   vid varje bekräftelse och matchningen kan peka ut learned_logo.
3. Kreditavräkningen sparar mellanskillnaden till nästa omgång:
   plan_credit_settlement → carryovers med remaining_amount,
   _partial_credit_carryover-märkning, apply_credit_carryovers +
   get_credit_carryovers (återställning mellan utskicksomgångar).

Beteendet i detalj täcks av Qt-sviterna (test_credit_carryover.py,
test_batch_learning_and_templates.py) som körs i CI med riktig Qt.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent
SCAN = PROJECT_DIR / "plugins" / "scan_import.py"
VIEW = PROJECT_DIR / "ui" / "scan_import_view.py"
HELPERS = PROJECT_DIR / "ui" / "invoices_helpers.py"
I18N = PROJECT_DIR / "ui" / "i18n.py"


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── 1. Flersidiga mallar sparas vid varje bekräftelse ───────────────


def test_multipage_confirmations_save_template_variants():
    scan = _src(SCAN)
    assert "MULTIPAGE_CONFIRMATIONS_TO_GRADUATE = 2" in scan
    assert 'MAX_TEMPLATES_PER_SUPPLIER = 15' in scan or \
        "MAX_TEMPLATES_PER_SUPPLIER = 15" in scan
    # Bekräftelsen räknar flersidiga separat (graduering mot vakten)
    assert '"multipage_confirmed"' in scan
    assert "multipage=self._row_pages(row) >= 2" in _src(VIEW)
    # Mall härleds från bekräftad rad och sparas till fil
    assert "derive_template_from_confirmation" in _src(VIEW)
    assert "store_supplier_template" in _src(VIEW)
    assert "invoice_templates.json" in _src(VIEW)


def test_multipage_guard_explains_graduation_path():
    scan = _src(SCAN)
    assert "def _multipage_total_corroborated(" in scan
    assert "def _apply_multipage_guard(" in scan
    assert "learning_graduated(learning, name)" in scan
    # 15 varianter per leverantör, även flersidiga (dokumenterat)
    assert "1..15" in scan or "1–flersidiga" in scan


# ── 2. Logotypmarkering → leverantörsmatchning ──────────────────────


def test_logo_marking_exists_and_is_persisted():
    view = _src(VIEW)
    assert 'QPushButton(tr("tmpl.mark"))' in view
    assert "tmpl.logo_help" in view
    assert "tmpl.logo_variants_saved" in view
    # Observatören sparar logotypen automatiskt vid bekräftelse
    assert "observe_confirmed_supplier_logo" in view
    scan = _src(SCAN)
    assert '_SUPPLIER_LOGO_HASH_PREFIX = "dhash128-v1:"' in scan
    # Matchningen kan peka ut logotypinlärning som skäl
    assert "learned_logo" in scan


@pytest.mark.parametrize("key", ["tmpl.mark", "tmpl.logo_help",
                                 "tmpl.logo_variants_saved"])
def test_logo_i18n_keys_exist(key):
    import importlib

    i18n = importlib.import_module("ui.i18n")
    entry = i18n._STRINGS.get(key)
    assert entry is not None, key
    assert entry.get("sv") and entry.get("en"), key


# ── 3. Kreditavräkning: mellanskillnaden sparas till nästa omgång ───


def test_credit_settlement_keeps_remaining_balance():
    h = _src(HELPERS)
    assert "def plan_credit_settlement(" in h
    assert "def chunk_settlement_rows(" in h
    assert "def apply_credit_carryovers(" in h
    # Dokumenterat scenario: −132 000 mot 10 fakturor → −78 450 kvar
    assert "−132 000" in h and "−78 450" in h
    # Delavräknade rader märks och saldot följer krediten vidare
    assert '"_partial_credit_carryover"' in h
    assert '"remaining_amount"' in h
    # Saldot sparas i export-historiken och återställs mellan omgångar
    assert "def get_credit_carryovers(" in h
    invoices = _src(PROJECT_DIR / "ui" / "invoices_view.py")
    assert "_on_credit_carryovers_restored" in invoices


def test_credit_carryover_qt_tests_cover_the_scenario():
    t = _src(PROJECT_DIR / "tests" / "test_credit_carryover.py")
    # Exakt användarens flöde: kredit mot 10 fakturor, saldo kvar,
    # nästa omgång fortsätter på resten.
    assert "test_plan_and_chunk_settlement_132k_against_10_invoices" in t
    assert "test_export_partial_credit_keeps_78450_then_exhausts_and_restores" in t
    assert "test_auto_batch_preserves_remaining_credit" in t
