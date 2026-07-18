# OM Automate data model and persistence register

**Baseline inspected:** om-automate/main at 9844a2f9a1996b8c8135a9e7bbde6a72f41df5ed
**Audit date:** 2026-07-18
**Status:** This document records the implemented stores and a target migration contract. Target tables, retention controls, and repository interfaces are not implemented unless explicitly marked current.

## 1. Scope and evidence

This register covers every durable or semi-durable application store found in the audited repository:

- the primary SQLAlchemy database;
- the scheduled-email and email-derived-data SQLite database;
- the optional legacy email cache database;
- JSON configuration, identity, preference, automation, and cache sidecars;
- uploaded and generated files;
- Chroma vector collections and local embedding caches;
- browser-local state;
- Docker named volumes and provider-owned remote records;
- backup, restore, retention, ownership, deletion, and migration implications.

Evidence came from source inspection, SQLite schema inspection, the native baseline run, restart-persistence smoke tests, and the repository backup script. No user content or credential values are reproduced here.

### Status vocabulary

| Status | Meaning |
|---|---|
| **Observed** | The store or behaviour existed in the native audit data directory or was exercised across restart. |
| **Implemented** | A concrete source path and tests exist, but the feature was not necessarily exercised with a live provider. |
| **Optional** | The path is created only when the associated feature runs. |
| **Derivative** | Rebuildable from a canonical record or provider, subject to a documented rebuild procedure. |
| **Parallel source** | Two current stores model the same domain without a single authoritative contract. |
| **Target** | Required OM Automate design, not current behaviour. |

## 2. Persistence topology

### 2.1 Data-root resolution

src/constants.py is the intended path registry. DATA_DIR resolves from ODYSSEUS_DATA_DIR or the runtime default. Most application files and directories are beneath it.

| Surface | Current resolution | Notes |
|---|---|---|
| Primary database | DATABASE_URL, default sqlite:///DATA_DIR/app.db in core/database.py | SQLAlchemy accepts another URL in principle, but current import-time migrations contain SQLite-specific SQL. SQLite is the evidenced backend. |
| Application data | DATA_DIR from src/constants.py | Native baseline used the repository data directory. |
| Mail attachments | ODYSSEUS_MAIL_ATTACHMENTS_DIR or DATA_DIR/mail-attachments | May be outside DATA_DIR and therefore outside the bundled backup. |
| FastEmbed cache | FASTEMBED_CACHE_PATH or DATA_DIR/fastembed_cache | May be outside DATA_DIR and is a derivative model cache. |
| Docker app data | Host APP_DATA_DIR, default ./data, mounted at /app/data | The application sees /app/data. |
| Docker Chroma | chromadb-data named volume | Separate from the app-data bind mount. |
| Docker SearXNG and ntfy | searxng-data and ntfy-cache named volumes | Operational state, also separate from app data. |
| Model and SSH caches | Host paths mounted under /app/.cache/huggingface, /app/.local, and /app/.ssh | Large artifacts and high-sensitivity SSH material are not part of the app backup. |
| Browser state | localStorage, session state, cookies, and caches in the browser profile | Not server-backed and not included in repository backups. |
| Provider state | Mailboxes, CalDAV/CardDAV resources, external integrations, model APIs, MCP services | Provider-owned; local rows may be cache, mirror, credential, or external-ID mappings. |

The path override is not consistently honoured by operational tooling. scripts/odysseus-backup hard-codes repository data rather than resolving ODYSSEUS_DATA_DIR or APP_DATA_DIR.

### 2.2 Current logical topology

| Layer | Current stores | Authority |
|---|---|---|
| Identity and browser sessions | auth.json and sessions.json | Canonical for local authentication. sessions.json means authentication sessions, not chat sessions. |
| Core product records | app.db | Canonical for chats, documents, endpoints, email accounts, tasks, notes, calendars, gallery metadata, API tokens, and several other domains. |
| Memory | memory.json, app.db memories, Chroma memory vectors | **Parallel source.** Current memory-manager behaviour primarily uses memory.json; SQL and vectors do not form one transactional record. |
| Generic integrations | integrations.json and app.db integrations | **Parallel source.** The active Settings and agent API-call path uses integrations.json. |
| Email schedule and derived cache | scheduled_emails.db | Canonical for scheduled/staged sends; cache/index tables are derivative. |
| Legacy email AI cache | email_cache.db | Optional compatibility input for the built-in email MCP server; absent in the observed baseline. |
| Calendar | app.db plus encrypted CalDAV accounts in user_prefs.json | Local records are authoritative for local calendars and a mirror/write-behind queue for CalDAV calendars. |
| Knowledge | source files plus Chroma RAG vectors and index sidecars | Source files are canonical; vectors are derivative. |
| Generated and uploaded media | filesystem plus app.db metadata | Both are required for a complete record; neither is sufficient alone. |
| Automation process state | app.db, JSON sidecars, bg_jobs files, and process memory | Fragmented. Scheduled tasks/runs are durable; active agent runs and some notification queues are not. |

## 3. Observed native baseline

The audited native data directory contained:

