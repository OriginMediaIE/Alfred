# OM Automate Security and Privacy Model

## Document status

- **Status:** baseline audit and mandatory remediation plan; the findings below are not yet remediated unless explicitly described as an existing control.
- **Audit date:** 2026-07-18.
- **Audited source:** upstream `main` commit `9844a2f9a1996b8c8135a9e7bbde6a72f41df5ed`, working branch `om-automate/main`.
- **Product context:** OM Automate is a privileged, local-first control system. It can reach private messages, calendars, files, local processes, provider credentials, model endpoints, knowledge stores and external integrations. A model response is never an authorisation boundary.
- **Scope:** authentication, sessions, agent tools, shell and file access, MCP, OAuth, secrets, webhooks, SSRF, prompt injection, auditability, privacy, deployment and supply-chain controls.

## Security objectives

OM Automate must:

1. Fail closed when identity, policy, ownership, secret storage or configuration integrity cannot be established.
2. Keep credentials out of model context, chat history, browser JavaScript, tool output and logs.
3. Treat email, documents, websites, transcripts, calendar text, memories, skills, attachments and tool output as untrusted data.
4. Authorise every side effect outside the model using authenticated identity, ownership, least privilege, risk and confirmation state.
5. Disable unrestricted shell execution for the primary OM companion by default.
6. Make consequential actions previewable, confirmable, verifiable and auditable.
7. Preserve local-only operation and make every external data route visible to the user.
8. Provide secure deletion, retention, export, revocation and recovery controls.

## Severity model

| Severity | Meaning | Release treatment |
|---|---|---|
| Critical | Credible path to host compromise, administrator takeover, or broad secret/data compromise | Block all production and externally reachable releases |
| High | Credible unauthorised side effect, credential exposure, replay, or loss of a required security boundary | Block release of the affected feature |
| Medium | Defence-in-depth or operational weakness that materially increases impact or likelihood | Fix before general availability or record an owner/date/compensating control |
| Low | Limited-impact hardening or documentation issue | Track and verify in the normal backlog |

## Trust boundaries and principal assets

| Boundary | Untrusted side | Trusted side | Required boundary control |
|---|---|---|---|
| Browser to application | Browser input, cookies, extensions, CSRF, API callers | Authenticated route/service layer | Secure session, CSRF, schema validation, ownership and scope checks |
| Model to tool executor | Model text and native tool calls | Policy engine and execution broker | Typed tool registry, deny-by-default permissions, risk classification and approval token |
| Retrieved content to model | Email, files, web pages, transcripts, RAG, MCP/tool output | Instruction hierarchy | Source labelling, sanitisation, untrusted boundaries and non-model policy enforcement |
| Application to operating system | Shell, Python, filesystem, Docker, SSH and local processes | Sandboxed runner | Minimal environment, isolated identity, confined mounts, egress policy, resource limits |
| Application to providers | OAuth/API credentials and user content | Google and other services | PKCE/state, minimal scopes, backend-only token broker, revocation and redacted logs |
| Application to MCP servers | Admin-supplied binaries and remote MCP endpoints | MCP subprocess/client | Per-server capability set, clean environment, sandbox, secret references rather than values |
| Internet to inbound webhooks | Arbitrary requests and replay | Workflow scheduler | HMAC, timestamp, nonce/delivery ID, replay cache, body cap, rate limit and event allowlist |
| Application to outbound URLs | User/provider URLs and DNS | HTTP client | Scheme/host validation, DNS pinning, redirect policy, response cap and egress allowlist |
| Persistent storage and backups | Host users, copied disks and backup destinations | Private data and keys | OS permissions, authenticated encryption, separated keys, rotation and encrypted backups |

## Existing controls to retain

The audit found useful controls that should remain covered by regression tests:

- Authentication defaults on and localhost bypass defaults off (`app.py:246-254`).
- The trusted internal-token bypass verifies a direct loopback peer rather than trusting forwarding headers (`app.py:331-389`).
- Non-admin users are denied privileged built-in tools and the MCP namespace (`src/tool_security.py:35-75` and `src/tool_security.py:217-259`).
- Dedicated file tools canonicalise paths and reject sensitive path patterns; the remaining defect is the unsafe choice of an allowed root (`src/tool_execution.py:61-102` and `src/tool_execution.py:154-244`).
- A fail-closed plan-mode allowlist and static mutator backstop exist (`src/tool_security.py:78-192`).
- Untrusted-context helpers label and escape retrieved content (`src/prompt_security.py:8-86`).
- Non-native tool results are wrapped as untrusted data (`src/agent_loop.py:2292-2305`).
- Public settings are recursively scrubbed for secret-shaped fields (`src/settings_scrub.py:17-70`).
- Normal application pages receive security headers and a nonce-based script CSP (`core/middleware.py:59-126`).
- API tokens are one-time returned, bcrypt-hashed, owner-bound, revocable and assigned granular scopes (`routes/api_token_routes.py:13-73` and `routes/api_token_routes.py:120-207`).
- Outbound webhook delivery validates all resolved IPs and pins the approved destination IP while preserving Host/SNI, disables redirects and applies a timeout (`src/webhook_manager.py:29-249` and `src/webhook_manager.py:392-430`).
- Google email OAuth tokens use application encryption and are not returned by the account-list API (`routes/email_routes.py:5183-5218` and `routes/email_routes.py:4796-4836`).

These controls reduce risk but do not compensate for the release blockers below.

## Finding register

### SEC-001 — unrestricted agent subprocesses inherit application secrets

- **Severity:** Critical.
- **Evidence:** `src/tool_execution.py:519-540` copies all of `os.environ` into a tool subprocess; `src/agent_tools/subprocess_tools.py:8-9` allows one-hour execution; `src/agent_tools/subprocess_tools.py:103-153` invokes an arbitrary shell command or Python program with that environment. `routes/chat_routes.py:873-881` only adds bash to the disabled set when the submitted value is explicitly false, while administrators receive every boolean privilege by default in `core/auth.py:25-49`. Detached bash is launched at `src/tool_execution.py:715-740` and background job commands are persisted by `src/bg_jobs.py:81-159`.
- **Risk:** a malicious prompt, retrieved instruction or tool package can read provider keys, Google client secrets, internal tokens and other process credentials; execute arbitrary commands; access the network; alter the host; or persist a command containing a secret.
- **Required remediation:** disable shell and Python for OM by default for every role; replace direct execution with a separate sandboxed worker identity; pass a minimal explicit environment; mount only an ephemeral working directory; deny host sockets and credential paths; default-deny network egress; apply short per-tool timeouts, CPU/memory/process/file/output quotas; prohibit privilege escalation and destructive command classes; require a fresh, scoped confirmation for every privileged invocation. Do not store raw command text when it contains secret references.
- **Acceptance:** adversarial agent tests cannot read a planted parent-process secret, reach a denied network target, escape the working mount, fork indefinitely, access the Docker socket, run a destructive command or execute without the correct confirmation record.

### SEC-002 — the default file-tool root contains the application's secrets

- **Severity:** Critical.
- **Evidence:** `_tool_path_roots()` includes `DATA_DIR` by default (`src/tool_execution.py:105-151`). That directory contains `sessions.json`, `settings.json`, `auth.json`, `integrations.json`, `.app_key`, `vault.json`, application/email databases and `mcp_oauth` (`src/constants.py:18-50`). The denylist only recognises selected home credential names (`src/tool_execution.py:61-102`). `ReadFileTool` and `WriteFileTool` then read or overwrite a resolved path (`src/agent_tools/filesystem_tools.py:133-230`). Workspace vetting rejects a filesystem root but permits other broad directories (`src/tool_execution.py:251-272`).
- **Risk:** an administrator-level agent or prompt injection can read encryption keys, sessions, password hashes and tokens, or corrupt authentication and user data.
- **Required remediation:** create a separate agent workspace outside the application data root; allow only user-selected document roots; use immutable per-tool grants; explicitly deny all credential, database, configuration, log, backup and key locations; separate read and write permissions; prevent symlink/hardlink/device-file escapes; keep shell confinement independent of cwd.
- **Acceptance:** table-driven tests cover case variants, traversal, symlinks, hardlinks, absolute paths, broad custom roots and every sensitive constant in `src/constants.py`; no file tool can read or mutate application state unless a dedicated typed backend tool permits that exact operation.

