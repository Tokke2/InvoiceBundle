"""Portable checks for COM method order, failures and ownership rules."""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import windows_shortcut as ws


class _Function:
    def __init__(self, fn):
        self.fn = fn
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.fn(*args)


@pytest.mark.parametrize("init_result, expected_uninit", [
    (0, True), (1, True), (ctypes.c_int32(0x80010106).value, False),
])
def test_com_creation_methods_and_apartment_ownership(
    monkeypatch, tmp_path, init_result, expected_uninit
):
    calls = []

    def initialize(_reserved, mode):
        calls.append(("init", mode))
        return init_result

    def create(_clsid, _outer, context, _iid, out):
        calls.append(("create", context))
        ctypes.cast(out, ctypes.POINTER(ctypes.c_void_p))[0] = 101
        return 0

    ole = SimpleNamespace(
        CoInitializeEx=_Function(initialize),
        CoUninitialize=_Function(lambda: calls.append(("uninit",))),
        CoCreateInstance=_Function(create),
    )
    monkeypatch.setattr(ws, "_windows_dll", lambda name: ole)

    def method(interface, index, _result_type, *_arg_types):
        def invoke(*args):
            if index == 0:
                calls.append(("query", interface.value))
                ctypes.cast(args[2], ctypes.POINTER(ctypes.c_void_p))[0] = 202
            elif index == 2:
                calls.append(("release", interface.value))
            else:
                calls.append((index, *args[1:]))
            return 0
        return invoke

    monkeypatch.setattr(ws, "_method", method)
    link = tmp_path / "fakturabunten åäö.lnk"
    ws.create_shortcut(
        link, target="pythonw.exe", arguments='"main.pyw" --minimized',
        workdir="D:/FakturaRäknaren", icon="D:/icon.ico",
        description="Fakturabunten",
    )
    assert calls == [
        ("init", 2), ("create", 1),
        (20, "pythonw.exe"), (11, '"main.pyw" --minimized'),
        (9, "D:/FakturaRäknaren"), (7, "Fakturabunten"),
        (17, "D:/icon.ico", 0), (15, 7),
        ("query", 101), (6, str(link.absolute()), 1),
        ("release", 202), ("release", 101),
        *([("uninit",)] if expected_uninit else []),
    ]


@pytest.mark.parametrize("failed_index", [17, 6])
def test_com_failures_release_interfaces_and_report_hresult(
    monkeypatch, tmp_path, failed_index
):
    calls = []

    def create(_clsid, _outer, _context, _iid, out):
        ctypes.cast(out, ctypes.POINTER(ctypes.c_void_p))[0] = 101
        return 0

    ole = SimpleNamespace(
        CoInitializeEx=_Function(lambda *_args: 0),
        CoUninitialize=_Function(lambda: calls.append("uninit")),
        CoCreateInstance=_Function(create),
    )
    monkeypatch.setattr(ws, "_windows_dll", lambda name: ole)

    def method(interface, index, _result_type, *_arg_types):
        def invoke(*args):
            if index == 0:
                ctypes.cast(args[2], ctypes.POINTER(ctypes.c_void_p))[0] = 202
            elif index == 2:
                calls.append(f"release-{interface.value}")
            if index == failed_index:
                return ctypes.c_int32(0x80070005).value
            return 0
        return invoke

    monkeypatch.setattr(ws, "_method", method)
    with pytest.raises(OSError, match="HRESULT 0x80070005"):
        ws.create_shortcut(
            tmp_path / "x.lnk", target="x", arguments="", workdir="x",
            icon="icon.ico", description="Fakturabunten",
        )
    expected = (["release-202"] if failed_index == 6 else []) + [
        "release-101", "uninit"
    ]
    assert calls == expected


def test_known_folder_result_is_freed_and_returned(monkeypatch):
    path_buffer = ctypes.create_unicode_buffer("D:/Flyttad Autostart åäö")
    calls = []

    def get_folder(_folder_id, flags, _token, out):
        calls.append(("flags", flags))
        ctypes.cast(out, ctypes.POINTER(ctypes.c_void_p))[0] = \
            ctypes.cast(path_buffer, ctypes.c_void_p).value
        return 0

    shell = SimpleNamespace(SHGetKnownFolderPath=_Function(get_folder))
    ole = SimpleNamespace(
        CoTaskMemFree=_Function(lambda pointer: calls.append(("free", pointer.value)))
    )
    monkeypatch.setattr(ws, "_windows_dll", lambda name: shell if name == "shell32" else ole)
    assert ws.startup_folder() == Path("D:/Flyttad Autostart åäö")
    assert calls == [
        ("flags", 0x4000), ("free", ctypes.cast(path_buffer, ctypes.c_void_p).value)
    ]