- .app_key;
- app.db;
- auth.json;
- logs/app.log and logs/search_engine_error.log;
- memory.json;
- presets.json;
- scheduled_emails.db;
- sessions.json;
- settings.json;
- user_prefs.json.

It also contained empty or not-yet-populated feature directories including cache/content, cache/search, chroma, deep_research, generated_images, mail-attachments/_compose, memory_vectors, personal_docs/runbook, personal_uploads, rag, skills, tts_cache, and uploads.

| Observation | Evidence |
|---|---|
| app.db size | 598,016 bytes |
| scheduled_emails.db size | 135,168 bytes |
| email_cache.db | Absent |
| app.db integrity | PRAGMA integrity_check returned ok |
| app.db objects | 142 sqlite_master objects; 32 physical tables including six FTS5 internal tables |
| Domain tables | 26 application tables |
| Restart persistence | Chat, task/note, calendar/email/knowledge entry points, and authentication flows were smoke-tested; created temporary task/note records were removed after verification. |
| Vector persistence | Not runtime-verified because ChromaDB was unavailable in the native baseline. |
| Secret-bearing file modes | .app_key was 0600; several JSON/database files were 0644. This is a security defect, not an approved deployment state. |

The snapshot is evidence of what this installation created, not a completeness promise. Optional stores appear only after their feature is used.

## 4. Primary database: app.db

### 4.1 Engine and schema management

core/database.py creates the engine, enables SQLite foreign keys, calls SQLAlchemy metadata creation, and executes a long series of idempotent-looking startup migration functions. There is no Alembic migration directory, schema_migrations table, or PRAGMA user_version contract.

Consequences:

- startup code, not a reviewed migration ledger, determines schema state;
- there is no durable record of which transformation ran, failed, or was retried;
- transactional rollback and downgrade semantics are undefined;
- a non-SQLite DATABASE_URL is not a supported claim merely because SQLAlchemy accepts it;
- backup and upgrade gates must assume ad hoc schema drift until versioned migrations replace this mechanism.

### 4.2 Domain table register

