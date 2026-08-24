# PrivateOS Personal Phased Development Plan

**Status:** Canonical working plan for the Personal PrivateOS build.
**Scope:** One principal-owned PrivateOS Core for private/personal use.
**Out of scope:** PrivateOS Corporate, family/household mode, enterprise tenancy, custom hardware, regulated financial advice, autonomous trading, and unmanaged consequential actions.
**Planning date:** 2026-08-21

This file is the single goal map for finishing the current project as a personal PrivateOS. The detailed implementation backlog, feature inventory, security model, and test plan remain the evidence base, but this file decides the order of work.

## North Star

Build one PrivateOS for one principal that is genuinely useful every day:

1. It starts reliably on the current local Core.
2. It knows what matters today from authorised personal sources.
3. It remembers source-backed context across work, meetings, documents, tasks, and communications.
4. It prepares useful actions.
5. It asks for approval before anything consequential.
6. It executes approved actions exactly once.
7. It verifies and records what happened.
8. It survives restart, backup, restore, and degraded local services.

The operating loop for every major capability is:

`Capture -> Understand -> Remember -> Prepare -> Approve -> Execute -> Verify`

## Current Baseline

The current codebase is a feature-rich Odysseus-derived local-first application, not a blank prototype. It already includes substantial foundations:

- FastAPI backend, SQLite/file stores, static JavaScript frontend, local model support, and optional Chroma/SearXNG/ntfy services.
- Authentication, users, 2FA, sessions, chat, model routing, documents, notes, local calendar, email, search, research, memory, RAG, skills, MCP, gallery, webhooks, and local tools.
- Newer Personal PrivateOS domain work for actions, approvals, work, Google Workspace, knowledge, meetings, automations, dashboard, privacy, backup, and operational health.
- A large automated test suite and recorded local macOS test-build evidence.

The remaining build is still **XL complexity**, because the hard work is trust, durability, verification, integration reliability, local release quality, and product coherence.

Expected remaining effort for a private single-user build on the current system: **16-24 focused engineering weeks**.

Expected effort for paid pilot/commercial-grade Personal PrivateOS: **6-9 months**, mainly due to security review, upgrade/restore proof, mobile access, legal/licensing, and provider certification.

The five implementation phases are complete on the current reference system.
The remaining path from that implementation milestone to a sellable product is
maintained in
[the Commercial Readiness Gap Analysis](18-commercial-readiness-gap-analysis.md).

## Phase 1 - Local Core Stabilisation

**Goal:** Make the current machine a repeatable PrivateOS Core.

**Status:** Complete for the current Apple Silicon Mac native profile on
2026-08-21. Docker runtime qualification remains external release evidence and
does not block progression to the Personal PrivateOS trust-boundary phase.

### Build

- Freeze the current working tree into a known checkpoint.
- Split or commit the current dirty/untracked work into coherent implementation slices.
- Keep the AGPL/licensing question visible before external operation or customer deployment.
- Lock Python, Node, Docker, container, model, Chroma, SearXNG, ntfy, and optional service versions.
- Make `./start-macos.sh`, direct `app.py` startup, and installer paths deterministic for the current Mac.
- Confirm the local agent model profile:
  - quality-first: `om-agent:qwen3.5-9b`
  - speed fallback: `qwen3:1.7b`
- Finish health/readiness coverage, secure file permissions, log paths, startup service gates, and graceful shutdown.
- Make degraded-service states explicit and non-fatal where appropriate.
- Keep all raw model/database/provider ports bound locally or behind a trusted private access layer.

### Acceptance

- One clean local setup/start/restart path works.
- Health and readiness distinguish live, ready, degraded, and failed states without leaking secrets.
- No orphaned MCP, model-serving, scheduler, meeting, automation, or privacy worker process remains after shutdown.
- Secret-bearing files are created with safe permissions.
- A focused and full automated test command is documented and repeatable.

### Main Files

