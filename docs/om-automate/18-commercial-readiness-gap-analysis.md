# Private OS Commercial Readiness Gap Analysis

**Assessment date:** 2026-08-21
**Scope:** Personal Private OS for one principal. Corporate, enterprise tenancy,
family/household mode, custom hardware, regulated advice, autonomous trading,
and unmanaged consequential actions are excluded.
**Reference plan:** `17-privateos-phased-plan.md`
**Source-verified:** 2026-08-21 against the working tree. Corrections in this
revision: `OM-BUG-007`/`OM-BUG-012` were transposed, `OM-BUG-003` was stale, and
the distribution and supply-chain scores were too generous. See `09-bug-register.md`.
**Assessment standard:** A product that can be sold, installed, upgraded,
supported, secured, recovered, and legally distributed to users who do not have
access to the development team.

## Executive Verdict

Private OS is a feature-rich release candidate, not a commercially releasable
product yet.

- **Personal Private OS feature completeness: 88% implemented / unverified.** The five-phase product
  loop exists: capture, understand, remember, prepare, approve, execute, and
  verify. Chat, Today, Work, approvals, Google contracts, Knowledge, Meetings,
  Document Vault, routines, privacy, backup/restore, companion access, and a
  native macOS window are implemented.
- **Current-system paid-pilot readiness: 70%.** The application is credible for
  controlled use by its owner on the verified Apple Silicon Mac, provided it
  remains loopback-only and degraded/unverified integrations are treated
  honestly.
- **Overall commercial readiness: 48%.** Distribution, migration, security,
  provider certification, platform qualification, legal compliance, operations,
  and customer-support readiness remain substantial release work.

The gap is not primarily a shortage of visible features. It is the difference
between software that works on its development machine and a product that can
make enforceable promises to paying users.

## Scoring Model

The overall score is weighted by commercial risk. A polished feature cannot
compensate for an unresolved critical authentication defect, an untested
upgrade, or an unlawful distribution package.

| Area | Weight | Current score | Weighted result | Evidence and main gap |
| --- | ---: | ---: | ---: | --- |
| Product capability and coherence | 20% | 70% | 14.0 | Five phases implemented, but scored on *implemented* not *verified*: no live-provider run, no real-user session, 0/7 soak. Onboarding, recovery UX, and accessibility remain |
| Security and trust boundary | 20% | 65% | 13.0 | `OM-BUG-003` largely closed (up); unauthenticated workflow trigger (`OM-BUG-012`) and non-durable agent-run state (`OM-BUG-007`) still open (down) |
| Reliability, data, and quality | 15% | 55% | 8.2 | Large suite, but it is not a gate: pytest is `continue-on-error` **and** a docs-only heuristic skips it entirely while still reporting green. Legacy migrations, soak, performance, and fault testing remain |
| Installation and distribution | 12% | 15% | 1.8 | **Zero installable artifacts.** `build-macos-app.sh:110` ad-hoc signs (`codesign --sign -`) and bakes `OMInstallDirectory = $REPO_DIR` into `Info.plist`; `native/macos/OMAutomateApp.m:166` shells `start-macos.sh` from that path. Bundle is non-relocatable. `Odysseus.spec` (PyInstaller) is orphaned from the AppKit shell |
| Provider and model integrations | 10% | 25% | 2.5 | Typed/test-double contracts prove our own code, not the integration; live Google/email/calendar/model/transcription/vector acceptance is approximately zero |
| Privacy and compliance | 8% | 55% | 4.4 | Local-first controls and encrypted backup exist; policy, DPIA, deletion/export validation, recording consent, and jurisdiction work remain |
| Licence, IP, and release provenance | 8% | 25% | 2.0 | AGPL baseline is known; `THIRD_PARTY_NOTICES` does not exist and `licenses/` holds 4 files against the full dependency tree. Counsel, source offer, SBOM, chain of title, and trademark clearance are open |
| Operations, support, and commercial delivery | 7% | 30% | 2.1 | Diagnostics and health exist, but a 338-file dirty tree means no release process exists yet; support, incident response, pricing/entitlements, and customer lifecycle remain |
| **Overall** | **100%** |  | **48.0%** | **Commercial release is blocked** |

