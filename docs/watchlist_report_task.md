# Daily Premier League watchlist report

The existing task runs at 8:00 AM America/New_York and delivers to the Owner bot
DM. It uses canonical watchlist evidence without conversation history or
interactive grounding. Every saved player receives a compact current outlook,
including on quiet days; an empty watchlist receives a short confirmation.

## Report contract

The mobile heading is `👀 WATCHLIST UPDATE` (bold in Discord). Use the active
2026/27 Premier League season; exclude previous-season, preseason, cup and
international performances from league-role and form claims.

The scheduler renders a short bullet list from structured, validated research.
Every watched player gets one 15–25 word takeaway (30-word maximum), with
important developments first. Each entry includes the name, club, one dated
source, and a short evidence-gap or Sleeper availability flag when needed.
There are no expanded cards, stat blocks, or duplicate priority section.
This is observation-only: no pickup, waiver, trade, or lineup instructions.
The footer explains the existing drilldown: use `/ask` with
`Detailed watchlist outlook for <player>: latest PL match, role, form, fitness, next PL fixture. Observation only.`
The interactive question obtains a fresh player assessment through the existing
advisor; it does not claim to retrieve a saved detailed card.

Research current-season role and availability even without breaking news. Use
dated lineups, match reports, club/manager updates and reputable reporting.
Established context gets visible dated source links, just like new developments.
Never present old stories as new, infer fitness from silence, or infer recent
trends from season totals. Interpretation must follow the available evidence.

Each research record retains its news outcome (verified update, no current
public update found, insufficient current evidence, or research failed), and
adds role and availability assessments with verification flags and sources,
an outlook, watch signal, and optional priority reason. Unknown assessments
must explain the specific missing fact. Generic “no update” text does not meet
the quality contract. Missing or stale evidence makes the report explicitly
partial; it never erases a watched player. Stale verified claims are removed,
and any outlook or priority that could depend on them is replaced with a safe
interpretation of current Sleeper workload and a concrete selection check.
Other players retain their valid research. A malformed or incomplete result
gets one corrective retry explaining the actual failure, then fails visibly.

Verified role evidence must concern the active Premier League season and be no
older than 21 days; prefer the last three matches. Verified availability must
be no older than seven days. Within 72 hours of kickoff, require timestamped
availability evidence within 72 hours or a dated ongoing timetable covering
that fixture. Unknown dates cannot establish current status. Source retrieval
times remain separate from fact dates.

## Deterministic facts and delivery

Current Sleeper identity, stats and maintained fixtures supply the displayed
facts. Saved club/position are historical audit fields; unresolved identity
withholds current club, position and fixture guidance. Missing stats remain
explicitly unavailable in the evidence. Available season totals, starts, minutes
and rates support research. If points are included, use `Sleeper standard: N pts`
labels, never as Kick & Run scoring or
future projections. Live season aggregates can already contain matches from the unfinished current
GW, so label them as season stats as retrieved, not stats through the last
completed GW. The header separates current GW from completed GW and
human times use America/New_York.

The schedule and persistence remain in place. `/task watchlist_report` reuses
the complete-DM delivery helper used by injury reports: edit the original
response, then send all remaining chunks through the authorized DM channel.
This avoids the user-installed webhook follow-up cap and preserves every player.
Source previews are suppressed. The existing model uses at least high reasoning
for multi-player source
reconciliation; an already higher configured effort is preserved. Watchlist research
and interactive watchlist questions use the current `web_search` tool with high
search context to inspect match-page details. Other report tools are unchanged.
See the [OpenAI web search guide](https://developers.openai.com/api/docs/guides/tools-web-search).
Unused six-week trend and previous-season lookups are disabled for this report.
Model/public-search call counts and elapsed
time are included in the existing scheduled trace; no new persistence or
service is introduced.
