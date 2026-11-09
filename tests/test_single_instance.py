from __future__ import annotations

import sys
import types


def _qt_modules(monkeypatch, *, core=None, network=None):
    package = types.ModuleType("PySide6")
    package.__path__ = []
    core_mod = core or types.ModuleType("PySide6.QtCore")
    network_mod = network or types.ModuleType("PySide6.QtNetwork")
    monkeypatch.setitem(sys.modules, "PySide6", package)
    monkeypatch.setitem(sys.modules, "PySide6.QtCore", core_mod)
    monkeypatch.setitem(sys.modules, "PySide6.QtNetwork", network_mod)
    return core_mod, network_mod


def _main_module():
    import main
    return main


def test_lock_location_is_shared_by_app_copies(tmp_path, monkeypatch):
    main = _main_module()
    monkeypatch.setattr(main, "CURRENT_PLATFORM", "linux")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(main, "BASE_DIR", tmp_path / "copy-one")
    first = main._single_instance_lock_path()
    monkeypatch.setattr(main, "BASE_DIR", tmp_path / "copy-two")
    second = main._single_instance_lock_path()
    assert first == second
    assert first == (
        tmp_path / "state" / "RickardLangkvist" / "Fakturabunten"
        / main.LOCK_FILE_NAME
    )


def test_lock_failure_is_fail_closed_and_release_is_idempotent(
    tmp_path, monkeypatch
):
    main = _main_module()
    main._release_single_instance_lock()
    monkeypatch.setattr(main, "CURRENT_PLATFORM", "linux")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    made = []

    class FakeLockFile:
        def __init__(self, path):
            self.path = path
            self.unlocked = False
            made.append(self)

        def tryLock(self, _timeout):  # noqa: N802
            return True

        def unlock(self):
            self.unlocked = True

    core = types.ModuleType("PySide6.QtCore")
    core.QLockFile = FakeLockFile
    _qt_modules(monkeypatch, core=core)
    try:
        assert main._acquire_single_instance_lock() is True
        assert made[0].path.endswith(main.LOCK_FILE_NAME)
        main._release_single_instance_lock()
        main._release_single_instance_lock()
        assert made[0].unlocked is True
    finally:
        main._release_single_instance_lock()


def test_lock_contention_or_lock_error_never_starts_another_copy(
    tmp_path, monkeypatch
):
    main = _main_module()
    main._release_single_instance_lock()
    monkeypatch.setattr(main, "CURRENT_PLATFORM", "linux")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    class BusyLockFile:
        def __init__(self, _path):
            pass

        def tryLock(self, _timeout):  # noqa: N802
            return False

    core = types.ModuleType("PySide6.QtCore")
    core.QLockFile = BusyLockFile
    _qt_modules(monkeypatch, core=core)
    assert main._acquire_single_instance_lock() is False

    class BrokenLockFile:
        def __init__(self, _path):
            raise PermissionError("lock directory is read-only")

    core.QLockFile = BrokenLockFile
    assert main._acquire_single_instance_lock() is False
    main._release_single_instance_lock()


class _Signal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self._callbacks):
            callback(*args)


class _LocalSocket:
    def __init__(self):
        self.readyRead = _Signal()
        self.disconnected = _Signal()
        self.incoming = bytearray()
        self.written = bytearray()
        self.deleted = False

    def bytesAvailable(self):
        return len(self.incoming)

    def readAll(self):
        data = bytes(self.incoming)
        self.incoming.clear()
        return data

    def write(self, data):
        self.written.extend(data)
        return len(data)

    def flush(self):
        pass

    def disconnectFromServer(self):
        self.disconnected.emit()

    def deleteLater(self):
        self.deleted = True

    def abort(self):
        self.deleted = True

    def send(self, data):
        self.incoming.extend(data)
        self.readyRead.emit()


class _LocalServer:
    class SocketOption:
        UserAccessOption = 1

    instances = []

    def __init__(self):
        self.newConnection = _Signal()
        self.pending = []
        self.name = ""
        self.instances.append(self)

    def setSocketOptions(self, _options):
        pass

    def listen(self, name):
        self.name = name
        return True

    def hasPendingConnections(self):
        return bool(self.pending)

    def nextPendingConnection(self):
        return self.pending.pop(0)

    def errorString(self):
        return "fake local server error"

    @staticmethod
    def removeServer(_name):
        return True


def test_focus_server_accepts_and_handles_second_start_request(monkeypatch):
    main = _main_module()
    _LocalServer.instances.clear()
    main._FOCUS_SERVER = None

    core = types.ModuleType("PySide6.QtCore")
    core.QTimer = types.SimpleNamespace(singleShot=lambda *_args: None)
    network = types.ModuleType("PySide6.QtNetwork")
    network.QLocalServer = _LocalServer
    _qt_modules(monkeypatch, core=core, network=network)

    focused = []
    assert main._start_focus_server(lambda: focused.append(True)) == "started"
    server = _LocalServer.instances[-1]
    client = _LocalSocket()
    server.pending.append(client)
    server.newConnection.emit()
    client.send(b"FOCUS\n")

    assert server.name == main.FOCUS_SERVER_NAME
    assert focused == [True]
    assert bytes(client.written) == b"OK\n"
    main._FOCUS_SERVER = None


def test_second_start_sends_focus_request_to_existing_server(monkeypatch):
    main = _main_module()
    clients = []

    class FakeClientSocket:
        def __init__(self):
            self.written = bytearray()
            self.disconnected = False
            clients.append(self)

        def connectToServer(self, name):
            self.name = name

        def waitForConnected(self, _timeout):
            return True

        def write(self, data):
            self.written.extend(data)
            return len(data)

        def flush(self):
            pass

        def waitForBytesWritten(self, _timeout):
            return True

        def disconnectFromServer(self):
            self.disconnected = True

        def abort(self):
            pass

    network = types.ModuleType("PySide6.QtNetwork")
    network.QLocalSocket = FakeClientSocket
    _qt_modules(monkeypatch, network=network)

    assert main._request_focus_existing(timeout_seconds=0.2) is True
    assert clients[0].name == main.FOCUS_SERVER_NAME
    assert bytes(clients[0].written) == b"FOCUS\n"
    assert clients[0].disconnected is True
