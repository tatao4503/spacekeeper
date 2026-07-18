from __future__ import annotations

from datetime import datetime

from .models import ScanResult


RISK_LABELS = {
    "low": "낮은 위험",
    "medium": "검토 필요",
    "high": "높은 주의",
}


def format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    raise AssertionError("unreachable")


def _format_date(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")


def render_text(result: ScanResult) -> str:
    duration = result.finished_at - result.started_at
    lines = [
        "SPACEKEEPER READ-ONLY REPORT",
        "=" * 31,
        "안전 상태: 읽기 전용 · 삭제 없음 · 네트워크 전송 없음 · 심볼릭 링크 미추적",
        f"스캔 경로: {', '.join(result.roots)}",
        f"확인한 파일: {result.scanned_files:,}개 / {format_bytes(result.scanned_bytes)}",
        f"소요 시간: {duration:.2f}초",
        f"검토 후보(중복 제외): {format_bytes(result.review_candidate_bytes)}",
    ]
    if result.duplicate_groups:
        lines.append(
            "완전 동일 파일의 이론상 절약량: "
            f"{format_bytes(result.duplicate_reclaimable_bytes)} (다른 후보와 겹칠 수 있음)"
        )
    if result.permission_denied or result.skipped_symlinks:
        lines.append(
            f"건너뜀: 권한 제한 {result.permission_denied}건 / "
            f"심볼릭 링크 {result.skipped_symlinks}건"
        )

    hidden_cache_count = result.cache_candidate_count - len(result.cache_candidates)
    cache_heading = "1. 재생성 가능한 폴더 후보"
    if hidden_cache_count:
        cache_heading += f" (상위 {len(result.cache_candidates)}개, {hidden_cache_count}개 생략)"
    lines.extend(["", cache_heading])
    if not result.cache_candidates:
        lines.append("  없음")
    for index, item in enumerate(result.cache_candidates, start=1):
        lines.extend(
            [
                f"  {index}) {format_bytes(item.size)} · {item.file_count:,}개 · {RISK_LABELS[item.risk]}",
                f"     {item.path}",
                f"     이유: {item.reason}",
                f"     주의: {item.caution}",
            ]
        )

    hidden_file_count = result.file_candidate_count - len(result.file_candidates)
    file_heading = "2. 개별 파일 검토 후보"
    if hidden_file_count:
        file_heading += f" (상위 {len(result.file_candidates)}개, {hidden_file_count}개 생략)"
    lines.extend(["", file_heading])
    if not result.file_candidates:
        lines.append("  없음")
    for index, item in enumerate(result.file_candidates, start=1):
        lines.extend(
            [
                f"  {index}) {format_bytes(item.size)} · {_format_date(item.modified_at)} · {RISK_LABELS[item.risk]}",
                f"     {item.path}",
                f"     이유: {' '.join(item.reasons)}",
                f"     주의: {item.caution}",
            ]
        )

    hidden_duplicate_count = result.duplicate_group_count - len(result.duplicate_groups)
    duplicate_heading = "3. 완전 동일 파일"
    if hidden_duplicate_count:
        duplicate_heading += (
            f" (상위 {len(result.duplicate_groups)}개, {hidden_duplicate_count}개 생략)"
        )
    lines.extend(["", duplicate_heading])
    if not result.duplicate_groups:
        lines.append("  검사하지 않았거나 발견되지 않음")
    for index, group in enumerate(result.duplicate_groups, start=1):
        lines.append(
            f"  {index}) 파일당 {format_bytes(group.size_each)} · "
            f"최대 {format_bytes(group.reclaimable_bytes)} 절약"
        )
        lines.extend(f"     {path}" for path in group.paths)

    if result.errors:
        lines.extend(["", "진단 메모"])
        lines.extend(f"  - {error}" for error in result.errors)

    lines.extend(
        [
            "",
            "판단: 이 보고서는 정리 후보를 좁혀줄 뿐, 삭제를 승인하지 않습니다.",
            "다음 단계에서도 선택한 항목만 휴지통 또는 격리함으로 이동해야 합니다.",
        ]
    )
    return "\n".join(lines)
