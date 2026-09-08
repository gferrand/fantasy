# Fantasy EPL Advisor

A read-only, personalized advisor for the **Kick & Run** Sleeper fantasy English Premier League league.

The project is designed to research and explain roster news, injuries, fixtures, lineup choices, waiver targets, trades, and weekly strategy. It must never make roster, waiver, trade, or lineup changes on Sleeper without an explicit human decision.

Use `/rotation` in the private Fantasy Advisor DM for a protected-core,
four-fixture Moneyball menu with independent pickup targets, trade targets, and
non-core drop/shop candidates. It does not force one player into a paired move,
never puts an automatically protected player on the drop/shop list, and leaves
every action manual in Sleeper. Trade options exclude the current-production
top quartile so the list stays focused on plausible buy-low and fixture-value
players rather than elite, expensive cornerstones.

## Project map

- [`league_context.md`](league_context.md) — canonical league constants, rules, validation policy, and current roster.
- [`docs/architecture.md`](docs/architecture.md) — system boundaries and planned data flow.
- [`docs/local_automation.md`](docs/local_automation.md) — local Discord advisor setup and private player catalog maintenance.
- [`docs/scheduled_tasks.md`](docs/scheduled_tasks.md) — historical ChatGPT Scheduled Task prompt references.
- [`docs/nightly_recap_task.md`](docs/nightly_recap_task.md) — the daily 10:00 PM Eastern game-day recap task definition.
- [`docs/transfer_monitor_task.md`](docs/transfer_monitor_task.md) — the hourly league-wide EPL transfer monitor definition.
- [`data/README.md`](data/README.md) — cache layout and freshness expectations.
- [`scripts/build_sleeper_feed.py`](scripts/build_sleeper_feed.py) — deterministic compact feed builder for GitHub Actions.
- [`src/fantasy_advisor/`](src/fantasy_advisor/) — future Python fetch and analysis package.

## Current status

The local scheduler runs the nightly recap at 10:00 PM Eastern and the
watchlist report at 8:00 AM Eastern, delivering both to the Owner bot DM.
Transfer Watch remains available for `/task transfer_monitor` but is paused
until the January transfer window. Scheduled reports use current evidence and
the OpenAI Fantasy Advisor; the project remains read-only and never mutates
Sleeper state.

The private Discord advisor includes `/injury opportunities`, which scans every
active Sleeper EPL player marked Out or GTD/Questionable and reports current,
source-backed recovery outlooks plus roster-aware playing-time beneficiaries.
Long reports are delivered as a sequence of Discord messages, never as an
attachment.

GitHub Actions refreshes a validated compact Sleeper feed hourly and publishes
it through GitHub Pages. Local scheduled reports consume that feed rather than
parse large raw API responses directly.

## Design rule

Sleeper's EPL eligibility tag is not authoritative. Every recommendation must verify the player's current Premier League club externally and account for transfer and injury overrides documented in [`league_context.md`](league_context.md).
