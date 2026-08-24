# Odysseus to OM Automate Migration Guide

## 1. Status and audience

This document is the migration contract and operator runbook for moving an existing Odysseus installation to OM Automate without silently losing data. It is based on the audited upstream baseline at commit `9844a2f9a1996b8c8135a9e7bbde6a72f41df5ed`.

**There is not yet a supported OM Automate in-place migration to run.** The current branch still uses the upstream storage layout, legacy identifiers, and import-time schema changes. It does not yet have a migration ledger, released OM Automate artifact, tested down migration, or certified Google-provider migration. Use the current procedures below to inventory and protect an installation; use the target runbook only after a release supplies the named migration commands and passes the gates in [10-test-plan.md](10-test-plan.md).

This guide distinguishes:

- **Current** — behavior present in the audited code and suitable for backup or inspection with the stated limitations.
- **Target** — the required OM Automate migration behavior; it is not a claim that the implementation exists.

## 2. Non-negotiable migration rules

1. Never upgrade the only copy of user data.
2. Record the exact source commit, platform, deployment mode, data root, service versions, and active integrations before changing code.
3. Stop writers before a final cutover snapshot, even though the current backup helper uses SQLite's backup API.
4. Preserve `data/.app_key` with the matching encrypted records. Losing it can make provider secrets unreadable.
5. Protect every backup as highly sensitive. The current gzip archive is **not encrypted** and normally contains both ciphertext and its application key.
6. Back up external volumes and paths separately. The application archive does not include Docker Chroma, model caches, host SSH material, or arbitrary custom paths.
7. Do not run older code against a database that newer startup code has modified. Rollback restores both the old code and its matching pre-upgrade data.
8. Do not rename legacy files, collections, cookies, token prefixes, headers, or environment variables by global replacement.
9. Do not reauthorize or revoke a real provider account until the operator has reviewed scopes and a rollback/connection-recovery plan.
10. Do not resume scheduled or agent work until migration validation and provider reconciliation are complete.

## 3. Current storage that must be inventoried

The native/source data root defaults to repository-local `data/` and can be redirected by `ODYSSEUS_DATA_DIR`. Docker maps `${APP_DATA_DIR:-./data}` on the host to `/app/data` in the application container.

An installation can contain:

| Data surface | Typical location | Migration treatment |
| --- | --- | --- |
| Primary relational data | `data/app.db` | Retain a consistent pre-upgrade copy; migrate only through tested additive schema steps. |
| Scheduled email and email cache | `data/scheduled_emails.db`, `data/email_cache.db` | Retain pending/user-authored state. Treat disposable cache separately only after its ownership and pending-action role are proven. |
| Authentication and settings | `data/auth.json`, `sessions.json`, `settings.json`, preferences, presets, features | Retain and validate. Session revocation may be an explicit security decision, never an accidental result. |
| Encryption material | `data/.app_key` and any legacy key files | Retain with restricted access. Never regenerate over an existing encrypted store. |
| Integrations and contacts | Integration JSON, model endpoint rows, email accounts, CalDAV/CardDAV state, MCP rows/OAuth files, `contacts.json` | Inventory without secret values; migrate ownership and secret references before removing legacy stores. |
| User content | Uploads, documents, personal documents, notes, gallery, generated media, skills, memory, research | Retain canonical content and provenance. Rebuild only derivatives whose source remains available. |
| Vector and search derivatives | Native Chroma data, Docker `chromadb-data`, memory/RAG collections, FTS indexes | Snapshot for rollback; eventually rebuild from canonical sources with count/query parity. |
| Logs and run artifacts | `data/logs`, task runs, background-job/research artifacts | Retain according to policy; redact secrets before sharing. Logs are not a canonical substitute for audit records. |
| External provider data | Gmail, CalDAV/Google Calendar, webhooks, hosted models | Not present in a local backup. Preserve provider IDs/cursors and reconcile remote state after restore. |

The detailed storage and backup matrix is in [05-data-model.md](05-data-model.md). The integration-specific retention rules are in [06-integration-register.md](06-integration-register.md).

## 4. Current pre-migration protection procedure

These steps prepare an audited baseline installation. They do not perform the OM Automate transformation.

### 4.1 Freeze and record

1. Put the installation into a maintenance window.
2. Record the current Git commit and dirty-worktree status.
3. Record whether the deployment is Docker, `start-macos.sh`, manual Uvicorn, or the Windows launcher.
4. Record the effective application data root and any external upload, attachment, embedding, model, or Chroma paths.
5. Record configured providers and account identifiers without copying API keys, passwords, OAuth tokens, cookies, or message content.
6. Record active scheduled tasks, pending email actions, model downloads/servers, research runs, and other background work.
7. Stop or allow those jobs to finish. Do not assume a process restart will resume them safely.

Useful read-only checks from the repository root include:

