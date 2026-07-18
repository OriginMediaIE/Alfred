# ADR-0001: Agent tool cancellation ownership

- **Status:** Accepted for SAFE-001
- **Date:** 2026-07-18
- **Decision owners:** OM Automate agent/runtime architecture
- **Related backlog:** `SAFE-001`, prerequisite for `SAFE-002`, `SAFE-005`, and `SAFE-007`

## Context

Normal chat/agent streams are detached from their SSE subscribers by `src/agent_runs.py`. This is intentional: closing a tab, changing sessions, or losing a network connection must not automatically terminate useful background work. An explicit Stop request calls `agent_runs.stop(session_id)`, which cancels the detached drain task.

Inside `stream_agent_loop()`, each selected tool is currently started as a separate `asyncio` child task so progress can be drained concurrently. The outer generator does not own that task in a `finally` block. Cancellation while waiting for the next progress event exits the generator but leaves the child running.

That violates the final behavioral contract. A UI state of stopped/cancelled cannot coexist with an untracked ongoing effect.

## Decision

Introduce a dependency-neutral `CancellableToolRun` lifecycle primitive with these responsibilities:

1. It is the sole owner of one in-process child tool task.
2. It creates and drains the tool's progress channel without granting any authority or interpreting tool data.
3. Its `close()` operation cancels and awaits a still-running child.
4. Closing is idempotent.
5. Normal result and exception propagation remain unchanged.
6. `stream_agent_loop()` must wrap the complete progress/result sequence in `try/finally` and call `close()`.

The detached run remains independent of SSE subscription lifetime. Only explicit Stop, replacement by a new run, process shutdown, or an actual outer execution failure closes the agent generator and therefore the current tool child.

## Cancellation state semantics

This first slice establishes local task ownership, not remote effect certainty:

```text
running
  ├─ normal return ───────────────→ completed (not yet provider-verified)
  ├─ local cancellation confirmed → cancelled
  ├─ cancellation after effect ───→ partially completed / completed
  └─ provider state unknown ──────→ failed or indeterminate, never "reversed"
```

The current run API only exposes `running | done | error | stopped`. SAFE-005/SAFE-007 will replace that coarse state with durable action attempts and explicit verification/reconciliation. Until then, this change guarantees only that no owned in-process task survives the outer run.

## Consequences

### Positive

- Stop reaches shell/Python adapters through `CancelledError`, allowing their existing process cleanup to run.
- MCP/provider coroutines receive cancellation rather than becoming orphan tasks.
- Normal completion and progress streaming remain structurally unchanged.
- The lifecycle module is acyclic and can become the local execution primitive beneath the future typed registry.

### Limitations

- Cancelling a coroutine cannot prove that a remote provider did not already commit an effect.
- A provider or thread that suppresses cancellation can still delay cleanup; registry-owned deadlines/worker isolation follow in SAFE-002/SAFE-008.
- This ADR does not add durable state, generic approval, idempotency, compensation, or readback verification.

### Risks and mitigations

- **Race with normal completion:** cancel only when the child is not done; result retrieval remains the normal path.
- **Double close:** make close idempotent.
- **Cancellation masking:** suppress only the child's expected `CancelledError`; do not swallow ordinary tool exceptions.
- **Subscriber disconnect:** retain the existing separation between subscriber teardown and explicit detached-run cancellation.
- **Cleanup hang:** the immediate primitive awaits cooperative cancellation; bounded adapter/worker deadlines are a follow-up release gate.

## Alternatives considered

### Keep an untracked `asyncio.create_task`

Rejected because it reproduces the confirmed safety defect.

### Execute tools inline without a child task

Rejected for now because the current UI depends on concurrent progress events. It would also couple tool adapters directly to SSE emission.

### Cancel every detached run on SSE disconnect

Rejected because it breaks intentional background/reconnect behavior and makes ordinary navigation destructive.

### Implement durable workflow orchestration first

Deferred. Durable action state is required, but the local orphan-task defect is independently dangerous and can be fixed/tested in a small compatibility-preserving slice.

## Verification

- A regression cancels a consumer while its child is blocked, asserts that child cleanup runs, and asserts no child remains active when the consumer settles.
- Normal completion returns its value and preserves progress ordering.
- Tool exceptions still propagate.
- Existing detached subscriber-disconnect, explicit Stop, partial-save, and normal-completion tests pass.
- Related agent/tool suites, the full suite, startup probes, and a browser Stop check run before the checkpoint.

## Follow-up decisions

- ADR for the canonical typed tool/action registry and model action envelope.
- ADR for durable run/action/approval/idempotency/verification records.
- ADR for isolated workers, secret-safe environments, filesystem capabilities, and bounded cancellation deadlines.
