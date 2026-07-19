from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spacekeeper import diagnostics


class DiagnosticsTests(unittest.TestCase):
    def test_reports_access_and_cleans_temporary_write_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            for name in ("Desktop", "Documents", "Downloads", ".Trash"):
                (home / name).mkdir()
            quarantine = home / ".spacekeeper" / "quarantine"

            result = diagnostics.diagnose_environment(
                home=home,
                quarantine_root=quarantine,
                trash_root=home / ".Trash",
            )

            checks = {check["id"]: check for check in result["checks"]}
            self.assertEqual(checks["desktop"]["status"], "ready")
            self.assertEqual(checks["documents"]["status"], "ready")
            self.assertEqual(checks["downloads"]["status"], "ready")
            self.assertEqual(checks["quarantine"]["status"], "ready")
            self.assertEqual(checks["trash"]["status"], "ready")
            self.assertEqual(list(quarantine.iterdir()), [])
            self.assertEqual(list((home / ".Trash").iterdir()), [])

    def test_marks_missing_protected_folder_for_attention(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Documents"

            check = diagnostics._probe_directory_read(
                "documents", "문서", path
            )

        self.assertEqual(check["status"], "attention")
        self.assertIn("생성", check["detail"])

    def test_marks_privacy_denial_as_blocked_with_settings_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir)
            with mock.patch.object(
                diagnostics.os,
                "scandir",
                side_effect=PermissionError("권한 없음"),
            ):
                check = diagnostics._probe_directory_read(
                    "desktop", "데스크탑", path
                )

        self.assertEqual(check["status"], "blocked")
        self.assertEqual(check["action"], "privacy_settings")

    def test_marks_unusable_quarantine_path_as_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "quarantine"
            path.write_text("not a directory")

            check = diagnostics._probe_directory_write(
                "quarantine",
                "Spacekeeper 격리함",
                path,
                create=True,
            )

        self.assertEqual(check["status"], "blocked")

    def test_marks_non_loopback_server_as_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            for name in ("Desktop", "Documents", "Downloads", ".Trash"):
                (home / name).mkdir()

            result = diagnostics.diagnose_environment(
                home=home,
                quarantine_root=home / ".spacekeeper" / "quarantine",
                trash_root=home / ".Trash",
                server_host="0.0.0.0",
            )

        local_server = next(
            check for check in result["checks"] if check["id"] == "local_server"
        )
        self.assertEqual(local_server["status"], "blocked")
        self.assertIn("0.0.0.0", local_server["detail"])

    def test_identifies_frozen_desktop_runtime_as_bundled(self) -> None:
        package_root = Path(diagnostics.__file__).resolve().parent
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            mock.patch.object(diagnostics.sys, "frozen", True, create=True),
        ):
            check, runtime = diagnostics._runtime_check(
                Path(temp_dir),
                package_root,
            )

        self.assertEqual(check["status"], "ready")
        self.assertIn("독립 실행", check["detail"])
        self.assertEqual(runtime["mode"], "bundled")


if __name__ == "__main__":
    unittest.main()