| Table | Purpose and important fields | Relationships | Ownership boundary | Data class and lifecycle |
|---|---|---|---|---|
| sessions | Chat configuration and counters: endpoint_url, model, headers, RAG/archive/folder flags, mode, token/message counts, crew_member_id, timestamps | Parent of chat_messages; referenced by documents, tools, crew, tasks, memories | owner is nullable; null represents legacy/shared data | Canonical chat record. headers may contain provider authorization material and must be migrated to secret references. |
| chat_messages | role, content, metadata JSON stored as text, timestamp | session_id foreign key with cascade delete | Inherited strictly from sessions; no direct owner column | Canonical transcript and nested tool metadata. High-sensitivity, retention-controlled content. |
| documents | title, language, current_content, version_count, active/archive/tidy state, source email references | Optional session; parent of document_versions | owner is nullable | Canonical document head. Email source references can link to provider data. |
| document_versions | version_number, content, summary, source, created_at | document_id cascade delete | Inherited from document | Canonical revision history. Deleting the head cascades every version. |
| gallery_albums | name, description, cover_id, timestamps | Parent of gallery_images | owner is nullable | Metadata only; referenced image files live on disk. |
| gallery_images | filename, prompt/caption, model, size/quality, user and AI tags, favorite/active flags, file hash, EXIF/GPS, dimensions and byte size | Optional session and album | owner is nullable | Metadata half of a media record. The generated/uploaded file is the other half. GPS/EXIF are sensitive. The built-in image MCP currently creates a row without assigning an owner. |
| email_accounts | IMAP and SMTP endpoints/users/passwords/security, from identity, OAuth provider/access/refresh/expiry, default/enabled | Referenced by email schedule/cache records by account_id string | owner is nullable and indexed | Canonical local connection config. Passwords and OAuth tokens are encrypted through current secret helpers; expiry is metadata. Remote mail remains provider-owned. |
| model_endpoints | base_url, encrypted api_key, enabled/type/kind, model caches and pins, refresh policy, supports_tools | Optional provider_auth_id | owner nullable; null is legacy/shared and visible broadly | Canonical endpoint config. cached_models and hidden_models are derivative; keys are sensitive. |
| provider_auth_sessions | provider, owner, label, base_url, encrypted access/refresh tokens, refresh time, auth_mode | Referenced by model_endpoints | owner nullable | Canonical refresh-aware model-provider credential session. Revoke and delete on disconnect. |
| mcp_servers | stdio command/args/env or remote URL, transport, enabled state, OAuth config/tokens, disabled tools | Dynamically exposes MCP tools | No owner; administrator-global | Canonical MCP configuration. oauth_tokens uses encrypted text; env and args are plain JSON text and may contain secrets. |
| comparisons | prompt, endpoint/model pair, responses, metrics, winner, blind mapping, vote time | Optional parent session by string | owner nullable | Canonical experiment result; contains full prompts and model output. |
| signatures | name, encrypted base64 PNG and optional SVG, dimensions | Used by documents/email | owner nullable | Sensitive biometric-like artifact. Encrypted columns still depend on .app_key. Delete promptly and include in export/delete workflows. |
| api_tokens | bcrypt-style token hash, display prefix, scopes, active and last-used state | Authenticates API, Codex, Claude, chat and automation clients | owner nullable | Canonical token verifier. Raw token is returned once and should never be backed up elsewhere by the app. |
| webhooks | name, destination URL, HMAC secret, event list, active and last-delivery status/error | Outbound event manager | No owner; administrator-global | Current create route encrypts the secret through the API-key manager, but the column is plain String and legacy plaintext is accepted on decrypt failure. URL can itself contain secrets. |
| user_tools | user mini-app HTML, scope/session, pinned/active/version/author | Optional session; parent of user_tool_data | owner nullable | Canonical executable/UI content and a prompt-injection/XSS-sensitive artifact. |
| user_tool_data | key/value records | tool_id cascade delete; unique tool/key | Inherited from user_tools | Canonical mini-app state; arbitrary content with no typed retention policy. |
| crew_members | persona, model/endpoint, greeting, enabled tools, default state, timezone | Optional session; referenced by tasks | owner nullable | Canonical persona/configuration. Personality and greeting may contain private data. |
| scheduled_tasks | prompt/action, schedule/cron/event/webhook trigger, counters, next/last run, chaining, session/model/endpoint, webhook token, crew, step and notification limits | Optional session, self-reference then_task_id; parent of task_runs | owner nullable | Canonical automation definition. webhook_token is an inbound bearer secret stored in plaintext in the row and URL. |
| editor_drafts | layered editor payload with base64 pixels, thumbnail, dimensions, source image, active state | Source image is an un-enforced string reference | owner nullable | Canonical draft. Potentially very large and sensitive; needs quota and retention. |
| task_runs | start/finish/status/result/error/tokens/steps/model | task_id cascade delete | Inherited from scheduled_tasks | Partial audit/execution record. steps is not a complete immutable agent-action ledger. |
| memories | text/category/source, owner, optional session, Unix timestamp | Optional session with set-null | owner nullable | Parallel memory representation; current memory.json behaviour prevents treating this table alone as canonical. |
| notes | note/checklist content/items, labels, due/repeat, source/session, image, AI classification/hash, agent session | String session references, no foreign keys for several links | owner nullable | Canonical note record. Reminder state also uses sidecars/process queues. |
| calendars | name/color/source, CalDAV account_id/base URL | Parent of calendar_events | owner nullable | Canonical local calendar and local representation of a remote calendar. account_id points into user_prefs.json rather than a relational credential table. |
| calendar_events | global uid primary key, calendar, content/time/recurrence, importance/type, provider href/etag, write-behind marker | calendar_id foreign key | Inherited from calendar | Canonical for local events; mirror for CalDAV. A globally unique uid cannot safely represent identical provider UIDs in two owners/calendars; target key must include connection/calendar scope. |
| caldav_deleted_events | deleted UID, owner/calendar, remote href/etag/base URL, summary, last error | Logical tombstone for CalDAV deletion | direct owner | Durable remote-delete retry state. Retain until verified deletion, then expire under audit policy. |
| integrations | name, type, config JSON, enabled | None | owner nullable | Present but not the active generic integration store. Parallel with integrations.json and therefore not authoritative. |

### 4.3 Search index objects

chat_messages_fts is an FTS5 virtual table used for transcript search. SQLite also creates chat_messages_fts_config, chat_messages_fts_content, chat_messages_fts_data, chat_messages_fts_docsize, and chat_messages_fts_idx.

These are derivatives of chat_messages:

- back them up only as part of a consistent SQLite snapshot;
- do not export them as user-facing records;
- rebuild them from canonical messages after repair or migration;
- ensure owner scope is established by joining through sessions before returning matches.

### 4.4 Relationship and ownership defects to resolve

1. Nullable owner is overloaded as legacy, shared, or unauthenticated state. The target must use an explicit tenant/user identifier and an explicit visibility enum; null cannot grant visibility.
2. Global administrator configuration tables, notably mcp_servers and webhooks, have no owning tenant or installation identifier.
3. Several relationships are string references without foreign keys, including provider account IDs, some session IDs, and gallery source IDs.
4. calendar_events uses provider UID as a global primary key. It must become an internal UUID with a unique constraint on connection_id, remote_calendar_id, and remote_uid.
5. chat session headers, MCP env/args, webhook URLs, scheduled webhook tokens, and arbitrary config JSON can contain secrets outside typed encrypted columns.
6. Generated image metadata can be created ownerless by mcp_servers/image_gen_server.py.
7. There is no durable agent run/action/attempt/approval/verification/audit schema. TaskRun is not a substitute.

## 5. Email scheduling and cache database

routes/email_helpers.py opens SCHEDULED_EMAILS_DB and creates both scheduling records and HTTP-email derived caches in the same SQLite file. In the observed baseline this was data/scheduled_emails.db.

### 5.1 Tables in scheduled_emails.db

