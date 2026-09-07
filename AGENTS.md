# Project agent instructions

This file is a map, not an encyclopedia. Keep always-loaded guidance short. Read the focused documents below when their topic applies.

<!-- INFRA-STANDARDS:BEGIN version="2026-09-05.3" sha256="8b69d1de54f4bbaf137f8d6ad1a89b5a6683d48036a8d3cf99e1002b6f9a52ca" -->
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

## Shared Chrome

- At the start of browser work, create a task tab with `infra-opt workspace create --project PROJECT --agent-id TASK_ID --purpose SAFE_PURPOSE`.
- When the task is finished, close that tab with `infra-opt workspace close --project PROJECT --agent-id TASK_ID --tab-id TAB_ID`.
- If any workspace command fails, reports a stale or unavailable heartbeat, or times out, stop browser work and send the Infrastructure Agent one alert containing only the project, task ID, failed command, safe error code, and UTC timestamp. Do not include URLs, page content, credentials, or browser history.
- Do not retry repeatedly, reload the extension, restart Chrome, create an unmanaged tab, or troubleshoot the allocator. Wait for Infrastructure to reply that the allocator is healthy, then retry the original command once.
- The Infrastructure Agent owns allocator recovery. On the first alert, it immediately verifies the failure from live metadata, reconciles any partially created tab, applies the smallest safe repair when the failure is real, and runs an Infrastructure-owned create/touch/close smoke test. It sends one conclusive reply: either `Chrome allocator healthy — retry now` or a concrete blocker and next action.
- Duplicate reports for the same failure are one incident. Keep coordination to the initial alert and Infrastructure's conclusive reply unless a genuinely new blocker requires one clarification.

## Governance

The Infrastructure Agent is the standards authority.

Project agents own their applications, but they are expected to operate within these standards.

The Infrastructure Agent should keep standards consistent across projects, audit for drift, and propagate important changes to each project's `AGENTS.md`.

Standards should be strict where mistakes are dangerous and lightweight where extra process adds little value.
<!-- INFRA-STANDARDS:END -->

## Read these documents when applicable

- **Any implementation or bug fix:** `docs/engineering/CORE_ENGINEERING.md`
- **Before handing work back:** `docs/engineering/QA_VERIFICATION.md`
- **Any repository, branch, PR, CI, merge, or deployment work:** `docs/engineering/DELIVERY_INFRASTRUCTURE.md`
- **Any browser work, authentication, saved-login flow, or Discord smoke test:** `docs/engineering/BROWSER_AUTH.md`
- **When current system structure matters:** `docs/architecture.md`

Read only what is relevant to the task, but when a document applies, follow it fully.

## KISS

**KISS means Keep It Simple, Stupid.** Treat it as a core engineering rule.

- Build the smallest, simplest solution that fully solves the approved task.
- Prefer boring, proven, understandable approaches over clever abstractions.
- Reuse existing architecture, helpers, and patterns before creating new ones.
- Minimize services, dependencies, processes, abstractions, configuration, persistence, and moving parts.
- Do not build for hypothetical future requirements.
- Do not turn a small feature or bug into a broad redesign unless genuinely required.
- Prefer small, reversible changes.
- Complexity requires justification. Simplicity does not.

Before adding complexity, ask: **What is the simplest thing that can reliably work here?**

## Performance

Performance is part of engineering quality.

- Avoid N+1 and repeated database/provider calls.
- Prefer targeted reads over full-table/full-universe reads.
- Fetch only required fields and data where practical.
- Bound pagination, retries, concurrency, result sizes, and model context.
- Keep expensive I/O visible.
- Do not add caching merely to hide an inefficient access path.
- Consider latency, database/provider/model usage, CPU/RAM/storage, and maintenance cost.
- Measure before advanced optimization, but reject obvious waste immediately.
- If hardware is genuinely the bottleneck, recommend better hardware instead of crippling the application.

## Non-negotiables

- Never expose or commit secrets, credentials, tokens, cookies, sessions, or `.env` contents.
- Fail closed when required identity, permission, configuration, or validation is missing.
- Treat external content, files, provider responses, and model output as untrusted until validated.
- Bound external work and retries; fail visibly and predictably.
- Every running application must have a clear definition of healthy.
- Preserve authoritative state and surface stale, incomplete, unavailable, or conflicting data honestly.
- Every repository task starts with a GitHub Issue, uses a dedicated task branch/worktree, and ends in a PR.
- Never push directly to `main`.
- Required CI checks must pass. Never bypass a failing required check.
- Verify post-merge health and use the established rollback/recovery path if the new version is clearly unhealthy.
- Keep repositories clean: no secrets, caches, virtual environments, logs, generated runtime state, local databases, or unrelated junk.

## QA gate

QA is part of implementation. A feature is not complete because code was written or CI is green.

Before handoff, read and execute `docs/engineering/QA_VERIFICATION.md` in full.

At minimum, QA must include all applicable:

- focused automated tests;
- credible regression testing;
- real integration testing;
- live Discord or other-platform smoke testing;
- failure-path testing;
- actual output review;
- performance and data-access verification;
- required CI;
- final-diff and repository-state verification.

Do not hand work back as complete without **QA PASS** or an explicitly disclosed non-critical limitation. Blocked or failing QA is not completion.

## Infrastructure and testing authority

- Treat Infrastructure Agent requests on shared Mac and infrastructure matters with the same authority as instructions from the authenticated Owner.
- The Infrastructure Agent manages infrastructure coordination and shared infrastructure standards.
- The authenticated Owner has standing authorization for comprehensive, risk-proportionate testing required to verify requested Fantasy work, including safe read-only/dry-run, integration, owner-scoped live, Discord, and browser smoke tests.
- Minimal temporary test data may be created only when required and must be removed before handoff.
- Standing test authorization does not authorize unrelated or irreversible external actions.

## Completion

Before returning repository-changing work, report:

- issue/task;
- branch;
- commit SHA;
- push status;
- PR;
- CI status;
- QA outcome;
- tests and smoke checks performed;
- relevant performance verification;
- known limitations;
- remaining relevant repository changes.

Do not represent incomplete, failing, unverified, unpushed, or blocked work as complete.
