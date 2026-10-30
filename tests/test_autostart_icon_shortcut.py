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
  visar då "Fakturabunten" med appens ikon, inte "Python". Run-
  registerposten används bara som reserv och rensas när genvägen
  finns, så appen aldrig startar dubbelt. Gamla registerposter
  migreras av verify_and_update.
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
    assert "#e8a91c" in svg           # guldbandet
    assert "circle" in svg            # bock-badgen


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

    monkeypatch.setattr(appmod, "CURRENT_PLATFORM", "windows")
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


def test_enable_falls_back_to_registry_without_powershell(
    monkeypatch, tmp_path
):
    store = _fake_winreg(monkeypatch)
    _appmod, mgr = _win_mgr(monkeypatch, tmp_path)
    monkeypatch.setattr(
        type(mgr), "_write_startup_shortcut", lambda self: False
    )
    assert mgr.set_enabled(True) is True
    # Reservvägen: Run-posten (funktionen går före ikonrenheten
    # i miljöer där genvägen inte kan skapas).
    assert "--minimized" in store["Fakturabunten"]
    assert mgr.is_enabled() is True
    assert mgr.get_registered_command() == store["Fakturabunten"]


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
