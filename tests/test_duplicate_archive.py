"""Dubbletter arkiveras i egen undermapp — importeras aldrig.

Användarkrav (besked 20): känns en fil igen som dubblett ska den
INTE importeras utan arkiveras i undermappen dubbletter/ bredvid
sig själv. Funktionella tester (Qt-fri modul ui/duplicate_archive.py)
+ text-tester som låser kopplingspunkterna i bevakningsflödet.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from ui.duplicate_archive import (  # noqa: E402
    DUPLICATE_FOLDER_NAME,
    sort_paid_original_into_year_folder,
    archive_duplicate_copy,
)

WATCH = PROJECT_DIR / "ui" / "watch_folders.py"


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── Funktionellt beteende (Qt-fri modul) ────────────────────────────


def test_duplicate_moves_into_own_subfolder(tmp_path):
    original = tmp_path / "faktura.pdf"
    original.write_bytes(b"duplikatinnehall")
    dest = archive_duplicate_copy(original)
    assert dest, "flytten misslyckades"
    dest_path = Path(dest)
    # dubbletter/<årsarkiv>/ (besked 25) — årsfallet: filens mtime
    assert dest_path.parent.parent.name == DUPLICATE_FOLDER_NAME
    assert dest_path.parent.name.isdigit()
    assert dest_path.parent.parent.parent == tmp_path
    assert not original.exists()
    assert dest_path.read_bytes() == b"duplikatinnehall"


def test_name_collisions_never_overwrite(tmp_path):
    first = tmp_path / "kopia.pdf"
    first.write_bytes(b"ett")
    d1 = Path(archive_duplicate_copy(first))
    assert d1.name == "kopia.pdf"
    # En till kopia med samma namn hamnar bredvid den första
    second = tmp_path / "kopia.pdf"
    second.write_bytes(b"tva")
    d2 = Path(archive_duplicate_copy(second))
    assert d2.name == "kopia (2).pdf"
    third = tmp_path / "kopia.pdf"
    third.write_bytes(b"tre")
    d3 = Path(archive_duplicate_copy(third))
    assert d3.name == "kopia (3).pdf"
    assert [p.read_bytes() for p in (d1, d2, d3)] == [b"ett", b"tva", b"tre"]


def test_missing_file_returns_empty_and_does_not_raise(tmp_path):
    assert archive_duplicate_copy(tmp_path / "saknas.pdf") == ""


def test_folder_is_created_when_missing(tmp_path):
    src = tmp_path / "a" / "b" / "faktura.pdf"
    src.parent.mkdir(parents=True)
    src.write_text("x")
    dest = Path(archive_duplicate_copy(src))
    assert dest.parent.parent == src.parent / "dubbletter"
    assert dest.exists()


# ── Kopplingspunkter i bevakningsflödet (text-lås) ──────────────────


def test_watch_flow_archives_both_duplicate_paths():
    t = _src(WATCH)
    # Hash-dubblett ("redan bearbetad") → arkiveras, processed-
    # vägen uppdateras (besked 25)
    assert 'info["path"] = dest' in t
    assert 'self._scan_stats["already"] += 1' in t
    # Exakt faktura-dubblett: registrerat original → Arkiv-backsort,
    # KOPIA → dubbletter/
    assert "if exact_attachment:" in t
    assert 'str(parsed.get("date", "") or "")' in t
    assert ") or str(path)" in t


def test_duplicate_subfolder_is_never_rescanned():
    t = _src(WATCH)
    # Som Arkiv/: hela trädet plockas bort från mappskanningen
    assert 'if d.lower() not in ("arkiv", DUPLICATE_FOLDER_NAME)' in t
    assert 'DUPLICATE_FOLDER_NAME = "dubbletter"' in t or \
        'DUPLICATE_FOLDER_NAME = "dubbletter"' in _src(
            PROJECT_DIR / "ui" / "duplicate_archive.py"
        )


def test_watch_flow_imports_the_qt_free_helper():
    t = _src(WATCH)
    assert "from ui.duplicate_archive import" in t
    assert "from duplicate_archive import" in t


# ── Betalda original i årsmappar (användarkrav, besked 24) ──────────


def test_paid_original_lands_in_year_folder_by_invoice_date(tmp_path):
    original = tmp_path / "faktura2794.pdf"
    original.write_bytes(b"betalad")
    dest = sort_paid_original_into_year_folder(
        original, "2021-03-17"
    )
    assert dest, "flytten misslyckades"
    dest_path = Path(dest)
    assert dest_path.parent == tmp_path / "Arkiv" / "2021"
    assert not original.exists()
    assert dest_path.read_bytes() == b"betalad"


def test_paid_original_year_falls_back_to_mtime(tmp_path):
    original = tmp_path / "f.pdf"
    original.write_bytes(b"x")
    dest = sort_paid_original_into_year_folder(original, "")
    assert Path(dest).parent.name in {
        str(datetime.date.today().year),
        str(datetime.date.today().year - 1),
    }


def test_paid_original_bad_date_and_missing_file_are_noops(tmp_path):
    src = tmp_path / "g.pdf"
    assert sort_paid_original_into_year_folder(src, "2021-03-17") == ""
    src.write_bytes(b"x")
    # Ogiltigt datum + oläsbar mtime-fallback är osannolikt, men
    # ogiltigt datum med läsbart datum → mtime-år; filen som saknas
    # ska aldrig krascha:
    assert sort_paid_original_into_year_folder(
        tmp_path / "saknas.pdf", "2021-03-17"
    ) == ""


def test_paid_original_collisions_never_overwrite(tmp_path):
    paths = []
    for i in range(2):
        f = tmp_path / "samma.pdf"
        f.write_bytes(bytes([i]))
        paths.append(sort_paid_original_into_year_folder(f, "2020-01-01"))
    folder = tmp_path / "Arkiv" / "2020"
    assert sorted(p.name for p in folder.iterdir()) == [
        "samma (2).pdf", "samma.pdf",
    ]


def test_mark_paid_flows_sort_the_original_by_year():
    app_src = _src(PROJECT_DIR / "app.py")
    assert "def _sort_paid_original(" in app_src
    assert "_sort_paid_fn is None or not isinstance(rec, dict)" in app_src
    # Båda betalda-flödena: mark_paid (1) + mark_exported_paid (2)
    assert app_src.count("self._sort_paid_original(") == 3
    assert "self._archive.update(rid, data)" in app_src
    # Återställning om bilagevägen inte kan sparas
    assert "os.replace(new_path, str(src))" in app_src
    mod = _src(PROJECT_DIR / "ui" / "duplicate_archive.py")
    assert "PAID_ARCHIVE_FOLDER_NAME = \"Arkiv\"" in mod
    assert "def sort_paid_original_into_year_folder(" in mod


# ── Ingen kapsling + årsundermapp (användarkrav, besked 25) ─────────


def test_duplicates_go_to_year_subfolder_not_nested(tmp_path):
    f = tmp_path / "kopia.pdf"
    f.write_bytes(b"dup")
    dest = Path(archive_duplicate_copy(f, "2021-05-01"))
    # EN dubbletter/-nivå med årsundermapp — aldrig dubbletter/dubbletter
    assert dest.parent == tmp_path / "dubbletter" / "2021"


def test_duplicate_already_in_folder_is_never_moved_deeper(tmp_path):
    deep = tmp_path / "dubbletter" / "dubbletter" / "dubbletter"
    deep.mkdir(parents=True)
    f = deep / "kopia.pdf"
    f.write_bytes(b"redan arkiverad")
    dest = archive_duplicate_copy(f)
    # Vakten: filen ligger redan under dubbletter/ → ingen ny flytt,
    # ingen ny nivå — exakt den kapsling användaren hittade.
    assert Path(dest) == f
    assert f.exists()
    assert not (tmp_path / "dubbletter" / "dubbletter" / "dubbletter"
                / "dubbletter").exists()


def test_duplicate_year_falls_back_to_mtime(tmp_path):
    f = tmp_path / "k.pdf"
    f.write_bytes(b"x")
    dest = Path(archive_duplicate_copy(f))
    assert dest.parent.name in {
        str(datetime.date.today().year),
        str(datetime.date.today().year - 1),
    }


def test_scan_enumerations_skip_the_duplicate_folder():
    """Root-oraken: båda skanningsuppräkningarna ska rensa
    dubbletter/ (som Arkiv/) — annars läses arkiverade filer igen
    varje runda och flyttas djupare."""
    wf = _src(WATCH)
    assert wf.count(
        'not in ("arkiv", DUPLICATE_FOLDER_NAME)'
    ) == 3  # mappskanning, strömning, watcher-vandring


def test_already_branch_updates_processed_path_after_move():
    """Efter arkiveringen uppdateras processed[hash]['path'] — annars
    pekar posten på den gamla vägen och filen behandlas om och om."""
    wf = _src(WATCH)
    assert (
        'info["path"] = dest\n'
        "                        info[\"file\"] = Path(dest).name" in wf
    )
    assert "self._save()" in wf
    # Exakt-dup-grenen skickar med fakturadatumet
    assert (
        "self._archive_duplicate_copy(\n"
        "                        path, str(parsed.get(\"date\", \"\") or \"\")"
    ) in wf
