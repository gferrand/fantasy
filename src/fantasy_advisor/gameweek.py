"""Current, read-only Sleeper context for gameweek preparation and recaps."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Mapping

from .league import LEAGUE_ID
from .forecast_model import MODEL_VERSION, historical_inputs
from .forecast_history import pending_actual_weeks, record_actuals
from .availability import apply_availability_adjustments
from .sleeper import API_BASE, STATS_BASE, SleeperClient, SleeperDataError
from .trade_proposals import (
    INACTIVE_INJURY_STATUSES,
    apply_fixture_adjusted_projections,
    evaluate_lineup,
    projection_signal_from_player,
)


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


def latest_completed_gameweek(state: object) -> int:
    """Return the completed round used by Fantasy's established recap flow.

    Sleeper's EPL state exposes ``display_week`` as the round being displayed;
    the recap has always reported the immediately preceding completed round.
    Keeping this rule here prevents transaction and recap callers from making
    separate calendar assumptions.
    """

    _season, display_week = _season_and_week(state)
    return max(1, display_week - 1)


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


def _prepare_forecasts(
    players: list[dict[str, Any]],
    *,
    scoring_settings: Mapping[str, Any],
    starting_slots: list[str],
    fixture_schedule: object | None,
    now: datetime,
    current_rows: list[Mapping[str, Any]],
    prior_rows: list[Mapping[str, Any]],
    recent_weekly_rows: list[list[Mapping[str, Any]]],
    availability_packet: object | None = None,
) -> dict[str, Any]:
    """Attach one-fixture custom-score forecasts and a legal deterministic XI.

    This deliberately consumes only the supplied Sleeper rows and persisted
    fixture board.  A missing input is displayed as unavailable instead of
    being converted into false precision.
    """
    signals = [
        projection_signal_from_player(
            player["player_id"],
            {"full_name": player["name"], "team_abbr": player["club"], "fantasy_positions": player["positions"], "injury_status": player["injury_status"]},
            player["raw_stats"],
            scoring_settings,
        )
        for player in players
    ]
    by_id = {signal["player_id"]: signal for signal in signals}
    player_by_id = {player["player_id"]: player for player in players}
    historical_inputs(
        signals,
        current_rows=current_rows,
        prior_rows=prior_rows,
        recent_weekly_rows=recent_weekly_rows,
        scoring_settings=scoring_settings,
    )
    verified_availability = apply_availability_adjustments(signals, availability_packet)
    scoring_available = bool(scoring_settings) and all(signal["scoring_data_available"] for signal in signals)
    if fixture_schedule is not None and scoring_available:
        apply_fixture_adjusted_projections(signals, schedule=fixture_schedule, now=now, horizon=1)
    unavailable_reason = (
        "Forecast unavailable: the persisted fixture calendar is unavailable."
        if fixture_schedule is None
        else "Forecast unavailable: Kick & Run scoring or player season data is unavailable."
    )
    complete = fixture_schedule is not None and scoring_available
    fragments: list[str] = []
    for player in players:
        signal = by_id[player["player_id"]]
        status = signal["injury_status"]
        if complete and signal.get("forecast_horizon_fixtures", 0) == 1:
            points = round(float(signal["projected_horizon_points"]), 1)
        else:
            points = None
        if points is None:
            display = f"**{player['name']}** · forecast unavailable"
        else:
            display = f"**{player['name']}** · est. {points:.1f} Kick & Run pts"
        marker = _availability_marker(status)
        if marker:
            display += f" · {marker}"
        player["forecast"] = {"points": points, "display": display, "status": "complete" if points is not None else "unavailable"}
        fragments.append(display)
        signal["projected_gameweek_points"] = points if points is not None else 0.0
        # Availability must not change the counterfactual estimate, but an
        # unavailable player cannot be selected into a legal projected XI.
        signal["projected_lineup_selection_points"] = (
            0.0 if status in INACTIVE_INJURY_STATUSES else signal["projected_gameweek_points"]
        )
    if not complete or any(player["forecast"]["points"] is None for player in players):
        return {"available": False, "note": unavailable_reason, "required_fragments": [unavailable_reason, *fragments]}
    lineup = evaluate_lineup(signals, starting_slots, score_field="projected_lineup_selection_points")
    if len(lineup.player_ids) != len(starting_slots):
        note = "Forecast unavailable: a legal starting XI could not be formed from the roster."
        return {"available": False, "note": note, "required_fragments": [note, *fragments]}
    total = round(sum(float(by_id[player_id]["projected_gameweek_points"]) for player_id in lineup.player_ids), 1)
    total_display = f"Projected XI: {total:.1f} Kick & Run pts"
    ordered_assignments = _ordered_forecast_xi_assignments(lineup.slot_assignments, by_id)
    xi_lines = [
        _forecast_xi_display(slot, by_id[player_id]["name"], player_by_id[player_id]["forecast"]["display"])
        for player_id, slot in ordered_assignments
    ]
    return {
        "available": True,
        "model_version": MODEL_VERSION,
        "availability_packet": verified_availability,
        "projected_xi_player_ids": [player_id for player_id, _slot in ordered_assignments],
        "projected_xi_slots": {player_id: slot for player_id, slot in ordered_assignments},
        "projected_xi_lines": xi_lines,
        "projected_xi_total": total,
        "total_display": total_display,
        "required_fragments": [total_display, *fragments],
    }


def _ordered_forecast_xi_ids(
    player_ids: tuple[str, ...], players: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Render a legal XI in the familiar goalkeeper-to-forwards order.

    Selection is deliberately completed before this display-only ordering, so
    flex eligibility and the calculated projection total cannot change.
    """
    position_order = {"GK": 0, "G": 0, "D": 1, "M": 2, "F": 3}

    def key(player_id: str) -> tuple[int, str, str]:
        player = players[player_id]
        positions = [str(position).upper() for position in player.get("positions", ())]
        rank = min((position_order.get(position, 4) for position in positions), default=4)
        return rank, str(player.get("name") or "").casefold(), player_id

    return sorted(player_ids, key=key)


