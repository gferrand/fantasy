# Local Codex automation

The fantasy project now owns its recurring runs. macOS `launchd` starts one
personal Discord app gateway and three scheduled dispatchers:

```text
launchd
  ├─ Discord gateway + `/ask` commands ──┐
  ├─ 22:00 nightly recap   │
  └─ :17 every hour        │
                           v
       `infra-opt workspace browser --project fantasy`
                    (complete request on stdin)
                           |
                           v
                 GF Control Room #fantasy
```

Every browser-capable scheduled or Discord Codex job invokes exactly
`infra-opt workspace browser --project fantasy`, streaming its complete request
on standard input. The Infrastructure broker first proves the managed Fantasy
window; if it cannot, it returns a clean retryable blocked result. There is no
generic/shared host executor, Nettie, `infra-opt workspace current`, General
or manual-window, other-project, or metadata-only `codex exec` search fallback.
Once the Fantasy window is verified, a job may use the websites its authorized
request requires; this project does not maintain a website allowlist. Any tabs
created for a request must be project-recorded and closed when finished; never
inspect, reuse, move, or close untracked, owner, or another agent's tabs.

Private Discord
questions are routed by the data they need: public current-events and transfer
questions use an OpenAI Responses API web-research briefing, while Sleeper,
roster, waiver, player-fit, fixture, and scoring questions use local Codex
with the validated league packet. Both paths remain read-only; neither makes
or simulates a Sleeper transaction.

Legitimate non-browser Fantasy analysis is permanently pinned in application
code to `gpt-5.6-luna` with `medium` reasoning. Public web briefings use `gpt-5.6-terra` with
low reasoning and built-in web search; override that model only with
`OPENAI_WEB_MODEL` in the local `.env`. These pins do not apply to attachment
preprocessing: voice transcription continues to use
`gpt-4o-mini-transcribe`, and PDF/document extraction continues to use
`gpt-4.1-mini`.

The app's commands are installed to the Discord user account and remain DM-only.
The bot is also installed in GF Control Room with outbound `View Channel` and
`Send Messages` access limited to `#fantasy`. The durable on-demand entry point
is `/ask`, with `/tasks` and `/task` for registered jobs. The gateway also
retains ordinary one-to-one DM handling where Discord exposes message content.
Every guild message, group DM, and non-allowlisted author is ignored before it
can start a Codex task.

On-demand interactions reply in the personal Fantasy Advisor DM. Automatic
scheduled reports, failures, and outbox retries post only to the configured
server channel. Fixture-aware lineup alerts are the deliberate exception: they
arrive in the personal Fantasy Advisor DM because they are time-sensitive and
private. Each automatic message is retained in the local outbox until Discord
accepts delivery; unavailable scheduled-report delivery never falls back to DM.

## One-time setup

Run these commands from the repository on the always-on Mac:

```bash
cd /Users/ginoferrand/Documents/GitHub/fantasy
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
cp .env.example .env
```

