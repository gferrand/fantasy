"""Current, read-only Sleeper context for gameweek preparation and recaps."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Mapping

from .sleeper import API_BASE, STATS_BASE, SleeperClient, SleeperDataError


LEAGUE_ID = "1378147559444348928"


@dataclass(frozen=True)
class GameweekContext:
    """The bounded live Sleeper data required for one gameweek report."""

    report_kind: str
    season: str
    gameweek: int
    retrieved_at: str
    payload: dict[str, Any]

    def as_json(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False, separators=(",", ":"))


def _number(mapping: Mapping[str, Any], key: str) -> float | None:
    try:
        return float(mapping[key])
    except (KeyError, TypeError, ValueError):
        return None


def _season_and_week(state: object) -> tuple[str, int]:
    if not isinstance(state, Mapping):
        raise SleeperDataError("Sleeper EPL state did not return an object")
    season = str(state.get("season") or "").strip()
    if not season.isdigit() or len(season) != 4:
        raise SleeperDataError("Sleeper EPL state did not include a current season")
    try:
        week = int(state.get("display_week") or state["week"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SleeperDataError("Sleeper EPL state did not include a current gameweek") from exc
    if week < 1:
        raise SleeperDataError("Sleeper EPL state included an invalid gameweek")
    return season, week


def _name(player_id: str, player: Mapping[str, Any]) -> str:
    metadata = player.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    return str(
        player.get("full_name")
        or metadata.get("full_name")
        or " ".join(str(value) for value in (player.get("first_name"), player.get("last_name")) if value)
        or f"Unknown player {player_id}"
    ).strip()


def _stat_player(row: Mapping[str, Any], *, include_week: bool) -> dict[str, Any]:
    player_id = str(row.get("player_id") or "").strip()
    player = row.get("player")
    player = player if isinstance(player, Mapping) else {}
    stats = row.get("stats")
    stats = stats if isinstance(stats, Mapping) else {}
    values = {
        key: value
        for key in ("pts_std", "gp", "gs", "min", "g", "a", "cs", "sv")
        if (value := _number(stats, key)) is not None
    }
    item = {
        "player_id": player_id,
        "name": _name(player_id, player),
        "club": str(player.get("team_abbr") or "").upper() or None,
        "positions": [str(value).upper() for value in (player.get("fantasy_positions") or [])],
        "injury_status": str(player.get("injury_status") or "").upper() or None,
        "stats": values,
    }
    if include_week:
        item["opponent_club_id"] = str(row.get("opponent") or "") or None
    return item


def _validate_array(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise SleeperDataError(f"Sleeper {label} did not return an array")
    return [item for item in value if isinstance(item, Mapping)]


def _load_common(*, manager_id: str, client: SleeperClient) -> tuple[str, int, Mapping[str, Any], list[Mapping[str, Any]], list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    state = client.get_json(f"{API_BASE}/state/clubsoccer:epl")
    season, display_week = _season_and_week(state)
    league = client.get_json(f"{API_BASE}/league/{LEAGUE_ID}")
    rosters = _validate_array(client.get_json(f"{API_BASE}/league/{LEAGUE_ID}/rosters"), "league rosters")
    users = _validate_array(client.get_json(f"{API_BASE}/league/{LEAGUE_ID}/users"), "league users")
    season_rows = _validate_array(
        client.get_json(f"{STATS_BASE}/clubsoccer:epl/{season}?season_type=regular"), "current season stats"
    )
    if not isinstance(league, Mapping):
        raise SleeperDataError("Sleeper league settings did not return an object")
    if not any(str(row.get("owner_id")) == str(manager_id) for row in rosters):
        raise SleeperDataError("Your current Sleeper roster could not be found")
    return season, display_week, league, rosters, users, season_rows


def _team_name(users: list[Mapping[str, Any]], owner_id: object) -> str | None:
    user = next((item for item in users if str(item.get("user_id")) == str(owner_id)), None)
    if user is None:
        return None
    metadata = user.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    return str(metadata.get("team_name") or user.get("display_name") or "").strip() or None


def _roster_players(
    roster: Mapping[str, Any], rows: list[Mapping[str, Any]], *, include_week: bool
) -> list[dict[str, Any]]:
    by_id = {str(row.get("player_id") or ""): row for row in rows}
    result = []
    for player_id in (roster.get("players") or []):
        row = by_id.get(str(player_id))
        if row is not None:
            result.append(_stat_player(row, include_week=include_week))
        else:
            result.append({"player_id": str(player_id), "name": f"Unknown player {player_id}", "club": None, "positions": [], "injury_status": None, "stats": {}})
    return result


def load_gameweek_prepare_context(
    *, manager_id: str, client: SleeperClient | None = None, retrieved_at: str | None = None
) -> GameweekContext:
    """Load the current roster and current-season signals for the next GW."""

    sleeper = client or SleeperClient()
    season, next_week, league, rosters, users, season_rows = _load_common(manager_id=manager_id, client=sleeper)
    roster = next(item for item in rosters if str(item.get("owner_id")) == str(manager_id))
    payload = {
        "source": "live Sleeper EPL",
        "report": "next gameweek preparation",
        "season": season,
        "gameweek": next_week,
        "your_team": {
            "name": _team_name(users, roster.get("owner_id")) or "Your team",
            "roster_id": roster.get("roster_id"),
            "players": _roster_players(roster, season_rows, include_week=False),
            "current_starters": [str(value) for value in (roster.get("starters") or []) if str(value) != "0"],
            "reserve": [str(value) for value in (roster.get("reserve") or [])],
            "formation": (roster.get("metadata") or {}).get("formation") if isinstance(roster.get("metadata"), Mapping) else None,
        },
        "starting_slots": [str(value) for value in (league.get("roster_positions") or []) if str(value).upper() not in {"BN", "BENCH", "IR", "TAXI"}],
        "scoring_settings": league.get("scoring_settings") if isinstance(league.get("scoring_settings"), Mapping) else {},
        "h2h_opponent": {
            "available": False,
            "reason": "Sleeper's EPL public API does not expose a league matchup endpoint for this gameweek.",
        },
    }
    return GameweekContext("prepare", season, next_week, retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds"), payload)


def load_gameweek_recap_context(
    *, manager_id: str, client: SleeperClient | None = None, retrieved_at: str | None = None
) -> GameweekContext:
    """Load the most recently completed gameweek and all player results."""

    sleeper = client or SleeperClient()
    season, display_week, league, rosters, users, _season_rows = _load_common(manager_id=manager_id, client=sleeper)
    completed_week = max(1, display_week - 1)
    weekly_rows = _validate_array(
        sleeper.get_json(f"{STATS_BASE}/clubsoccer:epl/{season}/{completed_week}?season_type=regular"),
        "gameweek stats",
    )
    roster = next(item for item in rosters if str(item.get("owner_id")) == str(manager_id))
    your_players = _roster_players(roster, weekly_rows, include_week=True)
    owned_by: dict[str, str] = {}
    for league_roster in rosters:
        team_name = _team_name(users, league_roster.get("owner_id")) or f"Roster {league_roster.get('roster_id')}"
        for player_id in league_roster.get("players") or []:
            owned_by[str(player_id)] = team_name
    all_players = [_stat_player(row, include_week=True) for row in weekly_rows]
    all_players.sort(key=lambda item: item["stats"].get("pts_std", 0), reverse=True)
    standouts = []
    for player in all_players[:12]:
        player["fantasy_team"] = owned_by.get(player["player_id"])
        standouts.append(player)
    payload = {
        "source": "live Sleeper EPL",
        "report": "completed gameweek recap",
        "season": season,
        "gameweek": completed_week,
        "your_team": {
            "name": _team_name(users, roster.get("owner_id")) or "Your team",
            "players": your_players,
            "record": (roster.get("metadata") or {}).get("record") if isinstance(roster.get("metadata"), Mapping) else None,
            "season_points": _number(roster.get("settings") if isinstance(roster.get("settings"), Mapping) else {}, "fpts"),
        },
        "league_standouts_by_sleeper_points": standouts,
        "h2h_opponent": {
            "available": False,
            "reason": "Sleeper's EPL public API does not expose a league matchup endpoint for this gameweek.",
        },
        "roster_slots": [str(value) for value in (league.get("roster_positions") or [])],
    }
    return GameweekContext("recap", season, completed_week, retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds"), payload)
