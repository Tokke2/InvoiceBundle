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
    assert br.missing_critical_files(PROJECT_DIR) == []


def test_all_release_files_exist_in_repo():
    assert br.validate_release_files(PROJECT_DIR) == []


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


def test_i18n_update_keys_exist():
    s = (PROJECT_DIR / "ui" / "i18n.py").read_text(encoding="utf-8")
    for key in ("menu.update", "update.title", "update.auto_menu",
                "update.found_title", "update.failed"):
        assert f'"{key}"' in s, key


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
        info = json.loads(zf.read("build_info.json").decode("utf-8"))
    assert info["sha"] == "deadbeef"
    assert info["version"] == "1.0.0"
    assert "plugins/updater.py" in info["files"]
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
