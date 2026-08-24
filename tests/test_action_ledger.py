"""Durable exact-action approval and audit-ledger regressions."""

from __future__ import annotations

from datetime import datetime, timedelta
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import AgentActionAuditEvent, Base
from src.action_ledger import (
    ActionConflict,
    ActionExpired,
    ActionLedger,
    ActionNotFound,
    ActionValidationError,
)
from src.tool_actions import build_action_envelope
from src.tool_authorization import ExecutionOrigin, ResolvedToolIdentity
from src.tool_registry import ToolSurface, build_builtin_registry


@pytest.fixture
def ledger_env():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    now = [datetime(2026, 7, 18, 12, 0, 0)]
    ledger = ActionLedger(
        session_factory=factory,
        clock=lambda: now[0],
        approval_ttl=timedelta(minutes=10),
    )
    try:
        yield ledger, factory, now
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _action(
    tool: str = "bash",
    content: str = "echo safe proposal",
    *,
    owner: str = "alice",
    request_id: str = "request-1",
    surface: ToolSurface = ToolSurface.FENCE,
    origin: ExecutionOrigin = ExecutionOrigin.INTERNAL,
):
    definition = build_builtin_registry().resolve(tool, surface=surface)
    identity = ResolvedToolIdentity(
        requested_name=tool,
        canonical_name=definition.name,
        definition=definition,
        surface=surface,
    )
    return build_action_envelope(
        identity,
        content,
        owner=owner,
        session_id="session-1",
        request_id=request_id,
        origin=origin,
    )


def _propose(ledger, action=None, *, risk=3):
    return ledger.propose(
        action or _action(),
        risk_level=risk,
        approval_reason="Explicit approval is required.",
    )


def test_proposal_is_durable_and_idempotent_for_one_request(ledger_env):
    ledger, _factory, _now = ledger_env

    first = _propose(ledger)
    second = _propose(ledger)

    assert first["id"] == second["id"]
    assert first["status"] == "pending"
    assert first["arguments"] == {"command": "echo safe proposal"}
    assert first["revision"] == 1
    assert ledger.verify_audit_chain(first["id"], "alice") is True


def test_owner_cannot_enumerate_or_open_another_users_action(ledger_env):
    ledger, _factory, _now = ledger_env
    proposal = _propose(ledger)

    assert ledger.list_actions("mallory", status="pending") == []
    with pytest.raises(ActionNotFound):
        ledger.get_action(proposal["id"], "mallory")


def test_edit_revalidates_schema_and_invalidates_stale_review(ledger_env):
    ledger, _factory, _now = ledger_env
    proposal = _propose(ledger)

    with pytest.raises(ActionValidationError):
        ledger.edit_arguments(
            proposal["id"],
            "alice",
            {"command": "echo edited", "unexpected": True},
            expected_revision=1,
        )

    edited = ledger.edit_arguments(
        proposal["id"],
        "alice",
        {"command": "echo edited"},
        expected_revision=1,
    )
    assert edited["revision"] == 2
    assert edited["arguments_hash"] != proposal["arguments_hash"]

    with pytest.raises(ActionConflict):
        ledger.claim_approval(
            proposal["id"],
            "alice",
            expected_revision=1,
            expected_hash=proposal["arguments_hash"],
        )


def test_claim_is_one_time_and_bound_to_exact_hash(ledger_env):
    ledger, _factory, _now = ledger_env
    proposal = _propose(ledger)

    with pytest.raises(ActionConflict):
        ledger.claim_approval(
            proposal["id"],
            "alice",
            expected_revision=1,
            expected_hash="0" * 64,
        )

    grant = ledger.claim_approval(
        proposal["id"],
        "alice",
        expected_revision=proposal["revision"],
        expected_hash=proposal["arguments_hash"],
    )
    assert grant.matches(_action(), now=_now[0]) is True
    assert grant.matches(
        _action(origin=ExecutionOrigin.APPROVAL_CENTRE), now=_now[0]
    ) is False
    ledger.consume_grant(grant)
    with pytest.raises(ActionConflict):
        ledger.consume_grant(grant)

    with pytest.raises(ActionConflict):
        ledger.claim_approval(
            proposal["id"],
            "alice",
            expected_revision=1,
            expected_hash=proposal["arguments_hash"],
        )


def test_expired_action_cannot_be_approved_and_moves_to_history(ledger_env):
    ledger, _factory, now = ledger_env
    proposal = _propose(ledger)
    now[0] += timedelta(minutes=11)

    assert ledger.list_actions("alice", status="pending") == []
    assert ledger.list_actions("alice", status="history")[0]["status"] == "expired"
    with pytest.raises(ActionExpired):
        ledger.claim_approval(
            proposal["id"],
            "alice",
            expected_revision=1,
            expected_hash=proposal["arguments_hash"],
        )
    assert ledger.get_action(proposal["id"], "alice")["stored_status"] == "expired"


