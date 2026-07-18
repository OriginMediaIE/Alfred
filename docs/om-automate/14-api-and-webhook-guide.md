# OM Automate API and Webhook Guide

## 1. Status, scope and notation

- **Document status:** implementation target and security acceptance guide.
- **Baseline reviewed:** repository commit `9844a2f9a1996b8c8135a9e7bbde6a72f41df5ed`.
- **Scope:** browser sessions, API tokens, public API routes, action execution, approvals, inbound task hooks, outbound webhooks, errors, rate limits, idempotency and audit evidence.
- **Related controls:** `07-security-model.md`, especially SEC-007, SEC-010, SEC-011, SEC-013 and SEC-014.
- **Brand compatibility:** `08-branding-register.md`, especially the rule that new machine identifiers are versioned and legacy identifiers are read through an explicit migration window.

The words **MUST**, **MUST NOT**, **SHOULD** and **MAY** are normative for the target contract. “Current” describes observed baseline behaviour; it is not a promise that consumers should depend on. “Target” describes the contract that must be implemented and verified before OM Automate is presented as suitable for external exposure.

Examples contain reserved domains, opaque example identifiers and environment-variable placeholders only. They contain no usable credential, signature, personal data or production endpoint.

## 2. Current surface inventory

### 2.1 Authentication and token surfaces

| Surface | Current route or mechanism | Current protection | Important observations |
|---|---|---|---|
| Browser authentication | `/api/auth/setup`, `/signup`, `/login`, `/logout`, `/status`, `/policy`, password and 2FA routes | Session cookie after login; setup/login routes are exempt | Cookie name is `odysseus_session`; it is HttpOnly and SameSite Lax, while `Secure` depends on configuration (`routes/auth_routes.py:84-269`). |
| Global request authentication | Application middleware | `AUTH_ENABLED` defaults true; localhost bypass defaults false | Browser cookie and `Bearer ody_...` are accepted centrally (`app.py:246-254`, `app.py:405-469`). Exact setup/auth/health paths and task-hook paths are exempt (`app.py:256-289`). |
| API token administration | `GET/POST /api/tokens`, `GET /api/tokens/profiles`, `PATCH/DELETE /api/tokens/{id}` | Administrator browser session | Raw token is returned once; bcrypt hash, owner, prefix, scopes and last-used metadata are persisted (`routes/api_token_routes.py:77-207`; `core/database.py:475-486`). |
| Companion pairing | `GET/POST /api/companion/pair` | Administrator browser session | Pairing currently returns a normal long-lived `chat` bearer token in JSON and a QR payload rather than a one-time exchange grant (`companion/routes.py:162-217`; `companion/pairing.py:83-126`). |
| Trusted internal request | Loopback-only internal headers | Direct peer validation plus internal secret | This is an implementation channel, not a public API. Proxy forwarding headers do not establish trust (`app.py:331-389`; `core/middleware.py:12-19`). |

Current API token scopes are:

| Capability | Read scope | Write/execute scope |
|---|---|---|
| Chat | `chat` | `chat` |
| Todos | `todos:read` | `todos:write` |
| Documents | `documents:read` | `documents:write` |
| Email | `email:read` | `email:draft`, `email:send` |
| Calendar | `calendar:read` | `calendar:write` |
| Memory | `memory:read` | `memory:write` |
| Cookbook/process execution | `cookbook:read` | `cookbook:launch` |

Write scopes imply the corresponding read scope in the current helper (`routes/api_token_routes.py:13-71`). Codex routes and `/api/v1/chat` perform explicit scope checks. `require_user()` deliberately rejects API bearer tokens on ordinary browser-user routes (`src/auth_helpers.py:62-109`). This is a useful safeguard, but the overall design still relies on every route choosing the correct helper.

Current CORS configuration uses an explicit local-origin default, permits credentials and allows a configured set of methods/headers (`app.py:127-146`). It does not itself authorise a request; cookie-authenticated mutations still need a real CSRF defence.

### 2.2 Current API routes

| Surface | Current contract | Notes |
|---|---|---|
| Chat | `POST /api/v1/chat` | Requires `chat`, enforces session ownership, accepts an optional provider endpoint/key, calls synchronously with a 120-second limit, and returns `{response, session_id, model}` (`routes/webhook_routes.py:229-393`). |
| Codex capabilities | `GET /api/codex/capabilities` | Advertises available integrations and scopes (`routes/codex_routes.py:167-216`). |
| Codex resources | `/api/codex/todos`, `/emails`, `/memory`, `/calendar/events`, `/documents` | Owner-scoped read/write APIs with granular scopes (`routes/codex_routes.py:234-513`). |
| Codex cookbook | `/api/codex/cookbook/...` | Includes local process and remote SSH launch/serve/stop operations guarded by `cookbook:launch` but not by a common approval/action resource (`routes/codex_routes.py:515-875`). |
| Task execution | `POST /api/tasks/{task_id}/run`; task-specific run-list routes | Returns an immediate triggered/already-running result and exposes task-run history, but there is no shared lifecycle contract across task, email and cookbook execution (`routes/task_routes.py:857-980`). |
| Email send | Codex email send route and underlying `/api/email/send` | Queues delivery in a background task. Capabilities say sending requires confirmation, but the direct scoped endpoint has no durable, digest-bound approval contract (`routes/codex_routes.py:212-215`, `routes/codex_routes.py:376-387`; `routes/email_routes.py:3760-3956`). |

