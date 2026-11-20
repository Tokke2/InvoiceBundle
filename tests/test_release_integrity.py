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
    assert "tests/test_startup_errors.py" in workflow
    assert "macos-latest" in workflow
    assert "autostart-ui:" in workflow
    assert "tests/test_autostart_ui_status.py" in workflow
    assert "QT_QPA_PLATFORM: offscreen" in workflow
    assert "needs: [updater-guard, windows-autostart, autostart-ui, unix-startup]" in workflow


def test_deferred_legacy_helpers_match_the_startup_hash_check():
    import main
    from plugins import updater

    assert updater.LEGACY_PYTHON_HELPERS == set(main._LEGACY_PYTHON_FILES)


def test_update_defers_legacy_helpers_to_content_checked_startup(monkeypatch, tmp_path):
    import main
    from plugins import updater

    # The historical, unmodified BAT is removed on the following startup,
    # while a user's modified PowerShell file survives even if old build_info
    # listed it. Neither helper is present in the new release package.
    batch = (
        b'@echo off\nsetlocal\necho.\n'
        b'echo Den manuella Python-uppdateringen ar avaktiverad.\n'
        b'echo Ingen Python-version har installerats eller andrats av denna fil.\n'
        b'echo Den automatiska veckokontrollen kan fortfarande uppdatera Python.\n'
        b'echo.\npause\nexit /b 2\n'
    )
    bat_name = "Installera senaste Python.bat"
    ps_name = "autostart/install_python.ps1"
    assert hashlib.sha256(batch).hexdigest() in main._LEGACY_PYTHON_FILES[bat_name]
    package = br.build_release_zip(
        PROJECT_DIR, tmp_path / "package.zip", version="1.0.0", sha="start-files"
    )
    old = tmp_path / "old-installation"
    (old / "autostart").mkdir(parents=True)
    (old / bat_name).write_bytes(batch.replace(b"\n", b"\r\n"))
    (old / ps_name).write_text("my customized file", encoding="utf-8")
    (old / "build_info.json").write_text(
        json.dumps({"sha": "old", "files": [bat_name, ps_name]}), encoding="utf-8"
    )
    (old / "data").mkdir()
    invoice = old / "data" / "invoices.json"
    invoice.write_text('[{"id":"keep-me"}]', encoding="utf-8")
    report = updater.apply_update(package, old, version="1.0.0", sha="start-files")

    assert report["removed"] == 0
    assert (old / bat_name).is_file()  # cleaned by the new app on restart
    assert (old / ps_name).read_text(encoding="utf-8") == "my customized file"
    assert all((old / name).is_file() for name in (
        "Starta Fakturabunten.bat", "Starta Fakturabunten.command",
        "Starta Fakturabunten.sh", "autostart/start_fakturabunten.ps1",
    ))
    if os.name != "nt":
        assert (old / "Starta Fakturabunten.command").stat().st_mode & 0o100
        assert (old / "Starta Fakturabunten.sh").stat().st_mode & 0o100
    assert json.loads(invoice.read_text(encoding="utf-8")) == [{"id": "keep-me"}]
    assert all((old / path).is_file() for path in PRINT_FILES)
    monkeypatch.setattr(main, "BASE_DIR", old)
    main._repair_startup_files()
    assert not (old / bat_name).exists()
    assert (old / ps_name).read_text(encoding="utf-8") == "my customized file"


def test_update_preserves_custom_tracked_legacy_batch(monkeypatch, tmp_path):
    import main
    from plugins import updater

    name = "Installera senaste Python.bat"
    package = br.build_release_zip(PROJECT_DIR, tmp_path / "package.zip", sha="new")
    old = tmp_path / "old-installation"
    old.mkdir()
    (old / name).write_text("custom batch", encoding="utf-8")
    (old / "build_info.json").write_text(
        json.dumps({"sha": "old", "files": [name]}), encoding="utf-8"
    )
    updater.apply_update(package, old, sha="new")
    monkeypatch.setattr(main, "BASE_DIR", old)
    main._repair_startup_files()
    assert (old / name).read_text(encoding="utf-8") == "custom batch"


@pytest.mark.parametrize("name", ["Installera senaste Python.bat", "autostart/install_python.ps1"])
def test_update_keeps_tracked_legacy_symlinks_and_their_targets(monkeypatch, tmp_path, name):
    import main
    from plugins import updater

    package = br.build_release_zip(PROJECT_DIR, tmp_path / "package.zip", sha="new")
    old = tmp_path / "old-installation"
    old.mkdir()
    target = tmp_path / "user-file"
    target.write_text("keep me", encoding="utf-8")
    link = old / name
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    (old / "build_info.json").write_text(
        json.dumps({"sha": "old", "files": [name]}), encoding="utf-8"
    )
    updater.apply_update(package, old, sha="new")
    monkeypatch.setattr(main, "BASE_DIR", old)
    main._repair_startup_files()
    assert link.is_symlink()
    assert target.read_text(encoding="utf-8") == "keep me"


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


