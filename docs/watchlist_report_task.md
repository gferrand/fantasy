# Daily Premier League watchlist report

This local task runs at 8:00 AM America/New_York for one private Discord user.
It receives `CURRENT CANONICAL WATCHLIST EVIDENCE` assembled before execution.
The local scheduler finalizes it directly through the OpenAI Advisor in the
Owner bot DM, without conversation history or interactive grounding. An empty
watchlist produces a concise confirmation card rather than a silent run.

The first 12 canonical watched players are checked in one bounded current-public
research pass. Each receives exactly one structured outcome: verified update,
no current public update found, insufficient current evidence, or research
failed. A missing player gets one corrective retry; a second incomplete result
is an honest partial report. Current Sleeper stats and the maintained fixture
schedule are deterministic authority. Each saved player is resolved by ID
against the current Sleeper EPL catalog before display: the saved club and
position are historical audit fields, never current identity. If that identity
is unresolved, current club, position, and fixture guidance are withheld.
Scores are always labeled `Sleeper standard: N pts`; the card separates current
GW from `stats through` the last completed GW and uses America/New_York for
human times. Source links include their fact date and suppress previews.

```text
Produce a compact daily status report for the personal Premier League watchlist.
This is observation only: do not recommend, simulate, or imply any Sleeper roster
transaction, pickup, waiver, trade, or lineup action.

The supplied CURRENT CANONICAL WATCHLIST EVIDENCE is authoritative for which
players are watched, current Sleeper stats, and deterministic fixtures. It
contains no Discord conversation context; do not request or rely on such context.

For every watched player, give:
- verified 2026/27 Premier League appearances, minutes, and current status only
  when directly supported by the snapshot or a source that clearly identifies the
  active Premier League season and competition;
- any material role, injury, transfer, suspension, or selection news, with a
  direct source link;
- a relevant next-fixture or availability note when it can be verified for the
  active Premier League season; otherwise say so plainly;
- `No material update` when there is no verified change today.

If current Sleeper stats are unavailable, keep the player in the report and
state that the current deterministic stats row was unavailable. Do not silently
delete them and do not guess a destination or availability.

The ACTIVE EVIDENCE WINDOW is binding. Exclude previous-season, preseason, cup,
European, youth, and career statistics or articles by default. A recent article
about 2025/26 is still invalid evidence for 2026/27. If current Premier League
evidence is unavailable or ambiguous, say `Not verified for the active Premier
League season`; never project current minutes, appearances, form, role, or
selection from older material.

Always deliver a concise status even on quiet days. Begin with the active evidence
window and source timestamp, then use one short bullet per watched player. Keep
facts separate from any clearly labeled inference.

DISCORD MOBILE PRESENTATION (binding)
- Begin `👀 WATCHLIST UPDATE`, followed by one compact evidence-window line.
- Use one easy-to-scan card per watched player: `**Player** · club · position`,
  then a single status/fact line, then a source or next-fixture note only when
  it changes the decision. Leave a blank line between players.
- Use `✅ NO MATERIAL UPDATE` on quiet entries. Do not add empty categories,
  tables, code blocks, raw snapshot JSON, task identifiers, or process notes.
- End with `🔎 RECHECK` only if something should be verified before a relevant
  match; otherwise omit it. Return only the report.
```
