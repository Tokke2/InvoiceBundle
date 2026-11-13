"""System Python selection, probing, persistence, and safe fallback."""
from __future__ import annotations

import builtins
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _directory in (
    str(PROJECT_DIR), str(PROJECT_DIR / "ui"), str(PROJECT_DIR / "plugins")
):
    if _directory not in sys.path:
        sys.path.insert(0, _directory)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _main_module(
    monkeypatch,
    version=(3, 14, 0),
    executable="/system/Python314/python.exe",
    base_dir=PROJECT_DIR,
):
    import main

    monkeypatch.setattr(
        main, "sys",
        SimpleNamespace(
            version_info=version,
            executable=executable,
            argv=["main.py"],
        ),
    )
    monkeypatch.setattr(main, "BASE_DIR", Path(base_dir))
    monkeypatch.setattr(main, "CURRENT_PLATFORM", "linux")
    monkeypatch.setattr(main, "DEBUG_MODE", False)
    monkeypatch.setattr(main, "SELFTEST", False)
    monkeypatch.setattr(main, "_RUNTIME_VERIFIED", set())
    monkeypatch.delenv(main._RUNTIME_ATTEMPTS, raising=False)
    return main


def test_selects_first_usable_system_python_and_remembers_it(
    monkeypatch, tmp_path,
):
    py315 = "/system/Python315/python.exe"
    py314 = "/system/Python314/python.exe"
    main = _main_module(
        monkeypatch,
        version=(3, 10, 1),
        executable="/system/Python310/python.exe",
        base_dir=tmp_path,
    )
    probes = []
    launches = []
    monkeypatch.setattr(
        main, "_system_python_candidates",
        lambda: [(py315, (3, 15, 2)), (py314, (3, 14, 9))],
    )

    def _probe(executable):
        probes.append(executable)
        return executable == py314

    monkeypatch.setattr(main, "_python_has_runtime", _probe)
    monkeypatch.setattr(
        main, "_spawn_with_python",
        lambda executable, **kwargs: launches.append((executable, kwargs)) or True,
    )

    assert main._relaunch_preferred_python() is True
    assert probes == [py315, py314]
    assert launches[0][0] == py314
    assert launches[0][1]["mark_current"] is False
    state = json.loads(main._runtime_selection_path().read_text(encoding="utf-8"))
    assert state["executable"] == str(Path(py314).resolve())
    assert state["version"] == [3, 14, 9]
    assert state["verified_at"]


def test_remembered_python_is_checked_after_newer_candidates(
    monkeypatch, tmp_path,
):
    py315 = "/system/Python315/python.exe"
    py314 = "/system/Python314/python.exe"
    main = _main_module(
        monkeypatch,
        version=(3, 13, 8),
        executable="/system/Python313/python.exe",
        base_dir=tmp_path,
    )
    main._remember_selected_python(py314, (3, 14, 9))
    probes = []
    launches = []
    monkeypatch.setattr(
        main, "_system_python_candidates",
        lambda: [(py315, (3, 15, 2)), ("/system/Python312/python.exe", (3, 12, 8))],
    )

    def _probe(executable):
        probes.append(executable)
        return executable == py314

    monkeypatch.setattr(main, "_python_has_runtime", _probe)
    monkeypatch.setattr(
        main, "_spawn_with_python",
        lambda executable, **kwargs: launches.append((executable, kwargs)) or True,
    )

    assert main._relaunch_preferred_python() is True
    assert probes == [py315, py314]
    assert launches[0][0] == py314
    assert main._load_selected_python() == (
        str(Path(py314).resolve()), (3, 14, 9)
    )


