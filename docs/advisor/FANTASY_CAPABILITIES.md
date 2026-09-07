# Fantasy Capability and Data-System Audit

**Milestone 1 contract.** Audited from accepted `origin/main` commit `ebaa0e0` on 2026-09-07. This document describes the implemented baseline, not intended future behavior. It is the scope contract for the deterministic capability layer; it deliberately introduces no runtime infrastructure.

See [Sleeper EPL Capability Verification](SLEEPER_CAPABILITIES.md) for separate provider evidence and official-versus-observed classifications.

## Discord command inventory

All 18 currently registered application commands are in `src/fantasy_advisor/discord_bot.py`; commands are private-DM/user-install scoped, and the configured owner check guards private commands.

| Command | Current path, sources, deterministic work | Model / output | Mutation | Advisor reuse |
| --- | --- | --- | --- | --- |
| `/ask` | `run_interaction` → `run_advisor`; eight historical Discord events plus required semantic grounding | Function-only grounding, then OpenAI final response with selective web search; four deterministic/private calls total | Conversation event log | Yes: normal Advisor entry. |
| `/analyze-waivers` | fixed waiver request → unified Advisor required grounding → one compound `get_waiver_context(position, limit)` call when selected | OpenAI final response with selective public research | Conversation event log | Yes: intentional Advisor surface sharing the authoritative pickup and swap engine. |
| `/rotation` | `load_fixture_schedule` + `load_rotation_context` | direct deterministic retrieval, then shared Advisor finalizer with required web research | fixture cache may refresh | Yes. |
| `/tasks` | `load_registry` from `automation/tasks.toml` | rendered task menu | remembered DM channel file | Yes: task metadata only. Preserve. |
| `/task {id}` | validates registry then `!task {id}` → `run_scheduled_task` | generated report | scheduled report/context and configured task state | Keep explicit manual control. |
| `/watch add` | catalog lookup → `add_watchlist_player` | confirmation card | watchlist SQLite | Explicit local action. |
| `/watch remove` | saved-watchlist resolution → `remove_watchlist_player` | confirmation card | watchlist SQLite | Explicit local action. |
| `/watch list` | `list_watchlist` | watchlist card | none | Yes. |
| `/watch stats` | `load_current_watchlist_stats` and `build_player_stat_profile` | deterministic stat card | none | Yes: reuse exact profile. |
| `/watch outlook` | canonical watchlist (first 12 maximum) + current stats | direct retrieval, then shared finalizer with required public outlook research | none | Yes: facts plus public research. |
| `/watch recommend` | recommendation context + swap signals | direct retrieval, then shared finalizer with required target research | none | Yes. |
| `/injury opportunities` | `load_injury_opportunities_context` | deterministic inventory, bounded (max 12) mandatory public timetable research, then shared finalizer | none | Yes; public timeline evidence is passed into finalization without a duplicate broad search. |
| `/trade propose` | persisted fixture schedule + `load_trade_proposal_context` | direct retrieval, then shared finalizer with required incoming-target research | none | Yes: legal context/packages. |
| `/guardian done` | `acknowledge_active_events` | acknowledgement card | Guardian JSON | Explicit local action. |
| `/guardian status` | `active_events` | status card | none | Yes. |
| `/gameweek prepare` | `load_gameweek_prepare_context` | direct retrieval, then shared finalizer with required team-news research | none | Yes; matchup unavailable. |
| `/gameweek recap` | `load_gameweek_recap_context` | direct retrieval, then shared finalizer; web is optional | none | Yes. |
| `/player_catalog update` | `update_player_catalog` → Sleeper player catalog | refresh card | player catalog SQLite | Explicit maintenance action. |

Plain owner DMs take the same Advisor route as `/ask`; clear watchlist and Guardian actions are model-selected authenticated local tools, and attachments are normalized before the Advisor. `!tasks` is an additional plain-DM registry read. `/task` and `/tasks` are preserved.

## Authoritative local/private state

Actual application storage is local files plus **SQLite**. No Supabase client, configuration, or call site exists in this baseline.

