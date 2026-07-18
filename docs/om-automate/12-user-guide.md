# OM Automate User Guide

## 1. Product status notice

This guide covers the audited application while it is being transformed from Odysseus into OM Automate. The current build is useful, but it is **not the finished OM Automate product**.

What you may notice today:

- many screens, browser titles, and messages still say **Odysseus**;
- ordinary chat, conversations, tasks, notes, local calendar, documents, email, contacts, search, research, memory, skills, and model settings have real implementations;
- the audited native baseline successfully exercised login, local-model chat, task/note creation, calendar and setup entry points, restart persistence, and logout;
- Google/Gmail/Calendar side effects, complete knowledge indexing, meeting workflows, backup/restore, and most external providers were not live-certified;
- the unified OM approval centre, granular permissions, verified provider actions, native Google Calendar adapter, projects, meeting records, and target automation engine do not exist yet.

Throughout this guide:

- **Available now** means a current UI/service path exists. It may still depend on configuration and may have a stated safety limitation.
- **Target** describes intended OM Automate behavior and is not available unless the current screen explicitly provides it.

If you are using personal or production data, ask the administrator which build, providers, and features they have certified before relying on them.

## 2. Getting started

### 2.1 Sign in

1. Open the private URL supplied by your administrator. A default local installation normally uses a loopback address such as `http://127.0.0.1:7000`; the audited macOS launcher used port `7860`.
2. Confirm that the address belongs to the expected installation. Do not enter credentials into an unexpected public host.
3. Sign in with the account created by the administrator.
4. Change a temporary password immediately.
5. Enable two-factor authentication in account settings when required by your administrator.
6. Log out when using a shared device.

Invalid credentials should be rejected without opening the application. If the login screen unexpectedly asks to create the first administrator on an installation that was already configured, stop and contact the administrator; damaged authentication state can currently reopen first-run setup.

### 2.2 Choose a model

The current model picker can use discovered local models or endpoints configured under Settings → Services/Added models.

For a private local session:

1. Ask the administrator to start and approve a local model runtime such as Ollama or another OpenAI-compatible server.
2. Select a model in the chat model picker.
3. Start with an ordinary, non-agent prompt such as “Reply with the word ready.”
4. Confirm that the response card shows the model you expected.

A model being able to chat does not prove it can use tools safely. The target product will require model capability profiles and minimum tool-use tests; that certification is not implemented yet.

### 2.3 Understand data egress

“Local-first” does not mean every request remains on the device. Content can leave the host when you select or enable:

- a hosted/API model;
- Gmail, IMAP/SMTP, CalDAV/CardDAV, or another external account;
- web search, page retrieval, research, or YouTube transcript retrieval;
- image, speech, notification, webhook, generic REST, or MCP integrations;
- a remote model or Cookbook/SSH host.

Before sending sensitive content, check the selected model, enabled integrations, search toggle, attachments, and workspace. The current UI does not yet provide the target per-request privacy/routing summary.

## 3. Using chat

### 3.1 Ordinary chat

Available now:

1. Open Chat and create or select a conversation from the sidebar.
2. Select the intended model.
3. Type a request and submit it.
4. Use the Stop control if you no longer want the response.
5. Rename, archive, search, fork, edit, compact, or export a conversation using the available conversation controls.

Messages and conversation metadata are stored in the main local database. Restart persistence was verified in the native baseline.

### 3.2 Attachments and context

You can attach supported files, select a workspace, and enable context features such as knowledge or web search. Treat every attached document, email, web page, transcript, and tool result as potentially untrusted. Embedded instructions inside a source do not become user instructions, but the current prompt-injection boundary is not yet strong enough for broad autonomous actions.

Only attach content you intend the selected provider to process. A hosted model may receive extracted attachment text or other assembled context.

### 3.3 Agent mode and tools

The current Agent toggle can invoke application, web, filesystem, shell, Python, and MCP tools depending on account/admin settings. It does not yet have the target typed registry, granular scopes, general approval workflow, durable action records, or deterministic verification.

Use these rules on the current build:

- Prefer ordinary chat for summaries, drafting, analysis, and questions.
- Use agent tools only in a disposable/test workspace unless the administrator has reviewed and constrained that tool.
- Do not authorize shell, Python, broad filesystem, bulk email, deletion, security changes, or external writes for routine personal use.
- Ask for a proposal or draft first, then perform/review the final change in the relevant UI.
- Verify every consequential result in the source system. A model statement that an action succeeded is not proof.
- If Stop is used, local owned tool tasks now cancel and their cards settle as `cancelled`; a remote provider may nevertheless have committed an effect. Check provider state before retrying.

