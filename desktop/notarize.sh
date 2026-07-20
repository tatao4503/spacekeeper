#!/bin/bash
# Sign, notarize, and staple the Spacekeeper macOS release DMG.
#
# Prerequisites:
#   - Apple Developer ID Application certificate installed in Keychain
#   - Environment variables:
#       APPLE_DEV_ID       "Developer ID Application: Your Name (TEAM_ID)"
#       APPLE_TEAM_ID      Your 10-character team ID
#       APPLE_ID           Your Apple ID email
#       APPLE_APP_PASSWORD App-specific password (generate at appleid.apple.com)
#
# Usage:
#   ./notarize.sh [path/to/Spacekeeper.dmg]
#
# If no DMG path is given, the script looks for the latest DMG in
# src-tauri/target/release/bundle/dmg/.
set -euo pipefail

DESKTOP_DIR="$(cd "$(dirname "$0")" && pwd)"
BUNDLE_DMG_DIR="$DESKTOP_DIR/src-tauri/target/release/bundle/dmg"

DMG_PATH="${1:-}"
if [ -z "$DMG_PATH" ]; then
  DMG_PATH="$(ls -t "$BUNDLE_DMG_DIR"/Spacekeeper_*.dmg 2>/dev/null | head -1)"
  if [ -z "$DMG_PATH" ]; then
    echo "Error: No DMG found. Run finalize-macos-release.sh first." >&2
    exit 1
  fi
fi

test -f "$DMG_PATH" || { echo "Error: DMG not found at $DMG_PATH" >&2; exit 1; }

# ─── Validate required environment variables ───
: "${APPLE_DEV_ID:?Set APPLE_DEV_ID to your Developer ID Application identity}"
: "${APPLE_TEAM_ID:?Set APPLE_TEAM_ID to your 10-character team ID}"
: "${APPLE_ID:?Set APPLE_ID to your Apple ID email}"
: "${APPLE_APP_PASSWORD:?Set APPLE_APP_PASSWORD to an app-specific password}"

echo "╔══════════════════════════════════════════════╗"
echo "║  Spacekeeper macOS Notarization Pipeline     ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
echo "  DMG: $DMG_PATH"
echo "  Identity: $APPLE_DEV_ID"
echo ""

# ─── Step 1: Deep code-sign the app inside the DMG ───
echo "▸ Step 1/4: Extracting app from DMG for signing..."
STAGING_DIR="$(mktemp -d /tmp/spacekeeper-notarize.XXXXXX)"
cleanup() {
  if [ -n "${MOUNT_PATH:-}" ] && /sbin/mount | /usr/bin/grep -Fq " on $MOUNT_PATH "; then
    /usr/bin/hdiutil detach "$MOUNT_PATH" >/dev/null 2>&1 || true
  fi
  /bin/rm -rf "$STAGING_DIR"
}
trap cleanup EXIT

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

APP_NAME="Spacekeeper.app"
/usr/bin/ditto --noextattr --noqtn "$MOUNT_PATH/$APP_NAME" "$STAGING_DIR/$APP_NAME"
/usr/bin/hdiutil detach "$MOUNT_PATH"
MOUNT_PATH=""

echo "▸ Step 2/4: Code-signing with Developer ID..."
/usr/bin/codesign --deep --force --options runtime \
  --sign "$APPLE_DEV_ID" \
  --timestamp \
  "$STAGING_DIR/$APP_NAME"

/usr/bin/codesign --verify --deep --strict --verbose=2 "$STAGING_DIR/$APP_NAME"
echo "  ✓ Code-signing verified"

# ─── Step 2: Recreate signed DMG ───
echo "▸ Step 3/4: Creating signed DMG..."
SIGNED_DMG="$STAGING_DIR/Spacekeeper-signed.dmg"
/usr/bin/hdiutil create \
  -volname "Spacekeeper" \
  -srcfolder "$STAGING_DIR/$APP_NAME" \
  -ov -format UDZO \
  "$SIGNED_DMG"

# ─── Step 3: Notarize ───
echo "▸ Step 4/4: Submitting for Apple notarization..."
/usr/bin/xcrun notarytool submit "$SIGNED_DMG" \
  --apple-id "$APPLE_ID" \
  --team-id "$APPLE_TEAM_ID" \
  --password "$APPLE_APP_PASSWORD" \
  --wait

# ─── Step 4: Staple ───
echo "▸ Stapling notarization ticket..."
/usr/bin/xcrun stapler staple "$SIGNED_DMG"

# ─── Replace original DMG ───
/bin/mv "$SIGNED_DMG" "$DMG_PATH"

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  ✅ Notarization complete!                   ║"
echo "║  DMG: $DMG_PATH                              ║"
echo "╚══════════════════════════════════════════════╝"
