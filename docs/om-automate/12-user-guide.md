# OM Automate User Guide

## 1. Release status

OM Automate is a local-first personal operations application. This branch now includes the OM interface, Today dashboard, chat and agents, personal Work and Life records, Google Workspace, email, calendars, meetings, knowledge, privacy controls, approvals, structured automations, and encrypted full-data backup/restore staging.

Automated tests cover the local contracts. A real Google grant, real external mail/calendar account, optional GPU runtime, and every supported operating-system installer still require operator-specific acceptance testing. “Configured” and “connected” are shown separately; the application must not claim a provider action succeeded when readback did not confirm it.

## 2. Sign in and choose a model

Open the private URL printed by the launcher. The current prepared test checkout uses `http://127.0.0.1:7000`; a fresh macOS native launch defaults to `http://127.0.0.1:7860` when `.env` does not override the port. Sign in, change temporary credentials, and enable two-factor authentication where required.

An existing unreadable or corrupt authentication store puts the service into recovery-required state. It does not reopen first-admin registration. If recovery is shown, stop and ask the local operator to restore the verified authentication data.

Select a model in the chat model picker. Local models keep model traffic on the configured local endpoint; hosted models send the assembled prompt to that provider. A successful ordinary chat does not by itself prove that a model can reliably call tools.

## 3. Privacy and routing

Settings → Privacy controls local-only routing, telemetry/model logging, integrations, and retention for conversations, files, email caches, memories, meeting audio, and transcripts. Incognito chat stays in the live in-memory session and is not written to SQLite by the message-save path.

Content can still leave the host when you explicitly use a hosted model, Google/IMAP/SMTP/CalDAV provider, web/research, image or speech provider, webhook, REST integration, remote model host, or MCP server. Check the selected model, enabled integrations, web toggle, attachments, and workspace before sending sensitive material.

Private model chain-of-thought is not exposed over the chat API, UI, metrics, or persistence. The UI shows only a generic reasoning status and a safe completion summary.

## 4. Chat, attachments, and agents

Ordinary Chat supports persistent conversations, search, fork, rename, archive, edit, compact, stop, and export. Attachments and selected workspace context are bounded as untrusted source material; embedded instructions do not authorize tools.

Agent mode exposes only tools allowed by the canonical registry, account permissions, current mode, per-turn toggles, and policy engine. Consequential actions create an exact durable proposal in Approval Centre. Approval binds the tool, arguments, owner, revision, expiry, request, and idempotency record; execution then performs domain/provider readback where supported.

Shell, Python, and filesystem capability is off unless the user enables the shell toggle for that turn and the account has permission. It remains Level 3, requires exact approval, uses a dedicated workspace, receives a scrubbed environment, and fails closed when the host cannot create the required OS sandbox. Network access is not granted to the sandbox; use the governed web/integration tools instead.

Stop cancels locally owned tool tasks and settles their UI state. A provider may have committed an external effect before cancellation arrived; inspect provider state before retrying an indeterminate action.

## 5. Approval Centre

Open Approval Centre to inspect pending consequential actions. Review the exact account, recipients, dates, resources, arguments, risk, source request, and expiry. Approve or reject the proposal; do not use a chat sentence as a substitute for the approval control.

Level 2 external actions require confirmation by default. Level 3 destructive, shell, sensitive, or security actions always require confirmation. An approval can be consumed only by its exact action. Results show verification/reversal state rather than treating model prose as proof.

## 6. Today, Work, and Life

Today combines calendar, priorities, overdue work, commitments, meetings, important email, relationship reminders, pending approvals, integration health, local Core health, and operating metrics. Switch between morning, evening, and weekly source-backed briefings; saving a briefing creates an idempotent owner-only history record. Missing providers and sources appear as unavailable/degraded rather than fabricated facts.

Work supports projects, outcomes, milestones, tasks, subtasks, dependencies, reminders, source references, suggested commitments, focus lists, work blocks, status history, activity, and editable breakdown/rescheduling drafts. Use the planning controls to inspect daily focus, blocked tasks, overdue commitments, and due reminders. Suggestions remain reviewable until accepted. Completing prerequisites updates blocked work; applying a local plan does not silently write an external calendar.

Life supports relationships, interactions, important dates, trips, packing items, travel documents, routines, goals, and habits. Travel items must reference an existing trip owned by the same user. Sensitive relationship and travel context remains owner-scoped.

Legacy Scheduled Tasks remains a separate compatibility surface; it is not reinterpreted as personal Work.

## 7. Calendar and Gmail

Local Calendar supports create/read/update/delete, recurrence, reminders, and ICS import/export. CalDAV remains available where configured.

Settings → Google connects one or more Google accounts using backend OAuth with state expiry/one-time consumption, PKCE, encrypted tokens, scoped connections, refresh/revocation handling, and normalized health. Gmail supports query/read, drafts, labels, archive/trash, attachments, and approved send. Google Calendar supports calendars/events, free/busy, tentative holds, create/update/delete, attendees, invitation responses, pagination/sync metadata, and deterministic readback.

Use a dedicated test account for first connection. A source-level test is not a live provider certification. Sending, invitation changes, deletion, and other consequential provider writes must pass Approval Centre and readback.

## 8. Meetings

