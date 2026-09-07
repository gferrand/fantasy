"""Behavioral coverage of the bounded advisor pipeline and evidence boundary."""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import ANY, AsyncMock, Mock, patch

from fantasy_advisor.automation import (
    AppConfig,
    AutomationError,
    FANTASY_WEB_MODEL,
    FANTASY_WEB_REASONING_EFFORT,
)
from fantasy_advisor import interactive_advisor as advisor
from fantasy_advisor.context_store import append_event, build_context_packet, DISCORD_USER_MESSAGE, PRIVATE_EVIDENCE
from fantasy_advisor.watchlist import WatchlistPlayer
from fantasy_advisor.watchlist_stats import WatchlistStat, WatchlistStatsReport

ROOT = Path(__file__).parents[1]


def config(root=ROOT):
    return AppConfig(
        repo_root=root, task_registry_path=root / "automation/tasks.toml",
        discord_bot_token=None, discord_allowed_user_id="123", discord_scheduled_channel_id=None,
        codex_bin="codex", codex_model="gpt-5.6-luna", codex_reasoning_effort="medium",
        codex_sandbox="read-only", codex_timeout_seconds=60, codex_ephemeral=False,
        openai_api_key="test-key",
    )


def result(text="OpenAI recommendation", output=None):
    return NS(output_text=text, output=output or [], id="response-test")


def plan(private=True, *, kind="player_evaluation", value="Julio Enciso"):
    request = None
    if private:
        request = {
            "kind": kind,
            "player_name": value if kind == "player_evaluation" else None,
            "codex_request": value if kind == "codex_exploration" else None,
        }
    return result(json.dumps({"needs_private_data": private, "request": request, "reason": "Current evidence needed"}))


def facts():
    return {"status": "complete", "data": {"roster_count": 17}, "limitations": [], "sources": [
        {"source": "Sleeper current roster", "retrieved_at": datetime.now(timezone.utc).isoformat(), "stale": False}
    ]}


def player_evaluation_facts():
    return {"status": "complete", "data": {"player_evaluation": {
        "target": {
            "player_id": "enciso", "positions": ["M", "F"], "club": "IPS", "active": True,
        },
        "ownership": {"state": "unrostered_unclassified"},
        "sleeper_standard": {"gp": 2, "gs": 2, "minutes": 175, "pts_std": 25.25},
        "kick_and_run": {"points_by_position": {"M": 31.5, "F": 28.0}},
        "los_blancos": {
            "roster_positions": ["M", "FM_FLEX"],
            "players": [{"name": "Roster Mid", "positions": ["M"]}],
        },
    }}, "limitations": [], "sources": [
        {"source": "Sleeper current league data", "retrieved_at": datetime.now(timezone.utc).isoformat(), "stale": False}
    ]}


def followup():
    return result("", [NS(type="function_call", name="retrieve_missing_private_fact", arguments=json.dumps({
        "request": {"kind": "player_evaluation", "player_name": "Julio Enciso", "codex_request": None},
        "reason": "Eligibility is essential to whether this swap is legal and Sleeper exposes it",
    }))])


