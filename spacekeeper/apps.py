"""Application uninstaller scan.

설치된 앱과, 그 앱이 `~/Library` 여기저기에 남긴 지원·캐시·설정 파일을 함께
찾습니다. 실제 제거는 engine의 격리(이동)로 처리하므로 되돌릴 수 있습니다.
"""

from __future__ import annotations

import plistlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .engine import _allocated_bytes

from .report import format_bytes

APP_DIRS = (Path("/Applications"), Path.home() / "Applications")

# 앱 잔여물이 흔히 쌓이는 ~/Library 하위 폴더.
_LEFTOVER_DIRS = (
    "Application Support",
    "Caches",
    "Containers",
    "HTTPStorages",
    "Logs",
    "Preferences",
    "Saved Application State",
    "WebKit",
    "Group Containers",
    "LaunchAgents",
    "LaunchDaemons",
    "Developer",
    "Cookies",
    "Application Scripts",
    "Autosave Information",
)

_CATEGORY_MAP = {
    "Caches": "cache",
    "HTTPStorages": "cache",
    "WebKit": "cache",
    "Cookies": "cache",
    "Saved Application State": "state",
    "Autosave Information": "state",
    "Preferences": "preference",
    "Containers": "container",
    "Group Containers": "container",
    "Application Scripts": "container",
    "Logs": "logs",
}


@dataclass(frozen=True)
class LeftoverItem:
    path: str
    allocated_bytes: int
    category: str = "support"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "allocated_bytes": self.allocated_bytes,
            "allocated_human": format_bytes(self.allocated_bytes),
            "category": self.category,
        }


@dataclass(frozen=True)
class InstalledApp:
    name: str
    path: str
    bundle_id: str
    app_bytes: int
    leftovers: list[LeftoverItem]

    @property
    def leftover_bytes(self) -> int:
        return sum(item.allocated_bytes for item in self.leftovers)

    @property
    def total_bytes(self) -> int:
        return self.app_bytes + self.leftover_bytes

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["leftover_bytes"] = self.leftover_bytes
        payload["total_bytes"] = self.total_bytes
        payload["leftovers"] = [item.to_dict() for item in self.leftovers]
        payload["app_human"] = format_bytes(self.app_bytes)
        payload["leftover_human"] = format_bytes(self.leftover_bytes)
        payload["total_human"] = format_bytes(self.total_bytes)
        return payload


def _bundle_id(app_path: Path) -> str:
    info = app_path / "Contents" / "Info.plist"
    if not info.is_file():
        return ""
    try:
        with info.open("rb") as handle:
            data = plistlib.load(handle)
    except (OSError, ValueError):
        return ""
    return str(data.get("CFBundleIdentifier", ""))


def _find_leftovers(bundle_id: str, app_stem: str) -> list[LeftoverItem]:
    library = Path.home() / "Library"
    needles = {n for n in (bundle_id, app_stem) if n}
    if not needles:
        return []
    found: list[LeftoverItem] = []
    seen: set[Path] = set()
    for sub in _LEFTOVER_DIRS:
        base = library / sub
        if not base.is_dir():
            continue
        try:
            entries = list(base.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink() or entry in seen:
                continue
            stem = entry.name.rsplit(".", 1)[0] if "." in entry.name else entry.name
            if entry.name in needles or stem in needles or (
                bundle_id and entry.name.startswith(bundle_id)
            ):
                seen.add(entry)
                category = _CATEGORY_MAP.get(sub, "support")
                found.append(
                    LeftoverItem(
                        path=str(entry),
                        allocated_bytes=_allocated_bytes(entry),
                        category=category,
                    )
                )
    return found


def scan_apps() -> list[InstalledApp]:
    apps: list[InstalledApp] = []
    for app_dir in APP_DIRS:
        if not app_dir.is_dir():
            continue
        try:
            entries = sorted(app_dir.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.suffix != ".app" or entry.is_symlink():
                continue
            bundle_id = _bundle_id(entry)
            app_stem = entry.stem
            apps.append(
                InstalledApp(
                    name=app_stem,
                    path=str(entry),
                    bundle_id=bundle_id,
                    app_bytes=_allocated_bytes(entry),
                    leftovers=_find_leftovers(bundle_id, app_stem),
                )
            )
    apps.sort(key=lambda a: a.total_bytes, reverse=True)
    return apps
