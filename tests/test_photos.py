from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from spacekeeper import photos


def _make_png(path: Path, color: str) -> bool:
    """sips 로 단색 이미지를 만든다. 실패하면 False."""
    result = subprocess.run(
        ["sips", "-s", "format", "png", "--resampleHeightWidth", "64", "64",
         "/System/Library/CoreServices/DefaultDesktop.heic", "--out", str(path)],
        capture_output=True,
    )
    return result.returncode == 0 and path.is_file()


class PhotoHashTests(unittest.TestCase):
    def test_bmp_parsing_rejects_garbage(self) -> None:
        self.assertIsNone(photos._bmp_to_gray(b"not a bmp"))
        self.assertIsNone(photos._bmp_to_gray(b""))

    def test_distance_counts_differing_bits(self) -> None:
        self.assertEqual(photos._distance(0b1010, 0b1010), 0)
        self.assertEqual(photos._distance(0b1010, 0b0000), 2)
        self.assertEqual(photos._distance(0, (1 << 64) - 1), 64)

    def test_identical_copies_group_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "a.png"
            if not _make_png(source, "red"):
                self.skipTest("sips 로 테스트 이미지를 만들 수 없음")
            shutil.copy(source, root / "b.png")

            result = photos.find_similar_photos(root, min_bytes=1)
            self.assertGreaterEqual(result["group_count"], 1)
            group = result["groups"][0]
            self.assertEqual(group["count"], 2)
            self.assertTrue(group["files"][0]["keep"])
            self.assertFalse(group["files"][1]["keep"])

    def test_skips_cloud_container(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cloud = root / "Library" / "CloudStorage"
            cloud.mkdir(parents=True)
            found = photos._iter_images(root, min_bytes=0, limit=50)
            self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
