from __future__ import annotations

"""
Fakturabunten — Advanced Logging Plugin
===============================================
Fil    : Fakturabunten_/plugins/advanced_logger.py
Författare : Rickard Längkvist
År     : Dynamiskt (auto)

ENDA LOGGFILEN: logs/app.log (JSONL — en JSON-rad per händelse).

Designmål
─────────
• EN loggfil, inget annat. Ingen rotation till .1/.2, inget archive/,
  ingen errors/audit/perf/structured-split.
• Loggar PRECIS ALLT: start/stopp, lås, tema, flikbyten, fönster
  visas/döljs, tray-klick, CRUD, settings, export, session-datum,
  fel + tracebacks.
• 100 % AI-chatt-förståeligt: varje rad är ett JSON-objekt med fast
  schema — ts/level/logger/action/msg/loc/thread + ctx{} + exc.
  En AI (eller människa) ser direkt vad som hänt och vad som är fel.
• Köbaserad skrivning (QueueHandler + QueueListener) — UI-tråden
  blockerar aldrig på disk.
• Filen trimmas vid 25 MB → senaste 5 MB behålls (fortfarande 1 fil).
• UI-panel (LoggerView) i Inställningar-fliken: live-logg, filter,
  sök, export, systeminfo.

Schema per rad (exempel)
────────────────────────
{"ts":"2026-09-23T09:30:32","level":"INFO","logger":"FakturaMain",
 "action":"START","msg":"Programmet startar",
 "loc":"main:123","thread":"MainThread",
 "ctx":{"platform":"windows","version":"1.4.0"}}

Copyright © dynamiskt år Rickard Längkvist
"""

import atexit
import datetime
import json
import logging
import logging.handlers
import os
import platform
import queue
import sys
import threading
import traceback
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QFrame,
    QFileDialog, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QGroupBox, QLineEdit, QCheckBox,
)
from PySide6.QtCore import Qt, QTimer, QEvent, QObject
from PySide6.QtGui import QFont, QColor, QBrush, QWheelEvent

# ═════════════════════════════════════════════════════════════════════
#  KONSTANTER
# ═════════════════════════════════════════════════════════════════════

COPYRIGHT_YEAR: int = datetime.date.today().year

BASE_DIR: Path = Path(__file__).parent.parent.resolve()
LOG_DIR: Path = BASE_DIR / "logs"

#: ENDA loggfilen.
LOG_FILE: Path = LOG_DIR / "app.log"

#: Vid denna storlek trimmas filen till KEEP_BYTES (fortfarande 1 fil).
MAX_LOG_BYTES: int = 25 * 1024 * 1024
KEEP_BYTES: int = 5 * 1024 * 1024

UI_MAX_ROWS: int = 500

# Egna loggnivåer (finns kvar för bakåtkompatibla anrop)
AUDIT_LEVEL: int = 25
PERF_LEVEL: int = 15

#: TRACE (idén från PDF reader Pro SPEC v2.1 §2.4): finaste nivån för
#: UI-händelser via Qt-bryggan i main.py — klick, tangenter, fokus.
#: Ligger UNDER DEBUG så att den kan filtreras bort helt vid behov.
TRACE_LEVEL: int = 5

logging.addLevelName(AUDIT_LEVEL, "AUDIT")
logging.addLevelName(PERF_LEVEL, "PERF")
logging.addLevelName(TRACE_LEVEL, "TRACE")


def _audit(self: logging.Logger, message: str, *args: Any, **kwargs: Any) -> None:
    if self.isEnabledFor(AUDIT_LEVEL):
        self._log(AUDIT_LEVEL, message, args, **kwargs)


def _perf(self: logging.Logger, message: str, *args: Any, **kwargs: Any) -> None:
    if self.isEnabledFor(PERF_LEVEL):
        self._log(PERF_LEVEL, message, args, **kwargs)


def _trace(self: logging.Logger, message: str, *args: Any, **kwargs: Any) -> None:
    if self.isEnabledFor(TRACE_LEVEL):
        self._log(TRACE_LEVEL, message, args, **kwargs)


logging.Logger.audit = _audit  # type: ignore[attr-defined]
logging.Logger.perf = _perf    # type: ignore[attr-defined]
logging.Logger.trace = _trace  # type: ignore[attr-defined]


# ═════════════════════════════════════════════════════════════════════
#  JSONL-POSTER (AI-förståeligt schema)
# ═════════════════════════════════════════════════════════════════════


def _record_to_entry(record: logging.LogRecord) -> dict[str, Any]:
    """Bygger en JSON-post med fast, AI-vänligt schema."""
    entry: dict[str, Any] = {
        "ts": datetime.datetime.fromtimestamp(record.created).isoformat(
            timespec="seconds"
        ),
        "level": record.levelname,
        "logger": record.name,
        "action": getattr(record, "action", None) or record.levelname,
        "msg": record.getMessage(),
        "loc": f"{record.module}:{record.lineno}",
        "thread": record.threadName,
    }
    ctx = {
        k[4:]: v
        for k, v in record.__dict__.items()
        if k.startswith("ctx_")
    }
    if ctx:
        entry["ctx"] = ctx
    if record.exc_info:
        entry["exc"] = "".join(
            traceback.format_exception(*record.exc_info)
        )
    return entry


def alog(
    action: str,
    msg: str,
    level: int = logging.INFO,
    logger: str = "App",
    **ctx: Any,
) -> None:
    """
    Strukturerad loggning: action-tagg + fritext + nyckelvärden.

    alog("EXPORT", "PDF exporterad", rader=3, netto=5750.0)
    → rad med action=EXPORT och ctx={"rader":3,"netto":5750.0}
    """
    try:
        extra = {"action": action}
        for k, v in ctx.items():
            extra[f"ctx_{k}"] = v
        logging.getLogger(logger).log(level, msg, extra=extra)
    except Exception:
        pass  # loggning får ALDRIG krascha appen


# ═════════════════════════════════════════════════════════════════════
#  HANDLERS
# ═════════════════════════════════════════════════════════════════════


class SingleFileJsonlHandler(logging.Handler):
    """
    Skriver ALLA loggposter som JSON-rader till EN fil: logs/app.log.

    Trimmad vid 25 MB (senaste 5 MB behålls) — alltid exakt 1 fil.
    """

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = json.dumps(
                _record_to_entry(record), ensure_ascii=False
            )
            with self._lock:
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                if self._path.stat().st_size > MAX_LOG_BYTES:
                    self._trim()
        except Exception:
            self.handleError(record)

    def _trim(self) -> None:
        """Behåller senaste KEEP_BYTES — filen förblir EN fil."""
        try:
            data = self._path.read_bytes()
            tail = data[-KEEP_BYTES:]
            nl = tail.find(b"\n")
            if nl != -1:
                tail = tail[nl + 1:]
            self._path.write_bytes(tail)
        except OSError:
            pass


