# -*- coding: utf-8 -*-
"""
build_release.py — bygger programpaketet (InvoiceBundle-vX.Y.Z.zip).

Det här är den ENDA kanoniska listan över filer som ska finnas i
release-zippen. Syftet är att autouppdateringen aldrig mer ska kunna
"försvinna" tyst ur ett paket: byggaren vägrar bygga om någon av de
kritiska uppdateringsfilerna saknas, och tests/test_release_integrity.py
vaktar samma lista i CI.

Zippen innehåller bara programfiler. Användardata (data/, ui/data/,
settings.json, loggar, exporter, backuper) läggs aldrig i paketet och
rörs aldrig av uppdateraren.
"""
from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
import zipfile
from pathlib import Path

#: Alla programfiler i release-zippen (build_info.json genereras).
RELEASE_FILES: tuple[str, ...] = (
    "CHANGELOG.md",
    "README.md",
    "app.py",
    "app_icon.ico",
    "app_icon.png",
    "app_icon.svg",
    "autostart/LAS_MIG.txt",
    "autostart/install_python.ps1",
    "autostart/start_hidden.sh",
    "autostart/start_hidden.vbs",
    "build_release.py",
    "ensure_packages.py",
    "main.py",
    "main.pyw",
    "plugins/advanced_logger.py",
    "plugins/pdf_export.py",
    "plugins/pdf_export_helpers.py",
    "plugins/scan_import.py",
    "plugins/updater.py",
    "requirements.txt",
    "ui/auto_batch.py",
    "ui/contrast.py",
    "ui/core/calculator.py",
    "ui/core/search.py",
    "ui/core/storage.py",
    "ui/dashboard_view.py",
    "ui/date_picker.py",
    "ui/design.py",
    "ui/donate.py",
    "ui/history_view.py",
    "ui/i18n.py",
    "ui/invoices_helpers.py",
    "ui/invoices_view.py",
    "ui/letter_jump.py",
    "ui/log_view.py",
    "ui/main_window.py",
    "ui/scan_import_view.py",
    "ui/suppliers_view.py",
    "ui/update_dialog.py",
    "ui/watch_folders.py",
)

#: Filer som aldrig får saknas — utan dem finns ingen autouppdatering.
CRITICAL_FILES: tuple[str, ...] = (
    "plugins/updater.py",
    "ui/update_dialog.py",
    "ui/main_window.py",
    "ui/i18n.py",
)

BUILD_INFO_NAME = "build_info.json"


def validate_release_files(root: Path) -> list[str]:
    """Relativa sökvägar i release-listan som saknas under root."""
    root = Path(root)
    return [rel for rel in RELEASE_FILES if not (root / rel).is_file()]


def missing_critical_files(root: Path) -> list[str]:
    root = Path(root)
    return [rel for rel in CRITICAL_FILES if not (root / rel).is_file()]


def git_sha(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root), capture_output=True, text=True, timeout=15,
        )
        sha = (out.stdout or "").strip()
        return sha if out.returncode == 0 else ""
    except Exception:
        return ""


def build_release_zip(root: Path, out: Path, *, version: str = "1.0.0",
                      sha: str = "") -> Path:
    """
    Bygger release-zippen i `out` med build_info.json.

    Vägrar (FileNotFoundError) om någon fil i RELEASE_FILES saknas —
    ett paket utan t.ex. uppdateraren får aldrig byggas tyst.
    """
    root, out = Path(root), Path(out)
    missing = validate_release_files(root)
    if missing:
        raise FileNotFoundError(
            "Release-paketet saknar filer och byggs inte: "
            + ", ".join(missing)
        )
    sha = sha or git_sha(root)
    files = sorted([*RELEASE_FILES, BUILD_INFO_NAME])
    info = {
        "version": version,
        "sha": sha,
        "built": datetime.datetime.now().isoformat(timespec="seconds"),
        "files": files,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in RELEASE_FILES:
            zf.write(root / rel, rel)
        zf.writestr(
            BUILD_INFO_NAME,
            json.dumps(info, ensure_ascii=False, indent=1),
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bygg Fakturabuntens release-zip."
    )
    parser.add_argument("--root", default=".",
                        help="approten (default: aktuell katalog)")
    parser.add_argument("--out", default="",
                        help="zip att skriva (default: InvoiceBundle-v<version>.zip)")
    parser.add_argument("--version", default="1.0.0")
    parser.add_argument("--sha", default="",
                        help="commit-sha till build_info.json (default: git HEAD)")
    args = parser.parse_args(argv)
    root = Path(args.root)
    out = Path(args.out) if args.out else (
        root / f"InvoiceBundle-v{args.version}.zip"
    )
    try:
        built = build_release_zip(
            root, out, version=args.version, sha=args.sha
        )
    except FileNotFoundError as exc:
        print(f"FEL: {exc}", file=sys.stderr)
        return 1
    print(f"Byggde {built} ({built.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
