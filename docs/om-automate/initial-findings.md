# Initial Findings and Implementation Gate

**Date:** 2026-07-18
**Baseline:** upstream `main` at `9844a2f9a1996b8c8135a9e7bbde6a72f41df5ed`
**Purpose:** Required Task 9 report before major transformation work

> Post-report update: SAFE-001 has fixed ownership/cancellation of the in-process tool child and the stale browser `Running` label. Durable action state and remote-provider reconciliation remain open; the findings below preserve the baseline condition that justified the slice.

## What already exists

Odysseus is a substantial local-first FastAPI application, not an empty prototype. Its raw HTML/CSS/ES-module client and Python backend already provide:

- Local and hosted model discovery/configuration, streaming chat, detached in-process SSE replay, provider fallback, context trimming, and multiple tool-call formats.
- Authentication, administrator/user controls, sessions/history, two-factor support, API tokens, security headers, settings redaction, and loopback-first deployment.
- Tasks and scheduled jobs, notes, documents/editor, memory/RAG, skills, MCP, search/research/web access, email, CalDAV-style calendar, contacts, gallery/image/media tools, TTS/STT, notifications, backup/restore, themes/presets, diagnostics, and companion/integration surfaces.
- SQLite/SQLAlchemy persistence plus files/JSON and Chroma-backed vector stores.
- A broad test corpus: 4,527 tests were collected and all passed across the baseline run plus isolated environment/path reruns.
- Useful safety foundations: external context is marked untrusted, file paths use realpath checks, non-admin tool backstops exist, API tokens are bcrypt-hashed, Google values can be encrypted/masked, outbound webhooks use SSRF/DNS pinning/HMAC, and Compose binds to loopback by default.

The native application was opened and used—not merely imported. Login success/failure, dashboard, Ollama chat, task/note create and restart persistence, calendar, email setup entry points, knowledge import entry points, logout, and fixture cleanup were manually verified.

## What is incomplete

- There is no canonical typed tool registry with typed results, per-resource permissions, four-level risk, approval requirements, idempotency, compensation, retry/timeout, and verification metadata.
- Run/action/approval state is not durable or restart-resumable. The process-local detached stream is useful for reconnects only while the process lives.
- Google integration is not yet the required hardened, unified connection manager; Gmail and Calendar do not yet meet the full typed UI/chat/approval/readback acceptance contract.
- Tasks do not yet form the requested unified project/commitment/source model. Meeting upload→local transcription→source-linked action workflow is absent as a complete product.
- Knowledge ingestion/retrieval/memory does not yet satisfy the complete source lifecycle, hybrid retrieval, authorization, citation, deletion-derivative, and reviewable-memory contract.
- Today, executive briefings, relationship intelligence, commitment tracking, durable structured automations, and a provider-neutral integration SDK are incomplete.
- Dependencies/images are not reproducibly locked; supported runtimes differ; one-click first-time installation for every declared platform does not exist.
- Migrations are ad hoc startup mutations rather than formally versioned, tested changes. Backups colocate keys and ciphertext and are not an adequately verified disaster-recovery format.
- Documentation, responsive/accessibility coverage, structured observability, health/readiness, and production release qualification are incomplete.

## What is broken

The confirmed release blockers are detailed in `09-bug-register.md`. The most important are:

1. Model-emitted structured prose can become an executable tool call.
2. Shell/Python/MCP execution inherits excessive application environment and file tools can reach privileged control-plane data.
3. Stop cancels the visible stream but can leave the side-effecting child tool running.
4. A corrupt/unreadable auth store fails open to first-run administrator setup.
5. Consequential tools lack a generic approval/policy/readback state machine.
6. Runs have no crash-safe action cursor or idempotency ledger, so retries can duplicate external effects.
7. Incognito content is written to SQLite and deleted later instead of never being persisted.
8. Raw hidden model reasoning is rendered in chat.
9. Tool definitions drift across several registries; `tail_serve_output` is exposed but fails conversion, and a cold tool-schema import is circular.
10. Fresh secret-bearing files use mode `0644`; OAuth/key/session/backup/webhook lifecycle controls need hardening.
11. Pytest is non-blocking in CI, and the suite has environment/order portability defects despite all tests clearing across isolated reruns.
12. Readiness is auth-protected/incomplete, Compose logs map the wrong path, and MCP shutdown emits cancel-scope warnings.

