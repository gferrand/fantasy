"""Bounded, deterministic private evidence for one named-player evaluation."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import time
from typing import Any, Mapping
from urllib.error import HTTPError

from .automation import AppConfig, EXPECTED_LEAGUE_ID, EXPECTED_MANAGER_ID, player_catalog_file
from .player_catalog import PlayerCatalogError, normalize_player_text, read_player_catalog
from .sleeper import API_BASE, STATS_BASE, SleeperClient, SleeperDataError, custom_points_by_position
from .watchlist import WatchlistPlayer
from .watchlist_stats import build_player_stat_profile


LOGGER = logging.getLogger(__name__)


def _source(name: str, timestamp: str | None, *, stale: bool) -> dict[str, Any]:
    return {"source": name, "retrieved_at": timestamp, "stale": stale}


def _limitation(kind: str, field: str, detail: str) -> dict[str, str]:
    return {"kind": kind, "field": field, "detail": detail}


def _http_status(error: BaseException) -> int | None:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, HTTPError):
            return current.code
        current = current.__cause__
    return None


def _failure_kind(error: BaseException) -> str:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, TimeoutError):
            return "timeout"
        current = current.__cause__
    return "sleeper_source"


def _log(*, source: str, success: bool, elapsed: float, failure: str | None = None, status: int | None = None) -> None:
    LOGGER.info(
        "private_retrieval type=player_evaluation source=%s success=%s elapsed_ms=%d http_status=%s failure=%s",
        source, success, round(elapsed * 1000), status if status is not None else "-", failure or "-",
    )


def _team_names(users: list[Mapping[str, Any]]) -> dict[str, str]:
    names: dict[str, str] = {}
    for user in users:
        metadata = user.get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        owner_id = str(user.get("user_id") or "")
        name = str(metadata.get("team_name") or user.get("display_name") or "").strip()
        if owner_id and name:
            names[owner_id] = name
    return names


def _metadata(row: Mapping[str, Any] | None, catalog: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    live = row.get("player") if isinstance(row, Mapping) else None
    live = live if isinstance(live, Mapping) else {}
    positions = [str(value).upper() for value in (live.get("fantasy_positions") or []) if str(value).strip()]
    from_catalog = not positions
    if not positions:
        positions = [str(value).upper() for value in (catalog.get("positions") or []) if str(value).strip()]
    player_id = str(catalog.get("player_id") or (row.get("player_id") if isinstance(row, Mapping) else "")).strip()
    return {
        "player_id": player_id,
        "name": str(live.get("full_name") or catalog.get("name") or "").strip(),
        "positions": positions,
        "club": str(live.get("team_abbr") or catalog.get("club") or "").upper() or None,
        "active": live.get("active") if "active" in live else catalog.get("active"),
        "status": str(live.get("status") or catalog.get("status") or "").upper() or None,
        "injury_status": str(live.get("injury_status") or "").upper() or None,
        "eligibility_source": "stale_catalog" if from_catalog else "current_sleeper_stats",
    }, from_catalog


def _profile(metadata: Mapping[str, Any], row: Mapping[str, Any] | None, scoring: Mapping[str, Any]) -> dict[str, Any]:
    player = WatchlistPlayer(
        player_id=str(metadata["player_id"]), name=str(metadata["name"]),
        club=str(metadata.get("club") or ""), positions=tuple(metadata.get("positions") or ()), added_at="",
    )
    stat = build_player_stat_profile(player, row)
    stats = row.get("stats") if isinstance(row, Mapping) and isinstance(row.get("stats"), Mapping) else {}
    points = custom_points_by_position(stats, scoring, metadata.get("positions") or ())
    games = stat.games
    minutes = stat.minutes
    return {
        "sleeper_standard": {
            "pts_std": stat.points,
            "gp": games,
            "gs": stat.starts,
            "minutes": minutes,
            "goals": stat.goals,
            "assists": stat.assists,
            "clean_sheets": stat.clean_sheets,
            "saves": stat.saves,
            "points_per_game": stat.points_per_game,
            "points_per_minute": stat.points_per_minute,
            "minutes_per_game": stat.minutes_per_game,
        },
        "kick_and_run": {
            "points_by_position": points,
            "points_per_game_by_position": {
                position: round(value / games, 3) for position, value in points.items() if games and games > 0
            },
            "points_per_minute_by_position": {
                position: round(value / minutes, 4) for position, value in points.items() if minutes and minutes > 0
            },
        },
    }


def _safe_profile(
    metadata: Mapping[str, Any], row: Mapping[str, Any] | None, scoring: Mapping[str, Any],
    limitations: list[dict[str, str]],
) -> dict[str, Any]:
    try:
        return _profile(metadata, row, scoring)
    except Exception:
        _log(source="player_evaluation_profile", success=False, elapsed=0, failure="retrieval_system")
        limitations.append(_limitation("temporarily_unavailable", "player_profile", "Current player data could not be processed."))
        return {"sleeper_standard": {}, "kick_and_run": {"points_by_position": {}, "points_per_game_by_position": {}, "points_per_minute_by_position": {}}}


def get_player_evaluation_context(
    config: AppConfig, player_name: str, *, timeout: float, client: SleeperClient | None = None,
) -> dict[str, Any]:
    """Return up to six direct reads for one player; never invokes Codex or writes."""

    started = time.monotonic()
    sources: list[dict[str, Any]] = []
    limitations: list[dict[str, str]] = []
    sleeper = client or SleeperClient(timeout=min(8.0, max(1.0, timeout)), retries=1)

    def fetch(source: str, url: str, field: str, expected_type: type) -> object | None:
        began = time.monotonic()
        try:
            value = sleeper.get_json(url)
        except SleeperDataError as exc:
            _log(source=source, success=False, elapsed=time.monotonic() - began,
                 status=_http_status(exc), failure=_failure_kind(exc))
            limitations.append(_limitation("temporarily_unavailable", field, "Current league data could not be accessed."))
            return None
        if not isinstance(value, expected_type):
            _log(source=source, success=False, elapsed=time.monotonic() - began, failure="validation")
            limitations.append(_limitation("temporarily_unavailable", field, "Current league data could not be processed."))
            return None
        _log(source=source, success=True, elapsed=time.monotonic() - began)
        sources.append(_source(source, datetime.now(timezone.utc).isoformat(), stale=False))
        return value

    league = fetch("Sleeper league settings", f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}", "league_settings", Mapping)
    users = fetch("Sleeper league users", f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}/users", "league_users", list)
    rosters = fetch("Sleeper league rosters", f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}/rosters", "league_rosters", list)
    state = fetch("Sleeper EPL state", f"{API_BASE}/state/clubsoccer:epl", "epl_state", Mapping)
    season = str(state.get("season") or "") if isinstance(state, Mapping) else ""
    stats = fetch(
        "Sleeper current-season EPL stats", f"{STATS_BASE}/clubsoccer:epl/{season}?season_type=regular", "current_stats", list,
    ) if season.isdigit() else None
    if state is not None and not season.isdigit():
        limitations.append(_limitation("temporarily_unavailable", "epl_state", "Current league data could not be processed."))
        _log(source="Sleeper EPL state", success=False, elapsed=0, failure="validation")

    owner_ids = ()
    if isinstance(rosters, list):
        owner = next((row for row in rosters if isinstance(row, Mapping) and str(row.get("owner_id")) == EXPECTED_MANAGER_ID), None)
        owner_ids = tuple(str(value) for value in (owner.get("players") or [])) if isinstance(owner, Mapping) else ()
    catalog_started = time.monotonic()
    try:
        refreshed_at, catalog_rows = read_player_catalog(
            player_catalog_file(config), names=(player_name,), player_ids=owner_ids,
        )
        sources.append(_source("Local player catalog", refreshed_at or None, stale=True))
        _log(source="local_player_catalog", success=True, elapsed=time.monotonic() - catalog_started)
    except (OSError, PlayerCatalogError):
        limitations.append(_limitation("temporarily_unavailable", "player_identity", "Player identity data could not be accessed."))
        _log(source="local_player_catalog", success=False, elapsed=time.monotonic() - catalog_started, failure="local_data")
        return {"status": "partial", "data": {}, "limitations": limitations, "sources": sources}

    requested = normalize_player_text(player_name)
    matches = [row for row in catalog_rows if normalize_player_text(row["name"]) == requested and "epl" in {str(x).casefold() for x in row.get("competitions") or []}]
    if len(matches) != 1:
        detail = "The requested player could not be uniquely resolved." if matches else "The requested player was not found in the current catalog."
        limitations.append(_limitation("not_found", "player", detail))
        return {"status": "partial", "data": {}, "limitations": limitations, "sources": sources}
    target_catalog = matches[0]
    catalog_by_id = {str(row["player_id"]): row for row in catalog_rows}
    rows = stats if isinstance(stats, list) else []
    stats_by_id = {str(row.get("player_id")): row for row in rows if isinstance(row, Mapping) and str(row.get("player_id") or "")}
    target_row = stats_by_id.get(str(target_catalog["player_id"]))
    target, target_uses_stale_eligibility = _metadata(target_row, target_catalog)
    if target_uses_stale_eligibility:
        limitations.append(_limitation("temporarily_unavailable", "eligibility", "Current player eligibility could not be confirmed."))

    scoring = league.get("scoring_settings") if isinstance(league, Mapping) and isinstance(league.get("scoring_settings"), Mapping) else {}
    if league is not None and not scoring:
        limitations.append(_limitation("temporarily_unavailable", "scoring", "Current league scoring could not be processed."))
    roster_rows = [row for row in rosters if isinstance(row, Mapping)] if isinstance(rosters, list) else []
    user_rows = [row for row in users if isinstance(row, Mapping)] if isinstance(users, list) else []
    names = _team_names(user_rows)
    owner = next((row for row in roster_rows if str(row.get("owner_id")) == EXPECTED_MANAGER_ID), None)
    if owner is None and rosters is not None:
        limitations.append(_limitation("temporarily_unavailable", "los_blancos", "Current league roster data could not be processed."))
    target_owner = next((row for row in roster_rows if str(target["player_id"]) in {str(value) for value in (row.get("players") or [])}), None)
    if target_owner is None:
        ownership = {"state": "unrostered_unclassified"}
    elif str(target_owner.get("owner_id")) == EXPECTED_MANAGER_ID:
        ownership = {"state": "los_blancos"}
    else:
        ownership = {"state": "rostered", "team": names.get(str(target_owner.get("owner_id")), "Unknown team")}

    roster_packet: list[dict[str, Any]] = []
    if isinstance(owner, Mapping):
        for player_id in owner.get("players") or []:
            catalog = catalog_by_id.get(str(player_id), {"player_id": str(player_id), "name": f"Unknown player {player_id}", "positions": [], "club": "", "active": None, "status": ""})
            metadata, _ = _metadata(stats_by_id.get(str(player_id)), catalog)
            roster_packet.append({**metadata, **_safe_profile(metadata, stats_by_id.get(str(player_id)), scoring, limitations)})

    data = {"player_evaluation": {
        "target": {**target, **_safe_profile(target, target_row, scoring, limitations)},
        "ownership": ownership,
        "season": season or None,
        "roster_position_rules": list(league.get("roster_positions") or []) if isinstance(league, Mapping) else [],
        "los_blancos": {"players": roster_packet},
    }}
    _log(source="player_evaluation_packet", success=True, elapsed=time.monotonic() - started)
    return {"status": "partial" if limitations else "complete", "data": data, "limitations": limitations, "sources": sources}
