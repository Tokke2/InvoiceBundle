"""Python runtime selection: prefer a tested 3.15, then fall back safely."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _directory in (
    str(PROJECT_DIR), str(PROJECT_DIR / "ui"), str(PROJECT_DIR / "plugins")
):
    if _directory not in sys.path:
        sys.path.insert(0, _directory)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _main_module(monkeypatch, version=(3, 14, 0), executable="python314"):
    import main

    monkeypatch.setattr(
        main, "sys",
        SimpleNamespace(
            version_info=version,
            executable=executable,
            argv=["main.py"],
        ),
    )
    monkeypatch.setattr(main, "CURRENT_PLATFORM", "linux")
    monkeypatch.setattr(main, "DEBUG_MODE", False)
    monkeypatch.setattr(main, "SELFTEST", False)
    monkeypatch.delenv(main._RUNTIME_ATTEMPTS, raising=False)
    return main


def test_prefer_python_315_only_when_runtime_probe_passes(monkeypatch):
    main = _main_module(monkeypatch)
    calls = []
    monkeypatch.setattr(
        main, "_system_python_candidates",
        lambda: [("python315", (3, 15, 2)), ("python314", (3, 14, 9))],
    )
    monkeypatch.setattr(
        main, "_python_has_runtime", lambda executable: executable == "python315"
    )
    monkeypatch.setattr(
        main, "_spawn_with_python",
        lambda executable, **kwargs: calls.append((executable, kwargs)) or True,
    )

    assert main._relaunch_preferred_python() is True
    assert calls[0][0] == "python315"
    assert calls[0][1]["mark_current"] is False


def test_unusable_python_315_keeps_current_runtime(monkeypatch):
    main = _main_module(monkeypatch)
    calls = []
    monkeypatch.setattr(
        main, "_system_python_candidates",
        lambda: [("python315", (3, 15, 2))],
    )
    monkeypatch.setattr(main, "_python_has_runtime", lambda _executable: False)
    monkeypatch.setattr(
        main, "_spawn_with_python",
        lambda executable, **kwargs: calls.append((executable, kwargs)) or True,
    )

    assert main._relaunch_preferred_python() is False
    assert calls == []


def test_failed_runtime_falls_back_to_healthy_python_314(monkeypatch):
    main = _main_module(monkeypatch, version=(3, 15, 2), executable="python315")
    calls = []
    monkeypatch.setattr(
        main, "_system_python_candidates",
        lambda: [
            ("python314", (3, 14, 9)),
            ("python313", (3, 13, 8)),
        ],
    )
    monkeypatch.setattr(
        main, "_python_has_runtime", lambda executable: executable == "python314"
    )
    monkeypatch.setattr(
        main, "_spawn_with_python",
        lambda executable, **kwargs: calls.append((executable, kwargs)) or True,
    )

    assert main._relaunch_runtime_fallback() is True
    assert calls[0][0] == "python314"
    assert calls[0][1]["mark_current"] is True


def test_python_discovery_ignores_app_local_runtime(monkeypatch, tmp_path):
    main = _main_module(monkeypatch)
    monkeypatch.setattr(main, "CURRENT_PLATFORM", "linux")
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)
    private = tmp_path / "python" / "bin" / "python3.15"
    private.parent.mkdir(parents=True)
    private.write_text("private", encoding="utf-8")
    assert main._is_app_local_python(private)
    commands = []

    def _which(name):
        if name == "python3.15":
            return str(private)
        if name == "python3.14":
            return "/usr/bin/python3.14"
        return None

    def _inspect(command):
        commands.append(command)
        if command == ["/usr/bin/python3.14"]:
            return "/usr/bin/python3.14", (3, 14, 9)
        return None

    monkeypatch.setattr(main.shutil, "which", _which)
    monkeypatch.setattr(main, "_inspect_python", _inspect)

    assert main._system_python_candidates() == [
        ("/usr/bin/python3.14", (3, 14, 9))
    ]
    assert commands == [["/usr/bin/python3.14"]]


def test_runtime_attempt_guard_prevents_returning_to_failed_python(monkeypatch):
    main = _main_module(monkeypatch, version=(3, 14, 9), executable="python314")
    monkeypatch.setenv(
        main._RUNTIME_ATTEMPTS,
        '["python314", "python315"]',
    )
    calls = []
    monkeypatch.setattr(
        main, "_system_python_candidates",
        lambda: [
            ("python315", (3, 15, 2)),
            ("python314", (3, 14, 9)),
        ],
    )
    monkeypatch.setattr(main, "_python_has_runtime", lambda _executable: True)
    monkeypatch.setattr(
        main, "_spawn_with_python",
        lambda executable, **kwargs: calls.append((executable, kwargs)) or True,
    )

    assert main._relaunch_runtime_fallback() is False
    assert calls == []
