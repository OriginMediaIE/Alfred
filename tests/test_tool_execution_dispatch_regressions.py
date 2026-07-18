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


_NATIVE_CASES = (
    ("bash", "echo native", "mcp__bash__bash"),
    ("python", "print('native')", "mcp__python__python"),
    ("web_search", "native query", "mcp__web_search__web_search"),
    ("web_fetch", "https://example.test", "mcp__web_fetch__web_fetch"),
    ("read_file", "native.txt", "mcp__filesystem__read_file"),
    ("write_file", "native.txt\nnative body", "mcp__filesystem__write_file"),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "content", "removed_mcp_name"), _NATIVE_CASES)
async def test_native_tools_bypass_removed_mcp_server_ids(
    monkeypatch, tool, content, removed_mcp_name
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
            "error": f"MCP server for {removed_mcp_name} not connected",
            "exit_code": 1,
        }
    )
    monkeypatch.setitem(agent_tools.TOOL_HANDLERS, tool, native_handler)
    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: mcp)
    monkeypatch.setattr(tool_execution, "is_public_blocked_tool", lambda _tool: False)

    description, result = await tool_execution.execute_tool_block(
        SimpleNamespace(tool_type=tool, content=content), owner="admin"
    )

    assert tool in tool_execution._NATIVE_DIRECT_TOOLS
    assert tool not in tool_execution._MCP_TOOL_MAP
    assert description.startswith(f"{tool}:")
    assert result == {"output": f"native:{tool}", "exit_code": 0}
    assert len(native_calls) == 1
    assert native_calls[0][0] == content
    assert mcp.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "content", "qualified_name"), _NATIVE_CASES)
async def test_explicit_qualified_mcp_collision_fails_closed(
    monkeypatch, tool, content, qualified_name
):
    """An explicit MCP call stays on MCP, including its error result."""
    import src.agent_tools as agent_tools
    import src.tool_execution as tool_execution

    async def unexpected_native_handler(_content, _ctx):
        raise AssertionError(f"explicit {qualified_name} fell back to native {tool}")

    mcp_error = {
        "error": f"MCP server for {qualified_name} not connected",
        "exit_code": 1,
    }
    mcp = _RecordingMcp(mcp_error)
    monkeypatch.setitem(agent_tools.TOOL_HANDLERS, tool, unexpected_native_handler)
    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: mcp)
    monkeypatch.setattr(tool_execution, "is_public_blocked_tool", lambda _tool: False)

    description, result = await tool_execution.execute_tool_block(
        SimpleNamespace(tool_type=qualified_name, content="{}"), owner="admin"
    )

    assert description == f"mcp: {qualified_name}"
    assert result == mcp_error
    assert mcp.calls == [(qualified_name, {})]


@pytest.mark.asyncio
async def test_bundled_generate_image_still_routes_through_mcp(monkeypatch):
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

    _, result = await tool_execution.execute_tool_block(
        SimpleNamespace(tool_type="generate_image", content="a cat"), owner="admin"
    )

    assert mcp.calls == [
        ("mcp__image_gen__generate_image", {"prompt": "a cat"}),
    ]
    assert result["image_url"] == "/api/generated-image/cat.png"


@pytest.mark.asyncio
async def test_bundled_mcp_error_does_not_trigger_string_matched_native_fallback(
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

    _, result = await tool_execution.execute_tool_block(
        SimpleNamespace(tool_type="generate_image", content="a cat"), owner="admin"
    )

    assert result == mcp_error
    assert mcp.calls == [
        ("mcp__image_gen__generate_image", {"prompt": "a cat"}),
    ]


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
