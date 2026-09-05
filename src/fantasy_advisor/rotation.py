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
    _season_and_week,
    _starting_slots,
    _team_name,
    _validate_array,
    apply_fixture_adjusted_projections,
    evaluate_lineup,
)


ROTATION_HORIZON = 4
MIN_INCOMING_MINUTES = 90.0
MIN_INCOMING_STARTS = 1.0
MIN_EXPECTED_MINUTES = 60.0
MAX_TARGET_FIXTURE_DIFFICULTY = 3.0
DIFFICULT_FIXTURE_THRESHOLD = 3.1
KNOWN_NON_EPL_TRANSFERS = {
    "Mohamed Salah": "Trabzonspor",
    "Leandro Trossard": "Beşiktaş",
    "Guglielmo Vicario": "Juventus (loan for 2026/27)",
}
EXCLUDED_NAMES = set(KNOWN_NON_EPL_TRANSFERS)
MEDICAL_HOLD_STATUSES = INACTIVE_INJURY_STATUSES | {"GTD", "QUESTIONABLE", "Q"}


@dataclass(frozen=True)
class RotationContext:
    season: str
    gameweek: int
    retrieved_at: str
    payload: dict[str, Any]

    def as_json(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False, separators=(",", ":"))


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


def _has_reliable_role(player: Mapping[str, Any]) -> bool:
    """Require enough current evidence to make a player worth researching."""

    return (
        float(player.get("minutes") or 0.0) >= MIN_INCOMING_MINUTES
        and float(player.get("starts") or 0.0) >= MIN_INCOMING_STARTS
        and float(player.get("forecast_expected_minutes_per_fixture") or 0.0)
        >= MIN_EXPECTED_MINUTES
    )


def _target_summary(
    player: Mapping[str, Any], *, extended: Mapping[str, Any], owner: str | None = None
) -> dict[str, Any]:
    summary = {
        key: player.get(key)
        for key in (
            "player_id", "name", "club", "positions", "injury_status", "minutes", "starts",
            "custom_points_per_90", "projected_horizon_points",
            "forecast_expected_minutes_per_fixture", "forecast_fixture_difficulty",
            "forecast_next_fixtures",
        )
    }
    summary["fixture_quality"] = (
        "favorable"
        if float(player.get("forecast_fixture_difficulty") or 5.0)
        <= MAX_TARGET_FIXTURE_DIFFICULTY
        else "mixed_or_difficult"
    )
    summary["exit_plan"] = _exit_plan(player, extended)
    if owner is not None:
        summary["current_fantasy_team"] = owner
    return summary


