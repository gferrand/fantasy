import unittest

from fantasy_advisor.discord_presentation import (
    advisor_header,
    error_card,
    help_menu,
    scheduled_header,
    task_menu,
    watchlist_card,
    watchlist_change,
)
from fantasy_advisor.watchlist import WatchlistPlayer


class _Task:
    id = "nightly_recap"
    name = "Los Blancos nightly game-day recap"


class DiscordPresentationTests(unittest.TestCase):
    def test_headers_hide_internal_thread_metadata(self):
        self.assertIn("🧠", advisor_header())
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


if __name__ == "__main__":
    unittest.main()
