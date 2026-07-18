from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ScanOptions:
    roots: tuple[Path, ...]
    large_bytes: int = 500 * 1024 * 1024
    old_days: int = 180
    top: int = 20
    find_duplicates: bool = False
    duplicate_min_bytes: int = 10 * 1024 * 1024
    include_cloud_storage: bool = False
    now: float | None = None


@dataclass
class FileCandidate:
    path: str
    size: int
    logical_size: int
    modified_at: float
    category: str
    reasons: list[str]
    caution: str
    risk: str


@dataclass
class CacheCandidate:
    path: str
    size: int
    logical_size: int
    file_count: int
    category: str
    reason: str
    caution: str
    risk: str = "low"


@dataclass
class DuplicateGroup:
    logical_size_each: int
    reclaimable_bytes: int
    paths: list[str]
    digest: str


@dataclass
class ScanResult:
    roots: list[str]
    started_at: float
    finished_at: float
    scanned_files: int
    scanned_bytes: int
    scanned_logical_bytes: int
    volume_total_bytes: int
    volume_used_bytes: int
    volume_free_bytes: int
    skipped_symlinks: int
    skipped_cloud_dirs: int
    permission_denied: int
    file_candidate_count: int
    cache_candidate_count: int
    duplicate_group_count: int
    review_candidate_bytes: int
    candidate_bytes_by_risk: dict[str, int]
    duplicate_reclaimable_bytes: int
    errors: list[str] = field(default_factory=list)
    file_candidates: list[FileCandidate] = field(default_factory=list)
    cache_candidates: list[CacheCandidate] = field(default_factory=list)
    duplicate_groups: list[DuplicateGroup] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["safety"] = {
            "read_only": True,
            "followed_symlinks": False,
            "network_used": False,
        }
        return payload
