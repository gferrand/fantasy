"""Deterministic, read-only helpers for the Sleeper EPL API.

The ChatGPT Scheduled Task is intentionally advisory, but this module provides a
small, testable parser for the raw Sleeper payloads.  It keeps transaction and
available-player logic out of prose so malformed or truncated API responses are
detected instead of becoming confident fantasy advice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import time
from typing import Any, Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


API_BASE = "https://api.sleeper.app/v1"
STATS_BASE = "https://api.sleeper.com/stats"
USER_AGENT = "Fantasy EPL Advisor/1.0 (+read-only Sleeper analysis)"
EASTERN = ZoneInfo("America/New_York")

ACTIVE_EPL_CLUBS = {
    "ARS",
    "AVL",
    "BOU",
    "BRE",
    "BHA",
    "CHE",
    "CRY",
    "EVE",
    "FUL",
    "HUL",
    "IPS",
    "LIV",
    "LEE",
    "MCI",
    "MUN",
    "NEW",
    "NFO",
    "SUN",
    "TOT",
    "COV",
}


class SleeperDataError(RuntimeError):
    """Raised when a Sleeper response is unavailable or structurally invalid."""


@dataclass(frozen=True)
class SleeperClient:
    """Minimal resilient HTTP client for public Sleeper JSON endpoints."""

    timeout: float = 30.0
    retries: int = 3
    backoff_seconds: float = 0.5
    opener: Callable[..., Any] = urlopen
    sleep: Callable[[float], None] = time.sleep

    def get_json(self, url: str) -> Any:
        """Fetch and decode a JSON object or array with bounded retries."""

        last_error: Exception | None = None
        for attempt in range(self.retries):
            request = Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    raw = response.read()
                if not raw:
                    raise SleeperDataError(f"Empty response from {url}")
                try:
                    return json.loads(raw)
                except (TypeError, json.JSONDecodeError) as exc:
                    raise SleeperDataError(f"Invalid JSON from {url}") from exc
            except HTTPError as exc:
                last_error = exc
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if not retryable:
                    break
            except (URLError, TimeoutError, SleeperDataError) as exc:
                last_error = exc
            if attempt + 1 < self.retries:
                self.sleep(self.backoff_seconds * (2**attempt))
        raise SleeperDataError(f"Sleeper request failed: {url}") from last_error


def league_url(league_id: str) -> str:
    return f"{API_BASE}/league/{league_id}"


def transactions_url(league_id: str, round_number: int) -> str:
    if round_number < 1:
        raise ValueError("Sleeper transaction rounds start at 1")
    return f"{API_BASE}/league/{league_id}/transactions/{round_number}"


def current_roster_player_ids(rosters: Iterable[Mapping[str, Any]]) -> set[str]:
    """Return every player ID currently owned in the league."""

    owned: set[str] = set()
    for roster in rosters:
        owned.update(str(player_id) for player_id in (roster.get("players") or []))
    return owned


def _player_name(player_id: str, players: Mapping[str, Mapping[str, Any]]) -> str:
    player = players.get(str(player_id), {})
    name = (
        player.get("full_name")
        or player.get("metadata", {}).get("full_name")
        or " ".join(
            part for part in (player.get("first_name"), player.get("last_name")) if part
        )
        or f"Unknown player {player_id}"
    )
    return str(name).strip()


def _roster_name(roster_id: int, roster_names: Mapping[int, str]) -> str:
    return roster_names.get(int(roster_id), f"Roster {roster_id}")


def _mapping_items(mapping: Any) -> Iterable[tuple[str, int]]:
    if not isinstance(mapping, Mapping):
        return ()
    result: list[tuple[str, int]] = []
    for player_id, roster_id in mapping.items():
        try:
            result.append((str(player_id), int(roster_id)))
        except (TypeError, ValueError):
            continue
    return result


def normalize_completed_trades(
    transactions: Iterable[Mapping[str, Any]],
    *,
    day: date,
    roster_names: Mapping[int, str],
    players: Mapping[str, Mapping[str, Any]],
    timezone_name: str = "America/New_York",
) -> list[dict[str, Any]]:
    """Filter and normalize completed trades created on one local calendar day.

    Sleeper stores adds/drops as ``player_id -> roster_id`` mappings.  For a
    trade, the add mapping identifies the receiving roster and the drop mapping
    identifies the sending roster, which lets us reconstruct each side without
    relying on the order of ``roster_ids``.
    """

    local_zone = ZoneInfo(timezone_name)
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for transaction in transactions:
        if transaction.get("type") != "trade" or transaction.get("status") != "complete":
            continue
        transaction_id = str(transaction.get("transaction_id") or "")
        if not transaction_id or transaction_id in seen:
            continue
        created = transaction.get("created")
        if not isinstance(created, (int, float)):
            continue
        created_at = datetime.fromtimestamp(created / 1000, tz=local_zone)
        if created_at.date() != day:
            continue

        roster_ids = {int(value) for value in (transaction.get("roster_ids") or [])}
        received: dict[int, list[dict[str, str]]] = {roster_id: [] for roster_id in roster_ids}
        sent: dict[int, list[dict[str, str]]] = {roster_id: [] for roster_id in roster_ids}
        for player_id, roster_id in _mapping_items(transaction.get("adds")):
            received.setdefault(roster_id, []).append(
                {"player_id": player_id, "name": _player_name(player_id, players)}
            )
        for player_id, roster_id in _mapping_items(transaction.get("drops")):
            sent.setdefault(roster_id, []).append(
                {"player_id": player_id, "name": _player_name(player_id, players)}
            )

        sides = []
        for roster_id in sorted(roster_ids):
            sides.append(
                {
                    "roster_id": roster_id,
                    "team": _roster_name(roster_id, roster_names),
                    "sends": sent.get(roster_id, []),
                    "receives": received.get(roster_id, []),
                }
            )
        normalized.append(
            {
                "transaction_id": transaction_id,
                "created": created_at.isoformat(),
                "sides": sides,
                "draft_picks": transaction.get("draft_picks") or [],
                "waiver_budget": transaction.get("waiver_budget") or [],
            }
        )
        seen.add(transaction_id)
    return sorted(normalized, key=lambda item: item["created"])


def available_epl_players(
    players: Mapping[str, Mapping[str, Any]],
    rosters: Iterable[Mapping[str, Any]],
    *,
    excluded_names: Iterable[str] = (),
    allowed_clubs: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return active, current-club, unrostered EPL players.

    The API does not expose direct-free-agent versus pending-waiver status, so
    every result is deliberately labeled ``unrostered_unclassified``.  The
    Sleeper app remains authoritative for whether an Add action is immediate.
    """

    owned = current_roster_player_ids(rosters)
    clubs = allowed_clubs or ACTIVE_EPL_CLUBS
    excluded = {name.casefold() for name in excluded_names}
    result: list[dict[str, Any]] = []
    for raw_id, player in players.items():
        player_id = str(player.get("player_id") or raw_id)
        if player_id in owned:
            continue
        name = _player_name(player_id, players)
        if name.casefold() in excluded:
            continue
        club = str(player.get("team_abbr") or "").upper()
        if club not in clubs or "epl" not in (player.get("competitions") or []):
            continue
        if player.get("active") is False:
            continue
        status = str(player.get("status") or "").upper()
        if status and status not in {"A", "ACTIVE"}:
            continue
        result.append(
            {
                "player_id": player_id,
                "name": name,
                "club": club,
                "positions": player.get("fantasy_positions") or [],
                "injury_status": player.get("injury_status"),
                "availability": "unrostered_unclassified",
            }
        )
    return sorted(result, key=lambda item: (item["name"].casefold(), item["player_id"]))


