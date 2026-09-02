"""Explainable routing for private fantasy-advisor conversations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re


class AdvisorRoute(StrEnum):
    """Execution backends for interactive Discord requests."""

    CHAT = "openai_web"
    CODEX = "codex_league"


@dataclass(frozen=True)
class RouteDecision:
    route: AdvisorRoute
    reason: str


# League-state questions need the validated Sleeper packet and the Codex
# workflow.  Keep this explicit and conservative: news questions may mention a
# player, but should not use the heavier league path unless they depend on the
# owner's team or fantasy-league state.
_LEAGUE_STATE_PATTERN = re.compile(
    r"\b(?:sleeper|waivers?|free\s+agents?|available\s+players?|pickup|pick\s+up|"
    r"drop|swap|roster|squad|my\s+team|los\s+blancos|team\s+fit|fit\s+for\s+my|"
    r"fantasy\s+points?|league\s+settings?|scoring|gameweek|fixture|lineup|captain|"
    r"minutes?|starting|starter|add\s+option|watchlist|injur(?:y|ies))\b",
    re.IGNORECASE,
)
_NEWS_PATTERN = re.compile(
    r"\b(?:what\s+happened|news|deal|transfer|rumou?r|latest|report(?:ed)?|"
    r"announc(?:e|ed|ement)|club\s+statement|confirmed?)\b",
    re.IGNORECASE,
)


def route_interactive_request(
    question: str,
    *,
    waiver_analysis: bool = False,
    has_attachment: bool = False,
) -> RouteDecision:
    """Choose the smallest capable backend for an owner DM request."""

    if waiver_analysis:
        return RouteDecision(AdvisorRoute.CODEX, "dedicated waiver analysis requires league data")
    if has_attachment:
        return RouteDecision(AdvisorRoute.CODEX, "attachment analysis stays on the local advisory path")
    if _LEAGUE_STATE_PATTERN.search(question):
        return RouteDecision(AdvisorRoute.CODEX, "request depends on Sleeper, roster, or fantasy-league state")
    if _NEWS_PATTERN.search(question):
        return RouteDecision(AdvisorRoute.CHAT, "current football news can use focused web research")
    return RouteDecision(AdvisorRoute.CHAT, "general question does not require private league data")
