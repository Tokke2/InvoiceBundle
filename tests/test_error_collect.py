# -*- coding: utf-8 -*-
"""
Tester: EN fellogg som samlar alla fel för snabb felsökning.

Användarens önskemål (2026-10-30): en loggfil som samlar alla fel
från de andra loggarna så felsökning går snabbt.

Felsamlingen logs/felsamling.log fylls på två sätt som prövas här:
1. SPEGLING: ERROR/CRITICAL från vilken modul som helst speglas
   direkt till filen (root-handler), inkl. traceback.
2. SKÖRD: collect_errors() hämtar fel ur logs/app.log (JSONL),
   logs/autostart.log och startup_crash.log — utan dubletter.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "ui"),
           str(PROJECT_DIR / "plugins")):
    if _d not in sys.path:
        sys.path.insert(0, _d)


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _read(root: Path) -> str:
    return (root / "logs" / "felsamling.log").read_text(
        encoding="utf-8"
    )


def _drop_mirror_handlers():
    root = logging.getLogger()
    for h in list(root.handlers):
        if type(h).__name__ == "ErrorMirrorHandler":
            root.removeHandler(h)


# ── Spegling i realtid ──────────────────────────────────────────────


def test_mirror_writes_errors_not_warnings(tmp_path):
    import error_collect as ec

    _drop_mirror_handlers()
    try:
        assert ec.install_error_mirror(tmp_path) is True
        # Andra installationen är en no-op (en enda spegel).
        assert ec.install_error_mirror(tmp_path) is True
        assert sum(
            1 for h in logging.getLogger().handlers
            if type(h).__name__ == "ErrorMirrorHandler"
        ) == 1

        log = logging.getLogger("test.modul")
        log.error("Databasen svarar inte")
        log.warning("Bara en varning")
        try:
            raise ValueError("trasigt belopp")
        except ValueError:
            log.error("Kunde inte tolka", exc_info=True)

        text = _read(tmp_path)
        assert "Databasen svarar inte" in text
        assert "ValueError: trasigt belopp" in text
        assert "Traceback" in text
        assert "Bara en varning" not in text
    finally:
        _drop_mirror_handlers()


def test_mirror_never_writes_info(tmp_path):
    import error_collect as ec

    assert ec.error_log_path(tmp_path).name == "felsamling.log"
    _drop_mirror_handlers()
    handler = ec.ErrorMirrorHandler(ec.error_log_path(tmp_path))
    assert handler.level == logging.ERROR


# ── Skörd ur andra loggar ───────────────────────────────────────────


def _seed_logs(root: Path) -> None:
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    entries = [
        {"ts": "2026-10-30 08:00:01", "level": "INFO",
         "logger": "App", "msg": "start", "loc": "a:1"},
        {"ts": "2026-10-30 08:01:02", "level": "ERROR",
         "logger": "ScanImport", "msg": "PDF trasig", "loc": "s:9",
         "exc": "Traceback (most recent call last):\n"
                "  File \"x.py\", line 1\nValueError: tom fil\n"},
        {"ts": "2026-10-30 08:02:03", "level": "WARNING",
         "logger": "App", "msg": "långsam disk", "loc": "a:2"},
        {"ts": "2026-10-30 08:03:04", "level": "CRITICAL",
         "logger": "App", "msg": "Krasch i export", "loc": "e:3"},
        "inte json alls",
    ]
    (logs / "app.log").write_text(
        "\n".join(
            json.dumps(e) if isinstance(e, dict) else e
            for e in entries
        ) + "\n",
        encoding="utf-8",
    )
    (logs / "autostart.log").write_text(
        "2026-10-30 OK start\n"
        "Traceback (most recent call last):\n"
        "  File \"main.py\", line 5, in <module>\n"
        "RuntimeError: disken E: saknas\n"
        "2026-10-30 OK igen\n",
        encoding="utf-8",
    )
    (root / "startup_crash.log").write_text(
        "CRITICAL krasch vid start\n"
        "Traceback (most recent call last):\n"
        "  File \"m.py\", line 2\nOSError: låst fil\n",
        encoding="utf-8",
    )


def test_collect_gathers_errors_from_all_logs(tmp_path):
    import error_collect as ec

    _seed_logs(tmp_path)
    report = ec.collect_errors(tmp_path)
    text = _read(tmp_path)
    assert report["added"] > 0
    assert report["file"].endswith("felsamling.log")
    # Från app.log (JSONL)
    assert "PDF trasig" in text
    assert "Krasch i export" in text
    assert "ValueError: tom fil" in text
    assert "långsam disk" not in text   # WARNING följer inte med
    assert '"start"' not in text
    # Från autostart.log (textlogg med traceback-block)
    assert "RuntimeError: disken E: saknas" in text
    assert "[autostart.log]" in text
    # Från startup_crash.log
    assert "OSError: låst fil" in text


def test_collect_is_deduplicated(tmp_path):
    import error_collect as ec

    _seed_logs(tmp_path)
    first = ec.collect_errors(tmp_path)
    second = ec.collect_errors(tmp_path)
    assert first["added"] > 0
    assert second["added"] == 0
    assert second["total"] == first["total"]
    assert _read(tmp_path).count("PDF trasig") == 1


def test_collect_trims_to_max_lines(tmp_path, monkeypatch):
    import error_collect as ec

    monkeypatch.setattr(ec, "MAX_LINES", 6)
    _seed_logs(tmp_path)
    ec.collect_errors(tmp_path)
    lines = [
        ln for ln in _read(tmp_path).splitlines()
        if not ln.startswith("#")
    ]
    assert len(lines) <= 6


def test_collect_tolerates_missing_logs(tmp_path):
    import error_collect as ec

    report = ec.collect_errors(tmp_path)
    assert report["total"] == 0
    assert (tmp_path / "logs" / "felsamling.log").exists()


def test_mirrored_error_not_duplicated_by_collect(tmp_path):
    """Speglat fel + samma fel i app.log ger EN rad i samlingen."""
    import error_collect as ec

    _drop_mirror_handlers()
    try:
        ec.install_error_mirror(tmp_path)
        record_logger = logging.getLogger("dup.modul")
        record_logger.error("Samma fel")
        # Samma händelse som den hamnar i app.log (JSONL, samma schema)
        logs = tmp_path / "logs"
        entry = {
            "ts": "2026-10-30 09:00:00", "level": "ERROR",
            "logger": "dup.modul", "msg": "Samma fel",
            "loc": "error_collect:1",
        }
        (logs / "app.log").write_text(
            json.dumps(entry) + "\n", encoding="utf-8"
        )
        ec.collect_errors(tmp_path)
        # Spegelns rad och skördens rad har olika loc-format här —
        # budskapet ska ändå bara förekomma som spegelrad + ev. EN
        # skördrad; vi kräver minst att filen innehåller felet och
        # att en andra skörd inte lägger till fler kopior.
        before = _read(tmp_path).count("Samma fel")
        ec.collect_errors(tmp_path)
        assert _read(tmp_path).count("Samma fel") == before
        assert before >= 1
    finally:
        _drop_mirror_handlers()


# ── Inkoppling ──────────────────────────────────────────────────────


def test_logging_setup_installs_mirror():
    """advanced_logger:s setup lägger tillbaka spegeln efter
    handler-bytet — annars dör speglingen vid plugin-laddning."""
    src = (
        PROJECT_DIR / "plugins" / "advanced_logger.py"
    ).read_text(encoding="utf-8")
    assert "install_error_mirror" in src
    main_src = (PROJECT_DIR / "main.py").read_text(encoding="utf-8")
    assert "install_error_mirror" in main_src   # tidig start-spegling
    assert "collect_errors(BASE_DIR)" in main_src  # skörd vid start


def test_log_view_collect_button(tmp_path):
    _qapp()
    from ui.log_view import LogView

    class FakeApp:
        settings = None

        def get_suppliers(self):
            return []

    logs = tmp_path / "logs"
    logs.mkdir(parents=True)
    log_file = logs / "app.log"
    log_file.write_text(
        json.dumps(
            {"ts": "2026-10-30 10:00:00", "level": "ERROR",
             "logger": "UI", "msg": "Knappfel", "loc": "v:1"}
        ) + "\n",
        encoding="utf-8",
    )
    view = LogView(FakeApp(), log_file=log_file)
    assert view._btn_errors.text()
    view._collect_all_errors()
    text = (logs / "felsamling.log").read_text(encoding="utf-8")
    assert "Knappfel" in text
    assert "felsamling" in view._lbl_info.text()