class MemoryHandler(logging.Handler):
    """Håller senaste N poster i minnet för UI-panelen (med cache)."""

    def __init__(self, capacity: int = 2000) -> None:
        super().__init__()
        self._capacity = capacity
        self._records: list[logging.LogRecord] = []
        self._lock = threading.Lock()
        self._seq = 0
        self._cache_key: tuple | None = None
        self._cache: list[logging.LogRecord] = []
        self.new_record_callback = None

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock:
            self._records.append(record)
            if len(self._records) > self._capacity:
                self._records.pop(0)
            self._seq += 1
        if self.new_record_callback:
            try:
                self.new_record_callback(record)
            except Exception:
                pass

    def get_records(
        self, level_name: str = "ALL", search: str = ""
    ) -> list[logging.LogRecord]:
        key = (level_name, search, self._seq)
        if key == self._cache_key:
            return self._cache
        with self._lock:
            records = list(self._records)
        if level_name != "ALL":
            level_map = {
                "AUDIT": AUDIT_LEVEL,
                "PERF": PERF_LEVEL,
                "TRACE": TRACE_LEVEL,
            }
            lvl = level_map.get(
                level_name, getattr(logging, level_name, logging.DEBUG)
            )
            records = [r for r in records if r.levelno >= lvl]
        if search:
            s = search.lower()
            records = [
                r for r in records
                if s in r.getMessage().lower() or s in r.name.lower()
            ]
        self._cache_key = key
        self._cache = records
        return records

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._seq += 1


# ═════════════════════════════════════════════════════════════════════
#  GLOBAL SETUP — EN fil, köbaserad, DEBUG-nivå (allt loggas)
# ═════════════════════════════════════════════════════════════════════

_memory_handler: MemoryHandler | None = None
_logger_ready: bool = False
_log_queue: "queue.Queue[Any] | None" = None
_listener: logging.handlers.QueueListener | None = None


def shutdown_logging() -> None:
    """Stoppar QueueListener ordnat (även via atexit)."""
    global _listener
    if _listener is not None:
        try:
            _listener.stop()
        except Exception:
            pass
        _listener = None


def setup_logging(trace_on: bool = True) -> MemoryHandler:
    """
    Sätter upp hela loggningen:

    • logs/app.log (JSONL, EN fil) bakom QueueListener i egen tråd
    • MemoryHandler direkt på root (UI-panel, omedelbar)
    • Konsol endast om en terminal finns
    • Nivå: TRACE (5) som standard — PRECIS ALLT loggas, inklusive
      varje musklick/tangenttryck via Qt-bryggan. Kan slås av med
      settings.json → "log_trace": false (eller kryssrutan i
      Inställningar-menyn), då gäller DEBUG.
    """
    global _memory_handler, _logger_ready, _log_queue, _listener

    if _logger_ready and _memory_handler:
        return _memory_handler

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(TRACE_LEVEL if trace_on else logging.DEBUG)

    # Byt ut tidigare handlers (main.py:s tidiga) — ingen dubblering.
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass

    file_handlers: list[logging.Handler] = [
        SingleFileJsonlHandler(LOG_FILE)
    ]

    _log_queue = queue.Queue(-1)
    _listener = logging.handlers.QueueListener(
        _log_queue, *file_handlers
    )
    _listener.start()
    atexit.register(shutdown_logging)
    root.addHandler(logging.handlers.QueueHandler(_log_queue))

    # Konsol (bara om terminal finns)
    try:
        if sys.stdout and sys.stdout.fileno() >= 0:
            ch = logging.StreamHandler(sys.stdout)
            ch.setLevel(logging.DEBUG)
            ch.setFormatter(
                logging.Formatter(
                    "%(asctime)s  %(levelname)-8s  %(name)s  →  %(message)s",
                    datefmt="%H:%M:%S",
                )
            )
            root.addHandler(ch)
    except Exception:
        pass

    _memory_handler = MemoryHandler(capacity=2000)
    # Samma nivå som root — då kan loggpanelen visa ÄVEN TRACE-rader
    # (varje klick/tangent) när nivån TRACE väljs i filtret.
    _memory_handler.setLevel(
        TRACE_LEVEL if trace_on else logging.DEBUG
    )
    root.addHandler(_memory_handler)

    _logger_ready = True
    set_trace_enabled(trace_on, log_change=False)

    alog(
        "SESSION_START",
        "Ny loggsession — en fil, JSONL, PRECIS ALLT loggas",
        logger="AdvancedLogger",
        version=os.environ.get("FBP_VERSION", ""),
        platform=platform.system(),
        python=sys.version.split()[0],
        pid=os.getpid(),
        cwd=str(Path.cwd()),
        exe=sys.executable,
        log_file=str(LOG_FILE),
        argv=sys.argv[:],
        autostart="--minimized" in sys.argv,
        selftest="--selftest" in sys.argv,
        debug="--debug" in sys.argv,
        trace=bool(trace_on),
    )
    return _memory_handler


#: Aktuell TRACE-status (modulnivå) — så att upprepade anrop till
#: set_trace_enabled() inte loggar/spammar i onödan.
_trace_state: bool | None = None


def set_trace_enabled(on: bool, log_change: bool = True) -> None:
    """
    Slår TRACE-loggning (varje klick/tangenttryck) PÅ/AV live.

    Anropas vid start (settings: log_trace) och varje gång användaren
    ändrar kryssrutan i Inställningar-menyn — nivåbytet sker direkt,
    ingen omstart krävs.
    """
    global _trace_state
    on = bool(on)
    if _trace_state == on:
        return
    _trace_state = on
    level = TRACE_LEVEL if on else logging.DEBUG
    root = logging.getLogger()
    root.setLevel(level)
    if _memory_handler is not None:
        _memory_handler.setLevel(level)
    if log_change:
        alog(
            "TRACE_TOGGLE",
            f"TRACE-loggning (varje tryck) → {'PÅ' if on else 'AV'}",
            logger="AdvancedLogger",
            enabled=on,
            root_level=logging.getLevelName(root.level),
        )


# ═════════════════════════════════════════════════════════════════════
#  UNDANTAGSHOOKS — allt som kraschar loggas med traceback
# ═════════════════════════════════════════════════════════════════════


