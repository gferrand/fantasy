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
essential, reasonably retrievable private fact. Never request a third retrieval.

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
