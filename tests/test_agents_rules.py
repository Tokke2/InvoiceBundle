"""AGENTS.md ska samla alla hårda regler på ett ställe.

Qt-fri textintegritet: agenter som läser AGENTS.md i en ny chatt ska
få med sig varje hård regel. Om en regel textas om här måste dess
nyckelord finnas kvar — annars fungerar inte "ny chatt läser reglerna".
"""

from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (PROJECT_DIR / rel).read_text(encoding="utf-8")


def test_agents_md_exists_in_repo_root():
    assert (PROJECT_DIR / "AGENTS.md").is_file()


def test_agents_md_codifies_release_and_updater_rules():
    t = _read("AGENTS.md")
    assert "publish-latest-release" in t
    assert "markerar releasen som latest" in t
    # Filjämförelse via updater — sha mot build_info.json, aldrig version
    assert "check_for_update()" in t
    assert "build_info.json" in t
    assert "aldrig\n  versionsnummer" in t.replace("  ", "  ") or "versionsnummer" in t
    assert "Lyckad uppdatering → backup tas bort" in t
    assert "7 dagar" in t


def test_agents_md_codifies_branch_and_never_merge_rules():
    t = _read("AGENTS.md")
    assert "arena/be184218-invoicebundle" in t
    assert "aldrig" in t.lower() and "main" in t.lower()
    assert "Aldrig merga" in t
    assert "merge-commits" in t


def test_agents_md_codifies_ten_message_rule():
    t = _read("AGENTS.md")
    assert "10:e användarbesked" in t
    assert "i chatten" in t
    assert "Aldrig återbruk" in t
    assert "docs/forslag_status.json" in t
    assert "docs/25-NYA-FORSLAG.md" in t


def test_agents_md_codifies_test_and_interface_rules():
    t = _read("AGENTS.md")
    assert "pytest" in t
    assert "py_compile" in t
    assert "CHANGELOG.md" in t
    assert "Inga tysta beroende- eller gränssnittsbrott" in t


def test_agents_md_codifies_ui_and_quality_goals():
    t = _read("AGENTS.md")
    assert "max höjd" in t
    assert "HiDPI" in t
    assert "minneshantering" in t
    assert "ui/icons.py" in t
    assert "brand/build_brand_assets.py" in t


def test_arbetsregler_contains_never_merge_rule():
    t = _read("ARBETSREGELER.md")
    assert "## 7. Aldrig merga — hård regel" in t
    assert "Inga merge-commits" in t
    assert "endast** som vanliga commits" in t


def test_agents_md_and_arbetsregler_agree_on_branch_name():
    for rel in ("AGENTS.md", "ARBETSREGELER.md"):
        assert "arena/be184218-invoicebundle" in _read(rel), rel
