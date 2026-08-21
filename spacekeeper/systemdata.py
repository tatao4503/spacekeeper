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
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

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
)


def _measure(path: Path) -> tuple[int, int, bool]:
    """(할당 바이트, 파일 수, 접근가능) — 심링크는 따라가지 않고, 권한 오류는 건너뛴다."""
    total = 0
    files = 0
    reachable = False
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
                            stack.append(Path(entry.path))
                            continue
                        stat = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    blocks = getattr(stat, "st_blocks", None)
                    total += blocks * 512 if blocks is not None else stat.st_size
                    files += 1
        except OSError:
            continue
    return total, files, reachable


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

    targets = [(area, resolve(area.path)) for area in AREAS]
    with ThreadPoolExecutor(max_workers=min(8, (os.cpu_count() or 2) + 2)) as executor:
        measured = list(executor.map(lambda item: _measure(item[1]), targets))

    items = []
    total_bytes = 0
    for (area, resolved), (size, files, reachable) in zip(targets, measured):
        exists = resolved.exists()
        if not exists or size <= 0:
            continue
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
    return {
        "items": items,
        "total_bytes": total_bytes,
        "disk": {"total": usage.total, "used": usage.used, "free": usage.free},
        "snapshot_count": len(snapshots),
        "outside_home_bytes": sum(i["size"] for i in items if i["outside_home"]),
        "quarantinable_bytes": sum(
            i["size"] for i in items if i["action"] == "quarantine"
        ),
    }