Response shapes and errors vary by route. Central handlers use objects such as `{error, message}`, FastAPI validation uses its own shape, and individual routes return further variants (`app.py:602-617`). A client cannot currently rely on one problem schema, one request identifier or one action-status model.

### 2.3 Current webhook surfaces

| Surface | Current contract | Security posture |
|---|---|---|
| Inbound task hook | `POST /api/tasks/{task_id}/webhook/{token}` | The random path token is the only request authentication. A valid request immediately schedules the task; there is no signature, timestamp, delivery ID, body cap, replay store or idempotency contract (`routes/task_routes.py:505-508`, `routes/task_routes.py:1045-1084`). |
| Outbound subscription administration | `GET/POST /api/webhooks`, `PATCH/DELETE /api/webhooks/{id}`, `POST /api/webhooks/{id}/test` | Administrator-only. Stores URL, optional encrypted secret, event selection and only the last delivery status/error (`routes/webhook_routes.py:71-181`; `core/database.py:489-501`). |
| Outbound event catalogue | `session.created`, `chat.completed`, `chat.message`, `webhook.test` | Event names are allowlisted (`src/webhook_manager.py:22-27`, `src/webhook_manager.py:252-260`). |
| Outbound body | `{"event": ..., "timestamp": ..., "data": ...}` | No schema/version, event ID, subject or data-minimisation declaration (`src/webhook_manager.py:405-426`). |
| Outbound signature | Optional hexadecimal HMAC-SHA256 in `X-Odysseus-Signature` | No version, delivery ID, explicit signed timestamp header, replay rule or overlapping-secret rotation (`src/webhook_manager.py:418-426`). |
| Destination connection | Public-IP validation, DNS resolution and approved-IP pinning; Host/SNI preservation; redirects disabled; ten-second timeout | This is a strong baseline and must be retained (`src/webhook_manager.py:29-249`, `src/webhook_manager.py:392-430`). |

`chat.completed` currently includes up to 2,000 characters each of user and assistant text (`routes/webhook_routes.py:388-391`). That is content disclosure, not harmless telemetry, and must not be enabled by a generic event subscription without explicit purpose and consent.

## 3. Gap register and release consequences

| ID | Severity | Gap | Required disposition |
|---|---|---|---|
| API-01 | High | Bearer acceptance is central but route-to-scope policy is decentralised. | Introduce a deny-by-default route registry and test every registered route/scope/ownership combination. |
| API-02 | High | High-impact operations have inconsistent execution models. Email can queue directly despite a confirmation claim; cookbook can launch host/SSH work without a shared approval object. | Route side effects through typed actions, risk policy and digest-bound approvals. |
| API-03 | High | A task-hook secret appears in the URL and provides no message integrity, freshness or replay protection. | Replace it with a non-secret hook locator plus signed, timestamped, idempotent requests. |
| API-04 | High | Companion pairing exposes a normal long-lived API token in a QR payload. | Use a short-lived, single-use pairing grant and exchange it for a separately revocable device credential. |
| API-05 | High | Session/TOTP storage, fail-open setup recovery, CSRF and process-local authentication throttling have known weaknesses. | Close SEC-010 before internet exposure; API versioning does not compensate for weak browser authentication. |
| API-06 | Medium | API token records have no expiry, audience, purpose or rotation lineage. | Add lifecycle fields and migrate without invalidating existing tokens unexpectedly. |
| API-07 | Medium | There is no durable API-wide rate-limit or idempotency service. | Add shared-store enforcement and concurrency tests. |
| API-08 | Medium | `/api/v1/chat` validates a supplied public provider URL but does not pin the approved address through connection establishment. | Reuse the pinned transport or remove per-request arbitrary endpoints. |
| API-09 | Medium | Error and pagination contracts are inconsistent. | Adopt the common problem, pagination and request-ID formats below. |
| API-10 | Medium | Chat accepts a provider API key in the ordinary request body, increasing exposure through traces, client history and error handling. | Use a backend secret reference/broker; do not accept reusable provider credentials in ordinary action/chat payloads. |
| WH-01 | High | Outbound signing is optional and has no replay-safe versioned contract. | Require versioned signing for non-loopback targets and publish receiver verification rules. |
| WH-02 | High | Deliveries lack durable attempts, retry/backoff, dead-letter state and reliable success reporting. | Create delivery/attempt resources and use 2xx-only success semantics. |
| WH-03 | Medium | Event payloads can disclose chat content without field-level purpose or consent. | Default to metadata; require a separate content event/permission and explicit UI disclosure. |
| WH-04 | Medium | Webhook-secret encryption has a plaintext fallback when the key manager is unavailable. | Fail closed for secret creation/update and migrate any plaintext value into the versioned secret store. |

