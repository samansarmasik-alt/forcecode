#!/usr/bin/env bash
# ForceCode — macOS / Linux launcher (POSIX)
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="$SCRIPT_DIR/forcecode.py"
if [ ! -f "$TARGET" ]; then
  echo "forcecode.py bulunamadı: $TARGET" >&2
  exit 1
fi
# Prefer python3, fallback to python
if command -v python3 >/dev/null 2>&1; then
  exec python3 "$TARGET" "$@"
elif command -v python >/dev/null 2>&1; then
  exec python "$TARGET" "$@"
else
  echo "ForceCode için Python 3.10+ gerekiyor. https://www.python.org/downloads/" >&2
  exit 1
fi
