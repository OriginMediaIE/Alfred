# OM Automate integration register

**Baseline inspected:** om-automate/main at 9844a2f9a1996b8c8135a9e7bbde6a72f41df5ed
**Audit date:** 2026-07-18
**Status:** Current adapters, configuration, health surfaces, tools, UI, and tests are registered below. Provider-neutral contracts and migration steps are target design and are not yet implemented.

## 1. Evidence and status rules

This register covers external providers, self-hosted network services, local model/speech/media runtimes, operating-system bridges, MCP servers, client API bridges, webhooks, and provider-facing content fetches.

The native baseline verified:

- the authenticated application UI;
- a local Ollama model at the configured endpoint using qwen3:1.7b;
- connection of the built-in image, memory, RAG, and email Python MCP servers;
- local records and restart persistence.

It did **not** verify a live credentialed Gmail, Google Calendar, CalDAV, CardDAV, IMAP, SMTP, cloud search, cloud model, remote MCP, transcription, speech, image-generation, vault, ntfy, SearXNG, ChromaDB, Docker, SSH, or webhook provider. Source-level and mocked test coverage must not be reported as a successful provider connection.

### Status vocabulary

| Status | Meaning |
|---|---|
| **Verified local** | Exercised against a real local runtime during this audit. |
| **Connected local** | Process/protocol connection was observed, but its complete feature flow was not exercised. |
| **Code/test only** | Implementation and automated tests exist; no live credentialed provider was used. |
| **Degraded** | Feature was configured or expected but an optional dependency/service was unavailable. |
| **Unavailable** | Attempted in the baseline and could not start/connect. |
| **Placeholder** | UI/configuration hint exists without the required provider implementation. |
| **Target** | Contract required for OM Automate; not current code. |

Automated tests named below were part of the 4,527-test audited suite. The suite passed across isolated reruns; provider tests are predominantly mocked, stubbed, structural, or static.

## 2. Current integration architecture

There is no single provider registry or connection lifecycle. Integrations are configured through several unrelated stores and dispatch paths.

| Integration family | Current configuration authority | Secret mechanism | Main runtime path |
|---|---|---|---|
| Model and media endpoints | model_endpoints and provider_auth_sessions in app.db | EncryptedText using data/.app_key | src/endpoint_resolver.py, src/llm_core.py, routes/model_routes.py |
| Generic REST APIs | data/integrations.json | api_key encrypted using data/.app_key; URL may carry a secret | src/integrations.py, routes/auth_routes.py, agent api_call |
| IMAP/SMTP/Gmail OAuth | email_accounts in app.db plus Google client environment variables | Password/token helpers using .app_key | routes/email_routes.py, routes/email_helpers.py, mcp_servers/email_server.py |
| CalDAV | Per-user caldav_accounts inside user_prefs.json | Password encrypted using .app_key | routes/calendar_routes.py, src/caldav_sync.py |
| CardDAV | Settings/environment plus contacts.json fallback/cache | Configured password encrypted by settings helpers | routes/contacts/contacts_routes.py |
| Search | settings.json and selected environment fallbacks | Selected settings keys encrypted/scrubbed | services/search, src/search compatibility wrappers |
| Embeddings | embedding_endpoint.json or environment | API key encrypted in the JSON store | src/embedding_manager.py, src/chroma_client.py |
| MCP | mcp_servers in app.db and data/mcp_oauth files | oauth_tokens encrypted; env/args can be plaintext | src/mcp_manager.py, src/mcp_oauth.py, routes/mcp_routes.py |
| Vault CLI | vault.json | File mode plus stored CLI session | routes/vault_routes.py |
| Webhooks and API clients | webhooks and api_tokens in app.db; scheduled-task webhook token | Outbound secret encrypted on current create path; API token hash; inbound task token plaintext | src/webhook_manager.py, routes/webhook_routes.py, routes/task_routes.py |
| Local runtime orchestration | cookbook_state.json, bg_jobs files, environment, SSH/Docker/tmux | Host SSH and process environment outside the app secret broker | routes/cookbook_routes.py and helpers |

Consequences:

- connection state has no common connected, expired, degraded, rate-limited, or repair-required lifecycle;
- health checks, credential rotation, scopes, rate limits, retries, idempotency, retention, and uninstall behaviour vary by feature;
- several configurations are installation-global when the data they expose is user-specific;
- models and tools can reach provider code through multiple dispatch systems;
- secret references are not typed and can leak into JSON, environment, command arguments, URLs, chat headers, or logs.

## 3. Health and diagnostics baseline

| Surface | What it proves | What it does not prove |
|---|---|---|
| GET /api/health | Application process responds | Database writes, provider credentials, queues, vectors, mail, search, or model inference |
| GET /api/ready | Authenticated database/data-directory readiness | External providers and most local dependencies; unauthenticated infrastructure probes receive 401 |
| GET /api/diagnostics/services | Bounded, sanitized aggregate checks for Chroma manager flags, SearXNG reachability, configured ntfy, enabled IMAP accounts, and model endpoint discovery | Gmail OAuth refresh, SMTP send, CalDAV/CardDAV, generic REST, MCP tools, STT/TTS, image generation, scheduler, storage capacity, webhook delivery, or end-to-end agent action |
| Provider-specific Test buttons | The selected integration's implemented probe or test side effect | Long-term health, scopes, all capabilities, webhook replay safety, or background reconciliation |

src/service_health.py sanitizes URLs/errors, limits fan-out, and avoids test searches or ntfy pushes. The generic integration Test route is different: ntfy and Discord tests intentionally send a real notification/embed.

The target must separate:

- passive health, safe to poll;
- authentication validation;
- capability checks;
- synthetic test writes with explicit user acknowledgement and cleanup;
- end-to-end production telemetry.

## 4. Model and inference integrations

### 4.1 Shared model implementation

**Code paths:** routes/model_routes.py, src/endpoint_resolver.py, src/llm_core.py, src/ai_interaction.py, src/chatgpt_subscription.py, and src/copilot.py.
**Configuration:** model_endpoints fields include base_url, encrypted api_key, owner, model_type, endpoint_kind, refresh mode/interval/timeout, cached/hidden/pinned model IDs, supports_tools, and optional provider_auth_id. LLM_HOST, LLM_HOSTS, OLLAMA_BASE_URL, and LM_STUDIO_URL participate in local discovery/defaults.
**Models:** model IDs are normally discovered from the provider model-list endpoint or pinned by the operator; the repository does not freeze a supported model catalog. Capability is partly inferred from URL/model names and may be overridden by supports_tools.
**Health:** endpoint model-list probe and optional tool-call probe; aggregate diagnostics reports model endpoints. A model-list success does not prove streaming, tool calls, context size, image/audio support, billing, or model availability at action time.
**UI:** Settings/Admin → AI/model endpoints and chat model picker.
**Agent tools:** list_models, chat_with_model, ask_teacher, manage_endpoints; ordinary chat and scheduled/research flows also select endpoints.
**Representative tests:** test_model_endpoint_owner_scope.py, test_model_endpoint_secret_encryption.py, test_model_provider_detection.py, test_model_tool_probe.py, test_llm_core_sse_no_space.py, test_chatgpt_subscription.py, and Copilot/device-flow tests.
**Observed status:** only local Ollama with qwen3:1.7b was live-verified.