All High items above are launch blockers for public/network-exposed use. A UI label, warning banner or “local-first” description does not waive them.

## 4. Target API foundations

### 4.1 Versioning and compatibility

1. New public contracts live below `/api/v1`. A major path version changes only for a breaking contract change.
2. Additive optional fields and new event types are allowed within a major version. Existing fields MUST NOT silently change meaning or type.
3. Every request and response uses UTF-8 JSON unless the endpoint explicitly documents a binary media type.
4. Timestamps are UTC RFC 3339 values. Durations are integer seconds. IDs are opaque and MUST NOT encode a database sequence, email address or secret.
5. Existing `/api/codex/*`, `/api/webhooks/*`, task URL hooks and the current chat response remain **legacy**, not target examples. Freeze them, instrument their use, and migrate through adapters.
6. A deprecated HTTP route returns `Deprecation: true`, a standards-formatted `Sunset` date after one is approved, and a `Link` to migration documentation. No route is removed until supported bundled clients have migrated and usage evidence shows the compatibility window is complete.
7. New tokens use the prefix selected by the branding ADR; the server continues to recognise existing `ody_` records until explicit rotation/revocation. The exact new prefix and public header spelling MUST be ratified before public preview, then frozen.

### 4.2 Authentication and authorisation

- Browser routes use hardened server sessions plus CSRF protection. Public API routes use `Authorization: Bearer <token>` only; tokens MUST NOT be accepted in query strings, fragments, path segments or ordinary JSON fields.
- The API gateway maps every route and method to: allowed principal type, required exact scopes, ownership rule, rate profile, idempotency policy and maximum body size. An unknown route/method/principal combination denies by default.
- Scope checks are repeated in the service layer so an internal caller cannot bypass ownership or capability policy.
- `401` means that credentials are absent, expired, revoked or invalid. `403` means an authenticated principal lacks a required scope or policy permission. Cross-owner object lookup SHOULD return `404` where that avoids object enumeration.
- Logs and errors contain token IDs/prefix metadata only, never bearer values. Token comparison is constant-time after a bounded, indexed candidate lookup.
- API token records contain: owner, creator, hashed secret, prefix, scopes, audience, purpose, issued time, optional not-before, mandatory expiry for device/integration tokens, last-used time, revoked time, replacement/rotation lineage and status.
- Token creation returns the raw value once. Rotation creates a new credential, supports an explicit short overlap where necessary, and then revokes the predecessor. Secret values are not recoverable through list/get APIs.
- A high-risk approval credential is a separate capability. A token that proposes an action MUST NOT acquire approval authority merely because it can create that action.
- Credentialed CORS uses exact trusted origins only and never combines `Access-Control-Allow-Credentials: true` with a wildcard origin. Preflight success is not an authorisation decision. Server-to-server API consumers do not need permissive CORS.
- Reusable provider credentials are referenced by an owner-scoped backend integration ID. They are not accepted in ordinary chat/action bodies, returned to clients or forwarded into model context.

Versioned token administration uses an administrator browser session with CSRF and recent authentication:

| Method and path | Purpose |
|---|---|
| `GET/POST /api/v1/api-tokens` | Cursor-list token metadata or create a scoped credential. |
| `GET/PATCH/DELETE /api/v1/api-tokens/{token_id}` | Read metadata, reduce/update permitted metadata, or revoke. |
| `POST /api/v1/api-tokens/{token_id}/rotate` | Create a replacement and an explicit, bounded overlap if policy permits it. |
| `POST /api/v1/pairing-grants` | Create a single-use companion grant with a maximum five-minute lifetime. |
| `POST /api/v1/device-credentials` | Exchange a valid pairing grant once for a revocable, expiring device credential. |

Token creation accepts a display name, exact scopes, audience, purpose and expiry. Its `201 Created` response includes the credential in a `token` field exactly once; list/get/patch responses omit that field entirely. A pairing QR contains only the HTTPS origin, grant ID and single-use grant value. Atomic exchange consumes the grant before returning the device credential, and a second exchange fails even if the first response was lost. The resulting device record can be named, inspected and independently revoked.

