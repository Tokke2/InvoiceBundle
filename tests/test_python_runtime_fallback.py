"""System Python selection, probing, persistence, and safe fallback."""
from __future__ import annotations

import builtins
import json
import os
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
    monkeypatch.setattr(main, "_additional_system_python_paths", lambda: [])

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


def test_windows_manager_lists_installed_paths_without_version_launches(monkeypatch):
    import main

    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout=(
            " -V:3.14 *        C:\\Program Files\\Python314\\python.exe\n"
            " -V:3.15          C:\\Users\\me\\Python315\\python.exe\n"
        ))

    monkeypatch.setattr(main.subprocess, "run", run)
    monkeypatch.setenv("PYTHON_MANAGER_AUTOMATIC_INSTALL", "1")
    paths = main._windows_launcher_paths("C:\\PythonManager\\py.exe")
    assert paths == [
        "C:\\Program Files\\Python314\\python.exe",
        "C:\\Users\\me\\Python315\\python.exe",
    ]
    assert calls[0][0] == ["C:\\PythonManager\\py.exe", "-0p"]
    assert calls[0][1]["env"]["PYTHON_MANAGER_AUTOMATIC_INSTALL"] == "0"
    assert os.environ["PYTHON_MANAGER_AUTOMATIC_INSTALL"] == "1"  # child only


def test_windows_runtime_discovery_only_probes_listed_executables(monkeypatch, tmp_path):
    main = _main_module(monkeypatch, base_dir=tmp_path)
    monkeypatch.setattr(main, "CURRENT_PLATFORM", "windows")
    monkeypatch.setattr(main.shutil, "which", lambda name: "py.exe" if name == "py.exe" else None)
    monkeypatch.setattr(main, "_windows_launcher_paths", lambda _: ["/installed/python.exe"])
    monkeypatch.setattr(main, "_additional_system_python_paths", lambda: [])
    for key in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        monkeypatch.delenv(key, raising=False)
    commands = []
    def inspect(command):
        commands.append(command)
        return (command[0], (3, 14, 0))
    monkeypatch.setattr(main, "_inspect_python", inspect)
    main._system_python_candidates()
    assert commands == [["/installed/python.exe"]]
    assert all(len(command) == 1 and command[0] != "py.exe" for command in commands)


def test_inspection_disables_python_manager_auto_install(monkeypatch):
    import main

    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="/installed/python\n3.14.0\n")
    monkeypatch.setattr(main.subprocess, "run", run)
    assert main._inspect_python(["/installed/python"])[1] == (3, 14, 0)
    assert calls[0][1]["env"]["PYTHON_MANAGER_AUTOMATIC_INSTALL"] == "0"


def test_python_discovery_includes_user_managed_frameworks_and_future_versions(monkeypatch, tmp_path):
    import main

    python = tmp_path / ".pyenv" / "versions" / "3.16.0" / "bin" / "python3.16"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(main, "CURRENT_PLATFORM", "linux")
    assert python in main._additional_system_python_paths()
