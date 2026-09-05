"""Read-only, current Sleeper stat lookups for saved watchlist players."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Literal, Mapping

from .sleeper import API_BASE, STATS_BASE, SleeperClient, SleeperDataError
from .watchlist import WatchlistPlayer


TREND_WINDOW_SIZE = 3
TrendDirection = Literal["up", "down", "flat"]


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
    points_per_minute: float | None = None
    points_per_game: float | None = None
    minutes_per_game: float | None = None
    points_per_minute_trend: TrendDirection | None = None
    points_per_game_trend: TrendDirection | None = None
    minutes_per_game_trend: TrendDirection | None = None


@dataclass(frozen=True)
class WatchlistStatsReport:
    """A single current Sleeper snapshot covering all saved watchlist entries."""

    season: str
    week: int | None
    retrieved_at: str
    entries: tuple[WatchlistStat, ...]
    trend_weeks: tuple[tuple[int, ...], tuple[int, ...]] | None = None
    trend_unavailable_reason: str | None = None


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


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _rows_by_player(rows: Iterable[object]) -> dict[str, Mapping[str, Any]]:
    return {
        str(row.get("player_id")): row
        for row in rows
        if isinstance(row, Mapping) and str(row.get("player_id") or "").strip()
    }


def _window_ratio(
    player_id: str,
    weekly_rows: Iterable[object],
    *,
    numerator_key: str,
    denominator_key: str,
) -> float | None:
    numerator = 0.0
    denominator = 0.0
    for rows in weekly_rows:
        if not isinstance(rows, list):
            return None
        row = _rows_by_player(rows).get(player_id)
        if row is None:
            continue
        stats = row.get("stats")
        if not isinstance(stats, Mapping):
            continue
        week_denominator = _number(stats, denominator_key)
        if week_denominator is None or week_denominator <= 0:
            continue
        week_numerator = _number(stats, numerator_key)
        if week_numerator is None:
            return None
        numerator += week_numerator
        denominator += week_denominator
    return _ratio(numerator, denominator)


def _trend(
    previous: float | None,
    recent: float | None,
    *,
    precision: int,
) -> TrendDirection | None:
    if previous is None or recent is None:
        return None
    previous_display = round(previous, precision)
    recent_display = round(recent, precision)
    if recent_display > previous_display:
        return "up"
    if recent_display < previous_display:
        return "down"
    return "flat"


def _player_stat(
    player: WatchlistPlayer,
    row: object,
    *,
    previous_rows: Iterable[object] = (),
    recent_rows: Iterable[object] = (),
) -> WatchlistStat:
    if not isinstance(row, Mapping):
        return WatchlistStat(player, None, None, None, None, None, None, None, None, None, None, False)
    stats = row.get("stats")
    stats = stats if isinstance(stats, Mapping) else {}
    metadata = row.get("player")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    injury_status = str(metadata.get("injury_status") or "").strip().upper() or None
    points = _number(stats, "pts_std")
    games = _number(stats, "gp")
    minutes = _number(stats, "min")
    previous_rows = tuple(previous_rows)
    recent_rows = tuple(recent_rows)
    previous_points_per_minute = _window_ratio(
        player.player_id, previous_rows, numerator_key="pts_std", denominator_key="min"
    )
    recent_points_per_minute = _window_ratio(
        player.player_id, recent_rows, numerator_key="pts_std", denominator_key="min"
    )
    previous_points_per_game = _window_ratio(
        player.player_id, previous_rows, numerator_key="pts_std", denominator_key="gp"
    )
    recent_points_per_game = _window_ratio(
        player.player_id, recent_rows, numerator_key="pts_std", denominator_key="gp"
    )
    previous_minutes_per_game = _window_ratio(
        player.player_id, previous_rows, numerator_key="min", denominator_key="gp"
    )
    recent_minutes_per_game = _window_ratio(
        player.player_id, recent_rows, numerator_key="min", denominator_key="gp"
    )
    return WatchlistStat(
        player=player,
        points=points,
        games=games,
        starts=_number(stats, "gs"),
        minutes=minutes,
        goals=_number(stats, "g"),
        assists=_number(stats, "a"),
        clean_sheets=_number(stats, "cs"),
        saves=_number(stats, "sv"),
        injury_status=injury_status,
        updated_at=_timestamp(row.get("updated_at") or row.get("last_modified")),
        found=True,
        points_per_minute=_ratio(points, minutes),
        points_per_game=_ratio(points, games),
        minutes_per_game=_ratio(minutes, games),
        points_per_minute_trend=_trend(
            previous_points_per_minute, recent_points_per_minute, precision=2
        ),
        points_per_game_trend=_trend(previous_points_per_game, recent_points_per_game, precision=1),
        minutes_per_game_trend=_trend(previous_minutes_per_game, recent_minutes_per_game, precision=1),
    )


def load_current_watchlist_stats(
    watched: Iterable[WatchlistPlayer],
    *,
    client: SleeperClient | None = None,
    retrieved_at: str | None = None,
    include_trends: bool = False,
) -> WatchlistStatsReport:
    """Fetch the current Sleeper season once and return stats for saved IDs.

    The local watchlist remains the durable source of player IDs. Sleeper is
    consulted only for the requested current-stat snapshot, never to rebuild
    or alter the watchlist.
    """

    sleeper = client or SleeperClient()
    state = sleeper.get_json(f"{API_BASE}/state/clubsoccer:epl")
    season, _ = _current_season(state)
    rows = sleeper.get_json(f"{STATS_BASE}/clubsoccer:epl/{season}?season_type=regular")
    _, display_week = _current_season(state)
    trend_weeks: tuple[tuple[int, ...], tuple[int, ...]] | None = None
    weekly_rows: dict[int, object] | None = None
    trend_unavailable_reason: str | None = None
    if include_trends:
        last_completed_week = (display_week - 1) if display_week is not None else 0
        if last_completed_week < TREND_WINDOW_SIZE * 2:
            trend_unavailable_reason = "Trend needs six completed gameweeks."
        else:
            recent_weeks = tuple(
                range(last_completed_week - TREND_WINDOW_SIZE + 1, last_completed_week + 1)
            )
            previous_weeks = tuple(
                range(
                    last_completed_week - (TREND_WINDOW_SIZE * 2) + 1,
                    last_completed_week - TREND_WINDOW_SIZE + 1,
                )
            )
            try:
                weekly_rows = {}
                for week in (*previous_weeks, *recent_weeks):
                    week_rows = sleeper.get_json(
                        f"{STATS_BASE}/clubsoccer:epl/{season}/{week}?season_type=regular"
                    )
                    if not isinstance(week_rows, list):
                        raise SleeperDataError("Sleeper gameweek stats did not return an array")
                    weekly_rows[week] = week_rows
                trend_weeks = previous_weeks, recent_weeks
            except SleeperDataError:
                weekly_rows = None
                trend_unavailable_reason = "Sleeper weekly trend history is temporarily unavailable."
    return build_watchlist_stats_report(
        watched,
        state=state,
        rows=rows,
        retrieved_at=retrieved_at,
        weekly_rows=weekly_rows,
        trend_weeks=trend_weeks,
        trend_unavailable_reason=trend_unavailable_reason,
    )


def build_watchlist_stats_report(
    watched: Iterable[WatchlistPlayer],
    *,
    state: object,
    rows: object,
    retrieved_at: str | None = None,
    weekly_rows: Mapping[int, object] | None = None,
    trend_weeks: tuple[tuple[int, ...], tuple[int, ...]] | None = None,
    trend_unavailable_reason: str | None = None,
) -> WatchlistStatsReport:
    """Build a watchlist report from already-fetched current Sleeper payloads."""

    entries = tuple(watched)
    season, week = _current_season(state)
    if not isinstance(rows, list):
        raise SleeperDataError("Sleeper current EPL stats did not return an array")
    by_id = _rows_by_player(rows)
    previous_rows: tuple[object, ...] = ()
    recent_rows: tuple[object, ...] = ()
    if trend_weeks is not None and weekly_rows is not None:
        previous_weeks, recent_weeks = trend_weeks
        previous_rows = tuple(weekly_rows.get(item) for item in previous_weeks)
        recent_rows = tuple(weekly_rows.get(item) for item in recent_weeks)
    timestamp = retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    return WatchlistStatsReport(
        season=season,
        week=week,
        retrieved_at=timestamp,
        entries=tuple(
            _player_stat(
                player,
                by_id.get(player.player_id),
                previous_rows=previous_rows,
                recent_rows=recent_rows,
            )
            for player in entries
        ),
        trend_weeks=trend_weeks,
        trend_unavailable_reason=trend_unavailable_reason,
    )