Initial target scope additions are:

| Scope | Purpose |
|---|---|
| `actions:read` | Read owner-visible action status and redacted result metadata. |
| `actions:create` | Propose only action types separately allowed by the token's resource scopes. |
| `actions:cancel` | Request cancellation where the action supports it. |
| `approvals:read` | Read pending approval summaries. |
| `approvals:decide` | Decide approvals only when principal policy and recent authentication permit it. Not issued to ordinary integration/device tokens. |
| `webhooks:read` | List subscriptions and delivery metadata. |
| `webhooks:write` | Create, rotate, disable and test subscriptions. Administrator/session-only by default. |

Resource scopes remain mandatory. For example, `actions:create` alone cannot submit `email.send`; it also needs `email:send`, and policy can still require a human approval.

### 4.3 Common request rules

Every response includes `X-Request-Id`; a syntactically valid client `X-Request-Id` MAY be retained, otherwise the server generates one. It is diagnostic metadata, never authentication.

State-changing creation requests use:

- `Content-Type: application/json`;
- `Idempotency-Key: <opaque-client-value>` for action creation and any endpoint marked idempotent-required;
- `If-Match` or an explicit `resource_version` when modifying a previously observed resource;
- a documented body cap enforced before full parsing or decompression.

The idempotency store keys on principal, method, canonical route and idempotency key. It stores a canonical request hash and the original status/body for at least 24 hours and no less than the action's retry/approval lifetime. Concurrent first requests are serialised. A retry with the same hash returns the original logical resource; the same key with a different hash returns `409 IDEMPOTENCY_KEY_REUSED`. Credentials and volatile headers are excluded from the request hash.

List endpoints use cursor pagination:

```json
{
  "data": [],
  "page": {
    "next_cursor": null,
    "has_more": false
  }
}
```

The server caps `limit`; cursors are opaque, scoped to the caller and query, and expire safely. Offset pagination is not used for mutable action/delivery histories.

### 4.4 Common error contract

Errors use `application/problem+json`:

```json
{
  "type": "https://om-automate.example.invalid/problems/approval-required",
  "title": "Approval required",
  "status": 409,
  "code": "APPROVAL_REQUIRED",
  "detail": "This action requires an approval decision before execution.",
  "instance": "/api/v1/actions/act_example",
  "request_id": "req_example",
  "errors": []
}
```

`code` is a stable machine value. `detail` is safe for the caller and MUST NOT contain a stack trace, SQL, filesystem path, provider body, token, secret, signed URL or unredacted third-party error. Validation errors identify JSON pointers and constraints, not rejected secret values. At minimum, clients can rely on `400`, `401`, `403`, `404`, `409`, `412`, `413`, `415`, `422`, `429` and `5xx` retaining their normal HTTP meaning.

## 5. Durable action and approval contract

### 5.1 Why actions are a resource

Email send, calendar mutation, task execution, process/SSH launch and similar work MUST NOT have unrelated “fire-and-forget” response shapes. They create a typed action resource. That resource is the authoritative record for policy evaluation, approval, queueing, execution, verification, cancellation, reversal and audit correlation.

An action is selected from a server-owned registry. Clients submit a type and schema-versioned arguments; they cannot submit a raw Python function name, shell string, arbitrary tool payload or unregistered URL as a substitute for an action type.

### 5.2 Endpoints

| Method and path | Purpose | Required baseline permission |
|---|---|---|
| `POST /api/v1/actions` | Validate and propose an action. | `actions:create` plus action-specific resource scope |
| `GET /api/v1/actions/{action_id}` | Read redacted state/result. | `actions:read` plus ownership |
| `GET /api/v1/actions` | Cursor-list caller-visible actions. | `actions:read` |
| `POST /api/v1/actions/{action_id}/approvals` | Record an approve/reject decision for the exact action digest. | `approvals:decide`, eligible human/session policy and recent auth |
| `POST /api/v1/actions/{action_id}/cancel` | Request cancellation; idempotent by action. | `actions:cancel` plus ownership/policy |
| `POST /api/v1/actions/{action_id}/reverse` | Propose a registered compensating action where supported. | Same action/approval policy as the compensating action |

### 5.3 States and transitions

The normal lifecycle is:

`proposed` → `awaiting_approval` → `approved` → `queued` → `running` → `verifying` → `succeeded`

Terminal or alternate states are `rejected`, `cancelled`, `expired`, `failed`, `partially_succeeded` and `reversed`. State changes are monotonic except that `reverse` creates a linked compensating action; it does not rewrite history. Cancellation is a request until the executor confirms a safe terminal state. A timed-out or disconnected client does not imply execution failure.

### 5.4 Create example

