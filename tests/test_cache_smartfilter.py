"""SMARTFILTER-cache: rensa manuellt med filter + automatiskt 1×/dygn.

Smartfiltret tar bara cachefiler ÄLDRE än 1 dygn och rör aldrig
färska filer (dagens, ev. låsta) eller riktiga filer.
Dygnsautomatiken (maybe_daily_cache_clean) kör högst en gång
per 24 timmar och sätter stämpeln först när rensningen gjorts.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as appmod


def _age(path: Path, days: float) -> None:
    old = time.time() - days * 86400
    os.utime(path, (old, old))


def _build(tmp_path: Path) -> dict[str, Path]:
    files = {}
    # Gammal cache (> 1 dygn)
    old_pc = tmp_path / "__pycache__"
    old_pc.mkdir()
    (old_pc / "mod.cpython-311.pyc").write_bytes(b"o" * 100)
    _age(old_pc / "mod.cpython-311.pyc", 2)
    _age(old_pc, 2)
    files["old_pycache"] = old_pc
    (tmp_path / "gammal.pyc").write_bytes(b"g" * 10)
    _age(tmp_path / "gammal.pyc", 3)
    files["old_pyc"] = tmp_path / "gammal.pyc"
    (tmp_path / "rest.tmp").write_bytes(b"t" * 5)
    _age(tmp_path / "rest.tmp", 2)
    files["old_tmp"] = tmp_path / "rest.tmp"
    # Färsk cache (idag)
    fresh_pc = tmp_path / "ui" / "__pycache__"
    fresh_pc.mkdir(parents=True)
    (fresh_pc / "x.pyc").write_bytes(b"f" * 50)
    files["fresh_pycache"] = fresh_pc
    (tmp_path / "farsk.pyc").write_bytes(b"n" * 7)
    files["fresh_pyc"] = tmp_path / "farsk.pyc"
    # Riktiga filer — aldrig röra
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    _age(tmp_path / "settings.json", 5)
    files["settings"] = tmp_path / "settings.json"
    return files


def test_smartfilter_only_removes_old_cache(tmp_path):
    f = _build(tmp_path)
    stats = appmod.clean_caches_smart(tmp_path, days=1)
    # Gamla borta
    assert not f["old_pycache"].exists()
    assert not f["old_pyc"].exists()
    assert not f["old_tmp"].exists()
    assert stats["pycache_mappar"] == 1
    assert stats["pyc_filer"] == 1
    assert stats["tmp_filer"] == 1
    assert stats["frigjorda_bytes"] == 100 + 10 + 5
    # Färska + riktiga orörda
    assert f["fresh_pycache"].exists()
    assert (f["fresh_pycache"] / "x.pyc").exists()
    assert f["fresh_pyc"].exists()
    assert f["settings"].exists()


def test_smartfilter_nothing_old_is_noop(tmp_path):
    (tmp_path / "farsk.pyc").write_bytes(b"n")
    stats = appmod.clean_caches_smart(tmp_path, days=1)
    assert stats["pycache_mappar"] == 0
    assert stats["pyc_filer"] == 0
    assert (tmp_path / "farsk.pyc").exists()


class _DailyFake:
    """Fejkad app-instans för dygnsautomatiken."""

    def __init__(self, tmp_path, last=""):
        self.settings = appmod.SettingsManager(
            tmp_path / "settings.json"
        )
        if last:
            self.settings.set("cache_last_daily_clean", last)


def test_daily_clean_runs_once_per_day(tmp_path, monkeypatch):
    # Rikta rensningen mot tmp-mappen i stället för appmappen
    monkeypatch.setattr(appmod, "BASE_DIR", tmp_path)
    _build(tmp_path)
    fake = _DailyFake(tmp_path)

    stats = appmod.FakturaApp.maybe_daily_cache_clean(fake)
    assert stats is not None
    assert stats["pyc_filer"] == 1  # gammal.pyc borta
    assert fake.settings.get("cache_last_daily_clean")

    # Andra körningen samma dygn: ingen rensning
    stats2 = appmod.FakturaApp.maybe_daily_cache_clean(fake)
    assert stats2 is None


def test_daily_clean_runs_again_after_24h(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "BASE_DIR", tmp_path)
    _build(tmp_path)
    import datetime as _dt
    old_stamp = (
        _dt.datetime.now() - _dt.timedelta(hours=25)
    ).isoformat()
    fake = _DailyFake(tmp_path, last=old_stamp)
    stats = appmod.FakturaApp.maybe_daily_cache_clean(fake)
    assert stats is not None


def test_clean_now_modes(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "BASE_DIR", tmp_path)
    f = _build(tmp_path)
    fake = _DailyFake(tmp_path)

    # old: bara gamla filer
    stats = appmod.FakturaApp.clean_caches_now(fake, "old")
    assert stats["pyc_filer"] == 1
    assert f["fresh_pyc"].exists()

    # all: även färska
    stats = appmod.FakturaApp.clean_caches_now(fake, "all")
    assert not f["fresh_pyc"].exists()
    assert f["settings"].exists()

    # okänt läge: tom dict, inget kraschar
    assert appmod.FakturaApp.clean_caches_now(fake, "??") == {}
