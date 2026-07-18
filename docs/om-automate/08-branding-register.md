# OM Automate Branding Register

## Document status

- **Status:** baseline inventory and migration plan; it does not claim that rebranding is complete.
- **Audit date:** 2026-07-18.
- **Audited source:** upstream `main` commit `9844a2f9a1996b8c8135a9e7bbde6a72f41df5ed`, working branch `om-automate/main`.
- **Canonical product name:** **OM Automate**.
- **Canonical assistant name:** **OM**.
- **Canonical positioning:** **Your private AI operating system**.
- **Legal rule:** product branding may change; copyright, licence, source-offer and factual provenance notices must not be removed. See `docs/om-automate/licence-and-attribution-review.md`.

## Classification rules

Every match must receive one of these classifications before it is changed:

| Classification | Meaning | Default treatment |
|---|---|---|
| Visible product branding | Text or imagery a user sees as the application/assistant identity | Replace with canonical OM Automate/OM branding |
| Internal technical identifier | Private symbol, CSS class, log label or implementation detail with no persistence/protocol contract | Rename incrementally where useful; not a launch blocker if truly invisible |
| Legal attribution | Licence, copyright, provenance, acknowledgement or source history | Retain factually; present through a dedicated Legal/Source surface |
| Compatibility-sensitive identifier | Environment variable, cookie, header, URL, CLI, package, service, cache key or integration contract | Introduce new name and read the old name as a deprecated alias |
| Database-sensitive identifier | Database column/value, vector collection, file path or persisted browser key | Migrate/dual-read/dual-write; never blind replace |
| External integration identifier | Published plugin/skill name, archive, header, user agent or external configuration key | Version and migrate with a documented compatibility window |
| Third-party identifier | Provider/project name or logo not owned by OM Automate | Keep only for accurate interoperability; review the owner's brand terms |

## Reproducible scan baseline

The baseline scan searched tracked files for product-name case variants and Greek/Odyssey terms:

```bash
git grep -Il -E '(Odysseus|odysseus|ODYSSEUS|Ithaca|Penelope|Telemachus|Ulysses|Homer|Greek|Odyssey)'
git grep -InE '(Odysseus|odysseus|ODYSSEUS|Ithaca|Penelope|Telemachus|Ulysses|Homer|Greek|Odyssey)' -- . \
  ':(exclude)static/lib/*.min.js' ':(exclude)package-lock.json'
```

At the audited commit this returns **316 tracked files**. The second command returns **2,128 matching lines** after excluding minified frontend bundles and `package-lock.json`. The file distribution is:

| Area | Matching files | Primary concern |
|---|---:|---|
| `tests/` | 108 | Expected assertion updates plus new prohibited-brand tests |
| `static/` | 52 | Visible UI, metadata, browser storage/events and assets |
| `src/` | 38 | Agent persona, protocol labels, persisted collections and internal symbols |
| `scripts/` | 34 | CLI names, help, caches, backup names and completions |
| repository root | 25 | README, packaging, Compose, services and build metadata |
| `routes/` | 17 | Downloads, headers, email markers, notifications and errors |
| `.github/` | 9 | Image/release workflows, templates and repository links |
| `integrations/` | 7 | Codex/Claude plugins, skills, scripts and environment variables |
| `docs/` | 6 | Wordmark, screenshots and user documentation |
| `core/` | 5 | environment/header names, session cookie and internal probes |
| `services/` | 4 | service prompts, paths and logging |
| `docker/` | 4 | runtime user, image/build/setup identifiers |
| `companion/` | 3 | pairing/product names and integration settings |
| `mcp_servers/` | 2 | email/reminder headers and subjects |
| `specs/` | 1 | packaging metadata |
| `licenses/` | 1 | legal attribution; retain |

This scan is a baseline, not the final inventory. The implementation must also inspect binary/image assets, browser rendering, generated output, database values, Docker/image labels and external plugin archives. Matches inside legal notices are expected exceptions; visible UI exceptions are not.

## Finding register

### BR-001 — visible UI and metadata still identify Odysseus

