"""비슷한 사진 찾기.

내용이 완전히 같은 파일(해시 중복)과 달리, 크기·압축률·약간의 보정이 달라도
'눈으로 보기에 같은' 사진을 찾는다. macOS 기본 도구 `sips` 로 이미지를 9x8 로
줄인 뒤 dHash(인접 픽셀 밝기 비교)를 계산하고, 해밍 거리로 묶는다.
외부 패키지를 쓰지 않으며 원본 파일을 수정하지 않는다.
"""

from __future__ import annotations

import os
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .report import format_bytes
from .scanner import _is_cloud_container

IMAGE_SUFFIXES = {
    ".jpg", ".jpeg", ".png", ".heic", ".heif",
    ".gif", ".bmp", ".tiff", ".tif", ".webp",
}

# dHash 는 9x8 로 줄인 뒤 가로 인접 픽셀을 비교해 64비트를 만든다.
_HASH_W = 9
_HASH_H = 8


def _bmp_to_gray(data: bytes) -> list[int] | None:
    """32/24bpp BMP 바이트를 밝기 값 목록으로 바꾼다(행 우선, 위→아래)."""
    if len(data) < 30 or data[:2] != b"BM":
        return None
    try:
        offset = struct.unpack_from("<I", data, 10)[0]
        width, height = struct.unpack_from("<ii", data, 18)
        bpp = struct.unpack_from("<H", data, 28)[0]
    except struct.error:
        return None
    if bpp not in (24, 32) or width <= 0 or height == 0:
        return None

    top_down = height < 0
    height = abs(height)
    step = bpp // 8
    row_size = ((bpp * width + 31) // 32) * 4  # 4바이트 정렬

    rows: list[list[int]] = []
    for row in range(height):
        start = offset + row * row_size
        if start + width * step > len(data):
            return None
        gray_row = []
        for col in range(width):
            base = start + col * step
            blue, green, red = data[base], data[base + 1], data[base + 2]
            gray_row.append((red * 299 + green * 587 + blue * 114) // 1000)
        rows.append(gray_row)
    if not top_down:
        rows.reverse()  # BMP 기본은 아래→위 저장
    return [value for row in rows for value in row]


def photo_hash(path: Path) -> int | None:
    """이미지의 dHash(64비트)를 계산한다. 실패하면 None."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "thumb.bmp"
        try:
            result = subprocess.run(
                [
                    "sips", "-s", "format", "bmp",
                    "-z", str(_HASH_H), str(_HASH_W),
                    str(path), "--out", str(out),
                ],
                capture_output=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0 or not out.is_file():
            return None
        try:
            pixels = _bmp_to_gray(out.read_bytes())
        except OSError:
            return None

    if not pixels or len(pixels) < _HASH_W * _HASH_H:
        return None

    bits = 0
    for row in range(_HASH_H):
        base = row * _HASH_W
        for col in range(_HASH_W - 1):
            bits <<= 1
            if pixels[base + col] > pixels[base + col + 1]:
                bits |= 1
    return bits


def _distance(left: int, right: int) -> int:
    return bin(left ^ right).count("1")


def _iter_images(root: Path, min_bytes: int, limit: int) -> list[tuple[Path, int]]:
    """이미지 파일을 모은다. 클라우드 폴더는 건너뛰고, 순회 오류는 무시한다."""
    found: list[tuple[Path, int]] = []

    def _walk(directory: Path) -> None:
        if len(found) >= limit or _is_cloud_container(directory):
            return
        try:
            entries = os.scandir(directory)
        except OSError:
            return
        with entries:
            while len(found) < limit:
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
                    if Path(entry.name).suffix.lower() not in IMAGE_SUFFIXES:
                        continue
                    stat = entry.stat(follow_symlinks=False)
                    blocks = getattr(stat, "st_blocks", None)
                    allocated = blocks * 512 if blocks is not None else stat.st_size
                except OSError:
                    continue
                if allocated >= min_bytes:
                    found.append((Path(entry.path), allocated))

    _walk(root)
    return found


def find_similar_photos(
    root: Path,
    *,
    min_bytes: int = 100 * 1024,
    max_images: int = 1200,
    max_distance: int = 10,
) -> dict[str, Any]:
    """root 하위에서 눈으로 비슷한 사진을 묶어 돌려준다.

    각 그룹의 첫 항목(가장 큰 파일)은 보관본으로 두고, 나머지 용량을
    정리 가능한 양으로 계산한다. 파일은 읽기만 한다.

    기본 임계값 10은 실측에 근거한다. 같은 사진의 복사본·리사이즈본은
    거리 0~7 에 모였고, 서로 다른 사진 91쌍의 최소 거리는 17이었다.
    """
    resolved = root.expanduser().resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"디렉토리가 아닙니다: {resolved}")

    images = _iter_images(resolved, min_bytes, max_images)
    hashed: list[tuple[Path, int, int]] = []
    for path, size in images:
        digest = photo_hash(path)
        if digest is not None:
            hashed.append((path, size, digest))

    # 큰 파일을 보관본으로 삼기 위해 크기 내림차순으로 묶는다.
    hashed.sort(key=lambda item: item[1], reverse=True)

    groups: list[dict[str, Any]] = []
    used: set[int] = set()
    for i, (path, size, digest) in enumerate(hashed):
        if i in used:
            continue
        members = [(path, size)]
        used.add(i)
        for j in range(i + 1, len(hashed)):
            if j in used:
                continue
            if _distance(digest, hashed[j][2]) <= max_distance:
                used.add(j)
                members.append((hashed[j][0], hashed[j][1]))
        if len(members) < 2:
            continue
        reclaimable = sum(size for _, size in members[1:])
        groups.append(
            {
                "files": [
                    {
                        "path": str(member_path),
                        "name": member_path.name,
                        "allocated_bytes": member_size,
                        "allocated_human": format_bytes(member_size),
                        "keep": index == 0,
                    }
                    for index, (member_path, member_size) in enumerate(members)
                ],
                "count": len(members),
                "reclaimable_bytes": reclaimable,
                "reclaimable_human": format_bytes(reclaimable),
            }
        )

    groups.sort(key=lambda group: group["reclaimable_bytes"], reverse=True)
    total = sum(int(group["reclaimable_bytes"]) for group in groups)
    return {
        "path": str(resolved),
        "scanned_images": len(hashed),
        "group_count": len(groups),
        "reclaimable_bytes": total,
        "reclaimable_human": format_bytes(total),
        "groups": groups,
    }
