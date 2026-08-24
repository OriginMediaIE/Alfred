"""Registry deadlines and owned subprocess lifecycle regressions."""

from __future__ import annotations

import asyncio
import os
import shlex
from dataclasses import replace
from types import SimpleNamespace

import pytest
from starlette.requests import Request


def _authority(*permissions: str):
    from src.tool_authorization import ExecutionAuthority
    from src.tool_registry import ToolSurface

    return ExecutionAuthority(
        owner="alice",
        permissions=frozenset(permissions),
        surface=ToolSurface.FENCE,
    )


@pytest.mark.asyncio
async def test_executor_enforces_resolved_registry_timeout(monkeypatch):
    import src.tool_execution as execution
    from src.tool_authorization import ResolvedToolIdentity
    from src.tool_registry import ToolSurface, build_builtin_registry

    definition = replace(
        build_builtin_registry().resolve("get_workspace"),
        timeout_seconds=0.02,
    )
    identity = ResolvedToolIdentity(
        requested_name="get_workspace",
        canonical_name="get_workspace",
        definition=definition,
        surface=ToolSurface.FENCE,
    )
    cancelled = asyncio.Event()

    monkeypatch.setattr(execution, "resolve_tool_identity", lambda *_a, **_k: identity)

    async def slow_execution(*_args, **_kwargs):
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    monkeypatch.setattr(execution, "_execute_tool_block_impl", slow_execution)

    description, result = await execution.execute_tool_block(
        SimpleNamespace(tool_type="get_workspace", content=""),
        authority=_authority("files.read"),
    )

    assert description == "get_workspace: TIMED OUT"
    assert result["policy_code"] == "tool_timeout"
    assert result["exit_code"] == 124
    assert result["timeout_seconds"] == 0.02
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_executor_propagates_registry_timeout_to_native_handler(monkeypatch):
    import src.agent_tools as agent_tools
    import src.tool_execution as execution
    from src.tool_registry import build_builtin_registry

    contexts = []

    async def recording_handler(_content, ctx):
        contexts.append(dict(ctx))
        return {"output": "ok", "exit_code": 0}

    monkeypatch.setitem(
        agent_tools.TOOL_HANDLERS,
        "get_workspace",
        recording_handler,
    )
    monkeypatch.setattr(execution, "is_public_blocked_tool", lambda _tool: False)

    _, result = await execution.execute_tool_block(
        SimpleNamespace(tool_type="get_workspace", content=""),
        authority=_authority("files.read"),
    )

    expected = build_builtin_registry().resolve("get_workspace").timeout_seconds
    assert result == {"output": "ok", "exit_code": 0}
    assert contexts[0]["timeout_seconds"] == expected
    assert contexts[0]["deadline_managed"] is True


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group regression")
async def test_bash_timeout_kills_background_descendant(tmp_path, monkeypatch):
    from src.agent_tools.subprocess_tools import BashTool

    monkeypatch.setenv("OM_ALLOW_UNSANDBOXED_AGENT_EXECUTION", "1")

    marker = tmp_path / "descendant-survived"
    command = f"(sleep 0.35; touch {shlex.quote(str(marker))}) & wait"

    result = await BashTool().execute(
        command,
        {"timeout_seconds": 0.05},
    )

    assert result["exit_code"] == 124
    assert result["timed_out"] is True
    assert result["timeout_seconds"] == 0.05
    await asyncio.sleep(0.45)
    assert not marker.exists()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group regression")
async def test_bash_cancellation_kills_background_descendant(tmp_path, monkeypatch):
    from src.agent_tools.subprocess_tools import BashTool

    monkeypatch.setenv("OM_ALLOW_UNSANDBOXED_AGENT_EXECUTION", "1")

    marker = tmp_path / "cancelled-descendant-survived"
    command = f"(sleep 0.35; touch {shlex.quote(str(marker))}) & wait"
    task = asyncio.create_task(
        BashTool().execute(
            command,
            {
                "timeout_seconds": 30,
                "deadline_managed": True,
            },
        )
    )
    await asyncio.sleep(0.05)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(0.45)
    assert not marker.exists()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group regression")
async def test_foreground_bash_cannot_detach_an_unowned_descendant(tmp_path, monkeypatch):
    from src.agent_tools.subprocess_tools import BashTool

    monkeypatch.setenv("OM_ALLOW_UNSANDBOXED_AGENT_EXECUTION", "1")

    marker = tmp_path / "detached-descendant-survived"
    command = (
        f"(sleep 0.35; touch {shlex.quote(str(marker))}) "
        ">/dev/null 2>&1 &"
    )

    result = await BashTool().execute(command, {"timeout_seconds": 5})

    assert result["exit_code"] == 0
    await asyncio.sleep(0.45)
    assert not marker.exists()


@pytest.mark.asyncio
async def test_cached_ssh_scan_reaps_process_tree_when_request_is_cancelled(
    monkeypatch,
):
    import routes.cookbook_routes as cookbook_routes
    import src.subprocess_lifecycle as lifecycle

    class BlockingProcess:
        def __init__(self):
            self.pid = 987654
            self.returncode = None
            self.communicate_started = asyncio.Event()
            self.exited = asyncio.Event()
            self.terminated = False

        async def communicate(self, input=None):
            assert input
            self.communicate_started.set()
            await asyncio.Future()

        async def wait(self):
            await self.exited.wait()
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15
            self.exited.set()

        def kill(self):
            self.terminate()

    process = BlockingProcess()
    exec_calls = []

    async def fake_exec(*args, **kwargs):
        exec_calls.append((args, kwargs))
        return process

    async def fake_owned_group_cleanup(proc, _grace):
        proc.terminate()

    monkeypatch.setattr(cookbook_routes, "require_admin", lambda _request: None)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(
        lifecycle,
        "_terminate_owned_posix_group",
        fake_owned_group_cleanup,
    )
    monkeypatch.setattr(lifecycle, "_kill_windows_tree", lambda _pid: process.terminate())

    router = cookbook_routes.setup_cookbook_routes()
    endpoint = next(
        route.endpoint
        for route in router.routes
        if route.path == "/api/model/cached" and "GET" in route.methods
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/model/cached",
            "headers": [],
            "state": {},
        }
    )
    request.state.current_user = "admin"

    task = asyncio.create_task(endpoint(request, host="user@gpu-box"))
    await asyncio.wait_for(process.communicate_started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert process.terminated is True
    assert process.returncode == -15
    argv, kwargs = exec_calls[0]
    assert argv[0] == "ssh"
    if os.name == "nt":
        assert kwargs["creationflags"]
    else:
        assert kwargs["start_new_session"] is True
