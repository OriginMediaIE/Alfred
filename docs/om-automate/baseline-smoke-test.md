# Baseline Smoke Test

## Scope and immutable baseline

- Source: `https://github.com/odysseus-dev/odysseus.git`
- Upstream branch: `main`
- Baseline commit: `9844a2f9a1996b8c8135a9e7bbde6a72f41df5ed`
- Working branch: `om-automate/main`
- Test date: 2026-07-18
- Host: macOS 15.1.1, Apple Silicon, 8 logical CPUs, 16 GiB RAM
- Browser: Codex in-app browser against `http://127.0.0.1:7860`
- Python: Homebrew CPython 3.11.14 in repository-local `venv`
- Model runtime: Ollama 0.31.1 at `http://127.0.0.1:11434`
- Selected model: `qwen3:1.7b`

This document records an observed baseline. It does not claim that unavailable external services or credentialed providers work.

## Installation and startup

The supported system Python was too old (`3.9.6`), so the native baseline used Python 3.11:

```bash
/opt/homebrew/bin/python3.11 -m venv venv
./venv/bin/python -m pip install -r requirements.txt
./venv/bin/python setup.py
./venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 7860
```

Setup created `.env`, `data/app.db`, `data/auth.json`, application directories, and a local test administrator. The credential was deliberately kept out of Git and is not reproduced in this document.

The application started successfully. Four bundled MCP child servers connected. ChromaDB, SearXNG, and ntfy were not listening locally, so RAG/memory reported degraded availability. The app remained usable for the flows below.

## Automated startup observations

| Check | Observed result | Status |
|---|---|---|
| `GET /` without a session | `302` to `/login` | Pass |
| `GET /login` | `200`; login HTML rendered | Pass |
| `GET /api/health` | `200`; healthy | Pass |
| `GET /api/version` | `200`; `1.0.2` | Pass |
| `GET /api/auth/status` | Configured, unauthenticated, signup disabled | Pass |
| `GET /api/ready` without a session | `401` | Defect |
| Database integrity | SQLite integrity check successful; 32 tables | Pass |
| Idle resource sample | About 217.6 MiB RSS across Uvicorn and four MCP children; 0% CPU sample | Recorded |
| Clean shutdown | Application stopped, but four MCP cancel-scope warnings were logged | Defect |

`/api/ready` cannot currently be used by an unauthenticated container orchestrator. It also checks only the database and writable data directory, not required/degraded dependencies.

## Manual browser acceptance results

| Required journey | Procedure and observed result | Status |
|---|---|---|
| Application starts | Opened the native Uvicorn service at `127.0.0.1:7860`. | Pass |
| Login page loads | Root redirected to a rendered `Odysseus — Login` page. | Pass |
| Invalid credentials rejected | Submitted an invalid password; UI displayed `Invalid credentials` and did not create a session. | Pass |
| Administrator login | Submitted the local test administrator credentials; dashboard loaded. | Pass |
| Main dashboard | Chat workspace and sidebar modules rendered. | Pass |
| Chat opens | Existing/new chat workspace accepted input. | Pass |
| Configured model answers | Added the local Ollama OpenAI-compatible endpoint, selected `qwen3:1.7b`, and requested the exact text `baseline-ok`; the final answer matched. | Pass with defect |
| Task creation | Created a one-time task named `Baseline smoke task`; it appeared in the task list. | Pass |
| Note creation | Created `Baseline smoke note` with a body; it appeared in Notes. | Pass |
| Calendar view | Opened Calendar; the July 2026 view rendered without an account/event error. | Pass |
| Email settings entry point | Opened Email; the empty state linked to Settings → Integrations for account setup. | Pass |
| Knowledge/document flow | Opened Brain → Add; supported import types and the skill import flow rendered. | Pass |
| Restart persistence | Stopped and restarted Uvicorn, logged in again, and verified the conversation, task, and note remained. | Pass |
| Logout | Logged out and returned to `/login`. | Pass |
| Test-data cleanup | Deleted the temporary task and note through their normal UI flows after persistence verification. | Pass |

## Defects exposed by the smoke test

1. The chat UI rendered the local model's raw reasoning trace under `View thinking process`. OM Automate must expose only a concise user-safe action/reasoning summary and never hidden chain-of-thought.
2. Readiness is authentication-protected and incomplete.
3. ChromaDB, SearXNG, and ntfy are not started by the minimal native command, so several modules degrade unless the platform launcher or Compose stack is used.
4. Shutdown logs `Attempted to exit cancel scope in a different task than it was entered in` for bundled MCP servers.
5. `.env`, authentication data, the main database, settings/sessions, and logs were created as mode `0644`; secret-bearing state needs `0600` and private directories need restrictive modes.
6. Compose maps a separate host logs directory to `/app/logs`, while the application writes its main log under `/app/data/logs/app.log`.
7. Docker runtime verification remains blocked because Docker Desktop is stopped, even though `docker compose config` validation succeeds.

## Test-suite baseline

- Pytest collected 4,527 tests.
- The initial restricted full run produced 4,501 passed, 23 failed, and 3 skipped.
- Twenty-one failures cleared with local socket access and a short temporary directory.
- The last two research failures came from a fixture that hardcodes `data/deep_research` while the audit run redirected `ODYSSEUS_DATA_DIR`; the complete file passed when those paths matched.
- All baseline tests passed across isolated reruns. After adding the startup/cancellation regressions and repairing the two environment-sensitive fixtures, a later single-command isolated gate recorded 4,535 passed and 3 expected skips in 135.54 seconds.
- CI currently marks pytest `continue-on-error: true`, so this baseline does not have a reliable behaviour gate.

## Repeat procedure

1. Use a disposable data directory and deterministic test administrator credential.
2. Start required local services or explicitly record each degraded dependency.
3. Start the application and wait for a public, dependency-aware readiness endpoint.
4. Run the automated startup checks.
5. Execute every browser journey in the table.
6. Restart the process/stack and verify persisted records.
7. Delete smoke fixtures and verify deletion.
8. Inspect application logs for uncaught exceptions, leaked secrets, and shutdown warnings.
9. Record CPU/RSS and service versions.
10. Do not mark the gate passed if a required provider was silently substituted or a side effect was not read back.

## Gate decision

The native baseline is usable and the mandatory UI entry points were manually observed. The clean one-shot test gate is now recorded. Milestone 1 is not yet complete: Docker deployment, reproducible dependency locks, and the documented remaining critical/high defects still require work.
