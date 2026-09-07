# Fantasy Core Engineering Standard

Use this document for implementation and bug-fix work. It expands the short rules in `AGENTS.md` without turning the root agent file into an encyclopedia.

## KISS Development Principle

**KISS means Keep It Simple, Stupid.** Treat it as a core engineering rule.

Build the **smallest, simplest solution that fully solves the approved task**.

* Prefer boring, proven, understandable approaches over clever or highly abstract ones.
* Reuse established project architecture, helpers, and patterns before introducing new ones.
* Prefer direct code and obvious control flow over unnecessary frameworks or indirection.
* Minimize services, dependencies, processes, abstractions, configuration, persistence, and moving parts.
* Do not build flexibility for hypothetical future requirements without concrete evidence.
* Do not turn a small feature or bug into a broad redesign unless the current architecture genuinely requires it.
* Prefer small, reversible changes when evidence is incomplete.
* Optimize for maintainability: another capable agent should be able to understand, debug, modify, and operate the solution easily.
* Every new component creates operational and maintenance cost. Add one only when its benefit clearly outweighs that cost.
* When several solutions are valid, choose the one with the least complexity and smallest long-term maintenance burden.
* Security should be strong but practical. Prefer a small attack surface over unnecessary security machinery.
* Complexity requires justification. Simplicity does not.

Before adding complexity, ask:

**What is the simplest thing that can reliably work here?**

The goal is not sophisticated architecture. The goal is software that is **correct, fast, secure, reliable, easy to understand, and easy to maintain**.

## Performance & Efficiency

Performance is part of engineering quality.

Use the resources genuinely required to make the product perform extremely well. Do not sacrifice business value or speed merely to minimize CPU, RAM, storage, provider usage, or model usage. Do not waste resources either.

### Data and I/O discipline

For meaningful database, provider, filesystem, network, or model paths, understand:

* how many queries or calls occur;
* how many rows or items are read;
* what fields are fetched;
* whether pagination is bounded;
* whether calls repeat unnecessarily;
* how much loaded data is discarded;
* how much context is passed to a model;
* what is persisted and why.

Rules:

* Fetch only what the current operation needs.
* Prefer targeted queries over bulk reads.
* Avoid full-table, full-universe, or full-history reads when bounded access is sufficient.
* Avoid N+1 database or provider calls.
* Avoid repeated identical I/O inside loops.
* Select only required fields where practical.
* Bound pagination, retries, concurrency, result sizes, and model context.
* Reuse already-fetched trustworthy state when safe.
* Keep expensive or failure-prone I/O visible. Do not hide it inside innocent-looking constructors, properties, packet builders, or deep abstraction chains.
* Do not persist large raw provider payloads without demonstrated reuse value.
* Do not introduce caching merely to conceal an inefficient access path. Fix the underlying path first.

### Total cost

Consider total cost, including:

* latency;
* database reads and writes;
* provider/API calls;
* network round trips;
* model calls and tokens;
* CPU, RAM, and storage;
* developer and review time;
* debugging difficulty;
* operational complexity;
* maintenance burden.

When two approaches solve the problem equally well, prefer the one with fewer moving parts and lower total cost.

Measure before advanced optimization, but obvious waste does not require benchmarking to reject.

If hardware is genuinely the bottleneck, recommend better hardware instead of degrading the application to fit inadequate hardware.

## Architecture & Scope

Prefer simple, boring, proven systems.

* Reuse existing architecture before introducing new foundational technology.
* Standardize on established project and infrastructure patterns where practical.
* Normal libraries and packages may be added when justified.
* Do not casually introduce a new database technology, programming language, container platform, cloud service, queue, broker, worker system, scheduler, orchestration platform, deployment surface, generic framework, plugin system, or multi-agent architecture.
* Keep persistent data clearly separated from replaceable code, caches, logs, and generated state.
* Avoid hidden setup and undocumented dependencies.
* Build only the approved task or milestone.
* Do not silently scaffold future milestones.
* Do not expand scope while debugging.
* A bug does not authorize a redesign. Identify the smallest root cause, repair the right boundary, add focused regression coverage, and stop.
* If a narrow fix genuinely requires a material architecture change, surface that before proceeding.

## Data & State Integrity

Important state must have a clear source of truth.

* Distinguish authoritative state from cached, generated, derived, indexed, or presentation state.
* Represent stale, incomplete, unavailable, or conflicting data explicitly.
* Never fabricate missing state or silently convert unknown values into known ones.
* Keep provider-specific behavior behind understandable integration boundaries.
* Treat provider, model, and other external outputs as untrusted until validated.
* Preserve meaningful existing state unless changing or deleting it is explicitly part of the task.
* Use restart-safe and idempotent state transitions where retries or interruption can occur.
* A retry must not silently duplicate consequential work.
* Do not create competing writable copies of the same truth without an explicit reconciliation model.
* Validate important state transitions at the authoritative boundary rather than relying only on UI or caller behavior.

## Security

Security must protect the system without unnecessary development bureaucracy.

* Never expose or commit passwords, API keys, tokens, cookies, sessions, credentials, `.env` contents, or other secrets.
* Treat exposed credentials as compromised.
* Keep secrets out of code, logs, URLs, errors, fixtures, generated documentation, and other unintended surfaces.
* Applications are private by default unless explicitly designed otherwise.
* Continue using approved Tailscale and private remote-access patterns.
* Minimize permissions and blast radius.
* Keep projects isolated from one another.
* Containers should follow the common hardened baseline wherever practical.
* Enforce authorization at the execution or backend boundary. Interface visibility is not authorization.
* Fail closed when required identity, permission, configuration, or validation is missing.
* Treat external files, URLs, content, provider responses, and model output as untrusted.
* Do not weaken or bypass a security control merely to make a feature work.

## Reliability, Health & Recovery

Every running application must have a clear definition of **healthy**.

* Project agents own the health of their applications. Machine-wide infrastructure health is monitored separately by Infrastructure.
* Services must fail visibly, recover predictably, and report meaningful failures.
* Bound external calls, long-running work, concurrency, and retries.
* Never allow important operations to hang indefinitely.
* Use explicit success, valid no-action or empty, stale or blocked, and failure states where applicable.
* Prefer graceful degradation over fabricated success.
* Preserve the last trustworthy state when a failed refresh does not invalidate it.
* Persist important workflow state when work must survive interruption.
* Use idempotency and duplicate suppression where repeated execution is possible.
* Record enough safe diagnostic context to identify the operation, stage, dependency, and failure.
* Do not swallow errors that materially affect behavior.
* Do not retry indefinitely.
* Do not silently substitute weaker or stale data when doing so could materially change the result.

Recurring and background work must make it possible to distinguish:

* successful run with a result;
* successful run with nothing actionable;
* stale or unavailable dependency;
* execution failure;
* delivery failure;
* unhealthy or not run recently enough to trust.

After a merge or deployment, verify application health. If the new version is clearly unhealthy, use the established rollback or recovery path rather than leaving the application broken.

## Documentation

Maintain useful, current documentation when changes materially affect:

* architecture;
* setup;
* deployment;
* integrations;
* configuration;
* persistent state;
* operating behavior or procedures.

Another capable engineer or agent should be able to understand, operate, debug, and recover the project from its repository and documented configuration.
