"""Small, explainable historical inputs for the Gameweek forecast.

The forecast deliberately works from Sleeper's raw stat rows.  It does not
pretend that a news article can improve a player's scoring rate: availability
is a minutes-only input and is validated separately by the caller.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .trade_proposals import projection_signal_from_player


MODEL_VERSION = "sleeper-eb-v1"
CURRENT_SHRINKAGE_MINUTES = 540.0
PRIOR_SHRINKAGE_MINUTES = 900.0


def _number(stats: Mapping[str, Any], key: str) -> float:
    try:
        return float(stats.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _row_by_player(rows: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(row.get("player_id")): row for row in rows if str(row.get("player_id") or "").strip()}


def _median(values: Iterable[float], fallback: float = 0.0) -> float:
    ordered = sorted(values)
    if not ordered:
        return fallback
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def historical_inputs(
    signals: list[dict[str, Any]],
    *,
    current_rows: Iterable[Mapping[str, Any]],
    prior_rows: Iterable[Mapping[str, Any]],
    recent_weekly_rows: Iterable[Iterable[Mapping[str, Any]]],
    scoring_settings: Mapping[str, Any],
) -> None:
    """Add empirical-Bayes rate and expected-minute inputs to roster signals.

    Current-season custom scoring is primary.  A prior season is deliberately
    only a stabilizer; players without either history use a position peer rate.
    Recent completed weeks affect minutes, never the production rate itself.
    """
    current_by_id = _row_by_player(current_rows)
    prior_by_id = _row_by_player(prior_rows)
    peer_rates: dict[str, list[float]] = {}
    for row in current_rows:
        player = row.get("player") if isinstance(row.get("player"), Mapping) else {}
        stats = row.get("stats") if isinstance(row.get("stats"), Mapping) else {}
        signal = projection_signal_from_player(str(row.get("player_id") or ""), player, stats, scoring_settings)
        rate = signal.get("custom_points_per_90")
        if not isinstance(rate, (float, int)) or rate < 0:
            continue
        for position in signal.get("positions", []):
            peer_rates.setdefault(str(position).upper(), []).append(float(rate))
    peer_baselines = {position: _median(values) for position, values in peer_rates.items()}

    recent_by_id: dict[str, list[Mapping[str, Any]]] = {}
    for weekly_rows in recent_weekly_rows:
        for row in weekly_rows:
            player_id = str(row.get("player_id") or "").strip()
            if player_id:
                recent_by_id.setdefault(player_id, []).append(row)

    for signal in signals:
        player_id = str(signal["player_id"])
        positions = [str(value).upper() for value in signal.get("positions", [])]
        peer = _median((peer_baselines[position] for position in positions if position in peer_baselines))
        current_rate = signal.get("custom_points_per_90")
        current_rate = float(current_rate) if isinstance(current_rate, (float, int)) else None
        prior_row = prior_by_id.get(player_id)
        prior_signal = projection_signal_from_player(
            player_id,
            prior_row.get("player") if isinstance(prior_row, Mapping) and isinstance(prior_row.get("player"), Mapping) else {"fantasy_positions": positions},
            prior_row.get("stats") if isinstance(prior_row, Mapping) and isinstance(prior_row.get("stats"), Mapping) else {},
            scoring_settings,
        )
        prior_rate = prior_signal.get("custom_points_per_90")
        prior_rate = float(prior_rate) if isinstance(prior_rate, (float, int)) else None
        current_minutes = float(signal.get("minutes") or 0.0)
        prior_minutes = float(prior_signal.get("minutes") or 0.0)
        current_weight = min(1.0, current_minutes / CURRENT_SHRINKAGE_MINUTES)
        prior_weight = min(1.0, prior_minutes / PRIOR_SHRINKAGE_MINUTES)
        current_blend = (current_rate * current_weight + peer * (1 - current_weight)) if current_rate is not None else peer
        prior_blend = (prior_rate * prior_weight + peer * (1 - prior_weight)) if prior_rate is not None else None
        # Current evidence dominates whenever it exists.  Prior evidence has a
        # useful early-season role without ever becoming the leading signal.
        rate = current_blend if prior_blend is None else current_blend * 0.72 + prior_blend * 0.28

        current_games = float(signal.get("games") or 0.0)
        prior_games = float(prior_signal.get("games") or 0.0)
        components: list[tuple[float, float]] = []
        if current_games > 0:
            components.append((current_minutes / current_games, 0.35))
        if prior_games > 0:
            components.append((prior_minutes / prior_games, 0.15))
        recent_minutes = [
            _number(row.get("stats") if isinstance(row.get("stats"), Mapping) else {}, "min")
            for row in recent_by_id.get(player_id, [])
        ]
        if recent_minutes:
            components.append((sum(recent_minutes) / len(recent_minutes), 0.50))
        if components:
            denominator = sum(weight for _value, weight in components)
            expected_minutes = sum(value * weight for value, weight in components) / denominator
        else:
            expected_minutes = 60.0
        signal.update({
            "forecast_model_version": MODEL_VERSION,
            "forecast_rate_per_90_input": round(rate, 3),
            "forecast_peer_rate_per_90": round(peer, 3),
            "forecast_expected_minutes_input": round(min(90.0, max(0.0, expected_minutes)), 1),
            "forecast_current_minutes": current_minutes,
            "forecast_prior_minutes": prior_minutes,
            "forecast_recent_week_count": len(recent_minutes),
            "forecast_prior_row_available": prior_row is not None,
            "forecast_current_row_available": player_id in current_by_id,
        })
