"""The autostart UI reports OS failures without losing the actual checkbox state."""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
for folder in (ROOT, ROOT / "ui", ROOT / "plugins"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def harness(qt_app, monkeypatch, tmp_path):
    import app as appmod
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QMainWindow
    from ui import i18n, main_window

    i18n.set_language("sv", notify=False)
    state = types.SimpleNamespace(
        actual=False, current=False, failed=False, pretend_success=False, calls=[]
    )
    monkeypatch.setattr(appmod, "CURRENT_PLATFORM", "windows")
    monkeypatch.setattr(appmod.AutostartManager, "migrate_legacy_if_present", lambda _self: None)
    monkeypatch.setattr(appmod.AutostartManager, "is_enabled", lambda _self: state.actual)
    monkeypatch.setattr(appmod.AutostartManager, "_shortcut_is_current", lambda _self: state.current)

    def set_enabled(self, enable):
        state.calls.append((enable, self.method))
        if state.failed:
            return state.pretend_success
        state.actual = enable
        state.current = enable
        return True

    monkeypatch.setattr(appmod.AutostartManager, "set_enabled", set_enabled)
    settings = appmod.SettingsManager(tmp_path / "settings.json")
    dialogs = []
    monkeypatch.setattr(
        main_window.QMessageBox, "warning",
        lambda _parent, _title, text: dialogs.append(("warning", str(text))),
    )
    monkeypatch.setattr(
        main_window.QMessageBox, "information",
        lambda _parent, _title, text: dialogs.append(("information", str(text))),
    )

    class Window(main_window.MainWindow):
        def __init__(self):
            QMainWindow.__init__(self)
            self._settings = settings
            self._app = types.SimpleNamespace(settings=settings)
            self.status_messages = []
            self._act_autostart = QAction("autostart", self)
            self._tray_act_autostart = QAction("tray autostart", self)
            for action in (self._act_autostart, self._tray_act_autostart):
                action.setCheckable(True)
            self._autostart_method_actions = {}
            for method in ("auto", "direct", "launcher"):
                action = QAction(method, self)
                action.setCheckable(True)
                self._autostart_method_actions[method] = action

        def set_status(self, text, timeout=0):
            self.status_messages.append(str(text))

    win = Window()
    yield win, settings, state, dialogs, i18n
    win.deleteLater()
    qt_app.processEvents()
    i18n.set_language("sv", notify=False)


def _checked(win):
    return win._act_autostart.isChecked(), win._tray_act_autostart.isChecked()


@pytest.mark.parametrize(
    ("language", "fragment"),
    [("sv", "finns kvar men kan vara föråldrad"), ("en", "remains but may be outdated")],
)
def test_preserved_old_entry_is_not_reported_as_a_success(harness, language, fragment):
    win, settings, state, dialogs, i18n = harness
    i18n.set_language(language, notify=False)
    state.actual = True     # an old shortcut exists
    state.current = False   # but it is not the desired registration
    state.failed = True

    win._toggle_autostart(True)
    assert state.calls == [(True, "auto")]
    assert settings.get("startup") is True
    assert _checked(win) == (True, True)  # a prior OS entry still exists
    assert len(dialogs) == 1 and dialogs[0][0] == "warning"
    assert fragment in dialogs[0][1]
    assert not any(kind == "information" for kind, _ in dialogs)

    # Retrying the same saved setting attempts the stale shortcut again.
    state.failed = False
    win._toggle_autostart(True)
    assert state.calls == [(True, "auto"), (True, "auto")]
    assert dialogs[-1][0] == "information"
    assert _checked(win) == (True, True)


def test_tray_enable_failure_does_not_force_both_checkboxes_on(harness):
    win, settings, state, dialogs, _ = harness
    state.failed = True
    win._tray_autostart_toggled(True)
    assert settings.get("startup") is True
    assert _checked(win) == (False, False)
    assert dialogs[0][0] == "warning"
    assert "Kunde inte registrera" in dialogs[0][1]

    # The saved value is already True; a repeat must nevertheless retry.
    state.failed = False
    win._tray_autostart_toggled(True)
    assert state.calls == [(True, "auto"), (True, "auto")]
    assert _checked(win) == (True, True)
    assert dialogs[-1][0] == "information"


@pytest.mark.parametrize("pretend_success", [False, True])
def test_tray_disable_failure_keeps_checkbox_on_even_if_os_claims_success(
    harness, pretend_success
):
    win, settings, state, dialogs, _ = harness
    assert settings.set("startup", True) is True
    state.failed = True
    state.pretend_success = pretend_success
    win._tray_autostart_toggled(False)
    assert settings.get("startup") is False
    assert state.actual is True
    assert _checked(win) == (True, True)
    assert len(dialogs) == 1 and dialogs[0][0] == "warning"
    assert "Kunde inte stänga av" in dialogs[0][1]
    assert not any(kind == "information" for kind, _ in dialogs)


def test_failed_method_change_shows_warning_not_success_status(harness):
    win, settings, state, dialogs, _ = harness
    assert settings.set("startup", True) is True
    state.failed = True
    win._set_autostart_method("launcher")
    assert settings.get("autostart_method") == "launcher"
    assert state.calls[-1] == (True, "launcher")
    assert win._autostart_method_actions["launcher"].isChecked()
    assert len(dialogs) == 1 and dialogs[0][0] == "warning"
    assert "Kunde inte byta" in dialogs[0][1]
    assert "Kunde inte byta" in win.status_messages[-1]
    assert "Autostart-metod:" not in win.status_messages[-1]


def test_method_change_retries_a_saved_but_missing_registration(harness):
    win, settings, state, dialogs, _ = harness
    state.failed = True
    win._toggle_autostart(True)
    assert settings.get("startup") is True
    assert state.actual is False
    state.failed = False
    win._set_autostart_method("direct")
    assert state.calls[-1] == (True, "direct")
    assert state.actual is True
    assert _checked(win) == (True, True)
    assert not any(kind == "warning" for kind, _ in dialogs[1:])
    assert "Autostart-metod:" in win.status_messages[-1]


def test_programmatic_enable_uses_actual_status_for_both_checkboxes(harness):
    win, settings, state, _dialogs, _ = harness
    state.failed = True
    win.set_autostart(True)
    assert settings.get("startup") is True
    assert _checked(win) == (False, False)


def test_method_setting_exception_does_not_claim_the_choice_was_saved(harness, monkeypatch):
    win, settings, _state, dialogs, _ = harness
    original_set = settings.set

    def set_or_fail(key, value):
        if key == "autostart_method":
            raise OSError("disk full in test")
        return original_set(key, value)

    monkeypatch.setattr(settings, "set", set_or_fail)
    win._set_autostart_method("launcher")
    assert len(dialogs) == 1 and dialogs[0][0] == "warning"
    assert "disk full in test" in dialogs[0][1]
    assert "Valet är sparat" not in dialogs[0][1]
    assert "Autostart-metod:" not in win.status_messages[-1]
