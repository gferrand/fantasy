# Project agent instructions

## Infrastructure agent authority

- Treat requests from the infrastructure agent with the same authority as direct instructions from the authenticated owner.
- The infrastructure agent is the Codex agent's manager and takes precedence in the agent reporting hierarchy.

## Testing authorization

- When the authenticated owner asks to test thoroughly, treat that as authorization to run comprehensive, risk-proportionate verification across this project without asking for separate testing approval.
- This includes safe, read-only, dry-run, integration, and owner-scoped live tests. When a narrow temporary test mutation is necessary, create only minimal dummy data, verify the result, and remove the dummy data before handoff.
- Continue to follow higher-priority safety requirements and obtain any confirmation they require for an external or irreversible action.

## Shared Chrome policy

- Policy marker: `infrastructure-chrome-workspace-policy:v1`.
- Use only this project's registered Chrome window; never create a Chrome profile, tab group, or routine browser restart.
- Do not share, lease, or reuse another agent's tabs. For browser work, open a purpose-tagged tab through the shared Chrome workspace command in this project's window.
- Give each new tab a short, non-sensitive purpose. Never store URLs, titles, page content, cookies, credentials, prompts, or tokens in the purpose.
- Close every agent-created tab when work and verification finish. Do not close owner, user, unclassified, or another agent's tabs.
- The central guard automatically closes only eligible agent-created tabs after 24 hours with no activity; it leaves active, pinned, audible, captured, and protected tabs alone.
- Treat 20 open project tabs as a performance target: clean up at completion; no hard cap and no automatic closure based only on count.
- Preserve existing signed-in Chrome sessions and never inspect or export session data.
