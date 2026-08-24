# OM Automate Test Plan

## 1. Purpose and release rule

This plan defines the evidence required to call an OM Automate build installable, safe to upgrade, and ready for local use. It covers unit, integration, contract, security, migration, installation, browser end-to-end, performance, and recovery testing.

Passing source-level tests is not sufficient. A release candidate is accepted only after the application has been installed from a clean checkout, opened in a browser, exercised against its supported services, restarted without data loss, and restored from a verified backup.

The recorded baseline below is Odysseus upstream `main` at commit `9844a2f9a1996b8c8135a9e7bbde6a72f41df5ed`, tested on 2026-07-18. Results from another commit must not be presented as baseline evidence for this one.

## 2. Recorded baseline evidence

### 2.1 Test host

| Item | Observed value |
| --- | --- |
| Operating system | macOS 15.1.1, Apple Silicon `arm64` |
| CPU / memory | 8 logical CPUs / 16 GiB RAM |
| Free disk before launch | Approximately 18 GiB |
| Supported Python used | Homebrew Python 3.11.14 |
| Unsupported system Python | Apple system Python 3.9.6 |
| Node / npm | Node 23.9.0 / npm 10.9.2 |
| Docker CLI / Compose | Docker 28.3.2 / Compose 2.38.2 |
| Docker daemon | Not running; image build and container startup were not verified |
| Local model service | Ollama 0.31.1 on `127.0.0.1:11434` |
| Local models found | `qwen3:1.7b`, `qwen2.5-coder:7b`, `llama3.1:8b`, `qwen3.5:latest` |

### 2.2 Commands and results

| Check | Result |
| --- | --- |
| Python dependency resolution | `pip check`: no broken requirements |
| Python source parse | 985 Python files parsed, 0 failures |
| JavaScript syntax | 160 `.js`/`.mjs` files checked, 0 failures |
| Shell syntax | 9 shell scripts checked, 0 failures |
| Compose configuration | Base, NVIDIA, AMD, host-Docker, combined overlays, and standalone GPU files all exited 0 |
| Initial pytest collection | 4,527 tests collected in 12.27 seconds |
| Initial restricted pytest run | 4,501 passed, 23 failed, 3 skipped, 8 warnings in 154.19 seconds |
| Current isolated socket-enabled full gate | 4,535 passed, 3 skipped, 8 warnings in 135.54 seconds; one command, exit 0 |
| Failed-test rerun | 21 failures passed with local socket permission and a short temporary path |
| Research test isolation rerun | All 3 tests passed when the test's relative `data/deep_research` path matched `ODYSSEUS_DATA_DIR` |

The clean full gate now passes with `ODYSSEUS_DATA_DIR=/tmp/od` and `TMPDIR=/tmp/ot`. The first run's failures were caused by restricted TCP binding/DNS, macOS's Unix-socket path-length and `/tmp`→`/private/tmp` aliasing, and two tests that hardcoded `data/deep_research` instead of using the configured data directory. The research fixture now consumes `DEEP_RESEARCH_DIR`, and the confinement assertion compares the canonical discovered path while still allowing the documented echo of a caller-supplied pattern.

The warnings included SQLAlchemy and Pydantic deprecations plus three scheduler tests that emitted an unawaited-coroutine warning. The GitHub Actions pytest job is currently `continue-on-error: true`, so upstream CI does not enforce a green suite.

### 2.3 Live native smoke evidence

This subsection is historical baseline evidence from 2026-07-18. The Phase 1
contract and current evidence are recorded in 2.4 below.

The native server was observed on `127.0.0.1:7860`:

| Probe | Observed result |
| --- | --- |
| `GET /api/health` | 200, `{"status":"healthy",...}` |
| `GET /api/version` | 200, version `1.0.2` |
| `GET /api/auth/status` | Configured, unauthenticated, signup disabled |
| `GET /login` | 200; login HTML loaded |
| `GET /` unauthenticated | 302 to `/login` |
| `GET /api/ready` unauthenticated | 401; current readiness probe is auth-gated |
| ChromaDB | Not listening; RAG and vector memory logged as degraded |
| SearXNG / ntfy | Not listening in the minimal native profile |
| Built-in MCP | Image, memory, RAG, and email servers connected |
| Browser MCP | Optional server unavailable |
| Idle resource snapshot | Approximately 217.6 MiB RSS for Uvicorn plus four MCP children; 0.0% CPU on the second sample |