Scores are evidence-based estimates, not a warranty or a substitute for legal,
security, accessibility, or platform certification.

## What Is Already Built

The five phases delivered a substantial Personal Private OS foundation:

1. **Local Core:** FastAPI, local data stores, authentication, owner-only file
   permissions, health/readiness, deterministic native startup, local models,
   optional ChromaDB, and clean worker/MCP shutdown on the current Mac.
2. **Trust and approvals:** 109 classified built-in tools, typed action
   envelopes, central authorization, exact one-time approvals, Approval Centre,
   audit history, cancellation, reconciliation state, confined subprocesses,
   incognito non-persistence, and reasoning redaction.
3. **Daily operating loop:** Today, briefings, Work projects/tasks/commitments,
   daily focus, operating metrics, typed Gmail/Google Calendar adapters, and
   verified-or-explicitly-unverifiable action outcomes.
4. **Compounding personal context:** Knowledge ingestion and citations,
   reviewable memory, meeting transcription/analysis workflow, Document Vault,
   source lifecycle, derivative deletion, and six durable routine templates.
5. **Current-system completion:** privacy and retention controls, scoped mobile
   companion, encrypted `.ombak` backups, integrity preflight, compensated
   restore, rollback evidence, schema ledgers for new domains, demo data, and
   release checks.
6. **Native desktop shell:** an arm64 AppKit/WKWebView application now runs the
   Private OS in its own macOS window without Chrome. It is installed locally
   and has a DMG build path.

Current release preflight passes database integrity, sensitive-file permissions,
privacy defaults, and pending-restore checks. The required seven-day soak has
**0 of 7 days** recorded. The last documented broad run recorded **4,970
passing tests**, with socket/DNS cases passing separately in an enabled runner.

## The Commercial Gap

The current application proves implementation on one known machine. A commercial
product must also prove all of the following:

- a new user can install it from an immutable release without the source tree or
  developer intervention;
- an existing user can upgrade and roll back without losing or corrupting data;
- critical security boundaries hold under hostile input and damaged local state;
- advertised providers and workflows work against their real APIs;
- every advertised platform has repeatable evidence;
- binaries, containers, licences, notices, and source offers are lawful and
  traceable;
- backups cover the complete deployed data topology and restore across releases;
- support can diagnose failures without collecting private content or secrets;
- incidents, vulnerabilities, dependency updates, and end-of-life releases have
  owners and response procedures;
- product claims, privacy promises, service terms, and pricing match actual
  behavior.

Until those conditions are met, Private OS should be described as a local
release candidate or controlled pilot, not a production-ready commercial app.

## Priority 0: Commercial Release Blockers

Every item in this section must be closed before a public paid release.

### 1. Fix corrupt-auth fail-open behavior

`OM-BUG-003` is **largely closed** — verified against source on 2026-08-21, not
inherited from the register. Implemented: tri-state store model
(`core/auth.py:141,181,192`), `recovery_required` (`:301`), `is_configured` true
during recovery (`:298`), `setup()` refusing under `_setup_lock` (`:317-322`), and
a 503 `auth_recovery_required` at the route (`routes/auth_routes.py:109`).
`tests/test_auth_security_controls.py:63,72` and
`tests/test_auth_config_lock_concurrency.py` pass (12 tests).

Closed on the current macOS profile on 2026-08-21 by adding the missing pieces:

- readiness now fails closed — the `auth_store` check in `src/readiness.py`
  returns `auth_recovery_required` and drives `/api/ready` to 503; its output is
  asserted secret-free (no paths, identities, or exception text);
- `13-admin-guide.md` §4.2 was rewritten against current behaviour. It previously
  described the *old* vulnerability and told operators to watch for an exposed
  setup screen, a symptom that can no longer occur;