def test_level_three_can_never_create_always_allow_rule(ledger_env):
    ledger, _factory, _now = ledger_env
    proposal = _propose(ledger)

    with pytest.raises(ActionConflict, match="Level 3"):
        ledger.claim_approval(
            proposal["id"],
            "alice",
            expected_revision=1,
            expected_hash=proposal["arguments_hash"],
            always_allow=True,
        )
    assert ledger.get_action(proposal["id"], "alice")["status"] == "pending"


def test_success_result_is_recorded_and_audit_chain_detects_tampering(ledger_env):
    ledger, factory, _now = ledger_env
    action = _action(
        "generate_image",
        '{"prompt":"an island"}',
        surface=ToolSurface.FENCE,
    )
    proposal = _propose(ledger, action, risk=2)
    grant = ledger.claim_approval(
        proposal["id"],
        "alice",
        expected_revision=1,
        expected_hash=proposal["arguments_hash"],
        always_allow=True,
    )
    ledger.consume_grant(grant)
    completed = ledger.finish_execution(
        grant,
        {
            "image_url": "/api/generated-image/a.png",
            "access_token": "must-not-enter-audit",
            "exit_code": 0,
        },
        verification_status="schema_verified",
    )

    assert completed["status"] == "succeeded"
    assert completed["verification_status"] == "schema_verified"
    assert grant.rule_id
    events = ledger.list_audit_events("alice", action_id=proposal["id"])
    assert {event["event_type"] for event in events} >= {
        "proposed",
        "approved",
        "execution_started",
        "execution_succeeded",
    }
    serialized = json.dumps(events)
    assert "must-not-enter-audit" not in serialized
    assert "REDACTED" in serialized
    assert ledger.verify_audit_chain(proposal["id"], "alice") is True

    db = factory()
    try:
        event = (
            db.query(AgentActionAuditEvent)
            .filter(AgentActionAuditEvent.action_id == proposal["id"])
            .order_by(AgentActionAuditEvent.sequence.asc())
            .first()
        )
        event.payload_json = '{"tampered":true}'
        db.commit()
    finally:
        db.close()
    assert ledger.verify_audit_chain(proposal["id"], "alice") is False


def test_operating_metrics_count_decisions_and_verified_results(ledger_env):
    ledger, _factory, now = ledger_env
    action = _action(
        "generate_image",
        '{"prompt":"a measured result"}',
        surface=ToolSurface.FENCE,
    )
    accepted = _propose(ledger, action, risk=2)
    grant = ledger.claim_approval(
        accepted["id"],
        "alice",
        expected_revision=1,
        expected_hash=accepted["arguments_hash"],
    )
    ledger.consume_grant(grant)
    ledger.finish_execution(
        grant,
        {"image_url": "/api/generated-image/result.png", "exit_code": 0},
        verification_status="schema_verified",
    )
    rejected = _propose(
        ledger,
        _action(request_id="request-rejected"),
    )
    ledger.reject(
        rejected["id"],
        "alice",
        expected_revision=1,
        reason="No",
    )

    metrics = ledger.operating_metrics(
        "alice", since=now[0] - timedelta(days=1)
    )

    assert metrics["proposed"] == 2
    assert metrics["accepted"] == 1
    assert metrics["rejected"] == 1
    assert metrics["verified"] == 1
    assert metrics["proposal_acceptance_rate"] == 0.5
    assert ledger.operating_metrics(
        "bob", since=now[0] - timedelta(days=1)
    )["proposed"] == 0


def test_pending_cancel_is_terminal_without_reconciliation_claim(ledger_env):
    ledger, _factory, _now = ledger_env
    proposal = _propose(ledger)

    cancelled = ledger.cancel(
        proposal["id"],
        "alice",
        expected_revision=proposal["revision"],
        reason="No longer needed.",
    )

    assert cancelled["status"] == "cancelled"
    assert cancelled["decision_reason"] == "No longer needed."
    assert cancelled["verification_status"] is None
    assert cancelled["reversal_status"] is None
    with pytest.raises(ActionConflict):
        ledger.claim_approval(
            proposal["id"],
            "alice",
            expected_revision=proposal["revision"],
            expected_hash=proposal["arguments_hash"],
        )


