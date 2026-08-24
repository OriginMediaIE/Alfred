import asyncio
import sys
import types
from unittest.mock import patch

from src.mcp_manager import (
    _format_mcp_connection_error,
    _minimal_mcp_environment,
    McpManager,
)


def test_mcp_child_environment_excludes_parent_secrets(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("OPENAI_API_KEY", "parent-secret")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///private.db")

    child = _minimal_mcp_environment({"MCP_SERVER_TOKEN": "explicit-token"})

    assert child["PATH"] == "/usr/bin"
    assert child["MCP_SERVER_TOKEN"] == "explicit-token"
    assert "OPENAI_API_KEY" not in child
    assert "DATABASE_URL" not in child


def test_playwright_mcp_connection_error_includes_install_hint():
    msg = _format_mcp_connection_error(
        "Browser (Playwright)",
        "npx",
        ["-y", "@playwright/mcp@latest", "--headless"],
        RuntimeError("package not found"),
    )

    assert "package not found" in msg
    assert "Browser MCP could not start" in msg
    assert "npx -y @playwright/mcp@latest --version" in msg
    assert "restart OM Automate" in msg


def test_generic_mcp_connection_error_preserves_original_error():
    msg = _format_mcp_connection_error(
        "Custom MCP",
        "python",
        ["server.py"],
        RuntimeError("boom"),
    )

    assert msg == "boom"


def test_http_transport_routes_to_start_http_connect():
    mgr = McpManager()

    async def fake_start(server_id, name, url):
        return "ROUTED"

    with patch.object(McpManager, "_start_http_connect", side_effect=fake_start) as m:
        result = asyncio.run(mgr.connect_server("id1", "n", "http", url="https://x/mcp"))
    assert result == "ROUTED"
    m.assert_called_once()


async def test_stdio_transport_is_closed_by_its_owner_task(monkeypatch):
    tasks = {}

    class TransportContext:
        async def __aenter__(self):
            tasks["transport_enter"] = asyncio.current_task()
            return object(), object()

        async def __aexit__(self, *_args):
            tasks["transport_exit"] = asyncio.current_task()

    class SessionContext:
        async def __aenter__(self):
            tasks["session_enter"] = asyncio.current_task()
            return self

        async def __aexit__(self, *_args):
            tasks["session_exit"] = asyncio.current_task()

        async def initialize(self):
            return None

        async def list_tools(self):
            tool = types.SimpleNamespace(
                name="read_status",
                description="Read status",
                inputSchema={},
                annotations=None,
            )
            return types.SimpleNamespace(tools=[tool])

    mcp = types.ModuleType("mcp")
    mcp.ClientSession = lambda *_args: SessionContext()
    mcp.StdioServerParameters = lambda **kwargs: kwargs
    client = types.ModuleType("mcp.client")
    stdio = types.ModuleType("mcp.client.stdio")
    stdio.stdio_client = lambda _params: TransportContext()
    monkeypatch.setitem(sys.modules, "mcp", mcp)
    monkeypatch.setitem(sys.modules, "mcp.client", client)
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", stdio)

    manager = McpManager()
    assert await manager.connect_server(
        "owned", "Owned MCP", "stdio", command="python", args=["server.py"]
    )
    owner = manager._owner_tasks["owned"]

    await manager.disconnect_server("owned")

    assert owner.done()
    assert tasks["transport_enter"] is tasks["transport_exit"] is owner
    assert tasks["session_enter"] is tasks["session_exit"] is owner
    assert "owned" not in manager._sessions
    assert "owned" not in manager._owner_tasks
