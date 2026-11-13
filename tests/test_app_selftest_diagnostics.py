# -*- coding: utf-8 -*-
"""Run the standalone app.py self-test in an isolated program folder."""
from __future__ import annotations

import datetime
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_standalone_selftest_has_no_spurious_warnings(tmp_path):
    pytest.importorskip("PySide6")
    pytest.importorskip("pymupdf")
    from build_release import RELEASE_FILES

    app_dir = tmp_path / "Fakturabunten"
    for relative in RELEASE_FILES:
        source = ROOT / relative
        dest = app_dir / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)

    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env.update({
        "HOME": str(home),
        "USERPROFILE": str(home),
        "APPDATA": str(home / "AppData"),
        "QT_QPA_PLATFORM": "offscreen",
        "PYTHONPATH": str(app_dir),
    })
    before = datetime.date.today()
    result = subprocess.run(
        [sys.executable, str(app_dir / "app.py")],
        cwd=app_dir, env=env, capture_output=True, text=True, timeout=60,
    )
    after = datetime.date.today()
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "app.py självtest klart" in output
    assert "Qt-brygga: ingen QApplication ännu; försöker igen" in output
    assert "Qt-brygga: ingen QApplication ännu — hoppar över" not in output
    assert "The `fitz` API is deprecated" not in output
    assert "Session-datum" in output and "är PASSERAT" not in output
    assert any(
        all((day + datetime.timedelta(days=offset)).isoformat() in output
            for offset in (30, 45))
        for day in (before, after)
    )
