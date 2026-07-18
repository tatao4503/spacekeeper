from __future__ import annotations

import hashlib
import os
import shutil
import time
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from threading import Event
from typing import Callable

from .models import (
    CacheCandidate,
    DuplicateGroup,
    FileCandidate,
    ScanOptions,
    ScanResult,
)


ARCHIVE_SUFFIXES = {
    ".7z",
    ".bz2",
    ".dmg",
    ".gz",
    ".iso",
    ".pkg",
    ".rar",
    ".tar",
    ".tgz",
    ".xz",
    ".zip",
}

IGNORED_METADATA_NAMES = {".DS_Store", ".localized"}
DEFAULT_EXCLUDED_ROOTS = (
    Path.home() / ".spacekeeper",
    Path.home() / ".Trash",
)
AUTOMATIC_EXCLUDED_DIR_NAMES = {".Trashes"}
ProgressCallback = Callable[[dict[str, object]], None]


class ScanCancelled(Exception):
    """Raised when a caller requests cooperative scan cancellation."""


@dataclass(frozen=True)
class CacheRule:
    parts: tuple[str, ...]
    category: str
    reason: str
    caution: str
    group_child: bool = False
    risk: str = "low"


CACHE_RULES = (
    CacheRule(
        ("Library", "Application Support", "Caches"),
        "app_cache",
        "앱 업데이트나 실행 과정에서 만든 캐시입니다.",
        "관련 앱을 종료한 뒤 정리해야 하며, 일부 데이터가 다시 내려받아질 수 있습니다.",
        group_child=True,
    ),
    CacheRule(
        (
            "Library",
            "Application Support",
            "Google",
            "GoogleUpdater",
            "crx_cache",
        ),
        "app_cache",
        "Google Updater가 업데이트 패키지를 위해 보관한 캐시입니다.",
        "Chrome과 Google 업데이트가 진행 중이지 않을 때만 정리를 검토해야 합니다.",
    ),
    CacheRule(
        ("Library", "Caches"),
        "app_cache",
        "앱이 다시 만들거나 내려받을 수 있는 캐시입니다.",
        "앱을 종료한 뒤 정리해야 하며, 다음 실행이 느려질 수 있습니다.",
        group_child=True,
    ),
    CacheRule(
        ("Library", "Developer", "Xcode", "DerivedData"),
        "xcode_derived_data",
        "Xcode가 빌드하면서 만든 파생 데이터입니다.",
        "정리 후 첫 빌드가 오래 걸리고 인덱스를 다시 만들 수 있습니다.",
        group_child=True,
    ),
    CacheRule(
        (".npm", "_cacache"),
        "package_cache",
        "npm이 다시 내려받을 수 있는 패키지 캐시입니다.",
        "오프라인 설치에 필요할 수 있으며 재다운로드 시간이 생깁니다.",
    ),
    CacheRule(
        (".gradle", "caches"),
        "package_cache",
        "Gradle이 다시 생성하거나 내려받을 수 있는 캐시입니다.",
        "다음 빌드가 느려지고 의존성을 다시 내려받을 수 있습니다.",
    ),
    CacheRule(
        (".ollama", "models", "blobs"),
        "local_ai_model",
        "Ollama가 로컬 실행을 위해 내려받은 AI 모델 데이터입니다.",
        "삭제하면 해당 모델을 쓸 수 없으며 필요할 때 수 GB를 다시 받아야 합니다.",
        risk="medium",
    ),
    CacheRule(
        (".cache",),
        "user_cache",
        "도구나 앱이 사용자 캐시 규약에 따라 저장한 데이터입니다.",
        "필요할 때 다시 생성되지만 첫 실행이나 재다운로드에 시간이 걸릴 수 있습니다.",
        group_child=True,
        risk="medium",
    ),
    CacheRule(
        ("node_modules",),
        "project_dependency",
        "패키지 명세로 다시 설치할 수 있는 프로젝트 의존성입니다.",
        "package.json과 lock 파일이 온전한지 먼저 확인해야 합니다.",
    ),
    CacheRule(
        (".pnpm-store",),
        "package_cache",
        "pnpm이 패키지를 재사용하기 위해 보관한 저장소입니다.",
        "다음 설치에서 패키지를 다시 내려받을 수 있습니다.",
    ),
    CacheRule(
        (".next",),
        "build_cache",
        "Next.js가 다시 생성할 수 있는 빌드 결과와 캐시입니다.",
        "배포 중인 로컬 서버를 먼저 종료해야 합니다.",
    ),
    CacheRule(
        (".turbo",),
        "build_cache",
        "Turbo가 다시 생성할 수 있는 빌드 캐시입니다.",
        "다음 빌드가 느려질 수 있습니다.",
    ),
    CacheRule(
        (".pytest_cache",),
        "test_cache",
        "pytest가 다시 생성할 수 있는 테스트 캐시입니다.",
        "테스트 실행 기록 일부가 초기화됩니다.",
    ),
    CacheRule(
        (".mypy_cache",),
        "tool_cache",
        "mypy가 다시 생성할 수 있는 타입 검사 캐시입니다.",
        "다음 타입 검사가 느려질 수 있습니다.",
    ),
    CacheRule(
        (".ruff_cache",),
        "tool_cache",
        "Ruff가 다시 생성할 수 있는 검사 캐시입니다.",
        "다음 검사가 느려질 수 있습니다.",
    ),
    CacheRule(
        ("__pycache__",),
        "python_cache",
        "Python이 다시 생성할 수 있는 바이트코드 캐시입니다.",
        "다음 Python 실행 때 다시 만들어집니다.",
    ),
)

