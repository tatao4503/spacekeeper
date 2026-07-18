from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from spacekeeper import engine


class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.quarantine = self.home / ".spacekeeper" / "quarantine"
        self.trash = self.home / ".Trash"
        patches = {
            "QUARANTINE_ROOT": self.quarantine,
            "MANIFEST_PATH": self.quarantine / "manifest.jsonl",
            "JOURNAL_PATH": self.quarantine / "operation.json",
            "TRASH_ROOT": self.trash,
            "_PROTECTED_ROOTS": (self.home / ".ssh",),
        }
        for name, value in patches.items():
            patcher = mock.patch.object(engine, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        home_patch = mock.patch.object(engine.Path, "home", classmethod(lambda cls: self.home))
        home_patch.start()
        self.addCleanup(home_patch.stop)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _make_dir(self, rel: str, payload: bytes = b"data") -> Path:
        path = self.home / rel
        path.mkdir(parents=True)
        (path / "file.bin").write_bytes(payload)
        return path

    def test_quarantine_then_restore_round_trip(self) -> None:
        target = self._make_dir("Desktop/proj/node_modules")
        outcome = engine.quarantine([("F-abc", str(target), "cache_directory")])

        self.assertEqual(len(outcome.moved), 1)
        self.assertFalse(target.exists())
        self.assertGreater(outcome.quarantined_bytes, 0)
        self.assertEqual(outcome.to_dict()["disk_space_freed_bytes"], 0)
        self.assertNotIn("freed_bytes", outcome.to_dict())
        self.assertEqual(len(engine.list_quarantine()), 1)

        restored = engine.restore("F-abc")
        self.assertEqual(restored.status, "restored")
        self.assertTrue(target.exists())
        self.assertTrue((target / "file.bin").exists())
        self.assertEqual(len(engine.list_quarantine()), 0)

    def test_refuses_symlink_and_outside_home(self) -> None:
        real = self._make_dir("Desktop/real")
        link = self.home / "Desktop" / "link"
        link.symlink_to(real)
        with TemporaryDirectory() as outside:
            outside_dir = Path(outside) / "x"
            outside_dir.mkdir()
            outcome = engine.quarantine(
                [
                    ("F-link", str(link), "file"),
                    ("F-out", str(outside_dir), "file"),
                ]
            )
        self.assertEqual(len(outcome.moved), 0)
        self.assertEqual(len(outcome.skipped), 2)
        self.assertTrue(real.exists())

    def test_double_quarantine_is_skipped(self) -> None:
        target = self._make_dir("Desktop/proj/.next")
        engine.quarantine([("F-next", str(target), "cache_directory")])
        again = self._make_dir("Desktop/proj/.next")  # recreated
        outcome = engine.quarantine([("F-next", str(again), "cache_directory")])
        self.assertEqual(len(outcome.moved), 0)
        self.assertEqual(len(outcome.skipped), 1)

    def test_empty_moves_to_trash(self) -> None:
        target = self._make_dir("Desktop/proj/target")
        engine.quarantine([("F-t", str(target), "cache_directory")])
        emptied = engine.empty_quarantine()
        self.assertEqual(len(emptied), 1)
        self.assertEqual(len(engine.list_quarantine()), 0)
        self.assertTrue(any(self.trash.iterdir()))

    def test_empty_can_target_selected_instances(self) -> None:
        first = self._make_dir("Desktop/proj/first")
        second = self._make_dir("Desktop/proj/second")
        outcome = engine.quarantine(
            [
                ("F-first", str(first), "cache_directory"),
                ("F-second", str(second), "cache_directory"),
            ]
        )
        first_record = next(
            record for record in outcome.moved if record.action_id == "F-first"
        )

        emptied = engine.empty_quarantine(
            selections={"F-first": first_record.instance_token}
        )

        self.assertEqual([record.action_id for record in emptied], ["F-first"])
        self.assertEqual(
            [record.action_id for record in engine.list_quarantine()],
            ["F-second"],
        )
        self.assertTrue((self.quarantine / "F-second__second").exists())

    def test_empty_rejects_token_from_previous_quarantine_instance(self) -> None:
        target = self._make_dir("Desktop/proj/reused")
        first = engine.quarantine(
            [("F-reused", str(target), "cache_directory")]
        ).moved[0]
        engine.restore("F-reused")
        second = engine.quarantine(
            [("F-reused", str(target), "cache_directory")]
        ).moved[0]

        self.assertNotEqual(first.instance_token, second.instance_token)
        with self.assertRaises(engine.StaleSelectionError):
            engine.empty_quarantine(
                selections={"F-reused": first.instance_token}
            )

        active = engine.list_quarantine()
        self.assertEqual([record.instance_token for record in active], [second.instance_token])
        self.assertFalse(any(self.trash.iterdir()))

    def test_recovers_quarantine_after_manifest_write_failure(self) -> None:
        target = self._make_dir("Desktop/proj/interrupted")

        with mock.patch.object(
            engine, "_write_records", side_effect=OSError("simulated failure")
        ):
            with self.assertRaises(engine.EngineRecoveryError):
                engine.quarantine(
                    [("F-interrupted", str(target), "cache_directory")]
                )

        stored = self.quarantine / "F-interrupted__interrupted"
        self.assertFalse(target.exists())
        self.assertTrue(stored.exists())
        self.assertTrue(engine.JOURNAL_PATH.exists())

        recovered = engine.list_quarantine()
        self.assertEqual([record.action_id for record in recovered], ["F-interrupted"])
        self.assertFalse(engine.JOURNAL_PATH.exists())
        self.assertTrue(engine.MANIFEST_PATH.exists())

        engine.restore("F-interrupted")
        self.assertTrue(target.exists())

    def test_recovers_restore_after_manifest_write_failure(self) -> None:
        target = self._make_dir("Desktop/proj/restore-interrupted")
        engine.quarantine([("F-restore", str(target), "cache_directory")])

        with mock.patch.object(
            engine, "_write_records", side_effect=OSError("simulated failure")
        ):
            with self.assertRaises(engine.EngineRecoveryError):
                engine.restore("F-restore")

        self.assertTrue(target.exists())
        self.assertTrue(engine.JOURNAL_PATH.exists())
        self.assertEqual(engine.list_quarantine(), [])
        self.assertFalse(engine.JOURNAL_PATH.exists())

    def test_failed_move_clears_unstarted_journal(self) -> None:
        target = self._make_dir("Desktop/proj/move-failure")

        def fail_after_journal(*_args: str) -> None:
            self.assertTrue(engine.JOURNAL_PATH.exists())
            raise OSError("simulated failure")

        with mock.patch.object(engine.shutil, "move", side_effect=fail_after_journal):
            outcome = engine.quarantine(
                [("F-move-failure", str(target), "cache_directory")]
            )

        self.assertEqual(outcome.moved, [])
        self.assertEqual(len(outcome.skipped), 1)
        self.assertTrue(target.exists())
        self.assertFalse(engine.JOURNAL_PATH.exists())
        self.assertEqual(engine.list_quarantine(), [])

    def test_ambiguous_recovery_preserves_both_paths(self) -> None:
        source = self._make_dir("Desktop/proj/ambiguous")
        destination = self.quarantine / "F-ambiguous__ambiguous"
        destination.mkdir(parents=True)
        record = engine.QuarantineRecord(
            action_id="F-ambiguous",
            original_path=str(source),
            stored_path=str(destination),
            allocated_bytes=1,
            kind="cache_directory",
            quarantined_at=1.0,
        )
        engine._write_journal("quarantine", source, destination, record)

        with self.assertRaises(engine.EngineRecoveryError):
            engine.list_quarantine()

        self.assertTrue(source.exists())
        self.assertTrue(destination.exists())
        self.assertTrue(engine.JOURNAL_PATH.exists())

    def test_recovers_empty_after_manifest_write_failure(self) -> None:
        target = self._make_dir("Desktop/proj/empty-interrupted")
        engine.quarantine([("F-empty", str(target), "cache_directory")])

        with mock.patch.object(
            engine, "_write_records", side_effect=OSError("simulated failure")
        ):
            with self.assertRaises(engine.EngineRecoveryError):
                engine.empty_quarantine()

        self.assertTrue(any(self.trash.iterdir()))
        self.assertTrue(engine.JOURNAL_PATH.exists())
        self.assertEqual(engine.list_quarantine(), [])
        self.assertFalse(engine.JOURNAL_PATH.exists())


if __name__ == "__main__":
    unittest.main()