```http
POST /api/v1/actions HTTP/1.1
Host: om-automate.example.invalid
Authorization: Bearer ${OM_AUTOMATE_API_TOKEN}
Content-Type: application/json
Idempotency-Key: idem_example_create_email

{
  "type": "email.send",
  "schema_version": 1,
  "arguments": {
    "account_id": "email_account_example",
    "to": ["recipient@example.invalid"],
    "subject": "Example subject",
    "text": "Example body"
  },
  "resource_versions": {
    "email_account_example": "version_example"
  },
  "client_reference": "client_ref_example",
  "dry_run": false
}
```

Example response:

The server returns `201 Created`, a `Location: /api/v1/actions/act_example` header and the created resource. Creation of the resource does not assert that its side effect ran.

```json
{
  "data": {
    "id": "act_example",
    "version": "version_example",
    "type": "email.send",
    "schema_version": 1,
    "state": "awaiting_approval",
    "risk": "R2",
    "requested_by": {
      "principal_type": "api_token",
      "id": "tok_example"
    },
    "input_digest": "sha256:<canonical-action-digest>",
    "approval": {
      "required": true,
      "policy": "human_user_gesture",
      "expires_at": "2030-01-01T00:10:00Z"
    },
    "result": null,
    "error": null,
    "created_at": "2030-01-01T00:00:00Z",
    "updated_at": "2030-01-01T00:00:00Z"
  }
}
```

No API response echoes provider credentials. Sensitive action arguments are returned only to authorised users and are redacted by field classification; list and webhook views contain summaries by default.

### 5.5 Approval semantics

Risk follows the security model: R0 read-only, R1 reversible write, R2 external/meaningful side effect, R3 privileged, destructive or difficult-to-reverse action. R2 requires an explicit user gesture. R3 additionally requires recent authentication and any configured separation-of-duty rule.

An approval decision binds all of the following:

- approver and authenticated session/capability;
- action ID, type and schema version;
- canonical argument digest;
- affected resource versions and destination/account identity;
- risk and displayed consequence summary;
- approval policy version;
- issued and expiry times.

Changing a bound field invalidates the approval and returns the action to policy evaluation. Free-form model text, earlier chat consent and possession of an action ID are not approvals. The executor rechecks ownership, scopes, approval validity, integration state and resource versions immediately before the side effect.

```http
POST /api/v1/actions/act_example/approvals HTTP/1.1
Host: om-automate.example.invalid
Cookie: <secure-browser-session-placeholder>
X-CSRF-Token: <csrf-placeholder>
Content-Type: application/json
Idempotency-Key: idem_example_approval

{
  "decision": "approve",
  "input_digest": "sha256:<canonical-action-digest>",
  "action_version": "version_example"
}
```

Approval decisions require an idempotency key. Approving an already-approved identical version is idempotent. A different or stale digest returns `409 ACTION_CHANGED`; a stale resource version returns `412 RESOURCE_VERSION_CHANGED`. Rejection records a reason code and safe optional note. R3 recent-auth expiry returns `403 RECENT_AUTH_REQUIRED` with no credential details.

### 5.6 Status and execution result

`GET /api/v1/actions/{action_id}` is the only polling authority. `201` from action creation means the action resource exists, not that a side effect occurred; `202` from an inbound hook means its trigger was accepted, not that the task succeeded. Terminal success requires executor-specific verification. For email, “queued locally” is not “provider accepted”; for a task, “process started” is not “task succeeded”.

Results use typed, minimal fields:

```json
{
  "data": {
    "id": "act_example",
    "state": "succeeded",
    "result": {
      "type": "email.send.result.v1",
      "provider_message_id": "provider_message_example",
      "accepted_at": "2030-01-01T00:01:00Z"
    },
    "error": null,
    "completed_at": "2030-01-01T00:01:01Z"
  }
}
```

Partial success lists completed and uncompensated sub-operations without leaking content. A retry is a new execution attempt under the same action only when the action registry declares that safe and provides an idempotency strategy. Otherwise the client creates a new linked action.

## 6. Outbound webhook contract

### 6.1 Subscription and delivery resources

| Method and path | Purpose |
|---|---|
| `GET/POST /api/v1/webhook-subscriptions` | List or create caller-authorised subscriptions. |
| `GET/PATCH/DELETE /api/v1/webhook-subscriptions/{subscription_id}` | Inspect, update, disable/delete a subscription. Delete disables before retention cleanup. |
| `POST /api/v1/webhook-subscriptions/{subscription_id}/rotate-secret` | Return a new secret once and begin a bounded two-secret overlap. |
| `POST /api/v1/webhook-subscriptions/{subscription_id}/test` | Create a real test delivery resource; does not claim success before response receipt. |
| `GET /api/v1/webhook-deliveries/{delivery_id}` | Read state, attempts, safe status/error and next-attempt time. |
| `POST /api/v1/webhook-deliveries/{delivery_id}/retry` | Administrator retry of a dead-letter delivery under normal SSRF/signing rules. |