def test_executing_cancel_requires_reconciliation_and_blocks_completion(ledger_env):
    ledger, _factory, _now = ledger_env
    proposal = _propose(ledger)
    grant = ledger.claim_approval(
        proposal["id"],
        "alice",
        expected_revision=proposal["revision"],
        expected_hash=proposal["arguments_hash"],
    )
    ledger.consume_grant(grant)

    cancelled = ledger.cancel(
        proposal["id"],
        "alice",
        expected_revision=proposal["revision"],
        reason="Stop now.",
    )

    assert cancelled["status"] == "cancelled"
    assert cancelled["verification_status"] == "reconciliation_required"
    assert cancelled["reversal_status"] == "not_attempted"
    with pytest.raises(ActionConflict):
        ledger.finish_execution(
            grant,
            {"output": "late result", "exit_code": 0},
            verification_status="process_exit_verified",
        )
    events = ledger.list_audit_events("alice", action_id=proposal["id"])
    assert events[0]["event_type"] == "cancelled"
    assert events[0]["payload"]["previous_status"] == "executing"


def test_exact_rule_auto_claims_later_level_two_action_and_is_revocable(ledger_env):
    ledger, _factory, _now = ledger_env
    first_action = _action(
        "generate_image",
        '{"prompt":"same exact image"}',
        surface=ToolSurface.FENCE,
    )
    first = _propose(ledger, first_action, risk=2)
    first_grant = ledger.claim_approval(
        first["id"],
        "alice",
        expected_revision=1,
        expected_hash=first["arguments_hash"],
        always_allow=True,
    )
    ledger.consume_grant(first_grant)
    ledger.finish_execution(
        first_grant,
        {"image_url": "/api/generated-image/one.png", "exit_code": 0},
        verification_status="schema_verified",
    )

    second_action = _action(
        "generate_image",
        '{"prompt":"same exact image"}',
        request_id="request-2",
        surface=ToolSurface.FENCE,
    )
    auto_grant = ledger.claim_matching_rule(
        second_action,
        risk_level=2,
        approval_reason="Approval required.",
    )
    assert auto_grant is not None
    assert auto_grant.rule_id == first_grant.rule_id
    assert ledger.get_action(auto_grant.approval_id, "alice")["status"] == "executing"

    assert ledger.list_rules("alice")[0]["enabled"] is True
    ledger.revoke_rule(first_grant.rule_id, "alice")
    third_action = _action(
        "generate_image",
        '{"prompt":"same exact image"}',
        request_id="request-3",
        surface=ToolSurface.FENCE,
    )
    assert (
        ledger.claim_matching_rule(
            third_action,
            risk_level=2,
            approval_reason="Approval required.",
        )
        is None
    )


@pytest.mark.asyncio
async def test_executor_consumes_exact_grant_once_before_handler(
    ledger_env,
    monkeypatch,
):
    import src.action_ledger as ledger_module
    import src.agent_tools as agent_tools
    import src.tool_execution as tool_execution
    from types import SimpleNamespace
    from src.tool_authorization import ExecutionAuthority

    ledger, _factory, _now = ledger_env
    action = _action()
    proposal = _propose(ledger, action)
    grant = ledger.claim_approval(
        proposal["id"],
        "alice",
        expected_revision=1,
        expected_hash=proposal["arguments_hash"],
    )
    monkeypatch.setattr(ledger_module, "_ledger", ledger)
    monkeypatch.setattr(ledger_module, "_utcnow", lambda: _now[0])
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda _owner: True)
    monkeypatch.setattr(tool_execution, "is_public_blocked_tool", lambda _name: False)
    calls = []

    async def handler(content, _ctx):
        calls.append(content)
        return {"output": "ok", "exit_code": 0}

    monkeypatch.setitem(agent_tools.TOOL_HANDLERS, "bash", handler)
    authority = ExecutionAuthority(
        owner="alice",
        permissions=frozenset({"shell.execute"}),
        surface=ToolSurface.FENCE,
    )
    description, result = await tool_execution.execute_tool_block(
        SimpleNamespace(tool_type="bash", content='{"command":"echo safe proposal"}'),
        owner="alice",
        session_id="session-1",
        request_id="request-1",
        authority=authority,
        approval_grant=grant,
    )
    assert description.startswith("bash:")
    assert result["exit_code"] == 0
    assert calls == ["echo safe proposal"]
    assert ledger.get_action(proposal["id"], "alice")["approval_consumed_at"]
    ledger.finish_execution(grant, result, verification_status="indeterminate")

    replay_description, replay = await tool_execution.execute_tool_block(
        SimpleNamespace(tool_type="bash", content='{"command":"echo safe proposal"}'),
        owner="alice",
        session_id="session-1",
        request_id="request-1",
        authority=authority,
        approval_grant=grant,
    )
    assert replay_description == "bash: BLOCKED"
    assert replay["policy_code"] == "approval_evidence_unavailable"
    assert calls == ["echo safe proposal"]