### SEC-003 — a damaged authentication store reopens first-run administrator setup

- **Severity:** Critical.
- **Evidence:** any exception while loading an existing `auth.json` logs the error and replaces configuration with `{}` (`core/auth.py:121-141`). The unauthenticated setup route creates the initial administrator whenever `is_configured` is false (`routes/auth_routes.py:98-114`). Container setup failures do not prevent startup (`docker/entrypoint.sh:138-146`).
- **Risk:** corruption, permission failure or partial operational damage can make a configured deployment appear unconfigured, allowing a remote caller to claim the first administrator account.
- **Required remediation:** distinguish `missing` from `present-but-invalid`; start in a locked recovery state when an existing auth store cannot be parsed or validated; fail readiness; require an operator-local recovery procedure; atomically initialise the first admin with an exclusive creation lock; never ignore setup failure.
- **Acceptance:** corrupt, empty, unreadable, wrong-shaped and concurrently created auth stores never expose first-run setup, and the process/readiness state clearly identifies recovery as required.

### SEC-004 — MCP packages receive global secrets and MCP environment values are plaintext

- **Severity:** High.
- **Evidence:** stdio MCP configuration inherits the process environment (`src/mcp_manager.py:181-192`). Arbitrary environment JSON is accepted and persisted (`routes/mcp_routes.py:184-250`), stored as a plain `Text` column (`core/database.py:415-425`), and returned decoded to the browser (`routes/mcp_routes.py:120-153`).
- **Risk:** a compromised or over-privileged MCP package receives unrelated OM Automate credentials. MCP-specific API tokens can also be exposed in the database and settings UI.
- **Required remediation:** launch each MCP server with an empty/minimal environment in the same sandbox class as other executors; store only encrypted secret references; resolve a permitted secret at invocation time without returning it to browser/model; define per-server tools, owners, resources and egress; pin package versions and verify package identity.
- **Acceptance:** a test MCP server sees only its declared non-secret configuration and brokered capabilities; list/update APIs never return credential values.

### SEC-005 — there is no central policy, confirmation and verification boundary

- **Severity:** High.
- **Evidence:** the common executor checks request-disabled tools, guide-only policy and administrator status (`src/tool_execution.py:680-712`), then emits only a generic result log (`src/tool_execution.py:961`). It does not evaluate resource ownership, risk, confirmation, rate, time window, automation policy, sensitivity or session trust. The action-intent module is routing logic, not an authorisation engine. Email send is a useful domain-specific exception: confirmation defaults on and drafts are held for approval (`mcp_servers/email_server.py:1119-1227`; approval/cancel is owner-scoped in `routes/email_routes.py:3667-3707`). Agent prompts instruct the model not to second-guess successful tools (`src/agent_loop.py:121`, `src/agent_loop.py:230` and `src/agent_loop.py:243`).
- **Risk:** the model can authorise itself, consequential tools have inconsistent safety semantics, and a successful HTTP/tool return can be mistaken for verified real-world state.
- **Required remediation:** implement one server-side policy engine and execution broker. Every typed action must carry actor, owner, resource, integration, risk, data class, automation context and proposed arguments. The policy result must be `deny`, `allow`, or `confirm` with a short-lived action hash. Consequential writes require preview and approval; the broker performs the action, reads back state using an independent path, records verification and offers reversal when possible.
- **Acceptance:** every mutating tool is registered and classified; unknown tools fail closed; forged/stale/argument-changed approvals fail; ownership is checked in the service layer; critical actions have read-back tests.

