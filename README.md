<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="static/brand/om-wordmark-light.svg">
    <img src="static/brand/om-wordmark-dark.svg" alt="OM Automate" width="300">
  </picture>
</p>

<p align="center"><strong>Your private AI operating system.</strong></p>

<p align="center">
  A local-first workspace for private chat, daily planning, governed AI actions,
  personal work, email, calendar, meetings, documents, knowledge, and automation.
</p>

# OM Automate

OM Automate is a self-hosted Personal Private OS. It brings conversations,
tasks, projects, commitments, calendar, email, meetings, private knowledge,
documents, routines, and local AI models into one owner-scoped application.

The system is designed around three rules:

1. Private data stays under the operator's control.
2. Consequential AI actions require an explicit, reviewable approval.
3. Answers and completed actions should expose sources, verification, and
   uncertainty instead of silently claiming success.

## Current Release Status

The complete five-phase Personal Private OS implementation is available in this
working tree and has been verified on an Apple Silicon Mac. The Python suite has
4,970 passing tests; the socket-enabled follow-up gate also passes. Encrypted
backup and fresh-directory restore have been rehearsed against the current data
layout.

This is still a release candidate, not a signed public distribution. The
following acceptance work remains open:

- seven consecutive days of real personal-use soak evidence;
- a clean, tagged, reproducible release checkout;
- signed and notarized native artifacts;
- physical iPhone Safari and live provider acceptance;
- complete Windows/Linux clean-machine qualification;
- closure of the remaining security, migration, and licence items recorded in
  the project documentation.

For the exact status, read
[Personal Private OS status](docs/om-automate/00-project-status.md) and the
[five-phase plan](docs/om-automate/17-privateos-phased-plan.md).

## Feature Summary

- Private chat with local or hosted models, streaming, attachments, search,
  voice input, personas, session history, exports, and a true incognito mode.
- A governed agent runtime with typed tools, risk levels, exact approvals,
  cancellation, audit history, reversal metadata, and result verification.
- A Today workspace combining schedule, priority work, commitments, important
  messages, approvals, reminders, meeting actions, and service health.
- Projects, milestones, tasks, dependencies, commitments, reminders, focus
  planning, provenance, activity history, and operating metrics.
- Gmail and Google Calendar adapters plus IMAP/SMTP email, CalDAV calendars,
  local calendars, contacts, drafts, scheduling, and read-back verification.
- Private Knowledge with ingestion, grounded search, citations, memories,
  sensitivity controls, expiry, source lifecycle, and derivative deletion.
- A Document Vault with reviewable classification, expiry extraction,
  obligation evidence, source-backed answers, and revision-safe corrections.
- Meeting recording/upload, consent controls, durable transcription jobs,
  transcript revisions, speaker mapping, summaries, decisions, risks, questions,
  action extraction, and promotion into Work or Knowledge.
- Durable automations with schedules and events, bounded action definitions,
  retries, approval checkpoints, dead letters, history, and six routine templates.
- Privacy settings, local-only model routing, retention, owner export/delete
  workflows, sensitive-data redaction, telemetry off by default, and integration
  controls.
- Authenticated-encrypted portable backup, SQLite preflight, restart-safe
  restore, rollback, and fresh-install recovery rehearsal.
- A responsive companion for Today, chat, read-only approvals, and reminders.

## Choose an Installation Path

| Path | Best for | Default URL | Current evidence |
| --- | --- | --- | --- |
| Apple Silicon native | Local models using Apple Metal; current reference system | `http://127.0.0.1:7860` | Verified current profile |
| Docker on macOS/Linux | Reproducible service stack and simpler dependencies | `http://127.0.0.1:7000` | Compose/configuration verified; runtime qualification varies by host |
| Docker Desktop on Windows | Windows evaluation | `http://127.0.0.1:7000` | Launcher exists; clean Windows acceptance remains open |
| Manual Python | Development and diagnostics | Operator-selected | Developer path, not the preferred end-user install |

Docker on an Apple Silicon Mac cannot use Metal acceleration. Use the native
path when local model performance on an M-series Mac matters.