def test_failed_remembered_python_is_replaced_with_next_usable_one(
    monkeypatch, tmp_path,
):
    py315 = "/system/Python315/python.exe"
    py314 = "/system/Python314/python.exe"
    main = _main_module(
        monkeypatch,
        version=(3, 10, 1),
        executable="/system/Python310/python.exe",
        base_dir=tmp_path,
    )
    main._remember_selected_python(py315, (3, 15, 2))
    launches = []
    monkeypatch.setattr(
        main, "_system_python_candidates",
        lambda: [(py315, (3, 15, 2)), (py314, (3, 14, 9))],
    )
    monkeypatch.setattr(
        main, "_python_has_runtime", lambda executable: executable == py314
    )
    monkeypatch.setattr(
        main, "_spawn_with_python",
        lambda executable, **kwargs: launches.append((executable, kwargs)) or True,
    )

    assert main._relaunch_preferred_python() is True
    assert launches[0][0] == py314
    assert main._load_selected_python() == (
        str(Path(py314).resolve()), (3, 14, 9)
    )


def test_unusable_newer_python_uses_working_current_interpreter(
    monkeypatch, tmp_path,
):
    py315 = "/system/Python315/python.exe"
    py314 = "/system/Python314/python.exe"
    main = _main_module(
        monkeypatch,
        version=(3, 14, 9),
        executable=py314,
        base_dir=tmp_path,
    )
    probes = []
    launches = []
    monkeypatch.setattr(
        main, "_system_python_candidates",
        lambda: [(py315, (3, 15, 2))],
    )

    def _probe(executable):
        probes.append(executable)
        return executable == py314

    monkeypatch.setattr(main, "_python_has_runtime", _probe)
    monkeypatch.setattr(
        main, "_spawn_with_python",
        lambda executable, **kwargs: launches.append((executable, kwargs)) or True,
    )

    assert main._relaunch_preferred_python() is False
    assert probes == [py315, py314]
    assert launches == []
    assert main._load_selected_python() == (
        str(Path(py314).resolve()), (3, 14, 9)
    )


def test_fallback_persists_a_working_python_314(monkeypatch, tmp_path):
    py314 = "/system/Python314/python.exe"
    main = _main_module(
        monkeypatch,
        version=(3, 15, 2),
        executable="/system/Python315/python.exe",
        base_dir=tmp_path,
    )
    launches = []
    monkeypatch.setattr(
        main, "_system_python_candidates",
        lambda: [
            (py314, (3, 14, 9)),
            ("/system/Python313/python.exe", (3, 13, 8)),
        ],
    )
    monkeypatch.setattr(
        main, "_python_has_runtime", lambda executable: executable == py314
    )
    monkeypatch.setattr(
        main, "_spawn_with_python",
        lambda executable, **kwargs: launches.append((executable, kwargs)) or True,
    )

    assert main._relaunch_runtime_fallback() is True
    assert launches[0][0] == py314
    assert launches[0][1]["mark_current"] is True
    assert main._load_selected_python() == (
        str(Path(py314).resolve()), (3, 14, 9)
    )


def test_python_discovery_ignores_app_local_runtime(monkeypatch, tmp_path):
    main = _main_module(monkeypatch, base_dir=tmp_path)
    private = tmp_path / "python" / "bin" / "python3.15"
    private.parent.mkdir(parents=True)
    private.write_text("private", encoding="utf-8")
    private_venv = tmp_path / ".venv" / "bin" / "python3"
    private_venv.parent.mkdir(parents=True)
    private_venv.write_text("private venv", encoding="utf-8")
    assert main._is_app_local_python(private)
    assert main._is_app_local_python(private_venv)
    commands = []

    def _which(name):
        if name == "python3.15":
            return str(private)
        if name == "python3.14":
            return "/usr/bin/python3.14"
        return None

    def _inspect(command):
        commands.append(command)
        if command == ["/usr/bin/python3.14"]:
            return "/usr/bin/python3.14", (3, 14, 9)
        return None

    monkeypatch.setattr(main.shutil, "which", _which)
    monkeypatch.setattr(main, "_inspect_python", _inspect)

    assert main._system_python_candidates() == [
        ("/usr/bin/python3.14", (3, 14, 9))
    ]
    assert commands == [["/usr/bin/python3.14"]]


