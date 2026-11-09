# -*- coding: utf-8 -*-
"""
Inget konsolfönster vid start av appen (Windows).

Appen ska ALLTID starta fönsterlöst:
- startas den ändå med konsoltolken python.exe (gammal genväg,
  dubbelklick på main.py, .bat) startar den om sig själv med
  pythonw.exe + main.pyw och avslutar direkt;
- omstarten efter en uppdatering väljer main.pyw och
  pythonw.exe, aldrig konsolvarianterna;
- --debug/--selftest rörs inte (där vill man se konsolen).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "ui"),
           str(PROJECT_DIR / "plugins")):
    if _d not in sys.path:
        sys.path.insert(0, _d)


def test_windowless_python_maps_python_exe_to_pythonw(
        tmp_path, monkeypatch):
    import main as m

    monkeypatch.setattr(m, "CURRENT_PLATFORM", "windows")
    exe = tmp_path / "python.exe"
    pyw = tmp_path / "pythonw.exe"
    exe.write_text("", encoding="utf-8")
    # Saknas pythonw bredvid -> ingen mappning (fallback: dölj)
    assert m._windowless_python(str(exe)) is None
    pyw.write_text("", encoding="utf-8")
    assert m._windowless_python(str(exe)) == pyw
    # Redan fönsterlös tolk används som den är
    assert m._windowless_python(str(pyw)) == pyw


def test_windowless_python_never_on_other_platforms(
        tmp_path, monkeypatch):
    import main as m

    monkeypatch.setattr(m, "CURRENT_PLATFORM", "linux")
    assert m._windowless_python(str(tmp_path / "python.exe")) is None


def test_relaunch_windowless_starts_pythonw_and_exits(
        tmp_path, monkeypatch):
    import main as m

    monkeypatch.setattr(m, "CURRENT_PLATFORM", "windows")
    monkeypatch.setattr(m, "DEBUG_MODE", False)
    monkeypatch.setattr(m, "SELFTEST", False)
    monkeypatch.delenv(m._WINDOWLESS_GUARD, raising=False)
    (tmp_path / "main.pyw").write_text("", encoding="utf-8")
    monkeypatch.setattr(m, "BASE_DIR", tmp_path)
    pyw = tmp_path / "pythonw.exe"
    monkeypatch.setattr(m, "_windowless_python", lambda *_a: pyw)

    calls: list = []

    class _Popen:
        def __init__(self, cmd, **kw):
            calls.append((cmd, kw))

    monkeypatch.setattr(m.subprocess, "Popen", _Popen)
    assert m._relaunch_windowless() is True
    cmd, kw = calls[0]
    assert cmd[0] == str(pyw)
    assert cmd[1] == str(tmp_path / "main.pyw")
    assert kw["env"][m._WINDOWLESS_GUARD] == "1"

    # Skyddet hindrar oändlig omstartsloop
    monkeypatch.setenv(m._WINDOWLESS_GUARD, "1")
    assert m._relaunch_windowless() is False


def test_relaunch_never_in_debug_or_selftest(monkeypatch):
    import main as m

    monkeypatch.setattr(m, "CURRENT_PLATFORM", "windows")
    monkeypatch.setattr(m, "DEBUG_MODE", True)
    monkeypatch.setattr(m, "SELFTEST", False)
    assert m._relaunch_windowless() is False
    monkeypatch.setattr(m, "DEBUG_MODE", False)
    monkeypatch.setattr(m, "SELFTEST", True)
    assert m._relaunch_windowless() is False


def test_update_restart_prefers_pyw_and_pythonw(
        tmp_path, monkeypatch):
    """Omstart efter uppdatering: main.pyw + pythonw.exe."""
    import ui.update_dialog as upd

    (tmp_path / "main.py").write_text("", encoding="utf-8")
    (tmp_path / "main.pyw").write_text("", encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "python.exe").write_text("", encoding="utf-8")
    (bindir / "pythonw.exe").write_text("", encoding="utf-8")

    calls: list = []

    class _Popen:
        def __init__(self, cmd, **kw):
            calls.append((cmd, kw))

    monkeypatch.setattr(upd.subprocess, "Popen", _Popen)
    monkeypatch.setattr(
        upd.sys, "executable", str(bindir / "python.exe"))
    monkeypatch.setattr(upd.sys, "platform", "win32")

    assert upd.schedule_restart(tmp_path) is True
    cmd, _kw = calls[0]
    assert cmd[0] == str(bindir / "pythonw.exe")   # aldrig python.exe
    assert "main.pyw" in cmd[2]                    # aldrig main.py
    assert "main.py'" not in cmd[2]
