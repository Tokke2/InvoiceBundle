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
import re
import tempfile
import threading
import time
import traceback
from pathlib import Path
from typing import Any

log = logging.getLogger("invoice_bundle")

#: Den samlade felloggens filnamn i logs/.
ERROR_LOG_NAME = "felsamling.log"
ERROR_STATE_NAME = "felstatus.json"
ERROR_RESOLVED_ARCHIVE_NAME = "felsamling-atgardade.log"
AUTO_RESOLVE_AFTER = datetime.timedelta(days=3)
AUTO_CLEAN_GRACE = datetime.timedelta(hours=24)
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
    "# Nyast längst ned. Öppna fel markeras troligen åtgärdade efter 72 h\n"
    "# utan ny träff och kan rensas bort (manuellt eller automatiskt).\n"
    "# Fingeravtryck och status finns i logs/felstatus.json (kod FB-...).\n"
)

_ERROR_LEVELS = {"ERROR", "CRITICAL"}
_TRACEBACK_MARK = "Traceback (most recent call last)"
_LINE_MARKERS = (
    " ERROR ", " CRITICAL ", " ERROR:", " FAIL ", "FEL:", "[ERROR]"
)


#: Svansen "  (modul:rad)" som spegelns rader har.
_LOC_SUFFIX_RE = re.compile(r"\s+\([^()\s]+:\d+\)\s*$")


def error_log_path(root: Path | None = None) -> Path:
    """Sökvägen till felsamlingen under appens logs/-mapp."""
    return Path(root or _ROOT) / "logs" / ERROR_LOG_NAME


def error_state_path(root: Path | None = None) -> Path:
    """Sökvägen till statusregistret för öppna/autoåtgärdade fel."""
    return Path(root or _ROOT) / "logs" / ERROR_STATE_NAME


def resolved_error_log_path(root: Path | None = None) -> Path:
    """Sökvägen till arkivfilen för bortrensade åtgärdade fel."""
    return Path(root or _ROOT) / "logs" / "archive" / ERROR_RESOLVED_ARCHIVE_NAME


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
            state: dict[str, Any] = {"version": 1, "issues": issues}
            cleared_before = str(payload.get("cleared_before", "") or "")
            if cleared_before:
                state["cleared_before"] = cleared_before
            return state
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
        cleared_before_dt = _parse_timestamp(state.get("cleared_before"))
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
                if (
                    replay
                    and cleared_before_dt is not None
                    and stamp_dt <= cleared_before_dt
                ):
                    continue
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
            cleared_at = _parse_timestamp(issue.get("cleared_at"))
            cutoff_pts = [
                dt for dt in (last_seen, cleared_at, cleared_before_dt)
                if dt is not None
            ]
            if replay and cutoff_pts and stamp_dt <= max(cutoff_pts):
                if first_seen is None or stamp_dt < first_seen:
                    issue["first_seen"] = stamp
                    changed += 1
                continue

            status = str(issue.get("status", "open"))
            if status != "open":
                issue["status"] = "open"
                issue["reopen_count"] = int(issue.get("reopen_count", 0) or 0) + 1
                issue.pop("resolved_at", None)
                issue.pop("cleared_at", None)
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


def _dedupe_key(line: str) -> str:
    """Jämförelsenyckel för en felsamlingsrad.

    Samma fel kan komma från flera källor: spegelns rad har en
    ``(modul:rad)``-svans, skörden ur en textlogg har ``[källa]``-prefix
    och annan indentering. Utan normalisering blev det två kopior av
    samma händelse i felsamlingen.
    """
    body = str(line or "").strip()
    if body.startswith("[") and "] " in body:
        body = body.split("] ", 1)[1]
    body = _LOC_SUFFIX_RE.sub("", body)
    return " ".join(body.split())


#: Datum/tid i början av en skördad rad ("2026-11-11T14:09:39 ...").
_STAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]")


def _strip_source(line: str) -> str:
    """Ta bort källprefixet "[autostart.log] " som skörden sätter."""
    body = str(line or "")
    if body.startswith("[") and "] " in body:
        body = body.split("] ", 1)[1]
    return body


def _is_block_header(line: str) -> bool:
    """True för en felhuvudrad (inte en traceback-fortsättning)."""
    body = str(line or "")
    if not body:
        return False
    has_source = body.startswith("[") and "] " in body
    body = _strip_source(body)
    if not body or body[:1].isspace():
        return False
    # "RuntimeError: ..." i slutet av en traceback är ingen ny rubrik.
    return has_source or bool(_STAMP_RE.match(body))


