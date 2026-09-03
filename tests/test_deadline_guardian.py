from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fantasy_advisor.automation import AppConfig, FANTASY_CODEX_MODEL, FANTASY_CODEX_REASONING_EFFORT, WebResult
from fantasy_advisor.deadline_guardian import (
    acknowledge_active_events,
    active_events,
    final_reminder_events,
    final_reminder_windows,
    mark_final_reminded,
    record_initial_alerts,
)
from fantasy_advisor.gameweek import GameweekContext
from fantasy_advisor.lineup_alerts import LineupFixture, run_deadline_guardian


class _Transport:
    def __init__(self):
        self.messages = []

    def send_dm(self, user_id, text):
        self.messages.append((user_id, text))


class DeadlineGuardianTests(unittest.TestCase):
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)

    def _config(self, root):
        return AppConfig(
            repo_root=root, task_registry_path=root / "tasks.toml", discord_bot_token="token",
            discord_allowed_user_id="123", discord_scheduled_channel_id=None, codex_bin="codex",
            codex_model=FANTASY_CODEX_MODEL, codex_reasoning_effort=FANTASY_CODEX_REASONING_EFFORT,
            codex_sandbox="read-only", codex_timeout_seconds=60, codex_ephemeral=False,
        )

    def _fixture(self):
        return LineupFixture(
            "fixture-1", self.now + timedelta(minutes=90), "Brentford", "Arsenal",
            ({"player_id": "one", "name": "Test Player", "club": "BRE"},),
        )

    def _context(self):
        return GameweekContext("prepare", "2026", 3, "now", {
            "gameweek": 3,
            "your_team": {"players": [{"player_id": "one", "name": "Test Player", "club": "BRE"}], "current_starters": ["one"]},
            "starting_slots": ["M"],
        })

    def _schedule(self):
        return {"events": [{"id": "fixture-1", "date": "2026-09-05T13:30:00Z", "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"displayName": "Brentford"}},
            {"homeAway": "away", "team": {"displayName": "Arsenal"}},
        ]}]}]}

    def test_acknowledgement_persists_across_restart_and_suppresses_final_reminder(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            record_initial_alerts(config, [self._fixture()], now=self.now)
            self.assertEqual(final_reminder_windows(config, now=self.now, lead_minutes=20), (self.now + timedelta(minutes=70),))
            acknowledged = acknowledge_active_events(config, now=self.now + timedelta(minutes=1))
            self.assertEqual([item.event_id for item in acknowledged], ["fixture-1"])
            self.assertEqual(len(active_events(config, now=self.now + timedelta(minutes=2))), 1)
            self.assertEqual(final_reminder_events(config, now=self.now + timedelta(minutes=70), lead_minutes=20), ())

    def test_unacknowledged_fixture_gets_one_final_live_recheck(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            record_initial_alerts(config, [self._fixture()], now=self.now)
            transport = _Transport()
            reminder_time = self.now + timedelta(minutes=70)
            self.assertEqual(
                run_deadline_guardian(
                    config, now=reminder_time, schedule=self._schedule(),
                    prepare_loader=lambda **_kwargs: self._context(),
                    analyst=lambda *_args, **_kwargs: WebResult("Latest team news", None, 0),
                    transport=transport,
                ),
                1,
            )
            self.assertIn("Final lineup check", transport.messages[0][1])
            self.assertIn("Latest team news", transport.messages[0][1])
            self.assertEqual(
                run_deadline_guardian(
                    config, now=reminder_time + timedelta(minutes=1), schedule=self._schedule(),
                    prepare_loader=lambda **_kwargs: self._context(),
                    analyst=lambda *_args, **_kwargs: self.fail("Final reminder must be sent once"),
                    transport=transport,
                ),
                0,
            )

    def test_dropped_player_suppresses_stale_final_reminder(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            record_initial_alerts(config, [self._fixture()], now=self.now)
            dropped = GameweekContext("prepare", "2026", 3, "now", {
                "gameweek": 3, "your_team": {"players": [], "current_starters": []}, "starting_slots": ["M"],
            })
            transport = _Transport()
            self.assertEqual(
                run_deadline_guardian(
                    config, now=self.now + timedelta(minutes=70), schedule=self._schedule(),
                    prepare_loader=lambda **_kwargs: dropped,
                    analyst=lambda *_args, **_kwargs: self.fail("Dropped player needs no escalation"),
                    transport=transport,
                ),
                0,
            )
            self.assertEqual(transport.messages, [])
            self.assertEqual(final_reminder_events(config, now=self.now + timedelta(minutes=71), lead_minutes=20), ())

    def test_final_reminder_state_is_durable_after_a_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            record_initial_alerts(config, [self._fixture()], now=self.now)
            mark_final_reminded(config, ["fixture-1"], now=self.now + timedelta(minutes=70))
            self.assertEqual(final_reminder_windows(config, now=self.now + timedelta(minutes=71), lead_minutes=20), ())


if __name__ == "__main__":
    unittest.main()
