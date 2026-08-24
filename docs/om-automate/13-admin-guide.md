# OM Automate Administrator Guide

## 1. Administrative status

This guide covers administration of the audited Odysseus baseline while it is being transformed into OM Automate, and defines the target runbooks required before a production-quality OM Automate release.

The current repository is **not production-ready or reproducibly deployable**:

- native macOS Apple Silicon startup and a browser baseline were exercised;
- the full isolated test suite passed after portability fixes;
- the Docker daemon was unavailable, so no image build, Compose startup, volume persistence, or container recovery test was completed;
- dependencies and multiple container images still float;
- readiness, secret-file modes, log mounting, shutdown, migrations, agent policy, approvals, audit, backup encryption, and provider verification have release-blocking gaps;
- no live Google/Gmail/Calendar or complete transcription workflow was certified.

Keep the current build on loopback or isolated test infrastructure. Do not call a platform/provider supported unless it passes [10-test-plan.md](10-test-plan.md) and the launch checklist in [15-deployment-guide.md](15-deployment-guide.md#19-launch-acceptance-checklist).

## 2. Operator responsibilities

The administrator owns:

- deployment identity, bind address, HTTPS/private access, and service exposure;
- initial administrator creation, user lifecycle, 2FA, session, signup, and API-token policy;
- model/provider configuration and data-egress disclosure;
- powerful agent tools, shell/filesystem/MCP boundaries, and feature visibility;
- integration credentials, scopes, health, revocation, and test accounts;
- logs, health checks, background work, storage capacity, and incident response;
- encrypted/off-host backup, restore proof, update, migration, rollback, and retention;
- licence/source availability and visible modification/attribution notices.

Do not delegate these decisions to the model. A chat response cannot grant permission, approve an action, declare a provider healthy, or prove an effect succeeded.

## 3. Current deployment boundary

### Recommended current boundary

For evaluation:

- bind the application to `127.0.0.1`;
- keep authentication enabled and localhost bypass disabled;
- keep model, Chroma, SearXNG, ntfy, database, and other service ports loopback/internal;
- use a dedicated test account for every external provider;
- disable shell, broad filesystem, external writes, and unattended schedules by default;
- keep a verified backup before setup, migration, destructive admin actions, or provider changes.

The exact Docker/native prerequisites, ports, and launch commands are in [15-deployment-guide.md](15-deployment-guide.md). The audited direct native start was:

```bash
./venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 7860
```

The normal direct/Docker default is port `7000`; `start-macos.sh` uses `7860`.

### Network access

Do not bind the current app directly to a public interface. For any access beyond loopback:

1. place it behind a trusted HTTPS reverse proxy/private access layer;
2. keep `AUTH_ENABLED=true` and `LOCALHOST_BYPASS=false`;
3. enable secure cookies only on the real HTTPS origin;
4. set exact allowed origins;
5. validate proxy/client-address handling so a remote caller is never treated as localhost;
6. keep raw provider/service ports private;
7. test login, logout, session, CORS/CSRF, rate limits, OAuth callbacks, SSRF, and webhooks through the actual proxy;
8. prove encrypted v2 backup/restore and incident rollback before opening access.

This is a hardening baseline, not a statement that public deployment is supported.

## 4. Initial administrator and authentication

### 4.1 First setup

`setup.py` creates the first administrator only when `data/auth.json` does not exist. The default username is `admin`; passwords must be at least eight characters. Non-interactive setup can use legacy `ODYSSEUS_ADMIN_USER` and `ODYSSEUS_ADMIN_PASSWORD`, or print a temporary generated password.

Current first-run procedure:

1. set `umask 077` before creating `.env` or data on POSIX;
2. run setup only on a private loopback installation;
3. use a unique password from an approved password manager;
4. sign in and change any generated/temporary password immediately;
5. confirm open signup is disabled;
6. create a second named administrator for recovery only when operationally required;
7. enable and verify 2FA;
8. test invalid-login rejection and logout/session revocation;
9. back up the configured state using the protected backup process.

Never publish the generated password in logs, screenshots, issues, chat, or shell history. Remove a bootstrap password from `.env` after safe rotation when the deployment mechanism permits.

### 4.2 Damaged authentication store

An `auth.json` that exists but cannot be parsed puts the instance into a
**recovery-only** state. It is never treated as a clean first boot.

**How it presents.** The application starts and serves liveness, but:

- `POST /api/auth/setup` returns **503** with code `auth_recovery_required`
  (`routes/auth_routes.py:109`);
- `GET /api/ready` returns **503** with check `auth_store` = `failed`, code
  `auth_recovery_required` (`src/readiness.py`);
- the log carries a single `CRITICAL` line, `"Auth store requires local recovery"`,
  with no store contents.

The damaged file is **left untouched** so it can be investigated and restored.

**If you see this state:**

1. remove the instance from network access;
2. do not attempt to create a new administrator — the attempt is refused, and
   repeated attempts only obscure the audit trail;
3. preserve `auth.json`, `sessions.json`, logs, and file permissions; take a
   read-only copy before touching anything;
4. stop the application;
5. verify storage, ownership, permissions, disk health, and the last known-good
   backup — a damaged store is often the first visible symptom of failing disk or
   an interrupted write, not of attack;
6. restore the matched authentication/data set in isolation (see §12), so the
   auth store and the data it authorizes come from the same point in time;
7. rotate sessions, API tokens, provider credentials, and passwords if
   unauthorized access cannot be excluded;
8. reopen only after login, ownership, and log review pass.

**Never** delete `auth.json` to "get back in". That converts a recoverable
incident into an unauthenticated first-admin claim on a populated data set, which
is precisely the failure mode this state exists to prevent (`OM-BUG-003`).

Restoring a verified backup is the supported route back to service. If no backup
exists, the instance's data can be preserved but its accounts cannot — treat that
as data loss and record it.

## 5. User management

### Current controls

Settings → Users allows an administrator to list/create users, rename accounts, promote/demote administrators, edit coarse privileges, delete users, and control open signup. Account settings provide password and 2FA operations. The backend protects the last remaining administrator from demotion.

Current non-admin privilege fields are:

- `can_use_agent`;
- `can_use_browser`;
- `can_use_bash` (off by default);
- `can_use_documents`;
- `can_use_research`;
- `can_generate_images`;
- `can_manage_memory`;
- daily message limit;
- allowed-model list/restriction, including a block-all sentinel.

These are feature gates, not the target domain scopes.

### Create a user

1. Confirm a backup exists and open signup is off.
2. In Settings → Users, create a named non-admin account with a unique temporary password.
3. Restrict models and disable agent/browser/bash/image/research capabilities that the user does not need.
4. Have the user sign in privately, change the password, and configure 2FA.
5. Test access to allowed and denied features.
6. Record the account owner and review date without recording credentials.

### Rename a user

Renaming updates many ownership references, including database rows, preferences, research/memory/uploads/RAG/skills/session state. Treat it as a data migration:

1. stop active runs for the user;
2. create and verify a backup;
3. perform the rename through the UI/API, not by editing `auth.json`;
4. log out old sessions and sign in as the new name;
5. verify conversations, documents, uploads, memory, skills, tasks, integrations, and owner isolation;
6. inspect logs for partial ownership updates.

### Delete or demote a user

1. Confirm another administrator exists before demoting an admin.
2. Inventory owned records, provider connections, API tokens, schedules, webhooks, sessions, and files.
3. Export/transfer or explicitly delete data according to policy. The current product does not provide one complete ownership-transfer/retention workflow.
4. Revoke provider credentials, API tokens, sessions, MCP grants, and scheduled work.
5. Delete/demote through Settings → Users.
6. Verify bearer-token cache invalidation, login denial, owner isolation, and cleanup.

Do not assume deleting the authentication entry removes every file, vector, cache, remote provider record, or backup copy.

### Signup policy

Keep open signup disabled except for a controlled enrollment window on a private origin. If temporarily enabled, monitor new accounts, turn it off immediately afterward, and verify every account/role. The target product should support explicit invitations and stronger enrollment/audit controls.

## 6. Permissions and agent policy

### Current limitations

Current privileges do not distinguish `email.read` from `email.send`, `calendar.write` from `calendar.delete`, or a narrow file root from the whole enabled tool class. Administrator status provides broad access. There is no general risk classification, exact-version approval token, durable action state, or immutable action ledger.

The common executor and plan/admin backstops are valuable defenses but are not a complete authorization system. Non-native model prose can still reach executable tool parsing. Shell/Python/MCP can inherit sensitive environment values, and current file roots can include application data. Cookbook log diagnostics now require a same-owner/internal-request launch → failed-list → one-shot-tail sequence, but that capability is process-local and must not be treated as durable action ownership or audit evidence.

### Safe current policy

For ordinary users:

- leave `can_use_bash` off;
- disable Agent unless a reviewed use case requires it;
- restrict allowed models to approved endpoints;
- disable browser/research/image capabilities when data egress is not acceptable;
- do not install user-supplied MCP servers or skills without review;
- keep external writes in the domain UI and require human verification;
- use a separate non-secret workspace for any authorized file tools.

For administrators, use a separate daily non-admin account where practical. Do not use broad admin agent authority for routine chat.

### Target permission runbook

When granular scopes and the policy engine exist:

1. define roles as explicit scopes, not “admin gets everything” shortcuts;
2. bind scopes to user, provider connection, resource/account, origin, and time window;
3. classify every registered tool at risk Level 0-3;
4. require confirmation by default for Level 2 and always for Level 3;
5. permit “always allow” only for a narrow Level 1 action/resource and make it revocable;
6. re-evaluate policy and the exact action hash at dispatch time;
7. require deterministic provider readback for consequential effects;
8. review immutable action/policy/approval/audit events regularly;
9. test forged, expired, edited, cross-owner, revoked-integration, and replayed approvals;
10. fail closed on unknown tools, missing metadata, or unhealthy providers.

Do not enable target autonomous writes until all ten steps are implemented and tested.

## 7. Model configuration

### Available current controls

Settings → Services/Added models and the model/Cookbook screens can discover local Ollama, llama.cpp, LM Studio, and OpenAI-compatible endpoints; add local/hosted endpoints; store encrypted API keys in model endpoint rows; select a default model; manage embeddings; and expose provider device flows. Cookbook can download/serve models, but large downloads, platform-specific servers, and remote/GPU paths were not live-certified.

### Configure a local chat model

1. Start the local runtime on loopback and confirm it is the expected process/version.
2. Add or discover its endpoint in Settings → Services/Added models.
3. Use the endpoint's test/discovery control.
4. Select a small test model in a new ordinary chat.
5. verify a deterministic basic response and streaming/Stop behavior;
6. restart the application/runtime and repeat discovery/chat;
7. record runtime/model artifact version, endpoint, privacy classification, context limit, and tested capabilities.

The audited local example was Ollama at `http://127.0.0.1:11434` with `qwen3:1.7b`. That is evidence for the audit host, not a universal recommendation or agent-safety certification.

### Configure a hosted/API model

1. Use a dedicated least-privilege provider credential.
2. Enter it only in the approved backend settings field; never in chat or a generic URL when a secret field exists.
3. Confirm the base URL, TLS, data residency, retention/training policy, model IDs, and expected cost.
4. Test using non-sensitive content.
5. Verify that API responses, diagnostics, browser state, and logs expose only masked/presence metadata.
6. Restrict the endpoint to approved users/models.
7. rotate/revoke the credential and verify disconnect behavior before production use.

### Target model certification

Before a model may execute tools, its versioned capability profile must prove native tools/strict schema support, streaming, context budget, privacy class, timeout behavior, and minimum tests for valid/invalid arguments, unavailable tools, ambiguity, confirmations, failures, prompt injection, and refusal to invent results. Models that can only produce prose may chat/plan but must not directly request effectful execution.

## 8. Integration administration

### Current integration posture

| Integration | Current administrative claim |
| --- | --- |
| Ollama/local OpenAI-compatible chat | Native browser smoke verified on one Apple Silicon host. |
| Gmail OAuth/IMAP/SMTP | Code and tests exist; no live Google grant/mailbox action certified. |
| CalDAV/CardDAV | Code and tests exist; no credential-live provider run certified. |
| Native Google Calendar API | Absent. |
| Chroma | Required for complete vector behavior; unavailable in the minimal audited native run. |
| SearXNG/ntfy | Compose definitions exist; unavailable in the audited native run. |
| Generic REST/webhooks | Implemented with useful SSRF controls; lifecycle, inbound signing/replay, and audit gaps remain. |
| MCP | Built-ins connected natively; user presets can be unpinned and processes receive too much ambient authority. |
| Speech/image/vault/Cookbook/remote hosts | Code/test paths exist; live end-to-end support was not certified. |

Use [06-integration-register.md](06-integration-register.md) as the evidence register.

### Current connection procedure

For any provider:

1. use a dedicated test account/project and least-privilege credential;
2. record provider/account, intended capabilities, requested scopes, data classes, owner, expiry, and revocation method;
3. configure through the most specific provider screen, never chat;
4. run a passive identity/health check first;
5. exercise read-only operations;
6. perform one explicitly approved sandbox write and independently read it back;
7. clean up the remote fixture and verify cleanup;
8. inspect logs/browser/API for secret leakage;
9. test expiry/revocation/disconnect and restart;
10. mark it supported only if its credential-live evidence is recorded for the exact provider/API/adapter version.

Do not treat a preset entry or green “Test” button as complete certification.

### Google administration

The current email OAuth route needs administrator-supplied Google client configuration and an approved callback. It is not the finished unified Google connection manager. The target flow must have expiring one-time state, PKCE S256, minimal scopes, encrypted backend-only refresh tokens, reconnect/reauthentication, provider revocation, scope/account display, and live conformance evidence.

There is no native Google Calendar OAuth adapter. Do not market CalDAV or an optional MCP preset as equivalent to the required Google Calendar provider.

### MCP administration

Current built-in and configured MCP servers can expose tools dynamically. Before enabling one:

- pin package/version/digest and verify publisher/licence;
- inspect the manifest, command, arguments, environment, filesystem access, network egress, and tool list;
- remove unrelated environment variables and secrets;
- disable all tools not needed for the use case;
- bind it to a specific owner/connection;
- test timeout, cancellation, crash, restart, redaction, and uninstall cleanup;
- never use `@latest` in a certified release.

The current runtime does not yet provide the target sandbox/secret-broker contract, so third-party MCP remains high trust.

## 9. Logs, diagnostics, and health

### Current endpoints

```bash
curl --fail http://127.0.0.1:7000/api/health
curl --fail http://127.0.0.1:7000/api/ready
```

Current behavior:

- `/api/health` is a public process-liveness check;
- `/api/ready` currently requires authentication and checks only database/data-directory integrity;
- Settings → System/admin diagnostics exposes service and log views plus database/RAG stats;
- aggregate diagnostics do not cover every required provider/queue/scheduler/storage dependency.

Do not route traffic solely because `/api/health` is 200. The target readiness endpoint must be safe for an orchestrator, dependency-aware, and free of sensitive detail.

### Log locations

The main application file log is currently:

```text
data/logs/app.log
```

Docker Compose mounts `${APP_LOGS_DIR:-./logs}` at `/app/logs`, but the app writes `/app/data/logs/app.log`. Until fixed, inspect both the data-root log and container stream:

```bash
tail -f data/logs/app.log
docker compose logs -f --tail=200 odysseus
```

Protect and rotate logs. Never send unreviewed logs to a third party; they may contain operational metadata or personal content. Search for passwords, bearer tokens, cookies, OAuth codes, webhook secrets, email/document content, and shell output before sharing.

### Routine health review

At each start and daily for an active installation, review:

- app/database/data-root health;
- scheduler and stale/failed runs;
- MCP child connection/shutdown warnings;
- model/embedding/vector/search provider state;
- email/calendar connection errors and credential expiry;
- disk usage for data, uploads, logs, models, vectors, and backups;
- repeated authentication, webhook, SSRF, provider, timeout, and agent-tool failures;
- backup age and last isolated restore result.

The current four bundled MCP servers logged cancel-scope warnings at shutdown in the audit; treat orphan processes or repeated warnings as a defect, not harmless noise.

## 10. File and secret protection

The audited native setup created several secret-bearing files as mode `0644`. On a single-user POSIX host, use a restrictive umask before setup and audit permissions:

```bash
umask 077
chmod 700 data
find data -type d -exec chmod 700 {} +
find data -type f -exec chmod 600 {} +
chmod 600 .env
```

Do not apply modes/ownership blindly on shared or network filesystems. Verify the service still works. Windows requires a tested profile ACL procedure.

Secrets must not appear in:

- populated committed `.env` files;
- chat history/model context;
- generic settings, URLs, command arguments, or browser storage;
- logs, test fixtures, screenshots, issue text, or backup filenames;
- MCP ambient environment unless that specific server is approved to receive them.

The current `.app_key` and backup design do not provide key separation/rotation. Keep backups externally encrypted and tightly restricted until the target secret/backup system exists.

## 11. Backup administration

### Current snapshot

For the repository-local `data/` layout:

```bash
./scripts/odysseus-backup snapshot --include-research --include-attachments
./scripts/odysseus-backup list
./scripts/odysseus-backup verify backups/odysseus-backup-YYYYMMDD-HHMMSS.tar.gz
```

Important limitations:

- the tool is hard-wired to repository-local `data/`, not an arbitrary `ODYSSEUS_DATA_DIR`;
- the gzip archive is not encrypted;
- it includes `.app_key` with encrypted records;
- it does not include Docker `chromadb-data` or arbitrary external paths/volumes;
- provider-owned remote records are not backed up;
- tar verification does not prove application recovery.

After creating a snapshot:

1. copy it to an encrypted, restricted, off-host destination;
2. record checksum, source commit, deployment/data-root identity, and included data classes;
3. snapshot required Docker/external volumes as one matched set;
4. restore into an isolated environment with all provider writes/schedules disabled;
5. test database integrity, login, decryption, record counts, files, knowledge, and restart;
6. retain evidence and rotate backups according to policy.

### Target backup runbook

A production OM Automate backup service must:

1. freeze or consistently checkpoint all canonical stores;
2. produce a signed/checksummed manifest with app/schema versions, source root, per-file hashes, vector watermark, and exclusions;
3. encrypt before leaving the process and reference a master key kept outside the ordinary backup;
4. include canonical DB/files and required external volumes while declaring rebuildable caches;
5. upload/copy to an access-controlled off-host destination;
6. verify integrity automatically;
7. restore into staging, run migrations and ownership/decryption/vector checks, then promote atomically;
8. emit an immutable redacted backup/restore audit event;
9. alert on missed backups or failed restore drills;
10. test the complete procedure on every supported platform/release.

Until that exists, current backups are an operator-controlled interim mechanism.

## 12. Restore administration

The current restore is destructive and always targets repository-local `data/`:

```bash
./scripts/odysseus-backup verify backups/<snapshot>.tar.gz
./scripts/odysseus-backup restore backups/<snapshot>.tar.gz --yes
```

It renames the current directory to `data.before-restore-<timestamp>` before extraction. Preserve that safety copy until recovery is proven.

Restore procedure:

1. remove the instance from service and stop application, schedulers, workers, MCP, Chroma writers, and provider actions;
2. identify the exact code/dependency/container version compatible with the snapshot;
3. verify application and external-volume backups;
4. restore in an isolated checkout first;
5. restore the matching `.app_key` and external Chroma/other volumes;
6. run SQLite integrity and ownership/count/decryption checks;
7. start on loopback with schedules, webhooks, and provider writes disabled;
8. verify login, records, files, knowledge, model, and restart;
9. revalidate credentials/scopes and reconcile remote provider IDs/effects;
10. resume capabilities gradually and retain the previous state through the observation window.

Never generate a replacement key over restored ciphertext. Never run a restored copy and production copy against the same providers with active schedules.

## 13. Updates and schema changes

Current database initialization uses `Base.metadata.create_all()` and import-time `_migrate_*` functions. There is no migration version ledger or supported down migration. `scripts/update_database.py` is not the normal startup path and must not be run against release data unless a specific tested migration guide requires it.

Current update procedure:

1. read release notes, licence/security changes, and [11-migration-guide.md](11-migration-guide.md);
2. record exact current code, environment, images, configuration checksum, and service state;
3. create/verify the matched backup set and isolated restore;
4. test the new code against a copy of production data on an isolated port/host;
5. run automated, migration, browser, provider, restart, backup, restore, and rollback checks;
6. stop writers and take a final backup;
7. install the immutable target release in a separate environment;
8. start once under observation and validate before resuming provider writes/schedules;
9. retain the previous code/environment and backup for rollback.

Do not use `git pull` followed by an immediate production restart. Do not reuse an upgraded venv or floating images as the rollback environment.

## 14. Security settings checklist

Before each release/startup window, confirm:

- authentication is enabled; localhost bypass and open signup are off;
- no unexpected first-admin setup is exposed;
- passwords are unique and 2FA policy is met;
- sessions/API tokens/provider grants for departed or compromised users are revoked;
- only intended users are administrators;
- shell is disabled for non-admins and Agent is limited to reviewed users;
- allowed models/providers match privacy policy;
- MCP/skills/integrations are pinned, reviewed, owner-scoped, and least privilege;
- `.env`, `data/`, keys, databases, logs, and backups have restrictive permissions;
- only the HTTPS app origin is accessible beyond loopback;
- CORS/origin/proxy/cookie settings match the real origin;
- raw model, Chroma, SearXNG, ntfy, DB, and internal ports are private;
- webhook/API tokens are rotated and current inbound task hooks are not publicly exposed;
- no secrets appear in logs/browser/API/model context;
- backup age, restore evidence, disk capacity, and rollback owner are current;
- critical/high findings in [07-security-model.md](07-security-model.md) and [09-bug-register.md](09-bug-register.md) remain release-blocking.

## 15. Incident response

### 15.1 General response

1. **Detect and classify.** Record time, affected user/host/provider, symptoms, and whether an external effect may have occurred. Do not copy secrets or unnecessary personal content into the incident record.
2. **Contain.** Remove public access, disable affected users/integrations/tools/schedules/webhooks, and stop uncertain agent work. Preserve the host when forensic value outweighs shutdown.
3. **Preserve evidence.** Save read-only copies/checksums of relevant configuration, databases, logs, action/run state, process list, version manifests, and provider event IDs. Redact before sharing.
4. **Revoke.** Rotate/revoke sessions, passwords, API tokens, OAuth grants, webhook secrets, model keys, MCP secrets, SSH keys, and backup credentials according to scope.
5. **Determine effects.** Query the source provider/domain by stable IDs. Distinguish proposed, running, completed, verified, failed, cancelled, and indeterminate actions.
6. **Eradicate.** Remove compromised packages/configuration, correct the root cause, patch from a verified release, and rebuild environments rather than trusting an altered one.
7. **Recover.** Restore a known-good matched backup when needed; validate on loopback; reconcile provider state; resume read-only then low-risk services gradually.
8. **Review.** Document root cause, affected data/actions, user/operator decisions, recovery evidence, and required tests. Update the bug/security register and notify affected parties when policy/law requires.

### 15.2 Scenario actions

| Incident | Immediate administrative action |
| --- | --- |
| Authentication store corrupt/unconfigured | Remove network access, stop app, preserve `auth.json`/logs, restore known-good identity/data, rotate all sessions/tokens if setup may have been exposed. |
| Credential appears in chat/log/browser | Stop the affected provider/tool, revoke/rotate the credential first, delete/redact derivatives according to policy, inspect model/provider retention, then fix the leakage path. |
| Agent shell/file/MCP compromise | Stop the run and child processes, isolate host/network, preserve process/command/tool evidence, rotate every credential in the inherited environment, rebuild from known-good artifacts. |
| Email/calendar action outcome unknown | Disable dependent work, inspect provider Sent/event state by ID/time/account, mark indeterminate until reconciled, and never retry blindly. |
| Webhook/API abuse | Disable endpoint/token, preserve delivery IDs/requests safely, rotate secrets/tokens, inspect affected task/action runs and remote effects, keep inbound task hooks private until signed/replay-safe. |
| Data loss/corruption | Stop writers, preserve failed state, verify backups, restore matched code/data/volumes in isolation, reconcile providers, and prove record counts/decryption/restart before promotion. |
| Malicious document/email prompt injection | Disable autonomous tools for the affected run/source, preserve source/action evidence, verify that no scope/secret/action changed, quarantine source, add a regression fixture. |
| Dependency/MCP supply-chain concern | Disable/remove package without deleting evidence, record digest/source, rotate exposed secrets, rebuild from pinned verified artifacts, audit every tool/action since install. |

### 15.3 Communication and evidence

Use a correlation/incident ID. Store sanitized facts, not raw passwords/tokens or full personal content. Record who authorized containment, revocation, restore, and service resumption. The current app lacks a complete immutable audit trail, so preserve OS/container/provider evidence carefully.

## 16. Routine operations schedule

### Per start/deploy

- verify commit/manifest, configuration, permissions, private bind, health, logs, provider state, and disabled risky capabilities;
- inspect migration/startup and MCP child logs;
- perform login, ordinary model chat, and a read-only record check;
- verify no schedule duplicated after restart.

### Daily while active

- review failed/stale tasks, provider/auth errors, storage capacity, log anomalies, and backup completion;
- investigate unknown external effects before any retry.

### Weekly

- review users/admins/2FA, active sessions/tokens, model/integration grants, MCP/skills, schedules/webhooks, and retention queues;
- run a sample read-only provider health check and inspect backup verification.

### Per release or monthly

- perform an isolated restore drill;
- review dependencies/images/advisories/licences and exact pins;
- run security, migration, installation, browser, restart, provider, and rollback suites;
- review critical/high bugs and support matrix claims.

## 17. Target OM Automate administrative runbook

Before authorizing a target release for real personal data, the administrator must complete this end-to-end sequence:

1. Install from a signed, immutable, fully pinned release on an explicitly supported platform.
2. Verify safe public liveness and dependency-aware readiness for database, storage, scheduler/queue, model, embeddings, vector, and required providers.
3. Complete initial admin, password rotation, 2FA, closed enrollment, session, and recovery tests.
4. Define granular roles/scopes and risk/approval policy; prove deny-by-default behavior.
5. Certify each model capability profile before permitting tools.
6. Connect each provider through the common connection manager using least scopes, encrypted secret references, passive health, sandbox write/readback, revoke, and restart tests.
7. Verify every tool has typed input/output, handler, timeout/retry/idempotency, risk, approval, audit, compensation, and verification metadata.
8. Test approval edit/expire/reject/replay and all Level 2/3 enforcement in the browser.
9. Prove durable run/action/event restart, cancellation, idempotency, provider reconciliation, and partial-failure behavior.
10. Validate privacy routing, incognito non-persistence, prompt-injection isolation, export/deletion/retention, and secret redaction.
11. Create encrypted manifested backups, off-host copy, staged restore, vector rebuild/reconciliation, and full rollback evidence.
12. Run the complete automated and browser E2E suite, including morning briefing, email draft/approve/send/readback, calendar scheduling/readback, meeting workflow, knowledge sources, and malicious email.
13. Review logs/metrics/audit activity, support matrix, licence/source notices, operator owners, and incident contacts.
14. Resume capabilities progressively: UI/read-only, models, read providers, reversible local writes, approved provider writes, schedules/webhooks, then explicitly certified high-risk tools.
15. Keep rollback artifacts and heightened monitoring through the recorded observation window.

If any step is absent or fails, keep the system in loopback/test mode and record the blocker. A successful process start is not authorization to operate OM Automate as a privileged personal control system.

## 18. Related records

- Architecture and current behavior: [01-repository-audit.md](01-repository-audit.md), [02-current-architecture.md](02-current-architecture.md), [04-agent-architecture.md](04-agent-architecture.md)
- Storage and integration contracts: [05-data-model.md](05-data-model.md), [06-integration-register.md](06-integration-register.md)
- Security, bugs, and tests: [07-security-model.md](07-security-model.md), [09-bug-register.md](09-bug-register.md), [10-test-plan.md](10-test-plan.md)
- Migration, API, and deployment: [11-migration-guide.md](11-migration-guide.md), [14-api-and-webhook-guide.md](14-api-and-webhook-guide.md), [15-deployment-guide.md](15-deployment-guide.md)
