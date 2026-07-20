from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spacekeeper import browsers
from spacekeeper.browsers import scan_browser_caches


class BrowserSafetyTests(unittest.TestCase):
    """캐시가 아닌 사용자 데이터(메일 저장소·사이트 데이터)를 대상에 넣지 않는다."""

    def test_targets_are_caches_only(self) -> None:
        subpaths = [
            entry["subpath"]
            for entry in browsers.BROWSER_CACHE_PATHS + browsers.MAIL_CACHE_PATHS
        ]
        self.assertNotIn("Library/Mail", subpaths)
        self.assertNotIn("Library/Safari/LocalStorage", subpaths)
        for subpath in subpaths:
            self.assertTrue(
                "Cache" in subpath or "cache" in subpath,
                f"캐시가 아닌 대상이 포함됨: {subpath}",
            )


class BrowserScanStructureTests(unittest.TestCase):
    """결과 dict 에 올바른 키가 포함되는지 확인."""

    def test_result_has_expected_keys(self) -> None:
        with TemporaryDirectory() as tmp:
            result = scan_browser_caches(home=Path(tmp))

        self.assertIn("browsers", result)
        self.assertIn("mail", result)
        self.assertIn("total_bytes", result)
        self.assertIn("total_human", result)
        self.assertIsInstance(result["browsers"], list)
        self.assertIsInstance(result["mail"], list)
        self.assertIsInstance(result["total_bytes"], int)
        self.assertIsInstance(result["total_human"], str)


class BrowserScanFakeDataTests(unittest.TestCase):
    """임시 디렉토리에 가짜 캐시 파일을 만들어 스캔 결과를 검증."""

    def test_scan_detects_safari_cache(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            safari_cache = home / "Library" / "Caches" / "com.apple.Safari"
            safari_cache.mkdir(parents=True)
            (safari_cache / "blob.db").write_bytes(b"x" * 2048)

            result = scan_browser_caches(home=home)

        safari_entries = [
            e for e in result["browsers"] if e["browser"] == "Safari"
        ]
        self.assertEqual(len(safari_entries), 1)
        entry = safari_entries[0]
        self.assertEqual(entry["browser"], "Safari")
        self.assertGreater(entry["allocated_bytes"], 0)
        self.assertGreater(entry["file_count"], 0)
        self.assertEqual(entry["risk"], "low")
        self.assertGreater(result["total_bytes"], 0)

    def test_scan_detects_chrome_cache(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            chrome_cache = (
                home
                / "Library"
                / "Application Support"
                / "Google"
                / "Chrome"
                / "Default"
                / "Cache"
            )
            chrome_cache.mkdir(parents=True)
            (chrome_cache / "data_0").write_bytes(b"c" * 512)

            result = scan_browser_caches(home=home)

        chrome_entries = [
            e for e in result["browsers"] if e["browser"] == "Chrome"
        ]
        self.assertEqual(len(chrome_entries), 1)
        self.assertGreater(chrome_entries[0]["allocated_bytes"], 0)

    def test_scan_detects_firefox_cache2(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            profile = (
                home
                / "Library"
                / "Caches"
                / "Firefox"
                / "Profiles"
                / "abc123.default"
                / "cache2"
            )
            profile.mkdir(parents=True)
            (profile / "index.dat").write_bytes(b"f" * 1024)

            result = scan_browser_caches(home=home)

        ff_entries = [
            e for e in result["browsers"] if e["browser"] == "Firefox"
        ]
        self.assertEqual(len(ff_entries), 1)
        self.assertGreater(ff_entries[0]["allocated_bytes"], 0)
        self.assertIn("cache2", ff_entries[0]["path"])

    def test_scan_detects_mail_cache(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            mail_cache = (
                home
                / "Library"
                / "Containers"
                / "com.apple.mail"
                / "Data"
                / "Library"
                / "Caches"
            )
            mail_cache.mkdir(parents=True)
            (mail_cache / "tmp.bin").write_bytes(b"m" * 256)

            result = scan_browser_caches(home=home)

        self.assertEqual(len(result["mail"]), 1)
        self.assertGreater(result["mail"][0]["allocated_bytes"], 0)

    def test_total_bytes_matches_sum(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            safari = home / "Library" / "Caches" / "com.apple.Safari"
            safari.mkdir(parents=True)
            (safari / "a.bin").write_bytes(b"a" * 100)

            mail = home / "Library" / "Mail"
            mail.mkdir(parents=True)
            (mail / "V9" / "store").parent.mkdir(parents=True)
            (mail / "V9" / "store").write_bytes(b"s" * 200)

            result = scan_browser_caches(home=home)

        parts = sum(e["allocated_bytes"] for e in result["browsers"])
        parts += sum(e["allocated_bytes"] for e in result["mail"])
        self.assertEqual(result["total_bytes"], parts)


class BrowserScanMissingPathsTests(unittest.TestCase):
    """존재하지 않는 경로는 건너뛰는지 확인."""

    def test_empty_home_returns_empty_lists(self) -> None:
        with TemporaryDirectory() as tmp:
            result = scan_browser_caches(home=Path(tmp))

        self.assertEqual(result["browsers"], [])
        self.assertEqual(result["mail"], [])
        self.assertEqual(result["total_bytes"], 0)

    def test_partial_paths_only_return_existing(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            # Safari 캐시만 생성, 나머지는 없음
            safari = home / "Library" / "Caches" / "com.apple.Safari"
            safari.mkdir(parents=True)
            (safari / "d.bin").write_bytes(b"d" * 64)

            result = scan_browser_caches(home=home)

        self.assertEqual(len(result["browsers"]), 1)
        self.assertEqual(result["browsers"][0]["browser"], "Safari")
        self.assertEqual(result["mail"], [])


if __name__ == "__main__":
    unittest.main()
