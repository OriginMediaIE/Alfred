# OM Automate Deployment Guide

## 1. Deployment status

This guide describes the current OM Automate deployment profile and its remaining release gates. The audited transformation baseline is upstream `main` commit `9844a2f9a1996b8c8135a9e7bbde6a72f41df5ed`.

The repository now has a reproducible **Docker installation contract**, but it is
not yet qualified as a production release:

- `requirements-om.lock` and `requirements-optional.lock` pin every declared Python distribution exactly;
- the runtime uses Python `3.14.6`; ChromaDB `1.5.9`, SearXNG `2026.5.31-7159b8aed`, and ntfy `v2.26.0` are exact Compose tags;
- macOS/Linux and Windows launchers perform preflight, protect existing configuration/data, validate Compose, start idempotently, and wait for `/api/ready`;
- Compose health-gates SearXNG, ChromaDB, and the application;
- syntax, Compose rendering, static pin checks, and a network-free fake-Docker installer harness pass;
- the Docker daemon was unavailable on the audit host, so no image pull/build, container startup, authenticated browser smoke, restart, backup/restore, or upgrade was verified;
- downloaded build artifacts are versioned but not all carry checked-in SHA-256 values or immutable container digests;
- the native manual launch can still degrade vector features and is not the maintained release profile;
- dependency-aware readiness and the log bind mismatch were completed in
  Personal PrivateOS Phase 1; versioned database migrations and cross-platform
  qualification remain open.

Do not describe a platform as supported until its installation, browser smoke, restart, backup, restore, and upgrade evidence has passed `10-test-plan.md`.

## 2. Current platform evidence

| Platform | Evidence | Current claim |
| --- | --- | --- |
| macOS Apple Silicon, native | Dependencies installed; setup/Uvicorn, authenticated browser, local-model, restart persistence, encrypted backup preflight, 32-file/6-database fresh restore rehearsal, rollback evidence, and scoped companion smoke observed | Phase 5 implementation verified; seven-day soak, physical iPhone Safari, Chroma, live providers, and copied-data upgrade remain open |
| macOS Apple Silicon, Docker Desktop | Shell preflight reached the daemon gate; Compose parses; daemon was stopped | Installer logic verified; runtime not installation-tested |
| macOS Intel | None | Unverified |
| Windows Docker Desktop | PowerShell launcher inspected and statically tested; Compose parses on macOS only | Unverified on Windows |
| Windows native / WSL2 | Launcher inspected; no PowerShell runtime test | Unverified |
| Linux CPU | POSIX installer exercised twice against a network-free fake Docker CLI with preserved `.env`; shell syntax and Compose parse pass | Harness-verified only; no real container run |
| Linux NVIDIA | Overlay parses; no hardware run | Unverified |
| Linux AMD | Overlay parses; no hardware run | Unverified |

## 3. Architecture, processes, and ports

### 3.1 Docker services

| Service | Container port | Default host binding | Persistence |
| --- | --- | --- | --- |
| OM application | 7000 | `127.0.0.1:7000` | `${APP_DATA_DIR:-./data}` plus model/SSH bind paths |
| SearXNG | 8080 | `127.0.0.1:8080` | `searxng-data` named volume |
| ChromaDB | 8000 | `127.0.0.1:8100` | `chromadb-data` named volume |
| ntfy | 80 | `127.0.0.1:8091` | `ntfy-cache` named volume |

The app reaches Docker services at `searxng:8080` and `chromadb:8000`. `host.docker.internal` is configured for an existing host Ollama or other model server.

### 3.2 Native processes

- Manual Linux/macOS launch: Uvicorn on `127.0.0.1:7000`.
- `start-macos.sh`: Uvicorn on `127.0.0.1:7860`, ChromaDB on `127.0.0.1:8100`, and optional Apfel on 11435.
- Existing Ollama normally listens on 11434.
- Four built-in stdio MCP child processes may run for image generation, memory, RAG, and email.
- Cookbook model servers commonly use ports 8000-8020; keep them private.

Only the authenticated application entrypoint should be exposed through a trusted reverse proxy. ChromaDB, SearXNG, ntfy administration, databases, and raw model APIs remain loopback/internal unless a specific private-network design requires otherwise.

