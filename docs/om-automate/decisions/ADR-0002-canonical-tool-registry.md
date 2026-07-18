# ADR-0002: Canonical typed tool registry and compatibility migration

- **Status:** Accepted; incremental implementation in SAFE-002
- **Date:** 2026-07-18
- **Decision owners:** OM Automate agent, security, and integration architecture
- **Related backlog:** `SAFE-002`, prerequisite for `SAFE-003` through `SAFE-008`

## Context

Odysseus currently describes built-in tools in independent schema, fence-tag, handler, prompt, retrieval-index, policy, admin-UI, and dispatcher structures. The five primary inventories contain 67, 73, 31, 58, and 69 names respectively; their union contains 74 names and their intersection only 27. Three additional vault executors are latent in the dispatcher. This is observable breakage, not just duplication: `tail_serve_output` has a native schema and executor but is absent from the tag gate, so both native and fenced calls are rejected.

The import graph also prevents dependency-safe reuse. A fresh import of either `src.tool_schemas` or `src.tool_parsing` re-enters the `src.agent_tools` facade and fails on a partially initialized module. Security and execution code work around the cycle through import order and a dynamic `__import__` hack.

The OM Automate contract requires every tool to declare typed input and output, domain, permissions, four-level risk, confirmation, reversibility, timeout, retry, idempotency, audit, compensation, verification, and user-facing examples. Those fields must become enforceable inputs to execution, not descriptive defaults added after dispatch.

Several legacy tools multiplex materially different operations under one name. For example, a `manage_calendar` list is read-only while deletion is destructive. Assigning one permissive risk to the wrapper would be unsafe; assigning Level 3 to every operation would preserve safety but make normal reads unusable.

## Decision

### 1. Dependency-light contracts

Create a module that owns immutable shared value types, including `ToolBlock` and the eventual structured `ToolInvocation`. It imports no facade, handlers, database, routes, provider clients, or UI modules. Parsing, schema conversion, execution, and the compatibility facade depend inward on this module.

### 2. One canonical definition per operation

The registry owns immutable `ToolDefinition` records. Each definition contains:

- canonical name, description, domain, and declared surfaces;
- object input and output JSON schemas;
- granular permission scopes;
- `RiskLevel` 0 through 3 and `ConfirmationPolicy`;
- timeout and typed retry policy;
- idempotency behavior and optional key strategy;
- reversibility and compensation policy;
- audit/redaction policy and required audit fields;
- verification policy;
- success and failure examples;
- presentation metadata;
- a stable runtime binding key, not an eagerly imported callable.

Aliases are separate mappings to canonical definitions and cannot carry independent policy. Duplicate canonical names or alias collisions fail validation.

### 3. Surfaces are explicit, not assumed equal

A definition declares whether it is available to native function calling, fenced local-model parsing, retrieval selection, prompt assembly, administrator controls, internal execution, or dynamic MCP exposure. Compatibility lists are generated from those declarations. An internal capability such as a vault adapter can remain hidden from model surfaces without becoming an undocumented executor.

This prevents registry parity from accidentally expanding model authority merely to make set counts equal.

### 4. Metadata and runtime binding remain acyclic

Definitions reference a stable binding key. A runtime binder attaches or resolves callables only after implementation modules are initialized. Registry import must never start databases, import routes, connect providers, load embeddings, or instantiate MCP clients.

Every enabled executable definition must resolve to exactly one binding, and every binding must have exactly one definition. The legacy dispatcher remains behind an explicit compatibility binding while domains migrate; it is not considered the final architecture.

### 5. Policy is resolved after argument validation

Simple tools carry one static effective policy. Multiplexed legacy wrappers carry a discriminated operation-policy table or resolver. The execution order is:

1. canonicalize the name;
2. parse and validate structured arguments;
3. resolve the exact operation policy;
4. enforce permission and confirmation;
5. apply idempotency, timeout, and retry rules;
6. execute the binding;
7. verify important effects;
8. compensate or reconcile partial failure;
9. persist the immutable audit outcome.

Unknown actions, methods, or ambiguous policy resolve fail-closed at Level 3 with explicit confirmation; they never inherit a read-only default. Long term, broad wrappers are split into operation-level definitions such as `calendar.list_events`, `calendar.create_event`, and `calendar.delete_event`, with the old tool name retained only as a compatibility router.

