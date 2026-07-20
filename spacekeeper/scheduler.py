from __future__ import annotations

import json
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
    return ScheduleConfig(
        enabled=data.get("enabled", False),
        interval_hours=data.get("interval_hours", 168),
        auto_quarantine_low_risk=data.get("auto_quarantine_low_risk", False),
        notify=data.get("notify", True),
        last_run_at=data.get("last_run_at"),
    )


def load_schedule() -> ScheduleConfig:
    """Load schedule configuration from *CONFIG_PATH*.

    Returns a default *ScheduleConfig* when the file does not exist or
    cannot be parsed.
    """
    try:
        text = CONFIG_PATH.read_text(encoding="utf-8")
        return from_dict(json.loads(text))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return ScheduleConfig()


def save_schedule(config: ScheduleConfig) -> None:
    """Persist *config* to *CONFIG_PATH*, creating parent directories."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(to_dict(config), indent=2) + "\n",
        encoding="utf-8",
    )


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
    freed = 0

    if config.auto_quarantine_low_risk:
        from . import engine
        from .planning import build_cleanup_plan

        plan = build_cleanup_plan(result, risks={"low"}, limit=1_000_000)
        items = [(entry.action_id, entry.path, entry.kind) for entry in plan.entries]
        try:
            outcome = engine.quarantine(items)
            quarantined = len(outcome.moved)
            freed = outcome.quarantined_bytes
        except Exception:  # noqa: BLE001 - 예약 실행은 조용히 실패해야 한다.
            quarantined = 0

    if config.notify:
        from . import notifier

        if quarantined:
            notifier.notify_quarantine_action(False, quarantined, freed)
        else:
            notifier.notify_scan_complete(result.review_candidate_bytes, candidate_count)

    config.last_run_at = now if now is not None else time.time()
    save_schedule(config)
    return {
        "status": "ok",
        "candidate_count": candidate_count,
        "quarantined": quarantined,
        "freed_bytes": freed,
    }