## 4. Data and persistence

The source/native data root defaults to `./data` and can be changed with `ODYSSEUS_DATA_DIR`. It includes:

- `app.db`, `scheduled_emails.db`, and `email_cache.db`;
- `auth.json`, `sessions.json`, `settings.json`, preferences, integrations, and presets;
- `.app_key`, which is required to decrypt stored encrypted values;
- uploads, personal documents, gallery/generated media, memory, skills, research, and native Chroma data;
- `data/logs/app.log` and search logs.

Docker mounts the host's `${APP_DATA_DIR:-./data}` at `/app/data`. It also mounts nested host paths for `/app/.ssh`, `/app/.cache/huggingface`, and `/app/.local`, keeping Cookbook keys, downloaded models, and installed serving engines across container recreation.

Docker Chroma data is separate in the Compose-managed `chromadb-data` volume. A backup of `./data` alone is therefore incomplete for Docker deployments.

### Application logs

Compose mounts `${APP_LOGS_DIR:-./logs}` at `/app/data/logs`, matching the
application's `DATA_DIR/logs/app.log` sink. The entrypoint repairs ownership and
the application applies owner-only POSIX modes. Real Docker log-persistence and
rotation evidence is still pending because Docker Desktop was stopped during
the Phase 1 verification. For current diagnostics use:

```bash
tail -f data/logs/app.log
docker compose logs -f --tail=200 odysseus
```

Do not rely on `APP_LOGS_DIR` for the main file log.

## 5. Prerequisites

### Docker path

- Git;
- Docker Engine with Compose v2, or Docker Desktop;
- sufficient disk for images, model caches, uploads, backups, and at least one rollback copy;
- a supported local/remote model provider;
- an operator-controlled backup destination.

GPU overlays additionally require host driver/runtime configuration. The overlay exposes hardware only; it does not install CUDA/ROCm userspace or an inference engine.

### Native path

- Python 3.11 or newer, using a native CPU architecture;
- Git and a working compiler/runtime for any dependency without a wheel;
- `tmux` for Cookbook background downloads/serves on POSIX;
- a ChromaDB service for vector features;
- optional `llama-server`/Ollama or a remote API model.

On Apple Silicon, use an arm64 Homebrew Python. Do not create the venv with an x86 interpreter under Rosetta.

## 6. Reproducibility contract and remaining gate

The maintained Docker profile installs from `requirements-om.lock`; optional PDF,
Office, transcription, and search extras use `requirements-optional.lock`. The
Dockerfile and all base Compose services use exact version tags. Unpinned
`requirements*.txt` files remain developer inputs and are not consumed by the
release image.

Before issuing a signed release:

1. resolve/test locks on every claimed platform and architecture, including wheel availability;
2. add immutable image digests and SHA-256 verification for the Docker CLI and every downloaded build artifact;
3. retain `package-lock.json` and use `npm ci` for Node build/test dependencies;
4. publish a signed release manifest containing source commit, OS/architecture matrix, Python, Node, Docker, service, model-runtime, and model-artifact versions;
5. rebuild from empty caches and compare installed distributions and image digests;
6. run fresh-install, restart, backup, restore, rollback, and upgrade acceptance on each claimed platform;
7. change any pin only through a reviewed dependency-update change with the same qualification evidence.

Exact tags prevent ordinary floating-version drift, but they are not equivalent to
an immutable digest when a registry owner can retag an image.

## 7. Docker installation

Docker Compose is the maintained deployment profile. Platform support is granted
only after its fresh-install acceptance passes.

### 7.1 Checkout and environment

Use the published OM Automate repository and a signed immutable release tag, not
a moving branch. No public OM Automate release URL/tag exists yet; the following
placeholders are a release blocker and must not be distributed unchanged:

```bash
git clone <OM_AUTOMATE_RELEASE_URL> om-automate
cd om-automate
git checkout <SIGNED_RELEASE_TAG>
```

The one-click installer creates `.env` with restrictive permissions only if it is
missing and never overwrites an existing file.

Set at least these deployment values in `.env`:

```dotenv
APP_BIND=127.0.0.1
APP_PORT=7000
APP_DATA_DIR=./data
AUTH_ENABLED=true
LOCALHOST_BYPASS=false
SECURE_COOKIES=false
ODYSSEUS_ADMIN_USER=admin
# ODYSSEUS_ADMIN_PASSWORD=<store a unique value from a password manager>
```

Do not commit `.env`. Generate a unique administrator password in a password manager or with an approved local cryptographic generator, store it directly in the secret store, and remove it from `.env` after first-login rotation where the deployment mechanism allows. Never paste it into issue text, logs, screenshots, or shell history.

On Linux, set `PUID` and `PGID` to the operator's numeric IDs so bind-mounted files remain manageable:

```bash
id -u
id -g
```

### 7.2 Preflight and launch

```bash
# macOS / Linux: validate without pulling/building/starting
./install-om-automate.sh --check

# Build, start, health-check, and open the local application
./install-om-automate.sh

# Optional accelerator overlays after the host runtime is verified
./install-om-automate.sh --accelerator nvidia
./install-om-automate.sh --accelerator amd
```

```powershell
# Windows PowerShell (or double-click install-om-automate.cmd)
.\install-om-automate.ps1 -Check
.\install-om-automate.ps1
```

For diagnostics, the equivalent manual commands are `docker compose config
--quiet`, `docker compose up -d --build`, `docker compose ps`, and `docker compose
logs --tail=200 odysseus`. Do not delete `.env`, `data/`, or named volumes to
resolve an install failure.

First boot runs `setup.py` in the container and then executes Uvicorn on container port 7000. If no admin password was pre-seeded, retrieve the generated temporary password from the first setup log and change it immediately:

```bash
docker compose logs odysseus
```

Open `http://127.0.0.1:7000` only after the release health gate succeeds.

### 7.3 Health contract and limitations

The base Compose file health-checks SearXNG, ChromaDB, and the OM application.
The application waits for the first two to become healthy, and the installers
complete only after the public liveness probe succeeds. ntfy is not health-gated.

Current probes:

```bash
curl --fail http://127.0.0.1:7000/api/health
curl --fail http://127.0.0.1:7000/api/ready
```

`/api/health` is intentionally only process liveness and returns status `live`.
`/api/ready` is public and secret-free. It returns 200 for `ready` or usable
`degraded` state and 503 for `failed` required checks. Current required checks
cover database, storage, private POSIX permissions, lifecycle, scheduler, meeting,
automation, and privacy workers; vector storage is classified as optional and may
degrade without taking down the local Core. Authenticated diagnostics retain the
richer provider detail. Do not add account identifiers, credentials, paths, or
provider error bodies to the public response.

### 7.4 Local model connection

For Ollama running on the Docker host, make Ollama reachable from the Docker VM and configure:

```dotenv
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
```

Do not publish Ollama's raw port to the internet. Verify model discovery and a basic response through the authenticated OM application, not merely by calling Ollama directly.

### 7.5 Optional overlays

Host Docker-socket access is high trust and disabled by default. Enable it only when Cookbook must manage the host daemon:

```dotenv
COMPOSE_FILE=docker-compose.yml:docker/host-docker.yml
DOCKER_GID=<host-docker-group-id>
```

GPU selections:

```dotenv
# NVIDIA
COMPOSE_FILE=docker-compose.yml:docker/gpu.nvidia.yml

# AMD
COMPOSE_FILE=docker-compose.yml:docker/gpu.amd.yml
RENDER_GID=<host-render-group-id>
```

Validate the merged configuration before launch. GPU visibility is not proof that a GPU-enabled model engine works; run an end-to-end model inference test.

## 8. Native installation

### 8.1 Apple Silicon one-click launcher

```bash
git clone <OM_AUTOMATE_RELEASE_URL> om-automate
cd om-automate
git checkout <SIGNED_RELEASE_TAG>
./start-macos.sh
```

The script:

- requires Homebrew;
- selects an arm64 Python 3.11-3.13;
- installs the exact core lock when it changes;
- attempts to install `tmux`, `llama.cpp`, and Apfel;
- runs first-time setup;
- replaces `chromadb-client` with full `chromadb==1.5.9` and launches a local Chroma service;
- starts optional Apfel on 11435;
- launches the app at `http://127.0.0.1:7860`.

