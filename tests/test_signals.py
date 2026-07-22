from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from spacekeeper import signals


class SignalParsingTests(unittest.TestCase):
    def test_parse_mdls_date(self) -> None:
        epoch = signals._parse_mdls_date("2026-06-14 05:58:18 +0000")
        self.assertIsNotNone(epoch)
        self.assertIsNone(signals._parse_mdls_date("(null)"))
        self.assertIsNone(signals._parse_mdls_date(""))

    def test_relative_age_wording(self) -> None:
        now = 1_000_000_000.0
        self.assertIsNone(signals._relative_age(None, now))
        self.assertEqual(signals._relative_age(now - 5 * 86400, now), "5일 전")
        self.assertEqual(signals._relative_age(now - 60 * 86400, now), "2개월 전")
        self.assertIn("년", signals._relative_age(now - 800 * 86400, now))


class SignalSafetyTests(unittest.TestCase):
    def test_rejects_path_outside_home(self) -> None:
        with self.assertRaises(signals.SignalError):
            signals._validate(Path("/etc/hosts"))

    def test_rejects_missing_file(self) -> None:
        with mock.patch.object(
            signals.Path, "home", classmethod(lambda cls: Path("/tmp"))
        ):
            with self.assertRaises(signals.SignalError):
                signals._validate(Path("/tmp/does-not-exist-xyz"))


class CopyPartitionTests(unittest.TestCase):
    def test_local_confirmed_by_hash_cloud_by_name_size(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / "photo.jpg"
            original.write_bytes(b"abc" * 1000)
            same = root / "sub" / "photo.jpg"
            same.parent.mkdir()
            same.write_bytes(b"abc" * 1000)  # 같은 내용 → 로컬 복사본
            different = root / "other" / "photo.jpg"
            different.parent.mkdir()
            different.write_bytes(b"xyz" * 1000)  # 같은 크기·이름, 다른 내용
            cloud = root / "cloud" / "photo.jpg"
            cloud.parent.mkdir()
            cloud.write_bytes(b"zzz" * 1000)  # 클라우드 취급: 이름+크기만 확인

            digest = signals._hash_file(original)
            candidates = [same, different, cloud]
            with mock.patch.object(signals, "CLOUD_ROOTS", (root / "cloud",)):
                local, cloud_hits = signals._partition_copies(
                    candidates, original.stat().st_size, digest
                )

            self.assertIn(str(same), local)
            self.assertNotIn(str(different), local)  # 내용 다르면 로컬 복사본 아님
            self.assertIn(str(cloud), cloud_hits)


if __name__ == "__main__":
    unittest.main()
