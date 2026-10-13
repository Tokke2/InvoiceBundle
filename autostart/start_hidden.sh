#!/bin/sh
# FakturaRäknaren — gömd autostart. Genererad av appen.
APP_DIR='/home/user/FakturaRäknaren_'
LOG="$APP_DIR/logs/autostart.log"
i=0
while [ "$i" -lt 45 ]; do
  if [ -d '/home/user/FakturaRäknaren_' ] && [ -f '/home/user/FakturaRäknaren_/main.py' ]; then
    break
  fi
  i=$((i + 1))
  sleep 2
done
if ! { [ -d '/home/user/FakturaRäknaren_' ] && [ -f '/home/user/FakturaRäknaren_/main.py' ]; }; then
  mkdir -p "$(dirname "$LOG")" 2>/dev/null
  echo "$(date '+%Y-%m-%d %H:%M:%S')  FAIL appmappen inte redo: $APP_DIR" >> "$LOG" 2>/dev/null
  exit 1
fi
cd '/home/user/FakturaRäknaren_' || exit 1
mkdir -p "$APP_DIR/logs"
echo "$(date '+%Y-%m-%d %H:%M:%S')  OK cwd=$APP_DIR --minimized" >> "$LOG"
exec '/usr/local/bin/python3' '/home/user/FakturaRäknaren_/main.py' --minimized
