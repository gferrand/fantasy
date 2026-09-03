import json
import unittest

from fantasy_advisor.sleeper import API_BASE, STATS_BASE
from fantasy_advisor.watchlist import WatchlistPlayer
from fantasy_advisor.watchlist_recommendations import (
    load_current_watchlist_recommendation_context,
    watchlist_outlook_context,
    watchlist_recommendation_context,
)


class _SleeperClient:
    def __init__(self, responses):
        self.responses = responses
        self.urls = []

    def get_json(self, url):
        self.urls.append(url)
        return self.responses[url]


class WatchlistRecommendationTests(unittest.TestCase):
    def test_current_context_uses_one_current_stats_snapshot_and_same_position_signals(self):
        state_url = f"{API_BASE}/state/clubsoccer:epl"
        stats_url = f"{STATS_BASE}/clubsoccer:epl/2026?season_type=regular"
        league_url = f"{API_BASE}/league/1378147559444348928"
        rosters_url = f"{API_BASE}/league/1378147559444348928/rosters"
        watched = WatchlistPlayer("watch", "Watched Defender", "ARS", ("D",), "now")
        client = _SleeperClient(
            {
                state_url: {"season": "2026", "display_week": 3},
                stats_url: [
                    {
                        "player_id": "watch",
                        "stats": {"gp": 2, "gs": 2, "min": 180, "pts_std": 20, "pos_d_min": 180},
                        "player": {"first_name": "Watched", "last_name": "Defender", "team_abbr": "ARS", "fantasy_positions": ["D"]},
                    },
                    {
                        "player_id": "rostered",
                        "stats": {"gp": 2, "gs": 1, "min": 90, "pts_std": 5, "pos_d_min": 90},
                        "player": {"first_name": "Current", "last_name": "Defender", "team_abbr": "CHE", "fantasy_positions": ["D"]},
                    },
                ],
                league_url: {"scoring_settings": {"pos_d_min": 0.1}},
                rosters_url: [{"owner_id": "owner", "players": ["rostered"]}],
            }
        )

        context = load_current_watchlist_recommendation_context(
            [watched], manager_id="owner", client=client, retrieved_at="2026-09-03T02:10:00+00:00"
        )

        self.assertEqual(client.urls, [state_url, stats_url, league_url, rosters_url])
        self.assertTrue(context.scoring_available)
        self.assertEqual(context.roster_players[0]["name"], "Current Defender")
        self.assertEqual(len(context.swap_signals), 1)
        self.assertEqual(context.swap_signals[0]["add"]["name"], "Watched Defender")
        self.assertEqual(context.swap_signals[0]["drop"]["name"], "Current Defender")
        outlook = json.loads(watchlist_outlook_context(context.stats_report))
        recommendation = json.loads(watchlist_recommendation_context(context))
        self.assertEqual(outlook["watched_players"][0]["name"], "Watched Defender")
        self.assertEqual(recommendation["your_current_roster"][0]["name"], "Current Defender")


if __name__ == "__main__":
    unittest.main()