| Table | Role | Key/scope | Retention and migration |
|---|---|---|---|
| scheduled_emails | Scheduled sends and staged agent drafts; recipients, subject/body, reply headers, attachment JSON, send/created time, status/error, owner, account_id, kind | id; owner index. Status includes pending, failed, sent, cancelled, and agent_draft. | Canonical pending-action record for email only. Migrate to generic actions/approvals/outbox; retain delivery proof without retaining full body indefinitely. |
| email_summaries | AI summary by message | message_id plus owner | Derivative. TTL, invalidate on provider message mutation, delete with owner/account disconnect. |
| email_ai_replies | Suggested reply by message | message_id plus owner | Derivative and potentially sensitive model output. Short TTL. |
| email_translations | Translation by body hash and target language | body_hash, owner, target_language | Derivative. Hash does not make content non-sensitive; apply TTL. |
| email_tags | Local tags/classification | message_id, owner, account_id | Derived/user-enhanced metadata. Export and delete with account. |
| email_calendar_extractions | Extracted event candidates | message_id plus owner | Derivative. Delete when source mail/account is removed unless promoted into a calendar event. |
| email_urgency_alerts | Urgency-classification cache | message_id plus owner | Derivative. Short TTL and explicit notification history boundary. |
| sender_signatures | Learned sender signature blocks | from_address plus owner | Derivative personal profile data. Must be owner-scoped, exportable, and resettable. |
| email_event_seen | Poller deduplication | owner, account_key, folder, message_key | Operational idempotency state. Retain for a bounded provider-specific window. |
| email_message_index | Message ID/UID/date lookup | owner, account_key, folder, uid; folder/date and message-ID indexes | Derivative provider index. Rebuild from mailbox; delete on disconnect. |
| email_body_preview_cache | Body preview | owner, account_key, folder, uid | Derivative sensitive content. Short TTL, storage cap, purge on logout/disconnect if policy requires. |
| email_attachment_metadata_cache | Attachment names/types/sizes | owner, account_key, folder, uid | Derivative; may expose sensitive filenames. Bounded TTL. |
| email_boundaries | Signature/quoted-text segmentation, model, turn JSON | message_id only | **Defect:** lacks owner, account, and folder scope. Two accounts can collide. Replace key with connection_id plus immutable provider message identity. |

The file mixes canonical scheduled effects with disposable caches. That prevents clean retention, backup, and restore choices. The target separates the durable action/outbox tables from a disposable cache database or cache service.

### 5.2 email_cache.db compatibility path

EMAIL_CACHE_DB defaults to DATA_DIR/email_cache.db. The built-in email MCP server opens it only as a legacy/optional AI cache and reads an email_ai table with subject, sender, summary, and suggested_reply when present. The repository does not establish that table as the current HTTP-email cache schema.

Important distinctions:

- email_cache.db was absent in the observed baseline;
- current email index/summary/reply tables were observed in scheduled_emails.db;
- deployment and feature documents must not claim that every email cache lives in email_cache.db;
- migration must import a discovered legacy email_ai table once, attach an owner/account where possible, quarantine ambiguous rows, then retire the file.

## 6. JSON and key-file register

All paths below default beneath DATA_DIR unless noted.

