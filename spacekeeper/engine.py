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
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import fcntl


QUARANTINE_ROOT = Path.home() / ".spacekeeper" / "quarantine"
MANIFEST_PATH = QUARANTINE_ROOT / "manifest.jsonl"
JOURNAL_PATH = QUARANTINE_ROOT / "operation.json"
TRASH_ROOT = Path.home() / ".Trash"
_ENGINE_LOCK = threading.RLock()

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


class EngineRecoveryError(Exception):
    """중단된 이동을 안전하게 판별·복구할 수 없을 때 발생."""


class StaleSelectionError(Exception):
    """사용자가 본 격리 항목과 현재 항목이 다를 때 발생."""


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
    instance_id: str | None = None

    @property
    def status(self) -> str:
        if self.emptied_at is not None:
            return "emptied"
        if self.restored_at is not None:
            return "restored"
        return "quarantined"

    @property
    def instance_token(self) -> str:
        if self.instance_id is not None:
            return self.instance_id
        return f"legacy-{self.action_id}-{float(self.quarantined_at).hex()}"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status
        payload["instance_token"] = self.instance_token
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
            data.pop("instance_token", None)
            records.append(QuarantineRecord(**data))
    return records


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _operation_lock():
    """스레드와 복수 Spacekeeper 프로세스의 이동을 직렬화한다."""
    with _ENGINE_LOCK:
        QUARANTINE_ROOT.mkdir(parents=True, exist_ok=True)
        lock_path = QUARANTINE_ROOT / ".engine.lock"
        with lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    _fsync_directory(path.parent)


def _write_records(records: list[QuarantineRecord]) -> None:
    QUARANTINE_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_PATH.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, MANIFEST_PATH)
    _fsync_directory(MANIFEST_PATH.parent)


def _write_journal(
    operation: str,
    source: Path,
    destination: Path,
    record: QuarantineRecord,
) -> None:
    _write_json_atomic(
        JOURNAL_PATH,
        {
            "version": 1,
            "operation": operation,
            "action_id": record.action_id,
            "source_path": str(source),
            "destination_path": str(destination),
            "record": asdict(record),
        },
    )


def _clear_journal() -> None:
    try:
        JOURNAL_PATH.unlink()
    except FileNotFoundError:
        return
    _fsync_directory(JOURNAL_PATH.parent)


def _read_journal() -> tuple[str, Path, Path, QuarantineRecord] | None:
    if not JOURNAL_PATH.exists():
        return None
    try:
        with JOURNAL_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("journal은 JSON 객체여야 합니다")
        if data.get("version") != 1:
            raise ValueError("지원하지 않는 journal 버전")
        operation = str(data["operation"])
        if operation not in {"quarantine", "restore", "empty"}:
            raise ValueError("알 수 없는 journal 작업")
        record_data = dict(data["record"])
        record_data.pop("status", None)
        record_data.pop("instance_token", None)
        record = QuarantineRecord(**record_data)
        if data.get("action_id") != record.action_id:
            raise ValueError("journal action_id 불일치")
        source = Path(data["source_path"])
        destination = Path(data["destination_path"])
        original = Path(record.original_path)
        stored = Path(record.stored_path)
        valid_paths = (
            operation == "quarantine" and source == original and destination == stored
        ) or (operation == "restore" and source == stored and destination == original)
        if operation == "empty":
            valid_paths = (
                source == stored and destination.parent == TRASH_ROOT
            )
        if not valid_paths:
            raise ValueError("journal 경로와 manifest 기록이 일치하지 않습니다")
        return operation, source, destination, record
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise EngineRecoveryError(
            f"중단된 작업 journal을 읽을 수 없습니다: {exc}"
        ) from exc


def _recover_incomplete_operation() -> None:
    pending = _read_journal()
    if pending is None:
        return

    operation, source, destination, final_record = pending
    try:
        records = _read_records()
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise EngineRecoveryError(
            f"중단된 {operation} 작업의 manifest를 읽을 수 없습니다: {exc}"
        ) from exc

    # manifest가 이미 확정됐다면 journal 제거만 남은 상태다.
    if _latest_by_action(records).get(final_record.action_id) == final_record:
        try:
            _clear_journal()
        except OSError as exc:
            raise EngineRecoveryError(
                f"완료된 {operation} journal을 정리하지 못했습니다: {exc}"
            ) from exc
        return

    source_exists = os.path.lexists(source)
    destination_exists = os.path.lexists(destination)
    if destination_exists and not source_exists:
        records.append(final_record)
        try:
            _write_records(records)
            _clear_journal()
        except OSError as exc:
            raise EngineRecoveryError(
                f"중단된 {operation} 작업을 manifest에 확정하지 못했습니다: {exc}"
            ) from exc
        return
    if source_exists and not destination_exists:
        try:
            _clear_journal()
        except OSError as exc:
            raise EngineRecoveryError(
                f"시작되지 않은 {operation} journal을 정리하지 못했습니다: {exc}"
            ) from exc
        return

    state = "양쪽에 모두 있습니다" if source_exists else "양쪽에 모두 없습니다"
    raise EngineRecoveryError(
        f"중단된 {operation} 작업을 자동 복구할 수 없습니다. "
        f"원본과 대상이 {state}: {source} -> {destination}"
    )