The subsequent manual browser pass completed invalid-login rejection, administrator login, dashboard/chat rendering, a real Ollama `qwen3:1.7b` response, task and note creation, calendar and email-settings entry, knowledge/import entry, process restart, conversation/task/note persistence, logout, and cleanup of the temporary task and note. The model's final answer matched the requested text, but the UI also exposed its raw reasoning trace; that is a release-blocking presentation defect.

This is meaningful native baseline evidence, not proof that the complete product works. No provider-backed calendar event, email account, document indexing/retrieval, backup/restore, Docker launch, or complete Google workflow was demonstrated, and ChromaDB remained degraded.

### 2.4 Personal PrivateOS Phase 1 gate - 2026-08-21

The current Apple Silicon native profile passed the Local Core Stabilisation
gate:

- `GET /api/health` is unauthenticated and returns 200 with status `live`.
- `GET /api/ready` is unauthenticated and secret-free. It returned 200 with
  status `degraded` while ChromaDB was offline because every required core check
  was healthy and the vector store is optional/degraded.
- Required readiness covers database, writable private storage, POSIX modes,
  app lifecycle, scheduler, meeting worker, automation worker, and privacy
  worker. Required failure returns status `failed` and HTTP 503.
- A real isolated lifespan started all four bundled stdio MCP servers and shut
  down with zero tracked app tasks and zero MCP owner tasks alive. No AnyIO
  cancel-scope errors were emitted.
- Existing `.env`, databases, JSON state, keys, logs, and runtime directories on
  the current Mac were normalized to owner-only modes.
- `om-agent:qwen3.5-9b` and `qwen3:1.7b` are installed in Ollama. Docker Desktop
  is stopped, so real Compose startup remains unverified.
- Final full command: `ODYSSEUS_DATA_DIR=<short-temporary-directory>
  TMPDIR=/tmp/alfred-ot ./venv/bin/python -m pytest -q`.
- Result: **4,958 passed, 3 skipped, 0 failed, 10 warnings in 179.72 seconds**.

### 2.5 Personal PrivateOS Phase 2 gate - 2026-08-21

The current Apple Silicon native profile passed the Trust Boundary And
Approvals source and automated behaviour gate:

- All 109 built-in executable tools have canonical metadata; registry
  validation allows no legacy/unclassified exception.
- Executor ingress rejects unknown, drifted, unauthorized, unqualified-model,
  malformed, stale, replayed, wrong-owner, wrong-origin, and argument-changed
  actions.
- Approval records bind exact canonical arguments, revision, tool/version,
  origin, request/session identity, owner, expiry and a one-time consumed nonce.
- Pending and executing actions can be cancelled. Executing cancellation
  signals the active task and records `reconciliation_required` without a false
  reversal claim.
- Shell/Python/file/MCP boundaries, untrusted-content proposal boundaries,
  incognito non-persistence, reasoning removal, backup sanitation, and redacted
  audit results have focused regression coverage.
- Approval/cancellation gate: **48 passed**. MCP/sandbox/registry/runtime gate:
  **100 passed**.
- Restricted full command: `./venv/bin/python -m pytest -q`.
- Restricted result: **4,950 passed, 20 failed, 3 skipped, 10 warnings in
  174.60 seconds**; all failures were local socket, Unix-socket or DNS
  permission denials.
- Socket-enabled rerun of the complete affected files: **65 passed, 0 failed,
  1 warning in 3.47 seconds**.
- `compileall` and `git diff --check` passed. API, Node helper, and static UI
  contracts cover Approval Centre; manual authenticated browser and real
  provider mutation/reversal drills were not repeated and remain explicit
  external evidence gaps.
- The final tree started on `127.0.0.1:7000`. Liveness returned `live` and
  readiness returned usable `degraded`; every required check was healthy and
  only optional ChromaDB/vector storage was degraded.

### 2.6 Personal PrivateOS Phase 3 gate - 2026-08-21

The current Apple Silicon native profile passed the Personal Operating Loop
source, service, route, persistence, and interface gate:

- Focused command covered executive briefings, Work, Google connection,
  Calendar, Gmail, approval ledger, operational health, routes, tools and static
  UI contracts.
- Result: **113 passed, 0 failed, 1 warning in 3.49 seconds**.
- Durable briefing tests prove owner isolation and idempotence; source tests
  prove concrete references and explicit missing-source states.
