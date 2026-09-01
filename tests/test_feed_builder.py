import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from build_sleeper_feed import build_feed


class FeedBuilderTests(unittest.TestCase):
    def test_core_feed_keeps_scoring_aware_pickup_shortlist(self):
        snapshot = {
            "retrieved_at": "2026-08-23T00:00:00+00:00",
            "round": 1,
            "league": {
                "name": "Kick & Run", "sport": "clubsoccer:epl", "season": "2026",
                "scoring_settings": {"pos_f_g": 9}, "roster_positions": [], "settings": {},
            },
            "state": {},
            "users": [{"user_id": "1", "display_name": "Manager", "metadata": {}}],
            "rosters": [{"roster_id": 1, "owner_id": "1", "players": ["owned"]}],
            "players": {
                "owned": {"player_id": "owned", "full_name": "Owned", "team_abbr": "ARS", "competitions": ["epl"], "active": True, "status": "A", "fantasy_positions": ["F"]},
                "free": {"player_id": "free", "full_name": "Available", "team_abbr": "ARS", "competitions": ["epl"], "active": True, "status": "A", "fantasy_positions": ["F"]},
            },
            "stats": [{"player_id": "free", "stats": {"pos_f_g": 1, "gp": 1, "gs": 1, "min": 90}, "player": {}}],
            "transactions": [],
        }
        feed = build_feed(snapshot)
        self.assertFalse(feed["available_players_complete"])
        self.assertEqual(feed["available_players_scope"], "bounded_current_season_shortlist")
        self.assertEqual(feed["available_players_count"], 1)
        self.assertEqual(feed["available_players"][0]["name"], "Available")
        self.assertEqual(feed["available_players"][0]["custom_points"], 9.0)


if __name__ == "__main__":
    unittest.main()