### SEC-006 — safe plan mode exists but chat disables it

- **Severity:** High.
- **Evidence:** the read-only allowlist and mutator backstop are implemented in `src/tool_security.py:78-192`, but `routes/chat_routes.py:568-570` ignores submitted plan mode and forces it to false.
- **Risk:** users cannot reliably separate investigation/planning from execution, despite the existence of the safer policy.
- **Required remediation:** make planning an explicit server-validated conversation state; expose it in the UI; persist it per turn; prohibit all mutation, MCP mutation and subprocesses while active; require a separate transition and confirmation to execute an approved plan.
- **Acceptance:** direct HTTP, stale-client and model attempts cannot execute a mutator in plan mode.

### SEC-007 — inbound task webhooks lack message authentication and replay controls

- **Severity:** High.
- **Evidence:** webhook tasks receive a random URL token (`routes/task_routes.py:505-508`). The unauthenticated endpoint treats that path token as the only authentication and immediately runs the task (`routes/task_routes.py:1045-1070`); regeneration merely replaces it (`routes/task_routes.py:1072-1084`).
- **Risk:** URL credentials leak through logs, browser history and referrers. A captured request can be replayed after completion to repeat side effects. There is no signature, timestamp, delivery ID, body limit, source policy or durable idempotency.
- **Required remediation:** move the secret out of the URL; require a versioned HMAC over method, canonical path, timestamp, delivery ID and raw body; enforce a small clock window; compare in constant time; store delivery IDs through the replay window; cap body before parsing; rate-limit per hook/source; support event allowlists, optional IP/CIDR rules and overlapping secret rotation; log structured redacted outcomes.
- **Acceptance:** altered, expired, duplicated, oversized, unknown-event and old-secret requests are rejected deterministically; concurrent duplicate deliveries execute once.

### SEC-008 — Google OAuth implementations do not consistently meet state, PKCE and revocation requirements

- **Severity:** High.
- **Evidence:** email OAuth state is signed but has no issue time, expiry or server-side one-time consumption (`routes/email_helpers.py:68-99`). The Google email authorisation request has no PKCE and requests `https://mail.google.com/ email` (`routes/email_routes.py:5106-5128`); the callback exchanges without a verifier (`routes/email_routes.py:5130-5167`). Token storage and owner matching are present (`routes/email_routes.py:5183-5218`), but local account deletion does not revoke the provider grant (`routes/email_routes.py:4934-4958`). Legacy Google MCP uses predictable `server_id` state and no PKCE (`routes/mcp_routes.py:428-495`), then writes client credentials and token responses to ordinary files and exposes a raw provider error (`routes/mcp_routes.py:523-571`). Generic MCP OAuth does use SDK discovery, PKCE, refresh and a five-minute pending-state registry (`src/mcp_oauth.py:1-72`), with encrypted DB token storage (`src/mcp_oauth.py:83-90`; `core/database.py:423-425`).
- **Risk:** login-flow replay/session mix-up, weaker code interception resistance, durable orphaned grants and plaintext credential theft.
- **Required remediation:** use one OAuth connection manager; cryptographically bind state to owner, provider, redirect and an issued-at value; store and atomically consume it once; require PKCE S256; document and display scope rationale; encrypt provider client secrets and tokens through a versioned key service; refresh only in the backend; add reconnect, reauthentication, disconnect and provider revocation; never reflect raw provider responses; delete legacy token files through a migration.
- **Acceptance:** OAuth conformance tests cover replay, expiry, wrong owner/provider/redirect, missing verifier, refresh, revoked grant, token-log redaction and disconnect cleanup. Browser responses and model/tool payloads contain no raw token.

