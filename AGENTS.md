# Project agent instructions

<!-- INFRA-STANDARDS:BEGIN version="2026-09-05.1" sha256="34691655f3cc8dcdfe455e7b48e2dae7d91f9e0ec3efc976bb8e10a19b293c99" -->
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

- Use the existing signed-in Chrome profile and Infrastructure's single shared normal window.
- Every browser task creates its own tab with `infra-opt workspace create --project PROJECT --agent-id TASK_ID --purpose SAFE_PURPOSE`, touches it during work lasting an hour, and closes it after verification.
- Never reuse another task's tab, create a Chrome profile or tab group, inspect session data, or routinely restart Chrome.
- The hourly Infrastructure sweep closes every non-anchor tab after 60 minutes without browser activity or an explicit touch.

## Governance

The Infrastructure Agent is the standards authority.

Project agents own their applications, but they are expected to operate within these standards.

The Infrastructure Agent should keep standards consistent across projects, audit for drift, and propagate important changes to each project's `AGENTS.md`.

Standards should be strict where mistakes are dangerous and lightweight where extra process adds little value.
<!-- INFRA-STANDARDS:END -->

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

## Discord web smoke-test procedure

- Discord web is verified as available when the owner DM for Fantasy EPL Advisor is visible and authenticated in the task-owned Fantasy tab in the shared Chrome window.
- For a narrowly scoped owner-DM smoke test, write the prompt in the Discord composer and submit it by sequentially entering a newline (`\n`) in that composer. The ordinary keyboard Enter dispatch is not reliable through the current automation layer.
- Verify both the posted owner message and the advisor's visible reply, then close only the exact task-owned tab with the matching project, agent ID, and tab ID.

## Shared Chrome tab policy

- The required task-owned tab lifecycle is `create` → `touch` (when needed) → `close`; do not skip or reorder these ownership steps.
- Chrome uses Infrastructure's single shared normal window in the existing signed-in profile. Never create a Chrome profile, tab group, extra window, or routine browser restart.
- Before any browser interaction, synchronously run `infra-opt workspace create --project fantasy --agent-id TASK_ID --purpose SAFE_PURPOSE` and wait for its confirmed tab ID. Work only in that exact task-owned tab.
- Give each task a unique, non-sensitive agent ID and a short, non-sensitive purpose. Never put URLs, titles, page content, cookies, credentials, prompts, or tokens in either value.
- If a task can remain open for an hour, refresh ownership before 60 minutes of inactivity with `infra-opt workspace touch --project fantasy --agent-id TASK_ID --tab-id TAB_ID`.
- After work and verification, synchronously close the exact owned tab with `infra-opt workspace close --project fantasy --agent-id TASK_ID --tab-id TAB_ID`, even when the task fails.
- Never reuse, inspect, move, touch, or close an owner, manual, unclassified, or another task's tab. Preserve existing signed-in Chrome sessions and never inspect or export session data.
- Browser-capable automation must allocate the tab before launching its Codex task, pass the exact tab and ownership metadata to that task, and close it in a guaranteed cleanup path. If allocation fails, take no browser action and return a retryable failure.
- The hourly Infrastructure sweep closes every non-anchor tab after 60 minutes without browser activity or an explicit touch.

## Chrome saved-password sign-in recovery

- For any service that requires sign-in, first use its normal sign-in flow and
  Chrome's supported saved-credential UI. If the service shows a saved-account
  chooser, click the visible account that matches the owner and service.
- If the service instead shows a standard login form, click only its visible
  username, email, or phone-number field as though you were about to type; do
  not type in that field or the Password field. Chrome presents its
  saved-password picker outside the webpage.
- When the service/account context is unambiguous or the owner specifically
  instructs it, select the first Chrome-suggested credential through Chrome's
  visible UI, then use the service's normal sign-in action only if it has not
  already advanced. Do not read the suggested credential or inspect either
  form value.
- Verify successful sign-in only from non-sensitive page state: the intended
  authenticated page, dashboard, or service-specific destination appears.
  Never inspect, copy, type, export, persist, or otherwise expose the username
  or password. If the picker is unavailable or rejected, or the service
  requires MFA, CAPTCHA, a warning, or account approval, record that exact
  verification gap and stop the login attempt.
- **Discord example:** in a dedicated Discord web tab, the chooser account is
  the visible saved owner username; the ordinary form's identifier control is
  named **Email or Phone Number**; successful sign-in advances to Discord or
  the Developer Portal.
