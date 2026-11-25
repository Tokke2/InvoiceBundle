"""Importens batch-port: max 10 fakturor åt gången (användarkrav).

Nästa batch får ALDRIG läsas in automatiskt — användaren ska matcha
och markera varje rad klar (och flytta den till Fakturor) innan
appen hämtar fler. Porten styrs av den explicita knappen
"Hämta nästa 10" (scan.next_batch) i ui/scan_import_view.py.

Qt-fria tester: AST/text-integritet + i18n-kontrakt (ui.i18n är
Qt-fri enligt moduldokumentationen).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from ui import i18n

PROJECT_DIR = Path(__file__).resolve().parent.parent
VIEW = PROJECT_DIR / "ui" / "scan_import_view.py"
I18N = PROJECT_DIR / "ui" / "i18n.py"


def _view_source() -> str:
    return VIEW.read_text(encoding="utf-8")


def _view_ast() -> ast.Module:
    return ast.parse(_view_source(), filename=str(VIEW))


def _module_constant(tree: ast.Module, name: str) -> int:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return int(ast.literal_eval(node.value))
    raise AssertionError(f"konstanten {name} hittades inte")


def test_batch_size_is_ten_for_initial_and_refill():
    tree = _view_ast()
    assert _module_constant(tree, "SCAN_INITIAL_BATCH_SIZE") == 10
    assert _module_constant(tree, "SCAN_REFILL_BATCH_SIZE") == 10


def test_next_batch_button_and_gate_handlers_exist():
    src = _view_source()
    # Knappen finns, är dold från start och kopplad till port-klikket
    assert 'QPushButton(tr("scan.next_batch"))' in src
    assert "self._btn_next_batch.setVisible(False)" in src
    assert (
        "self._btn_next_batch.clicked.connect(\n"
        "            self._load_next_scan_batch_clicked\n"
        "        )" in src
    )
    assert "def _update_next_batch_button" in src
    assert "def _load_next_scan_batch_clicked" in src
    # Porten: aktiv först när rader hanterats och ingen skanning pågår
    assert "and not self._rows" in src
    assert 'getattr(self, "_scanning_files", False)' in src


def test_auto_refill_is_removed_everywhere():
    """Ingen väg får läsa in nästa batch automatiskt (användarkrav)."""
    src = _view_source()
    assert (
        "not self._rows and self._pending_scan_queue and not cancelled:\n"
        "            self._maybe_load_next_scan_batch()"
    ) not in src
    # Tidigare fanns sju automatiska anrop — nu två: port-klikket
    # och efter "Skapa fakturor" (användaren har markerat klart).
    assert src.count("self._maybe_load_next_scan_batch()") == 2
    assert "def _load_next_scan_batch_clicked(self) -> None:" in src
    # _refresh_table uppdaterar porten (chokepoint)
    assert (
        "self._update_preview_panel(reset_page=False)\n"
        "        self._update_next_batch_button()" in src
    )


def test_gate_blocks_and_informs_via_i18n():
    """Port-klicket informerar när batchen inte är klar ännu."""
    src = _view_source()
    assert 'tr("scan.batch_wait")' in src
    assert 'tr("scan.batch_next_loaded")' in src


@pytest.mark.parametrize("key", [
    "scan.next_batch",
    "scan.batch_wait",
    "scan.batch_next_loaded",
    "scan.batch_queued",
])
@pytest.mark.parametrize("lang", ["sv", "en"])
def test_i18n_keys_exist_for_both_languages(key: str, lang: str):
    entry = i18n._STRINGS.get(key)
    assert entry is not None, key
    assert entry.get(lang), f"{key}.{lang} saknas"


def test_i18n_batch_messages_mention_the_explicit_button():
    sv = i18n._STRINGS["scan.batch_queued"]["sv"]
    assert "Hämta nästa 10" in sv
    assert "markerad klar" in sv
    wait = i18n._STRINGS["scan.batch_wait"]["sv"]
    assert "Hämta nästa 10" in wait


def test_view_module_compiles():
    compile(_view_source(), str(VIEW), "exec")
    compile(I18N.read_text(encoding="utf-8"), str(I18N), "exec")


def test_no_tab_switch_after_single_match():
    """Användarkrav (besked 17): efter matchning av EN faktura i Import
    byter appen INTE till Fakturor — bara datan uppdateras."""
    src = _view_source()
    # Enkelradsvägen (dialogbekräftelse): uppdatera utan att byta flik
    assert (
        "self._update_next_batch_button()\n"
        "                    # Ingen automatisk flikväxling (användarkrav):\n"
        "                    # användaren arbetar vidare i Import tills batchen\n"
        "                    # är hel (10) — bara Fakturors data uppdateras.\n"
        "                    self._refresh_invoices_view_only()" in src
    )


def test_tab_switch_only_when_full_batch_of_ten_is_bundled():
    """Flikväxling sker bara när en hel batch (10) skapats i en vända —
    'dags att bunta ihop dom'; delbatcher stannar i Import."""
    src = _view_source()
    assert (
        "if created >= SCAN_REFILL_BATCH_SIZE:\n"
        "                self._show_invoices_tab()\n"
        "            else:\n"
        "                self._refresh_invoices_view_only()" in src
    )
    # Endast ETT anrop återstår — det villkorade (hel batch bunts ihop)
    assert "self._show_invoices_tab()" in src
    assert src.count("self._show_invoices_tab()") == 1
    assert "def _refresh_invoices_view_only" in src