### SEC-009 — secret encryption has no rotation and backups combine keys with ciphertext

- **Severity:** High.
- **Evidence:** application Fernet material is created in `data/.app_key` with mode `0600`, but ciphertext carries no key identifier or rotation path (`src/secret_storage.py:37-65`). Provider keys use a second `data/.key` implementation with the same limitation (`src/api_key_manager.py:11-48`). Backups include the Fernet key, vault, sessions and tokens (`docs/backup-restore.md:3-16`) and `scripts/odysseus-backup:69-127` creates a gzip tarball without built-in encryption. Discord requires a token-bearing webhook URL (`src/integrations.py:106-116`), but only `api_key` is encrypted and masked (`src/integrations.py:166-203`), leaving the credential-bearing `base_url` exposed.
- **Risk:** theft of a data directory or backup yields both keys and protected values; keys cannot be rotated safely; URL-embedded secrets are plaintext at rest and returned to the frontend.
- **Required remediation:** consolidate secrets behind a versioned envelope-encryption interface; support active and previous key IDs, transactional re-encryption and recovery; keep the master key outside ordinary data/backups or protect it with an operator secret/OS key store; encrypt backups before leaving the process; treat credential-bearing URLs as secrets; prohibit secret material in generic settings fields.
- **Acceptance:** rotation and interrupted-rotation tests preserve data; old keys can be retired; a stolen backup without the external key is unreadable; restore performs integrity verification; APIs and logs show only presence/last-four metadata.

### SEC-010 — authentication and session hardening is incomplete

- **Severity:** Medium, elevated to High for an internet-exposed deployment.
- **Evidence:** login/signup/setup limiters are process-local and IP-based (`routes/auth_routes.py:90-92` and `routes/auth_routes.py:136-150`). The browser cookie is HttpOnly and SameSite Lax, but `Secure` defaults false (`routes/auth_routes.py:155-165`), and there is no explicit anti-CSRF token. TOTP secrets and eight `secrets.token_hex(4)` backup codes are stored directly in the auth JSON (`core/auth.py:495-555`). Session bearer tokens and expiry are persisted in plaintext (`core/auth.py:581-653`). Atomic JSON writes do not force restrictive file permissions (`core/atomic_io.py:21-45`). Setup prints the temporary administrator password (`README.md:37`; `setup.py:130-139`).
- **Risk:** weak recovery-code storage, bearer-token exposure from disk/backups, restart-reset throttling, CSRF exposure on state-changing cookie-authenticated routes and operational credential leakage.
- **Required remediation:** require HTTPS-aware secure cookies in production; add origin validation and synchroniser/double-submit CSRF protection; use durable account/IP/device throttling with bounded lockout; encrypt TOTP seeds and hash one-time backup codes with stronger entropy; store hashed/opaque session identifiers or protect the session store; add session/device inventory and revocation; enforce `0600`/ACLs on all credential stores; replace log-delivered bootstrap password with a one-time local setup URL or operator-supplied secret.
- **Acceptance:** CSRF, brute-force/restart, stolen-store, backup-code reuse, session revocation and bootstrap-race tests pass.

### SEC-011 — API bearer authentication is centrally accepted but route scope is decentralised

- **Severity:** High.
- **Evidence:** middleware accepts a valid `ody_` bearer token and authenticates the request across the application (`app.py:405-453`). `require_user()` correctly rejects API tokens on ordinary user routes (`src/auth_helpers.py:81-82`), while Codex routes and `/api/v1/chat` perform explicit scope checks. The design still relies on every current and future route selecting the right helper. Token records contain no expiry/rotation fields (`core/database.py:480-485`).
- **Risk:** one route that forgets the scope-aware helper can turn a limited bearer token into broader application access.
- **Required remediation:** centrally deny bearer tokens except on a declared route-to-scope registry; require exact read/write scopes and ownership in service methods; add expiry, last-used, creator, rotation lineage and purpose/audience; retain hashing and immediate revocation.
- **Acceptance:** route enumeration proves every API route is either browser-session-only or has an explicit scope; unknown/new routes deny bearer tokens by default.

