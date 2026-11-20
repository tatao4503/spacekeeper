"""iCloud(File Provider)가 관리하는 위치를 알아보고, 남은 표시를 떼어낸다.

실제로 겪은 두 가지 문제 때문에 있다 (2026-11, M1 Air, iCloud 가득 찬 상태):

1. 바탕화면·문서처럼 iCloud가 동기화하는 폴더 안의 항목을 밖으로 옮기면
   iCloud가 이동을 붙잡을 수 있다. 2.2GB 폴더가 20분 동안 멈췄고, 프로세스를
   끝내자 원본은 그대로 남아 있었다. 작은 새 폴더는 바로 옮겨졌다.
2. 동기화에서 빠진 `.nosync` 폴더에도 `com.apple.fileprovider.*` 표시가 붙고,
   밖으로 옮겨도 그대로 따라간다. 이 표시가 남은 폴더는 Finder에서 휴지통을
   비울 때 지워지지 않고 남았다. 표시를 떼자 바로 지워졌다.

동기화 영역의 맨 위 폴더(바탕화면·문서·iCloud Drive)에는
`com.apple.file-provider-domain-id` 표시가 붙어 있어 이것으로 알아본다.
표준 라이브러리만 쓰므로 확장 속성은 ctypes로 읽는다.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path

# 동기화 영역의 맨 위 폴더에 붙는 표시. 일반 사용자는 이 표시를 붙일 수 없어서
# 테스트는 이 값을 바꿔 끼운다.
DOMAIN_ATTRS: tuple[str, ...] = ("com.apple.file-provider-domain-id",)
# 옮긴 뒤 떼어낼 표시의 접두어. 동기화 영역 밖에서는 의미가 없다.
MARKER_PREFIX = "com.apple.fileprovider."

SYNCED = "synced"      # iCloud가 동기화하는 위치
EXCLUDED = "excluded"  # 동기화 영역 안이지만 .nosync로 빠진 위치

_XATTR_NOFOLLOW = 0x0001

try:
    _lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    _lib.listxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int]
    _lib.listxattr.restype = ctypes.c_ssize_t
    _lib.removexattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    _lib.removexattr.restype = ctypes.c_int
except (OSError, AttributeError):  # macOS가 아니면 표시도 없다
    _lib = None


def xattr_names(path: Path | str) -> list[str]:
    """심볼릭 링크를 따라가지 않고 확장 속성 이름 목록을 돌려준다. 실패하면 빈 목록."""
    if _lib is None:
        return []
    raw = os.fsencode(str(path))
    size = _lib.listxattr(raw, None, 0, _XATTR_NOFOLLOW)
    if size <= 0:
        return []
    buf = ctypes.create_string_buffer(size)
    size = _lib.listxattr(raw, buf, size, _XATTR_NOFOLLOW)
    if size <= 0:
        return []
    return [
        os.fsdecode(name) for name in buf.raw[:size].split(b"\0") if name
    ]


def is_domain_root(path: Path | str) -> bool:
    """바탕화면·문서·iCloud Drive처럼 동기화 영역의 맨 위 폴더인지."""
    return _is_domain_root(Path(path))


def _is_domain_root(path: Path) -> bool:
    names = xattr_names(path)
    return any(attr in names for attr in DOMAIN_ATTRS)


def sync_state(path: Path | str) -> str | None:
    """`path`가 iCloud 동기화 영역 안에 있는지 알려준다.

    SYNCED   동기화되는 위치
    EXCLUDED 동기화 영역 안이지만 경로 중간이나 끝이 `.nosync`라 빠진 위치
    None     동기화 영역 밖

    `path`가 아직 없어도(복원할 원래 위치) 상위 폴더로 판단한다.
    """
    path = Path(os.path.abspath(path))
    if os.path.lexists(path) and _is_domain_root(path):
        return SYNCED  # 바탕화면·문서 폴더 자체
    below_root: list[str] = [path.name]
    for parent in path.parents:
        if _is_domain_root(parent):
            if any(name.endswith(".nosync") for name in below_root):
                return EXCLUDED
            return SYNCED
        below_root.append(parent.name)
    return None


def _strip_one(path: str) -> int:
    removed = 0
    raw = os.fsencode(path)
    for name in xattr_names(path):
        if name.startswith(MARKER_PREFIX):
            if _lib.removexattr(raw, os.fsencode(name), _XATTR_NOFOLLOW) == 0:
                removed += 1
    return removed


def strip_markers(path: Path | str) -> int:
    """`path`와 그 안의 모든 항목에서 File Provider 표시를 뗀다. 뗀 개수를 돌려준다.

    동기화 영역 밖으로 옮긴 항목에만 쓴다. 심볼릭 링크는 따라가지 않고,
    읽지 못하는 폴더는 건너뛴다.
    """
    if _lib is None:
        return 0
    path = str(path)
    if not os.path.lexists(path):
        return 0
    removed = _strip_one(path)
    if os.path.isdir(path) and not os.path.islink(path):
        for root, dirs, files in os.walk(path, onerror=lambda _exc: None):
            for name in dirs + files:
                removed += _strip_one(os.path.join(root, name))
    return removed
