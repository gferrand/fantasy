"""Coverage for bounded deterministic named-player evidence packets."""

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fantasy_advisor.automation import AppConfig, EXPECTED_LEAGUE_ID, EXPECTED_MANAGER_ID, player_catalog_file
from fantasy_advisor.player_catalog import PlayerCatalogNotInitialized, read_player_catalog, refresh_player_catalog
from fantasy_advisor.player_evaluation import get_player_evaluation_context
from fantasy_advisor.sleeper import API_BASE, STATS_BASE, SleeperClient, SleeperDataError


def config(root: Path) -> AppConfig:
    return AppConfig(
        repo_root=root, task_registry_path=root / "automation/tasks.toml",
        discord_bot_token=None, discord_allowed_user_id="123", discord_scheduled_channel_id=None,
        codex_bin="codex", codex_model=None, codex_reasoning_effort=None,
        codex_sandbox="read-only", codex_timeout_seconds=60, codex_ephemeral=False,
    )


class FakeSleeper:
    def __init__(self, values):
        self.values = values
        self.urls = []

    def get_json(self, url):
        self.urls.append(url)
        value = self.values[url]
        if isinstance(value, Exception):
            raise value
        return value


class PlayerEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = config(self.root)
        refresh_player_catalog(player_catalog_file(self.config), {
            "enciso": {"player_id": "enciso", "full_name": "Julio Enciso", "team_abbr": "OLD", "fantasy_positions": ["M"], "competitions": ["epl"], "active": True, "status": "ACTIVE"},
            "lb": {"player_id": "lb", "full_name": "Roster Mid", "team_abbr": "LIV", "fantasy_positions": ["M"], "competitions": ["epl"], "active": True, "status": "ACTIVE"},
        }, refreshed_at="2026-09-07T00:00:00+00:00")

    def tearDown(self):
        self.temp.cleanup()

    def client(self, *, stats=None):
        season = "2026"
        return FakeSleeper({
            f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}": {"scoring_settings": {"pos_m_g": "5", "pos_f_g": "4"}, "roster_positions": ["M", "F", "FM_FLEX"]},
            f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}/users": [
                {"user_id": EXPECTED_MANAGER_ID, "metadata": {"team_name": "Los Blancos"}},
                {"user_id": "other", "metadata": {"team_name": "Other XI"}},
            ],
            f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}/rosters": [
                {"owner_id": EXPECTED_MANAGER_ID, "players": ["lb"]}, {"owner_id": "other", "players": []},
            ],
            f"{API_BASE}/state/clubsoccer:epl": {"season": season},
            f"{STATS_BASE}/clubsoccer:epl/{season}?season_type=regular": stats if stats is not None else [
                {"player_id": "enciso", "player": {"full_name": "Julio Enciso", "team_abbr": "IPS", "fantasy_positions": ["M", "F"], "active": True, "status": "ACTIVE", "injury_status": "QUESTIONABLE"}, "stats": {"pts_std": 20, "gp": 2, "gs": 1, "min": 120, "g": 2, "a": 0, "pos_m_g": 2, "pos_f_g": 2}},
                {"player_id": "lb", "player": {"full_name": "Roster Mid", "team_abbr": "LIV", "fantasy_positions": ["M"], "active": True, "status": "ACTIVE"}, "stats": {"pts_std": 9, "gp": 2, "min": 90, "g": 1, "pos_m_g": 1}},
            ],
        })

    def test_packet_uses_exactly_six_sources_and_fresh_player_metadata(self):
        client = self.client()
        packet = get_player_evaluation_context(self.config, "Julio Enciso", timeout=20, client=client)
        evidence = packet["data"]["player_evaluation"]
        target = evidence["target"]
        self.assertEqual(packet["status"], "complete")
        self.assertEqual(len(client.urls), 5)
        self.assertEqual(len(packet["sources"]), 6)
        self.assertEqual(target["club"], "IPS")
        self.assertEqual(target["positions"], ["M", "F"])
        self.assertEqual(target["eligibility_source"], "current_sleeper_stats")
        self.assertEqual(target["sleeper_standard"]["pts_std"], 20.0)
        self.assertEqual(target["kick_and_run"]["points_by_position"], {"M": 10.0, "F": 8.0})
        self.assertEqual(evidence["ownership"]["state"], "unrostered_unclassified")
        self.assertEqual([player["name"] for player in evidence["los_blancos"]["players"]], ["Roster Mid"])

    def test_stale_eligibility_is_disclosed_but_identity_is_usable(self):
        packet = get_player_evaluation_context(self.config, "Julio Enciso", timeout=20, client=self.client(stats=[]))
        target = packet["data"]["player_evaluation"]["target"]
        self.assertEqual(target["eligibility_source"], "stale_catalog")
        self.assertTrue(any(item["field"] == "eligibility" for item in packet["limitations"]))

    def test_sleeper_failure_keeps_partial_packet_and_safe_wording(self):
        client = self.client()
        client.values[f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}/users"] = SleeperDataError("transport")
        with self.assertLogs("fantasy_advisor.player_evaluation", level="INFO") as logs:
            packet = get_player_evaluation_context(self.config, "Julio Enciso", timeout=20, client=client)
        self.assertEqual(packet["status"], "partial")
        self.assertTrue(any(item["field"] == "league_users" for item in packet["limitations"]))
        self.assertIn("failure=sleeper_source", "\n".join(logs.output))
        self.assertTrue(all("Sleeper" not in item["detail"] for item in packet["limitations"]))

    def test_rosters_failure_keeps_ownership_unknown(self):
        client = self.client()
        client.values[f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}/rosters"] = SleeperDataError("transport")
        packet = get_player_evaluation_context(self.config, "Julio Enciso", timeout=20, client=client)
        evidence = packet["data"]["player_evaluation"]
        self.assertEqual(packet["status"], "partial")
        self.assertEqual(evidence["ownership"], {"state": "unknown"})
        self.assertTrue(any(item["kind"] == "temporarily_unavailable" and item["field"] == "league_rosters" for item in packet["limitations"]))
        self.assertFalse(any(item.get("state") == "unrostered_unclassified" for item in [evidence["ownership"]]))

    def test_invalid_rosters_keeps_ownership_unknown(self):
        client = self.client()
        client.values[f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}/rosters"] = [{"owner_id": "other", "players": "not-a-list"}]
        packet = get_player_evaluation_context(self.config, "Julio Enciso", timeout=20, client=client)
        self.assertEqual(packet["data"]["player_evaluation"]["ownership"], {"state": "unknown"})
        self.assertTrue(any(item["field"] == "league_rosters" for item in packet["limitations"]))

    def test_packet_deadline_bounds_request_and_stops_following_reads(self):
        calls: list[float] = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"{}"

        def slow_opener(request, *, timeout):
            calls.append(timeout)
            time.sleep(timeout + 0.01)
            return Response()

        started = time.monotonic()
        packet = get_player_evaluation_context(
            self.config, "Julio Enciso", timeout=0.03,
            client=SleeperClient(timeout=8, retries=1, opener=slow_opener),
        )
        elapsed = time.monotonic() - started
        self.assertEqual(packet["status"], "partial")
        self.assertEqual(len(calls), 1)
        self.assertLessEqual(calls[0], 0.03)
        self.assertLess(elapsed, 0.08)
        self.assertTrue(any(item["field"] == "packet_deadline" for item in packet["limitations"]))

    def test_timeout_validation_local_and_profile_failures_are_diagnosed_safely(self):
        timeout = SleeperDataError("timeout")
        timeout.__cause__ = TimeoutError("deadline")
        client = self.client()
        client.values[f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}/users"] = timeout
        client.values[f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}/rosters"] = {"bad": "shape"}
        with patch("fantasy_advisor.player_evaluation.read_player_catalog", side_effect=OSError("bad disk")), self.assertLogs("fantasy_advisor.player_evaluation", level="INFO") as logs:
            packet = get_player_evaluation_context(self.config, "Julio Enciso", timeout=20, client=client)
        output = "\n".join(logs.output)
        self.assertIn("failure=timeout", output)
        self.assertIn("failure=validation", output)
        self.assertIn("failure=local_data", output)
        self.assertTrue(all(item["kind"] in {"unsupported", "temporarily_unavailable", "not_found"} for item in packet["limitations"]))

    def test_profile_failure_returns_partial_evidence(self):
        with patch("fantasy_advisor.player_evaluation._profile", side_effect=RuntimeError("broken helper")), self.assertLogs("fantasy_advisor.player_evaluation", level="INFO") as logs:
            packet = get_player_evaluation_context(self.config, "Julio Enciso", timeout=20, client=self.client())
        self.assertEqual(packet["status"], "partial")
        self.assertIn("failure=retrieval_system", "\n".join(logs.output))
        self.assertTrue(any(item["field"] == "player_profile" for item in packet["limitations"]))

    def test_missing_target_is_not_found(self):
        packet = get_player_evaluation_context(self.config, "Nobody", timeout=20, client=self.client())
        self.assertEqual(packet["status"], "partial")
        self.assertEqual(packet["limitations"][-1]["kind"], "not_found")

    def test_catalog_accessor_is_bounded_and_does_not_initialize_missing_database(self):
        missing = self.root / "data" / "automation" / "missing.sqlite3"
        with self.assertRaises(PlayerCatalogNotInitialized):
            read_player_catalog(missing, names=("Julio Enciso",))
        self.assertFalse(missing.exists())
        refreshed_at, rows = read_player_catalog(player_catalog_file(self.config), names=("Julio Enciso",))
        self.assertEqual(refreshed_at, "2026-09-07T00:00:00+00:00")
        self.assertEqual([row["player_id"] for row in rows], ["enciso"])