| Path | Current content and owner model | Secret handling | Authority and target disposition |
|---|---|---|---|
| auth.json | Users keyed by normalized username; password hash, admin/privileges, two-factor fields, signup policy | Passwords are hashed; two-factor material is sensitive | Current identity authority. Migrate transactionally to users, roles, credentials, and recovery-factor tables. Fail closed on corruption. |
| sessions.json | Authentication token to username/expiry; default lifetime is seven days | Session tokens are bearer secrets | Current auth-session authority. Migrate to hashed session IDs with rotation, device metadata, revocation, and expiry indexes. This is not chat storage. |
| settings.json | Installation-wide search, speech, reminder, email-style, feature, and operational settings | Selected fields are encrypted/scrubbed, but no typed schema proves every secret field | Migrate to versioned typed installation settings and secret references. |
| features.json | Global feature flags | Normally no secrets | Version, validate, and keep installation-scoped. |
| user_prefs.json | _users map of username to arbitrary preferences; legacy flat data migrates to first admin | CalDAV account passwords are encrypted here; other arbitrary keys may become sensitive | Current user preference authority and CalDAV connection store. Move provider connections/secrets to relational typed records; keep presentation preferences separately. |
| memory.json | List of id, text, source, category, timestamp, owner | Plain personal content | Current memory-manager authority and parallel with SQL. Migrate once to canonical memories and vector outbox. |
| memory_tidy_state.json | Per-owner memory fingerprints/tidy progress | Metadata can reveal usage | Operational derivative; bounded and rebuildable. |
| presets.json | Built-in/custom prompt/persona presets and groups | Prompt content may contain private data | Global/legacy scope is ambiguous. Migrate user-created presets to owner-scoped records; ship built-ins as versioned code assets. |
| integrations.json | Generic REST integrations with base URL/auth fields and enabled state | api_key encrypted with .app_key; URL may embed a Discord token | Active generic integration authority, despite parallel SQL table. Migrate to provider_connections and secret references. |
| contacts.json | Local contacts array with names, emails, phones, addresses | Plain personal data | Local fallback/cache, global rather than clearly per-owner. Migrate to owner-scoped contacts or treat as provider cache. |
| api_keys.json and companion .key | Legacy provider-key map | Separate Fernet key mechanism from .app_key | Import into the central secret store, rotate where possible, and remove both legacy files. |
| .app_key | Fernet key for encrypted fields and JSON secrets | Mode 0600 observed | Root decryption secret. Must not travel in the same unprotected backup as ciphertext; integrate with OS keychain/KMS or encrypt the backup with a separate key. |
| embedding_endpoint.json | Custom embedding URL/model and encrypted API key | API key encrypted | Migrate to a typed embedding provider connection. |
| cookbook_state.json | Environment, server/download/preset/task state, model paths and SSH hosts | Can reveal host topology and commands | Operational state with privileged host references. Split durable presets from ephemeral job state and redact secrets. |
| bg_jobs.json | Background command/session/PID/path/status records | Commands/logs can contain secrets | Current process registry; active output also lives under bg_jobs/. Replace with durable job/action records, redacted command templates, and bounded logs. |
| vault.json | Vaultwarden/Bitwarden CLI server, email, and BW_SESSION | Explicit 0600 handling; session is a bearer secret | Current global vault CLI session. Move to per-owner provider connection and OS-backed secret; revoke on disconnect. |
| tidy_calendar_state.json | Calendar tidy fingerprints/progress | Per-user content fingerprints | Derivative operational state; bounded TTL. |
| email_urgency_state_OWNER.json | Per-owner urgency polling state | Mail identifiers and timing | Derivative; bounded TTL and delete with account. |
| note_pings_OWNER.json | Per-owner note reminder deduplication | Note identifiers/timing | Operational state; migrate to notification delivery/idempotency rows. |
| skills.json | Legacy skill index/config | Skill content can execute or instruct tools | Retire after migration to versioned skill manifests and owner-scoped installations. |
| personal_docs/indexed_directories.json | Indexed host-directory configuration | Reveals filesystem topology | Installation/user-scoped configuration; validate and keep out of model output. |
| personal_docs/excluded_files.json | Index exclusions | Reveals paths | Same treatment as indexed directories. |
| uploads/uploads.json | Upload metadata beside files | Filenames and sources are sensitive | Migrate to artifact metadata with ownership and content hash. |
| deep_research/SESSION.json | Run status, sources, report, and owner | Full research content | Current per-run record. Migrate to durable agent/research runs and artifacts with retention. |
| skills/_usage.json | Skill usage counters/history | Usage metadata | Derivative analytics; owner scope and retention are currently unclear. |
| fixture_email_messages.json | Test fixture data | Must contain no real data | Never treat as a production store; exclude from user backup/export. |

Atomic JSON writes are used in several helpers, but there is no common schema version, checksum, journaling, or corruption-recovery contract across all files.

## 7. Files, directories, and caches

| Path | Contents | Canonical or derivative | Ownership/retention implications |
|---|---|---|---|
| personal_docs/ and personal_docs/runbook/ | Indexed knowledge sources and runbook files | Canonical when copied into app storage; otherwise indexed host path may remain source | Must retain owner/source/path provenance and delete vectors on removal. |
| personal_uploads/ | Uploaded knowledge originals | Canonical artifact | Include in backup by default or explicitly document loss; current backup code comments and skip constants are inconsistent. |
| uploads/ | General uploaded files and metadata | Canonical artifact until promoted/deleted | Owner-scoped access, malware/content limits, quota, retention. |
| generated_images/ | Base64 API image outputs and gallery files | Canonical media bytes paired with gallery_images | Deleting metadata must delete bytes after a successful transaction; orphan sweeper required. |
| gallery/ and gallery_uploads/ | Gallery assets/imports | Canonical or staging depending route | Pair with metadata, owner, hash, and lifecycle state. |
| mail-attachments/ and _compose/ | Cached IMAP extraction and compose staging | Provider-derived cache and temporary staging | Excluded by default backup; purge by TTL and after send/cancel. External path override must be covered explicitly. |
| rag/ and chroma/ | Legacy/native vector artifacts and metadata | Derivative | Current Chroma client is HTTP; do not assume this directory contains the live Docker vectors. |
| memory_vectors/ | Legacy/local memory vector material | Derivative | Rebuild after canonical memory migration. |
| fastembed_cache/ | Downloaded embedding model cache | Derivative | Large, rebuildable, license/version manifest required. |
| cache/content and cache/search | Fetched/extracted content and search result cache | Derivative | TTL, size cap, URL/content privacy, and no backup by default. |
| emoji_cache/ | Downloaded/generated emoji assets | Derivative | Rebuildable, bounded. |
| tts_cache/ | Synthesized speech | Derivative but may reproduce private text | Short TTL, owner key, content hash, no default backup. |
| email_urgency_cache/ | Email urgency artifacts | Derivative | Owner/account scope and short TTL. |
| deep_research/ | Research run JSON and possible artifacts | Current run record, not safely derivative | Excluded by default backup unless requested; this means default recovery is incomplete for research history. |
| bg_jobs/ | Generated scripts, logs, exit files | Operational evidence | May contain commands, stdout, credentials, and host paths. Bounded encrypted/redacted retention. |
| mcp_oauth/ | OAuth key/token files for MCP presets | Secret material | Backup only into encrypted secret backup; revoke/delete on MCP uninstall. |
| skills/ | Installed SKILL.md packages and usage file | User/plugin code and configuration | Supply-chain metadata, version/digest, owner/installation scope, quarantine on uninstall. |
| logs/ | app.log and search error log | Operational log | Redact secrets/content; rotate by size/time; exclude or encrypt in support bundles. |

