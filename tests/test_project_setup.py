import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))


class ProjectSetupTests(unittest.TestCase):
    def test_analyze_waivers_command_is_registered(self):
        from fantasy_advisor.automation import AppConfig
        from fantasy_advisor.discord_bot import build_client

        config = AppConfig(
            repo_root=ROOT,
            task_registry_path=ROOT / "automation" / "tasks.toml",
            discord_bot_token="test",
            discord_allowed_user_id="1",
            discord_scheduled_channel_id="2",
            codex_bin="codex",
            codex_model="gpt-5.6-luna",
            codex_reasoning_effort="medium",
            codex_sandbox="read-only",
            codex_timeout_seconds=60,
            codex_ephemeral=True,
        )
        client = build_client(config)
        tree = client._fantasy_command_tree
        self.assertIn("analyze-waivers", [command.name for command in tree.get_commands()])

    def test_discord_presence_is_best_effort_and_guild_handling_stays_disabled(self):
        source = (ROOT / "src" / "fantasy_advisor" / "discord_bot.py").read_text()
        self.assertIn("async def set_online_presence()", source)
        self.assertIn("client.change_presence(status=discord.Status.online)", source)
        self.assertIn("asyncio.wait_for(", source)
        self.assertIn("def schedule_online_presence()", source)
        self.assertIn("Fantasy Discord presence set online", source)
        self.assertIn("async def on_resumed()", source)
        self.assertIn("Fantasy Discord presence update failed", source)
        self.assertIn("if message.guild is not None or not isinstance(message.channel, discord.DMChannel):", source)
        self.assertIn("allowed_installs(users=True, guilds=False)", source)
        self.assertIn('name="analyze-waivers"', source)
        self.assertIn("WAIVER_ANALYSIS_REQUEST", source)
        self.assertIn("waiver_analysis=True", source)
        self.assertIn("waiver_header()", source)
        self.assertIn("advisor_header()", source)

    def test_canonical_context_contains_league_identity(self):
        context = (ROOT / "league_context.md").read_text()
        self.assertIn("1378147559444348928", context)
        self.assertIn("Kick & Run", context)
        self.assertIn("Los Blancos", context)
        self.assertIn("1127171221277331456", context)


    def test_context_contains_current_club_safety_rules(self):
        context = (ROOT / "league_context.md").read_text()
        self.assertIn(
            "Never recommend a player solely because Sleeper labels them EPL-eligible.",
            context,
        )
        self.assertIn("Mohamed Salah", context)
        self.assertIn("Leandro Trossard", context)
        self.assertIn("Xavi Simons", context)


    def test_task_prompts_are_read_only(self):
        prompts = (ROOT / "docs" / "scheduled_tasks.md").read_text()
        self.assertIn("read-only fantasy EPL advisor", prompts)
        self.assertIn("Do not make or suggest that you made any Sleeper change.", prompts)
        self.assertIn("next seven calendar days", prompts)
        self.assertIn("RotoWire", prompts)
        self.assertIn("contingency swaps", prompts)
        self.assertIn("WAIVER AUCTION TARGETS", prompts)
        self.assertIn("IMMEDIATE FREE-AGENT PICKUPS", prompts)
        self.assertIn("No completed league trades today.", prompts)
        self.assertIn("Do not request the literal `{round}` placeholder.", prompts)
        self.assertIn("Trade data unavailable for this run", prompts)
        self.assertIn("Waiver targets unavailable for this run", prompts)
        self.assertIn("Immediate free-agent targets unavailable for this run", prompts)
        self.assertIn("stats-backed candidate set", prompts)

    def test_nightly_recap_task_has_schedule_and_safety_rules(self):
        task = (ROOT / "docs" / "nightly_recap_task.md").read_text()
        self.assertIn("10:00 PM", task)
        self.assertIn("America/New_York", task)
        self.assertIn("current calendar date in America/New_York", task)
        self.assertIn("Los Blancos", task)
        self.assertIn("Do not make, simulate, or imply that you made any Sleeper transaction.", task)
        self.assertIn("Sleeper's EPL eligibility tag can be stale", task)
        self.assertIn("scoring_settings", task)
        self.assertIn("api.sleeper.com/stats/clubsoccer:epl/2026?season_type=regular", task)
        self.assertIn("No Los Blancos players had a match today.", task)
        self.assertIn("next seven calendar days", task)
        self.assertIn("RotoWire", task)
        self.assertIn("at least two other credible sources", task)
        self.assertIn("F F M M M D D D GK FM_FLEX MD_FLEX", task)
        self.assertIn("High, Medium, or Low", task)
        self.assertIn("contingency swaps", task)
        self.assertIn("rechecked before kickoff", task)
        self.assertIn("transactions/{round}", task)
        self.assertIn("Completed trades today", task)
        self.assertIn("No completed league trades today.", task)
        self.assertIn("Waiver Auction Targets", task)
        self.assertIn("Immediate Free-Agent Pickups", task)
        self.assertIn("up to three", task)
        self.assertIn("Confirm the player shows an Add option in Sleeper before acting.", task)
        self.assertIn("Do not recommend a waiver bid amount", task)
        self.assertIn("top-level JSON array", task)
        self.assertIn("complete top-level JSON object", task)
        self.assertIn("Trade data unavailable for this run", task)
        self.assertIn("Waiver targets unavailable for this run", task)
        self.assertIn("Immediate free-agent targets unavailable for this run", task)
        self.assertIn("stats-backed candidate set", task)

    def test_transfer_monitor_task_is_hourly_and_read_only(self):
        task = (ROOT / "docs" / "transfer_monitor_task.md").read_text()
        self.assertIn("EPL top-player transfer monitor", task)
        self.assertIn("Every hour", task)
        self.assertIn("America/New_York", task)
        self.assertIn("✅ TRANSFER WATCH", task)
        self.assertIn("CONFIRMED, ADVANCED REPORT, or RUMOR", task)
        self.assertIn("must not make, simulate, or imply any Sleeper transaction", task)

    def test_discord_prompts_define_mobile_first_layouts(self):
        nightly = (ROOT / "docs" / "nightly_recap_task.md").read_text()
        transfer = (ROOT / "docs" / "transfer_monitor_task.md").read_text()
        watchlist = (ROOT / "docs" / "watchlist_report_task.md").read_text()
        self.assertIn("DISCORD MOBILE PRESENTATION (binding)", nightly)
        self.assertIn("🌙 NIGHTLY RECAP", nightly)
        self.assertIn("🚨 TRANSFER WATCH", transfer)
        self.assertIn("👀 WATCHLIST UPDATE", watchlist)

    def test_watchlist_task_requires_current_pl_evidence_and_quiet_day_status(self):
        task = (ROOT / "docs" / "watchlist_report_task.md").read_text()
        self.assertIn("8:00 AM", task)
        self.assertIn("2026/27 Premier League", task)
        self.assertIn("No material update", task)
        self.assertIn("previous-season, preseason, cup", task)
        self.assertIn("do not recommend, simulate, or imply", task)
        self.assertIn("no Discord conversation context", task)


if __name__ == "__main__":
    unittest.main()
