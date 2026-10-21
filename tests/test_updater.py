# -*- coding: utf-8 -*-
"""
Tester: uppdatering i appen (plugins/updater.py).

Uppdateraren frågar GitHub om senaste releasen och byter bara
programfiler — data/, js/, ui/data/, settings.json och loggar
rörs ALDRIG. Spårade filer som försvunnit ur builden tas bort,
med backup i bak/ först.
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "plugins"),
           str(PROJECT_DIR / "ui")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

import updater as up


def _zip(path: Path, files: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return path


def test_preserved_never_touched():
    for rel in ("data/invoices.json", "js/app.js", "logs/app.log",
                "exports/2026/x.pdf", "bak/backup.zip",
                "ui/data/invoices.json", "settings.json",
                "shortcuts.json"):
        assert up.is_preserved(rel), rel
    for rel in ("app.py", "main.py", "ui/main_window.py",
                "plugins/updater.py", "build_info.json"):
        assert not up.is_preserved(rel), rel


def test_pick_zip_asset_and_update_logic():
    release = {"assets": [
        {"name": "notes.txt", "browser_download_url": "x", "size": 1},
        {"name": "annat.zip", "browser_download_url": "y", "size": 2},
        {"name": "InvoiceBundle-v1.0.0.zip",
         "browser_download_url": "z", "size": 3},
    ]}
    assert up.pick_zip_asset(release)["url"] == "z"
    assert up.pick_zip_asset({"assets": []}) is None
    assert up.should_update("", "abc123")
    assert up.should_update("old", "abc123")
    assert not up.should_update("abc123", "abc123")
    assert not up.should_update("abc123", "")


def _fake_fetch(release_sha="nyasha"):
    def fetch(url):
        if url.endswith("/releases/latest"):
            return {
                "tag_name": "v1.0.0", "name": "v1.0.0",
                "published_at": "2026-10-14T10:00:00Z", "body": "nytt",
                "zipball_url": "https://example/zipball",
                "assets": [{"name": "InvoiceBundle-v1.0.0.zip",
                            "browser_download_url": "https://ex/z.zip",
                            "size": 42}],
            }
        assert "/git/ref/tags/" in url
        return {"object": {"sha": release_sha, "type": "commit"}}
    return fetch


def test_check_for_update_compares_sha(tmp_path):
    result = up.check_for_update(tmp_path, fetch=_fake_fetch())
    assert result["status"] == "update"          # ingen build_info ännu
    assert result["release"]["asset"]["url"].endswith("z.zip")
    (tmp_path / "build_info.json").write_text(
        json.dumps({"sha": "nyasha", "files": []}), encoding="utf-8"
    )
    result = up.check_for_update(tmp_path, fetch=_fake_fetch())
    assert result["status"] == "current"


def test_apply_update_replaces_only_program_files(tmp_path):
    root = tmp_path / "app"
    (root / "data").mkdir(parents=True)
    (root / "ui" / "data").mkdir(parents=True)
    (root / "app.py").write_text("GAMMAL", encoding="utf-8")
    (root / "settings.json").write_text('{"tema":"mitt"}', encoding="utf-8")
    (root / "data" / "invoices.json").write_text("[]", encoding="utf-8")
    (root / "stale.py").write_text("borta i nya", encoding="utf-8")
    (root / "build_info.json").write_text(
        json.dumps({"sha": "old", "files": ["app.py", "stale.py"]}),
        encoding="utf-8",
    )
    zipp = _zip(tmp_path / "ny.zip", {
        "app.py": "NY KOD",
        "ui/main_window.py": "nytt fönster",
        "settings.json": '{"tema":"FARLIGT"}',       # får ALDRIG skrivas
        "data/invoices.json": "FARLIGT",             # får ALDRIG skrivas
        "js/app.js": "hor inte hit",                 # js/ bevaras också
        "ui/data/invoices.json": "FARLIGT",
        "../slip.py": "zip-slip-forsok",
    })
    report = up.apply_update(zipp, root, version="1.0.0", sha="nyasha")
    assert (root / "app.py").read_text(encoding="utf-8") == "NY KOD"
    assert (root / "ui" / "main_window.py").exists()
    assert not (root / "js").exists()
    assert (root / "settings.json").read_text(
        encoding="utf-8") == '{"tema":"mitt"}'
    assert (root / "data" / "invoices.json").read_text(
        encoding="utf-8") == "[]"
    assert not (root / "slip.py").exists()
    assert not (root / "stale.py").exists()          # stale borttagen
    assert report["removed"] == 1
    info = json.loads(
        (root / "build_info.json").read_text(encoding="utf-8"))
    assert info["sha"] == "nyasha"
    assert "ui/main_window.py" in info["files"]
    # Backup av det som byttes/togs bort finns i bak/
    backups = list((root / "bak").rglob("app.py"))
    assert backups and backups[0].read_text(encoding="utf-8") == "GAMMAL"


def test_apply_update_strips_zipball_root(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    zipp = _zip(tmp_path / "zipball.zip", {
        "Tokke2-InvoiceBundle-abc123/main.py": "start",
        "Tokke2-InvoiceBundle-abc123/ui/design.py": "tema",
        "Tokke2-InvoiceBundle-abc123/data/x.json": "data i zipball",
    })
    up.apply_update(zipp, root, sha="abc123")
    assert (root / "main.py").read_text(encoding="utf-8") == "start"
    assert (root / "ui" / "design.py").exists()
    assert not (root / "data" / "x.json").exists()   # data rörs inte


def test_auto_check_due_daily_gate():
    import datetime as dt
    now = dt.datetime(2026, 10, 14, 12, 0, 0)
    assert up.auto_check_due("", now)                        # aldrig kollat
    assert up.auto_check_due("skräp", now)                   # korrupt värde
    assert up.auto_check_due("2026-10-13T11:59:59", now)     # > 24 h sedan
    assert not up.auto_check_due("2026-10-14T11:00:00", now)  # 1 h sedan
    assert not up.auto_check_due("2026-10-13T13:00:00", now)  # 23 h sedan


def test_restore_backup_roundtrip(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    (root / "app.py").write_text("STABIL GAMMAL", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "invoices.json").write_text("[]", encoding="utf-8")
    # Uppdatering: app.py ersätts (backup får gamla innehållet)
    up.apply_update(
        _zip(tmp_path / "v2.zip", {"app.py": "NY MEN TRASIG"}),
        root, sha="v2",
    )
    assert (root / "app.py").read_text(encoding="utf-8") == "NY MEN TRASIG"
    backups = up.find_backups(root)
    assert len(backups) == 1
    report = up.restore_backup(backups[0], root)
    assert report["restored"] == 1
    assert (root / "app.py").read_text(
        encoding="utf-8") == "STABIL GAMMAL"
    # Data aldrig rörd av återställningen
    assert (root / "data" / "invoices.json").read_text(
        encoding="utf-8") == "[]"
    assert up.find_backups(tmp_path / "tom") == []


def test_apply_update_reports_file_progress(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    zipp = _zip(tmp_path / "ny.zip", {
        "app.py": "a", "ui/x.py": "b", "plugins/y.py": "c",
        "data/invoices.json": "bevaras",   # räknas inte som arbete
    })
    calls = []
    up.apply_update(zipp, root, sha="s",
                    progress=lambda d, t: calls.append((d, t)))
    assert calls == [(1, 3), (2, 3), (3, 3)]
    assert not (root / "data" / "invoices.json").exists()


# ── Uppdatera från RELEASE, aldrig från main ─────────────────────────

def test_latest_release_archive_url_built_from_tag():
    # Även om GitHub-svaret skulle innehålla en branch-URL (main!)
    # bygger uppdateraren alltid arkiv-URL:en ur releasens tagg.
    def fetch(url):
        if url.endswith("/releases/latest"):
            return {
                "tag_name": "v1.0.0", "name": "v1.0.0",
                "published_at": "", "body": "",
                "zipball_url":
                    "https://api.github.com/repos/Tokke2/"
                    "InvoiceBundle/zipball/main",
                "assets": [],
            }
        assert "/git/ref/tags/" in url
        return {"object": {"sha": "abc123", "type": "commit"}}
    rel = up.get_latest_release(fetch)
    assert rel["zipball_url"].endswith("/zipball/refs/tags/v1.0.0")
    assert up.is_release_bound_url(rel["zipball_url"], "v1.0.0")
    assert up.release_archive_url("") == ""


def test_is_release_bound_url_rejects_branches():
    tag = "v1.0.0"
    assert up.is_release_bound_url(
        "https://github.com/Tokke2/InvoiceBundle/releases/"
        "download/v1.0.0/InvoiceBundle-v1.0.0.zip", tag)
    assert up.is_release_bound_url(
        "https://api.github.com/repos/Tokke2/InvoiceBundle/"
        "zipball/refs/tags/v1.0.0", tag)
    for bad in (
        "https://api.github.com/repos/Tokke2/InvoiceBundle/zipball/main",
        "https://api.github.com/repos/Tokke2/InvoiceBundle/zipball",
        "https://github.com/Tokke2/InvoiceBundle/archive/refs/heads/main.zip",
        "https://github.com/Tokke2/InvoiceBundle/releases/download/v9.9.9/x.zip",
        "https://example.com/v1.0.0.zip",
        "",
    ):
        assert not up.is_release_bound_url(bad, tag), bad
    assert not up.is_release_bound_url(
        "https://api.github.com/repos/Tokke2/InvoiceBundle/"
        "zipball/refs/tags/v1.0.0", "")


_ASSET_URL = ("https://github.com/Tokke2/InvoiceBundle/releases/"
              "download/v1.0.0/InvoiceBundle-v1.0.0.zip")


def _release(asset_url="", sha="abc123"):
    return {
        "tag": "v1.0.0", "sha": sha,
        "asset": ({"name": "InvoiceBundle-v1.0.0.zip",
                   "url": asset_url, "size": 1} if asset_url else None),
        "zipball_url": up.release_archive_url("v1.0.0"),
    }


def test_download_release_zip_prefers_verified_asset(tmp_path):
    asset_zip = _zip(tmp_path / "asset.zip", {
        "build_info.json": json.dumps({"sha": "abc123"}),
        "app.py": "NY KOD",
    })

    def fake_download(url, dest, progress=None):
        Path(dest).write_bytes(asset_zip.read_bytes())
        return Path(dest)

    out = up.download_release_zip(
        _release(_ASSET_URL), tmp_path / "dl.zip",
        download=fake_download)
    with zipfile.ZipFile(out) as zf:
        assert zf.read("app.py").decode() == "NY KOD"


def test_download_release_zip_stale_asset_falls_back_to_tag(tmp_path):
    # Asset från en äldre taggflytt (build-sha stämmer inte) får
    # aldrig installeras — taggens eget arkiv hämtas i stället.
    stale = _zip(tmp_path / "stale.zip", {
        "build_info.json": json.dumps({"sha": "gammalsha"}),
        "app.py": "GAMMAL KOD",
    })
    tag_zip = _zip(tmp_path / "tag.zip", {"app.py": "TAGGENS KOD"})
    calls = []

    def fake_download(url, dest, progress=None):
        calls.append(url)
        src = stale if url == _ASSET_URL else tag_zip
        Path(dest).write_bytes(src.read_bytes())
        return Path(dest)

    out = up.download_release_zip(
        _release(_ASSET_URL), tmp_path / "dl.zip",
        download=fake_download)
    assert calls == [_ASSET_URL, up.release_archive_url("v1.0.0")]
    with zipfile.ZipFile(out) as zf:
        assert zf.read("app.py").decode() == "TAGGENS KOD"


def test_download_release_zip_never_downloads_branch(tmp_path):
    tag_zip = _zip(tmp_path / "tag.zip", {"app.py": "TAGGENS KOD"})
    calls = []

    def fake_download(url, dest, progress=None):
        calls.append(url)
        Path(dest).write_bytes(tag_zip.read_bytes())
        return Path(dest)

    rel = _release(
        "https://api.github.com/repos/Tokke2/InvoiceBundle/zipball/main")
    up.download_release_zip(rel, tmp_path / "dl.zip",
                            download=fake_download)
    assert calls == [up.release_archive_url("v1.0.0")]
    assert all("main" not in u for u in calls)


def test_zip_build_sha_reads_built_zip(tmp_path):
    built = _zip(tmp_path / "b.zip", {
        "build_info.json": json.dumps({"sha": "deadbeef"}),
        "app.py": "x",
    })
    assert up.zip_build_sha(built) == "deadbeef"
    plain = _zip(tmp_path / "p.zip", {"app.py": "x"})
    assert up.zip_build_sha(plain) == ""   # taggarkiv: ingen build_info


def test_same_version_new_files_are_an_update(tmp_path):
    # Kravet: versionen står kvar på v1.0.0 — ändras filerna i
    # releasen (ny commit under samma tagg) ska appen ändå uppdatera.
    # Det är commit-shan som jämförs, aldrig versionsnumret.
    (tmp_path / "build_info.json").write_text(
        json.dumps({"version": "1.0.0", "sha": "forra", "files": []}),
        encoding="utf-8",
    )
    result = up.check_for_update(
        tmp_path, fetch=_fake_fetch(release_sha="nya-filer"))
    assert result["release"]["tag"] == "v1.0.0"      # samma version …
    assert result["status"] == "update"              # … men nya filer
    (tmp_path / "build_info.json").write_text(
        json.dumps({"version": "1.0.0", "sha": "nya-filer",
                    "files": []}),
        encoding="utf-8",
    )
    result = up.check_for_update(
        tmp_path, fetch=_fake_fetch(release_sha="nya-filer"))
    assert result["status"] == "current"
