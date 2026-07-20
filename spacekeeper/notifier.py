"""macOS Native Notification Center integration.

`osascript`를 활용하여 외부 종속성 없이 macOS 시스템 알림 센터로
스캔 완료 및 격리/복구 알림을 발송합니다.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

from .report import format_bytes


def _escape_applescript_string(value: str) -> str:
    """AppleScript 문자열 리터럴을 안전하게 이스케이프한다."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def notify_macos(
    title: str,
    message: str,
    *,
    subtitle: str = "",
) -> bool:
    """macOS 시스템 알림 센터에 메시지를 발송한다.

    Returns:
        bool: 알림 발송 명령이 성공했는지 여부
    """
    if sys.platform != "darwin":
        return False

    osascript_path = shutil.which("osascript")
    if not osascript_path:
        return False

    escaped_title = _escape_applescript_string(title)
    escaped_message = _escape_applescript_string(message)

    script_parts = [f'display notification "{escaped_message}" with title "{escaped_title}"']
    if subtitle:
        escaped_subtitle = _escape_applescript_string(subtitle)
        script_parts.append(f'subtitle "{escaped_subtitle}"')

    script = " ".join(script_parts)

    try:
        res = subprocess.run(
            [osascript_path, "-e", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5.0,
        )
        return res.returncode == 0
    except Exception:
        return False


def notify_scan_complete(
    review_bytes: int,
    candidate_count: int,
    *,
    duration_seconds: float | None = None,
) -> bool:
    """저장공간 스캔 완료 알림을 발송한다."""
    title = "Spacekeeper"
    subtitle = "저장공간 분석 완료"
    human_size = format_bytes(review_bytes)
    message = f"정리 가능한 후보 {candidate_count}개 ({human_size})를 발견했습니다."
    return notify_macos(title, message, subtitle=subtitle)


def notify_quarantine_action(
    restored: bool,
    item_count: int,
    total_bytes: int,
) -> bool:
    """격리함 이동 또는 복구 알림을 발송한다."""
    title = "Spacekeeper"
    human_size = format_bytes(total_bytes)
    if restored:
        subtitle = "원래 위치로 복구 완료"
        message = f"격리 항목 {item_count}개 ({human_size})를 원래 위치로 복구했습니다."
    else:
        subtitle = "격리함 이동 완료"
        message = f"선택 항목 {item_count}개 ({human_size})를 안전하게 격리함으로 옮겼습니다."
    return notify_macos(title, message, subtitle=subtitle)
