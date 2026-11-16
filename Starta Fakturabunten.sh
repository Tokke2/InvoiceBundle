#!/bin/sh
# Fakturabunten: start without requiring Python to run this file.
# Never install, replace or upgrade an existing interpreter.
APP_DIR=$(CDPATH= cd -P -- "$(dirname -- "$0")" 2>/dev/null && pwd) || exit 1
SYSTEM=$(uname -s 2>/dev/null || printf 'Unknown')
SEARCH_PATH="${PATH:-}:/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:/opt/local/bin"
PY_FOUND=0
PY_SELECTED=

consider_python() {
    candidate=$1
    name=${candidate##*/}
    suffix=${name#python}
    [ "$name" != "$suffix" ] || return
    case "$suffix" in
        ''|2|3) ;;
        2.*|3.*)
            digits=${suffix#?.}
            case "$digits" in ''|*[!0-9.]*) return ;; esac ;;
        *) return ;;
    esac
    [ -f "$candidate" ] || return

    # The macOS developer-tools placeholder can open an unsolicited Apple
    # installation dialog instead of running Python. It is not an interpreter
    # when the developer tools are absent, so never execute it in that case.
    if [ "$SYSTEM" = Darwin ]; then
        case "$candidate" in
            /usr/bin/python|/usr/bin/python3|/usr/bin/python3.*)
                if command -v xcode-select >/dev/null 2>&1 &&
                   ! xcode-select -p >/dev/null 2>&1; then
                    return
                fi ;;
        esac
    fi

    # Even an old, broken or app-local Python suppresses the installation
    # offer. Only a runnable, non-app-local Python can start the application.
    PY_FOUND=1
    [ -n "$PY_SELECTED" ] && return
    [ -x "$candidate" ] || return
    case "$candidate" in "$APP_DIR"/*) return ;; esac
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)' >/dev/null 2>&1; then
        PY_SELECTED=$candidate
    fi
}

discover_python() {
    PY_FOUND=0
    PY_SELECTED=
    saved_ifs=$IFS
    IFS=:
    for directory in $SEARCH_PATH; do
        [ -n "$directory" ] || directory=.
        case "$directory" in
            /*) ;;
            *) directory=$(CDPATH= cd -P -- "$directory" 2>/dev/null && pwd) || continue ;;
        esac
        for candidate in "$directory"/python*; do
            consider_python "$candidate"
        done
    done
    IFS=$saved_ifs
    # Include common framework and user-managed installs even when the
    # desktop environment has a minimal PATH.
    for candidate in /Library/Frameworks/Python.framework/Versions/*/bin/python* \
        "$HOME"/.local/bin/python* "$HOME"/.local/share/uv/python/*/bin/python* \
        "$HOME"/.pyenv/versions/*/bin/python* "$HOME"/.conda/envs/*/bin/python* \
        "$HOME"/anaconda3/bin/python* "$HOME"/miniconda3/bin/python* \
        "$HOME"/anaconda3/envs/*/bin/python* "$HOME"/miniconda3/envs/*/bin/python* \
        "$HOME"/micromamba/bin/python*; do
        consider_python "$candidate"
    done
}

start_application() {
    cd "$APP_DIR" || return 1
    exec "$PY_SELECTED" "$APP_DIR/main.py" --minimized
}

python_unusable() {
    printf '%s\n' 'Python hittades, men ingen tillgänglig systemtolk kan starta Fakturabunten.' \
        'Programmet kräver Python 3.10 eller senare. Befintlig Python har inte ändrats.' >&2
    return 1
}

ask_to_open_download() {
    prompt='Ingen Python hittades. Vill du öppna Python.org för att installera senaste stabila Python?'
    if [ "$SYSTEM" = Darwin ] && command -v osascript >/dev/null 2>&1; then
        osascript -e 'display dialog "Ingen Python hittades. Öppna Python.org för att installera senaste stabila Python?" with title "Fakturabunten" buttons {"Avbryt", "Öppna"} default button "Öppna" cancel button "Avbryt"' >/dev/null 2>&1
        return $?
    fi
    if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && command -v zenity >/dev/null 2>&1; then
        zenity --question --title='Fakturabunten' --text="$prompt" --ok-label='Öppna' --cancel-label='Avbryt' 2>/dev/null
        return $?
    fi
    printf '%s [j/N] ' "$prompt"
    IFS= read -r answer || return 1
    case "$answer" in j|J|ja|Ja|JA|y|Y|yes|Yes|YES) return 0 ;; *) return 1 ;; esac
}

open_download_page() {
    case "$SYSTEM" in
        Darwin)
            url='https://www.python.org/downloads/macos/'
            if command -v open >/dev/null 2>&1; then
                open "$url" >/dev/null 2>&1 && return 0
            fi ;;
        *)
            url='https://www.python.org/downloads/'
            if command -v xdg-open >/dev/null 2>&1; then
                xdg-open "$url" >/dev/null 2>&1 && return 0
            fi ;;
    esac
    printf 'Kunde inte öppna webbläsaren. Öppna själv: %s\n' "$url" >&2
    return 1
}

if [ ! -f "$APP_DIR/main.py" ]; then
    printf '%s\n' 'Fakturabunten saknas i startfilens mapp.' >&2
    exit 1
fi

discover_python
[ -n "$PY_SELECTED" ] && start_application
[ "$PY_FOUND" -eq 1 ] && { python_unusable; exit 1; }
# Automatic login must never display an installation dialog.
if [ "${1:-}" = '--no-prompt' ]; then
    printf '%s\n' 'Python saknas; starta Fakturabunten manuellt om du vill installera Python.' >&2
    exit 2
fi

if ! ask_to_open_download; then
    printf '\n%s\n' 'Ingen Python installerades. Starta filen igen när Python finns.'
    exit 2
fi
# Recheck after the question: Python might have appeared in the meantime.
discover_python
[ -n "$PY_SELECTED" ] && start_application
[ "$PY_FOUND" -eq 1 ] && { python_unusable; exit 1; }
if open_download_page; then
    printf '\n%s\n' 'Installera Python från den officiella sidan och starta sedan Fakturabunten igen.'
    if [ "$SYSTEM" = Darwin ] && command -v osascript >/dev/null 2>&1; then
        osascript -e 'display dialog "Installera Python från den officiella sidan och starta sedan Fakturabunten igen." with title "Fakturabunten" buttons {"OK"} default button "OK"' >/dev/null 2>&1 || :
    elif [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && command -v zenity >/dev/null 2>&1; then
        zenity --info --title='Fakturabunten' --text='Installera Python från den officiella sidan och starta sedan Fakturabunten igen.' 2>/dev/null || :
    fi
fi
exit 2
