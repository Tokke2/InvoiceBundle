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

import json
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


def test_python_update_helper_is_shipped_and_checks_before_download():
    launcher = PROJECT_DIR / "Installera senaste Python.bat"
    script = PROJECT_DIR / "autostart" / "install_python.ps1"
    assert launcher.is_file()
    assert "Installera senaste Python.bat" in br.RELEASE_FILES
    assert "autostart/install_python.ps1" in br.RELEASE_FILES
    assert "install_python.ps1" in launcher.read_text(encoding="utf-8")

    source = script.read_text(encoding="utf-8")
    detect = source.index("$registered = @(Get-RegistryPythonEntries)")
    release_lookup = source.index("$release = Get-LatestInstallerInfo $tag")
    download = source.index("Download-Installer $release.Url $TempInstaller")
    assert detect < release_lookup < download
    assert "Find-UnregisteredPython $registered" in source
    assert "Get-UninstallEntry $selected $selected.Scope" in source
    assert "Rollback-NewPython" in source
    assert "Test-AppPythonRuntime" in source
    assert "Get-FallbackInstallerInfo" in source
    assert "3.14.8" in source
    probe_new_runtime = source.index(
        "if (-not (Test-AppPythonRuntime $newExe -EnsureDependencies))"
    )
    uninstall_old_runtime = source.index(
        "Invoke-PythonUninstaller $oldUninstaller"
    )
    assert probe_new_runtime < uninstall_old_runtime
    assert "ingen ominstallation behövs" in source
    assert "[switch]$UpdatePackages" in source
    assert "[switch]$UseUserPackages" in source
    assert "[string]$PythonExe" in source
    assert "[int]$WaitForPid" in source
    assert "WEEKLY_PACKAGE_UPDATE_START" in source
    assert "ensure_packages.py" in source


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
