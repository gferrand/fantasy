# Branch consolidation audit — 2026-09-02

## Baseline and method

This audit used `origin/main` at `fcee716e216d419c89e8e743ba8dba20473daa88` as
its baseline. Each non-main local and remote ref was checked with ancestry,
commit/patch comparison, and, where histories diverged, file-level content
comparison. It records branch disposition; it does not delete pre-existing
branches or worktrees.

## Ref disposition

| Ref | Disposition | Evidence |
| --- | --- | --- |
| `codex/chrome-workspace-policy` and `origin/codex/chrome-workspace-policy` | Semantically represented; retain | Its Chrome-workspace policy is present in `main`'s `AGENTS.md`; the divergent documentation commit is ancestorless but has no missing policy content. |
| `docs/infrastructure-agent-authority` | Semantically represented; retain | Its infrastructure authority and Chrome-policy additions are present in `main`'s `AGENTS.md`. Its 21 implementation files were carried unchanged by main commit `94466cd`; later main commits evolve a subset. |
| `origin/docs/infrastructure-agent-authority` | Semantically represented; retain | The remote tip contains the earlier documentation subset already present in `main`'s `AGENTS.md`. |
| `continuous-waiver-ranks` | Fully represented; retain | Tip `0aac5f3` is an ancestor of `origin/main`. |
| `feat/analyze-waivers` | Fully represented; retain | Tip `94466cd` is an ancestor of `origin/main`. |
| `feat/roster-aware-swaps` | Fully represented; retain | Tip `ea36890` is an ancestor of `origin/main`. |
| `fix/available-player-shortlist` | Fully represented; retain | Tip `6c61fcb` is an ancestor of `origin/main`. |
| `improve-waiver-mobile` | Fully represented; retain | Tip `8af0f1f` is an ancestor of `origin/main`. |
| `redesign-discord-surfaces` and `origin/redesign-discord-surfaces` | Fully represented; retain | Tip `03e9a1c` is an ancestor of `origin/main`. |
| `delivery-readiness-issue-13` | Squash-superseded; retain | Its patch is identical to main commit `fcee716` (PR #14), but the original local tip is not an ancestor after squash merge. |

## Worktree disposition

- The shared checkout is intentionally dirty and stale; it was not changed.
- `continuous-waiver-ranks` has an untracked `.venv`, so its worktree is dirty
  and is retained.
- `redesign-discord-surfaces` is an existing registered worktree and is
  retained. Pre-existing branches and worktrees are report-only cleanup
  candidates unless their owner separately authorizes removal.

## Delivery safeguards preserved

No change in this consolidation alters branch protection or workflow
permissions. `main` remains unprotected because the scheduled Sleeper workflow
continues to commit snapshots directly to `main`. That workflow retains its
existing scoped `contents: write`, `pages: write`, and `id-token: write`
permissions; the PR CI workflow remains `contents: read` only.