RUST_TARGET_RULE = CacheRule(
    ("target",),
    "rust_build",
    "Cargo가 다시 생성할 수 있는 Rust 빌드 결과와 증분 캐시입니다.",
    "실행 중인 빌드를 멈추고 Cargo.toml과 소스가 온전한지 확인해야 합니다.",
)


@dataclass
class _CacheAggregate:
    rule: CacheRule
    size: int = 0
    logical_size: int = 0
    file_count: int = 0


def _find_sequence(parts: tuple[str, ...], needle: tuple[str, ...]) -> int | None:
    width = len(needle)
    for index in range(len(parts) - width + 1):
        if parts[index : index + width] == needle:
            return index
    return None


@lru_cache(maxsize=4096)
def _is_rust_target(path: Path) -> bool:
    return (path.parent / "Cargo.toml").is_file()


def _cache_bucket(path: Path) -> tuple[Path, CacheRule] | None:
    parts = path.parts
    for index, part in enumerate(parts[:-1]):
        if part != "target":
            continue
        target = Path(*parts[: index + 1])
        if _is_rust_target(target):
            return target, RUST_TARGET_RULE
    for rule in CACHE_RULES:
        index = _find_sequence(parts, rule.parts)
        if index is None:
            continue
        end = index + len(rule.parts)
        # The matching component must be a directory, not the file name itself.
        if end >= len(parts):
            continue
        if rule.group_child and end < len(parts) - 1:
            end += 1
        return Path(*parts[:end]), rule
    return None


def _is_download(path: Path) -> bool:
    return "Downloads" in path.parts


