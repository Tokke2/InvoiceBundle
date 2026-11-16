"""Real Windows shell-link integration tests; never touch real autostart."""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="real Windows test")


def _normalize(value: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(value)))


def _read_link(path: Path, run=subprocess.run) -> dict:
    # Independent readback via Windows Script Host. Production creation does
    # not need PowerShell or WScript on the preferred native COM path.
    env = os.environ.copy()
    env["FB_TEST_LINK"] = str(path)
    ps = (
        "[Console]::OutputEncoding = [Text.UTF8Encoding]::new(); "
        "$link = (New-Object -ComObject WScript.Shell).CreateShortcut($env:FB_TEST_LINK); "
        "[ordered]@{target=$link.TargetPath; arguments=$link.Arguments; "
        "workdir=$link.WorkingDirectory; icon=$link.IconLocation; "
        "description=$link.Description; show=$link.WindowStyle} | "
        "ConvertTo-Json -Compress"
    )
    result = run(
        ["powershell", "-NoProfile", "-Command", ps], env=env,
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.lstrip("\ufeff"))


def _manager(monkeypatch, tmp_path, method="direct"):
    import app

    app_dir = tmp_path / "FakturaRäknaren åäö O'Neil"
    app_dir.mkdir()
    (app_dir / "main.pyw").write_text("# test", encoding="utf-8")
    shutil.copyfile(ROOT / "app_icon.ico", app_dir / "app_icon.ico")
    startup = tmp_path / "Autostart med åäö"
    monkeypatch.setattr(app, "BASE_DIR", app_dir)
    monkeypatch.setattr(app, "DATA_DIR", app_dir / "data")
    mgr = app.AutostartManager(method=method)
    monkeypatch.setattr(mgr, "_startup_folder", lambda: startup)
    return app, mgr, startup


def _assert_link(mgr, link: Path, run=subprocess.run):
    readback = _read_link(link, run=run)
    target, args = mgr._shortcut_target()
    assert _normalize(readback["target"]) == _normalize(target)
    assert readback["arguments"] == args
    assert _normalize(readback["workdir"]) == _normalize(mgr.working_directory())
    icon_path, icon_index = readback["icon"].rsplit(",", 1)
    assert _normalize(icon_path) == _normalize(mgr.working_directory() / "app_icon.ico")
    assert icon_index == "0"
    assert readback["description"] == "Fakturabunten"
    assert readback["show"] == 7


@pytest.mark.parametrize("method", ["direct", "launcher"])
def test_native_shell_writes_real_icon_link_without_external_processes(
    monkeypatch, tmp_path, method
):
    app, mgr, startup = _manager(monkeypatch, tmp_path, method)
    real_run = subprocess.run

    def forbidden_shell(*_args, **_kwargs):
        raise AssertionError("the native method must not run PowerShell or WSH")

    monkeypatch.setattr(app.subprocess, "run", forbidden_shell)
    assert mgr._write_startup_shortcut(), mgr._shortcut_last_failure
    link = startup / "Fakturabunten.lnk"
    assert link.is_file()
    _assert_link(mgr, link, run=real_run)


@pytest.mark.parametrize("fallback", ["powershell", "cscript"])
def test_real_windows_fallback_creates_equivalent_link(
    monkeypatch, tmp_path, fallback
):
    import windows_shortcut

    app, mgr, startup = _manager(monkeypatch, tmp_path)
    real_run = subprocess.run

    def no_native(*_args, **_kwargs):
        raise OSError("native API unavailable")

    def maybe_disable_powershell(command, **kwargs):
        if fallback == "cscript" and Path(command[0]).name.lower() == "powershell":
            raise FileNotFoundError("PowerShell disabled")
        return real_run(command, **kwargs)

    monkeypatch.setattr(windows_shortcut, "create_shortcut", no_native)
    monkeypatch.setattr(app.subprocess, "run", maybe_disable_powershell)
    assert mgr._write_startup_shortcut(), mgr._shortcut_last_failure
    _assert_link(mgr, startup / "Fakturabunten.lnk", run=real_run)


