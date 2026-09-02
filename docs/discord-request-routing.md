# Discord request routing

The private Discord advisor chooses the smallest safe execution path for each
interactive request, while retaining the same bounded recent-DM context on
both paths.

| Request type | Execution path | Data access |
| --- | --- | --- |
| Public news, transfers, or general current-events questions | OpenAI Responses API (`gpt-5.6-terra`, low reasoning) with built-in web search | Public web only |
| Sleeper, roster, waiver, free-agent, scoring, lineup, fixture, or team-fit questions | Local Codex (`gpt-5.6-luna`, medium reasoning) | Project tools and approved live league data |
| `/analyze-waivers`, `/task`, or an attached document/audio note | Local Codex | Project tools and approved live league data |

The router is deliberately conservative: when a question asks about the
owner's team or any live league state, it selects Codex. A generic public
question defaults to the web-research path, so it never implies access to the
private roster or Sleeper data.

Both routes receive the rolling recent Discord context packet. That lets a
follow-up such as “what about him?” inherit the immediately relevant
conversation without treating historic text as fresh instructions. No route
makes transactions or simulations.
