# Project agent instructions

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