- the test matrix was extended to truncated, unreadable (mode 000), wrong-shaped
  (`users` as list/string/scalar), null, and empty stores, plus an 8-thread
  concurrent first-admin race — `tests/test_auth_store_readiness.py`, 13 tests.

Remaining before release (**High**, not Critical):

- run the same matrix on the other six supported platforms;
- make Docker setup failure fatal rather than ignored.

Exit gate: no damaged configured state can expose first-run setup, and recovery
can be completed without deleting user data.

### 2. Authenticate inbound automation webhooks

`OM-BUG-012` remains **High** (this item previously cited `OM-BUG-007` in error).
`routes/task_routes.py:1047` states it outright: "Unauthenticated endpoint — the
token IS the auth." A URL leaked via a log, referrer, or screenshot initiates
workflows. URL tokens provide no replay or body-integrity protection.

Required work:

- replace URL-only authority with versioned HMAC signatures;
- sign method, canonical path, timestamp, delivery ID, and raw body;
- enforce clock windows, body limits, constant-time comparison, event
  allowlists, rate limits, and durable delivery-ID deduplication;
- support overlapping secret rotation and redact all webhook credentials;
- reuse the existing outbound signer (`src/webhook_manager.py:425`) and verifier
  pattern (`services/automation_service.py:623`) rather than writing a third;
- prove altered, expired, duplicate, oversized, and concurrent deliveries fail
  safely or execute exactly once.

### 2b. Make agent-run state durable (the real `OM-BUG-007`)

Restored to Priority 0 — it was displaced by the mislabelling above.
`src/agent_runs.py` holds active runs in a process-local `_RUNS`. Crash mid-action,
restart, retry, and the external effect executes twice. This defeats the approval
model the product is sold on.

Required work:

- persist run/action/approval/attempt/result/verification state **before** execution;
- idempotency key per external effect, with a reconciliation sweep on startup;
- compensation records for indeterminate outcomes, surfaced in the UI.

Exit gate: `kill -9` at every state transition, then restart and replay, yields
exactly-once execution or an explicitly reconciled indeterminate state.

### 3. Make mandatory CI genuinely blocking

`OM-BUG-016` remains **High**, and is worse than previously stated. Beyond
`continue-on-error` on pytest (`ci.yml:109`), `container-trivy.yml:50,90` and
`dependency-review.yml:53`, a **docs-only heuristic** (`ci.yml:118-136`) skips the
pytest run entirely and still reports the check green.

Required work:

- split hermetic unit, socket-enabled integration, browser, container, migration,
  and live-provider suites into explicit jobs;
- remove `continue-on-error` from mandatory pytest and release security gates;
- isolate order-dependent modules and eliminate warnings caused by leaked tasks,
  unawaited coroutines, and deprecated interfaces;
- run randomized-order and repeated suites;
- require status checks through branch protection;
- archive test, browser trace, benchmark, SBOM, and release-manifest evidence.

### 4. Complete reproducible and immutable builds

`OM-BUG-017` remains **High**, and is worse than previously stated.
`requirements.txt` is effectively unpinned (`fastapi`, `uvicorn`, `SQLAlchemy`,
`numpy` carry no versions), and `.github/workflows/ci.yml:143` installs *that*
rather than `requirements-om.lock`. Container images in `docker-compose.yml` are
pinned by tag, not digest. Python runtimes disagree across surfaces: `Dockerfile:12`
uses 3.14.6 while `ci.yml:141` uses 3.11. Reproducibility is currently near zero.

Required work:

- resolve and test lock files for every supported OS/architecture;
- pin container images by digest and verify downloaded artifacts by SHA-256;
- retain `package-lock.json` and use `npm ci` for build/test tooling;
- generate CycloneDX or SPDX SBOMs for source, Python, Node, containers, fonts,
  vendored JavaScript, and native artifacts;
- sign release tags, manifests, binaries, DMGs, containers, checksums, and source
  archives;
- rebuild from empty caches and compare resolved dependency and image manifests;
- automate reviewed dependency updates and block known unacceptable CVEs.

