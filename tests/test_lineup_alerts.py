from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fantasy_advisor.automation import AppConfig, FANTASY_CODEX_MODEL, FANTASY_CODEX_REASONING_EFFORT, WebResult
from fantasy_advisor.gameweek import GameweekContext
from fantasy_advisor.lineup_alerts import (
    due_fixtures,
    fixture_alert_windows,
    load_fixture_schedule,
    roster_fixtures,
    run_lineup_alerts,
)


class _FixtureClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_schedule(self, start, end):
        self.calls.append((start, end))
        return self.payload


class _Transport:
    def __init__(self):
        self.messages = []

    def send_dm(self, user_id, text):
        self.messages.append((user_id, text))


class LineupAlertTests(unittest.TestCase):
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)

    def _context(self):
        return GameweekContext(
            "prepare", "2026", 3, "now",
            {
                "gameweek": 3,
                "your_team": {
                    "current_starters": ["giles"],
                    "players": [
                        {"player_id": "giles", "name": "Ryan Giles", "club": "HUL", "positions": ["D"], "injury_status": None, "stats": {"gp": 2}},
                        {"player_id": "gakpo", "name": "Cody Gakpo", "club": "LIV", "positions": ["F"], "injury_status": None, "stats": {"gp": 2}},
                    ],
                },
                "starting_slots": ["F", "D"],
            },
        )

    def _schedule(self):
        return {"events": [
            {"id": "fixture-hul", "date": "2026-09-05T13:00:00Z", "competitions": [{"competitors": [
                {"homeAway": "home", "team": {"displayName": "Hull City"}},
                {"homeAway": "away", "team": {"displayName": "Arsenal"}},
            ]}]},
            {"id": "fixture-liv", "date": "2026-09-05T13:00:00Z", "competitions": [{"competitors": [
                {"homeAway": "home", "team": {"displayName": "Liverpool"}},
                {"homeAway": "away", "team": {"displayName": "Everton"}},
            ]}]},
            {"id": "fixture-none", "date": "2026-09-05T13:00:00Z", "competitions": [{"competitors": [
                {"homeAway": "home", "team": {"displayName": "Everton"}},
                {"homeAway": "away", "team": {"displayName": "Fulham"}},
            ]}]},
        ]}

    def _config(self, root):
        return AppConfig(
            repo_root=root, task_registry_path=root / "tasks.toml", discord_bot_token="token",
            discord_allowed_user_id="123", discord_scheduled_channel_id=None, codex_bin="codex",
            codex_model=FANTASY_CODEX_MODEL, codex_reasoning_effort=FANTASY_CODEX_REASONING_EFFORT,
            codex_sandbox="read-only", codex_timeout_seconds=60, codex_ephemeral=False,
        )

    def test_roster_fixtures_and_due_window_only_include_relevant_unsent_games(self):
        fixtures = roster_fixtures(self._context(), self._schedule())
        self.assertEqual(len(fixtures), 2)
        self.assertEqual(fixtures[0].players[0]["name"], "Ryan Giles")
        self.assertEqual(due_fixtures(fixtures, now=self.now, lead_minutes=90, sent=set()), fixtures)
        self.assertEqual(len(due_fixtures(fixtures, now=self.now, lead_minutes=90, sent={"fixture-hul"})), 1)

    def test_alert_is_private_and_sent_once_after_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            transport = _Transport()
            analyst_calls = []

            def analyst(_config, *, live_context):
                analyst_calls.append(json.loads(live_context))
                return WebResult("⏰ **Lineup check**\nSTART Ryan Giles.", "response", 1.0)

            kwargs = {
                "now": self.now,
                "fixture_client": _FixtureClient(self._schedule()),
                "prepare_loader": lambda **_kwargs: self._context(),
                "analyst": analyst,
                "transport": transport,
            }
            self.assertEqual(run_lineup_alerts(config, **kwargs), 1)
            self.assertEqual(run_lineup_alerts(config, **kwargs), 0)
            self.assertEqual(transport.messages, [("123", "⏰ **Lineup check**\nSTART Ryan Giles.")])
            self.assertEqual(analyst_calls[0]["fixtures"][0]["event_id"], "fixture-hul")
            self.assertEqual(len(analyst_calls[0]["fixtures"]), 2)

    def test_published_schedule_is_cached_and_yields_exact_alert_times(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            fixture_client = _FixtureClient(self._schedule())
            schedule = load_fixture_schedule(config, now=self.now, fixture_client=fixture_client)
            again = load_fixture_schedule(config, now=self.now, fixture_client=fixture_client)
            windows = fixture_alert_windows(schedule, now=self.now, lead_minutes=90)
            self.assertIs(schedule, schedule)
            self.assertEqual(again, schedule)
            self.assertEqual(len(fixture_client.calls), 1)
            self.assertEqual(fixture_client.calls[0], (
                datetime(2026, 8, 1, tzinfo=timezone.utc),
                datetime(2027, 6, 15, tzinfo=timezone.utc),
            ))
            self.assertEqual(windows[0].alert_at, datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc))
            self.assertEqual({window.event_id for window in windows[:2]}, {"fixture-hul", "fixture-liv"})


if __name__ == "__main__":
    unittest.main()
