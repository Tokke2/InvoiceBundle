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


def test_agents_md_defines_req_k4_adapted_to_this_app():
    """REQ-K4 (anpassad till Fakturabunten) ska vara definierad i AGENTS.md."""
    t = _read("AGENTS.md")
    assert "REQ-K4 (layout — anpassad till denna app):" in t
    assert "max höjd" in t
    assert "test_ui_sharpness_and_responsiveness.py" in t


def test_proposal_docs_carry_no_stale_version_rows():
    """Städad anpassad till denna app: förslagsdokumenten bär aldrig
    gamla versionbundna rader (t.ex. v1.0.0)."""
    for rel in ("docs/25-NYA-FORSLAG.md", "docs/FORSLAG-BATCH-2.md",
                "docs/FORSLAG-SYSTEM.md"):
        assert "v1.0.0" not in _read(rel), rel


def test_forslag_batch_2_delivered_with_fresh_ids():
    """10-meddelanderegeln: batch 2 (ID 26–35) levererad, aldrig återbruk."""
    import json

    batch = _read("docs/FORSLAG-BATCH-2.md")
    for pid in range(26, 36):
        assert f"## {pid}." in batch, pid
    status = json.loads(_read("docs/forslag_status.json"))
    assert status["next_milestone"] == 20
    assert status["next_proposal_id"] == 36
    assert status["next_batch_id"] == 3
    assert len(status["used_proposal_ids"]) == 35
    assert len(set(status["used_proposal_ids"])) == 35
    assert status["batches_delivered"][-1]["batch"] == 2
