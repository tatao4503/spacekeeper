from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

from .models import CacheCandidate, FileCandidate, ScanResult
from .report import RISK_LABELS, format_bytes


VALID_RISKS = ("low", "medium", "high")


@dataclass(frozen=True)
class PlanEntry:
    action_id: str
    kind: str
    path: str
    allocated_bytes: int
    logical_bytes: int
    risk: str
    category: str
    reason: str
    caution: str
    proposed_action: str = "quarantine"
    selected: bool = False


@dataclass(frozen=True)
class CleanupPlan:
    schema_version: int
    mode: str
    created_at: float
    source_roots: list[str]
    risk_filter: list[str]
    entries: list[PlanEntry]
    total_allocated_bytes: int
    omitted_plan_entries: int
    omitted_scan_candidates: int
    scan_errors: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["safety"] = {
            "preview_only": True,
            "files_moved": 0,
            "files_deleted": 0,
            "requires_explicit_selection": True,
        }
        return payload


def _action_id(kind: str, path: str) -> str:
    digest = hashlib.sha256(f"{kind}\0{path}".encode("utf-8")).hexdigest()[:10]
    prefix = "C" if kind == "cache_directory" else "F"
    return f"{prefix}-{digest}"


def _cache_entry(item: CacheCandidate) -> PlanEntry:
    return PlanEntry(
        action_id=_action_id("cache_directory", item.path),
        kind="cache_directory",
        path=item.path,
        allocated_bytes=item.size,
        logical_bytes=item.logical_size,
        risk=item.risk,
        category=item.category,
        reason=item.reason,
        caution=item.caution,
    )


def _file_entry(item: FileCandidate) -> PlanEntry:
    return PlanEntry(
        action_id=_action_id("file", item.path),
        kind="file",
        path=item.path,
        allocated_bytes=item.size,
        logical_bytes=item.logical_size,
        risk=item.risk,
        category=item.category,
        reason=" ".join(item.reasons),
        caution=item.caution,
    )


def build_cleanup_plan(
    result: ScanResult,
    risks: set[str],
    limit: int,
) -> CleanupPlan:
    if not risks or not risks.issubset(VALID_RISKS):
        raise ValueError("지원하지 않는 위험도 필터입니다.")
    if limit <= 0:
        raise ValueError("미리보기 개수는 0보다 커야 합니다.")

    entries = [
        *(_cache_entry(item) for item in result.cache_candidates if item.risk in risks),
        *(_file_entry(item) for item in result.file_candidates if item.risk in risks),
    ]
    entries.sort(key=lambda item: item.allocated_bytes, reverse=True)
    matching_count = len(entries)
    entries = entries[:limit]
    omitted_scan_candidates = (
        result.cache_candidate_count
        + result.file_candidate_count
        - len(result.cache_candidates)
        - len(result.file_candidates)
    )
    return CleanupPlan(
        schema_version=1,
        mode="preview_only",
        created_at=result.finished_at,
        source_roots=result.roots,
        risk_filter=sorted(risks, key=VALID_RISKS.index),
        entries=entries,
        total_allocated_bytes=sum(item.allocated_bytes for item in entries),
        omitted_plan_entries=matching_count - len(entries),
        omitted_scan_candidates=max(0, omitted_scan_candidates),
        scan_errors=len(result.errors) + result.permission_denied,
    )


def render_cleanup_plan(plan: CleanupPlan) -> str:
    risk_labels = ", ".join(RISK_LABELS[risk] for risk in plan.risk_filter)
    lines = [
        "SPACEKEEPER CLEANUP PREVIEW",
        "=" * 31,
        "상태: 미리보기 전용 · 선택 0개 · 이동 0개 · 삭제 0개",
        f"위험도 필터: {risk_labels}",
        f"표시 항목: {len(plan.entries)}개",
        f"전체 할당량 추정: {format_bytes(plan.total_allocated_bytes)}",
        "참고: 실제 확보량은 APFS 공유 블록 때문에 더 작을 수 있습니다.",
    ]
    if plan.omitted_scan_candidates:
        lines.append(
            f"주의: 스캔 표시 한도 밖의 후보 {plan.omitted_scan_candidates}개는 "
            "이 미리보기에 포함되지 않았습니다."
        )
    if plan.omitted_plan_entries:
        lines.append(
            f"주의: 필터에 맞는 추가 후보 {plan.omitted_plan_entries}개는 "
            "--top 표시 한도로 생략됐습니다."
        )
    if plan.scan_errors:
        lines.append(
            f"주의: 권한 제한·스캔 오류 {plan.scan_errors}건으로 결과가 불완전할 수 있습니다."
        )

    lines.append("")
    if not plan.entries:
        lines.append("  조건에 맞는 정리 후보가 없습니다.")
    for index, entry in enumerate(plan.entries, start=1):
        lines.extend(
            [
                f"{index}) [{entry.action_id}] {format_bytes(entry.allocated_bytes)} · "
                f"{RISK_LABELS[entry.risk]} · {entry.category}",
                f"   {entry.path}",
                f"   이유: {entry.reason}",
                f"   주의: {entry.caution}",
                "   제안 작업: 격리함 이동 (현재는 실행하지 않음)",
            ]
        )

    lines.extend(
        [
            "",
            "이 ID는 경로가 같으면 다음 스캔에서도 같습니다.",
            "격리 기능이 추가되기 전까지 이 계획은 어떤 파일도 변경하지 않습니다.",
        ]
    )
    return "\n".join(lines)
