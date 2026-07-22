"""Local dashboard server.

127.0.0.1에만 바인딩하는 단일 사용자용 로컬 서버입니다. 정리(격리) 요청은
직전 스캔에서 나온 action_id에 대해서만 처리하므로, API로 임의 경로를
넘겨 파일을 옮기는 일은 불가능합니다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

from . import diagnostics, engine, notifier
from .apps import scan_apps
from .models import ScanOptions
from .planning import _action_id, build_cleanup_plan
from .report import format_bytes
from .scanner import ScanCancelled, scan

STATIC_DIR = Path(__file__).parent / "web"
_PLAN_LIMIT = 500
_EMPTY_LIMIT = 10_000
_REVEAL_TIMEOUT_SECONDS = 5
_SETTINGS_TIMEOUT_SECONDS = 5
_DESKTOP_PARENT_ENV = "SPACEKEEPER_DESKTOP_PARENT_PID"
_PARENT_CHECK_INTERVAL_SECONDS = 0.5


def _desktop_parent_pid() -> int | None:
    """Return the desktop parent PID when the server was launched by the app."""

    raw_pid = os.environ.get(_DESKTOP_PARENT_ENV, "")
    try:
        parent_pid = int(raw_pid)
    except ValueError:
        return None
    return parent_pid if parent_pid > 1 else None


def _parent_process_is_alive(parent_pid: int) -> bool:
    """Check process existence without changing its state."""

    try:
        os.kill(parent_pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _watch_desktop_parent(
    server: ThreadingHTTPServer,
    parent_pid: int,
    stop_event: threading.Event,
    *,
    check_interval: float = _PARENT_CHECK_INTERVAL_SECONDS,
) -> None:
    """Stop the local server if its owning desktop process disappears."""

    while not stop_event.wait(check_interval):
        if not _parent_process_is_alive(parent_pid):
            server.shutdown()
            return


class _ScanBusyError(RuntimeError):
    """Raised when another scan is already using the scanner."""


class _UnknownScanJob(LookupError):
    """Raised when a scan job is no longer available."""


@dataclass
class _ScanJob:
    job_id: str
    params: dict[str, list[str]]
    status: str = "running"
    progress: dict[str, object] = field(
        default_factory=lambda: {
            "phase": "scanning",
            "current_path": "",
            "scanned_files": 0,
            "scanned_bytes": 0,
            "candidates_found": 0,
            "directories_pending": 0,
            "duplicate_files_done": 0,
            "duplicate_files_total": 0,
        }
    )
    result: dict | None = None
    error: str | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def snapshot(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "progress": dict(self.progress),
            "result": self.result,
            "error": self.error,
        }


class _State:
    """직전에 표시한 action_id → (path, kind)만 정리를 허용한다.

    임의 경로를 API로 넘겨 파일을 옮기는 것을 막는 방어선이다. 각 화면
    (대시보드/중복/앱)이 표시한 항목만 버킷에 등록해 둔다.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, dict[str, tuple[str, str]]] = {}
        self._scan_job: _ScanJob | None = None

    def register(self, bucket: str, pairs: list[tuple[str, str, str]]) -> None:
        with self._lock:
            self._buckets[bucket] = {
                action_id: (path, kind) for action_id, path, kind in pairs
            }

    def resolve(self, action_ids: list[str]) -> list[tuple[str, str, str]]:
        with self._lock:
            merged: dict[str, tuple[str, str]] = {}
            for bucket in self._buckets.values():
                merged.update(bucket)
            items: list[tuple[str, str, str]] = []
            for action_id in action_ids:
                match = merged.get(action_id)
                if match is not None:
                    items.append((action_id, match[0], match[1]))
            return items

    def start_scan(self, params: dict[str, list[str]]) -> dict:
        with self._lock:
            if self._scan_job is not None and self._scan_job.status in {
                "running",
                "canceling",
            }:
                raise _ScanBusyError("이미 저장공간을 분석하고 있습니다.")
            job = _ScanJob(job_id=uuid.uuid4().hex, params=params)
            self._scan_job = job
            initial_snapshot = job.snapshot()

        worker = threading.Thread(
            target=self._run_scan,
            args=(job,),
            name=f"spacekeeper-scan-{job.job_id[:8]}",
            daemon=True,
        )
        worker.start()
        return initial_snapshot

    def scan_status(self, job_id: str) -> dict:
        with self._lock:
            job = self._current_scan(job_id)
            return job.snapshot()

    def cancel_scan(self, job_id: str) -> dict:
        with self._lock:
            job = self._current_scan(job_id)
            if job.status == "running":
                job.status = "canceling"
                job.cancel_event.set()
            return job.snapshot()

    def _current_scan(self, job_id: str) -> _ScanJob:
        if self._scan_job is None or self._scan_job.job_id != job_id:
            raise _UnknownScanJob("분석 작업을 찾을 수 없습니다.")
        return self._scan_job

    def _update_scan_progress(
        self, job_id: str, progress: dict[str, object]
    ) -> None:
        with self._lock:
            if self._scan_job is None or self._scan_job.job_id != job_id:
                return
            self._scan_job.progress = dict(progress)

    def _finish_scan(self, job: _ScanJob, payload: dict) -> None:
        pairs = [
            (entry["action_id"], entry["path"], entry["kind"])
            for entry in payload["entries"]
        ]
        for group in payload["duplicates"]:
            pairs.extend(
                (item["action_id"], item["path"], "file")
                for item in group["files"]
            )

        with self._lock:
            if self._scan_job is not job:
                return
            if job.cancel_event.is_set():
                job.status = "cancelled"
                return
            self._buckets["scan"] = {
                action_id: (path, kind) for action_id, path, kind in pairs
            }
            job.result = payload
            job.status = "completed"
            notifier.notify_scan_complete(
                payload.get("review_bytes", 0),
                payload.get("candidate_count", 0),
                duration_seconds=payload.get("duration"),
            )

    def _run_scan(self, job: _ScanJob) -> None:
        try:
            payload = _scan_payload(
                job.params,
                progress_callback=lambda progress: self._update_scan_progress(
                    job.job_id, progress
                ),
                cancel_event=job.cancel_event,
            )
        except ScanCancelled:
            with self._lock:
                if self._scan_job is job:
                    job.status = "cancelled"
        except (
            FileNotFoundError,
            NotADirectoryError,
            PermissionError,
            ValueError,
        ) as exc:
            with self._lock:
                if self._scan_job is job:
                    job.status = "failed"
                    job.error = str(exc)
        except Exception as exc:  # pragma: no cover - last-resort worker guard
            with self._lock:
                if self._scan_job is job:
                    job.status = "failed"
                    job.error = f"분석 중 예기치 않은 오류가 발생했습니다: {exc}"
        else:
            self._finish_scan(job, payload)


