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


def test_windows_registry_roundtrip_with_fake_winreg(monkeypatch):
    store = _fake_winreg(monkeypatch)
    mgr = _mgr(monkeypatch, "windows")  # direct som standard
    assert mgr.set_enabled(True) is True
    written = store[appmod.APP_NAME]
    assert "wscript" not in written.lower()
    assert "--minimized" in written
    assert mgr.get_registered_command() == written
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
