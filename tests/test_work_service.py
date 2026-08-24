from __future__ import annotations

from datetime import datetime, timedelta
import json

import pytest

from core.database import AgentAction, ScheduledTask
from src.work_models import WorkMutationReceipt, WorkTask
from src.work_service import (
    MutationContext,
    WorkApprovalRequired,
    WorkConflict,
    WorkNotFound,
    WorkValidationError,
)
from tests.work_support import make_work_service


@pytest.fixture
def work_env():
    service, sessions, bind = make_work_service()
    try:
        yield service, sessions
    finally:
        bind.dispose()


def _user(owner="alice"):
    return MutationContext.user(owner, correlation_id="request-1")


def _seed_executing_action(sessions, *, action_id="action-1", owner="alice", tool="manage_work"):
    db = sessions()
    try:
        now = datetime.utcnow()
        db.add(
            AgentAction(
                id=action_id,
                owner=owner,
                session_id="session-1",
                request_id="request-1",
                correlation_id="request-1",
                requested_tool=tool,
                tool_name=tool,
                tool_version=1,
                surface="native",
                origin="agent",
                arguments_json="{}",
                arguments_hash="a" * 64,
                execution_context_json="{}",
                idempotency_key=f"key-{action_id}",
                risk_level=1,
                approval_reason="test",
                status="executing",
                expires_at=now + timedelta(minutes=10),
                revision=1,
                approval_consumed_at=now,
                execution_started_at=now,
            )
        )
        db.commit()
    finally:
        db.close()


def test_full_project_and_task_shape_round_trips(work_env):
    service, _ = work_env
    project = service.create_project(
        "alice",
        {
            "title": "House renovation",
            "goal": "Renovate the kitchen",
            "desired_outcome": "A usable finished kitchen",
            "status": "active",
            "area": "Home",
            "notes": "Keep the sink usable",
            "risks": [{"title": "Permit delay", "severity": "high"}],
            "decisions": [{"title": "Use oak fronts", "decided_at": "2026-07-18"}],
            "tags": ["Renovation", "2026"],
            "budget": {
                "enabled": True,
                "currency": "eur",
                "amount_minor": 2_000_000,
                "spent_minor": 250_000,
            },
            "start_at": "2026-08-01",
            "target_at": "2026-10-01",
            "progress_summary": "Planning",
            "milestones": [
                {"title": "Design approved", "target_at": "2026-08-10", "sort_order": 1}
            ],
            "references": [
                {"type": "document", "external_id": "doc-1", "label": "Design"},
                {"type": "contact", "external_id": "contact-1", "label": "Builder"},
                {"type": "meeting", "external_id": "meeting-1", "label": "Kickoff"},
            ],
        },
        context=_user(),
    )
    assert project["budget"] == {
        "enabled": True,
        "currency": "EUR",
        "amount_minor": 2_000_000,
        "spent_minor": 250_000,
    }
    assert project["milestones"][0]["title"] == "Design approved"
    assert {ref["type"] for ref in project["references"]} == {
        "document",
        "contact",
        "meeting",
    }

    prerequisite = service.create_task(
        "alice", {"title": "Approve design", "project_id": project["id"]}, context=_user()
    )
    task = service.create_task(
        "alice",
        {
            "title": "Order cabinets",
            "description": "Order after design approval",
            "status": "ready",
            "priority": "high",
            "start_at": "2026-08-11T09:00:00Z",
            "due_at": "2026-08-12T17:00:00Z",
            "estimated_minutes": 90,
            "actual_minutes": 0,
            "project_id": project["id"],
            "milestone_id": project["milestones"][0]["id"],
            "area": "Home",
            "tags": ["Purchasing", "purchasing"],
            "contexts": ["computer"],
            "assignees": ["Alice", "Builder"],
            "energy": "medium",
            "effort": 3,
            "recurrence": {"frequency": "weekly", "interval": 2, "weekdays": [4, 1]},
            "dependency_ids": [prerequisite["id"]],
            "source_type": "email",
            "source_id": "message-7",
            "source_excerpt": "Please order the cabinets",
            "references": [
                {"type": "email", "external_id": "message-7"},
                {"type": "calendar_event", "external_id": "event-2"},
            ],
            "reminders": [
                {
                    "remind_at": "2026-08-12T09:00:00Z",
                    "message": "Order today",
                    "recurrence": {"frequency": "daily", "interval": 1, "count": 2},
                }
            ],
        },
        context=_user(),
    )
    assert task["tags"] == ["Purchasing"]
    assert task["dependency_ids"] == [prerequisite["id"]]
    assert task["recurrence"]["weekdays"] == [1, 4]
    assert task["source"]["id"] == "message-7"
    assert {ref["type"] for ref in task["references"]} == {"email", "calendar_event"}
    assert task["reminders"][0]["recurrence"]["count"] == 2
    assert task["created_by"] == "user"
    assert task["approval_state"] == "not_required"


