# -*- coding: utf-8 -*-
"""
updater.py — uppdatering i appen (Sök ny version).

Flöde:
  1. check_for_update() frågar GitHub om senaste releasen och jämför
     dess commit (via taggen) med build_info.json i appmappen.
  2. download_release() hämtar zip-asset (fallback: GitHubs zipball).
  3. apply_update() packar upp i en temporär mapp och byter
     programfilerna — men rör ALDRIG användardata.

Aldrig-rör-regeln (samma som appens cache-rensare):
  • Mapparna  data/  js/  logs/  exports/  bak/  (och ui/data/ —
    den äldre datamappen) lämnas helt orörda.
  • settings.json och shortcuts.json i approten rörs aldrig.
  • Filer som fanns i förra builden men inte i den nya tas bort
    (endast spårade programfiler — aldrig data).
Innan något skrivs tas en backup till bak/update-<tid>/ .

Modulen är Qt-fri och kan testas rakt av.
"""
from __future__ import annotations

import datetime
import json
import logging
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("invoice_bundle")

REPO = "Tokke2/InvoiceBundle"
API_BASE = f"https://api.github.com/repos/{REPO}"
USER_AGENT = "Fakturabunten-Updater/1.0"

#: Mappar i approten som ALDRIG skrivs över vid uppdatering.
PRESERVED_DIRS = {"data", "js", "logs", "exports", "bak", "__pycache__"}
#: Filer i approten som ALDRIG skrivs över.
PRESERVED_FILES = {"settings.json", "shortcuts.json",
                   "startup_crash.log"}
BUILD_INFO_NAME = "build_info.json"

ProgressFn = Callable[[int, int], None] | None


def is_preserved(rel: str | Path) -> bool:
    """True om den relativa sökvägen är användardata som aldrig rörs."""
    parts = Path(rel).parts
    if not parts:
        return True
    if parts[0] in PRESERVED_DIRS:
        return True
    if len(parts) == 1 and parts[0] in PRESERVED_FILES:
        return True
    # Legacy-datamappen ui/data/ (fakturajson m.m.)
    if len(parts) >= 2 and parts[0] == "ui" and parts[1] == "data":
        return True
    return False


# ── GitHub API ─────────────────────────────────────────────────────────

def _fetch_json(url: str, timeout: int = 25) -> Any:
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT,
                      "Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def pick_zip_asset(release: dict) -> dict | None:
    """Väljer zip-asset i en release (föredrar vårt eget paket)."""
    assets = release.get("assets") or []
    zips = [a for a in assets
            if str(a.get("name", "")).lower().endswith(".zip")]
    if not zips:
        return None
    zips.sort(key=lambda a: 0 if "invoicebundle" in
              str(a.get("name", "")).lower() else 1)
    chosen = zips[0]
    return {
        "name": chosen.get("name", ""),
        "url": chosen.get("browser_download_url", ""),
        "size": int(chosen.get("size", 0) or 0),
    }


def resolve_tag_sha(tag: str, fetch: Callable = _fetch_json) -> str:
    """Commit-sha som taggen pekar på (följer annoterade taggar)."""
    ref = fetch(f"{API_BASE}/git/ref/tags/{tag}")
    obj = ref.get("object") or {}
    sha = str(obj.get("sha", ""))
    if obj.get("type") == "tag" and sha:
        tag_obj = fetch(f"{API_BASE}/git/tags/{sha}")
        sha = str((tag_obj.get("object") or {}).get("sha", "")) or sha
    return sha


def get_latest_release(fetch: Callable = _fetch_json) -> dict:
    """Senaste releasen, normaliserad + taggens commit-sha."""
    release = fetch(f"{API_BASE}/releases/latest")
    tag = str(release.get("tag_name", ""))
    sha = resolve_tag_sha(tag, fetch) if tag else ""
    return {
        "tag": tag,
        "name": str(release.get("name", "") or tag),
        "published_at": str(release.get("published_at", "")),
        "body": str(release.get("body", "") or ""),
        "sha": sha,
        "asset": pick_zip_asset(release),
        "zipball_url": str(release.get("zipball_url", "")),
    }


# ── Lokal build-info ───────────────────────────────────────────────────

def read_local_build(root: Path) -> dict:
    """build_info.json i appmappen ({} om den saknas — äldre kopia)."""
    try:
        info = json.loads(
            (Path(root) / BUILD_INFO_NAME).read_text(encoding="utf-8")
        )
        return info if isinstance(info, dict) else {}
    except Exception:
        return {}


def auto_check_due(last_check: str,
                   now: datetime.datetime | None = None) -> bool:
    """True om bakgrundskollen får köras (minst 24 h sedan sist)."""
    now = now or datetime.datetime.now()
    try:
        last = datetime.datetime.fromisoformat(str(last_check))
    except Exception:
        return True
    return (now - last) >= datetime.timedelta(hours=24)


def should_update(local_sha: str, remote_sha: str) -> bool:
    """Ny version = annan commit än den installerade (eller okänd)."""
    if not remote_sha:
        return False
    return (local_sha or "").strip().lower() != remote_sha.strip().lower()


def check_for_update(root: Path,
                     fetch: Callable = _fetch_json) -> dict:
    """{status: current|update|unknown, local, release} — nät mot GitHub."""
    local = read_local_build(root)
    release = get_latest_release(fetch)
    status = (
        "update" if should_update(str(local.get("sha", "")),
                                  release["sha"])
        else "current"
    )
    return {"status": status, "local": local, "release": release}


