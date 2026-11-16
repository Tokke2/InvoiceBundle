"""Windows-native start-file and package-worker tests; never install Python."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='real Windows test')


def _powershell(*args):
    return subprocess.run(
        ['powershell.exe', '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', *args],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60,
    )


def test_windows_missing_existing_broken_and_concurrent_install_scenarios():
    result = _powershell('-File', str(ROOT / 'tests' / 'windows_bootstrap_scenarios.ps1'))
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert 'Windows bootstrap scenarios passed' in result.stdout


def test_real_windows_discovery_finds_existing_interpreter_without_installing():
    script = str(ROOT / 'autostart' / 'start_fakturabunten.ps1').replace("'", "''")
    command = (
        f". '{script}' -NoMain; $p = Get-InstalledPython; "
        "if (-not $p.Found -or -not $p.Executable) { "
        "$p | ConvertTo-Json | Write-Output; "
        "$cmd = Get-Command python.exe -ErrorAction SilentlyContinue; "
        "Write-Output ('python command: ' + $cmd.Source); "
        "throw 'installed Python not detected' }; "
        "if ($env:PYTHON_MANAGER_AUTOMATIC_INSTALL -ne '0') { throw 'automatic install enabled' }; "
        "Write-Output $p.Executable"
    )
    result = _powershell('-Command', command)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert 'python' in result.stdout.lower()


def test_real_windows_start_file_runs_an_existing_python_without_prompt(tmp_path):
    app = tmp_path / 'Fakturabunten med mellanslag'
    (app / 'autostart').mkdir(parents=True)
    shutil.copyfile(ROOT / 'Starta Fakturabunten.bat', app / 'Starta Fakturabunten.bat')
    shutil.copyfile(ROOT / 'autostart' / 'start_fakturabunten.ps1',
                    app / 'autostart' / 'start_fakturabunten.ps1')
    sentinel = tmp_path / 'started.txt'
    program = (
        'import os\nfrom pathlib import Path\n'
        "Path(os.environ['FB_START_TEST_SENTINEL']).write_text('started', encoding='utf-8')\n"
    )
    (app / 'main.py').write_text(program, encoding='utf-8')
    (app / 'main.pyw').write_text(program, encoding='utf-8')
    env = dict(os.environ, FB_START_TEST_SENTINEL=str(sentinel))
    result = subprocess.run(
        [os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', 'call',
         str(app / 'Starta Fakturabunten.bat')],
        cwd=app, env=env, input='', capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=60,
    )
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert 'Vill du' not in result.stdout
    deadline = time.monotonic() + 15
    while not sentinel.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert sentinel.read_text(encoding='utf-8') == 'started'


def test_windows_pid_probe_does_not_terminate_the_process():
    from plugins import python_update_scheduler as scheduler

    process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        assert scheduler._pid_is_alive(process.pid)
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=10)
    assert not scheduler._pid_is_alive(process.pid)


def test_native_windows_python_version_probe_preserves_its_quotes():
    exe = sys.executable.replace("'", "''")
    command = (
        f"$lines = @(& '{exe}' -c \"import sys; print('%d.%d.%d' % sys.version_info[:3])\" 2>&1); "
        "if ($LASTEXITCODE -ne 0 -or $lines.Count -eq 0) { throw ($lines -join ' ') }; "
        "Write-Output $lines[-1]"
    )
    result = _powershell('-Command', command)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stdout.strip().startswith(f'{sys.version_info.major}.')
