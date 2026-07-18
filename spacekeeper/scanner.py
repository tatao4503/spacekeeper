from __future__ import annotations

import hashlib
import os
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

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


@dataclass(frozen=True)
class CacheRule:
    parts: tuple[str, ...]
    category: str
    reason: str
    caution: str
    group_child: bool = False


CACHE_RULES = (
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


@dataclass
class _CacheAggregate:
    rule: CacheRule
    size: int = 0
    file_count: int = 0


def _find_sequence(parts: tuple[str, ...], needle: tuple[str, ...]) -> int | None:
    width = len(needle)
    for index in range(len(parts) - width + 1):
        if parts[index : index + width] == needle:
            return index
    return None


def _cache_bucket(path: Path) -> tuple[Path, CacheRule] | None:
    parts = path.parts
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
    path: Path, size: int, modified_at: float, options: ScanOptions, now: float
) -> FileCandidate | None:
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

    if path.suffix.lower() in ARCHIVE_SUFFIXES and (
        age_days >= options.old_days or size >= options.large_bytes
    ):
        reasons.append("설치 파일 또는 압축 파일이라 재다운로드 가능성을 검토할 수 있습니다.")
        category = "installer_or_archive"
        risk = "medium"
        caution = "원본이 유일한 백업이 아닌지, 다시 받을 수 있는지 확인해야 합니다."

    if not reasons:
        return None
    return FileCandidate(
        path=str(path),
        size=size,
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


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _find_duplicates(
    buckets: dict[int, list[Path]], errors: list[str]
) -> list[DuplicateGroup]:
    groups: list[DuplicateGroup] = []
    for size, paths in buckets.items():
        if len(paths) < 2:
            continue
        by_digest: dict[str, list[str]] = defaultdict(list)
        for path in paths:
            try:
                by_digest[_hash_file(path)].append(str(path))
            except (OSError, PermissionError) as exc:
                if len(errors) < 20:
                    errors.append(f"중복 검사 건너뜀: {path} ({exc})")
        for digest, matching_paths in by_digest.items():
            if len(matching_paths) < 2:
                continue
            groups.append(
                DuplicateGroup(
                    size_each=size,
                    reclaimable_bytes=size * (len(matching_paths) - 1),
                    paths=sorted(matching_paths),
                    digest=digest,
                )
            )
    return sorted(groups, key=lambda item: item.reclaimable_bytes, reverse=True)


def scan(options: ScanOptions) -> ScanResult:
    started_at = time.time()
    now = options.now if options.now is not None else started_at
    roots = _normalize_roots(options.roots)
    scanned_files = 0
    scanned_bytes = 0
    skipped_symlinks = 0
    permission_denied = 0
    errors: list[str] = []
    file_candidates: list[FileCandidate] = []
    cache_aggregates: dict[Path, _CacheAggregate] = {}
    duplicate_buckets: dict[int, list[Path]] = defaultdict(list)

    stack = list(reversed(roots))
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    try:
                        if entry.is_symlink():
                            skipped_symlinks += 1
                            continue
                        if entry.is_dir(follow_symlinks=False):
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
                    scanned_bytes += stat.st_size
                    cache_match = _cache_bucket(path)
                    if cache_match is not None:
                        bucket_path, rule = cache_match
                        aggregate = cache_aggregates.setdefault(
                            bucket_path, _CacheAggregate(rule=rule)
                        )
                        aggregate.size += stat.st_size
                        aggregate.file_count += 1
                    else:
                        candidate = _file_candidate(
                            path, stat.st_size, stat.st_mtime, options, now
                        )
                        if candidate is not None:
                            file_candidates.append(candidate)

                    if (
                        options.find_duplicates
                        and stat.st_size >= options.duplicate_min_bytes
                    ):
                        duplicate_buckets[stat.st_size].append(path)
        except PermissionError:
            permission_denied += 1
        except OSError as exc:
            if len(errors) < 20:
                errors.append(f"폴더 건너뜀: {directory} ({exc})")

    cache_candidates = [
        CacheCandidate(
            path=str(path),
            size=aggregate.size,
            file_count=aggregate.file_count,
            category=aggregate.rule.category,
            reason=aggregate.rule.reason,
            caution=aggregate.rule.caution,
        )
        for path, aggregate in cache_aggregates.items()
    ]
    file_candidates.sort(key=lambda item: item.size, reverse=True)
    cache_candidates.sort(key=lambda item: item.size, reverse=True)
    duplicate_groups = (
        _find_duplicates(duplicate_buckets, errors)
        if options.find_duplicates
        else []
    )
    review_candidate_bytes = sum(item.size for item in file_candidates) + sum(
        item.size for item in cache_candidates
    )
    duplicate_reclaimable_bytes = sum(
        group.reclaimable_bytes for group in duplicate_groups
    )

    return ScanResult(
        roots=[str(root) for root in roots],
        started_at=started_at,
        finished_at=time.time(),
        scanned_files=scanned_files,
        scanned_bytes=scanned_bytes,
        skipped_symlinks=skipped_symlinks,
        permission_denied=permission_denied,
        file_candidate_count=len(file_candidates),
        cache_candidate_count=len(cache_candidates),
        duplicate_group_count=len(duplicate_groups),
        review_candidate_bytes=review_candidate_bytes,
        duplicate_reclaimable_bytes=duplicate_reclaimable_bytes,
        errors=errors,
        file_candidates=file_candidates[: options.top],
        cache_candidates=cache_candidates[: options.top],
        duplicate_groups=duplicate_groups[: options.top],
    )
