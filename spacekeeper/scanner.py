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
from .report import format_bytes


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
        ("Library", "Developer", "Xcode", "DerivedData"),
        "xcode_derived_data",
        "Xcode가 빌드하면서 만든 파생 데이터입니다.",
        "정리 후 첫 빌드가 오래 걸리고 인덱스를 다시 만들 수 있습니다.",
        group_child=True,
    ),
    CacheRule(
        ("Library", "Developer", "CoreSimulator", "Devices"),
        "xcode_simulator",
        "Xcode 시뮬레이터 가상 기기 데이터와 런타임 저장소입니다.",
        "시뮬레이터에 설치된 임시 앱과 로컬 데이터가 초기화됩니다.",
        risk="medium",
    ),
    CacheRule(
        ("Library", "Developer", "CoreSimulator", "Caches"),
        "xcode_simulator",
        "Xcode 시뮬레이터 실행 캐시입니다.",
        "필요 시 시뮬레이터 실행 때 자동 재생성됩니다.",
    ),
    CacheRule(
        ("Library", "Developer", "Xcode", "iOS DeviceSupport"),
        "xcode_device_support",
        "연결했던 iOS 기기의 디버깅 기호(Symbol) 파일입니다.",
        "구형 iOS 기기 기호 파일은 정리해도 안전하지만 해당 기기 디버깅 시 재추출됩니다.",
    ),
    CacheRule(
        ("Library", "Developer", "Xcode", "watchOS DeviceSupport"),
        "xcode_device_support",
        "연결했던 watchOS 기기의 디버깅 기호 파일입니다.",
        "해당 기기 연결 디버깅 시 재추출됩니다.",
    ),
    CacheRule(
        ("Library", "Developer", "Xcode", "tvOS DeviceSupport"),
        "xcode_device_support",
        "연결했던 tvOS 기기의 디버깅 기호 파일입니다.",
        "해당 기기 연결 디버깅 시 재추출됩니다.",
    ),
    CacheRule(
        ("Library", "Developer", "Xcode", "Archives"),
        "xcode_archives",
        "Xcode가 앱 배포/아카이브 빌드 시 남긴 아카이브(.xcarchive) 파일입니다.",
        "과거 앱 배포 빌드 기록 및 디버깅 기호가 포함되어 있어 필요 여부를 검토해야 합니다.",
        risk="medium",
    ),
    CacheRule(
        ("Library", "Containers", "com.docker.docker"),
        "docker_data",
        "Docker 데스크탑이 보관 중인 VM 디스크 이미지, 컨테이너 및 빌드 캐시입니다.",
        "Docker 데스크탑을 종료 후 정리해야 하며, 로컬 컨테이너와 빌드 레이어가 지워질 수 있습니다.",
        risk="medium",
    ),
    CacheRule(
        (".docker",),
        "docker_data",
        "Docker CLI 및 런타임 캐시 데이터입니다.",
        "로컬 자격 증명과 빌드 캐시 설정이 초기화될 수 있습니다.",
        risk="medium",
    ),
    CacheRule(
        ("Library", "Caches", "Homebrew"),
        "homebrew_cache",
        "Homebrew 패키지 설치 및 업데이트 시 다운로드된 병목 캐시 파일입니다.",
        "정리 후 필요 시 다시 인터넷에서 다운로드합니다.",
    ),
    CacheRule(
        ("Library", "Caches", "CocoaPods"),
        "cocoapods_cache",
        "CocoaPods가 다운로드 및 인덱싱한 팟캐시입니다.",
        "pod install 시 필요 시 다시 다운로드됩니다.",
    ),
    CacheRule(
        ("Library", "Caches", "pip"),
        "pip_cache",
        "pip 패키지 설치 다운로드 캐시입니다.",
        "다음 pip install 시 인터넷에서 다시 다운로드합니다.",
    ),
    CacheRule(
        (".cache", "pip"),
        "pip_cache",
        "pip 패키지 설치 다운로드 캐시입니다.",
        "다음 pip install 시 인터넷에서 다시 다운로드합니다.",
    ),
    CacheRule(
        ("Library", "Caches", "go-build"),
        "go_cache",
        "Go 컴파일러가 다시 생성할 수 있는 빌드 캐시입니다.",
        "첫 go build가 느려질 수 있습니다.",
    ),
    CacheRule(
        (".m2", "repository"),
        "maven_cache",
        "Maven/Gradle이 다운로드한 Java 라이브러리 의존성 캐시입니다.",
        "다음 빌드 시 필요한 의존성을 다시 인터넷에서 다운로드합니다.",
        risk="medium",
    ),
    CacheRule(
        (".android", "avd"),
        "android_emulator",
        "Android Studio가 생성한 가상 기기(AVD) 이미지 데이터입니다.",
        "해당 가상 디바이스 및 내부 저장 데이터가 초기화되므로 확인이 필요합니다.",
        risk="medium",
    ),
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
        "앱과 개발 도구가 다시 만들 수 있는 데이터를 담아 두는 캐시입니다.",
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


