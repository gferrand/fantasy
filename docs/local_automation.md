# Local Codex automation

The fantasy project now owns its recurring runs. macOS `launchd` starts one
personal Discord app gateway and three scheduled dispatchers:

```text
launchd
  ├─ Discord gateway + `/ask` commands ──┐
  ├─ 22:00 nightly recap   │
  └─ :17 every hour        │
                           v
                    local `codex exec`
                           |
                           v
                 GF Control Room #fantasy
```

The scheduled jobs and future Discord questions use the installed local Codex
CLI. By default, the runner does not pass `--ephemeral`, so each invocation is
a real persistent Codex task and its thread ID is included in the response.
The project remains read-only with respect to Sleeper; Codex may research and
explain, but it is instructed not to make league changes.

Fantasy analysis is permanently pinned in application code to
`gpt-5.6-luna` with `medium` reasoning. The runner sends both settings on every
scheduled and on-demand invocation, including requests routed through the
shared host executor, so host-wide Codex defaults and environment variables do
not alter the Fantasy profile. This pin does not apply to attachment
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
scheduler successes, failures, and outbox retries post only to the configured
server channel. Each automatic message is retained in the local outbox until
Discord accepts delivery; unavailable channel delivery never falls back to DM.

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
one continuous ranked list. The bot acknowledges either command, opens a new
local Codex task, and replies in the same personal DM with the result. `/tasks` lists registered jobs, and
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

Use `/watch add player`, `/watch remove player`, and `/watch list` in the
personal DM to manage a private player watchlist. The 8:00 AM Eastern
watchlist report is silent when that list is empty and does not use Discord
conversation context.

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

When a plain-text DM or `/ask` starts an interactive Codex task, the bot loads
the recent Discord turns and latest scheduled reports into a bounded context
packet. The current request is added separately, so it is not duplicated in
the packet. Codex is told to use the saved material for continuity only and to
recheck current player, fixture, injury, club, and availability facts.

Scheduled runs never load Discord conversation context. They run their normal
standalone prompts and only write their completed reports to the store for
future interactive questions. `/task` follows the same standalone behavior,
even though it is launched from Discord.

The store is created automatically on the first relevant run. It is ignored by
git and remains in the runtime mirror because `sync_runtime` preserves the
generated `data/automation/` directory.

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
