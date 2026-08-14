"""로컬 활동 기록.

스캔·격리·복원·휴지통 이벤트를 ``~/.spacekeeper/history.jsonl`` 에 append-only
로 남긴다. 이 기록으로 '시간에 따른 추이'와 '정리 전/후 리포트'를 그린다.

네트워크·계정 없이 전부 로컬이며, 개인 경로가 남으므로 저장소에 커밋하지 않는다
(런타임 생성 파일). 기록 실패가 기능을 막지 않도록 모든 I/O 오류는 조용히 넘긴다.
숫자는 만들지 않고 스캐너·엔진이 계산한 값만 그대로 저장한다.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

HISTORY_PATH = Path.home() / ".spacekeeper" / "history.jsonl"
_MAX_RECORDS = 500


def _append(record: dict) -> None:
    try:
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with HISTORY_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        _trim()
    except OSError:
        pass


def _trim() -> None:
    """기록이 너무 커지지 않게 최근 _MAX_RECORDS개만 원자적으로 유지한다."""
    try:
        lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) <= _MAX_RECORDS:
        return
    kept = [line for line in lines if line.strip()][-_MAX_RECORDS:]
    temporary = HISTORY_PATH.with_suffix(".jsonl.tmp")
    try:
        temporary.write_text("\n".join(kept) + "\n", encoding="utf-8")
        os.replace(temporary, HISTORY_PATH)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def record_scan(payload: dict, now: float | None = None) -> None:
    """완료된 스캔의 요약을 기록한다(스캐너가 계산한 값 그대로)."""
    disk = payload.get("disk") or {}
    _append(
        {
            "ts": now if now is not None else time.time(),
            "type": "scan",
            "roots": list(payload.get("roots", [])),
            "reclaimable_bytes": int(payload.get("review_bytes", 0) or 0),
            "by_risk": payload.get("by_risk") or {},
            "scanned_files": int(payload.get("scanned_files", 0) or 0),
            "duplicate_bytes": int(payload.get("duplicate_reclaimable_bytes", 0) or 0),
            "disk_free": int(disk.get("free", 0) or 0),
            "disk_total": int(disk.get("total", 0) or 0),
            "duration": round(float(payload.get("duration", 0.0) or 0.0), 2),
        }
    )


def record_operation(
    op_type: str, count: int, total_bytes: int, now: float | None = None
) -> None:
    """격리/복원/휴지통 이벤트를 기록한다. op_type: quarantine | restore | empty."""
    _append(
        {
            "ts": now if now is not None else time.time(),
            "type": op_type,
            "count": int(count or 0),
            "bytes": int(total_bytes or 0),
        }
    )


def load_history(limit: int = 200) -> list[dict]:
    """최근 기록을 오래된 순으로 반환한다(그리기 편하게)."""
    try:
        lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records