### 4.2 Provider and runtime matrix

| Provider/runtime | UI preset or base | Adapter/protocol and credential | Models/capabilities | Current status |
|---|---|---|---|---|
| Ollama local | Default local host, commonly http://localhost:11434 | Native /api/chat and /api/tags or OpenAI-compatible /v1; normally no key | Discovered installed models; native tool-call parsing supported | **Verified local** with qwen3:1.7b. No complete agent side-effect/tool-capability certification. |
| LM Studio | LM_STUDIO_URL or discovered local OpenAI-compatible endpoint | /v1/models and /v1/chat/completions; optional key | Whatever the local server exposes | **Code/test only** |
| APFEL on Apple Silicon | start-macos.sh can run apfel --serve --port 11435; model discovery scans port 11435 | Local sibling model server; Homebrew-managed binary | Models/capabilities exposed by APFEL | **Code/test only**; not started in the native baseline |
| llama.cpp | Custom/Cookbook local endpoint | OpenAI-compatible server, normally /v1 | Loaded model determined by server command | **Code/test only** |
| vLLM and SGLang | Custom/Cookbook local or SSH-hosted endpoint | OpenAI-compatible server; optional key; tool flags inferred from launch command | Loaded Hugging Face model; server may advertise tool support | **Code/test only** |
| Other OpenAI-compatible local server | Custom URL | /v1/models and /chat/completions; optional key | Discovered or pinned | **Code/test only** |
| Anthropic | https://api.anthropic.com | Native Anthropic messages handling; API key stored in ModelEndpoint | Operator-selected/discovered model IDs; special payload/stream parsing | **Code/test only** |
| OpenAI | https://api.openai.com/v1 | OpenAI-compatible chat/models; static API key | Discovered/pinned text and image model IDs | **Code/test only** |
| DeepSeek | https://api.deepseek.com/v1 | OpenAI-compatible bearer key | Discovered/pinned | **Code/test only** |
| OpenRouter | https://openrouter.ai/api/v1 | OpenAI-compatible with provider-specific headers/handling | Aggregated model catalog | **Code/test only** |
| Ollama Cloud | https://ollama.com/api | Native Ollama cloud path with key | Provider catalog | **Code/test only** |
| Groq | https://api.groq.com/openai/v1 | OpenAI-compatible bearer key | Provider catalog | **Code/test only** |
| Mistral | https://api.mistral.ai/v1 | OpenAI-compatible bearer key | Provider catalog | **Code/test only** |
| Together AI | https://api.together.xyz/v1 | OpenAI-compatible bearer key | Provider catalog | **Code/test only** |
| Fireworks AI | https://api.fireworks.ai/inference/v1 | OpenAI-compatible bearer key | Provider catalog | **Code/test only** |
| Google Gemini OpenAI compatibility | https://generativelanguage.googleapis.com/v1beta/openai | OpenAI-compatible key | Gemini models available through that compatibility API | **Code/test only**; not a native Gemini adapter claim. |
| xAI Grok | https://api.x.ai/v1 | OpenAI-compatible bearer key | Provider catalog | **Code/test only** |
| Z.AI | https://api.z.ai/api/paas/v4 | OpenAI-compatible bearer key | Provider catalog | **Code/test only** |
| Z.AI Coding Plan | https://api.z.ai/api/coding/paas/v4 | OpenAI-compatible bearer key | Coding-plan catalog | **Code/test only** |
| OpenCode Zen | https://opencode.ai/zen/v1 | OpenAI-compatible with special provider detection | Provider catalog | **Code/test only** |
| OpenCode Go | https://opencode.ai/zen/go/v1 | OpenAI-compatible with special provider detection | Provider catalog | **Code/test only** |
| NVIDIA | https://integrate.api.nvidia.com/v1 | OpenAI-compatible bearer key | NIM/provider catalog | **Code/test only** |
| Moonshot/Kimi | Custom Moonshot/Kimi endpoint | OpenAI-compatible with URL and temperature/user-agent special cases | Provider catalog | **Code/test only** |
| Kimi Code | https://api.kimi.com/coding/v1 | OpenAI-compatible subscription key with provider-specific User-Agent retry handling | kimi-for-coding curated when advertised | **Code/test only** |
| Venice | https://api.venice.ai/api/v1 | OpenAI-compatible bearer key; recognized as a cloud API host | Provider catalog | **Code/test only** |
| Cerebras | Custom Cerebras endpoint | OpenAI-compatible with provider detection | Provider catalog | **Code/test only** |
| GitHub Copilot | copilot UI device-auth flow | Device flow; encrypted provider_auth_sessions; provider-specific runtime headers | Models returned through Copilot integration | **Code/test only**; no live GitHub authorization. |
| ChatGPT Subscription | chatgpt-subscription UI device-auth flow | OpenAI device/subscription session; encrypted access/refresh state; Responses-style backend adapter | Subscription-exposed models | **Code/test only**; no live authorization. |
| Arbitrary cloud OpenAI-compatible | Custom URL | ModelEndpoint base URL and encrypted API key | Discovered or pinned | **Code/test only**; compatibility must be certified per provider, not assumed. |

Static preset presence is not a support guarantee. Each provider needs an owned compatibility profile covering authentication, model discovery, streaming, structured tool calls, errors, usage, retries, rate limits, data handling, and removal.

## 5. Embeddings and vector service integrations

| Integration | Paths/config/secrets | Health, UI, tools, tests | Status |
|---|---|---|---|
| ChromaDB HTTP | src/chroma_client.py; CHROMADB_HOST and CHROMADB_PORT, native default localhost:8100; Docker service chromadb:8000; Docker data in chromadb-data | Chroma flags in /api/diagnostics/services; Knowledge/RAG and memory UI; manage_rag/manage_memory consumers; test_chroma_client.py and lane/owner tests | **Degraded/unavailable** in native baseline; no running Chroma |
| FastEmbed | Local sentence-transformers/all-MiniLM-L6-v2 default; FASTEMBED_CACHE_PATH; lane-specific collections | Embedding settings/RAG status; semantic tool index/RAG/memory; test_embedding_lanes_rag.py and memory lane tests | **Code/test only**; optional dependency/model execution not live-verified |
| Custom OpenAI-compatible embeddings | embedding_endpoint.json or EMBEDDING_URL, EMBEDDING_MODEL, EMBEDDING_API_KEY; POST /v1/embeddings; encrypted API key | Settings → Embeddings, endpoint test/status, RAG/memory; embedding endpoint and dimension/fingerprint tests | **Code/test only** |

Target requirement: embeddings are provider connections with explicit model, dimension, fingerprint, privacy/egress classification, batching and rate limits. Canonical knowledge never depends on vector availability.