### 5. Replace remaining legacy database migrations

`OM-BUG-018` remains **High**. New Private OS domains have a migration ledger,
but the older core still runs import-time schema changes without a complete
transactional version/rollback model.

Required work:

- inventory every legacy startup migration and define a single schema history;
- adopt versioned, locked, idempotent migration execution for all databases;
- add preconditions, data checksums, interrupted-step recovery, and explicit
  compatibility windows;
- build fixtures from every supported historical release;
- test upgrade, restart idempotency, failed migration, restore, and rollback;
- prevent older binaries from opening a schema they cannot safely understand.

### 6. Close secret-storage and key-lifecycle gaps

The current system encrypts sensitive values and encrypted backups are a strong
improvement, but `OM-BUG-021` and the security register retain unresolved secret
management work.

Required work:

- store MCP credentials as encrypted secret references and never return raw
  values through list/update APIs;
- consolidate the parallel `.app_key` and provider-key mechanisms behind a
  versioned envelope-encryption service;
- integrate macOS Keychain for the native product and define Windows/Linux
  equivalents;
- extend the existing `rotate_master_key(keep_previous=2)`
  (`src/secret_storage.py:158`) with key identifiers, interrupted-rotation
  recovery, and retirement — do not rewrite it;
- treat credentials embedded in URLs as secrets;
- prove logs, diagnostics, exports, backups, DOM state, model context, and tool
  output contain no recoverable credentials.

### 7. Resolve licence, source-offer, and trademark obligations

The repository declares AGPL-3.0-or-later, contains conflicting historical
licence language, and has no completed commercial legal review. This blocks
distribution regardless of engineering quality.

Required work:

- obtain qualified counsel approval for licence version, chain of title,
  combined-work boundaries, and the intended commercial model;
- remove inaccurate MIT/permissive claims without deleting upstream notices;
- produce complete `THIRD_PARTY_NOTICES`, dependency licences, and a file-level
  provenance manifest;
- publish exact-version Corresponding Source beside every binary/container and
  expose the source offer prominently to remote users, including before login;
- include build, install, migration, interface-definition, and installation
  information required for the distributed artifact;
- assess PyMuPDF and every other non-permissive, dual, or commercial dependency;
- clear ownership and trademark use for “OM Automate”, its logo, provider marks,
  and retained upstream branding;
- retain legal evidence and artifact hashes for the support life of each release.

### 8. Freeze a clean release source

The working tree currently contains a very large set of modified and untracked
phase implementation files. A commercial build cannot be traced to an
unreviewed dirty checkout.

Required work:

- split the five-phase implementation into reviewed, coherent commits;
- reconcile stale status/security/deployment statements with current behavior;
- run secret and private-data scans against Git history as well as the worktree;
- verify that `.env`, `data/`, logs, local databases, backups, screenshots, and
  personal fixtures are excluded;
- create a signed immutable release tag and source archive;
- make `/api/version`, About/Legal, native bundle metadata, containers, and
  diagnostics report the exact product version and source revision.

## Product and Experience Work

### First-run onboarding

Design one supported flow that takes a non-technical purchaser from install to a
useful first result:

- welcome, local-data promise, licence/source disclosure, and system check;
- administrator creation without exposing a temporary password in logs;
- model choice with hardware-aware recommendations and a working test prompt;
- optional ChromaDB, transcription, email, calendar, and notification setup;
- clear permission and provider-scope explanations;
- a deterministic sample workflow using synthetic data;
- completion state, recovery route, and ability to postpone optional services.

The app must distinguish unavailable, unconfigured, degraded, authorizing,
healthy, expired, and failed services with actionable recovery steps.

### Information architecture and workflow polish

- conduct task-based usability sessions with target users for Today, Inbox,
  Work, Meetings, Knowledge, Approvals, and backup;
- remove duplicate legacy and Private OS paths or explain their distinct roles;
- unify naming, empty states, notifications, errors, and destructive-action copy;
- preserve context when moving from a source to a proposal, approval, result,
  verification, or reversal;