def install_exception_hook() -> None:
    """Fångar oupptäckta Python-undantag och trådfel."""
    log = logging.getLogger("UncaughtException")
    original = sys.excepthook

    def hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            original(exc_type, exc_value, exc_tb)
            return
        log.critical(
            "UNCAUGHT EXCEPTION: %s: %s",
            exc_type.__name__, exc_value,
            exc_info=(exc_type, exc_value, exc_tb),
            extra={"action": "CRASH"},
        )

    sys.excepthook = hook

    def thread_hook(args):
        log.critical(
            "UNCAUGHT THREAD EXCEPTION in '%s': %s",
            args.thread.name if args.thread else "unknown",
            args.exc_value,
            exc_info=(args.exc_type, args.exc_value, args.exc_tb),
            extra={"action": "CRASH_THREAD"},
        )

    threading.excepthook = thread_hook
    log.debug("Exception hooks installed")


def install_qt_message_hook() -> None:
    """Fångar Qt-varningar/fel via qInstallMessageHandler."""
    from PySide6.QtCore import qInstallMessageHandler, QtMsgType

    log = logging.getLogger("Qt")

    def qt_handler(msg_type, context, message):
        loc = f" [{context.file}:{context.line}]" if context.file else ""
        if msg_type == QtMsgType.QtDebugMsg:
            log.debug("Qt DEBUG%s: %s", loc, message,
                      extra={"action": "QT_DEBUG"})
        elif msg_type == QtMsgType.QtInfoMsg:
            log.info("Qt INFO%s: %s", loc, message,
                     extra={"action": "QT_INFO"})
        elif msg_type == QtMsgType.QtWarningMsg:
            log.warning("Qt WARNING%s: %s", loc, message,
                        extra={"action": "QT_WARNING"})
        elif msg_type == QtMsgType.QtCriticalMsg:
            log.error("Qt CRITICAL%s: %s", loc, message,
                      extra={"action": "QT_CRITICAL"})
        elif msg_type == QtMsgType.QtFatalMsg:
            log.critical("Qt FATAL%s: %s", loc, message,
                         extra={"action": "QT_FATAL"})

    qInstallMessageHandler(qt_handler)
    log.debug("Qt message handler installed")


# ═════════════════════════════════════════════════════════════════════
#  FÖNSTER-SPY — loggar VISAS/DÖLJS/minimera/aktivera (blink-diagnos)
# ═════════════════════════════════════════════════════════════════════

_window_spy: QObject | None = None


class _WindowSpy(QObject):
    """
    Eventfilter som loggar alla fönsterhändelser (SHOW/HIDE m.m.).

    Qt 6 saknar QEvent.Type.Minimize — minimering/maximering kommer
    som WindowStateChange och känns igen via isMinimized()/
    isMaximized(). Allt ligger i try/except: loggning får ALDRIG
    krascha event-hanteringen.
    """

    def eventFilter(self, obj: Any, event: Any) -> bool:
        try:
            t = event.type()
            if t == QEvent.Type.Show:
                alog("WINDOW_SHOW", "Fönstret visas", logger="WindowSpy")
            elif t == QEvent.Type.Hide:
                alog("WINDOW_HIDE", "Fönstret döljs", logger="WindowSpy")
            elif t == QEvent.Type.WindowActivate:
                alog("WINDOW_ACTIVATE", "Fönstret aktiveras",
                     logger="WindowSpy")
            elif t == QEvent.Type.WindowDeactivate:
                alog("WINDOW_DEACTIVATE", "Fönstret förlorar fokus",
                     level=TRACE_LEVEL, logger="WindowSpy")
            elif t == QEvent.Type.WindowStateChange:
                try:
                    if obj.isMinimized():
                        alog("WINDOW_MINIMIZE", "Fönstret minimeras",
                             logger="WindowSpy")
                    elif obj.isMaximized():
                        alog("WINDOW_MAXIMIZE", "Fönstret maximeras",
                             logger="WindowSpy")
                    elif obj.isFullScreen():
                        alog("WINDOW_FULLSCREEN", "Helskärmsläge",
                             logger="WindowSpy")
                    else:
                        alog("WINDOW_RESTORE",
                             "Fönstret återställt (normalläge)",
                             level=TRACE_LEVEL, logger="WindowSpy")
                except Exception:
                    pass
            elif t == QEvent.Type.Close:
                alog("WINDOW_CLOSE", "Close-event på fönstret",
                     logger="WindowSpy")
        except Exception:
            pass
        return False


# ═════════════════════════════════════════════════════════════════════
#  SESSION-DATUM + APP-WATCHERS (allt som sker → logg)
# ═════════════════════════════════════════════════════════════════════


def log_session_due_date(app: Any) -> None:
    """Loggar session-betalningsdatum + konsistenskontroll."""
    log = logging.getLogger("SessionDueDate")
    try:
        session_due = getattr(app, "session_due_date", None)
        has_due = getattr(app, "has_session_due_date", False)

        if session_due is not None:
            alog("SESSION_DUE", f"Session-betalningsdatum: {session_due}",
                 datum=str(session_due))
        else:
            alog("SESSION_DUE", "Session-betalningsdatum: ej satt",
                 datum=None)

        if has_due and session_due is None:
            log.warning(
                "DIAGNOS: has_session_due_date=True men "
                "session_due_date=None — inkonsistent tillstånd i app.py",
                extra={"action": "DIAGNOS"},
            )
        elif not has_due and session_due is not None:
            log.warning(
                "DIAGNOS: session_due_date=%s men "
                "has_session_due_date=False — inkonsistent tillstånd",
                session_due, extra={"action": "DIAGNOS"},
            )
    except Exception as exc:
        log.warning("Kunde inte läsa session_due_date: %s", exc)


def attach_session_due_date_watcher(app: Any) -> None:
    """Monkey-patch: varje ändring av session-datumet loggas."""
    log = logging.getLogger("SessionDueDate")
    original_set = getattr(app, "set_session_due_date", None)
    if original_set is None:
        log.warning(
            "DIAGNOS: app.set_session_due_date() saknas",
            extra={"action": "DIAGNOS"},
        )
        return

    def patched_set(value):
        old = getattr(app, "session_due_date", None)
        original_set(value)
        new = getattr(app, "session_due_date", None)
        alog("SESSION_DUE_CHANGED",
             f"Session-datum ändrat: {old} → {new}",
             gammalt=str(old), nytt=str(new))
        if new is not None:
            today = datetime.date.today()
            if new < today:
                log.warning(
                    "Session-datum %s är PASSERAT (idag %s)",
                    new, today, extra={"action": "SESSION_DUE_PASSED"},
                )

    try:
        app.set_session_due_date = patched_set
    except Exception as exc:
        log.warning("Kunde inte patcha set_session_due_date: %s", exc)


