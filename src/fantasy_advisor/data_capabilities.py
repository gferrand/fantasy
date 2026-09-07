"""Compact, read-only product capabilities over Fantasy authoritative data."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import time
from typing import Any, Mapping

from .automation import (
    AppConfig, EXPECTED_LEAGUE_ID, SLEEPER_EPL_PLAYERS_URL,
    load_local_player_catalog, load_registry,
)
from .deadline_guardian import active_events
from .gameweek import latest_completed_gameweek
from .player_evaluation import get_player_evaluation_context
from .sleeper import (
    API_BASE,
    STATS_BASE,
    SleeperClient,
    SleeperDataError,
    custom_points_by_position,
    pickup_candidates,
    roster_swap_recommendations,
    transactions_url,
)
from .watchlist import WatchlistError, list_watchlist


def _source(name: str) -> dict[str, Any]:
    return {"source": name, "retrieved_at": datetime.now(timezone.utc).isoformat(), "stale": False}


def _local_source(name: str) -> dict[str, Any]:
    return {"source": name, "retrieved_at": None, "stale": True}


def _current_local_source(name: str) -> dict[str, Any]:
    """A local state read is authoritative now, even though it is local."""

    return _source(name)


def _limitation(field: str, detail: str) -> dict[str, str]:
    return {"kind": "temporarily_unavailable", "field": field, "detail": detail}


class DataCapabilities:
    """Request-scoped, deadline-bounded reads; no raw provider access is exposed."""

    def __init__(self, config: AppConfig, *, timeout: float, client: SleeperClient | None = None) -> None:
        self.config = config
        self.deadline = time.monotonic() + max(0.0, timeout)
        self.client = client or SleeperClient(timeout=min(8.0, max(0.001, timeout)), retries=1)
        self.cache: dict[str, object] = {}
        # Keep provenance beside a request-cache value.  A later capability
        # must be able to prove that a cache hit originated in this request.
        self.cache_sources: dict[str, list[dict[str, Any]]] = {}
        self.cache_hits: list[str] = []
        self.sources: list[dict[str, Any]] = []
        self.limitations: list[dict[str, str]] = []
        self.operation_deadline = self.deadline

    def begin_operation(self, timeout: float) -> None:
        """Scope evidence and provider time to one named capability call."""

        self.sources = []
        self.limitations = []
        self.cache_hits = []
        self.operation_deadline = min(self.deadline, time.monotonic() + max(0.0, timeout))

    def _remaining(self) -> float:
        return self.operation_deadline - time.monotonic()

    def bounded_client(self) -> SleeperClient:
        """Return the shared client clamped to this request's remaining budget."""

        if isinstance(self.client, SleeperClient):
            return replace(
                self.client,
                timeout=min(8.0, max(0.001, self._remaining())),
                retries=1,
                deadline=self.operation_deadline,
            )
        return self.client

    def _get(self, key: str, url: str, expected: type) -> object | None:
        if key in self.cache:
            self.sources.extend(dict(source) for source in self.cache_sources.get(key, []))
            self.cache_hits.append(key)
            return self.cache[key]
        if self._remaining() <= 0:
            self.limitations.append(_limitation("packet_deadline", "Current league data could not be retrieved within this answer's time limit."))
            return None
        try:
            value = self.bounded_client().get_json(url)
        except SleeperDataError:
            self.limitations.append(_limitation(key, "Current league data could not be accessed."))
            return None
        if self._remaining() <= 0 or not isinstance(value, expected):
            self.limitations.append(_limitation(key, "Current league data could not be processed."))
            return None
        source = _source(f"Sleeper {key.replace('_', ' ')}")
        self.cache[key] = value
        self.cache_sources[key] = [source]
        self.sources.append(source)
        return value

    def _result(self, data: dict[str, Any]) -> dict[str, Any]:
        result = {
            "status": "partial" if self.limitations else "complete",
            "data": data,
            "limitations": self.limitations.copy(),
            "sources": self.sources.copy(),
        }
        # The cache is request-scoped; evidence belongs only to this operation.
        self.sources.clear()
        self.limitations.clear()
        return result

    def unavailable(self, field: str, detail: str) -> dict[str, Any]:
        self.limitations.append(_limitation(field, detail))
        return self._result({})

    def _catalog(self) -> list[dict[str, Any]]:
        cached = self.cache.get("player_catalog")
        if isinstance(cached, list):
            self.sources.extend(dict(source) for source in self.cache_sources.get("player_catalog", []))
            self.cache_hits.append("player_catalog")
            return cached
        catalog = load_local_player_catalog(self.config)
        self.cache["player_catalog"] = catalog
        source = _local_source("Fantasy player catalog")
        self.cache_sources["player_catalog"] = [source]
        self.sources.append(source)
        return catalog

    @staticmethod
    def _player_identity(player_id: str, catalog: list[dict[str, Any]]) -> dict[str, Any]:
        player = next((row for row in catalog if str(row.get("player_id") or "") == player_id), {})
        return {
            "name": player.get("name") or f"Unknown player",
            "club": player.get("club") or None,
            "positions": list(player.get("positions") or []),
        }

    def _team_names(self) -> dict[str, str]:
        cached = self.cache.get("team_names")
        if isinstance(cached, dict):
            self.sources.extend(dict(source) for source in self.cache_sources.get("team_names", []))
            self.cache_hits.append("team_names")
            return cached
        users = self._get("league_users", f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}/users", list)
        rosters = self._get("league_rosters", f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}/rosters", list)
        labels = {
            str(user.get("user_id") or ""): str(
                (user.get("metadata") or {}).get("team_name") or user.get("display_name") or "Unknown team"
            )
            for user in users or [] if isinstance(user, Mapping)
        }
        names = {
            str(roster.get("roster_id") or ""): labels.get(str(roster.get("owner_id") or ""), "Unknown team")
            for roster in rosters or [] if isinstance(roster, Mapping)
        }
        self.cache["team_names"] = names
        # The two provider packets just used are the evidence for the derived
        # team-name map as well; retain them for any later cache hit.
        self.cache_sources["team_names"] = [
            *[dict(source) for source in self.cache_sources.get("league_users", [])],
            *[dict(source) for source in self.cache_sources.get("league_rosters", [])],
        ]
        return names

    @staticmethod
    def _number(stats: Mapping[str, Any], key: str) -> float | None:
        try:
            return float(stats[key])
        except (KeyError, TypeError, ValueError):
            return None

    def _team_player_profile(
        self,
        player_id: str,
        catalog: list[dict[str, Any]],
        stats: object,
        scoring: Mapping[str, Any],
        starter: bool,
        live_player: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        identity = self._player_identity(player_id, catalog)
        if isinstance(live_player, Mapping):
            metadata = live_player.get("metadata") if isinstance(live_player.get("metadata"), Mapping) else {}
            live_name = live_player.get("full_name") or metadata.get("full_name")
            live_positions = live_player.get("fantasy_positions")
            if live_name:
                identity["name"] = str(live_name)
            if live_player.get("team_abbr"):
                identity["club"] = str(live_player["team_abbr"])
            if isinstance(live_positions, list) and live_positions:
                identity["positions"] = [str(position) for position in live_positions]
        values = stats if isinstance(stats, Mapping) else {}
        points = custom_points_by_position(values, scoring, identity["positions"])
        games = self._number(values, "gp")
        return {
            **identity,
            "starter": starter,
            "kick_and_run": {
                "points_by_position": points,
                "points_per_game_by_position": {
                    position: round(value / games, 3)
                    for position, value in points.items() if games and games > 0
                },
            },
            "starts": self._number(values, "gs"),
            "minutes": self._number(values, "min"),
        }

    def get_league_context(self) -> dict[str, Any]:
        league = self._get("league_settings", f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}", Mapping)
        state = self._get("epl_state", f"{API_BASE}/state/clubsoccer:epl", Mapping)
        data: dict[str, Any] = {}
        if isinstance(league, Mapping):
            data["league"] = {"name": league.get("name"), "season": league.get("season"), "scoring_settings": league.get("scoring_settings") if isinstance(league.get("scoring_settings"), Mapping) else {}, "roster_positions": list(league.get("roster_positions") or [])}
        if isinstance(state, Mapping):
            data["state"] = {key: state.get(key) for key in ("season", "display_week", "week", "season_type")}
        return self._result(data)

    def get_team_context(self, team_name: str) -> dict[str, Any]:
        users = self._get("league_users", f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}/users", list)
        rosters = self._get("league_rosters", f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}/rosters", list)
        requested = team_name.casefold().strip()
        owner_id = None
        label = None
        for user in users if isinstance(users, list) else []:
            if not isinstance(user, Mapping):
                continue
            metadata = user.get("metadata") if isinstance(user.get("metadata"), Mapping) else {}
            candidate = str(metadata.get("team_name") or user.get("display_name") or "").strip()
            if candidate.casefold() == requested:
                owner_id, label = str(user.get("user_id") or ""), candidate
                break
        roster = next((row for row in rosters if isinstance(row, Mapping) and str(row.get("owner_id") or "") == owner_id), None) if owner_id else None
        if roster is None:
            self.limitations.append({"kind": "not_found", "field": "team", "detail": "The requested league team could not be resolved."})
            return self._result({})
        league = self._get("league_settings", f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}", Mapping)
        state = self._get("epl_state", f"{API_BASE}/state/clubsoccer:epl", Mapping)
        season = str(state.get("season") or "") if isinstance(state, Mapping) else ""
        stats_rows = self._get(
            "season_stats",
            f"{STATS_BASE}/clubsoccer:epl/{season}?season_type=regular",
            list,
        ) if season else None
        live_players = self._get("epl_players", SLEEPER_EPL_PLAYERS_URL, Mapping)
        try:
            catalog = self._catalog()
        except Exception:
            self.limitations.append(_limitation("player_catalog", "Player identity data could not be accessed."))
            return self._result({"team": {"name": label, "players": []}})
        scoring = league.get("scoring_settings") if isinstance(league, Mapping) and isinstance(league.get("scoring_settings"), Mapping) else {}
        stats_by_id = {
            str(row.get("player_id") or ""): row.get("stats")
            for row in stats_rows or []
            if isinstance(row, Mapping) and isinstance(row.get("stats"), Mapping)
        }
        starters = {str(value) for value in (roster.get("starters") or []) if str(value) != "0"}
        players = [
            self._team_player_profile(
                str(player_id), catalog, stats_by_id.get(str(player_id), {}), scoring,
                str(player_id) in starters,
                live_players.get(str(player_id)) if isinstance(live_players, Mapping) else None,
            )
            for player_id in (roster.get("players") or [])
        ]
        return self._result({"team": {"name": label, "players": players}})

    def get_watchlist(self) -> dict[str, Any]:
        if "watchlist" in self.cache:
            self.sources.extend(dict(source) for source in self.cache_sources.get("watchlist", []))
            self.cache_hits.append("watchlist")
            return self._result({"watchlist": self.cache["watchlist"]})
        try:
            players = list_watchlist(self.config.repo_root / "data" / "automation" / "watchlist.sqlite3")
        except WatchlistError:
            self.limitations.append(_limitation("watchlist", "Saved watchlist data could not be accessed."))
            return self._result({})
        data = [{"player_id": player.player_id, "name": player.name, "club": player.club, "positions": list(player.positions), "added_at": player.added_at} for player in players]
        self.cache["watchlist"] = data
        source = _current_local_source("Fantasy watchlist")
        self.cache_sources["watchlist"] = [source]
        self.sources.append(source)
        return self._result({"watchlist": data})

    def get_league_activity(self, round_number: int | None = None) -> dict[str, Any]:
        if round_number is None:
            state = self._get("epl_state", f"{API_BASE}/state/clubsoccer:epl", Mapping)
            if not isinstance(state, Mapping):
                return self._result({})
            try:
                round_number = latest_completed_gameweek(state)
            except SleeperDataError:
                self.limitations.append(_limitation("round", "The latest completed league round could not be resolved."))
                return self._result({})
        if round_number < 1:
            return {"status": "partial", "data": {}, "limitations": [{"kind": "unsupported", "field": "round", "detail": "Transaction rounds start at 1."}], "sources": []}
        rows = self._get(f"transactions_{round_number}", transactions_url(EXPECTED_LEAGUE_ID, round_number), list)
        team_names = self._team_names()
        try:
            catalog = self._catalog()
        except Exception:
            self.limitations.append(_limitation("player_catalog", "Player identity data could not be accessed."))
            return self._result({"round": round_number, "transactions": []})
        activities = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping):
                continue
            def moves(key: str) -> list[dict[str, Any]]:
                raw = row.get(key)
                return [
                    {"player": self._player_identity(str(player_id), catalog), "team": team_names.get(str(roster_id), "Unknown team")}
                    for player_id, roster_id in raw.items()
                ] if isinstance(raw, Mapping) else []
            activities.append({
                "type": row.get("type"), "status": row.get("status"), "created": row.get("created"),
                "adds": moves("adds"), "drops": moves("drops"),
                "teams": [team_names.get(str(value), "Unknown team") for value in (row.get("roster_ids") or [])],
            })
        return self._result({"round": round_number, "transactions": activities} if rows is not None else {})

    def get_draft_context(self, player_name: str, *, radius: int = 2) -> dict[str, Any]:
        """Return a named player's observed draft neighborhood when available."""
        try:
            catalog = self._catalog()
        except Exception:
            return {"status": "partial", "data": {}, "limitations": [_limitation("player_catalog", "Player identity data could not be accessed.")], "sources": []}
        matches = [row for row in catalog if str(row.get("name") or "").casefold() == player_name.casefold().strip()]
        if len(matches) != 1:
            return {"status": "partial", "data": {}, "limitations": [{"kind": "not_found", "field": "player", "detail": "The requested player could not be uniquely resolved."}], "sources": [_local_source("Fantasy player catalog")]}
        league = self._get("league_settings", f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}", Mapping)
        draft_id = str(league.get("draft_id") or "") if isinstance(league, Mapping) else ""
        if not draft_id:
            self.limitations.append({"kind": "unsupported", "field": "draft", "detail": "The current league does not expose a draft ID."})
            return self._result({})
        picks = self._get("draft_picks", f"{API_BASE}/draft/{draft_id}/picks", list)
        target_id = str(matches[0]["player_id"])
        index = next((i for i, pick in enumerate(picks or []) if isinstance(pick, Mapping) and str(pick.get("player_id") or "") == target_id), None)
        if index is None:
            self.limitations.append({"kind": "not_found", "field": "draft_pick", "detail": "The player was not found in the current league draft."})
            return self._result({})
        selected = [pick for pick in (picks or [])[max(0, index - max(0, radius)):index + max(0, radius) + 1] if isinstance(pick, Mapping)]
        team_names = self._team_names()
        return self._result({"player": {"name": matches[0]["name"]}, "picks": [{
            "pick_no": pick.get("pick_no"), "round": pick.get("round"), "draft_slot": pick.get("draft_slot"),
            "player": self._player_identity(str(pick.get("player_id") or ""), catalog),
            "team": team_names.get(str(pick.get("roster_id") or pick.get("picked_by") or ""), "Unknown team"),
        } for pick in selected]})

    def get_player_trends(self, *, kind: str, hours: int = 24, limit: int = 12) -> dict[str, Any]:
        if kind not in {"add", "drop"} or not 1 <= hours <= 168 or not 1 <= limit <= 25:
            return {"status": "partial", "data": {}, "limitations": [{"kind": "unsupported", "field": "trend_request", "detail": "Trend type, lookback, or limit is outside the supported bounds."}], "sources": []}
        rows = self._get(f"trending_{kind}_{hours}_{limit}", f"{API_BASE}/players/clubsoccer:epl/trending/{kind}?lookback_hours={hours}&limit={limit}", list)
        catalog = self._catalog()
        return self._result({"kind": kind, "lookback_hours": hours, "trends": [{**self._player_identity(str(row.get("player_id") or ""), catalog), "count": row.get("count")} for row in rows if isinstance(row, Mapping)]} if rows is not None else {})

    def get_waiver_context(self, *, manager_id: str, position: str, limit: int) -> dict[str, Any]:
        """Return the existing deterministic waiver engine's compact evidence."""

        if position not in {"ANY", "F", "M", "D", "GK"} or not 1 <= limit <= 25:
            return {
                "status": "partial",
                "data": {},
                "limitations": [{
                    "kind": "unsupported", "field": "waiver_request",
                    "detail": "Position must be ANY, F, M, D, or GK and limit must be between 1 and 25.",
                }],
                "sources": [],
            }

        league = self._get("league_settings", f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}", Mapping)
        state = self._get("epl_state", f"{API_BASE}/state/clubsoccer:epl", Mapping)
        rosters = self._get("league_rosters", f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}/rosters", list)
        live_players = self._get("epl_players", SLEEPER_EPL_PLAYERS_URL, Mapping)
        season = str(state.get("season") or "") if isinstance(state, Mapping) else ""
        stats_rows = self._get(
            "season_stats", f"{STATS_BASE}/clubsoccer:epl/{season}?season_type=regular", list,
        ) if season else None
        if not all((
            isinstance(league, Mapping), isinstance(rosters, list),
            isinstance(stats_rows, list), isinstance(live_players, Mapping),
        )):
            return self._result({})
        scoring = league.get("scoring_settings") if isinstance(league.get("scoring_settings"), Mapping) else {}
        players = {
            str(raw.get("player_id") or raw_id): {
                "player_id": str(raw.get("player_id") or raw_id),
                "full_name": raw.get("full_name"),
                "team_abbr": raw.get("team_abbr"),
                "fantasy_positions": raw.get("fantasy_positions") or [],
                "competitions": raw.get("competitions") or [],
                "active": raw.get("active"),
                "status": raw.get("status"),
                "injury_status": raw.get("injury_status"),
                "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), Mapping) else {},
            }
            for raw_id, raw in live_players.items()
            if isinstance(raw, Mapping) and str(raw.get("player_id") or raw_id)
        }
        # `players` is the complete eligible-player metadata universe.  Stats
        # enrich/rank it but never determine who can be available.
        candidates = pickup_candidates(
            players, rosters, stats_rows, scoring, required_position=position, limit=limit,
        )
        swaps = roster_swap_recommendations(
            candidates, players, rosters, stats_rows, scoring, manager_id=manager_id, limit=min(6, limit),
        )
        return self._result({
            "position": position,
            "limit": limit,
            "available_candidates": candidates,
            "roster_swap_recommendations": swaps,
            "availability_note": "Sleeper does not distinguish an immediate add from pending waivers.",
        })

    def get_player_context(self, player_name: str) -> dict[str, Any]:
        """Use the existing compact named-player evidence contract unchanged."""
        remaining = self._remaining()
        if remaining <= 0:
            return {"status": "partial", "data": {}, "limitations": [_limitation("packet_deadline", "Current player data could not be retrieved within this answer's time limit.")], "sources": []}
        return get_player_evaluation_context(
            self.config, player_name, timeout=remaining, client=self.bounded_client(),
        )

    def search_player_pool(self, query: str, *, limit: int = 12) -> dict[str, Any]:
        """Return a small local-catalog match set with safe ownership evidence."""
        normalized = query.casefold().strip()
        if not normalized or limit < 1:
            return {"status": "partial", "data": {}, "limitations": [{"kind": "not_found", "field": "player_query", "detail": "Provide a player name to search."}], "sources": []}
        try:
            catalog = load_local_player_catalog(self.config)
        except Exception:
            self.limitations.append(_limitation("player_catalog", "Player identity data could not be accessed."))
            return self._result({})
        matches = [row for row in catalog if normalized in str(row.get("name") or "").casefold()][:min(limit, 25)]
        if not matches:
            return {"status": "partial", "data": {}, "limitations": [{"kind": "not_found", "field": "player", "detail": "No current catalog player matched the requested name."}], "sources": [_local_source("Fantasy player catalog")]}
        self.sources.append(_local_source("Fantasy player catalog"))
        rosters = self._get("league_rosters", f"{API_BASE}/league/{EXPECTED_LEAGUE_ID}/rosters", list)
        valid_rosters = isinstance(rosters, list) and all(isinstance(row, Mapping) and isinstance(row.get("players"), list) for row in rosters)
        owners: dict[str, object] = {}
        if valid_rosters:
            for roster in rosters:
                for player_id in roster.get("players") or []:
                    owners[str(player_id)] = roster.get("roster_id")
        elif rosters is not None:
            self.limitations.append(_limitation("league_rosters", "Current league data could not be processed."))
        result = []
        for player in matches:
            player_id = str(player.get("player_id") or "")
            ownership: dict[str, object] = {"state": "unknown"}
            if valid_rosters:
                ownership = {"state": "rostered", "roster_id": owners[player_id]} if player_id in owners else {"state": "unrostered_unclassified"}
            result.append({"player_id": player_id, "name": player.get("name"), "club": player.get("club"), "positions": list(player.get("positions") or []), "active": player.get("active"), "status": player.get("status"), "ownership": ownership})
        return self._result({"players": result})

    def get_guardian_status(self, *, now: datetime) -> dict[str, Any]:
        try:
            events = active_events(self.config, now=now)
        except Exception:
            self.limitations.append(_limitation("guardian", "Deadline Guardian state could not be accessed."))
            return self._result({})
        self.sources.append(_current_local_source("Fantasy Deadline Guardian"))
        return self._result({"events": [{"event_id": event.event_id, "kickoff": event.kickoff.isoformat(), "home": event.home, "away": event.away, "acknowledged_at": event.acknowledged_at.isoformat() if event.acknowledged_at else None} for event in events]})

    def get_task_registry(self) -> dict[str, Any]:
        try:
            registry = load_registry(self.config.task_registry_path, repo_root=self.config.repo_root)
        except Exception:
            self.limitations.append(_limitation("task_registry", "Scheduled-task metadata could not be accessed."))
            return self._result({})
        self.sources.append(_local_source("Fantasy task registry"))
        return self._result({"tasks": [{"id": task.id, "name": task.name, "schedule_type": task.schedule_type, "run_at": task.run_at, "minute_past_hour": task.minute_past_hour} for task in registry.tasks]})

    def get_fixture_context(self) -> dict[str, Any]:
        try:
            schedule = load_persisted_fixture_schedule(self.config)
        except Exception:
            self.limitations.append(_limitation("fixtures", "Maintained fixture data could not be accessed."))
            return self._result({})
        self.sources.append(_local_source("Fantasy fixture calendar"))
        return self._result({"fixture_count": len(schedule) if isinstance(schedule, list) else None})
