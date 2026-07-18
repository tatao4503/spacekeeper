from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from spacekeeper.models import ScanOptions
from spacekeeper.report import format_bytes, render_text
from spacekeeper.scanner import scan


class ScannerTests(unittest.TestCase):
    def test_classifies_cache_large_and_old_download(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_file = root / "project" / "node_modules" / "pkg" / "index.js"
            cache_file.parent.mkdir(parents=True)
            cache_file.write_bytes(b"cache")

            large_file = root / "movie.mov"
            large_file.write_bytes(b"x" * 128)

            old_download = root / "Downloads" / "old.txt"
            old_download.parent.mkdir()
            old_download.write_text("old", encoding="utf-8")
            old_timestamp = time.time() - 400 * 86400
            os.utime(old_download, (old_timestamp, old_timestamp))

            result = scan(
                ScanOptions(
                    roots=(root,),
                    large_bytes=100,
                    old_days=180,
                    now=time.time(),
                )
            )

            self.assertEqual(result.scanned_files, 3)
            self.assertEqual(len(result.cache_candidates), 1)
            self.assertTrue(result.cache_candidates[0].path.endswith("node_modules"))
            categories = {item.category for item in result.file_candidates}
            self.assertIn("large_file", categories)
            self.assertIn("old_download", categories)

    def test_does_not_follow_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "target"
            target.mkdir()
            (target / "file.txt").write_text("once", encoding="utf-8")
            (root / "alias").symlink_to(target, target_is_directory=True)

            result = scan(ScanOptions(roots=(root,)))

            self.assertEqual(result.scanned_files, 1)
            self.assertEqual(result.skipped_symlinks, 1)

    def test_finds_only_exact_duplicates_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a.bin").write_bytes(b"same-content")
            (root / "b.bin").write_bytes(b"same-content")
            (root / "c.bin").write_bytes(b"other-content")

            result = scan(
                ScanOptions(
                    roots=(root,),
                    find_duplicates=True,
                    duplicate_min_bytes=1,
                )
            )

            self.assertEqual(len(result.duplicate_groups), 1)
            self.assertEqual(result.duplicate_groups[0].reclaimable_bytes, 12)
            self.assertEqual(len(result.duplicate_groups[0].paths), 2)

    def test_nested_roots_are_scanned_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            child = root / "child"
            child.mkdir()
            (child / "one.txt").write_text("one", encoding="utf-8")

            result = scan(ScanOptions(roots=(child, root)))

            self.assertEqual(result.scanned_files, 1)
            self.assertEqual(result.roots, [str(root.resolve())])

    def test_top_limit_does_not_reduce_summary_totals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "one.bin").write_bytes(b"1111")
            (root / "two.bin").write_bytes(b"2222")

            result = scan(
                ScanOptions(roots=(root,), large_bytes=1, top=1)
            )

            self.assertEqual(len(result.file_candidates), 1)
            self.assertEqual(result.file_candidate_count, 2)
            self.assertEqual(result.review_candidate_bytes, 8)
            self.assertIn("1개 생략", render_text(result))

    def test_report_and_json_declare_read_only_safety(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = scan(ScanOptions(roots=(Path(temp_dir),)))

            self.assertIn("읽기 전용", render_text(result))
            payload = json.loads(json.dumps(result.to_dict()))
            self.assertTrue(payload["safety"]["read_only"])
            self.assertFalse(payload["safety"]["network_used"])

    def test_format_bytes(self) -> None:
        self.assertEqual(format_bytes(1024), "1.0 KB")
        self.assertEqual(format_bytes(1024 * 1024), "1.0 MB")


if __name__ == "__main__":
    unittest.main()