def test_overarching_license_allows_private_and_commercial_use_and_ships(tmp_path):
    license_path = PROJECT_DIR / "LICENSE"
    assert license_path.is_file()
    text = license_path.read_text(encoding="utf-8")
    low = text.lower()
    assert "privat" in low and "kommersiellt" in low
    assert "private" in low and "commercial" in low
    assert "rickard längkvist" in low
    assert "LICENSE" in br.RELEASE_FILES

    package = br.build_release_zip(
        PROJECT_DIR, tmp_path / "package.zip", version="1.0.0", sha="licsha"
    )
    with zipfile.ZipFile(package) as zf:
        assert "LICENSE" in zf.namelist()
        assert zf.read("LICENSE") == license_path.read_bytes()
        manifest = json.loads(zf.read("build_info.json").decode("utf-8"))["files"]
        assert "LICENSE" in manifest


def test_donate_menu_and_locked_values_in_main_window():
    main_window = (PROJECT_DIR / "ui" / "main_window.py").read_text(
        encoding="utf-8"
    )
    donate_src = (PROJECT_DIR / "ui" / "donate.py").read_text(encoding="utf-8")
    assert 'tr("menu.donate")' in main_window
    assert "m_help.addAction(a_donate)" in main_window
    assert "bar.addMenu(self._donate_menu)" not in main_window
    assert "123 456 78 90" not in main_window
    assert "https://www.paypal.com/donate" not in main_window
    assert "LockedDonationConfig" in donate_src
    assert "frozen=True" in donate_src


def test_verify_release_zip_validates_checksum_manifest_and_cli(tmp_path):
    pkg = br.build_release_zip(
        PROJECT_DIR, tmp_path / "InvoiceBundle-v1.0.0.zip",
        version="1.0.0", sha="abc123",
    )
    digest = br.sha256_file(pkg)
    size = pkg.stat().st_size
    report = br.verify_release_zip(
        pkg,
        expected_version="1.0.0",
        expected_sha="abc123",
        expected_size=size,
        expected_sha256=digest,
    )
    assert report["version"] == "1.0.0"
    assert report["sha"] == "abc123"
    assert report["size"] == size
    assert report["sha256"] == digest
    assert report["file_count"] == len(br.RELEASE_FILES)

    # CLI --verify succeeds on matching metadata and fails on mismatch
    assert br.main([
        "--verify", str(pkg),
        "--version", "1.0.0",
        "--sha", "abc123",
        "--expected-sha256", digest,
        "--expected-size", str(size),
    ]) == 0
    assert br.main([
        "--verify", str(pkg),
        "--version", "1.0.0",
        "--sha", "wrongsha",
    ]) == 1

    # Missing file from RELEASE_FILES must fail verification
    broken_missing = tmp_path / "missing.zip"
    with zipfile.ZipFile(pkg, "r") as src, zipfile.ZipFile(
        broken_missing, "w", zipfile.ZIP_DEFLATED
    ) as dst:
        for item in src.infolist():
            if item.filename != "plugins/updater.py":
                dst.writestr(item, src.read(item.filename))
    with pytest.raises(ValueError, match="saknas"):
        br.verify_release_zip(broken_missing)

    # Leaked private/user data inside the zip must fail verification
    broken_user_data = tmp_path / "userdata.zip"
    with zipfile.ZipFile(pkg, "r") as src, zipfile.ZipFile(
        broken_user_data, "w", zipfile.ZIP_DEFLATED
    ) as dst:
        for item in src.infolist():
            dst.writestr(item, src.read(item.filename))
        dst.writestr("data/invoices.json", "[]")
    with pytest.raises(ValueError, match="privata"):
        br.verify_release_zip(broken_user_data)


def test_release_workflow_verifies_release_job_on_every_push():
    workflow = (
        PROJECT_DIR / ".github" / "workflows" / "release-integrity.yml"
    ).read_text(encoding="utf-8")
    # Tag pushes verify all workflow jobs, tag SHA, live asset download & checksum
    assert "verify-live-release:" in workflow
    assert "needs: [build-release-package]" in workflow
    assert "actions: read" in workflow
    assert "gh release download" in workflow
    assert "--expected-sha256" in workflow
    assert "--expected-size" in workflow
    assert "actions/runs/${GITHUB_RUN_ID}/jobs" in workflow

    # Non-tag pushes run dry-run build verification & check live release job status
    assert "verify-release-build:" in workflow
    assert "actions/workflows/release-integrity.yml/runs" in workflow
    assert "python build_release.py \\\n            --verify" in workflow or "--verify" in workflow
