from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from spacekeeper import apps


class AppScanTests(unittest.TestCase):
    def test_scan_finds_app_bundle_and_library_leftovers(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_dir = root / "Apps"
            contents = app_dir / "Demo.app" / "Contents"
            contents.mkdir(parents=True)
            (contents / "Info.plist").write_bytes(
                b'<?xml version="1.0"?><plist version="1.0"><dict>'
                b"<key>CFBundleIdentifier</key><string>com.demo.app</string>"
                b"</dict></plist>"
            )
            (contents / "blob").write_bytes(b"x" * 1000)

            library = root / "Library"
            leftover = library / "Caches" / "com.demo.app"
            leftover.mkdir(parents=True)
            (leftover / "c.bin").write_bytes(b"y" * 500)

            with mock.patch.object(apps, "APP_DIRS", (app_dir,)), mock.patch.object(
                apps.Path, "home", classmethod(lambda cls: root)
            ):
                found = apps.scan_apps()

            self.assertEqual(len(found), 1)
            app = found[0]
            self.assertEqual(app.name, "Demo")
            self.assertEqual(app.bundle_id, "com.demo.app")
            self.assertEqual(len(app.leftovers), 1)
            self.assertGreater(app.app_bytes, 0)
            self.assertEqual(app.total_bytes, app.app_bytes + app.leftover_bytes)

    def test_ignores_non_app_entries(self) -> None:
        with TemporaryDirectory() as tmp:
            app_dir = Path(tmp) / "Apps"
            app_dir.mkdir()
            (app_dir / "notes.txt").write_text("hi")
            with mock.patch.object(apps, "APP_DIRS", (app_dir,)), mock.patch.object(
                apps.Path, "home", classmethod(lambda cls: Path(tmp))
            ):
                self.assertEqual(apps.scan_apps(), [])


if __name__ == "__main__":
    unittest.main()
