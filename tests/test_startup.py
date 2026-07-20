from __future__ import annotations

import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spacekeeper import startup


def _write_plist(path: Path, label: str, program: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        plistlib.dump(
            {"Label": label, "ProgramArguments": [program], "RunAtLoad": True},
            handle,
        )


class StartupItemTests(unittest.TestCase):
    def test_lists_user_items_as_manageable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp) / "LaunchAgents"
            _write_plist(agents / "com.demo.agent.plist", "com.demo.agent", "/bin/true")
            with mock.patch.object(startup, "USER_AGENTS", agents), \
                    mock.patch.object(startup, "SYSTEM_DIRS", ()):
                result = startup.list_startup_items()
            self.assertEqual(result["user_count"], 1)
            self.assertEqual(result["manageable_count"], 1)
            item = result["items"][0]
            self.assertEqual(item["label"], "com.demo.agent")
            self.assertTrue(item["run_at_load"])
            self.assertTrue(item["manageable"])

    def test_system_items_are_listed_but_not_manageable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            system = Path(tmp) / "SystemAgents"
            _write_plist(system / "com.vendor.daemon.plist", "com.vendor.daemon", "/bin/true")
            with mock.patch.object(startup, "USER_AGENTS", Path(tmp) / "none"), \
                    mock.patch.object(startup, "SYSTEM_DIRS", (system,)):
                result = startup.list_startup_items()
            self.assertEqual(result["system_count"], 1)
            self.assertEqual(result["manageable_count"], 0)
            self.assertFalse(result["items"][0]["manageable"])

    def test_ignores_broken_plist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp) / "LaunchAgents"
            agents.mkdir(parents=True)
            (agents / "broken.plist").write_bytes(b"not a plist at all")
            with mock.patch.object(startup, "USER_AGENTS", agents), \
                    mock.patch.object(startup, "SYSTEM_DIRS", ()):
                result = startup.list_startup_items()
            self.assertEqual(result["user_count"], 0)


if __name__ == "__main__":
    unittest.main()
