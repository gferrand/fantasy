"""Read-only, roster-aware Sleeper trade proposal generation.

The public Sleeper API exposes current rosters and league scoring but not trade
preferences, private negotiations, or an acceptance probability.  This module
therefore does two deliberately separate jobs:

* calculate current custom-scoring lineup effects and player-only equity from
  live Sleeper data; and
* expose only mutually viable packages for a later expert-research briefing.

It never creates a Sleeper transaction.  The acceptance band attached to an
option is a bounded *plausibility heuristic*, not a prediction about a manager.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
import json
from typing import Any, Iterable, Mapping

from .gameweek import LEAGUE_ID
from .lineup_alerts import CLUB_ABBRS
from .sleeper import API_BASE, STATS_BASE, SleeperClient, SleeperDataError


MAX_PLAYERS_PER_PACKAGE = 2
MAX_PLAYERS_IN_TRADE = 3
# Six per roster keeps the legal-lineup search bounded for an on-demand Discord
# command while still covering the leading current-market assets on each team.
MAX_CANDIDATES_PER_TEAM = 6
FORECAST_FIXTURE_HORIZON = 6
FORECAST_SHRINKAGE_MINUTES = 540.0
INACTIVE_INJURY_STATUSES = {"IR", "IR+", "O", "OUT", "SUSP"}


@dataclass(frozen=True)
class LineupEvaluation:
    """A best legal lineup scored from current custom season totals."""

    score: float
    player_ids: tuple[str, ...]


@dataclass(frozen=True)
class TradeProposalContext:
    """Bounded Sleeper data and fairness-checked offers for web research."""

    season: str
    gameweek: int
    retrieved_at: str
    payload: dict[str, Any]

    def as_json(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False, separators=(",", ":"))


def _number(mapping: Mapping[str, Any], key: str) -> float | None:
    try:
        return float(mapping[key])
    except (KeyError, TypeError, ValueError):
        return None


def _validate_array(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise SleeperDataError(f"Sleeper {label} did not return an array")
    return [item for item in value if isinstance(item, Mapping)]


def _season_and_week(state: object) -> tuple[str, int]:
    if not isinstance(state, Mapping):
        raise SleeperDataError("Sleeper EPL state did not return an object")
    season = str(state.get("season") or "").strip()
    if not season.isdigit() or len(season) != 4:
        raise SleeperDataError("Sleeper EPL state did not include a current season")
    try:
        week = int(state.get("display_week") or state["week"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SleeperDataError("Sleeper EPL state did not include a current gameweek") from exc
    if week < 1:
        raise SleeperDataError("Sleeper EPL state included an invalid gameweek")
    return season, week


def _player_name(player_id: str, player: Mapping[str, Any]) -> str:
    metadata = player.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    return str(
        player.get("full_name")
        or metadata.get("full_name")
        or " ".join(str(value) for value in (player.get("first_name"), player.get("last_name")) if value)
        or f"Unknown player {player_id}"
    ).strip()


def _position_score(
    stats: Mapping[str, Any], scoring_settings: Mapping[str, Any], position: str
) -> float | None:
    """Calculate a player's live custom total for one Sleeper position."""

    prefix = f"pos_{position.casefold()}_"
    total = 0.0
    found = False
    for stat_key, raw_value in stats.items():
        if not str(stat_key).startswith(prefix) or stat_key not in scoring_settings:
            continue
        try:
            total += float(raw_value) * float(scoring_settings[stat_key])
        except (TypeError, ValueError):
            continue
        found = True
    return round(total, 2) if found else None


def _player_from_row(
    player_id: str,
    row: Mapping[str, Any] | None,
    scoring_settings: Mapping[str, Any],
) -> dict[str, Any]:
    row = row if isinstance(row, Mapping) else {}
    player = row.get("player")
    player = player if isinstance(player, Mapping) else {}
    stats = row.get("stats")
    stats = stats if isinstance(stats, Mapping) else {}
    positions = [str(item).upper() for item in (player.get("fantasy_positions") or []) if str(item).strip()]
    position_points = {
        position: value
        for position in positions
        if (value := _position_score(stats, scoring_settings, position)) is not None
    }
    minutes = _number(stats, "min")
    current_points = max(position_points.values()) if position_points else 0.0
    return {
        "player_id": str(player_id),
        "name": _player_name(str(player_id), player),
        "club": str(player.get("team_abbr") or "").upper() or None,
        "positions": positions,
        "injury_status": str(player.get("injury_status") or "").upper() or None,
        "current_custom_points": round(current_points, 2),
        "position_points": position_points,
        "games": _number(stats, "gp"),
        "starts": _number(stats, "gs"),
        "minutes": minutes,
        "custom_points_per_90": (
            round(current_points * 90 / minutes, 2) if minutes is not None and minutes > 0 else None
        ),
        "scoring_data_available": bool(position_points),
    }