The current application can expose raw model reasoning under a “thinking process” view. Do not treat it as a reliable explanation or audit record. The target UI will show concise action summaries without hidden chain-of-thought.

### 3.4 Incognito warning

Do not use the current Incognito toggle for sensitive information. The current implementation commits incognito messages to SQLite and deletes them later; it is not a truly non-persistent session. Use a dedicated disposable installation and a local model when non-persistence is required, or wait for the documented incognito fix and its database/file/log/vector tests.

## 4. Actions and approvals

### Current behavior

There is no complete general approval centre. A chat clarification card is not a policy approval. Text such as “I need confirmation” is not necessarily backed by a durable pending action, exact argument hash, expiry, or permission check.

Email has a backend-specific pending-send mechanism for some agent calls, but its structured state is flattened and there is no complete generic approval UI. Direct GUI send can transmit immediately.

For the current build:

1. Ask OM/the model to **draft**, not send or delete.
2. Open the domain UI and inspect recipients, dates, accounts, attachments, recurrence, and affected records.
3. Make the final consequential change yourself only when it is correct.
4. Read the created/changed record back from the provider.
5. If an outcome is unclear, do not retry automatically; ask the administrator to reconcile it.

### Target behavior

The finished OM Automate approval centre will show pending actions with exact arguments, affected records, risk, reason, source conversation, expiration, edit history, and approve/reject controls. Level 2 external actions will require confirmation by default; Level 3 destructive/sensitive actions will always require explicit confirmation. Approval and provider readback are release blockers, not current guarantees.

## 5. Calendar

### Available now

The Calendar panel supports local calendars and event create/read/update/delete operations, recurring events, ICS import/export, a natural-language quick parser, and reminders through the shared note-reminder path. A CalDAV account path and bidirectional sync logic also exist.

To use a local calendar:

1. Open Calendar.
2. Select or create a local calendar.
3. Create an event and review title, start/end, timezone, recurrence, location, and reminder fields.
4. Reopen the event after saving to confirm the stored values.
5. Use ICS import/export when exchanging data with another calendar system; verify imported timezone and recurrence behavior before relying on it.

To use CalDAV, ask the administrator to configure and test a dedicated account and full collection URL. Live CalDAV/Google credentials were not exercised during the audit, so a test button or source-level test is not provider certification.

### Not available as the target product

There is no native provider-neutral Google Calendar OAuth adapter with Google sync tokens, account/scopes UI, attendee/invitation workflows, conference data, or deterministic provider readback. Conflict-aware scheduling, travel/preparation buffers, focus rules, relationship context, and calendar briefings are target features.

Do not ask the current agent to bulk move/delete meetings or send invitations. Make a proposed plan, inspect it, and apply changes in the Calendar/provider UI.

## 6. Gmail and email

### Connect an account

Settings → Email exposes current IMAP/SMTP account configuration and a Gmail OAuth code path. The exact account fields depend on the provider. Use a dedicated test account first and let the administrator supply OAuth client configuration or approved mail-server settings.

Current Gmail OAuth was covered by automated tests but not a live Google grant. It does not yet meet every target requirement for state expiry/one-time use, PKCE, scope minimization, revocation, and unified connection health. Never paste an access or refresh token into chat.

### Read, organize, and draft

Available current paths include:

- inbox/folder listing, search, message/thread reading, unread counts, and attachments;
- read/unread, flag, archive, move, spam, and delete operations;
- compose, drafts, reply, scheduled email, summary, translation, and AI-assisted reply;
- remote IMAP/SMTP/Gmail behavior when a compatible account is correctly configured.

Recommended current workflow:

1. Open Email and confirm the active account.
2. Read the full thread and verify sender/recipients before drafting.
3. Create a draft or ask the model for draft text.
4. Inspect To/Cc/Bcc, subject, quoted history, attachments, and account identity.
5. Send from the Email UI only after review.
6. Confirm the message appears in the provider's Sent state/thread.

The current app does not guarantee agent-wide approval or readback for send/delete/bulk actions. Avoid using chat for those effects. “Write a reply” should be treated as drafting, but the current architecture cannot enforce that policy across every tool path.

## 7. Tasks, notes, reminders, and projects

### Tasks

The current Tasks panel is primarily a scheduled-task and workflow system. It can create persistent one-time/recurring work, retain run rows, deliver output to sessions/notifications, and invoke agent or shell/provider paths depending on configuration.