def _availability_marker(status: object) -> str | None:
    normalized = str(status or "").upper()
    return {
        "GTD": "GTD",
        "DOUBTFUL": "DOUBTFUL",
        "OUT": "OUT",
        "O": "OUT",
        "IR": "OUT",
        "IR+": "OUT",
        "SUSP": "SUSPENDED",
        "SUSPENDED": "SUSPENDED",
        "ROLE_UNCERTAIN": "ROLE UNCERTAIN",
    }.get(normalized)


def _ordered_forecast_xi_assignments(
    assignments: tuple[tuple[str, str], ...], players: Mapping[str, Mapping[str, Any]],
) -> list[tuple[str, str]]:
    """Order selected actual Sleeper slots GK-to-forward for display."""
    position_order = {"GK": 0, "G": 0, "D": 1, "M": 2, "F": 3}

    def key(item: tuple[str, str]) -> tuple[int, str, str]:
        player_id, slot = item
        normalized = slot.upper()
        base = normalized.removesuffix("_FLEX")
        rank = min((position_order.get(position, 4) for position in base), default=4)
        return rank, normalized, str(players[player_id].get("name") or "").casefold()

    return sorted(assignments, key=key)


def _forecast_xi_display(slot: str, name: str, forecast_display: str) -> str:
    """Prefix the locked player forecast with the actual selected slot."""
    player_prefix = f"**{name}**"
    if not forecast_display.startswith(player_prefix):
        return forecast_display
    label = str(slot).upper().replace("_", " ")
    return f"**{label} — {name}**{forecast_display[len(player_prefix):]}"


