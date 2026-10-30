# -*- coding: utf-8 -*-
"""
error_collect.py — EN fellogg som samlar alla fel för snabb felsökning.

logs/felsamling.log fylls på två sätt:

1. SPEGLING I REALTID — `install_error_mirror()` lägger en
   ERROR-handler på root-loggern. Varje fel (ERROR/CRITICAL, inkl.
   traceback) från VARJE modul i appen skrivs direkt hit, samtidigt
   som det hamnar i den stora logs/app.log. Installeras både av
   main.py:s tidiga loggning och av advanced_logger:s setup, så
   även startfel före plugin-laddningen fångas.

2. SKÖRD VID START/KNAPP — `collect_errors()` går igenom de andra
   loggarna (logs/app.log i JSONL-format, logs/autostart.log och
   startup_crash.log) och lägger hit fel som saknas. Exakta
   dubbletts-rader hoppas över, så samma fel aldrig står två gånger.

Filen trimmas till MAX_LINES rader (nyast behålls). Den heter
INTE errors.log — det namnet städar appen bort som legacy-filer
(EN-fil-principen för app.log gäller den stora loggen; felsamlingen
är ett eget, kuraterat utdrag).

Modulen är Qt-fri och får ALDRIG krascha appen — all felhantering
är defensiv.
"""
from __future__ import annotations

import datetime
import json
import logging
import traceback
from pathlib import Path
from typing import Any

log = logging.getLogger("invoice_bundle")

#: Den samlade felloggens filnamn i logs/.
ERROR_LOG_NAME = "felsamling.log"
#: Max antal felrader som behålls (nyast sist, äldst trimmar bort).
MAX_LINES = 5000

_ROOT = Path(__file__).resolve().parent.parent

_HEADER = (
    "# Fakturabunten — FELSAMLING: alla fel på ett ställe\n"
    "# för snabb felsökning.\n"
    "#\n"
    "# Fylls automatiskt på två sätt:\n"
    "#  1) fel speglas hit direkt när de inträffar i appen,\n"
    "#  2) vid varje start (och via knappen i Logg-fliken)\n"
    "#     samlas fel från logs/app.log, logs/autostart.log och\n"
    "#     startup_crash.log hit — utan dubletter.\n"
    "# Nyast längst ned. Filen trimmar sig själv.\n"
)

_ERROR_LEVELS = {"ERROR", "CRITICAL"}
_TRACEBACK_MARK = "Traceback (most recent call last)"
_LINE_MARKERS = (" ERROR ", " CRITICAL ", " ERROR:", "FEL:", "[ERROR]")


def error_log_path(root: Path | None = None) -> Path:
    """Sökvägen till felsamlingen under appens logs/-mapp."""
    return Path(root or _ROOT) / "logs" / ERROR_LOG_NAME


def _fmt(ts: str, level: str, logger: str, msg: str,
         loc: str = "") -> str:
    line = f"{ts} | {level} | {logger} | {msg}"
    if loc:
        line += f"  ({loc})"
    return line


class ErrorMirrorHandler(logging.Handler):
    """Speglar varje ERROR/CRITICAL-post direkt till felsamlingen."""

    def __init__(self, path: Path) -> None:
        super().__init__(level=logging.ERROR)
        self._path = Path(path)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            ts = datetime.datetime.fromtimestamp(
                record.created
            ).isoformat(timespec="seconds")
            lines = [
                _fmt(
                    ts, record.levelname, record.name,
                    record.getMessage(),
                    f"{record.module}:{record.lineno}",
                )
            ]
            if record.exc_info:
                exc = "".join(
                    traceback.format_exception(*record.exc_info)
                )
                lines.extend(
                    "    " + ln for ln in exc.rstrip().splitlines()
                )
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        except Exception:
            pass  # loggning får ALDRIG krascha appen


def install_error_mirror(root: Path | None = None) -> bool:
    """
    Lägger (en enda) ERROR-spegel på root-loggern.

    Idempotent: anropas av både den tidiga loggningen och av
    advanced_logger:s setup (som byter ut root-handlers) — spegeln
    läggs tillbaka om den tagits bort. True om spegeln är på plats.
    """
    try:
        path = error_log_path(root)
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            if isinstance(handler, ErrorMirrorHandler):
                return True
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(_HEADER, encoding="utf-8")
        root_logger.addHandler(ErrorMirrorHandler(path))
        return True
    except Exception as exc:  # pragma: no cover - defensiv
        log.debug("install_error_mirror: %s", exc)
        return False