## 8. Chroma and embedding data

### 8.1 Current client and collections

src/chroma_client.py uses an HTTP Chroma client:

- CHROMADB_HOST defaults to localhost;
- CHROMADB_PORT defaults to 8100;
- Docker reaches the Chroma service internally and persists it in the chromadb-data named volume;
- DATA_DIR/chroma is therefore not proof that the active vectors are backed up.

Current collection families:

| Domain | Collection family | Embedding lanes | Current ownership |
|---|---|---|---|
| Personal knowledge/RAG | odysseus_rag, odysseus_rag_custom, odysseus_rag_fastembed | Legacy unsuffixed plus custom endpoint and FastEmbed lanes | Chunk metadata includes owner and source/directory fields; query paths apply an owner filter. |
| Memories | odysseus_memories, odysseus_memories_custom, odysseus_memories_fastembed | Legacy unsuffixed plus custom endpoint and FastEmbed lanes | Current vector metadata records source=memory but not owner. Callers later filter JSON memories, which is not an adequate vector-store tenancy boundary. |

RAG IDs incorporate owner and text in the hash, and chunks are approximately 1,000 characters with overlap around 200. Lane separation protects against incompatible embedding dimensions/fingerprints.

Embedding choices are:

- local FastEmbed, default sentence-transformers/all-MiniLM-L6-v2, with FASTEMBED_CACHE_PATH;
- a custom OpenAI-compatible /v1/embeddings endpoint configured in embedding_endpoint.json or EMBEDDING_URL, EMBEDDING_MODEL, and EMBEDDING_API_KEY.

### 8.2 Required vector contract

The target vector record must contain:

- internal chunk or memory ID;
- tenant_id and owner_id;
- source artifact ID and source revision;
- embedding provider, model, dimensions, and normalized fingerprint;
- collection/lane version;
- content hash and tombstone/version;
- created, indexed, and deletion timestamps.

Vector writes must follow a transactional outbox from the canonical SQL record. Query filters must be enforced in the vector database before similarity results leave the store. Deleting or transferring an owner must enqueue verified deletion of every vector derivative. No ownerless memory vectors are permitted.

## 9. Browser and process-local state

The frontend uses localStorage for theme, layout, search scope, UI choices, and some preset-like state. Authentication cookies and browser caches are separate again. Active agent-run events, some notification queues, MCP process status, connection pools, and detached task state are process-local.

Implications:

- browser localStorage is not included in server backup, export, or account deletion;
- a different browser/device can produce different behaviour despite the same server state;
- restart persistence tests do not prove active run recovery;
- required product state must move to typed owner-scoped server records;
- purely cosmetic browser preferences may remain local but must be documented and resettable.

## 10. Ownership, retention, and deletion contract

### 10.1 Data classes

| Class | Examples | Default target treatment |
|---|---|---|
| Identity/security | Password hashes, auth sessions, API tokens, OAuth tokens, .app_key | Minimal retention; hash or encrypt; rotate/revoke; separate-key encrypted backup; immutable security audit without raw secret. |
| User-authored canonical | Chats, documents, notes, local events, memories, contacts, presets | Owner-scoped export/delete; user-configurable retention where appropriate; backups with tested restore. |
| Provider mirror | IMAP index/previews, CalDAV events, CardDAV cache | Connection-scoped; reconcile with provider; purge local mirror on disconnect unless user explicitly imports a copy. |
| Pending side effect | Scheduled email, webhook-triggered task, outbox action | Retain until terminal and verified; preserve minimal immutable receipt; expire sensitive payload separately. |
| Derivative AI/cache | Summaries, translations, classifications, vectors, TTS, search cache | Short TTL, quota, purge on source mutation/delete, rebuild rather than restore where practical. |
| Operational/audit | Task runs, provider health, action attempts, approvals, delivery receipts | Append-only/tamper-evident; redact payload; policy-defined retention and export. |
| Artifact | Uploads, attachments, generated images, editor payloads | Owner, content hash, MIME/size, encryption policy, reference count, quarantine, deletion and orphan sweep. |

No current unified retention scheduler implements this matrix. Retention values must be configuration with safe product defaults, not undocumented cleanup constants.

### 10.2 Required deletion semantics

1. A user deletion request freezes new work for that owner.
2. Active provider jobs/actions are cancelled or marked indeterminate.
3. OAuth/API sessions are revoked where supported before local credentials are removed.
4. Canonical SQL/JSON records are deleted or cryptographically erased in dependency order.
5. Provider mirrors, cache rows, files, Chroma vectors, browser tokens, MCP OAuth files, notification state, and background logs are removed.
6. Remote provider records are deleted only when the user requested remote deletion and an approval/verification record exists; disconnect alone must not delete remote mail/calendar/contact data.
7. Backups age out under a disclosed retention schedule. Deletion cannot honestly claim immediate erasure from immutable backups.
8. A minimal, non-content deletion receipt remains in the audit ledger.

