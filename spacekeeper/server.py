"""Local dashboard server.

127.0.0.1에만 바인딩하는 단일 사용자용 로컬 서버입니다. 정리(격리) 요청은
직전 스캔에서 나온 action_id에 대해서만 처리하므로, API로 임의 경로를
넘겨 파일을 옮기는 일은 불가능합니다.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import engine
from .apps import scan_apps
from .models import ScanOptions
from .planning import _action_id, build_cleanup_plan
from .report import format_bytes
from .scanner import scan

STATIC_DIR = Path(__file__).parent / "web"
_PLAN_LIMIT = 500


class _State:
    """직전에 표시한 action_id → (path, kind)만 정리를 허용한다.

    임의 경로를 API로 넘겨 파일을 옮기는 것을 막는 방어선이다. 각 화면
    (대시보드/중복/앱)이 표시한 항목만 버킷에 등록해 둔다.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, dict[str, tuple[str, str]]] = {}

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


def _scan_payload(params: dict[str, list[str]]) -> dict:
    raw_paths = params.get("paths", [])
    roots = tuple(Path(p) for p in raw_paths if p.strip()) or (
        Path.home() / "Downloads",
    )
    large_mb = int(params.get("large_mb", ["500"])[0])
    old_days = int(params.get("old_days", ["180"])[0])
    duplicates = params.get("duplicates", ["0"])[0] in ("1", "true", "on")
    include_cloud = params.get("include_cloud", ["0"])[0] in ("1", "true", "on")

    options = ScanOptions(
        roots=roots,
        large_bytes=large_mb * 1024 * 1024,
        old_days=old_days,
        top=_PLAN_LIMIT,
        find_duplicates=duplicates,
        include_cloud_storage=include_cloud,
    )
    result = scan(options)
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
        "duplicate_reclaimable_bytes": result.duplicate_reclaimable_bytes,
        "entries": entries,
        "duplicates": duplicates,
        "skipped": {
            "permission_denied": result.permission_denied,
            "symlinks": result.skipped_symlinks,
            "cloud_dirs": result.skipped_cloud_dirs,
        },
    }
    return payload


def _register_scan(state: "_State", payload: dict) -> None:
    pairs = [(e["action_id"], e["path"], e["kind"]) for e in payload["entries"]]
    for group in payload["duplicates"]:
        pairs.extend((f["action_id"], f["path"], "file") for f in group["files"])
    state.register("scan", pairs)


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
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path)
        if route.path in ("/", "/index.html"):
            self._send_static("index.html", "text/html; charset=utf-8")
        elif route.path == "/style.css":
            self._send_static("style.css", "text/css; charset=utf-8")
        elif route.path == "/app.js":
            self._send_static("app.js", "application/javascript; charset=utf-8")
        elif route.path == "/api/scan":
            try:
                payload = _scan_payload(parse_qs(route.query))
            except (FileNotFoundError, NotADirectoryError, PermissionError) as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            _register_scan(self.state, payload)
            self._send_json(payload)
        elif route.path == "/api/apps":
            payload = _apps_payload()
            _register_apps(self.state, payload)
            self._send_json(payload)
        elif route.path == "/api/quarantine":
            self._send_json(
                {"items": [r.to_dict() for r in engine.list_quarantine()]}
            )
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path)
        try:
            body = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json({"error": "잘못된 요청 본문"}, status=400)
            return

        if route.path == "/api/reclaim":
            action_ids = [str(a) for a in body.get("action_ids", [])]
            items = self.state.resolve(action_ids)
            if not items:
                self._send_json(
                    {"error": "직전 스캔에서 찾을 수 있는 항목이 없습니다."},
                    status=400,
                )
                return
            outcome = engine.quarantine(items)
            self._send_json(outcome.to_dict())
        elif route.path == "/api/restore":
            action_id = str(body.get("action_id", ""))
            try:
                record = engine.restore(action_id)
            except (KeyError, FileNotFoundError, FileExistsError) as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            self._send_json(record.to_dict())
        elif route.path == "/api/empty":
            emptied = engine.empty_quarantine()
            self._send_json(
                {"emptied": [r.to_dict() for r in emptied], "count": len(emptied)}
            )
        else:
            self.send_error(404)


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    handler = type("_BoundHandler", (_Handler,), {"state": _State()})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Spacekeeper 대시보드: http://{host}:{port}")
    print("종료하려면 Ctrl+C 를 누르세요.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")
    finally:
        server.server_close()
