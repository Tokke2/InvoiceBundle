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


def test_new_rule_workflow_codified_in_rules_files():
    """Hård regel: '- hård regel'/'regel' → regeln till GitHub direkt."""
    agents = _read("AGENTS.md")
    arb = _read("ARBETSREGELER.md")
    assert "## 8. Nya regler till GitHub direkt" in agents
    assert "## 8. Nya regler till GitHub direkt" in arb
    assert "i samma vända" in agents and "i samma vända" in arb


def test_agents_md_is_adaptable_per_app_with_profile():
    """AGENTS.md ska vara anpassningsbar per app via App-profilen."""
    t = _read("AGENTS.md")
    assert "anpassas efter varje app" in t
    assert "App-profil" in t
    assert "universella regler" in t


def test_invoice_table_supports_sorting_and_moving_columns():
    """Fakturatabellen: sortera kolumner (proxy+SORT_ROLE) och flytta dem."""
    t = _read("ui/invoices_view.py")
    assert "setSortingEnabled(True)" in t
    assert "setSectionsMovable(True)" in t
    assert "SORT_ROLE" in t


def test_windows_start_is_windowless_and_minimized():
    """Inget terminalfönster vid start/skanning; starta alltid minimerat."""
    ps1 = _read("autostart/start_fakturabunten.ps1")
    assert "pythonw.exe" in ps1
    assert "--minimized" in ps1
    assert "ProcessWindowStyle]::Hidden" in ps1
    main = _read("main.py")
    assert '"--minimized" in sys.argv' in main
    assert "CREATE_NO_WINDOW" in main
    scan = _read("plugins/scan_import.py")
    assert "CREATE_NO_WINDOW" in scan
    assert "never flashes a terminal" in scan


def test_error_log_holds_active_errors_and_archives_resolved():
    """Komplett fellog + app-log; åtgärdade fel lämnar felloggen;
    gårdagens loggar arkiveras och rensas efter 7 dagar."""
    ec = _read("plugins/error_collect.py")
    assert 'ERROR_RESOLVED_ARCHIVE_NAME = "felsamling-atgardade.log"' in ec
    assert "def resolve_stale_error_issues(" in ec
    assert "def auto_clean_resolved_errors(" in ec
    la = _read("plugins/log_archive.py")
    assert "ARCHIVE_RETENTION_DAYS = 7" in la
    assert "def prune_archive_logs(" in la
