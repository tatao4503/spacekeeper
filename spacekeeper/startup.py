"""로그인 시 자동 실행되는 항목 정리.

`LaunchAgents`/`LaunchDaemons` 의 plist 를 읽어 무엇이 자동 실행되는지 보여준다.
끄는 방법은 이 앱의 원칙을 그대로 따른다 — plist 를 지우지 않고 격리함으로
옮기면 다음 로그인부터 실행되지 않고, 복원하면 그대로 되살아난다.

홈 밖(`/Library/...`)의 시스템 항목은 목록으로만 보여주고 조작하지 않는다.
"""

from __future__ import annotations

import plistlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .report import format_bytes

USER_AGENTS = Path.home() / "Library" / "LaunchAgents"
SYSTEM_DIRS = (
    Path("/Library/LaunchAgents"),
    Path("/Library/LaunchDaemons"),
)


@dataclass(frozen=True)
class StartupItem:
    label: str
    path: str
    program: str
    scope: str  # "user" | "system"
    run_at_load: bool
    allocated_bytes: int

    @property
    def manageable(self) -> bool:
        """홈 안(사용자 영역) 항목만 격리로 끌 수 있다."""
        return self.scope == "user"

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "path": self.path,
            "program": self.program,
            "scope": self.scope,
            "run_at_load": self.run_at_load,
            "manageable": self.manageable,
            "allocated_bytes": self.allocated_bytes,
            "allocated_human": format_bytes(self.allocated_bytes),
        }


def _program_of(data: dict) -> str:
    program = data.get("Program")
    if isinstance(program, str) and program:
        return program
    args = data.get("ProgramArguments")
    if isinstance(args, list) and args:
        return " ".join(str(part) for part in args)
    return ""


def _read_items(directory: Path, scope: str) -> list[StartupItem]:
    if not directory.is_dir():
        return []
    items: list[StartupItem] = []
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return []
    for entry in entries:
        if entry.suffix != ".plist" or entry.is_symlink():
            continue
        try:
            with entry.open("rb") as handle:
                data = plistlib.load(handle)
            size = entry.stat().st_size
        except (OSError, ValueError, plistlib.InvalidFileException):
            continue
        if not isinstance(data, dict):
            continue
        items.append(
            StartupItem(
                label=str(data.get("Label") or entry.stem),
                path=str(entry),
                program=_program_of(data),
                scope=scope,
                run_at_load=bool(data.get("RunAtLoad", False)),
                allocated_bytes=size,
            )
        )
    return items


def list_startup_items() -> dict[str, Any]:
    """자동 실행 항목을 사용자/시스템으로 나눠 돌려준다."""
    user_items = _read_items(USER_AGENTS, "user")
    system_items: list[StartupItem] = []
    for directory in SYSTEM_DIRS:
        system_items.extend(_read_items(directory, "system"))

    items = user_items + system_items
    return {
        "items": [item.to_dict() for item in items],
        "user_count": len(user_items),
        "system_count": len(system_items),
        "manageable_count": sum(1 for item in items if item.manageable),
    }
