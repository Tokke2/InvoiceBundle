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
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

#: Alla programfiler i release-zippen (build_info.json genereras).
RELEASE_FILES: tuple[str, ...] = (
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
    "Starta Fakturabunten.bat",
    "Starta Fakturabunten.command",
    "Starta Fakturabunten.sh",
    "app.py",
    "app_icon.ico",
    "app_icon.png",
    "app_icon.svg",
    "app_icon_tray.png",
    "brand/README.md",
    "brand/fakturabunten-ikon.svg",
    "brand/fakturabunten-ikon-monokrom.svg",
    "brand/fakturabunten-ikon-tryck-bleed.svg",
    "brand/fakturabunten-logotyp.svg",
    "brand/fakturabunten-logotyp-mork-bakgrund.svg",
    "brand/fakturabunten-logotyp-svartvit.svg",
    "autostart/LAS_MIG.txt",
    "autostart/start_fakturabunten.ps1",
    "autostart/start_hidden.sh",
    "autostart/start_hidden.vbs",
    "build_release.py",
    "ensure_packages.py",
    "main.py",
    "main.pyw",
    "plugins/advanced_logger.py",
    "plugins/error_collect.py",
    "plugins/learning_logger.py",
    "plugins/log_archive.py",
    "plugins/pdf_export.py",
    "plugins/pdf_export_helpers.py",
    "plugins/python_update_scheduler.py",
    "plugins/scan_import.py",
    "plugins/updater.py",
    "requirements.txt",
    "windows_shortcut.py",
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
    "ui/icons.py",
    "ui/invoice_table_model.py",
    "ui/invoices_helpers.py",
    "ui/invoices_view.py",
    "ui/letter_jump.py",
    "ui/log_view.py",
    "ui/main_window.py",
    "ui/scan_import_view.py",
    "ui/suppliers_view.py",
    "ui/typography.py",
    "ui/update_dialog.py",
    "ui/watch_folders.py",
)

#: Filer som aldrig får saknas — utan dem finns ingen autouppdatering.
CRITICAL_FILES: tuple[str, ...] = (
    "plugins/updater.py",
    "ui/update_dialog.py",
    "ui/main_window.py",
    "ui/i18n.py",
    "ui/typography.py",
)

BUILD_INFO_NAME = "build_info.json"

FORBIDDEN_RELEASE_PREFIXES: tuple[str, ...] = (
    "data/",
    "ui/data/",
    "logs/",
    "exports/",
    "bak/",
)
FORBIDDEN_RELEASE_FILES: tuple[str, ...] = (
    "settings.json",
    "shortcuts.json",
    "Installera senaste Python.bat",
    "autostart/install_python.ps1",
)
EXECUTABLE_STARTERS: tuple[str, ...] = (
    "Starta Fakturabunten.command",
    "Starta Fakturabunten.sh",
)