def build_space_tree(
    target_path: Path,
    *,
    max_depth: int = 3,
    max_children: int = 25,
) -> dict[str, object]:
    """target_path 하위의 용량 구조 트리를 비주얼 트리맵용으로 집계한다."""
    resolved = target_path.resolve()
    if not resolved.exists() or resolved.is_symlink():
        raise FileNotFoundError(f"존재하지 않거나 접근할 수 없는 경로입니다: {resolved}")

    def _node(current: Path, depth: int) -> dict[str, object]:
        # 클라우드 컨테이너로 내려가면 오프라인 파일을 받으려다 폴더마다
        # 수십 초씩 멈춘다. 존재만 알리고 측정은 건너뛴다.
        if _is_cloud_container(current):
            return {
                "name": current.name,
                "path": str(current),
                "kind": "cloud",
                "allocated_bytes": 0,
                "allocated_human": format_bytes(0),
                "file_count": 0,
                "children": [],
                "skipped": "cloud",
            }
        if current.is_file():
            try:
                stat = current.stat(follow_symlinks=False)
                blocks = getattr(stat, "st_blocks", None)
                bytes_count = blocks * 512 if blocks is not None else stat.st_size
            except OSError:
                bytes_count = 0
            return {
                "name": current.name,
                "path": str(current),
                "kind": "file",
                "allocated_bytes": bytes_count,
                "allocated_human": format_bytes(bytes_count),
                "file_count": 1,
                "children": [],
            }

        children_nodes: list[dict[str, object]] = []
        total_bytes = 0
        total_files = 0

        try:
            entries = list(os.scandir(current))
        except (PermissionError, OSError):
            entries = []

        for entry in entries:
            child_path = Path(entry.path)
            if entry.is_symlink():
                continue
            if depth < max_depth and entry.is_dir(follow_symlinks=False):
                child_tree = _node(child_path, depth + 1)
                children_nodes.append(child_tree)
                total_bytes += int(child_tree["allocated_bytes"])
                total_files += int(child_tree["file_count"])
            else:
                try:
                    stat = entry.stat(follow_symlinks=False)
                    blocks = getattr(stat, "st_blocks", None)
                    b = blocks * 512 if blocks is not None else stat.st_size
                except OSError:
                    b = 0
                total_bytes += b
                total_files += 1
                if not entry.is_dir(follow_symlinks=False):
                    children_nodes.append(
                        {
                            "name": child_path.name,
                            "path": str(child_path),
                            "kind": "file",
                            "allocated_bytes": b,
                            "allocated_human": format_bytes(b),
                            "file_count": 1,
                            "children": [],
                        }
                    )

        children_nodes.sort(key=lambda item: int(item["allocated_bytes"]), reverse=True)
        top_children = children_nodes[:max_children]
        other_children = children_nodes[max_children:]
        if other_children:
            other_bytes = sum(int(item["allocated_bytes"]) for item in other_children)
            other_files = sum(int(item["file_count"]) for item in other_children)
            top_children.append(
                {
                    "name": f"기타 항목 ({len(other_children)}개)",
                    "path": str(current),
                    "kind": "other",
                    "allocated_bytes": other_bytes,
                    "allocated_human": format_bytes(other_bytes),
                    "file_count": other_files,
                    "children": [],
                }
            )

        return {
            "name": current.name or str(current),
            "path": str(current),
            "kind": "dir",
            "allocated_bytes": total_bytes,
            "allocated_human": format_bytes(total_bytes),
            "file_count": total_files,
            "children": top_children,
        }

    return _node(resolved, depth=1)


