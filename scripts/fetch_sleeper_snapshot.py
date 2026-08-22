#!/usr/bin/env python3
"""Fetch a validated, read-only Sleeper snapshot for local analysis.

The generated JSON is intentionally ignored by git.  This command is the
deterministic fallback for debugging Scheduled Task data-access failures and
can be run before producing a report locally.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fantasy_advisor.sleeper import API_BASE, STATS_BASE, SleeperClient, transactions_url


def fetch_snapshot(league_id: str) -> dict:
    client = SleeperClient()

    def get(path: str) -> object:
        return client.get_json(f"{API_BASE}{path}")

    state = get("/state/clubsoccer:epl")
    if not isinstance(state, dict):
        raise RuntimeError("Sleeper state endpoint did not return an object")
    try:
        current_round = int(state["week"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("Sleeper state did not include a numeric current week") from exc

    transactions = client.get_json(transactions_url(league_id, current_round))
    if not isinstance(transactions, list):
        raise RuntimeError("Sleeper transactions endpoint did not return an array")

    return {
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "league_id": league_id,
        "round": current_round,
        "urls": {
            "league": f"{API_BASE}/league/{league_id}",
            "users": f"{API_BASE}/league/{league_id}/users",
            "rosters": f"{API_BASE}/league/{league_id}/rosters",
            "state": f"{API_BASE}/state/clubsoccer:epl",
            "players": f"{API_BASE}/players/clubsoccer:epl",
            "transactions": transactions_url(league_id, current_round),
            "stats": f"{STATS_BASE}/clubsoccer:epl/2026?season_type=regular",
        },
        "league": get(f"/league/{league_id}"),
        "users": get(f"/league/{league_id}/users"),
        "rosters": get(f"/league/{league_id}/rosters"),
        "state": state,
        "players": get("/players/clubsoccer:epl"),
        "transactions": transactions,
        "stats": client.get_json(f"{STATS_BASE}/clubsoccer:epl/2026?season_type=regular"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--league-id", default="1378147559444348928")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "sleeper_snapshot.json")
    args = parser.parse_args()

    try:
        snapshot = fetch_snapshot(args.league_id)
    except Exception as exc:  # noqa: BLE001 - CLI should report one clear failure
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(args.output)
    print(f"Wrote validated Sleeper snapshot to {args.output}")
    print(f"Current round: {snapshot['round']}; transactions: {len(snapshot['transactions'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
