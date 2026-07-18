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


if __name__ == "__main__":
    unittest.main()
