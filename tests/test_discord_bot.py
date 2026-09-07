import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fantasy_advisor.automation import AppConfig, FANTASY_CODEX_MODEL, FANTASY_CODEX_REASONING_EFFORT
from fantasy_advisor import discord_bot
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

    def test_private_rotation_command_is_registered(self):
        client = build_client(_test_config())
        command = client._fantasy_command_tree.get_command("rotation")  # type: ignore[attr-defined]
        self.assertIsNotNone(command)
        self.assertFalse(command.allowed_contexts.guild)
        self.assertTrue(command.allowed_contexts.dm_channel)

    def test_rotation_initializes_fixture_schedule_when_missing(self):
        source = Path(discord_bot.__file__).read_text(encoding="utf-8")

        rotation_source = source.split("async def rotation_command", 1)[1][:1_500]
        self.assertIn("load_fixture_schedule,", rotation_source)
        self.assertIn("now=discord.utils.utcnow()", rotation_source)
        self.assertNotIn("load_persisted_fixture_schedule, config", rotation_source)

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


class UnifiedAdvisorDiscordTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from contextlib import ExitStack
        from types import SimpleNamespace as NS
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.advisor = self.stack.enter_context(patch.object(discord_bot, "run_advisor", new_callable=AsyncMock, return_value=NS(text="OpenAI final answer")))
        self.legacy = self.stack.enter_context(patch.object(discord_bot, "run_interactive_task", return_value=NS(text="Legacy waiver report", thread_id=None)))
        self.stack.enter_context(patch.object(discord_bot, "persist_discord_channel_id"))
        self.stack.enter_context(patch.object(discord_bot, "persist_advisor_context_event"))
        self.stack.enter_context(patch.object(discord_bot, "load_advisor_context", return_value="recent context"))
        self.stack.enter_context(patch.object(discord_bot, "claim_discord_message", return_value=True))
        self.client = build_client(_test_config())

    def message(self, content="Should I bench him?", attachments=None, author_id=123):
        from types import SimpleNamespace as NS
        from unittest.mock import Mock
        channel = Mock(spec=discord_bot.discord.DMChannel)
        channel.id = 1234
        channel.send = AsyncMock()
        return NS(content=content, attachments=attachments or [], author=NS(bot=False, id=author_id), guild=None, channel=channel, id=12345)

    async def test_plain_message_goes_to_openai_with_one_ack_and_answer(self):
        message = self.message()
        await self.client.on_message(message)
        self.advisor.assert_awaited_once()
        self.legacy.assert_not_called()
        self.assertEqual(message.channel.send.await_count, 2)
        self.assertIn("OpenAI final answer", message.channel.send.call_args.args[0])
        self.assertNotIn("Web briefing", message.channel.send.call_args.args[0])
        self.assertIn("recent context", self.advisor.call_args.kwargs["context_packet"])
        self.assertIsNotNone(self.advisor.call_args.kwargs["deadline"])

    async def test_ask_command_goes_to_unified_advisor(self):
        from types import SimpleNamespace as NS
        interaction = NS(user=NS(id=123), channel=NS(id=1234), response=NS(defer=AsyncMock()), edit_original_response=AsyncMock(), followup=NS(send=AsyncMock()))
        command = self.client._fantasy_command_tree.get_command("ask")
        await command.callback(interaction, "Should I bench him?")
        self.advisor.assert_awaited_once()
        self.legacy.assert_not_called()
        self.assertIn("OpenAI final answer", interaction.edit_original_response.call_args.kwargs["content"])

    async def test_waiver_command_keeps_legacy_route(self):
        from types import SimpleNamespace as NS
        from fantasy_advisor.advisor_router import RouteDecision, AdvisorRoute, LeagueDataScope
        interaction = NS(user=NS(id=123), channel=NS(id=1234), response=NS(defer=AsyncMock()), edit_original_response=AsyncMock(), followup=NS(send=AsyncMock()))
        command = self.client._fantasy_command_tree.get_command("analyze-waivers")
        with patch.object(discord_bot, "route_interactive_request", return_value=RouteDecision(AdvisorRoute.CODEX, "waiver", LeagueDataScope.LEAGUE_ROSTERS)):
            await command.callback(interaction)
        self.advisor.assert_not_awaited()
        self.legacy.assert_called_once()
        self.assertTrue(self.legacy.call_args.kwargs["waiver_analysis"])

    async def test_attachments_use_same_pipeline_and_remove_temporary_files(self):
        from types import SimpleNamespace as NS
        from fantasy_advisor.attachment_intake import NormalizedAttachment
        for kind, filename, content_type in (("pdf", "test.pdf", "application/pdf"), ("text", "test.txt", "text/plain"), ("audio", "test.ogg", "audio/ogg")):
            with self.subTest(kind=kind):
                paths = []
                async def save(path):
                    paths.append(path)
                    path.write_bytes(b"sample")
                attachment = NS(filename=filename, content_type=content_type, size=6, save=save)
                message = self.message(content="", attachments=[attachment])
                with patch.object(discord_bot, "normalize_attachment_async", new_callable=AsyncMock, return_value=NormalizedAttachment("Explain midfielder scoring", filename, kind, content_type)) as normalize:
                    await self.client.on_message(message)
                self.assertEqual(message.channel.send.await_count, 2)
                self.assertIn("Explain midfielder scoring", self.advisor.call_args.args[1])
                self.assertTrue(all(not path.exists() for path in paths))
                self.assertIs(normalize.call_args.kwargs["deadline"], self.advisor.call_args.kwargs["deadline"])

    async def test_attachment_failure_cleans_up_and_does_not_start_advisor(self):
        from types import SimpleNamespace as NS
        paths = []
        async def save(path):
            paths.append(path)
            path.write_bytes(b"bad")
        message = self.message(attachments=[NS(filename="test.pdf", content_type="application/pdf", size=3, save=save)])
        with patch.object(discord_bot, "normalize_attachment_async", side_effect=discord_bot.AttachmentIntakeError("Unreadable")):
            await self.client.on_message(message)
        self.advisor.assert_not_awaited()
        self.assertTrue(all(not path.exists() for path in paths))
        self.assertIn("Unreadable", message.channel.send.call_args.args[0])

    async def test_nonowner_and_guild_requests_are_ignored(self):
        for message in (self.message(author_id=999), self.message()):
            if message.author.id == 123:
                message.guild = object()
            await self.client.on_message(message)
            message.channel.send.assert_not_awaited()
        self.advisor.assert_not_awaited()

    async def test_whole_request_timeout_returns_visible_error(self):
        import asyncio
        import time
        from fantasy_advisor.interactive_advisor import RequestDeadline
        async def hung(*args, **kwargs):
            await asyncio.sleep(10)
        self.advisor.side_effect = hung
        message = self.message()
        with patch.object(discord_bot.RequestDeadline, "start", return_value=RequestDeadline(time.monotonic() + .02)):
            await self.client.on_message(message)
        self.assertIn("time limit", message.channel.send.call_args.args[0])
