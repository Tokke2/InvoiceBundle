"""Autoupdatering 00:00 varje dag (användarkrav, besked 28).

Qt-fria tester: slot-logiken i plugins/updater.py (daily_midnight_slot,
daily_auto_update_due) + text-lås för huvudfönstrets koppling
(timtick → check → automatisk installation av sha-verifierad release →
omstart). Av/pa-vregeln är update_auto_check.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "plugins"))

import updater  # noqa: E402

MAIN = PROJECT_DIR / "ui" / "main_window.py"
I18N = PROJECT_DIR / "ui" / "i18n.py"


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── Slot-logik ──────────────────────────────────────────────────────


def test_midnight_slot_is_today_at_0000():
    now = datetime.datetime(2026, 11, 25, 9, 41)
    assert updater.daily_midnight_slot(now) == datetime.datetime(
        2026, 11, 25, 0, 0
    )
    # Precis på midnatt → samma slot
    assert updater.daily_midnight_slot(
        datetime.datetime(2026, 11, 25, 0, 0)
    ) == datetime.datetime(2026, 11, 25, 0, 0)


def test_daily_due_when_never_run_or_new_day():
    now = datetime.datetime(2026, 11, 25, 0, 5)
    assert updater.daily_auto_update_due("", now) is True
    assert updater.daily_auto_update_due("ogiltig", now) is True
    # Igår 12:00 → idag 00:05 förfaller dagens slot
    assert updater.daily_auto_update_due(
        "2026-11-24T12:00:00", now
    ) is True
    # redan körd idag 00:05 → inte förfallen
    assert updater.daily_auto_update_due(
        "2026-11-25T00:05:00", now
    ) is False
    # Precis på midnatt: senaste slot == nu → körd
    assert updater.daily_auto_update_due(
        "2026-11-25T00:00:00", datetime.datetime(2026, 11, 25, 0, 0)
    ) is False


def test_midnight_slot_handles_tz_aware_input():
    class TZ(datetime.tzinfo):
        def utcoffset(self, _dt):
            return datetime.timedelta(hours=2)

        def dst(self, _dt):
            return datetime.timedelta(0)

    now = datetime.datetime(2026, 11, 25, 5, 0, tzinfo=TZ())
    slot = updater.daily_midnight_slot(now)
    assert slot.tzinfo is None
    assert (slot.year, slot.month, slot.day) == (2026, 11, 25)


# ── Koppling i huvudfönstret ────────────────────────────────────────


def test_poll_tick_runs_both_flows():
    t = _src(MAIN)
    assert "def _update_poll_tick(self) -> None:" in t
    assert "self._maybe_auto_update_check()" in t
    assert "self._maybe_daily_auto_update()" in t
    assert "QTimer.singleShot(5_000, self._update_poll_tick)" in t
    assert "self._update_poll_tick)" in t  # timtick


def test_daily_flow_checks_then_installs_and_restarts():
    t = _src(MAIN)
    assert "def _maybe_daily_auto_update(self) -> None:" in t
    assert "daily_auto_update_due" in t
    assert '"update_last_auto_slot"' in t
    # Automatisk installation med samma sha-verifierade flöde
    assert 'UpdateWorker(\n                "check", PROJECT_DIR, parent=self\n            )' in t
    assert 'UpdateWorker(\n                "install", PROJECT_DIR, release=release, parent=self\n            )' in t
    assert "def _on_daily_apply_done(self, report: dict) -> None:" in t
    assert "schedule_restart(PROJECT_DIR, delay_seconds=3.0)" in t
    # Misslyckad install → manuell dialog erbjuds (aldrig tyst)
    assert "update.daily_auto_failed" in t
    # Inställningsporten (update_auto_check) respekteras
    assert 'self._settings.get("update_auto_check", True)' in t


def test_daily_i18n_keys_sv_en():
    import importlib

    i18n = importlib.import_module("ui.i18n")
    for key in ("update.daily_auto_started", "update.daily_auto_done",
                "update.daily_auto_failed"):
        entry = i18n._STRINGS[key]
        assert entry.get("sv") and entry.get("en"), key


def test_changed_files_still_compile():
    for rel in ("plugins/updater.py", "ui/main_window.py", "ui/i18n.py"):
        compile(_src(PROJECT_DIR / rel), rel, "exec")
