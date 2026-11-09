# -*- coding: utf-8 -*-
"""
error_collect.py — EN fellogg som samlar alla fel för snabb felsökning.
Författare : Rickard Längkvist
Copyright © dynamiskt år Rickard Längkvist

logs/felsamling.log fylls på två sätt:

1. SPEGLING I REALTID — `install_error_mirror()` lägger en
   ERROR-handler på root-loggern. Varje fel (ERROR/CRITICAL, inkl.
   traceback) från VARJE modul i appen skrivs direkt hit, samtidigt
   som det hamnar i den stora logs/app.log. Installeras både av
   main.py:s tidiga loggning och av advanced_logger:s setup, så
   även startfel före plugin-laddningen fångas.

2. SKÖRD VID START/KNAPP — `collect_errors()` går igenom de andra
   loggarna (dagens app.log/autostart.log, deras dagsarkiv och äldre
   startup_crash.log i approten eller logs/) och lägger hit fel som
   saknas. Exakta
   dubbletts-rader hoppas över, så samma fel aldrig står två gånger.

Felhistoriken i logs/felsamling.log arkiveras eller trimmas inte bort.
Ett separat logs/felstatus.json håller reda på samma fel över tid: efter
72 timmar utan ny träff markeras det som troligen åtgärdat, men historiken
finns kvar. Om felet återkommer öppnas det igen. Filen heter INTE
errors.log — det namnet städar appen bort som legacy-fil.

Modulen är Qt-fri och får ALDRIG krascha appen — all felhantering
är defensiv.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import tempfile
import threading
import traceback
from pathlib import Path
from typing import Any

log = logging.getLogger("invoice_bundle")

#: Den samlade felloggens filnamn i logs/.
ERROR_LOG_NAME = "felsamling.log"
ERROR_STATE_NAME = "felstatus.json"
AUTO_RESOLVE_AFTER = datetime.timedelta(days=3)
_STATE_LOCK = threading.RLock()
_ROOT = Path(__file__).resolve().parent.parent

_HEADER = (
    "# Fakturabunten — FELSAMLING: alla fel på ett ställe\n"
    "# för snabb felsökning.\n"
    "#\n"
    "# Fylls automatiskt på två sätt:\n"
    "#  1) fel speglas hit direkt när de inträffar i appen,\n"
    "#  2) vid varje start (och via knappen i Logg-fliken)\n"
    "#     samlas fel från dagens loggar, dagsarkiv och äldre\n"
    "#     startup_crash.log — utan dubletter.\n"
    "# Nyast längst ned. Historiken roteras/rensas inte automatiskt.\n"
    "# Öppna fel markeras troligen åtgärdade efter 72 h utan ny träff.\n"
    "# Fingeravtryck och status finns i logs/felstatus.json (kod FB-...).\n"
)

_ERROR_LEVELS = {"ERROR", "CRITICAL"}
_TRACEBACK_MARK = "Traceback (most recent call last)"
_LINE_MARKERS = (
    " ERROR ", " CRITICAL ", " ERROR:", " FAIL ", "FEL:", "[ERROR]"
)


def error_log_path(root: Path | None = None) -> Path:
    """Sökvägen till felsamlingen under appens logs/-mapp."""
    return Path(root or _ROOT) / "logs" / ERROR_LOG_NAME


def error_state_path(root: Path | None = None) -> Path:
    """Sökvägen till statusregistret för öppna/autoåtgärdade fel."""
    return Path(root or _ROOT) / "logs" / ERROR_STATE_NAME


def _parse_timestamp(value: Any) -> datetime.datetime | None:
    try:
        result = datetime.datetime.fromisoformat(
            str(value or "").strip().replace("Z", "+00:00")
        )
        if result.tzinfo is not None:
            result = result.astimezone().replace(tzinfo=None)
        return result
    except (TypeError, ValueError):
        return None


def _load_error_state(root: Path) -> dict[str, Any]:
    path = error_state_path(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        issues = payload.get("issues") if isinstance(payload, dict) else None
        if isinstance(issues, dict):
            return {"version": 1, "issues": issues}
    except (OSError, ValueError, TypeError):
        pass
    return {"version": 1, "issues": {}}


def _save_error_state(root: Path, payload: dict[str, Any]) -> None:
    path = error_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=".felstatus.",
            suffix=".tmp", dir=path.parent, delete=False,
        ) as handle:
            temp = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except Exception:
        if temp is not None:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _exception_type(text: str) -> str:
    for line in reversed(str(text or "").splitlines()):
        head = line.strip().split(":", 1)[0].rsplit(".", 1)[-1]
        if head.endswith(("Error", "Exception", "Failure")):
            return head
    return ""


def _error_fingerprint(
    level: str, logger: str, message: str, exception_type: str,
) -> str:
    parts = (
        " ".join(str(level).upper().split()),
        " ".join(str(logger).strip().lower().split()),
        " ".join(str(message).strip().lower().split()),
        " ".join(str(exception_type).strip().lower().split()),
    )
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16].upper()


def _is_status_line(line: str) -> bool:
    return any(marker in line for marker in (
        " | ÖPPNAT | ", " | ÅTERÖPPNAT | ",
        " | TROLIGEN ÅTGÄRDAT ",
    ))


def _append_status_lines(root: Path, lines: list[str]) -> None:
    if not lines:
        return
    path = error_log_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(_HEADER, encoding="utf-8")
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError:
        pass


def register_error_events(
    root: Path,
    events: list[dict[str, Any]],
    *,
    replay: bool = False,
) -> int:
    """Upsert errors into the persistent status ledger.

    Archived log entries are replayed idempotently; live handler events can
    reopen an automatically resolved fingerprint immediately.
    """
    root = Path(root)
    now = datetime.datetime.now()
    transitions: list[str] = []
    changed = 0
    with _STATE_LOCK:
        state = _load_error_state(root)
        issues: dict[str, Any] = state["issues"]
        for event in events:
            level = str(event.get("level", "ERROR") or "ERROR").upper()
            logger_name = str(event.get("logger", "-") or "-")
            message = str(event.get("message", event.get("msg", "")) or "")[:500]
            exc_text = str(
                event.get("traceback", event.get("exc", "")) or ""
            )[:12000]
            exc_type = str(
                event.get("exception_type", "") or _exception_type(exc_text)
            )
            stamp_dt = _parse_timestamp(event.get("timestamp", event.get("ts"))) or now
            stamp = stamp_dt.isoformat(timespec="seconds")
            fingerprint = _error_fingerprint(
                level, logger_name, message, exc_type
            )
            code = f"FB-{fingerprint[:10]}"
            loc = str(event.get("location", event.get("loc", "")) or "")[:300]
            issue = issues.get(fingerprint)
            if not isinstance(issue, dict):
                issue = {
                    "code": code,
                    "fingerprint": fingerprint,
                    "status": "open",
                    "level": level,
                    "logger": logger_name,
                    "message": message,
                    "exception_type": exc_type,
                    "location": loc,
                    "first_seen": stamp,
                    "last_seen": stamp,
                    "occurrences": 1,
                    "reopen_count": 0,
                    "traceback": exc_text,
                }
                issues[fingerprint] = issue
                transitions.append(
                    f"{stamp} | ÖPPNAT | {code} | {logger_name}"
                )
                changed += 1
                continue

            last_seen = _parse_timestamp(issue.get("last_seen"))
            first_seen = _parse_timestamp(issue.get("first_seen"))
            if replay and last_seen is not None and stamp_dt <= last_seen:
                if first_seen is None or stamp_dt < first_seen:
                    issue["first_seen"] = stamp
                    changed += 1
                continue

            status = str(issue.get("status", "open"))
            if status != "open":
                issue["status"] = "open"
                issue["reopen_count"] = int(issue.get("reopen_count", 0) or 0) + 1
                issue.pop("resolved_at", None)
                issue.pop("resolution_reason", None)
                transitions.append(
                    f"{stamp} | ÅTERÖPPNAT | {code} | {logger_name}"
                )
            issue["last_seen"] = stamp
            if first_seen is None or stamp_dt < first_seen:
                issue["first_seen"] = stamp
            issue["occurrences"] = int(issue.get("occurrences", 0) or 0) + 1
            issue["level"] = level
            issue["logger"] = logger_name
            issue["message"] = message
            issue["exception_type"] = exc_type
            issue["location"] = loc
            if exc_text:
                issue["traceback"] = exc_text
            changed += 1

        if changed:
            _save_error_state(root, state)
            _append_status_lines(root, transitions)
    return changed


def record_error_issue(
    root: Path,
    *,
    level: str,
    logger: str,
    message: str,
    location: str = "",
    exception_type: str = "",
    traceback_text: str = "",
    timestamp: datetime.datetime | str | None = None,
) -> None:
    stamp = timestamp or datetime.datetime.now()
    register_error_events(
        Path(root),
        [{
            "timestamp": stamp.isoformat(timespec="seconds")
            if isinstance(stamp, datetime.datetime) else str(stamp),
            "level": level, "logger": logger, "message": message,
            "location": location, "exception_type": exception_type,
            "traceback": traceback_text,
        }],
    )
    resolve_stale_error_issues(Path(root))


def resolve_stale_error_issues(
    root: Path,
    now: datetime.datetime | None = None,
) -> int:
    """Mark errors as likely fixed after 72 hours with no recurrence.

    The raw error history is retained in felsamling.log; only the current
    status changes. A later occurrence reopens the same fingerprint.
    """
    root = Path(root)
    now = now or datetime.datetime.now()
    cutoff = now - AUTO_RESOLVE_AFTER
    transitions: list[str] = []
    with _STATE_LOCK:
        state = _load_error_state(root)
        for issue in state["issues"].values():
            if not isinstance(issue, dict) or issue.get("status") != "open":
                continue
            last_seen = _parse_timestamp(issue.get("last_seen"))
            if last_seen is None or last_seen > cutoff:
                continue
            issue["status"] = "likely_resolved"
            issue["resolved_at"] = now.isoformat(timespec="seconds")
            issue["resolution_reason"] = "ingen ny träff på 72 timmar"
            transitions.append(
                f"{now.isoformat(timespec='seconds')} | TROLIGEN ÅTGÄRDAT "
                f"(72 h utan ny träff) | {issue.get('code', '')} | "
                f"{issue.get('logger', '-')}"
            )
        if transitions:
            _save_error_state(root, state)
            _append_status_lines(root, transitions)
    return len(transitions)


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
            exception_type = (
                type(record.exc_info[1]).__name__ if record.exc_info else ""
            )
            exc = "".join(
                traceback.format_exception(*record.exc_info)
            ) if record.exc_info else ""
            record_error_issue(
                self._path.parent.parent,
                level=record.levelname,
                logger=record.name,
                message=record.getMessage(),
                location=f"{record.module}:{record.lineno}",
                exception_type=exception_type,
                traceback_text=exc,
                timestamp=datetime.datetime.fromtimestamp(record.created),
            )
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


def _read_app_error_events(path: Path) -> list[dict[str, Any]]:
    """Structured ERROR/CRITICAL events from one JSONL app log."""
    events: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return events
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
        events.append({
            "timestamp": str(entry.get("ts", "") or ""),
            "level": level or "ERROR",
            "logger": str(entry.get("logger", "-") or "-"),
            "message": str(entry.get("msg", "") or "")[:500],
            "location": str(entry.get("loc", "") or ""),
            "traceback": exc,
        })
    return events


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


def _events_from_text_scan(
    path: Path, source: str, scanned: list[str],
) -> list[dict[str, Any]]:
    """Recover dated issue events from autostart/crash text logs."""
    try:
        fallback_stamp = datetime.datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        fallback_stamp = datetime.datetime.now()
    events: list[dict[str, Any]] = []
    for raw in scanned:
        if raw[:1].isspace():
            continue  # traceback continuation belongs to the prior event
        body = raw
        if body.startswith("[") and "] " in body:
            body = body.split("] ", 1)[1]
        stamp = fallback_stamp
        message = body
        if len(body) >= 19:
            parsed = _parse_timestamp(body[:19])
            if parsed is not None:
                stamp = parsed
                message = body[19:].strip()
        if not message:
            message = body[:500]
        level = "CRITICAL" if "CRITICAL" in body.upper() else "ERROR"
        lower_source = source.lower()
        logger_name = (
            "Autostart" if lower_source.startswith("autostart")
            else "StartupCrash" if "startup_crash" in lower_source
            else source
        )
        events.append({
            "timestamp": stamp.isoformat(timespec="seconds"),
            "level": level,
            "logger": logger_name,
            "message": message[:500],
            "location": source,
        })
    return events


def _source_logs(root: Path) -> list[tuple[Path, str]]:
    """(fil, typ) för loggarna som skördas, i skördordning."""
    logs = root / "logs"
    archive = logs / "archive"
    sources = [
        (logs / "app.log", "jsonl"),
        (logs / "autostart.log", "text"),
        (root / "startup_crash.log", "text"),
        (logs / "startup_crash.log", "text"),
    ]
    sources.extend((path, "jsonl") for path in sorted(
        archive.glob("app-*.jsonl")
    ))
    sources.extend((path, "text") for path in sorted(
        archive.glob("autostart-*.log")
    ))
    return sources


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
        error_events: list[dict[str, Any]] = []
        for src, kind in _source_logs(root):
            if not src.is_file():
                continue
            if kind == "jsonl":
                error_events.extend(_read_app_error_events(src))
                scanned = _scan_app_log(src)
            else:
                scanned = _scan_text_log(src, src.name)
                error_events.extend(
                    _events_from_text_scan(src, src.name, scanned)
                )
            for line in scanned:
                if line not in seen:
                    seen.add(line)
                    fresh.append(line)
        lines = existing + fresh
        path.write_text(
            _HEADER + "\n".join(lines) + ("\n" if lines else ""),
            encoding="utf-8",
        )
        register_error_events(root, error_events, replay=True)
        resolve_stale_error_issues(root)
        try:
            final_lines = path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
            total = sum(
                1 for line in final_lines
                if line and not line.startswith("#") and not _is_status_line(line)
            )
        except OSError:
            total = len(lines)
        return {
            "added": len(fresh),
            "total": total,
            "file": str(path),
        }
    except Exception as exc:
        log.warning("collect_errors: %s", exc)
        return {"added": 0, "total": 0, "file": str(path)}
