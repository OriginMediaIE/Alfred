# OM Automate repository audit

**Audit date:** 2026-07-18
**Source repository:** `https://github.com/odysseus-dev/odysseus`
**Working branch:** `om-automate/main`
**Audited commit:** `9844a2f9a1996b8c8135a9e7bbde6a72f41df5ed` (`chore(release): bump version to 1.0.2`)
**Audit status:** Source architecture and focused tests inspected; the native browser baseline and restart-persistence smoke test are complete and recorded in `baseline-smoke-test.md`. Docker runtime smoke remains blocked by the stopped Docker daemon.

## Scope and method

This audit records the implementation that exists before the OM Automate transformation. It is based on direct source inspection, focused lifecycle/security tests, clean-process import probes, runtime tool-inventory probes, and Git state. It does not infer behaviour from the upstream README alone.

The audit covered startup, presentation, API routes, application services, persistence, the model and agent lifecycle, tool registration and execution, bundled and external integrations, security gates, scheduling, streaming, and tests. Detailed request flows are in [02-current-architecture.md](02-current-architecture.md); the current and target agent designs are in [04-agent-architecture.md](04-agent-architecture.md).

## Baseline repository state

- The audited checkout is on the required `om-automate/main` branch and tracks `origin/main`.
- No populated `.env`, database, upload, log, or model artifact was added by this audit.
- The code still identifies itself as Odysseus in many visible and internal locations. For example, the FastAPI title remains `AI Chat Application`, while `launcher.py:38-100` contains Odysseus splash, tray, and menu labels. Rebranding requires the separate branding and licence review; internal identifiers must not be globally replaced.
- The original licence and attribution files must be retained until the licence review determines which notices are mandatory.

## Repository map and disposition

File counts are a point-in-time inventory of the audited checkout. “Retain” means preserve working behaviour; it does not mean leave the implementation untouched.

