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

## 2026-07-18 — SAFE-002 inspection: canonical typed tool registry

### Current behaviour

- Built-in capability metadata is split across five independent sources: 67 native schemas, 73 executable fence tags, 31 registry handlers, 58 prompt sections, and 69 retrieval descriptions. Their union contains 74 names, while only 27 occur in every source.
- `tail_serve_output` is advertised as a native function and has a legacy dispatcher branch, but is absent from `TOOL_TAGS`; native conversion therefore logs `Unknown function call` and returns `None`.
- Seven executable tags have no native input schema: `ai_draft_email_reply`, `download_attachment`, `draft_email`, `draft_email_reply`, `generate_image`, `manage_research`, and `search_emails`.
- A fresh interpreter cannot import `src.tool_schemas`; `tool_schemas → agent_tools → tool_schemas` fails on a partially initialized module. Security and execution code contain import-order workarounds for the same cycle.
- Permission, risk, confirmation, timeout, retry, idempotency, reversibility, compensation, audit, verification, and presentation rules are not represented by one validated contract.

### Proposed change

- Add an acyclic, dependency-light registry contract with immutable typed definitions and explicit risk, permission, confirmation, retry, timeout, idempotency, reversibility, compensation, audit, verification, and presentation metadata.
- Move shared tool identity primitives out of the `agent_tools` facade, generate compatibility exports from the canonical registry, and reject duplicate or incomplete definitions during validation.
- Preserve all existing call formats and dispatch behavior while migrating incrementally; first repair cold imports, registry drift, and `tail_serve_output`, then route remaining schema/index/policy/handler consumers through generated views.
- Keep MCP-discovered tools in a separately validated dynamic namespace rather than pretending they are static built-ins.

### Files likely affected

- New `src/tool_registry.py` and registry metadata modules if separation is needed.
- `src/agent_tools/__init__.py`, `src/tool_schemas.py`, `src/tool_parsing.py`, `src/tool_index.py`, `src/tool_security.py`, `src/tool_execution.py`, and `src/agent_loop.py` compatibility consumers.
- New focused registry contract/import/parity tests, plus existing tool parsing, policy, schema, execution, and agent tests.
- `docs/om-automate/decisions/ADR-0002-canonical-tool-registry.md` and registry/security/architecture records.

### Risks

- Changing import direction can break application startup or tests that depend on historical facade import order.
- Treating every fence tag as a native function without a deliberate exposure flag could expand model authority.
- Incorrect conservative risk/permission defaults could allow a consequential action or block existing safe reads.
- Eagerly importing tool implementations into the registry could recreate cycles and trigger heavyweight provider side effects.
- A big-bang dispatcher rewrite could change owner/session/workspace/progress propagation.

### Tests required

- Reproduce the cold-import failure and `tail_serve_output` conversion failure before implementation, then make both green.
- Validate uniqueness, immutability, required metadata, four-level risk classification, confirmation invariants, positive finite timeouts, bounded retry policy, schemas, audit/verification fields, and known handler routes.
- Assert every built-in executable name has exactly one canonical definition and compatibility views have no orphan names.
- Preserve unknown/malformed-call rejection, email aliases, plan-mode fail-closed behavior, tool parsing/stripping, native schema filtering, handler owner/session propagation, and MCP namespace behavior.
- Run formatter/lint/type checks available in the repository, focused and related suites, the full suite, fresh application startup, and a browser smoke before checkpointing.

## 2026-07-18 — SAFE-002 checkpoint A: acyclic tool identity and reachable cookbook diagnostics

### Work completed

