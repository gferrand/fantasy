# Interactive Discord advisor

Normal `/ask` and plain messages, including PDFs, text files, and voice notes,
use one pipeline:

```text
normalized request + recent context + retained private evidence
                         |
          OpenAI reasoning + public web search
                         |
        up to four named deterministic Fantasy tools
                         |
       narrow read-only fallback only when no tool exists
                         |
                OpenAI final Fantasy Advisor answer
```

Public-only questions never start Codex. There is no keyword-based semantic
routing in this path. OpenAI selects named product capabilities from the
[capability contract](advisor/DATA_CAPABILITIES.md), then produces the final
response using the durable [reasoning standard](advisor/ADVISOR_REASONING.md).

OpenAI retains the configured `OPENAI_WEB_MODEL` and reasoning effort; Codex
retains the configured application model and reasoning effort. The retrieval
runner is ephemeral and allocates no browser. Its invocation-local Codex
permission profile extends `:read-only` and enables the network proxy for only
`api.sleeper.app` and `api.sleeper.com`. Filesystem writes and unrelated
network destinations remain blocked. It changes no global Codex settings.
This requires a Codex CLI supporting named permission profiles and the network
proxy; unsupported runtimes fail visibly without weakening the sandbox.
It receives only the requested facts and a compact source/identity map, not the
complete conversation. Known sources do not require repeated document discovery. HTTPS retrieval uses
the system HTTP client with certificate verification; trust failures remain
source failures and must never trigger a TLS-verification bypass.
Fresh source timestamps must fall within the current retrieval window; old
observations are accepted only when explicitly marked stale. Current public
news requires publication-date and event-year verification before it is called
current or latest.

The first retrieval may use up to 60 seconds, capped by the remaining shared
budget after reserving final-answer and cleanup time; a second uses at most 20.
One 120-second deadline starts when processing begins after queue acquisition
and acknowledgment. Download and attachment normalization count toward it.
Named deterministic calls share the request deadline and reserve 30 seconds for
the final answer plus process-cleanup allowance. Provider retries are disabled
for the interactive path. A slow intermediate OpenAI pass falls back to the
final-answer reserve.
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
