from __future__ import annotations

import plistlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from spacekeeper import launchd_agent, scheduler
from spacekeeper.scheduler import ScheduleConfig


class ScheduleConfigTests(unittest.TestCase):
    """Tests for *scheduler.load_schedule*, *save_schedule*, and serialization helpers."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.config_path = self.tmp_path / "schedule.json"
        self._patch = mock.patch.object(scheduler, "CONFIG_PATH", self.config_path)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    # -- load_schedule ---------------------------------------------------------

    def test_load_schedule_returns_defaults_when_missing(self) -> None:
        cfg = scheduler.load_schedule()
        self.assertIsInstance(cfg, ScheduleConfig)
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.interval_hours, 168)
        self.assertFalse(cfg.auto_quarantine_low_risk)
        self.assertTrue(cfg.notify)
        self.assertIsNone(cfg.last_run_at)

    # -- save / load roundtrip -------------------------------------------------

    def test_save_and_load_roundtrip(self) -> None:
        original = ScheduleConfig(
            enabled=True,
            interval_hours=24,
            auto_quarantine_low_risk=False,
            notify=False,
            last_run_at=1_700_000_000.0,
        )
        scheduler.save_schedule(original)
        loaded = scheduler.load_schedule()
        self.assertEqual(loaded.enabled, original.enabled)
        self.assertEqual(loaded.interval_hours, original.interval_hours)
        self.assertEqual(loaded.auto_quarantine_low_risk, original.auto_quarantine_low_risk)
        self.assertEqual(loaded.notify, original.notify)
        self.assertEqual(loaded.last_run_at, original.last_run_at)

    # -- to_dict / from_dict ---------------------------------------------------

    def test_to_dict_contains_all_fields(self) -> None:
        cfg = ScheduleConfig(enabled=True, last_run_at=99.9)
        d = scheduler.to_dict(cfg)
        self.assertIn("enabled", d)
        self.assertIn("interval_hours", d)
        self.assertIn("auto_quarantine_low_risk", d)
        self.assertIn("notify", d)
        self.assertIn("last_run_at", d)
        self.assertTrue(d["enabled"])
        self.assertEqual(d["last_run_at"], 99.9)

    def test_from_dict_with_empty_dict_returns_defaults(self) -> None:
        cfg = scheduler.from_dict({})
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.interval_hours, 168)
        self.assertFalse(cfg.auto_quarantine_low_risk)
        self.assertTrue(cfg.notify)
        self.assertIsNone(cfg.last_run_at)

    def test_from_dict_with_partial_data(self) -> None:
        cfg = scheduler.from_dict({"enabled": True, "interval_hours": 48})
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.interval_hours, 48)
        # remaining fields fall back to defaults
        self.assertFalse(cfg.auto_quarantine_low_risk)
        self.assertTrue(cfg.notify)
        self.assertIsNone(cfg.last_run_at)

    def test_from_dict_rejects_invalid_types_and_intervals(self) -> None:
        for payload in (
            {"enabled": "yes"},
            {"interval_hours": 0},
            {"interval_hours": True},
            {"notify": 1},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    scheduler.from_dict(payload)

    # -- run_scheduled ---------------------------------------------------------

    def test_run_scheduled_skips_when_disabled(self) -> None:
        scheduler.save_schedule(ScheduleConfig(enabled=False))
        result = scheduler.run_scheduled()
        self.assertEqual(result["status"], "skipped")

    def test_run_scheduled_notify_only_does_not_quarantine(self) -> None:
        """기본 설정(자동 격리 off)에서는 백그라운드가 파일을 옮기지 않는다."""
        scheduler.save_schedule(
            ScheduleConfig(enabled=True, auto_quarantine_low_risk=False, notify=False)
        )
        fake_result = mock.Mock(
            file_candidate_count=2, cache_candidate_count=1, review_candidate_bytes=50
        )
        with mock.patch("spacekeeper.scanner.scan", return_value=fake_result), \
                mock.patch("spacekeeper.engine.quarantine") as quarantine:
            result = scheduler.run_scheduled(now=1.0)
        quarantine.assert_not_called()
        self.assertEqual(result["quarantined"], 0)
        self.assertEqual(result["candidate_count"], 3)
        self.assertEqual(scheduler.load_schedule().last_run_at, 1.0)

    def test_run_scheduled_auto_quarantine_moves_low_risk(self) -> None:
        """명시적으로 켰을 때만 낮은 위험 후보를 격리한다."""
        scheduler.save_schedule(
            ScheduleConfig(enabled=True, auto_quarantine_low_risk=True, notify=False)
        )
        fake_result = mock.Mock(
            file_candidate_count=1, cache_candidate_count=0, review_candidate_bytes=100
        )
        fake_entry = mock.Mock(
            action_id="C-x",
            path="/tmp/x",
            kind="cache_directory",
            category="pip_cache",
        )
        fake_plan = mock.Mock(entries=[fake_entry])
        fake_outcome = mock.Mock(moved=[fake_entry], quarantined_bytes=100)
        with mock.patch("spacekeeper.scanner.scan", return_value=fake_result), \
                mock.patch(
                    "spacekeeper.planning.build_cleanup_plan", return_value=fake_plan
                ) as build_plan, \
                mock.patch(
                    "spacekeeper.engine.quarantine", return_value=fake_outcome
                ) as quarantine:
            result = scheduler.run_scheduled(now=123.0)
        # 낮은 위험만 대상으로 계획을 세운다.
        self.assertEqual(build_plan.call_args.kwargs["risks"], {"low"})
        quarantine.assert_called_once_with([("C-x", "/tmp/x", "cache_directory")])
        self.assertEqual(result["quarantined"], 1)
        self.assertEqual(result["quarantined_bytes"], 100)
        self.assertEqual(result["disk_space_freed_bytes"], 0)

    def test_run_scheduled_auto_quarantine_excludes_project_dependencies(
        self,
    ) -> None:
        scheduler.save_schedule(
            ScheduleConfig(
                enabled=True,
                auto_quarantine_low_risk=True,
                notify=False,
            )
        )
        fake_result = mock.Mock(
            file_candidate_count=0,
            cache_candidate_count=2,
            review_candidate_bytes=200,
        )
        safe = mock.Mock(
            action_id="C-safe",
            path="/tmp/cache",
            kind="cache_directory",
            category="pip_cache",
        )
        project = mock.Mock(
            action_id="C-project",
            path="/tmp/node_modules",
            kind="cache_directory",
            category="project_dependency",
        )
        fake_plan = mock.Mock(entries=[safe, project])
        fake_outcome = mock.Mock(moved=[safe], quarantined_bytes=100)
        with (
            mock.patch("spacekeeper.scanner.scan", return_value=fake_result),
            mock.patch(
                "spacekeeper.planning.build_cleanup_plan",
                return_value=fake_plan,
            ),
            mock.patch(
                "spacekeeper.engine.quarantine",
                return_value=fake_outcome,
            ) as quarantine,
        ):
            scheduler.run_scheduled(now=123.0)

        quarantine.assert_called_once_with(
            [("C-safe", "/tmp/cache", "cache_directory")]
        )


class LaunchdAgentTests(unittest.TestCase):
    """Tests for *launchd_agent* plist generation and install helpers."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.plist_path = self.tmp_path / "com.spacekeeper.agent.plist"
        self._patches = [
            mock.patch.object(launchd_agent, "PLIST_PATH", self.plist_path),
            mock.patch.object(
                launchd_agent,
                "LOG_PATH",
                self.tmp_path / ".spacekeeper" / "agent.log",
            ),
        ]
        for patcher in self._patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self._patches):
            patcher.stop()
        self._tmp.cleanup()

    # -- is_agent_installed ----------------------------------------------------

    def test_is_agent_installed_returns_false_when_no_plist(self) -> None:
        self.assertFalse(launchd_agent.is_agent_installed())

    def test_is_agent_installed_returns_true_when_plist_exists(self) -> None:
        with self.plist_path.open("wb") as handle:
            plistlib.dump(
                {
                    "Label": launchd_agent.PLIST_LABEL,
                    "ProgramArguments": [launchd_agent.sys.executable],
                },
                handle,
            )
        self.assertTrue(launchd_agent.is_agent_installed())

    def test_is_agent_installed_rejects_stale_executable(self) -> None:
        with self.plist_path.open("wb") as handle:
            plistlib.dump(
                {
                    "Label": launchd_agent.PLIST_LABEL,
                    "ProgramArguments": [str(self.tmp_path / "missing")],
                },
                handle,
            )
        self.assertFalse(launchd_agent.is_agent_installed())

    # -- install_launchd_agent (plist content) ---------------------------------

    @mock.patch("spacekeeper.launchd_agent.subprocess.run")
    def test_install_generates_valid_plist(self, mock_run: mock.MagicMock) -> None:
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = launchd_agent.install_launchd_agent(interval_hours=24)
        self.assertTrue(result)
        self.assertTrue(self.plist_path.exists())

        with self.plist_path.open("rb") as fh:
            plist = plistlib.load(fh)

        self.assertEqual(plist["Label"], "com.spacekeeper.agent")
        self.assertEqual(plist["StartInterval"], 24 * 3600)
        self.assertIn("--scheduled-run", plist["ProgramArguments"])

    @mock.patch("spacekeeper.launchd_agent.subprocess.run")
    def test_install_calls_launchctl_load(self, mock_run: mock.MagicMock) -> None:
        mock_run.return_value = mock.MagicMock(returncode=0)
        launchd_agent.install_launchd_agent()
        self.assertEqual(mock_run.call_count, 2)
        mock_run.assert_has_calls(
            [
                mock.call(
                    ["launchctl", "unload", str(self.plist_path)],
                    check=False,
                    stdout=launchd_agent.subprocess.DEVNULL,
                    stderr=launchd_agent.subprocess.DEVNULL,
                ),
                mock.call(
                    ["launchctl", "load", str(self.plist_path)],
                    check=True,
                    stdout=launchd_agent.subprocess.DEVNULL,
                    stderr=launchd_agent.subprocess.DEVNULL,
                ),
            ]
        )

    # -- uninstall_launchd_agent -----------------------------------------------

    @mock.patch("spacekeeper.launchd_agent.subprocess.run")
    def test_uninstall_removes_plist(self, mock_run: mock.MagicMock) -> None:
        self.plist_path.write_bytes(b"<plist/>")
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = launchd_agent.uninstall_launchd_agent()
        self.assertTrue(result)
        self.assertFalse(self.plist_path.exists())

    @mock.patch("spacekeeper.launchd_agent.subprocess.run")
    def test_uninstall_missing_agent_is_success(
        self, mock_run: mock.MagicMock
    ) -> None:
        self.assertTrue(launchd_agent.uninstall_launchd_agent())
        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