# ---------- Large file finder ----------

LARGE_FILE_KINDS: dict[str, set[str]] = {
    "video": {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm", ".m4v", ".ts"},
    "image": {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".psd", ".raw", ".heic", ".heif"},
    "archive": {".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar", ".zst", ".tgz"},
    "disk_image": {".dmg", ".iso", ".img", ".sparseimage", ".sparsebundle"},
    "document": {".pdf", ".docx", ".xlsx", ".pptx", ".pages", ".numbers", ".keynote"},
    "code": {".o", ".a", ".dylib", ".so", ".wasm", ".class", ".jar", ".war"},
}

_SUFFIX_TO_KIND: dict[str, str] = {}
for _kind, _suffixes in LARGE_FILE_KINDS.items():
    for _s in _suffixes:
        _SUFFIX_TO_KIND[_s] = _kind

KIND_ICONS: dict[str, str] = {
    "video": "🎬",
    "image": "🖼️",
    "archive": "📦",
    "disk_image": "💽",
    "document": "📄",
    "code": "⚙️",
    "other": "📁",
}


def find_large_files(
    root: Path,
    *,
    min_bytes: int = 50 * 1024 * 1024,
    limit: int = 100,
) -> dict[str, object]:
    """root 하위에서 min_bytes 이상의 대용량 파일을 찾아 크기순 상위 limit개 반환."""
    resolved = root.expanduser().resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"디렉토리가 아닙니다: {resolved}")

    results: list[dict[str, object]] = []

    def _walk(directory: Path) -> None:
        # 클라우드 컨테이너는 오프라인 파일을 내려받으려다 멈추거나 타임아웃한다.
        # 일반 스캔과 같은 규칙으로 건너뛴다.
        if _is_cloud_container(directory):
            return
        try:
            entries = os.scandir(directory)
        except OSError:
            return
        with entries:
            while True:
                # 순회 도중에도 OSError(네트워크 볼륨 타임아웃 등)가 날 수 있으므로
                # 해당 폴더만 포기하고 나머지 분석은 계속한다.
                try:
                    entry = next(entries, None)
                except OSError:
                    return
                if entry is None:
                    break
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        _walk(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    stat = entry.stat(follow_symlinks=False)
                    blocks = getattr(stat, "st_blocks", None)
                    allocated = blocks * 512 if blocks is not None else stat.st_size
                except OSError:
                    continue
                if allocated >= min_bytes:
                    suffix = Path(entry.name).suffix.lower()
                    kind = _SUFFIX_TO_KIND.get(suffix, "other")
                    results.append(
                        {
                            "name": entry.name,
                            "path": entry.path,
                            "kind": kind,
                            "kind_icon": KIND_ICONS.get(kind, "📁"),
                            "allocated_bytes": allocated,
                            "allocated_human": format_bytes(allocated),
                            "modified_at": stat.st_mtime,
                        }
                    )

    _walk(resolved)
    results.sort(key=lambda item: item["allocated_bytes"], reverse=True)  # type: ignore[arg-type]
    top = results[:limit]
    total_bytes = sum(int(item["allocated_bytes"]) for item in top)

    return {
        "path": str(resolved),
        "min_bytes": min_bytes,
        "min_human": format_bytes(min_bytes),
        "files": top,
        "count": len(top),
        "total_found": len(results),
        "total_bytes": total_bytes,
        "total_human": format_bytes(total_bytes),
    }