### 6. Conservative dynamic MCP adaptation

MCP tools are registered in a separate dynamic namespace at discovery time. Trustworthy read-only/destructive annotations may inform policy, but third-party descriptions never grant authority. Missing or ambiguous annotations default to consequential or destructive risk, explicit confirmation, a server-scoped permission, no automatic retry, a generic bounded output schema, redacted audit input, and no claim of reversibility.

### 7. Compatibility views migrate before removal

Existing imports from `src.agent_tools` remain supported while callers move to generated views. The migration order is:

1. repair `tail_serve_output` reachability and extract shared types/aliases to break cold imports;
2. add immutable contracts, strict validation, and a golden inventory;
3. classify and migrate core/filesystem/shell, documents/sessions, personal-data domains, email, cookbook, admin/integration, image, and research tools;
4. derive schemas, fence tags, retrieval/prompt descriptions, UI metadata, and security policy from classified records;
5. replace the long dispatcher and remove import-order workarounds;
6. register dynamic MCP definitions and enforce registry timeouts/retries;
7. connect approval, audit, idempotency, verification, and compensation services.

No intermediate compatibility default may be described as enforced safety metadata. Unclassified legacy records remain visibly `legacy_unclassified`, cannot receive a lower risk through omission, and prevent SAFE-002 from being marked complete.

## Validation invariants

Registry validation must prove:

- canonical names and aliases are unique and normalized;
- every enabled executable surface has one definition and one binding;
- input and output schemas are JSON object schemas;
- descriptions, domains, permissions, examples, presentation, audit, and verification fields are present;
- timeouts are positive and bounded;
- retries are bounded and cannot apply to non-idempotent effects without an idempotency key;
- Level 3 always requires explicit confirmation and Level 2 requires it by default;
- read-only operations declare no mutation compensation;
- reversible effectful operations declare a compensation strategy;
- examples conform to their declared schemas;
- every compatibility view equals the registry surface it claims to represent;
- aliases resolve to a definition and cannot bypass that definition's policy;
- unknown dynamic tools fail closed.

Development and test startup rejects invalid static definitions. Production does not silently enable an invalid tool: it disables the affected capability, emits a redacted high-severity audit event, and exposes an administrator-visible health error.

## Consequences

### Positive

- Importing registry contracts is deterministic and side-effect free.
- One reviewed definition drives model exposure, user controls, execution policy, audit, and presentation.
- Adding a tool without policy or a handler becomes a test/startup failure rather than latent drift.
- Mixed legacy tools can migrate without weakening policy or breaking all reads.
- Dynamic providers enter through the same deny-by-default policy boundary.

### Costs and risks

- Migration touches high-fan-out modules and must remain compatibility tested.
- Operation-level policy tables expose ambiguous legacy actions that require redesign.
- Existing timeout behavior will change when metadata becomes enforcement; long-running tools need progress-aware, cancellable budgets.
- The registry cannot by itself provide approval, audit durability, provider read-back, or compensation. Those are separate consumers and release gates.

## Alternatives considered

### Add missing names to each existing set

Rejected as a durable solution because it preserves the drift mechanism, import cycle, and absent policy contract. A one-line tag repair is still appropriate as the first regression fix.

### Put handlers directly in every definition

Rejected because importing the catalog would import heavy implementations and recreate cycles/provider side effects. Binding keys preserve type and parity checks without eager initialization.

### Assign one conservative Level 3 policy to every mixed tool

Rejected as the target because it makes routine reads require destructive-action approval. It is acceptable only as the temporary fail-closed result for unknown actions.

### Trust MCP descriptions or annotations completely

Rejected because third-party servers are outside the OM trust boundary and annotations may be absent, stale, or malicious.

## Initial verification

- Fresh subprocess imports for schemas, parsing, contracts, and registry.
- Native and fenced `tail_serve_output` conversion.
- Duplicate, immutability, required-field, schema, timeout, retry, confirmation, alias, and surface-inventory tests.
- Explicit golden inventory that accounts for latent vault executors and deliberately retired aliases.
- Existing unknown-call, malformed-call, email alias, plan-mode, parser/stripper, handler-context, schema-selection, and MCP tests.
- Full suite, fresh application startup, and browser tool smoke at every switch from a legacy list to a generated view.
