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
                WatchlistStat(player, 22.5, 2.0, 2.0, 180.0, 2.0, 1.0, None, None, None, None, True),
                WatchlistStat(missing, None, None, None, None, None, None, None, None, None, None, False),
            ),
        )
        card = watchlist_stats_card(report)
        self.assertIn("Watchlist stats · 2 players", card)
        self.assertIn("Pts 22.5 · GP 2 · GS 2 · Min 180", card)
        self.assertIn("G 2 · A 1", card)
        self.assertIn("Former Player", card)
        self.assertIn("No current regular-season Sleeper stats returned.", card)


if __name__ == "__main__":
    unittest.main()