def test_native_shortcut_works_when_the_thread_already_uses_com_mta(tmp_path):
    import windows_shortcut

    link = tmp_path / "MTA test.lnk"
    target = sys.executable
    icon = ROOT / "app_icon.ico"
    errors = []

    def worker():
        ole = ctypes.WinDLL("ole32")
        ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        ole.CoInitializeEx.restype = ctypes.c_int32
        ole.CoUninitialize.argtypes = []
        ole.CoUninitialize.restype = None
        code = int(ole.CoInitializeEx(None, 0))  # COINIT_MULTITHREADED
        try:
            if code not in (0, 1):
                raise RuntimeError(f"MTA initialization failed: {code}")
            windows_shortcut.create_shortcut(
                link, target=target, arguments='"Invoice.pyw" --minimized',
                workdir=str(ROOT), icon=str(icon), description="Fakturabunten",
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            if code in (0, 1):
                ole.CoUninitialize()

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(30)
    assert not thread.is_alive(), "COM thread did not finish"
    assert not errors, errors
    assert link.is_file()
    readback = _read_link(link)
    assert _normalize(readback["target"]) == _normalize(target)
    assert readback["arguments"] == '"Invoice.pyw" --minimized'


def test_windows_startup_folder_uses_the_current_user_known_folder():
    import windows_shortcut

    actual = windows_shortcut.startup_folder()
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "[Console]::OutputEncoding = [Text.UTF8Encoding]::new(); "
         "[Environment]::GetFolderPath([Environment+SpecialFolder]::Startup)"],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
    assert _normalize(actual) == _normalize(result.stdout.strip())


def test_failed_real_shortcut_replacement_is_reported_and_can_be_retried(
    monkeypatch, tmp_path
):
    """A real .lnk stays intact, while the settings result reports the failure."""
    import types
    import windows_shortcut

    app, original_mgr, startup = _manager(monkeypatch, tmp_path)
    monkeypatch.setattr(
        app.AutostartManager, "_native_startup_folder", staticmethod(lambda: startup)
    )
    monkeypatch.setattr(app.AutostartManager, "migrate_legacy_if_present", lambda _self: None)
    monkeypatch.setattr(app.AutostartManager, "_retire_legacy_autostart", lambda _self: None)

    # The real Startup folder and HKCU Run key are never touched by this test.
    registry = types.ModuleType("winreg")
    registry.HKEY_CURRENT_USER = 1
    registry.KEY_READ = 1
    registry.KEY_SET_VALUE = 2
    registry.OpenKey = lambda *_args: object()
    registry.CloseKey = lambda _key: None

    def not_found(*_args):
        raise FileNotFoundError("no Run entry in the test registry")

    registry.QueryValueEx = not_found
    registry.DeleteValue = not_found
    monkeypatch.setitem(sys.modules, "winreg", registry)

    assert original_mgr._write_startup_shortcut(), original_mgr._shortcut_last_failure
    link = startup / "Fakturabunten.lnk"
    before_bytes = link.read_bytes()
    before_fields = _read_link(link)
    settings = app.SettingsManager(tmp_path / "settings.json")
    assert settings.get("startup") is True  # an OS entry exists
    mgr = settings.get_autostart_manager()
    new_main = app.BASE_DIR / "annan startfil.pyw"
    new_main.write_text("# new test target", encoding="utf-8")
    mgr._main_py = str(new_main)
    assert mgr._shortcut_is_current() is False
    real_run = subprocess.run

    def fail(*_args, **_kwargs):
        raise PermissionError("simulated inability to create a replacement")

    with monkeypatch.context() as failed:
        failed.setattr(windows_shortcut, "create_shortcut", fail)
        failed.setattr(app.subprocess, "run", fail)
        assert settings.set("startup", True) is False
        assert mgr.is_enabled() is True
        assert link.read_bytes() == before_bytes
        assert _read_link(link, run=real_run) == before_fields
        assert "simulated inability" in mgr._shortcut_last_failure

    # Retrying the same saved setting must create the new target, not infer
    # success merely from the old .lnk's presence.
    assert settings.set("startup", True) is True
    assert mgr._shortcut_is_current() is True
    _assert_link(mgr, link)
    assert _read_link(link)["arguments"] != before_fields["arguments"]
