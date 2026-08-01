from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest import mock

from spacekeeper import scanner
from spacekeeper.models import ScanOptions
from spacekeeper.report import format_bytes, render_text
from spacekeeper.scanner import _allocated_size, find_large_files, scan


class ScannerTests(unittest.TestCase):
    def test_reports_scan_progress_without_changing_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "one.bin").write_bytes(b"progress")
            updates: list[dict[str, object]] = []

            result = scan(
                ScanOptions(roots=(root,), large_bytes=1),
                progress_callback=updates.append,
            )

        self.assertEqual(result.scanned_files, 1)
        self.assertEqual(updates[0]["phase"], "scanning")
        self.assertEqual(updates[-1]["phase"], "finalizing")
        self.assertEqual(updates[-1]["scanned_files"], 1)
        self.assertEqual(updates[-1]["candidates_found"], 1)

    def test_honors_preexisting_scan_cancellation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "one.bin").write_bytes(b"cancel")
            cancel_event = Event()
            cancel_event.set()

            with self.assertRaises(scanner.ScanCancelled):
                scan(ScanOptions(roots=(root,)), cancel_event=cancel_event)

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

    def test_classifies_developer_caches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            
            # Docker data
            docker_file = root / "Library" / "Containers" / "com.docker.docker" / "Data" / "Docker.raw"
            docker_file.parent.mkdir(parents=True)
            docker_file.write_bytes(b"docker")

            # Xcode simulator
            sim_file = root / "Library" / "Developer" / "CoreSimulator" / "Devices" / "sim.id"
            sim_file.parent.mkdir(parents=True)
            sim_file.write_bytes(b"simulator")

            # Homebrew cache
            brew_file = root / "Library" / "Caches" / "Homebrew" / "downloads" / "pkg.tar"
            brew_file.parent.mkdir(parents=True)
            brew_file.write_bytes(b"homebrew")

            result = scan(ScanOptions(roots=(root,), large_bytes=100000))

            categories = {candidate.category for candidate in result.cache_candidates}
            self.assertIn("docker_data", categories)
            self.assertIn("xcode_simulator", categories)
            self.assertIn("homebrew_cache", categories)

    def test_simulator_devices_require_review_but_cache_is_low_risk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            devices_root = (
                root
                / "Library"
                / "Developer"
                / "CoreSimulator"
                / "Devices"
            )
            caches_root = (
                root
                / "Library"
                / "Developer"
                / "CoreSimulator"
                / "Caches"
            )
            devices_file = devices_root / "device-id" / "data.bin"
            caches_file = caches_root / "cache-id" / "data.bin"
            devices_file.parent.mkdir(parents=True)
            caches_file.parent.mkdir(parents=True)
            devices_file.write_bytes(b"device-data")
            caches_file.write_bytes(b"cache-data")

            result = scan(ScanOptions(roots=(root,)))
            by_path = {
                candidate.path: candidate
                for candidate in result.cache_candidates
            }

            self.assertEqual(
                by_path[str(devices_root.resolve())].risk,
                "medium",
            )
            self.assertEqual(
                by_path[str(caches_root.resolve())].risk,
                "low",
            )

    def test_build_space_tree_generates_hierarchy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sub = root / "subfolder"
            sub.mkdir()
            (sub / "file1.bin").write_bytes(b"x" * 100)
            (root / "file2.bin").write_bytes(b"y" * 50)

            tree = scanner.build_space_tree(root, max_depth=3)
            self.assertEqual(tree["kind"], "dir")
            self.assertEqual(tree["file_count"], 2)
            self.assertTrue(len(tree["children"]) >= 1)

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
            self.assertGreater(result.duplicate_groups[0].reclaimable_bytes, 0)
            self.assertEqual(result.duplicate_groups[0].logical_size_each, 12)
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
            self.assertEqual(
                result.review_candidate_bytes,
                result.file_candidates[0].size * result.file_candidate_count,
            )
            self.assertEqual(
                sum(result.candidate_bytes_by_risk.values()),
                result.review_candidate_bytes,
            )
            self.assertIn("1개 생략", render_text(result))

    def test_ignores_zero_byte_macos_metadata_as_cleanup_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            downloads = Path(temp_dir) / "Downloads"
            downloads.mkdir()
            metadata = downloads / ".localized"
            metadata.touch()
            old_timestamp = time.time() - 400 * 86400
            os.utime(metadata, (old_timestamp, old_timestamp))

            result = scan(
                ScanOptions(
                    roots=(downloads,),
                    old_days=180,
                    now=time.time(),
                )
            )

            self.assertEqual(result.scanned_files, 1)
            self.assertEqual(result.file_candidate_count, 0)
            self.assertEqual(result.review_candidate_bytes, 0)

    def test_skips_cloud_roots_unless_explicitly_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cloud = root / "Library" / "CloudStorage"
            cloud.mkdir(parents=True)
            (cloud / "remote.txt").write_text("remote", encoding="utf-8")

            home_result = scan(ScanOptions(roots=(root,)))
            explicit_result = scan(ScanOptions(roots=(cloud,)))

            self.assertEqual(home_result.scanned_files, 0)
            self.assertEqual(home_result.skipped_cloud_dirs, 1)
            self.assertEqual(explicit_result.scanned_files, 1)

    def test_skips_default_and_custom_excluded_subtrees(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            internal = root / ".spacekeeper"
            custom = root / "large-project"
            volume_trash = root / ".Trashes"
            sibling = root / "keep"
            for directory in (internal, custom, volume_trash, sibling):
                directory.mkdir()
                (directory / "data.bin").write_bytes(b"same-content")

            with mock.patch.object(
                scanner, "DEFAULT_EXCLUDED_ROOTS", (internal,)
            ):
                result = scan(
                    ScanOptions(
                        roots=(root,),
                        large_bytes=1,
                        find_duplicates=True,
                        duplicate_min_bytes=1,
                        excluded_paths=(custom,),
                    )
                )

            self.assertEqual(result.scanned_files, 1)
            self.assertEqual(result.skipped_excluded_paths, 3)
            self.assertEqual(result.duplicate_group_count, 0)
            self.assertEqual(
                [candidate.path for candidate in result.file_candidates],
                [str((sibling / "data.bin").resolve())],
            )
            self.assertEqual(
                set(result.excluded_paths),
                {str(internal.resolve()), str(custom.resolve())},
            )

    def test_skips_direct_scan_of_external_trash_descendant(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trash_user_dir = Path(temp_dir) / ".Trashes" / "501"
            trash_user_dir.mkdir(parents=True)
            (trash_user_dir / "discarded.bin").write_bytes(b"discarded")

            result = scan(ScanOptions(roots=(trash_user_dir,)))

            self.assertEqual(result.scanned_files, 0)
            self.assertEqual(result.skipped_excluded_paths, 1)

    def test_rust_target_is_grouped_as_build_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            target_file = project / "target" / "debug" / "artifact"
            target_file.parent.mkdir(parents=True)
            (project / "Cargo.toml").write_text("[package]", encoding="utf-8")
            target_file.write_bytes(b"build-output")

            result = scan(ScanOptions(roots=(project,)))

            self.assertEqual(result.cache_candidate_count, 1)
            self.assertEqual(result.cache_candidates[0].category, "rust_build")
            self.assertEqual(
                result.cache_candidates[0].path,
                str((project / "target").resolve()),
            )

    def test_allocated_size_uses_disk_blocks_including_zero(self) -> None:
        sparse_stat = SimpleNamespace(st_blocks=8, st_size=16 * 1024 * 1024)
        empty_sparse_stat = SimpleNamespace(st_blocks=0, st_size=16 * 1024 * 1024)

        self.assertEqual(_allocated_size(sparse_stat), 4096)
        self.assertEqual(_allocated_size(empty_sparse_stat), 0)

    def test_report_and_json_declare_read_only_safety(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = scan(ScanOptions(roots=(Path(temp_dir),)))

            self.assertIn("읽기 전용", render_text(result))
            self.assertIn("APFS", render_text(result))
            payload = json.loads(json.dumps(result.to_dict()))
            self.assertTrue(payload["safety"]["read_only"])
            self.assertFalse(payload["safety"]["network_used"])
            self.assertGreater(payload["volume_total_bytes"], 0)

    def test_format_bytes(self) -> None:
        self.assertEqual(format_bytes(1024), "1.0 KB")
        self.assertEqual(format_bytes(1024 * 1024), "1.0 MB")


if __name__ == "__main__":
    unittest.main()


class FindLargeFilesRobustnessTests(unittest.TestCase):
    """대용량 파일 탐색이 클라우드 폴더·순회 오류에 멈추지 않아야 한다."""

    def test_skips_cloud_container(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cloud = root / "Library" / "CloudStorage"
            (cloud / "Provider").mkdir(parents=True)
            (cloud / "Provider" / "big.bin").write_bytes(b"x" * 4096)
            plain = root / "Docs"
            plain.mkdir()
            (plain / "big.bin").write_bytes(b"y" * 4096)

            result = find_large_files(root, min_bytes=1, limit=10)
            paths = [item["path"] for item in result["files"]]
            self.assertTrue(any("Docs" in p for p in paths))
            self.assertFalse(
                any("CloudStorage" in p for p in paths),
                "클라우드 컨테이너는 건너뛰어야 한다",
            )

    def test_iteration_error_does_not_abort_scan(self) -> None:
        """순회 중 OSError 가 나도 나머지 결과는 반환된다."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "keep").mkdir()
            (root / "keep" / "big.bin").write_bytes(b"z" * 4096)

            real_scandir = os.scandir

            def flaky_scandir(path):
                iterator = real_scandir(path)
                if str(path).endswith("keep"):
                    return iterator

                class _Flaky:
                    def __enter__(self_inner):
                        return self_inner

                    def __exit__(self_inner, *args):
                        iterator.close()
                        return False

                    def __iter__(self_inner):
                        return self_inner

                    def __next__(self_inner):
                        entry = next(iterator)
                        if entry.name == "boom":
                            raise TimeoutError(60, "Operation timed out")
                        return entry

                return _Flaky()

            (root / "boom").mkdir()
            with mock.patch.object(os, "scandir", flaky_scandir):
                result = find_large_files(root, min_bytes=1, limit=10)
            self.assertIsInstance(result["files"], list)


class SpaceTreeRobustnessTests(unittest.TestCase):
    """트리맵이 클라우드 폴더로 내려가 멈추지 않아야 한다."""

    def test_marks_cloud_container_without_descending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cloud = root / "Library" / "CloudStorage"
            (cloud / "Provider").mkdir(parents=True)
            (cloud / "Provider" / "big.bin").write_bytes(b"x" * 4096)

            def boom(path):
                raise TimeoutError(60, "Operation timed out")

            tree = scanner.build_space_tree(root, max_depth=4)

            def find(node, name):
                if node["name"] == name:
                    return node
                for child in node.get("children", []):
                    hit = find(child, name)
                    if hit:
                        return hit
                return None

            node = find(tree, "CloudStorage")
            self.assertIsNotNone(node, "CloudStorage 노드는 존재해야 한다")
            self.assertEqual(node["skipped"], "cloud")
            self.assertEqual(node["children"], [])
