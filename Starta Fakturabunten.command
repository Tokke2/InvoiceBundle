#!/bin/sh
# macOS double-click entry point; the shared launcher also runs on Linux.
APP_DIR=$(CDPATH= cd -P -- "$(dirname -- "$0")" 2>/dev/null && pwd) || exit 1
exec /bin/sh "$APP_DIR/Starta Fakturabunten.sh" "$@"