## 6. Email integrations

### 6.1 IMAP and SMTP

| Field | Current implementation |
|---|---|
| Code paths | routes/email_routes.py, routes/email_helpers.py, routes/email_pollers.py, and mcp_servers/email_server.py |
| Configuration | email_accounts in app.db: IMAP host/port/user/password/STARTTLS, SMTP host/port/security/user/password, from/display name, default/enabled, owner |
| Secrets | Passwords are encrypted through current helpers; application decrypts for connection. Mail attachment cache may hold provider content on disk. |
| Models | Optional configured LLM performs summaries, replies, translations, urgency, event extraction, and signature learning; there is no dedicated email-provider model. |
| Health | Account test endpoints can test IMAP/SMTP; aggregate diagnostics performs IMAP connect/logout only. It does not send mail. |
| UI | Settings → Email and Email/Inbox/Library/Composer |
| Agent tools | list_email_accounts, list_emails, search_emails, read_email, download_attachment, send_email, draft_email, reply_to_email, draft_email_reply, ai_draft_email_reply, archive_email, delete_email, mark_email_read, bulk_email |
| Tests | test_email_owner_scope.py, test_email_oauth.py, test_email_imap_timeout.py, test_icloud_imap_full_fetch.py, test_email_account_port_validation.py, test_email_send_only_no_inbox.py, and email cache/schedule/security tests |
| Status | **Code/test only.** No credentialed IMAP or SMTP provider was exercised. |

The Settings UI exposes these exact convenience presets; all use the same IMAP/SMTP adapter and shared health/tools/tests above:

| Preset | IMAP | SMTP | Auth/status |
|---|---|---|---|
| Gmail | imap.gmail.com:993 implicit TLS | smtp.gmail.com:465 SSL | App password form; **code/test only** |
| Google Workspace / .edu | imap.gmail.com:993 implicit TLS | smtp.gmail.com:587 STARTTLS | Google OAuth/XOAUTH2 path; **code/test only** |
| Migadu | imap.migadu.com:993 implicit TLS | smtp.migadu.com:465 SSL | Password/app credential; **code/test only** |
| iCloud | imap.mail.me.com:993 implicit TLS | smtp.mail.me.com:587 STARTTLS | Apple app-specific password; **code/test only** |
| Outlook / Office 365 | outlook.office365.com:993 implicit TLS | smtp.office365.com:587 STARTTLS | **Placeholder:** Microsoft OAuth/Graph is absent and normal-password auth is generally disabled |
| Fastmail | imap.fastmail.com:993 implicit TLS | smtp.fastmail.com:465 SSL | Password/app credential; **code/test only** |
| Yahoo | imap.mail.yahoo.com:993 implicit TLS | smtp.mail.yahoo.com:465 SSL | Yahoo app password; **code/test only** |
| Dovecot IMAP | Operator host, default UI port 31143 without STARTTLS | None by preset | Local/read-only convenience preset; **code/test only** |
| Custom | Operator host/port/TLS and optional separate credentials | Operator host/port and SSL, STARTTLS, or none | Covers custom domains and local bridges such as Proton Mail Bridge; **code/test only** |

### 6.2 Gmail OAuth

| Field | Current implementation |
|---|---|
| Authorization routes | /api/email/oauth/google/authorize and /api/email/oauth/google/callback |
| Client configuration | GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, optional GOOGLE_OAUTH_REDIRECT_URI |
| Requested scopes | https://mail.google.com/ and email |
| Token endpoints | Google authorization, oauth2.googleapis.com/token, and OAuth userinfo |
| Storage | oauth_provider, encrypted access/refresh token, and expiry in email_accounts |
| Runtime use | XOAUTH2 framing for Gmail IMAP and SMTP; this is not a Gmail REST API provider |
| Health/UI/tools/tests | Email account UI and tools above; test_email_oauth.py covers state, owner scope, token storage/refresh, and XOAUTH2 with mocks |
| Status | **Code/test only.** No live Google grant or mailbox operation was performed. |

A provider-neutral Gmail adapter is still required if OM Automate intends to use Gmail API resource IDs, history cursors, labels, watch notifications, idempotent drafts/sends, and provider-specific verification.

## 7. Calendar and contacts integrations

### 7.1 CalDAV

| Field | Current implementation |
|---|---|
| Code paths | routes/calendar_routes.py and src/caldav_sync.py |
| Configuration | Per-user caldav_accounts array inside user_prefs.json: id, label, URL, username, encrypted password |
| Protocol | python-caldav discovery/REPORT plus create/update/delete write-through; Basic/Digest test support; redirects disabled for security |
| Local model | calendars, calendar_events, and caldav_deleted_events in app.db; remote href/etag and pending create/update/delete marker |
| Google-specific compatibility | Recognizes https://apidata.googleusercontent.com/caldav/v2/ID/user and legacy https://www.google.com/calendar/dav/ID/user, mapping principal to events collection |
| Health | /api/calendar/test performs PROPFIND; /api/calendar/sync reports counts/errors. Not included in aggregate diagnostics. |
| UI | Calendar and Settings → Integrations → CalDAV |
| Agent tool | manage_calendar operates on the local service, which writes through for CalDAV calendars |
| Tests | test_caldav_bidirectional_sync.py, test_caldav_writeback.py, test_caldav_url_hardening.py, test_caldav_google_principal_url.py, owner/collision/tombstone tests |
| Status | **Code/test only.** No live CalDAV or Google Calendar account was exercised. |

This is not a native Google Calendar API/OAuth adapter. There is no Google Calendar provider connection with OAuth scopes, syncToken, event IDs, conference data, attendees, watch channels, or deterministic provider readback.

### 7.2 CardDAV and local contacts

| Field | Current implementation |
|---|---|
| Code paths | routes/contacts/contacts_routes.py and contact helpers |
| Configuration | carddav_url, carddav_username, encrypted carddav_password in settings, with CARDDAV environment fallbacks; contacts.json local fallback/cache |
| Protocol | CardDAV/vCard CRUD and search/import/export |
| Health | Contact config test routes; no aggregate health |
| UI | Contacts plus Settings → Integrations/contacts |
| Agent tools | resolve_contact and manage_contact |
| Tests | test_contacts_vcard_parse.py, test_contacts_carddav_security.py, test_contacts_import_nonstring.py, contact owner/security tests |
| Status | **Code/test only.** No live CardDAV provider was exercised. contacts.json has an unclear global ownership boundary. |

## 8. Search, web, and research integrations

### 8.1 Search providers

Shared code lives in services/search with src/search compatibility wrappers. Current settings include search_provider, search_url, search_fallback_chain, safe-search controls, provider keys, Google PSE CX, and a research-specific override. UI is Settings → Web Search. Agent tools are web_search and research flows. Representative tests include test_search_config_provider_key.py, test_search_provider_json.py, test_search_config_no_key_leak.py, and provider fallback/safe-search tests.

