# OM Automate Project Status

## 2026-07-18 — Baseline acquisition and audit

### Current behaviour

- The upstream Odysseus repository has been cloned from `https://github.com/odysseus-dev/odysseus.git`.
- The immutable starting point is upstream branch `main` at commit `9844a2f9a1996b8c8135a9e7bbde6a72f41df5ed`, matching the source URL in the implementation guide.
- Work is isolated on branch `om-automate/main`.
- The repository advertises Docker and native startup paths, authentication, chat and agent execution, local/API model support, email, CalDAV calendar, tasks, notes, documents, research, memory/RAG, MCP, shell/file tools, backup/restore, and two-factor authentication.
- A reproducible baseline installation and manual browser smoke test have not yet been completed, so no baseline-working claim is made.

### Proposed change

Complete the mandated read-only baseline audit first: trace the implementation, inventory every user-facing feature, review licence/security/branding, run the existing test and startup paths, and record blockers. Product behaviour will not be changed until those findings and an implementation backlog exist.

### Files likely affected

- `docs/om-automate/00-project-status.md`
- `docs/om-automate/01-repository-audit.md`
- `docs/om-automate/02-current-architecture.md`
- `docs/om-automate/03-feature-inventory.md`
- `docs/om-automate/04-agent-architecture.md`
- `docs/om-automate/06-integration-register.md`
- `docs/om-automate/07-security-model.md`
- `docs/om-automate/08-branding-register.md`
- `docs/om-automate/09-bug-register.md`
- `docs/om-automate/10-test-plan.md`
- `docs/om-automate/implementation-backlog.md`
- `docs/om-automate/licence-and-attribution-review.md`
- `docs/om-automate/baseline-smoke-test.md`

### Risks

- The clone initially checked out upstream's default `dev` branch. That untouched pointer is retained as local branch `om-automate/dev-baseline`; all implementation work is based on the requested `main` branch.
- The repository uses many optional local services and model runtimes; external downloads, credentials, and hardware-specific paths may prevent complete integration tests in this environment.
- The requested product scope is security-sensitive and broad; compatibility-sensitive identifiers and AGPL attribution must not be changed blindly.
- Existing workspace data must not be overwritten while exercising setup, migrations, backup, or destructive administration paths.

### Tests required

- Manifest/configuration validation and test collection.
- Existing formatter, linter, type-check, Python, JavaScript, security, and migration suites.
- Native and Docker startup/health checks where available.
- Browser smoke coverage for login, dashboard, chat, tasks, notes, calendar, email settings, knowledge upload, persistence, invalid login, logout, and restart.

### Work completed

- Read the complete 2,241-line OM Automate implementation guide.
- Cloned the exact upstream repository.
- Recorded the source URL, requested starting branch, and starting commit. The initial default-branch checkout was corrected before product changes.
- Created the `om-automate/main` working branch.
- Added the upstream source as the `upstream` Git remote.
- Began parallel architecture, installation, security, licence, and branding audits.

### Files changed

- `docs/om-automate/00-project-status.md` (created)

### Tests run

- None yet; audit and environment discovery are in progress.

### Tests passed

- None yet.

### Tests failed

- None yet.

### Bugs discovered

- None confirmed yet.

### Open risks

- Reproducible baseline startup remains unverified.
- Upstream dependency images and optional runtimes are not yet confirmed to be fully pinned.
- Live Google, Gmail, Calendar, model-provider, and transcription verification will require configured external credentials/models or deterministic local substitutes.

### Next recommended task

Finish the repository/feature/agent/security/licence/branding audits, then execute the supported baseline installation and smoke tests before implementing the first agent-safety slice.

### Manual action required from the user

- None at this stage.

## 2026-07-18 — Baseline installation, smoke test, and audit findings

### Current behaviour