Username rename is not an ownership primitive. Although current code migrates several owner strings and RAG metadata, the fragmented JSON, auxiliary database, file, and vector surfaces make a complete rename difficult to prove. Target ownership uses immutable user IDs; display name and login identifier can change independently.

## 11. Backup and restore coverage

scripts/odysseus-backup uses SQLite's backup API for discovered database files, copies other files into a gzip tar archive, and can verify archive structure. Its default source is the repository data directory.

### 11.1 Coverage matrix

| Surface | Current default snapshot | Recovery implication |
|---|---|---|
| app.db and scheduled_emails.db under repository data | Included using SQLite-safe copies | Useful, but schema version is not recorded. |
| Optional email_cache.db under repository data | Included if present | Legacy cache normally need not be restored once migration is complete. |
| JSON settings, identity, sessions, preferences | Included | Contains sensitive tokens and personal data. |
| .app_key | Included in the same gzip archive | Restores decryption, but defeats ciphertext/key separation if the archive is stolen. gzip is compression, not encryption. |
| Uploads, gallery, generated images, personal docs | Included when under data, subject to script filters | Verify the exact inclusion policy; comments and skip declarations are inconsistent for personal_uploads. |
| mail-attachments | Excluded unless include-attachments is passed | Expected for cache, but compose/pending-send attachments need a separate canonical rule. |
| deep_research | Excluded unless include-research is passed | Default restore loses research run history/artifacts. |
| ODYSSEUS_DATA_DIR outside repository data | Not selected by the script | Backup can silently snapshot the wrong directory. |
| ODYSSEUS_MAIL_ATTACHMENTS_DIR outside data | Not included | External attachment path is uncovered. |
| FASTEMBED_CACHE_PATH outside data | Not included | Acceptable only if declared rebuildable and model version is recorded. |
| Docker chromadb-data volume | Not included | Vector recovery requires a separate Chroma export/volume snapshot or deterministic rebuild. |
| SearXNG/ntfy volumes | Not included | Operational configuration/cache may be lost. Decide which is canonical. |
| Browser localStorage/cookies | Not included | UI preferences and browser sessions are not restored. |
| External provider records | Not included | Reconcile through provider APIs after restore. |
| SSH keys and model caches mounted into Docker | Not included | Correct for secrets/large caches only if separately managed and documented. |

### 11.2 Target backup contract

Every backup manifest must include:

- product and schema-migration version;
- source DATA_DIR and deployment ID;
- per-file size and SHA-256;
- consistent database checkpoint IDs;
- included/excluded data classes;
- Chroma collection version or rebuild watermark;
- encrypted secret-bundle reference, never a plaintext key in the same unprotected archive;
- provider reconciliation watermark;
- creation time, retention class, encryption/key ID, and restore compatibility range.

Restore must occur into a staging location, validate signatures/checksums and SQLite integrity, run versioned migrations transactionally, verify file/row ownership, rebuild derivatives, reconcile provider mirrors, and only then atomically promote the restored deployment. A destructive in-place restore is not a sufficient production procedure.

## 12. Target canonical data model

### 12.1 Common record rules

Every mutable domain record must have:

- immutable UUID primary key;
- tenant_id and owner_id, both non-null unless explicitly installation-scoped;
- created_at, updated_at, deleted_at, and row version;
- provenance: user, provider, agent action, import, or migration;
- classification and retention policy ID;
- optimistic-concurrency token;
- audit correlation ID.

Provider-originated resources additionally require connection_id, remote_id, remote_version/etag, sync state, last_seen_at, and a uniqueness constraint scoped to the connection.

### 12.2 New platform tables

| Target table/group | Responsibility |
|---|---|
| schema_migrations | Ordered migration ID, checksum, applied time, app version, success/failure and operator. |
| users, login_identities, roles, role_bindings | Replace auth.json and mutable username ownership. |
| auth_sessions, recovery_factors | Hashed bearer IDs, rotation, device and expiry metadata; no raw session token persistence. |
| installation_settings, user_preferences | Typed/versioned configuration separated by scope. |
| secrets, secret_versions, secret_bindings | Envelope-encrypted secret references, key ID, rotation and revocation; domain tables store references only. |
| provider_connections | Provider kind, owner, auth mode, capabilities, state, health, scopes, configuration version and secret bindings. |
| provider_resources, sync_cursors, sync_conflicts, provider_tombstones | Stable mapping between local and remote records, incremental sync and verified deletion. |
| artifacts, artifact_versions, artifact_references | Files/media with owner, hash, MIME, size, encryption, quarantine, storage backend and lifecycle. |
| knowledge_sources, knowledge_items, knowledge_chunks, embedding_jobs | Canonical source/revision and transactional derivative indexing. |
| agent_runs, run_events, action_intents, action_attempts | Durable orchestration and exact action lifecycle. |
| approvals, policy_decisions, verification_results | Immutable consequence review, authorization evidence and deterministic readback. |
| outbox, inbox_deliveries, idempotency_keys, replay_nonces | Crash-safe provider effects and webhook replay protection. |
| jobs, job_leases, job_logs | Durable scheduler/background work with cancellation and bounded redacted output. |
| audit_events | Append-only, correlated security/product audit with redacted structured payload. |
| retention_policies, deletion_jobs, export_jobs | Enforceable lifecycle, user export and deletion evidence. |