| Provider | Config and secret | Protocol/health | Current status |
|---|---|---|---|
| SearXNG | search_url or SEARXNG_INSTANCE; no key by default; general engines can use SEARXNG_GENERAL_ENGINES | JSON search endpoint; passive /healthz/root probe in aggregate diagnostics | **Degraded/unavailable** in baseline; service was not running |
| DuckDuckGo | No key | Direct library/HTTP search fallback; rate-limited; no aggregate probe | **Code/test only** |
| Brave Search | brave_api_key setting, legacy search_api_key, or DATA_BRAVE_API_KEY | Brave Search API; no aggregate provider probe | **Code/test only** |
| Google Programmable Search Engine | google_pse_key or legacy search_api_key or GOOGLE_API_KEY, plus google_pse_cx or GOOGLE_PSE_CX | Google Custom Search JSON API | **Code/test only** |
| Tavily | tavily_api_key, legacy search_api_key, or TAVILY_API_KEY | Tavily API | **Code/test only** |
| Serper | serper_api_key, legacy search_api_key, or SERPER_API_KEY | Serper Google-results API | **Code/test only** |
| Disabled | search_provider=disabled | No outbound search | Implemented control |

No credentialed cloud search was exercised. A fallback returning results does not prove the selected primary provider worked; target telemetry must record the actual provider used.

### 8.2 Web fetch and extraction

| Field | Current implementation |
|---|---|
| Paths | Web-fetch tools and URL/security helpers in src/agent_tools, src/url_security.py, content extraction and research services |
| Config | WEB_FETCH_USER_AGENT plus time/output limits and request inputs |
| Secret | Normally none; fetched URLs can contain sensitive query parameters and must be sanitized |
| Health | No passive aggregate health; each fetch reports its request result |
| UI/tools | Chat URL context, web_fetch, research panel |
| Tests | URL validation, SSRF, response truncation, prompt-injection/untrusted-context, and TLS-scope tests |
| Status | **Code/test only** for general internet content in this audit |

Fetched content is untrusted input. A target connector records egress policy, redirect/DNS decisions, final URL, content type/hash, data residency, and cache expiry without exposing secret query parameters.

### 8.3 YouTube transcript

services/youtube/youtube_handler.py uses youtube-transcript-api when installed; src/youtube_handler.py is a compatibility alias. Chat preprocessing recognizes YouTube URLs and injects the transcript as untrusted context. /api/test/youtube is a diagnostic route. Tests include test_youtube_handler_consolidation.py, extraction-ID and malformed-segment/comment tests.

**Configuration/secrets:** no account credential is required by the current path.
**Models:** no model is required to fetch a transcript; a selected chat/research model may later consume it.
**Health:** explicit diagnostic only, not aggregate.
**Status:** **Code/test only**; no live transcript fetch was recorded in the baseline.

### 8.4 Deep research

routes/research, src/deep_research.py, and research handlers combine a selected model endpoint, selected/fallback search provider, page extraction, and data/deep_research run artifacts. UI is the Research panel; tools include trigger_research/manage_research rather than an independently credentialed provider.

Health is the composition of model, search, fetch, and storage health; there is no full-story readiness probe. Tests cover owner scope, cancellation, search override, persistence, and synthesis paths. **Status: code/test only; no credentialed end-to-end research provider run was certified.**

## 9. Speech and media integrations

### 9.1 Speech to text

| Provider | Paths/config | Secret/model | Health/UI/tests/status |
|---|---|---|---|
| Disabled | services/stt/stt_service.py; stt_enabled=false or provider disabled | None | Settings/voice recorder; explicit /api/stt/stats. Implemented off state. |
| Browser Web Speech | static/js/voiceRecorder.js; provider browser | Browser/vendor implementation and browser permission | Composer voice UI; no server health. **Code/test only** and browser/platform dependent. |
| Faster Whisper local | stt_provider local; stt_model and stt_language; optional CPU/CUDA dependency | Local model download/cache; no API key | /api/stt/stats and /api/stt/transcribe; speech toggles/service tests. **Unavailable/unverified** in baseline; optional dependency was not certified. |
| ModelEndpoint transcription | stt_provider endpoint:ID | Reuses encrypted ModelEndpoint key; POST /audio/transcriptions with configured stt_model/language | Same UI/routes; no aggregate provider health. **Code/test only** |

### 9.2 Text to speech

| Provider | Paths/config | Secret/model | Health/UI/tests/status |
|---|---|---|---|
| Disabled | services/tts/tts_service.py; tts_enabled/provider | None | /api/tts/stats; implemented off state |
| Browser speech synthesis | Browser provider/UI | Browser voices and permission | Voice playback UI; no server health. **Code/test only** |
| Kokoro local | Local provider, Kokoro-82M path, tts_model, tts_voice, tts_speed | Local model/runtime; no key | /api/tts/synthesize, stats and clear-cache; data/tts_cache; service tests. **Code/test only** |
| ModelEndpoint speech | tts_provider endpoint:ID | Reuses encrypted ModelEndpoint key; POST /audio/speech | Same UI/routes; no aggregate health. **Code/test only** |

Speech caches can reproduce private text and require owner-scoped TTLs. Browser provider selection must be represented as device-local capability, not server connection health.

### 9.3 Image generation and editing

| Field | Current implementation |
|---|---|
| Generation path | mcp_servers/image_gen_server.py resolves an image-capable ModelEndpoint and POSTs to /images/generations |
| Configuration | image_gen_enabled, image_model, image_quality in settings; ModelEndpoint model_type=image, base_url, encrypted key |
| Models | Auto-attempt order gpt-image-1.5, gpt-image-1, then dall-e-3 when no image model is selected; custom OpenAI-compatible image model IDs are possible |
| Storage | Base64 result written to data/generated_images and gallery_images metadata; provider-hosted URL may be returned without local bytes |
| Editing | routes/gallery/gallery_routes.py proxies selected owner-visible image endpoints to fixed image edit/inpaint paths; local Cookbook image servers are also possible |
| Health | Model discovery only; no passive image-generation probe |
| UI/tools | Chat generate_image, Gallery, image editor, Settings/Admin image endpoint controls |
| Tests | test_chat_image_routing.py, test_gallery_image_endpoint_owner_scope.py, test_gallery_endpoint_ssrf.py, test_promote_image_fields.py, and gallery lifecycle tests |
| Status | Built-in image MCP **connected local**, but no image was generated. Provider functionality is **code/test only**. Current MCP metadata insert can be ownerless. |

## 10. Generic REST integration presets

src/integrations.py stores active entries in integrations.json. Settings → Integrations provides CRUD/Test. api_call supports GET, POST, PUT, PATCH, and DELETE with none, bearer, arbitrary header, query, or basic authentication. Secrets use the JSON encryption helper, but Discord embeds its token in the base URL. Private-network access is allowed by default for LAN services when INTEGRATION_API_BLOCK_PRIVATE_IPS is not enabled; link-local/metadata targets remain blocked. Tests include integration store/encryption, URL joining, SSRF, truncation, and API-call routing.