- The application installs and starts natively with Homebrew Python 3.11.14. The live baseline is running on `127.0.0.1:7860` with four bundled MCP child processes and Ollama on `127.0.0.1:11434`.
- Authentication, dashboard loading, local-model chat, tasks, notes, calendar, email setup entry points, knowledge import entry points, restart persistence, logout, and invalid-login rejection were exercised in the in-app browser.
- A local `qwen3:1.7b` model returned the requested deterministic response. The UI also exposed the model's raw reasoning trace; this violates the target requirement to show concise reasoning summaries without hidden chain-of-thought.
- Docker and Compose are installed, but Docker Desktop is not running. A full multi-container launch therefore remains unverified. ChromaDB, SearXNG, and ntfy were not available during the native smoke test, and knowledge/RAG correctly logged degraded availability.
- The database is created by SQLAlchemy plus ad-hoc startup migrations. There is no versioned migration framework or schema-version table.
- Agent execution currently lacks a central, fail-closed policy boundary, generic approvals, durable action state, result verification, and robust cancellation. Model-emitted tool syntax can reach shell, Python, filesystem, and MCP capabilities with excessive access to application data and inherited secrets.

### Proposed change

Finish and review the required audit documents and prioritised backlog. Then implement the first agent-safety slice before adding integrations: a typed canonical tool registry, explicit risk/permission policy, approval state machine, immutable audit records, secret-safe execution boundary, and verified outcomes.

### Files likely affected

- Audit and planning documents under `docs/om-automate/`
- Startup-critical tests under `tests/`
- Agent/tool execution modules under `src/`, `routes/`, and `core/` after the audit gate
- Authentication storage and application file-permission handling after dedicated regression tests exist

### Risks

- Shell/Python subprocesses inherit the application environment and can access secrets; file tools currently treat the whole data directory as an allowed root.
- A corrupt authentication store can fail open and permit first-user administrator setup.
- Dependency and container versions are not reproducibly pinned; Python versions differ across native, CI, and Docker paths.
- Fresh `.env`, authentication, database, settings, sessions, and log files were created with mode `0644` rather than a secrets-safe mode.
- `/api/ready` requires authentication and checks too little to serve as an orchestrator readiness probe.
- The main application log lives under `data/logs`, while Compose's separate logs mount targets `/app/logs`.
- Compatibility-sensitive `ODYSSEUS_*` settings, cookies, headers, storage keys, database values, and paths require aliases/migrations rather than blind replacement during rebranding.
- AGPL-3.0-or-later obligations and upstream attribution must remain; existing MIT wording in `ACKNOWLEDGMENTS.md` and `Dockerfile` conflicts with the repository licence and must be corrected carefully.

### Tests required

- Automated startup-critical health/auth/configuration tests that do not mutate product behaviour.
- Regression tests for fail-closed authentication, secret-safe subprocess environments, filesystem policy boundaries, tool argument validation, approval enforcement, cancellation, idempotency, audit records, and outcome verification.
- A single clean full-suite run in a short temporary directory with socket access.
- Docker build/start/readiness and persistent-volume tests once Docker Desktop is available.
- Manual browser smoke tests after each implementation slice.

### Work completed

- Created a Python 3.11 virtual environment and installed the baseline requirements; `pip check` passes.
- Ran native setup with an isolated local administrator and verified the SQLite database (`32` tables; integrity check successful).
- Started, stopped, and restarted the application; measured approximately `217.6 MiB` idle RSS across Uvicorn and four MCP children.
- Verified `/api/health`, `/api/version`, auth status, login redirect, login success/failure, dashboard, Ollama chat, task and note creation, calendar, email setup entry points, knowledge import entry points, restart persistence, logout, and cleanup of temporary task/note fixtures.
- Completed read-only architecture, agent, security, licence, attribution, branding, installation, dependency, storage, and test audits.
- Tagged the immutable upstream baseline as `om-automate-baseline` and retained the untouched upstream default-branch pointer as `om-automate/dev-baseline`.

### Files changed

- `docs/om-automate/00-project-status.md`
- Required audit documents are being created in the same directory; no product code has been changed yet.

### Tests run

- `pip check`
- Python compilation/AST parsing across the application
- JavaScript syntax checking across static modules
- Shell syntax checking across launch scripts
- Compose configuration validation for base and GPU/host overlays
- Pytest collection and a full restricted run, followed by focused reruns with socket access and a compatible temporary data path
- Manual in-app browser baseline smoke and restart-persistence flow

### Tests passed

- `pip check`: passed.
- Python: `985` files parsed, `0` failures.
- JavaScript: `160` files checked, `0` failures.
- Shell: `9` scripts checked, `0` failures.
- Compose configuration: all inspected variants passed.
- Pytest: all `4,527` collected tests passed across the full run plus isolated reruns.
- Manual baseline smoke: all required entry points and persistence assertions passed under the native/degraded-services configuration.

