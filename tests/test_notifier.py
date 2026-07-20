from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

from spacekeeper.notifier import (
    _escape_applescript_string,
    notify_macos,
    notify_quarantine_action,
    notify_scan_complete,
)


class NotifierTests(unittest.TestCase):
    def test_escapes_applescript_special_characters(self) -> None:
        raw = 'Hello "World" \\ Path'
        escaped = _escape_applescript_string(raw)
        self.assertEqual(escaped, 'Hello \\"World\\" \\\\ Path')

    @patch("shutil.which", return_value="/usr/bin/osascript")
    @patch("subprocess.run")
    def test_notify_macos_calls_osascript_on_darwin(
        self, mock_run: MagicMock, mock_which: MagicMock
    ) -> None:
        mock_run.return_value.returncode = 0
        with patch.object(sys, "platform", "darwin"):
            success = notify_macos("Title", "Message", subtitle="Subtitle")

        self.assertTrue(success)
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        command = args[0]
        self.assertEqual(command[0], "/usr/bin/osascript")
        self.assertIn('display notification "Message" with title "Title"', command[2])
        self.assertIn('subtitle "Subtitle"', command[2])

    def test_notify_macos_returns_false_on_non_darwin(self) -> None:
        with patch.object(sys, "platform", "linux"):
            self.assertFalse(notify_macos("Title", "Message"))

    @patch("spacekeeper.notifier.notify_macos", return_value=True)
    def test_notify_scan_complete_formats_message(self, mock_notify: MagicMock) -> None:
        res = notify_scan_complete(1024 * 1024 * 500, 12)
        self.assertTrue(res)
        mock_notify.assert_called_once_with(
            "Spacekeeper",
            "정리 가능한 후보 12개 (500.0 MB)를 발견했습니다.",
            subtitle="저장공간 분석 완료",
        )

    @patch("spacekeeper.notifier.notify_macos", return_value=True)
    def test_notify_quarantine_action_formats_message(self, mock_notify: MagicMock) -> None:
        notify_quarantine_action(restored=False, item_count=3, total_bytes=2048 * 1024)
        mock_notify.assert_called_with(
            "Spacekeeper",
            "선택 항목 3개 (2.0 MB)를 안전하게 격리함으로 옮겼습니다.",
            subtitle="격리함 이동 완료",
        )

        notify_quarantine_action(restored=True, item_count=1, total_bytes=1024)
        mock_notify.assert_called_with(
            "Spacekeeper",
            "격리 항목 1개 (1.0 KB)를 원래 위치로 복구했습니다.",
            subtitle="원래 위치로 복구 완료",
        )