- `app.py`
- `start-macos.sh`
- `install-om-automate.*`
- `Dockerfile`
- `docker-compose*.yml`
- `src/readiness.py`
- `src/subprocess_lifecycle.py`
- `docs/om-automate/10-test-plan.md`
- `docs/om-automate/15-deployment-guide.md`
- `docs/om-automate/16-local-agent-model.md`

## Phase 2 - Trust Boundary And Approvals

**Goal:** Make PrivateOS safe before it becomes useful enough to be dangerous.

### Build

- Complete the canonical tool registry so every executable capability has:
  - typed input and output schema
  - permission scope
  - risk level
  - confirmation policy
  - timeout
  - retry policy
  - idempotency mode
  - audit fields
  - reversibility/compensation metadata
  - verification mode
- Make registry authorization the only executor ingress.
- Deny unknown, drifted, or unclassified tools by default.
- Replace executable structured prose with validated typed action envelopes.
- Ensure unsupported or unqualified models remain chat-only.
- Finish durable action, attempt, result, verification, approval, and audit records.
- Wire Approval Centre into chat, tools, Google, work, knowledge, meetings, automations, file edits, shell, and effectful provider actions.
- Enforce exact-argument approval with expiry, one-time claim, actor, owner, revision, request id, and idempotency key.
- Sandbox shell, Python, file, and MCP execution with minimal environments and purpose-specific roots.
- Harden prompt-injection boundaries for email, web, RAG, files, meetings, and tool output.
- Remove raw chain-of-thought from UI, API, logs, exports, backups, and durable metadata.
- Fix incognito so it truly leaves no durable derivative.

### Acceptance

- No consequential action executes without a policy decision.
- Approval-required actions pause with a clear diff and execute only the exact approved action.
- Unknown/unclassified capabilities fail closed.
- Stop/cancel reaches active local tools, subprocess trees, workers, and partial-effect reconciliation.
- PrivateOS never says "done" unless action state and readback support that claim.
- Secrets do not enter model context, tool output, logs, browser DOM, or audit payloads.

### Main Files

- `src/tool_registry.py`
- `src/tool_actions.py`
- `src/tool_authorization.py`
- `src/tool_execution.py`
- `src/tool_policy.py`
- `src/tool_security.py`
- `src/action_ledger.py`
- `src/action_verification.py`
- `src/subprocess_sandbox.py`
- `src/prompt_security.py`
- `routes/action_routes.py`
- `static/js/approvalCentre.js`
- `static/js/approvalCore.js`
- `core/database.py`

### Completion Evidence - 2026-08-21

- All 109 built-in executable tools are classified; legacy/unclassified
  registry exceptions are zero and validation is fail-closed.
- The common executor enforces typed envelopes, owner permissions, exact
  approval evidence, policy deadlines, confined workspaces, and verification.
- Approval Centre provides exact review/edit/approve/reject/cancel/history and
  tamper-evident audit. Executing cancellation records reconciliation required
  when an external effect may already have begun.
- Incognito message/derivative persistence and private reasoning exposure are
  removed, including backup sanitation.
- Untrusted email and teacher output can propose effectful actions only.
- Final restricted suite: 4,950 passed, 20 environment-blocked socket/DNS
  failures, 3 skipped. Socket-enabled affected-file rerun: 65 passed, 0 failed.
- Final native startup returned `live` and usable `degraded` readiness with all
  required checks healthy; optional ChromaDB/vector storage was offline.
- Manual authenticated browser and live provider reversal drills remain
  external evidence; they are not represented as completed provider
  certification.

## Phase 3 - Personal Operating Loop

**Goal:** Complete the daily PrivateOS loop: Today -> decide -> prepare -> approve -> execute -> verify.

### Build

- Finish the Today dashboard:
  - schedule
  - important messages
  - priority tasks
  - commitments
  - pending approvals
  - meeting actions
  - reminders
  - integration health
  - local Core health
- Finish Work hub:
  - projects
  - tasks
  - commitments
  - reminders
  - dependencies
  - daily focus planning
  - status history
  - source links
