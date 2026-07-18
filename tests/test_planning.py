from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from spacekeeper.cli import main
from spacekeeper.models import ScanOptions
from spacekeeper.planning import build_cleanup_plan, render_cleanup_plan
from spacekeeper.scanner import scan


class CleanupPlanningTests(unittest.TestCase):
    def _scan_fixture(self, root: Path):
        dependency = root / "project" / "node_modules" / "pkg" / "index.js"
        dependency.parent.mkdir(parents=True)
        dependency.write_bytes(b"dependency-cache")

        model = root / ".ollama" / "models" / "blobs" / "model"
        model.parent.mkdir(parents=True)
        model.write_bytes(b"model-data")
        return scan(ScanOptions(roots=(root,)))

    def test_plan_filters_risk_and_uses_stable_unselected_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._scan_fixture(Path(temp_dir))

            first = build_cleanup_plan(result, risks={"low"}, limit=10)
            second = build_cleanup_plan(result, risks={"low"}, limit=10)

            self.assertEqual(len(first.entries), 1)
            self.assertEqual(first.entries[0].risk, "low")
            self.assertFalse(first.entries[0].selected)
            self.assertTrue(first.entries[0].action_id.startswith("C-"))
            self.assertEqual(first.entries[0].action_id, second.entries[0].action_id)
            self.assertTrue(first.to_dict()["safety"]["preview_only"])
            self.assertEqual(first.to_dict()["safety"]["files_moved"], 0)

    def test_plan_limit_reports_omitted_matching_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._scan_fixture(Path(temp_dir))

            plan = build_cleanup_plan(
                result,
                risks={"low", "medium", "high"},
                limit=1,
            )

            self.assertEqual(len(plan.entries), 1)
            self.assertEqual(plan.omitted_plan_entries, 1)
            self.assertIn("--top", render_cleanup_plan(plan))

    def test_cli_json_plan_is_preview_only_and_does_not_modify_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = self._scan_fixture(root)
            candidate = Path(result.cache_candidates[0].path)
            before = candidate.stat()
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(
                    [str(root), "--plan", "--risk", "all", "--json", "--top", "5"]
                )

            payload = json.loads(output.getvalue())
            after = candidate.stat()
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["mode"], "preview_only")
            self.assertEqual(payload["safety"]["files_deleted"], 0)
            self.assertEqual(before.st_ino, after.st_ino)
            self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)


if __name__ == "__main__":
    unittest.main()
