"""Application icon extraction.

macOS .app 번들에서 아이콘(.icns)을 추출하여 PNG로 변환·캐싱합니다.
`sips` CLI를 사용하므로 macOS에서만 동작합니다.
"""

from __future__ import annotations

import hashlib
import plistlib
import subprocess
from pathlib import Path

ICON_CACHE_DIR = Path.home() / ".spacekeeper" / "icon_cache"


def _read_plist_icon_name(app_path: Path) -> str | None:
    """Info.plist에서 CFBundleIconFile 값을 읽어 반환합니다."""
    info = app_path / "Contents" / "Info.plist"
    try:
        with info.open("rb") as handle:
            data = plistlib.load(handle)
    except (OSError, ValueError):
        return None
    icon_name = data.get("CFBundleIconFile")
    if icon_name is None:
        return None
    icon_name = str(icon_name)
    if not icon_name:
        return None
    if not Path(icon_name).suffix:
        icon_name += ".icns"
    return icon_name


def _cache_key(app_path: Path) -> str:
    """앱 경로로부터 안전한 캐시 파일명을 생성합니다."""
    md5_hex = hashlib.md5(str(app_path).encode()).hexdigest()
    return f"{md5_hex}.png"


def extract_app_icon(app_path: Path | str, size: int = 64) -> Path | None:
    """앱 번들의 아이콘을 PNG로 변환하여 캐시 경로를 반환합니다."""
    app_path = Path(app_path).resolve()
    cache_path = ICON_CACHE_DIR / _cache_key(app_path)

    if cache_path.exists():
        return cache_path

    icon_name = _read_plist_icon_name(app_path)
    if icon_name is None:
        return None

    icns_path = app_path / "Contents" / "Resources" / icon_name
    if not icns_path.is_file():
        return None

    ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            "sips",
            "-s", "format", "png",
            "-z", str(size), str(size),
            str(icns_path),
            "--out", str(cache_path),
        ],
        capture_output=True,
        timeout=5,
        check=False,
    )

    if result.returncode == 0 and cache_path.exists():
        return cache_path
    return None


def get_icon_bytes(app_path: Path | str, size: int = 64) -> bytes | None:
    """앱 아이콘 PNG 바이트를 반환합니다."""
    icon_path = extract_app_icon(app_path, size)
    if icon_path is None:
        return None
    try:
        return icon_path.read_bytes()
    except OSError:
        return None
