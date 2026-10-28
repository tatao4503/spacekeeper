#!/bin/bash
# Remove cloud/Finder metadata, seal the complete app bundle, and recreate the DMG.
set -euo pipefail

DESKTOP_DIR="$(cd "$(dirname "$0")" && pwd)"
BUNDLE_DIR="$DESKTOP_DIR/src-tauri/target/release/bundle"
APP_DIR="$BUNDLE_DIR/macos"
APP_NAME="Spacekeeper.app"
APP_PATH="$APP_DIR/$APP_NAME"
DMG_DIR="$BUNDLE_DIR/dmg"
CREATE_DMG="$DMG_DIR/bundle_dmg.sh"
STAGING_DIR="$(mktemp -d /tmp/spacekeeper-release-stage.XXXXXX)"
STAGED_APP="$STAGING_DIR/$APP_NAME"
MOUNT_PATH=""

cleanup() {
  if [ -n "$MOUNT_PATH" ] && /sbin/mount | /usr/bin/grep -Fq " on $MOUNT_PATH "; then
    /usr/bin/hdiutil detach "$MOUNT_PATH" >/dev/null 2>&1 || true
  fi
  case "$STAGING_DIR" in
    /tmp/spacekeeper-release-stage.*)
      /bin/rm -rf "$STAGING_DIR"
      ;;
  esac
}
trap cleanup EXIT

test -d "$APP_PATH"
test -x "$APP_PATH/Contents/MacOS/spacekeeper-desktop"
test -x "$APP_PATH/Contents/Resources/sidecar/spacekeeper-server"
test -x "$CREATE_DMG"

VERSION="$(/usr/bin/plutil -extract CFBundleShortVersionString raw -o - "$APP_PATH/Contents/Info.plist")"
case "$(/usr/bin/uname -m)" in
  arm64) RELEASE_ARCH="aarch64" ;;
  x86_64) RELEASE_ARCH="x64" ;;
  *) echo "Unsupported macOS release architecture" >&2; exit 1 ;;
esac
DMG_PATH="$DMG_DIR/Spacekeeper_${VERSION}_${RELEASE_ARCH}.dmg"

# Desktop가 File Provider로 관리되는 환경에서도 메타데이터가 다시 붙지 않도록
# 최종 이미지는 /tmp의 동기화 비대상 복사본에서 조립한다.
/usr/bin/ditto --noextattr --noqtn "$APP_PATH" "$STAGED_APP"

for attribute in \
  'com.apple.fileprovider.fpfs#P' \
  'com.apple.fileprovider.dir#N' \
  com.apple.ResourceFork \
  com.apple.FinderInfo
do
  /usr/bin/xattr -rd "$attribute" "$STAGED_APP" 2>/dev/null || true
done

# Tauri가 전체 리소스 목록을 포함해 이미 ad-hoc 서명했다. 여기서 다시 쓰기
# 서명을 하면 File Provider가 FinderInfo를 재부착하므로, 메타데이터 제거 후
# 읽기 전용 엄격 검증만 수행한다.
/usr/bin/codesign --verify --deep --strict --verbose=2 "$STAGED_APP"

/bin/rm -f "$DMG_PATH"
"$CREATE_DMG" \
  --volname "Spacekeeper" \
  --volicon "$DMG_DIR/icon.icns" \
  --background "$DESKTOP_DIR/dmg-assets/background.tiff" \
  --filesystem APFS \
  --window-size 660 400 \
  --icon-size 128 \
  --icon "$APP_NAME" 170 190 \
  --app-drop-link 490 190 \
  --no-internet-enable \
  "$DMG_PATH" \
  "$STAGING_DIR"

/usr/bin/hdiutil verify "$DMG_PATH"

ATTACH_PLIST="$STAGING_DIR/attach.plist"
/usr/bin/hdiutil attach -nobrowse -readonly -plist "$DMG_PATH" > "$ATTACH_PLIST"
MOUNT_PATH="$(/usr/bin/plutil -convert json -o - "$ATTACH_PLIST" | python3 -c '
import json, sys
for entity in json.load(sys.stdin)["system-entities"]:
    if "mount-point" in entity:
        print(entity["mount-point"])
        break
')"
test -n "$MOUNT_PATH"
/usr/bin/codesign --verify --deep --strict --verbose=2 "$MOUNT_PATH/$APP_NAME"
/usr/bin/hdiutil detach "$MOUNT_PATH"
MOUNT_PATH=""

echo "Finalized macOS release: $DMG_PATH"