- Finish least-privilege Google connection flow:
  - PKCE
  - one-time state
  - encrypted tokens
  - refresh/revoke
  - health and reauthorization states
- Finish Google Calendar provider:
  - list/read/create/update/delete/respond/free-busy
  - timezone and recurrence handling
  - approval for writes/destructive actions
  - provider readback verification
- Finish Gmail provider:
  - search/read/thread/labels/archive/draft/reply/send
  - strict draft/send separation
  - default approval before send
  - provider readback after send
- Build source-backed morning, evening, and weekly briefings.
- Add useful "attention returned" and proposal acceptance metrics.
- Keep all data in the principal-owned Personal workspace only.

### Completion Evidence - 2026-08-21

- Today and Work now expose the complete Phase 3 signal, planning, provenance,
  history, health, approval, and metric surfaces.
- Source-backed morning, evening, and weekly briefings are durable,
  owner-scoped, idempotent, and explicit about unavailable sources.
- Native Google OAuth, Calendar, and Gmail contracts implement PKCE, one-time
  state, encrypted tokens, refresh/revoke, least scopes, exact approval, and
  deterministic provider readback with deterministic test doubles.
- Focused automated gate: **113 passed, 0 failed, 1 warning**. JavaScript
  syntax, Python compilation, and diff whitespace checks passed.
- Restricted full suite: **4,955 passed, 20 sandbox-blocked network/socket
  failures, 3 skipped**; socket-enabled rerun of all affected files: **65
  passed, 0 failed**.
- Authenticated isolated browser smoke passed at desktop and 390 x 844 mobile
  viewports with no horizontal overflow or console errors.
- Live Google provider acceptance, Docker startup, and optional ChromaDB remain
  external/degraded evidence and are not represented as completed.

### Acceptance

- PrivateOS produces a useful daily brief from authorised sources.
- It can identify what needs attention without flooding the user.
- It can draft replies, tasks, calendar changes, and plans with source context.
- Email send, calendar mutation, deletion, and other consequential operations require approval.
- Approved changes execute once and are read back from the provider or marked unverifiable.

### Main Files

- `services/executive_service.py`
- `src/dashboard_tool_contract.py`
- `routes/dashboard_routes.py`
- `src/work_models.py`
- `src/work_service.py`
- `src/work_tool_contract.py`
- `routes/work_routes.py`
- `src/google_connection.py`
- `services/google_calendar.py`
- `services/google_gmail.py`
- `src/google_workspace_tool_contract.py`
- `src/tools/google_workspace.py`
- `routes/google_routes.py`
- `routes/google_workspace_routes.py`

## Phase 4 - Memory, Meetings, Vault, And Routines

**Goal:** Make PrivateOS compound value from real personal history, not just coordinate today.

### Build

- Finish durable knowledge ingestion for:
  - documents
  - notes
  - email
  - calendar events
  - meeting transcripts
  - approved memories
  - imported records
- Build source lifecycle:
  - source record
  - chunks/index jobs
  - citation links
  - sensitivity
  - deletion and derivative cleanup
  - re-indexing
  - stale-source handling
- Finish reviewable memory:
  - suggested, approved, rejected, expired states
  - category controls
  - provenance
  - edit/delete
  - expiry
  - incognito exclusion
- Finish meeting workflow:
  - upload/recording consent
  - supported media validation
  - durable transcription jobs
  - cancellation/recovery
  - transcript revisions
  - summaries, decisions, risks, questions, and action items
  - source-span evidence
  - approved task creation
- Add document vault workflows:
  - classification
  - semantic search
  - expiry extraction
  - obligation detection
  - sensitive-source controls
  - source-backed answers
- Finish structured recurring routines:
  - renewals
  - follow-ups
  - weekly reviews
  - inbox triage
  - backup reminders
  - meeting follow-up
- Keep browser/computer-use automation as sandboxed, allowlisted, approval-gated proof only.

### Completion Evidence - 2026-08-21

- Knowledge ingestion, source lifecycle, citations, reviewable memory,
  incognito exclusion, and derivative invalidation are owner-scoped and tested.