This path changes host packages. Its shell, brand configuration and focused
launcher tests pass, but it was not executed end-to-end on a clean Apple Silicon
host and is not a qualified release profile.

### 8.2 Manual Linux/macOS path

```bash
python3.11 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-om.lock
python -m pip check
python setup.py
python -m uvicorn app:app --host 127.0.0.1 --port 7000
```

The manual path installs the Chroma HTTP client but does not start a Chroma server. The audited launch therefore started with document RAG and vector memory degraded. A supported full native profile must add and supervise ChromaDB, or explicitly document a reduced profile and its unavailable features.

### 8.3 Windows native launcher

```powershell
powershell -ExecutionPolicy Bypass -File .\launch-windows.ps1
```

The launcher creates `venv`, installs `requirements-om.lock`, runs setup, and
serves on `127.0.0.1:7000`. Its `-BindHost` argument controls network exposure;
changing `APP_BIND` in `.env` alone does not change the native Windows bind
address. Static contracts pass, but PowerShell execution was not available on
the audit host.

## 9. Initial administrator and login

`setup.py` creates the first administrator only when `data/auth.json` does not exist:

- default username: `admin`;
- minimum password length: 8;
- interactive setup prompts for credentials;
- non-interactive setup uses configured environment values or prints a generated temporary password;
- open registration defaults off.

First-login checklist:

1. verify the browser is connected to the expected loopback/private HTTPS origin;
2. log in as the initial administrator;
3. change any generated/default password;
4. confirm open registration is disabled unless intentionally required;
5. configure least-privilege non-admin accounts;
6. enable 2FA where appropriate;
7. verify logout, session revocation, invalid-login rejection, and rate limiting.

If `auth.json` exists but is corrupt or contains no usable user, setup skips file creation. Use the first-run `/api/auth/setup` recovery flow only on a private loopback connection, or restore a known-good backup.

## 10. Integration setup status

### Google, Gmail, and Calendar

The OM Automate specification requires Google OAuth 2.0, Gmail, and Google Calendar. The audited upstream baseline primarily exposes IMAP/SMTP email and CalDAV calendar configuration; a complete Google OAuth deployment was not verified. Do not claim Google support until OAuth callback allowlists, state/PKCE, encrypted refresh tokens, scope minimization, rotation, revoke/disconnect, and mocked/live acceptance tests pass.

For current email/CalDAV testing, use dedicated accounts and full collection URLs. Never use a personal production mailbox during installation validation.

### Transcription

Local speech-to-text requires the optional `faster-whisper` dependency:

```bash
./venv/bin/python -m pip install -r requirements-optional.lock
```

That exact lock also installs other optional packages, including AGPL-licensed
PyMuPDF. Review the licence obligations before enabling this profile in a
distributed release.

## 11. File permissions

The audited native setup created `.env`, databases, auth, settings, sessions, and logs as `0644`. This is unsafe on a multi-user POSIX host. Until creation is fixed in code, apply a restrictive umask before setup and audit the result:

```bash
umask 077
chmod 700 data
find data -type d -exec chmod 700 {} +
find data -type f -exec chmod 600 {} +
chmod 600 .env
```

Do not blindly change ownership or modes on shared/network filesystems. Confirm the service account can still read/write after hardening. Windows relies on profile ACLs and needs a separate ACL verification test.

## 12. Network deployment

The application serves plain HTTP. For any access beyond loopback:

- keep `AUTH_ENABLED=true` and `LOCALHOST_BYPASS=false`;
- terminate HTTPS at a trusted reverse proxy/private access gateway;
- set `SECURE_COOKIES=true`;
- set `ALLOWED_ORIGINS` to exact approved HTTPS origins;
- preserve and validate proxy headers; never infer a remote user is localhost;
- use approved OAuth callback URLs only;
- change initial passwords and keep registration closed;
- keep raw model, database, ChromaDB, SearXNG, and internal service ports private;
- configure and test backup/restore before launch;
- test session, CSRF/CORS, rate-limit, webhook, and SSRF controls through the actual proxy.

