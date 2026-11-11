"""macOS '시스템 데이터' 해부.

저장공간 설정이 하나의 불투명한 덩어리로 뭉뚱그리는 '시스템 데이터'가 실제로
어떤 폴더들인지 분해한다. 이 앱의 다른 화면은 홈 폴더 안만 다루지만, 그 덩어리의
상당 부분은 홈 밖(``/Library``, ``/private/var``)에 있어 여기서만 보인다.

원칙:

* **읽기 전용.** 이 모듈은 아무것도 옮기거나 지우지 않는다. 크기를 재고 설명할 뿐이다.
* **홈 밖은 앱이 정리하지 않는다.** 되돌릴 수 없고 시스템을 깨뜨릴 수 있다. 대신
  무엇인지 설명하고, 사용자가 직접 실행할 수 있는 공식 명령을 안내한다.
* **정직한 숫자.** 크기는 실제 할당 블록(``st_blocks``) 기준이며, macOS 저장공간
  UI의 '시스템 데이터' 숫자와 정확히 일치하지 않을 수 있다. 분류 기준이 다르고
  APFS 공유 블록이 있기 때문이다. 화면에서 이 점을 그대로 밝힌다.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

_MEASURE_TIMEOUT_SECONDS = 5

# action:
#   "quarantine" — 홈 안이고 다시 만들 수 있어, 앱의 격리 흐름으로 처리 가능
#   "command"    — 전용 도구로만 안전하게 정리된다. 명령을 안내만 하고 실행하지 않는다
#   "system"     — macOS가 알아서 관리한다. 손대면 안 된다
@dataclass(frozen=True)
class SystemArea:
    key: str
    name: str
    path: str
    what: str
    why: str
    action: str
    risk: str
    command: str = ""
    hint: str = ""


AREAS: tuple[SystemArea, ...] = (
    SystemArea(
        key="simulator_runtimes",
        name="iOS 시뮬레이터 런타임",
        path="/Library/Developer/CoreSimulator/Volumes",
        what="Xcode 시뮬레이터가 쓰는 iOS·watchOS 런타임 디스크 이미지입니다.",
        why="Xcode를 설치하거나 새 iOS 버전으로 시뮬레이터를 돌릴 때마다 런타임이 하나씩 쌓입니다. 옛 버전도 지우기 전까지 그대로 남습니다.",
        action="command",
        risk="medium",
        command="xcrun simctl runtime list",
        hint="위 명령으로 설치된 런타임을 확인한 뒤, 더 안 쓰는 것만 `xcrun simctl runtime delete <식별자>`로 지웁니다. Xcode → Settings → Platforms에서 눌러서 지워도 됩니다.",
    ),
    SystemArea(
        key="simulator_caches",
        name="시뮬레이터 캐시",
        path="/Library/Developer/CoreSimulator/Caches",
        what="시뮬레이터가 런타임을 풀어놓고 쓰는 캐시입니다.",
        why="런타임을 받거나 시뮬레이터를 실행할 때 만들어지고, 오래된 것이 남아 있곤 합니다.",
        action="command",
        risk="low",
        command="xcrun simctl delete unavailable",
        hint="더 이상 쓸 수 없는 시뮬레이터 기기와 그 데이터를 정리합니다. 필요하면 다시 만들어집니다.",
    ),
    SystemArea(
        key="simulator_devices",
        name="시뮬레이터 기기 데이터",
        path="~/Library/Developer/CoreSimulator/Devices",
        what="시뮬레이터 기기별로 설치된 앱과 그 안의 데이터입니다.",
        why="시뮬레이터에서 앱을 돌릴 때마다 기기 폴더가 생기고, 만든 기기를 지우기 전까지 남습니다.",
        action="command",
        risk="medium",
        command="xcrun simctl delete unavailable",
        hint="지금 쓰는 기기는 두고 못 쓰는 것만 지웁니다. 특정 기기를 비우려면 `xcrun simctl erase <기기ID>`.",
    ),
    SystemArea(
        key="xcode_derived",
        name="Xcode 빌드 산출물 (DerivedData)",
        path="~/Library/Developer/Xcode/DerivedData",
        what="Xcode가 빌드하면서 만든 중간 산출물과 인덱스입니다.",
        why="프로젝트를 빌드할 때마다 쌓이고, Xcode가 스스로 지우지 않습니다.",
        action="quarantine",
        risk="low",
        hint="다시 빌드하면 그대로 만들어집니다. 정리 후 첫 빌드만 오래 걸립니다.",
    ),
    SystemArea(
        key="xcode_device_support",
        name="iOS 기기 디버깅 심볼",
        path="~/Library/Developer/Xcode/iOS DeviceSupport",
        what="연결했던 iPhone·iPad의 디버깅 심볼 파일입니다.",
        why="새 iOS 버전 기기를 연결할 때마다 그 버전의 심볼을 통째로 받아 둡니다.",
        action="command",
        risk="medium",
        command="open ~/Library/Developer/Xcode/iOS\\ DeviceSupport",
        hint="지금 개발 중인 기기의 iOS 버전 폴더는 남기고, 옛 버전만 골라 지우세요. 지워도 그 기기를 다시 연결하면 재생성되지만 시간이 걸립니다.",
    ),
    SystemArea(
        key="xcode_archives",
        name="Xcode 아카이브",
        path="~/Library/Developer/Xcode/Archives",
        what="앱을 배포용으로 빌드할 때 남은 .xcarchive 파일입니다.",
        why="Archive 빌드를 할 때마다 하나씩 쌓입니다.",
        action="command",
        risk="high",
        command="open ~/Library/Developer/Xcode/Archives",
        hint="이미 출시한 버전의 아카이브에는 크래시 로그를 해석할 심볼이 들어 있습니다. 앱을 배포한 적이 있다면 지우기 전에 꼭 확인하세요.",
    ),
    SystemArea(
        key="user_app_support",
        name="앱이 저장한 사용자 데이터",
        path="~/Library/Application Support",
        what="앱들이 각자 저장한 데이터입니다. 설정만 있는 앱도 있고, 대화 기록·모델·캐시를 통째로 넣어 두는 앱도 있습니다.",
        why="앱을 쓸수록 커집니다. 앱을 지워도 이 폴더는 남는 경우가 많습니다.",
        action="command",
        risk="high",
        command="du -sh ~/Library/Application\\ Support/* | sort -rh | head -15",
        hint="위 명령으로 어느 앱이 큰지 확인하세요. 실행 중인 앱의 데이터를 지우면 그 앱의 기록이 사라질 수 있습니다. '앱과 관련 파일' 화면에서 앱별로 안전하게 볼 수 있습니다.",
    ),
    SystemArea(
        key="containers",
        name="앱 샌드박스 컨테이너",
        path="~/Library/Containers",
        what="샌드박스로 격리된 앱들이 자기 데이터를 넣어 두는 곳입니다.",
        why="App Store 앱과 샌드박스 앱이 쓸수록 커집니다. 앱을 지워도 남기도 합니다.",
        action="command",
        risk="high",
        command="du -sh ~/Library/Containers/* | sort -rh | head -15",
        hint="앱의 실제 사용자 데이터가 들어 있습니다. 폴더 이름이 앱 번들 ID라 무엇인지 확인한 뒤에만 손대세요.",
    ),
    SystemArea(
        key="group_containers",
        name="앱 그룹 데이터",
        path="~/Library/Group Containers",
        what="여러 앱이 함께 쓰는 데이터(확장 프로그램, 위젯 등)입니다.",
        why="앱과 그 확장이 데이터를 주고받으며 쌓입니다.",
        action="command",
        risk="high",
        command="du -sh ~/Library/Group\\ Containers/* | sort -rh | head -15",
        hint="컨테이너와 마찬가지로 실제 데이터입니다. 확인 없이 지우지 마세요.",
    ),
    SystemArea(
        key="user_caches",
        name="사용자 캐시",
        path="~/Library/Caches",
        what="앱들이 다시 만들 수 있는 데이터를 담아 두는 캐시입니다.",
        why="앱을 쓰는 동안 계속 쌓이고, 앱이 스스로 비우지 않는 경우가 많습니다.",
        action="quarantine",
        risk="low",
        hint="'공간 요약'에서 분석하면 이 안의 캐시가 항목별로 잡힙니다.",
    ),
    SystemArea(
        key="system_app_support",
        name="시스템 전역 앱 지원 파일",
        path="/Library/Application Support",
        what="모든 사용자용으로 설치된 앱의 지원 파일입니다.",
        why="앱이나 드라이버를 설치할 때 여기에 들어가고, 앱을 지워도 남는 경우가 있습니다.",
        action="command",
        risk="high",
        command="sudo du -sh /Library/Application\\ Support/* | sort -rh | head -15",
        hint="시스템 전역이라 관리자 권한이 필요합니다. 어떤 앱 것인지 확인되지 않으면 두세요. 앱을 제거할 땐 그 앱의 공식 제거 프로그램을 쓰는 게 안전합니다.",
    ),
    SystemArea(
        key="command_line_tools",
        name="Command Line Tools",
        path="/Library/Developer/CommandLineTools",
        what="git·clang 같은 개발자 명령줄 도구 모음입니다.",
        why="Xcode나 `xcode-select --install`로 설치됩니다.",
        action="system",
        risk="high",
        hint="개발에 계속 쓰이는 도구입니다. 지우면 git 같은 명령이 동작하지 않습니다. 그대로 두세요.",
    ),
    SystemArea(
        key="var_folders",
        name="시스템 임시 파일",
        path="/private/var/folders",
        what="앱과 시스템이 쓰는 임시 파일·캐시 영역입니다.",
        why="실행 중인 앱들이 계속 만들고, macOS가 시점을 봐서 정리합니다.",
        action="system",
        risk="high",
        hint="macOS가 관리합니다. 직접 지우면 실행 중인 앱이 오작동할 수 있습니다. 재시동하면 상당 부분 정리됩니다.",
    ),
    SystemArea(
        key="swap",
        name="가상 메모리 (스왑)",
        path="/private/var/vm",
        what="메모리가 부족할 때 디스크로 밀어내는 스왑 파일입니다.",
        why="열어 둔 앱이 많고 메모리가 모자랄수록 커집니다.",
        action="system",
        risk="high",
        hint="macOS가 필요에 따라 자동으로 늘리고 줄입니다. 지우면 안 됩니다. 줄이고 싶으면 앱을 닫고 재시동하세요.",
    ),
    SystemArea(
        key="system_logs",
        name="시스템 로그",
        path="/private/var/log",
        what="macOS와 앱들이 남긴 진단 로그입니다.",
        why="문제를 추적할 수 있게 계속 기록되고, 오래된 것은 자동으로 회전됩니다.",
        action="system",
        risk="medium",
        hint="macOS가 알아서 오래된 로그를 지웁니다. 그대로 두어도 무한정 커지지 않습니다.",
    ),
    SystemArea(
        key="ios_backups",
        name="iPhone·iPad 백업",
        path="~/Library/Application Support/MobileSync/Backup",
        what="Finder로 받은 iOS 기기 백업입니다.",
        why="기기를 연결해 백업할 때마다 통째로 저장되고, 옛 백업도 지우기 전까지 남습니다.",
        action="command",
        risk="high",
        command="open ~/Library/Application\\ Support/MobileSync/Backup",
        hint="기기를 복구할 때 필요한 실제 백업입니다. 지우기 전에 다른 백업(iCloud 등)이 있는지 꼭 확인하세요. Finder → 기기 → 백업 관리에서 지우는 게 안전합니다.",
    ),
    # ── 홈의 숨김 개발 폴더 ─────────────────────────────────────────────
    # macOS는 이런 폴더를 '시스템 데이터'로 세는 경우가 많다. 실제로 꽉 찬 맥에서
    # 이 폴더들만 20GB였는데, 예전 목록에는 하나도 없었다.
    SystemArea(
        key="dot_local",
        name="개발 도구 데이터 (.local)",
        path="~/.local",
        what="여러 개발 도구가 설치본·데이터(share)와 실행 상태(state)를 두는 곳입니다. Claude Code 설치본이나 VM 샌드박스 이미지가 여기 쌓이기도 합니다.",
        why="도구를 업데이트하면 옛 설치본이, 가상머신을 쓰면 디스크 이미지와 상태가 남습니다.",
        action="command",
        risk="medium",
        command="du -sh ~/.local/share/* ~/.local/state/* 2>/dev/null | sort -rh | head -15",
        hint="어느 도구가 큰지 확인한 뒤 그 도구의 정리 기능을 쓰세요. 폴더째 지우면 도구가 설치본과 설정을 잃습니다.",
    ),
    SystemArea(
        key="codex_home",
        name="Codex 대화 기록·플러그인 (.codex)",
        path="~/.codex",
        what="Codex CLI·앱이 저장한 대화 기록(sessions, archived_sessions)과 플러그인입니다.",
        why="대화할 때마다 기록이 쌓이고, 보관한 대화도 지우기 전까지 남습니다.",
        action="command",
        risk="high",
        command="du -sh ~/.codex/* | sort -rh",
        hint="archived_sessions는 보관해 둔 지난 대화입니다. 지우면 그 대화를 다시 열 수 없습니다. 설정 파일(config.toml 등)은 남겨 두세요.",
    ),
    SystemArea(
        key="claude_home",
        name="Claude Code 기록 (.claude)",
        path="~/.claude",
        what="Claude Code의 프로젝트별 대화 기록과 기억(memory), 설정입니다.",
        why="대화할 때마다 기록이 쌓입니다.",
        action="command",
        risk="high",
        command="du -sh ~/.claude/projects/* | sort -rh | head",
        hint="기억과 설정이 같은 폴더에 들어 있어서, 통째로 지우면 Claude Code가 지금까지 기억한 것을 잃습니다. 줄이려면 projects 안의 오래된 대화 기록(.jsonl)만 고르세요.",
    ),
    SystemArea(
        key="android_avd",
        name="안드로이드 에뮬레이터 기기 (AVD)",
        path="~/.android/avd",
        what="안드로이드 에뮬레이터로 만든 가상 기기와 그 안의 데이터입니다.",
        why="가상 기기를 만들 때마다 디스크 이미지가 생기고, 지우기 전까지 남습니다.",
        action="command",
        risk="medium",
        command="ls ~/.android/avd",
        hint="Android Studio의 Device Manager에서 안 쓰는 기기를 지우거나 `avdmanager delete avd -n <이름>`으로 지웁니다. 기기 안에 설치한 앱과 데이터도 함께 사라집니다.",
    ),
    SystemArea(
        key="dev_cache",
        name="개발 도구 캐시 (.cache)",
        path="~/.cache",
        what="여러 개발 도구가 다시 받을 수 있는 파일을 담아 두는 공용 캐시입니다.",
        why="도구를 쓸수록 쌓이고, 대부분 스스로 비우지 않습니다.",
        action="quarantine",
        risk="low",
        hint="'공간 요약'에서 분석하면 이 안의 캐시가 항목별로 잡힙니다.",
    ),
    SystemArea(
        key="npm_cache",
        name="npm 캐시 (.npm)",
        path="~/.npm",
        what="npm이 내려받은 패키지를 다시 쓰려고 저장해 둔 캐시입니다.",
        why="패키지를 설치할 때마다 쌓이고, npm이 스스로 줄이지 않습니다.",
        action="command",
        risk="low",
        command="npm cache clean --force",
        hint="지워도 다음 설치 때 필요한 것만 다시 받습니다. 처음 설치가 조금 느려질 뿐입니다.",
    ),
    SystemArea(
        key="cargo_registry",
        name="Rust 패키지 원본 (cargo registry)",
        path="~/.cargo/registry",
        what="cargo가 내려받은 크레이트 원본과 압축 파일입니다.",
        why="의존성 버전이 바뀔 때마다 새 버전이 추가되고, 옛 버전도 남습니다.",
        action="command",
        risk="low",
        command="rm -rf ~/.cargo/registry/src ~/.cargo/registry/cache",
        hint="지워도 다음 빌드 때 필요한 것만 다시 받습니다. ~/.cargo/bin은 설치된 도구라 건드리지 마세요.",
    ),
    SystemArea(
        key="vscode_extensions",
        name="에디터 확장 (VS Code)",
        path="~/.vscode/extensions",
        what="VS Code에 설치한 확장 프로그램입니다.",
        why="확장이 업데이트될 때 옛 버전 폴더가 한동안 남기도 합니다.",
        action="command",
        risk="medium",
        hint="VS Code의 확장 보기에서 안 쓰는 확장을 제거하세요. 폴더를 직접 지우면 VS Code가 확장 상태를 잃을 수 있습니다.",
    ),
    # ── 작업 폴더 ───────────────────────────────────────────────────────
    SystemArea(
        key="codex_workspaces",
        name="Codex 작업 폴더",
        path="~/Documents/Codex",
        what="Codex 앱이 작업마다 만드는 폴더입니다. 작업 중에 내려받은 도구와 빌드 결과물, 완성된 결과물이 함께 들어 있습니다.",
        why="작업을 할 때마다 날짜별 폴더가 생기고, 끝난 작업도 지우기 전까지 남습니다.",
        action="command",
        risk="high",
        command="du -sh ~/Documents/Codex/*/* | sort -rh | head -15",
        hint="결과물이 섞여 있으니 통째로 지우지 마세요. '공간 요약'에서 이 폴더를 분석하면 안쪽의 빌드 찌꺼기(.nosync 포함)만 따로 잡힙니다.",
    ),
    # ── 비우기 전까지 공간을 차지하는 곳 ───────────────────────────────
    SystemArea(
        key="trash",
        name="휴지통",
        path="~/.Trash",
        what="휴지통에 넣은 파일입니다.",
        why="휴지통에 넣어도 비우기 전까지는 공간을 그대로 차지합니다.",
        action="command",
        risk="medium",
        hint="Finder에서 휴지통을 확인하고 비우면 공간이 돌아옵니다. 비우면 되돌릴 수 없습니다.",
    ),
    SystemArea(
        key="spacekeeper_quarantine",
        name="Spacekeeper 격리함",
        path="~/.spacekeeper/quarantine",
        what="Spacekeeper로 격리한 파일입니다.",
        why="격리는 옮기기일 뿐이라, 비우기 전까지 공간을 그대로 차지합니다.",
        action="command",
        risk="low",
        hint="'격리함' 화면에서 확인하고, 필요 없는 것만 macOS 휴지통으로 비우세요.",
    ),
    # ── macOS가 관리하는 큰 덩어리 ─────────────────────────────────────
    SystemArea(
        key="apple_assets",
        name="애플 시스템 자산 (AI 모델·음성 등)",
        path="/System/Library/AssetsV2",
        what="macOS가 내려받아 두는 Apple Intelligence 모델, 받아쓰기·음성, 사전 같은 시스템 자산입니다.",
        why="기능을 켜거나 macOS를 업데이트할 때 받아지고, 새 버전이 오면 교체됩니다.",
        action="system",
        risk="high",
        hint="macOS가 관리합니다. 직접 지우면 해당 기능이 동작하지 않거나 다시 받습니다. 쓰지 않는 기능을 끄면 macOS가 관련 자산을 나중에 정리하기도 합니다.",
    ),
    SystemArea(
        key="spotlight_index",
        name="Spotlight 검색 색인",
        path="/System/Volumes/Data/.Spotlight-V100",
        what="Spotlight가 파일을 빨리 찾으려고 만든 색인입니다.",
        why="파일이 많을수록, 특히 작은 파일이 수십만 개인 의존성 폴더가 많을수록 커집니다.",
        action="system",
        risk="medium",
        hint="macOS가 관리합니다. 관리자만 읽을 수 있어 Spacekeeper는 크기를 잴 수 없습니다. 색인이 크다면 시스템 설정 → Spotlight에서 검색하지 않을 폴더를 지정할 수 있습니다.",
    ),
    SystemArea(
        key="system_db",
        name="시스템 데이터베이스",
        path="/private/var/db",
        what="macOS가 쓰는 각종 데이터베이스(진단 기록, 시스템 상태 등)입니다.",
        why="시스템이 동작하면서 기록을 계속 남깁니다.",
        action="system",
        risk="high",
        hint="macOS가 관리합니다. 직접 지우면 안 됩니다.",
    ),
)

# 위 목록에 없는 홈의 숨김 폴더도 이 크기를 넘으면 보여 준다.
# 무엇인지 모르면 모른다고 말한다 — 새 도구가 쌓여도 놓치지 않기 위해서다.
_OTHER_HIDDEN_MIN_BYTES = 200 * 1024 * 1024
OTHER_HIDDEN_NAME = "숨김 폴더 {name}"
OTHER_HIDDEN_WHAT = "어떤 도구가 홈 폴더에 만든 숨김 폴더입니다. Spacekeeper가 아직 이 폴더가 무엇인지 설명하지 못합니다."
OTHER_HIDDEN_WHY = "보통 개발 도구가 설정·캐시·설치본을 여기에 둡니다."
OTHER_HIDDEN_HINT = "이름으로 어떤 도구 것인지 확인한 뒤 그 도구에서 정리하세요. 설정이 함께 들어 있을 수 있어 통째로 지우지 마세요."


def _known_hidden_names() -> set[str]:
    """목록에 이미 있는 홈 숨김 폴더의 맨 위 이름(.local, .codex …)."""
    names = set()
    for area in AREAS:
        if area.path.startswith("~/."):
            names.add(area.path[2:].split("/", 1)[0])
    return names


def _other_hidden_areas(home: Path) -> list[SystemArea]:
    known = _known_hidden_names()
    areas = []
    try:
        entries = sorted(home.iterdir())
    except OSError:
        return areas
    for entry in entries:
        name = entry.name
        if not name.startswith(".") or name in known:
            continue
        try:
            if entry.is_symlink() or not entry.is_dir():
                continue
        except OSError:
            continue
        areas.append(
            SystemArea(
                key=f"hidden:{name}",
                name=OTHER_HIDDEN_NAME.format(name=name),
                path=f"~/{name}",
                what=OTHER_HIDDEN_WHAT,
                why=OTHER_HIDDEN_WHY,
                action="command",
                risk="medium",
                command=f"du -sh ~/{name}/* 2>/dev/null | sort -rh | head",
                hint=OTHER_HIDDEN_HINT,
            )
        )
    return areas


class Measurement(NamedTuple):
    size: int        # 할당 바이트 (실제로 읽은 만큼)
    files: int
    reachable: bool  # 맨 위 폴더라도 열었는가
    denied: int      # 권한이 없어 열지 못한 폴더 수 — 0이 아니면 size는 '최소값'이다


def _measure(path: Path, device: int | None = None) -> Measurement:
    """심링크는 따라가지 않는다. 권한 때문에 못 연 폴더는 건너뛰되 **센다**.

    예전에는 못 연 폴더를 조용히 건너뛰어서, 다른 앱 데이터(~/Library/Containers)
    760개를 하나도 못 읽고도 '18MB'라고 보고했다. 못 읽었으면 못 읽었다고 말해야 한다.
    """
    total = 0
    files = 0
    reachable = False
    denied = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                reachable = True
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            # 디스크 전체를 훑을 때는 다른 볼륨(외장 드라이브 등)으로 넘어가지 않는다.
                            if device is None or entry.stat(follow_symlinks=False).st_dev == device:
                                stack.append(Path(entry.path))
                            continue
                        stat = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    blocks = getattr(stat, "st_blocks", None)
                    total += blocks * 512 if blocks is not None else stat.st_size
                    files += 1
        except PermissionError:
            denied += 1
        except OSError:
            continue  # 재는 동안 사라진 폴더 등 — 권한 문제가 아니다
    return Measurement(total, files, reachable, denied)


def _local_snapshots() -> list[str]:
    """Time Machine 로컬 스냅샷 목록(있으면). 실패하면 빈 목록."""
    try:
        out = subprocess.run(
            ["/usr/bin/tmutil", "listlocalsnapshots", "/"],
            capture_output=True,
            text=True,
            timeout=_MEASURE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [
        line.strip()
        for line in out.stdout.splitlines()
        if line.strip().startswith("com.apple.TimeMachine")
    ]


def analyze() -> dict:
    """시스템 데이터 영역을 측정한다. 읽기만 하며 아무것도 바꾸지 않는다."""
    home = Path.home()

    def resolve(raw: str) -> Path:
        return Path(raw.replace("~", str(home), 1)) if raw.startswith("~") else Path(raw)

    others = _other_hidden_areas(home)
    other_keys = {area.key for area in others}
    targets = [(area, resolve(area.path)) for area in (*AREAS, *others)]
    with ThreadPoolExecutor(max_workers=min(8, (os.cpu_count() or 2) + 2)) as executor:
        measured = list(executor.map(lambda item: _measure(item[1]), targets))

    items = []
    total_bytes = 0
    for (area, resolved), (size, files, reachable, denied) in zip(targets, measured):
        exists = resolved.exists()
        # 없는 영역과 정말 빈 영역은 뺀다. 못 읽어서 0인 영역은 빼면 안 된다 —
        # 사용자는 그 영역이 있는지조차 모르게 된다.
        if not exists or (size <= 0 and denied == 0):
            continue
        if area.key in other_keys and size < _OTHER_HIDDEN_MIN_BYTES:
            continue  # 모르는 숨김 폴더는 클 때만 보여 준다
        total_bytes += size
        items.append(
            {
                "key": area.key,
                "name": area.name,
                "path": str(resolved),
                "display_path": area.path,
                "outside_home": home not in resolved.parents and resolved != home,
                "size": size,
                "file_count": files,
                "reachable": reachable,
                "denied_dirs": denied,
                "complete": denied == 0,
                "what": area.what,
                "why": area.why,
                "action": area.action,
                "risk": area.risk,
                "command": area.command,
                "hint": area.hint,
            }
        )
    items.sort(key=lambda item: item["size"], reverse=True)

    usage = shutil.disk_usage(home)
    snapshots = _local_snapshots()
    incomplete = [i for i in items if not i["complete"]]
    return {
        "items": items,
        "total_bytes": total_bytes,
        # 하나라도 일부만 쟀으면 합계는 '최소값'이다. 화면이 '이상'으로 표시한다.
        "total_is_lower_bound": bool(incomplete),
        "incomplete_count": len(incomplete),
        "disk": {"total": usage.total, "used": usage.used, "free": usage.free},
        "snapshot_count": len(snapshots),
        "outside_home_bytes": sum(i["size"] for i in items if i["outside_home"]),
        "quarantinable_bytes": sum(
            i["size"] for i in items if i["action"] == "quarantine"
        ),
    }



def compare(result: dict, previous: dict | None) -> dict | None:
    """지난 분석과 비교한다. 무엇이 늘었는지 답하려고.

    같은 조건으로 잰 영역끼리만 비교한다. 지난번엔 권한이 없어 일부만 쟀는데
    이번엔 다 쟀다면, 그 차이는 늘어난 게 아니라 더 많이 본 것이다.
    """
    if not previous:
        return None
    before = previous.get("areas") or {}
    deltas = {}
    for item in result.get("items", []):
        old = before.get(item["key"])
        if not old or bool(old[1]) != bool(item.get("complete", True)):
            continue
        deltas[item["key"]] = int(item["size"]) - int(old[0])
    disk = result.get("disk") or {}
    return {
        "at": previous.get("ts"),
        "disk_free_delta": int(disk.get("free", 0) or 0) - int(previous.get("disk_free", 0) or 0),
        "areas": deltas,
    }

# ── 디스크 전체 맞춰보기 ────────────────────────────────────────────────
# 위 영역 목록은 '알려진 곳'만 잰다. 그러면 목록 밖에 있는 공간이 얼마인지는
# 알 수 없다. 여기서는 디스크가 실제로 쓰는 양과, 폴더를 전부 훑어서 확인한 양을
# 나란히 놓는다. 차이를 숨기지 않고 '확인 못 한 공간'으로 보여 주기 위해서다.

DATA_ROOT = Path("/System/Volumes/Data")

# 같은 디스크(APFS 컨테이너)에 있는 다른 볼륨들. 폴더로는 보이지 않는다.
VOLUME_ROLES = {
    "System": ("macOS 시스템", "macOS 자체가 들어 있는 봉인된 볼륨입니다. macOS를 업데이트할 때만 바뀝니다."),
    "Preboot": ("부팅 준비 영역 (Preboot)", "Mac을 켤 때 필요한 파일과, 빠른 보안 응답 같은 시스템 구성 요소를 macOS가 두는 볼륨입니다."),
    "Recovery": ("복구 모드", "macOS 복구 모드에서 쓰는 볼륨입니다."),
    "VM": ("가상 메모리", "메모리가 모자랄 때 쓰는 스왑과 잠자기 이미지를 두는 볼륨입니다."),
    "Update": ("업데이트 준비 영역", "내려받은 macOS 업데이트를 설치하기 전에 두는 볼륨입니다."),
}


def _run_plist(args: list[str]) -> dict | None:
    try:
        out = subprocess.run(args, capture_output=True, timeout=_MEASURE_TIMEOUT_SECONDS * 2, check=False)
        return plistlib.loads(out.stdout) if out.returncode == 0 and out.stdout else None
    except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException, ValueError):
        return None


def _apfs_volumes(root: Path) -> tuple[list[dict], dict] | None:
    """root가 들어 있는 APFS 컨테이너의 볼륨 목록. 알 수 없으면 None."""
    info = _run_plist(["/usr/sbin/diskutil", "info", "-plist", str(root)])
    listing = _run_plist(["/usr/sbin/diskutil", "apfs", "list", "-plist"])
    if not info or not listing:
        return None
    container_ref = info.get("APFSContainerReference")
    data_device = info.get("DeviceIdentifier")
    for container in listing.get("Containers", []):
        if container.get("ContainerReference") != container_ref:
            continue
        volumes = [
            {
                "device": volume.get("DeviceIdentifier"),
                "name": volume.get("Name", ""),
                "role": (volume.get("Roles") or [""])[0],
                "used": int(volume.get("CapacityInUse") or 0),
                "is_data": volume.get("DeviceIdentifier") == data_device,
            }
            for volume in container.get("Volumes", [])
        ]
        capacity = {
            "total": int(container.get("CapacityCeiling") or 0),
            "free": int(container.get("CapacityFree") or 0),
        }
        return volumes, capacity
    return None


def disk_accounting(root: Path = DATA_ROOT) -> dict:
    """디스크가 쓰는 양과 확인한 양을 맞춰 본다. 읽기만 한다."""
    try:
        device = os.stat(root).st_dev
        entries = list(os.scandir(root))
    except OSError:
        return {"available": False}

    folders: list[tuple[str, Path]] = []
    loose_bytes = 0
    for entry in entries:
        try:
            if entry.is_symlink() or entry.name == "Volumes":  # 외장 드라이브가 붙는 곳
                continue
            if entry.is_dir(follow_symlinks=False):
                if entry.stat(follow_symlinks=False).st_dev == device:
                    folders.append((entry.name, Path(entry.path)))
            else:
                stat = entry.stat(follow_symlinks=False)
                loose_bytes += getattr(stat, "st_blocks", 0) * 512
        except OSError:
            continue

    with ThreadPoolExecutor(max_workers=min(8, (os.cpu_count() or 2) + 2)) as executor:
        results = list(executor.map(lambda item: _measure(item[1], device), folders))

    rows = [
        {"name": name, "size": m.size, "denied_dirs": m.denied}
        for (name, _), m in zip(folders, results)
        if m.size > 0 or m.denied
    ]
    rows.sort(key=lambda row: row["size"], reverse=True)
    measured = sum(row["size"] for row in rows) + loose_bytes
    denied = sum(row["denied_dirs"] for row in rows)

    apfs = _apfs_volumes(root)
    data_used = None
    other_volumes: list[dict] = []
    capacity = None
    if apfs:
        volumes, capacity = apfs
        for volume in volumes:
            if volume["is_data"]:
                data_used = volume["used"]
            elif volume["used"] > 0:
                label, what = VOLUME_ROLES.get(volume["role"], (volume["name"], ""))
                other_volumes.append({"role": volume["role"], "name": label, "what": what, "used": volume["used"]})
        other_volumes.sort(key=lambda v: v["used"], reverse=True)

    return {
        "available": True,
        "data_used": data_used,
        "measured": measured,
        # 볼륨 정보를 못 얻으면 차이를 지어내지 않는다.
        "unexplained": max(0, data_used - measured) if data_used is not None else None,
        "denied_dirs": denied,
        "folders": rows,
        "other_volumes": other_volumes,
        "capacity": capacity,
        "snapshot_count": len(_local_snapshots()),
    }

