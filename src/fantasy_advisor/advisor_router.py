"""LLM-based execution routing for private fantasy-advisor conversations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any


class AdvisorRoute(StrEnum):
    """Execution backends for interactive Discord requests."""

    CHAT = "openai_web"
    CODEX = "codex_league"


@dataclass(frozen=True)
class RouteDecision:
    route: AdvisorRoute
    reason: str


class RoutingError(RuntimeError):
    """Raised when the LLM router cannot make a valid routing decision."""


ROUTING_CAPABILITIES = """You route private Discord messages for a read-only fantasy
Premier League advisor. Choose the smallest backend that can answer correctly.

CODEX LEAGUE ANALYSIS can read the advisor's current Sleeper league snapshot and
project context. It can reason about the owner's roster, other managers' rosters,
trade possibilities, player ownership and availability, league scoring, lineups,
waivers, free agents, watchlist, fixtures as they affect this particular league,
and prior conversation context. It can also do bounded public football research.
It is read-only: it cannot make Sleeper transactions.

WEB RESEARCH can research public football news, transfers, injuries, fixtures,
or player facts, but has no access to Sleeper, the owner's team, other managers,
league scoring, roster ownership, trade block, waivers, free agents, or watchlist.

Use CODEX whenever the answer needs, would materially benefit from, or is
explicitly requested to use any league-specific information. Do not infer that
a request is public merely because it does not name Sleeper. Interpret the full
request and supplied recent context. Use WEB only when public football research
is sufficient. Return only JSON matching the supplied schema."""

ROUTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "route": {"type": "string", "enum": ["codex_league", "openai_web"]},
        "reason": {"type": "string", "minLength": 1, "maxLength": 240},
    },
    "required": ["route", "reason"],
}


def _response_json(response: Any) -> dict[str, Any]:
    text = str(getattr(response, "output_text", "") or "").strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RoutingError("The advisor router returned an invalid decision") from exc
    if not isinstance(payload, dict):
        raise RoutingError("The advisor router returned an invalid decision")
    return payload


def route_interactive_request(
    question: str,
    *,
    api_key: str | None,
    model: str,
    reasoning_effort: str,
    context_packet: str | None = None,
    waiver_analysis: bool = False,
    has_attachment: bool = False,
    client: Any | None = None,
) -> RouteDecision:
    """Use LLM reasoning and the capability contract to select an execution path."""

    if not api_key:
        raise RoutingError("OPENAI_API_KEY is required to choose the advisor execution path")
    if client is None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise RoutingError("The OpenAI Python SDK is not installed") from exc
        client = OpenAI(api_key=api_key)

    request_context = {
        "user_request": question.strip(),
        "recent_conversation": (context_packet or "").strip(),
        "request_metadata": {
            "is_dedicated_waiver_analysis": waiver_analysis,
            "has_user_attachment": has_attachment,
        },
    }
    try:
        response = client.responses.create(
            model=model,
            instructions=ROUTING_CAPABILITIES,
            input=json.dumps(request_context, ensure_ascii=False),
            reasoning={"effort": reasoning_effort},
            text={
                "format": {
                    "type": "json_schema",
                    "name": "advisor_route",
                    "strict": True,
                    "schema": ROUTE_SCHEMA,
                }
            },
            store=False,
        )
    except Exception as exc:
        raise RoutingError("The advisor router could not choose an execution path") from exc

    payload = _response_json(response)
    try:
        route = AdvisorRoute(payload["route"])
    except (KeyError, ValueError) as exc:
        raise RoutingError("The advisor router returned an unsupported execution path") from exc
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise RoutingError("The advisor router returned an invalid decision")
    return RouteDecision(route=route, reason=reason.strip())