- Meetings provide consent-gated media, durable transcription/analysis,
  revisions, speaker mapping, source-span claims, approved Work tasks, and
  explicit Knowledge promotion.
- Document Vault provides deterministic suggested classification, expiry and
  obligation spans with revision-safe review and sensitive-source controls.
- Six durable routine templates cover the required workflows, install once per
  owner, survive service restart, and measure estimated attention returned on
  successful runs.
- Expanded Phase 4 domain gate: **165 passed**. Restricted full suite: **4,960
  passed, 20 sandbox-blocked network/socket failures, 3 skipped**; all affected
  files passed **65 tests** with socket access.
- Isolated desktop/mobile browser smoke passed with zero console errors and no
  horizontal overflow at 390 x 844.
- ChromaDB/vector infrastructure and real transcription quality remain
  degraded/external acceptance evidence.

### Acceptance

- A meeting can become transcript, summary, decisions, proposed tasks, and searchable source-linked memory.
- A document can become searchable knowledge with expiry/obligation metadata.
- PrivateOS can answer personal-memory questions with citations and clear uncertainty.
- Deleting a source deletes or invalidates its searchable derivatives.
- At least three recurring workflows save measurable time and survive restart.

### Main Files

- `src/knowledge_models.py`
- `services/knowledge_service.py`
- `src/knowledge_tool_contract.py`
- `src/tools/knowledge.py`
- `routes/knowledge_routes.py`
- `src/meeting_models.py`
- `src/meeting_contract.py`
- `services/meeting_service.py`
- `services/meeting_worker.py`
- `services/meeting_analysis.py`
- `services/local_transcription.py`
- `routes/meeting_routes.py`
- `services/automation_service.py`
- `services/automation_worker.py`
- `src/automation_models.py`
- `routes/automation_routes.py`
- `services/privacy_service.py`
- `services/privacy_retention.py`

## Phase 5 - PrivateOS Completion On Current System

**Goal:** Make the personal system dependable enough for daily use and credible demos.

**Status:** Implementation complete on 2026-08-21. Final acceptance remains
pending until the seven-consecutive-day personal-use soak is recorded.

### Build

- Finish encrypted, integrity-checked backup/export/restore.
- Rehearse restore on a fresh local installation.
- Add versioned migrations, preflight checks, idempotent startup, rollback guidance, and historical fixtures.
- Harden auth/session/TOTP/token/user management.
- Complete privacy controls:
  - retention
  - export
  - deletion
  - incognito
  - telemetry off by default
- Harden the desktop/local shell experience:
  - decide whether the current local web app is enough for this milestone
  - only introduce Tauri if it materially improves daily use or secure distribution
- Add iPhone access path:
  - Today
  - chat
  - approvals
  - notifications
  - secure client-to-Core access
- Finish browser smoke and core end-to-end journeys:
  - login
  - Today
  - Ask
  - approvals
  - email
  - calendar
  - work
  - meetings
  - knowledge
  - automations
  - backup/restore
- Create a synthetic demo dataset and ten-minute demo script:
  - morning briefing
  - inbox compression
  - meeting extraction
  - source-backed retrieval
  - approval and verification flow
- Run a security pass:
  - auth/session
  - CSRF/CORS
  - XSS
  - SSRF/DNS rebinding
  - path traversal/symlink escape
  - prompt injection
  - secret canaries
  - log redaction

### Acceptance

- PrivateOS runs on the current Core for at least one week of real personal use.
- Restart does not lose workflow, memory, approval, meeting, or automation state.
- Backup restores a fresh supported install with accounts, settings, data, and derivatives intact.
- At least three recurring workflows work reliably.
- A prospective user can understand the product in a ten-minute demo.
- No Corporate or family feature is required for completion.

### Completion Evidence - 2026-08-21

- Encrypted v2 `.ombak` exports include the instance key only inside the
  authenticated encrypted envelope. Restore preflight verifies archive hashes,
  safe paths, and every SQLite database before restart-safe staging.
