"""Request-scoped tool capabilities receive an internal, unforgeable ID."""

import asyncio
import json
import re

import src.agent_loop as agent_loop


def _collect(gen):
    async def invoke():
        return [chunk async for chunk in gen]

    return asyncio.run(invoke())


def test_agent_reuses_one_internal_tool_request_id_per_stream(monkeypatch):
    captured = []
    captured_auth_managers = []
    auth_manager = object()

    monkeypatch.setattr(agent_loop, "get_setting", lambda key, default=None: default)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *args, **kwargs: 10)
    real_authority_for_owner = agent_loop.authority_for_owner

    def capture_authority(
        owner,
        *,
        surface,
        auth_manager=None,
        api_token_scopes=None,
        origin=None,
    ):
        captured_auth_managers.append(auth_manager)
        return real_authority_for_owner(
            owner,
            surface=surface,
            auth_manager=auth_manager,
            api_token_scopes=api_token_scopes,
            origin=origin,
        )

    monkeypatch.setattr(agent_loop, "authority_for_owner", capture_authority)

    async def fake_stream(_candidates, _messages, **_kwargs):
        calls = [
            {
                "name": "list_served_models",
                "arguments": json.dumps({"request_id": "model-forged-a"}),
            },
            {
                "name": "list_served_models",
                "arguments": json.dumps({"request_id": "model-forged-b"}),
            },
        ]
        yield f'data: {json.dumps({"type": "tool_calls", "calls": calls})}\n\n'
        yield "data: [DONE]\n\n"

    async def fake_execute(block, **kwargs):
        captured.append((block.content, kwargs.get("request_id")))
        return "list_served_models", {"output": "none", "exit_code": 0}

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute)

    def run_once():
        return _collect(
            agent_loop.stream_agent_loop(
                "https://api.openai.com/v1",
                "gpt-test",
                [{"role": "user", "content": "Inspect the model servers."}],
                max_rounds=1,
                relevant_tools={"list_served_models"},
                session_id="session-a",
                owner="alice",
                auth_manager=auth_manager,
                _is_teacher_run=True,
                _certified_tool_calling=True,
            )
        )

    run_once()
    run_once()

    assert len(captured) == 4
    first_id = captured[0][1]
    second_id = captured[2][1]
    assert captured[1][1] == first_id
    assert captured[3][1] == second_id
    assert first_id != second_id
    assert re.fullmatch(r"[0-9a-f]{32}", first_id)
    assert re.fullmatch(r"[0-9a-f]{32}", second_id)
    assert all(value not in {"model-forged-a", "model-forged-b"} for _, value in captured)
    assert captured_auth_managers
    assert all(value is auth_manager for value in captured_auth_managers)


def test_executor_forwards_request_id_to_cookbook_diagnostic_tools(monkeypatch):
    from src.agent_tools import ToolBlock
    from src.tool_authorization import ExecutionAuthority
    from src.tool_registry import ToolSurface
    import src.tool_execution as tool_execution
    import src.tool_implementations as implementations

    captured = []

    def replacement(name):
        async def call(content, *, owner=None, request_id=""):
            captured.append((name, content, owner, request_id))
            return {"output": name, "exit_code": 0}

        return call

    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda _owner: True)
    for name in ("list_served_models", "tail_serve_output"):
        monkeypatch.setattr(implementations, f"do_{name}", replacement(name))

    async def invoke():
        authority = ExecutionAuthority(
            owner="alice",
            permissions=frozenset(
                {"models.runtime.read", "models.diagnostics.read"}
            ),
            surface=ToolSurface.FENCE,
        )
        for name, content in (
            ("list_served_models", "{}"),
            ("tail_serve_output", '{"session_id":"serve-a"}'),
        ):
            await tool_execution.execute_tool_block(
                ToolBlock(name, content),
                owner="alice",
                request_id="internal-request",
                authority=authority,
            )

    asyncio.run(invoke())

    assert captured == [
        ("list_served_models", "{}", "alice", "internal-request"),
        (
            "tail_serve_output",
            '{"session_id":"serve-a"}',
            "alice",
            "internal-request",
        ),
    ]
