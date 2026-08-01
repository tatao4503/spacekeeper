from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ScheduleConfig:
    enabled: bool = False
    interval_hours: int = 168
    # 백그라운드에서 사용자 확인 없이 파일을 옮기지 않는다. 명시적으로 켤 때만 True.
    auto_quarantine_low_risk: bool = False
    notify: bool = True
    last_run_at: float | None = None


CONFIG_PATH = Path.home() / ".spacekeeper" / "schedule.json"
_MAX_INTERVAL_HOURS = 24 * 365
AUTO_QUARANTINE_CATEGORIES = {
    "cocoapods_cache",
    "go_cache",
    "homebrew_cache",
    "package_cache",
    "pip_cache",
    "python_cache",
    "test_cache",
    "tool_cache",
}


def to_dict(config: ScheduleConfig) -> dict:
    """Serialize a *ScheduleConfig* to a JSON-safe dictionary."""
    return {
        "enabled": config.enabled,
        "interval_hours": config.interval_hours,
        "auto_quarantine_low_risk": config.auto_quarantine_low_risk,
        "notify": config.notify,
        "last_run_at": config.last_run_at,
    }


def from_dict(data: dict) -> ScheduleConfig:
    """Deserialize a dictionary into a *ScheduleConfig* with safe defaults."""
    if not isinstance(data, dict):
        raise ValueError("스케줄 설정은 JSON 객체여야 합니다.")

    def boolean(key: str, default: bool) -> bool:
        value = data.get(key, default)
        if not isinstance(value, bool):
            raise ValueError(f"{key}는 true 또는 false여야 합니다.")
        return value

    interval_hours = data.get("interval_hours", 168)
    if (
        isinstance(interval_hours, bool)
        or not isinstance(interval_hours, int)
        or not 1 <= interval_hours <= _MAX_INTERVAL_HOURS
    ):
        raise ValueError(
            f"interval_hours는 1~{_MAX_INTERVAL_HOURS} 사이 정수여야 합니다."
        )

    last_run_at = data.get("last_run_at")
    if (
        last_run_at is not None
        and (
            isinstance(last_run_at, bool)
            or not isinstance(last_run_at, (int, float))
        )
    ):
        raise ValueError("last_run_at 형식이 올바르지 않습니다.")

    return ScheduleConfig(
        enabled=boolean("enabled", False),
        interval_hours=interval_hours,
        auto_quarantine_low_risk=boolean(
            "auto_quarantine_low_risk", False
        ),
        notify=boolean("notify", True),
        last_run_at=last_run_at,
    )


def load_schedule() -> ScheduleConfig:
    """Load schedule configuration from *CONFIG_PATH*.

    Returns a default *ScheduleConfig* when the file does not exist or
    cannot be parsed.
    """
    try:
        text = CONFIG_PATH.read_text(encoding="utf-8")
        return from_dict(json.loads(text))
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        OSError,
        TypeError,
        ValueError,
    ):
        return ScheduleConfig()


def save_schedule(config: ScheduleConfig) -> None:
    """Persist *config* atomically, creating the parent directory."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(to_dict(config), handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, CONFIG_PATH)
    finally:
        temporary.unlink(missing_ok=True)


def run_scheduled(now: float | None = None) -> dict:
    """예약 실행 진입점.

    설정이 꺼져 있으면 아무것도 하지 않는다. 기본 동작은 홈 폴더를 분석해
    결과를 알림으로만 알리는 것이며, ``auto_quarantine_low_risk`` 를 명시적으로
    켠 경우에만 낮은 위험 후보를 격리함으로 옮긴다(되돌릴 수 있음).
    """
    import time
    from pathlib import Path

    from .models import ScanOptions
    from .scanner import scan

    config = load_schedule()
    if not config.enabled:
        return {"status": "skipped", "reason": "disabled"}

    result = scan(ScanOptions(roots=(Path.home(),)))
    candidate_count = result.file_candidate_count + result.cache_candidate_count
    quarantined = 0
    quarantined_bytes = 0

    if config.auto_quarantine_low_risk:
        from . import engine
        from .planning import build_cleanup_plan

        plan = build_cleanup_plan(result, risks={"low"}, limit=1_000_000)
        items = [
            (entry.action_id, entry.path, entry.kind)
            for entry in plan.entries
            if entry.category in AUTO_QUARANTINE_CATEGORIES
        ]
        try:
            outcome = engine.quarantine(items)
            quarantined = len(outcome.moved)
            quarantined_bytes = outcome.quarantined_bytes
        except Exception:  # noqa: BLE001 - 예약 실행은 조용히 실패해야 한다.
            quarantined = 0

    if config.notify:
        from . import notifier

        if quarantined:
            notifier.notify_quarantine_action(
                False, quarantined, quarantined_bytes
            )
        else:
            notifier.notify_scan_complete(result.review_candidate_bytes, candidate_count)

    config.last_run_at = now if now is not None else time.time()
    save_schedule(config)
    return {
        "status": "ok",
        "candidate_count": candidate_count,
        "quarantined": quarantined,
        "quarantined_bytes": quarantined_bytes,
        "disk_space_freed_bytes": 0,
    }