def _scan_payload(
    params: dict[str, list[str]],
    *,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict:
    raw_paths = params.get("paths", [])
    roots = tuple(Path(p) for p in raw_paths if p.strip()) or (
        Path.home() / "Downloads",
    )
    large_mb = int(params.get("large_mb", ["500"])[0])
    old_days = int(params.get("old_days", ["180"])[0])
    duplicates = params.get("duplicates", ["0"])[0] in ("1", "true", "on")
    include_cloud = params.get("include_cloud", ["0"])[0] in ("1", "true", "on")
    excluded_paths = tuple(
        Path(path) for path in params.get("exclude", []) if path.strip()
    )

    options = ScanOptions(
        roots=roots,
        large_bytes=large_mb * 1024 * 1024,
        old_days=old_days,
        top=_PLAN_LIMIT,
        find_duplicates=duplicates,
        include_cloud_storage=include_cloud,
        excluded_paths=excluded_paths,
    )
    result = scan(
        options,
        progress_callback=progress_callback,
        cancel_event=cancel_event,
    )
    plan = build_cleanup_plan(
        result, risks={"low", "medium", "high"}, limit=_PLAN_LIMIT
    )
    entries = [
        {
            "action_id": e.action_id,
            "kind": e.kind,
            "path": e.path,
            "name": Path(e.path).name,
            "allocated_bytes": e.allocated_bytes,
            "allocated_human": format_bytes(e.allocated_bytes),
            "risk": e.risk,
            "category": e.category,
            "reason": e.reason,
            "caution": e.caution,
        }
        for e in plan.entries
    ]

    duplicates = []
    for index, group in enumerate(result.duplicate_groups):
        files = [
            {
                "action_id": _action_id("file", path),
                "path": path,
                "name": Path(path).name,
                "keep": position == 0,
            }
            for position, path in enumerate(group.paths)
        ]
        duplicates.append(
            {
                "group_id": index,
                "each_bytes": group.logical_size_each,
                "each_human": format_bytes(group.logical_size_each),
                "reclaimable_bytes": group.reclaimable_bytes,
                "reclaimable_human": format_bytes(group.reclaimable_bytes),
                "files": files,
            }
        )

    payload = {
        "roots": result.roots,
        "disk": {
            "total": result.volume_total_bytes,
            "used": result.volume_used_bytes,
            "free": result.volume_free_bytes,
        },
        "scanned_files": result.scanned_files,
        "duration": result.finished_at - result.started_at,
        "review_bytes": result.review_candidate_bytes,
        "by_risk": result.candidate_bytes_by_risk,
        "candidate_count": result.file_candidate_count + result.cache_candidate_count,
        "displayed_entry_count": len(entries),
        "omitted_entries": (
            plan.omitted_plan_entries + plan.omitted_scan_candidates
        ),
        "duplicate_reclaimable_bytes": result.duplicate_reclaimable_bytes,
        "duplicate_group_count": result.duplicate_group_count,
        "omitted_duplicate_groups": result.duplicate_group_count - len(duplicates),
        "entries": entries,
        "duplicates": duplicates,
        "skipped": {
            "permission_denied": result.permission_denied,
            "symlinks": result.skipped_symlinks,
            "cloud_dirs": result.skipped_cloud_dirs,
            "excluded_paths": result.skipped_excluded_paths,
        },
        "excluded_paths": result.excluded_paths,
    }
    return payload


def _register_scan(state: "_State", payload: dict) -> None:
    pairs = [(e["action_id"], e["path"], e["kind"]) for e in payload["entries"]]
    for group in payload["duplicates"]:
        pairs.extend((f["action_id"], f["path"], "file") for f in group["files"])
    state.register("scan", pairs)


def _scan_params_from_body(body: dict) -> dict[str, list[str]]:
    raw_paths = body.get("paths")
    if not isinstance(raw_paths, list) or not raw_paths:
        raise ValueError("분석할 경로를 하나 이상 선택해주세요.")
    if len(raw_paths) > 32:
        raise ValueError("한 번에 32개 경로까지 분석할 수 있습니다.")
    if not all(isinstance(path, str) for path in raw_paths):
        raise ValueError("분석 경로 형식이 올바르지 않습니다.")
    paths = [path.strip() for path in raw_paths if path.strip()]
    if not paths:
        raise ValueError("빈 분석 경로는 사용할 수 없습니다.")

    raw_excluded = body.get("exclude", [])
    if not isinstance(raw_excluded, list) or not all(
        isinstance(path, str) for path in raw_excluded
    ):
        raise ValueError("제외 경로 형식이 올바르지 않습니다.")

    params = {
        "paths": paths,
        "exclude": [path.strip() for path in raw_excluded if path.strip()],
        "duplicates": ["1" if body.get("duplicates") is True else "0"],
        "include_cloud": ["1" if body.get("include_cloud") is True else "0"],
    }
    for key, default in (("large_mb", 500), ("old_days", 180)):
        value = body.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{key}는 0보다 큰 정수여야 합니다.")
        params[key] = [str(value)]
    return params


def _apps_payload() -> dict:
    apps = []
    for app in scan_apps():
        app_action = _action_id("file", app.path)
        leftovers = [
            {
                "action_id": _action_id("file", item.path),
                "path": item.path,
                "name": Path(item.path).name,
                "allocated_bytes": item.allocated_bytes,
                "allocated_human": format_bytes(item.allocated_bytes),
            }
            for item in app.leftovers
        ]
        apps.append(
            {
                "name": app.name,
                "path": app.path,
                "bundle_id": app.bundle_id,
                "app_action_id": app_action,
                "app_bytes": app.app_bytes,
                "app_human": format_bytes(app.app_bytes),
                "leftover_bytes": app.leftover_bytes,
                "leftover_human": format_bytes(app.leftover_bytes),
                "total_bytes": app.total_bytes,
                "total_human": format_bytes(app.total_bytes),
                "leftovers": leftovers,
            }
        )
    return {"apps": apps}


def _register_apps(state: "_State", payload: dict) -> None:
    pairs: list[tuple[str, str, str]] = []
    for app in payload["apps"]:
        pairs.append((app["app_action_id"], app["path"], "file"))
        pairs.extend((f["action_id"], f["path"], "file") for f in app["leftovers"])
    state.register("apps", pairs)


def _register_photos(state: "_State", payload: dict) -> None:
    """비슷한 사진의 각 파일에 action_id 를 붙이고 정리 대상으로 등록한다."""
    pairs: list[tuple[str, str, str]] = []
    for group in payload.get("groups", []):
        for item in group.get("files", []):
            action_id = _action_id("file", item["path"])
            item["action_id"] = action_id
            pairs.append((action_id, item["path"], "file"))
    state.register("photos", pairs)


def _register_startup(state: "_State", payload: dict) -> None:
    """사용자 영역 자동 실행 항목만 격리(=끄기) 대상으로 등록한다.

    시스템 항목은 홈 밖이라 engine 이 이동을 거부하므로 등록하지 않는다.
    """
    pairs: list[tuple[str, str, str]] = []
    for item in payload.get("items", []):
        if not item.get("manageable"):
            continue
        action_id = _action_id("file", item["path"])
        item["action_id"] = action_id
        pairs.append((action_id, item["path"], "file"))
    state.register("startup", pairs)


def _empty_selections(body: dict) -> dict[str, str]:
    raw_items = body.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("선택한 격리 항목이 없습니다.")
    if len(raw_items) > _EMPTY_LIMIT:
        raise ValueError(f"한 번에 {_EMPTY_LIMIT}개까지 처리할 수 있습니다.")

    selections: dict[str, str] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            raise ValueError("격리 항목 형식이 올바르지 않습니다.")
        action_id = item.get("action_id")
        instance_token = item.get("instance_token")
        if (
            not isinstance(action_id, str)
            or not action_id
            or not isinstance(instance_token, str)
            or not instance_token
        ):
            raise ValueError("격리 항목 식별 정보가 올바르지 않습니다.")
        if action_id in selections:
            raise ValueError(f"중복 선택된 항목입니다: {action_id}")
        selections[action_id] = instance_token
    return selections


def _reveal_in_finder(path: str) -> None:
    """Ask Finder to select an existing path without invoking a shell."""

    if sys.platform != "darwin":
        raise RuntimeError("Finder에서 보기는 macOS에서만 사용할 수 있습니다.")
    if not os.path.lexists(path):
        raise FileNotFoundError("파일이 이동되었거나 사라져 위치를 열 수 없습니다.")
    subprocess.run(
        ["open", "-R", path],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=_REVEAL_TIMEOUT_SECONDS,
    )


def _open_system_settings() -> None:
    """Open macOS System Settings without invoking a shell or URL handler."""

    if sys.platform != "darwin":
        raise RuntimeError("시스템 설정 열기는 macOS에서만 사용할 수 있습니다.")
    subprocess.run(
        ["open", "-b", "com.apple.systempreferences"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=_SETTINGS_TIMEOUT_SECONDS,
    )


def _quarantine_path_for_reveal(action_id: str, instance_token: str) -> str:
    records = engine.list_quarantine()
    record = next((item for item in records if item.action_id == action_id), None)
    if record is None or record.instance_token != instance_token:
        raise engine.StaleSelectionError(
            "격리함이 변경되었습니다. 새로고침 후 다시 확인하세요."
        )
    return record.stored_path


class _Handler(BaseHTTPRequestHandler):
    state: _State

    def log_message(self, *args) -> None:  # noqa: D401 - 조용히
        pass

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, filename: str, content_type: str) -> None:
        path = STATIC_DIR / filename
        if not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(body, dict):
            raise ValueError("요청 본문은 JSON 객체여야 합니다.")
        return body

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path)
        if route.path in ("/", "/index.html"):
            self._send_static("index.html", "text/html; charset=utf-8")
        elif route.path == "/style.css":
            self._send_static("style.css", "text/css; charset=utf-8")
        elif route.path == "/app.js":
            self._send_static("app.js", "application/javascript; charset=utf-8")
        elif route.path == "/i18n.js":
            self._send_static("i18n.js", "application/javascript; charset=utf-8")
        elif route.path == "/api/scan":
            try:
                payload = _scan_payload(parse_qs(route.query))
            except (
                FileNotFoundError,
                NotADirectoryError,
                PermissionError,
                ValueError,
            ) as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            _register_scan(self.state, payload)
            self._send_json(payload)
        elif route.path == "/api/scan/status":
            job_id = parse_qs(route.query).get("job_id", [""])[0]
            if not job_id:
                self._send_json(
                    {"error": "분석 작업 식별자가 필요합니다."},
                    status=400,
                )
                return
            try:
                payload = self.state.scan_status(job_id)
            except _UnknownScanJob as exc:
                self._send_json({"error": str(exc)}, status=404)
                return
            self._send_json(payload)
        elif route.path == "/api/apps":
            payload = _apps_payload()
            _register_apps(self.state, payload)
            self._send_json(payload)
        elif route.path == "/api/quarantine":
            try:
                items = engine.list_quarantine()
            except engine.EngineRecoveryError as exc:
                self._send_json({"error": str(exc)}, status=500)
                return
            self._send_json({"items": [r.to_dict() for r in items]})
        elif route.path == "/api/diagnostics":
            self._send_json(
                diagnostics.diagnose_environment(
                    server_host=str(self.server.server_address[0])
                )
            )
        elif route.path == "/api/space-tree":
            query_path = parse_qs(route.query).get("path", [""])[0]
            target = Path(query_path).expanduser() if query_path else Path.home() / "Downloads"
            try:
                from .scanner import build_space_tree
                payload = build_space_tree(target)
            except (FileNotFoundError, PermissionError, ValueError) as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            self._send_json(payload)
        elif route.path == "/api/system-status":
            self._send_json(diagnostics.get_system_metrics())
        elif route.path == "/api/similar-photos":
            qs = parse_qs(route.query)
            query_path = qs.get("path", [""])[0]
            target = Path(query_path).expanduser() if query_path else Path.home()
            min_kb = int(qs.get("min_kb", ["100"])[0])
            try:
                from .photos import find_similar_photos

                payload = find_similar_photos(target, min_bytes=min_kb * 1024)
            except (ValueError, OSError) as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            _register_photos(self.state, payload)
            self._send_json(payload)
        elif route.path == "/api/file-signals":
            qs = parse_qs(route.query)
            target = qs.get("path", [""])[0]
            if not target:
                self._send_json({"error": "경로가 필요합니다."}, status=400)
                return
            try:
                from .signals import collect_signals

                payload = collect_signals(target)
            except Exception as exc:  # SignalError 포함 — 읽기 전용이라 안전
                self._send_json({"error": str(exc)}, status=400)
                return
            self._send_json(payload)
        elif route.path == "/api/startup-items":
            try:
                from .startup import list_startup_items

                payload = list_startup_items()
            except (ValueError, OSError) as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            _register_startup(self.state, payload)
            self._send_json(payload)
        elif route.path == "/api/large-files":
            qs = parse_qs(route.query)
            query_path = qs.get("path", [""])[0]
            target = Path(query_path).expanduser() if query_path else Path.home()
            min_mb = int(qs.get("min_mb", ["50"])[0])
            limit = min(int(qs.get("limit", ["100"])[0]), 500)
            try:
                from .scanner import find_large_files
                payload = find_large_files(
                    target, min_bytes=min_mb * 1024 * 1024, limit=limit
                )
            # OSError 계열(네트워크 볼륨 타임아웃 등)까지 잡아, 응답 없이
            # 연결이 끊기는 대신 이유를 돌려준다.
            except (ValueError, OSError) as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            self._send_json(payload)
        elif route.path == "/api/browser-caches":
            try:
                from .browsers import scan_browser_caches
                self._send_json(scan_browser_caches())
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)
        elif route.path == "/api/schedule":
            from .scheduler import load_schedule, to_dict
            self._send_json(to_dict(load_schedule()))
        elif route.path == "/api/app-icon":
            app_path = parse_qs(route.query).get("path", [""])[0]
            if not app_path:
                self._send_json({"error": "path 파라미터가 필요합니다."}, status=400)
                return
            from .icons import get_icon_bytes
            icon_data = get_icon_bytes(app_path)
            if icon_data:
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(icon_data)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(icon_data)
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path)
        try:
            body = self._read_json_body()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            self._send_json({"error": f"잘못된 요청 본문: {exc}"}, status=400)
            return

        if route.path == "/api/scan/start":
            try:
                params = _scan_params_from_body(body)
                payload = self.state.start_scan(params)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            except _ScanBusyError as exc:
                self._send_json({"error": str(exc)}, status=409)
                return
            self._send_json(payload, status=202)
        elif route.path == "/api/scan/cancel":
            job_id = body.get("job_id")
            if not isinstance(job_id, str) or not job_id:
                self._send_json(
                    {"error": "취소할 분석 작업 식별자가 필요합니다."},
                    status=400,
                )
                return
            try:
                payload = self.state.cancel_scan(job_id)
            except _UnknownScanJob as exc:
                self._send_json({"error": str(exc)}, status=404)
                return
            self._send_json(payload, status=202)
        elif route.path == "/api/open-system-settings":
            try:
                _open_system_settings()
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            except (OSError, subprocess.SubprocessError) as exc:
                self._send_json(
                    {"error": f"시스템 설정을 여는 중 오류가 발생했습니다: {exc}"},
                    status=500,
                )
                return
            self._send_json({"opened": True})
        elif route.path == "/api/reveal":
            action_id = body.get("action_id")
            scope = body.get("scope")
            if not isinstance(action_id, str) or not action_id:
                self._send_json(
                    {"error": "Finder에서 확인할 항목 식별자가 필요합니다."},
                    status=400,
                )
                return
            try:
                if scope == "visible":
                    items = self.state.resolve([action_id])
                    if len(items) != 1:
                        self._send_json(
                            {"error": "현재 화면에서 확인할 수 없는 항목입니다."},
                            status=400,
                        )
                        return
                    reveal_path = items[0][1]
                elif scope == "quarantine":
                    instance_token = body.get("instance_token")
                    if not isinstance(instance_token, str) or not instance_token:
                        self._send_json(
                            {"error": "격리 항목 식별 정보가 필요합니다."},
                            status=400,
                        )
                        return
                    reveal_path = _quarantine_path_for_reveal(
                        action_id, instance_token
                    )
                else:
                    self._send_json(
                        {"error": "Finder에서 확인할 항목 범위가 올바르지 않습니다."},
                        status=400,
                    )
                    return
                _reveal_in_finder(reveal_path)
            except engine.StaleSelectionError as exc:
                self._send_json({"error": str(exc)}, status=409)
                return
            except (FileNotFoundError, RuntimeError) as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            except (
                OSError,
                subprocess.SubprocessError,
            ) as exc:
                self._send_json(
                    {"error": f"Finder에서 위치를 여는 중 오류가 발생했습니다: {exc}"},
                    status=500,
                )
                return
            self._send_json({"revealed": True, "action_id": action_id})
        elif route.path == "/api/reclaim":
            if body.get("confirmed") is not True:
                self._send_json(
                    {"error": "화면에서 정리 대상을 확인한 뒤 다시 시도하세요."},
                    status=400,
                )
                return
            action_ids = [str(a) for a in body.get("action_ids", [])]
            items = self.state.resolve(action_ids)
            if not items:
                self._send_json(
                    {"error": "직전 스캔에서 찾을 수 있는 항목이 없습니다."},
                    status=400,
                )
                return
            try:
                outcome = engine.quarantine(items)
            except engine.EngineRecoveryError as exc:
                self._send_json({"error": str(exc)}, status=500)
                return
            if outcome.moved:
                notifier.notify_quarantine_action(
                    restored=False,
                    item_count=len(outcome.moved),
                    total_bytes=outcome.quarantined_bytes,
                )
            self._send_json(outcome.to_dict())
        elif route.path == "/api/restore":
            action_id = body.get("action_id")
            instance_token = body.get("instance_token")
            if (
                not isinstance(action_id, str)
                or not action_id
                or not isinstance(instance_token, str)
                or not instance_token
            ):
                self._send_json(
                    {"error": "복원할 격리 항목 식별 정보가 필요합니다."},
                    status=400,
                )
                return
            try:
                record = engine.restore(action_id, instance_token=instance_token)
            except engine.StaleSelectionError as exc:
                self._send_json({"error": str(exc)}, status=409)
                return
            except engine.EngineRecoveryError as exc:
                self._send_json({"error": str(exc)}, status=500)
                return
            except (KeyError, FileNotFoundError, FileExistsError) as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            except OSError as exc:
                self._send_json({"error": f"복원 중 오류가 발생했습니다: {exc}"}, status=500)
                return
            notifier.notify_quarantine_action(
                restored=True,
                item_count=1,
                total_bytes=record.allocated_bytes,
            )
            self._send_json(record.to_dict())
        elif route.path == "/api/empty":
            if body.get("confirmed") is not True:
                self._send_json(
                    {
                        "error": "휴지통으로 옮길 항목을 확인한 뒤 "
                        "다시 시도하세요."
                    },
                    status=400,
                )
                return
            try:
                selections = _empty_selections(body)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            try:
                emptied = engine.empty_quarantine(selections=selections)
            except engine.StaleSelectionError as exc:
                self._send_json({"error": str(exc)}, status=409)
                return
            except engine.EngineRecoveryError as exc:
                self._send_json({"error": str(exc)}, status=500)
                return
            except OSError as exc:
                self._send_json(
                    {"error": f"휴지통 이동 중 오류가 발생했습니다: {exc}"},
                    status=500,
                )
                return
            self._send_json(
                {"emptied": [r.to_dict() for r in emptied], "count": len(emptied)}
            )
        elif route.path == "/api/schedule":
            from .scheduler import from_dict, save_schedule, to_dict
            from .launchd_agent import install_launchd_agent, uninstall_launchd_agent
            config = from_dict(body)
            save_schedule(config)
            if config.enabled:
                install_launchd_agent(config.interval_hours)
            else:
                uninstall_launchd_agent()
            self._send_json(to_dict(config))
        else:
            self.send_error(404)


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    handler = type("_BoundHandler", (_Handler,), {"state": _State()})
    server = ThreadingHTTPServer((host, port), handler)
    parent_stop = threading.Event()
    parent_watch: threading.Thread | None = None
    if (parent_pid := _desktop_parent_pid()) is not None:
        parent_watch = threading.Thread(
            target=_watch_desktop_parent,
            args=(server, parent_pid, parent_stop),
            name="spacekeeper-parent-watch",
            daemon=True,
        )
        parent_watch.start()
    print(f"Spacekeeper 대시보드: http://{host}:{port}")
    print("종료하려면 Ctrl+C 를 누르세요.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")
    finally:
        parent_stop.set()
        server.server_close()
        if parent_watch is not None:
            parent_watch.join(timeout=1)