- Google doubles cover PKCE, one-time state, encrypted tokens, scope checks,
  refresh/revoke, Calendar CRUD/respond/free-busy/timezone/recurrence, Gmail
  search/read/thread/labels/archive/draft/reply/send, exact approval and
  deterministic readback.
- An authenticated isolated browser smoke covered Today and Work on desktop and
  390 x 844 mobile viewports. Both had zero horizontal overflow; briefing
  history, metrics, health, provenance and planning controls rendered without
  console errors.
- JavaScript syntax, Python compilation and `git diff --check` passed.
- Restricted full command: `./venv/bin/python -m pytest -q`.
- Restricted result: **4,955 passed, 20 failed, 3 skipped, 10 warnings in
  179.56 seconds**; all failures were denied local TCP, Unix-socket, or DNS
  operations.
- Socket-enabled rerun of all affected files: **65 passed, 0 failed, 1 warning
  in 3.58 seconds**.
- A real Google grant, Gmail send and Calendar mutation were deliberately not
  performed and remain opt-in acceptance tests with a dedicated account.

### 2.7 Personal PrivateOS Phase 4 gate - 2026-08-21

- Focused meeting, Knowledge, memory, automation, Life, privacy, vault, route,
  and static-interface gate: **71 passed, 0 failed**.
- Expanded domain selection (`knowledge or meeting or memory or automation or
  life or privacy or vault`): **165 passed, 4,818 deselected, 0 failed, 1
  warning in 12.89 seconds**.
- Restricted full command: `./venv/bin/python -m pytest -q`.
- Restricted result: **4,960 passed, 20 failed, 3 skipped, 10 warnings in
  170.04 seconds**; every failure was a denied local TCP, Unix-socket, or DNS
  operation.
- Socket-enabled rerun of every affected file: **65 passed, 0 failed, 1 warning
  in 3.91 seconds**.
- Service tests prove owner isolation, source/derivative deletion, grounded
  citations, incognito memory exclusion, vault evidence and correction,
  meeting-to-task/Knowledge flow, routine idempotence, service-restart
  persistence, and measured successful runs.
- Isolated browser smoke rendered the vault evidence/review form and all six
  routine templates. The 390 x 844 mobile viewport had zero body/dialog
  horizontal overflow and the browser console had zero errors.
- JavaScript syntax and Python compilation passed. ChromaDB and real
  transcription-quality acceptance remain explicit gaps.

### 2.8 Personal PrivateOS Phase 5 implementation gate - 2026-08-21

- New Phase 5 regressions cover encrypted portable backup, SQLite preflight,
  empty-directory restore, completed-restore rollback, release preflight,
  non-inflatable soak evidence, idempotent synthetic demo data, exact companion
  scopes, session-only token storage, and mobile safe-area layout.
- Final focused command across Phase 5 backup, release, demo, companion,
  migrations, auth, and privacy files: **51 passed, 0 failed, 1 warning in 6.05
  seconds**.
- Fresh-install rehearsal against the live data root restored and
  manifest-verified **32 files and 6 SQLite databases**; rollback evidence was
  created and the real data root was not mutated.
- Restricted full command: `venv/bin/python -m pytest -q`.
- Restricted result: **4,970 passed, 20 failed, 3 skipped, 10 warnings in
  172.07 seconds**. All 20 failures were the established managed-sandbox TCP,
  Unix-socket, or DNS denials.
- Socket-enabled rerun of every affected file: **230 passed, 0 failed, 1
  warning in 3.89 seconds**.
- Live probes: `/api/health` returned `live`; `/api/ready` returned usable
  degraded readiness with only optional ChromaDB unavailable; unauthenticated
  `/api/companion/today` returned 401.
- Browser inspection rendered all four companion views with no horizontal
  overflow or overlapping controls. Exact 390 x 844 coverage is additionally
  enforced by responsive constraints/static tests; physical iPhone Safari
  remains operator acceptance.
- The seven-day soak gate is intentionally **not passed**. It begins only when
  genuine daily use is recorded; automated or synthetic dates are not valid
  release evidence.

## 3. Test isolation and evidence rules