def test_pythonw_and_python_exe_share_an_attempt_identity(
    monkeypatch, tmp_path,
):
    main = _main_module(monkeypatch, base_dir=tmp_path)
    install_dir = tmp_path.parent / "Python315"
    pythonw = install_dir / "pythonw.exe"
    python = install_dir / "python.exe"
    assert main._python_path_key(pythonw) == main._python_path_key(python)


def test_runtime_attempt_guard_prevents_returning_to_failed_python(
    monkeypatch, tmp_path,
):
    py314 = "/system/Python314/python.exe"
    py315 = "/system/Python315/python.exe"
    main = _main_module(
        monkeypatch, version=(3, 14, 9), executable=py314, base_dir=tmp_path
    )
    monkeypatch.setenv(
        main._RUNTIME_ATTEMPTS,
        json.dumps([main._python_path_key(py314), main._python_path_key(py315)]),
    )
    calls = []
    monkeypatch.setattr(
        main, "_system_python_candidates",
        lambda: [(py315, (3, 15, 2)), (py314, (3, 14, 9))],
    )
    monkeypatch.setattr(main, "_python_has_runtime", lambda _executable: True)
    monkeypatch.setattr(
        main, "_spawn_with_python",
        lambda executable, **kwargs: calls.append((executable, kwargs)) or True,
    )

    assert main._relaunch_runtime_fallback() is False
    assert calls == []


@pytest.mark.parametrize(
    "available", ["modern", "legacy", "broken_modern", "neither", "missing_qt"]
)
def test_runtime_probe_uses_available_pdf_api_and_still_requires_qt(
    available, capsys,
):
    import main

    calls = []
    qt_calls = []

    def module_import(name):
        calls.append(name)
        if name == "PySide6" and available == "missing_qt":
            raise ImportError("no Qt")
        if name == "pymupdf" and available != "modern":
            if available == "broken_modern":
                raise RuntimeError("modern PDF module is broken")
            raise ImportError("no modern PDF module")
        if name == "fitz" and available == "neither":
            raise ImportError("no legacy PDF module")
        return SimpleNamespace()

    class FakeApplication:
        def __init__(self, args):
            qt_calls.append(("created", args))

        def quit(self):
            qt_calls.append(("quit",))

    def fake_import(name, *args, **kwargs):
        if name == "importlib":
            return SimpleNamespace(import_module=module_import)
        if name == "PySide6.QtWidgets":
            return SimpleNamespace(QApplication=FakeApplication)
        return builtins.__import__(name, *args, **kwargs)

    namespace = {"__builtins__": {**vars(builtins), "__import__": fake_import}}
    if available in ("neither", "missing_qt"):
        with pytest.raises(ImportError):
            exec(main._RUNTIME_PROBE, namespace)
        assert not qt_calls
        assert "FAKTURABUNTEN_RUNTIME_OK" not in capsys.readouterr().out
        return

    exec(main._RUNTIME_PROBE, namespace)
    assert all(name in calls for name in (
        "PySide6", "reportlab", "pypdf", "PIL", "pytesseract", "qrcode"
    ))
    assert "pymupdf" in calls
    assert ("fitz" in calls) is (available != "modern")
    assert qt_calls == [("created", []), ("quit",)]
    assert "FAKTURABUNTEN_RUNTIME_OK" in capsys.readouterr().out


def test_windows_installer_uses_the_same_runtime_probe_as_main():
    import main

    script = (PROJECT_DIR / "autostart" / "install_python.ps1").read_text(
        encoding="utf-8"
    )
    match = re.search(r"\$probeCode = @'\n(.*?)\n'@", script, re.DOTALL)
    assert match is not None
    assert match.group(1).strip() == main._RUNTIME_PROBE.strip()