| Store / artifact | Authority and contents | Access / writer | Freshness and failure semantics |
| --- | --- | --- | --- |
| `data/automation/player_catalog.sqlite3` | Fantasy-owned local mirror of Sleeper identity metadata: IDs, names, club, eligibility, active/status, refresh time | `player_catalog.py`; `/player_catalog update` | Stale-able; targeted readonly lookup exists. Missing/malformed is unavailable, not live fallback. |
| `data/automation/watchlist.sqlite3` | Fantasy-owned saved watchlist | `watchlist.py`; `/watch add/remove` and explicit plain DM | Add idempotent; list is empty when absent. |
| `data/automation/advisor_context.sqlite3` | conversation, responses, scheduled reports, private evidence, Discord receipt deduplication | `context_store.py` | bounded packet; claim failure fails closed to prevent duplicate replies. |
| `data/automation/lineup_fixtures.json` | persisted public ESPN fixture calendar | `lineup_alerts.py` | validated 380-fixture schedule; stale/unavailable independently of Sleeper. |
| `data/automation/lineup_alerts.json` | sent-alert deduplication | lineup alert runner | operational delivery state. |
| `data/automation/deadline_guardian.json` | alert/acknowledgement/reminder state | `deadline_guardian.py` | acknowledgement affects only active pending events. |
| task state Markdown, channel/heartbeat/report files | last results and operational state | automation/scheduled runner | not decision evidence. |
| `data/sleeper_snapshot.json` and legacy raw caches | ignored live Sleeper snapshot | `scripts/fetch_sleeper_snapshot.py` | timestamped fallback/debug observation, not live authority when stale. |
| `public/sleeper_feed*`, availability feed and pages | generated compact public derivative | `scripts/build_sleeper_feed.py` / GitHub Actions | timestamp/complete flags; local fallback only. |
| `automation/tasks.toml`, task prompts, `league_context.md` | schedule metadata, prompts, human policy/overrides | automation | config/static context, never live ownership. |

## Deterministic engine inventory

| Domain | Existing authoritative functions/modules | Reuse finding |
| --- | --- | --- |
| Sleeper transport/normalization | `SleeperClient`, `normalize_completed_trades`, ownership/availability helpers | Reuse provider boundary; feature modules repeat fetch bundles. |
| Kick & Run scoring | `custom_position_score`, `custom_points_by_position`, candidate/swap helpers | Authoritative custom-score path; keep `pts_std` distinct. |
| player evaluation | `get_player_evaluation_context` | Compact structured facts/provenance and unknown-ownership protection; M2 seed. |
| player profiles/watch stats | `build_player_stat_profile`, `build_watchlist_stats_report` | Shared exact calculation for `/watch stats` and Advisor. |
| roster/slot legality | `evaluate_lineup` in `trade_proposals.py`, reused by `rotation.py` | Preserve this shared implementation; do not create another legality engine. |
| waiver/pickup swaps | `available_epl_players`, `pickup_candidates`, `roster_swap_recommendations` | Present in feed builder; command presentation still uses Codex/web. |
| rotation | `load_rotation_context`, fixture-adjusted projections, protected core | Deterministic context ready to share. |
| gameweek | prepare/recap loaders | current five-read bundle; H2H explicitly unavailable. |
| injuries | `load_injury_opportunities_context` | deterministic inventory/candidates, then public research. |
| trade | `load_trade_proposal_context`, `build_trade_options`, `evaluate_lineup` | deterministic legal packages, then model judgment. |
| Guardian/scheduling | Guardian helpers, registry/scheduler | local read/action boundary; task metadata only. |

## Runtime reasoning and external dependencies

```text
Discord /ask, normal DM, or /analyze-waivers
  → run_advisor required function-only grounding (no web/Codex/final answer)
  → semantic named deterministic capability selection
      → deterministic named product capability, or
      → exclusive no-private-data grounding result
  → final OpenAI reasoning with selective web and narrow later fallback

Specialist analytical slash commands
  → command-selected deterministic context builder (no grounding)
  → shared Advisor finalizer with current evidence and bounded public research
```

