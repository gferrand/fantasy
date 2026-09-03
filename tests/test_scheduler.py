from datetime import datetime, timezone
from pathlib import Path
import sys
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
            discord_allowed_user_id="123", discord_scheduled_channel_id=None, codex_bin="codex",
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

    def test_sleep_uses_exact_nearest_known_target(self):
        now = datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(_sleep_until(now, datetime(2026, 9, 3, 10, 12, tzinfo=timezone.utc), datetime(2026, 9, 3, 11, 0, tzinfo=timezone.utc)), 720.0)

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
            patch.object(scheduler.time, "sleep", side_effect=_StopScheduler),
        ):
            with self.assertRaises(_StopScheduler):
                scheduler.main()
        alert.assert_called_once_with(self._config(), now=now, schedule=schedule)

    def test_main_retries_a_failed_initial_calendar_load_after_fifteen_minutes(self):
        now = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
        with (
            patch.object(scheduler.AppConfig, "from_environment", return_value=self._config()),
            patch.object(scheduler, "load_registry", return_value=TaskRegistry("UTC", ())),
            patch.object(scheduler, "load_fixture_schedule", side_effect=AutomationError("offline")),
            patch.object(scheduler, "datetime", self._fixed_clock(now)),
            patch.object(scheduler.time, "sleep", side_effect=_StopScheduler) as sleep,
        ):
            with self.assertRaises(_StopScheduler):
                scheduler.main()
        self.assertEqual(sleep.call_args.args, (900.0,))


if __name__ == "__main__":
    unittest.main()
