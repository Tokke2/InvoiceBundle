"""Run the disabled manual entry point on Windows without touching Python."""
from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="real Windows test")


def test_disabled_batch_shows_notice_without_running_the_powershell_updater(tmp_path):
    app_dir = tmp_path / "Fakturabunten med mellanslag"
    (app_dir / "autostart").mkdir(parents=True)
    batch = app_dir / "Installera senaste Python.bat"
    shutil.copyfile(ROOT / batch.name, batch)
    sentinel = tmp_path / "powershell_was_called.txt"
    # A harmless replacement ensures that even an accidentally active old
    # BAT file cannot install, remove or modify Python during this test.
    (app_dir / "autostart" / "install_python.ps1").write_text(
        "Set-Content -LiteralPath $env:FB_TEST_PYTHON_SENTINEL -Value 'called'\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["FB_TEST_PYTHON_SENTINEL"] = str(sentinel)
    result = subprocess.run(
        [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "call", str(batch)],
        cwd=app_dir, env=env, input="", capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=15,
    )
    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
    assert "avaktiverad" in result.stdout.lower()
    assert "automatiska veckokontrollen" in result.stdout.lower()
    assert not sentinel.exists()


def test_weekly_windows_worker_remains_separate_from_the_disabled_batch(tmp_path):
    from plugins import python_update_scheduler as scheduler

    interpreter = str(tmp_path / "Python" / "pythonw.exe")
    args, _extra = scheduler._worker_command(
        tmp_path, interpreter, dt.datetime(2026, 10, 12, 8), 12345
    )
    assert Path(args[args.index("-File") + 1]) == tmp_path / "autostart" / "install_python.ps1"
    assert args[args.index("-PythonExe") + 1] == interpreter
    assert args[args.index("-WaitForPid") + 1] == "12345"
    assert "-UpdatePackages" in args
    assert not any(Path(part).name == "Installera senaste Python.bat" for part in args)