Create accepts an HTTPS target URL, exact versioned event types, optional non-secret description and enabled flag. In production mode, non-loopback plain HTTP is rejected. A signing secret with at least 256 bits of cryptographically random entropy is generated by the server and shown once. Secret creation/update fails closed if the encrypted secret store is unavailable.

Subscriptions expose `active_secret_id`, optional retiring-secret expiry, creation/update times and delivery health, never the secret value. Secret rotation signs with the new secret and MAY include one signature for the retiring secret during the documented overlap. The overlap defaults to 24 hours, is bounded by policy and is explicitly terminable.

### 6.2 Event catalogue and envelope

Event types are allowlisted and versioned independently, for example:

- `om.action.awaiting_approval.v1`
- `om.action.succeeded.v1`
- `om.action.failed.v1`
- `om.task.run.succeeded.v1`
- `om.webhook.test.v1`

Adding an event type does not subscribe existing endpoints to it. Chat or document content is excluded by default. Any content-bearing event requires a distinct event type, explicit permission, field-level minimisation, retention disclosure and an opt-in confirmation in the administration UI.

The target body is a CloudEvents-shaped JSON envelope; OM Automate does not claim full CloudEvents conformance until conformance tests pass:

```json
{
  "specversion": "1.0",
  "id": "evt_example",
  "type": "om.action.succeeded.v1",
  "source": "/api/v1/actions/act_example",
  "subject": "act_example",
  "time": "2030-01-01T00:01:01Z",
  "datacontenttype": "application/json",
  "data": {
    "action_id": "act_example",
    "action_type": "email.send",
    "state": "succeeded"
  }
}
```

The event ID identifies the logical event. The delivery ID identifies delivery of that event to one subscription and stays stable across retries.

### 6.3 Signing contract

The public-header ADR must ratify these target names before public preview. The proposed version-one headers are:

```text
OM-Webhook-Id: whd_example
OM-Webhook-Timestamp: <unix-seconds-placeholder>
OM-Webhook-Event: om.action.succeeded.v1
OM-Webhook-Attempt: <positive-integer-placeholder>
OM-Webhook-Signature: v1=<base64url-hmac-placeholder>
Idempotency-Key: whd_example
Content-Type: application/json
```

For each attempt, construct the signed byte sequence without JSON reserialisation:

```text
ASCII("v1.") || ASCII(timestamp) || ASCII(".") || ASCII(delivery_id) || ASCII(".") || raw_request_body
```

Compute HMAC-SHA256 with the subscription secret, encode the 32-byte result as unpadded base64url, and emit it as `v1=<value>`. If two secrets overlap, emit comma-separated `v1=<value>` entries and accept a match against either active secret. The event is authenticated by the raw signed body; receivers MUST also check that `OM-Webhook-Event` equals the body `type`. `OM-Webhook-Attempt` is informational and MUST NOT control a security decision.

Receiver verification order:

1. Reject a body larger than the configured cap before parsing; the default event cap is 256 KiB.
2. Require exactly one syntactically valid delivery ID and timestamp; reject unsupported signature versions.
3. Reject timestamps more than five minutes from receiver time, allowing a documented clock-skew tolerance rather than disabling freshness checks.
4. Compute HMAC over the exact received bytes and compare decoded bytes in constant time. Do not parse or transform JSON first.
5. Check the delivery ID in a durable idempotency store. If processing already committed, return the same 2xx acknowledgement without repeating the side effect.
6. Atomically claim the delivery ID, validate the event schema/type, process transactionally where possible, commit the outcome, then return 2xx.

Invalid signatures receive a generic `401`; logs identify subscription/delivery metadata only. A receiver retains the delivery ID for at least the greater of 24 hours and the advertised retry horizon. Clock errors and duplicates are observable without logging the secret, signature or raw content.

### 6.4 Delivery, retry and dead-letter semantics

- Only `200` through `299` acknowledge delivery. Redirects are never followed.
- Network errors, timeouts, `408`, `425`, `429` and `5xx` are retriable. Other `4xx` responses are terminal unless an administrator initiates a retry after correcting configuration.
- Initial delivery is followed by bounded, jittered attempts near 1 minute, 5 minutes, 30 minutes, 2 hours, 8 hours and 24 hours. `Retry-After` is honoured for `429`/`503` within the policy cap. Exact computed times are stored on the delivery.
- Every attempt has start/end time, outcome class, HTTP status, duration, resolved destination address metadata, response-size count and a sanitised error. Response bodies are not retained by default.
- Exhaustion enters `dead_letter`. It does not silently overwrite the last error on the subscription.
- A manual retry keeps the logical event immutable, creates an auditable new delivery lineage where necessary, and cannot bypass URL validation, signing or rate limits.
- `POST .../test` returns the delivery resource in `pending`/`delivering` state. The UI polls that resource and never displays “sent” merely because a background coroutine was queued.

