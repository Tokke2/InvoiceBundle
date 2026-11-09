# -*- coding: utf-8 -*-
"""Weekly Python/runtime and package update scheduling for Fakturabunten.

The app checks its persisted weekly slot at startup and schedules the next
Monday at 08:00 while its Qt event loop is running. Actual changes are
handed to a detached worker that waits for the app process to exit, so pip
and the interpreter installer never replace files currently in use.

On Windows the existing system Python installation and requirements are
updated by ``autostart/install_python.ps1``. On macOS/Linux the app updates
its required packages through the exact running interpreter; it does not
attempt to replace an OS-managed Python runtime.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

log = logging.getLogger("FakturaPythonUpdate")
STATE_RELATIVE_PATH = Path("data") / "python_update_state.json"
UPDATE_HOUR = 8
_ACTIVE_TIMERS: list[Any] = []


def weekly_slot(now: dt.datetime) -> dt.datetime:
    """Return the most recent local Monday 08:00 slot at or before ``now``."""
    if now.tzinfo is not None:
        now = now.astimezone().replace(tzinfo=None)
    monday = now.date() - dt.timedelta(days=now.weekday())
    slot = dt.datetime.combine(monday, dt.time(UPDATE_HOUR, 0))
    if slot > now:
        slot -= dt.timedelta(days=7)
    return slot


def next_weekly_slot(now: dt.datetime) -> dt.datetime:
    """Return the next local Monday 08:00 slot strictly after ``now``."""
    return weekly_slot(now) + dt.timedelta(days=7)


def weekly_update_due(now: dt.datetime, last_slot: dt.datetime | None) -> bool:
    """Whether this week's Monday 08:00 update slot has not been attempted."""
    if now.tzinfo is not None:
        now = now.astimezone().replace(tzinfo=None)
    if last_slot is not None and last_slot.tzinfo is not None:
        last_slot = last_slot.astimezone().replace(tzinfo=None)
    return last_slot is None or weekly_slot(now) > last_slot


def _state_path(base_dir: Path) -> Path:
    return Path(base_dir) / STATE_RELATIVE_PATH


def _read_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _parse_slot(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.strip())
        return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed
    except (TypeError, ValueError):
        return None


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    temp.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _append_log(base_dir: Path, message: str, level: str = "INFO") -> None:
    try:
        log_dir = Path(base_dir) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        line = {
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
            "level": level,
            "logger": "FakturaPythonUpdate",
            "action": "PYTHON_WEEKLY_UPDATE",
            "msg": message,
        }
        with (log_dir / "app.log").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _state_pid(value: Any) -> int:
    try:
        pid = int(value or 0)
        return pid if pid > 0 else 0
    except (TypeError, ValueError, OverflowError):
        return 0


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return False


def wait_for_active_update(base_dir: Path, *, poll_seconds: float = 2.0) -> bool:
    """Wait at startup only while a detached worker is actively updating.

    The worker initially waits for ``app_pid`` to exit. A second launch must
    not wait while that first app is still open (which would deadlock the
    wait), but it must stay clear once the worker has begun changing packages.
    """
    state = _read_state(_state_path(Path(base_dir)))
    if str(state.get("status", "")) != "pending":
        return False
    app_pid = _state_pid(state.get("app_pid"))
    worker_pid = _state_pid(state.get("worker_pid"))
    if _pid_is_alive(app_pid) or not _pid_is_alive(worker_pid):
        return False
    message = "Waiting for the weekly Python/package update to finish before startup."
    log.info("PYTHON_WEEKLY_UPDATE_WAIT: worker=%s", worker_pid)
    _append_log(base_dir, message)
    while _pid_is_alive(worker_pid):
        time.sleep(max(0.2, poll_seconds))
    return True