| Preset | Current auth/config | Test/health behaviour | Tool/UI/status |
|---|---|---|---|
| Miniflux | Base URL; X-Auth-Token header | GET /v1/me | Settings and api_call; **code/test only** |
| Gitea | Base URL; Authorization value such as token TOKEN | GET /api/v1/version | Settings and api_call; **code/test only** |
| Linkding | Base URL; Authorization Token value | GET /api/tags/ | Settings and api_call; **code/test only** |
| Home Assistant | Base URL; bearer token | GET /api/ | Settings and api_call; **code/test only** |
| ntfy | Base server; none, bearer, or header credential; reminder_ntfy_topic | Test POST sends a real connectivity notification; aggregate diagnostics passively checks /v1/health | Settings, reminders, api_call; **unavailable/unverified** in baseline |
| Discord Webhook | Full webhook URL including token; no separate key | Test POST sends a real embed | Settings, reminders/webhook output, api_call; **code/test only** |
| Vaultwarden REST | Base URL; Authorization bearer access token | Generic GET / fallback | Settings/api_call; **code/test only**. Returned vault fields remain client-encrypted and this path is not the same as the bw CLI integration. |
| FreshRSS | Base URL; Authorization value GoogleLogin auth=TOKEN | Generic GET / fallback | Settings/api_call; **code/test only** |
| Custom REST | Name, base URL, auth type/header/key | Generic GET / | Settings and api_call; **code/test only** |

These presets are prompt descriptions plus generic HTTP, not typed provider SDKs. They do not declare scopes, pagination, normalized errors, rate limits, action risk, idempotency, resource ownership, webhook events, or uninstall cleanup.

The agent's keyword router also recognizes Jellyfin as a candidate for api_call, but there is no Jellyfin preset or typed adapter. It is only supported as an administrator-created Custom REST integration and therefore has the same **code/test-only generic HTTP** status.

## 11. Password-vault integration

routes/vault_routes.py integrates the Bitwarden CLI bw with Vaultwarden/Bitwarden-compatible servers. vault.json stores server/email/session configuration, and UI Settings exposes login, unlock, lock, and logout.

| Concern | Current state |
|---|---|
| Secrets | Password is kept out of command-line arguments; BW_SESSION is a sensitive bearer session in vault.json/process environment. |
| Health | Login/unlock/status operations; no aggregate probe. |
| Agent tool | No general first-class vault tool is registered for OM in the audited tool inventory. |
| Tests | test_vault_password_not_in_argv.py and route/security tests. |
| Status | **Code/test only.** No live vault was accessed. |

This integration is distinct from the generic Vaultwarden REST preset. Target migration must choose one supported provider contract, make it per-owner, revoke sessions on disconnect, and prevent vault secrets from entering model context.

## 12. MCP integrations

### 12.1 Built-in servers

| Server | Implementation/config | Tools | Observed status |
|---|---|---|---|
| image_gen | Python stdio mcp_servers/image_gen_server.py; ModelEndpoint/settings | generate_image | **Connected local**; generation not exercised |
| memory | Python stdio mcp_servers/memory_server.py; memory stores/Chroma optional | manage_memory | **Connected local** |
| RAG | Python stdio mcp_servers/rag_server.py; personal docs/Chroma | manage_rag | **Connected local**, vector functionality degraded without Chroma |
| email | Python stdio mcp_servers/email_server.py; app/scheduled/optional email cache databases and IMAP/SMTP | Account/list/search/read/download/send/draft/reply/archive/delete/read-state/bulk tools | **Connected local**; provider operations unverified |
| Browser | npx @playwright/mcp@latest with headless/vision capability when available | Dynamic browser tools | **Unavailable**; package was not cached and network install was not performed |

### 12.2 User-configured MCP transport

**Paths:** routes/mcp_routes.py, src/mcp_manager.py, and src/mcp_oauth.py.
**Transports:** stdio plus SSE/streamable HTTP support in manager/routes.
**Configuration:** mcp_servers table stores command, args JSON, env JSON, URL, enabled flag, OAuth config/tokens, and disabled tools. OAuth files are constrained under data/mcp_oauth.
**Secrets:** generic oauth_tokens is encrypted; env/args can hold plaintext tokens or database URLs. Child-process environment is a high-trust boundary.
**Health:** server status and discovered tools through /api/mcp/servers and reconnect operations; not part of aggregate diagnostics.
**UI/tool:** Admin/Settings → Tools/MCP; manage_mcp; discovered tools are dynamically qualified as mcp__SERVER__TOOL. Non-admin access is restricted by current security controls.
**Tests:** test_mcp_manager.py, test_mcp_oauth.py, test_mcp_reconnect_args.py, test_mcp_oauth_cache.py, and security/path/reconnect tests.
**Status:** built-ins as above; no credentialed remote/user MCP provider was live-verified.

### 12.3 UI MCP preset catalog

Every preset below launches a third-party package; most use npx -y and are not immutably pinned.

| Preset | Command/package and config | Status |
|---|---|---|
| Gmail | @gongrzhe/server-gmail-autoauth-mcp; GOOGLE_CLIENT_ID/SECRET; OAuth keys/tokens under data/mcp_oauth/gmail; Gmail modify/settings scopes in preset | **Code/test only** |
| Email IMAP/SMTP | @codefuturist/email-mcp stdio; address/password/IMAP/SMTP env | **Code/test only** |
| CalDAV | caldav-mcp; base URL/username/password env | **Code/test only** |
| Google Calendar | @cocal/google-calendar-mcp; GOOGLE_OAUTH_CREDENTIALS | **Code/test only** |
| Google Drive | @modelcontextprotocol/server-gdrive; credential files/config | **Code/test only** |
| GitHub | @modelcontextprotocol/server-github; personal access token | **Code/test only** |
| Slack | @modelcontextprotocol/server-slack; bot token/team ID | **Code/test only** |
| Notion | @notionhq/notion-mcp-server; OPENAPI_MCP_HEADERS | **Code/test only** |
| Linear | mcp-linear; LINEAR_API_KEY | **Code/test only** |
| Brave Search | @modelcontextprotocol/server-brave-search; BRAVE_API_KEY | **Code/test only** |
| Browser Playwright | @playwright/mcp@latest --headless | **Unavailable** in baseline |
| Filesystem | @modelcontextprotocol/server-filesystem /home | **Code/test only**; overly broad default path for a privileged companion |
| Memory | @modelcontextprotocol/server-memory | **Code/test only** and separate from OM canonical memory |
| Postgres | @modelcontextprotocol/server-postgres with connection URL in args | **Code/test only**; secret-in-argument risk |
| Todoist | todoist-mcp-server; TODOIST_API_TOKEN | **Code/test only** |

Preset catalog entries are not supported integrations until package version/digest, publisher, license, capabilities, scopes, sandbox, secret injection, health, uninstallation, and an end-to-end test fixture are owned by the release.

## 13. Webhooks, API clients, and notification channels