class GuidanceTests(unittest.TestCase):
    def test_reasoning_standard_loads_from_repository(self):
        standard = advisor.advisor_reasoning(config())
        self.assertIn("# Fantasy Advisor Reasoning & Decision Standard", standard)
        self.assertIn("Do not tell the Owner to manually check", standard)

    def test_runtime_capability_contract_describes_named_tool_loop_not_planner_limits(self):
        contract = advisor.capability_contract(config()).casefold()
        self.assertIn("four deterministic/private tool calls", contract)
        self.assertIn("get_waiver_context", contract)
        self.assertNotIn("planner", contract)
        self.assertNotIn("third retrieval", contract)

    def test_missing_unreadable_or_empty_reasoning_standard_fails_clearly(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(AutomationError, "reasoning standard is unavailable"):
                advisor.advisor_reasoning(config(root))
            path = root / "docs/advisor/ADVISOR_REASONING.md"
            path.parent.mkdir(parents=True)
            path.write_text("\n", encoding="utf-8")
            with self.assertRaisesRegex(AutomationError, "reasoning standard is unavailable"):
                advisor.advisor_reasoning(config(root))
        with patch.object(Path, "read_text", side_effect=OSError("permission denied")):
            with self.assertRaisesRegex(AutomationError, "reasoning standard is unavailable"):
                advisor.advisor_reasoning(config())

    def test_runtime_source_does_not_duplicate_durable_reasoning_standard(self):
        source = Path(advisor.__file__).read_text(encoding="utf-8")
        self.assertNotIn("ADVISOR_INSTRUCTIONS =", source)
        self.assertNotIn("Optimize the roster, not the isolated player", source)

    def test_named_product_tool_rejects_raw_or_unknown_access(self):
        packet = advisor.execute_fantasy_tool(config(), "unknown", "{}", timeout=1)
        self.assertEqual(packet["status"], "partial")
        self.assertEqual(packet["limitations"][0]["field"], "requested_private_data")

    def test_watchlist_action_requires_a_named_explicit_tool_call(self):
        with patch.object(advisor, "LocalActions") as actions:
            actions.return_value.add_to_watchlist.return_value = {"status": "success", "data": {"name": "Enciso"}, "detail": "Added"}
            packet = advisor.execute_fantasy_tool(config(), "add_to_watchlist", json.dumps({"player_name": "Enciso"}), timeout=1, requester_id="123")
        self.assertEqual(packet["status"], "success")
        actions.return_value.add_to_watchlist.assert_called_once_with("Enciso")
        self.assertEqual(actions.call_args.kwargs["requester_id"], "123")

    def test_guardian_and_remove_are_named_authenticated_actions(self):
        with patch.object(advisor, "LocalActions") as actions:
            actions.return_value.remove_from_watchlist.return_value = {"status": "success", "data": {}, "detail": "Removed"}
            actions.return_value.acknowledge_guardian_alerts.return_value = {"status": "no_op", "data": {}, "detail": "None"}
            remove = advisor.execute_fantasy_tool(config(), "remove_from_watchlist", '{"player_name":"Enciso"}', timeout=1, requester_id="123")
            guardian = advisor.execute_fantasy_tool(config(), "acknowledge_guardian_alerts", "{}", timeout=1, requester_id="123")
        self.assertEqual(remove["status"], "success")
        self.assertEqual(guardian["status"], "no_op")
        actions.return_value.remove_from_watchlist.assert_called_once_with("Enciso")
        actions.return_value.acknowledge_guardian_alerts.assert_called_once()

    def test_named_catalog_routes_compact_league_and_market_requests(self):
        packet = {"status": "complete", "data": {}, "limitations": [], "sources": []}
        cases = (
            ("get_league_context", "{}", "get_league_context", ()),
            ("get_league_activity", '{"round_number":null}', "get_league_activity", (None,)),
            ("search_player_pool", '{"query":"Enciso","limit":5}', "search_player_pool", ("Enciso",)),
            ("get_draft_context", '{"player_name":"Damsgaard"}', "get_draft_context", ("Damsgaard",)),
            ("get_player_trends", '{"kind":"add","hours":24,"limit":8}', "get_player_trends", ()),
        )
        with patch.object(advisor, "DataCapabilities") as capabilities:
            for name, arguments, method, expected_args in cases:
                with self.subTest(name=name):
                    getattr(capabilities.return_value, method).return_value = packet
                    self.assertEqual(
                        advisor.execute_fantasy_tool(config(), name, arguments, timeout=1),
                        packet,
                    )
                    getattr(capabilities.return_value, method).assert_called()
                    self.assertEqual(
                        getattr(capabilities.return_value, method).call_args.args,
                        expected_args,
                    )
        capabilities.return_value.search_player_pool.assert_called_with("Enciso", limit=5)
        capabilities.return_value.get_player_trends.assert_called_with(
            kind="add", hours=24, limit=8,
        )

    def test_strict_tool_schemas_require_every_declared_property(self):
        for tool in advisor.FANTASY_TOOLS:
            with self.subTest(tool=tool["name"]):
                parameters = tool["parameters"]
                self.assertTrue(set(parameters["properties"]).issubset(parameters["required"]))
        activity = next(tool for tool in advisor.FANTASY_TOOLS if tool["name"] == "get_league_activity")
        self.assertEqual(activity["parameters"]["properties"]["round_number"]["type"], ["integer", "null"])

    def test_watchlist_stats_tool_uses_the_shared_bounded_stats_engine(self):
        watched = [WatchlistPlayer("enciso", "Julio Enciso", "IPS", ("M",), "2026-09-01T00:00:00+00:00")]
        report = WatchlistStatsReport(
            "2026", 3, "2026-09-07T12:00:00+00:00",
            (WatchlistStat(watched[0], 12.0, 2.0, 1.0, 120.0, None, 1.0, None, None, None, None, True),),
        )
        with (
            patch.object(advisor, "list_watchlist", return_value=watched),
            patch.object(advisor, "get_watchlist_stats", return_value=report) as stats,
        ):
            packet = advisor.execute_fantasy_tool(config(), "get_watchlist_stats", "{}", timeout=1)
        self.assertEqual(packet["status"], "complete")
        self.assertEqual(packet["data"]["entries"][0]["player"]["name"], "Julio Enciso")
        stats.assert_called_once_with(
            watched,
            client=ANY,
            include_trends=False,
            include_previous_season=False,
        )

    def test_named_intelligence_tools_return_provenanced_packets(self):
        context = NS(
            payload={"recommended_players": ["Enciso"]},
            retrieved_at="2026-09-07T12:00:00+00:00",
        )
        with (
            patch.object(advisor, "get_gameweek_prepare_context", return_value=context),
            patch.object(advisor, "get_injury_opportunity_context", return_value=context),
            patch.object(advisor, "load_persisted_fixture_schedule", return_value="schedule") as schedule,
            patch.object(advisor, "get_rotation_context", return_value=context) as rotation,
            patch.object(advisor, "get_trade_context", return_value=context) as trade,
        ):
            for name in (
                "get_gameweek_context",
                "get_injury_opportunity_context",
                "get_rotation_context",
                "get_trade_context",
            ):
                with self.subTest(name=name):
                    arguments = '{"mode":"prepare"}' if name == "get_gameweek_context" else "{}"
                    packet = advisor.execute_fantasy_tool(config(), name, arguments, timeout=1)
                    self.assertEqual(packet["status"], "complete")
                    self.assertEqual(packet["data"], context.payload)
                    self.assertFalse(packet["sources"][0]["stale"])
        self.assertEqual(schedule.call_count, 2)
        rotation.assert_called_once_with(
            manager_id=advisor.EXPECTED_MANAGER_ID,
            fixture_schedule="schedule",
            client=ANY,
        )
        trade.assert_called_once_with(
            manager_id=advisor.EXPECTED_MANAGER_ID,
            fixture_schedule="schedule",
            client=ANY,
        )

    def test_intelligence_provider_failures_return_partial_evidence(self):
        for name, arguments, target in (
            ("get_gameweek_context", '{"mode":"prepare"}', "get_gameweek_prepare_context"),
            ("get_injury_opportunity_context", "{}", "get_injury_opportunity_context"),
            ("get_rotation_context", "{}", "get_rotation_context"),
            ("get_trade_context", "{}", "get_trade_context"),
        ):
            with self.subTest(name=name), patch.object(advisor, target, side_effect=RuntimeError("provider unavailable")):
                if name in {"get_rotation_context", "get_trade_context"}:
                    with patch.object(advisor, "load_persisted_fixture_schedule", return_value="schedule"):
                        packet = advisor.execute_fantasy_tool(config(), name, arguments, timeout=1)
                else:
                    packet = advisor.execute_fantasy_tool(config(), name, arguments, timeout=1)
                self.assertEqual(packet["status"], "partial")
                self.assertEqual(packet["data"], {})
                self.assertEqual(packet["limitations"][0]["kind"], "temporarily_unavailable")


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_normal_advisor_starts_with_named_tools_not_the_legacy_planner(self):
        call = NS(type="function_call", name="get_player_context", arguments='{"player_name":"Enciso"}')
        client = NS(responses=NS(create=AsyncMock(side_effect=[result("", [call]), result("Grounded answer")])))
        packet = facts()
        with (patch.object(advisor, "execute_fantasy_tool", return_value=packet), patch.object(advisor, "persist_advisor_context_event")):
            answer = await advisor.run_advisor(config(), "Who owns Enciso?", client=client)
        self.assertEqual(answer.text, "Grounded answer")
        first = client.responses.create.call_args_list[0]
        self.assertNotIn("private_data_plan", first.kwargs["instructions"])
        self.assertEqual(first.kwargs["tool_choice"], "required")
        self.assertNotIn("web_search_preview", [tool["type"] for tool in first.kwargs["tools"]])
        self.assertNotIn("retrieve_missing_private_fact", [tool.get("name") for tool in first.kwargs["tools"] if tool["type"] == "function"])
        self.assertIn("get_player_context", [tool.get("name") for tool in first.kwargs["tools"] if tool["type"] == "function"])

    async def test_normal_advisor_executes_named_tool_then_returns_openai_answer(self):
        call = NS(type="function_call", name="get_team_context", arguments=json.dumps({"team_name": "Los Blancos"}))
        client = NS(responses=NS(create=AsyncMock(side_effect=[result("", [call]), result("Tool-grounded answer")])) )
        packet = {"status": "complete", "data": {"team": {"name": "Los Blancos"}}, "limitations": [], "sources": [{"source": "Sleeper league rosters", "retrieved_at": datetime.now(timezone.utc).isoformat(), "stale": False}]}
        with (
            patch.object(advisor, "execute_fantasy_tool", return_value=packet) as execute,
            patch.object(advisor, "persist_advisor_context_event") as persist,
        ):
            answer = await advisor.run_advisor(config(), "How is Los Blancos?", client=client)
        self.assertEqual(answer.text, "Tool-grounded answer")
        execute.assert_called_once()
        self.assertEqual(persist.call_args.kwargs["metadata"]["source"], "advisor_tool:get_team_context")
        self.assertEqual(json.loads(client.responses.create.call_args.kwargs["input"])["current_request_evidence"][0], packet)

    async def test_best_waiver_request_can_use_one_compound_capability_without_codex(self):
        call = NS(type="function_call", name="get_waiver_context", arguments='{"position":"ANY","limit":12}')
        client = NS(responses=NS(create=AsyncMock(side_effect=[result("", [call]), result("Add A, drop B")])) )
        packet = {"status": "complete", "data": {"available_candidates": [], "roster_swap_recommendations": []}, "limitations": [], "sources": [{"source": "test", "retrieved_at": datetime.now(timezone.utc).isoformat(), "stale": False}]}
        with (patch.object(advisor, "execute_fantasy_tool", return_value=packet) as execute, patch.object(advisor, "persist_advisor_context_event")):
            answer = await advisor.run_advisor(config(), "Look at my team and tell me the best waiver move I should make right now.", client=client, requester_id="123")
        self.assertEqual(answer.text, "Add A, drop B")
        execute.assert_called_once()
        self.assertEqual(execute.call_args.args[1], "get_waiver_context")
        first_names = [tool.get("name") for tool in client.responses.create.call_args_list[0].kwargs["tools"] if tool["type"] == "function"]
        self.assertNotIn("retrieve_missing_private_fact", first_names)

    async def test_normal_advisor_can_iterate_named_tools_for_compound_request(self):
        calls = [
            NS(type="function_call", name="get_team_context", arguments='{"team_name":"Los Blancos"}'),
            NS(type="function_call", name="get_watchlist", arguments="{}"),
        ]
        client = NS(responses=NS(create=AsyncMock(side_effect=[
            result("", [calls[0]]), result("", [calls[1]]), result("Compound answer"),
        ])))
        packet = {
            "status": "complete", "data": {}, "limitations": [],
            "sources": [{"source": "test", "retrieved_at": datetime.now(timezone.utc).isoformat(), "stale": False}],
        }
        with (
            patch.object(advisor, "execute_fantasy_tool", return_value=packet) as execute,
            patch.object(advisor, "persist_advisor_context_event"),
        ):
            answer = await advisor.run_advisor(config(), "Assess my roster and watchlist", client=client)
        self.assertEqual(answer.text, "Compound answer")
        self.assertEqual(execute.call_count, 2)
        final_input = json.loads(client.responses.create.call_args.kwargs["input"])
        self.assertEqual(len(final_input["current_request_evidence"]), 2)

    async def test_missing_reasoning_standard_stops_before_provider_work(self):
        client = NS(responses=NS(create=AsyncMock()))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capabilities = root / "docs/advisor/DATA_CAPABILITIES.md"
            capabilities.parent.mkdir(parents=True)
            capabilities.write_text("# Advisor data capabilities\n", encoding="utf-8")
            with self.assertRaisesRegex(AutomationError, "reasoning standard is unavailable"):
                await advisor.run_advisor(config(root), "hello", client=client)
        client.responses.create.assert_not_awaited()

    async def test_expired_deadline_starts_no_provider_work(self):
        client = NS(responses=NS(create=AsyncMock()))
        answer = await advisor.run_advisor(config(), "hello", client=client, deadline=advisor.RequestDeadline(time.monotonic() - 1))
        self.assertEqual(answer.text, advisor.CURRENT_DATA_REFRESH_FAILURE)
        client.responses.create.assert_not_awaited()

    async def test_transport_is_cancelled_at_deadline(self):
        cancelled = asyncio.Event()
        async def hung(**kwargs):
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.set()
        client = NS(responses=NS(create=hung))
        answer = await advisor.run_advisor(config(), "hello", client=client, deadline=advisor.RequestDeadline(time.monotonic() + 30.02))
        self.assertEqual(answer.text, advisor.CURRENT_DATA_REFRESH_FAILURE)
        self.assertTrue(cancelled.is_set())

    async def test_codex_fallback_is_only_for_unsupported_private_facts(self):
        call = NS(type="function_call", name="retrieve_missing_private_fact", arguments=json.dumps({
            "request": {"kind": "codex_exploration", "codex_request": "Find an unsupported private fact"}, "reason": "No named tool covers it",
        }))
        ground = NS(type="function_call", name="get_league_context", arguments="{}")
        client = NS(responses=NS(create=AsyncMock(side_effect=[result("", [ground]), result("", [call]), result("Conditional answer")])))
        with (patch.object(advisor, "retrieve_private_data", return_value=facts()) as retrieve, patch.object(advisor, "execute_fantasy_tool", return_value=facts()), patch.object(advisor, "persist_advisor_context_event")):
            answer = await advisor.run_advisor(config(), "What unusual private fact applies?", client=client)
        self.assertEqual(answer.text, "Conditional answer")
        retrieve.assert_called_once()
        self.assertNotIn("player_evaluation", json.dumps(client.responses.create.call_args_list[0].kwargs["tools"]))

    async def test_slow_first_pass_still_allows_one_explicit_authenticated_remove(self):
        call = NS(type="function_call", name="remove_from_watchlist", arguments='{"player_name":"Santos"}')
        client = NS(responses=NS(create=AsyncMock(side_effect=[asyncio.TimeoutError(), result("", [call]), result("Removed Santos.")])))
        packet = {"status": "success", "data": {"name": "Santos"}, "detail": "Removed", "limitations": [], "sources": []}
        with (patch.object(advisor, "execute_fantasy_tool", return_value=packet) as execute, patch.object(advisor, "persist_advisor_context_event")):
            answer = await advisor.run_advisor(config(), "Remove Santos from my watchlist.", client=client, requester_id="123")
        self.assertEqual(answer.text, "Removed Santos.")
        execute.assert_called_once()
        self.assertEqual(execute.call_args.args[1], "remove_from_watchlist")
        retry_tools = client.responses.create.call_args_list[1].kwargs["tools"]
        self.assertIn("remove_from_watchlist", [tool.get("name") for tool in retry_tools if tool["type"] == "function"])

    async def test_late_external_retrieval_window_does_not_hide_authenticated_remove(self):
        call = NS(type="function_call", name="remove_from_watchlist", arguments='{"player_name":"Santos"}')
        client = NS(responses=NS(create=AsyncMock(side_effect=[asyncio.TimeoutError(), result("", [call]), result("Removed Santos.")])))
        packet = {"status": "success", "data": {"name": "Santos"}, "detail": "Removed", "limitations": [], "sources": []}
        with (patch.object(advisor, "execute_fantasy_tool", return_value=packet) as execute, patch.object(advisor, "persist_advisor_context_event")):
            answer = await advisor.run_advisor(
                config(), "Remove Santos from my watchlist.", client=client, requester_id="123",
                deadline=advisor.RequestDeadline(time.monotonic() + 29),
            )
        self.assertEqual(answer.text, "Removed Santos from your watchlist.")
        execute.assert_called_once()

    async def test_slow_first_pass_does_not_mutate_for_watchlist_advice(self):
        client = NS(responses=NS(create=AsyncMock(side_effect=[asyncio.TimeoutError(), result("Here is advice only.")])))
        with (patch.object(advisor, "execute_fantasy_tool") as execute, patch.object(advisor, "persist_advisor_context_event")):
            answer = await advisor.run_advisor(config(), "Should I remove Santos from my watchlist?", client=client, requester_id="123")
        self.assertEqual(answer.text, advisor.CURRENT_DATA_REFRESH_FAILURE)
        execute.assert_not_called()

    async def test_completed_local_action_is_not_offered_for_a_same_request_retry(self):
        call = NS(type="function_call", name="remove_from_watchlist", arguments='{"player_name":"Santos"}')
        client = NS(responses=NS(create=AsyncMock(side_effect=[result("", [call]), result("Removed Santos.")])))
        packet = {"status": "success", "data": {"name": "Santos"}, "detail": "Removed", "limitations": [], "sources": []}
        with (patch.object(advisor, "execute_fantasy_tool", return_value=packet) as execute, patch.object(advisor, "persist_advisor_context_event")):
            answer = await advisor.run_advisor(config(), "Remove Santos from my watchlist.", client=client, requester_id="123")
        self.assertEqual(answer.text, "Removed Santos.")
        execute.assert_called_once()
        final_tools = client.responses.create.call_args_list[1].kwargs["tools"]
        self.assertNotIn(
            "remove_from_watchlist",
            [tool.get("name") for tool in final_tools if tool["type"] == "function"],
        )

    async def test_current_waiver_request_uses_a_fresh_compound_capability(self):
        call = NS(type="function_call", name="get_waiver_context", arguments='{"position":"ANY","limit":12}')
        client = NS(responses=NS(create=AsyncMock(side_effect=[result("", [call]), result("Fresh waiver answer.")])))
        packet = {"status": "complete", "data": {"available_candidates": []}, "limitations": [], "sources": []}
        with (patch.object(advisor, "execute_fantasy_tool", return_value=packet) as execute, patch.object(advisor, "persist_advisor_context_event")):
            await advisor.run_advisor(config(), "Look at my team and tell me the best waiver move I should make right now.", context_packet="recent conversation only", client=client)
        execute.assert_called_once()
        self.assertEqual(execute.call_args.args[1], "get_waiver_context")
        self.assertNotIn("RETAINED PRIVATE EVIDENCE", client.responses.create.call_args_list[0].kwargs["input"])
        self.assertEqual(client.responses.create.call_args_list[0].kwargs["tool_choice"], "required")
        final_tools = client.responses.create.call_args_list[1].kwargs["tools"]
        self.assertNotIn(
            "get_waiver_context",
            [tool.get("name") for tool in final_tools if tool["type"] == "function"],
        )

    async def test_grounding_noop_is_exclusive_and_public_only_uses_no_private_data(self):
        no_op = NS(type="function_call", name="no_private_fantasy_data_needed", arguments='{"reason":"Public club-role news only"}')
        client = NS(responses=NS(create=AsyncMock(side_effect=[result("", [no_op]), result("Tel update.")])))
        answer = await advisor.run_advisor(config(), "What’s the latest on Mathys Tel’s role at Tottenham?", client=client)
        self.assertEqual(answer.text, "Tel update.")
        self.assertEqual(answer.trace["grounding"][0]["calls"][0]["name"], "no_private_fantasy_data_needed")
        self.assertEqual(answer.trace["tools"][0]["status"], "no_op")
        second_tools = client.responses.create.call_args_list[1].kwargs["tools"]
        self.assertEqual([tool["type"] for tool in second_tools], ["web_search_preview"])

    async def test_invalid_grounding_retries_once_then_never_answers_from_history(self):
        no_op = NS(type="function_call", name="no_private_fantasy_data_needed", arguments='{"reason":"bad batch"}')
        private = NS(type="function_call", name="get_player_context", arguments='{"player_name":"Julio Enciso"}')
        client = NS(responses=NS(create=AsyncMock(side_effect=[result("", [no_op, private]), result("Plain answer")])))
        answer = await advisor.run_advisor(config(), "Who owns Julio Enciso right now?", context_packet="Enciso is unrostered", client=client)
        self.assertEqual(answer.text, advisor.CURRENT_DATA_REFRESH_FAILURE)
        self.assertEqual(client.responses.create.await_count, 2)
        self.assertEqual(answer.trace["grounding"][0]["error"], "The no-private-data function must be the sole grounding call.")

    async def test_grounding_calls_share_the_four_call_budget(self):
        ground = [
            NS(type="function_call", name="get_team_context", arguments='{"team_name":"Los Blancos"}'),
            NS(type="function_call", name="get_watchlist", arguments="{}"),
        ]
        later = [
            NS(type="function_call", name="get_player_context", arguments='{"player_name":"Julio Enciso"}'),
            NS(type="function_call", name="get_league_context", arguments="{}"),
            NS(type="function_call", name="get_rotation_context", arguments="{}"),
        ]
        client = NS(responses=NS(create=AsyncMock(side_effect=[result("", ground), result("", later)])))
        with (patch.object(advisor, "execute_fantasy_tool", return_value=facts()) as execute, patch.object(advisor, "persist_advisor_context_event")):
            answer = await advisor.run_advisor(config(), "Assess my roster and watchlist", client=client)
        self.assertEqual(answer.text, advisor.CURRENT_DATA_REFRESH_FAILURE)
        self.assertEqual(execute.call_count, 2)

    async def test_advice_never_mutates_when_grounding_selects_fresh_read(self):
        ground = NS(type="function_call", name="get_watchlist", arguments="{}")
        client = NS(responses=NS(create=AsyncMock(side_effect=[result("", [ground]), result("Keep Santos for now.")])))
        with (patch.object(advisor, "execute_fantasy_tool", return_value=facts()) as execute, patch.object(advisor, "persist_advisor_context_event")):
            answer = await advisor.run_advisor(config(), "Should I remove Santos from my watchlist?", client=client, requester_id="123")
        self.assertEqual(answer.text, "Keep Santos for now.")
        self.assertEqual(execute.call_args.args[1], "get_watchlist")
        self.assertNotEqual(answer.trace["local_action"], {"name": "remove_from_watchlist"})

    def test_runtime_has_no_phrase_based_waiver_router(self):
        self.assertNotIn("requires_fresh_waiver_context", Path(advisor.__file__).read_text())

    def test_current_player_and_unrostered_guidance_requires_fresh_evidence_and_web_research(self):
        instructions = advisor.ADVISOR_RUNTIME_INSTRUCTIONS
        waiver_tool = next(tool for tool in advisor.FANTASY_TOOLS if tool["name"] == "get_waiver_context")
        player_tool = next(tool for tool in advisor.FANTASY_TOOLS if tool["name"] == "get_player_context")
        self.assertIn("public web research", instructions)
        self.assertIn("unrostered, state that as fact", instructions)
        self.assertIn("immediate Add or through waivers", instructions)
        self.assertIn("Fresh current", player_tool["description"])
        self.assertIn("Unrostered means unrostered", waiver_tool["description"])


class RetrievalTests(unittest.TestCase):
    def test_accepts_fresh_and_stale_facts_and_each_limitation_kind(self):
        self.assertEqual(advisor.parse_retrieval(json.dumps(facts()))["status"], "complete")
        for kind in ("unsupported", "temporarily_unavailable", "not_found"):
            value = advisor.unavailable("Missing fact")
            value["limitations"][0]["kind"] = kind
            self.assertEqual(advisor.parse_retrieval(json.dumps(value)), value)
        value = facts()
        value["sources"][0].update(retrieved_at=None, stale=True)
        self.assertEqual(advisor.parse_retrieval(json.dumps(value)), value)

    def test_rejects_missing_provenance_unknown_live_time_and_malformed_fields(self):
        for mutate in (
            lambda x: x.update(sources=[]),
            lambda x: x["sources"][0].update(retrieved_at=None),
            lambda x: x["sources"][0].update(retrieved_at="2026-01-01"),
            lambda x: x["sources"][0].update(stale="false"),
            lambda x: x.update(status="partial"),
            lambda x: x.update(recommendation="drop someone"),
            lambda x: x.update(data=[]),
        ):
            with self.subTest(mutate=mutate):
                value = facts()
                mutate(value)
                with self.assertRaises(ValueError):
                    advisor.parse_retrieval(json.dumps(value))
        with self.assertRaises(ValueError):
            advisor.parse_retrieval("x" * 16001)

    def test_runner_enforces_readonly_ephemeral_and_no_browser(self):
        with patch.object(advisor, "CodexRunner") as runner:
            runner.return_value.run.return_value = NS(text=json.dumps(facts()))
            advisor.retrieve_private_data(replace(config(), codex_sandbox="danger-full-access"), "Retrieve roster", timeout=8)
        self.assertEqual(runner.call_args.args[0].codex_sandbox, "read-only")
        self.assertEqual(runner.call_args.args[0].codex_reasoning_effort, "low")
        options = runner.return_value.run.call_args.kwargs
        self.assertFalse(options["browser_capable"])
        self.assertTrue(options["ephemeral"])
        self.assertEqual(options["timeout_seconds"], 8)

    def test_player_evaluation_retrieval_contract_is_bounded_and_scoring_aware(self):
        with patch.object(advisor, "CodexRunner") as runner:
            runner.return_value.run.return_value = NS(text=json.dumps(facts()))
            advisor.retrieve_private_data(config(), "Evaluate Julio Enciso for Los Blancos", timeout=8)
        prompt = runner.return_value.run.call_args.args[0]
        self.assertIn("six targeted source reads", prompt)
        self.assertIn("build_player_stat_profile", prompt)
        self.assertIn("custom_points_by_position", prompt)
        self.assertIn("unrostered_unclassified", prompt)
        self.assertIn("do not duplicate", prompt)

    def test_runner_failure_and_invalid_json_become_honest_partial_evidence(self):
        for output in (AutomationError("private transport diagnostics"), NS(text="bad json")):
            with patch.object(advisor, "CodexRunner") as runner:
                if isinstance(output, Exception):
                    runner.return_value.run.side_effect = output
                else:
                    runner.return_value.run.return_value = output
                value = advisor.retrieve_private_data(config(), "retrieve roster", timeout=1)
                self.assertEqual(value["status"], "partial")
                self.assertEqual(value["data"], {})
                self.assertNotIn("private transport diagnostics", json.dumps(value))

    def test_persisted_evidence_preserves_conversation_and_source_timestamps(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "context.sqlite3"
            for i in range(20):
                append_event(path, kind=DISCORD_USER_MESSAGE, content=f"turn-{i:02} " + "x" * 1400)
            value = facts()
            append_event(path, kind=PRIVATE_EVIDENCE, content=json.dumps(value))
            standard = build_context_packet(path)
            packet = build_context_packet(path, include_private_evidence=True)
            self.assertNotIn("roster_count", standard)
            self.assertIn("roster_count", packet)
            self.assertIn(value["sources"][0]["retrieved_at"], packet)
            self.assertLessEqual(len(packet), 32000)
            for i in range(12, 20):
                self.assertIn(f"turn-{i:02}", packet)
            self.assertNotIn("turn-11", packet)


class TransportAndPresentationTests(unittest.TestCase):
    def test_private_runner_uses_scoped_readonly_network_profile(self):
        from fantasy_advisor.automation import CodexRunner
        command = CodexRunner(config(), private_data_only=True).command(Path('/tmp/test-answer'))
        self.assertIn('default_permissions="fantasy_retrieval"', command)
        profile = next(value for value in command if value.startswith('permissions.fantasy_retrieval='))
        import tomllib
        settings = tomllib.loads('profile=' + profile.split('=', 1)[1])['profile']
        self.assertEqual(settings['extends'], ':read-only')
        self.assertEqual(settings['network']['domains'], {'api.sleeper.app': 'allow', 'api.sleeper.com': 'allow'})
        self.assertIn('features.network_proxy=true', command)
        self.assertIn('web_search="disabled"', command)
        legacy = CodexRunner(config()).command(Path('/tmp/test-answer'))
        self.assertIn('--sandbox', legacy)
        self.assertNotIn('features.network_proxy=true', legacy)

    def test_citation_annotations_become_discord_links(self):
        marker = 'citeturn0search0'
        text = 'Verified current news. ' + marker
        annotation = NS(type='url_citation', url='https://example.com/news', title='Club update', start_index=text.index(marker), end_index=len(text))
        response = result(text, [NS(type='message', content=[NS(type='output_text', text=text, annotations=[annotation])])])
        rendered = advisor.discord_answer_text(response)
        self.assertEqual(rendered, 'Verified current news. [Club update](<https://example.com/news>)')
        self.assertNotIn('turn0search', rendered)

    def test_annotation_does_not_replace_the_claim_itself(self):
        text = 'Verified current news.'
        annotation = NS(type='url_citation', url='https://example.com/news', title='Club update', start_index=0, end_index=len(text))
        response = result(text, [NS(type='message', content=[NS(type='output_text', text=text, annotations=[annotation])])])
        rendered = advisor.discord_answer_text(response)
        self.assertIn(text, rendered)
        self.assertIn('[Club update](<https://example.com/news>)', rendered)


class FreshnessRegressionTests(unittest.TestCase):
    def test_prior_observation_cannot_be_labeled_fresh_in_current_retrieval(self):
        value = facts()
        value['sources'][0]['retrieved_at'] = '2026-01-01T00:00:00+00:00'
        with self.assertRaisesRegex(ValueError, 'predates'):
            advisor.parse_retrieval(json.dumps(value), not_before=time.time())
        value['sources'][0]['stale'] = True
        self.assertTrue(advisor.parse_retrieval(json.dumps(value), not_before=time.time())['sources'][0]['stale'])

    def test_new_retrieval_timestamp_is_accepted(self):
        self.assertEqual(advisor.parse_retrieval(json.dumps(facts()), not_before=time.time())['status'], 'complete')

    def test_unsupported_complete_status_is_rejected(self):
        value = facts()
        value['status'] = 'ok'
        with self.assertRaisesRegex(ValueError, 'status'):
            advisor.parse_retrieval(json.dumps(value))
