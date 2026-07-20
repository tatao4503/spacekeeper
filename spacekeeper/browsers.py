"""브라우저 및 메일 캐시 스캔.

Safari, Chrome, Firefox, Edge, Arc 등 주요 브라우저와 macOS 기본 메일
앱이 남기는 캐시를 찾아 용량을 측정합니다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .report import format_bytes


# ── 브라우저 캐시 경로 정의 ──────────────────────────────────────────

BROWSER_CACHE_PATHS: list[dict[str, str]] = [
    # Safari
    {
        "browser": "Safari",
        "category": "브라우저 캐시",
        "subpath": "Library/Caches/com.apple.Safari",
    },
    # Chrome
    {
        "browser": "Chrome",
        "category": "브라우저 캐시",
        "subpath": "Library/Application Support/Google/Chrome/Default/Cache",
    },
    {
        "browser": "Chrome",
        "category": "Service Worker 캐시",
        "subpath": "Library/Application Support/Google/Chrome/Default/Service Worker/CacheStorage",
    },
    # Firefox — Profiles 아래 모든 프로필의 cache2
    {
        "browser": "Firefox",
        "category": "브라우저 캐시",
        "subpath": "Library/Caches/Firefox/Profiles",
    },
    # Edge
    {
        "browser": "Edge",
        "category": "브라우저 캐시",
        "subpath": "Library/Application Support/Microsoft Edge/Default/Cache",
    },
    # Arc
    {
        "browser": "Arc",
        "category": "브라우저 캐시",
        "subpath": "Library/Application Support/Arc/User Data/Default/Cache",
    },
]

# ── 메일 캐시 경로 정의 ──────────────────────────────────────────────

# 주의: 실제 메일 저장소(~/Library/Mail)는 캐시가 아니므로 절대 포함하지 않는다.
# 재생성 가능한 컨테이너 캐시만 대상으로 한다.
MAIL_CACHE_PATHS: list[dict[str, str]] = [
    {
        "browser": "Apple Mail",
        "category": "메일 캐시",
        "subpath": "Library/Containers/com.apple.mail/Data/Library/Caches",
    },
]


# ── 내부 유틸 ────────────────────────────────────────────────────────

def _dir_stats(path: Path) -> tuple[int, int]:
    """경로의 할당 바이트 합계와 파일 수를 반환.

    ``os.scandir`` 을 재귀적으로 순회하며, ``st_blocks * 512`` 로 macOS
    할당 블록 크기를 측정합니다. ``PermissionError`` 는 무시합니다.
    """
    total_bytes = 0
    file_count = 0

    def _walk(p: Path) -> None:
        nonlocal total_bytes, file_count
        try:
            with os.scandir(p) as it:
                for entry in it:
                    if entry.is_symlink():
                        continue
                    if entry.is_file(follow_symlinks=False):
                        try:
                            stat = entry.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        blocks = getattr(stat, "st_blocks", None)
                        total_bytes += blocks * 512 if blocks is not None else stat.st_size
                        file_count += 1
                    elif entry.is_dir(follow_symlinks=False):
                        _walk(Path(entry.path))
        except PermissionError:
            pass

    _walk(path)
    return total_bytes, file_count


def _resolve_firefox_cache2(profiles_dir: Path) -> list[Path]:
    """Firefox Profiles 디렉토리 아래 모든 cache2 폴더를 반환."""
    results: list[Path] = []
    if not profiles_dir.is_dir():
        return results
    try:
        for entry in profiles_dir.iterdir():
            cache2 = entry / "cache2"
            if cache2.is_dir():
                results.append(cache2)
    except OSError:
        pass
    return results


# ── 공개 API ─────────────────────────────────────────────────────────

def scan_browser_caches(home: Path | None = None) -> dict[str, Any]:
    """브라우저·메일 캐시를 스캔하여 결과를 dict 로 반환.

    Parameters
    ----------
    home:
        홈 디렉토리 경로. ``None`` 이면 ``Path.home()`` 을 사용합니다.
        테스트 시 임시 디렉토리를 넘길 수 있습니다.

    Returns
    -------
    dict
        ``browsers``, ``mail``, ``total_bytes``, ``total_human`` 키를 가집니다.
    """
    if home is None:
        home = Path.home()

    grand_total = 0
    browsers: list[dict[str, Any]] = []
    mail: list[dict[str, Any]] = []

    # ── 브라우저 캐시 ──
    for entry in BROWSER_CACHE_PATHS:
        full = home / entry["subpath"]

        # Firefox는 Profiles 하위의 cache2 를 각각 스캔
        if entry["browser"] == "Firefox":
            targets = _resolve_firefox_cache2(full)
        else:
            targets = [full] if full.is_dir() else []

        for target in targets:
            allocated, count = _dir_stats(target)
            grand_total += allocated
            browsers.append({
                "browser": entry["browser"],
                "category": entry["category"],
                "path": str(target),
                "allocated_bytes": allocated,
                "allocated_human": format_bytes(allocated),
                "file_count": count,
                "risk": "low",
            })

    # ── 메일 캐시 ──
    for entry in MAIL_CACHE_PATHS:
        full = home / entry["subpath"]
        if not full.is_dir():
            continue
        allocated, count = _dir_stats(full)
        grand_total += allocated
        mail.append({
            "browser": entry["browser"],
            "category": entry["category"],
            "path": str(full),
            "allocated_bytes": allocated,
            "allocated_human": format_bytes(allocated),
            "file_count": count,
            "risk": "low",
        })

    return {
        "browsers": browsers,
        "mail": mail,
        "total_bytes": grand_total,
        "total_human": format_bytes(grand_total),
    }
