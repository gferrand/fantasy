from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fantasy_advisor.automation import AppConfig, AutomationError, FANTASY_CODEX_MODEL, FANTASY_CODEX_REASONING_EFFORT, WebResult
from fantasy_advisor.gameweek import GameweekContext
from fantasy_advisor.lineup_alerts import (
    due_fixtures,
    fixture_alert_windows,
    load_fixture_schedule,
    load_persisted_fixture_schedule,
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


class _FailOnceTransport(_Transport):
    def __init__(self):
        super().__init__()
        self.failures_remaining = 1

    def send_dm(self, user_id, text):
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise AutomationError("simulated Discord outage")
        super().send_dm(user_id, text)


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

    def _complete_schedule(self):
        seed = self._schedule()["events"]
        events = []
        for index in range(380):
            source = json.loads(json.dumps(seed[index % len(seed)]))
            source["id"] = f"season-{index}"
            events.append(source)
        return {"events": events}

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

    def test_persisted_fixture_schedule_never_refreshes_or_accepts_partial_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            path = config.repo_root / "data" / "automation" / "lineup_fixtures.json"
            path.parent.mkdir(parents=True)
            complete = self._complete_schedule()
            path.write_text(json.dumps({"retrieved_at": "now", "schedule": complete}), encoding="utf-8")
            self.assertEqual(load_persisted_fixture_schedule(config), complete)
            path.write_text(json.dumps({"schedule": self._schedule()}), encoding="utf-8")
            with self.assertRaisesRegex(AutomationError, "incomplete or invalid"):
                load_persisted_fixture_schedule(config)

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
                "schedule": self._schedule(),
                "prepare_loader": lambda **_kwargs: self._context(),
                "analyst": analyst,
                "transport": transport,
            }
            self.assertEqual(run_lineup_alerts(config, **kwargs), 1)
            self.assertEqual(run_lineup_alerts(config, **kwargs), 0)
            self.assertEqual(len(transport.messages), 1)
            self.assertIn("START Ryan Giles.", transport.messages[0][1])
            self.assertIn("/guardian done", transport.messages[0][1])
            self.assertEqual(analyst_calls[0]["fixtures"][0]["event_id"], "fixture-hul")
            self.assertEqual(len(analyst_calls[0]["fixtures"]), 2)

    def test_future_fixture_does_not_alert_after_player_is_dropped(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            transport = _Transport()
            dropped_context = GameweekContext(
                "prepare", "2026", 10, "later",
                {
                    "gameweek": 10,
                    "your_team": {"current_starters": [], "players": []},
                    "starting_slots": ["F", "D"],
                },
            )
            self.assertEqual(
                run_lineup_alerts(
                    config,
                    now=self.now,
                    schedule=self._schedule(),
                    prepare_loader=lambda **_kwargs: dropped_context,
                    analyst=lambda *_args, **_kwargs: self.fail("No analysis should run without a rostered player"),
                    transport=transport,
                ),
                0,
            )
            self.assertEqual(transport.messages, [])

    def test_research_failure_sends_factual_fallback_and_records_delivery(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            transport = _Transport()
            result = run_lineup_alerts(
                config,
                now=self.now,
                schedule=self._schedule(),
                prepare_loader=lambda **_kwargs: self._context(),
                analyst=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("simulated research outage")),
                transport=transport,
            )
            self.assertEqual(result, 1)
            self.assertEqual(len(transport.messages), 1)
            self.assertIn("Live roster + fixture match detected", transport.messages[0][1])
            self.assertEqual(
                run_lineup_alerts(
                    config,
                    now=self.now,
                    schedule=self._schedule(),
                    prepare_loader=lambda **_kwargs: self._context(),
                    analyst=lambda *_args, **_kwargs: self.fail("Delivered events must not be re-researched"),
                    transport=transport,
                ),
                0,
            )

    def test_discord_failure_leaves_fixture_pending_for_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            transport = _FailOnceTransport()
            with self.assertRaisesRegex(AutomationError, "Discord outage"):
                run_lineup_alerts(
                    config,
                    now=self.now,
                    schedule=self._schedule(),
                    prepare_loader=lambda **_kwargs: self._context(),
                    analyst=lambda *_args, **_kwargs: WebResult("test alert", None, 0),
                    transport=transport,
                )
            self.assertEqual(
                run_lineup_alerts(
                    config,
                    now=self.now,
                    schedule=self._schedule(),
                    prepare_loader=lambda **_kwargs: self._context(),
                    analyst=lambda *_args, **_kwargs: WebResult("retry alert", None, 0),
                    transport=transport,
                ),
                1,
            )
            self.assertEqual(len(transport.messages), 1)
            self.assertIn("retry alert", transport.messages[0][1])

    def test_malformed_sent_state_is_quarantined_and_does_not_suppress_an_alert(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            state = config.repo_root / "data" / "automation" / "lineup_alerts.json"
            state.parent.mkdir(parents=True)
            state.write_text("not json", encoding="utf-8")
            transport = _Transport()
            self.assertEqual(
                run_lineup_alerts(
                    config,
                    now=self.now,
                    schedule=self._schedule(),
                    prepare_loader=lambda **_kwargs: self._context(),
                    analyst=lambda *_args, **_kwargs: WebResult("recovered alert", None, 0),
                    transport=transport,
                ),
                1,
            )
            self.assertTrue(state.with_suffix(".json.corrupt").exists())
            self.assertEqual(len(transport.messages), 1)
            self.assertIn("recovered alert", transport.messages[0][1])

    def test_local_season_schedule_is_reused_even_after_months(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            fixture_client = _FixtureClient(self._complete_schedule())
            schedule = load_fixture_schedule(config, now=self.now, fixture_client=fixture_client)
            again = load_fixture_schedule(config, now=self.now + timedelta(days=100), fixture_client=fixture_client)
            windows = fixture_alert_windows(schedule, now=self.now, lead_minutes=90)
            self.assertIs(schedule, schedule)
            self.assertEqual(again, schedule)
            self.assertEqual(len(fixture_client.calls), 1)
            self.assertEqual(fixture_client.calls[0], (
                datetime(2026, 8, 1, tzinfo=timezone.utc),
                datetime(2027, 6, 15, tzinfo=timezone.utc),
            ))
            self.assertEqual(windows[0].alert_at, datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc))
            self.assertEqual({window.event_id for window in windows[:2]}, {"season-0", "season-1"})

    def test_incomplete_local_schedule_is_replaced_before_it_can_be_used(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            cache = config.repo_root / "data" / "automation" / "lineup_fixtures.json"
            cache.parent.mkdir(parents=True)
            cache.write_text(json.dumps({"schedule": self._schedule()}), encoding="utf-8")
            fixture_client = _FixtureClient({"events": self._schedule()["events"] * 127})
            with self.assertRaisesRegex(AutomationError, "complete valid season"):
                load_fixture_schedule(config, now=self.now, fixture_client=fixture_client)
            self.assertEqual(len(fixture_client.calls), 1)


if __name__ == "__main__":
    unittest.main()
