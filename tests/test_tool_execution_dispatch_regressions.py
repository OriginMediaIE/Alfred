"""Regression coverage for native/MCP dispatch and result formatting."""

from types import SimpleNamespace

import pytest


class _RecordingMcp:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return dict(self.result)


_LEVEL_ZERO_NATIVE_CASES = (
    ("web_search", "native query", "research.web"),
    ("web_fetch", "https://example.test", "research.web"),
    ("read_file", "native.txt", "files.read"),
)

_LEVEL_THREE_NATIVE_CASES = (
    ("bash", "echo native", "shell.execute"),
    ("python", "print('native')", "shell.execute"),
    ("write_file", "native.txt\nnative body", "files.write"),
)

_DYNAMIC_MCP_COLLISIONS = (
    ("bash", "mcp__bash__bash"),
    ("python", "mcp__python__python"),
    ("web_search", "mcp__web_search__web_search"),
    ("web_fetch", "mcp__web_fetch__web_fetch"),
    ("read_file", "mcp__filesystem__read_file"),
    ("write_file", "mcp__filesystem__write_file"),
)


def _authority(*permissions, surface):
    from src.tool_authorization import ExecutionAuthority

    return ExecutionAuthority(
        owner="admin",
        permissions=frozenset(permissions),
        surface=surface,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "content", "permission"), _LEVEL_ZERO_NATIVE_CASES)
async def test_level_zero_native_tools_bypass_removed_mcp_server_ids(
    monkeypatch, tool, content, permission
):
    """Unqualified native tools must never be hijacked by an MCP ID collision."""
    import src.agent_tools as agent_tools
    import src.tool_execution as tool_execution

    native_calls = []

    async def native_handler(actual_content, ctx):
        native_calls.append((actual_content, ctx))
        return {"output": f"native:{tool}", "exit_code": 0}

    mcp = _RecordingMcp(
        {
            "error": "removed MCP server not connected",
            "exit_code": 1,
        }
    )
    monkeypatch.setitem(agent_tools.TOOL_HANDLERS, tool, native_handler)
    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: mcp)
    monkeypatch.setattr(tool_execution, "is_public_blocked_tool", lambda _tool: False)

    description, result = await tool_execution.execute_tool_block(
        SimpleNamespace(tool_type=tool, content=content),
        authority=_authority(
            permission,
            surface=tool_execution.ToolSurface.NATIVE,
        ),
    )

    assert tool in tool_execution._NATIVE_DIRECT_TOOLS
    assert tool not in tool_execution._MCP_TOOL_MAP
    assert description.startswith(f"{tool}:")
    assert result == {"output": f"native:{tool}", "exit_code": 0}
    assert len(native_calls) == 1
    assert native_calls[0][0] == {
        "web_search": '{"query":"native query"}',
        "web_fetch": '{"url":"https://example.test"}',
        "read_file": '{"path":"native.txt"}',
    }[tool]
    assert mcp.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "content", "permission"), _LEVEL_THREE_NATIVE_CASES)
async def test_level_three_native_tools_require_approval_without_dispatch(
    monkeypatch, tool, content, permission
):
    """Native high-risk calls remain inert until exact approval exists."""
    import src.agent_tools as agent_tools
    import src.tool_execution as tool_execution

    native_calls = []

    async def native_handler(actual_content, ctx):
        native_calls.append((actual_content, ctx))
        return {"output": f"native:{tool}", "exit_code": 0}

    mcp = _RecordingMcp({"output": "unexpected MCP", "exit_code": 0})
    monkeypatch.setitem(agent_tools.TOOL_HANDLERS, tool, native_handler)
    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: mcp)
    monkeypatch.setattr(tool_execution, "is_public_blocked_tool", lambda _tool: False)

    description, result = await tool_execution.execute_tool_block(
        SimpleNamespace(tool_type=tool, content=content),
        authority=_authority(
            permission,
            surface=tool_execution.ToolSurface.NATIVE,
        ),
    )

    assert description == f"{tool}: APPROVAL REQUIRED"
    assert result["policy_decision"] == "require_approval"
    assert result["policy_code"] == "approval_required"
    assert result["approval_required"] is True
    preview = result["action_preview"]
    expected_arguments = {
        "bash": {"command": content},
        "python": {"code": content},
        "write_file": {"path": "native.txt", "content": "native body"},
    }[tool]
    assert preview["tool"] == tool
    assert preview["tool_version"] == 1
    assert preview["arguments"] == expected_arguments
    assert len(preview["arguments_hash"]) == 64
    assert native_calls == []
    assert mcp.calls == []


