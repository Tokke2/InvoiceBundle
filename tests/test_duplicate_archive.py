"""Dubbletter arkiveras i egen undermapp — importeras aldrig.

Användarkrav (besked 20): känns en fil igen som dubblett ska den
INTE importeras utan arkiveras i undermappen dubbletter/ bredvid
sig själv. Funktionella tester (Qt-fri modul ui/duplicate_archive.py)
+ text-tester som låser kopplingspunkterna i bevakningsflödet.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from ui.duplicate_archive import (  # noqa: E402
    DUPLICATE_FOLDER_NAME,
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
    assert dest_path.parent.name == DUPLICATE_FOLDER_NAME == "dubbletter"
    assert dest_path.parent.parent == tmp_path
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
    assert dest.parent == src.parent / "dubbletter"
    assert dest.exists()


# ── Kopplingspunkter i bevakningsflödet (text-lås) ──────────────────


def test_watch_flow_archives_both_duplicate_paths():
    t = _src(WATCH)
    # Hash-dubblett ("redan bearbetad") → arkiveras
    assert (
        "self._archive_duplicate_copy(path)\n"
        "                self._scan_stats[\"already\"] += 1" in t
    )
    # Exakt faktura-dubblett: registrerat original → Arkiv-backsort,
    # KOPIA → dubbletter/
    assert "if exact_attachment:" in t
    assert "self._archive_duplicate_copy(path) or str(path)" in t


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