### Tests failed

- The first restricted pytest run ended with `4,501 passed`, `23 failed`, and `3 skipped`. Twenty-one failures required local socket access; two research tests assumed a repository-relative data path while the run redirected `ODYSSEUS_DATA_DIR`. Focused reruns cleared all failures, but one clean full-suite invocation has not yet been recorded.
- Docker runtime smoke was blocked because the Docker daemon is stopped.

### Bugs discovered

- Critical: ungoverned shell/Python/filesystem/MCP execution can expose application secrets and sensitive local data.
- Critical: unreadable or corrupt authentication state fails open to unconfigured setup.
- High: no central agent policy, generic approval workflow, durable action state, or result-verification contract.
- High: Stop cancels the response stream without reliably cancelling the active child tool task; detached runs are memory-only.
- High: raw model reasoning is shown in chat.
- High: dependencies and service images are largely unpinned, and CI deliberately allows pytest failure.
- High: inbound task webhooks lack strong authenticity, replay, idempotency, and body/rate controls.
- Medium/high: OAuth, encryption-key lifecycle, backup confidentiality, session/TOTP storage, readiness, log mounts, shutdown, and migration behaviour need hardening.
- Confirmed correctness defects include a `tail_serve_output` schema-to-conversion failure and a cold-import circular dependency in the fragmented tool registry.

### Open risks

- Live Google/Gmail authorization, mail send/draft side effects, external Calendar writes, meeting transcription, and full container orchestration require dedicated test credentials or deterministic provider doubles before production claims can be made.
- The current temporary local administrator password must not become release configuration and must be rotated or the test data reset before final handoff.
- A legal professional should review distribution/source-offer language before any public redistribution; the project review is technical guidance, not legal advice.

### Next recommended task

Complete the mandated audit documents and automated baseline smoke gate, present the initial findings, then implement and verify the typed, policy-governed agent execution foundation.

### Manual action required from the user

- None for the native baseline. Docker Desktop will need to be started before the full container build and launch gate.

## 2026-07-18 — SAFE-001 inspection: agent Stop propagation

### Current behaviour

- `agent_runs.stop()` cancels the detached drain task, and the drain closes the outer chat/agent generator.
- During a tool round, `stream_agent_loop()` creates a separate `_tool_task` and waits for its progress queue. The generator has no `finally` ownership of that child task.
- If Stop arrives while the generator is waiting for tool progress, the outer run becomes `stopped` but the child tool can continue and perform a side effect after the UI has stopped.

### Proposed change

Introduce a small, dependency-neutral cancellable tool-run lifecycle that owns the child task and progress queue. Wire the agent loop through it so every exit path cancels and awaits a still-running child before the outer stream can settle. This slice will not yet claim durable provider reconciliation; that follows in the durable action/verification work.

### Files likely affected

- `src/agent_loop.py`
- A new focused lifecycle module under `src/`
- Focused lifecycle tests under `tests/`
- `docs/om-automate/decisions/ADR-0001-agent-tool-cancellation-ownership.md`
- Agent/security/test/bug/status documentation

### Risks

- Cancelling too broadly could stop detached runs merely because an SSE subscriber disconnects; only explicit run cancellation must propagate to the tool.
- Cancellation can race with normal tool completion or a progress sentinel.
- Some provider calls cannot guarantee remote cancellation; local task cancellation must not be misreported as verified reversal of a remote effect.
- A cancellation cleanup await must not hide the original exception or hang indefinitely.

### Tests required

- Reproduce cancellation while the child tool is blocked and prove its cancellation cleanup executes before the outer consumer finishes.
- Preserve normal completion, progress ordering, and tool exception propagation.
- Preserve detached-run behavior on subscriber disconnect and existing Stop partial-save behavior.
- Run focused lifecycle/agent-run tests, related agent/tool tests, full suite, startup probes, and a browser Stop scenario.

## 2026-07-18 — SAFE-001 local cancellation checkpoint

### Work completed

