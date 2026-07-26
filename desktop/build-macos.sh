#!/bin/bash
# Resilient macOS build.
#
# 이 저장소는 File Provider(iCloud Desktop 등)로 동기화되는 위치에 있을 수
# 있다. 그런 환경에서는 Tauri가 사이드카의 Python.framework를 번들로 복사하는
# 순간 시스템이 com.apple.FinderInfo를 다시 붙여, Tauri 내부 ad-hoc 서명이
# "resource fork, Finder information, or similar detritus not allowed"로 실패한다.
# 번들 자체는 이미 완성된 뒤이므로, 메타데이터를 제거하고 다시 ad-hoc 서명하면
# 정상적인 앱이 된다. 이 래퍼는 그 자가 치유 단계를 빌드에 포함시킨다.
set -uo pipefail

DESKTOP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DESKTOP_DIR"
APP="src-tauri/target/release/bundle/macos/Spacekeeper.app"

# 1) Tauri 빌드. 내부 codesign이 위 사유로 실패해도 번들은 만들어지므로
#    실패를 곧바로 치명적으로 보지 않는다 (아래에서 산출물을 검증한다).
npx tauri build || echo "▶ tauri build가 0이 아닌 코드로 끝났습니다 — 산출물을 검증한 뒤 봉인합니다."

# 2) 실제 컴파일 실패(번들 없음)는 여기서 걸러낸다.
if [ ! -d "$APP" ]; then
  echo "✗ 앱 번들이 생성되지 않았습니다. 컴파일 단계 오류입니다." >&2
  exit 1
fi
if [ ! -x "$APP/Contents/MacOS/spacekeeper-desktop" ] \
   || [ ! -x "$APP/Contents/Resources/sidecar/spacekeeper-server" ]; then
  echo "✗ 번들에 필수 실행 파일이 없습니다. 불완전한 빌드입니다." >&2
  exit 1
fi

# 3) 메타데이터 제거 + ad-hoc 재서명 → 검증.
/usr/bin/xattr -cr "$APP"
/usr/bin/codesign --force --deep --sign - "$APP"
/usr/bin/codesign --verify --deep --strict "$APP"
echo "✓ 앱 번들 서명 완료: $APP"

# 4) DMG 패키징(선택). AppleScript/Finder에 의존해 이 환경에서 종종 실패하지만,
#    앱 번들은 이미 봉인되어 설치·실행에 문제가 없으므로 실패해도 빌드를 막지 않는다.
if ./finalize-macos-release.sh; then
  echo "✓ DMG 패키징 완료"
else
  echo "▶ DMG 패키징을 건너뜁니다(앱 번들은 정상). 로컬 설치에는 영향 없음."
fi

echo "APP READY: $DESKTOP_DIR/$APP"
