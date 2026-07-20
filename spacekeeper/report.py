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
        f"볼륨 상태: 전체 {format_bytes(result.volume_total_bytes)} / "
        f"사용 {format_bytes(result.volume_used_bytes)} / "
        f"여유 {format_bytes(result.volume_free_bytes)}",
        f"확인한 파일: {result.scanned_files:,}개",
        f"파일별 할당 블록 합계: {format_bytes(result.scanned_bytes)} "
        f"(논리 크기 {format_bytes(result.scanned_logical_bytes)})",
        f"소요 시간: {duration:.2f}초",
        f"검토 후보 할당량 추정(중복 제외): {format_bytes(result.review_candidate_bytes)}",
        "위험도별 후보: "
        f"낮은 위험 {format_bytes(result.candidate_bytes_by_risk['low'])} / "
        f"검토 필요 {format_bytes(result.candidate_bytes_by_risk['medium'])} / "
        f"높은 주의 {format_bytes(result.candidate_bytes_by_risk['high'])}",
        "참고: APFS 복제·공유 블록 때문에 실제 확보량은 이 합계보다 작을 수 있습니다.",
    ]
    if result.duplicate_groups:
        lines.append(
            "완전 동일 파일의 이론상 절약량: "
            f"{format_bytes(result.duplicate_reclaimable_bytes)} (다른 후보와 겹칠 수 있음)"
        )
    if (
        result.permission_denied
        or result.skipped_symlinks
        or result.skipped_cloud_dirs
        or result.skipped_excluded_paths
    ):
        lines.append(
            f"건너뜀: 권한 제한 {result.permission_denied}건 / "
            f"심볼릭 링크 {result.skipped_symlinks}건 / "
            f"클라우드 루트 {result.skipped_cloud_dirs}건 / "
            f"제외 경로 {result.skipped_excluded_paths}건"
        )
    if result.excluded_paths:
        lines.append(f"제외 설정: {', '.join(result.excluded_paths)}")

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
            f"  {index}) 파일당 논리 크기 "
            f"{format_bytes(group.logical_size_each)} · "
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


def render_html_report(result: ScanResult) -> str:
    """ScanResult를 독립 실행 가능한 아름다운 HTML Audit 리포트로 렌더링한다."""
    text_content = render_text(result)
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <title>Spacekeeper Audit Report - {date_str}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0b0d12; color: #eef1f7; margin: 0; padding: 40px 20px; }}
    .container {{ max-width: 800px; margin: 0 auto; background: #161a22; border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 32px; box-shadow: 0 20px 50px rgba(0,0,0,0.5); }}
    h1 {{ color: #5b8cff; margin-top: 0; font-size: 24px; }}
    pre {{ background: #0c0e14; padding: 20px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.07); color: #a1b0cb; font-family: monospace; white-space: pre-wrap; font-size: 13px; line-height: 1.5; }}
    .footer {{ margin-top: 24px; font-size: 12px; color: #6a7180; text-align: center; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>🛡️ Spacekeeper Local Storage Audit Report</h1>
    <p>생성 시각: {date_str}</p>
    <pre>{text_content}</pre>
    <div class="footer">Spacekeeper • Local Storage Care Agent for macOS</div>
  </div>
</body>
</html>"""
