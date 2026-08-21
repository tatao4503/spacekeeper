from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from spacekeeper import systemdata


class AreaDefinitionTests(unittest.TestCase):
    def test_every_area_is_well_formed(self) -> None:
        keys = set()
        for area in systemdata.AREAS:
            self.assertNotIn(area.key, keys, f"중복 key: {area.key}")
            keys.add(area.key)
            self.assertIn(area.action, {"quarantine", "command", "system"})
            self.assertIn(area.risk, {"low", "medium", "high"})
            for field in (area.name, area.path, area.what, area.why):
                self.assertTrue(field.strip(), f"{area.key}: 빈 필드")

    def test_actionable_areas_tell_the_user_what_to_do(self) -> None:
        for area in systemdata.AREAS:
            if area.action in {"command", "system"}:
                self.assertTrue(
                    area.command.strip() or area.hint.strip(),
                    f"{area.key}: 직접 처리해야 하는데 안내가 없습니다",
                )

    def test_outside_home_areas_are_never_quarantined(self) -> None:
        """홈 밖 경로는 앱이 격리하지 않는다 — 되돌릴 수 없고 시스템을 깨뜨린다."""
        for area in systemdata.AREAS:
            if not area.path.startswith("~"):
                self.assertNotEqual(
                    area.action,
                    "quarantine",
                    f"{area.key}: 홈 밖인데 격리 대상으로 표시됨",
                )


class MeasureTests(unittest.TestCase):
    def test_counts_files_and_skips_symlinks(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.bin").write_bytes(b"x" * 4096)
            nested = root / "sub"
            nested.mkdir()
            (nested / "b.bin").write_bytes(b"y" * 4096)
            (root / "link").symlink_to(nested)

            size, files, reachable = systemdata._measure(root)
            self.assertTrue(reachable)
            self.assertEqual(files, 2)  # 심링크를 따라가 중복 계산하지 않는다
            self.assertGreater(size, 0)

    def test_missing_path_is_zero_and_unreachable(self) -> None:
        with TemporaryDirectory() as tmp:
            size, files, reachable = systemdata._measure(Path(tmp) / "nope")
            self.assertEqual((size, files, reachable), (0, 0, False))


class AnalyzeTests(unittest.TestCase):
    def _area(self, key: str, path: str, action: str = "command") -> systemdata.SystemArea:
        return systemdata.SystemArea(
            key=key,
            name=key,
            path=path,
            what="설명",
            why="이유",
            action=action,
            risk="low",
            hint="안내",
        )

    def test_skips_missing_paths_and_sorts_by_size(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            big = home / "big"
            big.mkdir()
            (big / "f").write_bytes(b"x" * 200_000)
            small = home / "small"
            small.mkdir()
            (small / "f").write_bytes(b"x" * 4096)

            areas = (
                self._area("small", str(small)),
                self._area("missing", str(home / "gone")),
                self._area("big", str(big)),
            )
            with mock.patch.object(systemdata, "AREAS", areas), mock.patch.object(
                systemdata.Path, "home", classmethod(lambda cls: home)
            ):
                result = systemdata.analyze()

            keys = [item["key"] for item in result["items"]]
            self.assertEqual(keys, ["big", "small"])  # 없는 경로는 빠지고 크기순
            self.assertEqual(result["total_bytes"], sum(i["size"] for i in result["items"]))
            self.assertIn("free", result["disk"])

    def test_reports_outside_home_separately(self) -> None:
        with TemporaryDirectory() as tmp, TemporaryDirectory() as outside:
            home = Path(tmp)
            inside = home / "inside"
            inside.mkdir()
            (inside / "f").write_bytes(b"x" * 8192)
            out = Path(outside)
            (out / "f").write_bytes(b"x" * 8192)

            areas = (self._area("inside", str(inside)), self._area("outside", str(out)))
            with mock.patch.object(systemdata, "AREAS", areas), mock.patch.object(
                systemdata.Path, "home", classmethod(lambda cls: home)
            ):
                result = systemdata.analyze()

            flags = {item["key"]: item["outside_home"] for item in result["items"]}
            self.assertFalse(flags["inside"])
            self.assertTrue(flags["outside"])
            self.assertGreater(result["outside_home_bytes"], 0)

    def test_analysis_never_modifies_anything(self) -> None:
        """이 화면은 진단 전용이다. 분석 후 파일이 그대로 있어야 한다."""
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            area_dir = home / "area"
            area_dir.mkdir()
            (area_dir / "keep.bin").write_bytes(b"x" * 4096)
            (area_dir / "also-keep.bin").write_bytes(b"y" * 4096)
            before = sorted(p.name for p in area_dir.iterdir())

            with mock.patch.object(
                systemdata, "AREAS", (self._area("area", str(area_dir)),)
            ), mock.patch.object(systemdata.Path, "home", classmethod(lambda cls: home)):
                systemdata.analyze()

            self.assertEqual(sorted(p.name for p in area_dir.iterdir()), before)


if __name__ == "__main__":
    unittest.main()
