from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

from fantasy_advisor.automation import AppConfig, player_catalog_file
from fantasy_advisor.local_actions import LocalActions
from fantasy_advisor.player_catalog import refresh_player_catalog
from fantasy_advisor.deadline_guardian import record_initial_alerts
from unittest.mock import patch


def config(root):
    return AppConfig(repo_root=root, task_registry_path=root / "automation/tasks.toml", discord_bot_token=None, discord_allowed_user_id="owner", discord_scheduled_channel_id=None, codex_bin="codex", codex_model=None, codex_reasoning_effort=None, codex_sandbox="read-only", codex_timeout_seconds=60, codex_ephemeral=False)


def test_watchlist_actions_are_owner_only_and_idempotent():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); app = config(root)
        refresh_player_catalog(player_catalog_file(app), {"p": {"player_id": "p", "full_name": "Player", "team_abbr": "IPS", "fantasy_positions": ["M"], "competitions": ["epl"], "active": True, "status": "ACTIVE"}})
        assert LocalActions(app, requester_id="other").add_to_watchlist("Player")["status"] == "forbidden"
        actions = LocalActions(app, requester_id="owner")
        assert actions.add_to_watchlist("Player")["status"] == "success"
        assert actions.add_to_watchlist("Player")["status"] == "no_op"
        assert actions.remove_from_watchlist("Player")["status"] == "success"


def test_guardian_action_changes_only_active_events():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); app = config(root); now = datetime.now(timezone.utc)
        fixture = type("Fixture", (), {"event_id": "event", "kickoff": now + timedelta(hours=2), "home": "A", "away": "B"})()
        record_initial_alerts(app, [fixture], now=now)
        actions = LocalActions(app, requester_id="owner")
        assert actions.acknowledge_guardian_alerts(now=now)["status"] == "success"
        assert actions.acknowledge_guardian_alerts(now=now)["status"] == "no_op"


def test_operational_watchlist_failure_is_not_mislabeled_as_not_found():
    with tempfile.TemporaryDirectory() as directory:
        app = config(Path(directory))
        actions = LocalActions(app, requester_id="owner")
        with patch("fantasy_advisor.local_actions.load_local_player_catalog", side_effect=OSError("disk unavailable")):
            result = actions.add_to_watchlist("Enciso")
        assert result == {
            "status": "failure", "data": {},
            "detail": "I couldn’t update the watchlist right now. Please try again.",
        }