def load_gameweek_prepare_context(
    *, manager_id: str, client: SleeperClient | None = None, retrieved_at: str | None = None,
    fixture_schedule: object | None = None, now: datetime | None = None,
    availability_packet: object | None = None,
) -> GameweekContext:
    """Load the current roster and current-season signals for the next GW."""

    sleeper = client or SleeperClient()
    season, next_week, league, rosters, users, season_rows = _load_common(manager_id=manager_id, client=sleeper)
    roster = next(item for item in rosters if str(item.get("owner_id")) == str(manager_id))
    players = _roster_players(roster, season_rows, include_week=False)
    # The previous regular season is optional: a promoted player or a temporary
    # Sleeper archive outage still has a useful current-season/peer forecast.
    prior_rows: list[Mapping[str, Any]] = []
    try:
        prior_rows = _validate_array(
            sleeper.get_json(f"{STATS_BASE}/clubsoccer:epl/{int(season) - 1}?season_type=regular"),
            "previous season stats",
        )
    except (SleeperDataError, KeyError):
        prior_rows = []
    # Recent completed weeks tune expected minutes only.  This bounded window
    # avoids turning a prepare request into a whole-season API crawl.
    recent_weekly_rows: list[list[Mapping[str, Any]]] = []
    for week in range(max(1, next_week - 3), next_week):
        try:
            recent_weekly_rows.append(_validate_array(
                sleeper.get_json(f"{STATS_BASE}/clubsoccer:epl/{season}/{week}?season_type=regular"),
                "recent gameweek stats",
            ))
        except (SleeperDataError, KeyError):
            continue
    by_id = {str(row.get("player_id") or ""): row for row in season_rows}
    for player in players:
        row = by_id.get(player["player_id"], {})
        player["raw_stats"] = row.get("stats") if isinstance(row.get("stats"), Mapping) else {}
    starting_slots = [str(value) for value in (league.get("roster_positions") or []) if str(value).upper() not in {"BN", "BENCH", "IR", "TAXI"}]
    forecast = _prepare_forecasts(
        players,
        scoring_settings=league.get("scoring_settings") if isinstance(league.get("scoring_settings"), Mapping) else {},
        starting_slots=starting_slots,
        fixture_schedule=fixture_schedule,
        now=now or datetime.now(timezone.utc),
        current_rows=season_rows,
        prior_rows=prior_rows,
        recent_weekly_rows=recent_weekly_rows,
        availability_packet=availability_packet,
    )
    for player in players:
        player.pop("raw_stats", None)
    payload = {
        "source": "live Sleeper EPL",
        "report": "next gameweek preparation",
        "season": season,
        "gameweek": next_week,
        "your_team": {
            "name": _team_name(users, roster.get("owner_id")) or "Your team",
            "roster_id": roster.get("roster_id"),
            "players": players,
            "current_starters": [str(value) for value in (roster.get("starters") or []) if str(value) != "0"],
            "reserve": [str(value) for value in (roster.get("reserve") or [])],
            "formation": (roster.get("metadata") or {}).get("formation") if isinstance(roster.get("metadata"), Mapping) else None,
        },
        "starting_slots": starting_slots,
        "scoring_settings": league.get("scoring_settings") if isinstance(league.get("scoring_settings"), Mapping) else {},
        "h2h_opponent": {
            "available": False,
            "reason": "Sleeper's EPL public API does not expose a league matchup endpoint for this gameweek.",
        },
        "forecast": forecast,
        "forecast_data": {
            "model_version": MODEL_VERSION,
            "prior_season": str(int(season) - 1),
            "prior_season_available": bool(prior_rows),
            "recent_completed_gameweeks": len(recent_weekly_rows),
            "availability_research": (
                forecast.get("availability_packet")
                or "No verified availability packet was supplied; Sleeper injury statuses only."
            ),
        },
    }
    return GameweekContext("prepare", season, next_week, retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds"), payload)


def sync_completed_forecast_actuals(repo_root: object, *, client: SleeperClient | None = None) -> int:
    """Join completed Sleeper weeks to prior forecast records.

    Only the current league scoring settings are used to translate raw rows,
    matching the same explicitly versioned scoring basis used at prediction
    time.  This runs after a prepare request and is bounded by the history
    store's small pending-week limit.
    """
    from pathlib import Path

    sleeper = client or SleeperClient()
    state = sleeper.get_json(f"{API_BASE}/state/clubsoccer:epl")
    season, display_week = _season_and_week(state)
    league = sleeper.get_json(f"{API_BASE}/league/{LEAGUE_ID}")
    scoring = league.get("scoring_settings") if isinstance(league, Mapping) and isinstance(league.get("scoring_settings"), Mapping) else {}
    completed = 0
    for historical_season, week in pending_actual_weeks(Path(repo_root), before_season=season, before_gameweek=display_week):
        try:
            rows = _validate_array(
                sleeper.get_json(f"{STATS_BASE}/clubsoccer:epl/{historical_season}/{week}?season_type=regular"),
                "completed forecast gameweek stats",
            )
        except SleeperDataError:
            continue
        actuals: dict[str, float] = {}
        for row in rows:
            player = row.get("player") if isinstance(row.get("player"), Mapping) else {}
            stats = row.get("stats") if isinstance(row.get("stats"), Mapping) else {}
            signal = projection_signal_from_player(str(row.get("player_id") or ""), player, stats, scoring)
            actuals[str(signal["player_id"])] = float(signal["current_custom_points"])
        record_actuals(Path(repo_root), season=historical_season, gameweek=week, actuals={
            "scoring_basis": "current Kick & Run settings", "player_points": actuals,
        })
        completed += 1
    return completed


def load_gameweek_recap_context(
    *, manager_id: str, client: SleeperClient | None = None, retrieved_at: str | None = None
) -> GameweekContext:
    """Load the most recently completed gameweek and all player results."""

    sleeper = client or SleeperClient()
    season, display_week, league, rosters, users, _season_rows = _load_common(manager_id=manager_id, client=sleeper)
    completed_week = latest_completed_gameweek({"season": season, "display_week": display_week})
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
