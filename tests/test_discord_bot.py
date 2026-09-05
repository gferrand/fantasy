import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fantasy_advisor.automation import AppConfig, FANTASY_CODEX_MODEL, FANTASY_CODEX_REASONING_EFFORT
from fantasy_advisor.discord_bot import build_client


def _test_config():
    return AppConfig(
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


class DiscordBotTests(unittest.TestCase):
    def assert_private_group(self, name, command_names):
        client = build_client(_test_config())
        group = client._fantasy_command_tree.get_command(name)  # type: ignore[attr-defined]
        self.assertIsNotNone(group)
        self.assertEqual([command.name for command in group.commands], command_names)
        self.assertFalse(group.allowed_contexts.guild)
        self.assertTrue(group.allowed_contexts.dm_channel)

    def test_private_player_catalog_update_command_is_registered(self):
        self.assert_private_group("player_catalog", ["update"])

    def test_private_watch_stats_command_is_registered(self):
        self.assert_private_group(
            "watch", ["add", "remove", "list", "stats", "outlook", "recommend"]
        )

    def test_private_gameweek_commands_are_registered(self):
        self.assert_private_group("gameweek", ["prepare", "recap"])

    def test_private_trade_proposal_command_is_registered(self):
        self.assert_private_group("trade", ["propose"])

    def test_private_injury_opportunities_command_is_registered(self):
        self.assert_private_group("injury", ["opportunities"])

    def test_private_deadline_guardian_commands_are_registered(self):
        self.assert_private_group("guardian", ["done", "status"])


class DiscordInjuryDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_injury_report_is_delivered_as_complete_messages(self):
        client = build_client(_test_config())
        command = client._fantasy_command_tree.get_command("injury").get_command("opportunities")  # type: ignore[attr-defined]
        channel = type("Channel", (), {"send": AsyncMock()})()
        interaction = type(
            "Interaction",
            (),
            {
                "user": type("User", (), {"id": 123})(),
                "response": type("Response", (), {"defer": AsyncMock()})(),
                "edit_original_response": AsyncMock(),
                "followup": type("Followup", (), {"send": AsyncMock()})(),
                "channel": channel,
            },
        )()
        fake_context = type("Context", (), {"as_json": lambda self: "{}"})()
        long_report = "\n\n".join(["x" * 1800] * 6)
        with (
            patch("fantasy_advisor.discord_bot.load_injury_opportunities_context", return_value=fake_context),
            patch("fantasy_advisor.discord_bot.run_injury_web_briefing", return_value=object()),
            patch("fantasy_advisor.discord_bot.render_injury_opportunities", return_value=long_report),
        ):
            await command.callback(interaction)

        interaction.edit_original_response.assert_awaited_once()
        interaction.followup.send.assert_not_awaited()
        self.assertGreater(channel.send.await_count, 0)
        delivered = [interaction.edit_original_response.await_args.kwargs["content"]]
        delivered.extend(call.args[0] for call in channel.send.await_args_list)
        self.assertEqual("\n\n".join(delivered), long_report)
        self.assertTrue(all(len(message) <= 1900 for message in delivered))
        for call in channel.send.await_args_list:
            self.assertNotIn("file", call.kwargs)

    async def test_short_injury_report_uses_only_the_original_response(self):
        client = build_client(_test_config())
        command = client._fantasy_command_tree.get_command("injury").get_command("opportunities")  # type: ignore[attr-defined]
        channel = type("Channel", (), {"send": AsyncMock()})()
        interaction = type(
            "Interaction",
            (),
            {
                "user": type("User", (), {"id": 123})(),
                "response": type("Response", (), {"defer": AsyncMock()})(),
                "edit_original_response": AsyncMock(),
                "followup": type("Followup", (), {"send": AsyncMock()})(),
                "channel": channel,
            },
        )()
        fake_context = type("Context", (), {"as_json": lambda self: "{}"})()
        report = "🩺 **Injury opportunities**\nNo current injuries."
        with (
            patch("fantasy_advisor.discord_bot.load_injury_opportunities_context", return_value=fake_context),
            patch("fantasy_advisor.discord_bot.run_injury_web_briefing", return_value=object()),
            patch("fantasy_advisor.discord_bot.render_injury_opportunities", return_value=report),
        ):
            await command.callback(interaction)

        self.assertEqual(interaction.edit_original_response.await_args.kwargs["content"], report)
        channel.send.assert_not_awaited()
        interaction.followup.send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