| Area | Approximate size | Responsibility and public interfaces | Dependencies, storage, security and tests | Decision |
|---|---:|---|---|---|
| `app.py` | 1 file, 1,276 lines | FastAPI composition root; middleware; route registration; SPA/static delivery; liveness/readiness; startup and shutdown | Imports managers from `core`, `services`, `src`, and nearly every route package. Auth bypass, CORS and process-global lifecycle state make this security-sensitive. Covered indirectly by route/startup tests. | **Refactor incrementally.** Keep as composition root; move manager construction and lifecycle jobs into explicit bootstrap modules. |
| `launcher.py` | 1 file, 143 lines | Standalone Windows/PyInstaller launcher, splash, tray, browser opening, Uvicorn startup | Defaults to `127.0.0.1:7000`; contains visible legacy branding and broad `except Exception` paths. | **Retain and refactor.** Centralise brand values and expose startup failures rather than silently swallowing all GUI errors. |
| `companion/` | 4 files, 3 Python | Read-only LAN companion pairing/access bridge | Shares main app authentication and storage; network exposure requires narrow scopes and explicit bind policy. | **Retain behind a feature flag; harden and document.** |
| `core/` | 11 Python files | SQLAlchemy models/database bootstrap, authentication, in-memory chat models, session manager, constants | `core/database.py` is 2,405 lines and contains models plus manual migrations. `core/models.py` has hidden persistence side effects. `core` imports `src`, weakening the intended dependency direction. | **Refactor.** Separate schema/migrations, repositories, session cache, and domain records. Preserve database compatibility. |
| `config/` | 1 file | SearXNG configuration | Mounted into the search container; contains externally exposed search behaviour. | **Retain, version, and validate.** |
| `docker/` | 5 files | Container entrypoint and runtime support | Entrypoint drops privileges and forwards signals. Works with bind-mounted data/log directories. | **Retain and harden.** Add reproducible image pins and installation checks. |
| `docker-compose.yml` | 1 file | Local app, Chroma, SearXNG and ntfy topology | App at `127.0.0.1:7000`; Chroma at `127.0.0.1:8100`; SearXNG at `127.0.0.1:8080`; ntfy at `127.0.0.1:8091`. Main SQLite and files are under `./data`; logs under `./logs`. | **Retain as primary local deployment, refactor for one-click, pinned, cross-platform installation.** |
| `docs/` | 19 tracked files before OM audit docs | Upstream operation and feature documentation | Documentation does not yet represent the target product or all implementation gaps. | **Retain attribution/history; extend with the OM Automate project record.** |
| `integrations/` | 6 files, 2 Python | Claude/Codex API and skill compatibility wrappers | Provider-specific and route-facing; depends on external tools and credentials. | **Retain as adapters; move behind provider-neutral application interfaces.** |
| `mcp_servers/` | 5 Python files | Bundled email, image generation, memory and RAG MCP servers | Email uses additional SQLite files; tools cross a process/protocol boundary. Results are commonly flattened to text. | **Retain protocol support; replace bespoke effect/approval handling with typed domain commands and generic audit/approval records.** |
| `routes/` | 65 Python files | FastAPI HTTP, SSE and integration endpoints | Contains application orchestration and direct SQLAlchemy access: 205 `SessionLocal`-family references across 25 route files. Compatibility shims replace modules in `sys.modules`. | **Refactor by domain.** Routes should validate transport data and call application use cases, not manipulate tables or run agent policy. |
| `scripts/` | 43 files, 16 Python | Installation, maintenance, diagnostics and model/runtime helpers | Several are platform-specific and may execute local or remote commands. | **Audit individually; retain supported scripts, replace duplicate install paths with one versioned installer.** |
| `services/` | 42 files, 40 Python | Partial services for documents, memory, research, search, shell, speech, YouTube and hardware fit | Not yet a consistent domain boundary. Search and other modules have compatibility duplicates under `src`. | **Retain behaviour; reorganise into provider-neutral domain services and application handlers.** |
| `specs/` | 1 file | Existing specification artifact | Limited coverage of the current product contract. | **Retain and expand only where executable contracts are useful.** |
| `src/` | 127 Python files | LLM providers, agent loop, tools, policy/security, scheduling, MCP manager, memory, search and utility infrastructure | Flat mixed layer. Contains the principal safety boundary and several monoliths: `agent_loop.py` 4,475 lines, `llm_core.py` 2,804, `tool_schemas.py` 1,513, `tool_parsing.py` 1,452. | **Refactor in compatibility-preserving slices.** Replace the current executable-text and fragmented registry design. |
| `static/` | 183 files, 160 JavaScript | Raw HTML/CSS/ES-module SPA | Served directly without a build step. `static/js/chat.js` is 5,441 lines and owns transport, state, parsing and rendering. No generated API/event types. | **Retain usable UI; refactor into domain modules and typed event contracts.** A framework rewrite is not a prerequisite. |
| `tests/` | 733 files, 723 Python; 711 `test_*.py` | Unit, route, service, CLI, security and JS-behaviour tests | Forty pytest files launch Node. Coverage is broad but order isolation is imperfect and pytest is non-gating in CI. | **Retain and make gating.** Add lifecycle, approval, persistence and end-to-end tests before architectural replacement. |
| `.github/workflows/` | multiple workflows | Compilation, syntax, dependency, secret, image and workflow security checks | Python compilation and Node syntax gate; pytest is `continue-on-error` at `.github/workflows/ci.yml:103-109`. | **Retain; make the repaired test suite required.** |

## Startup and installation audit

### Supported paths

1. **Docker Compose:** `README.md:34-37` documents `docker compose up -d --build`, then `http://localhost:7000`. The initial admin password is expected in `docker compose logs odysseus`.
2. **Direct Python:** `app.py:1271-1276` runs Uvicorn using `APP_BIND` (default `127.0.0.1`) and `APP_PORT` (default `7000`).
3. **Portable launcher:** `launcher.py:128-142` imports the same FastAPI app and opens the browser for frozen builds.

### Container topology and persistence

`docker-compose.yml:1-154` defines:

- Application container, host port `${APP_PORT:-7000}`, bind-mounted `${APP_DATA_DIR:-./data}` and `${APP_LOGS_DIR:-./logs}`.
- Chroma on host port `8100`, with a named `chromadb-data` volume.
- SearXNG on host port `8080`, with a health check and named configuration volume.
- ntfy on host port `8091`, with a named cache volume.

The app waits for healthy SearXNG and started Chroma. `app.py:926-967` exposes `/api/health` and `/api/ready`. The container entrypoint explicitly forwards stop signals to Uvicorn (`docker/entrypoint.sh:145+`).

### Reproducibility findings

