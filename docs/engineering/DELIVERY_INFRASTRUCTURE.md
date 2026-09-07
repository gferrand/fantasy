# Fantasy Delivery & Infrastructure Standard

Use this document for repository changes, Git and GitHub work, CI, pull requests, merges, deployment verification, and shared infrastructure coordination.

## Git & GitHub

- `/Documents/GitHub/` contains **one canonical folder per project**. Do not create duplicate project folders there.
- Every task starts with a **GitHub Issue**, then a dedicated task branch and worktree, then a PR.
- Never push directly to `main`.
- Temporary worktrees are allowed only when genuinely necessary, must live outside the canonical project folder, and must be cleaned up afterward.
- Keep repository changes focused on the task. Separate unrelated work.
- Keep repositories clean. Do not commit `.env`, credentials, caches, virtual environments, logs, generated runtime state, local databases, or junk.
- Use clear, specific commit messages that describe the completed change.
- Completed, reasonably verified work should be committed and pushed to the task branch when permitted and technically possible.
- PRs should normally squash merge so one completed task becomes one clean history entry.
- Important repository checks may block merge for meaningful security, reliability, QA, or infrastructure violations.
- Exceptions must be justified and documented.

## Required CI

Pull requests targeting `main` must pass all required checks, including `CI / test`.

If a required check fails:

1. preserve the branch and PR;
2. inspect the actual failed job;
3. correct only the demonstrated cause on the task branch;
4. push a new commit;
5. wait for a fresh successful check.

Never dismiss, rename, disable, or bypass a failing required check.

If the failure is external, such as a GitHub Actions outage or unavailable dependency:

- record the run URL;
- record the failure evidence;
- state the impact and safe next action on the task issue;
- do not merge until GitHub reports the required check successful.

## Merge and post-merge verification

- Squash-merge only after GitHub reports the PR mergeable and all required checks and repository rules pass.
- Merge is an approval gate separate from implementation and QA. Do not merge unless authorized.
- After merge, verify the merge commit is contained in `origin/main`.
- Verify the affected application or runtime is healthy after merge where applicable.
- If the new version is clearly unhealthy, use the established rollback or recovery path rather than leaving the application broken.
- Only after merge and health verification may a clean, unused task-owned worktree and merged branch be removed with non-forced commands.

## Infrastructure Agent authority

- The Infrastructure Agent is the standards authority for shared Mac and infrastructure concerns.
- Treat its infrastructure requests with the same authority as instructions from the authenticated Owner.
- The Infrastructure Agent manages Codex and infrastructure coordination and takes precedence in that reporting path.
- Project agents own their applications while operating within shared infrastructure standards.
- Infrastructure owns machine-wide standards, audits drift, and propagates important shared changes into project `AGENTS.md` files.
- Standards should be strict where mistakes are dangerous and lightweight where added process provides little value.

## Completion report

Before returning repository-changing work, report:

- issue or task;
- working branch;
- commit SHA;
- push status;
- PR number or URL;
- CI status;
- QA outcome;
- automated tests and results;
- regression coverage;
- integration verification;
- live platform smoke verification where applicable;
- relevant failure paths tested;
- performance and data-access verification where applicable;
- known limitations or residual risk;
- relevant modified, staged, or untracked files remaining.

Do not represent incomplete, failing, unverified, unpushed, or blocked work as complete.