- provide safe bulk management for old chats, records, sources, jobs, and
  approvals;
- design account recovery, integration reauthorization, partial failure,
  conflict, offline, and storage-full states;
- ensure every long-running operation exposes progress, cancellation, retry,
  resumability, and final evidence.

### Accessibility and inclusive design

Current targeted ARIA and keyboard tests are not a complete accessibility audit.

- target WCAG 2.2 AA for the web/native content surface;
- test VoiceOver, keyboard-only operation, focus order, zoom, reduced motion,
  contrast, screen-reader announcements, captions/transcripts, and error
  identification;
- validate responsive behavior on supported phones and desktop window sizes;
- publish an accessibility statement and known limitations;
- remediate findings with automated and manual regression evidence.

### Native macOS application completion

The current native app removes the Chrome dependency but remains a shell tied to
this source checkout and its existing `venv`.

To become a distributable Mac product:

- choose and document a minimum supported macOS and Apple Silicon/Intel policy;
- bundle or install an exact private runtime and all required app services;
- place mutable data under Application Support, logs under Logs, caches under
  Caches, and secrets in Keychain;
- add OAuth/deep-link callback handling and correct microphone/camera/file
  permission behavior;
- supervise ChromaDB and model helpers with readiness and clean shutdown;
- implement signed updates, rollback, release notes, and an uninstall/data
  retention choice;
- sign with a Developer ID, enable hardened runtime, notarize, staple, and test
  Gatekeeper on a clean Mac;
- verify sleep/wake, logout/login, multiple launches, crash recovery, low disk,
  denied permissions, and moved/deleted runtime paths;
- replace the older browser-launcher Dock entry only with explicit owner approval.

### Windows and Linux product decisions

Do not advertise platforms merely because a script exists. Decide the launch
scope:

- **Mac-first option:** commercially support Apple Silicon macOS only for v1 and
  label Docker/Windows/Linux as preview or unsupported.
- **Cross-platform option:** qualify Windows Docker Desktop, Windows WSL2,
  Linux CPU, Linux NVIDIA, Linux AMD, macOS Intel, and Apple Silicon separately.

Each supported platform needs clean install, first run, restart, update,
backup/restore, uninstall, permissions, filesystem, browser/native UI, and
provider evidence.

## Security Engineering Remaining

Beyond the Priority 0 defects, commercial hardening requires:

- reconcile the stale security model so fixed findings and residual risks are
  accurately versioned;
- replace the stale checked-in threat model with current data-flow, trust-zone,
  asset, actor, abuse-case, and mitigation diagrams;
- complete the legacy Google/MCP OAuth migration and revoke old credential files;
- centralize route-to-bearer-scope declarations and deny tokens on new routes by
  default;
- complete webhook retry, signature versioning, dead-letter, and signing-secret
  rotation;
- enforce destination policy and DNS pinning consistently across all outbound
  HTTP, provider, browser, MCP, and generic integration paths;
- add persistent, privacy-safe authentication throttling and account lockout
  recovery appropriate to the deployment model;
- prove prompt injection cannot cross server-side authorization with a corpus
  covering email, documents, web pages, transcripts, memory, skills, MCP, and
  tool output;
- triage `OM-BUG-025` broad exception handling, prioritizing auth, migrations,
  persistence, actions, backup, and provider side effects;
- reduce the monolithic/inverted dependencies tracked in `OM-BUG-026` where they
  impair isolation, fault handling, or reviewability;
- commission independent application and native-package penetration testing;
- define vulnerability disclosure, severity, patch SLAs, supported versions,
  and security advisory publication.

No Critical or High issue may remain open for the feature or deployment profile
being sold.

## Data Integrity, Backup, and Recovery Remaining

- include or explicitly rebuild every derivative store, especially external
  Docker Chroma volumes;
- define backup retention, destination, key custody, rotation, and lost-passphrase
  behavior;
