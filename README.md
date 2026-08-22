# Fantasy EPL Advisor

A read-only, personalized advisor for the **Kick & Run** Sleeper fantasy English Premier League league.

The project is designed to research and explain roster news, injuries, fixtures, lineup choices, waiver targets, trades, and weekly strategy. It must never make roster, waiver, trade, or lineup changes on Sleeper without an explicit human decision.

## Project map

- [`league_context.md`](league_context.md) — canonical league constants, rules, validation policy, and current roster.
- [`docs/architecture.md`](docs/architecture.md) — system boundaries and planned data flow.
- [`docs/scheduled_tasks.md`](docs/scheduled_tasks.md) — reusable prompts for ChatGPT Scheduled Tasks.
- [`docs/nightly_recap_task.md`](docs/nightly_recap_task.md) — the daily 10:00 PM Eastern game-day recap task definition.
- [`docs/transfer_monitor_task.md`](docs/transfer_monitor_task.md) — the hourly league-wide EPL transfer monitor definition.
- [`data/README.md`](data/README.md) — cache layout and freshness expectations.
- [`scripts/build_sleeper_feed.py`](scripts/build_sleeper_feed.py) — deterministic compact feed builder for GitHub Actions.
- [`src/fantasy_advisor/`](src/fantasy_advisor/) — future Python fetch and analysis package.

## Current status

The nightly recap task is active in ChatGPT Scheduled Tasks at 10:00 PM Eastern. It recaps Los Blancos activity, completed league trades, waiver-auction targets, and immediate free-agent options, while preparing for the next seven days with source-triangulated starter outlooks and a custom-scoring lineup recommendation. The project itself remains read-only and does not mutate Sleeper state.

GitHub Actions is configured to refresh a validated compact Sleeper feed hourly and publish it through GitHub Pages. The Scheduled Task should consume that feed rather than parse Sleeper's large raw API responses directly.

## Design rule

Sleeper's EPL eligibility tag is not authoritative. Every recommendation must verify the player's current Premier League club externally and account for transfer and injury overrides documented in [`league_context.md`](league_context.md).