### 13.1 Outbound signed webhooks

| Field | Current implementation |
|---|---|
| Paths | routes/webhook_routes.py and src/webhook_manager.py |
| Config | webhooks table: global name, URL, encrypted-or-legacy secret, comma-separated allowed events, enabled and last result |
| Protocol | JSON POST with event/timestamp/data, X-Odysseus-Event, optional HMAC-SHA256 X-Odysseus-Signature |
| Security/health | Public-IP validation, DNS pinning, no redirects, timeout, sanitized errors; explicit test delivery; last status in DB |
| UI/tool | Admin webhook management; manage_webhooks |
| Tests | test_webhook_ssrf_resilience.py, test_webhook_dns_rebinding_pin.py, test_webhook_task_refs.py, test_webhook_emitters_use_manager.py |
| Status | **Code/test only.** No live destination was exercised. |

Webhooks are installation-global and lack delivery-attempt rows, retry policy, per-owner scope, idempotency receipt, dead-letter queue, or receiver acknowledgement.

### 13.2 Inbound scheduled-task webhook

POST /api/tasks/TASK_ID/webhook/TOKEN is intentionally authentication-exempt and authorizes by a random path token stored in scheduled_tasks. The handler matches task ID and token, then triggers the task. The UI can regenerate it. Tests include test_webhook_trigger_auth_exempt.py.

**Status:** implemented/code-tested, not live-exercised.
**Release gap:** no HMAC signature, timestamp, replay nonce/delivery ID, request-body schema/size contract, source policy, or dedicated rate limit is evident. A bearer secret in the URL is exposed to logs/history.

### 13.3 API-token chat endpoint

POST /api/v1/chat requires an API token with chat scope. It can resume an owner-scoped session, use a request-supplied direct provider key/base URL, or choose a configured endpoint. routes/webhook_routes.py identifies n8n, Make, and Activepieces as intended clients; Zapier/curl-style callers can use the same bearer-token mechanism.

Raw request api_key is bounded but still traverses request memory and should be replaced by a saved connection reference. Tests cover token scope/owner and URL validation. **Status: code/test only as an external client integration.**

### 13.4 Codex and Claude Code bridges

| Bridge | Paths/config | Scope and UI | Status |
|---|---|---|---|
| Codex | routes/codex_routes.py; integrations/codex plugin/skill/scripts; ODYSSEUS_URL and one-time-issued API token | /api/codex capabilities, todos, email, memory, calendar, documents, and privileged Cookbook routes; exact scopes are chat, todos:read/write, documents:read/write, email:read/draft/send, calendar:read/write, memory:read/write, and cookbook:read/launch; Settings token UI | **Code/test only**; bundle and scope tests exist, no external Codex client session certified |
| Claude Code | /api/claude/plugin.zip ships integrations/claude skills; runtime uses the same /api/codex scope-gated endpoints | Same API token/scopes | **Code/test only** |

Cookbook launch scope can expose host topology, logs, SSH, tmux, GPU processes, and shell-capable model launch. It is a privileged local integration, not an ordinary data connector.

### 13.5 Notifications

| Channel | Configuration/path | Health and status |
|---|---|---|
| Browser Notifications | Browser permission and process-local polling queue | Device-local; no durable delivery receipt. **Implemented but partial** |
| Email reminders/results | Configured email account and reminder recipient/style settings | Depends on SMTP and model when synthesized. **Code/test only** |
| ntfy | Generic ntfy integration plus reminder_ntfy_topic | Passive service health and active test push. **Unavailable/unverified** |
| Generic webhook/Discord | Selected integration ID and payload template | Test side effect available. **Code/test only** |

Target notifications need a durable outbox, per-device/channel subscription, user consent, quiet hours, retry/deduplication, delivery receipts, and payload-minimization policy.

## 14. Local host and model-management integrations

### 14.1 Cookbook, Hugging Face, GitHub, SSH, tmux, and Docker

Cookbook routes and helpers can:

- query Hugging Face model metadata and download artifacts;
- obtain llama.cpp release/recipe information from GitHub;
- install or launch llama.cpp, vLLM, SGLang, Ollama, Node, or Python model servers;
- run locally or through SSH;
- use tmux/background jobs for durable-looking process control;
- optionally access a mounted Docker socket;
- register a launched server as a ModelEndpoint.

**Configuration:** cookbook_state.json, environment, model/cache paths, remote host/SSH port, launch commands, GPU/platform fields, and mounted SSH/cache directories.
**Secrets:** SSH keys/agent, provider download tokens, Docker authority, and inherited process environment are outside a common secret broker.
**Health:** task output/tmux/process/model endpoint checks; no one aggregate, durable lifecycle.
**UI/tools:** Cookbook UI, model serve/download tools, and scoped Codex Cookbook endpoints.
**Tests:** cookbook dependency/recipe, command validation, SSH-host validation, background job, serve lifecycle, and hardware-fit tests.
**Status:** **code/test only**; no download, Docker launch, remote SSH serve, or model install was certified during this audit.

Mounting the host Docker socket or giving an agent cookbook:launch is effectively host-level authority and requires a separate administrator trust domain.

### 14.2 Host filesystem, shell, and Python

Workspace/file tools, shell routes, subprocess tools, and background jobs integrate OM with the local host. They are not a third-party provider, but they are the highest-impact local integration.

| Concern | Current state |
|---|---|
| Config/UI/tools | Workspace picker, shell enablement/privileges, get_workspace, ls/glob/grep/read/write/edit, bash, python, pipeline |
| Secrets | Current subprocess path can inherit application environment; file roots can include data storage |
| Health | Route/process execution result only |
| Tests | Workspace confinement, path security, shell service/routes, task shell tools, edit/file tests |
| Status | **Implemented but release-blocking security risk** for the primary OM agent; see 07-security-model.md |

Target architecture runs privileged local work in a separate sandbox/worker identity with explicit mounts, minimal environment, egress/resource limits, confirmation, cancellation, and audit.

### 14.3 Tailscale-assisted endpoint discovery

src/model_discovery.py runs tailscale status --json to discover online tailnet peers for local model scans. src/endpoint_resolver.py can retry a DNS-failed model hostname by resolving it from that status output. Tailscale CGNAT addresses in 100.64.0.0/10 are classified as local unless endpoint_kind overrides that classification.

**Configuration/secrets:** the integration uses the host's installed Tailscale CLI/session; OM stores no separate Tailscale token. Hostnames and peer IPs can appear in diagnostics/logs.
**Health/UI/tools:** no dedicated connection card or passive health check; it is implicit in model discovery and endpoint resolution.
**Tests:** test_model_discovery_status.py, test_provider_endpoints_tailscale.py, model-context and endpoint-classification tests.
**Status:** **code/test only**; no tailnet peer discovery was certified in the baseline.

### 14.4 Browser assets, package sources, and external navigation

These paths are integrations because they make runtime network requests or execute downloaded code/assets even though they do not store provider credentials.