- Restore application uses per-file replacement with compensation on failure,
  preserves rollback copies, and can stage a completed restore rollback for the
  next restart.
- A fresh empty-directory rehearsal restored and manifest-verified **32 files
  and 6 SQLite databases**, including the instance key, and created rollback
  evidence.
- Domain schemas use versioned, locked, idempotent migrations with historical
  fixture coverage. Core legacy migration replacement remains tracked in
  `OM-BUG-018` and is bounded by preflight backup/restore recovery.
- Existing auth/session/TOTP/token hardening, privacy retention/export/delete,
  true incognito behavior, and telemetry/model-logging-off defaults passed the
  Phase 5 security gate.
- The current responsive local web shell is the desktop milestone. Tauri is not
  introduced because it does not materially improve this current-system release.
- The scoped companion surface at `/static/companion.html` provides Today,
  read-only approvals, due reminders, and chat. Pairing tokens are hash-only,
  owner-scoped, revocable, and stored by the browser in session storage only.
- `scripts/privateos_demo.py` idempotently seeds synthetic Work, Knowledge,
  Meeting, and three recurring-routine records in an explicitly selected data
  directory.
- `scripts/privateos_release_check.py` runs local database/privacy/permission
  preflight, a fresh-install restore rehearsal, and tamper-resistant daily soak
  bookkeeping. It will not report acceptance before seven consecutive dates.
- Restricted full suite: **4,970 passed, 20 environment-blocked socket/DNS
  failures, 3 skipped, 10 warnings in 172.07 seconds**. Socket-enabled rerun of
  all eight affected files: **230 passed, 0 failed, 1 warning in 3.89 seconds**.
- Live app smoke: liveness `live`; readiness usable/degraded only for optional
  offline ChromaDB; unauthenticated companion data returns `401`; companion
  browser layout has no horizontal overflow or control overlap.
- **Acceptance still open:** the required seven-consecutive-day real personal-use
  soak currently has 0 recorded days. This cannot be replaced by synthetic test
  time.

### Main Files

- `services/backup_service.py`
- `routes/system_backup_routes.py`
- `src/restore_bootstrap.py`
- `src/schema_migrations.py`
- `core/auth.py`
- `core/middleware.py`
- `services/privacy_service.py`
- `services/operational_health.py`
- `static/index.html`
- `static/style.css`
- `static/js/*`
- `docs/om-automate/10-test-plan.md`
- `docs/om-automate/12-user-guide.md`
- `docs/om-automate/13-admin-guide.md`
- `docs/om-automate/15-deployment-guide.md`

## Work Rules

- Build Personal PrivateOS first. Corporate and family concepts may influence isolation design, but they do not get UI, routes, or implementation priority in this plan.
- Finish safety before adding new effectful capabilities.
- Prefer source-backed answers over confident summaries.
- Prefer proposal plus approval over autonomous execution.
- Prefer exact readback over optimistic success messages.
- Keep local-first defaults and explicit degraded states.
- Treat integrations as untrusted inputs and untrusted execution surfaces until policy, approval, and verification prove otherwise.
- Keep each phase releasable on the current system before starting the next phase in earnest.

## Phase Exit Checklist

Every phase must update:

- `docs/om-automate/00-project-status.md`
- `docs/om-automate/03-feature-inventory.md`
- `docs/om-automate/09-bug-register.md`
- `docs/om-automate/10-test-plan.md`
- this file, if phase scope or acceptance changes

Every phase must record:

- commit or checkpoint
- tests run
- tests passed/failed/skipped
- browser smoke evidence where relevant
- known degraded services
- known security gaps
- user action required

## Current Next Goal

Complete the **Phase 5 seven-day personal-use soak and release sign-off**.

Run the normal PrivateOS workflows each day, then record that day's evidence
with `scripts/privateos_release_check.py --record-soak --owner <owner>`. On the
seventh consecutive day, rerun with `--restore-rehearsal --require-soak`. Do not
start Corporate or family scope while this acceptance gate remains open.
