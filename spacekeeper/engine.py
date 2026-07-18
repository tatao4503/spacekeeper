"""Reversible cleanup engine.

Spacekeeper는 파일을 영구 삭제하지 않습니다. 정리 요청은 파일을
`~/.spacekeeper/quarantine/`로 **이동**만 하며, manifest에 원래 위치를
기록해 언제든 복구할 수 있습니다. 최종 비우기는 hard delete가 아니라
macOS 휴지통으로 옮기므로 Finder에서도 되돌릴 수 있습니다.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


QUARANTINE_ROOT = Path.home() / ".spacekeeper" / "quarantine"
MANIFEST_PATH = QUARANTINE_ROOT / "manifest.jsonl"
TRASH_ROOT = Path.home() / ".Trash"

# 이동을 허용하는, 홈 밖의 추가 루트. 홈은 항상 허용된다.
_EXTRA_ALLOWED_ROOTS = (Path("/Applications"),)

# 절대 건드리면 안 되는 경로. 허용 루트 밑이라도 이 밑은 무조건 제외한다.
_PROTECTED_ROOTS = (
    Path("/System"),
    Path("/Library"),
    Path("/usr"),
    Path("/bin"),
    Path("/sbin"),
    Path("/private"),
    Path.home() / "Library" / "Keychains",
    Path.home() / ".ssh",
    Path.home() / ".gnupg",
)


class UnsafePathError(Exception):
    """이동하면 안 되는 경로를 정리하려 할 때 발생."""


@dataclass(frozen=True)
class QuarantineRecord:
    action_id: str
    original_path: str
    stored_path: str
    allocated_bytes: int
    kind: str
    quarantined_at: float
    restored_at: float | None = None
    emptied_at: float | None = None

    @property
    def status(self) -> str:
        if self.emptied_at is not None:
            return "emptied"
        if self.restored_at is not None:
            return "restored"
        return "quarantined"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status
        return payload


def _assert_safe_to_move(path: Path) -> None:
    """이동해도 안전한 경로인지 확인한다. 아니면 UnsafePathError."""
    allowed_roots = (Path.home().resolve(),) + tuple(
        root.resolve() for root in _EXTRA_ALLOWED_ROOTS
    )
    if path.is_symlink():
        raise UnsafePathError(f"심볼릭 링크는 이동하지 않습니다: {path}")
    if not path.exists():
        raise UnsafePathError(f"경로가 존재하지 않습니다: {path}")
    resolved = path.resolve()
    if resolved in allowed_roots:
        raise UnsafePathError(f"최상위 폴더 자체는 이동할 수 없습니다: {resolved}")
    if not any(resolved.is_relative_to(root) for root in allowed_roots):
        raise UnsafePathError(f"허용되지 않은 위치입니다: {resolved}")
    if resolved.is_relative_to(QUARANTINE_ROOT.resolve()):
        raise UnsafePathError("격리함 안의 항목은 다시 격리할 수 없습니다.")
    for protected in _PROTECTED_ROOTS:
        protected = protected.resolve() if protected.exists() else protected
        if resolved == protected or resolved.is_relative_to(protected):
            raise UnsafePathError(f"보호된 경로는 이동할 수 없습니다: {resolved}")


def _allocated_bytes(path: Path) -> int:
    if path.is_file():
        stat = path.stat()
        blocks = getattr(stat, "st_blocks", None)
        return blocks * 512 if blocks is not None else stat.st_size
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                stat = os.lstat(os.path.join(root, name))
            except OSError:
                continue
            blocks = getattr(stat, "st_blocks", None)
            total += blocks * 512 if blocks is not None else stat.st_size
    return total


def _read_records() -> list[QuarantineRecord]:
    if not MANIFEST_PATH.exists():
        return []
    records: list[QuarantineRecord] = []
    with MANIFEST_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            data.pop("status", None)
            records.append(QuarantineRecord(**data))
    return records


def _write_records(records: list[QuarantineRecord]) -> None:
    QUARANTINE_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_PATH.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
    tmp.replace(MANIFEST_PATH)


def _latest_by_action(records: list[QuarantineRecord]) -> dict[str, QuarantineRecord]:
    latest: dict[str, QuarantineRecord] = {}
    for record in records:
        latest[record.action_id] = record
    return latest


def _stored_dir(action_id: str, name: str) -> Path:
    return QUARANTINE_ROOT / f"{action_id}__{name}"


@dataclass(frozen=True)
class ReclaimOutcome:
    moved: list[QuarantineRecord]
    skipped: list[dict[str, str]]

    @property
    def quarantined_bytes(self) -> int:
        return sum(record.allocated_bytes for record in self.moved)

    def to_dict(self) -> dict[str, Any]:
        return {
            "moved": [record.to_dict() for record in self.moved],
            "skipped": self.skipped,
            "quarantined_bytes": self.quarantined_bytes,
            "disk_space_freed_bytes": 0,
            "moved_count": len(self.moved),
            "skipped_count": len(self.skipped),
        }


def quarantine(
    items: list[tuple[str, str, str]], now: float | None = None
) -> ReclaimOutcome:
    """(action_id, path, kind) 목록을 격리함으로 이동한다.

    각 항목을 개별적으로 검증하며, 안전하지 않은 항목은 건너뛰고 나머지는
    계속 진행한다. 실제로 이동한 항목만 manifest에 기록한다.
    """
    stamp = now if now is not None else time.time()
    QUARANTINE_ROOT.mkdir(parents=True, exist_ok=True)
    records = _read_records()
    active = {
        record.action_id
        for record in _latest_by_action(records).values()
        if record.status == "quarantined"
    }
    moved: list[QuarantineRecord] = []
    skipped: list[dict[str, str]] = []

    for action_id, raw_path, kind in items:
        path = Path(raw_path)
        if action_id in active:
            skipped.append({"path": raw_path, "reason": "이미 격리된 항목입니다."})
            continue
        try:
            _assert_safe_to_move(path)
        except UnsafePathError as exc:
            skipped.append({"path": raw_path, "reason": str(exc)})
            continue

        allocated = _allocated_bytes(path)
        destination = _stored_dir(action_id, path.name)
        if destination.exists():
            skipped.append(
                {"path": raw_path, "reason": "격리함에 같은 이름이 이미 있습니다."}
            )
            continue
        try:
            shutil.move(str(path), str(destination))
        except OSError as exc:
            skipped.append({"path": raw_path, "reason": f"이동 실패: {exc}"})
            continue

        record = QuarantineRecord(
            action_id=action_id,
            original_path=str(path),
            stored_path=str(destination),
            allocated_bytes=allocated,
            kind=kind,
            quarantined_at=stamp,
        )
        records.append(record)
        moved.append(record)
        active.add(action_id)

    if moved:
        _write_records(records)
    return ReclaimOutcome(moved=moved, skipped=skipped)


def list_quarantine() -> list[QuarantineRecord]:
    """현재 격리 상태(quarantined)인 항목만 최신 기준으로 반환한다."""
    latest = _latest_by_action(_read_records())
    return sorted(
        (r for r in latest.values() if r.status == "quarantined"),
        key=lambda r: r.quarantined_at,
        reverse=True,
    )


def restore(action_id: str, now: float | None = None) -> QuarantineRecord:
    """격리 항목을 원래 위치로 되돌린다."""
    stamp = now if now is not None else time.time()
    records = _read_records()
    latest = _latest_by_action(records)
    record = latest.get(action_id)
    if record is None or record.status != "quarantined":
        raise KeyError(f"격리 중인 항목이 아닙니다: {action_id}")

    stored = Path(record.stored_path)
    original = Path(record.original_path)
    if not stored.exists():
        raise FileNotFoundError(f"격리 파일이 없습니다: {stored}")
    if original.exists():
        raise FileExistsError(f"원래 위치에 이미 파일이 있습니다: {original}")
    original.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(stored), str(original))

    updated = QuarantineRecord(**{**asdict(record), "restored_at": stamp})
    records.append(updated)
    _write_records(records)
    return updated


def empty_quarantine(now: float | None = None) -> list[QuarantineRecord]:
    """격리 항목을 macOS 휴지통으로 옮긴다. hard delete가 아니다."""
    stamp = now if now is not None else time.time()
    TRASH_ROOT.mkdir(parents=True, exist_ok=True)
    records = _read_records()
    emptied: list[QuarantineRecord] = []
    for record in list_quarantine():
        stored = Path(record.stored_path)
        if not stored.exists():
            continue
        target = TRASH_ROOT / stored.name
        suffix = 1
        while target.exists():
            target = TRASH_ROOT / f"{stored.name}.{suffix}"
            suffix += 1
        shutil.move(str(stored), str(target))
        updated = QuarantineRecord(**{**asdict(record), "emptied_at": stamp})
        records.append(updated)
        emptied.append(updated)
    if emptied:
        _write_records(records)
    return emptied
