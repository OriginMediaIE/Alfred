from __future__ import annotations

from datetime import datetime, timedelta
import json

import pytest

from core.database import AgentAction
from src.tools import work
from tests.work_support import make_work_service


def _seed_action(
    sessions,
    action_id: str,
    tool_name: str,
    owner: str = "alice",
    *,
    request_id: str | None = None,
):
    db = sessions()
    try:
        now = datetime.utcnow()
        resolved_request_id = request_id or action_id
        db.add(
            AgentAction(
                id=action_id,
                owner=owner,
                session_id="session-1",
                request_id=resolved_request_id,
                correlation_id=resolved_request_id,
                requested_tool=tool_name,
                tool_name=tool_name,
                tool_version=1,
                surface="native",
                origin="agent",
                arguments_json="{}",
                arguments_hash=(action_id[0] if action_id else "a") * 64,
                execution_context_json="{}",
                idempotency_key=f"key-{action_id}",
                risk_level=1 if tool_name == "manage_work" else 3,
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


@pytest.fixture
def tool_env(monkeypatch):
    service, sessions, bind = make_work_service()
    monkeypatch.setattr(work, "get_work_service", lambda: service)
    try:
        yield service, sessions
    finally:
        bind.dispose()


@pytest.mark.asyncio
async def test_query_tool_is_read_only_and_owner_scoped(tool_env):
    service, _ = tool_env
    service.create_task(
        "alice",
        {"title": "Alice", "priority": "high"},
        context=work.MutationContext.user("alice"),
    )
    service.create_task(
        "bob",
        {"title": "Bob"},
        context=work.MutationContext.user("bob"),
    )

    result = await work.do_query_work(
        json.dumps({"action": "list_tasks"}),
        owner="alice",
    )
    assert result["exit_code"] == 0
    assert [item["title"] for item in result["tasks"]] == ["Alice"]

    mutation_attempt = await work.do_query_work(
        json.dumps({"action": "create_task", "record": {"title": "Bypass"}}),
        owner="alice",
    )
    assert mutation_attempt["exit_code"] == 1
    assert "Unknown read action" in mutation_attempt["error"]
    assert [item["title"] for item in service.list_tasks("alice")] == ["Alice"]


@pytest.mark.asyncio
async def test_manage_tool_fails_closed_without_claim_then_records_approved_action(tool_env):
    service, sessions = tool_env
    content = json.dumps(
        {
            "action": "create_commitment",
            "record": {
                "title": "Send proposal",
                "due_at": "2026-07-25",
                "source": {
                    "type": "email",
                    "id": "mail-7",
                    "excerpt": "I will send it Friday",
                },
            },
        }
    )
    denied = await work.do_manage_work(content, owner="alice")
    assert denied["exit_code"] == 1
    assert denied["code"] == "approval_required"
    assert service.list_commitments("alice") == []

    _seed_action(
        sessions,
        "manage-action",
        "manage_work",
        request_id="request-7",
    )
    created = await work.do_manage_work(
        content,
        owner="alice",
        approval_action_id="manage-action",
        request_id="request-7",
    )
    assert created["exit_code"] == 0
    commitment = created["commitment"]
    assert commitment["source"]["id"] == "mail-7"
    assert commitment["created_by"] == "agent"
    assert commitment["review_state"] == "suggested"
    assert commitment["action_id"] == "manage-action"
    assert created["verification"]["status"] == "verified"


@pytest.mark.asyncio
async def test_delete_tool_requires_delete_specific_ledger_claim(tool_env):
    service, sessions = tool_env
    task = service.create_task(
        "alice",
        {"title": "Delete me"},
        context=work.MutationContext.user("alice"),
    )
    _seed_action(sessions, "manage-action", "manage_work", request_id="wrong-request")
    wrong_claim = await work.do_delete_work(
        json.dumps(
            {
                "action": "delete_task",
                "task_id": task["id"],
                "revision": task["revision"],
            }
        ),
        owner="alice",
        approval_action_id="manage-action",
        request_id="wrong-request",
    )
    assert wrong_claim["code"] == "approval_required"
    assert service.get_task("alice", task["id"])["id"] == task["id"]

    _seed_action(
        sessions,
        "delete-action",
        "delete_work",
        request_id="delete-request",
    )
    deleted = await work.do_delete_work(
        json.dumps(
            {
                "action": "delete_task",
                "task_id": task["id"],
                "revision": task["revision"],
            }
        ),
        owner="alice",
        approval_action_id="delete-action",
        request_id="delete-request",
    )
    assert deleted["ok"] is True
    assert deleted["id"] == task["id"]
    assert deleted["exit_code"] == 0
    assert deleted["verification"]["status"] == "verified"
    assert deleted["verification"]["read_back"] == "not_found"
    assert service.list_tasks("alice") == []
    assert service.list_receipts("alice", entity_id=task["id"])[0]["action_id"] == "delete-action"


def test_work_tool_schemas_split_read_write_delete_surfaces():
    schemas = {item["function"]["name"]: item for item in work.WORK_TOOL_SCHEMAS}
    assert set(schemas) == {"query_work", "manage_work", "delete_work"}
    assert work.QUERY_WORK_ACTIONS.isdisjoint(work.MANAGE_WORK_ACTIONS)
    assert work.QUERY_WORK_ACTIONS.isdisjoint(work.DELETE_WORK_ACTIONS)
    assert work.MANAGE_WORK_ACTIONS.isdisjoint(work.DELETE_WORK_ACTIONS)
    for schema in schemas.values():
        params = schema["function"]["parameters"]
        assert params["additionalProperties"] is False
        assert "action" in params["required"]
    assert "revision" in schemas["delete_work"]["function"]["parameters"]["required"]
