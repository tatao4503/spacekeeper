#!/bin/bash
# 파이썬 런타임을 보호되지 않는 위치(~/.spacekeeper/runtime)로 복사한다.
# 데스크탑/문서 등 TCC 보호 폴더에 저장소가 있을 때, 서명 없는 데스크탑 앱이
# 스폰한 파이썬이 시작 시 권한 프롬프트에 막히는 것을 피하기 위함.
# 파이썬 소스를 바꾼 뒤에는 이 스크립트를 다시 실행하세요.
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"   # spacekeeper 저장소 루트
DEST="$HOME/.spacekeeper/runtime"
mkdir -p "$DEST"
rm -rf "$DEST/spacekeeper"
cp -R "$HERE/spacekeeper" "$DEST/spacekeeper"
find "$DEST" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
echo "런타임을 $DEST/spacekeeper 로 스테이징했습니다."
