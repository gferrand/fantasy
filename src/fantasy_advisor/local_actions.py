"""Explicit, owner-authorized Fantasy-owned local actions only."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .automation import AppConfig, load_local_player_catalog, watchlist_file
from .deadline_guardian import acknowledge_active_events
from .watchlist import (
    WatchlistError,
    add_watchlist_player,
    remove_watchlist_player,
    resolve_saved_watchlist_player,
    resolve_watchlist_player,
    list_watchlist,
)


class LocalActions:
    """Approved mutations; callers must deliberately select a named action."""

    def __init__(self, config: AppConfig, *, requester_id: str) -> None:
        self.config = config
        self.requester_id = str(requester_id)

    def _authorized(self) -> bool:
        return bool(self.config.discord_allowed_user_id) and self.requester_id == self.config.discord_allowed_user_id

    def _denied(self) -> dict[str, Any]:
        return {"status": "forbidden", "data": {}, "detail": "Only the configured owner can change Fantasy local state."}

    def add_to_watchlist(self, player_query: str) -> dict[str, Any]:
        if not self._authorized():
            return self._denied()
        try:
            player = resolve_watchlist_player(player_query, load_local_player_catalog(self.config))
            saved, added = add_watchlist_player(watchlist_file(self.config), player)
        except Exception as exc:
            return {"status": "not_found", "data": {}, "detail": str(exc)}
        return {"status": "success" if added else "no_op", "data": {"player_id": saved.player_id, "name": saved.name, "club": saved.club, "positions": list(saved.positions)}, "detail": "Added to watchlist." if added else "Already on watchlist."}

    def remove_from_watchlist(self, player_query: str) -> dict[str, Any]:
        if not self._authorized():
            return self._denied()
        try:
            saved = resolve_saved_watchlist_player(player_query, list_watchlist(watchlist_file(self.config)))
            removed = remove_watchlist_player(watchlist_file(self.config), saved.player_id)
        except WatchlistError as exc:
            return {"status": "not_found", "data": {}, "detail": str(exc)}
        if removed is None:
            return {"status": "not_found", "data": {}, "detail": "That player is no longer on the watchlist."}
        return {"status": "success", "data": {"player_id": removed.player_id, "name": removed.name}, "detail": "Removed from watchlist."}

    def acknowledge_guardian_alerts(self, *, now: datetime) -> dict[str, Any]:
        if not self._authorized():
            return self._denied()
        events = acknowledge_active_events(self.config, now=now)
        return {"status": "success" if events else "no_op", "data": {"acknowledged_event_ids": [event.event_id for event in events]}, "detail": "Guardian alerts acknowledged." if events else "No active Guardian alerts needed acknowledgement."}
