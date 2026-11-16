"""Exercise the no-Python and existing-Python launcher flows without installing anything."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(os.name == 'nt', reason='POSIX start files')

SEARCH = 'SEARCH_PATH="${PATH:-}:/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:/opt/local/bin"'
FRAMEWORK = '/Library/Frameworks/Python.framework/Versions/*/bin/python*'


def _executable(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    path.chmod(0o755)
    return path


@pytest.fixture
def launcher(tmp_path):
    app = tmp_path / 'Fakturabunten med mellanslag'
    app.mkdir()
    source = (ROOT / 'Starta Fakturabunten.sh').read_text(encoding='utf-8')
    # Isolate discovery, not application logic, so a CI runner's Python does
    # not hide the genuinely absent/broken cases.
    assert source.count(SEARCH) == 1 and source.count(FRAMEWORK) == 1
    source = source.replace(SEARCH, 'SEARCH_PATH="$FB_TEST_SEARCH_PATH"')
    source = source.replace(FRAMEWORK, '"$FB_TEST_EMPTY"/python*')
    _executable(app / 'Starta Fakturabunten.sh', source)
    _executable(
        app / 'Starta Fakturabunten.command',
        (ROOT / 'Starta Fakturabunten.command').read_text(encoding='utf-8'),
    )
    (app / 'main.py').write_text('# Never actually executed by these tests\n', encoding='utf-8')
    fake_bin = tmp_path / 'test tools'
    _executable(fake_bin / 'uname', '#!/bin/sh\nprintf "%s\\n" "$FB_TEST_OS"\n')
    browser = '#!/bin/sh\nprintf "%s\\n" "$1" >> "$FB_BROWSER_MARKER"\n'
    _executable(fake_bin / 'xdg-open', browser)
    _executable(fake_bin / 'open', browser)
    _executable(
        fake_bin / 'osascript',
        '#!/bin/sh\nprintf "question\\n" >> "$FB_PROMPT_MARKER"\n'
        '[ "$FB_CONFIRM" = yes ]\n',
    )
    env = os.environ.copy()
    env.update({
        'PATH': str(fake_bin) + os.pathsep + '/usr/bin:/bin',
        'HOME': str(tmp_path / 'empty-home'),
        'FB_TEST_SEARCH_PATH': str(tmp_path / 'installed Python'),
        'FB_TEST_EMPTY': str(tmp_path / 'no-framework'),
        'FB_BROWSER_MARKER': str(tmp_path / 'browser.txt'),
        'FB_PROMPT_MARKER': str(tmp_path / 'prompt.txt'),
        'FB_EXEC_MARKER': str(tmp_path / 'executed.txt'),
        'FB_CONFIRM': 'no',
    })
    env.pop('DISPLAY', None)
    env.pop('WAYLAND_DISPLAY', None)
    return app, env


def _run(launcher, system='Linux', answer='', *args):
    app, env = launcher
    env = dict(env, FB_TEST_OS=system)
    name = 'Starta Fakturabunten.command' if system == 'Darwin' else 'Starta Fakturabunten.sh'
    return subprocess.run(
        ['/bin/sh', str(app / name), *args], input=answer, text=True,
        capture_output=True, cwd=app.parent, env=env, timeout=15,
    )


def _fake_python(path: Path, compatible: bool = True):
    return _executable(
        path,
        '#!/bin/sh\n'
        f'if [ "$1" = "-c" ]; then exit {0 if compatible else 1}; fi\n'
        'printf "%s\\n" "$@" > "$FB_EXEC_MARKER"\nexit 0\n',
    )


@pytest.mark.parametrize('system', ['Linux', 'Darwin'])
def test_existing_python_starts_repeatedly_without_any_install_offer(launcher, system):
    app, env = launcher
    _fake_python(Path(env['FB_TEST_SEARCH_PATH']) / 'python3.14')
    for _ in range(2):
        result = _run(launcher, system, 'j\n')
        assert result.returncode == 0, result.stderr
        assert 'Vill du' not in result.stdout
        assert not Path(env['FB_PROMPT_MARKER']).exists()
        assert not Path(env['FB_BROWSER_MARKER']).exists()
        assert Path(env['FB_EXEC_MARKER']).read_text(encoding='utf-8').splitlines() == [
            str(app / 'main.py'), '--minimized'
        ]


@pytest.mark.parametrize('system', ['Linux', 'Darwin'])
def test_old_broken_or_private_python_never_prompts_to_install(launcher, system):
    app, env = launcher
    candidate = _fake_python(Path(env['FB_TEST_SEARCH_PATH']) / 'python3.9', compatible=False)
    result = _run(launcher, system, 'j\n')
    assert result.returncode == 1
    assert 'Python hittades' in result.stderr
    assert 'Vill du' not in result.stdout
    assert not Path(env['FB_PROMPT_MARKER']).exists()
    assert not Path(env['FB_BROWSER_MARKER']).exists()
    candidate.unlink()
    private = _fake_python(app / 'python' / 'bin' / 'python3')
    env['FB_TEST_SEARCH_PATH'] = str(private.parent)
    result = _run(launcher, system, 'j\n')
    assert result.returncode == 1
    assert not Path(env['FB_PROMPT_MARKER']).exists()
    assert not Path(env['FB_BROWSER_MARKER']).exists()
    assert not Path(env['FB_EXEC_MARKER']).exists()


@pytest.mark.parametrize('system', ['Linux', 'Darwin'])
def test_missing_python_offers_official_page_only_with_consent(launcher, system):
    _app, env = launcher
    declined = _run(launcher, system, 'n\n')
    assert declined.returncode == 2
    assert not Path(env['FB_BROWSER_MARKER']).exists()

    env['FB_CONFIRM'] = 'yes'
    accepted = _run(launcher, system, 'j\n')
    assert accepted.returncode == 2
    expected = ('https://www.python.org/downloads/macos/' if system == 'Darwin'
                else 'https://www.python.org/downloads/')
    assert Path(env['FB_BROWSER_MARKER']).read_text(encoding='utf-8').strip() == expected
    assert not Path(env['FB_EXEC_MARKER']).exists()

    # Once installed, repeated launches do not ask or reopen the site.
    prompts_before = (Path(env['FB_PROMPT_MARKER']).read_text(encoding='utf-8')
                      if Path(env['FB_PROMPT_MARKER']).exists() else '')
    _fake_python(Path(env['FB_TEST_SEARCH_PATH']) / 'python3')
    for _ in range(2):
        started = _run(launcher, system, 'j\n')
        assert started.returncode == 0, started.stderr
        assert 'Vill du' not in started.stdout
    assert Path(env['FB_BROWSER_MARKER']).read_text(encoding='utf-8').splitlines() == [expected]
    if system == 'Darwin':
        assert Path(env['FB_PROMPT_MARKER']).read_text(encoding='utf-8') == prompts_before


@pytest.mark.parametrize('system', ['Linux', 'Darwin'])
def test_automatic_start_never_asks_when_python_is_missing(launcher, system):
    _app, env = launcher
    env['FB_CONFIRM'] = 'yes'
    result = _run(launcher, system, 'j\n', '--no-prompt')
    assert result.returncode == 2
    assert 'Python saknas' in result.stderr
    assert not Path(env['FB_PROMPT_MARKER']).exists()
    assert not Path(env['FB_BROWSER_MARKER']).exists()


@pytest.mark.parametrize('system', ['Linux', 'Darwin'])
@pytest.mark.parametrize('relative', [
    '.pyenv/versions/3.14.0/bin/python3',
    '.local/share/uv/python/cpython-3.14/bin/python3',
    '.conda/envs/work/bin/python3',
])
def test_user_managed_python_outside_path_is_detected(launcher, system, relative):
    app, env = launcher
    candidate = Path(env['HOME']) / relative
    _fake_python(candidate)
    result = _run(launcher, system, 'j\n')
    assert result.returncode == 0, result.stderr
    assert Path(env['FB_EXEC_MARKER']).read_text(encoding='utf-8').splitlines() == [
        str(app / 'main.py'), '--minimized'
    ]
    assert not Path(env['FB_PROMPT_MARKER']).exists()
    assert not Path(env['FB_BROWSER_MARKER']).exists()


@pytest.mark.parametrize('system', ['Linux', 'Darwin'])
def test_python_appearing_during_the_question_starts_without_opening_download(launcher, system, tmp_path):
    app, env = launcher
    template = _fake_python(tmp_path / 'python-template')
    env['FB_PY_TEMPLATE'] = str(template)
    fake_bin = Path(env['PATH'].split(os.pathsep)[0])
    program = (
        '#!/bin/sh\n'
        'mkdir -p "$FB_TEST_SEARCH_PATH"\n'
        'cp "$FB_PY_TEMPLATE" "$FB_TEST_SEARCH_PATH/python3"\n'
        'chmod u+x "$FB_TEST_SEARCH_PATH/python3"\n'
        'exit 0\n'
    )
    if system == 'Darwin':
        _executable(fake_bin / 'osascript', program)
    else:
        env['DISPLAY'] = ':99'
        _executable(fake_bin / 'zenity', program)
    result = _run(launcher, system)
    assert result.returncode == 0, result.stderr
    assert Path(env['FB_EXEC_MARKER']).read_text(encoding='utf-8').splitlines() == [
        str(app / 'main.py'), '--minimized'
    ]
    assert not Path(env['FB_BROWSER_MARKER']).exists()