- Python dependencies are listed in `requirements.txt`, with optional dependencies in `requirements-optional.txt`; not every dependency is constrained to an exact version.
- SearXNG is deliberately pinned to `2026.5.31-7159b8aed` in `docker-compose.yml:91-96`.
- Chroma uses `chromadb/chroma:latest` and ntfy has no version tag, violating the target requirement for repeatable installations.
- `package.json` is repository metadata with a development dependency, not a frontend compilation/build contract.
- A one-click, cross-platform installation that verifies all services does not yet exist.
- The browser smoke run, administrator login, idle CPU/memory measurement, and restart/data-retention trial are recorded in `baseline-smoke-test.md`. The remaining deployment gap is a full Docker build/start/persistence run after Docker Desktop is available.

## Storage audit

`src/constants.py:12-66` is the main file-storage registry. It locates the main database, scheduled-email and email-cache databases, settings/auth/preset/integration/contact files, uploads, personal documents, RAG/Chroma data, generated images, gallery, TTS, memory vectors, background jobs, deep research, MCP OAuth and model caches beneath `DATA_DIR`.

`core/database.py:40-60` defaults to `sqlite:///<DATA_DIR>/app.db`. Important ORM models include:

- Sessions and messages: `core/database.py:103` and `:182`
- Documents and versions: `:211` and `:244`
- Email accounts and model endpoints: `:314` and `:361`
- MCP servers: `:411`
- API tokens/webhooks: `:475` and `:489`
- User tools and tool data: `:504` and `:529`
- Scheduled tasks and runs: `:571` and `:651`
- Memories: `:674`
- Notes, calendars, events and integrations: `:1632-1728`

Sensitive text can use `EncryptedText` (`core/database.py:78+`), but encryption policy is not consistently represented as a domain-level storage contract. Models and manual migration logic sharing one file make schema evolution high risk. Existing data must be migrated through additive, reversible migrations rather than replaced.

## Cross-cutting architecture findings

### Strengths to retain

- Localhost-first deployment and persistent local volumes.
- FastAPI route modularity and liveness/readiness endpoints.
- Provider breadth in `src/llm_core.py:817-852`, including local and hosted models.
- Explicit untrusted-context wrappers in `src/prompt_security.py:8-86`.
- Workspace/root/sensitive-path checks in `src/tool_execution.py:43-278` and filesystem tool implementations.
- Admin and plan-mode backstops in `src/tool_security.py`.
- Detached SSE resume within a running process in `src/agent_runs.py`.
- Large existing test suite and dedicated security tests.

### Refactor

- Split transport, use-case, domain, provider and persistence responsibilities.
- Replace route-level DB access with repositories/application handlers.
- Split large frontend and Python monoliths while retaining behaviour.
- Centralise storage configuration, brand configuration and provider contracts.
- Turn process-global session/run/scheduler state into explicit services with durable state where required.
- Normalize timeouts, retries and error envelopes across model and tool execution.

### Replace

- Direct tool execution derived from free-form model text.
- Fragmented tool registries and implicit dispatch chains.
- Bespoke email-only confirmation with a generic approval service.
- In-memory-only agent run state for consequential actions.
- Hidden persistence side effects in `core.models.Session`.
- “Incognito” implementation that writes content to SQLite and deletes it later.

## Confirmed blockers and risks