- Added dependency-free `ToolBlock` ownership in `src/tool_types.py`.
- Moved the canonical built-in fence/email/internal-only name inventory into the side-effect-free `src/tool_registry.py` foundation and retained facade re-exports.
- Kept `vault_search`, `vault_get`, and `vault_unlock` explicitly inventory-visible but internal-only; they were not exposed to models merely to equalize set counts.
- Added the omitted `tail_serve_output` fence surface. Native conversion and fenced parsing now reach its existing executor.
- Removed the `tool_schemas/tool_parsing → agent_tools facade → tool_schemas/tool_parsing` import cycle. Both low-level modules now cold-import in independent interpreters.
- Moved the built-in email-name source into the dependency-light catalog and made server-side security import that source.
- Accepted ADR-0002, which separates definitions, surfaces, effective operation policy, and lazy runtime binding and forbids permissive defaults for unclassified tools.
- Added current-state migration, user, and administrator guides with explicit target/not-yet-implemented labels.

### Files changed

- `src/tool_types.py`
- `src/tool_registry.py`
- `src/agent_tools/__init__.py`
- `src/tool_parsing.py`
- `src/tool_schemas.py`
- `src/tool_security.py`
- `tests/test_tool_registry_foundation.py`
- `docs/om-automate/00-project-status.md`
- `docs/om-automate/11-migration-guide.md`
- `docs/om-automate/12-user-guide.md`
- `docs/om-automate/13-admin-guide.md`
- `docs/om-automate/decisions/ADR-0002-canonical-tool-registry.md`

### Tests run

- Red characterization: three expected failures reproduced both cold-import cycles and the missing `tail_serve_output` tag.
- Green focused characterization: 3 passed.
- Related schema/parser/fence/email/policy/workspace/agent/task tests: 168 passed.
- First complete run inside the restricted sandbox: 4,518 passed, 3 skipped, 20 failed, 8 warnings. Every failure required a forbidden loopback socket bind or DNS resolution; no registry assertion failed.
- Identical complete run with loopback socket/DNS access: 4,538 passed, 3 skipped, 8 warnings in 136.04 seconds.
- Fresh native Uvicorn restart from the changed import graph.
- Authenticated in-app browser reload and DOM smoke of the existing conversation/composer/tool controls.
- Live `/api/health` probe after restart.

### Tests passed

- Final release gate for this slice: **4,538 passed, 3 expected skips, 8 tracked warnings**, exit 0.
- Native startup completed and all four available bundled MCP servers connected.
- Browser remained authenticated and rendered the chat application after reload.
- Live liveness returned HTTP 200 with `status=healthy`.

### Tests failed

- The three initial red tests failed exactly as intended before implementation.
- The sandboxed full run produced 20 environment-only networking failures; the required socket/DNS-enabled rerun passed every test without code changes.
- No product/test failure remains in the final gate.

### Bugs discovered or updated

- OM-BUG-009 is fixed for the confirmed `tail_serve_output` ingress defect and low-level cold imports. The larger metadata/handler/policy/UI drift remains open until all compatibility views are generated from typed definitions.
- The static executor contains three previously uncounted vault capabilities. They are now accounted for as internal-only registry debt rather than silently advertised.
- Plan-mode fallback omits `edit_file` when schema loading fails, timeout promises disagree with runtime enforcement, and static admin UI metadata contains stale `manage_rag`; these move into the next registry-policy slices.

### Open risks

- `src/tool_registry.py` currently owns identity/surfaces only. Immutable typed definitions, strict validation, operation-level policy, handler binding, output schemas, timeout/retry enforcement, and generated UI/index/prompt views are not implemented yet.
- The remaining broad `manage_*` tools require validated action-specific policy; a blanket risk classification would be unsafe.
- Dynamic MCP tools still enter without the required OM permission/risk/audit/verification overlay.
- The known MCP cancel-scope warnings remain on shutdown; Chroma/SearXNG/ntfy and Docker runtime remain unavailable in the current native environment.

### Next recommended task

Add the immutable registry contract and frozen golden inventory. Classify the core/filesystem/shell domain first, make every unclassified legacy capability explicit and fail-closed, then derive plan-mode and runtime timeout policy from those definitions before migrating broader personal-data/provider domains.

### Manual action required from the user

- None for this slice. Docker Desktop is still required later for the container launch gate.

## 2026-07-18 — SAFE-002 inspection B: immutable definition contract and frozen migration debt

### Current behaviour