## What should be retained

- FastAPI, SQLite/SQLAlchemy compatibility, raw progressive web client, and the local-first/loopback deployment default.
- Working user-visible features and data formats until additive migrations and characterization tests exist.
- Provider-neutral aspirations already present in LLM discovery/fallback, MCP interoperability, and modular route registration.
- Prompt untrusted-context markers, path canonicalization, CSP/security headers, settings redaction, encrypted fields, API-token hashing, outbound-webhook network defenses, repetition breaking, and reconnectable SSE concepts.
- Existing tests as characterization assets, after isolation and blocking-gate repairs.
- The original AGPL licence, copyright/attribution, acknowledgements, and exact upstream provenance.

## What should be refactored

- Split route transport from application use cases and repositories; 25 route files access sessions/database primitives directly.
- Separate the 4,475-line agent loop into planning, context, action decoding, policy, approval, execution, verification, and response/status services.
- Generate schemas, handlers, policy metadata, prompt descriptions, and UI presentation from one acyclic typed registry.
- Make detached streams a view over durable runs/actions rather than the source of truth.
- Put local and external providers behind explicit capability/health/error/secret contracts.
- Introduce domain models for tasks/projects/commitments, meetings, knowledge sources, contacts/relationships, automations, approvals, and audit records.
- Add formal migrations and repositories while retaining compatibility facades during transition.
- Decompose the 5,441-line chat client around a versioned event/action contract without requiring a risky framework rewrite.
- Centralize visible brand/build/source metadata and dual-read compatibility-sensitive Odysseus identifiers.

## What should be replaced

- Executable fenced/XML/DSML/raw-JSON tool parsing from ordinary model text.
- Fail-open authentication recovery and security-critical broad-exception continuation.
- Per-turn denylist as the primary authorization model.
- Bespoke per-integration confirmation in place of a generic approval service.
- Memory-only action lifecycle and opt-in/fail-open snapshot “verification.”
- Hour-long unsandboxed subprocess defaults and broad data-directory filesystem authority.
- Raw chain-of-thought display and the current misleading incognito persistence contract.
- Floating dependency/image resolution and non-gating behaviour tests.
- Ad-hoc schema mutation and unencrypted key-colocated backup as release mechanisms.

## Highest security risks

The application is a privileged local control system. Its highest risks are therefore authority confusion and secret/data reach, not only network exposure:

- Untrusted model/content can reach broad effectful tools without a typed authority boundary.
- Shell/Python/file/MCP capabilities can access sensitive host/application state.
- A user can believe an action stopped even while it continues.
- A crash/retry can produce untracked or duplicate external actions.
- Corrupt authentication state can expose administrator takeover.
- Missing generic approval/readback means the system can report intentions or adapter responses as completed effects.

These risks block adding more integrations because every new integration would enlarge an unsafe execution surface.

## Recommended first implementation slice

Begin with cancellation ownership (`SAFE-001`) and the minimum canonical action/registry lifecycle from `SAFE-002`:

1. Write a deterministic failing regression that starts a slow side-effecting test tool, cancels the run, and proves the child continues today.
2. Record an ADR defining run/action states, task ownership, cancellation propagation, partial-effect reconciliation, and truthful user-visible terminal states.
3. Ensure the active tool child is cancelled and awaited in every generator/stream/disconnect/error path; kill subprocess descendants and give adapters a cancellation token/deadline.
4. Record whether the operation was cancelled before effect, completed despite cancellation, partially completed, or indeterminate; read back where possible.
5. Stream and persist the exact state, then test Stop in the browser.

Follow immediately with the canonical typed registry, typed action envelope, deny-by-default policy, durable action/idempotency records, generic Approval Centre, and provider readback (`SAFE-002` through `SAFE-007`). Do not add new effectful integrations before that foundation is complete.

## Gate decision

The baseline is sufficiently understood and manually exercised to begin a small safety fix. It is not production-ready and no broad transformation is authorized by this gate. Each implementation slice must follow the inspect → status → ADR → test → implement → validate → review → checkpoint workflow and keep the application working.