- OpenAI is already the final voice for normal `run_advisor`; its Responses API has web search. Attachments use bounded local normalization/transcription.
- Codex is only a narrow later fallback for an unsupported private fact; it is absent from grounding and routine player evaluation and waiver analysis use named deterministic capabilities.
- Capability selection is model-based, not a keyword router. Local actions remain deterministic at the authorization and state-transition boundary.
- Public web briefing functions exist for watchlist, injury, gameweek, rotation, trade, lineup alerts, and scheduled work. ESPN is a separate read-only fixture source.

## Existing Sleeper call sites and duplication

`player_evaluation`, `watchlist_recommendations`, `gameweek`, `rotation`, `trade_proposals`, `injury_opportunities`, and `watchlist_stats` each compose overlapping state/league/roster/user/season-stat reads. Snapshot/feed scripts also fetch league, users, rosters, state, players, transactions, and stats. The next layer should use request-scoped reuse around the current `SleeperClient`, not persistent caching or a new provider abstraction.

`get_player_evaluation_context` already has an operation deadline and partial-evidence envelope. Other feature loaders generally fail the whole command on a single provider failure with per-call transport timeouts. Future capabilities must generalize the former behavior while retaining usable facts.

## Mutation inventory and non-exposure rules

Fantasy-owned writes are watchlist add/remove; player-catalog refresh; Guardian initial/acknowledgement/final-reminder state; context events and receipt claims; fixture/lineup alert caches; scheduled-task result/state files; and generated public feeds. Sleeper has no write client or mutation code.

Never expose arbitrary HTTP, SQL, filesystem, provider URL, raw database write, or generic `run_task(task_id)` to OpenAI. Never expose Sleeper adds, drops, waivers, lineups, trades, league settings, or draft mutations. `/task` remains the explicit manual control.

## Proposed product-level capability catalog

These are future contracts, not new APIs in Milestone 1. They return compact typed evidence (`status`, `data`, `limitations`, `sources`) with retrieval time/freshness where material.

### Read capabilities

- `get_league_context`: scoring, roster slots, season/state.
- `get_team_context`: one resolved team roster and league identity.
- `get_player_context`: identity, eligibility, Sleeper stats, ownership, Kick & Run score, concise Los Blancos comparison.
- `search_player_pool`: bounded EPL candidates with explicit availability limitations.
- `get_league_activity` and `get_draft_context`: bounded transactions or observed draft context; explicit unsupported result otherwise.
- `get_watchlist`, `get_watchlist_stats`, `get_fixture_context`, `get_guardian_status`, and `get_task_registry`.
- `get_waiver_context`, `get_rotation_context`, `get_gameweek_context`, `get_injury_opportunity_context`, and `get_trade_context`: compact inputs reusing exact engines.

### Approved future action candidates

Only with explicit owner intent and existing authorization: `add_to_watchlist`, `remove_from_watchlist`, and `acknowledge_guardian_alerts`. Catalog refresh is an audit-approved maintenance candidate but needs separate exposure justification; recommendations never imply action.

### Explicitly unavailable/unexposed

Raw SQL/filesystem/HTTP; full provider payloads; arbitrary scheduler execution; Sleeper mutations; inferred immediate availability; and H2H matchup capability until Sleeper documents or live-verifies EPL support.

## Contract invariants for the next milestones

1. OpenAI selects product capabilities semantically; deterministic hard safety and authorization remain in application code.
2. A roster read failure produces `ownership: unknown`, never false `unrostered_unclassified`.
3. `pts_std` always means Sleeper-standard points; Kick & Run is calculated from live `scoring_settings`.
4. A capability uses one monotonic whole-operation deadline and keeps partial successful evidence with explicit limitations.
5. Existing slash commands consume shared capability logic where practical; no command is removed or silently repurposed.
6. Public research can enrich public football facts but cannot overwrite private Sleeper roster/ownership or Fantasy-owned state.
