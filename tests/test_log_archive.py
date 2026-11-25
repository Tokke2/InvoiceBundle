from __future__ import annotations

from datetime import date
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "plugins")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

from log_archive import (  # noqa: E402
    archive_active_app_log,
    archive_previous_day_logs,
    prune_archive_logs,
)


def _entry(stamp: str, message: str) -> str:
    return json.dumps({
        "ts": stamp, "level": "INFO", "logger": "Test",
        "action": "TEST", "msg": message,
    }, ensure_ascii=False) + "\n"


def test_archives_prior_days_and_keeps_current_and_error_logs(tmp_path: Path):
    logs = tmp_path / "logs"
    logs.mkdir()
    app_log = logs / "app.log"
    app_log.write_text(
        _entry("2026-11-02T23:59:00", "two days old")
        + _entry("2026-11-03T23:59:00", "yesterday")
        + _entry("2026-11-04T08:00:00", "today")
        + "not-json-but-preserve-me\n",
        encoding="utf-8",
    )
    autostart_log = logs / "autostart.log"
    autostart_log.write_text(
        "2026-11-03 23:58:00 OK yesterday\n"
        "2026-11-04 08:01:00 OK today\n"
        "legacy line without date\n",
        encoding="utf-8",
    )
    error_log = logs / "felsamling.log"
    error_log.write_text("unresolved error stays here\n", encoding="utf-8")

    moved = archive_previous_day_logs(logs, today=date(2026, 11, 4))

    archive = logs / "archive"
    assert moved == 3
    assert "two days old" in (
        archive / "app-2026-11-02.jsonl"
    ).read_text(encoding="utf-8")
    assert "yesterday" in (
        archive / "app-2026-11-03.jsonl"
    ).read_text(encoding="utf-8")
    assert "2026-11-03 23:58:00 OK yesterday" in (
        archive / "autostart-2026-11-03.log"
    ).read_text(encoding="utf-8")

    current_app = app_log.read_text(encoding="utf-8")
    assert "today" in current_app
    assert "not-json-but-preserve-me" in current_app
    current_autostart = autostart_log.read_text(encoding="utf-8")
    assert "2026-11-04 08:01:00 OK today" in current_autostart
    assert "legacy line without date" in current_autostart
    assert error_log.read_text(encoding="utf-8") == "unresolved error stays here\n"

    # A repeat pass does not duplicate lines or rewrite today's active log.
    before = (archive / "app-2026-11-03.jsonl").read_text(encoding="utf-8")
    assert archive_previous_day_logs(logs, today=date(2026, 11, 4)) == 0
    assert (archive / "app-2026-11-03.jsonl").read_text(encoding="utf-8") == before


def test_archive_active_log_as_numbered_size_segment(tmp_path: Path):
    logs = tmp_path / "logs"
    archive = logs / "archive"
    logs.mkdir()
    app_log = logs / "app.log"
    app_log.write_text("current-day-entry\n", encoding="utf-8")

    first = archive_active_app_log(
        app_log, archive, day=date(2026, 11, 4)
    )
    assert first == archive / "app-2026-11-04-part001.jsonl"
    assert first.read_text(encoding="utf-8") == "current-day-entry\n"
    assert app_log.exists() and app_log.read_text(encoding="utf-8") == ""

    app_log.write_text("another-segment\n", encoding="utf-8")
    second = archive_active_app_log(
        app_log, archive, day=date(2026, 11, 4)
    )
    assert second == archive / "app-2026-11-04-part002.jsonl"


def test_archive_runs_auto_clean_for_old_resolved_errors(tmp_path: Path):
    import error_collect as ec

    logs = tmp_path / "logs"
    logs.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    (logs / "app.log").write_text("", encoding="utf-8")
    (logs / "autostart.log").write_text("", encoding="utf-8")
    ec.error_log_path(tmp_path).write_text(
        ec._HEADER
        + "2026-01-01T10:00:00 | ERROR | Test | Gammalt åtgärdat fel\n",
        encoding="utf-8",
    )

    # När auto_clean_resolved_errors = false behålls det gamla felet
    (data / "settings.json").write_text(
        json.dumps({"auto_clean_resolved_errors": False}),
        encoding="utf-8",
    )
    archive_previous_day_logs(logs, today=date(2026, 11, 4))
    assert "Gammalt åtgärdat fel" in ec.error_log_path(tmp_path).read_text(encoding="utf-8")

    # När auto_clean_resolved_errors = true (standard) städas gamla fel ut
    (data / "settings.json").write_text(
        json.dumps({"auto_clean_resolved_errors": True}),
        encoding="utf-8",
    )
    archive_previous_day_logs(logs, today=date(2026, 11, 4))
    assert "Gammalt åtgärdat fel" not in ec.error_log_path(tmp_path).read_text(encoding="utf-8")



# ── Arkiv-pruning: dagsarkiv äldre än 7 dagar rensas ────────────────


def test_prune_archive_logs_removes_only_old_dated_files(tmp_path: Path):
    import datetime as dt

    archive = tmp_path / "archive"
    archive.mkdir()
    today = dt.date(2026, 11, 25)

    old_app = archive / "app-2026-11-10.jsonl"          # 15 dagar → bort
    old_autostart = archive / "autostart-2026-11-12.log"  # 13 dagar → bort
    old_part = archive / "app-2026-11-13-part001.jsonl"   # 12 dagar → bort
    fresh_app = archive / "app-2026-11-22.jsonl"          # 3 dagar → kvar
    edge = archive / "app-2026-11-18.jsonl"               # exakt 7 dagar → kvar
    reserved = archive / "felsamling-atgardade.log"       # odaterad → kvar
    other = archive / "app_annan_mapp_2026-11-01.log"     # annat mönster → kvar
    for f in (old_app, old_autostart, old_part, fresh_app, edge,
              reserved, other):
        f.write_text("rad\n", encoding="utf-8")

    removed = prune_archive_logs(tmp_path, days=7, now=today)
    assert removed == 3
    assert not old_app.exists()
    assert not old_autostart.exists()
    assert not old_part.exists()
    assert fresh_app.exists()
    assert edge.exists()   # 7 dagar gammal är fortfarande inom gränsen
    assert reserved.exists()
    assert other.exists()


def test_prune_runs_with_previous_day_archiving(tmp_path: Path):
    """archive_previous_day_logs rensar samtidigt gamla dagsarkiv."""
    import datetime as dt

    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "app-2026-11-05.jsonl").write_text(
        '{"ts":"2026-11-05T10:00:00","level":"INFO","msg":"x"}\n',
        encoding="utf-8",
    )
    (archive / "autostart-2026-11-05.log").write_text(
        "2026-11-05 rad\n", encoding="utf-8"
    )

    today = dt.date(2026, 11, 25)
    # (Ingen app.log i log_dir → inget flyttas, men pruning körs.)
    archive_previous_day_logs(tmp_path, today=today)
    assert not (archive / "app-2026-11-05.jsonl").exists()
    assert not (archive / "autostart-2026-11-05.log").exists()
