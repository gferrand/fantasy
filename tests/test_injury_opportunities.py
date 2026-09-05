import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fantasy_advisor.automation import (
    AppConfig,
    FANTASY_CODEX_MODEL,
    FANTASY_CODEX_REASONING_EFFORT,
    injury_web_briefing_prompt,
    run_injury_web_briefing,
)
from fantasy_advisor.injury_opportunities import (
    build_injury_opportunities_context,
    load_injury_opportunities_context,
    parse_injury_research,
    render_injury_opportunities,
)
from fantasy_advisor.sleeper import API_BASE, STATS_BASE


def player(player_id, name, club, injury_status=None, **updates):
    value = {
        "player_id": player_id,
        "full_name": name,
        "team_abbr": club,
        "competitions": ["epl"],
        "active": True,
        "status": "Active",
        "fantasy_positions": ["M"],
        "injury_status": injury_status,
    }
    value.update(updates)
    return value


def context_fixture():
    players = {
        "1": player("1", "Out Star", "ARS", "Out"),
        "2": player("2", "GTD Star", "CHE", "GTD"),
        "3": player("3", "Suspended Star", "ARS", "Sus"),
        "4": player("4", "Free Backup", "ARS"),
        "5": player("5", "Owned Backup", "CHE"),
        "6": player("6", "Old League Player", "BAR", "Out"),
        "7": player("7", "Inactive Player", "ARS", "Out", active=False),
        "8": player("8", "Questionable Star", "ARS", "Questionable"),
    }
    return build_injury_opportunities_context(
        state={"season": "2026", "display_week": 4},
        league={"scoring_settings": {"pos_m_g": 10}},
        players=players,
        rosters=[{"roster_id": 1, "owner_id": "u1", "players": ["1", "5"]}],
        users=[{"user_id": "u1", "display_name": "Team One"}],
        stats_rows=[
            {"player_id": "4", "stats": {"gs": 1, "min": 120, "pts_std": 18, "pos_m_g": 2}},
            {"player_id": "5", "stats": {"gs": 3, "min": 270, "pts_std": 30}},
        ],
        retrieved_at="2026-09-05T12:00:00+00:00",
    )


class InjuryContextTests(unittest.TestCase):
    def test_builds_complete_selected_status_board_and_candidates(self):
        context = context_fixture()
        injuries = context.payload["injured_players"]
        self.assertEqual([item["player_id"] for item in injuries], ["1", "2", "8"])
        self.assertEqual(injuries[0]["ownership"], {"rostered": True, "team": "Team One"})
        self.assertEqual([item["player_id"] for item in context.payload["beneficiary_candidates"]], ["4", "5"])
        self.assertEqual(context.payload["beneficiary_candidates"][0]["minutes"], 120.0)
        self.assertEqual(context.payload["beneficiary_candidates"][0]["custom_points"], 20.0)

    def test_load_fetches_complete_players_rosters_users_and_current_stats(self):
        class FakeClient:
            def __init__(self):
                self.urls = []

            def get_json(self, url):
                self.urls.append(url)
                if url.endswith("/state/clubsoccer:epl"):
                    return {"season": "2026", "display_week": 4}
                if url.endswith("/players/clubsoccer:epl"):
                    return {"1": player("1", "Out Star", "ARS", "Out")}
                if url.endswith("/league/1378147559444348928"):
                    return {"scoring_settings": {}}
                return []

        client = FakeClient()
        context = load_injury_opportunities_context(client=client, retrieved_at="now")
        self.assertEqual(len(context.payload["injured_players"]), 1)
        self.assertIn(f"{API_BASE}/league/1378147559444348928/rosters", client.urls)
        self.assertIn(f"{API_BASE}/league/1378147559444348928", client.urls)
        self.assertIn(f"{API_BASE}/league/1378147559444348928/users", client.urls)
        self.assertIn(f"{STATS_BASE}/clubsoccer:epl/2026?season_type=regular", client.urls)

    def test_renderer_is_complete_validates_ids_and_puts_unrostered_first(self):
        research = parse_injury_research(
            {
                "injuries": [
                    {
                        "player_id": "1",
                        "injury_summary": "Hamstring injury confirmed.",
                        "return_window": "Around three weeks",
                        "confidence": "high",
                        "sources": [{"title": "Club update", "url": "https://example.com/injury"}],
                    }
                ],
                "opportunities": [
                    {"player_id": "5", "injured_player_ids": ["2"], "role_change": "Could start.", "confidence": "medium", "sources": []},
                    {"player_id": "4", "injured_player_ids": ["1"], "role_change": "Expected to cover.", "confidence": "high", "sources": []},
                    {"player_id": "missing", "injured_player_ids": ["1"], "role_change": "Invalid.", "confidence": "high", "sources": []},
                ],
            }
        )
        report = render_injury_opportunities(context_fixture(), research)
        self.assertIn("Hamstring injury confirmed", report)
        self.assertIn("No reliable timetable", report)
        self.assertIn("**Questionable Star**", report)
        self.assertLess(report.index("**Free Backup**"), report.index("**Owned Backup**"))
        self.assertNotIn("missing", report)
        self.assertIn("confirm the Add option", report)

    def test_renderer_degrades_without_guessing(self):
        report = render_injury_opportunities(
            context_fixture(), None, research_error="research timeout"
        )
        self.assertEqual(report.count("Injury details not verified"), 3)
        self.assertEqual(report.count("No reliable timetable"), 3)
        self.assertIn("no role increase is inferred", report)


class InjuryWebTests(unittest.TestCase):
    def _config(self):
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
            openai_api_key="test-key",
        )

    def test_prompt_forbids_generic_timeline_guesses(self):
        prompt = injury_web_briefing_prompt(live_context="INJURY_CONTEXT")
        self.assertIn("INJURY_CONTEXT", prompt)
        self.assertIn("No reliable timetable", prompt)
        self.assertIn("Never estimate recovery\nfrom a generic injury type", prompt)
        self.assertIn("at most eight", prompt)
        self.assertIn("Prioritize unrostered", prompt)

    def test_runner_uses_web_search_and_strict_structured_output(self):
        payload = {"injuries": [], "opportunities": []}

        class FakeResponses:
            def __init__(self):
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return type("Response", (), {"output_text": json.dumps(payload)})()

        responses = FakeResponses()
        fake_client = type("Client", (), {"responses": responses})()
        with patch("openai.OpenAI", return_value=fake_client):
            result = run_injury_web_briefing(self._config(), live_context="{}")
        self.assertEqual(result.injuries, ())
        call = responses.calls[0]
        self.assertEqual(call["tools"], [{"type": "web_search_preview", "search_context_size": "medium"}])
        self.assertTrue(call["text"]["format"]["strict"])
        self.assertFalse(call["store"])


if __name__ == "__main__":
    unittest.main()
