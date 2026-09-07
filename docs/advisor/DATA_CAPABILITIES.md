# Advisor data capabilities

## Runtime contract

Every freeform Advisor request (normal DM, `/ask`, and `/analyze-waivers`)
begins with a required function-only grounding turn. The grounding turn is a
15-second evidence-selection operation: it exposes named deterministic
capabilities, approved local actions, and the exclusive
`no_private_fantasy_data_needed(reason)` no-op. It has no web-search or Codex
fallback and cannot produce the final answer. Invalid grounding retries once,
then returns a generic current-data refresh failure rather than reconstructing
Fantasy facts from history. `/analyze-waivers` is intentionally an Advisor
surface; specialist deterministic slash commands retain their existing paths.

Grounding retrieval calls count against the four deterministic/private tool calls
for the whole request. The no-op consumes none. Later bounded reasoning can use
public research and, only for an unusual unsupported private fact, the Codex
fallback. Codex must never compete with ordinary product capabilities during
grounding or service supported roster, ownership, waiver, gameweek, rotation,
trade, watchlist, Guardian, activity, scoring, draft, or player questions.

Prefer named capabilities for all supported Fantasy facts. The sole private
exploration fallback is for a bounded, read-only fact that no named capability
can provide. Do not use that fallback for roster, ownership, scoring, stats,
watchlist, league activity, draft, waivers, rotation, gameweek, injuries, or
trades when their named capability applies.

Use `get_waiver_context(position, limit)` for roster-aware waiver questions:
`position` is `ANY`, `F`, `M`, `D`, or `GK`, and `limit` is 1–25. It contains
the authoritative current candidate and swap signals in one compact call. Its
universe is the full current eligible EPL player population, then current league
ownership exclusion, position filtering, stats/scoring/injury enrichment,
ranking, and limit. Recommendation turns normally request a research pool of
about 12 before listing their final few options. Statistics and watchlist membership do not define the
available-player universe. Use
`get_gameweek_context` with exactly one mode: `prepare` for a forthcoming
gameweek or `recap` for the latest completed gameweek. Do not retrieve both
unless the Owner explicitly asks distinct questions that require both.

Team, trend, draft, and activity responses use player names and canonical team
names. Owner and provider identifiers are internal plumbing. Team profiles
include each eligible position's distinct Kick & Run points and rate, plus
starts and minutes; standard Sleeper points are never mislabeled as Kick & Run.
When a fresh roster read establishes that a player is unrostered, say so
directly. Sleeper only leaves one separate question unresolved: whether that
unrostered player will process as an immediate Add or through waivers.

For a current named-player decision involving roster or watchlist value,
add/drop, trade, start/bench, role, minutes, or appearances, obtain fresh
current evidence in the same request with `get_player_context` and the relevant
compound capability. A concrete named trade offer is the exception: its exact
`get_trade_context` packet carries those player profiles directly. Use public research for material current real-world facts
that private statistics do not establish when they are reasonably retrievable.
For a concrete trade offer that names the players on both sides, use exactly one
compound `get_trade_context` call with `you_send` and `you_receive`. It returns the exact live player profiles, current
ownership, and legal before/after Kick & Run lineup math for that offer; an
all-null trade-context call is only for generating possible trade
packages.
A club-role, injury/news, or real-world-availability question with no Fantasy
league decision is public-only: ground exclusively to
`no_private_fantasy_data_needed` and research the public web instead.

Use `get_player_context` for a full-name current ownership question; use
`search_player_pool` only to resolve an ambiguous or partial name. A named
other-team roster question uses `get_team_context`, not a player lookup.

Watchlist and Guardian mutations are local only and require an explicit tool
call selected from a clear owner request. A direct request to add or remove a
named player may mutate once. Advice, questions, and ambiguous discussion must
not mutate. Guardian acknowledgement requires an explicit statement that the
relevant alert or lineup has been handled. Authorization is checked at the
local-action boundary.

Conversation continuity is historical and non-authoritative: interactive
requests receive at most eight Discord events, no scheduled reports, and no
retained private evidence. Current private claims require a capability executed
in the same request. Request-cache hits retain their original current-request
source and timestamp without leaking another operation's limitations. Current
watchlist and Guardian reads are fresh authoritative local state; the player
catalog is reference metadata and retains its actual refresh age.

Every result is a compact envelope with `status`, `data`, `limitations`, and
`sources`. Preserve successful evidence if another source is unavailable or a
deadline expires. State the exact missing fact narrowly rather than fabricating
an answer or consuming the final-response reserve. The final acquisition or
trade target requires current public injury/availability and role research when
material; if research changes the target, verify the replacement too.

## Retrieval reference

Sleeper access is read-only. Existing Fantasy helpers provide bounded reads for
league settings, users, rosters, state, football statistics, transactions,
drafts, trends, local player metadata, watchlist state, and Deadline Guardian
state. No raw HTTP, SQL, filesystem, credentials, or task-execution capability
is exposed to OpenAI.
