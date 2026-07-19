#!/bin/bash
# Build the local Python dashboard as a self-contained Tauri sidecar.
set -euo pipefail

DESKTOP_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$DESKTOP_DIR/.." && pwd)"
VENV_DIR="$DESKTOP_DIR/.venv-sidecar"
BUILD_DIR="$DESKTOP_DIR/.sidecar-build"
DIST_DIR="$DESKTOP_DIR/.sidecar-dist"
SIDECAR_NAME="spacekeeper-server"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  python3 -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install \
  --disable-pip-version-check \
  --quiet \
  --requirement "$DESKTOP_DIR/sidecar-requirements.txt"

mkdir -p "$DIST_DIR" "$BUILD_DIR/spec" "$BUILD_DIR/work"

"$VENV_DIR/bin/python" -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --noupx \
  --name "$SIDECAR_NAME" \
  --paths "$REPO_ROOT" \
  --add-data "$REPO_ROOT/spacekeeper/web:spacekeeper/web" \
  --specpath "$BUILD_DIR/spec" \
  --workpath "$BUILD_DIR/work" \
  --distpath "$DIST_DIR" \
  "$DESKTOP_DIR/sidecar_main.py"

# Python.framework 원본에 붙어 있던 Finder/File Provider 메타데이터는 macOS
# 번들 서명을 무효화할 수 있으므로, 생성된 복사본에서만 제거한다.
for attribute in \
  'com.apple.fileprovider.fpfs#P' \
  'com.apple.fileprovider.dir#N' \
  com.apple.ResourceFork \
  com.apple.FinderInfo
do
  /usr/bin/xattr -rd "$attribute" "$DIST_DIR/$SIDECAR_NAME" 2>/dev/null || true
done

echo "Built self-contained sidecar: $DIST_DIR/$SIDECAR_NAME"
