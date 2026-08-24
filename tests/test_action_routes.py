"""Approval Centre API contract and execution-boundary tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base
from routes import action_routes
from src.action_ledger import ActionLedger
from src.tool_actions import build_action_envelope
from src.tool_authorization import ExecutionAuthority, ResolvedToolIdentity
from src.tool_registry import ToolSurface, build_builtin_registry


def _endpoint(router, path: str, method: str):
    for route in router.routes:
        if route.path == path and method in route.methods:
            return route.endpoint
    raise AssertionError(f"missing {method} {path}")


@pytest.fixture
def route_env(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    now = datetime.utcnow()
    ledger = ActionLedger(
        session_factory=factory,
        clock=lambda: now,
        approval_ttl=timedelta(minutes=15),
    )
    monkeypatch.setattr(action_routes, "get_action_ledger", lambda: ledger)
    router = action_routes.setup_action_routes()
    try:
        yield router, ledger
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _proposal(ledger, *, tool="generate_image", content='{"prompt":"an island"}', risk=2):
    definition = build_builtin_registry().resolve(tool, surface=ToolSurface.FENCE)
    identity = ResolvedToolIdentity(
        requested_name=tool,
        canonical_name=tool,
        definition=definition,
        surface=ToolSurface.FENCE,
    )
    action = build_action_envelope(
        identity,
        content,
        owner="alice",
        session_id="session-1",
        request_id="request-1",
    )
    return ledger.propose(
        action,
        risk_level=risk,
        approval_reason="Approval required.",
    )


@pytest.mark.asyncio
async def test_list_and_detail_are_owner_scoped(route_env):
    router, ledger = route_env
    proposal = _proposal(ledger)
    list_actions = _endpoint(router, "/api/approvals", "GET")
    get_action = _endpoint(router, "/api/approvals/{action_id}", "GET")

    listed = await list_actions(status="pending", limit=100, owner="alice")
    assert [item["id"] for item in listed["actions"]] == [proposal["id"]]
    assert (await list_actions(status="pending", limit=100, owner="mallory"))["actions"] == []

    detail = await get_action(proposal["id"], owner="alice")
    assert detail["action"]["arguments"] == {"prompt": "an island"}
    assert detail["chain_valid"] is True
    assert detail["events"][0]["event_type"] == "proposed"


@pytest.mark.asyncio
async def test_edit_requires_revision_and_changes_hash(route_env):
    router, ledger = route_env
    proposal = _proposal(ledger)
    edit = _endpoint(router, "/api/approvals/{action_id}", "PATCH")

    response = await edit(
        proposal["id"],
        action_routes.EditActionBody(
            revision=1,
            arguments={"prompt": "a different island", "size": "1024x1024"},
        ),
        owner="alice",
    )
    assert response["action"]["revision"] == 2
    assert response["action"]["arguments_hash"] != proposal["arguments_hash"]


@pytest.mark.asyncio
async def test_approve_claims_once_and_executes_with_trusted_grant(
    route_env,
    monkeypatch,
):
    router, ledger = route_env
    proposal = _proposal(ledger)
    approve = _endpoint(router, "/api/approvals/{action_id}/approve", "POST")
    calls = []

    monkeypatch.setattr(
        action_routes,
        "authority_for_owner",
        lambda owner, *, surface, auth_manager=None, origin=None: ExecutionAuthority(
            owner=owner,
            permissions=frozenset({"images.generate"}),
            surface=surface,
            origin=origin or action_routes.ExecutionOrigin.INTERNAL,
        ),
    )

    async def fake_execute(block, **kwargs):
        calls.append((block, kwargs))
        grant = kwargs["approval_grant"]
        assert grant.approval_id == proposal["id"]
        assert kwargs["authority"].owner == "alice"
        ledger.consume_grant(grant)
        return "generate_image: an island", {
            "image_url": "/api/generated-image/island.png",
            "exit_code": 0,
        }

    monkeypatch.setattr(action_routes, "execute_tool_block", fake_execute)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(auth_manager=object())))
    response = await approve(
        proposal["id"],
        action_routes.ApproveActionBody(
            revision=1,
            arguments_hash=proposal["arguments_hash"],
            always_allow=True,
        ),
        request=request,
        owner="alice",
    )

    assert len(calls) == 1
    assert response["action"]["status"] == "succeeded"
    assert response["action"]["verification_status"] == "schema_verified"
    assert response["action"]["approval_rule_id"]

    with pytest.raises(Exception) as replay:
        await approve(
            proposal["id"],
            action_routes.ApproveActionBody(
                revision=1,
                arguments_hash=proposal["arguments_hash"],
            ),
            request=request,
            owner="alice",
        )
    assert getattr(replay.value, "status_code", None) == 409
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_reject_never_executes(route_env):
    router, ledger = route_env
    proposal = _proposal(ledger)
    reject = _endpoint(router, "/api/approvals/{action_id}/reject", "POST")

    response = await reject(
        proposal["id"],
        action_routes.RejectActionBody(revision=1, reason="Not what I intended."),
        owner="alice",
    )
    assert response["action"]["status"] == "rejected"
    assert response["action"]["decision_reason"] == "Not what I intended."


@pytest.mark.asyncio
async def test_cancel_pending_action(route_env):
    router, ledger = route_env
    proposal = _proposal(ledger)
    cancel = _endpoint(router, "/api/approvals/{action_id}/cancel", "POST")

    response = await cancel(
        proposal["id"],
        action_routes.CancelActionBody(revision=1, reason="Changed my mind."),
        owner="alice",
    )

    assert response["action"]["status"] == "cancelled"
    assert response["cancellation_signalled"] is False


@pytest.mark.asyncio
async def test_cancel_signals_active_execution_and_requires_reconciliation(
    route_env,
):
    router, ledger = route_env
    proposal = _proposal(ledger)
    ledger.claim_approval(
        proposal["id"],
        "alice",
        expected_revision=1,
        expected_hash=proposal["arguments_hash"],
    )
    cancel = _endpoint(router, "/api/approvals/{action_id}/cancel", "POST")

    class ActiveTask:
        cancelled = False

        def done(self):
            return False

        def cancel(self):
            self.cancelled = True

    task = ActiveTask()
    action_routes._active_approval_tasks[proposal["id"]] = task
    try:
        response = await cancel(
            proposal["id"],
            action_routes.CancelActionBody(revision=1, reason="Stop."),
            owner="alice",
        )
    finally:
        action_routes._active_approval_tasks.pop(proposal["id"], None)

    assert task.cancelled is True
    assert response["cancellation_signalled"] is True
    assert response["action"]["verification_status"] == "reconciliation_required"


@pytest.mark.asyncio
async def test_real_executor_uses_claimed_image_action_exactly_once(
    route_env,
    monkeypatch,
):
    import src.action_ledger as ledger_module
    import src.tool_execution as tool_execution

    router, ledger = route_env
    proposal = _proposal(ledger)
    approve = _endpoint(router, "/api/approvals/{action_id}/approve", "POST")
    monkeypatch.setattr(ledger_module, "_ledger", ledger)
    monkeypatch.setattr(
        action_routes,
        "authority_for_owner",
        lambda owner, *, surface, auth_manager=None, origin=None: ExecutionAuthority(
            owner=owner,
            permissions=frozenset({"images.generate"}),
            surface=surface,
            origin=origin or action_routes.ExecutionOrigin.INTERNAL,
        ),
    )
    # Some legacy import-isolation tests reload src.tool_execution during the
    # full suite. Patch the exact executor function retained by action_routes,
    # not whichever module object currently occupies sys.modules.
    executor_globals = action_routes.execute_tool_block.__globals__
    monkeypatch.setitem(executor_globals, "_owner_is_admin", lambda _owner: True)
    monkeypatch.setitem(executor_globals, "is_public_blocked_tool", lambda _name: False)

    class RecordingMcp:
        def __init__(self):
            self.calls = []

        async def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            return {
                "stdout": (
                    "Generated image for: an island\n"
                    "/api/generated-image/island.png"
                ),
                "stderr": "",
                "exit_code": 0,
            }

    mcp = RecordingMcp()
    monkeypatch.setitem(executor_globals, "get_mcp_manager", lambda: mcp)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(auth_manager=object())))

    response = await approve(
        proposal["id"],
        action_routes.ApproveActionBody(
            revision=1,
            arguments_hash=proposal["arguments_hash"],
        ),
        request=request,
        owner="alice",
    )

    assert response["action"]["status"] == "succeeded"
    assert response["result"]["image_url"] == "/api/generated-image/island.png"
    assert mcp.calls == [
        ("mcp__image_gen__generate_image", {"prompt": "an island"})
    ]


@pytest.mark.asyncio
async def test_real_executor_creates_work_record_with_consumed_claim_and_readback(
    route_env,
    monkeypatch,
):
    import src.action_ledger as ledger_module
    import src.tool_execution as tool_execution
    import src.tools.work as work_tools
    from src.work_service import WorkService

    router, ledger = route_env
    definition = build_builtin_registry().resolve(
        "manage_work", surface=ToolSurface.FENCE
    )
    identity = ResolvedToolIdentity(
        requested_name="manage_work",
        canonical_name="manage_work",
        definition=definition,
        surface=ToolSurface.FENCE,
    )
    action = build_action_envelope(
        identity,
        '{"action":"create_task","record":{"title":"Prepare launch"}}',
        owner="alice",
        session_id="session-1",
        request_id="work-request-1",
    )
    proposal = ledger.propose(
        action,
        risk_level=1,
        approval_reason="Approval required.",
    )
    factory = ledger._session_factory
    bind = factory.kw["bind"]
    service = WorkService(
        session_factory=factory,
        bind=bind,
        backfill_legacy=False,
    )
    monkeypatch.setattr(ledger_module, "_ledger", ledger)
    monkeypatch.setattr(work_tools, "get_work_service", lambda: service)
    import src.tool_implementations as facade
    monkeypatch.setattr(facade, "do_manage_work", work_tools.do_manage_work)
    monkeypatch.setattr(
        action_routes,
        "authority_for_owner",
        lambda owner, *, surface, auth_manager=None, origin=None: ExecutionAuthority(
            owner=owner,
            permissions=frozenset({"tasks.write"}),
            surface=surface,
            origin=origin or action_routes.ExecutionOrigin.INTERNAL,
        ),
    )
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda _owner: True)
    monkeypatch.setattr(tool_execution, "is_public_blocked_tool", lambda _name: False)
    approve = _endpoint(router, "/api/approvals/{action_id}/approve", "POST")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(auth_manager=object())))

    response = await approve(
        proposal["id"],
        action_routes.ApproveActionBody(
            revision=proposal["revision"],
            arguments_hash=proposal["arguments_hash"],
        ),
        request=request,
        owner="alice",
    )

    assert response["action"]["status"] == "succeeded"
    assert response["action"]["verification_status"] == "read_back_verified"
    assert response["result"]["verification"]["status"] == "read_back_verified"
    tasks = service.list_tasks("alice")
    assert [task["title"] for task in tasks] == ["Prepare launch"]
    assert tasks[0]["action_id"] == proposal["id"]


@pytest.mark.asyncio
async def test_real_executor_sends_gmail_once_with_consumed_claim_and_readback(
    route_env,
    monkeypatch,
):
    import src.action_ledger as ledger_module
    import src.tool_execution as tool_execution
    import src.tools.google_workspace as google_tools
    import src.tool_implementations as facade

    router, ledger = route_env
    definition = build_builtin_registry().resolve("send_gmail", surface=ToolSurface.FENCE)
    identity = ResolvedToolIdentity(
        requested_name="send_gmail",
        canonical_name="send_gmail",
        definition=definition,
        surface=ToolSurface.FENCE,
    )
    action = build_action_envelope(
        identity,
        (
            '{"action":"send_message","to":"bob@example.com",'
            '"subject":"Plan","body":"Ready."}'
        ),
        owner="alice",
        session_id="session-1",
        request_id="gmail-request-1",
    )
    proposal = ledger.propose(
        action,
        risk_level=2,
        approval_reason="Sending mail requires approval.",
    )

    class Connections:
        def list_connections(self, owner):
            assert owner == "alice"
            return [{"id": "google-1", "status": "connected"}]

    class Gmail:
        def __init__(self):
            self.calls = []

        async def send_message(self, owner, connection_id, **command):
            self.calls.append((owner, connection_id, command))
            return {
                "message": {"id": "m-1"},
                "verification": {
                    "status": "verified",
                    "provider": "gmail",
                    "read_back_id": "m-1",
                },
            }

    gmail = Gmail()
    monkeypatch.setattr(ledger_module, "_ledger", ledger)
    monkeypatch.setattr(
        google_tools, "get_google_connection_service", lambda: Connections()
    )
    monkeypatch.setattr(google_tools, "get_google_gmail_service", lambda: gmail)
    monkeypatch.setattr(facade, "do_send_gmail", google_tools.do_send_gmail)
    monkeypatch.setattr(
        action_routes,
        "authority_for_owner",
        lambda owner, *, surface, auth_manager=None, origin=None: ExecutionAuthority(
            owner=owner,
            permissions=frozenset({"email.send"}),
            surface=surface,
            origin=origin or action_routes.ExecutionOrigin.INTERNAL,
        ),
    )
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda _owner: True)
    monkeypatch.setattr(tool_execution, "is_public_blocked_tool", lambda _name: False)
    approve = _endpoint(router, "/api/approvals/{action_id}/approve", "POST")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(auth_manager=object())))

    response = await approve(
        proposal["id"],
        action_routes.ApproveActionBody(
            revision=proposal["revision"],
            arguments_hash=proposal["arguments_hash"],
        ),
        request=request,
        owner="alice",
    )

    assert response["action"]["status"] == "succeeded"
    assert response["action"]["verification_status"] == "read_back_verified"
    assert response["result"]["verification"]["status"] == "read_back_verified"
    assert gmail.calls == [
        (
            "alice",
            "google-1",
            {"to": "bob@example.com", "subject": "Plan", "body": "Ready."},
        )
    ]