- The first registry slice now owns all 77 known built-in identities and intentionally separates 74 model-fence names from three internal-only vault executors.
- Registry records do not yet express schemas, granular permissions, effective risk/confirmation, retry/idempotency, compensation, audit/redaction, verification, examples, presentation, or binding type.
- The 67 native input schemas remain a compatibility list; seven fence/MCP tools and three internal vault capabilities require deliberate schema/exposure records.
- There is no machine-enforced distinction between a new fully classified definition and historical unclassified migration debt.

### Proposed change

- Add frozen enums/value records for surfaces, migration state, risk, confirmation, retry, idempotency, audit, verification, presentation, and complete `ToolDefinition` metadata.
- Add a deterministic `ToolRegistry` that rejects duplicate names/aliases, malformed names/schemas, missing bindings, invalid timeouts/retries, and unsafe confirmation/idempotency combinations.
- Introduce an explicit, test-pinned legacy-debt allowlist. Unclassified records resolve fail-closed and the allowlist may shrink but cannot silently grow.
- Materialize all 77 current names as registry records without changing their existing exposure. Classify the first simple core/filesystem/shell operations individually; leave mixed wrappers visibly unclassified until action-level policy is designed.

### Files likely affected

- `src/tool_registry.py` and possibly a separate catalog module if data size warrants it.
- `tests/test_tool_registry_contract.py` and `tests/test_tool_registry_foundation.py`.
- ADR/status/agent architecture and bug/backlog records.

### Risks

- Deep immutability must not make compatibility JSON-schema serialization invalid.
- Lazy schema assembly must not recreate the repaired import cycle.
- Auto-generated descriptions/examples must not disguise missing policy or grant a new native/fence surface.
- Static validation cannot classify mixed `manage_*` actions safely; unknown operations must remain Level 3/always-confirmed once enforcement is connected.
- A registry that is not yet used by the executor must not be represented as permission, approval, timeout, audit, or verification enforcement.

### Tests required

- Records and nested schema/policy data are immutable.
- Duplicate names, aliases, name/alias collisions, invalid names, reserved dynamic namespace collisions, non-object schemas, missing fields/bindings, invalid timeout/retry combinations, and confirmation/risk violations are rejected.
- Exact golden inventory contains 77 identities, with vault tools internal-only and every legacy name explicitly accounted for.
- Surface projections preserve the current native/fence/internal boundaries and do not expose missing-schema or vault tools accidentally.
- New unclassified records outside the frozen debt allowlist fail validation; strict validation continues to fail until debt reaches zero.
- Focused registry tests, all existing schema/parser/policy tests, full suite, fresh startup, and browser smoke remain green.

## 2026-07-18 — SAFE-002 checkpoint B: immutable registry metadata and canonical projections

### Work completed

- Added an immutable `ToolDefinition`/`ToolRegistry` contract and frozen supporting records for surfaces, migration state, risk, confirmation, retry, idempotency, audit, verification, presentation, schemas, examples, and lazy bindings.
- Froze the complete built-in inventory at **77 canonical identities**. Exactly **12** simple operations are typed/classified; the remaining **65** are explicit `legacy_unclassified` debt with fail-closed registry metadata: Level 3, always-confirmed, no retry, no idempotency assumption, indeterminate verification, and manual reconciliation.
- Split native schema data/conversion into the pure, handler-free `src/tool_schema_catalog.py`. `src/tool_schemas.py` is now a thin compatibility facade, preserving existing imports without recreating the repaired tool-module cycle.
- Froze the plan-mode compatibility allowlist at exactly **23 names** and derive its denylist as the exact **54-name** complement of the canonical inventory. The deny projection includes `edit_file`, `vault_search`, `vault_get`, and `vault_unlock` and therefore cannot omit them through schema-import fallback.
- Made `src/tool_policy.py` consume canonical static identities and add only the separately declared dynamic native capability `builtin_browser`.
- Added `tail_serve_output` to the coarse non-administrator blocklist as an interim gate while operation ownership is still being designed.

