#!/usr/bin/env bash
# ForceCode — macOS / Linux global installer
# Kurulum yeri: ~/.local/share/forcecode  ve  ~/.local/bin/force
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
SOURCE_PY="$SCRIPT_DIR/forcecode.py"
SOURCE_MISSION="$SCRIPT_DIR/_forcecode_mission.py"
SOURCE_SH="$SCRIPT_DIR/forcecode.sh"
SOURCE_MODULES=(
  forcecode_base.py
  forcecode_config.py
  forcecode_stores.py
  forcecode_providers.py
  forcecode_queues.py
  forcecode_workspace.py
  forcecode_sandbox.py
  forcecode_skills.py
  forcecode_mcp.py
  forcecode_context.py
)

if [ ! -f "$SOURCE_PY" ] || [ ! -f "$SOURCE_MISSION" ]; then
  echo "HATA: ForceCode çalışma dosyaları bulunamadı ($SCRIPT_DIR)" >&2
  exit 1
fi
for module in "${SOURCE_MODULES[@]}"; do
  if [ ! -f "$SCRIPT_DIR/$module" ]; then
    echo "HATA: ForceCode modülü bulunamadı: $module" >&2
    exit 1
  fi
done

# macOS'ta XDG yoksa ev dizini kullanılır
if [ -n "${FORCECODE_HOME:-}" ]; then
  APP_HOME="$FORCECODE_HOME"
elif [ "$(uname -s)" = "Darwin" ]; then
  # macOS'ta tercih: ~/.forcecode (mevcut) ve Application Support alternatifi
  APP_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/forcecode"
  # aynı zamanda ~/.forcecode sembolik uyumluluğu korunur (forcecode.py app_home zaten destekliyor)
else
  APP_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/forcecode"
fi

APP_DIR="$APP_HOME/app"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"

mkdir -p "$APP_DIR" "$BIN_DIR"

cp -f "$SOURCE_PY" "$APP_DIR/forcecode.py"
cp -f "$SOURCE_MISSION" "$APP_DIR/_forcecode_mission.py"
for module in "${SOURCE_MODULES[@]}"; do
  cp -f "$SCRIPT_DIR/$module" "$APP_DIR/$module"
done
if [ -f "$SOURCE_SH" ]; then
  cp -f "$SOURCE_SH" "$APP_DIR/forcecode.sh"
  chmod +x "$APP_DIR/forcecode.sh"
fi
chmod +x "$APP_DIR/forcecode.py" 2>/dev/null || true

# Global launcher: ~/.local/bin/force
LAUNCHER="$BIN_DIR/force"
cat > "$LAUNCHER" <<'LAUNCHER_EOF'
#!/usr/bin/env bash
set -e
# FORCECODE_HOME override respected
if [ -n "${FORCECODE_HOME:-}" ]; then
  APP_HOME="$FORCECODE_HOME"
else
  APP_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/forcecode"
  # Legacy fallback: if new location empty but ~/.forcecode exists, use it
  if [ ! -d "$APP_HOME/app" ] && [ -d "$HOME/.forcecode" ]; then
    # forcecode.py handles both; launcher prefers new location
    true
  fi
fi
APP_PY="$APP_HOME/app/forcecode.py"
# Fallback to legacy ~/.forcecode location if needed
if [ ! -f "$APP_PY" ] && [ -f "$HOME/.forcecode/forcecode.py" ]; then
  APP_PY="$HOME/.forcecode/forcecode.py"
fi
# Development fallback: script dir relative (when running from repo)
if [ ! -f "$APP_PY" ]; then
  SCRIPT_FALLBACK="$(cd "$(dirname "$0")" && pwd)/forcecode.py"
  if [ -f "$SCRIPT_FALLBACK" ]; then APP_PY="$SCRIPT_FALLBACK"; fi
fi
if [ ! -f "$APP_PY" ]; then
  echo "ForceCode bulunamadı: $APP_PY" >&2
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
  echo "ForceCode kuruldu."
  echo "  Uygulama : $APP_DIR"
  echo "  Komut    : $LAUNCHER"
  echo "  Ayarlar  : ${FORCECODE_HOME:-$HOME/.forcecode} (veya \$FORCECODE_HOME)"
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
  echo "ForceCode global komutu kuruldu: $LAUNCHER"
fi

echo ""
echo "Yeni terminalde herhangi bir klasörde:"
echo "  force"
echo "veya repo içinden:"
echo "  ./forcecode.sh ."