1. Never run destructive tests against a user's real `data/`, `.env`, model cache, email account, calendar, or OAuth credentials.
2. Use a disposable checkout or worktree and a unique temporary data directory for each test run.
3. Do not repurpose `HOME`. Set only application-specific paths such as `ODYSSEUS_DATA_DIR` and a short `TMPDIR` where required.
4. Disable bytecode and pytest cache when the checkout must remain read-only.
5. Mock Google, Gmail, Calendar, OAuth, SMTP, IMAP, webhook, and model-provider calls in ordinary CI. Live-provider tests require an explicit test account and a dedicated opt-in marker.
6. Sending email, creating external calendar records, deleting data, restoring backups, and running agent shell/file tools require isolated fixtures and explicit approval.
7. Record the commit, OS, architecture, Python version, dependency lock hash, container digests, test command, duration, pass/fail/skip totals, and generated evidence for every release run.
8. A skipped mandatory journey is a coverage gap, not a pass.
9. Secrets, password values, cookies, OAuth codes, message bodies, and personal documents must be redacted from logs and screenshots.

Recommended disposable test environment:

```bash
test_root="$(mktemp -d /tmp/om-automate-test.XXXXXX)"
short_tmp="$(mktemp -d /tmp/omtmp.XXXXXX)"
export ODYSSEUS_DATA_DIR="$test_root/data"
export DATABASE_URL="sqlite:///$test_root/data/app.db"
export TMPDIR="$short_tmp"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$ODYSSEUS_DATA_DIR"
```

Some current tests assume the repository-relative `data/` path. Until those tests use `ODYSSEUS_DATA_DIR`, run the suite in a disposable checkout whose local `data/` can be safely created, rather than redirecting only production code and producing a false failure.

## 4. Canonical developer checks

### 4.1 Dependency and configuration checks

```bash
./venv/bin/python --version
./venv/bin/python -m pip check
docker compose config --quiet
docker compose -f docker-compose.yml -f docker/gpu.nvidia.yml config --quiet
RENDER_GID=989 docker compose -f docker-compose.yml -f docker/gpu.amd.yml config --quiet
DOCKER_GID=999 docker compose -f docker-compose.yml -f docker/host-docker.yml config --quiet
docker compose -f docker-compose.gpu-nvidia.yml config --quiet
RENDER_GID=989 docker compose -f docker-compose.gpu-amd.yml config --quiet
```

The placeholder GIDs above validate interpolation only. Hardware tests must use the host's real group IDs.

### 4.2 Source checks

These mirror the current CI intent:

```bash
./venv/bin/python -m compileall -q app.py core routes src services scripts tests

while IFS= read -r file; do
  node --check "$file"
done < <(rg --files -g '*.js' -g '*.mjs')

for file in $(rg --files -g '*.sh'); do
  bash -n "$file"
done
```

Also run `git diff --check` for any change set. Run focused `py_compile`, pytest, and browser checks for the files actually changed.

### 4.3 Focused and full pytest

```bash
./venv/bin/python tests/run_focus.py --fast
./venv/bin/python tests/run_focus.py --area security
./venv/bin/python tests/run_focus.py --area routes
./venv/bin/python tests/run_focus.py --area services
./venv/bin/python -m pytest -q
```

For test-order analysis:

```bash
./venv/bin/python tests/run_order_report.py --seed 123 -- tests/ -q
```

The final release command must run once, without retries that conceal order dependence. Store JUnit output:

```bash
./venv/bin/python -m pytest -q --junitxml=test-results/pytest.xml
```

## 5. Layered automated test scope

### 5.1 Unit tests

Unit tests must cover domain logic, input validation, permissions, dates/time zones, recurrence, model capability routing, prompt/context assembly, typed tool schemas, encryption helpers, task prioritisation, knowledge chunking, and automation conditions. They must not require network access, real credentials, or persistent application state.

### 5.2 Integration tests

Integration tests must exercise:

- SQLite creation, constraints, owner scoping, encryption-at-rest paths, and concurrent access;
- Google OAuth state/PKCE/token rotation with deterministic mocks;
- Gmail, IMAP/SMTP, Calendar, and CalDAV adapters;
- Ollama/OpenAI-compatible local model discovery, chat, embeddings, and tool calling;
- ChromaDB vector storage and retrieval;
- file upload, type validation, extraction, indexing, deletion, and derivative cleanup;
- scheduler restart, duplicate prevention, cancellation, retries, and time zones;
- signed webhooks, DNS rebinding resistance, replay protection, and retry policy;
- built-in and user MCP lifecycle, failure isolation, and shutdown;
- transcription provider selection, size limits, cancellation, and unsupported formats.