### SEC-012 — prompt-injection resistance is not yet an enforceable security boundary

- **Severity:** High because privileged tools are currently available.
- **Evidence:** `src/prompt_security.py:8-86` supplies strong untrusted-content labels and escaped guard markers, and non-native tool output is wrapped at `src/agent_loop.py:2292-2305`. Native function results are appended directly with role `tool` at `src/agent_loop.py:2283-2290`. The protection is primarily model instruction, while the model can reach the capabilities described in SEC-001 through SEC-005.
- **Risk:** malicious email, document, website, transcript, memory, skill or tool output can induce an unsafe call. Prompt text cannot reliably prevent authorisation bypass or exfiltration.
- **Required remediation:** retain wrappers, also label native tool results in provider-compatible metadata/content, sanitise rendered/retrieved formats, minimise context, add source provenance, and enforce all permissions, secret access, destination allowlists and confirmations outside the model. Add an exfiltration detector for sensitive data crossing provider/tool boundaries.
- **Acceptance:** a malicious-content corpus covering every source type cannot change policy, access a secret, add persistence, send data, or approve its own action.

### SEC-013 — outbound webhooks have strong SSRF controls but incomplete delivery security

- **Severity:** Medium.
- **Evidence:** event names are allowlisted (`src/webhook_manager.py:22-27` and `src/webhook_manager.py:252-260`); public IP validation and DNS pinning are implemented (`src/webhook_manager.py:29-249`); errors are sanitised (`src/webhook_manager.py:308-320`); redirects are disabled and a ten-second timeout is used (`src/webhook_manager.py:392-403`); a timestamped JSON body is HMAC-SHA256 signed when a secret exists (`src/webhook_manager.py:405-426`).
- **Risk:** consumers lack a standard signature version/timestamp header, delivery ID and idempotency key; OM Automate lacks retry/backoff, durable delivery history and overlapping signing-secret rotation. Signing is optional.
- **Required remediation:** require a secret for non-local destinations; use versioned signatures, timestamp and delivery-ID headers over raw bytes; publish verification rules; implement bounded retry with jitter, dead-letter state and idempotency; support two active secrets during rotation.
- **Acceptance:** receiver fixtures validate signature/version/replay semantics, and retry tests prove at-most-once consumer behaviour with a stable delivery ID.

### SEC-014 — other outbound integration paths have residual SSRF and lateral-movement risk

- **Severity:** Medium.
- **Evidence:** public `/api/v1/chat` endpoint URLs are validated (`routes/webhook_routes.py:284-292`), but the validator documents that DNS checks alone do not eliminate rebinding (`src/url_security.py:81-88`). Generic integrations allow private/LAN endpoints by design (`src/integrations.py:405-418`).
- **Risk:** a privileged model or compromised integration can probe local services or cloud metadata; non-pinned public requests retain a DNS-rebinding race.
- **Required remediation:** route untrusted public URLs through the pinned transport; classify integrations as `public-only` or an explicit admin-approved LAN target; block metadata networks and Unix/Docker sockets; attach destination allowlists to tool policy; cap response bodies and content types.
- **Acceptance:** SSRF tests cover IPv4/IPv6, mapped forms, alternate notation, redirects, rebinding, mixed public/private DNS, metadata hosts and private integration policy.

### SEC-015 — audit logging and privacy controls do not meet the product specification

