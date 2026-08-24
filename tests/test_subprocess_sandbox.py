from pathlib import Path

import pytest

from src import subprocess_sandbox as sandbox


def test_macos_profile_allows_workspace_but_not_network_or_data_root():
    profile = sandbox._macos_profile("/safe/workspace", "/usr/bin/python3")

    assert '(subpath "/safe/workspace")' in profile
    assert "file-write" in profile
    assert "network" not in profile
    assert "(allow default)" not in profile


def test_no_sandbox_fails_closed(monkeypatch):
    monkeypatch.setattr(sandbox.platform, "system", lambda: "Linux")
    monkeypatch.setattr(sandbox.shutil, "which", lambda _name: None)
    monkeypatch.delenv("OM_ALLOW_UNSANDBOXED_AGENT_EXECUTION", raising=False)

    with pytest.raises(sandbox.SandboxUnavailable):
        sandbox.sandboxed_argv("/bin/sh", ["-c", "echo no"], cwd="/tmp/job")


def test_unsandboxed_fallback_requires_exact_operator_opt_in(monkeypatch):
    monkeypatch.setattr(sandbox.platform, "system", lambda: "Linux")
    monkeypatch.setattr(sandbox.shutil, "which", lambda _name: None)
    monkeypatch.setenv("OM_ALLOW_UNSANDBOXED_AGENT_EXECUTION", "true")

    assert sandbox.sandboxed_argv(
        "/bin/sh", ["-c", "echo explicit"], cwd="/tmp/job"
    ) == ["/bin/sh", "-c", "echo explicit"]
