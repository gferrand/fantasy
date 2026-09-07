# Interactive Discord advisor

Normal `/ask` and plain messages, including PDFs, text files, and voice notes,
use one pipeline:

```text
normalized request + up to 8 historical Discord events
                         |
  required function-only grounding (no web or Codex)
                         |
   current deterministic evidence/actions (four-call total)
                         |
 OpenAI reasoning + selective public web / bounded fallback
                         |
                OpenAI final Fantasy Advisor answer
```

The grounding turn accepts only named deterministic capabilities, approved
local actions, or the exclusive `no_private_fantasy_data_needed` function. It
uses `tool_choice="required"`, has a 15-second ceiling, and retries an invalid
selection once. It cannot answer. Public-only questions ground to that no-op
and never start Codex. There is no keyword-based semantic routing in this path.
OpenAI selects named product capabilities from the
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

One 120-second deadline starts when processing begins after queue acquisition
and acknowledgment. Download and attachment normalization count toward it.
Named deterministic calls share cached data but have independent evidence
envelopes and per-call ceilings, each clamped by the remaining request deadline.
The request reserves 30 seconds for the final answer plus process-cleanup
allowance. Provider retries are disabled for the interactive path. A slow
grounding pass gets one bounded corrective retry. If grounding cannot obtain a
valid current-evidence decision, the Advisor returns a generic refresh failure
rather than using history as Fantasy state. Approved authenticated local actions
remain available independently of external/private retrieval time.
The gateway cancels overdue API work; the runner terminates overdue Codex trees.
The target is under 90 seconds; this is measured, not a guaranteed provider SLA.

PDFs use inline API input with response storage disabled; audio uses the existing
transcription model. Local raw attachment files are removed on success, failure,
or cancellation. Attachment-only documents go to the advisor, which can ask
what the user wants to know. Attachment content never triggers local watchlist
mutations or registered task dispatch.

Validated private results may be stored as `private_evidence` events for
diagnostics/history, but normal DMs, `/ask`, and `/analyze-waivers` never load
them into a new request. Evidence remains available only within the request that
retrieved it. Sources retain their current-request timestamps and cache-hit
provenance. Failed, unsupported, and absent facts are distinct, and stale
reference metadata is never presented as live state.

Only the OpenAI answer is displayed, with the existing working acknowledgment,
one Fantasy Advisor heading, and genuine operational errors. Current public
claims retain source links; private source details appear only when material.

`/analyze-waivers` uses the same unified Advisor path as `/ask`, selecting the
compound waiver capability when material. Specialist analytical slash commands
(`/rotation`, `/trade propose`, `/injury opportunities`, `/gameweek prepare`,
`/gameweek recap`, `/watch outlook`, and `/watch recommend`) skip semantic
grounding because the command itself is the explicit router. Each performs its
known deterministic retrieval, then enters the shared Advisor finalizer with
current evidence, a bounded deadline, runtime-SHA tracing, and no Codex
fallback. Commands requiring current football research require a web search;
recap may finalize from completed-round evidence alone. State and operational
commands remain direct and model-free.
Owner-DM authorization, duplicate suppression, and mention controls remain in
place.
