# Advisor data capabilities

## Runtime contract

The OpenAI Fantasy Advisor chooses product-level deterministic capabilities
semantically. Use the smallest material set automatically; do not ask the
Owner to retrieve information Fantasy can read. A normal request may use at
most four deterministic/private tool calls and always preserves time for the
final response. Public research is complementary but never receives private
league identifiers, roster data, or conversation context.

Prefer named capabilities for all supported Fantasy facts. The sole private
exploration fallback is for a bounded, read-only fact that no named capability
can provide. Do not use that fallback for roster, ownership, scoring, stats,
watchlist, league activity, draft, waivers, rotation, gameweek, injuries, or
trades when their named capability applies.

Use `get_waiver_context` for roster-aware waiver questions: it contains the
authoritative current candidate and swap signals in one compact call. Use
`get_gameweek_context` with exactly one mode: `prepare` for a forthcoming
gameweek or `recap` for the latest completed gameweek. Do not retrieve both
unless the Owner explicitly asks distinct questions that require both.

Team, trend, draft, and activity responses use player names and canonical team
names. Owner and provider identifiers are internal plumbing. Team profiles
include each eligible position's distinct Kick & Run points and rate, plus
starts and minutes; standard Sleeper points are never mislabeled as Kick & Run.
An unrostered player is not necessarily immediately addable because Sleeper
does not expose pending-waiver state.

Watchlist and Guardian mutations are local only and require an explicit tool
call selected from a clear owner request. A direct request to add or remove a
named player may mutate once. Advice, questions, and ambiguous discussion must
not mutate. Guardian acknowledgement requires an explicit statement that the
relevant alert or lineup has been handled. Authorization is checked at the
local-action boundary.

Every result is a compact envelope with `status`, `data`, `limitations`, and
`sources`. Preserve successful evidence if another source is unavailable or a
deadline expires. State the exact missing fact narrowly rather than fabricating
an answer or consuming the final-response reserve.

## Retrieval reference

Sleeper access is read-only. Existing Fantasy helpers provide bounded reads for
league settings, users, rosters, state, football statistics, transactions,
drafts, trends, local player metadata, watchlist state, and Deadline Guardian
state. No raw HTTP, SQL, filesystem, credentials, or task-execution capability
is exposed to OpenAI.
