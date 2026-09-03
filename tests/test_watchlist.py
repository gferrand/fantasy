import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from fantasy_advisor.watchlist import (
    WatchlistResolutionError,
    add_watchlist_player,
    list_watchlist,
    parse_watchlist_intent,
    remove_watchlist_player,
    resolve_saved_watchlist_player,
    resolve_watchlist_player,
)


class WatchlistTests(unittest.TestCase):
    def test_plain_english_watchlist_intents_are_explicit_and_safe(self):
        self.assertEqual(parse_watchlist_intent("Add Rayan Ait-Nouri to my watchlist"), ("add", "Rayan Ait-Nouri"))
        self.assertEqual(parse_watchlist_intent("Add Matt O’Riley to my wachlist"), ("add", "Matt O’Riley"))
        self.assertEqual(parse_watchlist_intent("Please remove Rayan Ait-Nouri from my watchlist."), ("remove", "Rayan Ait-Nouri"))
        self.assertEqual(parse_watchlist_intent("What's on my watchlist?"), ("list", None))
        self.assertEqual(parse_watchlist_intent("Show me my watchlist all players on it"), ("list", None))
        self.assertEqual(parse_watchlist_intent("Show all players on my watchlist"), ("list", None))
        self.assertEqual(parse_watchlist_intent("Keep an eye on João Pedro for my watchlist"), ("add", "João Pedro"))
        self.assertEqual(
            parse_watchlist_intent("I’m holding Van de Ven. Add Ryan Giles to my watchlist."),
            ("add", "Ryan Giles"),
        )
        self.assertIsNone(parse_watchlist_intent("Should I add Rayan Ait-Nouri to my watchlist?"))

    def test_add_list_remove_and_duplicate_add_are_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private" / "watchlist.sqlite3"
            player = {"player_id": "1", "name": "Rayan Aït-Nouri", "club": "MCI", "positions": ["D"]}
            saved, added = add_watchlist_player(path, player)
            duplicate, duplicate_added = add_watchlist_player(path, player)
            self.assertTrue(added)
            self.assertFalse(duplicate_added)
            self.assertEqual(saved, duplicate)
            self.assertEqual([item.name for item in list_watchlist(path)], ["Rayan Aït-Nouri"])
            self.assertEqual(remove_watchlist_player(path, "1").name, "Rayan Aït-Nouri")
            self.assertEqual(list_watchlist(path), [])

    def test_name_resolution_handles_accents_and_ambiguous_clubs(self):
        players = [
            {"player_id": "1", "name": "Rayan Aït-Nouri", "club": "MCI", "positions": ["D"]},
            {"player_id": "4", "name": "Matt O'Riley", "club": "BHA", "positions": ["M"]},
            {"player_id": "2", "name": "João Pedro", "club": "CHE", "positions": ["F"]},
            {"player_id": "3", "name": "João Pedro", "club": "BHA", "positions": ["F"]},
        ]
        self.assertEqual(resolve_watchlist_player("Rayan Ait-Nouri", players)["player_id"], "1")
        self.assertEqual(resolve_watchlist_player("Matt O’Riley", players)["player_id"], "4")
        with self.assertRaisesRegex(WatchlistResolutionError, "CHE"):
            resolve_watchlist_player("Joao Pedro", players)

    def test_saved_player_can_be_removed_after_leaving_current_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "watchlist.sqlite3"
            add_watchlist_player(path, {"player_id": "9", "name": "Transferred Player", "club": "ARS", "positions": ["M"]})
            watched = list_watchlist(path)
            resolved = resolve_saved_watchlist_player("Transferred Player", watched)
            self.assertEqual(resolved.player_id, "9")
            self.assertEqual(remove_watchlist_player(path, resolved.player_id).club, "ARS")

    def test_player_without_a_current_club_can_be_watched_and_resolved(self):
        players = [{"player_id": "7", "name": "Former Player", "club": "", "positions": []}]
        self.assertEqual(resolve_watchlist_player("Former Player", players)["player_id"], "7")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "watchlist.sqlite3"
            saved, added = add_watchlist_player(path, players[0])
            self.assertTrue(added)
            self.assertEqual(saved.club, "")


if __name__ == "__main__":
    unittest.main()