def test_updates_preserve_unspecified_json_and_budget_fields(work_env):
    service, _ = work_env
    project = service.create_project(
        "alice",
        {
            "title": "P",
            "risks": [{"title": "R"}],
            "decisions": [{"title": "D"}],
            "tags": ["tag"],
            "budget": {"enabled": True, "currency": "USD", "amount_minor": 1000},
        },
        context=_user(),
    )
    updated_project = service.update_project(
        "alice",
        project["id"],
        {"budget": {"spent_minor": 100}},
        expected_revision=project["revision"],
        context=_user(),
    )
    assert updated_project["risks"] == [{"title": "R"}]
    assert updated_project["decisions"] == [{"title": "D"}]
    assert updated_project["tags"] == ["tag"]
    assert updated_project["budget"] == {
        "enabled": True,
        "currency": "USD",
        "amount_minor": 1000,
        "spent_minor": 100,
    }

    task = service.create_task(
        "alice",
        {
            "title": "T",
            "tags": ["tag"],
            "contexts": ["home"],
            "assignees": ["Alice"],
            "recurrence": {"frequency": "daily", "interval": 1},
        },
        context=_user(),
    )
    updated = service.update_task(
        "alice",
        task["id"],
        {"description": "changed"},
        expected_revision=task["revision"],
        context=_user(),
    )
    assert updated["tags"] == ["tag"]
    assert updated["contexts"] == ["home"]
    assert updated["assignees"] == ["Alice"]
    assert updated["recurrence"]["frequency"] == "daily"


def test_owner_isolation_including_single_user_compatibility_tenant(work_env):
    service, _ = work_env
    alice = service.create_task("alice", {"title": "Alice only"}, context=_user("alice"))
    local = service.create_task(None, {"title": "Local only"}, context=_user(None))

    assert [item["id"] for item in service.list_tasks("alice")] == [alice["id"]]
    assert [item["id"] for item in service.list_tasks(None)] == [local["id"]]
    assert service.list_tasks("bob") == []
    with pytest.raises(WorkNotFound):
        service.get_task("bob", alice["id"])
    with pytest.raises(WorkNotFound):
        service.update_task(
            "bob", alice["id"], {"title": "stolen"}, context=_user("bob")
        )


def test_dependency_and_subtask_cycles_and_cross_owner_edges_are_rejected(work_env):
    service, _ = work_env
    a = service.create_task("alice", {"title": "A"}, context=_user())
    b = service.create_task(
        "alice", {"title": "B", "dependency_ids": [a["id"]]}, context=_user()
    )
    with pytest.raises(WorkValidationError, match="cycle"):
        service.update_task(
            "alice", a["id"], {"dependency_ids": [b["id"]]}, context=_user()
        )
    with pytest.raises(WorkValidationError, match="own parent"):
        service.update_task(
            "alice", a["id"], {"parent_task_id": a["id"]}, context=_user()
        )
    child = service.create_task(
        "alice", {"title": "Child", "parent_task_id": a["id"]}, context=_user()
    )
    with pytest.raises(WorkValidationError, match="cycle"):
        service.update_task(
            "alice", a["id"], {"parent_task_id": child["id"]}, context=_user()
        )
    foreign = service.create_task("bob", {"title": "Foreign"}, context=_user("bob"))
    with pytest.raises(WorkNotFound):
        service.update_task(
            "alice", a["id"], {"dependency_ids": [foreign["id"]]}, context=_user()
        )


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"title": "", "effort": 1}, "title is required"),
        ({"title": "T", "priority": "critical"}, "priority must be one of"),
        ({"title": "T", "effort": 6}, "effort must be between"),
        ({"title": "T", "start_at": "2026-08-02", "due_at": "2026-08-01"}, "after due_at"),
        ({"title": "T", "recurrence": {"frequency": "sometimes"}}, "recurrence.frequency"),
    ],
)
def test_task_validation(payload, message, work_env):
    service, _ = work_env
    with pytest.raises(WorkValidationError, match=message):
        service.create_task("alice", payload, context=_user())