def _worker_command(
    base_dir: Path,
    python_exe: str,
    slot: dt.datetime,
    parent_pid: int,
) -> tuple[list[str], dict[str, Any]]:
    slot_text = slot.isoformat(timespec="seconds")
    if os.name == "nt":
        script = Path(base_dir) / "autostart" / "install_python.ps1"
        powershell = shutil.which("powershell.exe") or "powershell.exe"
        args = [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-WaitForPid",
            str(parent_pid),
            "-UpdatePackages",
            "-PythonExe",
            python_exe,
            "-Slot",
            slot_text,
        ]
        return args, {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}

    worker = Path(__file__).resolve()
    args = [
        python_exe,
        str(worker),
        "--worker",
        "--base-dir",
        str(Path(base_dir).resolve()),
        "--wait-for-pid",
        str(parent_pid),
        "--python-exe",
        python_exe,
        "--slot",
        slot_text,
    ]
    return args, {"start_new_session": True}


def _finish_state(
    base_dir: Path,
    slot_text: str,
    status: str,
    message: str,
) -> None:
    path = _state_path(base_dir)
    state = _read_state(path)
    state.update({
        "last_slot": slot_text,
        "status": status,
        "worker_pid": 0,
        "app_pid": 0,
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "message": message[:500],
    })
    _write_state(path, state)


def _wait_for_pid(pid: int) -> None:
    while _pid_is_alive(pid):
        time.sleep(2)


