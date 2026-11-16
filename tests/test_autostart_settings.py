"""Autostart retries, failure propagation and startup safety without real OS writes."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as appmod


@pytest.fixture
def fake_windows(monkeypatch, tmp_path):
    """Isolate the Windows Startup folder and registry, even on Windows CI."""
    startup = tmp_path / "Startup"
    registry: dict[str, str] = {}
    fake = types.ModuleType("winreg")
    fake.HKEY_CURRENT_USER = 1
    fake.KEY_READ = 1
    fake.KEY_SET_VALUE = 2
    fake.REG_SZ = 1
    fake.OpenKey = lambda *_args: object()
    fake.CloseKey = lambda _key: None

    def query(_key, name):
        if name not in registry:
            raise FileNotFoundError(name)
        return registry[name], fake.REG_SZ

    def delete(_key, name):
        if name not in registry:
            raise FileNotFoundError(name)
        del registry[name]

    fake.QueryValueEx = query
    fake.DeleteValue = delete
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(appmod, "CURRENT_PLATFORM", "windows")
    monkeypatch.setattr(appmod, "BASE_DIR", tmp_path / "app")
    monkeypatch.setattr(appmod, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(
        appmod.AutostartManager, "_native_startup_folder",
        staticmethod(lambda: startup),
    )
    monkeypatch.setattr(
        appmod.AutostartManager, "_retire_legacy_autostart", lambda _self: None
    )
    return startup, registry


@pytest.mark.parametrize("operation", ["set", "update"])
def test_saved_enabled_setting_can_retry_when_os_entry_is_missing(
    fake_windows, monkeypatch, tmp_path, operation
):
    startup, registry = fake_windows
    settings = appmod.SettingsManager(tmp_path / "settings.json")
    mgr = settings.get_autostart_manager()
    calls = []

    def create():
        calls.append(1)
        if len(calls) == 1:
            mgr._shortcut_last_failure = "test failure"
            return False
        startup.mkdir(parents=True, exist_ok=True)
        (startup / "Fakturabunten.lnk").write_bytes(b"new shortcut")
        return True

    monkeypatch.setattr(mgr, "_write_startup_shortcut", create)

    def request():
        if operation == "set":
            return settings.set("startup", True)
        return settings.update({"startup": True})

    result = request()
    if operation == "set":
        assert result is False
    assert settings.get("startup") is True
    assert json.loads((tmp_path / "settings.json").read_text("utf-8"))["startup"] is True
    assert mgr.is_enabled() is False

    result = request()  # unchanged desired value must not suppress the retry
    if operation == "set":
        assert result is True
    assert len(calls) == 2
    assert mgr.is_enabled() is True
    assert not registry


def test_failed_replacement_is_reported_and_older_shortcut_is_preserved(
    fake_windows, monkeypatch, tmp_path
):
    startup, registry = fake_windows
    settings = appmod.SettingsManager(tmp_path / "settings.json")
    mgr = settings.get_autostart_manager()
    startup.mkdir(parents=True)
    link = startup / "Fakturabunten.lnk"
    link.write_bytes(b"old shortcut")
    attempts = []

    def replace():
        attempts.append(1)
        if len(attempts) == 1:
            mgr._shortcut_last_failure = "access denied in test"
            return False
        link.write_bytes(b"new shortcut")
        return True

    monkeypatch.setattr(mgr, "_write_startup_shortcut", replace)
    assert settings.set("startup", True) is False
    assert settings.get("startup") is True
    assert mgr.is_enabled() is True  # existence alone does not mean the update worked
    assert link.read_bytes() == b"old shortcut"
    assert not registry

    # Same saved value and an existing but unconfirmed link: retry the update.
    assert settings.set("startup", True) is True
    assert attempts == [1, 1]
    assert link.read_bytes() == b"new shortcut"
    assert mgr._shortcut_is_current() is True
    assert not registry


def test_unchanged_cached_link_is_not_rewritten(fake_windows, monkeypatch, tmp_path):
    startup, _ = fake_windows
    settings = appmod.SettingsManager(tmp_path / "settings.json")
    mgr = settings.get_autostart_manager()
    startup.mkdir(parents=True)
    (startup / "Fakturabunten.lnk").write_bytes(b"existing")
    mgr._remember_shortcut()
    assert settings.set("startup", True) is True

    def forbidden():
        raise AssertionError("unchanged cached shortcut must not be rewritten")

    monkeypatch.setattr(mgr, "_write_startup_shortcut", forbidden)
    assert settings.set("startup", True) is True
    assert settings.set("theme", "dark") is None


def test_missing_launcher_is_retried_even_if_shortcut_cache_matches(
    fake_windows, monkeypatch, tmp_path
):
    startup, _ = fake_windows
    settings = appmod.SettingsManager(tmp_path / "settings.json")
    settings.set("autostart_method", "launcher")
    mgr = settings.get_autostart_manager()
    startup.mkdir(parents=True)
    (startup / "Fakturabunten.lnk").write_bytes(b"existing")
    mgr._remember_shortcut()
    # The desired state was already saved, but the launcher file is gone.
    settings._data["startup"] = True
    assert mgr._shortcut_is_current() is True
    assert mgr._launcher_is_current() is False
    calls = []
    monkeypatch.setattr(mgr, "set_enabled", lambda value: calls.append(value) or True)
    assert settings.set("startup", True) is True
    assert calls == [True]


def test_disabled_setting_retries_when_os_entry_still_exists(
    fake_windows, monkeypatch, tmp_path
):
    startup, _ = fake_windows
    settings = appmod.SettingsManager(tmp_path / "settings.json")
    mgr = settings.get_autostart_manager()
    startup.mkdir(parents=True)
    link = startup / "Fakturabunten.lnk"
    link.write_bytes(b"old shortcut")
    calls = []

    def disable(value):
        calls.append(value)
        assert value is False
        if len(calls) == 1:
            return False
        link.unlink()
        return True

    monkeypatch.setattr(mgr, "set_enabled", disable)
    assert settings.set("startup", False) is False
    assert link.exists()
    assert settings.set("startup", False) is True
    assert calls == [False, False]
    assert not link.exists()


@pytest.mark.parametrize("platform", ["windows", "linux", "macos"])
def test_verify_direct_method_does_not_require_writing_a_launcher(
    monkeypatch, tmp_path, platform
):
    monkeypatch.setattr(appmod, "CURRENT_PLATFORM", platform)
    monkeypatch.setattr(appmod.AutostartManager, "_retire_legacy_autostart", lambda _self: None)
    monkeypatch.setattr(appmod.AutostartManager, "is_enabled", lambda _self: True)
    mgr = appmod.AutostartManager(method="direct")
    monkeypatch.setattr(mgr, "_write_launcher", lambda: pytest.fail("direct needs no launcher"))
    if platform == "windows":
        monkeypatch.setattr(mgr, "_win_set", lambda enabled: enabled)
    elif platform == "linux":
        desktop = tmp_path / "Fakturabunten.desktop"
        desktop.write_text(
            f"Exec={mgr._desktop_exec_value()}\nPath={appmod.BASE_DIR}\n", encoding="utf-8"
        )
        monkeypatch.setattr(mgr, "_linux_path", lambda: desktop)
    else:
        plist = tmp_path / "com.fakturabunten.plist"
        plist.write_text(
            f"<string>--minimized</string><string>{appmod.BASE_DIR}</string>",
            encoding="utf-8",
        )
        monkeypatch.setattr(mgr, "_macos_path", lambda: plist)
    assert mgr.verify_and_update() is True


def test_launcher_write_failure_is_reported_not_raised(monkeypatch, caplog):
    monkeypatch.setattr(appmod.AutostartManager, "_retire_legacy_autostart", lambda _self: None)
    monkeypatch.setattr(appmod.AutostartManager, "is_enabled", lambda _self: True)
    mgr = appmod.AutostartManager(method="launcher")
    monkeypatch.setattr(mgr, "_launcher_is_current", lambda: False)

    def denied():
        raise PermissionError("test launcher permission denied")

    monkeypatch.setattr(mgr, "_write_launcher", denied)
    assert mgr.verify_and_update() is False
    assert "test launcher permission denied" in caplog.text


def test_autostart_sync_error_does_not_prevent_settings_from_loading(
    monkeypatch, tmp_path, caplog
):
    monkeypatch.setattr(appmod.AutostartManager, "migrate_legacy_if_present", lambda _self: None)
    monkeypatch.setattr(appmod.AutostartManager, "is_enabled", lambda _self: True)

    def fail(_self):
        raise PermissionError("test OS error")

    monkeypatch.setattr(appmod.AutostartManager, "verify_and_update", fail)
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"startup": True, "theme": "light"}), encoding="utf-8")
    settings = appmod.SettingsManager(path)
    assert settings.get("startup") is True
    assert settings.get("theme") == "light"
    assert "test OS error" in caplog.text


@pytest.mark.parametrize("platform", ["windows", "linux", "macos"])
def test_batch_method_change_reregisters_even_when_startup_is_already_true(
    monkeypatch, tmp_path, platform
):
    monkeypatch.setattr(appmod, "CURRENT_PLATFORM", platform)
    monkeypatch.setattr(appmod.AutostartManager, "migrate_legacy_if_present", lambda _self: None)
    state = {"enabled": False}
    monkeypatch.setattr(appmod.AutostartManager, "is_enabled", lambda _self: state["enabled"])
    monkeypatch.setattr(appmod.AutostartManager, "_shortcut_is_current", lambda _self: True)
    monkeypatch.setattr(appmod.AutostartManager, "_launcher_is_current", lambda _self: True)
    calls = []

    def set_enabled(self, enabled):
        calls.append((self.method, enabled))
        state["enabled"] = enabled
        return True

    monkeypatch.setattr(appmod.AutostartManager, "set_enabled", set_enabled)
    settings = appmod.SettingsManager(tmp_path / "settings.json")
    settings.set("startup", True)
    assert calls == [("auto", True)]
    settings.update({"startup": True, "autostart_method": "launcher"})
    assert calls == [("auto", True), ("launcher", True)]


def test_failed_shortcut_removal_is_reported_and_retried(
    fake_windows, monkeypatch, tmp_path
):
    startup, registry = fake_windows
    settings = appmod.SettingsManager(tmp_path / "settings.json")
    mgr = settings.get_autostart_manager()
    startup.mkdir(parents=True)
    link = startup / "Fakturabunten.lnk"
    link.write_bytes(b"old shortcut")
    mgr._remember_shortcut()
    assert settings.set("startup", True) is True
    registry[appmod.APP_NAME] = "old Run entry"
    original_unlink = Path.unlink

    def deny_link(path, *args, **kwargs):
        if path == link:
            raise PermissionError("shortcut locked in test")
        return original_unlink(path, *args, **kwargs)

    with monkeypatch.context() as denied:
        denied.setattr(Path, "unlink", deny_link)
        assert settings.set("startup", False) is False
        assert link.read_bytes() == b"old shortcut"
        assert appmod.APP_NAME not in registry  # independent cleanup was attempted
        assert mgr.is_enabled() is True

    assert settings.set("startup", False) is True  # same desired value retries
    assert not link.exists()
    assert mgr.is_enabled() is False


def test_cache_removal_failure_does_not_claim_shortcut_is_still_enabled(
    fake_windows, monkeypatch, tmp_path
):
    startup, _ = fake_windows
    settings = appmod.SettingsManager(tmp_path / "settings.json")
    mgr = settings.get_autostart_manager()
    startup.mkdir(parents=True)
    link = startup / "Fakturabunten.lnk"
    link.write_bytes(b"old shortcut")
    mgr._remember_shortcut()
    cache = mgr._shortcut_fingerprint_path()
    assert settings.set("startup", True) is True
    original_unlink = Path.unlink

    def deny_cache(path, *args, **kwargs):
        if path == cache:
            raise PermissionError("cache locked in test")
        return original_unlink(path, *args, **kwargs)

    with monkeypatch.context() as denied:
        denied.setattr(Path, "unlink", deny_cache)
        assert settings.set("startup", False) is True
    assert not link.exists()
    assert cache.exists()
    assert mgr._shortcut_is_current() is False