def attach_app_watchers(app: Any) -> None:
    """CRUD/settings-watchers → varje datamutation loggas som AUDIT."""
    log = logging.getLogger("AppWatcher")

    def _make_store_cb(store_name: str):
        def cb(name: str, records: list):
            alog("DATA_CHANGED", f"DataStore[{store_name}] ändrad",
                 logger="AppWatcher", store=store_name,
                 poster=len(records))
        return cb

    for store_name in ("invoices", "suppliers", "payments"):
        store = getattr(app, f"{store_name}_store", None)
        if store and hasattr(store, "on_change"):
            store.on_change(_make_store_cb(store_name))

    if hasattr(app, "settings") and hasattr(app.settings, "on_change"):
        def settings_cb(data: dict):
            alog("SETTINGS_CHANGED", "Settings ändrades",
                 tema=data.get("theme"), startup=data.get("startup"),
                 close_to_tray=data.get("close_to_tray"),
                 start_minimized=data.get("start_minimized"))
        app.settings.on_change(settings_cb)

    log_session_due_date(app)
    attach_session_due_date_watcher(app)
    alog("WATCHERS", "App-watchers kopplade", logger="AppWatcher")


# ═════════════════════════════════════════════════════════════════════
#  QT-EVENTBRYGGA — varje klick, tangenttryck och fokus loggas (TRACE)
# ═════════════════════════════════════════════════════════════════════

#: Global brygga (behålls som modulreferens så GC inte tar den).
_qt_bridge: "QtEventBridge | None" = None


class QtEventBridge(QObject):
    """
    Global eventfilter på QApplication — loggar VARJE användarhändelse:

        BUTTON_CLICK   klick på knapp/menypost/annat med text
        UI_CLICK       klick på widget utan text (tabeller, ytor)
        UI_KEY         tangenttryckning (keykod + text + widget)
        UI_FOCUS       fokus flyttas till en widget
        UI_WHEEL       mushjuls-scroll (riktning)

    Alla rader skrivs på TRACE-nivå via alog() → JSONL. Bryggan är
    nästan kostnadsfri när TRACE är avstängt (en isEnabledFor-koll).
    Loggning får ALDRIG krascha appen — allt ligger i try/except.
    """

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.clicks = 0
        self.keys = 0
        self.wheels = 0

    def eventFilter(self, obj: Any, event: Any) -> bool:  # noqa: N802
        try:
            if not logging.getLogger().isEnabledFor(TRACE_LEVEL):
                return False
            t = event.type()
            cls = type(obj).__name__

            if t == QEvent.Type.MouseButtonPress:
                self.clicks += 1
                text_fn = getattr(obj, "text", None)
                text = ""
                if callable(text_fn):
                    try:
                        text = str(text_fn() or "")[:80]
                    except Exception:
                        text = ""
                try:
                    pos = event.position().toPoint()
                    xy = f"({pos.x()},{pos.y()})"
                except Exception:
                    xy = ""
                if text:
                    alog(
                        "BUTTON_CLICK",
                        f"Klick på '{text}' {xy}",
                        level=TRACE_LEVEL, logger="QtUI",
                        widget=cls, text=text,
                    )
                else:
                    alog(
                        "UI_CLICK",
                        f"Klick på {cls} {xy}",
                        level=TRACE_LEVEL, logger="QtUI", widget=cls,
                    )

            elif t == QEvent.Type.KeyPress:
                self.keys += 1
                try:
                    key_text = event.text() or ""
                except Exception:
                    key_text = ""
                msg = f"{cls} key={event.key()}"
                if key_text:
                    msg += f" text={key_text!r}"
                alog(
                    "UI_KEY", msg,
                    level=TRACE_LEVEL, logger="QtUI",
                    widget=cls, key=event.key(),
                )

            elif t == QEvent.Type.FocusIn:
                alog(
                    "UI_FOCUS", f"Fokus → {cls}",
                    level=TRACE_LEVEL, logger="QtUI", widget=cls,
                )

            elif t == QEvent.Type.Wheel:
                self.wheels += 1
                try:
                    dy = event.angleDelta().y()
                    riktning = "upp" if dy > 0 else "ner"
                except Exception:
                    riktning = "?"
                alog(
                    "UI_WHEEL", f"Scroll {riktning} på {cls}",
                    level=TRACE_LEVEL, logger="QtUI", widget=cls,
                )
        except Exception:
            pass
        return False


def install_qt_event_bridge(app_qt: Any) -> bool:
    """Installerar den globala Qt-bryggan. Returnerar True vid framgång."""
    global _qt_bridge
    try:
        if app_qt is None:
            return False
        _qt_bridge = QtEventBridge(app_qt)
        app_qt.installEventFilter(_qt_bridge)
        alog(
            "QT_BRIDGE",
            "Global Qt-brygga installerad — varje klick/tangent/fokus/"
            "scroll loggas (TRACE)",
            logger="AdvancedLogger",
        )
        return True
    except Exception as exc:
        _plugin_log.warning("Qt-brygga kunde inte installeras: %s", exc)
        return False


# ═════════════════════════════════════════════════════════════════════
#  SIGNAL-LOGGARE — menyer, verktygsfält, kombor, datumfält, textfält
# ═════════════════════════════════════════════════════════════════════


