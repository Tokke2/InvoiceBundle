# -*- coding: utf-8 -*-
"""
Tester: ny app-ikon överallt + autostart utan pythonw/Python-ikon.

Användarens krav (2026-10-30): en ny passande ikon ska användas
överallt i stället för Python-ikonen, och vid autostart ska
pythonw inte användas om den drar med sig Python-ikonen.

Lösning som prövas här:
* app_icon.png (1024²) + app_icon.ico (16–256 px) är de nya filerna;
  fönster/tray/dialoger hämtar dem via _load_app_icon.
* Windows-autostarten registreras som en genväg (Fakturabunten.lnk)
  i Autostart-mappen med app_icon.ico som IconLocation — Start-listan
  visar då "Fakturabunten" med appens ikon, inte "Python". Gamla
  Run-registerposter migreras till genvägen. Om en ikonbärande genväg
  inte kan skapas skrivs ingen Python-post som reserv.
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "ui"),
           str(PROJECT_DIR / "plugins")):
    if _d not in sys.path:
        sys.path.insert(0, _d)


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ── Ikonerna ────────────────────────────────────────────────────────


def test_icon_files_exist_and_have_all_sizes():
    from PIL import Image

    png = PROJECT_DIR / "app_icon.png"
    ico = PROJECT_DIR / "app_icon.ico"
    assert png.is_file() and ico.is_file()
    master = Image.open(png)
    assert master.size == (1024, 1024)
    sizes = Image.open(ico).info.get("sizes", set())
    for need in (16, 32, 48, 256):
        assert any(w == need for w, _h in sizes), f"saknar {need}px i .ico"


def test_load_app_icon_uses_new_icon():
    _qapp()
    from ui.main_window import _load_app_icon

    icon = _load_app_icon()
    assert icon is not None
    assert not icon.isNull()
    # Minsta tray-storleken och en stor skrivbordsstorlek ska finnas.
    widths = {s.width() for s in icon.availableSizes()}
    assert 16 in widths or any(w <= 24 for w in widths)
    assert max(widths) >= 128


def test_svg_fallback_matches_new_design():
    svg = (PROJECT_DIR / "app_icon.svg").read_text(encoding="utf-8")
    assert "#16305a" in svg           # marinblå bakgrund
    # Guldbandet: samma färg som i varumärkesfilen (brand/).
    assert "#e0a526" in svg
    assert "circle" in svg            # bock-badgen


def test_bootstrap_progress_uses_app_icon():
    source = (PROJECT_DIR / "ensure_packages.py").read_text(encoding="utf-8")
    assert "self.root.iconbitmap(default=str(ico))" in source
    assert "self.root.iconphoto(True, self._icon_photo)" in source


def test_python_updater_migrates_legacy_run_entry_to_icon_shortcut():
    script = (
        PROJECT_DIR / "autostart" / "install_python.ps1"
    ).read_text(encoding="utf-8")
    assert "Set-ItemProperty -LiteralPath $runKey" not in script
    assert "Remove-ItemProperty -LiteralPath $runKey" in script
    assert "app_icon.ico" in script
    assert "CreateShortcut($linkPath)" in script


# ── Autostart-genvägen ──────────────────────────────────────────────


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


def _win_mgr(monkeypatch, tmp_path, method="auto"):
    import app as appmod
    import windows_shortcut

    monkeypatch.setattr(appmod, "CURRENT_PLATFORM", "windows")
    monkeypatch.setattr(appmod, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(
        appmod.AutostartManager, "_native_startup_folder", staticmethod(lambda: None)
    )
    # Dessa tester simulerar PowerShell/WSH även när de körs på Windows;
    # den verkliga COM-vägen testas separat på en Windows-runner.
    def disabled_native(*_args, **_kwargs):
        raise OSError("native API disabled in this test")

    monkeypatch.setattr(windows_shortcut, "create_shortcut", disabled_native)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    return appmod, appmod.AutostartManager(method=method)


def _stub_shortcut_ok(monkeypatch, mgr):
    """Simulerar en lyckad PowerShell-skapelse av genvägen."""

    def fake_write(self):
        lnk = self._startup_shortcut_path()
        lnk.parent.mkdir(parents=True, exist_ok=True)
        lnk.write_bytes(b"LNK")
        return True

    monkeypatch.setattr(
        type(mgr), "_write_startup_shortcut", fake_write
    )


def test_powershell_script_carries_app_icon_not_python(monkeypatch, tmp_path):
    _appmod, mgr = _win_mgr(monkeypatch, tmp_path)
    ps = mgr._shortcut_powershell()
    assert "app_icon.ico" in ps            # egen ikon
    assert "IconLocation" in ps
    assert "--minimized" in ps             # startar gömd
    assert "CreateShortcut" in ps
    assert mgr._startup_shortcut_path().name == "Fakturabunten.lnk"
    assert "Startup" in str(mgr._startup_shortcut_path())


def test_wscript_fallback_keeps_the_app_icon(monkeypatch, tmp_path):
    appmod, mgr = _win_mgr(monkeypatch, tmp_path)
    commands = []
    staged_links = []
    real_vbscript = mgr._shortcut_vbscript

    def capture_script(destination):
        staged_links.append(destination)
        return real_vbscript(destination)

    def fake_run(command, **_kwargs):
        commands.append(command)
        if command[0] == "powershell":
            raise FileNotFoundError("PowerShell disabled")
        if command[0] == "wscript.exe":
            vbs = Path(command[-1])
            content = vbs.read_text(encoding="utf-16")
            assert "app_icon.ico,0" in content
            staged_links[-1].write_bytes(b"LNK")
            return types.SimpleNamespace(returncode=0)
        raise AssertionError(command)

    monkeypatch.setattr(mgr, "_shortcut_vbscript", capture_script)
    monkeypatch.setattr(appmod.subprocess, "run", fake_run)
    monkeypatch.setattr(appmod.shutil, "which", lambda _name: "wscript.exe")
    assert mgr._write_startup_shortcut() is True
    assert mgr._startup_shortcut_path().read_bytes() == b"LNK"
    assert [command[0] for command in commands] == [
        "powershell", "wscript.exe",
    ]
    assert not list(mgr._startup_folder().glob("*.vbs"))
    assert not staged_links[-1].parent.exists()


def test_enable_prefers_shortcut_and_clears_registry(
    monkeypatch, tmp_path
):
    store = _fake_winreg(monkeypatch)
    _appmod, mgr = _win_mgr(monkeypatch, tmp_path)
    _stub_shortcut_ok(monkeypatch, mgr)
    store["Fakturabunten"] = '"gammal" pythonw-post --minimized'
    assert mgr.set_enabled(True) is True
    # Genvägen är posten nu — registerposten (pythonw) är rensad.
    assert mgr._startup_shortcut_path().exists()
    assert "Fakturabunten" not in store
    assert mgr.is_enabled() is True
    assert mgr.set_enabled(False) is True
    assert not mgr._startup_shortcut_path().exists()
    assert mgr.is_enabled() is False


def test_enable_refuses_python_registry_fallback_without_shortcut(
    monkeypatch, tmp_path
):
    store = _fake_winreg(monkeypatch)
    _appmod, mgr = _win_mgr(monkeypatch, tmp_path)
    monkeypatch.setattr(
        type(mgr), "_write_startup_shortcut", lambda self: False
    )
    store["Fakturabunten"] = '"pythonw.exe" "main.pyw" --minimized'
    assert mgr.set_enabled(True) is False
    # Ingen Run-post får lämnas kvar med Python-ikonen.
    assert "Fakturabunten" not in store
    assert not mgr._startup_shortcut_path().exists()
    assert mgr.is_enabled() is False


def test_verify_migrates_registry_entry_to_shortcut(
    monkeypatch, tmp_path
):
    store = _fake_winreg(monkeypatch)
    _appmod, mgr = _win_mgr(monkeypatch, tmp_path)
    _stub_shortcut_ok(monkeypatch, mgr)
    # Gammalt läge: korrekt registerkommando men ingen genväg.
    store["Fakturabunten"] = mgr.build_command()
    assert mgr.verify_and_update() is True
    assert mgr._startup_shortcut_path().exists()
    assert "Fakturabunten" not in store


def test_launcher_method_shortcut_targets_wscript(monkeypatch, tmp_path):
    _appmod, mgr = _win_mgr(monkeypatch, tmp_path, method="launcher")
    target, args = mgr._shortcut_target()
    assert "wscript" in target.lower()
    assert "start_hidden.vbs" in args.replace("\\", "/")


def test_shortcut_update_preserves_old_link_until_new_link_is_ready(
    monkeypatch, tmp_path
):
    appmod, mgr = _win_mgr(monkeypatch, tmp_path)
    final_link = mgr._startup_shortcut_path()
    final_link.parent.mkdir(parents=True)
    final_link.write_bytes(b"OLD")
    staged_links = []
    real_powershell = mgr._shortcut_powershell

    def capture_script(destination):
        staged_links.append(destination)
        return real_powershell(destination)

    def fake_run(command, **_kwargs):
        assert command[0] == "powershell"
        assert final_link.read_bytes() == b"OLD"
        assert staged_links[-1] != final_link
        staged_links[-1].write_bytes(b"NEW")
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(mgr, "_shortcut_powershell", capture_script)
    monkeypatch.setattr(appmod.subprocess, "run", fake_run)
    assert mgr._write_startup_shortcut() is True
    assert final_link.read_bytes() == b"NEW"
    assert not staged_links[-1].parent.exists()


def test_failed_shortcut_update_keeps_existing_link_and_rejects_partial_file(
    monkeypatch, tmp_path
):
    appmod, mgr = _win_mgr(monkeypatch, tmp_path)
    final_link = mgr._startup_shortcut_path()
    final_link.parent.mkdir(parents=True)
    final_link.write_bytes(b"OLD")
    staged_links = []
    real_powershell = mgr._shortcut_powershell

    def capture_script(destination):
        staged_links.append(destination)
        return real_powershell(destination)

    def fake_run(command, **_kwargs):
        if command[0] == "powershell":
            staged_links[-1].write_bytes(b"PARTIAL")
        else:
            # PowerShell failed, so its partial output must not be accepted
            # when the fallback fails to create a link.
            assert not staged_links[-1].exists()
        return types.SimpleNamespace(returncode=1)

    monkeypatch.setattr(mgr, "_shortcut_powershell", capture_script)
    monkeypatch.setattr(appmod.subprocess, "run", fake_run)
    monkeypatch.setattr(appmod.shutil, "which", lambda _name: "wscript.exe")
    assert mgr._write_startup_shortcut() is False
    assert final_link.read_bytes() == b"OLD"
    assert not staged_links[-1].parent.exists()


def test_powershell_shortcut_quotes_apostrophes(monkeypatch, tmp_path):
    appmod, mgr = _win_mgr(monkeypatch, tmp_path)
    monkeypatch.setattr(appmod, "BASE_DIR", tmp_path / "Rickard's program")
    monkeypatch.setattr(mgr, "_python_exe", r"C:\Users\Rickard's\pythonw.exe")
    script = mgr._shortcut_powershell(tmp_path / "Rickard's link.lnk")
    assert "Rickard''s program" in script
    assert "Rickard''s link.lnk" in script
    assert "Rickard''s\\pythonw.exe" in script
    assert "$ErrorActionPreference = 'Stop'" in script


def test_native_shell_creates_shortcut_without_powershell_or_wscript(
    monkeypatch, tmp_path
):
    import windows_shortcut

    appmod, mgr = _win_mgr(monkeypatch, tmp_path)
    old_link = mgr._startup_shortcut_path()
    old_link.parent.mkdir(parents=True)
    old_link.write_bytes(b"old")
    calls = []

    def create(staged, **kwargs):
        calls.append((staged, kwargs))
        assert old_link.read_bytes() == b"old"
        staged.write_bytes(b"new native lnk")

    def no_shell(*_args, **_kwargs):
        raise AssertionError("PowerShell/WSH must not run on native success")

    monkeypatch.setattr(windows_shortcut, "create_shortcut", create)
    monkeypatch.setattr(appmod.subprocess, "run", no_shell)
    assert mgr._write_startup_shortcut() is True
    assert old_link.read_bytes() == b"new native lnk"
    assert calls[0][1] == {
        "target": mgr._shortcut_target()[0],
        "arguments": mgr._shortcut_target()[1],
        "workdir": str(appmod.BASE_DIR),
        "icon": str(appmod.BASE_DIR / "app_icon.ico"),
        "description": "Fakturabunten",
    }
    assert mgr._shortcut_last_failure == ""
    assert not calls[0][0].parent.exists()


def test_all_shortcut_failures_report_real_causes_and_keep_existing_link(
    monkeypatch, tmp_path, caplog
):
    import logging
    import windows_shortcut

    store = _fake_winreg(monkeypatch)
    appmod, mgr = _win_mgr(monkeypatch, tmp_path)
    final_link = mgr._startup_shortcut_path()
    final_link.parent.mkdir(parents=True)
    final_link.write_bytes(b"previous working link")
    staged = []

    def failed_native(path, **_kwargs):
        staged.append(path)
        path.write_bytes(b"partial native")
        raise OSError("COM 0x80070005 access denied")

    def failed_run(command, **_kwargs):
        assert not staged[0].exists(), "failed method left a partial link"
        if command[0] == "powershell":
            staged[0].write_bytes(b"partial powershell")
            return types.SimpleNamespace(
                returncode=1, stderr=b"PowerShell blocked by policy"
            )
        assert command[0] == "cscript.exe"
        return types.SimpleNamespace(returncode=5, stderr=b"WSH disabled")

    monkeypatch.setattr(windows_shortcut, "create_shortcut", failed_native)
    monkeypatch.setattr(appmod.subprocess, "run", failed_run)
    monkeypatch.setattr(
        appmod.shutil, "which",
        lambda name: "cscript.exe" if name == "cscript.exe" else None,
    )
    store["Fakturabunten"] = "legacy Python entry"
    appmod.log.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.ERROR, logger="FakturaApp"):
            assert mgr.set_enabled(True) is False
    finally:
        appmod.log.removeHandler(caplog.handler)

    assert final_link.read_bytes() == b"previous working link"
    assert "Fakturabunten" not in store  # no Python/Run fallback
    assert "Befintlig genväg är kvar" in caplog.text
    assert "0x80070005" in caplog.text
    assert "PowerShell blocked by policy" in caplog.text
    assert "WSH disabled" in caplog.text
    assert "exitkod 5" in caplog.text
    assert not staged[0].parent.exists()


def test_missing_app_icon_is_reported_without_creating_a_shortcut(
    monkeypatch, tmp_path
):
    appmod, mgr = _win_mgr(monkeypatch, tmp_path)
    missing_dir = tmp_path / "app utan ikon"
    missing_dir.mkdir()
    monkeypatch.setattr(appmod, "BASE_DIR", missing_dir)
    assert mgr._write_startup_shortcut() is False
    assert "appikonen saknas" in mgr._shortcut_last_failure
    assert not mgr._startup_shortcut_path().exists()


def test_redirected_windows_startup_folder_takes_precedence_over_appdata(
    monkeypatch, tmp_path
):
    _appmod, mgr = _win_mgr(monkeypatch, tmp_path)
    redirected = tmp_path / "Anpassad Autostart" / "åäö"
    monkeypatch.setattr(mgr, "_native_startup_folder", lambda: redirected)
    assert mgr._startup_shortcut_path() == redirected / "Fakturabunten.lnk"
    monkeypatch.setattr(mgr, "_native_startup_folder", lambda: None)
    assert mgr._startup_shortcut_path().is_relative_to(tmp_path / "appdata")