def _iter_error_blocks(lines: list[str]):
    """Dela in skördade rader i (huvudnyckel, rader)-block.

    Ett traceback hör till sin huvudrad: blir huvudet en dubblett ska
    hela blocket hoppas över, annars blir det kvarhängande tracebacks
    i felsamlingen.
    """
    def finish(lines_in_block: list[str]) -> str:
        """Nyckel för blocket — traceback-rader känns igen på innehållet.

        En naken "Traceback ..."-rad utan tidsstämpel säger inget om
        vilket fel det gäller, så hela blocket hashas. Annars skulle
        två helt olika krascher räknas som samma dubblett.
        """
        first = _dedupe_key(lines_in_block[0])
        if _STAMP_RE.match(_strip_source(lines_in_block[0])):
            return first
        body = "\n".join(_dedupe_key(ln) for ln in lines_in_block)
        return first + "#" + hashlib.sha1(
            body.encode("utf-8", "replace")
        ).hexdigest()[:12]

    block: list[str] = []
    for line in lines:
        if _is_block_header(line):
            if block:
                yield finish(block), block
            block = [line]
        else:
            block.append(line)
    if block:
        yield finish(block), block


def _fmt(ts: str, level: str, logger: str, msg: str,
         loc: str = "") -> str:
    line = f"{ts} | {level} | {logger} | {msg}"
    if loc:
        line += f"  ({loc})"
    return line


