# Fantasy QA & Verification Standard

QA is part of implementation. Work is not complete merely because code was written, tests compile, or CI is green.

Every material feature, bug fix, or milestone must be thoroughly verified before handoff.

## 1. Verify the task contract

Re-read the issue, task, or milestone and confirm:

* every requirement and acceptance criterion is implemented;
* explicit technical constraints were followed;
* prohibited or deferred scope was not added;
* behavior outside the authorized scope remains intact.

Do not silently reinterpret missing or conflicting requirements to make the work pass.

## 2. Focused automated testing

Add and run appropriate automated tests for the changed behavior.

Cover where applicable:

* happy paths;
* edge cases;
* malformed or empty inputs;
* calculations and hard constraints;
* state transitions;
* stale or missing data;
* provider failures;
* timeout and retry behavior;
* authorization boundaries;
* duplicate and idempotency behavior;
* persistence and restart behavior;
* failure and recovery behavior.

Tests should validate product behavior, not merely mirror implementation details.

## 3. Regression testing

Run the credible regression surface for every touched subsystem.

* Shared code requires testing affected callers and workflows, not only the new test file.
* Do not hand back work after only narrow unit tests when adjacent behavior could have changed.
* Preserve existing behavior outside the authorized scope.

## 4. Real integration testing

Exercise the real application boundary whenever practical.

Verify as applicable:

* actual data and provider behavior;
* correct source usage;
* persisted state;
* real outputs;
* duplicate suppression;
* retry and failure behavior;
* bounded provider, model, and database activity;
* performance characteristics relevant to the change.

Mocks are useful, but mocks alone are not a substitute for an available safe real integration test.

## 5. Live platform smoke testing

If the change affects Discord, browser workflows, scheduled reports, GitHub Pages or feed publication, or another external surface, test it on that **actual platform** whenever technically possible.

For Discord changes, use the Owner's private **Fantasy EPL Advisor** DM under the standing smoke-test authorization in `BROWSER_AUTH.md`.

Verify as applicable:

* the real request or command is accepted;
* the intended workflow executes;
* the actual result is delivered;
* formatting and message splitting are correct;
* no duplicate response occurs;
* failures are visible and truthful;
* authorization boundaries remain intact;
* no unintended external commitment occurs.

A mocked platform send is not a substitute for an available live smoke test.

## 6. Failure-path testing

Deliberately exercise realistic failure conditions when material, such as:

* provider unavailable;
* stale data or feed;
* empty result;
* timeout;
* malformed downstream response;
* invalid model or output;
* delivery failure;
* duplicate event;
* missing configuration;
* unauthorized request;
* restart after partial progress.

Verify failures are bounded, visible, truthful, and safe.

## 7. Actual output review

Inspect the real user-facing output.

For advisory, reasoning, synthesis, or other user-facing features, verify outputs are:

* factually and logically sound;
* grounded in required evidence;
* useful;
* complete enough for their purpose;
* correctly formatted;
* compliant with supplied product rules;
* honest about uncertainty and failure.

Schema-valid but poor or misleading output is a QA failure.

## 8. Performance verification

For changes affecting data access, providers, models, background tasks, or frequently used flows, inspect actual execution behavior.

Check where applicable:

* database query count;
* rows or items fetched;
* provider call count;
* repeated I/O;
* model call and context size;
* latency;
* concurrency;
* writes and storage produced.

Reject obviously wasteful implementations even when functional tests pass.

## 9. Required CI

All required GitHub checks, including `CI / test`, must pass.

Never dismiss, rename, disable, or bypass a failing required check.

If CI fails, follow `DELIVERY_INFRASTRUCTURE.md` and fix only the demonstrated cause.

## 10. Final-state verification

Before handoff:

* inspect the final diff for accidental scope expansion;
* verify no secrets, caches, virtual environments, logs, generated runtime state, local databases, or unrelated junk are included;
* ensure QA corresponds to the **final PR head**;
* rerun verification invalidated by later fixes;
* inspect final repository and worktree state.

## Defect loop

If QA finds a defect:

1. record expected versus observed behavior;
2. reproduce it;
3. identify the smallest root cause;
4. fix it;
5. add focused regression coverage where useful;
6. re-test the exact failed path;
7. rerun credible adjacent regressions;
8. repeat live-platform verification when applicable.

A code change or new automated test alone does not prove a defect is fixed.

## Testing authorization

The authenticated Owner has standing authorization for comprehensive, risk-proportionate verification needed to test requested Fantasy work. Do not repeatedly request separate testing permission.

This includes, where applicable:

* automated tests;
* safe read-only or dry-run tests;
* integration tests;
* owner-scoped live tests;
* Discord smoke tests;
* safe browser verification;
* minimal temporary dummy data when genuinely required.

When temporary test data is needed, create only the minimum, verify the result, and remove it before handoff.

Continue to respect higher-priority safety requirements and any genuinely required confirmation for irreversible or external consequential actions.

## QA outcomes

Every handoff must state one:

* **QA PASS**: all applicable automated, regression, integration, live-platform, failure-path, output-quality, performance, and CI verification passed.
* **QA PASS WITH DISCLOSED LIMITATION**: verification is strong, but one non-critical path could not be exercised; state exactly what and why.
* **QA FAIL**: required behavior failed; fix and re-run QA before handoff.
* **QA BLOCKED**: required verification cannot be completed because of a specific environment, provider, access, platform, data, or infrastructure blocker.

Never claim completion when required verification remains failing, skipped, stale, or blocked. Do not say "tested thoroughly" without evidence.

QA completion does not itself authorize merge, deployment, publication, or another approval-gated action.
