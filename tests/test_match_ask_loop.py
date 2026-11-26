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