- **Severity:** High for product acceptance.
- **Classification:** visible product branding.
- **Evidence:** PWA name and description are in `static/manifest.json:2-4`; login title/logo are in `static/login.html:6` and `static/login.html:256`; main title and route titles are in `static/index.html:5` and `static/index.html:159-177`; sidebar and accessible heading are in `static/index.html:709` and `static/index.html:955`; chat metadata, welcome identity and prompt are in `static/index.html:958-1016`; settings labels retain the old product at `static/index.html:1728`, `static/index.html:2041` and `static/index.html:2299`. Default session/prompt copy remains in `static/app.js:532` and `static/app.js:2318`; rendered assistant roles remain in `static/js/chatRenderer.js:2002` and `static/js/chatRenderer.js:2448`. Tours and generated chat roles contain visible references throughout `static/js/slashCommands.js`, including `static/js/slashCommands.js:2468-2537`, `static/js/slashCommands.js:308-658` and `static/js/slashCommands.js:3484-4381`. The authenticator-app issuer is still the old name at `core/auth.py:506-509`.
- **Required change:** render product/assistant/positioning through central brand configuration; replace every title, navigation label, login/setup/loading/empty/error string, generated email/notification label, API documentation label and accessibility string. Use **OM Automate** for the product and **OM** only for the conversational assistant.
- **Acceptance:** browser tests across login, setup, dashboard, every route, error states, offline/PWA mode and generated notifications find no prohibited visible match outside the Legal/Source page.

### BR-002 — old sailboat artwork, icons and screenshots remain

- **Severity:** High for product acceptance.
- **Classification:** visible product branding/assets.
- **Evidence:** `docs/odysseus-wordmark.png` is the old sailboat wordmark; `static/icons/icon-192.png`, `static/icons/icon-512.png`, `static/icons/icon-maskable-512.png` and `static/icon.ico` carry the old icon; inline sailboat SVGs remain in `static/login.html:256` and `static/index.html:960`; `docs/odysseus.jpg` and `docs/odysseus-browser.jpg` show the old-branded interface. These assets were visually inspected during the audit.
- **Required change:** create a legally cleared OM Automate logo/icon set with source artwork, square/maskable/PWA/favicon/native variants, light/dark contrast and accessible text alternatives. Replace or regenerate screenshots only after the UI is complete. Do not retain old marks in splash, installer, tray, app switcher, share cards or documentation thumbnails.
- **Acceptance:** image-diff/manual review verifies all shipped sizes and platform packages; a binary hash/asset allowlist prevents an old asset from being reintroduced.

### BR-003 — the default persona and examples are explicitly Homeric

- **Severity:** High because this changes assistant behaviour, not only appearance.
- **Classification:** visible product branding and default agent identity.
- **Evidence:** `static/js/presets.js:65-70` defines an Odysseus, king-of-Ithaca strategist persona. `static/js/research/panel.js:13` uses the ten-year Odyssey as the default example. `static/js/slashCommands.js:5261-5414` includes Odyssey quotations, a Homer attribution and old assistant roles; the hidden `/odyssey` command is registered at `static/js/slashCommands.js:6143`. Agent system/minimal prompts repeatedly identify the assistant as Odysseus, for example `src/agent_loop.py:1250-1389`.
- **Required change:** define one neutral OM executive-companion persona, focused on private, reliable, consent-based assistance. Replace examples with ordinary calendar/email/task/knowledge workflows. Remove the mythic quote command and Greek identity unless deliberately retained as an optional, clearly separate user-selectable character that does not become product branding.
- **Acceptance:** prompt snapshots and model-facing request tests prove the default system identity is OM; no user content, preset or hidden command silently reintroduces the old persona.

### BR-004 — persistent and protocol identifiers cannot be globally replaced