```bash
git rev-parse HEAD
git status --short
docker compose config --quiet
```

Run Docker commands only for a Docker deployment with its daemon available.

### 4.2 Create and verify the current application snapshot

For an installation that actually uses the repository-local `data/` directory:

```bash
./scripts/odysseus-backup snapshot --include-research --include-attachments
./scripts/odysseus-backup list
./scripts/odysseus-backup verify backups/odysseus-backup-YYYYMMDD-HHMMSS.tar.gz
```

The helper is currently hard-wired to repository-local `data/`. If `ODYSSEUS_DATA_DIR` points elsewhere, or Docker uses a different host `APP_DATA_DIR`, **do not accept this command's success as proof that the live data was backed up**. Stop the application and use a reviewed, platform-appropriate consistent snapshot of the actual directory, including SQLite databases and `.app_key`, until the backup tool supports an explicit validated data root.

Copy the verified backup to a restricted, encrypted, off-host location. Record its path, size, checksum, source commit, and creation time without publishing the archive.

### 4.3 Snapshot Docker service data

For Docker, the application archive does not contain the `chromadb-data` named volume. Stop application and Chroma writers, identify the exact Compose-prefixed volume, and follow the pinned-helper procedure in [15-deployment-guide.md](15-deployment-guide.md#142-docker-chroma-volume). Include any operator-owned SearXNG or ntfy state only when it is part of the recovery contract.

Do not use a floating archive image in a release procedure. Do not delete or recreate a named volume while merely trying to identify it.

### 4.4 Prove the backup before cutover

A verified tar header is necessary but insufficient. Restore a copy in an isolated directory/host and confirm:

- SQLite integrity succeeds;
- the expected users and row counts exist;
- a sample encrypted provider value can still be decrypted by the application;
- conversations, tasks, notes, local calendar records, documents, and user content open;
- knowledge/vector data either works or can be deterministically rebuilt;
- restart retains data;
- the restored instance cannot contact production providers or execute schedules during the test.

The current restore command is destructive and targets repository-local `data/`, so run it only in the isolated recovery checkout:

```bash
./scripts/odysseus-backup verify backups/<snapshot>.tar.gz
./scripts/odysseus-backup restore backups/<snapshot>.tar.gz --yes
```

## 5. Data retention and transformation contract

### 5.1 Data retained

An OM Automate upgrade must retain, unless the operator explicitly chooses otherwise:

- user identities, password hashes, 2FA configuration, and ownership mappings;
- conversations, messages, attachments, presets, and persona mappings;
- tasks, task history, notes, reminders, local calendars, and events;
- documents, versions, signatures, uploads, gallery items, and user-selected generated artifacts;
- contacts, memories, skills, knowledge sources, and source provenance;
- model endpoint metadata, connection metadata, and encrypted credentials;
- email/calendar account mappings, provider resource IDs, sync cursors, pending drafts/actions, and scheduled state;
- API token records, webhooks, MCP configuration, and integration grants until they are explicitly rotated or revoked;
- legal attribution, modification history, and upstream provenance.

Retention does not mean preserving unsafe sessions or stale provider grants forever. Security-driven revocation must be a documented, visible migration decision with a re-login/reconnect path.

### 5.2 Data transformed by the target migration

The target migration will progressively:

- add a schema migration ledger without rewriting the baseline on first adoption;
- assign immutable user/owner identifiers and quarantine ambiguous ownerless records;
- move provider connections and secrets behind versioned connection/secret records;
- migrate durable agent runs, action attempts, approvals, verifications, jobs, idempotency records, and audit events into first-class tables;
- separate canonical records from disposable caches and vector/search derivatives;
- normalize provider resource IDs by connection/account;
- rebuild FTS/vector indexes from canonical content with owner and fingerprint checks;
- copy browser/PWA and machine identifiers through compatibility readers before retiring legacy writers.

Each transformation must be versioned, idempotent, safe to retry, and accompanied by a dry-run count/checksum report. The table names and staged design are documented in [05-data-model.md](05-data-model.md#13-staged-migration-plan).

### 5.3 Data rebuilt rather than copied

Only documented derivatives may be rebuilt, for example:

- FTS indexes from their relational source rows;
- Chroma/embedding collections from retained knowledge sources and the recorded embedding model/fingerprint;
- disposable email/search/TTS caches from canonical or provider sources;
- generated UI caches and PWA assets from the release.

Never classify a pending action, user draft, sole copy of an upload, provider mapping, or user-approved memory as a disposable cache.

## 6. Compatibility-sensitive identifiers

The current application still uses legacy machine identifiers. A visual rebrand must not break them.

| Current identifier | Target behavior during compatibility window |
| --- | --- |
| `ODYSSEUS_*` environment variables | Read canonical `OM_AUTOMATE_*` first and legacy names second; new examples write canonical names only. This alias layer is not implemented yet. |
| `odysseus_session` cookie | Accept old and new, issue the new cookie after successful old-cookie validation, and clear both on logout. |
| `X-Odysseus-Internal-Token` / `X-Odysseus-Owner` | Accept both only on the existing trusted internal path while bundled clients migrate. |
| `ody_` API tokens | Keep issued tokens valid until explicit rotation; validate both prefixes during the declared window. |
| `odysseus-*` browser storage and `odysseus:*` events | Copy/validate with a version marker and dual-listen/dispatch for one compatibility cycle. |
| `odysseus_memories` / `odysseus_rag` | Copy with stable IDs/checksums, dual-read during cutover, verify count/content/query parity, then retire old writes. |
| Old email headers, kinds, subjects, and Message-ID domain | Continue recognizing historical markers so reminders and deduplication still work; write a neutral versioned schema for new messages. |
| `scripts/odysseus-*`, service names, paths, and backup names | Add canonical entry points and safe forwarding wrappers; detect old data before creating any empty new profile. |
| Old plugin names and `ODYSSEUS_URL` / `ODYSSEUS_API_TOKEN` | Publish versioned OM clients while retaining documented deprecated aliases. |

The exact compatibility matrix and retirement conditions are in [08-branding-register.md](08-branding-register.md#compatibility-migration-matrix).

## 7. Google and provider reauthorization

### Current state

- Gmail OAuth routes exist and use IMAP/SMTP XOAUTH2, but no real Google grant was verified in the audit.
- The current email OAuth path does not yet meet all target state-expiry, one-time-state, PKCE, minimal-scope, and provider-revocation requirements.
- There is no native Google Calendar API/OAuth provider. Google-compatible calendar access currently uses CalDAV configuration or optional unverified MCP presets.

### Target reauthorization rule

Do not silently carry a legacy grant into a new provider adapter. OM Automate must require a visible reconnect when any of these changes:

- OAuth client ID, redirect URI, provider adapter, or credential store;
- requested scopes or account identity;
- state/PKCE/token format;
- token encryption key or connection ownership mapping;
- provider grant is expired, revoked, ambiguous, or cannot be validated.

The connection screen must show the account, exact scopes, last successful sync, and whether remote data will remain untouched on disconnect. Reauthorization must occur in the backend OAuth flow; tokens must never be pasted into chat or exposed to the model/browser.

After reconnecting, perform read-only account identity and scope checks first. Reconcile calendars/mailboxes and provider resource IDs before enabling writes or scheduled work. Sending email, inviting attendees, deletion, or bulk operations remain disabled until approval and readback-verification gates pass.

## 8. Target release migration runbook

The following is the required workflow for a future migration-capable release. Replace placeholders only with commands shipped and tested by that release.

### 8.1 Preflight and dry run

1. Read the release notes, licence changes, security advisories, schema compatibility range, and platform support statement.
2. Verify the signed release/tag and pinned dependency/container manifest.
3. Complete the current freeze, inventory, encrypted backup, external-volume snapshot, and isolated restore proof.
4. Run the release's read-only migration preflight. It must report source schema, target schema, record/file/vector counts, ownership ambiguity, legacy identifiers, provider connections, disk requirements, and blockers without secret values.
5. Resolve or explicitly quarantine every blocker. A dry-run warning must never be converted to success by deleting unknown data.
6. Disable scheduled jobs, webhooks, provider writes, and agent actions for cutover.

### 8.2 Apply

1. Stop all application writers and confirm no worker/MCP/model-management child is changing data.
2. Take and verify the final cutover backup set.
3. Install the exact pinned release into a new code/environment location; do not reuse an upgraded virtual environment for rollback.
4. Point it at a **copy** of production data first and apply versioned migrations.
5. Require every migration checksum and postcondition to pass. Preserve a machine-readable migration report.
6. Start in maintenance/read-only mode and run validation before any provider write or schedule resumes.
7. Promote the migrated data only after the copy passes; use an atomic directory/volume switch where supported.

### 8.3 Validate

At minimum verify:

- login, invalid-login rejection, password change, 2FA, logout, and intended session behavior;
- user/owner counts and cross-owner isolation;
- conversation/message counts and sample attachments;
- tasks, notes, reminders, calendars/events, documents/versions, contacts, memories, skills, and knowledge sources;
- encrypted connection values can be resolved without appearing in API responses or logs;
- local model discovery and an ordinary chat response;
- provider connections in read-only mode, then explicitly approved sandbox writes with deterministic readback;
- FTS/vector count and sampled query parity after any rebuild;
- pending actions/schedules have one unambiguous state and do not duplicate on restart;
- browser storage/PWA migration, legal/source page, and intended OM Automate branding;
- backup and restore using the new release format;
- clean shutdown and restart persistence.

Record pass/fail evidence and keep the previous release stopped but recoverable through the observation window.

### 8.4 Resume service

Resume in this order:

1. authenticated read-only UI;
2. model chat without tools;
3. read-only provider synchronization;
4. low-risk local actions;
5. approval-backed provider writes;
6. scheduled jobs and webhooks after duplicate/replay controls are healthy;
7. high-risk tools only when their release gates pass.

## 9. Rollback procedure

Rollback restores a matched set: previous code, previous dependency/container versions, pre-upgrade application data, external volumes, and configuration.

1. Stop the failed release and all of its workers before they can perform more effects.
2. Record the failure and migration report. Preserve the failed data copy for diagnosis; do not use it as the rollback source.
3. Verify the pre-upgrade application and external-volume backups again.
4. Check out/install the previous verified release and recreate its environment from its lock/digests.
5. Restore the pre-upgrade `data/` and matching `.app_key` into the rollback instance.
6. Restore the matching Chroma/external volume set where required.
7. Start on loopback with schedules, webhooks, and provider writes disabled.
8. Run login, data-count, decryption, model, record, knowledge, and restart checks.
9. Reconcile provider effects that may have occurred during the failed upgrade. Mark uncertain actions indeterminate; never retry them automatically.
10. Resume service only after the rollback evidence passes.

For the current repository-local layout, [15-deployment-guide.md](15-deployment-guide.md#16-rollback-and-restore) contains the concrete destructive restore command and Docker/native variants.

## 10. Failure and recovery rules

| Failure | Required response |
| --- | --- |
| Migration stops before a versioned step commits | Preserve logs/report, correct the cause, and rerun only if the migration declares itself idempotent. Otherwise restore the pre-upgrade copy. |
| Schema changed but validation fails | Do not start old code against it. Keep the failed copy and restore the matched pre-upgrade set. |
| `.app_key` is missing or decryption fails | Stop. Do not generate a replacement. Locate the matching protected key/backup and validate in isolation. |
| Record ownership is ambiguous | Quarantine and require operator resolution; never assign another user by guess. |
| Vector counts/query results differ | Keep canonical data, discard the candidate derivative, and rebuild with the recorded model/fingerprint. Do not delete legacy collections until parity passes. |
| Provider write outcome is unknown | Disable dependent actions, query provider state using stable IDs, and record `indeterminate` until reconciled. Do not repeat the write blindly. |
| Google grant cannot be validated | Leave the connection disabled and require reauthorization; do not fall back to pasted tokens. |
| Browser opens an empty new profile | Stop immediately. Verify data-root/volume mapping and restore the previous mapping; do not continue setup and overwrite the expected identity. |

## 11. Migration acceptance record

For every supported source-to-target path, retain:

- source and target release identifiers;
- platform/architecture and deployment mode;
- dependency lock hashes and container digests;
- backup identifiers and restore-test result;
- preflight and migration reports;
- before/after row, file, vector, and owner counts;
- provider account/scope and reconciliation results without secrets;
- automated migration/full-suite results;
- browser, restart, backup, restore, and rollback smoke evidence;
- quarantined records and operator decisions;
- observation-window owner and end time.

An upgrade is not complete merely because the process starts. It is complete only when existing data remains usable, provider state is reconciled, no duplicate effect occurred, rollback evidence exists, and the target release's migration gates all pass.

## 12. Phase Ten task and project compatibility migration

The personal-work schema is additive. It does not rename, rebuild or delete `scheduled_tasks` or `task_runs`.

On schema initialisation:

1. `work_schema_meta` records the current personal-work schema version.
2. The `work_*` tables are created with `checkfirst` semantics.
3. Every discovered `scheduled_tasks` row gets one `work_tasks` projection keyed by unique `legacy_scheduled_task_id`.
4. The projection copies the legacy owner into the exact owner key (`""` only for an intentionally ownerless auth-disabled installation), title/prompt, schedule status, next/scheduled date and recurrence description.
5. The projection records `source_type=scheduled_task`, `created_by=migration`, `approval_state=migrated` and `legacy_read_only=true`.
6. Re-running backfill updates changed projection fields and creates no duplicate. It never writes to the legacy automation row.

Compatibility rules:

- Continue to edit, pause, resume, run and delete automations through legacy `/api/tasks` until a separately tested automation migration ships.
- Do not edit or delete their read-only personal-work projection.
- New personal tasks/projects/commitments live only in `work_*`; they are not silently scheduled as automations.
- Backups must retain both table families and `agent_actions`/audit records referenced by agent-originated mutation receipts.
- During owner migration, never treat an empty owner key as shared data. It belongs only to the explicit auth-disabled compatibility tenant; assign or quarantine it before enabling multi-user access.

Rollback can ignore/drop the additive `work_*` tables only if no new personal-work record must be retained. Otherwise export them first; reverting code will leave the tables inert but should not delete them.