- Added `CancellableToolRun`, an acyclic lifecycle owner for one tool child and its progress queue.
- Wired `stream_agent_loop()` through that lifecycle with `try/finally`, so explicit Stop cancels and awaits a still-running tool child before the outer run settles.
- Added deterministic tests for cancellation cleanup, normal result/progress order, exception propagation, and real agent-loop wiring.
- Added a small browser helper that settles a stopped tool node as `cancelled`, clears timers/animation, and replaces the stale bash/Python `Running` verb with the concrete tool label.
- Corrected two test-isolation defects: deep-research report fixtures now honor configured data storage, and the macOS confinement assertion compares canonical discovered paths across `/tmp` and `/private/tmp` aliases.
- Used a temporary loopback-only deterministic OpenAI-compatible fixture to exercise a real browser Agent → fenced bash tool → Stop flow. It was removed afterward together with its model endpoint and four temporary chats.
- The delayed command was `sleep 20; touch /private/tmp/omauto-stop-marker-019f7596`. Stop was pressed while the card showed `Running`; the node settled, and the marker remained absent after the original deadline.
- Reloaded the updated browser bundle successfully and kept the native application running on `127.0.0.1:7860`.

### Files changed

- `src/tool_run_lifecycle.py`
- `src/agent_loop.py`
- `static/js/toolRunStatus.js`
- `static/js/chat.js`
- `tests/test_tool_run_cancellation.py`
- `tests/test_chat_stop_tool_status_js.py`
- `tests/test_research_report_read.py`
- `tests/test_workspace_confine.py`
- Audit, architecture, test, bug, backlog, smoke, status, and ADR documents under `docs/om-automate/`

### Tests run

- Red/green focused lifecycle regression (`ModuleNotFoundError` before implementation; 4 passed afterward).
- Red/green stopped-tool DOM regression (2 failures before implementation; 2 passed afterward).
- Related cancellation/agent/scheduler set: 72 passed.
- Startup-critical baseline probe: 5 passed.
- Environment-sensitive socket/path focused set: 5 passed.
- Python compilation for changed runtime modules.
- Node syntax checking for changed browser modules.
- Full isolated, socket-enabled suite with `ODYSSEUS_DATA_DIR=/tmp/od` and `TMPDIR=/tmp/ot`.
- Native startup, authenticated in-app browser Stop probe, updated-bundle reload, and final `/api/health` probe.

### Tests passed

- Final full suite: **4,535 passed, 3 expected skips, 8 warnings in 135.54 seconds**, exit 0 in one command.
- Browser cancellation: the local shell effect did not occur after Stop.
- Final liveness: `/api/health` returned HTTP 200 with `status=healthy`.

### Tests failed

- Expected red tests were recorded before implementation.
- The first post-change full attempt exposed four overlong Unix-socket fixture paths; a short temp path cleared them.
- The second attempt exposed the known macOS `/tmp` versus `/private/tmp` assertion defect; the canonical-path correction passed focused tests and the final full run.
- No failure remains in the final gate. Three platform/dependency-conditioned skips and eight existing warnings remain tracked.

### Bugs discovered or updated

- OM-BUG-004 is fixed for owned in-process tool tasks. Provider-side cancellation/readback and indeterminate-effect reconciliation remain part of SAFE-005/SAFE-007.
- The Stop UI had simultaneously displayed `Running` and `stopped`; it now renders the concrete tool plus `cancelled`.
- OM-BUG-030's macOS alias assertion is fixed; broader sanitized error design remains open.
- Three scheduler tests still emit unawaited-coroutine warnings; SQLAlchemy and Pydantic deprecations remain.

### Open risks

- Coroutine cancellation does not prove a remote provider did not commit an effect. Durable action attempts, idempotency, bounded worker termination, provider readback, and compensation are still required.
- The system still accepts executable structured model prose and lacks the canonical registry/policy/approval/audit boundary.
- Docker runtime launch, dependency locks, permission/readiness/auth hardening, and all later milestone features remain open.

### Next recommended task

Create ADR-0002 and implement SAFE-002: an acyclic typed canonical tool registry that unifies schema, handler, risk/scope, confirmation, timeout/retry, idempotency, reversibility, verification, and presentation metadata. Begin with characterization/completeness tests and the confirmed `tail_serve_output` drift/cold-import failure.

### Manual action required from the user

- None for this checkpoint. Docker Desktop still needs to be started before the full container runtime gate.