- **Severity:** High migration risk.
- **Classification:** compatibility-sensitive and database-sensitive identifiers.
- **Evidence:** old environment names are exposed in `.env.example:64-186`, `docker-compose.yml:37-57`, `app.py:229` and `app.py:1057-1185`; the session cookie is `odysseus_session` (`routes/auth_routes.py:84`); internal headers include `X-Odysseus-Internal-Token` and `X-Odysseus-Owner` (`app.py:141-142`; `core/middleware.py:16-17`); generated API tokens use the `ody_` prefix (`app.py:407-410`; `routes/api_token_routes.py:130`). Browser storage and events use many `odysseus-*`/`odysseus:*` names, including `static/login.html:26`, `static/app.js:1481`, `static/app.js:1810`, `static/app.js:2601` and `static/app.js:3332`. The service-worker cache is `odysseus-v344` (`static/sw.js:10`). Chroma collections are `odysseus_memories` and `odysseus_rag` (`src/memory_vector.py:28`; `src/rag_vector.py:40`; also `scripts/migrate_faiss_to_chroma.py:8-9`). A tuned-model compatibility check uses `odysseus-qwen3` (`src/agent_loop.py:2609`).
- **Required change:** use the migration matrix below. New versions write canonical identifiers and read legacy aliases for a documented window. Persisted data must be copied or dual-read before legacy identifiers are retired. Never change a token prefix, collection, cookie or event in place without migration tests.
- **Acceptance:** an upgraded copy of baseline data retains login, sessions where intentionally supported, themes/preferences, memories, RAG results, scheduled work, integrations and external API clients; a fresh installation writes only new canonical identifiers.

### BR-005 — packaging, services, Docker and CLIs expose the old package name

- **Severity:** Medium, High for release/install acceptance.
- **Classification:** visible packaging and compatibility-sensitive identifiers.
- **Evidence:** native bundles are named in `Odysseus.spec:24` and `Odysseus.spec:44`; the launcher splash, tray and window labels retain the old identity (`launcher.py:42-104`); first-run terminal copy does too (`setup.py:2` and `setup.py:240`). Systemd uses `odysseus-ui.service:1-15`; `package.json:4` points to an old repository URL; Compose and Docker use the old service/user/path/image vocabulary; more than twenty `scripts/odysseus-*` commands and both completion files expose the name (`scripts/_completion/odysseus.zsh:1-66`; `scripts/_completion/odysseus.bash:1-91`). Backup/log/cache names also retain it, such as `scripts/odysseus-logs:1-33` and `docs/backup-restore.md:3-24`.
- **Required change:** publish `om-automate`/`om-automate-*` entry points, native display name, package/app identifiers, system service and documented image name. Keep forwarding wrappers for old CLI/service names during the compatibility window; wrappers must emit a non-secret deprecation message. Do not rename an existing volume or data directory until the installer detects, backs up and migrates it.
- **Acceptance:** fresh one-click installs expose only OM Automate labels; upgrade tests prove old commands/configuration still resolve or fail with an actionable migration message rather than data loss.

### BR-006 — Codex, Claude and companion integrations publish the old contract

- **Severity:** Medium.
- **Classification:** external integration identifier.
- **Evidence:** Codex and Claude skills are under `integrations/*/skills/odysseus/`; their `SKILL.md` files require `ODYSSEUS_URL` and `ODYSSEUS_API_TOKEN` (`integrations/codex/skills/odysseus/SKILL.md:3-15`; `integrations/claude/skills/odysseus/SKILL.md:3-15`). Helper scripts read those values (`integrations/codex/scripts/odysseus_api.py:39-45` and the Claude copy). Downloaded archives are named by `routes/codex_routes.py:231` and `routes/codex_routes.py:907`. Companion pairing/configuration and plugin manifests also retain the old product identity.
- **Required change:** version and publish OM Automate plugin/skill manifests, directories, helpers, archive names and documentation. Read `OM_AUTOMATE_URL`/`OM_AUTOMATE_API_TOKEN` first and legacy variables second. Keep server endpoints compatible or publish a versioned API migration; do not leak the old name in new install instructions.
- **Acceptance:** both clean installation and in-place upgrade are tested in Codex/Claude/companion clients; old environment variables work only as documented deprecated aliases.

### BR-007 — generated messages and historical markers need dual recognition

