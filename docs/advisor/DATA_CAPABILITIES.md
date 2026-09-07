# Advisor data capabilities

## Planner contract

OpenAI researches public football evidence: current injuries, transfers,
suspensions, manager comments, roles, lineup competition, fixtures, tactics,
and reputable analysis. Public search cannot see the owner's private Fantasy
state. Do not send private roster, league identifiers, or conversation text to
web search; use public player/club questions only.

Codex can retrieve facts from approved Fantasy repository data, local SQLite
records, and read-only Sleeper endpoints: Los Blancos roster, Kick & Run league
settings and custom scoring, positions, league state, player IDs and metadata,
stats, ownership, other league rosters, unrostered players, saved watchlist,
and maintained fixtures/projections. Request only facts needed for this answer.
Use retained stable evidence when sufficient; recheck volatile facts when they
matter. For decision-critical roster, ownership, availability, scoring, and
league state, query the freshest authoritative source available.

Fantasy value is personalized even when the owner does not explicitly say "my
team." When the owner asks whether a named player is interesting, valuable,
roster-worthy, startable, droppable, tradeable, an upgrade, or a fit for a
comparison, private Fantasy context is normally material: player identity and
eligibility, league ownership or unrostered state, current-season Sleeper
signals, Kick & Run scoring, and Los Blancos roster construction. Request the
smallest useful player-evaluation packet rather than evaluating the player in
isolation. Public research and private Fantasy facts are complementary. This is
semantic guidance, not keyword routing, and a pure public-football question
such as a manager's injury comment normally needs no private retrieval.

For player evaluation, request a compact packet with the resolved Sleeper ID,
positions, club/active/injury metadata, ownership (including the owning team
when rostered), current GP/GS/minutes and useful event totals/rates, distinct
Sleeper standard-stat signals, per-position Kick & Run points/rates, relevant
source timestamps, roster-position rules, and compact Los Blancos comparison
data. If no league roster owns the player, use `unrostered_unclassified`: the
answer may say "Unrostered in Kick & Run," but must not claim immediate Add
versus waiver processing. Keep the core packet to six targeted sources: local
catalog, league, users, rosters, EPL state, and current-season stats. Historical
watchlist-style trends are optional only when already within that budget.

Sleeper ownership does not establish an immediately addable free agent versus
pending waivers. Metadata may be stale for transfers and real-world club/role.
Some stats, minutes, and other fantasy concepts are not exposed. Current injury
outlook and likely starts require public research. Never infer an unsupported
capability or invent missing data. Distinguish unsupported, temporarily
unavailable, and not found. Label stale snapshots with their original timestamp.

Codex retrieves facts only: no fantasy advice, public research, transactions,
file/database writes, credentials, browser use, or unrelated account access.
OpenAI owns reasoning and the final response, including conditional advice when
facts are missing. Ask the user only if unresolved ambiguity could materially
change the decision. A second retrieval is allowed only for a specific missing,
essential, reasonably retrievable private fact. The final reasoning pass may
request that retrieval even if the initial planner selected no private data;
never request a third retrieval. Do not push retrievable Sleeper or Fantasy
facts back to the owner. If a retrieval fails, state that narrow failure rather
than asking the owner to look it up.

## Retrieval reference (not loaded into the planner)

Official [Sleeper API documentation](https://docs.sleeper.com/) describes the
read-only public API. Football endpoints below reflect existing Fantasy code;
the official documentation does not guarantee all football/stat fields.

Existing sources, with GET only:

- `https://api.sleeper.app/v1/league/{league_id}`: current settings/scoring.
- `/league/{league_id}/users`, `/rosters`, `/drafts`: league membership and state.
- `/league/{league_id}/transactions/{round}`: completed transaction records.
- `/state/clubsoccer:epl`: current football season/round.
- `/players/clubsoccer:epl`: large player catalog; prefer targeted local catalog
  reads, and do not download this full universe during interactive retrieval.
- `/user/{user_id}/leagues/clubsoccer:epl/{season}`: league membership history.
- `https://api.sleeper.com/stats/clubsoccer:epl/{season}?season_type=regular`:
  the football stats route used by Fantasy; filter immediately to requested IDs.

Use `league_context.md` for identity and safety rules, not as a live roster.
Inspect `src/fantasy_advisor/sleeper.py` for API parsing and custom scoring.
`data/automation/player_catalog.sqlite3` contains catalog metadata and player rows; query
SQLite with `mode=ro`, bounded selections, and the original refresh timestamp.
Locate other actual data paths through the existing application helpers. Do not
call helpers that initialize, refresh, or write a database during retrieval.
Stored feed/snapshot observations and fixture/projection data are fallback
context with source timestamps, not live facts. Do not dump full databases,
raw snapshots, all league history, or entire catalogs into model context.

Return at most 16,000 characters of JSON. `status` is `complete` or `partial`;
`data` is an object of requested facts. `limitations` is a list of objects with
`kind` (`unsupported`, `temporarily_unavailable`, or `not_found`), `field`, and
`detail`. `sources` is a list with `source`, timezone-qualified `retrieved_at`
(or null when unknown), and boolean `stale`. Every nonempty data result needs
source provenance. An unknown timestamp must be marked stale. No advice fields.
