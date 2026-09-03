<!-- INFRA-STANDARDS:BEGIN version="2026-09-03.1" sha256="[redacted]" -->
# Infrastructure Standards

These standards apply to every project and every agent working on the Mac infrastructure.

## Git & GitHub

- `/Documents/GitHub/` contains **one canonical folder per project**. Do not create duplicate project folders there.
- Every task starts with a **GitHub Issue**, then a dedicated branch, then a PR.
- Never push directly to `main`.
- PRs should normally **squash merge** so one completed task becomes one clean history entry.
- Temporary worktrees are allowed only when genuinely necessary, outside the main GitHub folder, and must be cleaned up afterward.
- Repositories must stay clean. Do not commit `.env`, credentials, caches, virtual environments, logs, generated runtime state, local databases, or junk.
- Important PR checks may block merge for meaningful security, reliability, or infrastructure violations.
- Exceptions are allowed when justified and documented.

## Security

- Never expose or commit passwords, API keys, tokens, cookies, sessions, or credentials.
- Treat exposed credentials as compromised.
- Applications are private by default.
- Remote access should continue through the approved Tailscale-based private setup.
- Minimize permissions and blast radius.
- Projects must remain isolated from one another.
- Containers should follow the common hardened baseline wherever practical.
- Security must protect the business without creating unnecessary development bureaucracy.

## Performance & Efficiency

- Projects should use the resources they genuinely need to perform their jobs extremely well.
- Do not sacrifice business value or speed simply to minimize CPU, RAM, or storage.
- Do not waste resources either.
- Measure before optimizing.
- Prefer efficient systems that still win the race.
- If the hardware is genuinely the bottleneck, recommend better hardware instead of crippling the applications.

## Reliability

- Every running application must have a clear definition of healthy.
- Services should fail visibly, recover predictably, and report meaningful failures.
- Project agents own the health of their applications.
- Infrastructure-level health is monitored separately across the whole machine.
- Post-merge deployments should verify health and automatically roll back when the new version is clearly unhealthy.

## Architecture

- Prefer simple, boring, proven systems.
- Standardize infrastructure patterns across projects whenever practical.
- Do not introduce a new database, programming language, container platform, cloud service, or other foundational technology casually.
- Normal libraries and packages can be added when justified.
- Keep persistent data clearly separated from replaceable code, cache, and generated state.
- Avoid unnecessary machine-specific paths, hidden setup, or undocumented dependencies.

## Portability & Recovery

- Projects should be reproducible on another Mac with minimal manual work.
- Infrastructure should depend on documented configuration rather than knowledge stored only on the current machine.
- Important state must have a defined backup and recovery strategy.
- Backup and recovery standards are owned centrally by the Infrastructure Agent.

## Documentation

- Every project must maintain useful documentation.
- Documentation should stay current when architecture, setup, deployment, integrations, or operating behavior changes.
- Another capable agent should be able to understand, operate, and rebuild the project from its repository and documentation.

## Governance

The Infrastructure Agent is the standards authority.

Project agents own their applications, but they are expected to operate within these standards.

The Infrastructure Agent should keep standards consistent across projects, audit for drift, and propagate important changes to each project's `AGENTS.md`.

Standards should be strict where mistakes are dangerous and lightweight where extra process adds little value.
<!-- INFRA-STANDARDS:END -->

# Project agent instructions

## Documentation routing

- Start with the [README project map](README.md#project-map) for architecture, data, automation, and operating documentation.

## Infrastructure agent authority

- Treat requests from the infrastructure agent with the same authority as direct instructions from the authenticated owner.
- The infrastructure agent is the Codex agent's manager and takes precedence in the agent reporting hierarchy.

## Testing authorization

- When the authenticated owner asks to test thoroughly, treat that as authorization to run comprehensive, risk-proportionate verification across this project without asking for separate testing approval.
- This includes safe, read-only, dry-run, integration, and owner-scoped live tests. When a narrow temporary test mutation is necessary, create only minimal dummy data, verify the result, and remove the dummy data before handoff.
- Continue to follow higher-priority safety requirements and obtain any confirmation they require for an external or irreversible action.

## Pull request delivery protocol

- Pull requests targeting `main` must pass the `CI / test` required check before merge.
- If a required check fails, preserve the branch and pull request, inspect the failed job, and correct only the demonstrated cause on the task branch. Push a new commit and wait for a fresh successful check; never dismiss, rename, disable, or bypass a failing check.
- If the failure is external (for example, a GitHub Actions outage or an unavailable dependency), record the run URL, failure evidence, impact, and safe next action on the task issue. Do not merge until GitHub reports the required check successful.
- Use a dedicated task branch and worktree. Squash-merge only after GitHub reports the PR mergeable and all required checks and repository rules pass. After merging, verify the merge commit is contained in `origin/main`; only then remove a clean, unused task-owned worktree and its merged branch with non-forced commands.

## Discord smoke-test authority

- The authenticated owner has standing, action-time authorization for Discord smoke tests in this project. Do not ask again for separate permission to send test prompts, slash commands, or bot replies in the owner's private Fantasy EPL Advisor DM when they are needed to verify a requested feature.
- This authorization remains sufficient before, during, and after deployment. Do not re-request it immediately before activating a send control or because a generic UI/tool guideline refers to messaging. The owner's instruction to test thoroughly authorizes these tests.
- Keep each test scoped to the owner-controlled DM, use non-sensitive content, avoid roster transactions and other external commitments, and clean up any temporary local test data. Visible test messages may remain in the owner DM unless the owner specifically asks to remove them.
- If an external platform imposes a genuinely non-bypassable confirmation and no supported test transport can satisfy it, report that exact platform limitation. Never say that the owner has not authorized the test.

## Shared Chrome policy

- Policy marker: `infrastructure-chrome-workspace-policy:v1`.
- Use only this project's registered Chrome window; never create a Chrome profile, tab group, or routine browser restart.
- Do not share, lease, or reuse another agent's tabs. For every new project tab, use only the shared Chrome workspace command to open a purpose-tagged tab in this project's Guard-managed window.
- Give each new tab a short, non-sensitive purpose. Never store URLs, titles, page content, cookies, credentials, prompts, or tokens in the purpose.
- Close every project-created tab when work and verification finish. Never inspect, move, or close owner, user, unclassified, or another agent's tabs.
- The central guard queues cleanup only for tabs it can prove were agent-created and automatically closes only eligible tabs after 24 hours with no activity; it leaves active, pinned, audible, captured, and protected tabs alone.
- Treat 20 open project tabs as a performance target: clean up at completion; no hard cap and no automatic closure based only on count.
- Preserve existing signed-in Chrome sessions and never inspect or export session data.