| ID | Severity | Evidence | User impact | Required direction |
|---|---|---|---|---|
| `AUD-001` | Critical | `src/agent_loop.py:_resolve_tool_blocks`, `:2175-2223`; `src/tool_parsing.py:1235-1407` | Non-native model prose in fenced/XML/DSML/raw-JSON forms can become executable actions. | Accept only validated typed action envelopes; treat all model prose as data. |
| `AUD-002` | Critical | `_tool_task` created at `src/agent_loop.py:4015`, awaited at `:4025`; no cancel/finally path | Pressing Stop can end streaming while a side-effecting child tool continues. | Propagate cancellation, await cleanup, and test subprocess/provider cancellation. |
| `AUD-003` | Critical | `src/agent_runs.py:1-42,141-212` | Agent execution state is process-local; a restart can lose the result after an external side effect and a retry can duplicate it. | Persist run/action checkpoints and idempotency records before effects. |
| `AUD-004` | Critical | `routes/chat_helpers.py:431-438,1010-1078`; `core/models.py:94-107`; `core/session_manager.py:220-270` | Incognito messages are committed to SQLite before later cleanup, contrary to the documented privacy behaviour. | Implement a truly non-persistent session path or accurately rename and disclose the mode. |
| `AUD-005` | High | `src/tool_schemas.py`, `src/tool_index.py`, `src/tool_execution.py`, `src/agent_tools/__init__.py` | Tool metadata is split across incompatible collections, allowing advertised tools to fail at conversion or dispatch. | Create one typed registry and generate provider schemas/index/UI metadata from it. |
| `AUD-006` | High | Clean import of `src.tool_schemas` raises a partially initialized module error; workarounds at `src/tool_execution.py:629-638` and `src/tool_security.py:173-179` | Behaviour depends on import order and can fail in tests, scripts or future workers. | Remove registry circular dependencies. |
| `AUD-007` | High | Email staging `mcp_servers/email_server.py:1119-1225`; approve routes `routes/email_routes.py:3641-3710`; no matching pending-action code under `static/` | Email confirmation is backend-only and not a usable approval-centre flow. | Move pending actions to a generic typed approval UI/service. |
| `AUD-008` | High | Prompt says 60 seconds at `src/agent_loop.py:116`; constants say 60/30 at `src/agent_tools/__init__.py:71-73`; subprocess defaults are one hour at `src/agent_tools/subprocess_tools.py:8-9,117,143` | Actions can run far longer than the policy and UI imply. | Make timeout a registry field enforced by a common executor. |
| `AUD-009` | High | `routes/chat_routes.py:1393-1403` permits unlimited tool calls and up to 200 rounds | Runaway cost, latency and repeated-side-effect risk. | Add explicit per-run/action budgets and approval-aware limits. |
| `AUD-010` | High | `.github/workflows/ci.yml:103-109` | Python behaviour regressions do not fail CI. | Repair isolation/portability failures, then make pytest required. |

### Verified tool-registry drift

A runtime inventory found 67 native function schemas, 73 tool tags, 31 entries in the newer handler map, 58 tool-index sections, and 69 built-in descriptions. The union was 74 tool names, while only 27 names appeared in every collection. These collections are not all intended to be one-to-one, but the split has produced a confirmed defect:

- `tail_serve_output` is advertised at `src/tool_schemas.py:855`.
- It is absent from `TOOL_TAGS`.
- `function_call_to_tool_block()` rejects names absent from `TOOL_TAGS` at `src/tool_schemas.py:1333-1335`.
- A runtime probe returned `None` and logged `Unknown function call` for a valid `tail_serve_output` invocation.

## Test evidence

Focused lifecycle and security suites produced **305 unique passing tests and one reproducible failure**:

- The reproducible failure was `tests/test_workspace_confine.py::test_glob_confined_e2e` on macOS. The supplied path used `/var/folders/...`; `realpath` normalized the workspace to `/private/var/folders/...`. The tool returned “No files matching,” but the test failed because the rejected user pattern containing `secret.txt` was echoed. This is a portability/assertion defect; the run did not demonstrate that the secret was read.
- `tests/test_security_regressions.py::test_dns_rebinding_pinned_transport_dials_pinned_ip` failed under the restricted sandbox because socket binding was denied and passed when rerun with socket permission.
- Plan/update-plan tests passed alone: **12 passed**.
- Scheduler restart/cancel tests passed alone: **5 passed**, with three unawaited-coroutine warnings.
- Running scheduler tests before plan tests caused **16 passed, 1 failed** because `tests/test_scheduler_restart_doublefire.py:_stub_heavy` leaves a fake `src.agent_loop` in `sys.modules`. This is deterministic order contamination.
- SQLAlchemy reports the legacy `declarative_base()` call at `core/database.py:17` as deprecated under SQLAlchemy 2.

The focused test evidence supports many existing safeguards, but it is not a substitute for the required browser smoke test, provider integration tests, cancellation tests, restart/idempotency tests, or approval-path tests.

## Repository-level decision

The application is a substantial working base and should **not** be rewritten wholesale. Retain the UI, route coverage, local storage compatibility, provider adapters, MCP support, prompt-security wrappers, filesystem confinement and tests. Refactor toward explicit application/domain boundaries. Replace only the unsafe execution, approval, run-state and hidden-persistence mechanisms behind compatibility adapters and feature flags.
