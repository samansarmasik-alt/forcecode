#!/usr/bin/env bash
# ForgeCode — macOS / Linux launcher (POSIX)
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="$SCRIPT_DIR/forgecode.py"
if [ ! -f "$TARGET" ]; then
  echo "forgecode.py bulunamadı: $TARGET" >&2
  exit 1
fi
# Prefer python3, fallback to python
if command -v python3 >/dev/null 2>&1; then
  exec python3 "$TARGET" "$@"
elif command -v python >/dev/null 2>&1; then
  exec python "$TARGET" "$@"
else
  echo "ForgeCode için Python 3.10+ gerekiyor. https://www.python.org/downloads/" >&2
  exit 1
fi
