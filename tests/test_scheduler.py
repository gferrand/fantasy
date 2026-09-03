from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fantasy_advisor.automation import TaskSpec
from fantasy_advisor.scheduler import _next_task_time, _sleep_until


class SchedulerTimingTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
