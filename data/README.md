# Data cache

This directory is reserved for timestamped raw API responses and normalized datasets. The initial project setup does not fetch live data.

Expected handoff files, when restored or regenerated:

```text
sleeper_current_league.json
sleeper_users.json
sleeper_rosters.json
sleeper_drafts.json
sleeper_epl_players.json
sleeper_2025_stats.json
```

## Deterministic local snapshot

For a validated local pull of the live league, run from the project root:

```text
python3 scripts/fetch_sleeper_snapshot.py
```

The command fetches the league, users, rosters, current state, complete player
metadata, current-season stats, and the current-round transaction array. It
validates the transaction response shape and writes an atomic snapshot to
`data/sleeper_snapshot.json`. The file is ignored by git because it is dynamic.

The normalized helpers in `src/fantasy_advisor/sleeper.py` reconstruct completed
trades and compute the current-club, active, unrostered EPL pool without
pretending that the public API can distinguish an immediate free agent from a
pending waiver claim.

Dynamic files should record their source and retrieval time. Do not use cached Sleeper EPL eligibility without applying the current-club whitelist and external transfer overrides in [`../league_context.md`](../league_context.md).
