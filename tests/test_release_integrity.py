# -*- coding: utf-8 -*-
"""
Regressionstester: autouppdateringen får aldrig försvinna igen.

Bakgrund: en publicerad kopia saknade "Sök ny version" i Hjälp-menyn
(menyn hade bara Om programmet/Kopiera diagnostik) eftersom
uppdaterarfilerna bara fanns i en lokalt byggd zip, inte i den
publicerade källkoden. De här testerna är Qt-fria och vaktar:

  • release-manifestet (build_release.RELEASE_FILES) innehåller
    uppdateraren och alla kritiska filer,
  • filerna faktiskt finns i repot,
  • Hjälp-menyn, tray-menyn, auto-kollen vid start och
    inställningskrysset för auto-koll är inkopplade i main_window,
  • byggaren vägrar bygga ett paket som saknar release-filer.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import build_release as br


def test_release_manifest_contains_autoupdater():
    for rel in br.CRITICAL_FILES:
        assert rel in br.RELEASE_FILES, rel
    assert "plugins/updater.py" in br.RELEASE_FILES
    assert "ui/update_dialog.py" in br.RELEASE_FILES
    assert "plugins/python_update_scheduler.py" in br.RELEASE_FILES
    assert br.missing_critical_files(PROJECT_DIR) == []


def test_all_release_files_exist_in_repo():
    assert br.validate_release_files(PROJECT_DIR) == []


def test_tag_workflow_builds_and_attaches_the_release_package():
    workflow = (
        PROJECT_DIR / ".github" / "workflows" / "release-integrity.yml"
    ).read_text(encoding="utf-8")
    assert "build-release-package:" in workflow
    assert "startsWith(github.ref, 'refs/tags/v')" in workflow
    assert "contents: write" in workflow
    assert "python build_release.py" in workflow
    assert "gh release upload" in workflow
    assert "--clobber" in workflow
    assert 'VERSION="${GITHUB_REF_NAME#v}"' in workflow


def test_python_runtime_and_autostart_use_system_interpreters_only():
    app = (PROJECT_DIR / "app.py").read_text(encoding="utf-8")
    main = (PROJECT_DIR / "main.py").read_text(encoding="utf-8")
    starter = (
        PROJECT_DIR / "autostart" / "start_fakturabunten.ps1"
    ).read_text(encoding="utf-8")
    shell = (
        PROJECT_DIR / "autostart" / "start_hidden.sh"
    ).read_text(encoding="utf-8")
    vbs = (
        PROJECT_DIR / "autostart" / "start_hidden.vbs"
    ).read_text(encoding="utf-16")
    assert 'local = BASE_DIR / "python"' not in app
    assert 'parent / "python" / "bin"' not in main
    assert "APP_LOCAL_PYTHON_REJECTED" in main
    assert "python_runtime_selection.json" in main
    assert "_choose_working_system_python" in main
    assert "_remember_selected_python" in main
    assert "Test-AppLocalPython" in starter
    assert "PYTHON_MANAGER_AUTOMATIC_INSTALL = '0'" in starter
    assert "APP_DIR/python/bin/" not in shell
    assert 'appDir & "\\python\\pythonw.exe"' not in vbs
    assert 'appDir & "\\python\\pythonw.exe"' not in app
    assert "system-Python" in app or "systemtolk" in app


def test_system_tray_registration_retries_when_desktop_is_not_ready():
    main_window = (
        PROJECT_DIR / "ui" / "main_window.py"
    ).read_text(encoding="utf-8")
    main = (PROJECT_DIR / "main.py").read_text(encoding="utf-8")
    assert "def _schedule_tray_setup_retry" in main_window
    assert "timer.start(1000)" in main_window
    assert "SYSTEM_TRAY_SETUP_GAVE_UP" in main_window
    assert "if tray_ready:" in main
    assert "Utan tray får appen inte försvinna från användaren" in main


def test_runtime_helper_modules_are_in_the_release_manifest():
    for rel in (
        "plugins/error_collect.py",
        "plugins/log_archive.py",
        "ui/invoice_table_model.py",
        "ui/typography.py",
    ):
        assert rel in br.RELEASE_FILES, rel
        assert (PROJECT_DIR / rel).is_file(), rel


def test_every_ui_and_plugin_python_module_is_shipped():
    runtime_modules = {
        path.relative_to(PROJECT_DIR).as_posix()
        for package in (PROJECT_DIR / "ui", PROJECT_DIR / "plugins")
        for path in package.rglob("*.py")
    }
    assert runtime_modules - set(br.RELEASE_FILES) == set()


def test_release_ships_start_files_but_not_the_old_python_installer(tmp_path):
    names = {
        "Starta Fakturabunten.bat",
        "Starta Fakturabunten.command",
        "Starta Fakturabunten.sh",
        "autostart/start_fakturabunten.ps1",
    }
    forbidden = {"Installera senaste Python.bat", "autostart/install_python.ps1"}
    assert names <= set(br.RELEASE_FILES)
    assert not (forbidden & set(br.RELEASE_FILES))
    assert all(not (PROJECT_DIR / name).exists() for name in forbidden)
    package = br.build_release_zip(PROJECT_DIR, tmp_path / "package.zip", sha="start-files")
    with zipfile.ZipFile(package) as zf:
        members = set(zf.namelist())
        manifest = json.loads(zf.read("build_info.json"))["files"]
        assert names <= members and names <= set(manifest)
        assert not (forbidden & members) and not (forbidden & set(manifest))
        for name in ("Starta Fakturabunten.command", "Starta Fakturabunten.sh"):
            assert (zf.getinfo(name).external_attr >> 16) & 0o100


def test_weekly_python_update_is_wired_and_shipped():
    scheduler = PROJECT_DIR / "plugins" / "python_update_scheduler.py"
    main = (PROJECT_DIR / "main.py").read_text(encoding="utf-8")
    assert scheduler.is_file()
    assert "plugins/python_update_scheduler.py" in br.RELEASE_FILES
    assert '"plugins/python_update_scheduler.py"' in main
    assert "schedule_weekly_python_updates" in main
    assert "wait_for_active_update" in main


def test_main_window_wires_update_everywhere():
    s = (PROJECT_DIR / "ui" / "main_window.py").read_text(
        encoding="utf-8"
    )
    # Hjälp-menyn: Sök ny version ska alltid finnas där.
    assert 'a_update = QAction(tr("menu.update"), self)' in s
    assert "m_help.addAction(a_update)" in s
    assert "a_update.triggered.connect(self._check_updates)" in s
    # Tyst auto-koll högst två gånger per dygn: vid start (om mogen)
    # + timtick medan appen körs; spärren (minst 12 h mellan
    # GENOMFÖRDA kollar) bor i updater.auto_check_due och stämpeln
    # sätts först när nätet svarat — offline förbrukar ingen gång.
    assert "QTimer.singleShot(5_000, self._maybe_auto_update_check)" in s
    assert "_update_poll_timer" in s
    assert "setInterval(3600 * 1000)" in s
    assert "auto_check_due" in s
    # Efter lyckad installation: tyst omstart — ingen knapp att klicka.
    d = (PROJECT_DIR / "ui" / "update_dialog.py").read_text(
        encoding="utf-8"
    )
    assert "QTimer.singleShot(1500, self._restart)" in d
    assert "_btn_restart.show()" not in d
    assert 'self._settings.get("update_auto_check", True)' in s
    assert "_act_update_auto" in s
    # Även systembrickan har samma val.
    assert 'a_update_tray = QAction(tr("menu.update"), self)' in s
    assert "a_update_tray.triggered.connect(self._tray_check_updates)" in s
    # Trasig/saknad uppdaterare ska ge ett synligt fel, inte tystnad.
    assert "QMessageBox.warning" in s
    assert 'tr("update.failed"' in s


def test_invoices_context_menu_is_translated():
    s = (PROJECT_DIR / "ui" / "invoices_view.py").read_text(
        encoding="utf-8"
    )
    start = s.index("def _context_menu")
    end = s.index("def apply_theme", start)
    body = s[start:end]
    # Hela högerklicksmenyn går via i18n — inklusive Skriv ut.
    assert 'tr("invoices.ctx_print")' in body
    assert 'tr("invoices.ctx_status")' in body
    assert 'tr("invoices.ctx_undo_status")' in body
    assert "tr_status(s)" in body
    # Inga hårdkodade svenska menytexter kvar i menyn.
    for hard in (
        '"✏️  Redigera"',
        '"📋  Duplicera"',
        '"✅  Markera betald"',
        '"🗑  Ta bort"',
        '"📊  Ändra status"',
        '"↩  Ångra statusändring"',
    ):
        assert hard not in body


def test_i18n_update_keys_exist():
    s = (PROJECT_DIR / "ui" / "i18n.py").read_text(encoding="utf-8")
    for key in ("menu.update", "update.title", "update.auto_menu",
                "update.found_title", "update.failed"):
        assert f'"{key}"' in s, key


def test_tray_menu_can_open_the_app_folder():
    main_window = (PROJECT_DIR / "ui" / "main_window.py").read_text(
        encoding="utf-8"
    )
    i18n = (PROJECT_DIR / "ui" / "i18n.py").read_text(encoding="utf-8")
    assert 'QAction(tr("tray.app_folder"), self)' in main_window
    assert "a_app_folder.triggered.connect(self._open_app_folder)" in main_window
    assert "def _open_app_folder(self)" in main_window
    assert "_open_path(PROJECT_DIR)" in main_window
    assert '"tray.app_folder"' in i18n
    assert "Öppna appmappen" in i18n
    assert "Open app folder" in i18n


def test_builder_refuses_incomplete_package(tmp_path):
    # Tom rot: byggaren ska vägra, aldrig producera en trasig zip.
    with pytest.raises(FileNotFoundError):
        br.build_release_zip(tmp_path, tmp_path / "x.zip", sha="abc")


def test_built_zip_contains_updater_and_build_info(tmp_path):
    out = br.build_release_zip(
        PROJECT_DIR, tmp_path / "InvoiceBundle-v1.0.0.zip",
        version="1.0.0", sha="deadbeef",
    )
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        for rel in br.CRITICAL_FILES:
            assert rel in names, rel
        for rel in (
            "plugins/error_collect.py",
            "plugins/log_archive.py",
            "ui/typography.py",
        ):
            assert rel in names, rel
        assert "plugins/python_update_scheduler.py" in names
        info = json.loads(zf.read("build_info.json").decode("utf-8"))
    assert info["sha"] == "deadbeef"
    assert info["version"] == "1.0.0"
    assert "plugins/updater.py" in info["files"]
    assert "plugins/python_update_scheduler.py" in info["files"]
    # Inga användardata i programpaketet — någonsin.
    assert not any(
        n.startswith(("data/", "ui/data/", "logs/", "exports/", "bak/"))
        or n in ("settings.json", "shortcuts.json")
        for n in names
    )


def test_updater_downloads_from_release_never_main():
    up_src = (PROJECT_DIR / "plugins" / "updater.py").read_text(
        encoding="utf-8"
    )
    dlg_src = (PROJECT_DIR / "ui" / "update_dialog.py").read_text(
        encoding="utf-8"
    )
    # Arkiv-URL:en byggs ur releasens tagg (refs/tags/), och nedladd-
    # ningen går alltid via den verifierade release-vägen.
    assert "zipball/refs/tags/" in up_src
    assert "def download_release_zip" in up_src
    assert "def is_release_bound_url" in up_src
    assert "download_release_zip" in dlg_src
    # Ingen kodväg får peka på main/default-branchen för nedladdning.
    for src in (up_src, dlg_src):
        assert "heads/main" not in src
        assert "zipball/main" not in src
        assert "archive/main" not in src


#: Tryckfilerna ska ligga INUTI programpaketet — inte som en separat
#: nedladdning. Alla sex SVG:er + README följer med varje release.
PRINT_FILES = (
    "brand/README.md",
    "brand/fakturabunten-ikon.svg",
    "brand/fakturabunten-ikon-monokrom.svg",
    "brand/fakturabunten-ikon-tryck-bleed.svg",
    "brand/fakturabunten-logotyp.svg",
    "brand/fakturabunten-logotyp-mork-bakgrund.svg",
    "brand/fakturabunten-logotyp-svartvit.svg",
)


def test_print_ready_brand_files_are_in_the_release_manifest():
    for rel in PRINT_FILES:
        assert rel in br.RELEASE_FILES, rel
    assert br.validate_release_files(PROJECT_DIR) == []
    # Inga tryckfiler får ligga utanför manifestet — då skulle de
    # saknas i release-zipen och kräva en egen nedladdning.
    for path in sorted((PROJECT_DIR / "brand").rglob("*")):
        if path.is_file() and path.suffix.lower() in (".svg", ".md"):
            rel = path.relative_to(PROJECT_DIR).as_posix()
            assert rel in br.RELEASE_FILES, rel


def test_built_package_ships_the_print_files_inside_the_zip(tmp_path):
    out = br.build_release_zip(
        PROJECT_DIR, tmp_path / "InvoiceBundle-v1.0.0.zip",
        version="1.0.0", sha="deadbeef",
    )
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        info = json.loads(zf.read("build_info.json").decode("utf-8"))
    for rel in PRINT_FILES:
        assert rel in names, rel
        # Uppdateraren installerar det som står i build_info.files —
        # därför måste tryckfilerna listas där också.
        assert rel in info["files"], rel
    # Tryckfilerna ska aldrig ligga som egna toppnivåfiler i paketet.
    svg_top = [n for n in names if n.lower().endswith(".svg") and "/" not in n]
    assert svg_top == ["app_icon.svg"], svg_top


def test_release_workflow_verifies_the_package_contains_print_files():
    workflow = (
        PROJECT_DIR / ".github" / "workflows" / "release-integrity.yml"
    ).read_text(encoding="utf-8")
    assert "Verifiera tryckfilerna i paketet" in workflow
    for rel in PRINT_FILES:
        assert rel in workflow, rel


def test_native_windows_shortcut_is_bundled_and_installed_on_update(tmp_path):
    from plugins import updater

    assert "windows_shortcut.py" in br.RELEASE_FILES
    package = br.build_release_zip(
        PROJECT_DIR, tmp_path / "package.zip", version="1.0.0", sha="testsha"
    )
    with zipfile.ZipFile(package) as zf:
        names = set(zf.namelist())
        info = json.loads(zf.read("build_info.json").decode("utf-8"))
        assert zf.read("windows_shortcut.py") == (
            PROJECT_DIR / "windows_shortcut.py"
        ).read_bytes()
    assert "windows_shortcut.py" in names
    assert "windows_shortcut.py" in info["files"]

    # A previously installed app has no helper yet. Updating adds it and
    # does not touch existing invoices or other local data.
    old = tmp_path / "old-installation"
    (old / "data").mkdir(parents=True)
    invoices = old / "data" / "invoices.json"
    invoices.write_text('[{"id":"keep-me"}]', encoding="utf-8")
    report = updater.apply_update(package, old, version="1.0.0", sha="testsha")
    assert "windows_shortcut.py" in report["files"]
    assert (old / "windows_shortcut.py").read_bytes() == (
        PROJECT_DIR / "windows_shortcut.py"
    ).read_bytes()
    assert json.loads(invoices.read_text(encoding="utf-8")) == [{"id": "keep-me"}]
    assert all((old / path).is_file() for path in PRINT_FILES)


def test_release_workflow_tests_actual_windows_shortcuts_before_upload():
    workflow = (
        PROJECT_DIR / ".github" / "workflows" / "release-integrity.yml"
    ).read_text(encoding="utf-8")
    assert "windows-autostart:" in workflow
    assert "runs-on: windows-latest" in workflow
    assert 'python: ["3.11", "3.15"]' in workflow
    assert "tests/test_windows_shortcut_native.py" in workflow
    assert "tests/test_autostart_settings.py" in workflow
    assert "tests/test_start_launcher_windows.py" in workflow
    assert "tests/test_start_launcher_unix.py" in workflow
    assert "macos-latest" in workflow
    assert "autostart-ui:" in workflow
    assert "tests/test_autostart_ui_status.py" in workflow
    assert "QT_QPA_PLATFORM: offscreen" in workflow
    assert "needs: [updater-guard, windows-autostart, autostart-ui, unix-startup]" in workflow


def test_update_removes_obsolete_tracked_installers_and_preserves_data(tmp_path):
    from plugins import updater

    obsolete = ("Installera senaste Python.bat", "autostart/install_python.ps1")
    package = br.build_release_zip(
        PROJECT_DIR, tmp_path / "package.zip", version="1.0.0", sha="start-files"
    )
    old = tmp_path / "old-installation"
    old.mkdir()
    for rel in obsolete:
        path = old / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("old program file", encoding="utf-8")
    (old / "build_info.json").write_text(
        json.dumps({"sha": "old", "files": list(obsolete)}), encoding="utf-8"
    )
    (old / "data").mkdir()
    invoice = old / "data" / "invoices.json"
    invoice.write_text('[{"id":"keep-me"}]', encoding="utf-8")
    report = updater.apply_update(package, old, version="1.0.0", sha="start-files")

    assert all(not (old / rel).exists() for rel in obsolete)
    assert report["removed"] == 2
    assert all((old / name).is_file() for name in (
        "Starta Fakturabunten.bat", "Starta Fakturabunten.command",
        "Starta Fakturabunten.sh", "autostart/start_fakturabunten.ps1",
    ))
    if os.name != "nt":
        assert (old / "Starta Fakturabunten.command").stat().st_mode & 0o100
        assert (old / "Starta Fakturabunten.sh").stat().st_mode & 0o100
    assert json.loads(invoice.read_text(encoding="utf-8")) == [{"id": "keep-me"}]
    assert all((old / path).is_file() for path in PRINT_FILES)


def test_legacy_no_manifest_cleanup_removes_only_known_shipped_batch(monkeypatch, tmp_path):
    import main

    # Exact historical launcher, with Windows CRLF as it may exist on disk.
    batch = (
        '@echo off\nsetlocal\nset "SCRIPT=%~dp0autostart\\install_python.ps1"\n'
        'if not exist "%SCRIPT%" (\n'
        '    echo Python-skriptet saknas: "%SCRIPT%"\n'
        '    pause\n    exit /b 2\n)\n\n'
        'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"\n'
        'set "RC=%ERRORLEVEL%"\nif not "%RC%"=="0" (\n    echo.\n'
        '    echo Python kunde inte uppdateras eller installeras. Se logs\\starta.log.\n'
        '    pause\n)\nexit /b %RC%\n'
    ).encode('utf-8')
    assert hashlib.sha256(batch).hexdigest() in main._LEGACY_PYTHON_FILES['Installera senaste Python.bat']
    old = tmp_path / "old-no-manifest"
    old.mkdir()
    path = old / "Installera senaste Python.bat"
    path.write_bytes(batch.replace(b"\n", b"\r\n"))
    (old / "data").mkdir()
    (old / "data" / "invoice.json").write_text('safe', encoding='utf-8')
    from plugins import updater
    package = br.build_release_zip(PROJECT_DIR, tmp_path / 'new.zip', sha='new')
    updater.apply_update(package, old, sha='new')
    assert path.exists()  # the legacy updater cannot infer untracked old files
    starters = [old / 'Starta Fakturabunten.sh', old / 'Starta Fakturabunten.command']
    if os.name != 'nt':
        for starter in starters:  # simulate an older updater that lost execute bits
            starter.chmod(0o644)
    monkeypatch.setattr(main, 'BASE_DIR', old)
    main._repair_startup_files()
    assert not path.exists()
    if os.name != 'nt':
        assert all(starter.stat().st_mode & 0o100 for starter in starters)
    assert (old / "data" / "invoice.json").read_text(encoding='utf-8') == 'safe'

    path.write_text('my customized file', encoding='utf-8')
    main._repair_startup_files()
    assert path.read_text(encoding='utf-8') == 'my customized file'


def test_startup_help_does_not_recommend_the_disabled_batch(monkeypatch, tmp_path):
    import app as appmod

    for path, encoding in (
        (PROJECT_DIR / "autostart" / "LAS_MIG.txt", "utf-8"),
        (PROJECT_DIR / "autostart" / "start_hidden.vbs", "utf-16"),
        (PROJECT_DIR / "app.py", "utf-8"),
    ):
        text = path.read_text(encoding=encoding)
        assert "Kör Installera senaste Python.bat" not in text
        assert "kör Installera senaste Python.bat" not in text

    # Regenerating the portable launcher must not reintroduce stale help.
    monkeypatch.setattr(appmod, "BASE_DIR", tmp_path)
    monkeypatch.setattr(appmod, "CURRENT_PLATFORM", "windows")
    launcher = appmod.AutostartManager(method="launcher")._write_launcher()
    assert launcher.read_text(encoding="utf-16") == (
        PROJECT_DIR / "autostart" / "start_hidden.vbs"
    ).read_text(encoding="utf-16")
    assert (launcher.parent / "LAS_MIG.txt").read_text(encoding="utf-8") == (
        PROJECT_DIR / "autostart" / "LAS_MIG.txt"
    ).read_text(encoding="utf-8")
    monkeypatch.setattr(appmod, "CURRENT_PLATFORM", "linux")
    shell = appmod.AutostartManager(method="launcher")._write_launcher()
    assert shell.read_text(encoding="utf-8") == (
        PROJECT_DIR / "autostart" / "start_hidden.sh"
    ).read_text(encoding="utf-8")
    assert "--no-prompt" in shell.read_text(encoding="utf-8")


def test_legacy_cleanup_does_not_follow_symlinks_outside_app(monkeypatch, tmp_path):
    import main

    app = tmp_path / 'app'
    app.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    payload = b'legacy program file'
    target = outside / 'install_python.ps1'
    target.write_bytes(payload)
    try:
        (app / 'autostart').symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('symlink creation unavailable')
    monkeypatch.setattr(main, 'BASE_DIR', app)
    monkeypatch.setattr(main, '_LEGACY_PYTHON_FILES', {
        'autostart/install_python.ps1': frozenset({hashlib.sha256(payload).hexdigest()}),
    })
    main._repair_startup_files()
    assert target.read_bytes() == payload
