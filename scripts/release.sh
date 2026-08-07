#!/usr/bin/env bash
# ForgeCode — macOS / Linux release script (POSIX)
# Windows'taki scripts/release.ps1 ile aynı işi yapar.
set -e
set -o pipefail

VERSION=""
TOKEN=""
REMOTE_URL="https://github.com/samansarmasik-alt/forcecode.git"
BRANCH=""
SKIP_TESTS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version|-v) VERSION="$2"; shift 2;;
    --token) TOKEN="$2"; shift 2;;
    --remote-url) REMOTE_URL="$2"; shift 2;;
    --branch) BRANCH="$2"; shift 2;;
    --skip-tests) SKIP_TESTS=1; shift;;
    *) echo "Bilinmeyen arg: $1" >&2; echo "Kullanim: $0 [--version 7.12.10] [--token ghp_xxx] [--branch main] [--skip-tests]" >&2; exit 1;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"
echo "Proje kok: $ROOT"

# 1) Versiyon
if [[ -z "$VERSION" ]]; then
  VERSION="$(grep -E '^VERSION = ' forgecode.py | sed -E 's/.*"([^"]+)".*/\1/')"
  if [[ -z "$VERSION" ]]; then echo "HATA: forgecode.py icinde VERSION bulunamadi" >&2; exit 1; fi
  echo "Versiyon forgecode.py'den alindi: $VERSION"
fi
TAG="v$VERSION"
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)"
if [[ -z "$BRANCH" ]]; then
  if [[ "$CURRENT_BRANCH" != "HEAD" && -n "$CURRENT_BRANCH" ]]; then BRANCH="$CURRENT_BRANCH"; else BRANCH="main"; fi
fi
echo "Tag: $TAG  Branch: $BRANCH (mevcut: $CURRENT_BRANCH)"

# 2) forgecode.py <-> pyproject.toml eşitle
TOML_VER="$(grep -E '^version = ' pyproject.toml | sed -E 's/.*"([^"]+)".*/\1/')"
PY_VER="$(grep -E '^VERSION = ' forgecode.py | sed -E 's/.*"([^"]+)".*/\1/')"
if [[ "$PY_VER" != "$TOML_VER" ]]; then
  echo "Versiyon uyusmazligi: forgecode.py=$PY_VER pyproject.toml=$TOML_VER -> pyproject.toml guncelleniyor..."
  # macOS sed farki için
  if sed --version >/dev/null 2>&1; then
    sed -i "s/version = \"[^\"]*\"/version = \"$VERSION\"/" pyproject.toml
  else
    sed -i '' "s/version = \"[^\"]*\"/version = \"$VERSION\"/" pyproject.toml
  fi
  echo "pyproject.toml $VERSION olarak guncellendi"
fi
if [[ "$PY_VER" != "$VERSION" ]]; then
  echo "forgecode.py VERSION $PY_VER -> $VERSION olarak guncelleniyor..."
  if sed --version >/dev/null 2>&1; then
    sed -i "s/VERSION = \"[^\"]*\"/VERSION = \"$VERSION\"/" forgecode.py
  else
    sed -i '' "s/VERSION = \"[^\"]*\"/VERSION = \"$VERSION\"/" forgecode.py
  fi
  echo "forgecode.py $VERSION olarak guncellendi"
fi

# 3) Gizli anahtar taraması
echo "Gizli anahtar taramasi..."
if grep -R --include="*.py" --include="*.toml" -E "(sk-ant-|sk-proj-|ghp_|github_pat_|AKIA)" forgecode.py pyproject.toml 2>/dev/null | grep -v "test_forgecode" ; then
  echo "HATA: Olasi gizli anahtar bulundu" >&2; exit 1
fi
echo "Temiz."

# 4) Syntax + test
echo "Syntax kontrol..."
PY=""
for c in python3 python "py -3"; do
  if $c -m py_compile forgecode.py 2>/dev/null; then PY="$c"; break; fi
done
if [[ -z "$PY" ]]; then echo "HATA: Python bulunamadi" >&2; exit 1; fi
echo "py_compile OK ($PY)"

if [[ "$SKIP_TESTS" -eq 0 ]]; then
  echo "Testler calistiriliyor..."
  $PY -m unittest discover -s tests -v
  echo "Testler OK"
else
  echo "Testler atlandi (--skip-tests)"
fi

# 5) Git hazırla
if ! command -v git >/dev/null 2>&1; then echo "HATA: git bulunamadi" >&2; exit 1; fi
if [[ ! -d .git ]]; then
  echo "Git repo yok -> git init"
  git init
  git branch -M "$BRANCH"
fi
if [[ "$CURRENT_BRANCH" == "master" && "$BRANCH" == "main" ]]; then
  echo "Yerel branch master -> main'e geciliyor"
  git branch -M main
  BRANCH="main"
fi
if ! git remote | grep -qx "origin"; then
  echo "Remote ekleniyor: origin -> $REMOTE_URL"
  git remote add origin "$REMOTE_URL"
else
  CUR="$(git remote get-url origin 2>/dev/null || true)"
  echo "Mevcut remote origin: $CUR"
  if [[ "$CUR" != "$REMOTE_URL" ]]; then
    echo "Remote guncelleniyor -> $REMOTE_URL"
    git remote set-url origin "$REMOTE_URL"
  fi
fi

# Token env fallback
if [[ -z "$TOKEN" ]]; then
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then TOKEN="$GITHUB_TOKEN"; echo "Token GITHUB_TOKEN env'den alindi"; 
  elif [[ -n "${GH_TOKEN:-}" ]]; then TOKEN="$GH_TOKEN"; echo "Token GH_TOKEN env'den alindi"; fi
fi

# 6) Commit
git add .
if ! git diff --cached --quiet; then
  MSG="chore: release $TAG"
  echo "Commit: $MSG"
  git commit -m "$MSG"
  echo "Commit OK"
else
  echo "Commit edilecek degisiklik yok — var olan commit kullanilacak"
fi

# 7) Tag
if git tag --list "$TAG" | grep -qx "$TAG"; then
  echo "Tag $TAG zaten var — yeniden olusturuluyor"
  git tag -d "$TAG" || true
fi
git tag "$TAG"
echo "Tag olusturuldu: $TAG"

# 8) Push
echo "Push ediliyor: $BRANCH + $TAG -> $REMOTE_URL"
export GIT_TERMINAL_PROMPT=0
if [[ -n "$TOKEN" ]]; then
  B64="$(printf 'x-access-token:%s' "$TOKEN" | base64 | tr -d '\n')"
  git -c http.extraHeader="Authorization: Basic $B64" push -u origin "$BRANCH"
  git -c http.extraHeader="Authorization: Basic $B64" push origin "$TAG"
else
  if ! git push -u origin "$BRANCH"; then
    echo "" >&2
    echo "git push basarisiz — kimlik dogrulanamadi." >&2
    echo "Cozumlerden birini yap:" >&2
    echo "  1) ./scripts/release.sh --token ghp_xxx" >&2
    echo "  2) GITHUB_TOKEN=ghp_xxx ./scripts/release.sh" >&2
    echo "  3) gh auth login  (tarayici ile giris) sonra tekrar dene" >&2
    exit 1
  fi
  git push origin "$TAG"
fi
echo "Push OK"

# 9) Doğrulama
echo "Dogrulama: git ls-remote --tags origin"
git ls-remote --tags origin | grep -F "$TAG" || true
git ls-remote --heads origin | grep -F "$BRANCH" || true

RELEASE_URL="https://github.com/samansarmasik-alt/forcecode/releases/tag/$TAG"
REPO_URL="https://github.com/samansarmasik-alt/forcecode/tree/$BRANCH"
echo ""
echo "Tamamlandi!"
echo "  Repo   : $REPO_URL"
echo "  Release: $RELEASE_URL"
echo "  Actions: https://github.com/samansarmasik-alt/forcecode/actions"
echo ""
echo "GitHub Actions 'Release' workflow tag'i gorunce otomatik calisir ve dist/*.whl + ForgeCode-v*.zip'i Releases'e ekler."
echo "Bitti demeden once Actions'in yesil oldugunu kontrol et."