| Service/source | Exact path and purpose | Config, health, UI/tool, tests | Status |
|---|---|---|---|
| jsDelivr KaTeX | static/index.html loads KaTeX 0.16.22 CSS/JS | No key; browser fetch at page load; math rendering UI; CSP/frontend tests, but no dedicated dependency health | **Code/test only** as an online runtime dependency |
| jsDelivr Mermaid | static/index.html loads Mermaid 11 | No key; browser fetch at page load; diagram rendering; frontend/CSP coverage | **Code/test only** |
| jsDelivr Pyodide | static/js/codeRunner.js lazy-loads Pyodide 0.27.5 and its index | No key; runs Python in the browser code runner; load error is local UI health | **Code/test only**; not certified offline |
| jsDelivr OpenMoji | routes/emoji_routes.py fetches OpenMoji 15.0.0 black SVGs and caches them in data/emoji_cache | No key; same-origin emoji proxy/UI; emoji and route tests | **Code/test only** |
| GitHub and skills.sh skills | services/memory/skill_importer.py and routes/skills_routes.py import public SKILL.md bundles; skills.sh URLs resolve to GitHub | No key in current public import; Skills UI and manage_skills; importer/path/prompt-injection tests | **Code/test only** |
| Hugging Face model hub | Cookbook API/model/collection queries and artifact downloads; cache in mounted Hugging Face path | Optional external hub credential in host environment; Cookbook UI/tools/tests | **Code/test only** |
| GitHub model/runtime artifacts | Cookbook fetches llama.cpp/vLLM recipes/releases; gallery can download Real-ESRGAN and GFPGAN weights from GitHub releases | No app connection card; per-operation failure only; Cookbook/Gallery and optional-dependency tests | **Code/test only** |
| Apple Maps and OpenStreetMap | static/js/calendar.js opens a location search URL from an event | No key; external navigation from Calendar; no provider read/write or aggregate health | **Implemented link-out**, not a synced map provider |

The release must either bundle critical browser/runtime assets with verified digests or declare online operation and failure UX. Remote code such as Pyodide/Mermaid must be pinned with integrity and CSP controls; imported skills and model artifacts need publisher, license, digest, quarantine, and update provenance.

## 15. Current verification summary

| Integration | Audit evidence |
|---|---|
| Local Ollama qwen3:1.7b | Real chat response obtained through the application |
| Built-in image/memory/RAG/email MCP processes | Four stdio servers connected |
| Browser MCP | Unavailable because the package was not cached |
| ChromaDB | Not running; vector/RAG path degraded |
| SearXNG | Not running |
| ntfy | Not running |
| Docker services | Compose configuration parsed; Docker daemon stopped |
| IMAP/SMTP/Gmail OAuth | Not credential-live verified |
| CalDAV/CardDAV/Google Calendar | Not credential-live verified |
| Cloud search/model/embedding/image/speech providers | Not credential-live verified |
| User/remote MCP presets | Not credential-live verified |
| Vault, webhook destinations, Codex/Claude external clients, SSH/Cookbook launch | Not live verified |

This table is the authoritative wording for launch claims until new signed test evidence is attached.

## 16. Target provider-neutral contracts

### 16.1 Connection manifest

Every provider package must declare a versioned manifest:

- provider ID, display name, adapter version, publisher, license, source digest;
- supported resource domains and operations;
- auth modes, requested scopes, redirect requirements, and revocation endpoint;
- configuration schema with secret-reference fields;
- normalized capabilities and limitations;
- passive health and synthetic-test definitions;
- rate-limit/retry/idempotency semantics;
- data sent to the provider, residency/retention disclosures, and local cache policy;
- actions/triggers, risk class, approval rule, deterministic verification method, and compensation support;
- uninstall/disconnect/export/delete hooks;
- supported provider/API versions and compatibility fixtures.

MCP discovery may add tools at runtime, but it cannot substitute for a reviewed manifest or grant authority.

### 16.2 Common connection lifecycle

ProviderConnection must expose:

- disconnected;
- connecting;
- connected;
- degraded;
- token_expiring;
- auth_failed;
- permission_missing;
- rate_limited;
- provider_down;
- repair_required;
- disconnecting;
- revoked.

Stored health fields include last_checked_at, last_success_at, last_error_code, retry_after, credential_expiry, granted_scopes, capability_snapshot, adapter_version, and repair action. User-visible errors are normalized and never include secrets.

### 16.3 Operation envelope

Every provider operation accepts:

- ActorContext with immutable user/tenant/role;
- connection_id;
- typed request schema;
- action_intent_id and idempotency_key;
- risk/approval token where required;
- deadline, cancellation token, and retry budget;
- audit correlation ID.

It returns a normalized result:

- local resource ID and remote resource ID/version;
- status: succeeded, failed, cancelled, partial, indeterminate, or rate-limited;
- structured provider error code and retry advice;
- usage/cost metadata;
- verification strategy/result;
- sanitized audit fields;
- any compensation token.

Provider adapters never receive model prose directly and never return secrets to model context.

## 17. Required domain provider interfaces

| Interface | Required operations and guarantees |
|---|---|
| ModelProvider | list_models, get_capabilities, stream_chat, complete, count/estimate tokens, usage; typed native tool calls only; provider-specific errors, cancellation and rate limits |
| EmbeddingProvider | fingerprint, dimensions, embed_batch, limits, privacy/egress; deterministic lane compatibility |
| CalendarProvider | list/sync calendars/events, create/update/delete/readback, incremental cursor, recurrence/attendees/timezones, conflict and tombstone semantics |
| EmailProvider | list/sync messages, fetch body/attachments, label/move/archive, create draft, send, reply, readback/delivery evidence, history cursor and stable message/thread IDs |
| ContactsProvider | list/search/create/update/delete, ETag/version conflict, normalized names/emails/phones/addresses |
| SearchProvider | search with locale/safe-search/time filters, actual-provider telemetry, citations, quota/rate-limit metadata |
| WebContentProvider | validate/fetch/extract with egress policy, redirect/DNS record, MIME/size/hash, cache TTL and untrusted-content classification |
| TranscriptionProvider | supported audio formats/languages/models, transcribe/stream, timestamps, diarization, privacy and deletion |
| SpeechProvider | voices/models/formats, synthesize/stream, cache policy, text privacy and usage |
| ImageProvider | model capabilities, generate/edit/inpaint, size/quality limits, safety result, provenance and durable artifact import |
| KnowledgeProvider | source enumeration, incremental change cursor, ACL mapping, fetch, deletion; vectors remain internal derivatives |
| NotificationProvider | subscribe/send/status, dedupe key, quiet-hours support, payload limits and delivery receipt |
| GenericConnector | reviewed typed actions/resources/triggers; generic arbitrary HTTP remains administrator-only and cannot be auto-granted to OM |
| McpProvider | sandboxed process/remote session, reviewed tool allowlist, secret references, health, cancellation, provenance and uninstall |
| LocalRuntimeProvider | sandboxed file/process/model job operations with explicit mounts, limits, egress, cancellation and artifact collection |

