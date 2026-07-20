from __future__ import annotations

import plistlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spacekeeper import icons


class ReadPlistIconNameTests(unittest.TestCase):
    def test_reads_icon_name_from_plist(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "Test.app"
            contents = app / "Contents"
            contents.mkdir(parents=True)
            with (contents / "Info.plist").open("wb") as f:
                plistlib.dump({"CFBundleIconFile": "AppIcon"}, f)

            result = icons._read_plist_icon_name(app)
            self.assertEqual(result, "AppIcon.icns")

    def test_preserves_existing_extension(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "Test.app"
            contents = app / "Contents"
            contents.mkdir(parents=True)
            with (contents / "Info.plist").open("wb") as f:
                plistlib.dump({"CFBundleIconFile": "AppIcon.icns"}, f)

            result = icons._read_plist_icon_name(app)
            self.assertEqual(result, "AppIcon.icns")

    def test_returns_none_for_missing_plist(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "Nonexistent.app"
            self.assertIsNone(icons._read_plist_icon_name(app))

    def test_returns_none_when_key_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "Test.app"
            contents = app / "Contents"
            contents.mkdir(parents=True)
            with (contents / "Info.plist").open("wb") as f:
                plistlib.dump({"CFBundleIdentifier": "com.test"}, f)

            self.assertIsNone(icons._read_plist_icon_name(app))


class CacheKeyTests(unittest.TestCase):
    def test_returns_consistent_hash(self) -> None:
        path = Path("/Applications/Test.app")
        key1 = icons._cache_key(path)
        key2 = icons._cache_key(path)
        self.assertEqual(key1, key2)
        self.assertTrue(key1.endswith(".png"))

    def test_different_paths_produce_different_keys(self) -> None:
        key_a = icons._cache_key(Path("/Applications/A.app"))
        key_b = icons._cache_key(Path("/Applications/B.app"))
        self.assertNotEqual(key_a, key_b)


class ExtractAppIconTests(unittest.TestCase):
    def test_returns_none_for_nonexistent_app(self) -> None:
        result = icons.extract_app_icon(Path("/nonexistent/Fake.app"))
        self.assertIsNone(result)


class GetIconBytesTests(unittest.TestCase):
    def test_returns_none_for_nonexistent_app(self) -> None:
        result = icons.get_icon_bytes(Path("/nonexistent/Fake.app"))
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