## Before You Install

You need an approved source checkout or release archive. A public release URL
and signed tag have not yet been assigned. When one exists, replace the
placeholders below with the published repository and tag:

```bash
git clone <[OM_AUTOMATE_RELEASE_URL](https://github.com/OriginMediaIE/Alfred)> om-automate
cd om-automate
```

Do not install from an arbitrary branch when protecting real personal data.
Record the exact commit, retain a verified encrypted backup, and inspect release
notes before upgrading.

For a beginner-friendly GitHub install walkthrough, see
[Beginner Guide: Install And Use OM Automate From GitHub](docs/github-install-and-use.md).

Minimum practical requirements:

- 64-bit macOS, Linux, or Windows host;
- enough free disk for the app, data, backups, and any local models;
- Python 3.11 or newer for native installation;
- Docker Engine/Desktop with Compose v2 for Docker installation;
- a modern browser;
- at least one local or hosted LLM endpoint for AI features.

The core application can run without a local GPU. Model speed, memory use, and
disk requirements depend on the selected model and serving runtime.

## Install on Apple Silicon macOS

This is the most thoroughly exercised profile and the recommended route for an
M-series Mac.

### 1. Install Homebrew

Check whether Homebrew exists:

```bash
brew --version
```

If it is missing, install it from [brew.sh](https://brew.sh), then open a new
Terminal window. The launcher uses Homebrew for an arm64 Python and optional
local-model helpers.

### 2. Enter the project directory

```bash
cd /path/to/om-automate
chmod +x start-macos.sh install-om-automate.sh install-om-automate.command
```

### 3. Start the native stack

```bash
./start-macos.sh
```

On its first run, the launcher:

- verifies that the interpreter is native arm64 rather than Rosetta Python;
- creates `venv/` and installs `requirements-om.lock`;
- creates a private `.env` when one does not exist;
- initializes private data directories and SQLite databases;
- creates the first administrator account;
- starts a local ChromaDB when its CLI is available;
- optionally starts local model helpers installed on the Mac;
- starts Uvicorn and opens the application in the default browser.

The normal fresh-install URL is:

```text
http://127.0.0.1:7860
```

If `.env` already defines `APP_PORT`, that configured port wins. This checkout
may already use port `7000`.

### 4. Create or retrieve the administrator account

When setup is interactive, it asks for an administrator username and a password
of at least the configured minimum length. In non-interactive setup, it may print
a temporary password once. Keep the terminal output private and change a
temporary password immediately under **Settings -> Account**.

If `data/auth.json` already exists, setup preserves it and does not create a new
administrator. Restore a known-good backup if the auth store is corrupt; never
delete an existing auth store merely to reopen first-run setup.

### 5. Stop and restart

Keep the Terminal process running while using the app. Press `Ctrl+C` in that
Terminal to stop the application and the helper processes started by the script.

Restart later with:

```bash
./start-macos.sh
```

The command is idempotent and preserves `.env`, `data/`, accounts, integrations,
and application state.

### 6. Build the native macOS app

After the native setup has completed once, package OM Automate as a normal
macOS application:

```bash
./build-macos-app.sh
```

This creates `dist/OM Automate.app` and `dist/OM Automate.dmg`. The application
uses Apple's AppKit and WKWebView frameworks, so the Private OS runs in its own
native window and does not require Chrome or another browser. Opening the app
starts the local Python, ChromaDB, and model services through `start-macos.sh`;
quitting stops the service process started by that app session.

The app is tied to the current project directory while private data, models,
and Python packages remain outside the bundle. Rebuild it after moving the
project folder. The local service continues to bind to `127.0.0.1` by default.

### Internal Apple Silicon test installer

Build the self-contained internal test DMG on an Apple Silicon Mac with Xcode
Command Line Tools installed:

```bash
./scripts/build-internal-macos-test-installer.sh
```

The command creates `dist/OM Automate Internal Test.dmg`. The tester opens the
DMG and double-clicks `Install OM Automate.command`; it installs the sanitized
runtime under `~/Library/Application Support/OM Automate`, creates
`~/Applications/OM Automate.app`, and opens it. Existing application data,
models, account state, `.env`, and the Python environment are preserved when the
installer is run again.

This internal-only build seeds `Admin` / `Admin` on an empty installation and
opens Cookbook after the first login. The weak default is gated by
`OM_AUTOMATE_INTERNAL_TEST_DEFAULTS=1` and is not accepted by normal setup,
signup, password-change, or public build flows. Change it in **Settings >
Account** after testing. The DMG is ad-hoc signed, not Apple-notarized, and is
intended only for trusted internal distribution.

## Install with Docker on macOS or Linux

Docker starts OM Automate together with ChromaDB, SearXNG, and ntfy. All
published ports bind to loopback by default.

### 1. Install and start Docker

Install Docker Desktop on macOS or Docker Engine with Compose v2 on Linux.
Verify both the CLI and daemon:

```bash
docker compose version
docker info
```

### 2. Run the non-destructive preflight

From the project directory:

```bash
./install-om-automate.sh --check
```

This validates Docker, Compose, the selected accelerator, data paths, port
configuration, and network-binding safety without building or starting anything.

### 3. Build and start

```bash
./install-om-automate.sh
```

The installer creates `.env` only when absent, preserves existing data, builds
the local image, waits for `/api/ready`, and opens:

```text
http://127.0.0.1:7000
```

Useful options:

```bash
./install-om-automate.sh --no-open
./install-om-automate.sh --no-build
./install-om-automate.sh --accelerator nvidia
./install-om-automate.sh --accelerator amd
./install-om-automate.sh --timeout 480
```

Use an accelerator option only after the corresponding host driver and
container runtime work. CPU is the default.

### 4. Read the first-login credentials

Docker setup writes the temporary credential to the application log when no
administrator exists:

```bash
docker compose logs odysseus
```

Sign in, change the temporary password, configure two-factor authentication,
and store the recovery codes securely.

### 5. Operate the Docker stack

```bash
docker compose ps
docker compose logs --tail=200 odysseus
docker compose restart odysseus
docker compose stop
docker compose up -d
```

Do not run `docker compose down -v` unless you explicitly intend to delete named
service volumes. Application data in `APP_DATA_DIR` and external Chroma data
must both be covered by the operator's recovery plan.

## Install on Windows with Docker Desktop

Install Docker Desktop, enable Compose v2, obtain an approved source checkout,
and open PowerShell in the project directory.

Run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install-om-automate.ps1
```

Alternatively, double-click `install-om-automate.cmd`. To use an image that was
already built:

```powershell
.\install-om-automate.ps1 -NoBuild
```

Open `http://127.0.0.1:7000` after readiness succeeds. Retrieve an initial
temporary password with:

```powershell
docker compose logs odysseus
```

The Windows launcher exists and is statically tested, but a clean Windows
installation is not yet a supported release claim. Use test data until that
qualification is complete.

## Manual Native Installation

Use this route for development or when diagnosing the launcher.

```bash
cd /path/to/om-automate
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-om.lock
python setup.py
python -m uvicorn app:app --host 127.0.0.1 --port 7000
```

On Windows PowerShell, activate with:

```powershell
.\venv\Scripts\Activate.ps1
```

Then use `python` for the remaining commands. Native optional features may also
need `tmux`, media tools, a model runtime, or provider-specific dependencies.

## Core Configuration

The installers copy `.env.example` to `.env` without overwriting an existing
file. Keep `.env` private and never commit it.

| Setting | Purpose | Safe default |
| --- | --- | --- |
| `AUTH_ENABLED` | Require login | `true` |
| `APP_BIND` | Web bind address | `127.0.0.1` |
| `APP_PORT` | Published application port | Docker `7000`; native launcher `7860` unless overridden |
| `APP_DATA_DIR` | Docker host data directory | `./data` |
| `ODYSSEUS_DATA_DIR` | Native compatibility data path | repository `data/` when unset |
| `DATABASE_URL` | Main database URL | SQLite inside the data directory |
| `LOCALHOST_BYPASS` | Trusted direct-loopback bypass | `false` |
| `SECURE_COOKIES` | HTTPS-only session cookies | enable for HTTPS network access |
| `ALLOWED_ORIGINS` | Exact browser origins allowed by CORS | loopback origins only |
| `CHROMADB_HOST` / `CHROMADB_PORT` | Vector service location | native `localhost:8100` |
| `OLLAMA_BASE_URL` | Optional Ollama/OpenAI-compatible endpoint | unset until configured |

Changing `APP_BIND` to `0.0.0.0` makes the app reachable from other devices.
Do this only with authentication enabled, localhost bypass disabled, exact
origins, HTTPS or a trusted private access layer, and firewall rules. Never
publish the application, ChromaDB, SearXNG, ntfy, model, or database ports
directly to the public internet.

## First-Run Checklist

After signing in:

1. Change any temporary administrator password.
2. Enable two-factor authentication and save recovery codes offline.
3. Confirm **Settings -> Privacy** has the intended local-only, retention,
   redaction, telemetry, and provider-routing settings.
4. Add or discover at least one model endpoint.
5. Create a harmless chat and verify a response.
6. Review **Approval Centre** before enabling effectful agent tools.
7. Configure only the integrations you plan to use.
8. Create and preflight an encrypted `.ombak` backup.
9. Check `/api/health` and `/api/ready`.
10. Keep the app on loopback until network access is intentionally secured.

## Configure an AI Model

OM Automate can use local Ollama/OpenAI-compatible servers and supported hosted
providers. Open **Settings -> Models** to add an endpoint, test it, discover
models, and select the model used by a chat.

For Ollama running on the same native host, use its local endpoint. For Ollama
running on the Docker host while OM Automate runs in Docker, use:

```text
http://host.docker.internal:11434/v1
```

The host Ollama service must accept connections from Docker. API keys should be
entered through the protected settings flow or secret store, never hard-coded
into prompts, documents, scripts, or source files.

Model capability matters. Models without a qualified structured-tool channel
remain chat-only. Agent mode should be used with a capability-tested model and
with the smallest necessary tool set.

## Functionality

### Chat and Personal Assistant

The central chat workspace supports persistent conversations, streaming,
stop/reconnect, model selection, attachments, web/research context, personas,
exports, voice input, and session organization. Incognito chats use request-local
history and disable durable message, memory, research, image, and session saves.

Chat can remain conversational or enter Agent mode. Agent mode uses the same
conversation but can propose typed tool calls. Ordinary model prose is not an
executable instruction.

### Governed Actions and Approval Centre

Built-in tools are described by a canonical registry with permissions, risk,
confirmation, timeout, idempotency, reversal, and verification metadata.
Consequential operations create an exact action proposal. Approval Centre shows
the operation and arguments before execution, records the decision, and retains
the resulting audit and verification state.

Examples include email send, calendar mutation, file changes, shell/Python,
external integration calls, and approved Work changes. A user can reject,
cancel, or edit an eligible proposal instead of granting broad autonomy.

### Today and Briefings

Today combines local Core health, schedule, important messages, priority and
overdue work, commitments, approvals, meeting actions, and reminders. Missing or
degraded providers are shown as unavailable rather than silently omitted.

Morning, evening, and weekly briefings retain source references. Generated
briefings can be saved as owner-scoped runs and reviewed later. Metrics summarize
completed work, fulfilled commitments, accepted proposals, verified actions,
and estimated attention returned.

### Work: Projects, Tasks, and Commitments

The Work domain includes:

- projects with goals, desired outcomes, milestones, risks, decisions, budgets,
  dates, tags, and progress summaries;
- tasks with status, priority, effort, energy, dependencies, subtasks, recurrence,
  reminders, contexts, assignees, and source references;
- commitments with counterparties, due dates, source excerpts, confidence,
  review state, fulfillment, and completion evidence;
- focus, blocked-work, overdue-commitment, breakdown, and rescheduling views;
- revisioned plans and append-only mutation receipts.

Records extracted by an agent remain proposals until the governed mutation path
accepts them.

### Email and Calendar

Email supports account configuration, inbox/search/read, folders, flags,
archive/move/delete, attachments, drafts, replies, signatures, scheduling,
summaries, translation, and writing-style assistance. Provider paths include
Gmail OAuth and IMAP/SMTP.

Calendar supports local calendars, event CRUD, recurrence, reminders, ICS
import/export, quick parsing, CalDAV synchronization, and Google Calendar OAuth.
Google writes use exact approval and deterministic provider read-back where the
provider supports it.

Live provider functionality requires valid credentials, scopes, callback URLs,
and network access. Test destructive or outbound operations with a dedicated
account before using personal production data.

### Meetings

Meetings support manual records, calendar-linked records, consent-gated media,
validated uploads, durable transcription and analysis jobs, cancellation,
retry, transcript revisions, speaker mapping, and retention settings.

Analysis produces source-span-backed summaries, decisions, risks, questions,
and proposed action items. Approved items can become Work tasks, and a reviewed
transcript can be promoted to Private Knowledge.

### Private Knowledge and Memory

Private Knowledge ingests text, notes, documents, email/calendar/meeting
records, and imported sources. It maintains source records, searchable chunks,
citations, sensitivity, processing status, expiry, stale state, revisions, and
derivative cleanup.

Search combines local lexical and deterministic vector-style retrieval, with
optional Chroma infrastructure. Answers are expected to cite source IDs and
state when evidence is insufficient. Memories have suggested, approved,
rejected, expired, sensitive, edited, and deleted states with source provenance.

### Document Vault

The Document Vault adds reviewable metadata to Knowledge sources. It can suggest
document classifications, expiry dates, and obligation excerpts with source
offsets. Suggestions remain correctable and revision-controlled. Sensitive
sources can disable memory suggestions while still supporting explicit,
source-backed queries.

### Documents, Notes, Contacts, and Files

The application includes a document editor and library, versions, archive,
imports, PDF rendering/export, annotation/signature workflows, notes and
checklists, contacts and CardDAV, general uploads, and an authorized workspace
for file tools.

Filesystem and shell tools are high-trust capabilities. They use confined
workspaces and protected control-plane paths, but should remain disabled unless
needed for a specific approved task.

### Automations and Routines

Automations use validated triggers, conditions, bounded actions, run limits,
idempotency, correlation IDs, durable step history, approval checkpoints,
retries, failure counters, cancellation, and dead-letter records.

Six installable routine templates are included:

| Routine | What it does |
| --- | --- |
| Renewals review | Searches indexed renewal and expiry evidence daily |
| Follow-up review | Surfaces source-backed follow-ups and commitments daily |
| Weekly review | Generates a source-backed weekly operating briefing |
| Inbox triage | Prompts a review-and-draft workflow without sending mail |
| Backup reminder | Reminds the user to create and verify an encrypted backup |
| Meeting follow-up | Reviews source-linked decisions and actions after meetings |

External communications and effectful integration steps pause for approval.

### Models, Cookbook, Research, MCP, and Media

The model Cookbook discovers hardware, checks dependencies, downloads models,
and manages compatible local or remote serve engines. OM Automate can also use
MCP servers, web search, deep research, image generation/editing, speech-to-text,
and text-to-speech when their optional services are installed and configured.

Provider and MCP content is untrusted input. Keep credentials isolated, grant
minimal scopes, and review tool access before enabling an integration.

### Privacy and Data Control

Owner-scoped privacy settings include local-only routing, provider visibility,
retention periods, sensitive-data redaction, integration controls, model logging,
and telemetry. Model logging and product telemetry default off.

Retention workers can purge expired owner data through explicit controls.
Knowledge, sessions, contacts, calendars, and other domains provide their own
export/delete workflows. Incognito content is excluded from durable chat and
memory paths, and backup snapshots sanitize known legacy reasoning/incognito
residue.

### Mobile Companion

The responsive companion lives at:

```text
/static/companion.html
```

An administrator pairs a device at `/api/companion/pair`. The resulting token is
shown once, stored hashed on the Core, owner-scoped, revocable, and retained by
the browser in session storage rather than permanent local storage. It grants
chat plus read-only Today, approvals, and reminder views. Approval decisions and
account administration remain in the full authenticated app.

## Real Feature Use Cases

### Start the day with one operating view

1. Connect the calendars and mailboxes you actually use.
2. Add priority tasks, projects, and reviewed commitments.
3. Open **Today** to see schedule, important messages, overdue work, approvals,
   reminders, meeting actions, and service health together.
4. Generate and save a morning briefing.
5. Follow its source links before accepting recommendations.

This uses the real Today aggregation, durable briefing runs, source references,
Work records, provider status, and Approval Centre.

### Compress an inbox without giving away send authority

1. Connect Gmail or an IMAP/SMTP account.
2. Search or open the relevant thread.
3. Ask OM to summarize it and prepare a reply draft.
4. Edit the draft in the document/email composer.
5. Review the exact recipient, subject, body, and attachments.
6. Approve sending only when the final proposal is correct.
7. Inspect the provider read-back and action history.

Drafting and sending are separate real capabilities. The inbox-triage routine
deliberately prompts review and drafting without silently sending messages.

### Turn a meeting into reviewed work and searchable knowledge

1. Create or import a meeting and record consent before adding media.
2. Upload supported audio and monitor the durable transcription job.
3. Review the transcript, speakers, summary, decisions, risks, and source spans.
4. Select only the action items that should become Work tasks.
5. Approve those exact task proposals.
6. Promote the reviewed transcript into Private Knowledge.
7. Later ask a question and follow the citation back to the meeting source.

This uses the actual meeting job system, revision history, evidence-backed
claims, governed Work mutation, and Knowledge promotion.

### Manage a personal project with provenance

1. Create a project with an outcome, milestones, risks, decisions, and target.
2. Add tasks with dependencies, effort, energy, reminders, and contexts.
3. Capture commitments from emails or meetings with source excerpts.
4. Use Focus and Blocked views to choose the next feasible work.
5. Review overdue commitments and create a correctable plan.
6. Use operating metrics to inspect completion and fulfillment trends.

The links between tasks, projects, meetings, documents, email, and calendar are
real stored references rather than free-form chat memory.

### Build a private document and renewal memory

1. Import an insurance policy, contract, receipt, or membership document.
2. Mark an appropriate sensitivity level.
3. Run Document Vault analysis.
4. Review and correct the suggested classification, expiry, and obligation
   excerpts against the original source.
5. Install the Renewals review routine.
6. Ask when renewal is due and require a citation to the indexed source.
7. Delete the source and verify its searchable derivatives are removed when the
   record should no longer be retained.

### Run a weekly review that survives restart

1. Install the Weekly review, Follow-up review, and Backup reminder templates.
2. Restart the application and confirm the definitions remain installed.
3. Let scheduled runs create durable history.
4. Review outputs and any approval-required steps.
5. Inspect retry, failure, and attention-returned metrics.

Routine definitions and run history are persisted in the automation database;
they are not browser-only timers.

### Use a phone as a private companion

1. Secure Core access over a trusted private network or HTTPS gateway.
2. Sign in as an administrator and open `/api/companion/pair`.
3. Generate a one-time pairing token and enter it in the companion page.
4. Review Today, pending approvals, and due reminders from the phone.
5. Use companion chat for a quick question.
6. Open the full app to make an approval decision.
7. Revoke the token under API token settings if the device is lost.

## Backup and Recovery

### Create a portable backup

Open **Settings -> System Backup**, enter a passphrase of at least 12 characters,
and download the `.ombak` file. User-created backups are always encrypted.

The portable v2 envelope contains consistent SQLite snapshots and the instance
key required to decrypt restored application records. The instance key appears
only inside the authenticated encrypted envelope. Logs, staging directories,
transient WAL/SHM files, unrelated private keys, and the scheduled-backup
passphrase file are excluded.

Store the backup and passphrase separately. Losing both the original instance
key and the backup passphrase can make encrypted data unrecoverable.

### Validate and stage a restore

In **Settings -> System Backup**:

1. choose an `.ombak` file;
2. enter its passphrase;
3. run preview/preflight;
4. confirm the file count and SQLite integrity checks;
5. explicitly stage restore;
6. restart the application;
7. verify login and representative records.

Startup applies staged files using per-file replacement and retains rollback
copies. A completed restore can be staged for rollback on the next restart.

### Run a local recovery rehearsal

The release check creates an encrypted backup and restores it into a temporary
empty data directory without replacing the live data root:

```bash
venv/bin/python scripts/privateos_release_check.py \
  --data-dir data \
  --restore-rehearsal
```

Record a genuine daily-use soak entry with:

```bash
venv/bin/python scripts/privateos_release_check.py \
  --data-dir data \
  --owner <username> \
  --record-soak \
  --note "Completed normal daily workflows"
```

After seven consecutive genuine days, require both restore and soak gates:

```bash
venv/bin/python scripts/privateos_release_check.py \
  --data-dir data \
  --owner <username> \
  --restore-rehearsal \
  --require-soak
```

Docker's named Chroma volume is outside the application `.ombak` and requires a
separate recovery decision if exact external vector state is needed.

## Synthetic Demonstration Data

To explore Work, Knowledge, Meetings, and routines without importing private
records, seed the clearly marked synthetic dataset into a disposable data
directory:

```bash
venv/bin/python scripts/privateos_demo.py \
  --data-dir /tmp/om-privateos-demo \
  --owner demo \
  --confirm
```

The operation is idempotent. Do not point demo tooling at a real data directory
unless you intentionally want synthetic records in that profile.

## Health and Diagnostics

These probes do not require a login and contain no secrets:

```bash
curl http://127.0.0.1:7000/api/health
curl http://127.0.0.1:7000/api/ready
```

Use the actual configured port when running natively. `live` means the web
process is responding. Readiness distinguishes required failures from optional
degraded services. For example, unavailable ChromaDB can produce usable degraded
readiness while the local lexical Knowledge path remains available.

Administrators can inspect service health and bounded logs under **Settings ->
System**. Do not paste unredacted logs into public issues.

## Updating Safely

Do not pull arbitrary new source over a live installation and immediately
restart it.

1. Create and preflight an encrypted backup.
2. Record the current commit, lock hashes, configuration, and service state.
3. Test the new version against a copy of the data.
4. Read migration and release notes.
5. Stop application writers.
6. Switch to the exact approved release tag.
7. Rebuild or reinstall from its locks.
8. Start once and inspect migration/readiness logs.
9. Verify login, representative records, automations, and restart persistence.
10. Retain the old code and backup through the observation window.

New Private OS domains use a versioned migration ledger. Some legacy core
schema paths remain import-time migrations, so the encrypted pre-upgrade backup
is still the rollback boundary.

## Uninstalling

Stop services before uninstalling. Decide whether to retain or securely erase:

- `.env`;
- `data/` and external data paths;
- encrypted backups and their passphrases;
- Docker named volumes;
- model caches;
- `venv/` and native helper packages;
- logs and generated SSH identities;
- launch agents, system services, or app wrappers created by the operator.

Removing the repository alone does not remove personal data or external Docker
volumes. `docker compose down -v` is destructive and should be used only after a
verified retention and backup decision.

## Troubleshooting

### The port is already in use

Choose another native port:

```bash
ODYSSEUS_PORT=7900 ./start-macos.sh
```

For Docker, set `APP_PORT=7001` in `.env`, then recreate the application service.

### ChromaDB is unavailable

The app should report optional vector infrastructure as degraded. Native users
can rerun `./start-macos.sh`; Docker users should inspect:

```bash
docker compose ps chromadb
docker compose logs --tail=200 chromadb
```

### No model is available

Start the configured model server, open **Settings -> Models**, test the endpoint,
refresh model discovery, and select a model for the chat. Check whether the app
runs natively or in Docker before using `localhost`; container-to-host endpoints
normally use `host.docker.internal`.

### Login reports recovery required

Do not create a replacement administrator over existing data. Stop the app,
inspect permissions and the auth-store error locally, and restore a known-good
encrypted backup when the store is corrupt.

### A provider operation is indeterminate

Do not immediately repeat an email send, event creation, or other consequential
operation. Inspect Approval Centre, provider state, and audit history first.
Reconcile whether the effect occurred before retrying.

### Docker setup times out

```bash
docker compose ps
docker compose logs --tail=200 odysseus
docker compose logs --tail=200 chromadb
docker compose logs --tail=200 searxng
```

Confirm the daemon is running, ports are free, storage is writable, and enough
disk and memory are available.

## Development and Verification

Create an isolated test environment; never run destructive tests against real
personal data.

```bash
venv/bin/python -m pip check
venv/bin/python -m pytest -q
git diff --check
```

The managed development sandbox can deny tests that intentionally bind sockets
or resolve DNS. Those tests require an explicitly socket-enabled integration
environment and must not be silently ignored in release CI.

Major implementation areas:

```text
app.py                         Application composition and lifecycle
core/                          Authentication, database, and middleware
routes/                        HTTP/API boundaries
services/                      Private OS domain and provider services
src/                           Agent runtime, tools, migrations, and models
static/                        Main browser application and companion
tests/                         Unit, service, route, security, and UI contracts
docs/om-automate/              Architecture, security, operations, and status
```

## Security Guidance

OM Automate controls private records and can be granted powerful local or
provider capabilities.

- Keep `AUTH_ENABLED=true`.
- Keep the default loopback bind unless network access is intentionally secured.
- Keep `LOCALHOST_BYPASS=false` for network deployments.
- Use HTTPS and secure cookies outside loopback.
- Never commit `.env`, `data/`, logs, sessions, backups, or credentials.
- Grant the smallest integration scopes and agent tools needed.
- Treat email, web, documents, model output, MCP output, and retrieved text as
  untrusted input.
- Review exact Approval Centre arguments before granting an action.
- Use a dedicated test account for initial email/calendar/provider acceptance.
- Keep encrypted recovery copies and rehearse restoration.

Read the [security model](docs/om-automate/07-security-model.md),
[administrator guide](docs/om-automate/13-admin-guide.md), and
[deployment guide](docs/om-automate/15-deployment-guide.md) before enabling
network access or effectful integrations.

## Documentation

- [Project status](docs/om-automate/00-project-status.md)
- [Feature inventory](docs/om-automate/03-feature-inventory.md)
- [Security model](docs/om-automate/07-security-model.md)
- [Bug register](docs/om-automate/09-bug-register.md)
- [Test and acceptance plan](docs/om-automate/10-test-plan.md)
- [Migration guide](docs/om-automate/11-migration-guide.md)
- [User guide](docs/om-automate/12-user-guide.md)
- [Administrator guide](docs/om-automate/13-admin-guide.md)
- [API and webhook guide](docs/om-automate/14-api-and-webhook-guide.md)
- [Deployment guide](docs/om-automate/15-deployment-guide.md)
- [Recommended local agent model](docs/om-automate/16-local-agent-model.md)
- [Five-phase Private OS plan](docs/om-automate/17-privateos-phased-plan.md)
- [Commercial readiness gap analysis](docs/om-automate/18-commercial-readiness-gap-analysis.md)

## Source, Licence, and Attribution

OM Automate is a modified interface and product layer based on the
[Odysseus project](https://github.com/odysseus-dev/odysseus), with the audited
transformation baseline at commit
[`9844a2f9a1996b8c8135a9e7bbde6a72f41df5ed`](https://github.com/odysseus-dev/odysseus/commit/9844a2f9a1996b8c8135a9e7bbde6a72f41df5ed).
It is not sponsored by or affiliated with the upstream authors.

The repository declares AGPL-3.0-or-later. Before any public, hosted, binary,
container, app-store, or commercial release, resolve the licence inconsistencies
and source-offer requirements identified in
[the licence and attribution review](docs/om-automate/licence-and-attribution-review.md).
See [LICENSE](LICENSE), [ACKNOWLEDGMENTS.md](ACKNOWLEDGMENTS.md), and the
in-product Legal & source page.
