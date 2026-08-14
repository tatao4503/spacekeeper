"""즐겨찾는 분석 경로.

자주 스캔하는 폴더를 ``~/.spacekeeper/favorites.json`` 에 저장해 원클릭 재스캔에
쓴다. 전부 로컬이며, 홈 폴더 안의 실제 디렉터리만 허용한다(스캔 대상과 같은 안전
경계). 저장소에 커밋하지 않는다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

FAVORITES_PATH = Path.home() / ".spacekeeper" / "favorites.json"
_MAX_FAVORITES = 20


class FavoriteError(Exception):
    """즐겨찾기 경로가 안전 경계를 벗어났을 때."""


def _validate(path: Path) -> Path:
    resolved = path.expanduser()
    try:
        resolved = resolved.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise FavoriteError("존재하지 않거나 접근할 수 없는 경로입니다.") from exc
    home = Path.home().resolve()
    if resolved != home and home not in resolved.parents:
        raise FavoriteError("홈 폴더 안의 경로만 즐겨찾기에 추가할 수 있습니다.")
    if not resolved.is_dir():
        raise FavoriteError("폴더만 즐겨찾기에 추가할 수 있습니다.")
    return resolved


def load_favorites() -> list[str]:
    try:
        data = json.loads(FAVORITES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    seen: list[str] = []
    for item in data:
        if isinstance(item, str) and item and item not in seen:
            seen.append(item)
    return seen[:_MAX_FAVORITES]


def _save(paths: list[str]) -> list[str]:
    FAVORITES_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = FAVORITES_PATH.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(paths[:_MAX_FAVORITES], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, FAVORITES_PATH)
    return paths[:_MAX_FAVORITES]


def add_favorite(raw_path: str) -> list[str]:
    resolved = str(_validate(Path(raw_path)))
    favorites = load_favorites()
    if resolved in favorites:
        return favorites
    favorites.insert(0, resolved)
    return _save(favorites)


def remove_favorite(raw_path: str) -> list[str]:
    # add 는 심링크를 푼(resolve된) 경로를 저장하므로(macOS /var→/private/var 등)
    # 원경로·홈확장·resolve 를 모두 후보로 두고 지운다.
    candidates = {raw_path}
    expanded = Path(raw_path).expanduser()
    candidates.add(str(expanded))
    try:
        candidates.add(str(expanded.resolve()))
    except (OSError, RuntimeError):
        pass
    remaining = [item for item in load_favorites() if item not in candidates]
    return _save(remaining)