### Frozen plan-mode compatibility allowlist

```text
ask_teacher              chat_with_model          get_workspace
glob                     grep                     list_cached_models
list_cookbook_servers    list_downloads           list_email_accounts
list_emails              list_models              list_serve_presets
list_served_models       list_sessions            ls
read_email               read_file                resolve_contact
search_chats             search_emails            search_hf_models
web_fetch                web_search
```

`plan_mode_disabled_tools()` is `BUILTIN_TOOL_NAMES - PLAN_MODE_ALLOWED_TOOL_NAMES`: 54 canonical names. This is a frozen compatibility projection, not an inference from risk metadata.

### Focused verification recorded

- Earlier registry/policy characterization: **37 passed**.
- New immutable contract suite: **28 passed**.
- Earlier combined focused checkpoint gate: **62 passed**.
- Latest expanded focused gate: **77 passed, 1 warning**.
- Final-state restricted full suite: **4,558 passed, 3 skipped, 20 failed, 8 warnings in 132.80 seconds**. All 20 failures require loopback TCP, overlong/forbidden Unix-socket creation, or DNS access denied by the restricted sandbox; no registry/policy assertion failed.
- The required socket-enabled rerun could not start because the escalation request hit the account usage limit until **2026-07-25**. Do not treat the restricted run as a full pass.
- Checkpoint A's earlier socket-enabled **4,538 passed, 3 skipped** result remains valid for its prior code only; it is not release evidence for checkpoint B.
- Checkpoint B therefore does not claim a passing full-suite, startup, browser, container, or release qualification gate.

### Scope boundary and remaining debt

- Checkpoint B implements **registry metadata, validation, and compatibility projections only**. The executor does not yet consume registry permissions, approvals, risk decisions, timeouts, retries, idempotency, compensation, audit, or verification as runtime enforcement.
- **16 of the 23 plan-allowed tools remain `legacy_unclassified` compatibility debt:** `ask_teacher`, `chat_with_model`, `list_cached_models`, `list_cookbook_servers`, `list_downloads`, `list_email_accounts`, `list_emails`, `list_models`, `list_serve_presets`, `list_served_models`, `list_sessions`, `read_email`, `resolve_contact`, `search_chats`, `search_emails`, and `search_hf_models`.
- The `tail_serve_output` gate blocks non-administrators, but the tool still does not prove that the requested session belongs to the caller or that it is the fresh failed launch produced by the required `serve_model` → `list_served_models` sequence.
- Runtime schemas, handlers, prompt/index/UI presentation, MCP discovery, and the legacy dispatcher are not yet all generated from the registry.

### Bugs discovered or updated

- OM-BUG-009 remains partially open: registry identity/import drift is repaired and the immutable catalog exists, but runtime consumers and `tail_serve_output` ownership/launch-sequence enforcement are incomplete.
- OM-BUG-023 remains open: bash/Python metadata records 3,600-second timeouts, the prompt promises 60 seconds, compatibility constants say 60/30 seconds, and the worker still independently enforces 3,600 seconds.
- OM-BUG-031: `update_plan` emits an event without checking for an active plan, while `static/js/chat.js` calls the undefined `_setStoredPlan`; the advertised no-active-plan no-op is not implemented.
- OM-BUG-032: nominal `manage_bg_jobs` list/output reads invoke global `bg_jobs.refresh()`, which can kill timed-out jobs and prune records/files across all sessions before session filtering.
- OM-BUG-033: `_MCP_TOOL_MAP` still routes bash, Python, filesystem, and web tools through removed built-in MCP server IDs before falling back to native handlers.
- OM-BUG-034: `format_tool_result()` selects the `stdout` branch for timeout results and drops their `error` field, so the LLM can receive only exit code 124 rather than the timeout reason.

### Next recommended task

Connect registry policy to a deny-by-default operation-level runtime decision without broadening authority. First repair the four newly recorded execution/presentation defects, add owner and launch-sequence enforcement to `tail_serve_output`, classify the 16 plan-compatible reads, and make timeout/formatter behavior contract-tested before migrating mixed `manage_*` actions.