- test large backups, low disk, interrupted upload/download, tampering, partial
  restore, cross-filesystem replacement, and process crash during restore;
- verify restoration from every supported previous commercial version;
- measure recovery point and recovery time objectives and publish realistic
  operator expectations;
- add scheduled backup failure notifications that do not expose private paths or
  content;
- test secure deletion limitations on SSDs, cloud-synced folders, filesystem
  snapshots, logs, provider copies, and backups;
- verify owner export/delete across every SQL table, JSON store, file tree,
  vector index, generated derivative, provider connection, and audit-retention
  exception;
- define data corruption detection and a support-safe repair procedure.

## Integration and Model Qualification

Contract tests and deterministic doubles are necessary but insufficient for an
advertised integration.

### Required live acceptance

- Google OAuth verification, Gmail read/search/draft/send/readback, Calendar
  free-busy/create/update/delete/respond/readback, expiry, refresh, revoke, and
  reauthorization;
- IMAP/SMTP and CalDAV against declared supported providers, including timezone,
  recurrence, attachments, duplicate sends, and provider rate/error behavior;
- supported local model discovery, chat, structured tool use, context limits,
  cancellation, malformed output, and unsupported-model chat-only behavior;
- each advertised hosted model adapter with real authentication, streaming,
  usage accounting, rate limits, failover, and redaction;
- ChromaDB indexing, retrieval, deletion, rebuild, corruption, version upgrade,
  and degraded recovery;
- local transcription with short/long media, multiple speakers, cancellation,
  restart recovery, consent, quality thresholds, and supported formats;
- remote MCP servers with package/version pinning, capability approval,
  credentials, disconnect, failures, and malicious-output tests;
- notification delivery and companion access on a physical iPhone over the
  chosen trusted network path.

### Provider product work

- register production OAuth applications and complete provider verification;
- publish redirect URIs, scopes, privacy policy, terms, support contact, and
  deletion instructions required by providers;
- define supported provider/version matrices and deprecation policy;
- add user-facing quota/rate-limit/reauthorization states;
- maintain dedicated test tenants and exact cleanup automation;
- avoid claiming support for adapters that have only mocked evidence.

## Testing and Acceptance Remaining

### Mandatory automated gates

- one clean full suite with socket/DNS capability and no unexplained failures,
  skips, task leaks, or resource warnings;
- blocking unit, integration, security, migration, browser, native-package, and
  container jobs;
- browser automation for login, Today, chat, task, note, calendar, inbox,
  approvals, meetings, Knowledge, routines, privacy, backup, restore, and logout;
- the six core end-to-end scenarios in the test plan, including malicious email;
- property/fuzz testing for parsers, archives, routes, action envelopes, paths,
  dates/timezones, recurrence, and provider payloads;
- concurrency tests for approvals, idempotency, jobs, migrations, schedules,
  backups, restore, and multiple app launches;
- fault injection for process death, timeout, provider ambiguity, disk full,
  database lock/corruption, network loss, and optional-service recovery.

### Manual and real-environment gates

- record seven consecutive days of genuine owner use; current evidence is 0/7;
- complete physical iPhone Safari/companion acceptance;
- test VoiceOver and keyboard workflows;
- exercise real provider mutation, verification, reversal, and indeterminate
  reconciliation using dedicated accounts;
- validate a ten-minute sales/demo journey from a clean synthetic profile;
- run fresh installation and upgrade on every advertised platform;
- conduct a controlled paid pilot with consented users and support observation.

### Performance and capacity gates

- define reference hardware and supported dataset limits;
- establish cold/warm startup, page p95, first-token, search, indexing,
  transcription, queue, backup, and restore baselines;
- test long-running use for memory/file-handle/process growth;
- test large inboxes, calendars, document collections, meetings, and histories;
- set resource and output limits for tools, workers, uploads, archives, and model
  context;
- record regression budgets and fail releases that exceed them.

## Privacy, Policy, and Regulatory Work

For a local-first Personal Private OS, the commercial privacy design should be
minimal-data by default. Commercial readiness still requires documented truth.

