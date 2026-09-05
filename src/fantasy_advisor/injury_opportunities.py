"""Deterministic Sleeper context and rendering for injury opportunities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from .gameweek import LEAGUE_ID
from .sleeper import ACTIVE_EPL_CLUBS, API_BASE, STATS_BASE, SleeperClient, SleeperDataError


OUT_STATUSES = {"OUT", "O", "IR", "IR+"}
DOUBTFUL_STATUSES = {"GTD", "Q", "QUESTIONABLE", "DOUBTFUL", "D"}
MAX_OPPORTUNITIES = 8


@dataclass(frozen=True)
class InjuryOpportunitiesContext:
    """Bounded, trusted Sleeper data supplied to current-web research."""

    season: str
    gameweek: int | None
    retrieved_at: str
    payload: dict[str, Any]

    def as_json(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class InjuryResearch:
    """Validated research payload returned by the web model."""

    injuries: tuple[dict[str, Any], ...]
    opportunities: tuple[dict[str, Any], ...]


INJURY_RESEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "injuries": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "player_id": {"type": "string"},
                    "injury_summary": {"type": "string"},
                    "return_window": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low", "unknown"]},
                    "sources": {
                        "type": "array",
                        "maxItems": 2,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "title": {"type": "string"},
                                "url": {"type": "string"},
                            },
                            "required": ["title", "url"],
                        },
                    },
                },
                "required": ["player_id", "injury_summary", "return_window", "confidence", "sources"],
            },
        },
        "opportunities": {
            "type": "array",
            "maxItems": MAX_OPPORTUNITIES,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "player_id": {"type": "string"},
                    "injured_player_ids": {"type": "array", "items": {"type": "string"}},
                    "role_change": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "sources": {
                        "type": "array",
                        "maxItems": 2,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "title": {"type": "string"},
                                "url": {"type": "string"},
                            },
                            "required": ["title", "url"],
                        },
                    },
                },
                "required": ["player_id", "injured_player_ids", "role_change", "confidence", "sources"],
            },
        },
    },
    "required": ["injuries", "opportunities"],
}


def _array(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise SleeperDataError(f"Sleeper {label} did not return an array")
    return [item for item in value if isinstance(item, Mapping)]


def _season_week(state: object) -> tuple[str, int | None]:
    if not isinstance(state, Mapping):
        raise SleeperDataError("Sleeper EPL state did not return an object")
    season = str(state.get("season") or "").strip()
    if len(season) != 4 or not season.isdigit():
        raise SleeperDataError("Sleeper EPL state did not include a current season")
    try:
        week = int(state.get("display_week") or state["week"])
    except (KeyError, TypeError, ValueError):
        week = None
    return season, week


def _name(player_id: str, player: Mapping[str, Any]) -> str:
    metadata = player.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    return str(
        player.get("full_name")
        or metadata.get("full_name")
        or " ".join(str(value) for value in (player.get("first_name"), player.get("last_name")) if value)
        or f"Unknown player {player_id}"
    ).strip()


def _status_category(value: object) -> str | None:
    normalized = str(value or "").strip().upper()
    if normalized in OUT_STATUSES:
        return "out"
    if normalized in DOUBTFUL_STATUSES:
        return "doubt"
    return None


def _is_current_epl_player(player: Mapping[str, Any]) -> bool:
    club = str(player.get("team_abbr") or "").upper()
    competitions = {str(item).casefold() for item in (player.get("competitions") or [])}
    status = str(player.get("status") or "").upper()
    return (
        club in ACTIVE_EPL_CLUBS
        and "epl" in competitions
        and player.get("active") is not False
        and status in {"", "A", "ACTIVE"}
    )


def _number(mapping: Mapping[str, Any], key: str) -> float | None:
    try:
        return float(mapping[key])
    except (KeyError, TypeError, ValueError):
        return None


def _position_points(
    stats: Mapping[str, Any], scoring_settings: Mapping[str, Any], positions: Iterable[str]
) -> dict[str, float]:
    result: dict[str, float] = {}
    for position in positions:
        prefix = f"pos_{position.casefold()}_"
        total = 0.0
        found = False
        for stat_key, value in stats.items():
            if not str(stat_key).startswith(prefix) or stat_key not in scoring_settings:
                continue
            try:
                total += float(value) * float(scoring_settings[stat_key])
            except (TypeError, ValueError):
                continue
            found = True
        if found:
            result[position] = round(total, 2)
    return result


def _ownership(rosters: Iterable[Mapping[str, Any]], users: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    user_names = {
        str(user.get("user_id")): str(user.get("display_name") or user.get("username") or "Unknown manager")
        for user in users
        if user.get("user_id") is not None
    }
    result: dict[str, str] = {}
    for roster in rosters:
        metadata = roster.get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        team = str(metadata.get("team_name") or user_names.get(str(roster.get("owner_id"))) or f"Roster {roster.get('roster_id')}")
        for player_id in roster.get("players") or []:
            result[str(player_id)] = team
    return result


def build_injury_opportunities_context(
    *,
    state: object,
    league: object,
    players: object,
    rosters: object,
    users: object,
    stats_rows: object,
    retrieved_at: str | None = None,
) -> InjuryOpportunitiesContext:
    """Normalize complete Sleeper injury flags and affected-club candidates."""

    season, gameweek = _season_week(state)
    if not isinstance(league, Mapping):
        raise SleeperDataError("Sleeper league did not return an object")
    scoring_settings = league.get("scoring_settings")
    scoring_settings = scoring_settings if isinstance(scoring_settings, Mapping) else {}
    if not isinstance(players, Mapping):
        raise SleeperDataError("Sleeper EPL players did not return an object")
    roster_rows = _array(rosters, "league rosters")
    user_rows = _array(users, "league users")
    stat_rows = _array(stats_rows, "current season stats")
    owners = _ownership(roster_rows, user_rows)
    stats_by_id: dict[str, Mapping[str, Any]] = {}
    for row in stat_rows:
        player_id = str(row.get("player_id") or "")
        stats = row.get("stats")
        if player_id and isinstance(stats, Mapping):
            stats_by_id[player_id] = stats

    normalized: list[tuple[str, Mapping[str, Any], str]] = []
    for raw_id, value in players.items():
        if not isinstance(value, Mapping) or not _is_current_epl_player(value):
            continue
        category = _status_category(value.get("injury_status"))
        if category:
            normalized.append((str(value.get("player_id") or raw_id), value, category))
    normalized.sort(key=lambda item: (item[2] != "out", _name(item[0], item[1]).casefold()))
    affected_clubs = {str(player.get("team_abbr") or "").upper() for _, player, _ in normalized}

    def common(player_id: str, player: Mapping[str, Any]) -> dict[str, Any]:
        stats = stats_by_id.get(player_id, {})
        owner = owners.get(player_id)
        positions = [str(item).upper() for item in (player.get("fantasy_positions") or [])]
        position_points = _position_points(stats, scoring_settings, positions)
        return {
            "player_id": player_id,
            "name": _name(player_id, player),
            "club": str(player.get("team_abbr") or "").upper(),
            "positions": positions,
            "ownership": {"rostered": owner is not None, "team": owner},
            "starts": _number(stats, "gs"),
            "minutes": _number(stats, "min"),
            "points": _number(stats, "pts_std"),
            "custom_points": max(position_points.values()) if position_points else None,
            "position_points": position_points,
        }

    injuries = [
        {
            **common(player_id, player),
            "sleeper_status": str(player.get("injury_status") or "").strip(),
            "status_category": category,
        }
        for player_id, player, category in normalized
    ]
    candidates: list[dict[str, Any]] = []
    for raw_id, value in players.items():
        if not isinstance(value, Mapping) or not _is_current_epl_player(value):
            continue
        club = str(value.get("team_abbr") or "").upper()
        if club not in affected_clubs or str(value.get("injury_status") or "").strip():
            continue
        player_id = str(value.get("player_id") or raw_id)
        candidates.append(common(player_id, value))
    candidates.sort(
        key=lambda item: (
            item["club"],
            item["ownership"]["rostered"],
            -(item["custom_points"] or 0),
            -(item["minutes"] or 0),
            item["name"].casefold(),
        )
    )
    timestamp = retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = {
        "season": season,
        "gameweek": gameweek,
        "retrieved_at": timestamp,
        "injured_players": injuries,
        "beneficiary_candidates": candidates,
    }
    return InjuryOpportunitiesContext(season, gameweek, timestamp, payload)


def load_injury_opportunities_context(
    *, client: SleeperClient | None = None, retrieved_at: str | None = None
) -> InjuryOpportunitiesContext:
    """Fetch one complete, read-only Sleeper snapshot for the command."""

    sleeper = client or SleeperClient()
    state = sleeper.get_json(f"{API_BASE}/state/clubsoccer:epl")
    season, _ = _season_week(state)
    return build_injury_opportunities_context(
        state=state,
        league=sleeper.get_json(f"{API_BASE}/league/{LEAGUE_ID}"),
        players=sleeper.get_json(f"{API_BASE}/players/clubsoccer:epl"),
        rosters=sleeper.get_json(f"{API_BASE}/league/{LEAGUE_ID}/rosters"),
        users=sleeper.get_json(f"{API_BASE}/league/{LEAGUE_ID}/users"),
        stats_rows=sleeper.get_json(f"{STATS_BASE}/clubsoccer:epl/{season}?season_type=regular"),
        retrieved_at=retrieved_at,
    )


def parse_injury_research(value: str | Mapping[str, Any]) -> InjuryResearch:
    """Validate the outer research shape; renderer validates every referenced ID."""

    try:
        payload = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError as exc:
        raise ValueError("Injury research returned invalid JSON") from exc
    if not isinstance(payload, Mapping) or not isinstance(payload.get("injuries"), list) or not isinstance(payload.get("opportunities"), list):
        raise ValueError("Injury research returned an invalid result")
    return InjuryResearch(
        tuple(item for item in payload["injuries"] if isinstance(item, dict)),
        tuple(item for item in payload["opportunities"] if isinstance(item, dict)),
    )


def _text(value: object, fallback: str, limit: int = 220) -> str:
    compact = " ".join(str(value or "").split()).strip()
    return (compact[: limit - 1].rstrip() + "…") if len(compact) > limit else (compact or fallback)


def _source_links(value: object) -> str:
    links: list[str] = []
    if isinstance(value, list):
        for source in value[:2]:
            if not isinstance(source, Mapping):
                continue
            url = str(source.get("url") or "").strip()
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                continue
            title = _text(source.get("title"), parsed.netloc, 50).replace("[", "").replace("]", "")
            links.append(f"[{title}]({url})")
    return " · ".join(links)


def render_injury_opportunities(
    context: InjuryOpportunitiesContext,
    research: InjuryResearch | None,
    *,
    research_error: str | None = None,
) -> str:
    """Render every Sleeper flag and only ID-resolved opportunity research."""

    injuries = list(context.payload["injured_players"])
    window = f"Sleeper EPL · {context.season}"
    if context.gameweek is not None:
        window += f" · GW{context.gameweek}"
    lines = ["🩺 **Injury opportunities**", f"*{window} · fetched {context.retrieved_at}*", ""]
    if not injuries:
        return "\n".join(lines + ["Sleeper currently marks no active EPL players Out or GTD/Questionable."])
    research_by_id = {
        str(item.get("player_id")): item for item in (research.injuries if research else ())
    }
    for category, heading in (("out", "🚑 **Out**"), ("doubt", "⚠️ **GTD / Questionable**")):
        selected = [item for item in injuries if item["status_category"] == category]
        if not selected:
            continue
        lines.append(heading)
        for player in selected:
            item = research_by_id.get(player["player_id"], {})
            owner = player["ownership"]["team"]
            ownership = f"Owned · {owner}" if owner else "Unrostered in league"
            detail = _text(item.get("injury_summary"), "Injury details not verified", 170)
            timeline = _text(item.get("return_window"), "No reliable timetable", 100)
            sources = _source_links(item.get("sources"))
            lines.append(
                f"• **{player['name']}** · {player['club']} · {player['sleeper_status']} · {ownership}\n"
                f"  {detail} · **Return:** {timeline}" + (f" · {sources}" if sources else "")
            )
        lines.append("")

    candidates = {item["player_id"]: item for item in context.payload["beneficiary_candidates"]}
    injured = {item["player_id"]: item for item in injuries}
    valid: list[tuple[int, int, dict[str, Any], dict[str, Any], list[dict[str, Any]]]] = []
    seen: set[str] = set()
    for index, opportunity in enumerate(research.opportunities if research else ()):
        player_id = str(opportunity.get("player_id") or "")
        candidate = candidates.get(player_id)
        if candidate is None or player_id in seen:
            continue
        causes = [injured[item] for item in map(str, opportunity.get("injured_player_ids") or []) if item in injured]
        if not causes:
            continue
        seen.add(player_id)
        valid.append((int(candidate["ownership"]["rostered"]), index, opportunity, candidate, causes))
    valid.sort(key=lambda item: (item[0], item[1]))
    lines.append("📈 **Top playing-time opportunities**")
    if not valid:
        if research_error:
            lines.append(f"Live research was unavailable ({_text(research_error, 'unknown error', 120)}), so no role increase is inferred.")
        else:
            lines.append("No beneficiary cleared the current-evidence threshold; no role increase is inferred.")
    for _, _, opportunity, candidate, causes in valid[:MAX_OPPORTUNITIES]:
        owner = candidate["ownership"]["team"]
        ownership = f"Owned · {owner}" if owner else "**Unrostered in league**"
        cause_names = ", ".join(item["name"] for item in causes)
        role = _text(opportunity.get("role_change"), "Role increase not verified", 220)
        confidence = _text(opportunity.get("confidence"), "low", 20).title()
        sources = _source_links(opportunity.get("sources"))
        lines.append(
            f"• **{candidate['name']}** · {candidate['club']} · {ownership}\n"
            f"  Benefits from: {cause_names} · {role} · **Confidence:** {confidence}" + (f" · {sources}" if sources else "")
        )
    lines.extend(("", "*Read-only: confirm the Add option in Sleeper before any manual move.*"))
    return "\n".join(lines)