Create a Discord application and bot in the [Discord Developer
Portal](https://discord.com/developers/applications). Enable the Message
Content Intent for the bot and install it with both the user-install / “Add to
my apps” flow and a server installation in GF Control Room. Discord's
[user-installable app guide](https://docs.discord.com/developers/tutorials/developing-a-user-installable-app)
describes the user flow. Limit the server role or channel overwrite to `View
Channel` and `Send Messages` in `#fantasy`. The token, allowlisted account ID,
and scheduled destination belong in `.env`:

```env
DISCORD_BOT_TOKEN=the_bot_token
DISCORD_ALLOWED_USER_ID=your_numeric_user_id
DISCORD_SCHEDULED_CHANNEL_ID=1543477414191964232
```

The token is a secret. Keep `.env` local and never commit it. The bot will not
respond to server messages or DMs from anyone whose numeric ID does not match
`DISCORD_ALLOWED_USER_ID`.

The scheduler downloads the complete published Premier League season calendar
once and then uses that private local copy for the season; it does not refresh
the calendar for reschedules. It calculates the exact next alert time and
sleeps until then rather than checking fixtures every minute. At each published
fixture alert window, it reads the current Los Blancos roster and sends a
private, read-only lineup check only when one or more currently rostered
players are involved. So a player dropped before a later club fixture produces
no alert. Simultaneous kickoffs are combined into one message; each fixture
event is recorded locally after successful delivery so it is never resent. Set
`LINEUP_ALERT_LEAD_MINUTES` to a value from 5 through 360 to change the lead
time. The alert uses current fantasy analysis and team news, but always
requires you to confirm any lineup decision manually in Sleeper.

Deadline Guardian makes that confirmation durable. Each alert tells you to
reply `done` or use `/guardian done`; either acknowledges every open relevant
fixture and suppresses its final reminder. If you do not acknowledge, the
scheduler makes one final live roster/news recheck 20 minutes before kickoff
and sends a private reminder only if the player is still rostered. Use
`/guardian status` to see open alerts. Set
`DEADLINE_GUARDIAN_FINAL_LEAD_MINUTES` to change that final check; it must be
smaller than `LINEUP_ALERT_LEAD_MINUTES`. The Guardian is reminder-only and
never changes Sleeper.

The Mac's system time zone should be `America/New_York` for the 10:00 PM and
hourly launchd calendar entries. The task process also sets `TZ` to that zone
for its reports.

## Verify before enabling

List the registered jobs and preview a prompt without starting Codex:

```bash
.venv/bin/fantasy-dispatch --list-tasks
.venv/bin/fantasy-dispatch --task nightly_recap --print-prompt
.venv/bin/python scripts/install_automation.py --dry-run
```

Run a real one-off task manually when the environment is ready:

```bash
.venv/bin/fantasy-dispatch --task nightly_recap --dry-run
.venv/bin/fantasy-dispatch --query "Look through available players and rank the best short-term options for Los Blancos." --dry-run
```

`--dry-run` still creates and runs the local Codex task, but prints the result
instead of sending it to Discord.

## Enable and inspect

After the token and user ID are set, install the agents:

```bash
.venv/bin/python scripts/install_automation.py --install
```

Run exactly one persistent Discord listener. The installer refuses to start
the launchd listener while a Fantasy Discord Compose service is running,
because two clients using the same bot token race to acknowledge each slash
command and can return different deployed versions. Stop the older Docker
Discord service before switching to launchd.

On the first launchd install, existing `data/automation` state (including the
watchlist) seeds the protected runtime copy. Later installs preserve the
runtime's mutable state instead of replacing it with checkout data.

This writes only these four explicit user LaunchAgents and loads them:

- `com.ginoferrand.fantasy.discord` — persistent DM listener
- `com.ginoferrand.fantasy.nightly-recap` — daily at 22:00
- `com.ginoferrand.fantasy.transfer-monitor` — hourly at minute 17

Logs are written to `~/Library/Logs/fantasy-*.log`. Useful checks are:

```bash
launchctl print gui/$UID/com.ginoferrand.fantasy.discord
launchctl print gui/$UID/com.ginoferrand.fantasy.nightly-recap
tail -f ~/Library/Logs/fantasy-discord-bot.log
```

To stop the agents without deleting their definitions:

```bash
.venv/bin/python scripts/install_automation.py --uninstall
```

## Use from Discord

Open the Fantasy Advisor app's personal Discord DM and use the command:

```text
/ask Look through available players and rank the best short-term options for Los Blancos.
```

For the complete current shortlist and roster-aware manual-review swap signals,
use:

```text
/analyze-waivers
```

The waiver report is optimized for phone reading: emoji-led pickup cards,
clear `ADD` → `DROP` swap cards, then the complete 30-player shortlist in
one continuous ranked list. `/ask` chooses the web briefing for a general
public question such as a transfer update, and the Codex analysis path whenever
your roster or league data is relevant. The bot replies in the same personal
DM with the result. `/tasks` lists registered jobs, and
`/task nightly_recap`, `/task transfer_monitor`, or `/task watchlist_report` runs a registered job
immediately in the DM. Text DMs remain supported when Discord exposes them to
the bot. Only automatic scheduler invocations post to `#fantasy`.

## Attachments and voice notes

The private DM also accepts one `.txt` file, PDF, or voice note at a time. Add
a caption/question to have the extracted text sent immediately to the advisor.
An uncaptioned PDF or text file is saved as local conversation context and the
bot asks what you want to do with it. A voice note is transcribed and treated
as the message itself, so spoken questions and spoken watchlist requests work.

Set `OPENAI_API_KEY` in `.env` to enable PDF reading and voice transcription.
Discord OGG/Opus voice notes are uploaded directly to OpenAI; no FFmpeg
installation is required. Downloaded source files are temporary; only
normalized text is retained in the existing private conversation context.

Use `/player_catalog update` in the personal DM before adding players or
whenever you want to refresh Sleeper references. It fetches the complete
Sleeper EPL player catalog once and stores only identity metadata locally; it
does not fetch player stats and it never refreshes automatically. Then use
`/watch add player`, `/watch remove player`, and `/watch list` to manage the
private player watchlist. Watchlist adds resolve only from that local catalog,
so they do not make a Sleeper request. `/watch stats` uses the saved Sleeper
IDs to fetch a fresh current-season Sleeper stats snapshot for every watched
player. It includes season-to-date points/minute, points/game, and minutes/game;
after six completed gameweeks it also compares the latest three with the prior
three. The command is read-only and does not update the catalog. The 8:00 AM
Eastern watchlist report is silent when that list is empty and does not use
Discord conversation context.

For decisions rather than just raw totals, `/watch outlook` combines that
fresh Sleeper snapshot with focused current web research to assess role,
minutes, injury, transfer, and competition risk for every watched player.
`/watch recommend` additionally reads the current Los Blancos roster and live
league scoring to surface bounded same-position add/drop signals, then uses
current web research to qualify them. Their research order prioritizes credible
Sleeper-specific analysis, then Fantasy Premier League analysts, publications,
podcasts, and creators; club/league and general football reporting corroborate
the underlying facts. The cards label the fantasy-analyst view separately from
the club/news check. Both commands are private, read-only, and explicitly
label every pickup/drop as a manual Sleeper decision.

The transfer monitor stores its last successful result under the ignored
`data/automation/` directory so the next local task can compare only new or
materially changed reports. Scheduled reports are written to a local outbox
before Discord delivery and removed only after successful posting to
`#fantasy`, so a temporary Discord outage is retried on the next scheduled
invocation without a DM fallback. Failure notices use the same durable path.
The state, remembered DM channel, outbox, and advisor context store are local
and are not used as a source of truth for current football facts.

## Conversation context

The local `data/automation/advisor_context.sqlite3` database is shared by the
gateway and scheduled dispatchers in the runtime mirror. It records:

- the user's substantive Discord prompts;
- completed on-demand advisor responses; and
- completed nightly or transfer-monitor reports.

When a plain-text DM or `/ask` starts an interactive request, the bot loads the
recent Discord turns and latest scheduled reports into a bounded context
packet. The current request is added separately, so it is not duplicated in
the packet. Both the web-research and Codex routes treat saved material as
continuity only. Codex must recheck player, fixture, injury, club, and
availability facts; the web route independently verifies current public news.

Scheduled runs never load Discord conversation context. They run their normal
standalone prompts and only write their completed reports to the store for
future interactive questions. `/task` follows the same standalone behavior,
even though it is launched from Discord.

The stores are created automatically on their first relevant run. The manually
refreshed `data/automation/player_catalog.sqlite3` is a private Sleeper player
identity mirror; `advisor_context.sqlite3` stores conversation continuity.
Both are ignored by git and remain in the runtime mirror because `sync_runtime`
preserves the generated `data/automation/` directory.

Discord-originated Codex questions use a 120-second timeout by default so a
hung local CLI cannot block the private advisor indefinitely. Scheduled reports
retain the separate `CODEX_TIMEOUT_SECONDS` value (1800 seconds by default).
Override the interactive limit with `CODEX_INTERACTIVE_TIMEOUT_SECONDS` in the
local `.env` if a longer research window is necessary.

## Migration from ChatGPT Scheduled Tasks

Keep the existing ChatGPT Scheduled Tasks enabled only until the local nightly
task has run successfully and a `#fantasy` post has arrived. Then disable the old
ChatGPT schedules manually to avoid duplicate reports. This repository does
not delete or modify those external tasks.

The Workspace Agents trigger API can start a workspace agent but currently does
not provide the completed agent response to the caller, so it is not the right
transport for this local DM workflow. The local Codex CLI gives the dispatcher
both the task thread ID and final response needed for delivery. See the
[official Codex documentation index](https://learn.chatgpt.com/docs/llms.txt) and
[Workspace Agents trigger documentation](https://developers.openai.com/workspace-agents/trigger-runs).