- **Severity:** High migration risk for reminders/email cleanup.
- **Classification:** visible branding plus database/external compatibility identifiers.
- **Evidence:** old names appear in ntfy/email connectivity messages (`routes/auth_routes.py:750-807`), outbound webhook headers and user agent (`src/webhook_manager.py:418-426`) and demo email headers (`scripts/demo_email/seed_demo_emails.py:41`). Email creation writes `X-Odysseus-Origin`, `X-Odysseus-Kind` and `X-Odysseus-Ref` (`routes/email_routes.py:956-960`); reminder lookup depends on the old header/subject (`routes/email_routes.py:1475-1480` and `routes/email_routes.py:3117-3160`); generated mail uses the `odysseus.local` Message-ID domain (`routes/email_routes.py:3794`). Persisted email rows use `odysseus_kind` (`mcp_servers/email_server.py:1165-1172`).
- **Required change:** all newly generated copy must use OM Automate/OM and new headers. Search, deduplication, update and delete code must continue recognising old headers, kinds, subjects and IDs. Prefer an unbranded versioned machine header for future stability, for example `X-OM-Automate-Schema: 1`, while retaining old-reader fallbacks.
- **Acceptance:** upgrade fixtures containing historical reminders/messages can still be located, updated, deduplicated and deleted; new messages contain no visible old brand.

### BR-008 — legal attribution must remain separate from product branding

- **Severity:** High legal/compliance risk.
- **Classification:** legal attribution.
- **Evidence:** `LICENSE`, `ACKNOWLEDGMENTS.md`, source history, adapted-code notices and repository provenance factually refer to Odysseus. AGPL section 5 requires prominent modification/date notices for conveyed modified source (`LICENSE:77-86`), and section 13 can require a source offer for remote users (`LICENSE:186-190`).
- **Required change:** retain accurate licence/copyright/acknowledgement/provenance references and add the OM Automate modification notice recommended in `licence-and-attribution-review.md`. Put them behind an accessible Legal/Source item; do not use them as the product identity in navigation, but do not conceal or rewrite history.
- **Acceptance:** the prohibited-brand UI scanner permits old-name text only in an explicit legal allowlist; manual review verifies the Legal/Source page remains prominent and accurate.

### BR-009 — third-party names and logos need separate rights review

- **Severity:** Medium.
- **Classification:** third-party identifier/trademark.
- **Evidence:** provider assets include `static/icons/ollama-mark.png`, `static/icons/ollama-mark-crop.png`, `static/icons/sglang-logo.png` and `static/icons/sglang-mark.png`; provider/project names occur throughout settings and integrations.
- **Required change:** do not global-replace provider names. Use them only to describe compatible integrations, preserve required attribution, review current brand guidelines and remove a logo when rights are unclear. Do not imply sponsorship or endorsement.
- **Acceptance:** a documented asset provenance/licence/trademark record exists for every shipped third-party mark.

## Compatibility migration matrix

| Legacy identifier | Canonical identifier | Migration rule | Retirement condition |
|---|---|---|---|
| `ODYSSEUS_*` | `OM_AUTOMATE_*` | Read new first, then old; warn on old; examples write new only | At least one documented major-version window and telemetry-free local migration report |
| `odysseus_session` | `om_automate_session` | Accept both; issue new cookie after successful old-cookie validation; delete both on logout | Maximum old session TTL has elapsed after migration release |
| `X-Odysseus-Internal-Token` / `X-Odysseus-Owner` | `X-OM-Automate-Internal-Token` / `X-OM-Automate-Owner` | Server accepts both only on the existing trusted-loopback path; clients send new | All bundled clients and integrations have migrated |
| `ody_` API-token prefix | `oma_` or an unbranded versioned prefix | Prefer keeping legacy tokens valid until explicit rotation; validator recognises both; new token issuance uses chosen canonical prefix | User/admin has rotated or revoked every old token |
| `odysseus-*` localStorage | `om-automate-*` | One-time copy with schema/version marker; validate value; new key wins; optionally remove old after success | Browser migration test and rollback window complete |
| `odysseus:*` custom events/global names | `om-automate:*` | Dispatch/listen to both during one frontend compatibility cycle; stop creating old public globals | All bundled modules and plugin consumers migrated |
| `odysseus-v344` PWA cache | versioned `om-automate-v*` | New service worker explicitly deletes all known legacy cache names on activate | Installed PWA update test passes offline and online |
| `odysseus_memories` | `om_automate_memories` | Idempotently copy with stable IDs/checksum, dual-read during cutover, never re-embed silently | Counts/content/query parity and backup/rollback verified |
| `odysseus_rag` | `om_automate_rag` | Same copy/dual-read/parity process; preserve source metadata | RAG parity and rollback verified |
| `odysseus_kind`, old email headers/subjects/Message-ID domain | New neutral/versioned schema fields and OM headers | Dual-read and, where necessary, dual-write; retain legacy search forever for historical mail | May remain as a permanent compatibility reader |
| `odysseus-qwen3` model prefix | Existing prefix plus future OM metadata | Preserve recognition for existing tuned models; prefer explicit model capability metadata over a product-name prefix | All supported model manifests carry capability metadata |
| `scripts/odysseus-*` / `odysseus-ui.service` | `om-automate-*` / `om-automate.service` | Add canonical commands/service; old wrappers forward safely; installer detects old unit | Upgrade adoption documented and old unit disabled without deleting data |
| old data/cache/tmp/backup paths | OM Automate paths | Discover, back up, lock and atomically migrate; fall back to old data if new absent; never create a second empty profile silently | Restore, rollback and cross-platform upgrade tests pass |
| old plugin/skill/archive names | OM Automate names | Publish new version; keep server download alias and old env support | Bundled/external client compatibility window ends |

