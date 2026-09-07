"""Shared deterministic Fantasy intelligence capability entry points.

These wrappers deliberately own no scoring, legality, provider, or model logic.
They expose the existing authoritative engines to Discord and the future Advisor.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping

from .gameweek import GameweekContext, load_gameweek_prepare_context, load_gameweek_recap_context
from .injury_opportunities import InjuryOpportunitiesContext, load_injury_opportunities_context
from .rotation import RotationContext, load_rotation_context
from .sleeper import SleeperClient
from .trade_proposals import TradeProposalContext, load_trade_proposal_context
from .watchlist import WatchlistPlayer
from .watchlist_stats import WatchlistStatsReport, load_current_watchlist_stats


def get_watchlist_stats(
    watched: list[WatchlistPlayer],
    *,
    client: SleeperClient | None = None,
    include_trends: bool = True,
    include_previous_season: bool = True,
) -> WatchlistStatsReport:
    if client is None:
        return load_current_watchlist_stats(
            watched,
            include_trends=include_trends,
            include_previous_season=include_previous_season,
        )
    return load_current_watchlist_stats(
        watched,
        client=client,
        include_trends=include_trends,
        include_previous_season=include_previous_season,
    )


def get_rotation_context(*, manager_id: str, fixture_schedule: object, client: SleeperClient | None = None, now: datetime | None = None) -> RotationContext:
    return load_rotation_context(manager_id=manager_id, fixture_schedule=fixture_schedule, client=client, now=now)


def get_gameweek_prepare_context(*, manager_id: str, client: SleeperClient | None = None) -> GameweekContext:
    return load_gameweek_prepare_context(manager_id=manager_id, client=client)


def get_gameweek_recap_context(*, manager_id: str, client: SleeperClient | None = None) -> GameweekContext:
    return load_gameweek_recap_context(manager_id=manager_id, client=client)


def get_injury_opportunity_context(
    *, manager_id: str | None = None, client: SleeperClient | None = None,
) -> InjuryOpportunitiesContext:
    return load_injury_opportunities_context(client=client, manager_id=manager_id)


def get_trade_context(
    *,
    manager_id: str,
    fixture_schedule: object,
    client: SleeperClient | None = None,
    now: datetime | None = None,
    named_offer: Mapping[str, Iterable[str]] | None = None,
) -> TradeProposalContext:
    return load_trade_proposal_context(
        manager_id=manager_id,
        fixture_schedule=fixture_schedule,
        client=client,
        now=now,
        named_offer=named_offer,
    )
