import tempfile
import unittest
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fantasy_advisor.automation import (
    AppConfig,
    AutomationError,
    advisor_context_file,
    CodexResult,
    CodexRunner,
    FANTASY_CODEX_MODEL,
    FANTASY_CODEX_REASONING_EFFORT,
    TaskSpec,
    final_message_from_events,
    load_live_compact_feed_context,
    load_interactive_live_feed_context,
    build_watchlist_live_packet,
    watchlist_file,
    premier_league_evidence_window,
    discord_channel_state_file,
    flush_outbox,
    interactive_prompt,
    load_registry,
    persist_advisor_context_event,
    persist_outbox_report,
    persist_discord_channel_id,
    persist_task_state,
    read_discord_channel_id,
    split_discord_message,
    run_scheduled_task,
    task_prompt_for_run,
    thread_id_from_events,
)
from fantasy_advisor.context_store import DISCORD_USER_MESSAGE, build_context_packet
from fantasy_advisor.watchlist import add_watchlist_player

def test_config() -> AppConfig:
    return AppConfig(
        repo_root=ROOT,
        task_registry_path=ROOT / "automation" / "tasks.toml",
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


class AutomationTests(unittest.TestCase):
    def test_environment_cannot_override_fantasy_luna_medium_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.dict(
                os.environ,
                {
                    "CODEX_MODEL": "gpt-5.6-sol",
                    "CODEX_REASONING_EFFORT": "high",
                },
            ):
                config = AppConfig.from_environment(
                    repo_root=root,
                    env_file=root / "missing.env",
                )
        self.assertEqual(config.codex_model, "gpt-5.6-luna")
        self.assertEqual(config.codex_reasoning_effort, "medium")

    def test_scheduled_discord_configuration_requires_numeric_channel(self):
        missing = test_config().__class__(
            **{
                **test_config().__dict__,
                "discord_bot_token": "token",
                "discord_scheduled_channel_id": None,
            }
        )
        with self.assertRaisesRegex(AutomationError, "DISCORD_SCHEDULED_CHANNEL_ID is not configured"):
            missing.require_scheduled_discord()
        invalid = test_config().__class__(
            **{
                **test_config().__dict__,
                "discord_bot_token": "token",
                "discord_scheduled_channel_id": "fantasy",
            }
        )
        with self.assertRaisesRegex(AutomationError, "numeric Discord channel ID"):
            invalid.require_scheduled_discord()

    def test_registry_loads_scheduled_tasks_and_history_file(self):
        registry = load_registry(ROOT / "automation" / "tasks.toml", repo_root=ROOT)
        self.assertEqual([task.id for task in registry.tasks], ["nightly_recap", "transfer_monitor", "watchlist_report"])
        self.assertIsNone(registry.get("nightly_recap").state_file)
        self.assertEqual(
            registry.get("transfer_monitor").state_file,
            ROOT / "data" / "automation" / "transfer_monitor_last_result.md",
        )
        watchlist = registry.get("watchlist_report")
        self.assertEqual(watchlist.run_at, "08:00")
        self.assertEqual(watchlist.state_file, ROOT / "data" / "automation" / "watchlist_last_result.md")

    def test_watchlist_live_packet_is_scoped_and_empty_list_is_silent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "public").mkdir()
            core = {"schema_version": 1, "complete": True, "league_id": "1378147559444348928", "retrieved_at": "2026-08-25T00:00:00+00:00", "round": 2, "league": {"season": "2026"}, "state": {"display_week": 2}, "stats": [{"player_id": "10", "stats": {"gp": 2, "min": 180}}]}
            index = {**core, "players": [{"player_id": "10", "name": "Watched Player", "club": "ARS", "positions": ["M"]}]}
            (root / "public" / "sleeper_feed.json").write_text(json.dumps(core), encoding="utf-8")
            (root / "public" / "sleeper_player_index.json").write_text(json.dumps(index), encoding="utf-8")
            config = test_config().__class__(**{**test_config().__dict__, "repo_root": root})
            self.assertIsNone(build_watchlist_live_packet(config))
            add_watchlist_player(watchlist_file(config), index["players"][0])
            with patch("fantasy_advisor.automation.urlopen", side_effect=OSError("offline")):
                packet = build_watchlist_live_packet(config)
            self.assertIn("PERSONAL WATCHLIST LIVE SNAPSHOT", packet)
            self.assertIn("Watched Player", packet)
            self.assertIn('"gp":2', packet)
            self.assertNotIn("DISCORD_CONTEXT_MARKER", packet)

    def test_prompt_extraction_and_interactive_guardrails(self):
        registry = load_registry(ROOT / "automation" / "tasks.toml", repo_root=ROOT)
        prompt = task_prompt_for_run(registry.get("nightly_recap"))
        self.assertIn("LOCAL SCHEDULER EXECUTION CONTRACT", prompt)
        self.assertIn("return only its report", prompt)
        self.assertIn("Do not create, edit, enable, disable", prompt)
        self.assertIn("You are my read-only fantasy EPL advisor", prompt)
        self.assertIn("Pickup opportunities", prompt)
        self.assertIn("Do not make, simulate, or imply", prompt)
        self.assertIn("CURRENT-SEASON PREMIER LEAGUE EVIDENCE RULE", prompt)
        self.assertIn("Do not use 2025/26", prompt)
        one_off = interactive_prompt("Look through available players")
        self.assertIn("read-only", one_off)
        self.assertIn("Look through available players", one_off)
        self.assertIn("do not modify repository files", one_off)
        self.assertIn("Discord gateway normally supplies", one_off)
        self.assertIn("Do not read or download `data/sleeper_snapshot.json`", one_off)
        self.assertIn("raw Sleeper\n`/players/clubsoccer:epl`", one_off)
        self.assertIn("no more than six candidates", one_off)
        self.assertIn("Never\nuse 2025/26", one_off)
        self.assertIn("Not verified for the active Premier League season", one_off)
        self.assertIn("Evidence\nwindow:", one_off)
        waiver = interactive_prompt("Waiver analysis", waiver_analysis=True)
        self.assertIn("phone-first Discord waiver report", waiver)
        self.assertIn("Never use a Markdown table", waiver)
        self.assertIn("🎯 BEST PICKUPS", waiver)
        self.assertIn("🔁 RECOMMENDED SWAPS", waiver)
        self.assertIn("📋 FULL TOP 30", waiver)
        self.assertIn("team_swap_recommendations", waiver)
        self.assertNotIn("assess no more than six candidates", waiver)

    def test_premier_league_evidence_window_uses_live_season_and_round(self):
        window = premier_league_evidence_window(
            {
                "retrieved_at": "2026-08-25T04:04:27+00:00",
                "round": 2,
                "league": {"season": "2026"},
                "state": {"display_week": 2},
            }
        )
        self.assertIn("Season: 2026/27", window)
        self.assertIn("Competition: Premier League only", window)
        self.assertIn("Coverage: through GW2", window)
        self.assertIn("Do not use previous-season", window)

    def test_live_feed_context_falls_back_to_valid_local_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "public").mkdir()
            (root / "public" / "sleeper_feed.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "complete": True,
                        "league_id": "1378147559444348928",
                        "retrieved_at": "2026-08-25T00:00:00+00:00",
                        "round": 2,
                        "league": {"season": "2026"},
                        "available_players": [],
                    }
                ),
                encoding="utf-8",
            )
            config = test_config().__class__(
                **{**test_config().__dict__, "repo_root": root}
            )
            with patch("fantasy_advisor.automation.urlopen", side_effect=OSError("offline")):
                packet = load_live_compact_feed_context(config)
            self.assertIn("local fallback", packet)
            self.assertIn('"league_id":"1378147559444348928"', packet)
            self.assertIn("ACTIVE EVIDENCE WINDOW (binding)", packet)
            self.assertIn("Season: 2026/27", packet)

    def test_interactive_feed_context_is_roster_scoped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "public").mkdir()
            feed = {
                "schema_version": 1, "complete": True, "league_id": "1378147559444348928",
                "retrieved_at": "2026-08-25T00:00:00+00:00", "round": 2,
                "league": {"season": "2026", "name": "Kick & Run", "scoring_settings": {"pos_d_tk": 1}, "roster_positions": ["D"]},
                "state": {"display_week": 2},
                "users": [{"user_id": "1127171221277331456", "team_name": "Los Blancos"}],
                "rosters": [{"owner_id": "1127171221277331456", "players": ["owned"]}],
                "players": {"owned": {"name": "Owned Defender", "club": "ARS", "positions": ["D"]}, "other": {"name": "Other Player", "club": "CHE", "positions": ["M"]}},
                "stats": [{"player_id": "owned", "stats": {"gp": 2, "gs": 2, "min": 180, "ignored": 99}}],
                "available_players": [{"name": "Candidate"}],
                "team_swap_recommendations": [{"add": {"name": "Candidate"}, "drop": {"name": "Owned Defender"}, "position": "D", "current_season_point_gain": 5}],
                "team_swap_recommendations_note": "Manual review only.",
            }
            (root / "public" / "sleeper_feed.json").write_text(json.dumps(feed), encoding="utf-8")
            config = test_config().__class__(**{**test_config().__dict__, "repo_root": root})
            with patch("fantasy_advisor.automation.urlopen", side_effect=OSError("offline")):
                packet = load_interactive_live_feed_context(config, include_availability=True)
            self.assertIn("Owned Defender", packet)
            self.assertNotIn("Other Player", packet)
            self.assertNotIn('"ignored":99', packet)
            self.assertIn('"team_swap_recommendations"', packet)
            self.assertIn('"current_season_point_gain":5', packet)
            self.assertIn("INTERACTIVE", packet)

    def test_previous_state_is_bounded_and_included(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_file = Path(temporary) / "last.md"
            marker = "PREVIOUS_MARKER_123 "
            state_file.write_text("old result\n" + marker * 1400, encoding="utf-8")
            task = TaskSpec(
                id="test",
                name="Test",
                prompt_file=ROOT / "docs" / "nightly_recap_task.md",
                schedule_type="daily",
                state_file=state_file,
            )
            prompt = task_prompt_for_run(task)
            self.assertIn("LOCAL RUN HISTORY", prompt)
            self.assertNotIn("old result", prompt)
            self.assertLessEqual(prompt.count(marker), 12000 // len(marker))

    def test_scheduled_run_stays_standalone_and_writes_reference_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            prompt_file = root / "prompt.md"
            prompt_file.write_text("```text\nStandalone scheduled prompt\n```\n", encoding="utf-8")
            registry_file = root / "tasks.toml"
            registry_file.write_text(
                '[settings]\ntimezone = "America/New_York"\n\n'
                '[[tasks]]\nid = "nightly"\nname = "Nightly"\n'
                'prompt_file = "prompt.md"\nschedule_type = "daily"\nrun_at = "22:00"\n',
                encoding="utf-8",
            )
            config = AppConfig(
                repo_root=root,
                task_registry_path=registry_file,
                discord_bot_token=None,
                discord_allowed_user_id=None,
                discord_scheduled_channel_id=None,
                codex_bin="codex",
                codex_model=None,
                codex_reasoning_effort=None,
                codex_sandbox="read-only",
                codex_timeout_seconds=60,
                codex_ephemeral=False,
            )
            persist_advisor_context_event(
                config,
                kind=DISCORD_USER_MESSAGE,
                content="DISCORD_CONTEXT_MARKER",
            )
            result = CodexResult("scheduled report", "thread-scheduled", 1.0)
            with patch("fantasy_advisor.automation.CodexRunner.run", return_value=result) as runner:
                run_scheduled_task(config, "nightly", deliver=False)

            scheduled_prompt = runner.call_args.args[0]
            self.assertIn("Standalone scheduled prompt", scheduled_prompt)
            self.assertNotIn("DISCORD_CONTEXT_MARKER", scheduled_prompt)
            packet = build_context_packet(advisor_context_file(config))
            self.assertIn("scheduled report", packet)

    def test_state_persistence_is_atomic_from_callers_perspective(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_file = Path(temporary) / "nested" / "last.md"
            task = TaskSpec(
                id="test",
                name="Test",
                prompt_file=ROOT / "docs" / "nightly_recap_task.md",
                schedule_type="daily",
                state_file=state_file,
            )
            persist_task_state(
                task,
                CodexResult(text="NO_MATERIAL_TRANSFER_UPDATE", thread_id="thread-1", elapsed_seconds=1.0),
            )
            self.assertIn("thread-1", state_file.read_text(encoding="utf-8"))
            self.assertFalse(state_file.with_suffix(".md.tmp").exists())

    def test_outbox_is_removed_only_after_delivery(self):
        class FakeTransport:
            def __init__(self):
                self.sent = []

            def send_channel(self, channel_id, report):
                self.sent.append((channel_id, report))

        with tempfile.TemporaryDirectory() as temporary:
            config = AppConfig(
                repo_root=Path(temporary),
                task_registry_path=Path(temporary) / "tasks.toml",
                discord_bot_token="token",
                discord_allowed_user_id="123",
                discord_scheduled_channel_id="789",
                codex_bin="codex",
                codex_model=None,
                codex_reasoning_effort=None,
                codex_sandbox="read-only",
                codex_timeout_seconds=60,
                codex_ephemeral=False,
            )
            task = TaskSpec("nightly", "Nightly", Path(temporary) / "prompt.md", "daily")
            report_file = persist_outbox_report(
                config,
                task,
                CodexResult("report", "thread-1", 1.0),
                "report",
            )
            transport = FakeTransport()
            flush_outbox(config, transport)
            self.assertEqual(transport.sent, [("789", "report")])
            self.assertFalse(report_file.exists())

    def test_automatic_scheduled_run_posts_to_configured_channel(self):
        class FakeTransport:
            def __init__(self):
                self.sent = []

            def send_channel(self, channel_id, report):
                self.sent.append((channel_id, report))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "prompt.md").write_text("```text\nScheduled prompt\n```\n", encoding="utf-8")
            registry_file = root / "tasks.toml"
            registry_file.write_text(
                '[settings]\ntimezone = "America/New_York"\n\n'
                '[[tasks]]\nid = "nightly"\nname = "Nightly"\n'
                'prompt_file = "prompt.md"\nschedule_type = "daily"\nrun_at = "22:00"\n',
                encoding="utf-8",
            )
            config = test_config().__class__(
                **{
                    **test_config().__dict__,
                    "repo_root": root,
                    "task_registry_path": registry_file,
                    "discord_bot_token": "token",
                    "discord_scheduled_channel_id": "789",
                }
            )
            transport = FakeTransport()
            result = CodexResult("scheduled report", "thread-1", 1.0)
            with (
                patch("fantasy_advisor.automation.CodexRunner.run", return_value=result),
                patch("fantasy_advisor.discord_transport.DiscordTransport", return_value=transport),
            ):
                run_scheduled_task(config, "nightly")
            self.assertEqual(len(transport.sent), 1)
            self.assertEqual(transport.sent[0][0], "789")
            self.assertIn("scheduled report", transport.sent[0][1])
            self.assertFalse(list((root / "data" / "automation" / "outbox").glob("*.md")))

    def test_failed_scheduled_run_is_queued_for_channel_retry_without_dm_fallback(self):
        class FailingTransport:
            def __init__(self):
                self.channel_attempts = []

            def send_channel(self, channel_id, report):
                self.channel_attempts.append((channel_id, report))
                raise AutomationError("channel unavailable")

            def send_dm(self, user_id, report):
                raise AssertionError("scheduled failures must never fall back to DM")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "prompt.md").write_text("```text\nScheduled prompt\n```\n", encoding="utf-8")
            registry_file = root / "tasks.toml"
            registry_file.write_text(
                '[settings]\ntimezone = "America/New_York"\n\n'
                '[[tasks]]\nid = "nightly"\nname = "Nightly"\n'
                'prompt_file = "prompt.md"\nschedule_type = "daily"\nrun_at = "22:00"\n',
                encoding="utf-8",
            )
            config = test_config().__class__(
                **{
                    **test_config().__dict__,
                    "repo_root": root,
                    "task_registry_path": registry_file,
                    "discord_bot_token": "token",
                    "discord_scheduled_channel_id": "789",
                }
            )
            transport = FailingTransport()
            with (
                patch(
                    "fantasy_advisor.automation.CodexRunner.run",
                    side_effect=AutomationError("Codex failed"),
                ),
                patch("fantasy_advisor.discord_transport.DiscordTransport", return_value=transport),
            ):
                with self.assertRaisesRegex(AutomationError, "Codex failed"):
                    run_scheduled_task(config, "nightly")
            self.assertEqual(transport.channel_attempts[0][0], "789")
            queued = list((root / "data" / "automation" / "outbox").glob("*.md"))
            self.assertEqual(len(queued), 1)
            self.assertIn("Nightly failed", queued[0].read_text(encoding="utf-8"))

    def test_discord_channel_state_is_local_and_atomic(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = AppConfig(
                repo_root=Path(temporary),
                task_registry_path=Path(temporary) / "tasks.toml",
                discord_bot_token="token",
                discord_allowed_user_id="123",
                discord_scheduled_channel_id="789",
                codex_bin="codex",
                codex_model=None,
                codex_reasoning_effort=None,
                codex_sandbox="read-only",
                codex_timeout_seconds=60,
                codex_ephemeral=False,
            )
            persist_discord_channel_id(config, "456")
            self.assertEqual(read_discord_channel_id(config), "456")
            self.assertTrue(discord_channel_state_file(config).exists())
            with self.assertRaisesRegex(RuntimeError, "numeric"):
                persist_discord_channel_id(config, "not-a-channel")

    def test_discord_chunks_obey_limit(self):
        text = ("paragraph\n" * 400) + "end"
        chunks = split_discord_message(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(0 < len(chunk) <= 2000 for chunk in chunks))
        self.assertIn("end", chunks[-1])

    def test_codex_command_is_non_interactive_and_read_only_by_default(self):
        command = CodexRunner(test_config()).command(Path("/tmp/fantasy-last-message.txt"))
        self.assertEqual(command[:3], ["codex", "--search", "exec"])
        self.assertIn("--model", command)
        self.assertIn("gpt-5.6-luna", command)
        self.assertIn('model_reasoning_effort="medium"', command)
        self.assertIn("--sandbox", command)
        self.assertIn("read-only", command)
        self.assertIn("--skip-git-repo-check", command)
        self.assertIn("--json", command)
        self.assertIn("--output-last-message", command)
        self.assertNotIn("--ephemeral", command)

    def test_interactive_runs_are_ephemeral_even_when_scheduled_runs_are_not(self):
        command = CodexRunner(test_config()).command(
            Path("/tmp/fantasy-last-message.txt"),
            ephemeral=True,
        )
        self.assertIn("--ephemeral", command)

    def test_host_executor_request_pins_luna_medium(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(
                    {"status": "completed", "result": {"response": "ok"}}
                ).encode()

        def fake_urlopen(request, timeout):
            captured["payload"] = json.loads(request.data.decode())
            captured["timeout"] = timeout
            return FakeResponse()

        config = test_config().__class__(
            **{
                **test_config().__dict__,
                "host_executor_url": "http://127.0.0.1:8799",
                "host_executor_token": "secret",
            }
        )
        with patch("fantasy_advisor.automation.urlopen", side_effect=fake_urlopen):
            result = CodexRunner(config).run("Return ok.", label="test")
        self.assertEqual(result.text, "ok")
        self.assertEqual(captured["payload"]["model"], "gpt-5.6-luna")
        self.assertEqual(captured["payload"]["reasoning_effort"], "medium")

    def test_codex_event_parsing(self):
        events = "\n".join(
            [
                '{"type":"thread.started","thread_id":"thread-123"}',
                '{"type":"item.completed","item":{"type":"agent_message","text":"first"}}',
                '{"type":"item.completed","item":{"type":"agent_message","text":"final"}}',
            ]
        )
        self.assertEqual(thread_id_from_events(events), "thread-123")
        self.assertEqual(final_message_from_events(events), "final")


if __name__ == "__main__":
    unittest.main()