def _file_candidate(
    path: Path,
    size: int,
    logical_size: int,
    modified_at: float,
    options: ScanOptions,
    now: float,
) -> FileCandidate | None:
    if size == 0 or path.name in IGNORED_METADATA_NAMES:
        return None
    age_days = max(0, int((now - modified_at) // 86400))
    reasons: list[str] = []
    category = "large_file"
    risk = "high"
    caution = "내용과 백업 여부를 직접 확인하기 전에는 정리하면 안 됩니다."

    if size >= options.large_bytes:
        reasons.append(f"큰 파일 기준을 넘었습니다 ({size} bytes).")

    if _is_download(path) and age_days >= options.old_days:
        reasons.append(f"다운로드 폴더에서 {age_days}일 동안 수정되지 않았습니다.")
        category = "old_download"
        risk = "medium"
        caution = "다시 구하기 어렵거나 아직 필요한 파일인지 확인해야 합니다."

    if path.suffix.lower() in ARCHIVE_SUFFIXES and size >= options.large_bytes:
        reasons.append("설치 파일 또는 압축 파일이라 재다운로드 가능성을 검토할 수 있습니다.")
        category = "installer_or_archive"
        risk = "medium"
        caution = "원본이 유일한 백업이 아닌지, 다시 받을 수 있는지 확인해야 합니다."

    if not reasons:
        return None
    return FileCandidate(
        path=str(path),
        size=size,
        logical_size=logical_size,
        modified_at=modified_at,
        category=category,
        reasons=reasons,
        caution=caution,
        risk=risk,
    )


def _normalize_roots(roots: tuple[Path, ...]) -> list[Path]:
    resolved: list[Path] = []
    for raw_root in roots:
        root = raw_root.expanduser().resolve(strict=True)
        if not root.is_dir():
            raise NotADirectoryError(f"스캔 경로가 폴더가 아닙니다: {root}")
        if any(root == existing or root.is_relative_to(existing) for existing in resolved):
            continue
        resolved = [existing for existing in resolved if not existing.is_relative_to(root)]
        resolved.append(root)
    return resolved


def _normalize_excluded_paths(
    paths: tuple[Path, ...], roots: list[Path]
) -> list[Path]:
    resolved: list[Path] = []
    for raw_path in (*DEFAULT_EXCLUDED_ROOTS, *paths):
        path = raw_path.expanduser().resolve(strict=False)
        if any(
            path == existing or path.is_relative_to(existing)
            for existing in resolved
        ):
            continue
        resolved = [
            existing for existing in resolved if not existing.is_relative_to(path)
        ]
        resolved.append(path)
    return [
        path
        for path in resolved
        if any(
            path == root
            or path.is_relative_to(root)
            or root.is_relative_to(path)
            for root in roots
        )
    ]


def _is_excluded(path: Path, excluded_paths: list[Path]) -> bool:
    return any(
        path == excluded or path.is_relative_to(excluded)
        for excluded in excluded_paths
    )


def _is_automatic_excluded_directory(path: Path) -> bool:
    return any(part in AUTOMATIC_EXCLUDED_DIR_NAMES for part in path.parts)


def _raise_if_cancelled(cancel_event: Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ScanCancelled("사용자가 분석을 중단했습니다.")


def _hash_file(path: Path, cancel_event: Event | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            _raise_if_cancelled(cancel_event)
            digest.update(chunk)
    return digest.hexdigest()


def _find_duplicates(
    buckets: dict[int, list[tuple[Path, int]]],
    errors: list[str],
    cancel_event: Event | None = None,
    progress_callback: Callable[[Path, int, int], None] | None = None,
) -> list[DuplicateGroup]:
    groups: list[DuplicateGroup] = []
    hash_total = sum(len(entries) for entries in buckets.values() if len(entries) > 1)
    hashed_files = 0
    for logical_size, entries in buckets.items():
        _raise_if_cancelled(cancel_event)
        if len(entries) < 2:
            continue
        by_digest: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for path, allocated_size in entries:
            _raise_if_cancelled(cancel_event)
            try:
                by_digest[_hash_file(path, cancel_event)].append(
                    (str(path), allocated_size)
                )
            except (OSError, PermissionError) as exc:
                if len(errors) < 20:
                    errors.append(f"중복 검사 건너뜀: {path} ({exc})")
            hashed_files += 1
            if progress_callback is not None:
                progress_callback(path, hashed_files, hash_total)
        for digest, matches in by_digest.items():
            if len(matches) < 2:
                continue
            matching_paths = sorted(path for path, _ in matches)
            allocated_sizes = [allocated for _, allocated in matches]
            groups.append(
                DuplicateGroup(
                    logical_size_each=logical_size,
                    reclaimable_bytes=sum(allocated_sizes) - min(allocated_sizes),
                    paths=matching_paths,
                    digest=digest,
                )
            )
    return sorted(groups, key=lambda item: item.reclaimable_bytes, reverse=True)


def _allocated_size(stat: os.stat_result) -> int:
    blocks = getattr(stat, "st_blocks", None)
    return blocks * 512 if blocks is not None else stat.st_size


def _is_cloud_container(path: Path) -> bool:
    return path.parts[-2:] in {
        ("Library", "CloudStorage"),
        ("Library", "Mobile Documents"),
    }


def scan(
    options: ScanOptions,
    *,
    progress_callback: ProgressCallback | None = None,
    cancel_event: Event | None = None,
) -> ScanResult:
    started_at = time.time()
    now = options.now if options.now is not None else started_at
    roots = _normalize_roots(options.roots)
    excluded_paths = _normalize_excluded_paths(options.excluded_paths, roots)
    volume_usage = shutil.disk_usage(roots[0])
    scanned_files = 0
    scanned_bytes = 0
    scanned_logical_bytes = 0
    skipped_symlinks = 0
    skipped_cloud_dirs = 0
    skipped_excluded_paths = 0
    permission_denied = 0
    errors: list[str] = []
    file_candidates: list[FileCandidate] = []
    cache_aggregates: dict[Path, _CacheAggregate] = {}
    duplicate_buckets: dict[int, list[tuple[Path, int]]] = defaultdict(list)
    last_progress_at = 0.0

    def emit_progress(
        phase: str,
        current_path: Path,
        *,
        force: bool = False,
        duplicate_files_done: int = 0,
        duplicate_files_total: int = 0,
    ) -> None:
        nonlocal last_progress_at
        if progress_callback is None:
            return
        progress_now = time.monotonic()
        if not force and progress_now - last_progress_at < 0.1:
            return
        last_progress_at = progress_now
        progress_callback(
            {
                "phase": phase,
                "current_path": str(current_path),
                "scanned_files": scanned_files,
                "scanned_bytes": scanned_bytes,
                "candidates_found": len(file_candidates) + len(cache_aggregates),
                "directories_pending": len(stack),
                "duplicate_files_done": duplicate_files_done,
                "duplicate_files_total": duplicate_files_total,
            }
        )

    stack = list(reversed(roots))
    emit_progress("scanning", roots[0], force=True)
    while stack:
        _raise_if_cancelled(cancel_event)
        directory = stack.pop()
        emit_progress("scanning", directory)
        if (
            _is_excluded(directory, excluded_paths)
            or _is_automatic_excluded_directory(directory)
        ):
            skipped_excluded_paths += 1
            continue
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    _raise_if_cancelled(cancel_event)
                    path = Path(entry.path)
                    try:
                        if entry.is_symlink():
                            skipped_symlinks += 1
                            continue
                        if _is_excluded(path, excluded_paths):
                            skipped_excluded_paths += 1
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if _is_automatic_excluded_directory(path):
                                skipped_excluded_paths += 1
                                continue
                            if (
                                not options.include_cloud_storage
                                and _is_cloud_container(path)
                            ):
                                skipped_cloud_dirs += 1
                                continue
                            stack.append(path)
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        stat = entry.stat(follow_symlinks=False)
                    except PermissionError:
                        permission_denied += 1
                        continue
                    except OSError as exc:
                        if len(errors) < 20:
                            errors.append(f"파일 건너뜀: {path} ({exc})")
                        continue

                    scanned_files += 1
                    allocated_size = _allocated_size(stat)
                    scanned_bytes += allocated_size
                    scanned_logical_bytes += stat.st_size
                    cache_match = _cache_bucket(path)
                    if cache_match is not None:
                        bucket_path, rule = cache_match
                        aggregate = cache_aggregates.setdefault(
                            bucket_path, _CacheAggregate(rule=rule)
                        )
                        aggregate.size += allocated_size
                        aggregate.logical_size += stat.st_size
                        aggregate.file_count += 1
                    else:
                        candidate = _file_candidate(
                            path,
                            allocated_size,
                            stat.st_size,
                            stat.st_mtime,
                            options,
                            now,
                        )
                        if candidate is not None:
                            file_candidates.append(candidate)

                    if (
                        options.find_duplicates
                        and stat.st_size >= options.duplicate_min_bytes
                    ):
                        duplicate_buckets[stat.st_size].append(
                            (path, allocated_size)
                        )
                    emit_progress("scanning", path)
        except PermissionError:
            permission_denied += 1
        except OSError as exc:
            if len(errors) < 20:
                errors.append(f"폴더 건너뜀: {directory} ({exc})")

    cache_candidates = [
        CacheCandidate(
            path=str(path),
            size=aggregate.size,
            logical_size=aggregate.logical_size,
            file_count=aggregate.file_count,
            category=aggregate.rule.category,
            reason=aggregate.rule.reason,
            caution=aggregate.rule.caution,
            risk=aggregate.rule.risk,
        )
        for path, aggregate in cache_aggregates.items()
        if aggregate.size > 0
    ]
    file_candidates.sort(key=lambda item: item.size, reverse=True)
    cache_candidates.sort(key=lambda item: item.size, reverse=True)
    _raise_if_cancelled(cancel_event)
    duplicate_groups: list[DuplicateGroup] = []
    if options.find_duplicates:
        emit_progress("duplicates", roots[0], force=True)

        def emit_duplicate_progress(path: Path, done: int, total: int) -> None:
            emit_progress(
                "duplicates",
                path,
                force=True,
                duplicate_files_done=done,
                duplicate_files_total=total,
            )

        duplicate_groups = _find_duplicates(
            duplicate_buckets,
            errors,
            cancel_event=cancel_event,
            progress_callback=emit_duplicate_progress,
        )
    _raise_if_cancelled(cancel_event)
    emit_progress("finalizing", roots[0], force=True)
    review_candidate_bytes = sum(item.size for item in file_candidates) + sum(
        item.size for item in cache_candidates
    )
    candidate_bytes_by_risk = {"low": 0, "medium": 0, "high": 0}
    for candidate in [*file_candidates, *cache_candidates]:
        candidate_bytes_by_risk[candidate.risk] += candidate.size
    duplicate_reclaimable_bytes = sum(
        group.reclaimable_bytes for group in duplicate_groups
    )

    return ScanResult(
        roots=[str(root) for root in roots],
        started_at=started_at,
        finished_at=time.time(),
        scanned_files=scanned_files,
        scanned_bytes=scanned_bytes,
        scanned_logical_bytes=scanned_logical_bytes,
        volume_total_bytes=volume_usage.total,
        volume_used_bytes=volume_usage.used,
        volume_free_bytes=volume_usage.free,
        skipped_symlinks=skipped_symlinks,
        skipped_cloud_dirs=skipped_cloud_dirs,
        skipped_excluded_paths=skipped_excluded_paths,
        permission_denied=permission_denied,
        file_candidate_count=len(file_candidates),
        cache_candidate_count=len(cache_candidates),
        duplicate_group_count=len(duplicate_groups),
        review_candidate_bytes=review_candidate_bytes,
        candidate_bytes_by_risk=candidate_bytes_by_risk,
        duplicate_reclaimable_bytes=duplicate_reclaimable_bytes,
        excluded_paths=[str(path) for path in excluded_paths],
        errors=errors,
        file_candidates=file_candidates[: options.top],
        cache_candidates=cache_candidates[: options.top],
        duplicate_groups=duplicate_groups[: options.top],
    )
