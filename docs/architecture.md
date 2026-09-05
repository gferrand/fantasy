# Advisor Architecture

## Purpose

The project is a read-only fantasy EPL advisor for the Los Blancos manager in Sleeper's Kick & Run league. It researches and explains decisions; it does not operate the league account.

## Components

### 1. Context layer

`league_context.md` stores static league facts, scoring assumptions, roster context, source policy, transfer overrides, and injury overrides. It is the canonical human-readable reference.

### 2. Data layer

Future Python fetchers will retrieve and cache:

- League metadata, users, rosters, drafts, and player metadata from Sleeper.
- EPL statistics from the working `api.sleeper.com` stats route.
- External current-club, injury, suspension, and news evidence.

Each cache should include retrieval time, source URL, and enough raw data to reproduce the analysis.

The local `SleeperClient` and snapshot command provide the deterministic path for
large or structurally sensitive responses. They validate JSON shapes, retry
transient HTTP failures, write snapshots atomically, reconstruct completed
trades from transaction mappings, and compute an explicitly unclassified
unrostered pool. The public API does not identify direct free agents versus
pending waivers, so that final availability check remains in Sleeper.

### 3. Verification layer

Before a player enters an active recommendation pool, reconcile:

- Sleeper player ID and position
- Active status
- EPL competition tag
- Current club against the 2026/27 whitelist
- Explicit transfer overrides
- Injury and availability evidence

Conflicting or stale evidence must be surfaced in the report rather than silently resolved in favor of Sleeper.

### 4. Analysis layer

Planned read-only analyses include:

- Roster news and injury monitoring
- A complete on-demand Sleeper injury board with current-source return outlooks and roster-aware playing-time beneficiaries
- Fixture difficulty and next-opponent previews
- Start/bench recommendations based on league-specific scoring
- Waiver-wire rankings
- Trade-target and trade-value analysis
- Weekly playoff and roster strategy

Every recommendation should explain the evidence, uncertainty, relevant scoring categories, and the action for the manager to consider.

The private `/injury opportunities` path fetches the complete active Sleeper
EPL catalog, league ownership, and current stats. Sleeper supplies the Out and
GTD/Questionable inventory; a bounded structured web pass supplies only
current-source injury details, supported return windows, and up to eight
ID-resolved beneficiaries. Missing research degrades to an explicit unknown
rather than a generic recovery estimate. Unrostered beneficiaries are shown
first, but Sleeper remains authoritative for whether an Add action is available.

### 5. Conversation layer

Browser-capable recurring and Discord-request analysis streams its complete
request on standard input to `infra-opt workspace browser --project fantasy`.
The Infrastructure broker may proceed only after it proves the managed Fantasy
window. A failed proof is a clean retryable blocked result: no generic/shared
executor, Nettie, `infra-opt workspace current`, General/manual window, other
project, or metadata-only `codex exec` search fallback is allowed. Once the
window is verified, the request may use its required websites without a website
allowlist. It records and closes only its own project tabs at completion.

Legitimate non-browser local execution remains available for work that does not
need browser capability. Stable league context is embedded in task packets so
the advisor can make bounded, reproducible use of league data.

## Boundaries

- No Sleeper authentication or write operations.
- No autonomous waiver claims, trades, lineup submissions, or roster edits.
- No recommendation based only on Sleeper's EPL eligibility tag.
- No standard-FPL scoring assumptions when the league scoring map is available.
- No confident recommendation when current club or availability is unresolved.

## Data flow

```text
Sleeper API + authoritative external sources
                |
                v
       cached raw observations
                |
                v
 current-club / injury verification
                |
                v
     league-specific analysis
                |
                v
      evidence-backed briefing
                |
                v
       manager decides manually
```
