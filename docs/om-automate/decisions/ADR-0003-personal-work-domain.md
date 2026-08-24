# ADR-0003: Separate personal work from scheduled automations

- **Status:** Accepted for Phase Ten implementation
- **Date:** 2026-07-18
- **Decision owners:** OM Automate maintainers

## Context

The existing `ScheduledTask` record and `/api/tasks` routes describe executable automations: LLM prompts, research jobs and built-in actions with time, event or webhook triggers. Its `active`, `paused` and `completed` states control a scheduler. It has execution runs, model endpoints, output targets and bearer webhook tokens.

Phase Ten requires a different aggregate: user work with descriptions, projects, subtasks, dependencies, effort, contexts, provenance, commitments, reminders, recurrence, completion evidence and correctable planning proposals. Reinterpreting scheduler fields would break existing automation data and UI behaviour. Treating notes/checklists as canonical would lose project and source relationships.

The generic action ledger is the authority for agent approval and immutable execution audit. A personal-work service must not invent a parallel agent approval mechanism, although it still needs domain-level review states for extracted commitments and proposed plans.

## Decision

1. Add a versioned `work_*` schema alongside `scheduled_tasks`.
2. Store owners as a non-null canonical key (`""` for the deliberate single-user compatibility tenant) and require every query and relationship check to match that key exactly. Null/shared wildcard queries are forbidden.
3. Keep scheduled automations unchanged. On schema initialisation, idempotently create read-only `work_tasks` projections linked by unique `legacy_scheduled_task_id`. The projection records retain source/provenance and may be rebuilt without deleting the legacy row.
4. Use relational records for projects, milestones, tasks, dependencies, reminders, commitments, references, planning drafts and append-only mutation receipts. Flexible bounded lists and planning payloads use canonical JSON text so SQLite and existing backup tooling remain compatible.
5. Validate the dependency graph before commit. Self, cross-owner and cyclic dependencies are rejected.
6. Treat recurrence and reminders as planning metadata in this domain. Phase Ten does not silently create scheduler jobs, calendar events, messages or other external effects.
7. Direct authenticated user writes use `actor_kind=user`. Agent writes use `actor_kind=agent` and must present an owner-matching action-ledger row for the canonical Phase Ten tool in `executing` state. Without that evidence, mutation fails closed. Migration writes use the internal `migration` actor.
8. Store extracted commitments as `suggested` until the user approves or rejects them. Every commitment retains structured source fields and optional typed references.
9. Store generated focus/breakdown/rescheduling plans as revisioned drafts. Users can edit a draft before applying it; applying is a separate mutation.

## Consequences

### Positive

- Existing scheduled tasks, runs, webhooks and Tasks UI remain compatible.
- Personal tasks get coherent status, dependency, provenance and project semantics.
- Owner isolation is enforceable at every aggregate boundary.
- Agent approval evidence and domain audit receipts can be joined by action ID.
- Planning suggestions remain correctable rather than being silently executed.

### Costs and limitations

- The product temporarily has two task concepts: personal work and scheduled automations. UI copy and migration documentation must distinguish them.
- Legacy projections are read-only; editing the automation still occurs through the legacy route/tool and the projection refreshes on the next backfill.
- A later reconciled registry/dispatcher patch must register the Phase Ten tool and pass its claimed action ID into the handler.
- Provider/calendar work-block execution remains a later approved integration, not an implicit side effect of applying a local plan.

## Alternatives rejected

- **Expand `ScheduledTask`:** rejected because personal completion and automation lifecycle states conflict and scheduler code assumes the existing shape.
- **Use notes/checklists:** rejected because they lack projects, graph validation, commitment provenance and planning revisions.
- **Store the whole domain in one JSON document:** rejected because owner isolation, dependency integrity, filtering, migrations and audit joins would be fragile.
- **Let the new service self-approve agent writes:** rejected because approval authority belongs to the generic action ledger outside the model/tool handler.