Use it conservatively:

1. Create a small local task with a clear title and schedule.
2. Avoid powerful tools and external side effects in the first run.
3. Review run status/output and application logs.
4. Restart once in a test environment and confirm the next schedule is correct.
5. Disable the task after repeated failures or any uncertain side effect.

Runs are not yet durable/resumable in the target sense. A restart can abort stale runs rather than continue them, and current step history is incomplete. Do not build safety-critical or exactly-once routines on this engine.

### Notes and reminders

Notes support text/checklist records, pinning, archiving, due dates, ordering, and reminders. Reminder channels can include browser, email, ntfy, or webhook depending on administrator configuration. Browser notification delivery currently depends on process-local state, so verify delivery on the actual device and keep an independent reminder for critical deadlines.

### Projects and commitments

The target unified project, dependency, milestone, and commitment-tracking model does not exist. Use tasks, notes, documents, and calendar links as separate current features; do not assume OM can reliably infer or track every promise across email/meetings.

## 8. Meetings and transcription

The current app has voice recording/upload and speech-to-text service paths, but no dedicated meeting record, stable live transcription, speaker diarization, timestamp-linked decisions, action-item approval workflow, or meeting archive.

Current safe use is limited to:

1. record or upload a short non-sensitive test clip where the browser/provider is configured;
2. review and correct the transcript manually;
3. save a summary as a note/document if desired;
4. create tasks manually from confirmed action items.

Do not describe the result as a source-linked meeting record, and do not treat inferred decisions as confirmed facts. Local transcription quality was not live-certified in the audit.

## 9. Knowledge, documents, memory, and skills

### Documents and notes

The document library/editor supports document creation, editing, versions, archive/restore, PDF import/render/export, and drafts. Open or export an important result after saving to confirm it is usable. Signed-PDF flows exist in code but were not end-to-end verified.

### Knowledge and RAG

The Brain/Knowledge Add flow can register directories and uploads for retrieval. Chroma and an embedding provider are needed for the complete vector path; when unavailable, some areas degrade to lexical behavior. The audited minimal native launch did not have Chroma running.

Before importing sensitive material:

1. confirm the selected model/embedding provider and whether content leaves the host;
2. confirm Chroma/embedding health with the administrator;
3. import a small test source;
4. ask a question whose answer you already know;
5. inspect cited/source context where available;
6. test deletion and index behavior before importing the full collection.

The target system will provide hybrid retrieval, source-linked claims, sensitivity/retention controls, and verified deletion of every indexed derivative. Those guarantees are not complete today.

### Memory

Current memory supports viewing, adding, searching, editing, pinning, and deleting owner-scoped records. Vector retrieval can degrade when embeddings fail. Review stored memories rather than assuming every extracted fact is correct. The target suggested/approved/rejected/expired/sensitive memory lifecycle is not complete.

### Skills and MCP

Skills can modify model context and tools can expand authority. Import only reviewed skills. MCP servers may run local packages/processes and can currently receive a broader environment than the target security model permits. Only an administrator should install/configure MCP, pin reviewed packages, and constrain its tools.

## 10. Research, search, and web content

Web search, page fetch, YouTube transcript context, and deep research have current implementations. Search/page content is marked untrusted in prompts, but it can still be incorrect or malicious.

For important research:

- inspect the source pages and publication dates;
- distinguish retrieved statements from the model's inference;
- do not let a page/email/document instruct the agent to use tools;
- do not enter secrets requested by retrieved content;
- verify facts independently before making a consequential decision.

Search availability and privacy depend on the configured provider. SearXNG was unavailable in the audited native baseline.

## 11. Automations and proactive assistance

Current scheduled tasks, daily assistant check-ins, email triage paths, reminders, notification channels, and task webhooks are useful legacy building blocks. They are not the target structured automation engine.

Missing target guarantees include durable step state, common action approvals, idempotency keys, loop/depth/rate controls, dead-letter handling, provider verification, complete run history, and safe restart/resume.

Until those exist:

- keep automations read-only or locally reversible;
- avoid unattended email sends, calendar writes, deletion, shell, bulk work, and security changes;
- use dedicated test accounts;
- review every first run and failure;
- disable a workflow after an unknown result rather than rerunning it;
- do not expose the current task webhook directly to the internet; its inbound authentication/replay controls are incomplete.

## 12. Privacy and security controls

