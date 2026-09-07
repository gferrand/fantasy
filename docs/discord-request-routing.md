# Interactive Discord advisor

Normal `/ask` and plain messages, including PDFs, text files, and voice notes,
use one pipeline:

```text
normalized request + recent context + retained private evidence
                         |
                  OpenAI private-data plan
                         |
          optional read-only Codex facts retrieval
                         |
              OpenAI reasoning + public web search
                         |
       optional second retrieval of one essential missing fact
                         |
                OpenAI final Fantasy Advisor answer
```

Public-only questions never start Codex. There is no keyword-based semantic
routing in this path. The planner uses the concise portion of
[the capability contract](advisor/DATA_CAPABILITIES.md); its retrieval reference
is available to Codex but is not always loaded into the planner.

OpenAI retains the configured `OPENAI_WEB_MODEL` and reasoning effort; Codex
retains the configured application model and reasoning effort. The retrieval
runner is ephemeral and allocates no browser. Its invocation-local Codex
permission profile extends `:read-only` and enables the network proxy for only
`api.sleeper.app` and `api.sleeper.com`. Filesystem writes and unrelated
network destinations remain blocked. It changes no global Codex settings.
This requires a Codex CLI supporting named permission profiles and the network
proxy; unsupported runtimes fail visibly without weakening the sandbox.
It receives only the requested facts, not the complete conversation.

One 120-second deadline starts when processing begins after queue acquisition
and acknowledgment. Download and attachment normalization count toward it.
Planner calls are capped at 15 seconds, first retrieval at 45 seconds, and a
second retrieval at 20 seconds. Retrieval reserves 30 seconds for a final
answer plus process-cleanup allowance. Provider retries are disabled for the new
path. A slow intermediate OpenAI pass falls back to the final-answer reserve.
The gateway cancels overdue API work; the runner terminates overdue Codex trees.
The target is under 90 seconds; this is measured, not a guaranteed provider SLA.

PDFs use inline API input with response storage disabled; audio uses the existing
transcription model. Local raw attachment files are removed on success, failure,
or cancellation. Attachment-only documents go to the advisor, which can ask
what the user wants to know. Attachment content never triggers local watchlist
mutations or registered task dispatch.

Validated private results are stored as `private_evidence` events in the existing
context SQLite database. Two recent results can contribute up to roughly 6 KB
of field-bounded evidence within the existing 32 KB packet. Recent conversation
retains priority; omitted evidence fields are labeled. Sources retain original
timestamps. Volatile facts are rechecked; stable facts may be reused. Failed,
unsupported, and absent facts are distinct, and stale fallback is never live.

Only the OpenAI answer is displayed, with the existing working acknowledgment,
one Fantasy Advisor heading, and genuine operational errors. Current public
claims retain source links; private source details appear only when material.

`/analyze-waivers`, `/task`, `/rotation`, `/trade propose`, `/injury opportunities`,
`/gameweek`, `/watch recommend`, other dedicated workflows, and scheduled reports
retain their existing execution paths. Their legacy routing/feed helpers remain
available. Owner-DM authorization, duplicate suppression, and mention controls
remain in place.
