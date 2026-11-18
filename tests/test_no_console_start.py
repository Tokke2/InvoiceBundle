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
    assert "--minimized" in cmd[2]


def test_scan_import_suppresses_console_in_pytesseract_checks_and_ocr(monkeypatch):
    """Tesseract version probe and OCR must both inject CREATE_NO_WINDOW on Windows."""
    import types
    import plugins.scan_import as si

    recorded = []

    class _FakeSubprocess:
        CREATE_NO_WINDOW = 0x08000000
        STARTF_USESHOWWINDOW = 1
        SW_HIDE = 0

        @staticmethod
        def check_output(*args, **kwargs):
            recorded.append(("check_output", args, kwargs))
            return b"tesseract 5.4.0\n"

        @staticmethod
        def Popen(*args, **kwargs):  # noqa: N802
            recorded.append(("Popen", args, kwargs))
            return types.SimpleNamespace(returncode=0)

    def _orig_subprocess_args(include_stdout=True):
        return {"stdin": -1, "stderr": -1, "include_stdout": include_stdout}

    fake_engine = types.SimpleNamespace(
        tesseract_cmd="tesseract.exe",
        subprocess=_FakeSubprocess,
        subprocess_args=_orig_subprocess_args,
    )
    fake_pyt = types.SimpleNamespace(pytesseract=fake_engine)
    monkeypatch.setattr(si, "HAS_TESS", True)
    monkeypatch.setattr(si, "pytesseract", fake_pyt, raising=False)
    monkeypatch.setattr(si.sys, "platform", "win32")

    si._install_pytesseract_no_console_hooks()
    fake_engine.subprocess.check_output(["tesseract.exe", "--version"])
    fake_engine.subprocess.Popen(["tesseract.exe", "in.png", "out"])
    args_dict = fake_engine.subprocess_args()

    assert recorded[0][0] == "check_output"
    assert recorded[0][2]["creationflags"] & 0x08000000
    assert recorded[1][0] == "Popen"
    assert recorded[1][2]["creationflags"] & 0x08000000
    assert args_dict["creationflags"] & 0x08000000


def test_ensure_packages_and_scheduler_hide_windows_consoles(tmp_path, monkeypatch):
    import ensure_packages as ep
    from plugins import python_update_scheduler as sched

    pip_calls = []

    class _FakeProc:
        stdout = iter(())

        @staticmethod
        def wait():
            return 0

    monkeypatch.setattr(ep.sys, "platform", "win32")
    monkeypatch.setattr(
        ep.subprocess,
        "Popen",
        lambda cmd, **kw: pip_calls.append((cmd, kw)) or _FakeProc(),
    )
    assert ep._run_pip(["python.exe", "-m", "pip", "install"], None, "x") == 0
    assert pip_calls[0][1]["creationflags"] & 0x08000000
    assert pip_calls[0][1]["stdin"] is ep.subprocess.DEVNULL

    (tmp_path / "requirements.txt").write_text("PySide6>=6.6\n", encoding="utf-8")
    (tmp_path / "ensure_packages.py").write_text("# test\n", encoding="utf-8")
    worker_calls = []
    monkeypatch.setattr(sched.sys, "platform", "win32")
    monkeypatch.setattr(sched, "_wait_for_pid", lambda _pid: None)
    monkeypatch.setattr(sched, "_append_log", lambda *_a, **_k: None)
    monkeypatch.setattr(
        sched.subprocess,
        "Popen",
        lambda cmd, **kw: worker_calls.append((cmd, kw)) or _FakeProc(),
    )
    assert sched.run_package_worker(tmp_path, 1, "python.exe", "2026-10-12T08:00:00") == 0
    assert worker_calls[0][1]["creationflags"] & 0x08000000
    assert worker_calls[0][1]["stdin"] is sched.subprocess.DEVNULL


def test_windows_shortcut_prefers_native_com_without_powershell(tmp_path, monkeypatch):
    import main as m
    import windows_shortcut as ws

    (tmp_path / "app_icon.ico").write_bytes(b"ico")
    (tmp_path / "main.pyw").write_text("# app", encoding="utf-8")
    pyw = tmp_path / "pythonw.exe"
    pyw.write_text("", encoding="utf-8")

    monkeypatch.setattr(m, "CURRENT_PLATFORM", "windows")
    monkeypatch.setattr(m, "BASE_DIR", tmp_path)
    monkeypatch.setattr(m.sys, "executable", str(pyw))
    monkeypatch.setattr(
        m.subprocess,
        "run",
        lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("PowerShell must not run")),
    )
    created = []
    monkeypatch.setattr(
        ws,
        "create_shortcut",
        lambda dest, **kw: (Path(dest).write_bytes(b"lnk"), created.append((Path(dest), kw))),
    )
    m._windows_shortcut()
    assert (tmp_path / "Fakturabunten.lnk").is_file()
    assert len(created) == 1
    assert "--minimized" in created[0][1]["arguments"]
    assert created[0][1]["show_cmd"] == 7


def test_launcher_scripts_hide_consoles():
    bat = (PROJECT_DIR / "Starta Fakturabunten.bat").read_text(encoding="utf-8")
    ps1 = (PROJECT_DIR / "autostart" / "start_fakturabunten.ps1").read_text(encoding="utf-8")
    sh = (PROJECT_DIR / "Starta Fakturabunten.sh").read_text(encoding="utf-8")
    assert "-WindowStyle Hidden" in bat
    assert "pause" not in bat.lower()
    assert "Hide-LauncherConsole" in ps1
    assert "Invoke-HiddenProcess" in ps1
    assert "CreateNoWindow = $true" in ps1
    assert "nohup" in sh