def sha256_file(path: Path) -> str:
    """Returnerar hex-kodad SHA-256-kontrollsumma för en fil."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_release_zip(
    zip_path: Path,
    *,
    expected_version: str = "",
    expected_sha: str = "",
    expected_size: int | None = None,
    expected_sha256: str = "",
) -> dict[str, object]:
    """
    Verifierar ett byggt eller hämtat release-paket på riktigt.

    Kontrollerar filstorlek, SHA-256, zip-CRC för varje post,
    build_info.json (version/sha/files), samtliga RELEASE_FILES +
    CRITICAL_FILES, exekverbara startfiler och frånvaro av användardata.
    Kastar ValueError eller FileNotFoundError vid avvikelse.
    """
    zip_path = Path(zip_path)
    if not zip_path.is_file():
        raise FileNotFoundError(f"Release-paketet saknas: {zip_path}")
    actual_size = zip_path.stat().st_size
    if actual_size <= 0:
        raise ValueError(f"Release-paketet är tomt: {zip_path}")
    if expected_size is not None and actual_size != int(expected_size):
        raise ValueError(
            f"Fel storlek på release-paketet: {actual_size} != {expected_size}"
        )
    actual_sha256 = sha256_file(zip_path)
    if expected_sha256 and actual_sha256.lower() != expected_sha256.strip().lower():
        raise ValueError(
            "SHA-256 för release-paketet stämmer inte: "
            f"{actual_sha256} != {expected_sha256}"
        )

    with zipfile.ZipFile(zip_path, "r") as zf:
        bad_member = zf.testzip()
        if bad_member is not None:
            raise ValueError(f"Korrupt zip-post i paketet: {bad_member}")
        names = set(zf.namelist())
        if BUILD_INFO_NAME not in names:
            raise ValueError(f"{BUILD_INFO_NAME} saknas i release-paketet")
        try:
            info = json.loads(zf.read(BUILD_INFO_NAME).decode("utf-8"))
        except Exception as exc:
            raise ValueError(
                f"Ogiltig {BUILD_INFO_NAME} i release-paketet: {exc}"
            ) from exc
        if not isinstance(info, dict):
            raise ValueError(f"{BUILD_INFO_NAME} måste vara ett JSON-objekt")

        if expected_version and info.get("version") != expected_version:
            raise ValueError(
                f"Fel version i {BUILD_INFO_NAME}: "
                f"{info.get('version')!r} != {expected_version!r}"
            )
        if expected_sha and info.get("sha") != expected_sha:
            raise ValueError(
                f"Fel commit-SHA i {BUILD_INFO_NAME}: "
                f"{info.get('sha')!r} != {expected_sha!r}"
            )

        listed = set(info.get("files") or [])
        missing_in_zip = [rel for rel in RELEASE_FILES if rel not in names]
        if missing_in_zip:
            raise ValueError(
                "Filer saknas i release-zippen: " + ", ".join(missing_in_zip)
            )
        missing_in_manifest = [rel for rel in RELEASE_FILES if rel not in listed]
        if missing_in_manifest:
            raise ValueError(
                "Filer saknas i build_info.json: "
                + ", ".join(missing_in_manifest)
            )
        for rel in CRITICAL_FILES:
            if zf.getinfo(rel).file_size <= 0:
                raise ValueError(f"Kritisk fil är tom i paketet: {rel}")

        for starter in EXECUTABLE_STARTERS:
            unix_mode = zf.getinfo(starter).external_attr >> 16
            if unix_mode and not (unix_mode & 0o100):
                raise ValueError(
                    f"Exekverbart läge saknas på startfil: {starter}"
                )

        forbidden = [
            name
            for name in sorted(names)
            if name.startswith(FORBIDDEN_RELEASE_PREFIXES)
            or name in FORBIDDEN_RELEASE_FILES
        ]
        if forbidden:
            raise ValueError(
                "Otillåtna/privata filer hittades i paketet: "
                + ", ".join(forbidden)
            )

    return {
        "path": str(zip_path),
        "size": actual_size,
        "sha256": actual_sha256,
        "version": str(info.get("version", "")),
        "sha": str(info.get("sha", "")),
        "file_count": len(RELEASE_FILES),
    }


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
        description="Bygg eller verifiera Fakturabuntens release-zip."
    )
    parser.add_argument("--root", default=".",
                        help="approten (default: aktuell katalog)")
    parser.add_argument("--out", default="",
                        help="zip att skriva (default: InvoiceBundle-v<version>.zip)")
    parser.add_argument("--verify", default="",
                        help="verifiera befintlig release-zip utan att bygga ny")
    parser.add_argument("--expected-sha256", default="",
                        help="förväntad SHA-256-kontrollsumma vid --verify")
    parser.add_argument("--expected-size", type=int, default=None,
                        help="förväntad filstorlek i byte vid --verify")
    parser.add_argument("--version", default="1.0.0")
    parser.add_argument("--sha", default="",
                        help="commit-sha till build_info.json (default: git HEAD)")
    args = parser.parse_args(argv)

    if args.verify:
        try:
            report = verify_release_zip(
                Path(args.verify),
                expected_version=args.version,
                expected_sha=args.sha,
                expected_size=args.expected_size,
                expected_sha256=args.expected_sha256,
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"FEL: {exc}", file=sys.stderr)
            return 1
        print(
            f"Verifierade {report['path']} "
            f"({report['size']} bytes, sha256={report['sha256']}, "
            f"version={report['version']}, sha={report['sha']}, "
            f"{report['file_count']} filer OK)"
        )
        return 0

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
