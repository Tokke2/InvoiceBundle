"""Native Windows startup-folder and .lnk helpers, with no extra packages.

Windows shell links are COM objects. Calling IShellLinkW directly avoids
requiring PowerShell, Windows Script Host or the pywin32 package. All COM
objects stay on the calling thread and are released before it returns.
This module can be imported on other platforms; its operations are Windows-only.
"""
from __future__ import annotations

import ctypes
import os
import uuid
from pathlib import Path
from typing import Any


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def parse(cls, value: str) -> "_GUID":
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


_CLSID_SHELL_LINK = _GUID.parse("00021401-0000-0000-c000-000000000046")
_IID_SHELL_LINK_W = _GUID.parse("000214f9-0000-0000-c000-000000000046")
_IID_PERSIST_FILE = _GUID.parse("0000010b-0000-0000-c000-000000000046")
_FOLDERID_STARTUP = _GUID.parse("b97d20bb-f46a-4c97-ba10-5e3608430854")
_RPC_E_CHANGED_MODE = 0x80010106


def _windows_dll(name: str) -> Any:
    if os.name != "nt":
        raise OSError("Windows shell API is only available on Windows")
    return ctypes.WinDLL(name, use_last_error=True)  # type: ignore[attr-defined]


def _check_hresult(result: int, operation: str) -> None:
    if result >= 0:
        return
    code = result & 0xFFFFFFFF
    try:
        # HRESULT_FROM_WIN32 embeds the original Win32 error in its low word.
        error = code & 0xFFFF if ((code >> 16) & 0x1FFF) == 7 else code
        explanation = ctypes.FormatError(error).strip()  # type: ignore[attr-defined]
    except Exception:
        explanation = ""
    message = f"{operation}: HRESULT 0x{code:08X}"
    if explanation:
        message += f" ({explanation})"
    raise OSError(message)


def startup_folder() -> Path:
    """Return the current user's actual Startup folder, including redirection."""
    shell = _windows_dll("shell32")
    ole = _windows_dll("ole32")
    get_folder = shell.SHGetKnownFolderPath
    get_folder.argtypes = [
        ctypes.POINTER(_GUID), ctypes.c_uint32,
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
    ]
    get_folder.restype = ctypes.c_int32
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    result_path = ctypes.c_void_p()
    try:
        # KF_FLAG_DONT_VERIFY: also resolve folders that need to be created.
        result = int(get_folder(
            ctypes.byref(_FOLDERID_STARTUP), 0x4000, None,
            ctypes.byref(result_path),
        ))
        _check_hresult(result, "SHGetKnownFolderPath(Startup)")
        if not result_path.value:
            raise OSError("SHGetKnownFolderPath(Startup) returned an empty path")
        text = ctypes.wstring_at(result_path.value)
        if not text:
            raise OSError("SHGetKnownFolderPath(Startup) returned an empty path")
        return Path(text)
    finally:
        if result_path.value:
            ole.CoTaskMemFree(result_path)


def _method(interface: ctypes.c_void_p, index: int, result_type: Any,
            *argument_types: Any) -> Any:
    """Bind one documented IUnknown/IShellLinkW/IPersistFile vtable method."""
    if not interface.value:
        raise OSError("Attempt to call an empty COM interface")
    vtable = ctypes.cast(
        interface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
    ).contents
    address = vtable[index]
    if not address:
        raise OSError(f"Missing COM method at index {index}")
    prototype = ctypes.WINFUNCTYPE(  # type: ignore[attr-defined]
        result_type, ctypes.c_void_p, *argument_types
    )
    return prototype(address)


def create_shortcut(destination: Path, *, target: str, arguments: str,
                    workdir: str, icon: str, description: str,
                    show_cmd: int = 7) -> None:
    """Create a .lnk with an explicit icon using the Windows Shell COM API.

    The caller supplies a temporary destination and is responsible for
    replacing the final link only after creation succeeds.
    """
    ole = _windows_dll("ole32")
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole.CoInitializeEx.restype = ctypes.c_int32
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    ole.CoCreateInstance.argtypes = [
        ctypes.POINTER(_GUID), ctypes.c_void_p, ctypes.c_uint32,
        ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p),
    ]
    ole.CoCreateInstance.restype = ctypes.c_int32

    result = int(ole.CoInitializeEx(None, 2))  # COINIT_APARTMENTTHREADED
    must_uninitialize = result in (0, 1)  # S_OK or S_FALSE
    if result < 0 and (result & 0xFFFFFFFF) != _RPC_E_CHANGED_MODE:
        _check_hresult(result, "CoInitializeEx")
    # RPC_E_CHANGED_MODE means COM is already initialized with another
    # apartment model on this thread; use it without uninitializing it.
    link = ctypes.c_void_p()
    persist = ctypes.c_void_p()
    try:
        result = int(ole.CoCreateInstance(
            ctypes.byref(_CLSID_SHELL_LINK), None, 1,  # CLSCTX_INPROC_SERVER
            ctypes.byref(_IID_SHELL_LINK_W), ctypes.byref(link),
        ))
        _check_hresult(result, "CoCreateInstance(ShellLink)")
        if not link.value:
            raise OSError("CoCreateInstance(ShellLink) returned a null interface")

        for index, operation, value in (
            (20, "SetPath", target),
            (11, "SetArguments", arguments),
            (9, "SetWorkingDirectory", workdir),
            (7, "SetDescription", description),
        ):
            method = _method(link, index, ctypes.c_int32, ctypes.c_wchar_p)
            _check_hresult(int(method(link, str(value))), f"IShellLinkW.{operation}")

        set_icon = _method(
            link, 17, ctypes.c_int32, ctypes.c_wchar_p, ctypes.c_int
        )
        _check_hresult(int(set_icon(link, str(icon), 0)), "IShellLinkW.SetIconLocation")
        set_show = _method(link, 15, ctypes.c_int32, ctypes.c_int)
        _check_hresult(int(set_show(link, int(show_cmd))), "IShellLinkW.SetShowCmd")

        query = _method(
            link, 0, ctypes.c_int32,
            ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p),
        )
        _check_hresult(int(query(
            link, ctypes.byref(_IID_PERSIST_FILE), ctypes.byref(persist)
        )), "QueryInterface(IPersistFile)")
        if not persist.value:
            raise OSError("QueryInterface(IPersistFile) returned a null interface")
        save = _method(persist, 6, ctypes.c_int32, ctypes.c_wchar_p, ctypes.c_int)
        _check_hresult(int(save(
            persist, str(Path(destination).absolute()), 1
        )), "IPersistFile.Save")
    finally:
        try:
            if persist.value:
                _method(persist, 2, ctypes.c_uint32)(persist)
        finally:
            try:
                if link.value:
                    _method(link, 2, ctypes.c_uint32)(link)
            finally:
                if must_uninitialize:
                    ole.CoUninitialize()