The Docker installer fails closed on non-loopback binding. After setting the
required hardened values and configuring the HTTPS proxy, authorize that
specific launch with `OM_AUTOMATE_ALLOW_NETWORK=1`; this acknowledgement does
not configure or prove the proxy for you.

A minimal topology is:

```text
client -> HTTPS reverse proxy/private access layer -> 127.0.0.1:7000 OM application
                                                    -> internal-only providers/services
```

Do not bind directly to `0.0.0.0` on a public host and treat application login alone as sufficient production hardening.

## 13. Routine operations

### Docker

```bash
docker compose ps
docker compose logs -f --tail=200 odysseus
docker compose restart odysseus
docker compose stop
docker compose start
```

### Native

Run Uvicorn under a supervised user service only after replacing the placeholder `odysseus-ui.service`. The checked-in unit binds `0.0.0.0`, contains placeholder paths, and has no service hardening or dependency readiness; it is not production-ready as-is.

Application logs are currently at `data/logs/app.log`. Rotate and protect them. Logs may contain operational metadata and must not contain passwords, cookies, OAuth codes, tokens, message content, or document content.

The observed native idle footprint was approximately 217.6 MiB RSS for Uvicorn and four MCP children on a 16 GiB Apple Silicon host, with 0.0% CPU on a settled sample. Re-measure every release on declared reference hardware.

## 14. Backup plan

Backups contain passwords, sessions, encryption keys, provider tokens, messages, and personal files. Store them encrypted with access restricted to the operator.

### 14.1 Application data snapshot

From the repository root:

```bash
./scripts/odysseus-backup snapshot --include-research --include-attachments
./scripts/odysseus-backup list
./scripts/odysseus-backup verify backups/odysseus-backup-YYYYMMDD-HHMMSS.tar.gz
```

The script uses SQLite's backup API and includes `data/.app_key`. Verification is mandatory before an upgrade. Copy the verified archive to an encrypted off-host destination and test restoration periodically.

### 14.2 Docker Chroma volume

The application snapshot does not include Docker's `chromadb-data` volume. For a consistent pre-upgrade backup, stop writers, identify the actual Compose-prefixed volume, and archive it with a pinned helper image:

```bash
docker compose stop odysseus chromadb
docker volume ls | grep chromadb-data
docker run --rm \
  -v <project>_chromadb-data:/data:ro \
  -v "$PWD/backups":/backup \
  <pinned-archive-image>@sha256:<digest> \
  tar czf /backup/chromadb-YYYYMMDD-HHMMSS.tar.gz -C /data .
docker compose start chromadb odysseus
```

Record the application snapshot, Chroma archive, Git commit, lock hashes, image digests, and configuration checksum as one backup set. Consider whether SearXNG settings and ntfy state are required for the deployment and archive those named volumes too.

### 14.3 Backup acceptance

A backup is valid only if:

- archive verification succeeds;
- it contains the matching `.app_key`;
- Docker vector data is included where required;
- the backup set is encrypted and readable by the recovery operator;
- an isolated restore boots and passes login, record counts, sample decryption, knowledge retrieval, and restart checks.

## 15. Upgrade plan

Do not run `git pull` and immediately restart a production instance. Use a staged immutable release:

1. read release notes, licence changes, security advisories, and migration notes;
2. record current Git commit, dependency lock hashes, image digests, configuration checksum, and service state;
3. create and verify a full backup set;
4. test the upgrade against a copy of production data in an isolated environment;
5. verify disk capacity for old/new images, backup, database growth, and rollback;
6. fetch and verify the signed release tag/artifacts;
7. validate merged Compose configuration;
8. stop application writers;
9. build/pull the exact pinned release;
10. start it once and monitor schema migration/startup logs;
11. run readiness, login, model, task/note/calendar, knowledge, and persistence smoke tests;
12. retain the previous release and backup until the observation window ends.

PrivateOS domain schemas now use a versioned `om_schema_migrations` ledger with
cross-process locking and idempotent startup. Historical fixture tests cover
those domain migrations. The older core application schema still contains
legacy import-time migration paths and has no supported down migration, so an
encrypted v2 pre-upgrade backup plus tested restore remains the rollback
boundary. Track replacement of the remaining legacy path under `OM-BUG-018`.

## 16. Rollback and restore