Existing domain tables can be evolved rather than replaced wholesale, but their owner, provider-ID, secret, and lifecycle fields must conform to these rules.

### 12.3 Repository and transaction contracts

Domain code and agents must not read JSON files, Chroma, or provider SDKs directly. Required interfaces:

- Repository methods accept ActorContext and enforce tenant/owner scope internally.
- UnitOfWork commits canonical rows plus outbox/audit events atomically.
- SecretBroker returns short-lived credentials to a provider adapter and never serializes them into model/tool output.
- ArtifactStore owns file commit, reference counting, quarantine, streaming, and deletion.
- VectorIndex consumes committed indexing jobs; it is never the source of truth.
- ProviderAdapter reads/writes remote resources using stable idempotency keys and returns normalized IDs/versions.
- RetentionService evaluates policy and records deletion jobs across every derivative store.

## 13. Staged migration plan

| Phase | Change | Verification gate |
|---|---|---|
| 0. Freeze and inventory | Add read-only store diagnostics, checksums, schema snapshot, owner/null counts, path manifest and backup coverage report | Repeated inventory is deterministic and contains no secret values. |
| 1. Version the schema | Introduce migration ledger and baseline the exact existing schema without rewriting data | Fresh install and every supported upgrade path end at the same checksum. |
| 2. Establish immutable ownership | Create user IDs/installation scope, map usernames, quarantine ambiguous null-owner rows | No route, query, cache, or vector lookup can return another owner's fixture. |
| 3. Centralize secrets/connections | Create provider_connections and secret references; import model, email, CalDAV, generic integration, MCP and vault credentials | Credential rotation/revocation tests pass; no raw secret remains in JSON, URLs, args, headers, or chat sessions. |
| 4. Collapse parallel sources | Migrate memory.json to canonical memories; integrations.json to provider connections; legacy email_cache into scoped cache tables | Dual-read comparison reports zero differences, then legacy writes are disabled. |
| 5. Split canonical and derivative data | Move scheduled effects to action/outbox tables; move email/search/TTS caches behind TTL cache repositories | Backup can omit caches without losing a pending action or user-authored record. |
| 6. Normalize provider resources | Replace global calendar UID and cache keys with connection-scoped internal IDs; create sync cursors/conflicts | Two users/accounts with identical remote IDs coexist; replay and conflict tests pass. |
| 7. Durable agent and jobs | Add run/action/approval/verification/jobs/audit records; remove process-only authority | Crash/restart resumes or reconciles exactly once; cancellation state is truthful. |
| 8. Reindex derivatives | Rebuild FTS and Chroma from canonical records with owner/provider/model fingerprints | Counts, owner filters, sampled hashes, and delete propagation pass. |
| 9. Backup/restore cutover | Manifested encrypted backups, external-volume coverage and staged restore | Full restore plus provider reconciliation passes on every supported platform. |
| 10. Retire legacy | Remove JSON/legacy DB readers, startup ALTER migrations, old keys and orphan files after rollback window | No production code opens retired paths; a rollback plan remains for the declared window. |

Migrations must be resumable and idempotent. Each phase requires a pre-migration encrypted backup, dry-run report, row/file/vector counts, quarantined-record report, and rollback boundary.

## 14. Release blockers and decisions

The following are data-layer release blockers for a fully working OM Automate system:

1. No versioned migration ledger or reproducible upgrade path.
2. Null/username ownership and globally keyed provider resources cannot prove tenant isolation.
3. Memory and integrations have parallel sources of truth.
4. Email canonical schedule data is mixed with disposable caches; email_boundaries is not owner/account scoped.
5. Chroma memory metadata is not owner-scoped, and Docker Chroma is absent from the bundled backup.
6. Secrets remain in plain JSON-capable fields, URLs, headers, command arguments, and path-embedded webhook tokens.
7. Active agent runs/actions/approvals/verifications are not durable.
8. Backup tooling can select the wrong data root, includes .app_key in an unencrypted archive, and omits external paths/volumes.
9. There is no unified retention, export, account deletion, cache purge, or provider disconnect service.
10. Native secret-bearing files were observed with permissions broader than 0600.

Required product decisions before implementation:

- single-user-only versus real multi-tenant support;
- supported database backend for the first release;
- local OS keychain, deployment KMS, or passphrase-encrypted secret bundle;
- default retention periods by data class;
- whether remote provider disconnect preserves or imports local mirrors;
- whether vector derivatives are backed up or always rebuilt;
- maximum artifact/editor/chat sizes and quotas;
- backup encryption, key custody, and immutable-backup deletion policy.
