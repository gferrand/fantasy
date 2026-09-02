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
# workflow. Keep this explicit: public player facts such as injury news,
# minutes, likely starts, and fixtures belong on the lighter web path unless
# the owner asks us to apply them to their team or league.
_LEAGUE_STATE_PATTERN = re.compile(
    r"\b(?:sleeper|waivers?|free\s+agents?|available\s+players?|pickup|pick\s+up|"
    r"drop|swap|replace|roster|squad|my\s+team|my\s+players?|los\s+blancos|"
    r"team\s+fit|fit\s+for\s+my|fantasy\s+points?|league\s+settings?|scoring|"
    r"gameweek|my\s+lineup|set\s+(?:my\s+)?lineup|captain|add\s+option|watchlist)\b",
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
