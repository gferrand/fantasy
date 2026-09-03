"""Read-only, current Sleeper stat lookups for saved watchlist players."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .sleeper import API_BASE, STATS_BASE, SleeperClient, SleeperDataError
from .watchlist import WatchlistPlayer


@dataclass(frozen=True)
class WatchlistStat:
    """The current regular-season Sleeper row for one saved watchlist player."""

    player: WatchlistPlayer
    points: float | None
    games: float | None
    starts: float | None
    minutes: float | None
    goals: float | None
    assists: float | None
    clean_sheets: float | None
    saves: float | None
    injury_status: str | None
    updated_at: str | None
    found: bool


@dataclass(frozen=True)
class WatchlistStatsReport:
    """A single current Sleeper snapshot covering all saved watchlist entries."""

    season: str
    week: int | None
    retrieved_at: str
    entries: tuple[WatchlistStat, ...]


def _number(mapping: Mapping[str, Any], key: str) -> float | None:
    try:
        return float(mapping[key])
    except (KeyError, TypeError, ValueError):
        return None


def _timestamp(value: object) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return None


def _current_season(state: object) -> tuple[str, int | None]:
    if not isinstance(state, Mapping):
        raise SleeperDataError("Sleeper EPL state did not return an object")
    season = str(state.get("season") or "").strip()
    if not season.isdigit() or len(season) != 4:
        raise SleeperDataError("Sleeper EPL state did not include a current season")
    try:
        week = int(state["display_week"])
    except (KeyError, TypeError, ValueError):
        week = None
    return season, week


def _player_stat(player: WatchlistPlayer, row: object) -> WatchlistStat:
    if not isinstance(row, Mapping):
        return WatchlistStat(player, None, None, None, None, None, None, None, None, None, None, False)
    stats = row.get("stats")
    stats = stats if isinstance(stats, Mapping) else {}
    metadata = row.get("player")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    injury_status = str(metadata.get("injury_status") or "").strip().upper() or None
    return WatchlistStat(
        player=player,
        points=_number(stats, "pts_std"),
        games=_number(stats, "gp"),
        starts=_number(stats, "gs"),
        minutes=_number(stats, "min"),
        goals=_number(stats, "g"),
        assists=_number(stats, "a"),
        clean_sheets=_number(stats, "cs"),
        saves=_number(stats, "sv"),
        injury_status=injury_status,
        updated_at=_timestamp(row.get("updated_at") or row.get("last_modified")),
        found=True,
    )


def load_current_watchlist_stats(
    watched: Iterable[WatchlistPlayer],
    *,
    client: SleeperClient | None = None,
    retrieved_at: str | None = None,
) -> WatchlistStatsReport:
    """Fetch the current Sleeper season once and return stats for saved IDs.

    The local watchlist remains the durable source of player IDs. Sleeper is
    consulted only for the requested current-stat snapshot, never to rebuild
    or alter the watchlist.
    """

    entries = tuple(watched)
    sleeper = client or SleeperClient()
    season, week = _current_season(sleeper.get_json(f"{API_BASE}/state/clubsoccer:epl"))
    rows = sleeper.get_json(f"{STATS_BASE}/clubsoccer:epl/{season}?season_type=regular")
    if not isinstance(rows, list):
        raise SleeperDataError("Sleeper current EPL stats did not return an array")
    by_id = {
        str(row.get("player_id")): row
        for row in rows
        if isinstance(row, Mapping) and str(row.get("player_id") or "").strip()
    }
    timestamp = retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    return WatchlistStatsReport(
        season=season,
        week=week,
        retrieved_at=timestamp,
        entries=tuple(_player_stat(player, by_id.get(player.player_id)) for player in entries),
    )
