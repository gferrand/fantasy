import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fantasy_advisor.automation import (
    AppConfig,
    FANTASY_CODEX_MODEL,
    FANTASY_CODEX_REASONING_EFFORT,
    run_trade_web_briefing,
    trade_web_briefing_prompt,
)
from fantasy_advisor.gameweek import LEAGUE_ID
from fantasy_advisor.sleeper import API_BASE, STATS_BASE, SleeperDataError
from fantasy_advisor.trade_proposals import evaluate_lineup, load_trade_proposal_context


class _SleeperClient:
    def __init__(self, responses):
        self.responses = responses
        self.urls = []

    def get_json(self, url):
        self.urls.append(url)
        return self.responses[url]


def _stat_player(player_id, name, position, points, *, club="ARS", minutes=360):
    first, last = name.split(" ", 1)
    return {
        "player_id": str(player_id),
        "player": {
            "first_name": first,
            "last_name": last,
            "team_abbr": club,
            "fantasy_positions": [position],
        },
        "stats": {
            f"pos_{position.casefold()}_points": points,
            "gp": 4,
            "gs": 4,
            "min": minutes,
        },
    }


class TradeProposalTests(unittest.TestCase):
    manager_id = "owner"

    def _responses(self, *, scoring=True):
        season = "2026"
        stats_url = f"{STATS_BASE}/clubsoccer:epl/{season}?season_type=regular"
        players = [
            _stat_player("1", "Owner Forward", "F", 30),
            _stat_player("2", "Owner Mid", "M", 66, minutes=540),
            _stat_player("3", "Owner Backup", "M", 50),
            _stat_player("4", "Owner Defender", "D", 50),
            _stat_player("5", "Target Forward", "F", 60, club="CHE", minutes=180),
            _stat_player("6", "Rival Mid", "M", 10, club="CHE"),
            _stat_player("7", "Rival Defender", "D", 50, club="CHE"),
            _stat_player("8", "Rival Backup", "F", 20, club="CHE"),
            _stat_player("9", "Erling Haaland", "F", 500, club="MCI"),
            _stat_player("10", "Other Mid", "M", 5, club="MCI"),
            _stat_player("11", "Other Defender", "D", 5, club="MCI"),
            _stat_player("12", "Other Backup", "F", 5, club="MCI"),
        ]
        return {
            f"{API_BASE}/state/clubsoccer:epl": {"season": season, "display_week": 4},
            f"{API_BASE}/league/{LEAGUE_ID}": {
                "roster_positions": ["F", "M", "D", "BN", "BN"],
                "scoring_settings": (
                    {"pos_f_points": 1, "pos_m_points": 1, "pos_d_points": 1} if scoring else {}
                ),
                "settings": {"waiver_budget": 100},
            },
            f"{API_BASE}/league/{LEAGUE_ID}/rosters": [
                {"owner_id": "owner", "roster_id": 1, "players": ["1", "2", "3", "4"], "settings": {"waiver_budget_used": 8}},
                {"owner_id": "rival", "roster_id": 2, "players": ["5", "6", "7", "8"], "settings": {"waiver_budget_used": 0}},
                {"owner_id": "other", "roster_id": 3, "players": ["9", "10", "11", "12"], "settings": {"waiver_budget_used": 0}},
            ],
            f"{API_BASE}/league/{LEAGUE_ID}/users": [
                {"user_id": "owner", "display_name": "Owner", "metadata": {"team_name": "Los Blancos"}},
                {"user_id": "rival", "display_name": "Rival", "metadata": {"team_name": "Fair Rivals"}},
                {"user_id": "other", "display_name": "Other", "metadata": {"team_name": "Big Prices"}},
            ],
            stats_url: players,
        }

    @staticmethod
    def _event(event_id, date, home, away, *, home_score=None, away_score=None, completed=False):
        def competitor(name, side, score):
            item = {"homeAway": side, "team": {"displayName": name}}
            if score is not None:
                item["score"] = str(score)
            return item

        return {
            "id": str(event_id),
            "date": date,
            "competitions": [
                {
                    "status": {"type": {"completed": completed}},
                    "competitors": [
                        competitor(home, "home", home_score),
                        competitor(away, "away", away_score),
                    ],
                }
            ],
        }

    def _schedule(self):
        return {
            "events": [
                self._event("1", "2026-08-20T19:00:00Z", "Manchester City", "Coventry City", home_score=3, away_score=0, completed=True),
                self._event("2", "2026-08-21T19:00:00Z", "Chelsea", "Arsenal", home_score=1, away_score=1, completed=True),
                self._event("3", "2026-09-05T19:00:00Z", "Manchester City", "Arsenal"),
                self._event("4", "2026-09-05T19:00:00Z", "Chelsea", "Coventry City"),
            ]
        }

    def _context(self):
        client = _SleeperClient(self._responses())
        context = load_trade_proposal_context(
            manager_id=self.manager_id,
            client=client,
            fixture_schedule=self._schedule(),
            now=datetime(2026, 9, 1, tzinfo=timezone.utc),
            retrieved_at="now",
        )
        return context, client

    def test_loads_only_read_only_live_roster_scoring_data_and_finds_mutual_package(self):
        context, client = self._context()
        payload = json.loads(context.as_json())
        self.assertEqual((context.season, context.gameweek), ("2026", 4))
        self.assertEqual(payload["your_team"]["remaining_faab"], 92)
        self.assertTrue(payload["candidate_packages"])
        option = next(
            item
            for item in payload["candidate_packages"]
            if [player["player_id"] for player in item["you_receive"]] == ["5"]
        )
        self.assertEqual([player["player_id"] for player in option["you_send"]], ["2"])
        self.assertEqual(option["math"]["your_lineup_gain"], 14.0)
        self.assertEqual(option["math"]["partner_lineup_gain"], 16.0)
        self.assertEqual(option["math"]["player_equity_ratio"], 1.1)
        self.assertFalse(option["math"]["faab_included_in_point_math"])
        self.assertGreater(option["math"]["your_projected_lineup_gain"], 0)
        sent = option["you_send"][0]
        received = option["you_receive"][0]
        self.assertGreater(sent["forecast_fixture_difficulty"], received["forecast_fixture_difficulty"])
        self.assertLess(sent["forecast_fixture_adjustment"], received["forecast_fixture_adjustment"])
        self.assertNotIn("players/clubsoccer:epl", "\n".join(client.urls))
        self.assertEqual(len(client.urls), 5)

    def test_every_selected_package_is_bounded_fair_and_neutral_or_better_for_partner(self):
        context, _client = self._context()
        for option in context.payload["candidate_packages"]:
            self.assertLessEqual(len(option["you_send"]) + len(option["you_receive"]), 3)
            self.assertGreater(option["math"]["your_lineup_gain"], 0)
            self.assertGreater(option["math"]["partner_lineup_gain"], 0)
            self.assertGreaterEqual(option["math"]["player_equity_ratio"], 0.8)
            self.assertLessEqual(option["math"]["player_equity_ratio"], 1.15)
            band = option["acceptance_plausibility"]
            self.assertGreaterEqual(band["low"], 30)
            self.assertLessEqual(band["high"], 50)
            self.assertIn("Heuristic only", band["method"])

    def test_rejects_an_obviously_unaffordable_star_target(self):
        context, _client = self._context()
        received_names = {
            player["name"]
            for option in context.payload["candidate_packages"]
            for player in option["you_receive"]
        }
        self.assertNotIn("Erling Haaland", received_names)

    def test_requires_current_custom_scoring(self):
        with self.assertRaisesRegex(SleeperDataError, "custom scoring"):
            load_trade_proposal_context(
                manager_id=self.manager_id,
                client=_SleeperClient(self._responses(scoring=False)),
                fixture_schedule=self._schedule(),
            )

    def test_requires_local_fixture_schedule_for_prediction_based_trade_math(self):
        with self.assertRaisesRegex(SleeperDataError, "fixture schedule"):
            load_trade_proposal_context(manager_id=self.manager_id, client=_SleeperClient(self._responses()))

    def test_lineup_optimizer_handles_multi_position_flex_slots_without_reusing_players(self):
        lineup = evaluate_lineup(
            [
                {
                    "player_id": "f",
                    "positions": ["F", "M"],
                    "position_points": {"F": 60, "M": 25},
                    "current_custom_points": 60,
                },
                {"player_id": "m", "positions": ["M"], "position_points": {"M": 10}, "current_custom_points": 10},
            ],
            ["F", "M"],
        )
        self.assertEqual(lineup.score, 70.0)
        self.assertCountEqual(lineup.player_ids, ["f", "m"])

    def test_trade_web_prompt_and_runner_only_receive_candidate_context(self):
        context, _client = self._context()
        prompt = trade_web_briefing_prompt(live_context=context.as_json())
        self.assertIn("Target Forward", prompt)
        self.assertIn("Never make, simulate, submit", prompt)
        self.assertIn("heuristic, not a prediction", prompt)
        self.assertIn("Negotiation kit", prompt)
        self.assertIn("Never invent a stat", prompt)
        self.assertIn("No Sleeper trade was created or simulated", prompt)

        class FakeResponses:
            def __init__(self):
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return type("Response", (), {"output_text": "🤝 **Trade proposal**", "id": "resp-trade"})()

        fake_responses = FakeResponses()
        fake_client = type("Client", (), {"responses": fake_responses})()
        config = AppConfig(
            repo_root=ROOT,
            task_registry_path=ROOT / "automation" / "tasks.toml",
            discord_bot_token=None,
            discord_allowed_user_id=None,
            discord_scheduled_channel_id=None,
            codex_bin="codex",
            codex_model=FANTASY_CODEX_MODEL,
            codex_reasoning_effort=FANTASY_CODEX_REASONING_EFFORT,
            codex_sandbox="read-only",
            codex_timeout_seconds=60,
            codex_ephemeral=False,
            openai_api_key="test-key",
        )
        with patch("openai.OpenAI", return_value=fake_client) as openai_client:
            result = run_trade_web_briefing(config, live_context=context.as_json())
        self.assertEqual(result.response_id, "resp-trade")
        openai_client.assert_called_once_with(api_key="test-key", timeout=config.codex_interactive_timeout_seconds)
        call = fake_responses.calls[0]
        self.assertFalse(call["store"])
        self.assertEqual(call["tools"], [{"type": "web_search_preview", "search_context_size": "medium"}])


if __name__ == "__main__":
    unittest.main()
