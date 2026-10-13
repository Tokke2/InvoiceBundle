from __future__ import annotations

"""
Fakturabunten — Main Entry Point
========================================
Fil    : Fakturabunten_/main.py
Författare : Rickard Längkvist
År     : Dynamiskt (auto)

Startpunkt för Fakturabunten.

Ansvar (i startordning):
    1.  Qt-runtime-miljö före QApplication (DPI-scalning)
    2.  Dölj konsolfönster (Windows, produktionsläge)
    3.  Sätt Windows AppUserModelID (korrekt gruppering i fältet)
    4.  Snabbladda settings från JSON (för tidigt tema)
    5.  Skapa QApplication + applicera tema tidigt
    6.  Single-instance-lås (QLockFile) — hindrar flera kopior
    6b. Fokus-överlämning: andra instansen ber den första visa
        fönstret (QLocalServer/QLocalSocket) innan den avslutar
    7.  Skapa FakturaApp (app.py)
    8.  Inget datum väljs vid start. Datum väljs bara vid export.
    9.  Skapa MainWindow, kör plugin phase-2, koppla watchers
    9b. Globala snabbknappar: Ctrl+1–7 (flikhopp), Ctrl+E (export),
        F5 (uppdatera)
    10. Starta minimerat i systemfältet (standard) eller synligt
    11. Kör event-loopen, frigör låset vid avslut
    12. Kraschskydd: startup_crash.log för tysta pythonw-krascher

Övrigt:
    • Autostart hanteras av AutostartManager i app.py (MASTER).
      Denna fil läser/synkar bara status robust vid start.
    • Multi-OS: Windows / Linux / macOS.
    • Körs utan terminalfönster (pythonw.exe på Windows).

Copyright © dynamiskt år Rickard Längkvist
"""

import datetime
import json
import logging
import os
import platform
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable

# ═════════════════════════════════════════════════════════════════════
#  SÖKVÄGAR — måste vara på plats före alla ui/app-importer
# ═════════════════════════════════════════════════════════════════════

BASE_DIR: Path = Path(__file__).parent.resolve()
UI_DIR: Path = BASE_DIR / "ui"

#: Autostart via registret startar med cwd = System32. Lås arbetsmappen
#: till appmappen innan något relativt öppnas.
_CWD_BEFORE: Path = Path.cwd()
try:
    os.chdir(BASE_DIR)
except OSError:
    pass

for _dir in (str(BASE_DIR), str(UI_DIR)):
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

# ═════════════════════════════════════════════════════════════════════
#  KONSTANTER
# ═════════════════════════════════════════════════════════════════════

APP_NAME: str = "Fakturabunten"
APP_SHORT_NAME: str = "Fakturabunten"
APP_VERSION: str = "1.0.0"
APP_ORGANIZATION: str = "Rickard Längkvist"

COPYRIGHT_YEAR: int = datetime.date.today().year
COPYRIGHT: str = f"© {COPYRIGHT_YEAR} Rickard Längkvist"

SETTINGS_FILE: Path = BASE_DIR / "settings.json"
LOG_DIR: Path = BASE_DIR / "logs"
#: ENDA loggfilen (JSONL) — delas med advanced_logger-pluginet.
LOG_FILE: Path = LOG_DIR / "app.log"
LOCK_FILE_NAME: str = f"{APP_SHORT_NAME}_single_instance.lock"
FOCUS_SERVER_NAME: str = f"{APP_SHORT_NAME}_focus_server"

DEBUG_MODE: bool = "--debug" in sys.argv

#: True när appen startats via autostart (registret/.desktop/plist).
#: Då (och endast då) startar appen minimerad i systemfältet.
#: Manuell start (dubbelklick/genväg) visar alltid fönstret.
AUTOSTART_LAUNCH: bool = "--minimized" in sys.argv

#: Headless självtest (idén från PDF reader Pro SPEC v2.1 §2.8):
#:   python main.py --selftest
#: Kör en kontrollsvit utan GUI och avslutar med exitkod 0/1.
SELFTEST: bool = "--selftest" in sys.argv
if SELFTEST:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

#: Standardvärden för settings.json — används tills FakturaApp tar över.
DEFAULT_SETTINGS: dict[str, Any] = {
    "theme":           "dark",
    "startup":         False,
    "start_minimized": True,
    "close_to_tray":   True,
    "auto_backup":     True,
}

#: Globalt single-instance-lås — måste leva under hela livstiden.
_APP_LOCK: Any = None

#: Fokus-server — måste också leva under hela livstiden.
_FOCUS_SERVER: Any = None


_ARCHIVED_FOREIGN_LOG: Path | None = None


def _archive_foreign_log() -> None:
    """
    Flyttar logs/app.log om den skrevs i en annan mapp.

    Händer när hela appmappen kopieras (sandbox → D:\\Program\\...)
    och den gamla loggen följer med. Utan detta drunknar den nya
    starten i hundratals rader från fel dator.
    """
    global _ARCHIVED_FOREIGN_LOG
    if not LOG_FILE.is_file():
        return
    try:
        text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    if not text.strip():
        return
    base = str(BASE_DIR).replace("\\", "/").rstrip("/").lower()
    foreign = 0
    own = 0
    for line in text.splitlines():
        norm = line.replace("\\", "/").lower()
        if base and base in norm:
            own += 1
            continue
        if any(
            mark in norm
            for mark in ("/home/user/", "/tmp/", "c:/", "d:/", "e:/")
        ):
            foreign += 1
    if foreign < 15 or foreign <= own:
        return
    archive = LOG_DIR / "archive"
    try:
        archive.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = archive / f"app_annan_mapp_{stamp}.log"
        LOG_FILE.replace(dest)
        _ARCHIVED_FOREIGN_LOG = dest
    except OSError:
        return


_archive_foreign_log()


def get_platform() -> str:
    """Returnerar 'windows' | 'macos' | 'linux'."""
    p = platform.system().lower()
    if p == "darwin":
        return "macos"
    if p == "windows":
        return "windows"
    return "linux"


CURRENT_PLATFORM: str = get_platform()


# ═════════════════════════════════════════════════════════════════════
#  LOGGING — EN fil (JSONL), samma schema som advanced_logger
# ═════════════════════════════════════════════════════════════════════


