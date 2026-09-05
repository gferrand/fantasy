"""Fixture-aware, read-only roster rotation analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Iterable, Mapping

from .gameweek import LEAGUE_ID
from .sleeper import ACTIVE_EPL_CLUBS, API_BASE, STATS_BASE, SleeperClient, SleeperDataError
from .trade_proposals import (
    INACTIVE_INJURY_STATUSES,
    _player_from_row,
    _remaining_faab,
    _season_and_week,
    _starting_slots,
    _team_name,
    _validate_array,
    apply_fixture_adjusted_projections,
    build_trade_options,
    evaluate_lineup,
)


ROTATION_HORIZON = 4
MIN_PROJECTED_LINEUP_GAIN = 2.0
DIFFICULT_FIXTURE_THRESHOLD = 3.1
EXCLUDED_NAMES = {"Mohamed Salah", "Leandro Trossard"}
MEDICAL_HOLD_STATUSES = INACTIVE_INJURY_STATUSES | {"GTD", "QUESTIONABLE", "Q"}


@dataclass(frozen=True)
class RotationContext:
    season: str
    gameweek: int
    retrieved_at: str
    payload: dict[str, Any]

    def as_json(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False, separators=(",", ":"))


def _projected_gain(option: Mapping[str, Any]) -> float:
    if option.get("kind") == "available":
        return float(option.get("projected_lineup_gain") or 0.0)
    math = option.get("math") if isinstance(option.get("math"), Mapping) else {}
    return float(math.get("your_projected_lineup_gain") or 0.0)


def _exit_plan(player: Mapping[str, Any], extended: Mapping[str, Any]) -> str:
    fixtures = extended.get("forecast_next_fixtures")
    if not isinstance(fixtures, list) or len(fixtures) < 2:
        return "Reassess after the four-fixture window."
    search_end = min(len(fixtures), ROTATION_HORIZON + 2)
    for index in range(1, search_end):
        previous = fixtures[index - 1]
        upcoming = fixtures[index]
        try:
            jump = float(upcoming["difficulty"]) - float(previous["difficulty"])
        except (KeyError, TypeError, ValueError):
            continue
        if jump >= 0.75 and float(upcoming["difficulty"]) >= 3.4:
            return f"Reassess after {previous['opponent']}, before {upcoming['opponent']}."
    return "Reassess after the four-fixture window."


def _protected_players(
    owner_players: list[dict[str, Any]], slots: tuple[str, ...]
) -> tuple[set[str], list[dict[str, Any]]]:
    current = set(evaluate_lineup(owner_players, slots).player_ids)
    projected = set(
        evaluate_lineup(owner_players, slots, score_field="projected_horizon_points").player_ids
    )
    reasons: dict[str, set[str]] = {}
    for player_id in current:
        reasons.setdefault(player_id, set()).add("best current XI")
    for player_id in projected:
        reasons.setdefault(player_id, set()).add("best projected four-fixture XI")
    for player in owner_players:
        status = str(player.get("injury_status") or "").upper()
        if status in MEDICAL_HOLD_STATUSES:
            reasons.setdefault(str(player["player_id"]), set()).add("medical hold")
    protected = set(reasons)
    rendered = [
        {
            "player_id": player["player_id"],
            "name": player["name"],
            "club": player["club"],
            "reasons": sorted(reasons[str(player["player_id"])]),
            "fixture_difficulty": player.get("forecast_fixture_difficulty"),
            "next_fixtures": player.get("forecast_next_fixtures") or [],
        }
        for player in owner_players
        if str(player["player_id"]) in protected
    ]
    return protected, rendered


def _available_options(
    owner_players: list[dict[str, Any]],
    available_players: Iterable[dict[str, Any]],
    slots: tuple[str, ...],
    protected: set[str],
    extended_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    before = evaluate_lineup(owner_players, slots, score_field="projected_horizon_points")
    options: list[dict[str, Any]] = []
    for add in available_players:
        if str(add.get("injury_status") or "").upper() in MEDICAL_HOLD_STATUSES:
            continue
        if not add.get("positions") or not add.get("scoring_data_available"):
            continue
        if int(add.get("forecast_horizon_fixtures") or 0) < ROTATION_HORIZON:
            continue
        for drop in owner_players:
            drop_id = str(drop.get("player_id"))
            if drop_id in protected:
                continue
            after_players = [player for player in owner_players if str(player.get("player_id")) != drop_id]
            after_players.append(add)
            try:
                after = evaluate_lineup(after_players, slots, score_field="projected_horizon_points")
            except SleeperDataError:
                continue
            gain = round(after.score - before.score, 2)
            if gain < MIN_PROJECTED_LINEUP_GAIN:
                continue
            options.append(
                {
                    "kind": "available",
                    "add": {key: add.get(key) for key in (
                        "player_id", "name", "club", "positions", "injury_status", "minutes",
                        "starts", "custom_points_per_90", "projected_horizon_points",
                        "forecast_fixture_difficulty", "forecast_next_fixtures",
                    )},
                    "drop": {key: drop.get(key) for key in (
                        "player_id", "name", "club", "positions", "minutes",
                        "projected_horizon_points", "forecast_fixture_difficulty", "forecast_next_fixtures",
                    )},
                    "projected_lineup_before": before.score,
                    "projected_lineup_after": after.score,
                    "projected_lineup_gain": gain,
                    "availability": "unrostered_unclassified",
                    "exit_plan": _exit_plan(add, extended_by_id.get(str(add["player_id"]), {})),
                }
            )
    ranked = sorted(options, key=lambda option: (
        option["projected_lineup_gain"],
        float(option["add"].get("projected_horizon_points") or 0.0),
        -float(option["drop"].get("projected_horizon_points") or 0.0),
        float(option["drop"].get("forecast_fixture_difficulty") or 3.0),
        str(option["drop"].get("name") or "").casefold(),
    ), reverse=True)
    selected: list[dict[str, Any]] = []
    used_adds: set[str] = set()
    used_drops: set[str] = set()
    for option in ranked:
        add_id = str(option["add"]["player_id"])
        drop_id = str(option["drop"]["player_id"])
        if add_id in used_adds or drop_id in used_drops:
            continue
        selected.append(option)
        used_adds.add(add_id)
        used_drops.add(drop_id)
        if len(selected) == 5:
            break
    return selected


def _mix_moves(available: list[dict[str, Any]], trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = available[:2] + trades[:2]
    used = {id(item) for item in selected}
    remaining = [item for item in (*available, *trades) if id(item) not in used]
    remaining.sort(key=_projected_gain, reverse=True)
    selected.extend(remaining[: max(0, 5 - len(selected))])
    return selected[:5]


def load_rotation_context(
    *,
    manager_id: str,
    fixture_schedule: object,
    client: SleeperClient | None = None,
    now: datetime | None = None,
    retrieved_at: str | None = None,
) -> RotationContext:
    """Build deterministic four-fixture rotation and protected-core signals."""

    if fixture_schedule is None:
        raise SleeperDataError(
            "The local Premier League fixture schedule is required for rotation analysis"
        )
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    sleeper = client or SleeperClient()
    season, gameweek = _season_and_week(sleeper.get_json(f"{API_BASE}/state/clubsoccer:epl"))
    league = sleeper.get_json(f"{API_BASE}/league/{LEAGUE_ID}")
    rosters = _validate_array(sleeper.get_json(f"{API_BASE}/league/{LEAGUE_ID}/rosters"), "league rosters")
    users = _validate_array(sleeper.get_json(f"{API_BASE}/league/{LEAGUE_ID}/users"), "league users")
    rows = _validate_array(
        sleeper.get_json(f"{STATS_BASE}/clubsoccer:epl/{season}?season_type=regular"),
        "current season stats",
    )
    if not isinstance(league, Mapping):
        raise SleeperDataError("Sleeper league settings did not return an object")
    scoring = league.get("scoring_settings")
    if not isinstance(scoring, Mapping) or not scoring:
        raise SleeperDataError("Sleeper league custom scoring settings are unavailable")
    slots = _starting_slots(league)
    signals = [
        _player_from_row(str(row.get("player_id")), row, scoring)
        for row in rows
        if str(row.get("player_id") or "").strip()
    ]
    signals = [
        player for player in signals
        if player.get("club") in ACTIVE_EPL_CLUBS and player.get("name") not in EXCLUDED_NAMES
    ]
    extended = [dict(player) for player in signals]
    apply_fixture_adjusted_projections(signals, schedule=fixture_schedule, now=current_time, horizon=ROTATION_HORIZON)
    apply_fixture_adjusted_projections(extended, schedule=fixture_schedule, now=current_time, horizon=8)
    by_id = {str(player["player_id"]): player for player in signals}
    extended_by_id = {str(player["player_id"]): player for player in extended}
    owner_roster = next((item for item in rosters if str(item.get("owner_id")) == str(manager_id)), None)
    if owner_roster is None:
        raise SleeperDataError("Your current Sleeper roster could not be found")
    owner_ids = [str(player_id) for player_id in owner_roster.get("players") or []]
    owner_players = [by_id[player_id] for player_id in owner_ids if player_id in by_id]
    protected, protected_rows = _protected_players(owner_players, slots)
    owned_ids = {str(player_id) for roster in rosters for player_id in roster.get("players") or []}
    available_players = [player for player in signals if str(player["player_id"]) not in owned_ids]
    available = _available_options(
        owner_players, available_players, slots, protected, extended_by_id
    )
    teams = []
    for roster in rosters:
        player_ids = [str(player_id) for player_id in roster.get("players") or []]
        teams.append({
            "name": _team_name(users, roster.get("owner_id"), roster.get("roster_id")),
            "roster_id": roster.get("roster_id"),
            "owner_id": str(roster.get("owner_id") or ""),
            "players": [by_id[player_id] for player_id in player_ids if player_id in by_id],
            "remaining_faab": _remaining_faab(roster, league),
        })
    owner_team = next(team for team in teams if team["owner_id"] == str(manager_id))
    trades = build_trade_options(
        owner_team=owner_team,
        partner_teams=(team for team in teams if team["owner_id"] != str(manager_id)),
        starting_slots=slots,
        protected_player_ids=protected,
        limit=5,
    )
    for trade in trades:
        trade["kind"] = "trade"
        for player in trade["you_receive"]:
            player["exit_plan"] = _exit_plan(
                player, extended_by_id.get(str(player.get("player_id")), {})
            )
    difficult_holds = [
        player for player in protected_rows
        if float(player.get("fixture_difficulty") or 3.0) >= DIFFICULT_FIXTURE_THRESHOLD
    ]
    moves = _mix_moves(available, trades)
    timestamp = retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = {
        "source": "live Sleeper EPL plus persisted Premier League fixture calendar",
        "report": "read-only four-fixture rotation analysis",
        "season": season,
        "gameweek": gameweek,
        "retrieved_at": timestamp,
        "fixture_horizon": ROTATION_HORIZON,
        "core_policy": (
            "Protected players are the union of the best current XI, best projected four-fixture XI, "
            "and medical holds. They are excluded from all outgoing rotation moves."
        ),
        "protected_players": protected_rows,
        "difficult_core_holds": difficult_holds,
        "rotation_eligible_players": [
            {key: player.get(key) for key in (
                "player_id", "name", "club", "positions", "minutes",
                "projected_horizon_points", "forecast_fixture_difficulty", "forecast_next_fixtures",
            )}
            for player in owner_players if str(player["player_id"]) not in protected
        ],
        "recommended_moves": moves,
        "limitations": {
            "read_only": True,
            "max_moves": 5,
            "minimum_projected_lineup_gain": MIN_PROJECTED_LINEUP_GAIN,
            "availability": "Sleeper public data cannot distinguish an immediate Add from waivers.",
            "transactions": "No Sleeper add, waiver, drop, or trade was made or simulated.",
        },
    }
    return RotationContext(season, gameweek, timestamp, payload)