@pytest.mark.asyncio
async def test_invalid_arguments_are_rejected_before_approval_or_dispatch(monkeypatch):
    import src.agent_tools as agent_tools
    import src.tool_execution as tool_execution

    calls = []

    async def unexpected_handler(*args, **kwargs):
        calls.append((args, kwargs))
        return {"output": "unexpected", "exit_code": 0}

    monkeypatch.setitem(agent_tools.TOOL_HANDLERS, "write_file", unexpected_handler)
    monkeypatch.setattr(tool_execution, "is_public_blocked_tool", lambda _tool: False)

    description, result = await tool_execution.execute_tool_block(
        SimpleNamespace(
            tool_type="write_file",
            content='{"path":"note.txt","content":"x","surprise":true}',
        ),
        authority=_authority("files.write", surface=tool_execution.ToolSurface.NATIVE),
    )

    assert description == "write_file: BLOCKED"
    assert result["policy_code"] == "invalid_arguments"
    assert result["argument_path"] == "surprise"
    assert "approval_required" not in result
    assert calls == []


@pytest.mark.asyncio
async def test_action_hash_is_stable_across_json_key_order(monkeypatch):
    import src.tool_execution as tool_execution

    monkeypatch.setattr(tool_execution, "is_public_blocked_tool", lambda _tool: False)
    authority = _authority("files.write", surface=tool_execution.ToolSurface.NATIVE)
    previews = []
    for content in (
        '{"path":"note.txt","content":"hello"}',
        '{"content":"hello","path":"note.txt"}',
    ):
        _, result = await tool_execution.execute_tool_block(
            SimpleNamespace(tool_type="write_file", content=content),
            authority=authority,
        )
        previews.append(result["action_preview"])

    assert previews[0]["arguments"] == previews[1]["arguments"]
    assert previews[0]["arguments_hash"] == previews[1]["arguments_hash"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "qualified_name"), _DYNAMIC_MCP_COLLISIONS)
async def test_explicit_dynamic_mcp_collision_fails_closed_before_dispatch(
    monkeypatch, tool, qualified_name
):
    """An unregistered qualified MCP name cannot fall back to native."""
    import src.agent_tools as agent_tools
    import src.tool_execution as tool_execution

    native_calls = []

    async def native_handler(actual_content, ctx):
        native_calls.append((actual_content, ctx))
        return {"output": f"native:{tool}", "exit_code": 0}

    mcp = _RecordingMcp({"output": "unexpected MCP", "exit_code": 0})
    monkeypatch.setitem(agent_tools.TOOL_HANDLERS, tool, native_handler)
    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: mcp)
    monkeypatch.setattr(tool_execution, "is_public_blocked_tool", lambda _tool: False)

    description, result = await tool_execution.execute_tool_block(
        SimpleNamespace(tool_type=qualified_name, content="{}"),
        authority=_authority(surface=tool_execution.ToolSurface.DYNAMIC_MCP),
    )

    assert description == f"{qualified_name}: BLOCKED"
    assert result["policy_decision"] == "deny"
    assert result["policy_code"] == "dynamic_mcp_unregistered"
    assert native_calls == []
    assert mcp.calls == []


@pytest.mark.asyncio
async def test_bundled_generate_image_alias_requires_approval_before_mcp(monkeypatch):
    import src.tool_execution as tool_execution

    mcp = _RecordingMcp(
        {
            "stdout": "Generated image for: a cat\n/api/generated-image/cat.png",
            "stderr": "",
            "exit_code": 0,
        }
    )
    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: mcp)
    monkeypatch.setattr(tool_execution, "is_public_blocked_tool", lambda _tool: False)

    description, result = await tool_execution.execute_tool_block(
        SimpleNamespace(
            tool_type="mcp__image_gen__generate_image",
            content='{"prompt": "a cat"}',
        ),
        authority=_authority(
            "images.generate",
            surface=tool_execution.ToolSurface.DYNAMIC_MCP,
        ),
    )

    assert description == "generate_image: APPROVAL REQUIRED"
    assert result["policy_decision"] == "require_approval"
    assert result["policy_code"] == "approval_required"
    assert result["requested_tool"] == "mcp__image_gen__generate_image"
    assert result["tool_name"] == "generate_image"
    assert mcp.calls == []