- create a reviewed privacy policy describing local data, optional providers,
  diagnostics, support bundles, update checks, retention, backups, and deletion;
- create terms of use, warranty/support terms, acceptable-use boundaries, and
  clear AI limitations;
- map every data category, purpose, storage location, recipient, retention,
  deletion path, and legal basis where applicable;
- complete a data protection impact/risk assessment for email, meetings,
  recordings, contacts, documents, model providers, and remote companion access;
- design explicit consent and recording notices for meetings and microphone use;
- ensure optional telemetry/crash reporting is off by default, consented,
  inspectable, revocable, and free of message/document content;
- define subject access/export/deletion handling if the vendor ever receives
  customer data through support or hosted services;
- review GDPR/ePrivacy, consumer protection, communications/recording,
  accessibility, export-control, sanctions, and target-market requirements with
  qualified advisors;
- document which responsibilities remain with the local operator and which are
  assumed by the vendor.

This report is engineering analysis, not legal advice.

## Observability, Operations, and Support

Commercial operation requires a supportable failure model without compromising
the product's privacy promise.

- use structured logs with rotation, retention, redaction, event IDs, and
  severity guidance;
- create an owner-reviewed diagnostics bundle that excludes credentials and
  private content by construction;
- expose local metrics for startup, queues, jobs, actions, verification,
  provider health, backup age, storage, and error rates;
- add crash detection and clear recovery instructions without automatically
  uploading data;
- define release channels, release notes, update cadence, rollback windows, and
  end-of-support policy;
- create incident response, security incident, provider outage, data-loss, and
  compromised-signing-key runbooks;
- establish support intake, identity verification, privacy-safe reproduction,
  escalation, and resolution targets;
- maintain a known-issues page and a compatibility/status matrix;
- rehearse restore and rollback as operational drills, not only unit tests.

## Commercial Product Work

Engineering completion alone does not define a sellable product.

- define the initial customer and supported use cases precisely;
- choose direct sale, paid support, managed installation, hosted service, or
  another business model compatible with the final licence advice;
- define pricing, trial/refund rules, entitlement delivery, upgrades, and what
  continues to work offline;
- avoid introducing a licence server that weakens local-first reliability or
  collects unnecessary identity data;
- define included support, response targets, maintenance period, and paid
  upgrade policy;
- create truthful product claims tied to acceptance evidence;
- prepare onboarding, backup, recovery, provider, privacy, security, and
  troubleshooting documentation for non-developers;
- establish a feedback, defect triage, roadmap, and release decision process;
- run a small paid pilot before broad availability.

## Recommended Delivery Sequence

The following sequence minimizes the chance of polishing a product that still
cannot lawfully or safely ship.

### Gate 1: Freeze and reconcile the product baseline

**Estimated effort:** 1-2 focused engineering weeks.

- organize and review the five-phase working tree;
- update contradictory status, security, test, and deployment documents;
- create a clean signed internal release candidate;
- run history-aware secret/private-data scans;
- choose Mac-first or cross-platform v1 scope;
- decide the intended commercial/distribution model with legal input.

### Gate 2: Close security and migration blockers

**Estimated effort:** 4-8 focused engineering weeks.

- close `OM-BUG-003`, `007`, `016`, `017`, and `018`;
- finish MCP/OAuth secret storage and key rotation;
- make mandatory CI blocking;
- replace legacy migrations and prove historical upgrades;
- update the threat/security model and complete independent review.

### Gate 3: Build the distributable Mac product

**Estimated effort:** 4-6 focused engineering weeks.

- bundle an immutable runtime and adopt standard macOS data locations;
- complete native lifecycle, permissions, OAuth callbacks, updates, uninstall,
  signing, hardened runtime, notarization, and Gatekeeper acceptance;
- generate SBOM, notices, source package, checksums, and release manifest;
- test clean installation and upgrade on supported Macs.

### Gate 4: Qualify real workflows and providers

**Estimated effort:** 4-8 focused engineering weeks.