### Required first-party adapters

The product specification requires first-party implementations, not merely generic HTTP or unreviewed MCP presets, for:

- Google Calendar;
- Gmail;
- transcription;
- local/private knowledge;
- one local/private model provider;
- notifications needed by the shipped automation experience.

CalDAV and IMAP/SMTP may remain additional protocol adapters, but they do not satisfy a native Google provider contract by themselves.

## 18. UI and tool contract

Each connection card must show:

- provider and account identity;
- connected/degraded/expired state and last success;
- granted scopes and capabilities;
- what data leaves the device;
- default model/calendar/mailbox and ownership;
- Test connection with a clear distinction between passive and side-effecting tests;
- Repair, reconnect, rotate credential, revoke, export, clear cache, and disconnect;
- local data retained after disconnect and remote data unaffected/deleted;
- adapter/package version and update status.

Tool exposure is derived from the connection manifest:

- tools appear only when the connection and required capability are healthy;
- read and write operations have separate permissions;
- consequential writes require policy approval and durable action intent;
- provider connection ID is explicit, never inferred from the first/default account for a consequential action;
- model-generated arguments are schema-validated and normalized;
- results include the actual provider/account and verification status;
- unavailable tools return a repair action, not a silent fallback to a different provider.

## 19. Ownership, retention, backup, and uninstall implications

| Integration class | Local records to own | Disconnect/uninstall rule | Backup/recovery rule |
|---|---|---|---|
| Models/embeddings | Connection, secret refs, model capability cache, usage, vector fingerprint | Revoke session/key where possible; delete capability cache; retain audited usage without prompt content per policy | Back up connection metadata and encrypted secret reference; rebuild caches/vectors |
| Email | Connection, cursors/index/cache, drafts/pending actions, attachment staging | Revoke OAuth; close sessions; purge mirrors/caches; preserve user-created drafts only by explicit import; never delete remote mailbox on disconnect | Back up approved local drafts/actions and connection metadata; remote mailbox is provider recovery source |
| Calendar/contacts | Connection, cursors, local mirrors, conflicts/tombstones | Revoke auth; resolve pending writes; purge mirrors; preserve local-only resources; remote deletion requires separate approval | Back up local-only data and provider mappings; reconcile remote after restore |
| Search/web | Connection/key, query/cache telemetry | Revoke/delete key; purge content/query caches by TTL | Normally omit caches; keep configuration and minimal usage audit |
| Speech/image | Connection, generated canonical artifacts, derivative caches | Cancel work; revoke key; keep user-selected artifacts, purge caches | Back up canonical artifacts and provenance; rebuild caches |
| Generic REST/MCP | Manifest/config, secret refs, installed package digest, allowed tools, OAuth files | Stop process, revoke tokens, delete OAuth files/env secrets, remove tool grants and caches | Back up reviewed manifest/config and encrypted secret refs; never depend on npx latest at restore |
| Webhooks/API tokens | Destination/subscription, token hash/secret ref, attempts/receipts | Disable first, drain/cancel, revoke token/secret, retain redacted receipt | Back up config and audit, not raw one-time API tokens |
| Local runtime | Job/action metadata and user-approved artifacts | Cancel/kill leases, remove temp mounts/processes, preserve chosen artifacts, delete command logs by policy | Back up artifacts and redacted job metadata; manage SSH/Docker/model caches separately |

Provider-owned remote records are never implied to be in an OM backup. Restore must refresh credentials, revalidate scopes/capabilities, rebuild derivatives, and reconcile remote IDs before automations resume.

## 20. Migration plan

| Phase | Work | Acceptance evidence |
|---|---|---|
| 1. Inventory and freeze | Export every current ModelEndpoint, EmailAccount, CalDAV/CardDAV config, generic integration, MCP server, webhook, API token metadata, speech/search/embedding setting, and local runtime reference without secret values | Deterministic manifest; unknown/ownerless connections quarantined |
| 2. Create connection/secret schema | Add provider_connections, capability/health, secret references, adapter versions, scopes and ownership | No new feature writes credentials to JSON/env/args/URLs |
| 3. Wrap existing adapters | Put Ollama/OpenAI-compatible, IMAP/SMTP, CalDAV/CardDAV, search, speech/image, REST, MCP, webhook and local-runtime paths behind common contracts | Contract tests pass without changing user-visible read behaviour |
| 4. First-party product adapters | Implement Google Calendar, Gmail, transcription, knowledge, local model and notification providers | Sandbox and credential-live end-to-end fixtures prove read/write/readback/revoke |
| 5. Durable actions | Route every provider write through action intent, policy, approval, outbox, attempt and verification | Crash/retry/cancel/replay tests prove exactly-once or explicit indeterminate state |
| 6. Health/lifecycle UI | Replace scattered Test buttons with passive health, capability test and explicit synthetic-write flows | Expiry, missing scope, rate limit, outage and repair journeys pass |
| 7. Migrate secrets/state | Import JSON/SQL/OAuth files, rotate/revoke where possible, convert provider IDs/cursors, purge legacy plaintext | Secret scanner and legacy-path monitor remain clean |
| 8. Pin/sandbox MCP/runtime | Pin package digests, isolate processes, minimal env/mount/egress, reviewed tool grants | Malicious MCP/runtime fixture cannot access app secrets/host outside grant |
| 9. Disconnect/retention | Implement revocation, cache purge, local import choices, provider mapping cleanup and audit | Per-provider uninstall tests leave no active token/tool/job/vector |
| 10. Certify integrations | Run credential-live conformance in dedicated test accounts and supported platforms | Signed evidence records provider/API/adapter version, scopes, IDs, cleanup and timestamp |

## 21. Integration release blockers

1. No common connection registry, provider capability schema, lifecycle, health, or ownership model.
2. No credential-live evidence for required Gmail, Google Calendar, transcription, cloud provider, notification, or remote-knowledge flows.
3. Native Gmail API and Google Calendar API adapters are absent; current Gmail is IMAP/SMTP XOAUTH2 and current Google Calendar path is CalDAV or optional MCP.
4. Generic REST and MCP can expose broad, dynamically discovered authority without typed product contracts.
5. MCP env/args, webhook URLs/tokens, chat headers, local process environment, and configuration JSON can contain secrets outside the central encrypted fields.
6. User-configured MCP presets are unpinned; Browser uses @latest and was unavailable offline.
7. Provider writes are not uniformly durable, idempotent, approval-backed, cancellable, and deterministically verified.
8. Aggregate diagnostics omit several critical services and cannot serve as full readiness.
9. Connection removal does not have one tested revocation/cache/vector/artifact/audit workflow.
10. Local shell, SSH, Docker, filesystem, and Cookbook integrations operate in a trust domain too broad for the primary OM companion.

No integration should be marked production-supported until its contract tests, credential-live sandbox tests, failure/recovery tests, uninstall cleanup, retention behaviour, backup/reconciliation procedure, and user-visible data-egress disclosure all pass.
