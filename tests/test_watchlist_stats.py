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
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


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
        self.assertAlmostEqual(report.entries[0].points_per_minute, 25.25 / 175)
        self.assertEqual(report.entries[0].points_per_game, 12.625)
        self.assertEqual(report.entries[0].minutes_per_game, 87.5)
        self.assertTrue(report.entries[0].found)
        self.assertFalse(report.entries[1].found)

    def test_trends_compare_latest_three_completed_weeks_with_prior_three(self):
        state_url = f"{API_BASE}/state/clubsoccer:epl"
        stats_url = f"{STATS_BASE}/clubsoccer:epl/2026?season_type=regular"
        responses = {
            state_url: {"season": "2026", "display_week": 7},
            stats_url: [
                {"player_id": "1", "stats": {"pts_std": 42, "gp": 6, "min": 450}},
                {"player_id": "2", "stats": {"pts_std": 30.1, "gp": 6, "min": 540}},
            ],
        }
        for week in range(1, 4):
            responses[f"{STATS_BASE}/clubsoccer:epl/2026/{week}?season_type=regular"] = [
                {"player_id": "1", "stats": {"pts_std": 5, "gp": 1, "min": 90}},
                {"player_id": "2", "stats": {"pts_std": 5, "gp": 1, "min": 90}},
            ]
        responses[f"{STATS_BASE}/clubsoccer:epl/2026/4?season_type=regular"] = [
            {"player_id": "1", "stats": {"pts_std": 18, "gp": 2, "min": 120}},
            {"player_id": "2", "stats": {"pts_std": 5.1, "gp": 1, "min": 90}},
        ]
        responses[f"{STATS_BASE}/clubsoccer:epl/2026/5?season_type=regular"] = [
            {"player_id": "1", "stats": {"pts_std": 9, "gp": 1, "min": 60}},
            {"player_id": "2", "stats": {"pts_std": 5, "gp": 1, "min": 90}},
        ]
        responses[f"{STATS_BASE}/clubsoccer:epl/2026/6?season_type=regular"] = [
            {"player_id": "2", "stats": {"pts_std": 5, "gp": 1, "min": 90}},
        ]
        client = _SleeperClient(responses)
        watched = (
            WatchlistPlayer("1", "Rising Player", "ARS", ("F",), "now"),
            WatchlistPlayer("2", "Steady Player", "CHE", ("M",), "now"),
        )

        report = load_current_watchlist_stats(watched, client=client, include_trends=True)

        self.assertEqual(report.trend_weeks, ((1, 2, 3), (4, 5, 6)))
        self.assertIsNone(report.trend_unavailable_reason)
        rising, steady = report.entries
        self.assertEqual(rising.points_per_minute_trend, "up")
        self.assertEqual(rising.points_per_game_trend, "up")
        self.assertEqual(rising.minutes_per_game_trend, "down")
        self.assertEqual(steady.points_per_minute_trend, "flat")
        self.assertEqual(steady.points_per_game_trend, "flat")
        self.assertEqual(steady.minutes_per_game_trend, "flat")
        self.assertEqual(
            client.urls,
            [state_url, stats_url]
            + [f"{STATS_BASE}/clubsoccer:epl/2026/{week}?season_type=regular" for week in range(1, 7)],
        )

    def test_early_season_does_not_fetch_incomplete_trend_window(self):
        state_url = f"{API_BASE}/state/clubsoccer:epl"
        stats_url = f"{STATS_BASE}/clubsoccer:epl/2026?season_type=regular"
        client = _SleeperClient(
            {
                state_url: {"season": "2026", "display_week": 3},
                stats_url: [{"player_id": "1", "stats": {"pts_std": 4, "gp": 1, "min": 45}}],
            }
        )

        report = load_current_watchlist_stats(
            (WatchlistPlayer("1", "Player", "ARS", ("M",), "now"),),
            client=client,
            include_trends=True,
        )

        self.assertEqual(client.urls, [state_url, stats_url])
        self.assertIsNone(report.trend_weeks)
        self.assertEqual(report.trend_unavailable_reason, "Trend needs six completed gameweeks.")
        self.assertIsNone(report.entries[0].points_per_game_trend)

    def test_weekly_history_failure_preserves_current_averages(self):
        state_url = f"{API_BASE}/state/clubsoccer:epl"
        stats_url = f"{STATS_BASE}/clubsoccer:epl/2026?season_type=regular"
        week_url = f"{STATS_BASE}/clubsoccer:epl/2026/1?season_type=regular"
        client = _SleeperClient(
            {
                state_url: {"season": "2026", "display_week": 7},
                stats_url: [{"player_id": "1", "stats": {"pts_std": 18, "gp": 2, "min": 180}}],
                week_url: SleeperDataError("unavailable"),
            }
        )

        report = load_current_watchlist_stats(
            (WatchlistPlayer("1", "Player", "ARS", ("M",), "now"),),
            client=client,
            include_trends=True,
        )

        self.assertEqual(report.entries[0].points_per_game, 9)
        self.assertIsNone(report.trend_weeks)
        self.assertIn("temporarily unavailable", report.trend_unavailable_reason)

    def test_malformed_weekly_history_preserves_current_averages(self):
        state_url = f"{API_BASE}/state/clubsoccer:epl"
        stats_url = f"{STATS_BASE}/clubsoccer:epl/2026?season_type=regular"
        week_url = f"{STATS_BASE}/clubsoccer:epl/2026/1?season_type=regular"
        client = _SleeperClient(
            {
                state_url: {"season": "2026", "display_week": 7},
                stats_url: [{"player_id": "1", "stats": {"pts_std": 18, "gp": 2, "min": 180}}],
                week_url: {},
            }
        )

        report = load_current_watchlist_stats(
            (WatchlistPlayer("1", "Player", "ARS", ("M",), "now"),),
            client=client,
            include_trends=True,
        )

        self.assertEqual(client.urls, [state_url, stats_url, week_url])
        self.assertEqual(report.entries[0].minutes_per_game, 90)
        self.assertIn("temporarily unavailable", report.trend_unavailable_reason)

    def test_zero_denominators_and_players_without_window_appearances_are_unavailable(self):
        state_url = f"{API_BASE}/state/clubsoccer:epl"
        stats_url = f"{STATS_BASE}/clubsoccer:epl/2026?season_type=regular"
        responses = {
            state_url: {"season": "2026", "display_week": 7},
            stats_url: [
                {"player_id": "1", "stats": {"pts_std": 0, "gp": 0, "min": 0}},
                {"player_id": "2", "stats": {"pts_std": 8, "gp": 1, "min": 90}},
            ],
        }
        for week in range(1, 7):
            responses[f"{STATS_BASE}/clubsoccer:epl/2026/{week}?season_type=regular"] = []
        client = _SleeperClient(responses)

        report = load_current_watchlist_stats(
            (
                WatchlistPlayer("1", "Unused Player", "ARS", ("M",), "now"),
                WatchlistPlayer("2", "New Player", "CHE", ("F",), "now"),
            ),
            client=client,
            include_trends=True,
        )

        unused, new = report.entries
        self.assertIsNone(unused.points_per_minute)
        self.assertIsNone(unused.points_per_game)
        self.assertIsNone(unused.minutes_per_game)
        self.assertIsNone(new.points_per_minute_trend)
        self.assertIsNone(new.points_per_game_trend)
        self.assertIsNone(new.minutes_per_game_trend)

    def test_malformed_current_stats_fail_clearly(self):
        state_url = f"{API_BASE}/state/clubsoccer:epl"
        stats_url = f"{STATS_BASE}/clubsoccer:epl/2026?season_type=regular"
        client = _SleeperClient({state_url: {"season": "2026"}, stats_url: {}})
        watched = (WatchlistPlayer("1", "Player", "ARS", ("M",), "now"),)

        with self.assertRaisesRegex(SleeperDataError, "did not return an array"):
            load_current_watchlist_stats(watched, client=client)


if __name__ == "__main__":
    unittest.main()
