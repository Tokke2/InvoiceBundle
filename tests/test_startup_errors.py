"""Startup errors are visible without requiring Qt or installing Python."""
from __future__ import annotations

import ctypes
import os
import runpy
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_windows_startup_error_uses_native_dialog_without_tkinter(monkeypatch):
    import ensure_packages

    calls = []
    user32 = types.SimpleNamespace(
        MessageBoxW=lambda *args: calls.append(args) or 1,
    )
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", "win32")
        patch.setattr(ctypes, "windll", types.SimpleNamespace(user32=user32), raising=False)
        patch.setitem(sys.modules, "tkinter", None)
        ensure_packages._tell_user("Startfel", "Ett tillbehör saknas")
    assert calls == [(0, "Ett tillbehör saknas", "Startfel", 0x10)]


@pytest.mark.parametrize("platform,dialog", [("darwin", "osascript"), ("linux", "zenity")])
def test_desktop_fallback_when_tkinter_missing(monkeypatch, platform, dialog):
    import ensure_packages

    calls = []
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", platform)
        patch.setitem(sys.modules, "tkinter", None)
        patch.setenv("DISPLAY", ":99")
        patch.setattr(ensure_packages.shutil, "which", lambda name: f"/bin/{name}" if name == dialog else None)
        patch.setattr(
            ensure_packages.subprocess, "run",
            lambda args, **kwargs: calls.append((args, kwargs)) or types.SimpleNamespace(returncode=0),
        )
        ensure_packages._tell_user("Startfel", "Ett tillbehör saknas")
    assert len(calls) == 1
    assert calls[0][0][0] == dialog
    if platform == "darwin":
        assert calls[0][0][-2:] == ["Startfel", "Ett tillbehör saknas"]
    else:
        assert calls[0][0] == [
            "zenity", "--error", "--title", "Startfel", "--text", "Ett tillbehör saknas"
        ]


def test_error_falls_back_to_stderr_without_a_gui(monkeypatch, capsys):
    import ensure_packages

    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", "linux")
        patch.setitem(sys.modules, "tkinter", None)
        patch.delenv("DISPLAY", raising=False)
        patch.delenv("WAYLAND_DISPLAY", raising=False)
        ensure_packages._tell_user("Startfel", "Paket saknas")
    assert "Startfel\nPaket saknas" in capsys.readouterr().err


def test_missing_companion_is_reported_not_silently_dropped(monkeypatch, tmp_path):
    import main

    messages = []
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)
    monkeypatch.setattr(main, "_show_startup_error", messages.append)
    with pytest.raises(SystemExit) as exc:
        main._abort_missing_files([tmp_path / "app.py"])
    assert exc.value.code == 1
    assert len(messages) == 1 and "app.py" in messages[0]
    assert "Rör inte data" in messages[0]


def test_missing_error_helper_still_uses_native_windows_dialog(monkeypatch):
    import main

    calls = []
    user32 = types.SimpleNamespace(MessageBoxW=lambda *args: calls.append(args) or 1)
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "ensure_packages", None)
        patch.setattr(main, "CURRENT_PLATFORM", "windows")
        patch.setattr(ctypes, "windll", types.SimpleNamespace(user32=user32), raising=False)
        main._show_startup_error("Appfil saknas")
    assert calls and calls[0][1] == "Appfil saknas"


def test_unhandled_startup_error_is_logged_and_shown(monkeypatch):
    import main

    recorded = []
    shown = []

    def broken_main():
        raise ValueError("fel vid start")

    monkeypatch.setattr(main, "main", broken_main)
    monkeypatch.setattr(main, "_write_startup_crash", recorded.append)
    monkeypatch.setattr(main, "_show_startup_error", shown.append)
    with pytest.raises(SystemExit) as exc:
        main.run_with_crash_reporting()
    assert exc.value.code == 1
    assert len(recorded) == 1 and str(recorded[0]) == "fel vid start"
    assert len(shown) == 1 and "fel vid start" in shown[0]


def test_windowless_entry_uses_same_crash_reporting(monkeypatch):
    calls = []
    fake_main = types.ModuleType("main")
    fake_main.run_with_crash_reporting = lambda: calls.append("called")
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "main", fake_main)
        runpy.run_path(str(ROOT / "main.pyw"), run_name="__main__")
    assert calls == ["called"]


@pytest.mark.parametrize("entry", ["main.py", "main.pyw"])
def test_incomplete_installation_reports_missing_files_end_to_end(tmp_path, entry):
    # Use a real fresh interpreter and both real entry points. The dialog
    # itself is replaced with a marker so this test cannot block CI.
    app = tmp_path / "App med mellanslag"
    app.mkdir()
    shutil.copyfile(ROOT / "main.py", app / "main.py")
    shutil.copyfile(ROOT / "main.pyw", app / "main.pyw")
    (app / "ensure_packages.py").write_text(
        "import os\nfrom pathlib import Path\n"
        "def _tell_user(title, text):\n"
        "    Path(os.environ['FB_ERROR_MARKER']).write_text(title + '\\n' + text, encoding='utf-8')\n",
        encoding="utf-8",
    )
    marker = tmp_path / "error.txt"
    env = dict(os.environ, FB_ERROR_MARKER=str(marker))
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(app / entry), "--selftest"],
        cwd=app, env=env, capture_output=True, text=True, errors="replace", timeout=30,
    )
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert marker.is_file(), (result.stdout, result.stderr)
    text = marker.read_text(encoding="utf-8")
    assert "Startfel" in text and "app.py" in text and "Rör inte data" in text