Rollback requires both old code and old data. Do not run older code against a database already modified by newer startup migrations.

### Docker rollback

```bash
docker compose stop
git checkout <previous-verified-release>
docker compose config --quiet
./scripts/odysseus-backup verify backups/<pre-upgrade>.tar.gz
./scripts/odysseus-backup restore backups/<pre-upgrade>.tar.gz --yes
```

Restore the matching Chroma volume archive, then rebuild/start the previous pinned images:

```bash
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=200 odysseus
```

The restore tool renames the current data directory to `data.before-restore-<timestamp>` before extraction. Preserve it until recovery is confirmed.

### Native rollback

1. stop Uvicorn and all supervised MCP/Chroma/model children;
2. verify the pre-upgrade backup;
3. check out the previous verified release;
4. recreate the venv from that release's lock, rather than reusing upgraded packages;
5. restore the application snapshot and native `data/chroma`;
6. launch on loopback and run the complete rollback smoke test.

Rollback passes only when login, decrypted integrations, sessions/messages, tasks, calendar, knowledge retrieval, and restart persistence all match the pre-upgrade evidence.

## 17. Uninstall

Create and verify a final backup before uninstalling.

Docker application removal while preserving data/volumes:

```bash
docker compose down
```

`docker compose down -v` deletes named service volumes and is destructive. Use it only after identifying every target volume and confirming the final backup/retention decision. Host `data/`, `backups/`, model caches, `.env`, and logs must be handled explicitly.

For native installs, stop supervised services first, then retain or securely erase the source tree, `data/`, `.env`, backups, model caches, venv, launch agents/systemd units, and generated SSH keys according to the operator's retention policy. Removing the repository alone does not remove Homebrew/system packages installed by the macOS launcher.

## 18. Troubleshooting

| Symptom | Check | Current guidance |
| --- | --- | --- |
| Docker commands cannot connect | `docker info` | Start Docker Engine/Desktop; configuration parsing alone is not a launch |
| App unavailable on macOS port 7000 | Check launcher output | `start-macos.sh` defaults to 7860 because AirPlay may occupy 7000 |
| RAG/memory degraded | Check 8100 and `data/logs/app.log` | Start/configure ChromaDB; manual native instructions do not do this |
| `/api/ready` returns 503 | Inspect the response's non-sensitive required check codes, then authenticated diagnostics and `data/logs/app.log` | A required core subsystem is failed; optional service loss should return 200/degraded |
| `logs/` is empty | Inspect `data/logs/app.log` | Known `APP_LOGS_DIR` mount mismatch |
| Files are mode `0644` | `stat`/`ls -l` | Apply restrictive umask/modes and fix creation code before multi-user deployment |
| Browser MCP missing | Review startup log | Optional; pre-cache/install Playwright MCP only when required and pinned |
| `python-magic` unavailable natively | Review upload log | Docker installs it with `libmagic`; define a supported native package/profile |
| MCP shutdown warnings/orphans | Inspect process tree and log | Known lifecycle defect; stop children and block release until regression passes |
| Dependency result changes | Compare exact locks and image tags/digests | Stop; do not update a pin without clean-build qualification |

## 19. Launch acceptance checklist

Production/private launch is authorized only after:

- a fresh Docker installation succeeds from pinned artifacts;
- the exact platform appears in the tested support matrix;
- full automated, migration, security, installation, and browser suites pass;
- an administrator logs in, changes the initial password, and verifies 2FA/registration policy;
- a supported local/API model responds and passes minimum agent tool-use probes;
- required vector, email, calendar, transcription, and OAuth integrations report healthy;
- readiness is safe, unauthenticated, dependency-aware, and wired into the orchestrator;
- only the HTTPS application entrypoint is network-accessible;
- logs are present at the documented protected path and contain no secrets;
- backup, off-host copy, restore, and rollback have been demonstrated;
- restart preserves user data and creates no duplicate jobs/orphan children;
- file ownership/modes and container volume mappings are verified;
- monitoring captures startup, latency, error, queue, provider, and tool-success signals locally;
- rollback owners, commands, backup identifiers, and the observation window are recorded.

If any gate fails, keep the deployment on loopback/test infrastructure, document the blocker, and do not claim the release is fully operational.