def _install_ui_signal_loggers(main_window: Any) -> None:
    """
    Kopplar loggning på Qt-signaler som eventfilter inte når:

        ACTION_TRIGGERED  varje meny-/verktygsfält-/tray-kommando
        COMBO_CHANGED     rullisteval
        SPIN_CHANGED      sifferfält (år/belopp)
        DATE_CHANGED      datumfält
        TEXT_EDITED       textfält (vid Enter/fokus bort)

    Körs FÖRDRÖJT (QTimer.singleShot(0)) så att ALLA plugins fas-2
    hunnit skapa sinaaktioner innan vi kopplar — annars skulle t.ex.
    PDF-exportens menyaktion missas.
    """
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import (
        QComboBox, QSpinBox, QDoubleSpinBox,
        QDateEdit, QLineEdit,
    )

    def _hook() -> None:
        try:
            counts = {"aktioner": 0, "kombor": 0, "fält": 0}
            window = main_window

            # ── QActions: meny + toolbar + tray-meny ─────────────────
            actions = list(window.findChildren(QAction))
            tray = getattr(window, "tray", None)
            if tray is not None:
                try:
                    menu = tray.contextMenu()
                    if menu is not None:
                        actions += menu.findChildren(QAction)
                except Exception:
                    pass
            for act in actions:
                if getattr(act, "_fbp_logged", False):
                    continue
                label = (act.text() or "").strip() or "(namnlös)"

                def _mk(lbl: str = label):
                    def _f(*_a):
                        alog(
                            "ACTION_TRIGGERED",
                            f"Menyaktion: '{lbl}'",
                            logger="QtUI", aktion=lbl,
                        )
                    return _f

                try:
                    act.triggered.connect(_mk())
                    act._fbp_logged = True  # type: ignore[attr-defined]
                    counts["aktioner"] += 1
                except Exception:
                    pass

            # ── Rullistor ─────────────────────────────────────────────
            for combo in window.findChildren(QComboBox):
                if getattr(combo, "_fbp_logged", False):
                    continue

                def _mk_c(c: QComboBox = combo):
                    def _f(_idx: int):
                        alog(
                            "COMBO_CHANGED",
                            f"Rullista → '{c.currentText()}'",
                            level=TRACE_LEVEL, logger="QtUI",
                            objekt=c.objectName() or type(c).__name__,
                            varde=c.currentText(),
                        )
                    return _f

                try:
                    combo.currentIndexChanged.connect(_mk_c())
                    combo._fbp_logged = True  # type: ignore[attr-defined]
                    counts["kombor"] += 1
                except Exception:
                    pass

            # ── Datum-, siffer- och textfält ──────────────────────────
            for w in window.findChildren(QDateEdit):
                if getattr(w, "_fbp_logged", False):
                    continue

                def _mk_d(d: QDateEdit = w):
                    def _f(_date):
                        alog(
                            "DATE_CHANGED",
                            f"Datumfält → {d.date().toString('yyyy-MM-dd')}",
                            level=TRACE_LEVEL, logger="QtUI",
                            objekt=d.objectName() or type(d).__name__,
                        )
                    return _f

                try:
                    w.dateChanged.connect(_mk_d())
                    w._fbp_logged = True  # type: ignore[attr-defined]
                    counts["fält"] += 1
                except Exception:
                    pass

            # PySide6 finner inte tuple av typer — sök per typ.
            spin_widgets = list(window.findChildren(QSpinBox)) + list(
                window.findChildren(QDoubleSpinBox)
            )
            for w in spin_widgets:
                if getattr(w, "_fbp_logged", False):
                    continue

                def _mk_s(s=w):
                    def _f(v):
                        alog(
                            "SPIN_CHANGED",
                            f"Sifferfält → {v}",
                            level=TRACE_LEVEL, logger="QtUI",
                            objekt=s.objectName() or type(s).__name__,
                            varde=v,
                        )
                    return _f

                try:
                    w.valueChanged.connect(_mk_s())
                    w._fbp_logged = True  # type: ignore[attr-defined]
                    counts["fält"] += 1
                except Exception:
                    pass

            for w in window.findChildren(QLineEdit):
                if getattr(w, "_fbp_logged", False):
                    continue

                def _mk_t(e: QLineEdit = w):
                    def _f():
                        alog(
                            "TEXT_EDITED",
                            f"Textfält redigerat "
                            f"({len(e.text() or '')} tecken)",
                            level=TRACE_LEVEL, logger="QtUI",
                            objekt=e.objectName() or type(e).__name__,
                        )
                    return _f

                try:
                    w.editingFinished.connect(_mk_t())
                    w._fbp_logged = True  # type: ignore[attr-defined]
                    counts["fält"] += 1
                except Exception:
                    pass

            alog(
                "UI_HOOKS",
                f"Signal-loggare kopplade: {counts['aktioner']} aktioner, "
                f"{counts['kombor']} kombor, {counts['fält']} fält",
                logger="AdvancedLogger",
                **{k.replace("ä", "a"): v for k, v in counts.items()},
            )
        except Exception as exc:
            _plugin_log.warning("UI-signalloggare: %s", exc)

    try:
        QTimer.singleShot(0, _hook)
    except Exception as exc:
        _plugin_log.warning("UI-signalloggare (fördröjning): %s", exc)


def attach_window_watchers(main_window: Any) -> None:
    """Tema/flik/tray-händelser + fönster-spy → allt synligt loggas."""
    global _window_spy
    log = logging.getLogger("WindowWatcher")

    if hasattr(main_window, "theme_changed"):
        def _on_theme(theme: dict):
            alog("THEME_CHANGED", f"Tema bytt → {theme.get('name')}",
                 tema=theme.get("name"), bg=theme.get("bg"))
        main_window.theme_changed.connect(_on_theme)

    if hasattr(main_window, "tabs"):
        def _on_tab(idx: int):
            try:
                alog("TAB_CHANGED",
                     f"Flik bytt → [{idx}] {main_window.tabs.tabText(idx)}",
                 flik=idx)
            except Exception:
                pass
        main_window.tabs.currentChanged.connect(_on_tab)

    # Tray-klick loggas (diagnos för blink/göm-beteendet)
    tray = getattr(main_window, "tray", None)
    if tray is not None:
        def _on_tray(reason):
            alog("TRAY_CLICK", f"Tray-ikon klickad (reason={reason})",
                 reason=str(reason))
        try:
            tray.activated.connect(_on_tray)
        except Exception:
            pass

    # Fönster-spy: SHOW/HIDE/MINIMIZE/ACTIVATE/CLOSE
    try:
        _window_spy = _WindowSpy()
        main_window.installEventFilter(_window_spy)
        alog("WINDOW_SPY", "Fönster-spY installerad (SHOW/HIDE loggas)")
    except Exception as exc:
        log.debug("Window spy: %s", exc)

    alog("WATCHERS", "Fönster-watchers kopplade", logger="WindowWatcher")


# ═════════════════════════════════════════════════════════════════════
#  DIAGNOS + PRESTANDA + SYSTEMINFO
# ═════════════════════════════════════════════════════════════════════


def log_diagnosis(context: str, exc: Exception) -> None:
    """Loggar fel med trace + troliga orsaker (AI-läsbart)."""
    log = logging.getLogger("Diagnosis")
    log.error(
        "FEL i '%s': %s: %s — MÖJLIGA ORSAKER: "
        "1 importproblem 2 dataformat 3 pluginordning "
        "4 temadict 5 singleton 6 on_change 7 session_due_date",
        context, type(exc).__name__, exc,
        exc_info=exc, extra={"action": "DIAGNOS"},
    )


class PerfTimer:
    """Context manager: loggar långsamma operationer (PERF-nivå)."""

    def __init__(self, operation: str, threshold_ms: float = 200.0) -> None:
        import time
        self._op = operation
        self._threshold = threshold_ms
        self._time = time
        self._start = 0.0

    def __enter__(self):
        self._start = self._time.perf_counter()
        return self

    def __exit__(self, *_):
        ms = (self._time.perf_counter() - self._start) * 1000
        if ms > self._threshold:
            alog("PERF_SLOW", f"{self._op} tog {ms:.1f} ms",
                 level=logging.WARNING, operation=self._op, ms=round(ms, 1))
        else:
            alog("PERF", f"{self._op} tog {ms:.1f} ms",
                 level=PERF_LEVEL, operation=self._op, ms=round(ms, 1))


