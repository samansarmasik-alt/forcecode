#!/usr/bin/env bash
# ForceCode — macOS / Linux uninstaller
set -euo pipefail
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
APP_HOME="${FORCECODE_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/forcecode}"
LAUNCHER="$BIN_DIR/force"

if [ -f "$LAUNCHER" ]; then rm -f "$LAUNCHER"; echo "Kaldırıldı: $LAUNCHER"; fi
if [ -d "$APP_HOME/app" ]; then rm -rf "$APP_HOME/app"; echo "Kaldırıldı: $APP_HOME/app"; fi
# Ayarları koru — sadece sor
if [ -d "$APP_HOME" ]; then
  echo "Ayarlar korundu: $APP_HOME (silmek için: rm -rf \"$APP_HOME\")"
fi
if [ -d "$HOME/.forcecode" ]; then
  echo "Eski ayarlar: $HOME/.forcecode korundu."
fi
echo "Force komutu kaldırıldı."