### 6.5 SSRF and destination requirements

The existing outbound protections are required, not optional refactoring:

- allow only `http`/`https`, with HTTPS required for non-loopback production targets;
- reject URL credentials, malformed/ambiguous hosts, internal-use suffixes and unexpected ports by policy;
- resolve all addresses and reject private, loopback, link-local, multicast, reserved, unspecified and IPv4-mapped equivalents;
- fail closed on DNS errors or any mixed public/private answer;
- pin the approved address during connection while preserving the validated Host header and TLS SNI;
- revalidate before every attempt, including manual retry;
- disable redirects; cap connect/read/total time, request body and response bytes;
- use an isolated egress client with no ambient proxy credentials or cloud metadata access.

The direct provider URL option on chat must use the same resolve-and-pin primitive. A DNS-only pre-check is insufficient because resolution can change before connection.

## 7. Inbound signed task hooks

The target endpoint is:

```text
POST /api/v1/hooks/tasks/{hook_id}
```

`hook_id` is an opaque locator, not a credential. The per-hook secret is shown once at hook creation and never appears in a URL, QR payload, referrer, access log or query string. The request uses the same versioned signature, timestamp, delivery ID and raw-body algorithm as outbound webhooks.

Additional requirements:

- `Content-Type` is `application/json`; compressed bodies are disabled initially; the default maximum is 256 KiB.
- The body contains one allowlisted, versioned trigger type and schema-valid data. Data is treated as untrusted input, never as executable instructions or an authorisation to exceed the task's predefined capabilities.
- Signature, timestamp and durable delivery-ID replay checks complete before scheduling. The idempotency claim and run/action creation are atomic.
- Repeating the same valid delivery ID/body returns the original `202` result and cannot create a second run. Reusing the ID with a different body returns `409 DELIVERY_ID_REUSED`.
- A valid trigger returns `202` with a task-run/action reference and status URL; it does not claim task success.
- Disabled/expired hooks, bad signatures and unknown hook locators return a generic response that does not disclose a secret or task configuration.
- Secret rotation supports one bounded overlap; revocation is immediate and auditable.
- Per-hook, owner and source-network throttles apply before expensive parsing. Invalid-signature traffic has a stricter abuse limit.

Legacy `/api/tasks/{task_id}/webhook/{token}` links are marked deprecated, can be individually regenerated into the new form, and are disabled by default for fresh installations. Access logging MUST redact the legacy token while compatibility remains.

## 8. Rate limiting and load safety

Limits are enforced in a shared durable store so restart or multiple workers do not reset them. Keys combine the relevant IP, normalised account, owner, token ID, hook/subscription and route profile. Client-supplied forwarding headers are used only behind an explicitly trusted proxy configuration.

Initial safe profiles, adjustable downward or by a reviewed deployment policy, are:

| Profile | Baseline |
|---|---|
| Failed login/recent-auth | 5 attempts per 15 minutes per account and 10 per 15 minutes per source IP, with progressive delay |
| Ordinary authenticated reads | 120 requests per minute per token/user |
| Ordinary writes | 60 requests per minute per token/user |
| Action creation | 30 requests per minute per token/user and 10 concurrent non-terminal actions per owner by default |
| Approval decisions | 10 requests per minute per user, in addition to recent-auth controls |
| Inbound hooks | 60 valid requests per minute per hook and a stricter invalid-auth abuse bucket per source |

Expensive endpoints also have concurrency, queue-depth and cost budgets. A limit response is `429` with `Retry-After`, `RateLimit-Limit`, `RateLimit-Remaining` and `RateLimit-Reset`; it uses the common problem body. Rate-limit errors do not reveal whether an account, token or hook exists.

## 9. Audit and privacy requirements

The audit stream is append-only from application principals and records, at minimum:

- request ID, time, principal type/ID, owner, route, method, token ID, evaluated scopes and allow/deny result;
- action ID/type/schema/risk, canonical input digest, state transition, executor attempt and safe result category;
- approval decision, approver, recent-auth fact, policy version, bound digest/version and expiry;
- webhook subscription/delivery/event IDs, destination origin (credentials stripped), signature version/secret ID, attempt, status and SSRF decision;
- token/hook/webhook-secret creation, rotation, disablement and revocation;
- administrative policy/configuration changes.

