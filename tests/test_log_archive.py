from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from log_archive import archive_active_app_log, archive_previous_day_logs


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
