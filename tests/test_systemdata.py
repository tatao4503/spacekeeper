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


    def test_every_area_is_translated(self) -> None:
        """영역 문구는 영어 화면에서도 보여야 한다. 새 영역을 넣고 번역을 빼먹으면 여기서 잡힌다."""
        i18n = (Path(systemdata.__file__).parent / "web" / "i18n.js").read_text(encoding="utf-8")
        texts = [systemdata.OTHER_HIDDEN_WHAT, systemdata.OTHER_HIDDEN_WHY, systemdata.OTHER_HIDDEN_HINT]
        for area in systemdata.AREAS:
            texts += [area.name, area.what, area.why] + ([area.hint] if area.hint else [])
        missing = [t for t in texts if f'"{t}"' not in i18n]
        self.assertEqual(missing, [])
        self.assertIn("숨김 폴더 (\\..+)", i18n)  # 이름이 바뀌는 숨김 폴더는 패턴으로 번역

    def test_trash_and_quarantine_are_never_emptied_by_the_app(self) -> None:
        """휴지통 비우기는 되돌릴 수 없어 사용자가 한다. 격리함도 '격리함' 화면에서만 다룬다."""
        by_key = {area.key: area for area in systemdata.AREAS}
        for key in ("trash", "spacekeeper_quarantine"):
            self.assertNotEqual(by_key[key].action, "quarantine")
            self.assertEqual(by_key[key].command, "")


class MeasureTests(unittest.TestCase):
    def test_counts_files_and_skips_symlinks(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.bin").write_bytes(b"x" * 4096)
            nested = root / "sub"
            nested.mkdir()
            (nested / "b.bin").write_bytes(b"y" * 4096)
            (root / "link").symlink_to(nested)

            size, files, reachable, denied = systemdata._measure(root)
            self.assertTrue(reachable)
            self.assertEqual(denied, 0)
            self.assertEqual(files, 2)  # 심링크를 따라가 중복 계산하지 않는다
            self.assertGreater(size, 0)

    def test_missing_path_is_zero_and_unreachable(self) -> None:
        with TemporaryDirectory() as tmp:
            m = systemdata._measure(Path(tmp) / "nope")
            self.assertEqual((m.size, m.files, m.reachable, m.denied), (0, 0, False, 0))

    def test_unreadable_folders_are_counted_not_silently_skipped(self) -> None:
        """권한이 없어 못 연 폴더는 건너뛰되 센다. 예전엔 조용히 넘어가서
        다른 앱 데이터 760개를 하나도 못 읽고도 '18MB'라고 보고했다."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "readable.bin").write_bytes(b"x" * 4096)
            locked = root / "locked"
            locked.mkdir()
            (locked / "hidden.bin").write_bytes(b"y" * 400_000)
            locked.chmod(0)
            try:
                m = systemdata._measure(root)
            finally:
                locked.chmod(0o755)
            self.assertTrue(m.reachable)
            self.assertEqual(m.denied, 1)
            self.assertEqual(m.files, 1)  # 잠긴 폴더 안의 파일은 세지 못했다


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

    def test_partly_unreadable_area_is_flagged_and_total_is_a_lower_bound(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            area_dir = home / "area"
            area_dir.mkdir()
            (area_dir / "seen.bin").write_bytes(b"x" * 8192)
            locked = area_dir / "locked"
            locked.mkdir()
            locked.chmod(0)
            try:
                with mock.patch.object(
                    systemdata, "AREAS", (self._area("area", str(area_dir)),)
                ), mock.patch.object(systemdata.Path, "home", classmethod(lambda cls: home)):
                    result = systemdata.analyze()
            finally:
                locked.chmod(0o755)
            item = result["items"][0]
            self.assertFalse(item["complete"])
            self.assertEqual(item["denied_dirs"], 1)
            self.assertTrue(result["total_is_lower_bound"])
            self.assertEqual(result["incomplete_count"], 1)

    def test_fully_unreadable_area_is_kept_not_dropped(self) -> None:
        """통째로 못 읽어 0바이트인 영역을 빼면, 사용자는 그 영역이 있는지조차 모른다."""
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            area_dir = home / "area"
            area_dir.mkdir()
            (area_dir / "hidden.bin").write_bytes(b"x" * 8192)
            area_dir.chmod(0)
            try:
                with mock.patch.object(
                    systemdata, "AREAS", (self._area("area", str(area_dir)),)
                ), mock.patch.object(systemdata.Path, "home", classmethod(lambda cls: home)):
                    result = systemdata.analyze()
            finally:
                area_dir.chmod(0o755)
            self.assertEqual(len(result["items"]), 1)
            item = result["items"][0]
            self.assertEqual(item["size"], 0)
            self.assertFalse(item["complete"])
            self.assertFalse(item["reachable"])

    def test_unknown_hidden_folders_show_up_only_when_large(self) -> None:
        """목록에 없는 숨김 폴더도 크면 보여 준다. 무엇인지 모른다고 말하면서."""
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            big = home / ".sometool"
            big.mkdir()
            (big / "blob").write_bytes(b"x" * 200_000)
            tiny = home / ".tinytool"
            tiny.mkdir()
            (tiny / "cfg").write_bytes(b"x" * 100)
            known = home / ".known"
            known.mkdir()
            (known / "blob").write_bytes(b"x" * 200_000)

            areas = (self._area("known", "~/.known"),)
            with mock.patch.object(systemdata, "AREAS", areas), mock.patch.object(
                systemdata, "_OTHER_HIDDEN_MIN_BYTES", 100_000
            ), mock.patch.object(systemdata.Path, "home", classmethod(lambda cls: home)):
                result = systemdata.analyze()

            keys = sorted(item["key"] for item in result["items"])
            self.assertEqual(keys, ["hidden:.sometool", "known"])  # 작은 것은 숨기고, 아는 것은 한 번만
            other = next(i for i in result["items"] if i["key"] == "hidden:.sometool")
            self.assertEqual(other["name"], "숨김 폴더 .sometool")
            self.assertEqual(other["what"], systemdata.OTHER_HIDDEN_WHAT)

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