- run Google, email, calendar, model, vector, transcription, MCP, notification,
  and physical-phone acceptance;
- automate complete browser and native end-to-end journeys;
- establish performance/capacity baselines and fault-recovery evidence;
- close or narrow any feature whose provider acceptance fails.

### Gate 5: Complete legal, privacy, and commercial operations

**Estimated calendar:** 4-10 weeks in parallel, dependent on external review.

- obtain licence/chain-of-title/trademark advice;
- complete notices, source offers, privacy policy, terms, and consent surfaces;
- define pricing, support, incident response, release, update, and end-of-life
  operations;
- complete accessibility audit and remediate material findings.

### Gate 6: Pilot and release

**Estimated effort:** 3-6 weeks.

- complete the seven-day owner soak;
- run an internal dogfood release and then a small paid pilot;
- record support burden, failures, recovery, retention, and workflow value;
- fix launch blockers and repeat all release gates;
- issue a signed release only when the acceptance record is complete.

These ranges overlap and depend on platform scope. A Mac-first controlled paid
beta is plausibly **4-6 months** of focused engineering plus external review.
A defensible cross-platform public release remains approximately **6-9 months**,
consistent with the five-phase plan's original commercial estimate.

## Definition of 100% Commercial Readiness

For the scoped Personal Private OS v1, “100%” means every item below has current,
archived evidence:

- [ ] No open Critical or High defect in the sold profile.
- [ ] Mandatory CI, security, migration, browser, package, and container gates block release on failure.
- [ ] Seven consecutive genuine-use days and a controlled paid pilot pass.
- [ ] Every advertised workflow passes end to end with real dependencies.
- [ ] Every advertised platform passes clean install, update, restart, restore, rollback, and uninstall.
- [ ] Native artifacts and containers are immutable, signed, scanned, and reproducible from the offered source.
- [ ] macOS artifacts pass hardened-runtime, notarization, stapling, and clean Gatekeeper tests.
- [ ] All historical supported databases upgrade safely and interrupted migration recovers.
- [ ] Complete encrypted backup and isolated restore meet documented recovery objectives.
- [ ] Provider OAuth applications, scopes, revocation, quotas, and policies are approved and tested.
- [ ] Security model, threat model, penetration test, vulnerability process, and incident runbooks are current.
- [ ] Privacy policy, terms, consent, deletion/export, and support-data practices match runtime behavior.
- [ ] Counsel has approved licence, chain of title, source offer, notices, dependency, and trademark treatment.
- [ ] SBOM, `THIRD_PARTY_NOTICES`, exact Corresponding Source, checksums, release manifest, and modification notices ship with every format.
- [ ] Accessibility audit and material WCAG 2.2 AA findings are closed or truthfully disclosed.
- [ ] Performance, capacity, idle resource use, and long-run stability meet published support limits.
- [ ] Diagnostics, logs, support, release updates, rollback, and end-of-life procedures are operational.
- [ ] Product claims, pricing, support promises, and supported use cases are approved and evidence-backed.

If one of these gates is intentionally excluded, the product can still ship only
after the supported profile and claim are narrowed so the excluded behavior is
not advertised or relied upon.

## Immediate Next Goal

The single next commercial-readiness goal should be:

> Produce a clean, signed internal release candidate that closes the critical
> corrupt-auth recovery defect, makes mandatory CI blocking, reconciles the
> security/status documents, and can be installed and upgraded on a clean Apple
> Silicon Mac without the development checkout.

That goal removes the highest concentration of technical and evidentiary risk
while keeping the v1 scope limited to Personal Private OS.

## Evidence Used

- `00-project-status.md`
- `03-feature-inventory.md`
- `07-security-model.md`
- `09-bug-register.md`
- `10-test-plan.md`
- `15-deployment-guide.md`
- `17-privateos-phased-plan.md`
- `licence-and-attribution-review.md`
- current release preflight output
- current Git worktree and CI workflow inspection
- current native macOS application build and verification evidence
