"""Matchningsdialogen ska inte komma upprepade gånger i onödan.

Användarkrav (besked 21): dialogen "Vilken leverantör/mall gäller?"
kom upprepade gånger för samma fil — för att (1) en Avbryt-rad
frågades igen vid varje skanningsrunda och (2) användaren inte såg
när flersidig-inlärningen var klar. Nu:

* Avbryt → raden frågas INTE igen automatiskt under sessionen
  (sessionminne via _row_ask_key); den ligger kvar i Import och
  matchas manuellt.
* Dialogen visar leverantörens flersidiga graduering
  ("N av 2 bekräftelser — en till så slutar frågan komma").

Qt-fria text-/i18n-tester; detaljbeteendet täcks av Qt-sviterna.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
VIEW = PROJECT_DIR / "ui" / "scan_import_view.py"
I18N = PROJECT_DIR / "ui" / "i18n.py"


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_cancelled_rows_are_not_asked_again_automatically():
    v = _src(VIEW)
    assert "_cancelled_ask_keys" in v
    assert "def _row_ask_key" in v
    # Avbryt → filen minns; nästa skanningsrunda frågar inte igen
    assert (
        "else:\n"
        "                # Avbryt: kom ihåg filen — ingen automatisk omfrågan.\n"
        "                cancelled.add(self._row_ask_key(row))" in v
    )
    # Redan avbrutna rader hoppas över med tydlig status
    assert "skipped_cancelled" in v
    assert '"scan.uncertain_cancelled"' in v


def test_dialog_shows_multipage_graduation_progress():
    v = _src(VIEW)
    assert 'reason == "multipage":' in v
    assert '"scan.match_multipage_progress"' in v
    # Tröskeln från en källa (scan_import) — ingen hårdkodad 2 i vyn
    assert "MULTIPAGE_CONFIRMATIONS_TO_GRADUATE" in v


def test_the_guard_still_never_guesses():
    """Säkerheten är oförändrad: flersidiga/osäkra frågar — appen
    gissar aldrig; fixen minns bara AVBRYT, den tystar aldrig
    bekräftelseflödet."""
    scan = _src(PROJECT_DIR / "plugins" / "scan_import.py")
    assert "MULTIPAGE_CONFIRMATIONS_TO_GRADUATE = 2" in scan
    v = _src(VIEW)
    assert "if self._ask_user_for_match(row):" in v
    # Avbrutna rader ligger kvar synliga i Import (de tas inte bort)
    assert "skipped_cancelled = [\n            row for row in uncertain" in v


def test_i18n_keys_sv_en():
    import importlib

    i18n = importlib.import_module("ui.i18n")
    for key in ("scan.match_multipage_progress",
                "scan.uncertain_cancelled",
                "scan.match_multipage_note"):
        entry = i18n._STRINGS[key]
        assert entry.get("sv") and entry.get("en"), key


def test_changed_files_still_compile():
    for path in (VIEW, I18N):
        compile(_src(path), str(path), "exec")


def test_match_dialog_offers_template_creation():
    """Användarkrav (besked 22): 'behöver matcha mot mall då' — dialogen
    ska erbjuda 'Skapa mall för den här fakturan…' som öppnar mall-
    redigeraren för raden; sparad mall → framtida auto-matchning."""
    v = _src(VIEW)
    assert '"scan.match_create_template"' in v
    # Knappen öppnar mallredigeraren för just den raden
    assert "self._open_template_dialog(row)" in v
    # Endast när raden har en originalfil (mallmarkering kräver bild)
    assert 'if str(row.get("_path", "") or "").strip():' in v
    # Mallkedjan finns redan: bekräftelse → mallvariant sparas
    assert "def _open_template_dialog(self, row: dict | None = None)" in v
    assert "_ensure_verified_template_from_row" in v


def test_template_create_i18n_sv_en():
    import importlib

    i18n = importlib.import_module("ui.i18n")
    entry = i18n._STRINGS["scan.match_create_template"]
    assert "Skapa mall" in entry["sv"]
    assert "Create a template" in entry["en"]


def test_asks_try_all_saved_templates_first():
    """Användarkrav (besked 23): matchningsfrågan testar ALLA sparade
    mallar FÖRST — träff (exakt fakturanummer + belopp) löser raden
    utan fråga; ingen träff → dialogen som vanligt."""
    v = _src(VIEW)
    assert "def _try_match_saved_templates(self, row: dict) -> bool:" in v
    # Anropas i _ask_user_for_match före dialogen
    assert (
        "if self._try_match_saved_templates(row):\n"
        "            self._lbl_status.setText(tr(" in v
    )
    # Går igenom ALLA mallar (hela dicten), inte bara radens leverantör
    assert "for tname, tentry in templates.items():" in v
    # Ankaret: exakt fakturanummer + belopp läses tillbaka
    assert "found_nr != inv_nr or abs(want - got) > 0.005" in v
    # Träff rensar osäkerheten (raden är användarens egen mall)
    assert 'row.pop("match_uncertain", None)' in v
    assert 'row["saved_template_resolved"] = True' in v
    assert '"scan.saved_template_matched"' in v
    assert "self._try_match_saved_templates(row)" in v


def test_saved_template_matched_i18n_sv_en():
    import importlib

    i18n = importlib.import_module("ui.i18n")
    entry = i18n._STRINGS["scan.saved_template_matched"]
    assert "sparad mall" in entry["sv"]
    assert "saved template" in entry["en"]