def _parse_kickoff(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _fixture_sides(event: Mapping[str, Any]) -> tuple[str, str, float | None, float | None] | None:
    competitions = event.get("competitions")
    competition = competitions[0] if isinstance(competitions, list) and competitions else None
    if not isinstance(competition, Mapping):
        return None
    competitors = competition.get("competitors")
    if not isinstance(competitors, list):
        return None
    sides: dict[str, tuple[str, float | None]] = {}
    for competitor in competitors:
        if not isinstance(competitor, Mapping) or not isinstance(competitor.get("team"), Mapping):
            continue
        side = str(competitor.get("homeAway") or "")
        name = str(competitor["team"].get("displayName") or "").strip()
        club = CLUB_ABBRS.get(name)
        if side not in {"home", "away"} or not club:
            continue
        try:
            score = float(competitor.get("score"))
        except (TypeError, ValueError):
            score = None
        sides[side] = (club, score)
    if set(sides) != {"home", "away"}:
        return None
    home, home_score = sides["home"]
    away, away_score = sides["away"]
    return home, away, home_score, away_score


def _fixture_is_completed(event: Mapping[str, Any], kickoff: datetime, now: datetime) -> bool:
    competitions = event.get("competitions")
    competition = competitions[0] if isinstance(competitions, list) and competitions else None
    status = competition.get("status") if isinstance(competition, Mapping) else None
    status_type = status.get("type") if isinstance(status, Mapping) else None
    if isinstance(status_type, Mapping) and status_type.get("completed") is True:
        return True
    # A historical cached event with two numeric scores is usable even if the
    # provider omitted the nested completion flag.
    sides = _fixture_sides(event)
    return bool(sides and kickoff < now and sides[2] is not None and sides[3] is not None)


def _club_strengths(schedule: object, *, now: datetime) -> tuple[dict[str, float], float]:
    """Estimate opponent strength from completed local-schedule results only.

    Early-season points per game are shrunk toward the observed league average
    over six matches. This deliberately avoids declaring a two-match hot start
    to be a permanent team-strength signal.
    """

    events = schedule.get("events") if isinstance(schedule, Mapping) else None
    table: dict[str, dict[str, float]] = {}
    if isinstance(events, list):
        for raw in events:
            if not isinstance(raw, Mapping):
                continue
            kickoff = _parse_kickoff(raw.get("date"))
            sides = _fixture_sides(raw)
            if kickoff is None or sides is None or not _fixture_is_completed(raw, kickoff, now):
                continue
            home, away, home_score, away_score = sides
            if home_score is None or away_score is None:
                continue
            for club in (home, away):
                table.setdefault(club, {"played": 0.0, "points": 0.0})
                table[club]["played"] += 1
            if home_score > away_score:
                table[home]["points"] += 3
            elif away_score > home_score:
                table[away]["points"] += 3
            else:
                table[home]["points"] += 1
                table[away]["points"] += 1
    total_played = sum(row["played"] for row in table.values())
    total_points = sum(row["points"] for row in table.values())
    league_ppg = total_points / total_played if total_played else 1.3
    strengths = {
        club: (row["points"] + league_ppg * 6) / (row["played"] + 6)
        for club, row in table.items()
    }
    return strengths, league_ppg


def _fixtures_for_club(
    schedule: object, *, club: str, now: datetime
) -> list[tuple[datetime, str, bool]]:
    """Return every remaining locally-published fixture for one club."""

    events = schedule.get("events") if isinstance(schedule, Mapping) else None
    fixtures: list[tuple[datetime, str, bool]] = []
    if not isinstance(events, list):
        return fixtures
    for raw in events:
        if not isinstance(raw, Mapping):
            continue
        kickoff = _parse_kickoff(raw.get("date"))
        sides = _fixture_sides(raw)
        if kickoff is None or sides is None or kickoff <= now:
            continue
        home, away, _home_score, _away_score = sides
        if club == home:
            fixtures.append((kickoff, away, True))
        elif club == away:
            fixtures.append((kickoff, home, False))
    return sorted(fixtures, key=lambda fixture: fixture[0])


def _median(values: Iterable[float], *, fallback: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return fallback
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return round((ordered[middle - 1] + ordered[middle]) / 2, 4)


def apply_fixture_adjusted_projections(
    players: Iterable[dict[str, Any]],
    *,
    schedule: object,
    now: datetime,
    horizon: int = FORECAST_FIXTURE_HORIZON,
) -> None:
    """Attach transparent fixture-adjusted short-horizon projections in place.

    Each player rate is shrunk toward their position-peer median when minutes
    are thin, then adjusted by the local schedule's opponent-strength run. It
    is deliberately a modest, explainable projection rather than a claim that
    past points alone predict future outcomes.
    """

    if horizon < 1:
        raise ValueError("forecast fixture horizon must be positive")
    player_list = list(players)
    strengths, league_ppg = _club_strengths(schedule, now=now)
    observed_strengths = list(strengths.values())
    fallback_strength = _median(observed_strengths, fallback=league_ppg)
    peer_rates: dict[str, list[float]] = {}
    for player in player_list:
        rate = player.get("custom_points_per_90")
        positions = player.get("positions") or []
        if not isinstance(rate, (int, float)) or rate < 0:
            continue
        for position in positions:
            peer_rates.setdefault(str(position).upper(), []).append(float(rate))
    position_medians = {
        position: _median(rates, fallback=0.0) for position, rates in peer_rates.items()
    }

    for player in player_list:
        club = str(player.get("club") or "").upper()
        fixtures = _fixtures_for_club(schedule, club=club, now=now)
        upcoming = fixtures[:horizon]
        all_remaining = fixtures
        positions = [str(position).upper() for position in (player.get("positions") or [])]
        peer_rate = _median(
            (position_medians.get(position, 0.0) for position in positions), fallback=0.0
        )
        raw_rate = player.get("custom_points_per_90")
        raw_rate = float(raw_rate) if isinstance(raw_rate, (int, float)) else peer_rate
        minutes = player.get("minutes")
        minutes = float(minutes) if isinstance(minutes, (int, float)) else 0.0
        reliability = min(1.0, minutes / FORECAST_SHRINKAGE_MINUTES)
        blended_rate = round(raw_rate * reliability + peer_rate * (1.0 - reliability), 3)
        games = player.get("games")
        games = float(games) if isinstance(games, (int, float)) else 0.0
        expected_minutes = min(90.0, max(20.0, minutes / games if games > 0 else 60.0))

        def difficulty(fixture: tuple[datetime, str, bool]) -> float:
            _kickoff, opponent, is_home = fixture
            strength = strengths.get(opponent, fallback_strength)
            # 3 is league-neutral; road matches receive a small known-context
            # adjustment. Values are intentionally bounded and descriptive.
            return round(min(5.0, max(1.0, 3.0 + (strength - league_ppg) * 1.5 + (-0.2 if is_home else 0.2))), 2)

        next_difficulties = [difficulty(fixture) for fixture in upcoming]
        remaining_difficulties = [difficulty(fixture) for fixture in all_remaining]
        next_average = _median(next_difficulties, fallback=3.0)
        remaining_average = _median(remaining_difficulties, fallback=3.0)
        fixture_multiplier = round(min(1.35, max(0.65, 1.0 - (next_average - 3.0) * 0.12)), 3)
        baseline_points = round(blended_rate * expected_minutes * len(upcoming) / 90, 2)
        projected_points = round(baseline_points * fixture_multiplier, 2)
        player.update(
            {
                "forecast_horizon_fixtures": len(upcoming),
                "forecast_horizon": f"next {horizon} published fixtures",
                "forecast_blended_points_per_90": blended_rate,
                "forecast_expected_minutes_per_fixture": round(expected_minutes, 1),
                "forecast_fixture_difficulty": next_average,
                "forecast_remaining_fixture_difficulty": remaining_average,
                "forecast_fixture_multiplier": fixture_multiplier,
                "forecast_baseline_points": baseline_points,
                "projected_horizon_points": projected_points,
                "forecast_fixture_adjustment": round(projected_points - baseline_points, 2),
                "forecast_next_fixtures": [
                    {
                        "opponent": opponent,
                        "home": is_home,
                        "kickoff_utc": kickoff.isoformat(),
                        "difficulty": difficulty((kickoff, opponent, is_home)),
                    }
                    for kickoff, opponent, is_home in upcoming
                ],
            }
        )


def _team_name(users: Iterable[Mapping[str, Any]], owner_id: object, roster_id: object) -> str:
    user = next((item for item in users if str(item.get("user_id")) == str(owner_id)), None)
    if user is not None:
        metadata = user.get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        name = str(metadata.get("team_name") or user.get("display_name") or "").strip()
        if name:
            return name
    return f"Roster {roster_id}"


def _starting_slots(league: Mapping[str, Any]) -> tuple[str, ...]:
    bench_labels = {"BN", "BENCH", "IR", "TAXI", "RESERVE"}
    slots = tuple(
        str(value).upper()
        for value in (league.get("roster_positions") or [])
        if str(value).upper() not in bench_labels
    )
    if not slots:
        raise SleeperDataError("Sleeper league settings did not include starting roster slots")
    return slots


def _slot_matches(slot: str, positions: Iterable[str]) -> bool:
    """Return whether a Sleeper player can fill a regular or documented flex slot."""

    player_positions = {str(position).upper() for position in positions}
    slot = slot.upper()
    if slot in player_positions:
        return True
    # Sleeper's EPL roster uses GK while player metadata may use G.
    if slot == "GK" and "G" in player_positions:
        return True
    if slot == "G" and "GK" in player_positions:
        return True
    if slot in {"FLEX", "UTIL", "ANY"}:
        return bool(player_positions)
    if slot.endswith("_FLEX"):
        prefix = slot.removesuffix("_FLEX")
        # EPL's FM_FLEX and MD_FLEX are compact position combinations.
        allowed = set(prefix) if prefix.isalpha() else set()
        return bool(player_positions.intersection(allowed))
    return False


def _slot_score(slot: str, player: Mapping[str, Any]) -> float:
    """Return the configured score for the position actually filling a slot."""

    position_points = player.get("position_points")
    position_points = position_points if isinstance(position_points, Mapping) else {}
    slot = slot.upper()
    allowed: set[str]
    if slot in {"FLEX", "UTIL", "ANY"}:
        allowed = {str(position).upper() for position in position_points}
    elif slot.endswith("_FLEX"):
        prefix = slot.removesuffix("_FLEX")
        allowed = set(prefix) if prefix.isalpha() else set()
    elif slot == "GK":
        allowed = {"GK", "G"}
    elif slot == "G":
        allowed = {"G", "GK"}
    else:
        allowed = {slot}
    scores = []
    for position, value in position_points.items():
        if str(position).upper() not in allowed:
            continue
        try:
            scores.append(float(value))
        except (TypeError, ValueError):
            continue
    if scores:
        return max(scores)
    try:
        return float(player.get("current_custom_points") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def evaluate_lineup(
    players: Iterable[Mapping[str, Any]],
    slots: Iterable[str],
    *,
    score_field: str = "current_custom_points",
) -> LineupEvaluation:
    """Maximize current custom-scoring totals across a legal Sleeper lineup.

    The dynamic program fills each actual starting slot at most once, handles
    multi-position players correctly, and does not mistake a deep bench for a
    legal starting lineup.
    """

    slot_list = tuple(str(slot).upper() for slot in slots)
    if len(slot_list) > 20:  # Defensive bound: the state space is 2**slots.
        raise SleeperDataError("Sleeper league has too many starting slots to evaluate safely")
    states: dict[int, tuple[float, tuple[str, ...]]] = {0: (0.0, ())}
    for raw_player in players:
        player_id = str(raw_player.get("player_id") or "").strip()
        if not player_id:
            continue
        eligible_slots = [
            index
            for index, slot in enumerate(slot_list)
            if _slot_matches(slot, raw_player.get("positions") or [])
        ]
        if not eligible_slots:
            continue
        updated = dict(states)
        for mask, (score, assigned_ids) in states.items():
            for slot_index in eligible_slots:
                bit = 1 << slot_index
                if mask & bit:
                    continue
                if score_field == "current_custom_points":
                    points = _slot_score(slot_list[slot_index], raw_player)
                else:
                    try:
                        points = float(raw_player.get(score_field) or 0.0)
                    except (TypeError, ValueError):
                        points = 0.0
                candidate = (round(score + points, 2), assigned_ids + (player_id,))
                previous = updated.get(mask | bit)
                if previous is None or candidate[0] > previous[0]:
                    updated[mask | bit] = candidate
        states = updated
    complete = states.get((1 << len(slot_list)) - 1)
    if complete is None:
        raise SleeperDataError("A legal current lineup could not be formed from a Sleeper roster")
    return LineupEvaluation(score=round(complete[0], 2), player_ids=complete[1])


def _remaining_faab(roster: Mapping[str, Any], league: Mapping[str, Any]) -> int | None:
    settings = league.get("settings")
    settings = settings if isinstance(settings, Mapping) else {}
    budget = _number(settings, "waiver_budget")
    if budget is None or budget <= 0:
        return None
    roster_settings = roster.get("settings")
    roster_settings = roster_settings if isinstance(roster_settings, Mapping) else {}
    spent = _number(roster_settings, "waiver_budget_used") or 0.0
    return max(0, int(round(budget - spent)))


def _display_player(player: Mapping[str, Any]) -> dict[str, Any]:
    """Return only the decision data needed by the trade briefing."""

    return {
        key: player.get(key)
        for key in (
            "player_id",
            "name",
            "club",
            "positions",
            "injury_status",
            "current_custom_points",
            "custom_points_per_90",
            "games",
            "starts",
            "minutes",
            "forecast_horizon_fixtures",
            "forecast_blended_points_per_90",
            "forecast_fixture_difficulty",
            "forecast_remaining_fixture_difficulty",
            "forecast_fixture_multiplier",
            "forecast_baseline_points",
            "projected_horizon_points",
            "forecast_fixture_adjustment",
            "forecast_next_fixtures",
        )
    }


def _package_value(players: Iterable[Mapping[str, Any]]) -> float:
    return round(sum(float(player.get("current_custom_points") or 0.0) for player in players), 2)


def _roster_after(
    roster_players: Iterable[Mapping[str, Any]],
    *,
    remove_ids: Iterable[str],
    add_players: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    removed = {str(player_id) for player_id in remove_ids}
    result = [dict(player) for player in roster_players if str(player.get("player_id")) not in removed]
    result.extend(dict(player) for player in add_players)
    return result


def _candidate_players(
    players: Iterable[Mapping[str, Any]],
    *,
    market_side: str,
    limit: int = MAX_CANDIDATES_PER_TEAM,
) -> list[dict[str, Any]]:
    """Keep a bounded sell-high or buy-low pool for package construction."""

    if market_side not in {"send", "receive"}:
        raise ValueError("market_side must be 'send' or 'receive'")

    eligible = []
    for raw in players:
        player = dict(raw)
        if not player.get("scoring_data_available") or not player.get("positions"):
            continue
        if float(player.get("current_custom_points") or 0.0) <= 0:
            continue
        if "forecast_horizon_fixtures" in player and int(player["forecast_horizon_fixtures"] or 0) < 1:
            continue
        if str(player.get("injury_status") or "").upper() in INACTIVE_INJURY_STATUSES:
            continue
        eligible.append(player)
    if market_side == "send":
        # These are marketable assets: real points already on the board plus a
        # potentially deteriorating fixture run create an honest sell-high
        # opportunity without inventing a decline.
        key = lambda player: (
            float(player.get("current_custom_points") or 0.0),
            -float(player.get("forecast_fixture_adjustment") or 0.0),
            float(player.get("minutes") or 0.0),
            str(player.get("name") or "").casefold(),
        )
    else:
        # Targets are chosen for the forecast, not merely the score that every
        # other manager can already see in the standings.
        key = lambda player: (
            float(player.get("projected_horizon_points") or player.get("current_custom_points") or 0.0),
            float(player.get("forecast_fixture_adjustment") or 0.0),
            float(player.get("custom_points_per_90") or 0.0),
            str(player.get("name") or "").casefold(),
        )
    return sorted(eligible, key=key, reverse=True)[:limit]


def _packages(players: list[dict[str, Any]]) -> tuple[list[tuple[dict[str, Any], ...]], list[tuple[dict[str, Any], ...]]]:
    singles = [(player,) for player in players]
    pairs = [tuple(pair) for pair in combinations(players, MAX_PLAYERS_PER_PACKAGE)]
    return singles, pairs


def _faab_sweetener(*, equity_ratio: float, remaining_faab: int | None) -> int | None:
    """Suggest a modest FAAB sweetener only for a near-equitable offer.

    FAAB has no Sleeper point conversion, so it is intentionally excluded from
    player-equity arithmetic.  This simply gives the recipient a small tangible
    reason to consider a slightly player-light but otherwise viable package.
    """

    if remaining_faab is None or remaining_faab < 1 or equity_ratio >= 0.94:
        return None
    if equity_ratio < 0.80:
        return None
    percentage_shortfall = max(0.0, 1.0 - equity_ratio)
    return min(remaining_faab, max(3, min(15, int(round(percentage_shortfall * 100)))))


def _acceptance_band(
    *, owner_projection_gain: float, partner_gain: float, equity_ratio: float, faab_offer: int | None
) -> dict[str, Any]:
    """Create an explicitly non-predictive 30--50% plausibility band."""

    partner_bonus = min(8, int(round(max(0.0, partner_gain) / 4)))
    equity_bonus = min(5, int(round(max(0.0, 1.0 - abs(1.0 - equity_ratio)) * 5)))
    faab_bonus = 2 if faab_offer else 0
    low = min(40, 30 + partner_bonus + equity_bonus + faab_bonus)
    high = min(50, low + 10)
    return {
        "range": f"{low}-{high}%",
        "low": low,
        "high": high,
        "method": (
            "Heuristic only: current player-only equity plus the recipient's "
            "before/after starting-lineup score. It cannot observe manager preferences, messages, or trade history."
        ),
        "partner_lineup_score_gain": round(partner_gain, 2),
        "owner_projected_lineup_gain": round(owner_projection_gain, 2),
    }


def build_trade_options(
    *,
    owner_team: Mapping[str, Any],
    partner_teams: Iterable[Mapping[str, Any]],
    starting_slots: Iterable[str],
) -> list[dict[str, Any]]:
    """Return up to three mutually viable two- or three-player packages.

    A package is eligible only when the owner's legal, current custom-scoring
    lineup improves, the other manager's legal lineup also improves, and the
    player-only value is close enough to be a credible conversation starter.
    This is intentionally a stricter bar than finding a lopsided upgrade.
    """

    slots = tuple(starting_slots)
    owner_players = [dict(player) for player in owner_team.get("players") or []]
    owner_before = evaluate_lineup(owner_players, slots)
    owner_projection_before = evaluate_lineup(
        owner_players, slots, score_field="projected_horizon_points"
    )
    outgoing_candidates = _candidate_players(owner_players, market_side="send")
    outgoing_singles, outgoing_pairs = _packages(outgoing_candidates)
    raw_options: list[dict[str, Any]] = []

    for partner in partner_teams:
        partner_players = [dict(player) for player in partner.get("players") or []]
        try:
            partner_before = evaluate_lineup(partner_players, slots)
        except SleeperDataError:
            # A roster with stale or missing player metadata cannot support an
            # honest before/after comparison, so it is not a trade target.
            continue
        incoming_candidates = _candidate_players(partner_players, market_side="receive")
        incoming_singles, incoming_pairs = _packages(incoming_candidates)
        package_shapes = (
            (incoming_singles, outgoing_singles),  # 1-for-1
            (incoming_singles, outgoing_pairs),    # 2-for-1 from owner
            (incoming_pairs, outgoing_singles),    # 1-for-2 from owner
        )
        for incoming, outgoing in package_shapes:
            for receive in incoming:
                receive_value = _package_value(receive)
                if receive_value <= 0:
                    continue
                for send in outgoing:
                    if len(receive) + len(send) > MAX_PLAYERS_IN_TRADE:
                        continue
                    send_value = _package_value(send)
                    if send_value <= 0:
                        continue
                    equity_ratio = round(send_value / receive_value, 3)
                    if not 0.80 <= equity_ratio <= 1.15:
                        continue
                    faab_offer = _faab_sweetener(
                        equity_ratio=equity_ratio,
                        remaining_faab=owner_team.get("remaining_faab"),
                    )
                    try:
                        owner_after_players = _roster_after(
                            owner_players,
                            remove_ids=(player["player_id"] for player in send),
                            add_players=receive,
                        )
                        owner_after = evaluate_lineup(owner_after_players, slots)
                        owner_projection_after = evaluate_lineup(
                            owner_after_players, slots, score_field="projected_horizon_points"
                        )
                        partner_after = evaluate_lineup(
                            _roster_after(
                                partner_players,
                                remove_ids=(player["player_id"] for player in receive),
                                add_players=send,
                            ),
                            slots,
                        )
                    except SleeperDataError:
                        # A proposal may not strip either manager below a legal lineup.
                        continue
                    owner_gain = round(owner_after.score - owner_before.score, 2)
                    owner_projection_gain = round(
                        owner_projection_after.score - owner_projection_before.score, 2
                    )
                    partner_gain = round(partner_after.score - partner_before.score, 2)
                    # The owner's edge is forward-looking; the recipient sees
                    # an immediate current-scoring improvement, which makes an
                    # equitable sell-high / buy-low conversation more credible.
                    if owner_projection_gain <= 0 or partner_gain <= 0:
                        continue
                    acceptance = _acceptance_band(
                        owner_projection_gain=owner_projection_gain,
                        partner_gain=partner_gain,
                        equity_ratio=equity_ratio,
                        faab_offer=faab_offer,
                    )
                    raw_options.append(
                        {
                            "partner_team": partner["name"],
                            "partner_roster_id": partner["roster_id"],
                            "you_send": [_display_player(player) for player in send],
                            "you_receive": [_display_player(player) for player in receive],
                            "faab_offer": faab_offer,
                            "package_shape": f"{len(send)}-for-{len(receive)}",
                            "math": {
                                "lineup_score_basis": "current-season custom Sleeper points to date",
                                "your_before": owner_before.score,
                                "your_after": owner_after.score,
                                "your_lineup_gain": owner_gain,
                                "your_projected_before": owner_projection_before.score,
                                "your_projected_after": owner_projection_after.score,
                                "your_projected_lineup_gain": owner_projection_gain,
                                "projection_horizon": next(
                                    (
                                        str(player.get("forecast_horizon") or "")
                                        for player in (*send, *receive)
                                        if player.get("forecast_horizon")
                                    ),
                                    "next published fixtures",
                                ),
                                "partner_before": partner_before.score,
                                "partner_after": partner_after.score,
                                "partner_lineup_gain": partner_gain,
                                "your_offer_player_points": send_value,
                                "your_request_player_points": receive_value,
                                "player_equity_ratio": equity_ratio,
                                "faab_included_in_point_math": False,
                            },
                            "acceptance_plausibility": acceptance,
                            # Ranking is deterministic and does not claim a projection.
                            "_rank": round(
                                owner_projection_gain * 3
                                + partner_gain * 2
                                - abs(1.0 - equity_ratio) * 10
                                - (len(send) + len(receive)) * 0.1,
                                4,
                            ),
                        }
                    )

    selected: list[dict[str, Any]] = []
    seen: set[tuple[object, frozenset[str], frozenset[str]]] = set()
    for option in sorted(
        raw_options,
        key=lambda item: (
            item["_rank"],
            item["math"]["your_projected_lineup_gain"],
            item["math"]["partner_lineup_gain"],
            -abs(1.0 - item["math"]["player_equity_ratio"]),
        ),
        reverse=True,
    ):
        identity = (
            option["partner_roster_id"],
            frozenset(player["player_id"] for player in option["you_send"]),
            frozenset(player["player_id"] for player in option["you_receive"]),
        )
        if identity in seen:
            continue
        seen.add(identity)
        option.pop("_rank", None)
        selected.append(option)
        if len(selected) == 3:
            break
    return selected


def load_trade_proposal_context(
    *,
    manager_id: str,
    client: SleeperClient | None = None,
    retrieved_at: str | None = None,
    fixture_schedule: object | None = None,
    now: datetime | None = None,
) -> TradeProposalContext:
    """Load live league data and construct bounded, read-only trade packages."""

    if fixture_schedule is None:
        raise SleeperDataError(
            "The local Premier League fixture schedule is required for fixture-adjusted trade projections"
        )
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    sleeper = client or SleeperClient()
    state = sleeper.get_json(f"{API_BASE}/state/clubsoccer:epl")
    season, gameweek = _season_and_week(state)
    league = sleeper.get_json(f"{API_BASE}/league/{LEAGUE_ID}")
    rosters = _validate_array(sleeper.get_json(f"{API_BASE}/league/{LEAGUE_ID}/rosters"), "league rosters")
    users = _validate_array(sleeper.get_json(f"{API_BASE}/league/{LEAGUE_ID}/users"), "league users")
    rows = _validate_array(
        sleeper.get_json(f"{STATS_BASE}/clubsoccer:epl/{season}?season_type=regular"), "current season stats"
    )
    if not isinstance(league, Mapping):
        raise SleeperDataError("Sleeper league settings did not return an object")
    scoring_settings = league.get("scoring_settings")
    if not isinstance(scoring_settings, Mapping) or not scoring_settings:
        raise SleeperDataError("Sleeper league custom scoring settings are unavailable")
    slots = _starting_slots(league)
    stats_by_id = {
        str(row.get("player_id")): row
        for row in rows
        if str(row.get("player_id") or "").strip()
    }
    all_player_signals = [
        _player_from_row(player_id, row, scoring_settings)
        for player_id, row in stats_by_id.items()
    ]
    apply_fixture_adjusted_projections(
        all_player_signals,
        schedule=fixture_schedule,
        now=current_time,
    )
    projections_by_id = {str(player["player_id"]): player for player in all_player_signals}
    owner_roster = next((roster for roster in rosters if str(roster.get("owner_id")) == str(manager_id)), None)
    if owner_roster is None:
        raise SleeperDataError("Your current Sleeper roster could not be found")

    teams = []
    for roster in rosters:
        player_ids = [str(player_id) for player_id in (roster.get("players") or []) if str(player_id)]
        teams.append(
            {
                "name": _team_name(users, roster.get("owner_id"), roster.get("roster_id")),
                "roster_id": roster.get("roster_id"),
                "owner_id": str(roster.get("owner_id") or ""),
                "players": [
                    {
                        **_player_from_row(player_id, stats_by_id.get(player_id), scoring_settings),
                        **{
                            key: value
                            for key, value in projections_by_id.get(player_id, {}).items()
                            if key.startswith("forecast_") or key == "projected_horizon_points"
                        },
                    }
                    for player_id in player_ids
                ],
                "remaining_faab": _remaining_faab(roster, league),
            }
        )
    owner_team = next(team for team in teams if team["owner_id"] == str(manager_id))
    owner_lineup = evaluate_lineup(owner_team["players"], slots)
    options = build_trade_options(
        owner_team=owner_team,
        partner_teams=(team for team in teams if team["owner_id"] != str(manager_id)),
        starting_slots=slots,
    )
    payload = {
        "source": "live Sleeper EPL",
        "report": "read-only trade proposal",
        "season": season,
        "gameweek": gameweek,
        "retrieved_at": retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "your_team": {
            "name": owner_team["name"],
            "roster_id": owner_team["roster_id"],
            "remaining_faab": owner_team["remaining_faab"],
            "current_lineup_score_to_date": owner_lineup.score,
            "starting_slots": list(slots),
        },
        "candidate_packages": options,
        "limitations": {
            "read_only": True,
            "no_sleeper_trade_created_or_simulated": True,
            "score_math": (
                "Lineup comparisons use current-season custom Sleeper points to date. "
                "They are a mathematical signal, not a rest-of-season projection."
            ),
            "fixture_projection": (
                "The trade edge uses the next six fixtures from the locally downloaded full-season calendar, "
                "opponent strength from completed local-schedule results, and minute-weighted player rates."
            ),
            "acceptance": (
                "Sleeper does not expose private manager preferences, negotiations, or a calibrated acceptance probability."
            ),
        },
    }
    return TradeProposalContext(season, gameweek, payload["retrieved_at"], payload)