Use real local containers for database/vector/search contract tests where practical. External provider calls remain mocked unless the job is explicitly marked as a live integration run.

### 5.3 Provider contract tests

Every provider adapter must satisfy a shared contract for configuration validation, health, authentication failure, timeout, rate limit, retryability, pagination, redaction, and normalized result/error shapes. Model adapters additionally cover streaming, JSON schema, vision, embeddings, and tool-use capability claims.

A model must not be marked agent-capable until a minimum tool-use probe passes with valid arguments, rejected invalid arguments, approval enforcement, and a verified side effect.

### 5.4 Security tests

Mandatory security coverage includes unauthorised and cross-owner access, admin gates, CSRF/CORS, XSS, SSRF and DNS rebinding, path traversal/symlink escape, prompt injection, tool privilege escalation, secret exposure, replay, OAuth state attacks, session expiry/revocation, login/signup rate limits, upload limits, webhook signing, and audit integrity.

Security failures block release. They may not be skipped, xfailed, or downgraded because of environment setup.

### 5.5 Migration tests

The current database initializes through `Base.metadata.create_all()` and import-time `_migrate_*` functions rather than a versioned migration framework. Until formal migrations exist, tests must:

1. create a database from the immutable upstream baseline;
2. populate representative users, sessions, messages, notes, tasks, calendar events, email configuration, documents, memories, API tokens, and encrypted values;
3. copy that database and its `.app_key` into an isolated upgrade workspace;
4. start the new code exactly once;
5. assert schema, row counts, ownership, indexes/FTS, encrypted-field readability, and application behaviour;
6. restart and confirm every migration is idempotent;
7. exercise rollback by restoring the pre-upgrade snapshot.

Never run the legacy `scripts/update_database.py` against a release database unless a specific migration guide requires and tests it. It is not the normal startup path.

### 5.6 Installation tests

Each supported platform needs a clean-machine or clean-VM job that verifies prerequisites, pinned dependency resolution, setup, initial admin creation, service health, browser load, restart persistence, backup/restore, update, and uninstall. Configuration parsing alone is not installation evidence.

Platform results must be recorded separately for macOS Apple Silicon, macOS Intel, Windows Docker Desktop, Windows WSL2, Linux CPU, Linux NVIDIA, and Linux AMD. Untested platforms must be labelled unverified.

## 6. Baseline browser smoke test

Use a deterministic test administrator and disposable provider data. Record a screenshot or trace for each UI step and retain server logs with secrets redacted.

| ID | Journey | Required evidence | Acceptance gate |
| --- | --- | --- | --- |
| B01 | Application starts | Process/container state and startup log | Startup completes without critical error |
| B02 | Login page | Browser opens `/login` | Page, CSS, and JS load without console error |
| B03 | Invalid login | Submit a known-wrong password | 401/user-safe error; no session cookie |
| B04 | Admin login | Submit configured test credentials | Secure HTTP-only session established |
| B05 | Dashboard | Open the main application | Navigation and dashboard render |
| B06 | Chat open | Create/open a chat | Session appears and persists |
| B07 | Model response | Ask a basic prompt through a configured local model | Non-empty grounded response; model/latency recorded |
| B08 | Task | Create a task, read it back, refresh | Same task remains visible |
| B09 | Note | Create a note, read it back, refresh | Same note remains visible |
| B10 | Calendar | Open calendar and create a local test event | View loads; event reads back correctly |
| B11 | Email settings | Open email configuration without credentials | Page loads and gives actionable unconfigured state |
| B12 | Knowledge upload | Open upload flow and import a safe fixture | File is indexed or a clear degraded-state error appears |
| B13 | Restart persistence | Restart the application/services | User, chat, task, note, event, and upload persist |
| B14 | Logout | Log out and revisit an authenticated route | Session revoked; redirect/401 occurs |
| B15 | Readiness | Probe the release readiness endpoint | Correct 200/503 without credentials or secret detail |

Current baseline status: B01-B09, B11, and B14 passed. B10 passed calendar rendering but not event creation/read-back; B12 passed the knowledge/import entry point but not indexing; B13 passed conversation/task/note persistence but not event/upload persistence; B15 failed because readiness returned 401 and was incomplete. Provider-backed side effects and degraded-service recovery remain open.

