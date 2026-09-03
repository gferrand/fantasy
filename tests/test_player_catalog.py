import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fantasy_advisor.automation import (
    AppConfig,
    FANTASY_CODEX_MODEL,
    FANTASY_CODEX_REASONING_EFFORT,
    load_local_player_catalog,
    player_catalog_file,
    update_player_catalog,
)
from fantasy_advisor.player_catalog import (
    PlayerCatalogError,
    PlayerCatalogNotInitialized,
    load_player_catalog,
    refresh_player_catalog,
)


def test_config(root: Path) -> AppConfig:
    return AppConfig(
        repo_root=root,
        task_registry_path=root / "automation" / "tasks.toml",
        discord_bot_token=None,
        discord_allowed_user_id=None,
        discord_scheduled_channel_id=None,
        codex_bin="codex",
        codex_model=FANTASY_CODEX_MODEL,
        codex_reasoning_effort=FANTASY_CODEX_REASONING_EFFORT,
        codex_sandbox="read-only",
        codex_timeout_seconds=60,
        codex_ephemeral=False,
    )


SAMPLE_PLAYERS = {
    "14937": {
        "player_id": "14937",
        "full_name": "Ryan Giles",
        "team_abbr": "HUL",
        "fantasy_positions": ["D"],
        "competitions": ["epl"],
        "active": True,
        "status": "A",
        "ignored_stats": {"minutes": 175},
    },
    "2": {
        "player_id": "2",
        "full_name": "Former Player",
        "team_abbr": None,
        "fantasy_positions": [],
        "competitions": ["epl"],
        "active": False,
        "status": "INACTIVE",
    },
}


class PlayerCatalogTests(unittest.TestCase):
    def test_refresh_mirrors_identity_metadata_without_stats(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private" / "player_catalog.sqlite3"
            refreshed = refresh_player_catalog(path, SAMPLE_PLAYERS, refreshed_at="2026-09-02T14:00:00+00:00")
            players = load_player_catalog(path)
            self.assertEqual(refreshed.player_count, 2)
            self.assertEqual(refreshed.refreshed_at, "2026-09-02T14:00:00+00:00")
            self.assertEqual(players[1]["player_id"], "14937")
            self.assertEqual(players[1]["positions"], ["D"])
            self.assertNotIn("ignored_stats", players[1])
            with sqlite3.connect(path) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            self.assertEqual(tables, {"catalog_metadata", "catalog_players"})

    def test_failed_validation_keeps_the_last_successful_catalog(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "player_catalog.sqlite3"
            refresh_player_catalog(path, SAMPLE_PLAYERS)
            with self.assertRaisesRegex(PlayerCatalogError, "without an ID or name"):
                refresh_player_catalog(path, {"bad": {"player_id": "", "full_name": ""}})
            self.assertEqual(len(load_player_catalog(path)), 2)

    def test_uninitialized_catalog_has_an_actionable_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(PlayerCatalogNotInitialized, "/player_catalog update"):
                load_player_catalog(Path(temporary) / "player_catalog.sqlite3")

    def test_automation_update_fetches_once_and_local_reads_do_not_use_the_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = test_config(Path(temporary))
            with patch("fantasy_advisor.automation.SleeperClient.get_json", return_value=SAMPLE_PLAYERS) as fetch:
                result = update_player_catalog(config)
            self.assertEqual(result.player_count, 2)
            self.assertEqual(fetch.call_count, 1)
            self.assertIn("/players/clubsoccer:epl", fetch.call_args.args[0])
            with patch("fantasy_advisor.automation.urlopen", side_effect=AssertionError("network lookup")):
                players = load_local_player_catalog(config)
            self.assertEqual({player["player_id"] for player in players}, {"14937", "2"})
            self.assertTrue(player_catalog_file(config).exists())


if __name__ == "__main__":
    unittest.main()
