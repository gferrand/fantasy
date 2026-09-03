import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fantasy_advisor.automation import AppConfig, FANTASY_CODEX_MODEL, FANTASY_CODEX_REASONING_EFFORT
from fantasy_advisor.discord_bot import build_client


class DiscordBotTests(unittest.TestCase):
    def test_private_player_catalog_update_command_is_registered(self):
        config = AppConfig(
            repo_root=ROOT,
            task_registry_path=ROOT / "automation" / "tasks.toml",
            discord_bot_token=None,
            discord_allowed_user_id="123",
            discord_scheduled_channel_id=None,
            codex_bin="codex",
            codex_model=FANTASY_CODEX_MODEL,
            codex_reasoning_effort=FANTASY_CODEX_REASONING_EFFORT,
            codex_sandbox="read-only",
            codex_timeout_seconds=60,
            codex_ephemeral=False,
        )
        client = build_client(config)
        command_tree = client._fantasy_command_tree  # type: ignore[attr-defined]
        group = command_tree.get_command("player_catalog")
        self.assertIsNotNone(group)
        self.assertEqual([command.name for command in group.commands], ["update"])
        self.assertFalse(group.allowed_contexts.guild)
        self.assertTrue(group.allowed_contexts.dm_channel)


if __name__ == "__main__":
    unittest.main()