def run_non_windows_worker(
    base_dir: Path,
    wait_for_pid: int,
    python_exe: str,
    slot_text: str,
) -> int:
    """Run the package upgrade after the GUI exits (non-Windows worker)."""
    base_dir = Path(base_dir).resolve()
    _wait_for_pid(wait_for_pid)
    _append_log(
        base_dir,
        "Weekly update started after the app closed. "
        "The OS-managed Python runtime is left unchanged on this platform; "
        "updating the app's requirements in the current interpreter.",
    )
    requirements = base_dir / "requirements.txt"
    helper = base_dir / "ensure_packages.py"
    if not requirements.is_file() or not helper.is_file():
        message = "Weekly package update skipped: requirements.txt or ensure_packages.py is missing."
        _append_log(base_dir, message, "ERROR")
        _finish_state(base_dir, slot_text, "failed", message)
        return 1

    cmd = [python_exe, str(helper), "--upgrade-all"]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(base_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            text = line.rstrip()
            if text:
                _append_log(base_dir, "pip: " + text)
        code = proc.wait()
        status = "success" if code == 0 else "failed"
        message = f"Package update exit code {code}."
        _append_log(base_dir, message, "INFO" if code == 0 else "ERROR")
        _finish_state(base_dir, slot_text, status, message)
        return int(code)
    except Exception as exc:
        message = f"Package update failed: {exc}"
        _append_log(base_dir, message, "ERROR")
        _finish_state(base_dir, slot_text, "failed", message)
        return 1


def schedule_weekly_python_updates(
    qt_app: Any,
    base_dir: Path,
    *,
    python_exe: str | None = None,
) -> None:
    """Schedule one update at Monday 08:00, or after that slot if missed.

    No package index or version check happens on every startup. Startup only
    reads the small local state file and schedules a Qt timer. The worker is
    detached and waits for this app process to exit before changing Python or
    its packages.
    """
    from PySide6.QtCore import QTimer

    base_dir = Path(base_dir).resolve()
    python_exe = str(python_exe or sys.executable)
    state_path = _state_path(base_dir)
    state = _read_state(state_path)
    now = dt.datetime.now()
    last_slot = _parse_slot(state.get("last_slot"))

    if last_slot is None:
        # First activation: run once now, unless this is Monday before 08:00;
        # in that case the first run belongs at today's scheduled slot.
        current_slot = weekly_slot(now)
        if now.weekday() == 0 and now.time() < dt.time(UPDATE_HOUR, 0):
            last_slot = current_slot
        else:
            last_slot = current_slot - dt.timedelta(days=7)
        state.update({
            "last_slot": last_slot.isoformat(timespec="seconds"),
            "status": "initialized",
            "worker_pid": 0,
            "app_pid": 0,
        })
        _write_state(state_path, state)
        _append_log(base_dir, "Weekly Python update schedule initialized.")

    timer = QTimer(qt_app)
    timer.setSingleShot(True)
    _ACTIVE_TIMERS.append(timer)

    def schedule_next() -> None:
        current_now = dt.datetime.now()
        current_state = _read_state(state_path)
        current_last = _parse_slot(current_state.get("last_slot"))
        status = str(current_state.get("status", ""))
        worker_pid = _state_pid(current_state.get("worker_pid"))

        if status == "pending":
            if _pid_is_alive(worker_pid):
                # Recheck periodically both for a worker exit and for clock/DST changes.
                timer.start(60 * 60 * 1000)
                return
            # A worker that died before recording a result is not restarted
            # on every app launch; this week's slot is considered attempted.
            current_state["status"] = "failed"
            current_state["worker_pid"] = 0
            current_state["app_pid"] = 0
            current_state["updated_at"] = current_now.isoformat(timespec="seconds")
            current_state["message"] = "Update worker exited before recording its result."
            _write_state(state_path, current_state)
            _append_log(base_dir, current_state["message"], "ERROR")
            current_last = _parse_slot(current_state.get("last_slot"))

        current_slot = weekly_slot(current_now)
        if current_last is None or current_slot > current_last:
            target = current_now
        else:
            target = next_weekly_slot(current_now)
        delay = max(0, int((target - current_now).total_seconds() * 1000))
        # A bounded timeout rechecks wall time so DST or clock adjustments do
        # not shift the intended local Monday 08:00 slot.
        timer.start(min(delay, 60 * 60 * 1000))

    def launch_update() -> None:
        current_now = dt.datetime.now()
        current_slot = weekly_slot(current_now)
        current_state = _read_state(state_path)
        current_last = _parse_slot(current_state.get("last_slot"))
        if current_last is not None and current_slot <= current_last:
            schedule_next()
            return
        if str(current_state.get("status", "")) == "pending":
            if _pid_is_alive(_state_pid(current_state.get("worker_pid"))):
                schedule_next()
                return

        slot_text = current_slot.isoformat(timespec="seconds")
        current_state.update({
            "last_slot": slot_text,
            "status": "pending",
            "worker_pid": 0,
            "app_pid": os.getpid(),
            "updated_at": current_now.isoformat(timespec="seconds"),
            "message": "Weekly Python/package update queued; waiting for app shutdown.",
        })
        _write_state(state_path, current_state)
        _append_log(base_dir, current_state["message"])

        try:
            command, extra = _worker_command(
                base_dir, python_exe, current_slot, os.getpid()
            )
            kwargs: dict[str, Any] = {
                "cwd": str(base_dir),
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            kwargs.update(extra)
            worker = subprocess.Popen(command, **kwargs)
            current_state["worker_pid"] = int(worker.pid)
            _write_state(state_path, current_state)
            log.info("PYTHON_WEEKLY_UPDATE_QUEUED: slot=%s worker=%s", slot_text, worker.pid)
        except Exception as exc:
            message = f"Could not start weekly Python update worker: {exc}"
            _finish_state(base_dir, slot_text, "failed", message)
            _append_log(base_dir, message, "ERROR")
            log.error("PYTHON_WEEKLY_UPDATE_START_FAIL: %s", exc)
        schedule_next()

    timer.timeout.connect(launch_update)
    schedule_next()
    log.info("PYTHON_WEEKLY_UPDATE_SCHEDULED: Monday %02d:00 local time", UPDATE_HOUR)


def _worker_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the weekly package update worker")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--base-dir", required=True)
    parser.add_argument("--wait-for-pid", type=int, required=True)
    parser.add_argument("--python-exe", required=True)
    parser.add_argument("--slot", required=True)
    args = parser.parse_args(argv)
    if not args.worker:
        parser.error("--worker is required")
    return run_non_windows_worker(
        Path(args.base_dir), args.wait_for_pid, args.python_exe, args.slot
    )


if __name__ == "__main__":
    raise SystemExit(_worker_cli())
