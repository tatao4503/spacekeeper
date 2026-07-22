"""파일 삭제 결정을 돕는 '단서' 수집.

이 앱은 "지워도 된다/안 된다"를 판정하지 않는다. 대신 사람이 몇 초 만에
스스로 정할 수 있도록 사실만 모아 평평하게 돌려준다. 없는 정보는 지어내지
않고 없다고 말한다(예: macOS는 파일 절반가량의 열람 기록을 갖고 있지 않다).

모든 조회는 읽기 전용이며, 파일을 열거나 내려받지 않는다. 클라우드 대조는
내용이 아니라 이름+크기(메타데이터)로만 하여 오프라인 파일 다운로드를 유발하지
않는다.
"""

from __future__ import annotations

import hashlib
import os
import plistlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .report import format_bytes
from .scanner import _is_cloud_container

CLOUD_ROOTS = (
    Path.home() / "Library" / "Mobile Documents",
    Path.home() / "Library" / "CloudStorage",
)


class SignalError(Exception):
    """단서를 수집할 수 없는 경로."""


def _validate(path: Path) -> Path:
    """홈 폴더 안의 실제 파일인지 확인한다."""
    home = Path.home().resolve()
    if path.is_symlink():
        raise SignalError("심볼릭 링크는 확인하지 않습니다.")
    resolved = path.resolve()
    if not resolved.is_relative_to(home):
        raise SignalError("홈 폴더 안의 파일만 확인할 수 있습니다.")
    if not resolved.is_file():
        raise SignalError("파일을 찾을 수 없습니다.")
    return resolved


def _mdls(path: Path, attrs: list[str]) -> dict[str, str]:
    """mdls 로 Spotlight 메타데이터를 읽는다. 실패하면 빈 dict."""
    args = ["mdls"]
    for attr in attrs:
        args += ["-name", attr]
    args.append(str(path))
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    result: dict[str, str] = {}
    for line in out.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def _where_from(path: Path) -> list[str]:
    """다운로드 출처 URL 목록. 없으면 빈 리스트."""
    try:
        raw = subprocess.run(
            ["xattr", "-px", "com.apple.metadata:kMDItemWhereFroms", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    hex_text = raw.replace("\n", "").replace(" ", "")
    if not hex_text:
        return []
    try:
        data = bytes.fromhex(hex_text)
        parsed = plistlib.loads(data)
    except (ValueError, plistlib.InvalidFileException):
        return []
    return [str(item) for item in parsed if isinstance(item, str) and item.strip()]


def _parse_mdls_date(value: str) -> float | None:
    """mdls 날짜 문자열('2026-06-14 05:58:18 +0000')을 epoch 로."""
    if not value or value == "(null)":
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z").timestamp()
    except ValueError:
        return None


def _relative_age(epoch: float | None, now: float) -> str | None:
    if epoch is None:
        return None
    days = max(0, int((now - epoch) // 86400))
    if days < 1:
        return "오늘"
    if days < 30:
        return f"{days}일 전"
    if days < 365:
        return f"{days // 30}개월 전"
    years = days // 365
    months = (days % 365) // 30
    return f"{years}년 {months}개월 전" if months else f"{years}년 전"


def _hash_file(path: Path, limit: int = 512 * 1024 * 1024) -> str | None:
    """내용 해시. 너무 큰 파일은 건너뛴다(시간 보호)."""
    try:
        if path.stat().st_size > limit:
            return None
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _same_name_files(name: str, exclude: Path) -> list[Path]:
    """Spotlight(mdfind)로 같은 이름의 파일을 즉시 찾는다.

    인덱스 조회라 빠르고, 클라우드 파일을 내려받지 않는다. `-name` 은 부분
    일치이므로 정확히 같은 이름만 남기고, 원본 자신은 제외한다. 트리를 직접
    걷지 않아 오프라인 파일에서 멈추는 문제를 피한다.
    """
    try:
        out = subprocess.run(
            ["mdfind", "-name", name],
            capture_output=True,
            text=True,
            timeout=12,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    results: list[Path] = []
    for line in out.splitlines():
        candidate = Path(line)
        if candidate.name != name:  # -name 은 부분 일치 → 정확 일치만
            continue
        try:
            if candidate.resolve() == exclude:
                continue
        except OSError:
            continue
        results.append(candidate)
        if len(results) >= 200:
            break
    return results


def _under_cloud(path: Path) -> bool:
    return any(
        str(path).startswith(str(root) + os.sep) for root in CLOUD_ROOTS
    )


def _partition_copies(
    candidates: list[Path], size: int, digest: str | None
) -> tuple[list[str], list[str]]:
    """같은 이름 후보를 (로컬 내용일치, 클라우드 이름+크기일치)로 나눈다.

    로컬은 내용 해시로 확실히 확인하고, 클라우드는 다운로드를 피하려 이름+크기
    까지만 본다. stat 은 메타데이터만 읽으므로 오프라인 파일을 받지 않는다.
    """
    local: list[str] = []
    cloud: list[str] = []
    for candidate in candidates:
        try:
            candidate_size = candidate.stat().st_size
        except OSError:
            continue
        if candidate_size != size:
            continue
        if _under_cloud(candidate):
            cloud.append(str(candidate))
        elif digest is not None and _hash_file(candidate) == digest:
            local.append(str(candidate))
        if len(local) >= 5 and len(cloud) >= 5:
            break
    return local[:5], cloud[:5]


def collect_signals(raw_path: str, *, now: float | None = None) -> dict[str, Any]:
    """한 파일에 대한 결정 단서를 모아 돌려준다."""
    import time

    stamp = now if now is not None else time.time()
    path = _validate(Path(raw_path).expanduser())
    stat = path.stat()
    size = stat.st_size

    meta = _mdls(
        path,
        [
            "kMDItemLastUsedDate",
            "kMDItemDateAdded",
            "kMDItemContentModificationDate",
            "kMDItemKind",
        ],
    )
    last_used = _parse_mdls_date(meta.get("kMDItemLastUsedDate", ""))
    added = _parse_mdls_date(meta.get("kMDItemDateAdded", ""))
    modified = _parse_mdls_date(meta.get("kMDItemContentModificationDate", "")) or stat.st_mtime
    kind = meta.get("kMDItemKind", "").strip().strip('"') or None

    sources = _where_from(path)
    digest = _hash_file(path)
    candidates = _same_name_files(path.name, path)
    local_copies, cloud = _partition_copies(candidates, size, digest)

    return {
        "path": str(path),
        "name": path.name,
        "size_bytes": size,
        "size_human": format_bytes(size),
        "kind": kind,
        "sources": sources,
        "last_used_epoch": last_used,
        "last_used_label": _relative_age(last_used, stamp),
        "has_open_record": last_used is not None,
        "added_epoch": added,
        "added_label": _relative_age(added, stamp),
        "modified_epoch": modified,
        "modified_label": _relative_age(modified, stamp),
        "local_copies": local_copies,
        "local_copy_count": len(local_copies),
        "content_hashable": digest is not None,
        "cloud_name_size_matches": cloud,
        "cloud_match_count": len(cloud),
    }
