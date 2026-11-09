# -*- coding: utf-8 -*-
"""
Tester: autostart-metoder (direkt utan VBS / startfil) på
Windows, macOS och Linux + att standardmetoden är VBS-fri.

Plattform simuleras via appmod.CURRENT_PLATFORM + fejkad winreg;
filer skrivs bara under tmp-HOME. Inget rör det riktiga OS:et.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import app as appmod


def _mgr(monkeypatch, platform: str, method: str = "auto"):
    monkeypatch.setattr(appmod, "CURRENT_PLATFORM", platform)
    return appmod.AutostartManager(method=method)


def _fake_winreg(monkeypatch):
    store: dict[str, str] = {}

    fake = types.ModuleType("winreg")
    fake.HKEY_CURRENT_USER = 1
    fake.KEY_READ = 1
    fake.KEY_SET_VALUE = 2
    fake.REG_SZ = 1

    class _Key:
        pass

    def OpenKey(_root, _path, _reserved=0, _access=0):  # noqa: N802
        return _Key()

    def SetValueEx(_key, name, _r, _t, value):  # noqa: N802
        store[name] = value

    def QueryValueEx(_key, name):  # noqa: N802
        if name not in store:
            raise FileNotFoundError(name)
        return store[name], fake.REG_SZ

    def DeleteValue(_key, name):  # noqa: N802
        if name not in store:
            raise FileNotFoundError(name)
        del store[name]

    def CloseKey(_key):  # noqa: N802
        pass

    fake.OpenKey = OpenKey
    fake.SetValueEx = SetValueEx
    fake.QueryValueEx = QueryValueEx
    fake.DeleteValue = DeleteValue
    fake.CloseKey = CloseKey
    monkeypatch.setitem(sys.modules, "winreg", fake)
    return store


def test_method_normalization():
    assert appmod.AutostartManager.normalize_method("DIRECT") == "direct"
    assert appmod.AutostartManager.normalize_method("skräp") == "auto"
    assert appmod.AutostartManager(method="LAUNCHER").resolved_method() \
        == "launcher"
    assert "autostart_method" in appmod.DEFAULT_SETTINGS


def test_autostart_uses_system_python_even_if_app_copy_exists(
    monkeypatch, tmp_path,
):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "main.pyw").write_text("", encoding="utf-8")
    app_local = app_dir / "python"
    app_local.mkdir()
    (app_local / "pythonw.exe").write_text("private", encoding="utf-8")

    system_python = tmp_path / "Programs" / "Python315"
    system_python.mkdir(parents=True)
    python_exe = system_python / "python.exe"
    pythonw_exe = system_python / "pythonw.exe"
    python_exe.write_text("system", encoding="utf-8")
    pythonw_exe.write_text("system", encoding="utf-8")

    monkeypatch.setattr(appmod, "BASE_DIR", app_dir)
    monkeypatch.setattr(
        appmod, "sys",
        types.SimpleNamespace(executable=str(python_exe), frozen=False),
    )
    mgr = _mgr(monkeypatch, "windows")
    assert mgr._python_exe == str(pythonw_exe)
    assert mgr._main_py == str(app_dir / "main.pyw")


def test_linux_autostart_uses_system_python_even_if_app_copy_exists(
    monkeypatch, tmp_path,
):
    app_dir = tmp_path / "app"
    (app_dir / "python" / "bin").mkdir(parents=True)
    (app_dir / "python" / "bin" / "python3").write_text(
        "private", encoding="utf-8"
    )
    system_python = "/usr/bin/python3"
    monkeypatch.setattr(appmod, "BASE_DIR", app_dir)
    monkeypatch.setattr(
        appmod, "sys",
        types.SimpleNamespace(executable=system_python, frozen=False),
    )
    mgr = _mgr(monkeypatch, "linux")
    assert mgr._python_exe == system_python
    assert mgr._main_py == str(app_dir / "main.py")


def test_generated_and_static_launchers_only_choose_system_python(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(appmod, "BASE_DIR", tmp_path)
    linux = _mgr(monkeypatch, "linux")
    shell = linux._sh_text()
    assert '"$APP_DIR/python/bin/' not in shell
    assert "command -v python3" in shell

    windows = _mgr(monkeypatch, "windows", method="launcher")
    vbs = windows._vbs_text()
    assert 'appDir & "\\\\python\\\\pythonw.exe"' not in vbs
    assert "%LocalAppData%" in vbs
    assert "%ProgramFiles%" in vbs

    static_sh = (PROJECT_DIR / "autostart" / "start_hidden.sh").read_text(
        encoding="utf-8"
    )
    static_vbs = (PROJECT_DIR / "autostart" / "start_hidden.vbs").read_text(
        encoding="utf-16"
    )
    assert "APP_DIR/python/bin/" not in static_sh
    assert 'appDir & "\\\\python\\\\pythonw.exe"' not in static_vbs


def test_windows_direct_has_no_vbs(monkeypatch):
    mgr = _mgr(monkeypatch, "windows")
    cmd = mgr.build_command()
    assert "vbs" not in cmd.lower()
    assert "wscript" not in cmd.lower()
    assert "--minimized" in cmd
    assert mgr.plan()["uses_launcher"] is False
    assert "direktstart, utan VBS" in mgr.user_message(True)

    legacy = _mgr(monkeypatch, "windows", method="launcher")
    cmd2 = legacy.build_command()
    assert "wscript" in cmd2.lower()
    assert "start_hidden.vbs" in cmd2.replace("\\", "/")
    assert legacy.plan()["launcher"].endswith("start_hidden.vbs")


def test_windows_direct_uses_icon_shortcut_without_run_entry(
    monkeypatch, tmp_path
):
    store = _fake_winreg(monkeypatch)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    mgr = _mgr(monkeypatch, "windows")  # direct som standard

    def fake_write_shortcut(self):
        link = self._startup_shortcut_path()
        link.parent.mkdir(parents=True, exist_ok=True)
        link.write_bytes(b"LNK")
        return True

    monkeypatch.setattr(
        type(mgr), "_write_startup_shortcut", fake_write_shortcut
    )
    assert mgr.set_enabled(True) is True
    assert mgr._startup_shortcut_path().exists()
    assert appmod.APP_NAME not in store  # aldrig pythonw i Run-nyckeln
    assert mgr.is_enabled() is True
    assert mgr.set_enabled(False) is True
    assert mgr.is_enabled() is False


def test_linux_direct_and_launcher_desktop_files(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    mgr = _mgr(monkeypatch, "linux")  # direkt
    assert mgr.set_enabled(True) is True
    desktop = (
        tmp_path / ".config" / "autostart" / "Fakturabunten.desktop"
    )
    text = desktop.read_text(encoding="utf-8")
    assert "start_hidden" not in text
    assert "--minimized" in text
    assert f"Path={appmod.BASE_DIR}" in text
    assert mgr.is_enabled() is True
    assert mgr.set_enabled(False) is True
    assert not desktop.exists()

    launcher_mgr = _mgr(monkeypatch, "linux", method="launcher")
    assert launcher_mgr.set_enabled(True) is True
    text2 = desktop.read_text(encoding="utf-8")
    assert "start_hidden.sh" in text2
    launcher_mgr.set_enabled(False)


def test_macos_plist_direct_and_launcher(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    calls = []
    mgr = _mgr(monkeypatch, "macos")
    monkeypatch.setattr(
        mgr, "_launchctl", lambda a, p: calls.append(a)
    )
    assert mgr.set_enabled(True) is True
    plist = (
        tmp_path / "Library" / "LaunchAgents"
        / "com.fakturabunten.plist"
    )
    text = plist.read_text(encoding="utf-8")
    assert "--minimized" in text
    assert "start_hidden" not in text
    assert f"<string>{appmod.BASE_DIR}</string>" in text  # WorkingDir
    assert calls == ["load"]

    launcher_mgr = _mgr(monkeypatch, "macos", method="launcher")
    monkeypatch.setattr(
        launcher_mgr, "_launchctl", lambda a, p: calls.append(a)
    )
    assert launcher_mgr.set_enabled(True) is True
    text2 = plist.read_text(encoding="utf-8")
    assert "start_hidden.sh" in text2
    assert "/bin/sh" in text2
