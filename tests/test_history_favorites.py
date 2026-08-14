from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from spacekeeper import favorites, history


class HistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name) / "history.jsonl"
        p = mock.patch.object(history, "HISTORY_PATH", self.path)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)

    def test_records_scan_and_operation_in_order(self) -> None:
        history.record_scan(
            {
                "roots": ["/Users/x"],
                "review_bytes": 1000,
                "by_risk": {"low": 1000},
                "scanned_files": 42,
                "disk": {"free": 5, "total": 10},
                "duration": 1.234,
            },
            now=100.0,
        )
        history.record_operation("quarantine", 3, 900, now=101.0)
        records = history.load_history()
        self.assertEqual([r["type"] for r in records], ["scan", "quarantine"])
        self.assertEqual(records[0]["reclaimable_bytes"], 1000)
        self.assertEqual(records[0]["scanned_files"], 42)
        self.assertEqual(records[1]["count"], 3)
        self.assertEqual(records[1]["bytes"], 900)

    def test_trims_to_cap(self) -> None:
        with mock.patch.object(history, "_MAX_RECORDS", 5):
            for i in range(12):
                history.record_operation("quarantine", i, i, now=float(i))
        records = history.load_history()
        self.assertEqual(len(records), 5)
        self.assertEqual(records[-1]["count"], 11)

    def test_ignores_corrupt_lines(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text('{"type":"scan","ts":1}\nnot json\n', encoding="utf-8")
        records = history.load_history()
        self.assertEqual(len(records), 1)


class FavoritesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.store = self.home / ".spacekeeper" / "favorites.json"
        for name, value in {"FAVORITES_PATH": self.store}.items():
            p = mock.patch.object(favorites, name, value)
            p.start()
            self.addCleanup(p.stop)
        home_patch = mock.patch.object(
            favorites.Path, "home", classmethod(lambda cls: self.home)
        )
        home_patch.start()
        self.addCleanup(home_patch.stop)
        self.addCleanup(self._tmp.cleanup)

    def test_add_and_remove_roundtrip(self) -> None:
        target = self.home / "Projects"
        target.mkdir()
        favorites.add_favorite(str(target))
        self.assertIn(str(target.resolve()), favorites.load_favorites())
        favorites.remove_favorite(str(target))
        self.assertEqual(favorites.load_favorites(), [])

    def test_rejects_outside_home(self) -> None:
        with TemporaryDirectory() as outside:
            with self.assertRaises(favorites.FavoriteError):
                favorites.add_favorite(outside)

    def test_rejects_file(self) -> None:
        f = self.home / "note.txt"
        f.write_text("x", encoding="utf-8")
        with self.assertRaises(favorites.FavoriteError):
            favorites.add_favorite(str(f))

    def test_dedupes(self) -> None:
        target = self.home / "Docs"
        target.mkdir()
        favorites.add_favorite(str(target))
        favorites.add_favorite(str(target))
        self.assertEqual(len(favorites.load_favorites()), 1)


if __name__ == "__main__":
    unittest.main()
