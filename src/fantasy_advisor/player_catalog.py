"""Private, manually refreshed Sleeper player identity catalog."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import unicodedata
from typing import Any, Mapping


class PlayerCatalogError(RuntimeError):
    """Raised when the private player catalog cannot be used safely."""


class PlayerCatalogNotInitialized(PlayerCatalogError):
    """Raised when an owner has not yet populated the local catalog."""


@dataclass(frozen=True)
class PlayerCatalogRefresh:
    player_count: int
    refreshed_at: str


def normalize_player_text(text: str) -> str:
    """Normalize player and club text for accent- and punctuation-tolerant lookup."""

    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character) and character.isalnum()
    ).casefold()


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
        CREATE TABLE IF NOT EXISTS catalog_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_players (
            player_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            club TEXT NOT NULL,
            normalized_club TEXT NOT NULL,
            positions_json TEXT NOT NULL,
            competitions_json TEXT NOT NULL,
            active INTEGER,
            status TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS catalog_players_normalized_name "
        "ON catalog_players(normalized_name)"
    )
    connection.commit()
    return connection


def _canonical_name(player: Mapping[str, Any]) -> str:
    metadata = player.get("metadata")
    metadata_name = metadata.get("full_name") if isinstance(metadata, Mapping) else None
    return str(
        player.get("full_name")
        or metadata_name
        or " ".join(
            str(part).strip()
            for part in (player.get("first_name"), player.get("last_name"))
            if str(part or "").strip()
        )
        or ""
    ).strip()


def _catalog_row(raw_id: object, raw_player: object) -> tuple[object, ...]:
    if not isinstance(raw_player, Mapping):
        raise PlayerCatalogError("Sleeper player catalog contains a non-object player record")
    player_id = str(raw_player.get("player_id") or raw_id or "").strip()
    name = _canonical_name(raw_player)
    if not player_id or not name:
        raise PlayerCatalogError("Sleeper player catalog contains a player without an ID or name")
    club = str(raw_player.get("team_abbr") or "").strip().upper()
    positions = raw_player.get("fantasy_positions") or []
    competitions = raw_player.get("competitions") or []
    if not isinstance(positions, list) or not isinstance(competitions, list):
        raise PlayerCatalogError(f"Sleeper player catalog has malformed metadata for {name}")
    active = raw_player.get("active")
    active_value = None if active is None else int(bool(active))
    return (
        player_id,
        name,
        normalize_player_text(name),
        club,
        normalize_player_text(club),
        json.dumps([str(position) for position in positions if str(position).strip()]),
        json.dumps([str(competition) for competition in competitions if str(competition).strip()]),
        active_value,
        str(raw_player.get("status") or "").strip().upper(),
    )


def refresh_player_catalog(path: Path, payload: object, *, refreshed_at: str | None = None) -> PlayerCatalogRefresh:
    """Atomically replace the catalog with a validated Sleeper players payload."""

    if not isinstance(payload, Mapping) or not payload:
        raise PlayerCatalogError("Sleeper player catalog did not return a non-empty object")
    rows = [_catalog_row(raw_id, raw_player) for raw_id, raw_player in payload.items()]
    if not rows:
        raise PlayerCatalogError("Sleeper player catalog contains no usable players")
    timestamp = refreshed_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    connection = _connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM catalog_players")
        connection.executemany(
            """
            INSERT INTO catalog_players (
                player_id, name, normalized_name, club, normalized_club,
                positions_json, competitions_json, active, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.execute(
            "INSERT INTO catalog_metadata(key, value) VALUES ('refreshed_at', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (timestamp,),
        )
        connection.commit()
        return PlayerCatalogRefresh(player_count=len(rows), refreshed_at=timestamp)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def load_player_catalog(path: Path) -> list[dict[str, Any]]:
    """Return the local identity catalog without making a network request."""

    if not path.exists():
        raise PlayerCatalogNotInitialized("The local player catalog is empty. Run `/player_catalog update` first.")
    connection = _connect(path)
    try:
        refreshed = connection.execute(
            "SELECT value FROM catalog_metadata WHERE key = 'refreshed_at'"
        ).fetchone()
        if refreshed is None:
            raise PlayerCatalogNotInitialized("The local player catalog is empty. Run `/player_catalog update` first.")
        rows = connection.execute(
            """
            SELECT player_id, name, club, positions_json, competitions_json, active, status
            FROM catalog_players
            ORDER BY name COLLATE NOCASE, player_id
            """
        ).fetchall()
    finally:
        connection.close()
    if not rows:
        raise PlayerCatalogNotInitialized("The local player catalog is empty. Run `/player_catalog update` first.")
    players: list[dict[str, Any]] = []
    for row in rows:
        try:
            positions = json.loads(str(row["positions_json"]))
            competitions = json.loads(str(row["competitions_json"]))
        except json.JSONDecodeError as exc:
            raise PlayerCatalogError("The local player catalog is malformed. Run `/player_catalog update`.") from exc
        players.append(
            {
                "player_id": str(row["player_id"]),
                "name": str(row["name"]),
                "club": str(row["club"]),
                "positions": [str(position) for position in positions],
                "competitions": [str(competition) for competition in competitions],
                "active": None if row["active"] is None else bool(row["active"]),
                "status": str(row["status"]),
            }
        )
    return players


def player_catalog_refreshed_at(path: Path) -> str | None:
    """Return the successful refresh time without creating an uninitialized catalog."""

    if not path.exists():
        return None
    connection = _connect(path)
    try:
        row = connection.execute(
            "SELECT value FROM catalog_metadata WHERE key = 'refreshed_at'"
        ).fetchone()
        return str(row["value"]) if row is not None else None
    finally:
        connection.close()
