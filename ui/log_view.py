# -*- coding: utf-8 -*-
"""
LogView — egen flik för systemloggen (felsökning).

Idén: felsökning ska ta sekunder, inte letande i filer.
Vyn läser logs/app.log (JSONL — samma fil som advanced_logger
skriver), visar även FÖREGÅENDE sessioner (krascher syns!), och ger:

* Felbanner med "visa senaste felet" (hoppa direkt till felet)
* Filter: nivå, fritext, endast-fel, endast-denna-session
* 🔖 Markering: tryck Markera → återskapa felet → "Kopiera efter
  markering" ger exakt de rader som hör till felet
* 📋 Felsökningspaket: ETT klick kopierar version, miljö,
  inställningar, dataräkning, senaste felen med tracebacks och
  loggens slut — redo att klistra in i mejl eller AI-chatt.
* Live-uppdatering (pausbar), auto-scroll, detaljruta med
  traceback, export av visade rader och "öppna loggmapp".

De rena hjälpfunktionerna (parse/filter/format) är testbara utan Qt.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from ui.design import ICON_HEADER_PX, app_icon_pixmap, header_font
except Exception:  # pragma: no cover
    ICON_HEADER_PX = 28  # type: ignore[no-redef]

    def app_icon_pixmap(size: int = 28):  # type: ignore[no-redef]
        return QPixmap()

    def header_font():  # type: ignore[no-redef]
        return QFont("Segoe UI", 17, QFont.Weight.Bold)

try:
    from ui.i18n import tr
except Exception:  # pragma: no cover - fristående körning
    try:
        from i18n import tr  # type: ignore[no-redef]
    except Exception:
        def tr(key: str, **_f: object) -> str:  # type: ignore[no-redef]
            return key

log = logging.getLogger("LogView")

#: Max antal rader som läses in från loggfilens slut.
MAX_LINES = 4000

LEVEL_ORDER: dict[str, int] = {
    "TRACE": 5, "DEBUG": 10, "PERF": 10, "INFO": 20,
    "AUDIT": 25, "WARNING": 30, "WARN": 30,
    "ERROR": 40, "CRITICAL": 50, "FATAL": 50,
}

LEVEL_BG: dict[str, str] = {
    "ERROR": "#7a1f1f", "CRITICAL": "#7a1f1f", "FATAL": "#7a1f1f",
    "WARNING": "#6b5410", "WARN": "#6b5410",
    "INFO": "#1d4e2e", "AUDIT": "#274b63", "DEBUG": "#3a3f44",
    "TRACE": "#3a3f44", "PERF": "#4a2d5e",
}

DEFAULT_LOG_FILE = (
    Path(__file__).resolve().parent.parent / "logs" / "app.log"
)


# ═════════════════════════════════════════════════════════════════════
#  RENA HJÄLPARE (testbara utan Qt)
# ═════════════════════════════════════════════════════════════════════

def parse_log_text(text: str) -> list[dict]:
    """JSONL → poster. Icke-JSON-rader behålls som råa INFO-poster."""
    entries: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError("inte ett objekt")
        except Exception:
            entries.append({
                "ts": "", "level": "INFO", "logger": "-",
                "action": "", "msg": line, "raw": line,
            })
            continue
        entries.append({
            "ts": str(obj.get("ts", "") or ""),
            "level": str(obj.get("level", "INFO") or "INFO").upper(),
            "logger": str(obj.get("logger", "-") or "-"),
            "action": str(obj.get("action", "") or ""),
            "msg": str(obj.get("msg", "") or ""),
            "loc": str(obj.get("loc", "") or ""),
            "exc": str(obj.get("exc", "") or ""),
            "ctx": obj.get("ctx") or {},
            "raw": line,
        })
    return entries


def last_session_start(entries: list[dict]) -> str:
    """ts för senaste sessionsstart ('' om ingen hittas)."""
    for e in reversed(entries):
        if e.get("action") == "START" or str(
            e.get("msg", "")
        ).startswith("Programmet startar"):
            return str(e.get("ts", ""))
    return ""


def filter_entries(
    entries: list[dict],
    min_level: str = "ALL",
    search: str = "",
    only_errors: bool = False,
    session_start: str = "",
) -> list[dict]:
    """Filtrerar poster på nivå/sök/fel/session (ISO-ts som sträng)."""
    out: list[dict] = []
    min_no = LEVEL_ORDER.get(str(min_level).upper(), 0) if min_level else 0
    needle = search.strip().lower()
    for e in entries:
        lvl = LEVEL_ORDER.get(str(e.get("level", "INFO")).upper(), 20)
        if only_errors:
            if lvl < LEVEL_ORDER["ERROR"]:
                continue
        elif lvl < min_no:
            continue
        if session_start and str(e.get("ts", "")) < session_start:
            continue
        if needle:
            hay = " ".join([
                str(e.get("msg", "")), str(e.get("logger", "")),
                str(e.get("action", "")), str(e.get("exc", "")),
            ]).lower()
            if needle not in hay:
                continue
        out.append(e)
    return out


def count_levels(entries: list[dict]) -> tuple[int, int]:
    """(antal fel, antal varningar)."""
    errors = sum(
        1 for e in entries
        if LEVEL_ORDER.get(str(e.get("level", "")).upper(), 0)
        >= LEVEL_ORDER["ERROR"]
    )
    warnings = sum(
        1 for e in entries
        if LEVEL_ORDER.get(str(e.get("level", "")).upper(), 0)
        == LEVEL_ORDER["WARNING"]
    )
    return errors, warnings


def format_entry_text(e: dict) -> str:
    """En post som läsbar textrad (+ indenterad traceback)."""
    parts = [
        str(e.get("ts", "")), f"[{e.get('level', 'INFO')}]",
        str(e.get("logger", "-")),
    ]
    if e.get("action"):
        parts.append(str(e["action"]))
    line = "  ".join(p for p in parts if p)
    line += f"  —  {e.get('msg', '')}"
    if e.get("loc"):
        line += f"  ({e['loc']})"
    if e.get("exc"):
        line += "\n" + "\n".join(
            "    " + ln for ln in str(e["exc"]).splitlines()
        )
    return line


def format_entries_text(entries: list[dict]) -> str:
    return "\n".join(format_entry_text(e) for e in entries)


_UI_NOISE_ACTIONS = {"UI_CLICK", "UI_FOCUS", "UI_WHEEL"}


def _is_ui_noise(e: dict) -> bool:
    """Ren UI-trace (klick/fokus/skroll) — buller i ett
    felsökningspaket; den riktiga loggen finns kvar i filen."""
    return (
        str(e.get("logger", "")) == "QtUI"
        and str(e.get("action", "")) in _UI_NOISE_ACTIONS
    )


def _error_key(e: dict) -> str:
    """Gruppnyckel för likadana fel: meddelandets början före
    tillfälliga detaljer (t.ex. temporärfilens slumpnamn i
    "JSON save error (...): [WinError 5] ... 'x.tmp'")."""
    msg = str(e.get("msg", ""))
    head = msg.split(": [", 1)[0]
    return f"{e.get('level', '')}/{e.get('logger', '')}/{head[:110]}"


def _collapse_errors(
    errors: list[dict],
) -> list[tuple[int, dict]]:
    """Slår ihop på varandra följande likadana fel → (antal,
    senaste posten). En felstorm (antivirus-låsning som ger
    samma WinError 5 femton gånger) blir EN rad med ×N i
    paketet i stället för att dränka alla andra fel."""
    groups: list[tuple[str, int, dict]] = []
    for e in errors:
        key = _error_key(e)
        if groups and groups[-1][0] == key:
            k, n, _prev = groups[-1]
            groups[-1] = (k, n + 1, e)
        else:
            groups.append((key, 1, e))
    return [(n, e) for _k, n, e in groups]


def format_diagnostics(
    entries: list[dict], meta: dict[str, Any]
) -> str:
    """
    Felsökningspaketet: miljö + senaste fel + loggslut som ren text.
    Avsett att klistras in i mejl/chatt — bara fakta, inga hemligheter.
    """
    lines: list[str] = []
    lines.append("═══ FAKTURARÄKNAREN — FELSÖKNINGSPAKET ═══")
    for key in (
        "generated", "app", "os", "python", "qt",
        "language", "theme", "log_file", "log_size_kb",
        "suppliers", "invoices", "invoices_active",
        "invoices_archived", "watch_folders",
    ):
        if meta.get(key) not in (None, ""):
            lines.append(f"{key}: {meta[key]}")
    marker = str(meta.get("marker_ts") or "")
    if marker:
        lines.append(f"marker: {marker}")

    if marker:
        scope = [e for e in entries if str(e.get("ts", "")) >= marker]
    else:
        scope = entries

    all_errors = [
        e for e in entries
        if LEVEL_ORDER.get(str(e.get("level", "")).upper(), 0)
        >= LEVEL_ORDER["ERROR"]
    ]
    shown_errors = _collapse_errors(all_errors)[-15:]
    lines.append("")
    lines.append(f"── Senaste fel ({len(shown_errors)}) ──")
    for times, entry in shown_errors:
        text = format_entry_text(entry)
        if times > 1:
            text += f"  (samma fel ×{times})"
        lines.append(text)
    if not shown_errors:
        lines.append("(inga ERROR/CRITICAL i inläst logg)")

    watch_lines = [
        str(x) for x in (meta.get("watch_lines") or [])
    ]
    if watch_lines:
        lines.append("")
        lines.append("── Bevakade mappar ──")
        lines.extend(watch_lines)

    scan_entries = [
        e for e in scope
        if "SCAN_WATCH" in str(e.get("msg", ""))
        or "SCAN_WATCH" in str(e.get("action", ""))
    ][-25:]
    lines.append("")
    lines.append("── Skanning bevakade mappar (SCAN_WATCH) ──")
    if scan_entries:
        lines.extend(format_entry_text(e) for e in scan_entries)
    else:
        lines.append(
            "(inga SCAN_WATCH-rader i inläst logg — ingen "
            "bevakningsskanning har loggats i den här loggfilen)"
        )

    if marker:
        lines.append("")
        lines.append("── Logg efter markering ──")
    else:
        lines.append("")
        lines.append("── Loggens slut (senaste 60) ──")
    tail = scope[-60:]
    cleaned = [e for e in scope if not _is_ui_noise(e)][-60:]
    if cleaned:
        tail = cleaned
    lines.extend(format_entry_text(e) for e in tail)
    lines.append("═══ SLUT ═══")
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════
#  VYN
# ═════════════════════════════════════════════════════════════════════

class LogView(QWidget):
    """Loggflik: historik + live, filter, markering, felsökningspaket."""

    def __init__(
        self,
        app: Any,
        parent: QWidget | None = None,
        log_file: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._app = app
        self._log_file = Path(log_file) if log_file else DEFAULT_LOG_FILE
        self._all_entries: list[dict] = []
        self._shown: list[dict] = []
        self._marker_ts: str = ""
        self._paused = False
        self._dark = True
        self._last_size = -1
        self._last_mtime = 0.0

        self._build_ui()
        self._reload_from_file(scroll_bottom=True)
        self.retranslate()

        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ── UI-bygge ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 10)
        root.setSpacing(8)

        self._lbl_title = QLabel()
        self._lbl_title.setFont(header_font())
        head = QHBoxLayout()
        _pix = app_icon_pixmap(ICON_HEADER_PX)
        if not _pix.isNull():
            _mark = QLabel()
            _mark.setPixmap(_pix)
            _mark.setStyleSheet("background:transparent;")
            head.addWidget(_mark)
        head.addWidget(self._lbl_title)
        head.addStretch()
        root.addLayout(head)

        # Felbanner (dold när inga fel finns)
        banner_row = QHBoxLayout()
        self._lbl_banner = QLabel()
        self._lbl_banner.setWordWrap(True)
        self._lbl_banner.setStyleSheet(
            "background:#5a1d1d; color:#ffd7d7; border:1px solid #a33;"
            " border-radius:6px; padding:6px 10px;"
        )
        self._btn_goto_error = QPushButton()
        self._btn_goto_error.clicked.connect(self._goto_last_error)
        banner_row.addWidget(self._lbl_banner, stretch=1)
        banner_row.addWidget(self._btn_goto_error)
        self._banner_widget = QWidget()
        self._banner_widget.setLayout(banner_row)
        self._banner_widget.setVisible(False)
        root.addWidget(self._banner_widget)

        # Filterrad
        row1 = QHBoxLayout()
        self._lbl_level = QLabel()
        row1.addWidget(self._lbl_level)
        self._cmb_level = QComboBox()
        for name in ("ALL", "TRACE", "DEBUG", "INFO", "WARNING",
                     "ERROR", "CRITICAL"):
            self._cmb_level.addItem(name, name)
        self._cmb_level.setCurrentText("INFO")
        self._cmb_level.currentIndexChanged.connect(self._refresh_table)
        row1.addWidget(self._cmb_level)
        self._search = QLineEdit()
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._refresh_table)
        row1.addWidget(self._search, stretch=1)
        self._chk_errors = QCheckBox()
        self._chk_errors.stateChanged.connect(self._refresh_table)
        row1.addWidget(self._chk_errors)
        self._chk_session = QCheckBox()
        self._chk_session.stateChanged.connect(self._refresh_table)
        row1.addWidget(self._chk_session)
        root.addLayout(row1)

        # Knapprad
        row2 = QHBoxLayout()
        self._btn_refresh = QPushButton()
        self._btn_refresh.clicked.connect(
            lambda: self._reload_from_file(scroll_bottom=True)
        )
        self._btn_pause = QPushButton()
        self._btn_pause.clicked.connect(self._toggle_pause)
        self._btn_mark = QPushButton()
        self._btn_mark.clicked.connect(self._set_marker)
        self._btn_copy_marked = QPushButton()
        self._btn_copy_marked.clicked.connect(self._copy_after_marker)
        self._btn_copy_diag = QPushButton()
        self._btn_copy_diag.clicked.connect(self._copy_diagnostics)
        self._btn_open_dir = QPushButton()
        self._btn_open_dir.clicked.connect(self._open_log_dir)
        self._btn_errors = QPushButton()
        self._btn_errors.clicked.connect(self._collect_all_errors)
        self._btn_export = QPushButton()
        self._btn_export.clicked.connect(self._export_shown)
        self._btn_reset = QPushButton()
        self._btn_reset.clicked.connect(self._reset_filters)
        for b in (self._btn_refresh, self._btn_pause, self._btn_mark,
                  self._btn_copy_marked, self._btn_copy_diag,
                  self._btn_open_dir, self._btn_errors,
                  self._btn_export, self._btn_reset):
            b.setMinimumHeight(34)
            row2.addWidget(b)
        row2.addStretch()
        self._chk_scroll = QCheckBox()
        self._chk_scroll.setChecked(True)
        row2.addWidget(self._chk_scroll)
        root.addLayout(row2)

        # Tabell
        self._table = QTableWidget(0, 5)
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        hdr = self._table.horizontalHeader()
        hdr.setStretchLastSection(True)
        self._table.setColumnWidth(0, 150)
        self._table.setColumnWidth(1, 86)
        self._table.setColumnWidth(2, 140)
        self._table.setColumnWidth(3, 130)
        self._table.itemSelectionChanged.connect(self._on_select)
        self._table.itemDoubleClicked.connect(
            lambda _i: self._copy_selected()
        )
        root.addWidget(self._table, stretch=1)

        # Detaljruta (full post + traceback)
        self._detail = QPlainTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setMaximumHeight(130)
        self._detail.setFont(QFont("Consolas", 9))
        root.addWidget(self._detail)

        row3 = QHBoxLayout()
        self._btn_copy_row = QPushButton()
        self._btn_copy_row.clicked.connect(self._copy_selected)
        row3.addWidget(self._btn_copy_row)
        row3.addStretch()
        self._lbl_info = QLabel()
        row3.addWidget(self._lbl_info)
        root.addLayout(row3)

    # ── Data ──────────────────────────────────────────────────────────

    def _reload_from_file(self, scroll_bottom: bool = False) -> None:
        try:
            if self._log_file.exists():
                stat = self._log_file.stat()
                self._last_size = stat.st_size
                self._last_mtime = stat.st_mtime
                text = self._log_file.read_text(
                    encoding="utf-8", errors="replace"
                )
                self._all_entries = parse_log_text(
                    "\n".join(text.splitlines()[-MAX_LINES:])
                )
            else:
                self._all_entries = []
        except Exception as exc:
            log.warning("LogView: kunde inte läsa loggfil: %s", exc)
            self._all_entries = []
        self._refresh_table(scroll_bottom=scroll_bottom)
        self._update_banner()

    def _tick(self) -> None:
        if self._paused:
            return
        try:
            if not self._log_file.exists():
                return
            stat = self._log_file.stat()
            if (stat.st_size, stat.st_mtime) != (
                self._last_size, self._last_mtime
            ):
                self._reload_from_file(
                    scroll_bottom=self._chk_scroll.isChecked()
                )
        except Exception:
            pass

    def _current_filter_result(self) -> list[dict]:
        session = ""
        if self._chk_session.isChecked():
            session = last_session_start(self._all_entries)
        return filter_entries(
            self._all_entries,
            min_level=str(self._cmb_level.currentData() or "ALL"),
            search=self._search.text(),
            only_errors=self._chk_errors.isChecked(),
            session_start=session,
        )

    def _refresh_table(self, scroll_bottom: bool = False) -> None:
        self._shown = self._current_filter_result()
        tbl = self._table
        tbl.setRowCount(len(self._shown))
        for r, e in enumerate(self._shown):
            lvl = str(e.get("level", "INFO"))
            values = [
                str(e.get("ts", ""))[5:19].replace("T", " "),
                lvl,
                str(e.get("logger", "-")),
                str(e.get("action", "")),
                str(e.get("msg", "")),
            ]
            for c, val in enumerate(values):
                item = QTableWidgetItem(val)
                if c == 1:
                    bg = LEVEL_BG.get(lvl.upper())
                    if bg:
                        item.setBackground(QColor(bg))
                        item.setForeground(QColor("#ffffff"))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 4 and e.get("exc"):
                    item.setToolTip(str(e["exc"])[:800])
                tbl.setItem(r, c, item)
        errors, warnings = count_levels(self._all_entries)
        size_kb = 0
        try:
            if self._log_file.exists():
                size_kb = self._log_file.stat().st_size // 1024
        except Exception:
            pass
        self._lbl_info.setText(tr(
            "log.info_line",
            shown=len(self._shown), total=len(self._all_entries),
            errors=errors, warnings=warnings, size=size_kb,
        ))
        if scroll_bottom and self._shown:
            tbl.scrollToBottom()

    def _update_banner(self) -> None:
        errors = [
            e for e in self._all_entries
            if LEVEL_ORDER.get(str(e.get("level", "")).upper(), 0)
            >= LEVEL_ORDER["ERROR"]
        ]
        if not errors:
            self._banner_widget.setVisible(False)
            return
        last = errors[-1]
        self._lbl_banner.setText(tr(
            "log.banner_errors", n=len(errors),
            last=f"{str(last.get('ts', ''))[5:19]} {last.get('msg', '')}",
        ))
        self._banner_widget.setVisible(True)

    # ── Aktioner ──────────────────────────────────────────────────────

    def _on_select(self) -> None:
        row = self._table.currentRow()
        if 0 <= row < len(self._shown):
            self._detail.setPlainText(
                format_entry_text(self._shown[row])
            )
        else:
            self._detail.clear()

    def _goto_last_error(self) -> None:
        self._chk_errors.setChecked(True)
        self._refresh_table(scroll_bottom=True)
        if self._shown:
            self._table.selectRow(len(self._shown) - 1)
            self._on_select()

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self._btn_pause.setText(
            tr("log.resume") if self._paused else tr("log.pause")
        )

    def _reset_filters(self) -> None:
        self._cmb_level.setCurrentText("INFO")
        self._search.clear()
        self._chk_errors.setChecked(False)
        self._chk_session.setChecked(False)
        self._refresh_table()

    def _set_marker(self) -> None:
        self._marker_ts = datetime.now().isoformat(timespec="seconds")
        self._all_entries.append({
            "ts": self._marker_ts, "level": "AUDIT",
            "logger": "LogView", "action": "MARKER",
            "msg": tr("log.marker_text"), "exc": "", "ctx": {},
        })
        try:
            logging.getLogger("FakturaMain").info(
                "🔖 %s", tr("log.marker_text")
            )
        except Exception:
            pass
        self._refresh_table(scroll_bottom=True)
        self._flash(self._btn_mark, tr("log.marker_set"))

    def _entries_after_marker(self) -> list[dict]:
        if not self._marker_ts:
            return list(self._shown)
        return [
            e for e in self._all_entries
            if str(e.get("ts", "")) >= self._marker_ts
        ]

    def _flash(self, button: QPushButton, text: str) -> None:
        old = button.text()
        button.setText(text)
        QTimer.singleShot(1800, lambda: button.setText(old))

    def _copy_to_clipboard(self, text: str, button: QPushButton,
                           done_key: str) -> None:
        QApplication.clipboard().setText(text)
        self._flash(button, tr(done_key))

    def _copy_selected(self) -> None:
        row = self._table.currentRow()
        if 0 <= row < len(self._shown):
            self._copy_to_clipboard(
                format_entry_text(self._shown[row]),
                self._btn_copy_row, "log.copied",
            )

    def _copy_after_marker(self) -> None:
        self._copy_to_clipboard(
            format_entries_text(self._entries_after_marker()),
            self._btn_copy_marked, "log.copied",
        )

    def _diagnostics_meta(self) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "generated": datetime.now().isoformat(timespec="seconds"),
            "marker_ts": self._marker_ts,
        }
        try:
            import app as app_module
            meta["app"] = (
                f"{app_module.APP_NAME} {app_module.APP_VERSION}"
            )
        except Exception:
            meta["app"] = "FakturaRäknaren"
        import platform
        meta["os"] = platform.platform()
        meta["python"] = sys.version.split()[0]
        try:
            import PySide6
            meta["qt"] = f"PySide6 {PySide6.__version__}"
        except Exception:
            pass
        app = self._app
        for key in ("language", "theme"):
            try:
                meta[key] = str(app.get_setting(key, ""))
            except Exception:
                pass
        for key, fn_name in (("suppliers", "get_suppliers"),
                             ("invoices", "get_invoices")):
            try:
                meta[key] = len(getattr(app, fn_name)())
            except Exception:
                pass
        for key, fn_name in (
            ("invoices_active", "get_active_invoices"),
            ("invoices_archived", "get_archived_invoices"),
        ):
            try:
                meta[key] = len(getattr(app, fn_name)())
            except Exception:
                pass
        try:
            from ui.watch_folders import watch_diagnostic_lines

            from app import DATA_DIR as _data_dir

            cfg_path = _data_dir / "watch_folders.json"
            wcfg: dict = {}
            if cfg_path.is_file():
                loaded = json.loads(
                    cfg_path.read_text(encoding="utf-8")
                )
                if isinstance(loaded, dict):
                    wcfg = loaded
            meta["watch_folders"] = len(wcfg.get("folders", []) or [])
            # Malldiagnosen per parkerad fil behöver registret
            # och mallarna (samma underlag som tolkningen).
            _suppliers: list = []
            try:
                _suppliers = list(app.get_suppliers() or [])
            except Exception:
                pass
            _templates: dict = {}
            try:
                import scan_import as _si

                _templates = _si.load_templates(
                    _data_dir / "invoice_templates.json"
                )
            except Exception:
                pass
            meta["watch_lines"] = watch_diagnostic_lines(
                wcfg, suppliers=_suppliers, templates=_templates
            )
        except Exception:
            pass
        meta["log_file"] = str(self._log_file)
        try:
            meta["log_size_kb"] = (
                self._log_file.stat().st_size // 1024
                if self._log_file.exists() else 0
            )
        except Exception:
            pass
        return meta

    def _copy_diagnostics(self) -> None:
        self._copy_to_clipboard(
            format_diagnostics(
                self._all_entries, self._diagnostics_meta()
            ),
            self._btn_copy_diag, "log.copied",
        )

    def _open_log_dir(self) -> None:
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self._log_file.parent))
        )

    def _collect_all_errors(self) -> None:
        """Samlar ALLA fel från alla loggar till logs/felsamling.log
        och visar resultatet — snabbaste vägen vid felsökning."""
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "plugins"))
            from error_collect import collect_errors, error_log_path

            root = self._log_file.parent.parent
            report = collect_errors(root)
            path = error_log_path(root)
            content = ""
            try:
                content = path.read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                pass
            # Visa senaste delen i detaljrutans stora yta
            self._detail.setPlainText(content[-20000:])
            self._lbl_info.setText(
                tr(
                    "log.collect_done",
                    total=report.get("total", 0),
                    added=report.get("added", 0),
                )
            )
        except Exception as exc:
            self._lbl_info.setText(f"⚠ {exc}")

    def _export_shown(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("log.export_title"), "logg-export.txt",
            "Text (*.txt);;JSONL (*.jsonl)",
        )
        if not path:
            return
        try:
            if path.endswith(".jsonl"):
                content = "\n".join(
                    str(e.get("raw", ""))
                    or json.dumps(e, ensure_ascii=False)
                    for e in self._shown
                )
            else:
                content = format_entries_text(self._shown)
            Path(path).write_text(content, encoding="utf-8")
            self._flash(self._btn_export, tr("log.copied"))
        except Exception as exc:
            log.warning("LogView export: %s", exc)

    # ── Tema / språk ──────────────────────────────────────────────────

    def apply_theme(self, theme: dict | None = None) -> None:
        name = str((theme or {}).get("name", "")).lower()
        self._dark = name != "light"
        self._refresh_table()

    def retranslate(self) -> None:
        self._lbl_title.setText(tr("log.title"))
        self._table.setHorizontalHeaderLabels([
            tr("log.col_time"), tr("log.col_level"),
            tr("log.col_logger"), tr("log.col_action"),
            tr("log.col_message"),
        ])
        self._lbl_level.setText(tr("log.level"))
        self._search.setPlaceholderText(tr("log.search_ph"))
        self._chk_errors.setText(tr("log.only_errors"))
        self._chk_session.setText(tr("log.only_session"))
        self._chk_scroll.setText(tr("log.auto_scroll"))
        self._btn_goto_error.setText(tr("log.goto_error"))
        self._btn_refresh.setText(tr("log.refresh"))
        self._btn_pause.setText(
            tr("log.resume") if self._paused else tr("log.pause")
        )
        self._btn_mark.setText(tr("log.mark"))
        self._btn_copy_marked.setText(tr("log.copy_marked"))
        self._btn_copy_diag.setText(tr("log.copy_diag"))
        self._btn_open_dir.setText(tr("log.open_dir"))
        self._btn_errors.setText(tr("log.collect_errors"))
        self._btn_export.setText(tr("log.export_shown"))
        self._btn_reset.setText(tr("log.reset_filters"))
        self._btn_copy_row.setText(tr("log.copy_row"))
        self._update_banner()
        self._refresh_table()