def log_system_info() -> None:
    """Systeminfo → en strukturerad rad i den enda loggfilen."""
    try:
        import importlib.metadata as meta
        pyside = meta.version("PySide6")
    except Exception:
        pyside = "okänd"
    try:
        import reportlab  # noqa: F401
        rl = "ja"
    except Exception:
        rl = "nej (text-fallback)"
    alog(
        "SYSTEM_INFO",
        "Systeminfo vid start",
        os=platform.system(), os_release=platform.release(),
        python=sys.version.split()[0], pyside6=pyside,
        reportlab=rl, exe=sys.executable, cwd=str(Path.cwd()),
        log_file=str(LOG_FILE),
    )


# ═════════════════════════════════════════════════════════════════════
#  LOGGER VIEW (UI-panel)
# ═════════════════════════════════════════════════════════════════════


class LoggerView(QWidget):
    """Live-loggpanel: filter, sök, export, systeminfo, session-banner."""

    def __init__(
        self,
        memory_handler: MemoryHandler,
        app: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._handler = memory_handler
        self._app = app
        self._paused = False
        self._is_dark = True
        self._auto_scroll = True

        self._handler.new_record_callback = self._on_new_record
        self._build_ui()
        self._refresh_table()
        self._refresh_session_due_label()

        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self._on_timer)
        self._timer.start()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 10)
        root.setSpacing(10)

        hdr = QLabel("🔍  Systemlogg — en fil, allt loggas (JSONL)")
        hdr.setFont(QFont("Segoe UI", 17, QFont.Bold))
        root.addWidget(hdr)
        root.addWidget(self._separator())

        self._session_due_banner = QLabel()
        self._session_due_banner.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self._session_due_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._session_due_banner.setMinimumHeight(32)
        self._session_due_banner.setVisible(False)
        root.addWidget(self._session_due_banner)

        ctrl1 = QHBoxLayout()
        ctrl1.setSpacing(8)
        lbl_level = QLabel("Nivå:")
        lbl_level.setFont(QFont("Segoe UI", 11, QFont.Bold))
        lbl_level.setStyleSheet("background:transparent;")
        ctrl1.addWidget(lbl_level)

        self._cmb_level = QComboBox()
        self._cmb_level.setMinimumHeight(36)
        self._cmb_level.setFont(QFont("Segoe UI", 11))
        self._cmb_level.setMinimumWidth(130)
        self._cmb_level.addItems([
            "ALL", "TRACE", "DEBUG", "PERF", "INFO",
            "AUDIT", "WARNING", "ERROR", "CRITICAL",
        ])
        self._cmb_level.setCurrentText("INFO")
        self._cmb_level.currentTextChanged.connect(self._refresh_table)
        ctrl1.addWidget(self._cmb_level)

        lbl_search = QLabel("Sök:")
        lbl_search.setFont(QFont("Segoe UI", 11, QFont.Bold))
        lbl_search.setStyleSheet("background:transparent;")
        ctrl1.addWidget(lbl_search)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filtrera loggmeddelanden …")
        self._search.setMinimumHeight(36)
        self._search.setFont(QFont("Segoe UI", 11))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._refresh_table)
        ctrl1.addWidget(self._search, stretch=1)
        root.addLayout(ctrl1)

        ctrl2 = QHBoxLayout()
        ctrl2.setSpacing(8)

        self._btn_pause = QPushButton("⏸  Pausa")
        self._btn_pause.clicked.connect(self._toggle_pause)
        self._btn_clear = QPushButton("🗑  Rensa panel")
        self._btn_clear.clicked.connect(self._clear_log)
        self._btn_export = QPushButton("📁  Exportera logg")
        self._btn_export.clicked.connect(self._export_log)
        self._btn_sysinfo = QPushButton("💻  Systeminfo")
        self._btn_sysinfo.clicked.connect(self._show_sysinfo)

        self._chk_scroll = QCheckBox("Auto-scroll")
        self._chk_scroll.setChecked(True)
        self._chk_scroll.stateChanged.connect(
            lambda s: setattr(self, "_auto_scroll", bool(s))
        )
        for b in (self._btn_pause, self._btn_clear,
                  self._btn_export, self._btn_sysinfo):
            b.setMinimumHeight(36)
            b.setFont(QFont("Segoe UI", 11, QFont.Bold))
            ctrl2.addWidget(b)
        ctrl2.addWidget(self._chk_scroll)
        ctrl2.addStretch()

        self._lbl_count = QLabel("0 rader")
        self._lbl_count.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self._lbl_count.setStyleSheet("background:transparent;")
        ctrl2.addWidget(self._lbl_count)
        root.addLayout(ctrl2)

        info_box = QGroupBox("Loggfil (enda)")
        info_box.setFont(QFont("Segoe UI", 10, QFont.Bold))
        info_layout = QVBoxLayout(info_box)
        row = QHBoxLayout()
        lbl = QLabel("Alla händelser (JSONL):")
        lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl.setFixedWidth(150)
        lbl.setStyleSheet("background:transparent;")
        path_lbl = QLabel(str(LOG_FILE))
        path_lbl.setFont(QFont("Consolas", 9))
        path_lbl.setStyleSheet("background:transparent;")
        row.addWidget(lbl)
        row.addWidget(path_lbl)
        row.addStretch()
        info_layout.addLayout(row)
        root.addWidget(info_box)

        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels([
            "Tid", "Nivå", "Logger", "Action", "Meddelande",
        ])
        self._table.setSortingEnabled(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setWordWrap(True)
        self._table.setShowGrid(True)
        hh = self._table.horizontalHeader()
        for i in range(4):
            hh.setSectionResizeMode(
                i, QHeaderView.ResizeMode.ResizeToContents
            )
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setDefaultSectionSize(26)
        self._table.wheelEvent = self._table_wheel  # type: ignore
        root.addWidget(self._table, stretch=1)

        self._status = QLabel("Redo")
        self._status.setFont(QFont("Segoe UI", 10))
        self._status.setStyleSheet("background:transparent;color:#888;")
        root.addWidget(self._status)

        root.addWidget(self._separator())
        footer = QLabel(
            f"© {COPYRIGHT_YEAR} Rickard Längkvist"
            f"  —  Fakturabunten"
        )
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setFont(QFont("Segoe UI", 9))
        footer.setStyleSheet("background:transparent;color:#718096;")
        root.addWidget(footer)

    def _table_wheel(self, event: QWheelEvent) -> None:
        sb = self._table.verticalScrollBar()
        sb.setValue(sb.value() - (event.angleDelta().y() // 40))
        event.accept()

    @staticmethod
    def _separator() -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setFrameShadow(QFrame.Shadow.Sunken)
        return f

    def _refresh_session_due_label(self) -> None:
        if self._app is None:
            self._session_due_banner.setVisible(False)
            return
        try:
            session_due = getattr(self._app, "session_due_date", None)
            if session_due is None:
                self._session_due_banner.setVisible(False)
                return
            today = datetime.date.today()
            days_left = (session_due - today).days
            if days_left > 0:
                color, icon = "#1565c0", "📅"
                extra = f"({days_left} dagar kvar)"
            elif days_left == 0:
                color, icon = "#2e7d32", "✅"
                extra = "(idag)"
            else:
                color, icon = "#b71c1c", "⚠️"
                extra = f"(PASSERAT — {abs(days_left)} dagar sedan)"
            self._session_due_banner.setText(
                f"{icon}  Session-betalningsdatum: {session_due}  {extra}"
            )
            self._session_due_banner.setStyleSheet(
                f"background:{color};color:#ffffff;"
                f"border-radius:6px;padding:4px 12px;font-weight:700;"
            )
            self._session_due_banner.setVisible(True)
        except Exception:
            self._session_due_banner.setVisible(False)

    def _on_timer(self) -> None:
        self._refresh_table()
        self._refresh_session_due_label()

    def _on_new_record(self, record: logging.LogRecord) -> None:
        if not self._paused:
            QTimer.singleShot(0, self._refresh_table)

    def _refresh_table(self) -> None:
        if self._paused:
            return
        records = self._handler.get_records(
            self._cmb_level.currentText(), self._search.text().strip()
        )
        if len(records) > UI_MAX_ROWS:
            records = records[-UI_MAX_ROWS:]

        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(records))
        colors = (
            {
                "DEBUG": "#888888", "PERF": "#2196f3", "INFO": "#e0e0e0",
                "AUDIT": "#4caf50", "WARNING": "#ff9800",
                "ERROR": "#f44336", "CRITICAL": "#ff1744",
            }
            if self._is_dark
            else {
                "DEBUG": "#999999", "PERF": "#1565c0", "INFO": "#1a202c",
                "AUDIT": "#2e7d32", "WARNING": "#e65100",
                "ERROR": "#b71c1c", "CRITICAL": "#d50000",
            }
        )
        for row, rec in enumerate(records):
            ts = datetime.datetime.fromtimestamp(
                rec.created
            ).strftime("%H:%M:%S")
            action = getattr(rec, "action", "") or rec.levelname
            msg = rec.getMessage()
            if rec.exc_info:
                msg += "\n" + "".join(
                    traceback.format_exception(*rec.exc_info)
                )
            fg = QColor(colors.get(rec.levelname, colors["INFO"]))
            bold = rec.levelname in ("ERROR", "CRITICAL", "WARNING")
            for col, text in enumerate(
                [ts, rec.levelname, rec.name, action, msg]
            ):
                item = QTableWidgetItem(str(text))
                item.setForeground(QBrush(fg))
                font = QFont("Consolas", 10)
                font.setBold(bold)
                item.setFont(font)
                item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                )
                self._table.setItem(row, col, item)
        self._table.resizeRowsToContents()

        total = len(self._handler.get_records())
        session_due = (
            getattr(self._app, "session_due_date", None)
            if self._app else None
        )
        due_str = f"  |  Betalningsdatum: {session_due}" if session_due else ""
        self._lbl_count.setText(f"{len(records)} rader")
        self._status.setText(
            f"Visar {len(records)} av {total} loggposter"
            + (" (pausad)" if self._paused else "")
            + due_str
        )
        if self._auto_scroll and records:
            self._table.scrollToBottom()

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self._btn_pause.setText(
            "▶️  Återuppta" if self._paused else "⏸  Pausa"
        )
        if not self._paused:
            self._refresh_table()

    def _clear_log(self) -> None:
        reply = QMessageBox.question(
            self, "Rensa loggpanel",
            "Rensa loggpanelen?\n\nLoggfilen på disk påverkas inte.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._handler.clear()
            self._refresh_table()

    def _export_log(self) -> None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        # Alltid i appmappen. Ingen sökväg utanför.
        root = Path(__file__).resolve().parent.parent / "exports"
        day = root / datetime.date.today().isoformat()
        day.mkdir(parents=True, exist_ok=True)
        path = str(day / f"logg_export_{ts}.txt")
        try:
            lines = []
            for rec in self._handler.get_records(
                self._cmb_level.currentText(),
                self._search.text().strip(),
            ):
                lines.append(
                    json.dumps(_record_to_entry(rec), ensure_ascii=False)
                )
            Path(path).write_text("\n".join(lines), encoding="utf-8")
            QMessageBox.information(
                self, "Export klar", f"✅  Logg exporterad:\n{path}"
            )
        except Exception as exc:
            QMessageBox.critical(self, "Export-fel", str(exc))

    def _show_sysinfo(self) -> None:
        log_system_info()
        session_due = (
            getattr(self._app, "session_due_date", None)
            if self._app else None
        )
        size = LOG_FILE.stat().st_size // 1024 if LOG_FILE.exists() else 0
        info = (
            f"OS:        {platform.system()} {platform.release()}\n"
            f"Python:    {sys.version.split()[0]}\n"
            f"Exe:       {sys.executable}\n"
            f"Cwd:       {Path.cwd()}\n"
            f"Loggfil:   {LOG_FILE} ({size} KB)\n\n"
            f"Session-betalningsdatum: {session_due or 'ej satt'}\n"
        )
        QMessageBox.information(self, "Systeminfo", info)

    def apply_theme(self, theme: dict) -> None:
        self._is_dark = theme.get("bg", "#0d1117") not in (
            "#ffffff", "#f5f7fa", "#f8f9fa", "#f6f8fa", "#eaeef2",
        )
        t = theme
        dark = self._is_dark
        text_strong = t.get("text_strong", "#f0f6fc" if dark else "#1c2128")
        accent = t.get("accent", "#58a6ff" if dark else "#0969da")
        header_bg = t.get("header_bg", "#161b22" if dark else "#0969da")
        row_normal = t.get("row_normal", "#0d1117" if dark else "#ffffff")
        row_alt = t.get("row_alt", "#161b22" if dark else "#f6f8fa")
        border = t.get("border", "#30363d" if dark else "#d0d7de")
        input_bg = t.get("input_bg", "#0d1117" if dark else "#ffffff")
        input_bdr = t.get("input_border", "#30363d" if dark else "#d0d7de")
        button_bg = t.get("button_bg", "#21262d" if dark else "#6e7781")
        button_hov = t.get("button_hover", "#30363d" if dark else "#57606a")
        button_text = t.get("button_text", "#f0f6fc" if dark else "#ffffff")
        scroll_h = t.get("scrollbar_handle", "#30363d" if dark else "#d0d7de")

        self._table.setStyleSheet(f"""
            QTableWidget {{
                background-color:{row_normal}; color:{text_strong};
                font-weight:600; font-size:11px;
                gridline-color:{border};
                alternate-background-color:{row_alt};
                selection-background-color:{accent};
                selection-color:#ffffff;
                border:1px solid {border}; border-radius:6px; outline:none;
            }}
            QHeaderView::section {{
                background-color:{header_bg}; color:#ffffff;
                font-weight:700; font-size:11px; padding:5px 8px;
                border:none; border-right:1px solid {border};
                border-bottom:1px solid {border};
            }}
            QScrollBar:vertical {{
                background:{row_alt}; width:10px; border-radius:5px;
            }}
            QScrollBar::handle:vertical {{
                background:{scroll_h}; border-radius:5px; min-height:20px;
            }}
        """)
        btn_ss = f"""
            QPushButton {{
                background-color:{button_bg}; color:{button_text};
                font-weight:700; border-radius:7px;
                border:1px solid {border}; padding:5px 14px; min-height:34px;
            }}
            QPushButton:hover {{
                background-color:{button_hov}; border-color:{accent};
            }}
        """
        for btn in (self._btn_pause, self._btn_clear,
                    self._btn_export, self._btn_sysinfo):
            btn.setStyleSheet(btn_ss)
        self._search.setStyleSheet(f"""
            QLineEdit {{
                background-color:{input_bg}; color:{text_strong};
                border:1.5px solid {input_bdr}; border-radius:6px;
                padding:4px 10px; font-size:12px; font-weight:600;
            }}
            QLineEdit:focus {{ border-color:{accent}; }}
        """)
        self._cmb_level.setStyleSheet(f"""
            QComboBox {{
                background-color:{input_bg}; color:{text_strong};
                border:1.5px solid {input_bdr}; border-radius:6px;
                padding:4px 10px; font-size:12px; font-weight:600;
            }}
        """)
        self._lbl_count.setStyleSheet(
            f"color:{text_strong};font-weight:700;background:transparent;"
        )
        self._refresh_session_due_label()
        self._refresh_table()


# ═════════════════════════════════════════════════════════════════════
#  PLUGIN-REGISTRERING
# ═════════════════════════════════════════════════════════════════════

_plugin_log: logging.Logger = logging.getLogger("AdvancedLogger")
_memory_handler_global: MemoryHandler | None = None
_app_ref: Any = None


def register(app: Any) -> None:
    """Phase-1: en fil, kölogg, hooks, watchers, systeminfo, Qt-brygga."""
    global _memory_handler_global, _app_ref
    _app_ref = app

    # TRACE (varje tryck) styrs av settings.json → "log_trace"
    trace_on = True
    settings = getattr(app, "settings", None)
    if settings is not None:
        try:
            trace_on = bool(settings.get("log_trace", True))
        except Exception:
            trace_on = True

    try:
        _memory_handler_global = setup_logging(trace_on=trace_on)
    except Exception as exc:
        print(f"KRITISKT: setup_logging() misslyckades: {exc}",
              file=sys.stderr)
        return

    try:
        install_exception_hook()
    except Exception as exc:
        _plugin_log.error("exception hook: %s", exc)
    try:
        install_qt_message_hook()
    except Exception as exc:
        _plugin_log.warning("Qt message hook: %s", exc)
    try:
        log_system_info()
    except Exception as exc:
        _plugin_log.warning("system info: %s", exc)

    # ── Global Qt-brygga: varje klick/tangent/fokus/scroll loggas ────
    try:
        from PySide6.QtWidgets import QApplication

        qapp = QApplication.instance()
        if qapp is not None:
            install_qt_event_bridge(qapp)
        else:
            _plugin_log.warning(
                "Qt-brygga: ingen QApplication ännu — hoppar över"
            )
    except Exception as exc:
        _plugin_log.warning("Qt-brygga: %s", exc)

    # ── Live-växling av TRACE via settings (kryssruta i menyn) ───────
    if settings is not None:
        try:
            def _on_settings_changed(snapshot: dict) -> None:
                try:
                    set_trace_enabled(bool(snapshot.get("log_trace", True)))
                except Exception:
                    pass

            settings.on_change(_on_settings_changed)
        except Exception as exc:
            _plugin_log.warning("TRACE-live-växling: %s", exc)

    if app is not None:
        try:
            attach_app_watchers(app)
        except Exception as exc:
            log_diagnosis("_attach_app_watchers", exc)
    else:
        _plugin_log.warning(
            "DIAGNOS: app är None i register()",
            extra={"action": "DIAGNOS"},
        )

    alog("PLUGIN", "AdvancedLogger registrerad (phase 1)",
         logger="AdvancedLogger", log_file=str(LOG_FILE))


def register_ui(main_window: Any) -> None:
    """Phase-2: LoggerView + fönster-watchers + fönster-spy."""
    global _memory_handler_global, _app_ref

    if _memory_handler_global is None:
        try:
            _memory_handler_global = setup_logging()
        except Exception as exc:
            _plugin_log.error("setup_logging i register_ui: %s", exc)
            return

    if _app_ref is None:
        _app_ref = getattr(main_window, "_app", None)

    try:
        attach_window_watchers(main_window)
    except Exception as exc:
        log_diagnosis("_attach_window_watchers", exc)

    # Meny-/kombo-/fält-signaler loggas efter alla plugins fas-2
    try:
        _install_ui_signal_loggers(main_window)
    except Exception as exc:
        log_diagnosis("_install_ui_signal_loggers", exc)

    try:
        view = LoggerView(
            _memory_handler_global, app=_app_ref, parent=main_window
        )
        tab_map = getattr(main_window, "_tab_map", {})
        if getattr(main_window, "_settings_tab_custom", False):
            # Inställningar-fliken har eget innehåll (kortkommandon,
            # plugins, TRACE-kryssruta) → loggen blir en EGEN flik.
            main_window.add_plugin_tab(view, "🔍  Logg", "logger_tab")
            alog(
                "LOGGER_VIEW",
                "LoggerView monterad som egen flik (Inställningar "
                "har egen panel)",
                logger="AdvancedLogger",
            )
        elif (
            hasattr(main_window, "replace_tab_content")
            and "settings_tab" in tab_map
        ):
            main_window.replace_tab_content("settings_tab", view)
        else:
            main_window.add_plugin_tab(view, "🔍  Logg", "logger_tab")

        if hasattr(main_window, "theme_changed"):
            main_window.theme_changed.connect(view.apply_theme)
            view.apply_theme(main_window.current_theme_dict())
    except Exception as exc:
        log_diagnosis("LoggerView injection", exc)

    alog("PLUGIN", "AdvancedLogger UI registrerat (phase 2)",
         logger="AdvancedLogger")
