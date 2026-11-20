from __future__ import annotations

import ctypes
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from spacekeeper import engine, icloud

# 일반 사용자는 진짜 동기화 표시(com.apple.file-provider-domain-id)를 붙일 수 없어서
# 시험용 이름으로 바꿔 끼운다. File Provider 표시는 실제 이름 그대로 붙일 수 있다.
TEST_DOMAIN_ATTR = "org.spacekeeper.test-domain"
MARKER = "com.apple.fileprovider.dir#N"

_lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
_lib.setxattr.argtypes = [
    ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
    ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int,
]


def set_xattr(path: Path, name: str) -> None:
    if _lib.setxattr(os.fsencode(str(path)), name.encode(), b"1", 1, 0, 1) != 0:
        raise OSError(ctypes.get_errno(), f"setxattr {name} on {path}")


class _DomainCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.base = Path(self._tmp.name).resolve()
        self.domain = self.base / "Desktop"
        self.domain.mkdir()
        set_xattr(self.domain, TEST_DOMAIN_ATTR)
        patcher = mock.patch.object(icloud, "DOMAIN_ATTRS", (TEST_DOMAIN_ATTR,))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class SyncStateTests(_DomainCase):
    def test_outside_any_domain(self) -> None:
        other = self.base / "Downloads" / "a.zip"
        other.parent.mkdir()
        other.write_bytes(b"x")
        self.assertIsNone(icloud.sync_state(other))

    def test_inside_domain_is_synced_even_if_missing(self) -> None:
        self.assertEqual(icloud.sync_state(self.domain / "proj" / "big.mov"), icloud.SYNCED)

    def test_domain_root_itself_is_synced(self) -> None:
        self.assertEqual(icloud.sync_state(self.domain), icloud.SYNCED)

    def test_nosync_anywhere_below_root_is_excluded(self) -> None:
        self.assertEqual(
            icloud.sync_state(self.domain / "proj" / "node_modules.nosync"),
            icloud.EXCLUDED,
        )
        self.assertEqual(
            icloud.sync_state(self.domain / "proj" / "toolchains.nosync" / "sdk" / "x"),
            icloud.EXCLUDED,
        )

    def test_nosync_above_the_root_does_not_count(self) -> None:
        outer = self.base / "outer.nosync" / "Documents"
        outer.mkdir(parents=True)
        set_xattr(outer, TEST_DOMAIN_ATTR)
        self.assertEqual(icloud.sync_state(outer / "a.txt"), icloud.SYNCED)


class StripMarkerTests(_DomainCase):
    def test_strips_only_file_provider_markers_recursively(self) -> None:
        top = self.base / "node_modules.nosync"
        nested = top / "bn.js" / "lib"
        nested.mkdir(parents=True)
        (nested / "index.js").write_text("x")
        for path in (top, top / "bn.js", nested, nested / "index.js"):
            set_xattr(path, MARKER)
        set_xattr(top, "org.spacekeeper.keep")

        removed = icloud.strip_markers(top)

        self.assertEqual(removed, 4)
        for path in (top, top / "bn.js", nested, nested / "index.js"):
            self.assertFalse(
                any(n.startswith(icloud.MARKER_PREFIX) for n in icloud.xattr_names(path)),
                path,
            )
        self.assertIn("org.spacekeeper.keep", icloud.xattr_names(top))

    def test_missing_path_is_a_no_op(self) -> None:
        self.assertEqual(icloud.strip_markers(self.base / "nope"), 0)


