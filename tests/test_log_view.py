# -*- coding: utf-8 -*-
"""
Regressionstester: loggfliken (egen flik för felsökning).

Skyddar: JSONL-tolkning (även trasiga rader), filtrering,
sessionsstart, felsökningspaketets innehåll, markeringsflödet
samt att advanced_logger INTE skapar en andra loggflik när
huvudfönstret har den inbyggda.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "ui"),
           str(PROJECT_DIR / "plugins")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

SAMPLE = """\
{"ts":"2026-10-01T08:00:00","level":"INFO","logger":"FakturaMain","action":"START","msg":"Programmet startar","loc":"main:1"}
{"ts":"2026-10-01T08:00:05","level":"DEBUG","logger":"Store","action":"","msg":"Laddade 3 poster","loc":""}
{"ts":"2026-10-01T08:01:00","level":"ERROR","logger":"PDF","action":"EXPORT","msg":"Export kraschade","loc":"pdf:9","exc":"Traceback...\\nValueError: boom"}
en trasig rad som inte är json
{"ts":"2026-10-01T08:02:00","level":"WARNING","logger":"Store","action":"","msg":"Saknar fält","loc":""}
{"ts":"2026-10-02T09:00:00","level":"INFO","logger":"FakturaMain","action":"START","msg":"Programmet startar","loc":"main:1"}
{"ts":"2026-10-02T09:05:00","level":"CRITICAL","logger":"App","action":"","msg":"Andra kraschen","loc":"","exc":"RuntimeError: aj"}
"""


def _entries():
    from ui.log_view import parse_log_text

    return parse_log_text(SAMPLE)


def test_parse_jsonl_and_broken_lines():
    entries = _entries()
    assert len(entries) == 7
    assert entries[0]["action"] == "START"
    assert entries[3]["msg"].startswith("en trasig rad")
    assert entries[3]["level"] == "INFO"  # rå rad → INFO-fallback
    assert "ValueError: boom" in entries[2]["exc"]


def test_filter_levels_search_errors_session():
    from ui.log_view import filter_entries, last_session_start

    entries = _entries()
    assert len(filter_entries(entries, min_level="WARNING")) == 3
    assert len(filter_entries(entries, only_errors=True)) == 2
    assert len(filter_entries(entries, search="krasch")) == 2
    assert len(filter_entries(entries, search="store")) == 2
    start = last_session_start(entries)
    assert start == "2026-10-02T09:00:00"
    session = filter_entries(entries, session_start=start)
    assert [e["msg"] for e in session] == [
        "Programmet startar", "Andra kraschen",
    ]


def test_count_levels_and_diagnostics_package():
    from ui.log_view import count_levels, format_diagnostics

    entries = _entries()
    errors, warnings = count_levels(entries)
    assert (errors, warnings) == (2, 1)

    text = format_diagnostics(entries, {
        "app": "FakturaRäknaren 1.0.0", "os": "TestOS",
        "suppliers": 4, "invoices": 9,
    })
    assert "FakturaRäknaren 1.0.0" in text
    assert "suppliers: 4" in text
    assert "Export kraschade" in text
    assert "ValueError: boom" in text  # traceback följer med
    assert "Andra kraschen" in text

    marked = format_diagnostics(entries, {
        "app": "X", "marker_ts": "2026-10-02T09:00:30",
    })
    assert "Logg efter markering" in marked
    tail = marked.split("Logg efter markering", 1)[1]
    assert "Andra kraschen" in tail
    assert "Export kraschade" not in tail  # före markeringen → borta


def test_log_view_builds_filters_and_marks(tmp_path):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from ui import i18n
    from ui.log_view import LogView

    log_file = tmp_path / "app.log"
    log_file.write_text(SAMPLE, encoding="utf-8")

    class FakeApp:
        def get_setting(self, key, default=None):
            return default

        def get_suppliers(self):
            return []

        def get_invoices(self):
            return []

    view = LogView(FakeApp(), log_file=log_file)
    try:
        # INFO är standardnivån → DEBUG döljs, 6 av 7 rader visas
        assert view._table.rowCount() == 6
        assert not view._banner_widget.isHidden()  # fel finns → banner
        view._goto_last_error()
        assert view._table.currentRow() == view._table.rowCount() - 1
        assert "RuntimeError: aj" in view._detail.toPlainText()

        # Markering → "efter markering" innehåller markeringsraden
        view._set_marker()
        after = view._entries_after_marker()
        assert any(e.get("action") == "MARKER" for e in after)

        # Engelska etiketter vid språkbyte
        i18n.set_language("en")
        view.retranslate()
        assert view._btn_copy_diag.text() == "📋  Copy diagnostics"
        assert view._lbl_title.text().startswith("🪵  System log")
        i18n.set_language("sv")
        view.retranslate()
        assert view._btn_copy_diag.text() == "📋  Kopiera felsökningspaket"
    finally:
        view._timer.stop()
        view.close()


def test_advanced_logger_skips_tab_when_builtin_exists():
    """Huvudfönstrets inbyggda loggflik → ingen plugin-flik ovanpå."""
    import advanced_logger as al

    al._memory_handler_global = al.MemoryHandler()  # hoppa setup_logging

    class FakeWindow:
        _builtin_log_tab = True
        _app = None

        def __init__(self):
            self.added_tabs = []

        def add_plugin_tab(self, widget, title, key=""):
            self.added_tabs.append((title, key))

    fake = FakeWindow()
    al.register_ui(fake)
    assert fake.added_tabs == []


def test_log_view_clean_resolved_errors_and_auto_clean_setting(tmp_path):
    """Manuell rensning + inställningen 'Rensa åtgärdade automatiskt' i LogView."""
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    import error_collect as ec
    from ui import i18n
    from ui.log_view import LogView, format_diagnostics

    logs = tmp_path / "logs"
    logs.mkdir(parents=True)
    log_file = logs / "app.log"
    log_file.write_text(SAMPLE, encoding="utf-8")

    ec.error_log_path(tmp_path).write_text(
        ec._HEADER
        + "2026-10-01T10:00:00 | ERROR | Test | Åtgärdat gammalt fel\n"
        + "2026-10-19T12:01:00 | CRITICAL | App | Andra kraschen\n",
        encoding="utf-8",
    )

    saved: dict[str, object] = {"auto_clean_resolved_errors": True}

    class FakeApp:
        def get_setting(self, key, default=None):
            return saved.get(key, default)

        def set_setting(self, key, value):
            saved[key] = value

        def get_suppliers(self):
            return []

        def get_invoices(self):
            return []

    view = LogView(FakeApp(), log_file=log_file)
    try:
        assert view._chk_auto_clean.isChecked() is True
        view._chk_auto_clean.setChecked(False)
        assert saved["auto_clean_resolved_errors"] is False

        # Både sv & en översättning för nya kontroller
        i18n.set_language("en")
        view.retranslate()
        assert "Clean resolved" in view._btn_clean_errors.text()
        assert "Auto-clean" in view._chk_auto_clean.text()
        i18n.set_language("sv")
        view.retranslate()
        assert "Rensa åtgärdade" in view._btn_clean_errors.text()

        # Före rensning visas felbannern
        assert not view._banner_widget.isHidden()

        # Rensa bort allt (inkl. aktuella markerade som åtgärdade)
        result = view.clean_resolved_errors(
            include_open=True, prompt_if_open=False
        )
        assert result["remaining"] == 0
        assert "Andra kraschen" not in ec.error_log_path(tmp_path).read_text(encoding="utf-8")
        # Bannern döljs direkt eftersom inga nyare fel skett efter rensningen
        assert view._banner_widget.isHidden()

        # Felsökningspaketet döljer redan rensade gamla fel
        diag = format_diagnostics(
            view._all_entries, view._diagnostics_meta()
        )
        assert "inga olösta fel sedan rensning" in diag
    finally:
        view._timer.stop()
        view.close()