class ErrorMirrorHandler(logging.Handler):
    """Speglar varje ERROR/CRITICAL-post direkt till felsamlingen."""

    #: Samma fel som upprepas inom den här tiden skrivs en gång —
    #: frekvensen finns ändå kvar i felstatus.json (occurrences).
    REPEAT_WINDOW_SECONDS = 300.0

    def __init__(self, path: Path) -> None:
        super().__init__(level=logging.ERROR)
        self._path = Path(path)
        self._last_written: dict[tuple[str, ...], float] = {}

    def emit(self, record: logging.LogRecord) -> None:
        try:
            exc_text = (
                "".join(traceback.format_exception(*record.exc_info))
                if record.exc_info else ""
            )
            signature = (
                str(record.levelname), str(record.name),
                record.getMessage(), exc_text[:2000],
            )
            now = time.monotonic()
            previous = self._last_written.get(signature)
            if (
                previous is not None
                and now - previous < self.REPEAT_WINDOW_SECONDS
            ):
                # Stormskydd: en felande hook som upprepas varje gång en
                # widget stängs får inte fylla hela felsamlingen.
                record_error_issue(
                    self._path.parent.parent,
                    level=record.levelname,
                    logger=record.name,
                    message=record.getMessage(),
                    location=f"{record.module}:{record.lineno}",
                    exception_type=(
                        type(record.exc_info[1]).__name__
                        if record.exc_info else ""
                    ),
                    traceback_text=exc_text,
                    timestamp=datetime.datetime.fromtimestamp(record.created),
                )
                return
            self._last_written[signature] = now
            if len(self._last_written) > 500:
                self._last_written.clear()
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
            if exc_text:
                lines.extend(
                    "    " + ln for ln in exc_text.rstrip().splitlines()
                )
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
            record_error_issue(
                self._path.parent.parent,
                level=record.levelname,
                logger=record.name,
                message=record.getMessage(),
                location=f"{record.module}:{record.lineno}",
                exception_type=(
                    type(record.exc_info[1]).__name__
                    if record.exc_info else ""
                ),
                traceback_text=exc_text,
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
                    or nxt.startswith(_TRACEBACK_MARK)
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


_CODE_RE = re.compile(r"\b(FB-[0-9A-F]{6,16})\b")


def _parse_block_fields(
    block: list[str],
) -> tuple[datetime.datetime | None, str, str, str, str]:
    """Extraherar (timestamp, level, logger, message, exception_type) ur ett block."""
    if not block:
        return None, "", "", "", ""
    head = _strip_source(block[0]).strip()
    head_clean = _LOC_SUFFIX_RE.sub("", head).strip()
    parts = [p.strip() for p in head_clean.split(" | ", 3)]
    stamp_dt = _parse_timestamp(parts[0]) if parts else None
    if stamp_dt is None and len(head_clean) >= 19:
        stamp_dt = _parse_timestamp(head_clean[:19])
    level = parts[1].upper() if len(parts) >= 2 else ""
    logger_name = parts[2] if len(parts) >= 3 else ""
    message = parts[3] if len(parts) >= 4 else ""
    if not message and len(parts) == 1 and stamp_dt is not None:
        message = head_clean[19:].strip()
    if not level and "CRITICAL" in head_clean.upper():
        level = "CRITICAL"
    elif not level and "ERROR" in head_clean.upper():
        level = "ERROR"
    exc_text = "\n".join(block[1:])
    exc_type = _exception_type(exc_text) or _exception_type(message)
    return stamp_dt, level, logger_name, message, exc_type


def _match_issue_for_block(
    block: list[str],
    issues: dict[str, Any],
) -> tuple[str | None, dict[str, Any] | None]:
    """Letar upp motsvarande issue-post i felstatus.json för ett block."""
    if not block or not issues:
        return None, None
    first = block[0]
    m_code = _CODE_RE.search(first)
    if m_code:
        code = m_code.group(1)
        for fp, issue in issues.items():
            if isinstance(issue, dict) and issue.get("code") == code:
                return fp, issue
        return code, None

    stamp_dt, level, logger_name, message, exc_type = _parse_block_fields(block)
    if level and message:
        fp_exact = _error_fingerprint(level, logger_name, message, exc_type)
        if fp_exact in issues and isinstance(issues[fp_exact], dict):
            return fp_exact, issues[fp_exact]
        fp_no_exc = _error_fingerprint(level, logger_name, message, "")
        if fp_no_exc in issues and isinstance(issues[fp_no_exc], dict):
            return fp_no_exc, issues[fp_no_exc]
        norm_msg = " ".join(message.lower().split())
        norm_logger = " ".join(logger_name.lower().split())
        for fp, issue in issues.items():
            if not isinstance(issue, dict):
                continue
            imsg = " ".join(str(issue.get("message", "")).lower().split())
            ilog = " ".join(str(issue.get("logger", "")).lower().split())
            if imsg and imsg == norm_msg and (not norm_logger or ilog == norm_logger):
                return fp, issue
    return None, None


def _block_already_cleared(
    block: list[str],
    state: dict[str, Any],
    *,
    source_mtime: datetime.datetime | None = None,
) -> bool:
    """True om ett skördat block hör till en redan rensad/åtgärdad tidpunkt."""
    issues = state.get("issues") or {}
    stamp_dt, _lvl, _log, _msg, _exc = _parse_block_fields(block)
    eff_dt = stamp_dt or source_mtime
    cleared_before_dt = _parse_timestamp(state.get("cleared_before"))
    if (
        cleared_before_dt is not None
        and eff_dt is not None
        and eff_dt <= cleared_before_dt
    ):
        return True
    _key, issue = _match_issue_for_block(block, issues)
    if not isinstance(issue, dict):
        return False
    status = str(issue.get("status", "open"))
    cleared_at = _parse_timestamp(issue.get("cleared_at"))
    resolved_at = _parse_timestamp(issue.get("resolved_at"))
    last_seen = _parse_timestamp(issue.get("last_seen"))
    if status == "resolved" or (status == "likely_resolved" and cleared_at is not None):
        bound = max(
            [dt for dt in (cleared_at, resolved_at, last_seen) if dt is not None],
            default=None,
        )
        if eff_dt is None or bound is None or eff_dt <= bound:
            return True
    return False


def collect_errors(
    root: Path | None = None,
    *,
    auto_clean: bool = False,
) -> dict[str, Any]:
    """
    Samlar fel från alla loggar till logs/felsamling.log.

    Dubblett (exakt samma rad) läggs aldrig in två gånger —
    speglade fel som redan står i filen hoppas därför över när
    app.log skördas. Redan åtgärdade/rensade poster återinförs inte
    från gamla arkiv om de inte inträffat på nytt efter rensningen.
    Returnerar {added, total, file}.
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
        with _STATE_LOCK:
            state = _load_error_state(root)
        seen: set[str] = set()
        for _key, block in _iter_error_blocks(existing):
            seen.add(_key)
        fresh: list[str] = []
        error_events: list[dict[str, Any]] = []
        for src, kind in _source_logs(root):
            if not src.is_file():
                continue
            try:
                src_mtime = datetime.datetime.fromtimestamp(src.stat().st_mtime)
            except OSError:
                src_mtime = None
            if kind == "jsonl":
                error_events.extend(_read_app_error_events(src))
                scanned = _scan_app_log(src)
            else:
                scanned = _scan_text_log(src, src.name)
                error_events.extend(
                    _events_from_text_scan(src, src.name, scanned)
                )
            for key, block in _iter_error_blocks(scanned):
                if not key or key in seen:
                    continue
                if _block_already_cleared(block, state, source_mtime=src_mtime):
                    continue
                seen.add(key)
                fresh.extend(block)
        lines = existing + fresh
        path.write_text(
            _HEADER + "\n".join(lines) + ("\n" if lines else ""),
            encoding="utf-8",
        )
        register_error_events(root, error_events, replay=True)
        resolve_stale_error_issues(root)
        if auto_clean:
            auto_clean_resolved_errors(root, enabled=True)
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


def error_summary(root: Path | None = None) -> dict[str, Any]:
    """Returnerar statusöversikt för feljournalen och logs/felsamling.log."""
    root = Path(root or _ROOT)
    with _STATE_LOCK:
        state = _load_error_state(root)
    issues = state.get("issues") or {}
    open_cnt = sum(
        1 for it in issues.values()
        if isinstance(it, dict) and it.get("status", "open") == "open"
    )
    likely_cnt = sum(
        1 for it in issues.values()
        if isinstance(it, dict) and it.get("status") == "likely_resolved"
    )
    resolved_cnt = sum(
        1 for it in issues.values()
        if isinstance(it, dict) and it.get("status") == "resolved"
    )
    path = error_log_path(root)
    log_blocks = 0
    if path.exists():
        try:
            lines = [
                ln for ln in path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                if ln.strip() and not ln.startswith("#")
            ]
            for _k, blk in _iter_error_blocks(lines):
                if blk and not _is_status_line(blk[0]):
                    log_blocks += 1
        except OSError:
            pass
    return {
        "open": open_cnt,
        "likely_resolved": likely_cnt,
        "resolved": resolved_cnt,
        "log_blocks": log_blocks,
        "cleared_before": str(state.get("cleared_before", "") or ""),
    }


def purge_resolved_errors(
    root: Path | None = None,
    *,
    include_likely_resolved: bool = True,
    include_open: bool = False,
    min_resolved_age: datetime.timedelta | None = None,
    archive_removed: bool = True,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Rensar bort åtgärdade fel från logs/felsamling.log och arkiverar dem.

    * `include_likely_resolved=True`: tar bort fel som redan markerats som
      troligen åtgärdade (72 h) eller manuellt markerats som åtgärdade, samt
      äldre daterade historikblock utan nya träffar.
    * `include_open=True`: markerar även alla nuvarande öppna fel som
      åtgärdade (resolved), rensar hela felloggen och sätter `cleared_before`
      så Logg-flikens varningsbanner börjar om rent från nu. Om ett fel
      sedan uppstår på nytt öppnas det automatiskt igen.
    """
    root = Path(root or _ROOT)
    now = now or datetime.datetime.now()
    now_iso = now.isoformat(timespec="seconds")
    resolve_stale_error_issues(root, now=now)

    path = error_log_path(root)
    archive_file = resolved_error_log_path(root)
    removed_lines: list[str] = []
    removed_blocks = 0
    removed_issues = 0

    with _STATE_LOCK:
        state = _load_error_state(root)
        issues: dict[str, Any] = state["issues"]

        if include_open:
            state["cleared_before"] = now_iso
            for issue in issues.values():
                if not isinstance(issue, dict):
                    continue
                if issue.get("status") != "resolved":
                    issue["status"] = "resolved"
                    issue.setdefault("resolved_at", now_iso)
                    issue["resolution_reason"] = (
                        issue.get("resolution_reason")
                        or "markerad som åtgärdad av användaren"
                    )
                    issue["cleared_at"] = now_iso
                    removed_issues += 1

        # Avgör vilka kända issues som ska få sina block rensade
        purge_fps: set[str] = set()
        purge_codes: set[str] = set()
        for fp, issue in issues.items():
            if not isinstance(issue, dict):
                continue
            status = str(issue.get("status", "open"))
            if status == "resolved":
                purge_fps.add(fp)
                if issue.get("code"):
                    purge_codes.add(str(issue["code"]))
                if not issue.get("cleared_at"):
                    issue["cleared_at"] = now_iso
            elif status == "likely_resolved" and include_likely_resolved:
                resolved_at = _parse_timestamp(issue.get("resolved_at")) or _parse_timestamp(issue.get("last_seen"))
                last_seen = _parse_timestamp(issue.get("last_seen"))
                silent_long_enough = (
                    min_resolved_age is None
                    or resolved_at is None
                    or (now - resolved_at) >= min_resolved_age
                    or (
                        last_seen is not None
                        and (now - last_seen) >= (AUTO_RESOLVE_AFTER + min_resolved_age)
                    )
                )
                if silent_long_enough:
                    purge_fps.add(fp)
                    if issue.get("code"):
                        purge_codes.add(str(issue["code"]))
                    issue["status"] = "resolved"
                    issue["cleared_at"] = now_iso
                    removed_issues += 1

        existing_lines: list[str] = []
        if path.exists():
            try:
                existing_lines = [
                    ln for ln in path.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()
                    if not ln.startswith("#")
                ]
            except OSError:
                existing_lines = []

        blocks = list(_iter_error_blocks(existing_lines))
        kept_lines: list[str] = []
        seen_kept: set[str] = set()
        stale_cutoff = now - (
            AUTO_RESOLVE_AFTER + (min_resolved_age or datetime.timedelta(0))
        )

        # Fånga även koder från ev. fristående "TROLIGEN ÅTGÄRDAT"-rader som uppfyller ålderskravet
        if include_likely_resolved:
            for _k, blk in blocks:
                if blk and _is_status_line(blk[0]) and "TROLIGEN ÅTGÄRDAT" in blk[0]:
                    st_dt = _parse_timestamp(blk[0][:19])
                    m_code = _CODE_RE.search(blk[0])
                    if m_code and st_dt is not None and (
                        min_resolved_age is None or (now - st_dt) >= min_resolved_age
                    ):
                        purge_codes.add(m_code.group(1))

        # Samla max-tidsstämpel per normaliserat blockmeddelande så ett äldre
        # meddelande utan felstatus.json-post inte rensas om samma fel just skett.
        latest_stamp_by_sig: dict[tuple[str, str], datetime.datetime] = {}
        for _k, blk in blocks:
            if not blk or _is_status_line(blk[0]):
                continue
            ts, lvl, log_name, msg, _exc = _parse_block_fields(blk)
            if ts is not None and msg:
                sig = (lvl, " ".join(msg.lower().split()))
                prev_ts = latest_stamp_by_sig.get(sig)
                if prev_ts is None or ts > prev_ts:
                    latest_stamp_by_sig[sig] = ts

        purged_fragments: list[str] = []
        for idx, (blk_key, blk) in enumerate(blocks):
            if not blk or not any(ln.strip() for ln in blk):
                continue
            first = blk[0]
            should_purge = False

            if _is_status_line(first):
                m_code = _CODE_RE.search(first)
                code = m_code.group(1) if m_code else ""
                if include_open or (code and code in purge_codes):
                    should_purge = True
                elif include_likely_resolved and "TROLIGEN ÅTGÄRDAT" in first:
                    st_dt = _parse_timestamp(first[:19])
                    if (
                        st_dt is not None
                        and (min_resolved_age is None or (now - st_dt) >= min_resolved_age)
                    ):
                        should_purge = True
                        if code:
                            purge_codes.add(code)
            else:
                fp, issue = _match_issue_for_block(blk, issues)
                if include_open:
                    should_purge = True
                    if isinstance(issue, dict) and fp not in purge_fps:
                        issue["status"] = "resolved"
                        issue["cleared_at"] = now_iso
                        removed_issues += 1
                elif fp in purge_fps or (
                    isinstance(issue, dict) and issue.get("status") == "resolved"
                ):
                    should_purge = True
                elif include_likely_resolved:
                    ts, lvl, log_name, msg, exc_type = _parse_block_fields(blk)
                    if ts is not None:
                        sig = (lvl, " ".join(msg.lower().split()))
                        latest_ts = latest_stamp_by_sig.get(sig, ts)
                        is_stale_untracked = (
                            issue is None
                            and latest_ts <= stale_cutoff
                        )
                        if is_stale_untracked:
                            should_purge = True
                            new_fp = _error_fingerprint(
                                lvl or "ERROR", log_name or "-", msg, exc_type
                            )
                            purge_fps.add(new_fp)
                            if new_fp not in issues:
                                issues[new_fp] = {
                                    "code": f"FB-{new_fp[:10]}",
                                    "fingerprint": new_fp,
                                    "status": "resolved",
                                    "level": lvl or "ERROR",
                                    "logger": log_name or "-",
                                    "message": msg[:500],
                                    "exception_type": exc_type,
                                    "location": "",
                                    "first_seen": ts.isoformat(timespec="seconds"),
                                    "last_seen": latest_ts.isoformat(timespec="seconds"),
                                    "occurrences": 1,
                                    "reopen_count": 0,
                                    "resolved_at": now_iso,
                                    "cleared_at": now_iso,
                                    "resolution_reason": "auto-rensad som åtgärdad",
                                }
                                removed_issues += 1

            # Om första raden före första daterade rubriken är ett löst traceback-fragment
            # som matchar något som nyss rensades (t.ex. avklippt Error-rad) -> rensa bort den.
            if (
                not should_purge
                and idx == 0
                and not _STAMP_RE.match(_strip_source(first))
                and not first.startswith("[")
                and (
                    include_open
                    or (
                        _looks_like_exception_line(_LOC_SUFFIX_RE.sub("", first).strip())
                        and _LOC_SUFFIX_RE.sub("", first).strip()
                    )
                )
            ):
                frag = _LOC_SUFFIX_RE.sub("", first).strip().lower()
                if include_open or any(frag in pf for pf in purged_fragments):
                    should_purge = True

            if should_purge:
                removed_lines.extend(blk)
                removed_blocks += 1
                purged_fragments.append(" ".join(first.lower().split()))
            else:
                if blk_key in seen_kept:
                    # Deduplicera eventuella gamla dubletter av kvarvarande fel
                    removed_lines.extend(blk)
                    removed_blocks += 1
                    continue
                seen_kept.add(blk_key)
                kept_lines.extend(blk)

        # Om föräldralösa inledande fragment-rader råkade ligga precis före rensade block:
        while (
            kept_lines
            and not _STAMP_RE.match(_strip_source(kept_lines[0]))
            and not kept_lines[0].startswith("[")
            and purged_fragments
        ):
            head_frag = _LOC_SUFFIX_RE.sub("", kept_lines[0]).strip().lower()
            if head_frag and any(head_frag in pf for pf in purged_fragments):
                removed_lines.append(kept_lines.pop(0))
                removed_blocks += 1
            else:
                break

        if removed_lines and archive_removed:
            try:
                archive_file.parent.mkdir(parents=True, exist_ok=True)
                stamp_hdr = f"\n# === Rensade som åtgärdade {now_iso} ===\n"
                with archive_file.open("a", encoding="utf-8") as afh:
                    afh.write(stamp_hdr + "\n".join(removed_lines) + "\n")
            except OSError:
                pass

        if removed_blocks > 0 or include_open or not path.exists():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                content = _HEADER + (
                    "\n".join(kept_lines) + "\n" if kept_lines else ""
                )
                path.write_text(content, encoding="utf-8")
            except OSError:
                pass

        if removed_issues > 0 or include_open or removed_blocks > 0:
            _save_error_state(root, state)

    remaining_blocks = sum(
        1 for _k, blk in _iter_error_blocks(kept_lines)
        if blk and not _is_status_line(blk[0])
    )
    return {
        "removed_blocks": removed_blocks,
        "removed_lines": len(removed_lines),
        "removed_issues": removed_issues,
        "remaining": remaining_blocks,
        "cleared_before": str(state.get("cleared_before", "") or ""),
        "archive_file": str(archive_file) if (removed_lines and archive_removed) else "",
        "file": str(path),
    }


def auto_clean_resolved_errors(
    root: Path | None = None,
    *,
    enabled: bool = True,
    grace_hours: int = 24,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Automatisk rensning av fel som markerats troligen åtgärdade (72 h + grace)."""
    root = Path(root or _ROOT)
    now = now or datetime.datetime.now()
    resolve_stale_error_issues(root, now=now)
    if not enabled:
        summary = error_summary(root)
        return {
            "removed_blocks": 0,
            "removed_lines": 0,
            "removed_issues": 0,
            "remaining": summary["log_blocks"],
            "cleared_before": summary["cleared_before"],
            "archive_file": "",
            "file": str(error_log_path(root)),
        }
    return purge_resolved_errors(
        root,
        include_likely_resolved=True,
        include_open=False,
        min_resolved_age=datetime.timedelta(hours=max(0, int(grace_hours))),
        archive_removed=True,
        now=now,
    )