def available_stats_backed_players(
    stats_rows: Iterable[Mapping[str, Any]],
    rosters: Iterable[Mapping[str, Any]],
    *,
    excluded_names: Iterable[str] = (),
    allowed_clubs: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return a bounded available pool from valid current-season stats rows.

    This is intentionally a fallback, not a replacement for the complete
    player metadata universe.  The stats endpoint embeds player metadata in
    each row and is much smaller for constrained retrieval environments.  Each
    result is marked as stats-backed so callers cannot present it as a complete
    waiver scan.
    """

    owned = current_roster_player_ids(rosters)
    clubs = allowed_clubs or ACTIVE_EPL_CLUBS
    excluded = {name.casefold() for name in excluded_names}
    result: dict[str, dict[str, Any]] = {}
    for row in stats_rows:
        if not isinstance(row, Mapping):
            continue
        player_id = str(row.get("player_id") or "")
        player = row.get("player")
        if not player_id or not isinstance(player, Mapping) or player_id in owned:
            continue
        name = str(
            player.get("full_name")
            or player.get("metadata", {}).get("full_name")
            or " ".join(part for part in (player.get("first_name"), player.get("last_name")) if part)
            or f"Unknown player {player_id}"
        ).strip()
        if name.casefold() in excluded:
            continue
        club = str(player.get("team_abbr") or "").upper()
        if club not in clubs or player.get("active") is False:
            continue
        status = str(player.get("status") or "").upper()
        if status and status not in {"A", "ACTIVE"}:
            continue
        result[player_id] = {
            "player_id": player_id,
            "name": name,
            "club": club,
            "positions": player.get("fantasy_positions") or [],
            "injury_status": player.get("injury_status"),
            "availability": "unrostered_unclassified",
            "candidate_source": "current-season-stats",
        }
    return sorted(result.values(), key=lambda item: (item["name"].casefold(), item["player_id"]))


def _position_score(
    stats: Mapping[str, Any],
    scoring_settings: Mapping[str, Any],
    position: str,
) -> float | None:
    """Calculate the configured score for one position when stats support it."""

    prefix = f"pos_{position.casefold()}_"
    total = 0.0
    found = False
    for stat_key, raw_value in stats.items():
        if not stat_key.startswith(prefix) or stat_key not in scoring_settings:
            continue
        try:
            value = float(raw_value)
            multiplier = float(scoring_settings[stat_key])
        except (TypeError, ValueError):
            continue
        total += value * multiplier
        found = True
    return round(total, 2) if found else None


def _stat_number(stats: Mapping[str, Any], key: str) -> float | None:
    try:
        return float(stats[key])
    except (KeyError, TypeError, ValueError):
        return None


def pickup_candidates(
    players: Mapping[str, Mapping[str, Any]],
    rosters: Iterable[Mapping[str, Any]],
    stats_rows: Iterable[Mapping[str, Any]],
    scoring_settings: Mapping[str, Any],
    *,
    excluded_names: Iterable[str] = (),
    allowed_clubs: set[str] | None = None,
    limit: int = 24,
) -> list[dict[str, Any]]:
    """Return a compact scoring-aware pickup shortlist for bounded readers."""

    if limit < 1:
        return []
    available = available_epl_players(
        players,
        rosters,
        excluded_names=excluded_names,
        allowed_clubs=allowed_clubs,
    )
    stats_by_id: dict[str, Mapping[str, Any]] = {}
    for row in stats_rows:
        if not isinstance(row, Mapping):
            continue
        player_id = str(row.get("player_id") or "")
        stats = row.get("stats")
        if player_id and isinstance(stats, Mapping):
            stats_by_id[player_id] = stats

    candidates: list[dict[str, Any]] = []
    for item in available:
        player_id = item["player_id"]
        stats = stats_by_id.get(player_id, {})
        positions = [str(position).upper() for position in item.get("positions") or []]
        position_scores = {
            position: score
            for position in positions
            if (score := _position_score(stats, scoring_settings, position)) is not None
        }
        candidates.append(
            {
                **item,
                "positions": positions,
                "custom_points": max(position_scores.values()) if position_scores else None,
                "position_points": position_scores,
                "games": _stat_number(stats, "gp"),
                "starts": _stat_number(stats, "gs"),
                "minutes": _stat_number(stats, "min"),
                "candidate_source": (
                    "current-season-stats" if stats else "complete-player-metadata"
                ),
            }
        )

    ranked = sorted(
        candidates,
        key=lambda item: (
            item["custom_points"] is not None,
            item["custom_points"] if item["custom_points"] is not None else float("-inf"),
            item["minutes"] if item["minutes"] is not None else float("-inf"),
            item["games"] if item["games"] is not None else float("-inf"),
            item["starts"] if item["starts"] is not None else float("-inf"),
            -len(item["name"]),
            item["name"].casefold(),
            item["player_id"],
        ),
        reverse=True,
    )
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    position_counts: dict[str, int] = {}
    max_per_position = max(3, limit // 3)
    for item in ranked:
        if len(selected) >= limit:
            break
        item_positions = item["positions"] or ["UNKNOWN"]
        if all(position_counts.get(position, 0) >= max_per_position for position in item_positions):
            continue
        selected.append(item)
        selected_ids.add(item["player_id"])
        for position in item_positions:
            position_counts[position] = position_counts.get(position, 0) + 1
    if len(selected) < limit:
        selected.extend(item for item in ranked if item["player_id"] not in selected_ids)
    return selected[:limit]


def eastern_today() -> date:
    """Return today's calendar date in the league's reporting timezone."""

    return datetime.now(tz=EASTERN).date()
