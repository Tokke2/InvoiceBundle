# -*- coding: utf-8 -*-
"""Fakturabunten — Daily Log Archive

Författare : Rickard Längkvist
Copyright © dynamiskt år Rickard Längkvist

Daily archival for the app's ordinary log streams.

The live files stay in ``logs/`` for the current day. Older dated entries
are moved to ``logs/archive/``; the separate error journal is not moved
or trimmed. Its issue status is managed by ``error_collect`` and marked
likely resolved after 72 hours without a recurrence.

Qt-free and defensive: a logging failure must never interrupt the app.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
import json
import os
from pathlib import Path
import tempfile
from typing import Callable


def _json_line_date(line: str) -> date | None:
    try:
        item = json.loads(line)
        stamp = item.get("ts") if isinstance(item, dict) else None
        if not isinstance(stamp, str) or not stamp.strip():
            return None
        return datetime.fromisoformat(
            stamp.strip().replace("Z", "+00:00")
        ).date()
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _text_line_date(line: str) -> date | None:
    try:
        return date.fromisoformat(line[:10])
    except (TypeError, ValueError):
        return None


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="",
            prefix=f".{path.name}.", suffix=".tmp",
            dir=path.parent, delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _archive_older_entries(
    log_file: Path,
    archive_dir: Path,
    today: date,
    date_reader: Callable[[str], date | None],
    archive_name: Callable[[date], str],
) -> int:
    """Archive dated lines older than ``today``; leave unknown lines alone.

    Existing archive entries are merged using a multiset comparison. That
    makes retries safe if the process stopped after writing the archive but
    before replacing the active log, without collapsing legitimate repeated
    log lines.
    """
    try:
        lines = log_file.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines(keepends=True)
    except OSError:
        return 0

    by_day: dict[date, list[str]] = defaultdict(list)
    for line in lines:
        day = date_reader(line)
        if day is not None and day < today:
            by_day[day].append(line)
    if not by_day:
        return 0

    archived_days: set[date] = set()
    for day, day_lines in sorted(by_day.items()):
        target = archive_dir / archive_name(day)
        try:
            existing = (
                target.read_text(encoding="utf-8", errors="replace")
                .splitlines(keepends=True)
                if target.exists() else []
            )
            seen = Counter(existing)
            missing: list[str] = []
            for line in day_lines:
                if seen[line]:
                    seen[line] -= 1
                else:
                    missing.append(line)
            if missing:
                _atomic_write(target, "".join(existing + missing))
            archived_days.add(day)
        except OSError:
            # Leave any date that could not be archived in the active file.
            continue

    if not archived_days:
        return 0

    remaining = [
        line for line in lines
        if date_reader(line) not in archived_days
    ]
    try:
        _atomic_write(log_file, "".join(remaining))
    except OSError:
        # The archive is already safe; a later pass can retry the rewrite.
        return 0
    return sum(len(by_day[day]) for day in archived_days)


def archive_previous_day_logs(
    log_dir: Path, today: date | None = None,
) -> int:
    """Archive prior-day app/autostart entries into ``logs/archive``.

    Although the normal trigger is a date change, any older days are also
    archived on startup so a machine that was off yesterday catches up.
    Returns the number of source lines moved.
    """
    root = Path(log_dir)
    cutoff = today or date.today()
    archive_dir = root / "archive"
    moved = _archive_older_entries(
        root / "app.log", archive_dir, cutoff,
        _json_line_date,
        lambda day: f"app-{day.isoformat()}.jsonl",
    )
    moved += _archive_older_entries(
        root / "autostart.log", archive_dir, cutoff,
        _text_line_date,
        lambda day: f"autostart-{day.isoformat()}.log",
    )
    try:
        from error_collect import resolve_stale_error_issues

        resolve_stale_error_issues(root.parent)
    except Exception:
        pass
    return moved


def archive_active_app_log(
    log_file: Path, archive_dir: Path, day: date | None = None,
) -> Path | None:
    """Move a full current-day app log into a numbered archive segment."""
    source = Path(log_file)
    try:
        if not source.is_file() or source.stat().st_size == 0:
            return None
        archive = Path(archive_dir)
        archive.mkdir(parents=True, exist_ok=True)
        log_day = day or date.today()
        index = 1
        while True:
            target = archive / (
                f"app-{log_day.isoformat()}-part{index:03d}.jsonl"
            )
            if not target.exists():
                break
            index += 1
        os.replace(source, target)
        source.touch(exist_ok=True)
        return target
    except OSError:
        return None