- **Severity:** Medium, elevated to High where regulated or highly sensitive data is used.
- **Evidence:** common tool logging records only description and exit code (`src/tool_execution.py:961`). URL redaction removes userinfo/query/fragment but is narrowly scoped and not universal (`core/log_safety.py:13-27`). Several paths log raw endpoint/error data or user prompt/query snippets, including `src/llm_core.py:2035`, `src/llm_core.py:2054`, `src/ai_interaction.py:1008`, `routes/chat_routes.py:1062` and `routes/email_routes.py:3484`.
- **Risk:** users cannot reconstruct who approved or verified an action; sensitive content can enter logs; deletion/retention controls cannot be proven.
- **Required remediation:** implement an append-only, tamper-evident audit store with actor, agent, session, action, redacted typed arguments, risk, policy decision, approver, timestamps, result, verification, reversal and correlation ID. Build central structured redaction. Add local-only mode, provider-routing disclosure, export/deletion, per-domain retention, model logging and telemetry controls, and integration uninstall cleanup.
- **Acceptance:** audit-chain integrity and redaction tests pass; users can view/export/filter history; retention jobs delete each data class and derived copies while preserving only legally/operationally required audit metadata.

### SEC-016 — dependency and container builds are not reproducible or fully verified

- **Severity:** Medium.
- **Evidence:** `Dockerfile:6` and `Dockerfile:12` use an unpinned image digest; `Dockerfile:22-36` installs unpinned operating-system packages; the Docker CLI archive is downloaded without a checksum (`Dockerfile:57-68`). Most Python requirements are unpinned (`requirements.txt:1-50`; `requirements-optional.txt:7-25`). Compose uses `chromadb/chroma:latest` and an untagged ntfy image (`docker-compose.yml:81` and `docker-compose.yml:141`). Entrypoint recursively changes ownership under configured writable trees and guards only a short list of broad mount roots (`docker/entrypoint.sh:50-101`).
- **Risk:** installations drift, a compromised or changed upstream artifact can enter the build, and a mis-mounted host directory can be recursively changed.
- **Required remediation:** pin images by tested version and digest; lock Python/system dependencies with hashes; verify downloaded archives; generate an SBOM and provenance; scan images/dependencies; remove or tightly validate recursive ownership repair; use migrations instead of mutable startup setup.
- **Acceptance:** clean builds on supported platforms resolve identical artifacts, pass vulnerability/licence policy, verify checksums/signatures and never mutate a deliberately broad test mount.

### SEC-017 — the checked-in threat model is stale

- **Severity:** Medium.
- **Evidence:** `THREAT_MODEL.md:75-81` says file tools lack confinement, `/api/v1/chat` permits arbitrary SSRF targets and token scopes are coarse. Current code has realpath confinement, public URL validation and granular token scopes, while the more serious allowed-root and central-scope defects above are not accurately represented.
- **Risk:** maintainers and reviewers may focus on fixed behaviour and miss current release blockers.
- **Required remediation:** replace assertions with tested invariants, link each threat to code/tests and update the model in every security-affecting change.
- **Acceptance:** security CI checks referenced tests and a reviewer checklist requires threat-model impact for tool, auth, OAuth, integration and storage changes.

## Target action-policy architecture

Every action must follow this server-side sequence:

1. **Parse:** convert the model proposal into a registered, versioned schema. Raw model text is never executable.
2. **Resolve:** bind authenticated user, role, session, owned resource and integration account.
3. **Classify:** assign data sensitivity and risk:
   - `R0`: read-only, low-sensitivity and no external disclosure.
   - `R1`: local, reversible mutation with bounded impact.
   - `R2`: external message, deletion, calendar/task commitment, integration write, bulk operation or sensitive disclosure.
   - `R3`: shell/process, credential/security/admin change, arbitrary destination, destructive/irreversible or high-volume action.
