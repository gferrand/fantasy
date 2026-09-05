import unittest

from fantasy_advisor.discord_presentation import (
    advisor_header,
    error_card,
    guardian_acknowledged,
    guardian_status,
    help_menu,
    scheduled_header,
    task_menu,
    web_briefing_header,
    watchlist_card,
    watchlist_change,
    watchlist_stats_card,
)
from fantasy_advisor.watchlist import WatchlistPlayer
from fantasy_advisor.watchlist_stats import WatchlistStat, WatchlistStatsReport


class _Task:
    id = "nightly_recap"
    name = "Los Blancos nightly game-day recap"


class DiscordPresentationTests(unittest.TestCase):
    def test_headers_hide_internal_thread_metadata(self):
        self.assertIn("🧠", advisor_header())
        self.assertIn("🌐", web_briefing_header())
        self.assertIn("📬", scheduled_header("Nightly recap", "Sep 1 · 10:00 PM EDT"))
        self.assertNotIn("Codex task", advisor_header())

    def test_task_and_help_menus_are_scannable(self):
        tasks = task_menu([_Task()])
        self.assertIn("📚", tasks)
        self.assertIn("/task nightly_recap", tasks)
        self.assertIn("🏟️", help_menu())
        self.assertIn("👀", help_menu())

    def test_watchlist_cards_use_compact_player_rows(self):
        player = WatchlistPlayer("1", "Bukayo Saka", "ARS", ("F", "M"), "2026-09-01T00:00:00+00:00")
        self.assertEqual(
            watchlist_card([player]),
            "👀 **Your watchlist · 1 players**\n\n• **Bukayo Saka** · ARS · F/M",
        )
        self.assertTrue(watchlist_change("added", player).startswith("✅"))

    def test_error_card_keeps_action_and_detail_separate(self):
        self.assertEqual(error_card("Couldn’t load report", "Try again."), "⚠️ **Couldn’t load report**\nTry again.")

    def test_guardian_cards_are_actionable(self):
        fixture = type("Fixture", (), {"home": "Brentford", "away": "Arsenal", "acknowledged_at": None})()
        self.assertIn("/guardian", guardian_acknowledged([fixture]))
        self.assertIn("awaiting", guardian_status([fixture]))

    def test_watchlist_stats_card_is_compact_and_marks_missing_rows(self):
        player = WatchlistPlayer("1", "Bukayo Saka", "ARS", ("F", "M"), "2026-09-01T00:00:00+00:00")
        missing = WatchlistPlayer("2", "Former Player", "", ("M",), "2026-09-01T00:00:00+00:00")
        report = WatchlistStatsReport(
            "2026", 3, "2026-09-03T02:10:00+00:00",
            (
                WatchlistStat(
                    player, 22.5, 2.0, 2.0, 180.0, 2.0, 1.0, None, None, None, None, True,
                    points_per_minute=0.125,
                    points_per_game=11.25,
                    minutes_per_game=90.0,
                    points_per_minute_trend="up",
                    points_per_game_trend="down",
                    minutes_per_game_trend="flat",
                ),
                WatchlistStat(missing, None, None, None, None, None, None, None, None, None, None, False),
            ),
            trend_weeks=((1, 2, 3), (4, 5, 6)),
        )
        card = watchlist_stats_card(report)
        self.assertIn("Watchlist stats · 2 players", card)
        self.assertIn("Pts 22.5 · GP 2 · GS 2 · Min 180", card)
        self.assertIn("Trend: GW4–6 vs GW1–3", card)
        self.assertIn("Pts/min 0.12 🟢⬆️", card)
        self.assertIn("Pts/game 11.2 🔴⬇️", card)
        self.assertIn("Min/game 90.0 ➖", card)
        self.assertIn("G 2 · A 1", card)
        self.assertIn("Former Player", card)
        self.assertIn("No current regular-season Sleeper stats returned.", card)

    def test_watchlist_stats_card_explains_unavailable_trends(self):
        player = WatchlistPlayer("1", "Bukayo Saka", "ARS", ("F",), "now")
        report = WatchlistStatsReport(
            "2026",
            3,
            "now",
            (
                WatchlistStat(
                    player, 4.0, 1.0, 0.0, 45.0, None, None, None, None, None, None, True,
                    points_per_minute=4 / 45,
                    points_per_game=4,
                    minutes_per_game=45,
                ),
            ),
            trend_unavailable_reason="Trend needs six completed gameweeks.",
        )

        card = watchlist_stats_card(report)

        self.assertIn("Trend needs six completed gameweeks.", card)
        self.assertIn("Pts/min 0.09 · Pts/game 4.0 · Min/game 45.0", card)
        self.assertNotIn("🟢", card)
        self.assertNotIn("🔴", card)

    def test_watchlist_stats_card_sorts_players_by_total_points_descending(self):
        low = WatchlistPlayer("1", "Low Scorer", "ARS", ("M",), "now")
        missing = WatchlistPlayer("2", "Missing Scorer", "CHE", ("F",), "now")
        high = WatchlistPlayer("3", "High Scorer", "LIV", ("F",), "now")
        tied = WatchlistPlayer("4", "Tied Scorer", "MCI", ("D",), "now")
        report = WatchlistStatsReport(
            "2026",
            3,
            "now",
            (
                WatchlistStat(low, 4.0, 1.0, 1.0, 90.0, None, None, None, None, None, None, True),
                WatchlistStat(missing, None, None, None, None, None, None, None, None, None, None, False),
                WatchlistStat(high, 12.0, 2.0, 2.0, 180.0, None, None, None, None, None, None, True),
                WatchlistStat(tied, 4.0, 2.0, 1.0, 100.0, None, None, None, None, None, None, True),
            ),
        )

        card = watchlist_stats_card(report)

        self.assertLess(card.index("High Scorer"), card.index("Low Scorer"))
        self.assertLess(card.index("Low Scorer"), card.index("Tied Scorer"))
        self.assertLess(card.index("Tied Scorer"), card.index("Missing Scorer"))

    def test_watchlist_stats_card_shows_previous_season_performance(self):
        up = WatchlistPlayer("1", "Up Player", "ARS", ("M",), "now")
        down = WatchlistPlayer("2", "Down Player", "CHE", ("F",), "now")
        flat = WatchlistPlayer("3", "Flat Player", "LIV", ("D",), "now")
        new = WatchlistPlayer("4", "New Player", "HUL", ("M",), "now")
        missing = WatchlistPlayer("5", "Missing Player", "CRY", ("F",), "now")
        report = WatchlistStatsReport(
            "2026",
            3,
            "now",
            (
                WatchlistStat(
                    up, 12.0, 1.0, 1.0, 90.0, None, None, None, None, None, None, True,
                    previous_season_points_per_minute=0.1,
                    points_per_minute_season_trend="up",
                ),
                WatchlistStat(
                    down, 5.0, 1.0, 1.0, 90.0, None, None, None, None, None, None, True,
                    previous_season_points_per_minute=0.1,
                    points_per_minute_season_trend="down",
                ),
                WatchlistStat(
                    flat, 9.0, 1.0, 1.0, 90.0, None, None, None, None, None, None, True,
                    previous_season_points_per_minute=0.1,
                    points_per_minute_season_trend="flat",
                ),
                WatchlistStat(new, 8.0, 1.0, 1.0, 90.0, None, None, None, None, None, None, True),
                WatchlistStat(
                    missing, None, None, None, None, None, None, None, None, None, None, False,
                    previous_season_points_per_minute=0.08,
                ),
            ),
            previous_season="2025",
        )

        card = watchlist_stats_card(report)

        self.assertIn("Last season (2025) Pts/min 0.10 · This season 🟢⬆️ overperforming", card)
        self.assertIn("Last season (2025) Pts/min 0.10 · This season 🔴⬇️ underperforming", card)
        self.assertIn("Last season (2025) Pts/min 0.10 · This season ➖ in line", card)
        self.assertIn("Last season (2025) Pts/min — · no EPL minutes", card)
        self.assertIn(
            "Last season (2025) Pts/min 0.08 · This season comparison unavailable",
            card,
        )

    def test_watchlist_stats_card_reports_previous_season_fetch_failure_once(self):
        player = WatchlistPlayer("1", "Player", "ARS", ("M",), "now")
        report = WatchlistStatsReport(
            "2026",
            3,
            "now",
            (WatchlistStat(player, 9.0, 1.0, 1.0, 90.0, None, None, None, None, None, None, True),),
            previous_season="2025",
            previous_season_unavailable_reason=(
                "Sleeper last-season Pts/min comparison is temporarily unavailable."
            ),
        )

        card = watchlist_stats_card(report)

        self.assertEqual(card.count("last-season Pts/min comparison is temporarily unavailable"), 1)
        self.assertNotIn("Last season (2025) Pts/min", card)

    def test_watchlist_stats_card_marks_player_specific_missing_history(self):
        player = WatchlistPlayer("1", "New Player", "ARS", ("F",), "now")
        report = WatchlistStatsReport(
            "2026",
            7,
            "now",
            (WatchlistStat(player, 8.0, 1.0, 1.0, 90.0, None, None, None, None, None, None, True),),
            trend_weeks=((1, 2, 3), (4, 5, 6)),
        )

        card = watchlist_stats_card(report)

        self.assertIn("Trend unavailable for Pts/min, Pts/game, Min/game", card)


if __name__ == "__main__":
    unittest.main()
