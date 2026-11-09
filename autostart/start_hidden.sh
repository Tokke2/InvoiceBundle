#!/bin/sh
# Fakturabunten — gömd autostart. PORTABEL.
HERE=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
APP_DIR=$(CDPATH= cd -- "$HERE/.." && pwd)
LOG="$APP_DIR/logs/autostart.log"
i=0
while [ "$i" -lt 45 ]; do
  if [ -d "$APP_DIR" ] && [ -f "$APP_DIR/main.py" ]; then
    break
  fi
  i=$((i + 1))
  sleep 2
done
if [ ! -f "$APP_DIR/main.py" ]; then
  mkdir -p "$(dirname "$LOG")" 2>/dev/null
  echo "$(date '+%Y-%m-%d %H:%M:%S')  FAIL appmappen inte redo: $APP_DIR" >> "$LOG" 2>/dev/null
  exit 1
fi
cd "$APP_DIR" || exit 1
mkdir -p "$APP_DIR/logs"
if command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  PY=python
fi
echo "$(date '+%Y-%m-%d %H:%M:%S')  OK cwd=$APP_DIR --minimized" >> "$LOG"
exec "$PY" "$APP_DIR/main.py" --minimized