# ── Hämtning ───────────────────────────────────────────────────────────

def download_file(url: str, dest: Path,
                  progress: ProgressFn = None,
                  timeout: int = 120) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as fh:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    return dest


# ── Applicering ────────────────────────────────────────────────────────

def _strip_root(names: list[str]) -> str:
    """Gemensam topp-mapp i zipen (GitHub-zipball) att strippa, annars ''."""
    files = [n for n in names if not n.endswith("/")]
    if not files:
        return ""
    firsts = {n.split("/")[0] for n in files}
    if len(firsts) != 1:
        return ""
    top = firsts.pop()
    rest = [n[len(top) + 1:] for n in files if n.startswith(top + "/")]
    if any(Path(r).name in ("main.py", "app.py") for r in rest):
        return top + "/"
    return ""


def _safe_extract(zip_path: Path, stage: Path) -> Path:
    """Packar upp zipen i `stage`; returnerar effektiva programroten."""
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        prefix = _strip_root(names)
        root_resolved = stage.resolve()
        for name in names:
            if name.endswith("/"):
                continue
            rel = name[len(prefix):] if prefix and \
                name.startswith(prefix) else name
            if not rel or rel.startswith("/") or ".." in Path(rel).parts:
                continue  # zip-slip-skydd
            target = (stage / rel).resolve()
            if not str(target).startswith(str(root_resolved)):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return stage


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".update-tmp")
    shutil.copyfile(src, tmp)
    tmp.replace(dst)


def find_backups(root: Path) -> list[Path]:
    """Uppdateringsbackuper i bak/, nyaste först."""
    bak = Path(root) / "bak"
    try:
        dirs = [d for d in bak.glob("update-*") if d.is_dir()]
    except Exception:
        return []
    return sorted(dirs, reverse=True)


def restore_backup(backup_dir: Path, root: Path) -> dict:
    """Kopierar tillbaka en updateringsbackup (bara programfiler)."""
    backup_dir, root = Path(backup_dir), Path(root)
    report = {"restored": 0, "skipped": 0}
    for src in sorted(backup_dir.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(backup_dir).as_posix()
        if is_preserved(rel):
            report["skipped"] += 1
            continue
        try:
            _copy_file(src, root / rel)
            report["restored"] += 1
        except Exception as exc:
            log.warning("UPDATE återställ %s: %s", rel, exc)
            report["skipped"] += 1
    log.info("UPDATE återställd från %s: %s", backup_dir.name, report)
    return report


def apply_update(zip_path: Path, root: Path, *,
                 version: str = "",
                 sha: str = "",
                 progress: ProgressFn = None) -> dict:
    """
    Ersätter programfiler i `root` med zipens innehåll.

    Bevarar user-data (is_preserved), tar backup till
    bak/update-<tid>/ och tar bort spårade programfiler som inte
    längre finns i den nya builden. Returnerar rapport-dict.
    """
    root = Path(root)
    old = read_local_build(root)
    old_files = [str(f) for f in old.get("files", [])]
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = root / "bak" / f"update-{stamp}"
    report: dict[str, Any] = {
        "replaced": 0, "added": 0, "removed": 0, "skipped": 0,
        "backup": str(backup_dir), "files": [],
    }

    with tempfile.TemporaryDirectory(prefix="fb-update-") as tmp:
        stage = _safe_extract(Path(zip_path), Path(tmp) / "stage")
        # Samla arbetet först så förloppet kan visa fil X av Y
        work: list[tuple[Path, str]] = []
        new_files: list[str] = []
        for src in sorted(stage.rglob("*")):
            if not src.is_file():
                continue
            rel = src.relative_to(stage).as_posix()
            if is_preserved(rel) or "__pycache__" in Path(rel).parts:
                report["skipped"] += 1
                continue
            new_files.append(rel)
            work.append((src, rel))
        total_files = len(work)
        for done_files, (src, rel) in enumerate(work, start=1):
            dst = root / rel
            try:
                if dst.exists():
                    bak = backup_dir / rel
                    bak.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(dst, bak)
                    report["replaced"] += 1
                else:
                    report["added"] += 1
                _copy_file(src, dst)
            except Exception as exc:
                log.warning("UPDATE %s misslyckades: %s", rel, exc)
                report["skipped"] += 1
            if progress:
                progress(done_files, total_files)

        # Stale: spårade programfiler som inte finns i nya builden
        for rel in old_files:
            if rel in new_files or is_preserved(rel):
                continue
            dst = root / rel
            try:
                if dst.exists():
                    bak = backup_dir / rel
                    bak.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(dst, bak)
                    dst.unlink()
                    report["removed"] += 1
            except Exception as exc:
                log.warning("UPDATE stale %s: %s", rel, exc)

        info = {
            "version": version or str(old.get("version", "")),
            "sha": sha,
            "built": datetime.datetime.now().isoformat(timespec="seconds"),
            "files": sorted(new_files),
        }
        (root / BUILD_INFO_NAME).write_text(
            json.dumps(info, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        report["files"] = info["files"]
    log.info(
        "UPDATE klar: %d ersatta, %d nya, %d borttagna, %d hoppade över "
        "(backup: %s)",
        report["replaced"], report["added"], report["removed"],
        report["skipped"], report["backup"],
    )
    return report