The exact API-token prefix and HTTP-header spelling must be fixed in an ADR before implementation. Once published, machine identifiers should be unbranded or versioned so a future visual rebrand does not require another data migration.

## Central brand configuration requirement

Create one typed, server-owned source of truth that exposes only non-sensitive branding to the frontend. At minimum it must define:

- product name: `OM Automate`;
- assistant name: `OM`;
- positioning: `Your private AI operating system`;
- logo and icon asset references, including light/dark/maskable variants;
- browser/PWA title templates;
- navigation labels;
- welcome, empty-state and default persona copy;
- support, documentation, source and legal links;
- native package display labels;
- theme tokens and accessible alternative text.

Templates/components consume this object rather than repeating literals. Machine identifiers, database schema names and security protocol constants must live in separate compatibility modules and must not be derived dynamically from the display name.

## Implementation sequence

1. Approve the new logo/icon and create the central brand configuration plus Legal/Source link.
2. Replace visible text, system persona and generated messages without changing persisted identifiers.
3. Replace images, screenshots, manifest/native metadata and packaging display labels.
4. Introduce canonical compatibility aliases and idempotent data/browser/PWA migrations.
5. Publish versioned integration/CLI/service names and forwarding aliases.
6. Update tests/docs and run the prohibited-brand scan against rendered/generated output.
7. Remove legacy writers only after upgrade evidence; retain necessary legacy readers.

## Verification plan

### Automated static checks

- Run the baseline grep on every change. Every remaining match must be classified in this register or an attached generated inventory.
- Fail CI when a prohibited name appears in non-allowlisted HTML, JavaScript user copy, email/notification templates, manifest, packaging metadata, API descriptions or new asset filenames.
- Scan binary assets using an approved hash list and OCR the login/dashboard/screenshots.
- Verify legal files are present and unchanged except for reviewed additive modification/source notices.

### Runtime/browser checks

- Login, first-run setup, every primary route, loading/offline/error/empty states, admin settings and accessibility tree.
- Browser title, route metadata, favicon, installable PWA name/icons, home-screen/launcher/tray labels and service-worker upgrade.
- New chat/default persona, tool confirmations, emails, reminders, ntfy, webhooks, exports, downloads and generated filenames.
- Fresh profile and upgraded profile with old cookie, localStorage, PWA cache, database, vector collections and integration settings.
- Codex, Claude, companion, CLI, systemd, Docker and native package flows.

### Acceptance criteria

- Visible product surfaces say **OM Automate**; the conversational assistant is **OM**; positioning uses **Your private AI operating system** where specified.
- No old sailboat/logo or Greek persona remains in ordinary product surfaces.
- No existing user data, memory/RAG content, integration, automation, session migration or external client is silently lost.
- Old names remain visible only where they are factual legal attribution, an explicit migration/deprecation message or user-owned historical content.
- Legal attribution and exact-version source access remain prominent and functional.

## Open decisions requiring an ADR

- Final logo/icon ownership and asset licence.
- Stable application/package/bundle identifiers on macOS, Windows and Linux.
- Canonical unbranded/versioned API token prefix and public machine-header namespace.
- Compatibility-window duration and whether selected legacy readers remain permanent.
- Data-directory/volume migration strategy for each supported installer.
- Repository/image/package publication names and source URL.
- Whether the old mythic persona survives as a separately named optional preset; it must not be the default or imply ownership of upstream marks.
