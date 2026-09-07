"""Compact, read-only product capabilities over Fantasy authoritative data."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import time
from typing import Any, Mapping

from .automation import AppConfig, EXPECTED_LEAGUE_ID, load_local_player_catalog, load_registry
from .deadline_guardian import active_events
from .lineup_alerts import load_persisted_fixture_schedule
from .player_evaluation import get_player_evaluation_context
from .sleeper import API_BASE, SleeperClient, SleeperDataError, transactions_url
from .watchlist import WatchlistError, list_watchlist


def _source(name: str) -> dict[str, Any]:
    return {"source": name, "retrieved_at": datetime.now(timezone.utc).isoformat(), "stale": False}


def _local_source(name: str) -> dict[str, Any]:
    return {"source": name, "retrieved_at": None, "stale": True}


def _limitation(field: str, detail: str) -> dict[str, str]:
    return {"kind": "temporarily_unavailable", "field": field, "detail": detail}


class DataCapabilities:
    """Request-scoped, deadline-bounded reads; no raw provider access is exposed."""

    def __init__(self, config: AppConfig, *, timeout: float, client: SleeperClient | None = None) -> None:
        self.config = config
        self.deadline = time.monotonic() + max(0.0, timeout)
        self.client = client or SleeperClient(timeout=min(8.0, max(0.001, timeout)), retries=1)
        self.cache: dict[str, object] = {}
        self.sources: list[dict[str, Any]] = []
        self.limitations: list[dict[str, str]] = []

    def _remaining(self) -> float:
        return self.deadline - time.monotonic()

    def _get(self, key: str, url: str, expected: type) -> object | None:
        if key in self.cache:
            return self.cache[key]
        if self._remaining() <= 0:
            self.limitations.append(_limitation("packet_deadline", "Current league data could not be retrieved within this answer's time limit."))
            return None
        try:
            requester = replace(self.client, timeout=min(8.0, self._remaining()), retries=1) if isinstance(self.client, SleeperClient) else self.client
            value = requester.get_json(url)
        except SleeperDataError:
            self.limitations.append(_limitation(key, "Current league data could not be accessed."))
            return None
        if self._remaining() <= 0 or not isinstance(value, expected):
            self.limitations.append(_limitation(key, "Current league data could not be processed."))
            return None
        self.cache[key] = value
        self.sources.append(_source(f"Sleeper {key.replace('_', ' ')}"))
        return value

    def _result(self, data: dict[str, Any]) -> dict[str, Any]:
        return {"status": "partial" if self.limitations else "complete", "data": data, "limitations": self.limitations.copy(), "sources": self.sources.copy()}

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
        return self._result({"team": {"name": label, "owner_id": owner_id, "roster_id": roster.get("roster_id"), "player_ids": [str(value) for value in (roster.get("players") or [])], "starters": [str(value) for value in (roster.get("starters") or [])]}})

    def get_watchlist(self) -> dict[str, Any]:
        if "watchlist" in self.cache:
            return self._result({"watchlist": self.cache["watchlist"]})
        try:
            players = list_watchlist(self.config.repo_root / "data" / "automation" / "watchlist.sqlite3")
        except WatchlistError:
            self.limitations.append(_limitation("watchlist", "Saved watchlist data could not be accessed."))
            return self._result({})
        data = [{"player_id": player.player_id, "name": player.name, "club": player.club, "positions": list(player.positions), "added_at": player.added_at} for player in players]
        self.cache["watchlist"] = data
        self.sources.append(_local_source("Fantasy watchlist"))
        return self._result({"watchlist": data})

    def get_league_activity(self, round_number: int) -> dict[str, Any]:
        if round_number < 1:
            return {"status": "partial", "data": {}, "limitations": [{"kind": "unsupported", "field": "round", "detail": "Transaction rounds start at 1."}], "sources": []}
        rows = self._get(f"transactions_{round_number}", transactions_url(EXPECTED_LEAGUE_ID, round_number), list)
        activities = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping):
                continue
            activities.append({key: row.get(key) for key in ("transaction_id", "type", "status", "created", "leg", "roster_ids", "adds", "drops", "draft_picks")})
        return self._result({"round": round_number, "transactions": activities} if rows is not None else {})

    def get_draft_context(self, player_name: str, *, radius: int = 2) -> dict[str, Any]:
        """Return a named player's observed draft neighborhood when available."""
        try:
            catalog = load_local_player_catalog(self.config)
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
        return self._result({"player": {"player_id": target_id, "name": matches[0]["name"]}, "picks": [{key: pick.get(key) for key in ("pick_no", "round", "draft_slot", "player_id", "picked_by", "roster_id")} for pick in selected]})

    def get_player_trends(self, *, kind: str, hours: int = 24, limit: int = 12) -> dict[str, Any]:
        if kind not in {"add", "drop"} or not 1 <= hours <= 168 or not 1 <= limit <= 25:
            return {"status": "partial", "data": {}, "limitations": [{"kind": "unsupported", "field": "trend_request", "detail": "Trend type, lookback, or limit is outside the supported bounds."}], "sources": []}
        rows = self._get(f"trending_{kind}_{hours}_{limit}", f"{API_BASE}/players/clubsoccer:epl/trending/{kind}?lookback_hours={hours}&limit={limit}", list)
        return self._result({"kind": kind, "lookback_hours": hours, "trends": [{"player_id": str(row.get("player_id") or ""), "count": row.get("count")} for row in rows if isinstance(row, Mapping)]} if rows is not None else {})

    def get_player_context(self, player_name: str) -> dict[str, Any]:
        """Use the existing compact named-player evidence contract unchanged."""
        remaining = self._remaining()
        if remaining <= 0:
            return {"status": "partial", "data": {}, "limitations": [_limitation("packet_deadline", "Current player data could not be retrieved within this answer's time limit.")], "sources": []}
        return get_player_evaluation_context(self.config, player_name, timeout=remaining, client=self.client)

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
        self.sources.append(_local_source("Fantasy Deadline Guardian"))
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
