import json
from pathlib import Path
import sys
import unittest
from datetime import datetime, timezone


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fantasy_advisor.gameweek import (
    LEAGUE_ID,
    _assigned_lineup_position,
    _forecast_xi_display,
    _formation_display,
    _ordered_forecast_xi_assignments,
    _ordered_forecast_xi_ids,
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
        self.assertEqual(payload["your_team"]["players"][0]["sleeper_lineup_state"], "starter")
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

    def test_prepare_forecasts_custom_score_and_out_or_gtd_availability(self):
        responses = self._responses()
        league_url = f"{API_BASE}/league/{LEAGUE_ID}"
        responses[league_url] = {"roster_positions": ["D", "F", "BN"], "scoring_settings": {"pos_d_g": 9, "pos_f_g": 4}}
        stats_url = f"{STATS_BASE}/clubsoccer:epl/2026?season_type=regular"
        responses[stats_url] = [
            {"player_id": "1", "player": {"full_name": "Defender", "team_abbr": "HUL", "fantasy_positions": ["D"]}, "stats": {"gp": 2, "min": 180, "pos_d_g": 2}},
            {"player_id": "2", "player": {"full_name": "Forward", "team_abbr": "LEE", "fantasy_positions": ["F"], "injury_status": "GTD"}, "stats": {"gp": 2, "min": 180, "pos_f_g": 2}},
            {"player_id": "3", "player": {"full_name": "Out Player", "team_abbr": "HUL", "fantasy_positions": ["F"], "injury_status": "OUT"}, "stats": {"gp": 2, "min": 180, "pos_f_g": 20}},
        ]
        responses[f"{API_BASE}/league/{LEAGUE_ID}/rosters"][0]["players"] = ["1", "2", "3"]
        schedule = {"events": [{"date": "2026-09-20T15:00:00Z", "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"displayName": "Hull City"}},
            {"homeAway": "away", "team": {"displayName": "Leeds United"}},
        ]}]}]}
        context = load_gameweek_prepare_context(
            manager_id=self.manager_id, client=_SleeperClient(responses), fixture_schedule=schedule,
            now=datetime(2026, 9, 11, tzinfo=timezone.utc),
        )
        forecast = context.payload["forecast"]
        by_name = {player["name"]: player for player in context.payload["your_team"]["players"]}
        self.assertTrue(forecast["available"])
        self.assertGreater(by_name["Defender"]["forecast"]["points"], 0)
        self.assertGreater(by_name["Forward"]["forecast"]["points"], 0)
        self.assertGreater(by_name["Out Player"]["forecast"]["points"], 0)
        self.assertTrue(by_name["Out Player"]["forecast"]["display"].endswith("OUT"))
        self.assertIn("Projected XI:", forecast["total_display"])
        self.assertEqual(len(forecast["projected_xi_player_ids"]), 2)
        by_id = {player["player_id"]: player for player in context.payload["your_team"]["players"]}
        self.assertEqual(forecast["projected_xi_total"], round(sum(
            by_id[player_id]["forecast"]["selection_points"] for player_id in forecast["projected_xi_player_ids"]
        ), 1))
        self.assertGreaterEqual(forecast["projected_xi_if_active_total"], forecast["projected_xi_total"])
        self.assertEqual(forecast["projected_xi_lines"][0], "**Formation: 1D / 0M / 1F**")
        self.assertEqual(forecast["projected_xi_lines"][1].split(" — ", 1)[0], "**D")
        self.assertEqual(forecast["projected_xi_lines"][2].split(" — ", 1)[0], "**F")
        self.assertNotIn("3", forecast["projected_xi_player_ids"])

    def test_prepare_degrades_when_fixture_calendar_is_missing(self):
        context = load_gameweek_prepare_context(manager_id=self.manager_id, client=_SleeperClient(self._responses()))
        self.assertFalse(context.payload["forecast"]["available"])
        self.assertIn("Forecast unavailable", context.payload["forecast"]["note"])

    def test_prepare_degrades_when_custom_scoring_or_player_stats_are_missing(self):
        responses = self._responses()
        responses[f"{API_BASE}/league/{LEAGUE_ID}"]["scoring_settings"] = {}
        context = load_gameweek_prepare_context(manager_id=self.manager_id, client=_SleeperClient(responses), fixture_schedule={"events": []})
        self.assertFalse(context.payload["forecast"]["available"])
        self.assertIn("scoring or player season data", context.payload["forecast"]["note"])

    def test_forecast_xi_display_order_runs_goalkeeper_to_forwards(self):
        players = {
            "forward": {"name": "Forward", "positions": ["F"]},
            "midfielder": {"name": "Midfielder", "positions": ["M"]},
            "defender": {"name": "Defender", "positions": ["D"]},
            "keeper": {"name": "Keeper", "positions": ["GK"]},
        }
        self.assertEqual(
            _ordered_forecast_xi_ids(("forward", "midfielder", "defender", "keeper"), players),
            ["keeper", "defender", "midfielder", "forward"],
        )

    def test_forecast_xi_display_uses_assigned_lineup_position(self):
        self.assertEqual(
            _forecast_xi_display(
                "FMD_FLEX", "Granit Xhaka", "M", ["M"],
                "**Granit Xhaka** · est. 7.9 Kick & Run pts",
            ),
            "**M — Granit Xhaka** · est. 7.9 Kick & Run pts",
        )

    def test_forecast_formation_uses_assigned_slots_not_primary_scoring_tags(self):
        players = {
            "khusanov": {"name": "Khusanov", "position": "D", "positions": ["D"]},
            "van_de_ven": {"name": "van de Ven", "position": "D", "positions": ["D"]},
            "calafiori": {"name": "Calafiori", "position": "D", "positions": ["D"]},
            "ajayi": {"name": "Ajayi", "position": "D", "positions": ["D"]},
            "xhaka": {"name": "Xhaka", "position": "M", "positions": ["M"]},
            "gakpo": {"name": "Gakpo", "position": "F", "positions": ["F", "M"]},
            "barnes": {"name": "Barnes", "position": "M", "positions": ["M"]},
            "schade": {"name": "Schade", "position": "M", "positions": ["F", "M"]},
            "wissa": {"name": "Wissa", "position": "F", "positions": ["F"]},
            "semenyo": {"name": "Semenyo", "position": "F", "positions": ["F"]},
        }
        assignments = (
            ("khusanov", "MD_FLEX"), ("van_de_ven", "D"), ("calafiori", "D"), ("ajayi", "D"),
            ("xhaka", "FMD_FLEX"), ("gakpo", "M"), ("barnes", "M"), ("schade", "M"),
            ("wissa", "FM_FLEX"), ("semenyo", "F"),
        )
        ordered = _ordered_forecast_xi_assignments(assignments, players)
        assigned_positions = [
            _assigned_lineup_position(slot, players[player_id]["position"], players[player_id]["positions"])
            for player_id, slot in ordered
        ]
        self.assertEqual(_formation_display(assigned_positions), "**Formation: 4D / 4M / 2F**")
        self.assertEqual(assigned_positions, ["D", "D", "D", "D", "M", "M", "M", "M", "F", "F"])


if __name__ == "__main__":
    unittest.main()
