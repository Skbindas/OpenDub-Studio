#!/usr/bin/env sh
# Run in the foreground so the local studio logs remain visible.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ -x .venv/bin/python ]; then
  task_python=.venv/bin/python
elif [ -f .venv/Scripts/python.exe ]; then
  task_python=.venv/Scripts/python.exe
else
  printf '%s\n' 'OpenDub environment missing. Run the installer first.'
  exit 1
fi
exec "$task_python" -u scripts/launch.py