4. **Decide:** evaluate user/tool/integration permission, ownership, automation policy, time/rate limits, provider health, current session trust and destination policy. Unknowns deny.
5. **Preview:** render the exact target, effect, sensitive-data route, reversibility and changed fields.
6. **Approve:** require a user gesture for `R2` and a stronger recent-auth confirmation for `R3`. The approval token binds actor, action schema/version, canonical arguments, resource version and expiry.
7. **Execute:** use a least-privileged backend adapter; credentials are resolved inside the adapter and never returned.
8. **Verify:** read the provider/resource through an independent operation and compare the intended postcondition.
9. **Audit:** append the redacted proposal, policy decision, approval, result, verification and correlation ID.
10. **Reverse:** expose undo/revoke/cancel when supported and append its own audit event.

Automations use the same path. A pre-approved automation policy may replace an interactive prompt only when it narrowly fixes the action type, resources, destinations, volume, schedule, expiry and data classes; it cannot authorise `R3` shell/security actions.

## Privacy data map and required controls

| Data class | Examples | Default | Required user control |
|---|---|---|---|
| Identity/security | passwords, TOTP, sessions, device/IP history | local only; shortest practical retention | session view/revoke, security export, secure reset |
| Provider credentials | OAuth refresh/access tokens, API keys, webhook secrets | backend vault only; never model/browser/chat | connect, scopes, rotate, revoke, disconnect cleanup |
| Communications | email bodies, drafts, contacts | local cache only when enabled | account/label selection, cache duration, export/delete |
| Calendar/tasks | events, commitments, routines | local with provider sync chosen by user | calendar selection, sync direction, retention/delete |
| Files/knowledge/memory | uploads, embeddings, notes, RAG, memories | local by default | per-item/source delete, reindex, export, retention |
| Audio/transcripts | recordings, transcripts, summaries | no retention beyond task unless enabled | provider visibility, recording/transcript retention/delete |
| Conversations | prompts, model responses, tool results | configurable local history | incognito, retention, export, delete and derived-memory control |
| Diagnostics/audit | logs, metrics, action history | redacted; telemetry off by default | logging level, telemetry opt-in, audit export and retention policy |

Deletion must cover primary records, attachments, caches, indexes/embeddings, scheduled jobs and provider-side data where an API supports deletion. Where an immutable audit record must remain, it must contain only minimal redacted facts and document why it is retained.

## Release gates and required tests

OM Automate must not be described as secure, production-ready or safe for external exposure until all Critical and High findings are closed and the following gates pass:

- Unit and integration tests for the policy engine, ownership, confirmations, stale/forged approvals and read-back verification.
- Sandbox escape, environment-secret, filesystem, process/resource-exhaustion, egress and destructive-command tests.
- Auth-store corruption/recovery, first-admin race, CSRF, cookie, rate-limit/restart, 2FA backup-code and session-revocation tests.
- OAuth state/PKCE/refresh/revocation and browser/model/log token-non-disclosure tests.
- Inbound and outbound webhook signature, timestamp, replay, body-size, allowlist, rotation, idempotency, SSRF and retry tests.
- Prompt-injection corpus tests across email, attachment, document, website, transcript, calendar, contact, memory, skill, MCP and native/non-native tool results.
- Secret rotation, encrypted backup/restore, interrupted migration and stolen-backup tests.
- Audit tamper evidence, correlation, argument redaction, retention, export and delete tests.
- Dependency lock, checksum, SBOM, licence and container vulnerability checks.
- Manual browser verification of confirmation previews, recent-auth prompts, action history, Google connection state/scopes/revoke and every privacy control.

## Immediate implementation order

1. Close SEC-001 through SEC-004 and SEC-003's fail-open recovery path before allowing any external access.
2. Build the common policy/approval/audit broker and re-enable a real plan mode (SEC-005 and SEC-006).
3. Replace inbound webhook and OAuth/secret flows (SEC-007 through SEC-009).
4. Harden sessions, bearer route scopes and prompt-injection boundaries (SEC-010 through SEC-012).
5. Finish delivery, SSRF, privacy and supply-chain controls (SEC-013 through SEC-017).

Every remediation must be implemented incrementally with a migration, automated regression coverage, a startup/health check, a browser smoke test and an entry in the project status/bug register.