@pytest.mark.asyncio
async def test_bare_generate_image_requires_approval_before_mcp_or_native_fallback(
    monkeypatch,
):
    import src.tool_execution as tool_execution

    mcp_error = {
        "error": "MCP server image_gen not connected",
        "exit_code": 1,
    }
    mcp = _RecordingMcp(mcp_error)

    async def unexpected_fallback(*_args, **_kwargs):
        raise AssertionError("MCP errors must not trigger a text-matched fallback")

    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: mcp)
    monkeypatch.setattr(tool_execution, "_direct_fallback", unexpected_fallback)
    monkeypatch.setattr(tool_execution, "is_public_blocked_tool", lambda _tool: False)

    description, result = await tool_execution.execute_tool_block(
        SimpleNamespace(tool_type="generate_image", content="a cat"),
        authority=_authority(
            "images.generate",
            surface=tool_execution.ToolSurface.FENCE,
        ),
    )

    assert description == "generate_image: APPROVAL REQUIRED"
    assert result["policy_decision"] == "require_approval"
    assert result["policy_code"] == "approval_required"
    assert mcp.calls == []


@pytest.mark.parametrize(
    ("stdout", "stderr"),
    (
        ("", ""),
        ("partial stdout", ""),
        ("", "partial stderr"),
        ("partial stdout", "partial stderr"),
    ),
)
def test_format_tool_result_preserves_timeout_error_once(stdout, stderr):
    from src.tool_execution import format_tool_result

    timeout_error = "bash: timed out after 60 seconds"
    formatted = format_tool_result(
        "bash: slow command",
        {
            "error": timeout_error,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": 124,
        },
    )

    assert formatted.count(timeout_error) == 1
    assert "**exit_code:** 124" in formatted
    if stdout:
        assert stdout in formatted
    if stderr:
        assert stderr in formatted


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "handler_name"),
    (("manage_work", "do_manage_work"), ("delete_work", "do_delete_work")),
)
async def test_work_mutation_dispatch_forwards_exact_claimed_approval_id(
    monkeypatch, tool_name, handler_name
):
    import src.tool_execution as execution
    import src.tools.work as work_tools
    from src.tool_authorization import resolve_tool_identity

    calls = []

    async def handler(content, owner=None, *, request_id="", approval_action_id=None):
        calls.append((content, owner, request_id, approval_action_id))
        return {"output": "ok", "exit_code": 0}

    monkeypatch.setattr(work_tools, handler_name, handler)
    import src.tool_implementations as facade
    monkeypatch.setattr(facade, handler_name, handler)
    identity = resolve_tool_identity(tool_name, surface=execution.ToolSurface.NATIVE)
    binding = execution._resolve_runtime_binding(identity)
    grant = SimpleNamespace(approval_id="action-exact-1")

    _, result = await execution._dispatch_resolved_binding(
        binding,
        '{"action":"test"}',
        session_id="session-1",
        owner="alice",
        request_id="request-1",
        progress_cb=None,
        approval_grant=grant,
    )

    assert result["exit_code"] == 0
    assert calls == [
        ('{"action":"test"}', "alice", "request-1", "action-exact-1")
    ]


@pytest.mark.asyncio
async def test_query_work_is_read_only_and_dispatches_without_approval(monkeypatch):
    import src.tool_execution as execution
    import src.tools.work as work_tools
    import src.tool_implementations as facade

    calls = []

    async def query_handler(content, owner=None):
        calls.append((content, owner))
        return {"tasks": [], "exit_code": 0}

    monkeypatch.setattr(work_tools, "do_query_work", query_handler)
    monkeypatch.setattr(facade, "do_query_work", query_handler)
    monkeypatch.setattr(execution, "is_public_blocked_tool", lambda _name: False)

    description, result = await execution.execute_tool_block(
        SimpleNamespace(
            tool_type="query_work",
            content='{"action":"list_tasks"}',
        ),
        owner="admin",
        request_id="request-read",
        authority=_authority(
            "tasks.read",
            surface=execution.ToolSurface.NATIVE,
        ),
    )

    assert description == "query_work"
    assert result == {"tasks": [], "exit_code": 0}
    assert calls == [('{"action":"list_tasks"}', "admin")]