### Manual action required from the user

- None for this metadata/projection checkpoint.

## 2026-07-18 — SAFE-002 execution-helper remediation checkpoint

### Work completed

- Bound `update_plan` to a request-local active-plan record carrying session, plan identity, and monotonic version. Calls now fail closed when no active approved plan exists, subsequent agent rounds receive the new checklist revision, and SSE updates include compare-and-set metadata.
- Replaced the browser's undefined `_setStoredPlan` call with a version-checked plan state module. Wrong-session, wrong-plan, stale, and replayed events are rejected; legacy `{sid, text}` browser state is migrated. The previously removed proposal/approval UI and a durable server-side plan record are not restored by this checkpoint.
- Made `manage_bg_jobs` list and output paths observational. They no longer call global reconciliation, persist state, kill timed-out processes, prune other chats, or delete their artifacts. Explicit kill now checks chat ownership inside the mutating store operation.
- Removed stale native-to-MCP aliases for bash, Python, filesystem, and web tools. Unqualified calls now use their native handlers; explicitly qualified MCP calls remain MCP calls and fail closed without error-string fallback. `generate_image` remains the only bundled unqualified MCP alias.
- Preserved timeout errors in the LLM-facing formatter alongside stdout/stderr and exit code, without repeating the same error text.
- Added an internal random identity per streamed agent request and threaded it through the executor. The identity is generated by the application, not accepted from model arguments.
- Added a process-local, one-shot capability for cookbook diagnostics. `tail_serve_output` now requires the same owner and internal request to launch the exact serve task, observe it in `error`, `crashed`, or `failed` through `list_served_models`, and consume the exact session/host grant before expiry. Cross-owner, cross-request, host-redirection, stale, and replayed reads deny before shell or HTTP execution.
- Repaired isolated `test_review_regressions.py` execution by including the production `core.log_safety` dependency in its deliberately narrow import stubs.

### Verification recorded

- Focused/related gates passed in three groups: **62**, **91**, and **122** tests (**275 total**) across plan state, agent policy, request identity, cookbook diagnostics, dispatcher/MCP routing, timeout rendering, background jobs, registry contracts, workspace confinement, and sensitive-path enforcement.
- The final restricted full suite reached **4,600 passed, 3 skipped, 20 failed, 8 warnings in 133.07 seconds**. The 20 failures are the same environment-only loopback TCP, Unix-socket, and DNS cases recorded at checkpoint B; no remediation test or product assertion failed.
- Socket-enabled execution, current-code startup, browser smoke, and container qualification could not be repeated because the escalation service reports the account usage limit until **2026-07-25**. The still-running browser/server process predates this checkpoint and is not evidence for these changes.

### Scope boundary and remaining debt

- OM-BUG-032, OM-BUG-033, and OM-BUG-034 have implemented, focused-regression-tested fixes. They remain in the open register until the required socket-enabled full suite, startup, and applicable browser/runtime gates pass.
- OM-BUG-031 is materially safer and no longer throws in the browser, but plan ownership remains browser-backed/request-local. A durable server-side plan/run record and cross-process compare-and-set are still required under SAFE-005; the historical proposal/approval UI remains intentionally absent pending the generic Approval Centre.
- Cookbook diagnostic grants fail closed on restart and prevent the confirmed cross-owner/fresh-sequence defect, but the ledger is intentionally process-local. Durable action/attempt ownership and audit state must replace it in SAFE-005.
- SAFE-002 remains incomplete: registry metadata still does not authorize runtime execution, 65 tools remain unclassified, and registry timeouts are not yet enforced.

### Next recommended task

Make the canonical registry authoritative at the executor boundary without broadening capability. Classify the safe read set first, add one typed allow/deny/require-approval decision, fail closed for unknown/unclassified or missing bindings, and make runtime deadlines consume registry policy before enabling consequential actions.

### Manual action required from the user

- None for implementation. Socket-enabled, startup, browser, and container gates remain environment-dependent release work.