def _commit_move(
    operation: str,
    source: Path,
    destination: Path,
    final_record: QuarantineRecord,
    records: list[QuarantineRecord],
) -> None:
    try:
        _write_journal(operation, source, destination, final_record)
    except OSError as exc:
        raise EngineRecoveryError(
            f"{operation} 이동 전 journal을 기록하지 못했습니다: {exc}"
        ) from exc

    try:
        shutil.move(str(source), str(destination))
    except OSError as exc:
        # shutil.move는 디렉터리를 복사한 뒤 원본을 지우는데, 원본이
        # macOS 보호 폴더(예: ~/Library/Caches)면 내용은 모두 옮겨졌는데도
        # 비어 버린 원본 폴더를 지우지 못해 예외가 날 수 있다. 이때 대상이
        # 존재하고 원본이 비어 있으면 이동 자체는 성공한 것으로 본다.
        recovered = False
        if os.path.lexists(destination) and os.path.isdir(source):
            try:
                source_empty = not os.listdir(source)
            except OSError:
                source_empty = False
            if source_empty:
                try:
                    os.rmdir(source)
                except OSError:
                    pass  # 상위가 보호돼 못 지워도 내용은 이미 격리됨
                recovered = True
        if not recovered:
            if os.path.lexists(source) and not os.path.lexists(destination):
                try:
                    _clear_journal()
                except OSError as cleanup_exc:
                    raise EngineRecoveryError(
                        f"이동 실패 후 journal을 정리하지 못했습니다: {cleanup_exc}"
                    ) from cleanup_exc
                raise
            raise EngineRecoveryError(
                f"{operation} 이동 중 파일 상태가 불명확해졌습니다: {exc}"
            ) from exc

    records.append(final_record)
    try:
        _write_records(records)
        _clear_journal()
    except OSError as exc:
        raise EngineRecoveryError(
            f"{operation} 이동은 되었지만 manifest 확정이 중단됐습니다: {exc}"
        ) from exc


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
    with _operation_lock():
        _recover_incomplete_operation()
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
            if os.path.lexists(destination):
                skipped.append(
                    {"path": raw_path, "reason": "격리함에 같은 이름이 이미 있습니다."}
                )
                continue
            record = QuarantineRecord(
                action_id=action_id,
                original_path=str(path),
                stored_path=str(destination),
                allocated_bytes=allocated,
                kind=kind,
                quarantined_at=stamp,
                instance_id=uuid.uuid4().hex,
            )
            try:
                _commit_move("quarantine", path, destination, record, records)
            except OSError as exc:
                skipped.append({"path": raw_path, "reason": f"이동 실패: {exc}"})
                continue

            moved.append(record)
            active.add(action_id)

        return ReclaimOutcome(moved=moved, skipped=skipped)


def list_quarantine() -> list[QuarantineRecord]:
    """현재 격리 상태(quarantined)인 항목만 최신 기준으로 반환한다."""
    with _operation_lock():
        _recover_incomplete_operation()
        latest = _latest_by_action(_read_records())
        return sorted(
            (r for r in latest.values() if r.status == "quarantined"),
            key=lambda r: r.quarantined_at,
            reverse=True,
        )


def restore(
    action_id: str,
    now: float | None = None,
    instance_token: str | None = None,
) -> QuarantineRecord:
    """격리 항목을 원래 위치로 되돌린다."""
    with _operation_lock():
        _recover_incomplete_operation()
        stamp = now if now is not None else time.time()
        records = _read_records()
        latest = _latest_by_action(records)
        record = latest.get(action_id)
        if record is None or record.status != "quarantined":
            raise KeyError(f"격리 중인 항목이 아닙니다: {action_id}")
        if instance_token is not None and record.instance_token != instance_token:
            raise StaleSelectionError(f"격리 항목이 변경되었습니다: {action_id}")

        stored = Path(record.stored_path)
        original = Path(record.original_path)
        if not os.path.lexists(stored):
            raise FileNotFoundError(f"격리 파일이 없습니다: {stored}")
        if os.path.lexists(original):
            raise FileExistsError(f"원래 위치에 이미 파일이 있습니다: {original}")
        original.parent.mkdir(parents=True, exist_ok=True)

        updated = QuarantineRecord(**{**asdict(record), "restored_at": stamp})
        _commit_move("restore", stored, original, updated, records)
        return updated


def empty_quarantine(
    now: float | None = None,
    selections: dict[str, str] | None = None,
) -> list[QuarantineRecord]:
    """격리 항목을 macOS 휴지통으로 옮긴다. hard delete가 아니다."""
    with _operation_lock():
        _recover_incomplete_operation()
        stamp = now if now is not None else time.time()
        TRASH_ROOT.mkdir(parents=True, exist_ok=True)
        records = _read_records()
        latest = _latest_by_action(records)
        if selections is not None:
            for action_id, instance_token in selections.items():
                selected = latest.get(action_id)
                if (
                    selected is None
                    or selected.status != "quarantined"
                    or selected.instance_token != instance_token
                ):
                    raise StaleSelectionError(
                        f"격리 항목이 변경되었습니다: {action_id}"
                    )
        active = sorted(
            (
                record
                for record in latest.values()
                if record.status == "quarantined"
                and (selections is None or record.action_id in selections)
            ),
            key=lambda record: record.quarantined_at,
            reverse=True,
        )
        emptied: list[QuarantineRecord] = []
        for record in active:
            stored = Path(record.stored_path)
            if not os.path.lexists(stored):
                continue
            target = TRASH_ROOT / stored.name
            suffix = 1
            while target.exists():
                target = TRASH_ROOT / f"{stored.name}.{suffix}"
                suffix += 1
            updated = QuarantineRecord(**{**asdict(record), "emptied_at": stamp})
            _commit_move("empty", stored, target, updated, records)
            emptied.append(updated)
        return emptied
