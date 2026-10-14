# -*- coding: utf-8 -*-
"""
update_dialog.py — dialogen för "Sök ny version".

Kollar GitHubs senaste release (plugins/updater.py), visar
versionsnoteringar och — om användaren vill — hämtar och installerar
uppdateringen. Användardata (data/, settings.json, loggar …) rörs
aldrig; efteråt erbjuds omstart av appen.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QVBoxLayout,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "plugins"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import updater  # plugins/updater.py
except Exception:  # pragma: no cover
    updater = None  # type: ignore

from ui.i18n import tr

log = logging.getLogger("invoice_bundle")


def schedule_restart(root: Path, delay_seconds: float = 2.5) -> bool:
    """
    Startar en ny instans strax efter att denna stängts
    (en liten hjälpare väntar så att single-instance-låset hinner
    släppas). Returnerar True om hjälparen startades.
    """
    root = Path(root)
    entry = root / "main.py"
    if not entry.exists():
        entry = root / "main.pyw"
    if not entry.exists() or not sys.executable:
        return False
    helper = (
        "import subprocess, sys, time;"
        f"time.sleep({float(delay_seconds)});"
        f"subprocess.Popen([sys.executable, {str(entry)!r}], "
        f"cwd={str(root)!r})"
    )
    try:
        subprocess.Popen(
            [sys.executable, "-c", helper],
            cwd=str(root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception as exc:
        log.warning("UPDATE omstart: %s", exc)
        return False


class UpdateWorker(QThread):
    """Bakgrundstråd: nätverk + filbyte ska aldrig frysa UI:t."""

    check_done = Signal(dict)
    apply_done = Signal(dict)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, mode: str, root: Path, release: dict | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._mode = mode
        self._root = Path(root)
        self._release = release or {}

    def run(self) -> None:  # noqa: D401
        try:
            if updater is None:
                raise RuntimeError("updater-modulen saknas")
            if self._mode == "check":
                self.check_done.emit(updater.check_for_update(self._root))
                return
            release = self._release
            asset = release.get("asset") or {}
            url = asset.get("url") or release.get("zipball_url") or ""
            if not url:
                raise RuntimeError("Ingen nedladdningslänk i releasen.")
            zip_path = Path(tempfile.gettempdir()) / "fakturabunten-update.zip"
            updater.download_file(
                url, zip_path,
                progress=lambda d, t: self.progress.emit(d, t),
            )
            self.progress.emit(0, 0)  # 0/0 = installationsfasen
            report = updater.apply_update(
                zip_path, self._root,
                version=str(release.get("tag", "")).lstrip("vV"),
                sha=release.get("sha", ""),
            )
            try:
                zip_path.unlink(missing_ok=True)
            except Exception:
                pass
            self.apply_done.emit(report)
        except Exception as exc:
            log.warning("UPDATE worker (%s): %s", self._mode, exc)
            self.failed.emit(str(exc))


class UpdateDialog(QDialog):
    """Dialog för versionskoll och installation av uppdatering."""

    def __init__(self, parent, root: Path, version: str,
                 initial_result: dict | None = None) -> None:
        super().__init__(parent)
        self._root = Path(root)
        self._version = version
        self._initial_result = initial_result
        self._release: dict = {}
        self._worker: UpdateWorker | None = None
        self.restart_requested = False

        self.setWindowTitle(tr("update.title"))
        self.setMinimumWidth(540)
        root_layout = QVBoxLayout(self)
        root_layout.setSpacing(10)

        self._lbl_status = QLabel(tr("update.checking"))
        self._lbl_status.setWordWrap(True)
        root_layout.addWidget(self._lbl_status)

        self._lbl_build = QLabel()
        self._lbl_build.setStyleSheet("color:#5a6b80;")
        self._lbl_build.setWordWrap(True)
        root_layout.addWidget(self._lbl_build)
        self._show_local_build()

        lbl_safe = QLabel(tr("update.safe_note"))
        lbl_safe.setWordWrap(True)
        lbl_safe.setStyleSheet("color:#5a6b80;")
        root_layout.addWidget(lbl_safe)

        self._lbl_notes = QLabel(tr("update.notes"))
        self._txt_notes = QPlainTextEdit()
        self._txt_notes.setReadOnly(True)
        self._txt_notes.setMaximumHeight(180)
        self._lbl_notes.hide()
        self._txt_notes.hide()
        root_layout.addWidget(self._lbl_notes)
        root_layout.addWidget(self._txt_notes)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        root_layout.addWidget(self._progress)

        row = QHBoxLayout()
        self._btn_install = QPushButton(tr("update.install"))
        self._btn_install.setProperty("accent", True)
        self._btn_install.clicked.connect(self._install)
        self._btn_install.hide()
        self._btn_restart = QPushButton(tr("update.restart"))
        self._btn_restart.setProperty("accent", True)
        self._btn_restart.clicked.connect(self._restart)
        self._btn_restart.hide()
        self._btn_close = QPushButton(tr("update.close"))
        self._btn_close.clicked.connect(self.reject)
        self._btn_restore = QPushButton(tr("update.restore"))
        self._btn_restore.clicked.connect(self._restore)
        if updater is None or not updater.find_backups(self._root):
            self._btn_restore.hide()
        row.addWidget(self._btn_install)
        row.addWidget(self._btn_restart)
        row.addWidget(self._btn_restore)
        row.addStretch(1)
        row.addWidget(self._btn_close)
        root_layout.addLayout(row)

        if self._initial_result is not None:
            self._on_check(self._initial_result)
        else:
            self._start_check()

    # ── Status / lokal build ────────────────────────────────────────
    def _show_local_build(self) -> None:
        if updater is None:
            self._lbl_build.setText("")
            return
        local = updater.read_local_build(self._root)
        sha = str(local.get("sha", ""))
        built = str(local.get("built", ""))
        build = (
            f"v{self._version} · {sha[:7]}" if sha
            else tr("update.unknown_build")
        )
        if built:
            build += f" · {built[:16].replace('T', ' ')}"
        self._lbl_build.setText(tr("update.installed_build", build=build))

    # ── Flöde ────────────────────────────────────────────────────────
    def _start_check(self) -> None:
        self._lbl_status.setText(tr("update.checking"))
        self._progress.setRange(0, 0)
        self._worker = UpdateWorker("check", self._root, parent=self)
        self._worker.check_done.connect(self._on_check)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_check(self, result: dict) -> None:
        self._release = result.get("release") or {}
        rel = self._release
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        if result.get("status") == "update":
            sha = str(rel.get("sha", ""))
            tag = rel.get("tag", "")
            if sha:
                tag = f"{tag} ({sha[:7]})"
            self._lbl_status.setText(
                tr("update.available", tag=tag,
                   current=f"v{self._version}")
            )
            pub = str(rel.get("published_at", ""))[:10]
            if pub:
                self._lbl_build.setText(
                    self._lbl_build.text()
                    + "   ·   " + tr("update.published", date=pub)
                )
            body = str(rel.get("body", "")).strip()
            if body:
                self._lbl_notes.show()
                self._txt_notes.show()
                self._txt_notes.setPlainText(body[:6000])
            self._btn_install.show()
        else:
            self._lbl_status.setText(
                tr("update.current", version=self._version)
            )

    def _install(self) -> None:
        self._btn_install.hide()
        self._lbl_status.setText(tr("update.applying"))
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._worker = UpdateWorker(
            "apply", self._root, self._release, parent=self
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.apply_done.connect(self._on_applied)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, done: int, total: int) -> None:
        if total == 0:  # installationsfasen (efter hämtningen)
            self._progress.setRange(0, 0)
            self._lbl_status.setText(tr("update.applying"))
            return
        self._progress.setRange(0, 100)
        if total > 0:
            pct = int(done * 100 / total)
            self._progress.setValue(pct)
            self._lbl_status.setText(
                tr("update.downloading", percent=pct)
            )

    def _on_applied(self, report: dict) -> None:
        self._progress.setValue(100)
        n = (
            report.get("replaced", 0) + report.get("added", 0)
            + report.get("removed", 0)
        )
        self._lbl_status.setText(tr("update.done", n=n))
        self._show_local_build()
        self._btn_restart.show()

    def _on_failed(self, error: str) -> None:
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._lbl_status.setText(tr("update.failed", error=error))
        self._btn_install.hide()

    # ── Återställning (rullback) ─────────────────────────────────────
    def _restore(self) -> None:
        if updater is None:
            return
        backups = updater.find_backups(self._root)
        if not backups:
            self._btn_restore.hide()
            return
        latest = backups[0]
        answer = QMessageBox.question(
            self, tr("update.title"),
            tr("update.restore_confirm", name=latest.name),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            report = updater.restore_backup(latest, self._root)
            self._lbl_status.setText(
                tr("update.restored", n=report.get("restored", 0))
            )
            self._btn_install.hide()
            self._btn_restart.show()
            self._show_local_build()
        except Exception as exc:
            self._lbl_status.setText(tr("update.failed", error=str(exc)))

    # ── Omstart ──────────────────────────────────────────────────────
    def _restart(self) -> None:
        self.restart_requested = True
        self.accept()

    # Skydd: stäng inte mitt i nedladdning/installation
    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker is not None and self._worker.isRunning():
            event.ignore()
            return
        event.accept()
        super().closeEvent(event)
