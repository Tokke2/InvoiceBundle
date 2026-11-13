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


def _raise_from_logger_module(message: str) -> BaseException:
    """Skapar ett undantag vars stackspår går genom advanced_logger.py.

    Samma form som i felsamlingen: ``_f`` i den här modulen läser
    ``text()`` på en widget som redan rivits.
    """
    source = (
        "def _f(field):\n"
        "    return len(field.text() or '')\n"
    )
    namespace: dict = {}
    exec(compile(source, "advanced_logger.py", "exec"), namespace)
    try:
        namespace["_f"](object())
    except Exception as exc:  # AttributeError → byts mot rätt fel nedan
        return RuntimeError(message).with_traceback(exc.__traceback__)
    raise AssertionError("undantaget uteblev")


def test_closed_widget_error_from_our_hooks_is_never_critical(
    monkeypatch, caplog
):
    """Bruset från en stängd widget får aldrig bli en CRITICAL-rad.

    Felsamlingen visade upprepade ``Internal C++ object (QLineEdit)
    already deleted`` med action CRASH. Hookarna ska fånga det själva,
    och om något ändå når sys.excepthook ska det bara bli DEBUG.
    """
    import logging

    import advanced_logger

    monkeypatch.setattr(sys, "excepthook", sys.__excepthook__)
    advanced_logger.install_exception_hook()
    installed = sys.excepthook

    exc = _raise_from_logger_module(
        "libshiboken: Internal C++ object "
        "(PySide6.QtWidgets.QLineEdit) already deleted."
    )
    with caplog.at_level(logging.DEBUG, logger="UncaughtException"):
        installed(type(exc), exc, exc.__traceback__)

    critical = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert critical == [], [r.getMessage() for r in critical]
    assert any("redan stängd widget" in r.getMessage()
               for r in caplog.records)


def test_real_uncaught_error_still_becomes_critical(monkeypatch, caplog):
    """Skyddsnätet får inte dölja verkliga fel utanför loggningen."""
    import logging

    import advanced_logger

    advanced_logger.install_exception_hook()
    installed = sys.excepthook

    try:
        raise RuntimeError("Internal C++ object (QLineEdit) already deleted.")
    except RuntimeError as exc:
        real = exc

    with caplog.at_level(logging.DEBUG, logger="UncaughtException"):
        installed(type(real), real, real.__traceback__)

    critical = [r for r in caplog.records if r.levelno >= logging.CRITICAL]
    assert len(critical) == 1
    assert "UNCAUGHT EXCEPTION" in critical[0].getMessage()


def test_window_and_tray_loggers_are_wrapped(monkeypatch):
    """Fönster-, flik- och tray-hookarna använder samma skydd."""
    import advanced_logger

    source = (
        PROJECT_DIR / "plugins" / "advanced_logger.py"
    ).read_text(encoding="utf-8")
    assert "main_window.theme_changed.connect(_safe_qt_callback(_on_theme))" in source
    assert "main_window.tabs.currentChanged.connect(_safe_qt_callback(_on_tab))" in source
    assert "tray.activated.connect(_safe_qt_callback(_on_tray))" in source


def test_qt_bridge_is_installed_after_late_qapplication_without_duplicates(
    monkeypatch,
):
    """Fas 1 utan Qt följt av UI-start måste ge exakt en aktiv brygga."""
    import logging
    from types import SimpleNamespace
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication, QWidget
    import advanced_logger as al

    qapp = _qapp()
    previous_bridge = al._qt_bridge
    previous_live = (
        previous_bridge is not None
        and al._qt_is_valid(previous_bridge)
        and previous_bridge.parent() is qapp
    )
    if previous_live:
        qapp.removeEventFilter(previous_bridge)
    monkeypatch.setattr(al, "_qt_bridge", None)
    monkeypatch.setattr(al, "_memory_handler_global", None)
    monkeypatch.setattr(al, "_app_ref", None)
    monkeypatch.setattr(al, "setup_logging", lambda **_kw: object())
    monkeypatch.setattr(al, "install_exception_hook", lambda: None)
    monkeypatch.setattr(al, "install_qt_message_hook", lambda: None)
    monkeypatch.setattr(al, "log_system_info", lambda: None)
    monkeypatch.setattr(al, "attach_app_watchers", lambda _app: None)
    monkeypatch.setattr(al, "attach_window_watchers", lambda _window: None)
    monkeypatch.setattr(al, "_install_ui_signal_loggers", lambda _window: None)
    actions = []
    monkeypatch.setattr(al, "alog", lambda action, *_a, **_kw: actions.append(action))
    debug_messages = []
    warnings = []
    monkeypatch.setattr(al._plugin_log, "debug", lambda msg, *_a: debug_messages.append(msg))
    monkeypatch.setattr(al._plugin_log, "warning", lambda msg, *_a, **_kw: warnings.append(msg))

    bridge = None
    root = logging.getLogger()
    original_level = root.level
    try:
        # Kärnan registreras innan någon QApplication finns.
        monkeypatch.setattr(QApplication, "instance", lambda: None)
        al.register(SimpleNamespace())
        assert al._qt_bridge is None
        assert any("ingen QApplication" in msg for msg in debug_messages)
        assert not any("Qt-brygga" in msg for msg in warnings)

        # När fönstret senare registreras ska bryggan installeras på riktigt.
        monkeypatch.setattr(QApplication, "instance", lambda: qapp)
        window = QWidget()
        window._builtin_log_tab = True
        al.register_ui(window)
        bridge = al._qt_bridge
        assert bridge is not None and bridge.parent() is qapp
        assert actions.count("QT_BRIDGE") == 1

        # Upprepad registrering får inte skapa flera eventfilter.
        al.register_ui(window)
        assert al._qt_bridge is bridge
        assert actions.count("QT_BRIDGE") == 1

        actions.clear()
        root.setLevel(al.TRACE_LEVEL)
        qapp.sendEvent(window, QEvent(QEvent.Type.FocusIn))
        assert actions.count("UI_FOCUS") == 1
        window.close()
    finally:
        root.setLevel(original_level)
        if bridge is not None and al._qt_is_valid(bridge):
            qapp.removeEventFilter(bridge)
            bridge.setParent(None)
            bridge.deleteLater()
        if previous_live:
            qapp.installEventFilter(previous_bridge)
