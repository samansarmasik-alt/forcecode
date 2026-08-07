#!/usr/bin/env bash
# ForgeCode — macOS / Linux global installer
# Kurulum yeri: ~/.local/share/forgecode  ve  ~/.local/bin/force
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
SOURCE_PY="$SCRIPT_DIR/forgecode.py"
SOURCE_SH="$SCRIPT_DIR/forgecode.sh"

if [ ! -f "$SOURCE_PY" ]; then
  echo "HATA: forgecode.py bulunamadı ($SCRIPT_DIR)" >&2
  exit 1
fi

# macOS'ta XDG yoksa ev dizini kullanılır
if [ -n "${FORGECODE_HOME:-}" ]; then
  APP_HOME="$FORGECODE_HOME"
elif [ "$(uname -s)" = "Darwin" ]; then
  # macOS'ta tercih: ~/.forgecode (mevcut) ve Application Support alternatifi
  APP_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/forgecode"
  # aynı zamanda ~/.forgecode sembolik uyumluluğu korunur (forgecode.py app_home zaten destekliyor)
else
  APP_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/forgecode"
fi

APP_DIR="$APP_HOME/app"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"

mkdir -p "$APP_DIR" "$BIN_DIR"

cp -f "$SOURCE_PY" "$APP_DIR/forgecode.py"
if [ -f "$SOURCE_SH" ]; then
  cp -f "$SOURCE_SH" "$APP_DIR/forgecode.sh"
  chmod +x "$APP_DIR/forgecode.sh"
fi
chmod +x "$APP_DIR/forgecode.py" 2>/dev/null || true

# Global launcher: ~/.local/bin/force
LAUNCHER="$BIN_DIR/force"
cat > "$LAUNCHER" <<'LAUNCHER_EOF'
#!/usr/bin/env bash
set -e
# FORGECODE_HOME override respected
if [ -n "${FORGECODE_HOME:-}" ]; then
  APP_HOME="$FORGECODE_HOME"
else
  APP_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/forgecode"
  # Legacy fallback: if new location empty but ~/.forgecode exists, use it
  if [ ! -d "$APP_HOME/app" ] && [ -d "$HOME/.forgecode" ]; then
    # forgecode.py handles both; launcher prefers new location
    true
  fi
fi
APP_PY="$APP_HOME/app/forgecode.py"
# Fallback to legacy ~/.forgecode location if needed
if [ ! -f "$APP_PY" ] && [ -f "$HOME/.forgecode/forgecode.py" ]; then
  APP_PY="$HOME/.forgecode/forgecode.py"
fi
# Development fallback: script dir relative (when running from repo)
if [ ! -f "$APP_PY" ]; then
  SCRIPT_FALLBACK="$(cd "$(dirname "$0")" && pwd)/forgecode.py"
  if [ -f "$SCRIPT_FALLBACK" ]; then APP_PY="$SCRIPT_FALLBACK"; fi
fi
if [ ! -f "$APP_PY" ]; then
  echo "ForgeCode bulunamadı: $APP_PY" >&2
  exit 1
fi
if command -v python3 >/dev/null 2>&1; then exec python3 "$APP_PY" "$@"
elif command -v python >/dev/null 2>&1; then exec python "$APP_PY" "$@"
else echo "Python 3.10+ gerekiyor." >&2; exit 1; fi
LAUNCHER_EOF
chmod +x "$LAUNCHER"

# PATH uyarısı (macOS zsh/bash)
if ! echo ":$PATH:" | grep -q ":$BIN_DIR:"; then
  SHELL_RC=""
  if [ -n "${ZSH_VERSION:-}" ] || [ "$SHELL" = "/bin/zsh" ] || [ -f "$HOME/.zshrc" ]; then
    SHELL_RC="$HOME/.zshrc"
  elif [ -f "$HOME/.bashrc" ]; then
    SHELL_RC="$HOME/.bashrc"
  elif [ -f "$HOME/.bash_profile" ]; then
    SHELL_RC="$HOME/.bash_profile"
  fi
  echo ""
  echo "ForgeCode kuruldu."
  echo "  Uygulama : $APP_DIR"
  echo "  Komut    : $LAUNCHER"
  echo "  Ayarlar  : ${FORGECODE_HOME:-$HOME/.forgecode} (veya \$FORGECODE_HOME)"
  if [ -n "$SHELL_RC" ]; then
    if ! grep -q "$BIN_DIR" "$SHELL_RC" 2>/dev/null; then
      echo ""
      read -r -p "$BIN_DIR PATH'e eklensin mi? ($SHELL_RC) [Y/n]: " ans
      ans=${ans:-Y}
      if [[ "$ans" =~ ^[YyEe] ]]; then
        echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> "$SHELL_RC"
        echo "Eklendi: $SHELL_RC — yeni terminalde 'force' kullanılabilir."
      else
        echo "Atlandı. Manuel ekleyin: export PATH=\"\$HOME/.local/bin:\$PATH\""
      fi
    fi
  else
    echo "PATH'e ekleyin: export PATH=\"\$HOME/.local/bin:\$PATH\""
  fi
else
  echo "ForgeCode global komutu kuruldu: $LAUNCHER"
fi

echo ""
echo "Yeni terminalde herhangi bir klasörde:"
echo "  force"
echo "veya repo içinden:"
echo "  ./forgecode.sh ."
