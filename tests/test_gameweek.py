import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fantasy_advisor.gameweek import (
    LEAGUE_ID,
    load_gameweek_prepare_context,
    load_gameweek_recap_context,
)
from fantasy_advisor.sleeper import API_BASE, STATS_BASE


class _SleeperClient:
    def __init__(self, responses):
        self.responses = responses
        self.urls = []

    def get_json(self, url):
        self.urls.append(url)
        return self.responses[url]


class GameweekContextTests(unittest.TestCase):
    manager_id = "owner"

    def _responses(self):
        season = "2026"
        state_url = f"{API_BASE}/state/clubsoccer:epl"
        stats_url = f"{STATS_BASE}/clubsoccer:epl/{season}?season_type=regular"
        weekly_url = f"{STATS_BASE}/clubsoccer:epl/{season}/2?season_type=regular"
        player = {
            "player_id": "1",
            "player": {"first_name": "Ryan", "last_name": "Giles", "team_abbr": "HUL", "fantasy_positions": ["D"]},
            "stats": {"pts_std": 20, "gp": 2, "gs": 2, "min": 180, "g": 1, "a": 2},
        }
        weekly = {**player, "opponent": "100", "stats": {"pts_std": 11, "gp": 1, "gs": 1, "min": 90, "g": 1, "a": 1}}
        return {
            state_url: {"season": season, "display_week": 3},
            f"{API_BASE}/league/{LEAGUE_ID}": {"roster_positions": ["F", "D", "BN"], "scoring_settings": {"pos_d_g": 9}},
            f"{API_BASE}/league/{LEAGUE_ID}/rosters": [
                {"owner_id": "owner", "roster_id": 10, "players": ["1"], "starters": ["1"], "reserve": [], "metadata": {"record": "1-1"}, "settings": {"fpts": 20}},
                {"owner_id": "other", "roster_id": 11, "players": []},
            ],
            f"{API_BASE}/league/{LEAGUE_ID}/users": [
                {"user_id": "owner", "display_name": "owner", "metadata": {"team_name": "Los Blancos"}},
                {"user_id": "other", "display_name": "other", "metadata": {"team_name": "Rivals"}},
            ],
            stats_url: [player],
            weekly_url: [weekly],
        }

    def test_prepare_uses_current_roster_and_does_not_request_player_catalog(self):
        client = _SleeperClient(self._responses())
        context = load_gameweek_prepare_context(manager_id=self.manager_id, client=client, retrieved_at="now")
        payload = json.loads(context.as_json())
        self.assertEqual((context.report_kind, context.season, context.gameweek), ("prepare", "2026", 3))
        self.assertEqual(payload["your_team"]["players"][0]["name"], "Ryan Giles")
        self.assertEqual(payload["starting_slots"], ["F", "D"])
        self.assertFalse(payload["h2h_opponent"]["available"])
        self.assertFalse(any("players/clubsoccer" in url for url in client.urls))

    def test_recap_uses_last_completed_week_and_marks_fantasy_team(self):
        client = _SleeperClient(self._responses())
        context = load_gameweek_recap_context(manager_id=self.manager_id, client=client, retrieved_at="now")
        payload = json.loads(context.as_json())
        self.assertEqual((context.report_kind, context.gameweek), ("recap", 2))
        self.assertEqual(payload["your_team"]["players"][0]["stats"]["pts_std"], 11.0)
        self.assertEqual(payload["league_standouts_by_sleeper_points"][0]["fantasy_team"], "Los Blancos")
        self.assertIn(f"{STATS_BASE}/clubsoccer:epl/2026/2?season_type=regular", client.urls)


if __name__ == "__main__":
    unittest.main()