def test_commitment_provenance_review_and_overdue_detection(work_env):
    service, _ = work_env
    commitment = service.create_commitment(
        "alice",
        {
            "title": "Send the proposal",
            "description": "Promised during the call",
            "due_at": "2026-07-10T12:00:00Z",
            "counterparty": "Sarah",
            "source_type": "meeting",
            "source_id": "meeting-42",
            "source_url": "https://example.invalid/meetings/42",
            "source_excerpt": "I will send it Friday",
            "source_occurred_at": "2026-07-03T10:00:00Z",
            "confidence": 93,
            "review_state": "suggested",
            "references": [{"type": "meeting", "external_id": "meeting-42"}],
        },
        context=_user(),
    )
    assert commitment["source"]["excerpt"] == "I will send it Friday"
    assert service.overdue_commitments("alice", as_of="2026-07-18")[0]["id"] == commitment["id"]

    approved = service.update_commitment(
        "alice",
        commitment["id"],
        {"review_state": "approved"},
        expected_revision=commitment["revision"],
        context=_user(),
    )
    with pytest.raises(WorkConflict, match="cannot transition"):
        service.update_commitment(
            "alice",
            commitment["id"],
            {"review_state": "suggested"},
            expected_revision=approved["revision"],
            context=_user(),
        )
    fulfilled = service.update_commitment(
        "alice",
        commitment["id"],
        {"status": "fulfilled", "completion_notes": "Sent via email"},
        expected_revision=approved["revision"],
        context=_user(),
    )
    assert fulfilled["fulfilled_at"] is not None
    assert service.overdue_commitments("alice", as_of="2026-07-18") == []


def test_focus_excludes_blocked_tasks_and_respects_duration_budget(work_env):
    service, _ = work_env
    prerequisite = service.create_task(
        "alice", {"title": "Prerequisite", "priority": "low", "estimated_minutes": 30}, context=_user()
    )
    blocked = service.create_task(
        "alice",
        {
            "title": "Blocked urgent",
            "priority": "urgent",
            "estimated_minutes": 30,
            "dependency_ids": [prerequisite["id"]],
        },
        context=_user(),
    )
    urgent = service.create_task(
        "alice",
        {
            "title": "Urgent ready",
            "priority": "urgent",
            "energy": "high",
            "contexts": ["office"],
            "estimated_minutes": 45,
            "due_at": "2026-07-18T12:00:00Z",
        },
        context=_user(),
    )
    service.create_task(
        "alice",
        {"title": "Long low", "priority": "low", "estimated_minutes": 120},
        context=_user(),
    )

    blocked_rows = service.blocked_tasks("alice")
    assert blocked_rows[0]["id"] == blocked["id"]
    focus = service.daily_focus(
        "alice",
        plan_date="2026-07-18",
        available_minutes=60,
        energy="high",
        contexts=["office"],
    )
    assert [row["id"] for row in focus["tasks"]] == [urgent["id"]]
    assert focus["scheduled_minutes"] == 45


def test_correctable_breakdown_and_reschedule_plans(work_env):
    service, _ = work_env
    plan = service.create_plan(
        "alice",
        {
            "plan_type": "breakdown",
            "goal": "Prepare launch",
            "steps": [
                {"title": "Draft announcement", "estimated_minutes": 45},
                {"title": "Publish announcement", "estimated_minutes": 15},
            ],
        },
        context=_user(),
    )
    corrected = service.update_plan(
        "alice",
        plan["id"],
        {
            "proposals": [
                {"title": "Review announcement", "estimated_minutes": 30, "priority": "high"}
            ]
        },
        expected_revision=plan["revision"],
        context=_user(),
    )
    applied = service.apply_plan(
        "alice",
        plan["id"],
        expected_revision=corrected["revision"],
        context=_user(),
    )
    assert applied["plan"]["status"] == "applied"
    assert [item["title"] for item in applied["affected"]] == ["Review announcement"]
    assert service.list_tasks("alice")[0]["source"] == {
        "type": "work_plan",
        "id": plan["id"],
        "url": "",
        "excerpt": "",
    }

    task = applied["affected"][0]
    reschedule = service.create_plan(
        "alice",
        {"plan_type": "reschedule", "plan_date": "2026-08-01", "task_ids": [task["id"]]},
        context=_user(),
    )
    result = service.apply_plan(
        "alice",
        reschedule["id"],
        expected_revision=reschedule["revision"],
        context=_user(),
    )
    assert result["affected"][0]["due_at"].startswith("2026-08-01")


