import unittest

from fantasy_advisor.sleeper import API_BASE, STATS_BASE, SleeperDataError
from fantasy_advisor.watchlist import WatchlistPlayer
from fantasy_advisor.watchlist_stats import load_current_watchlist_stats


class _SleeperClient:
    def __init__(self, responses):
        self.responses = responses
        self.urls = []

    def get_json(self, url):
        self.urls.append(url)
        return self.responses[url]


class WatchlistStatsTests(unittest.TestCase):
    def test_current_stats_use_saved_ids_and_one_stats_snapshot(self):
        state_url = f"{API_BASE}/state/clubsoccer:epl"
        stats_url = f"{STATS_BASE}/clubsoccer:epl/2026?season_type=regular"
        client = _SleeperClient(
            {
                state_url: {"season": "2026", "display_week": 3},
                stats_url: [
                    {
                        "player_id": "14937",
                        "stats": {"pts_std": 25.25, "gp": 2, "gs": 2, "min": 175, "cs": 2},
                        "player": {"injury_status": "GTD"},
                        "updated_at": 1788391786164,
                    }
                ],
            }
        )
        watched = (
            WatchlistPlayer("14937", "Ryan Giles", "HUL", ("D",), "2026-09-01T00:00:00+00:00"),
            WatchlistPlayer("missing", "Former Player", "", ("M",), "2026-09-01T00:00:00+00:00"),
        )

        report = load_current_watchlist_stats(watched, client=client, retrieved_at="2026-09-03T02:10:00+00:00")

        self.assertEqual(client.urls, [state_url, stats_url])
        self.assertEqual((report.season, report.week), ("2026", 3))
        self.assertEqual(report.entries[0].player.player_id, "14937")
        self.assertEqual(report.entries[0].points, 25.25)
        self.assertEqual(report.entries[0].clean_sheets, 2.0)
        self.assertEqual(report.entries[0].injury_status, "GTD")
        self.assertTrue(report.entries[0].found)
        self.assertFalse(report.entries[1].found)

    def test_malformed_current_stats_fail_clearly(self):
        state_url = f"{API_BASE}/state/clubsoccer:epl"
        stats_url = f"{STATS_BASE}/clubsoccer:epl/2026?season_type=regular"
        client = _SleeperClient({state_url: {"season": "2026"}, stats_url: {}})
        watched = (WatchlistPlayer("1", "Player", "ARS", ("M",), "now"),)

        with self.assertRaisesRegex(SleeperDataError, "did not return an array"):
            load_current_watchlist_stats(watched, client=client)


if __name__ == "__main__":
    unittest.main()
