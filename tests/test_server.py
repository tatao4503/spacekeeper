from __future__ import annotations

import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest import mock

from spacekeeper import engine, server


class ServerSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.target = self.root / "candidate"
        self.target.mkdir()
        (self.target / "file.bin").write_bytes(b"temporary-test-data")

        quarantine = self.root / ".spacekeeper" / "quarantine"
        patches = {
            "QUARANTINE_ROOT": quarantine,
            "MANIFEST_PATH": quarantine / "manifest.jsonl",
            "TRASH_ROOT": self.root / ".Trash",
            "_EXTRA_ALLOWED_ROOTS": (self.root,),
            "_PROTECTED_ROOTS": (),
        }
        for name, value in patches.items():
            patcher = mock.patch.object(engine, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        state = server._State()
        state.register(
            "scan", [("C-test", str(self.target), "cache_directory")]
        )
        handler = type("_TestHandler", (server._Handler,), {"state": state})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.httpd.server_address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        self._tmp.cleanup()

    def _post(self, payload: dict) -> tuple[int, dict]:
        request = Request(
            self.base_url + "/api/reclaim",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=2) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            try:
                return exc.code, json.load(exc)
            finally:
                exc.close()

    def test_reclaim_requires_explicit_confirmation(self) -> None:
        status, payload = self._post({"action_ids": ["C-test"]})

        self.assertEqual(status, 400)
        self.assertIn("확인", payload["error"])
        self.assertTrue(self.target.exists())

    def test_confirmed_reclaim_reports_quarantine_not_freed_space(self) -> None:
        status, payload = self._post(
            {"action_ids": ["C-test"], "confirmed": True}
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["moved_count"], 1)
        self.assertGreater(payload["quarantined_bytes"], 0)
        self.assertEqual(payload["disk_space_freed_bytes"], 0)
        self.assertFalse(self.target.exists())


if __name__ == "__main__":
    unittest.main()
