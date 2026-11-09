# -*- coding: utf-8 -*-
"""Tests for the app-controlled weekly Python/package update path."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import sys
import types

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from plugins import python_update_scheduler as scheduler
import ensure_packages


def test_weekly_slot_uses_local_monday_at_0800():
    monday_before = dt.datetime(2026, 11, 2, 7, 59, 59)
    monday_at = dt.datetime(2026, 11, 2, 8, 0, 0)
    sunday = dt.datetime(2026, 11, 8, 21, 30)

    assert scheduler.weekly_slot(monday_before) == dt.datetime(2026, 10, 26, 8)
    assert scheduler.weekly_slot(monday_at) == dt.datetime(2026, 11, 2, 8)
    assert scheduler.weekly_slot(sunday) == dt.datetime(2026, 11, 2, 8)
    assert scheduler.next_weekly_slot(sunday) == dt.datetime(2026, 11, 9, 8)


def test_due_is_once_per_week_and_missed_slot_stays_due():
    last = dt.datetime(2026, 11, 2, 8)
    assert not scheduler.weekly_update_due(dt.datetime(2026, 11, 8, 23), last)
    assert scheduler.weekly_update_due(dt.datetime(2026, 11, 9, 8), last)
    assert scheduler.weekly_update_due(dt.datetime(2026, 11, 10, 9), last)
    assert not scheduler.weekly_update_due(
        dt.datetime(2026, 11, 10, 9), dt.datetime(2026, 11, 9, 8)
    )


def test_state_reader_accepts_utf8_bom_from_older_powershell(tmp_path):
    path = tmp_path / "state.json"
    path.write_bytes(b'\xef\xbb\xbf{"status":"success"}')
    assert scheduler._read_state(path) == {"status": "success"}


def test_startup_waits_only_when_worker_is_updating(monkeypatch, tmp_path):
    state_path = tmp_path / "data" / "python_update_state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "status": "pending", "app_pid": 111, "worker_pid": 222,
    }), encoding="utf-8")

    # A still-open app is not waited on; its worker is just waiting for exit.
    monkeypatch.setattr(scheduler, "_pid_is_alive", lambda pid: pid == 111)
    assert scheduler.wait_for_active_update(tmp_path) is False

    # Once the app has exited, wait for the update worker and then continue.
    checks = {222: iter((True, True, False))}

    def pid_alive(pid):
        if pid == 111:
            return False
        return next(checks[222], False)

    monkeypatch.setattr(scheduler, "_pid_is_alive", pid_alive)
    monkeypatch.setattr(scheduler.time, "sleep", lambda _seconds: None)
    assert scheduler.wait_for_active_update(tmp_path, poll_seconds=0.2) is True


def _install_fake_qtimer(monkeypatch):
    timers = []

    class FakeSignal:
        def __init__(self):
            self.callback = None

        def connect(self, callback):
            self.callback = callback

    class FakeTimer:
        def __init__(self, _parent):
            self.timeout = FakeSignal()
            self.delay = None
            timers.append(self)

        def setSingleShot(self, _single):
            pass

        def start(self, delay):
            self.delay = delay

    fake_qtcore = types.ModuleType("PySide6.QtCore")
    fake_qtcore.QTimer = FakeTimer
    fake_pyside = types.ModuleType("PySide6")
    fake_pyside.QtCore = fake_qtcore
    monkeypatch.setitem(sys.modules, "PySide6", fake_pyside)
    monkeypatch.setitem(sys.modules, "PySide6.QtCore", fake_qtcore)
    return timers


def test_scheduler_does_not_queue_again_in_same_week(tmp_path, monkeypatch):
    timers = _install_fake_qtimer(monkeypatch)
    now_slot = scheduler.weekly_slot(dt.datetime.now())
    state_path = tmp_path / "data" / "python_update_state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "last_slot": now_slot.isoformat(), "status": "success",
    }), encoding="utf-8")
    monkeypatch.setattr(scheduler, "_append_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        scheduler, "_worker_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("queued twice")),
    )

    scheduler.schedule_weekly_python_updates(object(), tmp_path, python_exe="/active/python")

    assert timers[-1].delay is not None
    assert timers[-1].delay > 0
    assert timers[-1].delay <= 60 * 60 * 1000


def test_scheduler_queues_detached_worker_for_missed_week(tmp_path, monkeypatch):
    timers = _install_fake_qtimer(monkeypatch)
    state_path = tmp_path / "data" / "python_update_state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "last_slot": "2000-01-03T08:00:00", "status": "success",
    }), encoding="utf-8")
    command_calls = []
    popen_calls = []

    def fake_command(base_dir, python_exe, slot, parent_pid):
        command_calls.append((base_dir, python_exe, slot, parent_pid))
        return ["weekly-worker"], {}

    class FakeWorker:
        pid = 4242

    def fake_popen(command, **kwargs):
        popen_calls.append((command, kwargs))
        return FakeWorker()

    monkeypatch.setattr(scheduler, "_worker_command", fake_command)
    monkeypatch.setattr(scheduler.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(scheduler, "_pid_is_alive", lambda _pid: True)
    monkeypatch.setattr(scheduler, "_append_log", lambda *_args, **_kwargs: None)

    scheduler.schedule_weekly_python_updates(
        object(), tmp_path, python_exe="/active/python"
    )
    timer = timers[-1]
    assert timer.delay == 0
    assert timer.timeout.callback is not None

    timer.timeout.callback()

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "pending"
    assert state["worker_pid"] == 4242
    assert state["app_pid"] == os.getpid()
    assert state["last_slot"] == scheduler.weekly_slot(dt.datetime.now()).isoformat()
    assert command_calls[0][1] == "/active/python"
    assert popen_calls[0][0] == ["weekly-worker"]
    assert timer.delay == 60 * 60 * 1000


def test_non_windows_worker_uses_current_python_and_marks_completion(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("PySide6>=6.6\n", encoding="utf-8")
    (tmp_path / "ensure_packages.py").write_text("# helper\n", encoding="utf-8")
    command_calls = []
    monkeypatch.setattr(scheduler, "_wait_for_pid", lambda _pid: None)
    monkeypatch.setattr(scheduler, "_append_log", lambda *_args, **_kwargs: None)

    class FakeProcess:
        stdout = iter(("Collecting package\n", "Successfully installed\n"))

        @staticmethod
        def wait():
            return 0

    def fake_popen(command, **kwargs):
        command_calls.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr(scheduler.subprocess, "Popen", fake_popen)
    slot = "2026-11-02T08:00:00"
    code = scheduler.run_non_windows_worker(
        tmp_path, 123, "/active/python", slot
    )

    assert code == 0
    assert command_calls[0][0] == [
        "/active/python", str(tmp_path / "ensure_packages.py"), "--upgrade-all",
    ]
    state = json.loads(
        (tmp_path / "data" / "python_update_state.json").read_text(encoding="utf-8")
    )
    assert state["last_slot"] == slot
    assert state["status"] == "success"
    assert state["worker_pid"] == 0
    assert state["app_pid"] == 0


def test_package_upgrade_uses_requirements_and_running_interpreter(tmp_path, monkeypatch):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("PySide6>=6.6\nreportlab>=4.0\n", encoding="utf-8")
    monkeypatch.setattr(ensure_packages, "REQUIREMENTS", requirements)
    monkeypatch.setattr(ensure_packages, "_append_log", lambda _message: None)
    pip_base = [sys.executable, "-m", "pip", "install", "--upgrade"]
    monkeypatch.setattr(ensure_packages, "_pip_base", lambda: list(pip_base))
    calls = []

    def fake_run(command, progress, status):
        calls.append((command, progress, status))
        return 0

    monkeypatch.setattr(ensure_packages, "_run_pip", fake_run)
    assert ensure_packages.upgrade_all_packages() == 0
    command, progress, status = calls[0]
    assert command == pip_base + ["-r", str(requirements)]
    assert command[0] == sys.executable
    assert progress is None
    assert status == "Veckovis paketuppdatering"

    assert ensure_packages.upgrade_all_packages(force_user=True) == 0
    user_command = calls[1][0]
    assert "--user" in user_command
    assert user_command[-2:] == ["-r", str(requirements)]