# ── Skörd ur befintliga loggar ──────────────────────────────────────


def _scan_app_log(path: Path) -> list[str]:
    """Felrader ur app.log (JSONL): level ERROR/CRITICAL eller exc."""
    out: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw.startswith("{"):
            continue
        try:
            entry = json.loads(raw)
        except Exception:
            continue
        if not isinstance(entry, dict):
            continue
        level = str(entry.get("level", "") or "").upper()
        exc = str(entry.get("exc", "") or "")
        if level not in _ERROR_LEVELS and not exc:
            continue
        out.append(
            _fmt(
                str(entry.get("ts", "") or ""),
                level or "ERROR",
                str(entry.get("logger", "-") or "-"),
                str(entry.get("msg", "") or "")[:500],
                str(entry.get("loc", "") or ""),
            )
        )
        if exc:
            out.extend(
                "    " + ln for ln in exc.rstrip().splitlines()
            )
    return out


def _looks_like_exception_line(line: str) -> bool:
    """Sista raden i en traceback: 'ValueError: ...' o.dyl."""
    head = line.split(":", 1)[0].strip()
    return (
        head.replace(".", "").replace("_", "").isalnum()
        and (
            head.endswith(("Error", "Exception", "Exit",
                           "Interrupt", "Failure"))
            or head in ("SystemExit", "KeyboardInterrupt")
        )
    )


def _scan_text_log(path: Path, source: str) -> list[str]:
    """Fel + traceback-block ur en vanlig textlogg (autostart m.m.)."""
    out: list[str] = []
    try:
        lines = path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except OSError:
        return out
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if _TRACEBACK_MARK in line or any(
            m in line for m in _LINE_MARKERS
        ):
            out.append(f"[{source}] {line}")
            captured = 0
            j = i + 1
            while j < len(lines) and captured < 40:
                nxt = lines[j].rstrip()
                if (
                    nxt.startswith((" ", "\t"))
                    or nxt.startswith("File ")
                    or _looks_like_exception_line(nxt)
                ):
                    out.append(nxt)
                    captured += 1
                    j += 1
                    if _looks_like_exception_line(nxt):
                        break
                else:
                    break
            i = max(j, i + 1)
        else:
            i += 1
    return out


def _source_logs(root: Path) -> list[tuple[Path, str]]:
    """(fil, typ) för loggarna som skördas, i skördordning."""
    logs = root / "logs"
    return [
        (logs / "app.log", "jsonl"),
        (logs / "autostart.log", "text"),
        (root / "startup_crash.log", "text"),
        (logs / "startup_crash.log", "text"),
    ]


def collect_errors(root: Path | None = None) -> dict[str, Any]:
    """
    Samlar fel från alla loggar till logs/felsamling.log.

    Dubblett (exakt samma rad) läggs aldrig in två gånger —
    speglade fel som redan står i filen hoppas därför över när
    app.log skördas. Returnerar {added, total, file}.
    """
    root = Path(root or _ROOT)
    path = error_log_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: list[str] = []
        if path.exists():
            existing = [
                ln for ln in path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                if not ln.startswith("#")
            ]
        seen = set(existing)
        fresh: list[str] = []
        for src, kind in _source_logs(root):
            if not src.is_file():
                continue
            scanned = (
                _scan_app_log(src)
                if kind == "jsonl"
                else _scan_text_log(src, src.name)
            )
            for line in scanned:
                if line not in seen:
                    seen.add(line)
                    fresh.append(line)
        lines = existing + fresh
        if len(lines) > MAX_LINES:
            lines = lines[-MAX_LINES:]
        path.write_text(
            _HEADER + "\n".join(lines) + ("\n" if lines else ""),
            encoding="utf-8",
        )
        return {
            "added": len(fresh),
            "total": len(lines),
            "file": str(path),
        }
    except Exception as exc:
        log.warning("collect_errors: %s", exc)
        return {"added": 0, "total": 0, "file": str(path)}