def _rank_targets(
    players: Iterable[Mapping[str, Any]],
    *,
    extended_by_id: Mapping[str, Mapping[str, Any]],
    owners: Mapping[str, str] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Rank independent acquisition targets without forcing an outgoing player."""

    eligible = [player for player in players if _has_reliable_role(player)]
    ranked = sorted(
        eligible,
        key=lambda player: (
            float(player.get("forecast_fixture_difficulty") or 5.0)
            <= MAX_TARGET_FIXTURE_DIFFICULTY,
            float(player.get("projected_horizon_points") or 0.0),
            -float(player.get("forecast_fixture_difficulty") or 5.0),
            float(player.get("minutes") or 0.0),
        ),
        reverse=True,
    )
    selected: list[Mapping[str, Any]] = []
    represented_positions: set[str] = set()
    for player in ranked:
        positions = {str(position).upper() for position in player.get("positions") or []}
        if positions - represented_positions:
            selected.append(player)
            represented_positions.update(positions)
        if len(selected) == limit:
            break
    selected_ids = {str(player.get("player_id")) for player in selected}
    selected.extend(
        player
        for player in ranked
        if str(player.get("player_id")) not in selected_ids
    )
    return [
        _target_summary(
            player,
            extended=extended_by_id.get(str(player.get("player_id")), {}),
            owner=(owners or {}).get(str(player.get("player_id"))),
        )
        for player in selected[:limit]
    ]


def _rank_drop_candidates(
    owner_players: Iterable[Mapping[str, Any]], protected: set[str], *, limit: int = 5
) -> list[dict[str, Any]]:
    """Rank non-core roster spots independently from acquisition targets."""

    eligible = [
        player
        for player in owner_players
        if str(player.get("player_id")) not in protected
    ]
    ranked = sorted(
        eligible,
        key=lambda player: (
            float(player.get("projected_horizon_points") or 0.0),
            float(player.get("forecast_expected_minutes_per_fixture") or 0.0),
            -float(player.get("forecast_fixture_difficulty") or 3.0),
        ),
    )
    return [
        {
            key: player.get(key)
            for key in (
                "player_id", "name", "club", "positions", "injury_status", "minutes", "starts",
                "projected_horizon_points", "forecast_expected_minutes_per_fixture",
                "forecast_fixture_difficulty", "forecast_next_fixtures",
            )
        }
        for player in ranked[:limit]
    ]


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
    teams = []
    for roster in rosters:
        player_ids = [str(player_id) for player_id in roster.get("players") or []]
        teams.append({
            "name": _team_name(users, roster.get("owner_id"), roster.get("roster_id")),
            "roster_id": roster.get("roster_id"),
            "owner_id": str(roster.get("owner_id") or ""),
            "players": [by_id[player_id] for player_id in player_ids if player_id in by_id],
        })
    partner_players = [
        player
        for team in teams
        if team["owner_id"] != str(manager_id)
        for player in team["players"]
    ]
    partner_owners = {
        str(player["player_id"]): team["name"]
        for team in teams
        if team["owner_id"] != str(manager_id)
        for player in team["players"]
    }
    pickup_targets = _rank_targets(
        available_players, extended_by_id=extended_by_id, limit=5
    )
    trade_targets = _rank_targets(
        partner_players,
        extended_by_id=extended_by_id,
        owners=partner_owners,
        limit=5,
    )
    drop_candidates = _rank_drop_candidates(owner_players, protected, limit=5)
    difficult_holds = [
        player for player in protected_rows
        if float(player.get("fixture_difficulty") or 3.0) >= DIFFICULT_FIXTURE_THRESHOLD
    ]
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
        "known_non_epl_transfers": KNOWN_NON_EPL_TRANSFERS,
        "protected_players": protected_rows,
        "difficult_core_holds": difficult_holds,
        "rotation_eligible_players": [
            {key: player.get(key) for key in (
                "player_id", "name", "club", "positions", "minutes",
                "projected_horizon_points", "forecast_fixture_difficulty", "forecast_next_fixtures",
            )}
            for player in owner_players if str(player["player_id"]) not in protected
        ],
        "pickup_targets": pickup_targets,
        "trade_targets": trade_targets,
        "drop_candidates": drop_candidates,
        "limitations": {
            "read_only": True,
            "max_options_per_list": 5,
            "independent_lists": (
                "Acquisition targets and non-core drop candidates are ranked separately; "
                "the report must not force one-to-one pairings."
            ),
            "incoming_role_gate": (
                f"At least {MIN_INCOMING_STARTS:.0f} start, {MIN_INCOMING_MINUTES:.0f} current minutes, "
                f"and {MIN_EXPECTED_MINUTES:.0f} expected minutes per fixture."
            ),
            "fixture_priority": (
                f"Targets at or below {MAX_TARGET_FIXTURE_DIFFICULTY:.1f} difficulty rank first; "
                "mixed runs remain visible as clearly labeled alternatives."
            ),
            "availability": "Sleeper public data cannot distinguish an immediate Add from waivers.",
            "transactions": "No Sleeper add, waiver, drop, or trade was made or simulated.",
        },
    }
    return RotationContext(season, gameweek, timestamp, payload)