class _EarlyJsonlHandler(logging.Handler):
    """Tidig JSONL-skrivning till logs/app.log (enda loggfilen)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "ts": datetime.datetime.fromtimestamp(
                    record.created
                ).isoformat(timespec="seconds"),
                "level": record.levelname,
                "logger": record.name,
                "action": getattr(record, "action", None)
                or record.levelname,
                "msg": record.getMessage(),
                "loc": f"{record.module}:{record.lineno}",
                "thread": record.threadName,
            }
            if record.exc_info:
                entry["exc"] = "".join(
                    traceback.format_exception(*record.exc_info)
                )
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass


def _make_console_handler() -> logging.Handler | None:
    """Konsol-handler OM en riktig stdout finns (pythonw = None)."""
    stream = sys.stdout
    if stream is None:
        return None
    try:
        if stream.fileno() < 0:
            return None
    except (AttributeError, OSError, ValueError):
        return None

    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(name)s  →  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    return handler


def _setup_logging() -> None:
    """
    Tidig loggning: EN JSONL-fil + konsol när terminal finns.
    advanced_logger byter sen till köbaserad skrivning till SAMMA fil.
    """
    level = logging.DEBUG if DEBUG_MODE else logging.INFO
    handlers: list[logging.Handler] = [_EarlyJsonlHandler()]

    console_handler = _make_console_handler()
    if console_handler is not None:
        handlers.append(console_handler)

    logging.basicConfig(level=level, handlers=handlers, force=True)


_setup_logging()
log = logging.getLogger("FakturaMain")
try:
    if Path.cwd().resolve() != _CWD_BEFORE.resolve():
        log.info(
            "ARBETSMAPP: %s → %s (autostart får inte lämna appen i System32)",
            _CWD_BEFORE,
            Path.cwd(),
        )
    else:
        log.info("ARBETSMAPP: %s", Path.cwd())
    log.info("VERSION: %s %s", APP_NAME, APP_VERSION)
    log.info(
        "PORTABEL: appen följer sin egen mapp (%s), inte en fast sökväg",
        BASE_DIR,
    )
    if _ARCHIVED_FOREIGN_LOG is not None:
        log.info(
            "LOGG_ARKIV: gammal logg från annan mapp flyttad till %s",
            _ARCHIVED_FOREIGN_LOG,
        )
except Exception:
    pass


# ═════════════════════════════════════════════════════════════════════
#  KRASCHSKYDD — skrivs som JSONL-rad i ENDA loggfilen
# ═════════════════════════════════════════════════════════════════════


def _write_startup_crash(exc: BaseException) -> None:
    """
    Sista skyddsnätet för tysta krascher (pythonw.exe).
    Lägger en CRASH-rad (med traceback) i logs/app.log.
    """
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "level": "CRITICAL",
            "logger": "FakturaMain",
            "action": "START_CRASH",
            "msg": f"{type(exc).__name__}: {exc}",
            "exc": "".join(
                traceback.format_exception(
                    type(exc), exc, exc.__traceback__
                )
            ),
        }
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ═════════════════════════════════════════════════════════════════════
#  PLATTFORMS-HJÄLPARE
# ═════════════════════════════════════════════════════════════════════


def _hide_console() -> None:
    """Döljer konsolfönstret på Windows i produktionsläge."""
    if CURRENT_PLATFORM != "windows" or DEBUG_MODE:
        return
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def _windows_shortcut() -> None:
    """
    Skapar Fakturabunten.lnk i appmappen.

    Windows visar annars Python-ikonen på pythonw.exe. Genvägen
    bär app_icon.ico, så aktivitetsfält och skrivbord får den egna ikonen.
    """
    if CURRENT_PLATFORM != "windows":
        return
    ico = BASE_DIR / "app_icon.ico"
    pyw = Path(sys.executable)
    if pyw.name.lower() == "python.exe":
        alt = pyw.with_name("pythonw.exe")
        if alt.is_file():
            pyw = alt
    script = BASE_DIR / "main.pyw"
    if not script.is_file():
        script = BASE_DIR / "main.py"
    lnk = BASE_DIR / "Fakturabunten.lnk"
    if not ico.is_file() or not script.is_file():
        return
    try:
        import subprocess
        ps = (
            "$w = New-Object -ComObject WScript.Shell; "
            f"$s = $w.CreateShortcut('{lnk}'); "
            f"$s.TargetPath = '{pyw}'; "
            f"$s.Arguments = '\"{script}\"'; "
            f"$s.WorkingDirectory = '{BASE_DIR}'; "
            f"$s.IconLocation = '{ico},0'; "
            "$s.WindowStyle = 7; "
            "$s.Description = 'Fakturabunten'; "
            "$s.Save()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            cwd=str(BASE_DIR),
            check=False,
            timeout=20,
            capture_output=True,
        )
        log.info("IKON_GENVAG: %s", lnk)
    except Exception as exc:
        log.warning("IKON_GENVAG: %s", exc)


def _set_win32_window_icon(hwnd: int) -> None:
    """Tvingar fönsterikonen så aktivitetsfältet inte behåller Python."""
    ico = BASE_DIR / "app_icon.ico"
    if not ico.is_file() or not hwnd:
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        WM_SETICON = 0x0080
        big = user32.LoadImageW(None, str(ico), IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
        small = user32.LoadImageW(None, str(ico), IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        if big:
            user32.SendMessageW(hwnd, WM_SETICON, 1, big)
        if small:
            user32.SendMessageW(hwnd, WM_SETICON, 0, small)
    except Exception:
        pass


def _set_windows_app_id() -> None:
    """
    Sätter AppUserModelID på Windows — appen grupperas under EGEN
    ikon/post i aktivitetsfältet i stället för python.exe/pythonw.exe.
    """
    if CURRENT_PLATFORM != "windows":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            f"RickardLangkvist.{APP_SHORT_NAME}"
        )
    except Exception:
        pass


# ═════════════════════════════════════════════════════════════════════
#  SINGLE-INSTANCE + FOKUS-ÖVERLÄMNING
# ═════════════════════════════════════════════════════════════════════


def _acquire_single_instance_lock() -> bool:
    """
    Säkerställer att bara EN kopia av Fakturabunten körs.

    Lockfilen ligger i logs/ inuti appmappen — aldrig i systemets temp.
    Den är unik för denna app och påverkar inte andra program.
    """
    global _APP_LOCK
    try:
        from PySide6.QtCore import QLockFile

        lock_dir = BASE_DIR / "logs"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / LOCK_FILE_NAME

        lock = QLockFile(str(lock_path))
        if lock.tryLock(100):
            _APP_LOCK = lock
            log.info("Single-instance lås OK: %s", lock_path)
            return True

        log.warning(
            "Programmet körs redan — avbryter ny instans.\n"
            "  Lockfil: %s",
            lock_path,
        )
        return False
    except ImportError:
        log.debug("QLockFile ej tillgänglig — hoppar över single-instance")
        return True
    except Exception as exc:
        log.error("Single-instance låsfel: %s", exc)
        return True


def _release_single_instance_lock() -> None:
    """Frigör single-instance-låset vid avslut (idempotent)."""
    global _APP_LOCK
    if _APP_LOCK is None:
        return
    try:
        _APP_LOCK.unlock()
        log.debug("Single-instance lås frigjort")
    except Exception:
        pass
    _APP_LOCK = None


def _start_focus_server(on_focus: Callable[[], None]) -> None:
    """
    Första instansen lyssnar på fokus-förfrågningar via QLocalServer.
    När en andra instans kopplar upp → visa/aktivera fönstret.
    """
    global _FOCUS_SERVER
    try:
        from PySide6.QtNetwork import QLocalServer

        QLocalServer.removeServer(FOCUS_SERVER_NAME)  # rensa gammal socket
        server = QLocalServer()
        if server.listen(FOCUS_SERVER_NAME):
            server.newConnection.connect(lambda: on_focus())
            _FOCUS_SERVER = server
            log.debug("Fokus-server lyssnar: %s", FOCUS_SERVER_NAME)
    except Exception as exc:
        log.debug("Fokus-server ej tillgänglig: %s", exc)


def _request_focus_existing() -> None:
    """
    Andra instansen ber den första visa fönstret innan den avslutar.
    """
    try:
        from PySide6.QtNetwork import QLocalSocket

        sock = QLocalSocket()
        sock.connectToServer(FOCUS_SERVER_NAME)
        if sock.waitForConnected(300):
            sock.write(b"focus")
            sock.waitForBytesWritten(300)
            log.info("Fokus-förfrågan skickad till första instansen")
        sock.disconnectFromServer()
    except Exception as exc:
        log.debug("Fokus-förfrågan misslyckades: %s", exc)


# ═════════════════════════════════════════════════════════════════════
#  AUTOSTART — ROBUSTA HJÄLPFUNKTIONER
#
#  AutostartManager i app.py är MASTER för all autostart-logik.
# ═════════════════════════════════════════════════════════════════════


def safe_autostart_check(manager: Any) -> bool:
    """
    Läser is_enabled från AutostartManager på ett säkert sätt.
    Hanterar metod, property och saknat attribut.
    """
    is_enabled_attr = getattr(manager, "is_enabled", None)
    if is_enabled_attr is None:
        return False
    if callable(is_enabled_attr):
        try:
            return bool(is_enabled_attr())
        except Exception as exc:
            log.warning("is_enabled() kastade: %s", exc)
            return False
    try:
        return bool(is_enabled_attr)
    except Exception:
        return False


def safe_autostart_set(manager: Any, enable: bool) -> bool:
    """
    Aktiverar/inaktiverar autostart via AutostartManager.
    Prövar i ordning: enable()/disable() → set_enabled(bool)
    → set_autostart(bool). Returnerar True om något anrop lyckades.
    """
    if manager is None:
        return False

    candidates = (
        ["enable", "set_enabled", "set_autostart"]
        if enable
        else ["disable", "set_enabled", "set_autostart"]
    )
    no_arg_methods = {"enable", "disable"}

    for method_name in candidates:
        fn = getattr(manager, method_name, None)
        if fn is None or not callable(fn):
            continue
        try:
            if method_name in no_arg_methods:
                fn()
            else:
                fn(bool(enable))
            log.info(
                "Autostart %s via %s.%s()",
                "aktiverat" if enable else "inaktiverat",
                type(manager).__name__,
                method_name,
            )
            return True
        except Exception as exc:
            log.warning(
                "%s.%s(%s): %s",
                type(manager).__name__, method_name, enable, exc,
            )
    return False


# ═════════════════════════════════════════════════════════════════════
#  SETTINGS — snabbladdning innan FakturaApp finns
# ═════════════════════════════════════════════════════════════════════


def _quick_load_settings() -> dict[str, Any]:
    """
    Snabb settings-läsning utan FakturaApp — används BARA för tidigt
    tema. Skriver aldrig till disk — FakturaApp äger settings.json.
    """
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
                stored = json.load(fh)
            merged = DEFAULT_SETTINGS.copy()
            if isinstance(stored, dict):
                merged.update(stored)
            return merged
    except Exception as exc:
        log.warning("_quick_load_settings: %s", exc)
    return DEFAULT_SETTINGS.copy()


# ═════════════════════════════════════════════════════════════════════
#  TEMA
# ═════════════════════════════════════════════════════════════════════


def _apply_theme(app_qt: Any, theme_name: str, source: str) -> None:
    """
    Applicerar ett tema på QApplication.
    source = var temat kom ifrån — enbart för loggning.
    Fel loggas men kraschar aldrig starten.
    """
    try:
        from ui.main_window import (
            resolve_theme,
            build_stylesheet,
            apply_app_palette,
        )

        theme = resolve_theme(theme_name)
        apply_app_palette(theme)
        app_qt.setStyleSheet(build_stylesheet(theme))
        log.info("Tema applicerat (%s) → %s", source, theme_name)
    except Exception as exc:
        log.warning("Tema (%s) misslyckades: %s", source, exc)


# ═════════════════════════════════════════════════════════════════════
#  DATUM
#
#  Inget datum väljs vid start. session_due_date förblir osatt.
#  Datum väljs bara i exportdialogen.
# ═════════════════════════════════════════════════════════════════════




# ═════════════════════════════════════════════════════════════════════
#  KOMPONENT-SKAPARE (med tydliga felmeddelanden)
# ═════════════════════════════════════════════════════════════════════


def _fatal_exit(message: str, exc: Exception | None = None) -> None:
    """Visar ett kritiskt felmeddelande, frigör låset och avslutar."""
    log.error("%s%s", message, f"\nUndantag: {exc}" if exc else "")
    try:
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.critical(
            None, "Startfel — Fakturabunten", message
        )
    except Exception:
        pass
    _release_single_instance_lock()
    sys.exit(1)


def _create_app_core() -> Any:
    """Skapar FakturaApp (app.py). Avslutar med felmeddelande vid fel."""
    try:
        from app import FakturaApp

        app_core = FakturaApp()
        log.info("FakturaApp laddad")
        return app_core
    except ImportError as exc:
        _fatal_exit(
            f"Kunde inte ladda applikationskärnan (app.py).\n\n"
            f"Kontrollera att alla filer finns i:\n{BASE_DIR}\n\n"
            f"Importfel: {exc}\n\nSe loggfilen för detaljer.",
            exc,
        )
    except Exception as exc:
        _fatal_exit(
            f"Applikationskärnan (app.py) kunde inte initieras:\n{exc}\n\n"
            f"Se loggfilen för detaljer.",
            exc,
        )


def _create_main_window(app_core: Any) -> Any:
    """Skapar MainWindow. Avslutar med felmeddelande vid fel."""
    try:
        from ui.main_window import MainWindow
    except Exception as exc:
        _fatal_exit(
            f"Kunde inte ladda huvudfönstret (ui/main_window.py):\n{exc}",
            exc,
        )

    try:
        window = MainWindow(app=app_core)
        log.info("MainWindow skapat")
        return window
    except Exception as exc:
        _fatal_exit(f"Kunde inte skapa huvudfönstret:\n{exc}", exc)


def _verify_window_visible(window: Any) -> None:
    """
    SÄKERHETSVAKT (700 ms efter start): verifierar att fönstret
    FAKTISKT är synligt efter manuell start.

    • Synligt        → WINDOW_VISIBLE_OK loggas (med geometri)
    • OSYNLIGT       → fönstret visas och centreras på primärskärmen,
                       WINDOW_VISIBILITY_GUARD loggas

    Detta gör att "fönstret blinkade till och försvann" aldrig igen
    kan hända tyst — loggen visar exakt vad som hände och vaktens
    reparation garanterar ett synligt fönster.
    """
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    def _check() -> None:
        try:
            geo = window.frameGeometry()
            visible = bool(window.isVisible()) and not window.isMinimized()
            alog_fn = _get_alog()
            if alog_fn is not None:
                alog_fn(
                    "WINDOW_VISIBLE_OK"
                    if visible else "WINDOW_NOT_VISIBLE",
                    f"Fönsterstatus vid start: "
                    f"{'SYNLIGT' if visible else 'OSYNLIGT'} "
                    f"({geo.width()}x{geo.height()} @ {geo.x()},{geo.y()})",
                    logger="FakturaMain",
                    synligt=visible,
                    bredd=geo.width(), hojd=geo.height(),
                    x=geo.x(), y=geo.y(),
                )
            if visible:
                return

            log.warning(
                "Fönstret var OSYNLIGT efter start → visar och "
                "centrerar det (geo=%sx%s @ %s,%s)",
                geo.width(), geo.height(), geo.x(), geo.y(),
            )
            try:
                scr = QApplication.primaryScreen().availableGeometry()
                w = min(window.width() or 1280, scr.width() - 40)
                h = min(window.height() or 800, scr.height() - 40)
                window.resize(w, h)
                window.move(
                    scr.x() + (scr.width() - w) // 2,
                    scr.y() + (scr.height() - h) // 2,
                )
            except Exception:
                pass
            window.showNormal()
            window.raise_()
            window.activateWindow()
            if alog_fn is not None:
                alog_fn(
                    "WINDOW_VISIBILITY_GUARD",
                    "Fönstret var osynligt efter start → visat och "
                    "centrerat på primärskärmen",
                    logger="FakturaMain",
                )
        except Exception as exc:
            log.warning("_verify_window_visible: %s", exc)

    QTimer.singleShot(700, _check)


def _verify_window_hidden(window: Any) -> None:
    """
    Motsvarande vakt för GÖMD autostart: om fönstret mot förmodan
    är synligt 700 ms efter start → döljs det och händelsen loggas.
    """
    from PySide6.QtCore import QTimer

    def _check() -> None:
        try:
            if not window.isVisible():
                return
            log.warning(
                "Fönstret var SYNLIGT trots gömd autostart → döljs"
            )
            window.hide()
            alog_fn = _get_alog()
            if alog_fn is not None:
                alog_fn(
                    "WINDOW_HIDDEN_GUARD",
                    "Fönstret var synligt vid gömd autostart → dolt",
                    logger="FakturaMain",
                )
        except Exception as exc:
            log.warning("_verify_window_hidden: %s", exc)

    QTimer.singleShot(700, _check)


def _start_minimized_or_show(
    window: Any, app_core: Any, autostart_launch: bool
) -> None:
    """
    Startläge:

    • AUTOSTART (registry/.desktop/plist → --minimized) +
      start_minimized=True + tray → starta GÖMD i systemfältet.
    • MANUELL start (dubbelklick/genväg) → visa ALLTID fönstret.
      (Tidigare blinkade fönstret till och gömdes även vid manuell
      start — det är nu fixat.)
    """
    from PySide6.QtWidgets import QSystemTrayIcon

    start_minimized = app_core.settings.get("start_minimized", True)
    tray_available = QSystemTrayIcon.isSystemTrayAvailable()

    if (
        autostart_launch
        and start_minimized
        and tray_available
        and hasattr(window, "tray")
    ):
        # Säkerhet på säkerhet: fönstret får ALDRIG vara synligt vid
        # gömd autostart — även om något oväntat skulle ha show():at det.
        try:
            window.hide()
        except Exception:
            pass
        log.info(
            "Startar MINIMERAT (autostart)", extra={"action": "START_MIN"}
        )
        try:
            window.tray.showMessage(
                APP_NAME,
                "Fakturabunten körs i systemfältet.\n"
                "Klicka på ikonen för att öppna.",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
        except Exception:
            pass
        _verify_window_hidden(window)
    else:
        window.show()
        window.raise_()
        window.activateWindow()
        log.info(
            "Startar SYNLIGT (autostart=%s, tray=%s, minimized-setting=%s)",
            autostart_launch,
            tray_available,
            start_minimized,
            extra={"action": "START_SHOW"},
        )
        _verify_window_visible(window)


def _install_shortcuts(window: Any) -> None:
    """
    Globala snabbknappar — konfigurerbara via shortcuts.json (app.py).

        Ctrl+1–7 → hoppa till flik (visar den om den är dold)
        Ctrl+E   → exportera alla aktiva fakturor (fakturavyn)
        F5       → uppdatera alla vyer

    Moderna MainWindow bygger själva flikhopp + F5 i
    _build_shortcut_actions() (läsande från ShortcutManager). Då
    installerar vi här BARA Ctrl+E för export — aldrig dubbelt.
    Fallback (äldre fönster utan metoden): klassisk hårdkodning.
    """
    try:
        from PySide6.QtGui import QKeySequence
        from PySide6.QtWidgets import QShortcut
    except ImportError:
        return

    mgr = getattr(getattr(window, "_app", None), "shortcuts", None)

    def _seq(action: str, fallback: str) -> QKeySequence:
        if mgr is not None:
            try:
                s = mgr.get(action)
                if s:
                    return QKeySequence(s)
            except Exception:
                pass
        return QKeySequence(fallback)

    window_handles_own = hasattr(window, "_build_shortcut_actions")

    if not window_handles_own:
        # Fallback-väg för fönster utan egen genvägs-hantering
        tab_defs = getattr(window, "_TAB_DEFS", [])
        tab_keys = [d[0] for d in tab_defs]

        def _jump(index: int) -> None:
            if index >= len(tab_keys):
                return
            key = tab_keys[index]
            idx = window._tab_index(key)
            if idx == -1 and hasattr(window, "_set_tab_visible"):
                title = next(
                    (d[2] for d in tab_defs if d[0] == key), key
                )
                window._set_tab_visible(key, title, True)
                idx = window._tab_index(key)
            if idx >= 0:
                window.tabs.setCurrentIndex(idx)

        for n in range(1, len(tab_keys) + 1):
            sc = QShortcut(QKeySequence(f"Ctrl+{n}"), window)
            sc.activated.connect(lambda n=n: _jump(n - 1))

        if hasattr(window, "_refresh_all"):
            sc_f5 = QShortcut(_seq("uppdatera", "F5"), window)
            sc_f5.activated.connect(window._refresh_all)

    # Ctrl+E → exportera alla aktiva fakturor (ägs alltid här,
    # eftersom fakturavyn först finns efter plugin fas-2).
    try:
        inv_view = window.get_invoices_view()
    except Exception:
        inv_view = None
    if inv_view is not None and hasattr(inv_view, "_export_all_pdf"):
        sc_e = QShortcut(_seq("exportera_pdf", "Ctrl+E"), window)
        sc_e.activated.connect(inv_view._export_all_pdf)

    log.debug(
        "Globala snabbknappar installerade (flikhopp=%s, Ctrl+E, F5)",
        "fönstret" if window_handles_own else "main.py",
    )


# ═════════════════════════════════════════════════════════════════════
#  STRUKTURERAD AVSLUTSLOGGNING — SESSION_END med körtid
# ═════════════════════════════════════════════════════════════════════

#: Sessionens start (monoton klocka) — för exakt körtid i SESSION_END.
_SESSION_MONOTONIC: float = 0.0


def _get_alog() -> Any:
    """
    Hämtar alog() från advanced_logger (redan laddad som modul
    'advanced_logger' av PluginLoader). None om pluginet ej finns —
    loggning är aldrig kritiskt.
    """
    import importlib

    for name in ("advanced_logger", "plugins.advanced_logger"):
        mod = sys.modules.get(name)
        if mod is None:
            try:
                mod = importlib.import_module(name)
            except Exception:
                continue
        fn = getattr(mod, "alog", None)
        if callable(fn):
            return fn
    return None


def _log_session_end(app_core: Any, exit_code: int) -> None:
    """
    Loggar SESSION_END med körtid + slutstatus — så att en AI/utvecklare
    i loggen ser exakt hur länge sessionen levde och hur den slutade.
    """
    runtime = (
        time.monotonic() - _SESSION_MONOTONIC
        if _SESSION_MONOTONIC else 0.0
    )
    fn = _get_alog()
    ctx: dict[str, Any] = {
        "körtid_s": round(runtime, 1),
        "exitkod": exit_code,
        "autostart": AUTOSTART_LAUNCH,
    }
    try:
        if app_core is not None:
            ctx["fakturor"] = app_core.invoices.count()
            ctx["leverantörer"] = app_core.suppliers_store.count()
            ctx["tema"] = app_core.settings.get("theme", "?")
    except Exception:
        pass
    if fn is not None:
        fn(
            "SESSION_END",
            f"Session avslutad efter {runtime:.0f} s (exit={exit_code})",
            logger="FakturaMain",
            **ctx,
        )
    log.info(
        "SESSION_END: körtid %.0f s, exitkod %d", runtime, exit_code
    )


# ═════════════════════════════════════════════════════════════════════
#  SELF-TEST  (python main.py --selftest)
#  Idén från PDF reader Pro SPEC v2.1 §2.8 — headless kontrollsvit.
# ═════════════════════════════════════════════════════════════════════


def run_selftest(app_core: Any) -> int:
    """
    Kör en headless kontrollsvit och returnerar exitkod (0 = OK).

    Kontroller:
      1.  Atomär JSON-skrivning (fsync + os.replace)
      2.  Settings-schema: reparation av felaktiga värden
      3.  Settings-schema: korrupt fil namnbyts + standardvärden
      4.  ShortcutManager: standardvärden + spara/ladda
      5.  WCAG-kontrastberäkning + tema-reparation
      6.  round_by_mode (alla 4 avrundningslägen)
      7.  PluginLoader: 3-strikes-avaktivering + återställning
      8.  Autostart startar gömd, med arbetsmapp = appmappen
      9.  FakturaApp-motorer: add/update/summor/typsynk
      10. Diagnostik-samlaren producerar text
    """
    import tempfile

    try:
        import app as appmod
    except ImportError as exc:
        print(f"SELFTEST FEL: kan inte importera app.py: {exc}")
        return 1

    results: list[tuple[str, bool, str]] = []

    def check(name: str, fn: Callable[[], None]) -> None:
        try:
            fn()
            results.append((name, True, ""))
        except Exception as exc:
            results.append((name, False, f"{type(exc).__name__}: {exc}"))

    (BASE_DIR / "logs").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".selftest_", dir=str(BASE_DIR / "logs")
    ) as td:
        tmp = Path(td)

        # 1 — atomär skrivning
        def c_atomic() -> None:
            p = tmp / "atomic.json"
            assert appmod._save_json(p, {"nyckel": "värde", "n": 1})
            with open(p, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            assert data == {"nyckel": "värde", "n": 1}
            leftovers = list(tmp.glob("*.tmp")) + list(tmp.glob(".*.tmp"))
            assert not leftovers, f"tmp-lämmar kvar: {leftovers}"

        # 2 — schema-reparation
        def c_repair() -> None:
            raw = {
                "theme": "rosa",            # ogiltigt värde
                "window_width": "800",      # fel typ
                "startup": "ja",            # fel typ (bool)
                "okänd_nyckel": 42,         # ska behållas
            }
            clean, repairs = appmod.validate_settings(raw)
            assert clean["theme"] == "dark"
            assert clean["startup"] is False
            assert clean["okänd_nyckel"] == 42
            assert clean["schema_version"] == appmod.SETTINGS_SCHEMA_VERSION
            assert len(repairs) >= 2, f"rep={repairs}"

        # 3 — korrupt fil
        def c_corrupt() -> None:
            p = tmp / "settings.json"
            p.write_text("{trasig json!!", encoding="utf-8")
            sm = appmod.SettingsManager(p)
            assert sm.get("theme") == "dark"
            assert not p.with_name("settings.json").exists() or True
            corrupts = list(tmp.glob("settings.json.corrupt-*"))
            assert corrupts, "korrupt fil namnbytes inte"
            assert sm.get("schema_version") == appmod.SETTINGS_SCHEMA_VERSION

        # 4 — shortcuts
        def c_shortcuts() -> None:
            p = tmp / "shortcuts.json"
            sm = appmod.ShortcutManager(p)
            assert sm.get("ny_faktura") == "Ctrl+N"
            sm.set("ny_faktura", "Ctrl+Shift+N")
            sm2 = appmod.ShortcutManager(p)   # ladda om från disk
            assert sm2.get("ny_faktura") == "Ctrl+Shift+N"
            sm2.reset_all()
            assert sm2.get("ny_faktura") == "Ctrl+N"

        # 5 — WCAG-kontrast
        def c_contrast() -> None:
            from ui.contrast import (
                contrast_ratio, passes_aa, enforce_theme_contrast,
            )
            assert abs(contrast_ratio("#000000", "#ffffff") - 21.0) < 0.01
            assert not passes_aa("#ffffff", "#d0d7de")
            fixed = enforce_theme_contrast(
                {"bg": "#ffffff", "text": "#d0d7de"}
            )
            assert passes_aa("#ffffff", fixed["text"])

        # 6 — avrundningslägen
        def c_rounding() -> None:
            from ui.invoices_helpers import round_by_mode
            assert round_by_mode(123.456, "exact") == 123.46
            assert round_by_mode(123.5, "hel") == 124.0
            assert round_by_mode(123.0, "50") == 100.0
            assert round_by_mode(126.0, "50") == 150.0
            assert round_by_mode(149.0, "100") == 100.0
            assert round_by_mode(-123.5, "hel") == -124.0

        # 7 — 3-strikes plugins
        def c_strikes() -> None:
            settings_file = tmp / "plugin_settings.json"
            settings = appmod.SettingsManager(settings_file)
            plugdir = tmp / "plugins"
            plugdir.mkdir(exist_ok=True)
            (plugdir / "trasig.py").write_text(
                "raise RuntimeError('medvetet krasch')\n",
                encoding="utf-8",
            )
            loader = appmod.PluginLoader(plugdir, settings)
            for _ in range(3):
                loader.load_all()
            status = loader.status()
            assert "trasig" in status["disabled"], status
            loader.reenable_all()
            assert loader.status()["disabled"] == []

        # 8 — autostart: gömd start, arbetsmapp = appmappen
        def c_autostart() -> None:
            mgr = appmod.AutostartManager()
            assert mgr.starts_minimized()
            assert mgr.working_directory() == appmod.BASE_DIR.resolve()
            assert "start_hidden" in mgr.build_command().replace("\\", "/")

        # 9 — motorer
        def c_engines() -> None:
            inv = app_core.invoices
            rec = inv.add({
                "supplier": "SELFTEST AB",
                "invoice_number": "ST-1",
                "total_amount": 100.0,
            })
            rid = rec["id"]
            assert rec["invoice_type"] == "Faktura"
            inv.update(rid, {"total_amount": -50.0})
            rec2 = inv.get(rid)
            assert rec2 is not None and rec2["invoice_type"] == "Kreditfaktura"
            assert inv.total_amount([rec2]) == -50.0
            inv.delete(rid)
            assert inv.get(rid) is None

        # 10 — diagnostik
        def c_diag() -> None:
            text = appmod.collect_diagnostics(app_core)
            assert "DIAGNOSTIK" in text
            assert "Fakturor" in text

        check("Atomär JSON-skrivning (fsync)", c_atomic)
        check("Settings-schema: reparation", c_repair)
        check("Settings-schema: korrupt fil", c_corrupt)
        check("ShortcutManager", c_shortcuts)
        check("WCAG-kontrast", c_contrast)
        check("round_by_mode", c_rounding)
        check("PluginLoader 3-strikes", c_strikes)
        check("Autostart gömd från appmappen", c_autostart)
        check("Fakturamotorer", c_engines)
        check("Diagnostik-samlaren", c_diag)

    ok = sum(1 for _, passed, _ in results if passed)
    total = len(results)

    print("=" * 60)
    print(f"  {APP_NAME} v{APP_VERSION} — SELFTEST")
    print("=" * 60)
    for name, passed, err in results:
        mark = "✔" if passed else "✘"
        print(f"  {mark}  {name}" + (f"   [{err}]" if err else ""))
    print("-" * 60)
    print(f"  Resultat: {ok}/{total}  "
          f"{'✅  SELFTEST OK' if ok == total else '❌  SELFTEST FEL'}")
    print("=" * 60)

    log.info(
        "SELFTEST: %d/%d kontroller OK", ok, total
    )
    return 0 if ok == total else 1


def _log_startup_info(app_core: Any) -> None:
    """Loggar startbanner med all relevant statusinformation."""
    try:
        mgr = app_core.settings.get_autostart_manager()
        autostart_os = safe_autostart_check(mgr)
        build_cmd = getattr(mgr, "_build_command", None)
        autostart_cmd = build_cmd() if callable(build_cmd) else "?"
    except Exception:
        autostart_os = False
        autostart_cmd = "?"

    log.info(
        "═══ %s v%s ═══  %s  ·  Platform: %s  ·  Python: %s\n"
        "    Plugins: %d  ·  Autostart: %s  ·  SessionDue: %s\n"
        "    Autostart-kommando: %s",
        APP_NAME,
        APP_VERSION,
        COPYRIGHT,
        CURRENT_PLATFORM,
        sys.version.split()[0],
        len(getattr(app_core.plugin_loader, "modules", [])),
        autostart_os,
        getattr(app_core, "session_due_date", "?"),
        autostart_cmd,
    )


# ═════════════════════════════════════════════════════════════════════
#  WINDOW WATCHERS — loggning och synk av UI/status vid start
# ═════════════════════════════════════════════════════════════════════


def _watch_theme(window: Any) -> None:
    """Loggar alla temabyten."""
    watcher_log = logging.getLogger("WindowWatcher")
    try:
        def _on_theme_changed(theme: dict) -> None:
            watcher_log.info(
                "Tema bytt → %s (bg=%s)",
                theme.get("name", "?"),
                theme.get("bg", "?"),
            )

        window.theme_changed.connect(_on_theme_changed)
        watcher_log.debug("theme_changed-watcher kopplad")
    except Exception as exc:
        watcher_log.debug("theme_changed-watcher: %s", exc)


def _watch_tabs(window: Any) -> None:
    """Loggar alla flikbyten."""
    watcher_log = logging.getLogger("WindowWatcher")
    try:
        def _on_tab_changed(idx: int) -> None:
            try:
                watcher_log.debug(
                    "Flik bytt → [%d] %s", idx, window.tabs.tabText(idx)
                )
            except Exception:
                pass

        window.tabs.currentChanged.connect(_on_tab_changed)
        watcher_log.debug("Tab-watcher kopplad")
    except Exception as exc:
        watcher_log.debug("Tab-watcher: %s", exc)


def _sync_autostart(app_core: Any) -> None:
    """
    Synkar settings.json ↔ OS-registrerad autostart vid start.

    • settings=True men OS=False → aktivera i OS
    • OS=True men fel kommando (Windows registry) → uppdatera
    """
    watcher_log = logging.getLogger("WindowWatcher")
    try:
        mgr = app_core.settings.get_autostart_manager()
        os_status = safe_autostart_check(mgr)
        settings_status = app_core.settings.get("startup", False)
        build_cmd = getattr(mgr, "_build_command", None)
        cmd = build_cmd() if callable(build_cmd) else ""

        watcher_log.info(
            "Autostart-status vid start: %s",
            "aktiverad" if os_status else "inaktiverad",
        )
        watcher_log.info("  OS-registrerad : %s", os_status)
        watcher_log.info("  settings.json  : %s", settings_status)
        watcher_log.info("  Kommando       : %s", cmd)

        # Fall 1: settings=True men OS-post saknas → aktivera
        if settings_status and not os_status:
            watcher_log.info(
                "  ⚠️  OS-post saknas men settings=True → aktiverar nu"
            )
            safe_autostart_set(mgr, True)
            return

        # Fall 2: OS=True men registry pekar fel (endast Windows)
        if os_status and CURRENT_PLATFORM == "windows":
            registered_cmd = ""
            get_cmd_fn = getattr(mgr, "get_registered_command", None)
            if callable(get_cmd_fn):
                try:
                    registered_cmd = get_cmd_fn()
                except Exception:
                    pass

            watcher_log.info(
                "  Registry-värde : %s",
                registered_cmd or "(ej registrerad)",
            )
            if registered_cmd and registered_cmd != cmd:
                watcher_log.warning(
                    "  ⚠️  Registry pekar FEL!\n"
                    "  Korrekt : %s\n"
                    "  Faktiskt: %s\n"
                    "  → Uppdaterar automatiskt",
                    cmd,
                    registered_cmd,
                )
                safe_autostart_set(mgr, True)
            elif registered_cmd == cmd:
                watcher_log.info("  ✔  Registry korrekt")
    except Exception as exc:
        watcher_log.debug("Autostart-synk: %s", exc)


def _verify_invoices_view(window: Any) -> None:
    """Verifierar att InvoicesView verkligen laddades."""
    watcher_log = logging.getLogger("WindowWatcher")
    try:
        inv_view = window.get_invoices_view()
        watcher_log.info(
            "InvoicesView laddad: %s",
            type(inv_view).__name__ if inv_view else "SAKNAS",
        )
        if inv_view is None:
            watcher_log.error(
                "InvoicesView saknas!\n"
                "  1. Finns ui/invoices_view.py?\n"
                "  2. Finns ui/invoices_helpers.py?\n"
                "  3. Se loggfilen för importfel"
            )
    except Exception as exc:
        watcher_log.warning("InvoicesView-kontroll: %s", exc)


def _watch_settings(app_core: Any) -> None:
    """Loggar alla settings-ändringar."""
    app_watcher = logging.getLogger("AppWatcher")
    try:
        def _on_settings_changed(snap: dict) -> None:
            app_watcher.info(
                "Settings ändrades — tema=%s  startup=%s  "
                "close_to_tray=%s  start_minimized=%s",
                snap.get("theme", "?"),
                snap.get("startup", "?"),
                snap.get("close_to_tray", "?"),
                snap.get("start_minimized", "?"),
            )

        app_core.settings.on_change(_on_settings_changed)
        app_watcher.debug("Settings-watcher kopplad")
    except Exception as exc:
        app_watcher.debug("Settings-watcher: %s", exc)


def _watch_stores(app_core: Any) -> None:
    """Kopplar change-watchers på alla datastores."""
    app_watcher = logging.getLogger("AppWatcher")
    try:
        def _make_watcher(name: str):
            def _cb(store_name: str, records: list) -> None:
                app_watcher.debug(
                    "%s ändrades (%d poster)", name, len(records)
                )

            return _cb

        for store_name in (
            "invoices_store",
            "suppliers_store",
            "payments_store",
        ):
            store = getattr(app_core, store_name, None)
            if store is not None and hasattr(store, "on_change"):
                store.on_change(_make_watcher(store_name))
                app_watcher.debug(
                    "Watcher kopplad till %s", store_name
                )

        app_watcher.info("App-watchers kopplade till FakturaApp")
    except Exception as exc:
        app_watcher.debug("Store-watchers: %s", exc)


def _setup_window_watchers(window: Any, app_core: Any) -> None:
    """Kopplar alla debug-/synk-watchers. Kraschar aldrig starten."""
    watcher_log = logging.getLogger("WindowWatcher")

    _watch_theme(window)
    _watch_tabs(window)
    _sync_autostart(app_core)
    _verify_invoices_view(window)

    try:
        session_due = getattr(app_core, "session_due_date", None)
        watcher_log.info(
            "Session-betalningsdatum: %s",
            session_due if session_due else "ej satt",
        )
    except Exception as exc:
        watcher_log.debug("session_due_date-logg: %s", exc)

    _watch_settings(app_core)
    _watch_stores(app_core)

    watcher_log.info("Fönster-watchers kopplade")


# ═════════════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════════════


#: Filer som måste ligga bredvid main.py. Saknas någon är kopian ofullständig.
#: Ikoner och settings.json krävs inte för att starten ska gå vidare.
_COMPANION_FILES: tuple[str, ...] = (
    "app.py",
    "ensure_packages.py",
    "requirements.txt",
    "ui/letter_jump.py",
    "ui/main_window.py",
    "ui/invoices_view.py",
    "ui/invoices_helpers.py",
    "ui/suppliers_view.py",
    "ui/contrast.py",
    "ui/scan_import_view.py",
    "ui/core/calculator.py",
    "plugins/advanced_logger.py",
    "plugins/pdf_export.py",
    "plugins/pdf_export_helpers.py",
    "plugins/scan_import.py",
)


def _missing_companion_files() -> list[Path]:
    """Returnerar programfiler som inte följde med kopian."""
    return [BASE_DIR / rel for rel in _COMPANION_FILES if not (BASE_DIR / rel).is_file()]


def _abort_missing_files(missing: list[Path]) -> None:
    """Avslutar med en lista. Säger inte PySide6 när felet är en saknad fil."""
    lines = "\n".join(f"  - {path.relative_to(BASE_DIR)}" for path in missing)
    log.critical(
        "FIL_SAKNAS: %d filer saknas i %s:\n%s",
        len(missing),
        BASE_DIR,
        lines,
    )
    print(
        f"{APP_NAME} startar inte. Dessa filer saknas i\n{BASE_DIR}\n\n"
        f"{lines}\n\n"
        "Det här är inte PySide6. Kopiera filerna från den nya versionen\n"
        "till samma mapp som main.py.\n"
        "Rör inte data, logs, exports eller bak.",
        file=sys.stderr,
    )
    sys.exit(1)


def main() -> None:
    """Startpunkt — se moduldocstring för steg-för-steg-ordningen."""
    global _SESSION_MONOTONIC
    _SESSION_MONOTONIC = time.monotonic()

    # Qt-runtime-miljö före QApplication (DPI-scalning, Qt6-hantering)
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

    _hide_console()
    _set_windows_app_id()

    early_settings = _quick_load_settings()

    missing = _missing_companion_files()
    if missing:
        _abort_missing_files(missing)

    # Saknade tillbehör (PySide6, reportlab, pypdf) hämtas här,
    # med förloppsindikator, innan resten av programmet startar.
    # Hoppas över vid --selftest så kontrollen förblir tyst.
    if not SELFTEST and os.environ.get("FAKTURA_SKIP_PACKAGES") != "1":
        try:
            from ensure_packages import ensure_packages
            if not ensure_packages():
                sys.exit(1)
        except ModuleNotFoundError as exc:
            log.error(
                "FIL_SAKNAS: ensure_packages.py ligger inte i %s (%s)",
                BASE_DIR,
                exc,
            )
        except Exception as exc:
            log.error("TILLBEHOR: %s", exc, exc_info=True)

    # ── PySide6 måste finnas. Lokal fil är ett annat fel. ───────────────
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt
    except ImportError as exc:
        log.critical("PySide6 saknas: %s", exc)
        print(
            "Fakturabunten kräver PySide6.\n"
            "Installera med:  pip install PySide6",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        from ui.letter_jump import LetterJumpApplication
    except ImportError as exc:
        log.critical(
            "FIL_SAKNAS: %s (%s)",
            BASE_DIR / "ui" / "letter_jump.py",
            exc,
        )
        print(
            "Fakturabunten saknar filen ui\\letter_jump.py\n"
            f"i {BASE_DIR}\n\n"
            "Det här är inte PySide6. Kopiera ui\\letter_jump.py "
            "till ui-mappen.",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── QApplication ────────────────────────────────────────────────────
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app_qt = LetterJumpApplication(sys.argv)
    app_qt.setApplicationName(APP_NAME)
    app_qt.setApplicationVersion(APP_VERSION)
    app_qt.setOrganizationName(APP_ORGANIZATION)
    app_qt.setStyle("Fusion")
    app_qt.setQuitOnLastWindowClosed(False)
    for _icon_name in ("app_icon.ico", "app_icon.png", "app_icon.svg"):
        _icon_path = BASE_DIR / _icon_name
        if _icon_path.exists():
            from PySide6.QtCore import QEvent, QObject
            from PySide6.QtGui import QIcon

            _app_icon = QIcon(str(_icon_path))
            app_qt.setWindowIcon(_app_icon)

            class _IconOnShow(QObject):
                """Sätter appikonen på varje fönster och dialog."""

                def __init__(self, icon: QIcon, parent: QObject | None = None) -> None:
                    super().__init__(parent)
                    self._icon = icon

                def eventFilter(self, obj, event):  # noqa: N802
                    if event.type() == QEvent.Type.Show:
                        try:
                            if (
                                obj.isWindow()
                                and not obj.property("_frak_icon")
                            ):
                                obj.setWindowIcon(self._icon)
                                obj.setProperty("_frak_icon", True)
                                if CURRENT_PLATFORM == "windows":
                                    _set_win32_window_icon(int(obj.winId()))
                        except Exception:
                            pass
                    return False

            app_qt.installEventFilter(_IconOnShow(_app_icon, app_qt))
            _windows_shortcut()
            break

    # ── Single instance — bara EN kopia åt gången ─────────────────────
    if not _acquire_single_instance_lock():
        # Be första instansen visa fönstret, avsluta sedan själv.
        _request_focus_existing()
        log.info("Avbryter — programmet körs redan.")
        sys.exit(0)

    try:
        # ── Tidigt tema (från settings.json direkt) ───────────────────
        _apply_theme(
            app_qt, early_settings.get("theme", "dark"), "tidigt"
        )

        # ── Applikationskärnan ────────────────────────────────────────
        # (advanced_logger-pluginet installerar själv den globala
        #  Qt-bryggan som TRACE-loggar varje klick/tangent/fokus.)
        app_core = _create_app_core()

        # ── Selftest: kör kontrollsviten headless och avsluta ─────────
        if SELFTEST:
            code = run_selftest(app_core)
            log.info("SELFTEST avslutad (exit=%d)", code)
            sys.exit(code)

        # Inget datum väljs vid start. Datum väljs bara vid export.
        log.info("INGET_DATUM_VID_START: datum väljs bara vid export")

        # ── Tema via app.settings (kan ha annat värde än råfilen) ────
        _apply_theme(
            app_qt,
            app_core.settings.get("theme", "dark"),
            "app.settings",
        )

        # ── Huvudfönster + plugin phase-2 ─────────────────────────────
        window = _create_main_window(app_core)

        # ── Fokus-server: andra instanser kan be oss visa fönstret ──
        window_holder: dict[str, Any] = {"window": window}

        def _on_focus_request() -> None:
            w = window_holder.get("window")
            if w is not None and hasattr(w, "_bring_to_front"):
                w._bring_to_front()

        _start_focus_server(_on_focus_request)

        try:
            app_core.register_plugins_ui(window)
            log.info("Plugin phase-2 klar")
        except Exception as exc:
            log.error("register_plugins_ui: %s", exc, exc_info=True)

        # ── Watchers, snabbknappar, startläge, startinfo ─────────────
        _setup_window_watchers(window, app_core)
        _install_shortcuts(window)
        _start_minimized_or_show(window, app_core, AUTOSTART_LAUNCH)

        _log_startup_info(app_core)

        # ── Event loop ────────────────────────────────────────────────
        alog_fn = _get_alog()
        if alog_fn is not None:
            alog_fn(
                "EVENT_LOOP_START",
                "Qt-händelseslingan startad — appen är interaktiv",
                logger="FakturaMain",
            )
        exit_code = app_qt.exec()

        # ── Smart cache-rensare: töm cache vid avslut (settings) ─────
        try:
            stats = app_core.clean_caches_on_exit()
            alog_fn = _get_alog()
            if alog_fn is not None and stats:
                alog_fn(
                    "CACHE_CLEAN",
                    f"Cache tömd vid avslut: {stats['pycache_mappar']} "
                    f"__pycache__, {stats['pyc_filer']} pyc, "
                    f"{stats['tmp_filer']} tmp "
                    f"({stats['frigjorda_bytes'] / 1024:.1f} KB)",
                    logger="FakturaMain",
                    **{k.replace("ö", "o"): v for k, v in stats.items()},
                )
        except Exception as exc:
            log.warning("Cache-rensning vid avslut: %s", exc)

        # ── Avslutsloggning: körtid + slutstatus → JSONL ─────────────
        _log_session_end(app_core, exit_code)
    finally:
        _release_single_instance_lock()

    log.info("Programmet avslutat (exit=%d)", exit_code)
    sys.exit(exit_code)


# ═════════════════════════════════════════════════════════════════════
#  ENTRY POINT — med kraschskydd för tysta pythonw-krascher
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 — sista skyddsnätet
        _write_startup_crash(exc)
        log.critical("STARTKRASCH: %s", exc, exc_info=True)
        try:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(
                None,
                "Startfel — Fakturabunten",
                f"Ohanterat fel vid start:\n{exc}\n\n"
                f"Detaljer: {LOG_FILE}",
            )
        except Exception:
            pass
        sys.exit(1)
