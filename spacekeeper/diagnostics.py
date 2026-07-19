"""Non-destructive environment checks for the local Spacekeeper dashboard."""

from __future__ import annotations

import os
import shutil
import stat
import sys
import uuid
from datetime import datetime, timezone
from ipaddress import ip_address
from pathlib import Path

from . import engine


def _check(
    check_id: str,
    label: str,
    group: str,
    status_value: str,
    detail: str,
    *,
    path: Path | None = None,
    action: str | None = None,
) -> dict[str, str]:
    result = {
        "id": check_id,
        "label": label,
        "group": group,
        "status": status_value,
        "detail": detail,
    }
    if path is not None:
        result["path"] = str(path)
    if action is not None:
        result["action"] = action
    return result


def _probe_directory_read(check_id: str, label: str, path: Path) -> dict[str, str]:
    try:
        path_stat = path.stat()
        if not stat.S_ISDIR(path_stat.st_mode):
            return _check(
                check_id,
                label,
                "protected",
                "blocked",
                "폴더가 아닌 다른 항목이 경로를 차지하고 있습니다.",
                path=path,
            )
        with os.scandir(path) as entries:
            next(entries, None)
    except FileNotFoundError:
        return _check(
            check_id,
            label,
            "protected",
            "attention",
            "아직 생성되지 않은 폴더입니다.",
            path=path,
        )
    except PermissionError:
        return _check(
            check_id,
            label,
            "protected",
            "blocked",
            "macOS 개인정보 보호 설정으로 읽을 수 없습니다.",
            path=path,
            action="privacy_settings",
        )
    except OSError as exc:
        return _check(
            check_id,
            label,
            "protected",
            "blocked",
            f"폴더를 확인하지 못했습니다: {exc}",
            path=path,
        )
    return _check(
        check_id,
        label,
        "protected",
        "ready",
        "현재 실행 중인 Spacekeeper에서 읽을 수 있습니다.",
        path=path,
    )


def _probe_directory_write(
    check_id: str,
    label: str,
    path: Path,
    *,
    create: bool,
) -> dict[str, str]:
    test_path: Path | None = None
    descriptor: int | None = None
    try:
        if create:
            path.mkdir(parents=True, exist_ok=True)
        path_stat = path.stat()
        if not stat.S_ISDIR(path_stat.st_mode):
            raise NotADirectoryError(str(path))
        test_path = path / f".spacekeeper-write-check-{uuid.uuid4().hex}"
        descriptor = os.open(
            test_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        os.close(descriptor)
        descriptor = None
        test_path.unlink()
        test_path = None
    except FileNotFoundError:
        return _check(
            check_id,
            label,
            "safety",
            "attention",
            "대상 폴더가 아직 생성되지 않았습니다.",
            path=path,
        )
    except OSError as exc:
        return _check(
            check_id,
            label,
            "safety",
            "blocked",
            f"임시 파일 쓰기·정리 검사를 완료하지 못했습니다: {exc}",
            path=path,
        )
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if test_path is not None:
            try:
                test_path.unlink()
            except OSError:
                pass
    return _check(
        check_id,
        label,
        "safety",
        "ready",
        "임시 파일을 쓰고 지우는 검사를 안전하게 마쳤습니다.",
        path=path,
    )


def _runtime_check(home: Path, package_root: Path) -> tuple[dict[str, str], dict]:
    staged_root = home / ".spacekeeper" / "runtime"
    if getattr(sys, "frozen", False):
        runtime_mode = "bundled"
    elif package_root.is_relative_to(staged_root):
        runtime_mode = "staged"
    else:
        runtime_mode = "development"
    version = ".".join(str(part) for part in sys.version_info[:3])
    required_assets = (
        package_root / "web" / "index.html",
        package_root / "web" / "style.css",
        package_root / "web" / "app.js",
    )
    assets_ready = all(path.is_file() for path in required_assets)
    version_ready = sys.version_info >= (3, 11)
    status_value = "ready" if version_ready and assets_ready else "blocked"
    mode_label = {
        "bundled": "앱에 포함된 독립 실행 런타임",
        "staged": "데스크톱 앱용 스테이징 런타임",
        "development": "개발 소스 런타임",
    }[runtime_mode]
    details = [f"{mode_label} · Python {version}"]
    if not version_ready:
        details.append("Python 3.11 이상이 필요합니다.")
    if not assets_ready:
        details.append("웹 대시보드 파일이 누락되었습니다.")
    return (
        _check(
            "runtime",
            "앱 런타임",
            "environment",
            status_value,
            " ".join(details),
            path=package_root,
        ),
        {
            "mode": runtime_mode,
            "python_version": version,
            "package_root": str(package_root),
        },
    )


def diagnose_environment(
    *,
    home: Path | None = None,
    quarantine_root: Path | None = None,
    trash_root: Path | None = None,
    package_root: Path | None = None,
    server_host: str = "127.0.0.1",
) -> dict:
    """Probe the current process without moving or retaining user files."""

    resolved_home = (home or Path.home()).expanduser().resolve()
    resolved_quarantine = quarantine_root or engine.QUARANTINE_ROOT
    resolved_trash = trash_root or engine.TRASH_ROOT
    resolved_package = package_root or Path(__file__).resolve().parent

    checks = [
        _probe_directory_read("desktop", "데스크탑", resolved_home / "Desktop"),
        _probe_directory_read("documents", "문서", resolved_home / "Documents"),
        _probe_directory_read("downloads", "다운로드", resolved_home / "Downloads"),
        _probe_directory_write(
            "quarantine",
            "Spacekeeper 격리함",
            resolved_quarantine,
            create=True,
        ),
        _probe_directory_write(
            "trash",
            "macOS 휴지통 연결",
            resolved_trash,
            create=False,
        ),
    ]
    runtime_check, runtime = _runtime_check(resolved_home, resolved_package)
    checks.append(runtime_check)

    finder_ready = sys.platform == "darwin" and shutil.which("open") is not None
    checks.append(
        _check(
            "finder",
            "Finder 연동",
            "environment",
            "ready" if finder_ready else "blocked",
            (
                "Finder에서 항목 위치를 열 수 있습니다."
                if finder_ready
                else "macOS Finder 연동을 사용할 수 없습니다."
            ),
        )
    )
    try:
        local_server_ready = ip_address(server_host).is_loopback
    except ValueError:
        local_server_ready = False
    checks.append(
        _check(
            "local_server",
            "로컬 전용 서버",
            "environment",
            "ready" if local_server_ready else "blocked",
            (
                f"{server_host}에서만 대시보드 요청을 받습니다."
                if local_server_ready
                else f"로컬 전용이 아닌 주소({server_host})에 연결되어 있습니다."
            ),
        )
    )

    counts = {
        status_value: sum(
            1 for check in checks if check["status"] == status_value
        )
        for status_value in ("ready", "attention", "blocked")
    }
    overall_status = (
        "blocked"
        if counts["blocked"]
        else "attention" if counts["attention"] else "ready"
    )
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "overall_status": overall_status,
        "counts": counts,
        "checks": checks,
        "runtime": runtime,
    }
