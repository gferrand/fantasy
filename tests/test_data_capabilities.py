from pathlib import Path
import tempfile
import time

from fantasy_advisor.automation import AppConfig, EXPECTED_LEAGUE_ID
from fantasy_advisor.data_capabilities import DataCapabilities
from fantasy_advisor.sleeper import API_BASE
from fantasy_advisor.sleeper import SleeperClient
from fantasy_advisor.player_catalog import refresh_player_catalog
from fantasy_advisor.watchlist import add_watchlist_player


class FakeSleeper:
    def __init__(self, values): self.values, self.urls = values, []
    def get_json(self, url): self.urls.append(url); return self.values[url]


def config(root):
    return AppConfig(repo_root=root, task_registry_path=root / "automation/tasks.toml", discord_bot_token=None, discord_allowed_user_id=None, discord_scheduled_channel_id=None, codex_bin="codex", codex_model=None, codex_reasoning_effort=None, codex_sandbox="read-only", codex_timeout_seconds=60, codex_ephemeral=False)


def test_league_reads_are_reused_with_typed_provenance():
    with tempfile.TemporaryDirectory() as directory:
        client = FakeSleeper({f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}": {"name": "Kick & Run", "season": "2026", "scoring_settings": {"pos_m_g": 5}, "roster_positions": ["M"]}, f"{API_BASE}/state/clubsoccer:epl": {"season": "2026", "display_week": 7}})
        capabilities = DataCapabilities(config(Path(directory)), timeout=10, client=client)
        assert capabilities.get_league_context()["status"] == "complete"
        assert capabilities.get_league_context()["data"]["league"]["name"] == "Kick & Run"
        assert len(client.urls) == 2


def test_team_and_watchlist_are_product_level_results():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); app = config(root)
        add_watchlist_player(root / "data/automation/watchlist.sqlite3", {"player_id": "x", "name": "Player", "club": "IPS", "positions": ["M"]})
        client = FakeSleeper({f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}/users": [{"user_id": "a", "display_name": "Owner", "metadata": {"team_name": "Los Blancos"}}], f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}/rosters": [{"owner_id": "a", "roster_id": 1, "players": ["x"], "starters": ["x"]}]})
        capabilities = DataCapabilities(app, timeout=10, client=client)
        assert capabilities.get_team_context("Los Blancos")["data"]["team"]["player_ids"] == ["x"]
        assert capabilities.get_watchlist()["data"]["watchlist"][0]["name"] == "Player"
        assert capabilities.get_watchlist()["data"]["watchlist"][0]["name"] == "Player"


def test_transaction_results_are_bounded_and_invalid_round_is_explicit():
    with tempfile.TemporaryDirectory() as directory:
        url = f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}/transactions/3"
        client = FakeSleeper({url: [{"transaction_id": "t", "type": "waiver", "status": "complete", "adds": {"x": 1}, "secret": "not exposed"}]})
        capabilities = DataCapabilities(config(Path(directory)), timeout=10, client=client)
        packet = capabilities.get_league_activity(3)
        assert packet["data"]["transactions"] == [{"transaction_id": "t", "type": "waiver", "status": "complete", "created": None, "leg": None, "roster_ids": None, "adds": {"x": 1}, "drops": None, "draft_picks": None}]
        assert capabilities.get_league_activity(0)["limitations"][0]["kind"] == "unsupported"


def test_player_pool_never_calls_an_unowned_player_available_without_rosters():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); app = config(root)
        refresh_player_catalog(root / "data/automation/player_catalog.sqlite3", {"enciso": {"player_id": "enciso", "full_name": "Julio Enciso", "team_abbr": "IPS", "fantasy_positions": ["M"], "competitions": ["epl"], "active": True, "status": "ACTIVE"}})
        client = FakeSleeper({f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}/rosters": [{"owner_id": "x", "players": []}]})
        assert DataCapabilities(app, timeout=10, client=client).search_player_pool("Enciso")["data"]["players"][0]["ownership"]["state"] == "unrostered_unclassified"
        class BrokenSleeper:
            def get_json(self, _):
                from fantasy_advisor.sleeper import SleeperDataError
                raise SleeperDataError("unavailable")
        assert DataCapabilities(app, timeout=10, client=BrokenSleeper()).search_player_pool("Enciso")["data"]["players"][0]["ownership"] == {"state": "unknown"}


def test_draft_context_returns_only_a_small_pick_neighborhood():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); app = config(root)
        refresh_player_catalog(root / "data/automation/player_catalog.sqlite3", {"x": {"player_id": "x", "full_name": "Player X", "team_abbr": "IPS", "fantasy_positions": ["M"], "competitions": ["epl"], "active": True, "status": "ACTIVE"}})
        client = FakeSleeper({f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}": {"draft_id": "draft"}, f"{API_BASE}/draft/draft/picks": [{"pick_no": 1, "player_id": "a"}, {"pick_no": 2, "player_id": "x"}, {"pick_no": 3, "player_id": "b"}]})
        packet = DataCapabilities(app, timeout=10, client=client).get_draft_context("Player X", radius=1)
        assert [pick["player_id"] for pick in packet["data"]["picks"]] == ["a", "x", "b"]


def test_trends_are_bounded_and_never_presented_as_availability():
    with tempfile.TemporaryDirectory() as directory:
        url = f"{API_BASE}/players/clubsoccer:epl/trending/add?lookback_hours=24&limit=2"
        client = FakeSleeper({url: [{"player_id": "x", "count": 3}]})
        packet = DataCapabilities(config(Path(directory)), timeout=10, client=client).get_player_trends(kind="add", limit=2)
        assert packet["data"] == {"kind": "add", "lookback_hours": 24, "trends": [{"player_id": "x", "count": 3}]}


def test_whole_operation_deadline_stops_after_the_first_slow_provider_read():
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return b"{}"
    calls = []
    def slow(_, *, timeout):
        calls.append(timeout); time.sleep(timeout + 0.01); return Response()
    with tempfile.TemporaryDirectory() as directory:
        started = time.monotonic()
        packet = DataCapabilities(config(Path(directory)), timeout=0.03, client=SleeperClient(timeout=8, retries=1, opener=slow)).get_league_context()
        assert packet["status"] == "partial"
        assert len(calls) == 1
        assert calls[0] <= 0.03
        assert time.monotonic() - started < 0.08
