"""Private, durable player watchlist management for the Discord advisor."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable

from .player_catalog import normalize_player_text


class WatchlistError(RuntimeError):
    """Raised when a watchlist operation cannot be completed safely."""


class WatchlistResolutionError(WatchlistError):
    """Raised when a player name is missing or does not resolve uniquely."""


def parse_watchlist_intent(message: str) -> tuple[str, str | None] | None:
    """Recognize safe watchlist commands in an ordinary Discord DM.

    Only direct, imperative requests are handled here. Questions such as
    "should I add..." remain advisor questions for Codex instead of silently
    changing the personal list.
    """

    text = " ".join(message.strip().split())
    # Treat one near-miss word as "watchlist" before applying the narrow
    # command grammar. This catches natural mobile typos without interpreting
    # broad advisor questions as mutations.
    corrected_words = []
    for word in text.split(" "):
        stripped = word.strip(".,?!")
        if stripped and SequenceMatcher(None, stripped.casefold(), "watchlist").ratio() >= 0.84:
            corrected_words.append(word.replace(stripped, "watchlist"))
        else:
            corrected_words.append(word)
    text = " ".join(corrected_words)
    normalized = text.casefold().rstrip(".?!")
    if normalized in {
        "watchlist",
        "my watchlist",
        "list my watchlist",
        "show my watchlist",
        "show me my watchlist",
        "what is on my watchlist",
        "what's on my watchlist",
        "who am i watching",
    }:
        return "list", None
    prefix = r"(?:please\s+)?(?:(?:can|could)\s+you\s+)?"
    for action, pattern in (
        ("remove", rf"^{prefix}(?:remove|delete|unwatch)\s+(.+?)\s+(?:from|off)\s+(?:my\s+)?watchlist$"),
        ("add", rf"^{prefix}(?:add|watch)\s+(.+?)\s+(?:to|on)\s+(?:my\s+)?watchlist$"),
        ("add", rf"^{prefix}(?:keep\s+(?:an\s+eye|tabs)\s+on)\s+(.+?)(?:\s+for\s+my\s+watchlist)?$"),
    ):
        match = re.fullmatch(pattern, normalized, flags=re.IGNORECASE)
        if match:
            player = text[match.start(1):match.end(1)].strip(" .,?!")
            if player:
                return action, player
    # A clear imperative clause after a completed thought is still explicit.
    # Do not match tentative wording such as "Should I add ..." or a clause
    # embedded in an unfinished sentence.
    compound = re.search(
        rf"(?:^|[.!?;]\s+){prefix}(?:add|watch)\s+(.+?)\s+(?:to|on)\s+(?:my\s+)?watchlist(?=$|[.!?;])",
        normalized,
        flags=re.IGNORECASE,
    )
    if compound:
        player = text[compound.start(1):compound.end(1)].strip(" .,?!;")
        if player:
            return "add", player
    return None


@dataclass(frozen=True)
class WatchlistPlayer:
    player_id: str
    name: str
    club: str
    positions: tuple[str, ...]
    added_at: str


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(path, timeout=30)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlist_players (
            player_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            club TEXT NOT NULL,
            positions_json TEXT NOT NULL,
            added_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def _watchlist_player(row: sqlite3.Row) -> WatchlistPlayer:
    import json

    try:
        positions = json.loads(str(row["positions_json"]))
    except json.JSONDecodeError:
        positions = []
    return WatchlistPlayer(
        player_id=str(row["player_id"]),
        name=str(row["name"]),
        club=str(row["club"]),
        positions=tuple(str(position) for position in positions if str(position).strip()),
        added_at=str(row["added_at"]),
    )


def list_watchlist(path: Path) -> list[WatchlistPlayer]:
    if not path.exists():
        return []
    connection = _connect(path)
    try:
        rows = connection.execute(
            "SELECT player_id, name, club, positions_json, added_at "
            "FROM watchlist_players ORDER BY name COLLATE NOCASE, player_id"
        ).fetchall()
        return [_watchlist_player(row) for row in rows]
    finally:
        connection.close()


def add_watchlist_player(path: Path, player: dict[str, Any]) -> tuple[WatchlistPlayer, bool]:
    """Add a resolved player. Returns the canonical entry and whether it was new."""

    import json

    player_id = str(player.get("player_id") or "").strip()
    name = str(player.get("name") or "").strip()
    club = str(player.get("club") or "").strip().upper()
    positions = [str(position).strip() for position in (player.get("positions") or []) if str(position).strip()]
    if not player_id or not name:
        raise WatchlistError("Resolved watchlist players need an ID and name")
    added_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    connection = _connect(path)
    try:
        existing = connection.execute(
            "SELECT player_id, name, club, positions_json, added_at FROM watchlist_players WHERE player_id = ?",
            (player_id,),
        ).fetchone()
        if existing is not None:
            return _watchlist_player(existing), False
        connection.execute(
            "INSERT INTO watchlist_players (player_id, name, club, positions_json, added_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (player_id, name, club, json.dumps(positions), added_at),
        )
        connection.commit()
        return WatchlistPlayer(player_id, name, club, tuple(positions), added_at), True
    finally:
        connection.close()


def remove_watchlist_player(path: Path, player_id: str) -> WatchlistPlayer | None:
    connection = _connect(path)
    try:
        row = connection.execute(
            "SELECT player_id, name, club, positions_json, added_at FROM watchlist_players WHERE player_id = ?",
            (str(player_id),),
        ).fetchone()
        if row is None:
            return None
        connection.execute("DELETE FROM watchlist_players WHERE player_id = ?", (str(player_id),))
        connection.commit()
        return _watchlist_player(row)
    finally:
        connection.close()


def matching_players(query: str, players: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return exact-first Sleeper EPL catalog candidates for a Discord name."""

    normalized = normalize_player_text(query.strip())
    if not normalized:
        return []
    exact: list[dict[str, Any]] = []
    partial: list[dict[str, Any]] = []
    for player in players:
        name = str(player.get("name") or "").strip()
        club = str(player.get("club") or "").strip().upper()
        if not name:
            continue
        name_key = normalize_player_text(name)
        display_key = normalize_player_text(f"{name} {club}") if club else name_key
        if normalized in {name_key, display_key}:
            exact.append(player)
        elif normalized in name_key:
            partial.append(player)
    candidates = exact or partial
    return sorted(candidates, key=lambda player: (str(player.get("name", "")).casefold(), str(player.get("club", ""))))


