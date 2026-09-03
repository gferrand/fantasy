"""Live, read-only roster comparisons for saved watchlist players."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Iterable, Mapping

from .sleeper import API_BASE, STATS_BASE, SleeperClient, SleeperDataError, roster_swap_recommendations
from .watchlist import WatchlistPlayer
from .watchlist_stats import WatchlistStatsReport, build_watchlist_stats_report


@dataclass(frozen=True)
class WatchlistRecommendationContext:
    """Current Sleeper context supplied to the web-backed recommendation model."""

    stats_report: WatchlistStatsReport
    roster_players: tuple[dict[str, Any], ...]
    swap_signals: tuple[dict[str, Any], ...]
    scoring_available: bool


def watchlist_outlook_context(report: WatchlistStatsReport) -> str:
    """Serialize only the current saved-player data needed for web research."""

    players = []
    for entry in report.entries:
        players.append(
            {
                "player_id": entry.player.player_id,
                "name": entry.player.name,
                "club": entry.player.club or None,
                "positions": entry.player.positions,
                "sleeper_current_season": {
                    "found": entry.found,
                    "points": entry.points,
                    "games": entry.games,
                    "starts": entry.starts,
                    "minutes": entry.minutes,
                    "goals": entry.goals,
                    "assists": entry.assists,
                    "clean_sheets": entry.clean_sheets,
                    "saves": entry.saves,
                    "injury_status": entry.injury_status,
                    "updated_at": entry.updated_at,
                },
            }
        )
    return json.dumps(
        {
            "source": "live Sleeper watchlist stats",
            "season": report.season,
            "gameweek": report.week,
            "retrieved_at": report.retrieved_at,
            "watched_players": players,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def watchlist_recommendation_context(context: WatchlistRecommendationContext) -> str:
    """Serialize the bounded current roster comparison for web qualification."""

    return json.dumps(
        {
            "watchlist": json.loads(watchlist_outlook_context(context.stats_report)),
            "your_current_roster": context.roster_players,
            "same_position_current_scoring_signals": context.swap_signals,
            "scoring_settings_available": context.scoring_available,
            "instruction": "These are read-only signals, not executed Sleeper moves.",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _number(stats: Mapping[str, Any], key: str) -> float | None:
    try:
        return float(stats[key])
    except (KeyError, TypeError, ValueError):
        return None


def _name(player_id: str, player: Mapping[str, Any]) -> str:
    metadata = player.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    return str(
        player.get("full_name")
        or metadata.get("full_name")
        or " ".join(str(value) for value in (player.get("first_name"), player.get("last_name")) if value)
        or f"Unknown player {player_id}"
    )


def _position_score(stats: Mapping[str, Any], scoring: Mapping[str, Any], position: str) -> float | None:
    prefix = f"pos_{position.casefold()}_"
    total = 0.0
    found = False
    for key, raw_value in stats.items():
        if not key.startswith(prefix) or key not in scoring:
            continue
        try:
            total += float(raw_value) * float(scoring[key])
        except (TypeError, ValueError):
            continue
        found = True
    return round(total, 2) if found else None


def _candidate_rows(
    watched: Iterable[WatchlistPlayer],
    rows_by_id: Mapping[str, Mapping[str, Any]],
    scoring: Mapping[str, Any],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for watched_player in watched:
        row = rows_by_id.get(watched_player.player_id, {})
        stats = row.get("stats") if isinstance(row, Mapping) else {}
        stats = stats if isinstance(stats, Mapping) else {}
        positions = [str(position).upper() for position in watched_player.positions]
        position_points = {
            position: score
            for position in positions
            if (score := _position_score(stats, scoring, position)) is not None
        }
        if not position_points:
            continue
        candidates.append(
            {
                "player_id": watched_player.player_id,
                "name": watched_player.name,
                "club": watched_player.club,
                "positions": positions,
                "position_points": position_points,
                "custom_points": max(position_points.values()),
                "games": _number(stats, "gp"),
                "starts": _number(stats, "gs"),
                "minutes": _number(stats, "min"),
            }
        )
    return candidates


def load_current_watchlist_recommendation_context(
    watched: Iterable[WatchlistPlayer],
    *,
    manager_id: str,
    client: SleeperClient | None = None,
    retrieved_at: str | None = None,
) -> WatchlistRecommendationContext:
    """Load a current Sleeper roster and derive same-position swap signals.

    This is strictly observational. It returns current scoring signals for the
    LLM to qualify against web-researched role, injury, and transfer context.
    """

    watched_entries = tuple(watched)
    sleeper = client or SleeperClient()
    state = sleeper.get_json(f"{API_BASE}/state/clubsoccer:epl")
    if not isinstance(state, Mapping):
        raise SleeperDataError("Sleeper EPL state did not return an object")
    season = str(state.get("season") or "").strip()
    if not season.isdigit() or len(season) != 4:
        raise SleeperDataError("Sleeper EPL state did not include a current season")
    stats_rows = sleeper.get_json(f"{STATS_BASE}/clubsoccer:epl/{season}?season_type=regular")
    league = sleeper.get_json(f"{API_BASE}/league/1378147559444348928")
    rosters = sleeper.get_json(f"{API_BASE}/league/1378147559444348928/rosters")
    if not isinstance(league, Mapping):
        raise SleeperDataError("Sleeper league settings did not return an object")
    if not isinstance(rosters, list):
        raise SleeperDataError("Sleeper league rosters did not return an array")
    report = build_watchlist_stats_report(
        watched_entries,
        state=state,
        rows=stats_rows,
        retrieved_at=retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    rows_by_id: dict[str, Mapping[str, Any]] = {}
    players: dict[str, Mapping[str, Any]] = {}
    if isinstance(stats_rows, list):
        for row in stats_rows:
            if not isinstance(row, Mapping):
                continue
            player_id = str(row.get("player_id") or "").strip()
            raw_player = row.get("player")
            if player_id and isinstance(raw_player, Mapping):
                rows_by_id[player_id] = row
                players[player_id] = raw_player
    scoring = league.get("scoring_settings")
    scoring = scoring if isinstance(scoring, Mapping) else {}
    roster = next(
        (item for item in rosters if isinstance(item, Mapping) and str(item.get("owner_id")) == str(manager_id)),
        None,
    )
    if roster is None:
        raise SleeperDataError("Your current Sleeper roster could not be found")
    roster_ids = [str(player_id) for player_id in (roster.get("players") or [])]
    roster_players = []
    for player_id in roster_ids:
        player = players.get(player_id, {})
        stats = rows_by_id.get(player_id, {}).get("stats")
        stats = stats if isinstance(stats, Mapping) else {}
        roster_players.append(
            {
                "player_id": player_id,
                "name": _name(player_id, player),
                "club": str(player.get("team_abbr") or "").upper(),
                "positions": [str(position).upper() for position in (player.get("fantasy_positions") or [])],
                "injury_status": str(player.get("injury_status") or "").upper() or None,
                "stats": {
                    key: value
                    for key in ("pts_std", "gp", "gs", "min")
                    if (value := _number(stats, key)) is not None
                },
            }
        )
    candidates = _candidate_rows(watched_entries, rows_by_id, scoring)
    swaps = roster_swap_recommendations(
        candidates,
        players,
        rosters,
        stats_rows if isinstance(stats_rows, list) else [],
        scoring,
        manager_id=manager_id,
        limit=6,
    )
    return WatchlistRecommendationContext(
        stats_report=report,
        roster_players=tuple(roster_players),
        swap_signals=tuple(swaps),
        scoring_available=bool(scoring),
    )
