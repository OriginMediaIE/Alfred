import os

import pytest

from src.agent_tools.subprocess_tools import BashTool, validate_agent_shell
from src.tool_execution import _handler_context


@pytest.mark.parametrize("command", [
    "sudo cat /etc/shadow",
    "rm -rf /",
    "cat ~/.ssh/id_ed25519",
    "security find-generic-password -s provider -w",
    "mkfs.ext4 /dev/sda",
])
def test_agent_shell_rejects_escalation_destruction_and_secret_access(command):
    with pytest.raises(ValueError):
        validate_agent_shell(command)


def test_agent_shell_allows_bounded_development_commands():
    validate_agent_shell("git status && pytest -q tests/test_example.py")


def test_agent_subprocess_environment_excludes_parent_secrets(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("DATABASE_URL", "must-not-leak")
    monkeypatch.setenv("PATH", os.environ.get("PATH", "/usr/bin"))
    env = _handler_context(progress_cb=None, session_id="s1", owner="alice", request_id="r1")["subproc_env"]
    assert "OPENAI_API_KEY" not in env
    assert "DATABASE_URL" not in env
    assert env["HOME"]


@pytest.mark.asyncio
async def test_bash_tool_fails_closed_before_spawning_for_blocked_command(monkeypatch):
    async def must_not_spawn(*args, **kwargs):
        raise AssertionError("process should not start")

    monkeypatch.setattr("asyncio.create_subprocess_shell", must_not_spawn)
    result = await BashTool().execute("sudo whoami", {"subproc_env": {}, "timeout_seconds": 1})
    assert result["blocked"] is True
    assert result["exit_code"] == 126
