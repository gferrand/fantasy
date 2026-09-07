#!/usr/bin/env python3
"""Run the read-only real-model Advisor grounding matrix and print traces."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fantasy_advisor.automation import AppConfig, AutomationError, load_advisor_context
from fantasy_advisor.interactive_advisor import run_advisor


MATRIX = (
    ("Who owns Julio Enciso right now?", {"get_player_context"}),
    ("Look at Garner State Penitentiary’s roster. What’s their biggest weakness?", {"get_team_context"}),
    ("Give me the three best available midfielders for my team right now.", {"get_waiver_context"}),
    ("Look at my roster, my watchlist and the waiver market. What move am I missing?", {"get_waiver_context", "get_watchlist"}),
    ("Who should I rotate out over the next few fixtures?", {"get_rotation_context"}),
    ("Find me one realistic trade that would materially improve Los Blancos.", {"get_trade_context"}),
    ("Help me prepare for the next gameweek.", {"get_gameweek_context"}),
    ("What’s the latest on Mathys Tel’s role at Tottenham?", {"no_private_fantasy_data_needed"}),
)


def grounding_passes(prompt: str, trace: dict | None, required: set[str]) -> tuple[bool, str | None]:
    attempts = (trace or {}).get("grounding") or []
    calls = attempts[-1].get("calls") if attempts else []
    names = {str(call.get("name")) for call in calls or []}
    if not required.issubset(names):
        return False, f"required grounding {sorted(required)}; got {sorted(names)}"
    if "no_private_fantasy_data_needed" in names and names != {"no_private_fantasy_data_needed"}:
        return False, "public-only no-op was not exclusive"
    if "no_private_fantasy_data_needed" in names and not (trace or {}).get("web_search_used"):
        return False, "public-only current question completed without web research"
    if "get_waiver_context" in names:
        waiver = next(call for call in calls if call.get("name") == "get_waiver_context")
        try:
            arguments = json.loads(waiver["arguments"])
        except (KeyError, TypeError, json.JSONDecodeError):
            return False, "waiver grounding arguments were invalid"
        if arguments.get("position") not in {"ANY", "F", "M", "D", "GK"} or not 1 <= arguments.get("limit", 0) <= 25:
            return False, "waiver grounding did not use bounded position and limit"
        if "midfield" in prompt.casefold() and arguments.get("position") != "M":
            return False, "midfielder request did not ground to position=M"
    if "get_gameweek_context" in names:
        gameweek = next(call for call in calls if call.get("name") == "get_gameweek_context")
        if "prepare for the next" in prompt.casefold() and '"prepare"' not in str(gameweek.get("arguments")):
            return False, "next-gameweek request did not ground to mode=prepare"
    if (trace or {}).get("codex_used"):
        return False, "supported semantic smoke invoked Codex"
    return True, None


async def run_matrix(config: AppConfig, prompts: tuple[tuple[str, set[str]], ...]) -> int:
    failures = 0
    context = load_advisor_context(config, include_private_evidence=False)
    for number, (prompt, required) in enumerate(prompts, start=1):
        try:
            result = await run_advisor(
                config, prompt, context_packet=context,
                request_id=f"semantic-smoke-{number}", retain_evidence=False,
            )
            passed, detail = grounding_passes(prompt, result.trace, required)
            print(json.dumps({
                "prompt": prompt, "required_grounding": sorted(required), "passed": passed,
                "detail": detail, "trace": result.trace, "answer": result.text,
            }, ensure_ascii=False, default=str))
            if not passed or result.text.startswith("I couldn’t refresh the current Fantasy data"):
                failures += 1
        except AutomationError as exc:
            failures += 1
            print(json.dumps({"prompt": prompt, "error": str(exc)}))
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", action="append", default=[], help="run one prompt instead of the full matrix")
    args = parser.parse_args(argv)
    config = AppConfig.from_environment(repo_root=ROOT)
    if not config.openai_api_key:
        print("error: OPENAI_API_KEY is not configured", file=sys.stderr)
        return 2
    prompts = (
        tuple((prompt, set()) for prompt in args.prompt)
        if args.prompt else MATRIX
    )
    return asyncio.run(run_matrix(config, prompts))


if __name__ == "__main__":
    raise SystemExit(main())