class EngineICloudTests(_DomainCase):
    def setUp(self) -> None:
        super().setUp()
        self.home = self.base
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

    def _hang_mv(self):
        # 붙잡힌 iCloud 이동처럼 돌아오지 않는 mv.
        return mock.patch.multiple(
            engine,
            _MV_COMMAND=("/bin/sh", "-c", "sleep 30", "sh"),
            ICLOUD_MOVE_TIMEOUT=0.3,
        )

    def test_nosync_item_is_quarantined_without_markers(self) -> None:
        item = self.domain / "proj" / "node_modules.nosync"
        (item / "bn.js").mkdir(parents=True)
        (item / "bn.js" / "f.js").write_text("x")
        set_xattr(item, MARKER)
        set_xattr(item / "bn.js", MARKER)

        outcome = engine.quarantine([("a1", str(item), "cache")])

        self.assertEqual(len(outcome.moved), 1)
        stored = Path(outcome.moved[0].stored_path)
        self.assertTrue((stored / "bn.js" / "f.js").exists())
        for path in (stored, stored / "bn.js"):
            self.assertNotIn(MARKER, icloud.xattr_names(path))

    def test_domain_root_itself_is_never_moved(self) -> None:
        (self.domain / "a.txt").write_text("x")
        outcome = engine.quarantine([("a1", str(self.domain), "file")])
        self.assertEqual(outcome.moved, [])
        self.assertIn("iCloud", outcome.skipped[0]["reason"])
        self.assertTrue((self.domain / "a.txt").exists())

    def test_synced_item_moves_through_bounded_mv(self) -> None:
        item = self.domain / "video.mov"
        item.write_bytes(b"v" * 10)
        outcome = engine.quarantine([("a1", str(item), "file")])
        self.assertEqual(len(outcome.moved), 1)
        self.assertFalse(item.exists())
        self.assertTrue(Path(outcome.moved[0].stored_path).exists())

    def test_held_move_is_skipped_and_leaves_original_in_place(self) -> None:
        first = self.domain / "avds"
        first.mkdir()
        (first / "disk.img").write_bytes(b"d")
        second = self.domain / "other.mov"
        second.write_bytes(b"o")

        with self._hang_mv():
            outcome = engine.quarantine(
                [("a1", str(first), "file"), ("a2", str(second), "file")]
            )

        self.assertEqual(outcome.moved, [])
        self.assertEqual(len(outcome.skipped), 2)
        for entry in outcome.skipped:
            self.assertEqual(entry["reason"], engine.ICLOUD_BUSY_MESSAGE)
        self.assertTrue((first / "disk.img").exists())
        self.assertTrue(second.exists())
        self.assertFalse(engine.JOURNAL_PATH.exists())
        self.assertEqual(engine.list_quarantine(), [])

    def test_held_move_does_not_block_items_outside_icloud(self) -> None:
        held = self.domain / "avds"
        held.mkdir()
        local = self.home / "Downloads" / "old.dmg"
        local.parent.mkdir()
        local.write_bytes(b"x")

        with self._hang_mv():
            outcome = engine.quarantine(
                [("a1", str(held), "file"), ("a2", str(local), "file")]
            )

        self.assertEqual([r.action_id for r in outcome.moved], ["a2"])
        self.assertTrue(held.exists())

    def test_held_restore_keeps_item_quarantined(self) -> None:
        item = self.domain / "clip.mov"
        item.write_bytes(b"c")
        engine.quarantine([("a1", str(item), "file")])

        with self._hang_mv():
            with self.assertRaises(engine.ICloudBusyError) as ctx:
                engine.restore("a1")

        self.assertEqual(str(ctx.exception), engine.ICLOUD_RESTORE_BUSY_MESSAGE)
        self.assertFalse(item.exists())
        self.assertEqual([r.action_id for r in engine.list_quarantine()], ["a1"])
        self.assertFalse(engine.JOURNAL_PATH.exists())

    def test_empty_strips_markers_left_by_older_versions(self) -> None:
        item = self.home / "Downloads" / "pkg"
        item.mkdir(parents=True)
        outcome = engine.quarantine([("a1", str(item), "cache")])
        stored = Path(outcome.moved[0].stored_path)
        set_xattr(stored, MARKER)

        emptied = engine.empty_quarantine()

        self.assertEqual(len(emptied), 1)
        in_trash = next(self.trash.iterdir())
        self.assertNotIn(MARKER, icloud.xattr_names(in_trash))


if __name__ == "__main__":
    unittest.main()