def test_agent_mutations_require_matching_executing_ledger_action(work_env):
    service, sessions = work_env
    with pytest.raises(WorkApprovalRequired, match="requires an approved"):
        service.create_task(
            "alice",
            {"title": "No bypass"},
            context=MutationContext.agent("alice", action_id=None),
        )

    _seed_executing_action(sessions)
    task = service.create_task(
        "alice",
        {"title": "Approved agent task"},
        context=MutationContext.agent(
            "alice", action_id="action-1", correlation_id="request-1"
        ),
    )
    assert task["created_by"] == "agent"
    assert task["approval_state"] == "approved"
    assert task["action_id"] == "action-1"
    receipts = service.list_receipts("alice", entity_id=task["id"])
    assert receipts[0]["action_id"] == "action-1"
    assert receipts[0]["actor_kind"] == "agent"

    with pytest.raises(WorkApprovalRequired, match="already been used"):
        service.create_task(
            "alice",
            {"title": "Replayed action"},
            context=MutationContext.agent(
                "alice", action_id="action-1", correlation_id="request-1"
            ),
        )

    with pytest.raises(WorkApprovalRequired, match="missing, belongs"):
        service.create_task(
            "bob",
            {"title": "Cross-owner bypass"},
            context=MutationContext.agent("bob", action_id="action-1"),
        )


def test_legacy_backfill_is_idempotent_owner_scoped_and_read_only():
    service, sessions, bind = make_work_service()
    db = sessions()
    try:
        alice_legacy = ScheduledTask(
            id="scheduled-alice",
            owner="alice",
            name="Daily briefing",
            prompt="Prepare briefing",
            task_type="llm",
            schedule="daily",
            scheduled_time="09:00",
            next_run=datetime(2026, 7, 19, 9, 0),
            status="active",
        )
        local_legacy = ScheduledTask(
            id="scheduled-local",
            owner=None,
            name="Local reminder",
            prompt="Remember",
            task_type="llm",
            schedule="once",
            scheduled_time="09:00",
            status="paused",
        )
        db.add_all([alice_legacy, local_legacy])
        db.commit()
    finally:
        db.close()

    try:
        assert service.backfill_legacy_scheduled_tasks() == {"created": 2, "updated": 0}
        assert service.backfill_legacy_scheduled_tasks() == {"created": 0, "updated": 0}
        alice = service.list_tasks("alice")[0]
        local = service.list_tasks(None)[0]
        assert alice["legacy_scheduled_task_id"] == "scheduled-alice"
        assert alice["recurrence"]["frequency"] == "daily"
        assert local["legacy_scheduled_task_id"] == "scheduled-local"
        assert service.list_tasks("bob") == []
        with pytest.raises(WorkConflict, match="read-only"):
            service.update_task(
                "alice", alice["id"], {"title": "Changed"}, context=_user()
            )
        db = sessions()
        try:
            untouched = db.query(ScheduledTask).filter(ScheduledTask.id == "scheduled-alice").one()
            assert untouched.name == "Daily briefing"
            assert untouched.status == "active"
            assert db.query(WorkMutationReceipt).filter(
                WorkMutationReceipt.operation == "legacy_backfill"
            ).count() == 2
        finally:
            db.close()
    finally:
        bind.dispose()


def test_completion_updates_project_progress_and_due_reminders(work_env):
    service, _ = work_env
    project = service.create_project("alice", {"title": "P"}, context=_user())
    task = service.create_task(
        "alice",
        {
            "title": "T",
            "project_id": project["id"],
            "reminders": [
                {"remind_at": "2026-07-18T08:00:00Z", "message": "Start"},
                {"remind_at": "2026-07-20T08:00:00Z", "message": "Later"},
            ],
        },
        context=_user(),
    )
    assert len(service.pending_reminders("alice", due_before="2026-07-19")) == 1
    completed = service.update_task(
        "alice",
        task["id"],
        {"status": "completed", "actual_minutes": 25, "completion_notes": "Done"},
        context=_user(),
    )
    assert completed["completed_at"] is not None
    assert service.get_project("alice", project["id"])["progress"]["percent"] == 100


def test_operating_metrics_use_completed_and_fulfilled_evidence(work_env):
    service, _ = work_env
    task = service.create_task(
        "alice",
        {"title": "Focused work", "estimated_minutes": 40},
        context=_user(),
    )
    service.update_task(
        "alice",
        task["id"],
        {"status": "completed"},
        expected_revision=task["revision"],
        context=_user(),
    )
    commitment = service.create_commitment(
        "alice",
        {
            "title": "Send notes",
            "source_type": "manual",
            "review_state": "approved",
        },
        context=_user(),
    )
    service.update_commitment(
        "alice",
        commitment["id"],
        {"status": "fulfilled"},
        expected_revision=commitment["revision"],
        context=_user(),
    )

    metrics = service.operating_metrics("alice", since="2020-01-01")

    assert metrics == {
        "completed_tasks": 1,
        "fulfilled_commitments": 1,
        "attention_returned_items": 2,
        "attention_returned_minutes": 40,
        "minutes_are_estimated": True,
    }
    assert service.operating_metrics("bob", since="2020-01-01")["attention_returned_items"] == 0