Meetings supports manual or calendar-linked records, media upload, consent capture, queued local post-meeting transcription, timestamped segments/words, transcript editing with revisions, speaker mapping, summaries, decisions, questions, risks, claims with source links, and proposed action items. It does not claim stable real-time transcription.

Meeting jobs are durable and expose progress, cancellation, retry, interrupted-run recovery, and failure details. Review the transcript and approve action items before creating Work tasks. Explicitly save a reviewed transcript to Knowledge when desired; it is not silently promoted to memory.

## 9. Knowledge and memory

Knowledge supports owner-scoped text/file ingestion, source metadata, chunk fingerprints, lexical/vector hybrid retrieval, citations, sensitivity/access metadata, refresh/rebuild, and derivative deletion. Vector features degrade clearly when Chroma or embeddings are unavailable.

Use Document vault to analyze document-like sources for reviewable classification, expiry dates, and obligations. Every extracted obligation retains a source character span. Review and correct the metadata, sensitivity, and memory-suggestion permission before approving it; the document remains the cited source of truth.

Memory supports suggested, approved, rejected, expired, and sensitive states. Review suggestions in the Knowledge screen; edit, approve, reject, expire, or delete them. Deleting a source or derivatives is verified locally.

Treat documents, email, web pages, transcripts, tool output, saved memories, and imported skills as untrusted data. Only reviewed skills and MCP servers should be enabled.

## 10. Automations

Automations supports scheduled time, recurring interval, webhook, new email, calendar-before-event, task-due, meeting-completed, file-added, integration-event, conditional polling, and manual triggers. Definitions are validated and bounded for steps, recursion depth, rate, cooldown, and payload size.

Routine templates installs durable renewals, follow-up, weekly review, inbox triage, backup reminder, and meeting follow-up workflows. Templates install once per owner and survive restart. The workspace reports estimated attention returned only for successful routine runs; it is a transparent template estimate, not observed wall-clock time.

Runs retain step state, logs, tool calls, correlation/idempotency data, approval checkpoints, retry linkage, cancellation, failure counters, and dead-letter state. Consequential steps pause for an exact approval and resume from that step. A failed or cancelled run can be retried with a fresh idempotency key. Built-in actions include briefings, local tasks/reminders, review-only email drafts, knowledge query, research, notifications, nested workflows, declared integration calls, and encrypted scheduled backups.

Signed automation webhooks require timestamped HMAC verification and replay protection. Do not expose legacy task hooks as a substitute.

## 11. Backups and recovery

The administrative System Backup API creates a validated archive of the application data root using consistent SQLite snapshots. User-created backups require a passphrase of at least 12 characters and produce authenticated-encrypted `.ombak` exports. The instance `.app_key` is included only inside that encrypted v2 envelope so a fresh installation can decrypt restored records. Backups exclude logs, backup/restore staging, transient WAL/SHM files, unrelated private key files, and the scheduled passphrase file.

Preview validates paths, sizes, hashes, and SQLite integrity before restore staging. Staging writes a restart marker; startup applies each replacement atomically, retains rollback copies, and supports staging a completed restore rollback. Legacy unencrypted v1 archives still require the original instance key and are not portable fresh-install backups.

The mobile companion is `/static/companion.html`. Pair it from the admin-only
`/api/companion/pair` page. Its token grants chat plus owner-scoped read access
to Today, pending approvals, and due reminders; approval decisions remain in
the full authenticated application. The browser retains the token in session
storage, so closing the browser session clears it.

Run `scripts/privateos_release_check.py --restore-rehearsal` for a local release
preflight and empty-directory restore rehearsal. Record one genuine use day with
`--record-soak --owner <owner>`; `--require-soak` fails until seven consecutive
days exist. `scripts/privateos_demo.py --owner <owner> --confirm` seeds only
clearly synthetic Personal PrivateOS records and three routine templates.

External provider data, arbitrary external directories, model caches, and external Chroma volumes are not automatically included. Validate a recovery copy in isolation before relying on it.

## 12. Troubleshooting

| Symptom | Action |
| --- | --- |
| Recovery required at login | Restore a verified auth/data backup locally; never create a replacement admin over existing data. |
| No model | Start/discover an approved endpoint, refresh models, and inspect admin model-provider health. |
| Tool unavailable | Check mode, account permission, per-turn toggle, registry policy, provider health, and Approval Centre. |
| Shell reports sandbox unavailable | Keep shell off or configure a supported host OS sandbox; do not bypass it casually. |
| Google/email/calendar fails | Check connection health, account/scopes, token refresh, privacy integration toggle, and provider status. |
| Knowledge answer is weak | Check embedding/vector health, source status and citations; lexical fallback may be active. |
| Meeting job failed | Inspect its error, correct provider/media configuration, then use Retry. |
| Automation awaits approval | Open Approval Centre and review the exact paused step. |
| Action result is indeterminate | Do not blindly retry; reconcile the provider/resource first. |
| `/api/ready` is 503 | Inspect the administrator diagnostics report and local logs. |

## 13. Verification boundary

Automated tests certify local contracts, not credentials or third-party availability. Before production use, the operator must run the platform installer, launch/readiness checks, browser acceptance, provider-specific sandbox-account tests, encrypted backup restore drill, and any GPU/runtime tests applicable to that installation.
