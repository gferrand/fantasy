from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fantasy_advisor.automation import (
    AppConfig,
    AutomationError,
    FANTASY_CODEX_MODEL,
    FANTASY_CODEX_REASONING_EFFORT,
    TaskRegistry,
    TaskSpec,
)
from fantasy_advisor import scheduler
from fantasy_advisor.scheduler import _next_task_time, _sleep_until


class _StopScheduler(Exception):
    pass


class SchedulerTimingTests(unittest.TestCase):
    def _config(self):
        return AppConfig(
            repo_root=ROOT, task_registry_path=ROOT / "tasks.toml", discord_bot_token="token",
            discord_allowed_user_id="123", codex_bin="codex",
            codex_model=FANTASY_CODEX_MODEL, codex_reasoning_effort=FANTASY_CODEX_REASONING_EFFORT,
            codex_sandbox="read-only", codex_timeout_seconds=60, codex_ephemeral=False,
        )

    @staticmethod
    def _fixed_clock(now):
        return type("FixedDateTime", (), {"now": staticmethod(lambda _zone: now)})

    def test_next_task_time_skips_current_minute_and_uses_nearest_future_task(self):
        now = datetime(2026, 9, 3, 10, 17, 5, tzinfo=timezone.utc)
        tasks = (
            TaskSpec("hourly", "Hourly", ROOT / "x", "hourly", minute_past_hour=17),
            TaskSpec("daily", "Daily", ROOT / "x", "daily", run_at="22:00"),
        )
        self.assertEqual(_next_task_time(tasks, now), datetime(2026, 9, 3, 11, 17, tzinfo=timezone.utc))

    def test_disabled_task_is_excluded_from_due_and_next_run_calculation(self):
        now = datetime(2026, 9, 3, 10, 17, 5, tzinfo=timezone.utc)
        paused_hourly = TaskSpec(
            "transfer_monitor", "Transfer", ROOT / "x", "hourly", minute_past_hour=17, enabled=False,
        )
        active_daily = TaskSpec("daily", "Daily", ROOT / "x", "daily", run_at="22:00")
        self.assertFalse(scheduler._is_due(paused_hourly, now.replace(second=0)))
        self.assertEqual(
            _next_task_time((paused_hourly, active_daily), now),
            datetime(2026, 9, 3, 22, 0, tzinfo=timezone.utc),
        )

    def test_sleep_uses_exact_nearest_known_target(self):
        now = datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(_sleep_until(now, datetime(2026, 9, 3, 10, 12, tzinfo=timezone.utc), datetime(2026, 9, 3, 11, 0, tzinfo=timezone.utc)), 720.0)

    def test_busy_health_lease_uses_timeout_overhead_cap_and_retains_failures(self):
        config = self._config()
        with (
            patch.object(scheduler.time, "time", return_value=1_000.0),
            patch.object(scheduler, "write_health_state") as heartbeat,
        ):
            scheduler._write_scheduler_health(config, {"fixture_schedule"}, busy=True)

        heartbeat.assert_called_once_with(
            config.repo_root,
            "scheduler",
            healthy=False,
            unhealthy_components={"fixture_schedule"},
            now=1_000.0,
            busy_until=1_240.0,
        )
        self.assertEqual(
            scheduler._busy_lease_seconds(replace(config, codex_timeout_seconds=5_000)),
            3_600.0,
        )

    def test_main_leases_every_synchronous_task_and_check(self):
        now = datetime(2026, 9, 3, 22, 0, tzinfo=timezone.utc)
        task = TaskSpec("nightly_recap", "Nightly", ROOT / "x", "daily", run_at="22:00")
        schedule = {"events": []}
        events = []

        def heartbeat(_root, _component, **kwargs):
            events.append(("health", kwargs["busy_until"] is not None))

        def record(name, result=None):
            def callback(*_args, **_kwargs):
                events.append((name, None))
                return result

            return callback

        lineup_window = SimpleNamespace(
            event_id="fixture-1",
            alert_at=now,
            kickoff=now + timedelta(minutes=90),
        )
        with (
            patch.object(scheduler.AppConfig, "from_environment", return_value=self._config()),
            patch.object(scheduler, "load_registry", return_value=TaskRegistry("UTC", (task,))),
            patch.object(scheduler, "run_scheduled_task", side_effect=record("task")),
            patch.object(scheduler, "load_fixture_schedule", side_effect=record("fixture_load", schedule)),
            patch.object(scheduler, "fixture_alert_windows", side_effect=record("lineup_check", (lineup_window,))),
            patch.object(scheduler, "run_lineup_alerts", side_effect=record("lineup_run", 1)),
            patch.object(scheduler, "final_reminder_windows", side_effect=record("guardian_check", (now,))),
            patch.object(scheduler, "run_deadline_guardian", side_effect=record("guardian_run", 1)),
            patch.object(scheduler, "datetime", self._fixed_clock(now)),
            patch.object(scheduler, "write_health_state", side_effect=heartbeat),
            patch.object(scheduler.time, "sleep", side_effect=_StopScheduler),
        ):
            with self.assertRaises(_StopScheduler):
                scheduler.main()

        self.assertEqual(
            events,
            [
                ("health", False),
                ("health", True), ("task", None), ("health", False),
                ("health", True), ("fixture_load", None), ("health", False),
                ("health", True), ("lineup_check", None), ("lineup_run", None), ("health", False),
                ("health", True), ("guardian_check", None), ("guardian_run", None), ("health", False),
                ("health", False),
            ],
        )

    def test_main_invokes_alert_at_the_exact_pre_kickoff_window(self):
        now = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
        schedule = {"events": [{
            "id": "fixture-1", "date": "2026-09-03T13:30:00Z", "competitions": [{"competitors": [
                {"homeAway": "home", "team": {"displayName": "Brentford"}},
                {"homeAway": "away", "team": {"displayName": "Arsenal"}},
            ]}],
        }]}
        with (
            patch.object(scheduler.AppConfig, "from_environment", return_value=self._config()),
            patch.object(scheduler, "load_registry", return_value=TaskRegistry("UTC", ())),
            patch.object(scheduler, "load_fixture_schedule", return_value=schedule),
            patch.object(scheduler, "run_lineup_alerts", return_value=1) as alert,
            patch.object(scheduler, "datetime", self._fixed_clock(now)),
            patch.object(scheduler, "write_health_state") as heartbeat,
            patch.object(scheduler.time, "sleep", side_effect=_StopScheduler),
        ):
            with self.assertRaises(_StopScheduler):
                scheduler.main()
        alert.assert_called_once_with(self._config(), now=now, schedule=schedule)
        self.assertTrue(heartbeat.call_args.kwargs["healthy"])

    def test_main_retries_a_failed_initial_calendar_load_after_fifteen_minutes(self):
        now = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
        with (
            patch.object(scheduler.AppConfig, "from_environment", return_value=self._config()),
            patch.object(scheduler, "load_registry", return_value=TaskRegistry("UTC", ())),
            patch.object(scheduler, "load_fixture_schedule", side_effect=AutomationError("offline")),
            patch.object(scheduler, "datetime", self._fixed_clock(now)),
            patch.object(scheduler, "write_health_state") as heartbeat,
            patch.object(scheduler.time, "sleep", side_effect=_StopScheduler) as sleep,
        ):
            with self.assertRaises(_StopScheduler):
                scheduler.main()
        self.assertEqual(sleep.call_args.args, (60.0,))
        self.assertFalse(heartbeat.call_args.kwargs["healthy"])
        self.assertEqual(heartbeat.call_args.kwargs["unhealthy_components"], {"fixture_schedule"})

    def test_main_reports_a_failed_scheduled_task_as_unhealthy(self):
        now = datetime(2026, 9, 3, 22, 0, tzinfo=timezone.utc)
        task = TaskSpec("nightly_recap", "Nightly", ROOT / "x", "daily", run_at="22:00")
        with (
            patch.object(scheduler.AppConfig, "from_environment", return_value=self._config()),
            patch.object(scheduler, "load_registry", return_value=TaskRegistry("UTC", (task,))),
            patch.object(scheduler, "run_scheduled_task", side_effect=AutomationError("offline")),
            patch.object(scheduler, "load_fixture_schedule", return_value={"events": []}),
            patch.object(scheduler, "datetime", self._fixed_clock(now)),
            patch.object(scheduler, "write_health_state") as heartbeat,
            patch.object(scheduler.time, "sleep", side_effect=_StopScheduler),
        ):
            with self.assertRaises(_StopScheduler):
                scheduler.main()

        self.assertFalse(heartbeat.call_args.kwargs["healthy"])
        self.assertEqual(
            heartbeat.call_args.kwargs["unhealthy_components"],
            {"task:nightly_recap"},
        )


if __name__ == "__main__":
    unittest.main()