Current controls include login, users, two-factor authentication, coarse feature privileges, local-first defaults, some encrypted credential fields, prompt boundaries, path confinement, SSRF defenses for selected web paths, and administrator gates for powerful tools.

Current limitations users must understand:

- permissions are coarse and do not expose target scopes such as `email.send` or `calendar.delete`;
- there is no immutable unified action/audit history;
- incognito content reaches SQLite before later cleanup;
- shell/Python/MCP processes can receive sensitive application environment values;
- broad file roots can include application data;
- selected hosted providers/search/integrations can receive content;
- backups currently combine private data and decryption material in an unencrypted gzip archive;
- raw model reasoning may be displayed.

Practical user habits:

1. Use a strong unique password and 2FA.
2. Keep the app on the private URL supplied by the administrator.
3. Select a local model for sensitive work when possible.
4. Review attachments, workspace, search, and provider selection before submitting.
5. Never paste passwords, API keys, OAuth tokens, recovery codes, or private SSH keys into chat.
6. Treat agent tools as privileged and verify results outside chat.
7. Export or delete data only after confirming backup and retention consequences with the administrator.

## 13. Backups and exports

The Settings/admin export/import feature covers selected application data and is useful for interchange. It is **not** a complete disaster-recovery backup of databases, files, keys, external volumes, and provider state.

For a complete backup, ask the administrator to follow [15-deployment-guide.md](15-deployment-guide.md#14-backup-plan) and [11-migration-guide.md](11-migration-guide.md#4-current-pre-migration-protection-procedure). A valid recovery copy must be encrypted/restricted, verified, restored in isolation, and include the matching `.app_key` plus Docker Chroma or other required external storage.

External provider records are not stored in the local backup. After restore, the administrator must revalidate credentials and reconcile remote email/calendar state before automations resume.

## 14. Troubleshooting

| Symptom | What to do |
| --- | --- |
| Login unexpectedly offers first-admin setup | Stop and contact the administrator. Do not create a new admin over a previously configured installation. |
| No model is available | Ask the administrator to start/discover a local runtime or configure/test an approved endpoint; then refresh the model list. |
| Chat streams but tools do not work | Use ordinary chat. The tool may be disabled, unavailable, permission-gated, or absent from the fragmented current registry. |
| Stop was pressed during an external action | Do not retry. Check the provider/domain UI and ask the administrator to reconcile the result. |
| Knowledge answers are weak/missing | Confirm Chroma and embedding health; test with a small known source; lexical fallback may be active. |
| Email/calendar connection fails | Confirm the correct account, collection/server URL, scopes, and provider status. Do not paste tokens into chat. |
| Reminder did not arrive | Check the note/task state and configured channel; browser notifications and process-local queues may have been interrupted. |
| A scheduled task is stuck/aborted after restart | Disable it, inspect run/log state, and rerun only if the action is known not to have happened. |
| The interface still says Odysseus | Expected on the audited transformation branch. Visible rebranding is a future milestone; legal references will remain intentionally. |
| `/api/ready` or service status looks unhealthy | Contact the administrator. Current readiness requires authentication and does not cover every dependency. |
| Private data may have reached the wrong provider | Stop using the integration, preserve details without copying more content, and follow the administrator's incident process. |

Application-specific operational issues and ports are covered in [15-deployment-guide.md](15-deployment-guide.md#18-troubleshooting).

## 15. Target OM Automate experience

The following experiences are requirements, not current instructions:

| Target experience | Current status |
| --- | --- |
| One primary assistant named OM across the UI | Not implemented; legacy names/personas remain. |
| Today dashboard and grounded morning/weekly briefings | Not implemented as the target cross-domain product. |
| Unified approval centre and risk levels | Not implemented. |
| Typed, scoped, audited, verified actions | Not implemented; safety foundation is in progress. |
| Native Google account manager for Gmail and Calendar | Not implemented as one complete provider-neutral connection. |
| Unified tasks, projects, dependencies, and commitments | Partial legacy task/scheduler features only. |
| Meeting records, diarized transcripts, decisions, and source-linked action items | Not implemented. |
| Hybrid, source-grounded knowledge with complete deletion | Partial current RAG/memory paths. |
| Structured, resumable, loop-safe automations | Partial legacy scheduled tasks only. |
| Per-request privacy/routing visibility and granular scopes | Not implemented. |
| Full encrypted backup, restore preview, and tested recovery | Current CLI snapshot is partial and unencrypted. |

Do not rely on a target capability until its UI, provider behavior, automated tests, manual browser test, migration evidence, and release status all say it is available.