Audit data MUST NOT include bearer/session tokens, webhook secrets/signatures, CSRF tokens, provider credentials, full message/document bodies, raw prompt context, attachment bytes or unsanitised third-party responses. Sensitive object names and destinations are minimised or pseudonymised according to purpose. Audit access is separately authorised and itself audited. Retention, export and deletion rules are configuration-backed and documented; immutable security facts retain only the minimum redacted data necessary.

Every action status, webhook delivery and problem response can be correlated by opaque IDs without exposing a secret. Application logs are supplementary diagnostics, not the authoritative audit store.

## 10. Migration plan

1. Build the central route/method/principal/scope registry and fail tests on unclassified API routes.
2. Add shared request IDs, problem responses, idempotency and durable rate limiting behind compatibility middleware.
3. Introduce the action store and adapters. Migrate email send, task run and cookbook/process launch first; preserve legacy response adapters while execution uses the new core.
4. Add approval policy/digest binding and executor revalidation. Remove direct bypasses for action-managed side effects.
5. Create target webhook subscription, delivery, attempt and hook-secret records. Migrate encrypted legacy secrets; fail closed rather than preserving plaintext fallback.
6. Issue target signed webhooks alongside legacy deliveries only for explicitly migrated subscriptions. Display verification tooling and observed receiver success before turning legacy delivery off.
7. Convert legacy task URL hooks to signed locators, redact legacy paths in logs, then disable legacy creation.
8. Replace companion QR bearer tokens with one-time pairing exchange grants. Existing companion tokens remain visible/revocable and are prompted for rotation.
9. Ratify the API-token prefix and public-header ADR, dual-read legacy machine identifiers, update bundled clients, then begin the measured deprecation window.

Migration scripts are restartable, transactionally checkpointed and tested on a copy of baseline data. They never silently create a second empty identity/token/webhook store when old data exists.

## 11. Verification and acceptance

### 11.1 Automated contract tests

- Snapshot the OpenAPI document and fail on an unreviewed breaking diff.
- Generate a client from the published schema and run create/status/approval/cancel/error/pagination examples against the application.
- Enumerate every API route and prove it is session-only or has explicit principal, scope, ownership, body, rate and idempotency policy. A newly added route without policy fails CI.
- Test every token scope for allowed method, denied sibling method, cross-owner lookup, revoked/expired token, rotation overlap and last-used audit behaviour.
- Test problem bodies for content type, stable code/request ID and absence of secrets, stack traces, paths and provider response bodies.

### 11.2 Action and approval tests

- Race identical and mismatched idempotency keys across workers; prove one logical action and deterministic replay/conflict responses.
- Exercise every state transition and reject impossible transitions, stale versions and late approvals.
- Forge and modify action arguments, destination, account, schema, resource version, actor and expiry after approval; every change must invalidate execution.
- Prove R2 requires a user gesture and R3 requires recent auth; an integration token cannot self-approve merely by owning the action.
- Kill/restart workers at queue, side-effect and verification boundaries; prove executor idempotency or explicit `partially_succeeded` handling.
- Verify the real external outcome before `succeeded`, including provider rejection and delayed task/process failure.

### 11.3 Webhook and hook tests

- Golden-vector tests cover exact raw bytes, base64url encoding, wrong secret, wrong version, altered body/ID/timestamp, comma-separated rotation signatures and constant-time comparison behaviour.
- Replay tests cover duplicate requests before processing, during processing, after commit, after receiver restart and across multiple workers.
- Delivery tests cover every retry class, `Retry-After`, jitter bounds, 2xx acknowledgement, non-followed redirects, timeout, response cap, dead-letter and manual retry lineage.
- SSRF tests cover IPv4/IPv6, IPv4-mapped IPv6, decimal/octal/encoded hosts, credentials, internal suffixes, mixed DNS answers, rebinding between validation and connection, redirects to private space and cloud metadata addresses.
- Inbound tests enforce the pre-parse body cap, content type, schema/event allowlist, disabled/expired hook, secret overlap/revocation, per-hook rate limit and atomic delivery-ID/run creation.
- Privacy tests prove metadata events omit chat/email/document content and webhook/list/log APIs never return secrets or signatures.

### 11.4 Operational evidence

Before launch, retain evidence of:

- passing contract, security, migration, restart and multi-worker suites;
- an OpenAPI artefact and receiver verification guide matching the deployed build;
- rate-limit, queue saturation, webhook failure and dead-letter dashboards/alerts;
- successful token, hook and webhook-secret rotation drills;
- restore tests preserving revocation, idempotency and audit state;
- a route/scope inventory reviewed by security and product owners;
- closure of every High item in section 3 with a code reference and test reference.

The system is not verified merely because an endpoint returns `200`, a job is queued or a test webhook coroutine starts. Verification requires authenticated policy enforcement, one-time/idempotent execution, durable status, confirmed side effect, redacted audit evidence and recovery behaviour under retries and restarts.
