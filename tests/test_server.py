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
            "JOURNAL_PATH": quarantine / "operation.json",
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

    def _post(
        self, payload: object, path: str = "/api/reclaim"
    ) -> tuple[int, dict]:
        request = Request(
            self.base_url + path,
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

    def _active_empty_items(self) -> list[dict[str, str]]:
        return [
            {
                "action_id": record.action_id,
                "instance_token": record.instance_token,
            }
            for record in engine.list_quarantine()
        ]

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

    def test_reveal_opens_only_registered_existing_path_in_finder(self) -> None:
        with (
            mock.patch.object(server.sys, "platform", "darwin"),
            mock.patch.object(server.subprocess, "run") as run,
        ):
            status, payload = self._post(
                {"action_id": "C-test", "scope": "visible"},
                path="/api/reveal",
            )

        self.assertEqual(status, 200)
        self.assertTrue(payload["revealed"])
        run.assert_called_once_with(
            ["open", "-R", str(self.target)],
            check=True,
            stdout=server.subprocess.DEVNULL,
            stderr=server.subprocess.PIPE,
            text=True,
            timeout=server._REVEAL_TIMEOUT_SECONDS,
        )

    def test_reveal_rejects_unregistered_action_id(self) -> None:
        with mock.patch.object(server.subprocess, "run") as run:
            status, payload = self._post(
                {"action_id": "C-missing", "scope": "visible"},
                path="/api/reveal",
            )

        self.assertEqual(status, 400)
        self.assertIn("현재 화면", payload["error"])
        run.assert_not_called()

    def test_reveal_rejects_path_that_no_longer_exists(self) -> None:
        (self.target / "file.bin").unlink()
        self.target.rmdir()
        with (
            mock.patch.object(server.sys, "platform", "darwin"),
            mock.patch.object(server.subprocess, "run") as run,
        ):
            status, payload = self._post(
                {"action_id": "C-test", "scope": "visible"},
                path="/api/reveal",
            )

        self.assertEqual(status, 400)
        self.assertIn("사라져", payload["error"])
        run.assert_not_called()

    def test_reveal_current_quarantine_instance_uses_stored_path(self) -> None:
        self._post({"action_ids": ["C-test"], "confirmed": True})
        current = engine.list_quarantine()[0]
        with (
            mock.patch.object(server.sys, "platform", "darwin"),
            mock.patch.object(server.subprocess, "run") as run,
        ):
            status, payload = self._post(
                {
                    "action_id": current.action_id,
                    "instance_token": current.instance_token,
                    "scope": "quarantine",
                },
                path="/api/reveal",
            )

        self.assertEqual(status, 200)
        self.assertTrue(payload["revealed"])
        self.assertEqual(run.call_args.args[0], ["open", "-R", current.stored_path])

    def test_reveal_rejects_stale_quarantine_instance(self) -> None:
        self._post({"action_ids": ["C-test"], "confirmed": True})
        current = engine.list_quarantine()[0]
        with mock.patch.object(server.subprocess, "run") as run:
            status, payload = self._post(
                {
                    "action_id": current.action_id,
                    "instance_token": "stale-token",
                    "scope": "quarantine",
                },
                path="/api/reveal",
            )

        self.assertEqual(status, 409)
        self.assertIn("새로고침", payload["error"])
        run.assert_not_called()

    def test_scan_payload_honors_excluded_paths(self) -> None:
        payload = server._scan_payload(
            {"paths": [str(self.root)], "exclude": [str(self.target)]}
        )

        self.assertEqual(payload["scanned_files"], 0)
        self.assertEqual(payload["skipped"]["excluded_paths"], 1)
        self.assertIn(str(self.target), payload["excluded_paths"])

    def test_scan_payload_reports_entries_omitted_by_display_limit(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index in range(server._PLAN_LIMIT + 1):
                (root / f"candidate-{index}.bin").write_bytes(b"candidate")

            payload = server._scan_payload(
                {"paths": [str(root)], "large_mb": ["0"]}
            )

        self.assertEqual(payload["candidate_count"], server._PLAN_LIMIT + 1)
        self.assertEqual(payload["displayed_entry_count"], server._PLAN_LIMIT)
        self.assertEqual(payload["omitted_entries"], 1)

    def test_empty_requires_confirmation_and_selected_ids(self) -> None:
        self._post({"action_ids": ["C-test"], "confirmed": True})

        status, payload = self._post({}, path="/api/empty")

        self.assertEqual(status, 400)
        self.assertIn("확인", payload["error"])
        self.assertEqual(
            [record.action_id for record in engine.list_quarantine()],
            ["C-test"],
        )

    def test_empty_moves_only_selected_quarantine_items_to_trash(self) -> None:
        self._post({"action_ids": ["C-test"], "confirmed": True})

        status, payload = self._post(
            {"items": self._active_empty_items(), "confirmed": True},
            path="/api/empty",
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(engine.list_quarantine(), [])
        self.assertTrue(any(engine.TRASH_ROOT.iterdir()))

    def test_empty_rejects_stale_action_ids_without_moving_active_item(self) -> None:
        self._post({"action_ids": ["C-test"], "confirmed": True})

        status, _payload = self._post(
            {
                "items": [
                    {"action_id": "missing", "instance_token": "stale-token"}
                ],
                "confirmed": True,
            },
            path="/api/empty",
        )

        self.assertEqual(status, 409)
        self.assertEqual(
            [record.action_id for record in engine.list_quarantine()],
            ["C-test"],
        )

    def test_empty_rejects_malformed_items(self) -> None:
        self._post({"action_ids": ["C-test"], "confirmed": True})

        status, payload = self._post(
            {"items": None, "confirmed": True},
            path="/api/empty",
        )

        self.assertEqual(status, 400)
        self.assertIn("항목", payload["error"])
        self.assertEqual(len(engine.list_quarantine()), 1)

    def test_post_rejects_non_object_json(self) -> None:
        status, payload = self._post([], path="/api/empty")

        self.assertEqual(status, 400)
        self.assertIn("JSON 객체", payload["error"])

    def test_empty_selection_parser_accepts_more_than_scan_display_limit(self) -> None:
        items = [
            {"action_id": f"C-{index}", "instance_token": f"token-{index}"}
            for index in range(server._PLAN_LIMIT + 1)
        ]

        selections = server._empty_selections({"items": items})

        self.assertEqual(len(selections), server._PLAN_LIMIT + 1)

    def test_empty_rejects_previous_instance_of_same_action_id(self) -> None:
        self._post({"action_ids": ["C-test"], "confirmed": True})
        first = engine.list_quarantine()[0]
        engine.restore("C-test")
        self._post({"action_ids": ["C-test"], "confirmed": True})
        second = engine.list_quarantine()[0]

        status, _payload = self._post(
            {
                "items": [
                    {
                        "action_id": first.action_id,
                        "instance_token": first.instance_token,
                    }
                ],
                "confirmed": True,
            },
            path="/api/empty",
        )

        self.assertNotEqual(first.instance_token, second.instance_token)
        self.assertEqual(status, 409)
        self.assertEqual(
            [record.instance_token for record in engine.list_quarantine()],
            [second.instance_token],
        )

    def test_restore_rejects_previous_instance_of_same_action_id(self) -> None:
        self._post({"action_ids": ["C-test"], "confirmed": True})
        first = engine.list_quarantine()[0]
        engine.restore("C-test")
        self._post({"action_ids": ["C-test"], "confirmed": True})
        second = engine.list_quarantine()[0]

        status, _payload = self._post(
            {
                "action_id": first.action_id,
                "instance_token": first.instance_token,
            },
            path="/api/restore",
        )

        self.assertNotEqual(first.instance_token, second.instance_token)
        self.assertEqual(status, 409)
        self.assertEqual(
            [record.instance_token for record in engine.list_quarantine()],
            [second.instance_token],
        )

    def test_restore_accepts_current_instance_token(self) -> None:
        self._post({"action_ids": ["C-test"], "confirmed": True})
        current = engine.list_quarantine()[0]

        status, payload = self._post(
            {
                "action_id": current.action_id,
                "instance_token": current.instance_token,
            },
            path="/api/restore",
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "restored")
        self.assertTrue(self.target.exists())
        self.assertEqual(engine.list_quarantine(), [])


if __name__ == "__main__":
    unittest.main()