def resolve_watchlist_player(query: str, players: Iterable[dict[str, Any]]) -> dict[str, Any]:
    candidates = matching_players(query, players)
    if not candidates:
        raise WatchlistResolutionError(f"No Sleeper EPL player matched {query!r}.")
    if len(candidates) > 1:
        options = ", ".join(
            f"{candidate['name']} ({candidate['club'] or 'no current club'})" for candidate in candidates[:8]
        )
        raise WatchlistResolutionError(f"{query!r} is ambiguous. Use one of: {options}")
    return candidates[0]


def resolve_saved_watchlist_player(query: str, players: Iterable[WatchlistPlayer]) -> WatchlistPlayer:
    candidates = matching_players(
        query,
        [
            {"player_id": player.player_id, "name": player.name, "club": player.club}
            for player in players
        ],
    )
    if not candidates:
        raise WatchlistResolutionError(f"No watched player matched {query!r}.")
    if len(candidates) > 1:
        options = ", ".join(
            f"{candidate['name']} ({candidate['club'] or 'no current club'})" for candidate in candidates[:8]
        )
        raise WatchlistResolutionError(f"{query!r} is ambiguous. Use one of: {options}")
    player_id = str(candidates[0]["player_id"])
    return next(player for player in players if player.player_id == player_id)