## 7. Core end-to-end scenarios

Automate the following after the baseline smoke suite is stable:

1. **Morning briefing:** login; retrieve calendar, important email, and priority tasks; generate a grounded briefing with links to source records.
2. **Email response:** identify the correct thread; create a draft; require user edit/approval; send; read back sent state; record the audited action.
3. **Meeting workflow:** upload audio; transcribe; summarize decisions; propose tasks; approve selected tasks; retain transcript references; query the meeting later.
4. **Calendar scheduling:** inspect free/busy; propose choices; accept one; create the event; read it back from the provider.
5. **Knowledge query:** import documents; wait for indexing; retrieve relevant passages; answer with source links; reject unsupported claims.
6. **Malicious email:** ingest an email containing agent instructions; treat it as untrusted; prevent prohibited tools/secret access; warn appropriately; record a security event.

All external writes must use dedicated test tenants and unique identifiers so cleanup is exact and auditable.

## 8. Performance and reliability checks

Record hardware, model, quantization, context size, dataset size, and cold/warm state. Initial release-candidate gates are:

- local warm restart reaches liveness within 15 seconds and readiness within 30 seconds;
- Docker cold start reaches readiness within 120 seconds after images exist locally;
- login and cached local pages complete within 2 seconds at p95 on the reference host;
- scheduler jobs do not duplicate across restart;
- no background loop performs unbounded retries or produces repeated unconfigured-service warnings;
- idle CPU settles below 2% on the reference host after startup work completes;
- idle RSS is recorded and regressions above 20% require review;
- chat first-token, tool latency, email/calendar search, retrieval, ingestion, transcription throughput, and queue delay have per-provider baselines before release.

These are initial engineering gates, not claims about the current product. Provider-dependent latency must be reported separately from application overhead.

## 9. Known defects requiring regression coverage

| Defect | Required regression test |
| --- | --- |
| `/api/ready` returns 401 without a session | **Fixed in Phase 1:** unauthenticated orchestrator probe returns safe 200/503 |
| Readiness checks only DB/data directory | **Fixed in Phase 1:** required lifecycle/scheduler/workers/permissions and optional degraded vector state are classified |
| Compose lacks Odysseus/ChromaDB/ntfy health checks | Compose installation test waits on all required services |
| `APP_LOGS_DIR` mounts `/app/logs`, while app writes `/app/data/logs/app.log` | **Fixed in Phase 1:** mount now targets `/app/data/logs`; real Docker persistence test remains pending |
| Native `.env`, auth, DB, settings, sessions, and logs were created as `0644` | **Fixed for current POSIX profile:** startup/setup repair to `0600` files and `0700` directories; Windows ACL acceptance remains pending |
| Core requirements and several container images float | Lock verification rejects unpinned requirements, tags, or missing digests |
| Manual native path does not start ChromaDB | Fresh native smoke either starts Chroma or clearly selects a supported degraded profile |
| MCP shutdown logged cancel-scope errors | **Fixed in Phase 1:** owner-task transport lifecycle passed real four-server start/stop and full regression gate |
| Research tests hardcode relative `data/` | Run suite with a non-default `ODYSSEUS_DATA_DIR` |
| Pytest is non-blocking in CI | Required CI job fails the pipeline on any mandatory test failure |

## 10. Release acceptance gates

A release candidate is approved only when all of the following are true:

- dependency and container inputs are pinned and their checksums/digests recorded;
- every tracked source/configuration check passes;
- one clean full pytest run passes with no unexpected skips or resource warnings;
- all critical/high security tests pass;
- baseline and six core browser scenarios pass where their features are in release scope;
- upgrade from a copied baseline database and a second idempotency restart pass;
- backup, integrity verification, restore, and rollback are demonstrated;
- Docker fresh installation passes on at least one declared host platform;
- every platform advertised as supported has current evidence;
- health/readiness accurately reports critical dependencies without disclosing secrets;
- restart leaves no duplicate jobs or orphan MCP/model processes;
- logs are available at the documented path and contain no credentials or private content;
- default/generated passwords are changed, open registration is off unless intended, and network deployment uses HTTPS;
- test results, screenshots/traces, benchmark data, migration evidence, and exact release identifiers are archived.

Until those gates pass, documentation must say which partial path was tested and must not claim that OM Automate is fully working or production-ready.
