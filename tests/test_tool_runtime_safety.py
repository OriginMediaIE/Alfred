"""Safety regressions for canonical dispatch, standing rules, and verification."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
import json
import os
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import AgentApprovalRule, Base
from src.action_ledger import ActionLedger
from src.action_verification import (
    prepare_action_verification,
    verify_action_result,
)
from src.tool_actions import ActionEnvelope, build_action_envelope
from src.tool_authorization import (
    ExecutionAuthority,
    ExecutionOrigin,
    ResolvedToolIdentity,
)
from src.tool_registry import ToolSurface, build_builtin_registry


class _RecordingMcp:
    def __init__(self, result=None, *, error: Exception | None = None, wait=False):
        self.result = result or {"image_url": "/api/generated-image/ok.png", "exit_code": 0}
        self.error = error
        self.wait = wait
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name, args):
        self.calls.append((name, dict(args)))
        if self.wait:
            await asyncio.Event().wait()
        if self.error is not None:
            raise self.error
        return dict(self.result)


@pytest.fixture
def ledger_env(monkeypatch):
    import src.action_ledger as ledger_module

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    now = [datetime.utcnow()]
    ledger = ActionLedger(
        session_factory=factory,
        clock=lambda: now[0],
        approval_ttl=timedelta(minutes=10),
    )
    monkeypatch.setattr(ledger_module, "_ledger", ledger)
    monkeypatch.setattr(ledger_module, "_utcnow", lambda: now[0])
    try:
        yield ledger, factory, now
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _action(
    tool: str,
    content: str,
    *,
    request_id: str,
    origin: ExecutionOrigin = ExecutionOrigin.INTERACTIVE_CHAT,
    surface: ToolSurface = ToolSurface.FENCE,
) -> ActionEnvelope:
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
        owner="alice",
        session_id="session-1",
        request_id=request_id,
        origin=origin,
    )


def _seed_image_rule(ledger: ActionLedger) -> str:
    action = _action(
        "generate_image",
        '{"prompt":"same exact image"}',
        request_id="rule-seed",
    )
    proposal = ledger.propose(
        action,
        risk_level=2,
        approval_reason="Approval required.",
        origin=action.origin.value,
    )
    grant = ledger.claim_approval(
        proposal["id"],
        "alice",
        expected_revision=1,
        expected_hash=proposal["arguments_hash"],
        always_allow=True,
    )
    ledger.consume_grant(grant)
    ledger.finish_execution(
        grant,
        {"image_url": "/api/generated-image/seed.png", "exit_code": 0},
        verification_status="schema_verified",
    )
    assert grant.rule_id
    return grant.rule_id


def _image_authority(origin=ExecutionOrigin.INTERACTIVE_CHAT):
    return ExecutionAuthority(
        owner="alice",
        permissions=frozenset({"images.generate"}),
        surface=ToolSurface.FENCE,
        origin=origin,
    )


def _allow_role_gates(monkeypatch, execution):
    monkeypatch.setattr(execution, "_owner_is_admin", lambda _owner: True)
    monkeypatch.setattr(execution, "is_public_blocked_tool", lambda _name: False)


def test_grant_and_standing_rule_cannot_cross_request_or_edited_row(ledger_env):
    ledger, _factory, _now = ledger_env
    _seed_image_rule(ledger)
    action = _action(
        "generate_image",
        '{"prompt":"same exact image"}',
        request_id="collision-request",
    )
    proposal = ledger.propose(
        action,
        risk_level=2,
        approval_reason="Approval required.",
        origin=action.origin.value,
    )
    edited = ledger.edit_arguments(
        proposal["id"],
        "alice",
        {"prompt": "different reviewed image"},
        expected_revision=1,
    )
    assert edited["revision"] == 2
    assert (
        ledger.claim_matching_rule(
            action,
            risk_level=2,
            approval_reason="Approval required.",
            origin=action.origin.value,
        )
        is None
    )
    assert ledger.get_action(proposal["id"], "alice")["status"] == "pending"

    other = _action(
        "generate_image",
        '{"prompt":"a separate approval"}',
        request_id="grant-request",
    )
    other_proposal = ledger.propose(
        other,
        risk_level=2,
        approval_reason="Approval required.",
    )
    grant = ledger.claim_approval(
        other_proposal["id"],
        "alice",
        expected_revision=1,
        expected_hash=other_proposal["arguments_hash"],
    )
    different_request = _action(
        "generate_image",
        '{"prompt":"a separate approval"}',
        request_id="not-the-approved-request",
    )
    assert grant.matches(different_request) is False


@pytest.mark.asyncio
async def test_exact_standing_rule_executes_once_and_replay_is_blocked(
    ledger_env,
    monkeypatch,
):
    import src.tool_execution as execution

    ledger, _factory, _now = ledger_env
    _seed_image_rule(ledger)
    mcp = _RecordingMcp()
    monkeypatch.setattr(execution, "get_mcp_manager", lambda: mcp)
    _allow_role_gates(monkeypatch, execution)
    block = SimpleNamespace(
        tool_type="generate_image",
        content='{"prompt":"same exact image"}',
    )

    description, result = await execution.execute_tool_block(
        block,
        owner="alice",
        session_id="session-1",
        request_id="auto-request",
        authority=_image_authority(),
    )

    assert description.startswith("generate_image:")
    assert result["auto_approved"] is True
    assert result["approval_status"] == "succeeded"
    assert result["verification"]["status"] == "schema_verified"
    assert ledger.get_action(result["approval_id"], "alice")["approval_consumed_at"]
    assert mcp.calls == [
        ("mcp__image_gen__generate_image", {"prompt": "same exact image"})
    ]

    replay_description, replay = await execution.execute_tool_block(
        block,
        owner="alice",
        session_id="session-1",
        request_id="auto-request",
        authority=_image_authority(),
    )
    assert replay_description == "generate_image: BLOCKED"
    assert replay["policy_code"] == "approval_action_not_pending"
    assert len(mcp.calls) == 1


@pytest.mark.asyncio
async def test_standing_rule_isolated_by_origin_and_expiry(ledger_env, monkeypatch):
    import src.tool_execution as execution

    ledger, factory, now = ledger_env
    rule_id = _seed_image_rule(ledger)
    mcp = _RecordingMcp()
    monkeypatch.setattr(execution, "get_mcp_manager", lambda: mcp)
    _allow_role_gates(monkeypatch, execution)

    _, scheduled = await execution.execute_tool_block(
        SimpleNamespace(
            tool_type="generate_image",
            content='{"prompt":"same exact image"}',
        ),
        owner="alice",
        request_id="scheduled-request",
        authority=_image_authority(ExecutionOrigin.SCHEDULED_AUTOMATION),
    )
    assert scheduled["approval_required"] is True
    assert scheduled["action_preview"]["origin"] == "scheduled_automation"
    assert mcp.calls == []

    db = factory()
    try:
        rule = db.query(AgentApprovalRule).filter(AgentApprovalRule.id == rule_id).one()
        rule.expires_at = now[0] - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()

    _, expired = await execution.execute_tool_block(
        SimpleNamespace(
            tool_type="generate_image",
            content='{"prompt":"same exact image"}',
        ),
        owner="alice",
        request_id="expired-rule-request",
        authority=_image_authority(),
    )
    assert expired["approval_required"] is True
    assert expired["approval_status"] == "pending"
    assert mcp.calls == []


@pytest.mark.asyncio
async def test_auto_approved_timeout_finishes_ledger_failure(ledger_env, monkeypatch):
    import src.tool_execution as execution

    ledger, _factory, _now = ledger_env
    _seed_image_rule(ledger)
    mcp = _RecordingMcp(wait=True)
    monkeypatch.setattr(execution, "get_mcp_manager", lambda: mcp)
    _allow_role_gates(monkeypatch, execution)
    real_deadline = execution._await_registry_deadline

    async def short_deadline(awaitable, _timeout):
        return await real_deadline(awaitable, 0.01)

    monkeypatch.setattr(execution, "_await_registry_deadline", short_deadline)
    _, result = await execution.execute_tool_block(
        SimpleNamespace(
            tool_type="generate_image",
            content='{"prompt":"same exact image"}',
        ),
        owner="alice",
        request_id="timeout-request",
        authority=_image_authority(),
    )

    assert result["timed_out"] is True
    history = ledger.list_actions("alice", status="history")
    timed_out = next(item for item in history if item["request_id"] == "timeout-request")
    assert timed_out["status"] == "failed"
    assert timed_out["approval_consumed_at"]
    assert timed_out["verification_status"] == "failed"


@pytest.mark.asyncio
async def test_auto_approved_exception_finishes_ledger_failure(ledger_env, monkeypatch):
    import src.tool_execution as execution

    ledger, _factory, _now = ledger_env
    _seed_image_rule(ledger)
    monkeypatch.setattr(
        execution,
        "get_mcp_manager",
        lambda: _RecordingMcp(error=RuntimeError("provider exploded")),
    )
    _allow_role_gates(monkeypatch, execution)

    with pytest.raises(RuntimeError, match="provider exploded"):
        await execution.execute_tool_block(
            SimpleNamespace(
                tool_type="generate_image",
                content='{"prompt":"same exact image"}',
            ),
            owner="alice",
            request_id="exception-request",
            authority=_image_authority(),
        )

    action = next(
        item
        for item in ledger.list_actions("alice", status="history")
        if item["request_id"] == "exception-request"
    )
    assert action["status"] == "failed"
    assert action["approval_consumed_at"]
    assert action["error"] == "provider exploded"


@pytest.mark.asyncio
async def test_binding_namespace_mismatch_denies_before_mcp_or_handler_import(monkeypatch):
    import src.tool_execution as execution

    definition = build_builtin_registry().resolve("generate_image")
    binding = execution.ResolvedRuntimeBinding(
        definition=definition,
        kind=execution.RuntimeBindingKind.BUILTIN_MCP,
        namespace="email",
        target="generate_image",
    )

    def unexpected(*_args, **_kwargs):
        raise AssertionError("a mismatched binding must not import or resolve a provider")

    monkeypatch.setattr(execution.importlib, "import_module", unexpected)
    monkeypatch.setattr(execution, "get_mcp_manager", unexpected)
    description, result = await execution._dispatch_resolved_binding(
        binding,
        '{"prompt":"no dispatch"}',
        session_id=None,
        owner="alice",
        request_id="binding-test",
        progress_cb=None,
    )

    assert description == "generate_image: BLOCKED"
    assert result["policy_code"] == "binding_dispatch_mismatch"


@pytest.mark.asyncio
async def test_invalid_resolved_target_denies_before_handler_import(monkeypatch):
    import src.tool_execution as execution

    definition = build_builtin_registry().resolve("web_search", surface=ToolSurface.FENCE)
    definition = replace(definition, binding="legacy_dispatch:read_file")
    identity = ResolvedToolIdentity(
        requested_name="web_search",
        canonical_name="web_search",
        definition=definition,
        surface=ToolSurface.FENCE,
    )
    monkeypatch.setattr(execution, "resolve_tool_identity", lambda *_a, **_k: identity)

    def unexpected_import(*_args, **_kwargs):
        raise AssertionError("invalid binding must deny before implementation import")

    monkeypatch.setattr(execution.importlib, "import_module", unexpected_import)
    description, result = await execution.execute_tool_block(
        SimpleNamespace(tool_type="web_search", content="query"),
        owner="alice",
        authority=ExecutionAuthority(
            owner="alice",
            permissions=frozenset({"research.web"}),
            surface=ToolSurface.FENCE,
            origin=ExecutionOrigin.INTERACTIVE_CHAT,
        ),
    )
    assert description == "web_search: BLOCKED"
    assert result["policy_code"] == "missing_binding"


async def _approved_file_action(
    *,
    ledger: ActionLedger,
    monkeypatch,
    workspace: str,
    tool: str,
    content: str,
    request_id: str,
):
    import src.tool_execution as execution

    action = _action(tool, content, request_id=request_id)
    proposal = ledger.propose(
        action,
        risk_level=3,
        approval_reason="Approval required.",
        origin=action.origin.value,
        execution_context={"workspace": workspace},
    )
    grant = ledger.claim_approval(
        proposal["id"],
        "alice",
        expected_revision=1,
        expected_hash=proposal["arguments_hash"],
    )
    _allow_role_gates(monkeypatch, execution)
    _, result = await execution.execute_tool_block(
        SimpleNamespace(tool_type=tool, content=content),
        owner="alice",
        session_id="session-1",
        request_id=request_id,
        workspace=workspace,
        authority=ExecutionAuthority(
            owner="alice",
            permissions=frozenset({"files.write"}),
            surface=ToolSurface.FENCE,
            origin=ExecutionOrigin.INTERACTIVE_CHAT,
        ),
        approval_grant=grant,
    )
    completed = ledger.finish_execution(
        grant,
        result,
        verification_status=result["verification"]["status"],
    )
    return result, completed


@pytest.mark.asyncio
async def test_write_and_edit_are_byte_verified_and_stored(
    ledger_env,
    monkeypatch,
    tmp_path,
):
    ledger, _factory, _now = ledger_env
    write_result, written = await _approved_file_action(
        ledger=ledger,
        monkeypatch=monkeypatch,
        workspace=str(tmp_path),
        tool="write_file",
        content='{"path":"note.txt","content":"hello world"}',
        request_id="write-request",
    )
    assert write_result["verification"]["status"] == "read_back_verified"
    assert written["verification_status"] == "read_back_verified"
    assert written["result"]["verification"]["evidence"]["observed_size"] == 11

    edit_result, edited = await _approved_file_action(
        ledger=ledger,
        monkeypatch=monkeypatch,
        workspace=str(tmp_path),
        tool="edit_file",
        content=json.dumps(
            {
                "path": "note.txt",
                "old_string": "world",
                "new_string": "Odysseus",
            }
        ),
        request_id="edit-request",
    )
    assert edit_result["verification"]["status"] == "read_back_verified"
    assert edited["verification_status"] == "read_back_verified"
    assert (tmp_path / "note.txt").read_text() == "hello Odysseus"


@pytest.mark.asyncio
async def test_false_handler_success_becomes_failed_after_readback(
    ledger_env,
    monkeypatch,
    tmp_path,
):
    import src.agent_tools as agent_tools

    ledger, _factory, _now = ledger_env

    async def false_success(_content, _ctx):
        return {"output": "claimed write", "exit_code": 0}

    monkeypatch.setitem(agent_tools.TOOL_HANDLERS, "write_file", false_success)
    result, completed = await _approved_file_action(
        ledger=ledger,
        monkeypatch=monkeypatch,
        workspace=str(tmp_path),
        tool="write_file",
        content='{"path":"missing.txt","content":"must exist"}',
        request_id="false-success",
    )
    assert result["verification"]["status"] == "read_back_failed"
    assert completed["status"] == "failed"
    assert completed["verification_status"] == "read_back_failed"
    assert not (tmp_path / "missing.txt").exists()


def test_move_file_verifier_checks_destination_bytes_and_source_absence(tmp_path):
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    source.write_bytes(b"move me exactly\x00")
    definition = replace(
        build_builtin_registry().resolve("write_file"),
        name="move_file",
    )
    action = SimpleNamespace(
        tool_name="move_file",
        arguments_dict=lambda: {
            "source": "source.bin",
            "destination": "destination.bin",
        },
    )
    plan = prepare_action_verification(
        definition,
        action,
        path_resolver=lambda value: str(tmp_path / value),
    )
    os.replace(source, destination)
    outcome = verify_action_result(plan, {"exit_code": 0})

    assert outcome.status == "read_back_verified"
    assert outcome.evidence["source_absent"] is True
    assert outcome.evidence["observed_sha256"] == outcome.evidence["expected_sha256"]
