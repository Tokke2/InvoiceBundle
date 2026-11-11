# -*- coding: utf-8 -*-
"""
Tester: UI-loggningen får aldrig krascha på en redan stängd widget.

Felrapporten visade upprepade
``RuntimeError: Internal C++ object (QLineEdit) already deleted`` från
logg-hooken för ``editingFinished``: signalen kan komma precis när en
dialog rivs, och då finns ingen C++-widget kvar att läsa ``text()`` från.
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


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _delete(widget) -> None:
    import shiboken6
    shiboken6.delete(widget)


def test_qt_is_valid_tracks_widget_lifetime():
    _qapp()
    from PySide6.QtWidgets import QLineEdit

    import advanced_logger

    field = QLineEdit()
    assert advanced_logger._qt_is_valid(field) is True
    _delete(field)
    assert advanced_logger._qt_is_valid(field) is False
    assert advanced_logger._qt_is_valid(None) is False


def test_safe_qt_callback_swallows_deleted_object():
    """En logg-callback på en stängd widget ska bara hoppa över."""
    _qapp()
    from PySide6.QtWidgets import QLineEdit

    import advanced_logger

    field = QLineEdit()
    field.setText("12345")
    callback = advanced_logger._safe_qt_callback(
        lambda: len(field.text() or "")
    )
    assert callback() == 5

    _delete(field)
    assert callback() is None  # inget undantag, ingen CRITICAL-rad


def test_ui_signal_loggers_skip_deleted_fields(monkeypatch):
    """De genererade hookarna läser aldrig text ur en förstörd widget."""
    _qapp()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QComboBox, QLineEdit, QWidget

    import advanced_logger

    logged: list[tuple[str, str]] = []
    monkeypatch.setattr(
        advanced_logger, "alog",
        lambda action, message="", **_kw: logged.append((action, message)),
    )

    callbacks = []
    real_safe = advanced_logger._safe_qt_callback

    def recording(callback):
        wrapped = real_safe(callback)
        callbacks.append(wrapped)
        return wrapped

    monkeypatch.setattr(advanced_logger, "_safe_qt_callback", recording)

    window = QWidget()
    field = QLineEdit(window)
    field.setObjectName("belopp")
    field.setText("1 250,00")
    combo = QComboBox(window)
    advanced_logger._install_ui_signal_loggers(window)

    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    QTimer.singleShot(0, lambda: None)
    QApplication.processEvents()

    assert callbacks, "inga UI-loggare kopplades"

    # En levande widget loggas som vanligt …
    field.editingFinished.emit()
    assert any(
        action == "TEXT_EDITED" for action, _msg in logged
    )

    # … men efter rivningen får ingen hook röra den igen.
    logged.clear()
    _delete(field)
    _delete(combo)
    for callback in callbacks:
        callback()
        callback(0)
        callback(None)
    assert not any(
        action == "TEXT_EDITED" for action, _msg in logged
    )

    window.deleteLater()
    QApplication.processEvents()


def test_uncaught_deleted_widget_error_is_not_logged_critical(monkeypatch):
    """Säkerhetsnätet: hooken får aldrig nå sys.excepthook."""
    _qapp()
    from PySide6.QtWidgets import QLineEdit

    import advanced_logger

    field = QLineEdit()
    _delete(field)
    seen: list[BaseException] = []
    monkeypatch.setattr(sys, "excepthook", lambda *a: seen.append(a[1]))

    callback = advanced_logger._safe_qt_callback(
        lambda: field.text()
    )
    callback()
    assert seen == []
