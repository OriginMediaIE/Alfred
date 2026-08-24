"""Regression tests for Cookbook tools that promise observational reads."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest
from starlette.requests import Request

import routes.cookbook_routes as cookbook_routes
from src.tools import cookbook


def _endpoint(path: str, method: str):
    router = cookbook_routes.setup_cookbook_routes()
    for route in router.routes:
        if route.path == path and method in route.methods:
            return route.endpoint
    raise AssertionError(f"{method} {path} route not found")


def _admin_request(path: str) -> Request:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [],
            "state": {},
        }
    )
    request.state.current_user = "admin"
    return request


class _Process:
    def __init__(self, stdout: bytes, stderr: bytes, returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.communicate_inputs: list[bytes | None] = []

    async def communicate(self, input=None):
        self.communicate_inputs.append(input)
        return self.stdout, self.stderr


@pytest.mark.asyncio
async def test_cached_model_read_uses_python_c_without_writing_scan_file(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(cookbook_routes, "require_admin", lambda _request: None)
    log_dir = tmp_path / "cookbook-logs"
    monkeypatch.setattr(cookbook_routes, "TMUX_LOG_DIR", log_dir)

    process = _Process(b"[]", b"")
    exec_calls = []

    async def fake_exec(*args, **kwargs):
        exec_calls.append((args, kwargs))
        return process

    async def fail_shell(*_args, **_kwargs):
        raise AssertionError("cached-model reads must not invoke a shell")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", fail_shell)

    endpoint = _endpoint("/api/model/cached", "GET")
    result = await endpoint(
        _admin_request("/api/model/cached"),
        model_dir="/data/models",
    )

    assert result == {"models": [], "host": "local"}
    assert len(exec_calls) == 1
    argv, kwargs = exec_calls[0]
    assert argv[1] == "-c"
    assert "/data/models" in argv[2]
    assert "stdin" not in kwargs
    assert process.communicate_inputs == [None]
    assert not log_dir.exists()
    assert not (log_dir / "scan_cache.py").exists()


@pytest.mark.asyncio
async def test_cached_model_read_streams_remote_script_without_repairing_known_hosts(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(cookbook_routes, "require_admin", lambda _request: None)
    log_dir = tmp_path / "cookbook-logs"
    monkeypatch.setattr(cookbook_routes, "TMUX_LOG_DIR", log_dir)

    host_key_error = (
        b"REMOTE HOST IDENTIFICATION HAS CHANGED!\n"
        b"Host key verification failed\n"
    )
    process = _Process(b"", host_key_error, returncode=255)
    exec_calls = []

    async def fake_exec(*args, **kwargs):
        exec_calls.append((args, kwargs))
        return process

    async def fail_shell(*_args, **_kwargs):
        raise AssertionError("cached-model reads must not invoke a shell")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", fail_shell)

    endpoint = _endpoint("/api/model/cached", "GET")
    result = await endpoint(
        _admin_request("/api/model/cached"),
        host="user@gpu-box",
        ssh_port="2222",
    )

    assert result["models"] == []
    assert "HOST IDENTIFICATION HAS CHANGED" in result["error"]
    # A repair would spawn ssh-keygen and ssh-keyscan subprocesses.  The one
    # subprocess here is only the requested SSH inventory scan.
    assert len(exec_calls) == 1
    argv, kwargs = exec_calls[0]
    assert argv[:3] == ("ssh", "-o", "BatchMode=yes")
    for option in (
        "StrictHostKeyChecking=yes",
        "UpdateHostKeys=no",
        "ControlMaster=no",
        "ControlPath=none",
        "ControlPersist=no",
        "PermitLocalCommand=no",
    ):
        assert option in argv
    assert argv[-3:] == ("user@gpu-box", "python3", "-")
    assert kwargs["stdin"] == asyncio.subprocess.PIPE
    assert process.communicate_inputs[0]
    assert b"/scan_cache.py" not in process.communicate_inputs[0]
    assert not log_dir.exists()


@pytest.mark.asyncio
async def test_observe_only_status_uses_an_isolated_lane_and_skips_orphan_sweep(
    monkeypatch,
    tmp_path,
):
    state_path = tmp_path / "cookbook-state.json"
    state_path.write_text(
        json.dumps({"tasks": [], "env": {"servers": []}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cookbook_routes, "COOKBOOK_STATE_FILE", str(state_path))
    monkeypatch.setattr(cookbook_routes, "require_admin", lambda _request: None)

    async def inline_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(cookbook_routes.asyncio, "to_thread", inline_to_thread)

    sweep_threads = []

    class FakeThread:
        def __init__(self, *, target, daemon, name):
            sweep_threads.append((target, daemon, name))

        def start(self):
            return None

    monkeypatch.setattr(threading, "Thread", FakeThread)

    endpoint = _endpoint("/api/cookbook/tasks/status", "GET")
    request = _admin_request("/api/cookbook/tasks/status")

    assert await endpoint(request, observe_only=True) == {"tasks": []}
    assert sweep_threads == []

    # The normal UI lane is separate from the observational cache and retains
    # orphan adoption.  If the caches were shared, this call would return the
    # observe-only cached result without exercising the sweep.
    assert await endpoint(request, observe_only=False) == {"tasks": []}
    assert len(sweep_threads) == 1
    assert sweep_threads[0][1:] == (True, "orphan-sweep")


class _Response:
    def __init__(self, payload):
        self._payload = payload
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_cookbook_read_tools_explicitly_disable_mutating_read_behaviour(
    monkeypatch,
):
    calls = []
    header_owners = []

    def owner_headers(owner=None):
        header_owners.append(owner)
        return {"X-Odysseus-Owner": owner or ""}

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, **kwargs):
            calls.append(
                (
                    url,
                    kwargs.get("params") or {},
                    kwargs.get("headers") or {},
                )
            )
            if url.endswith("/api/cookbook/tasks/status"):
                return _Response({"tasks": []})
            if url.endswith("/api/cookbook/state"):
                return _Response({"env": {"servers": []}})
            if url.endswith("/api/model/cached"):
                return _Response({"models": []})
            if url.endswith("/api/cookbook/hf-latest"):
                return _Response({"models": []})
            raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr("httpx.AsyncClient", Client)
    monkeypatch.setattr("src.tool_implementations._internal_headers", owner_headers)
    monkeypatch.setattr(cookbook, "_scan_running_model_processes", lambda: [])

    await cookbook.do_list_served_models("{}", owner="alice", request_id="request-1")
    await cookbook.do_list_downloads("{}", owner="alice")
    await cookbook.do_search_hf_models('{"query":"safe model"}', owner="alice")
    await cookbook.do_list_cached_models("{}", owner="alice")

    status_params = [params for url, params, _headers in calls if url.endswith("/tasks/status")]
    cached_params = [params for url, params, _headers in calls if url.endswith("/model/cached")]
    assert status_params == [
        {"observe_only": "true"},
        {"observe_only": "true"},
    ]
    assert cached_params
    assert all("repair_host_key" not in params for params in cached_params)
    assert header_owners and set(header_owners) == {"alice"}
    assert all(
        headers.get("X-Odysseus-Owner") == "alice"
        for _url, _params, headers in calls
    )


@pytest.mark.asyncio
async def test_cached_model_tool_rejects_model_controlled_hosts_and_paths(
    monkeypatch,
):
    calls = []

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, **kwargs):
            calls.append((url, kwargs.get("params") or {}))
            if url.endswith("/api/cookbook/state"):
                return _Response(
                    {
                        "env": {
                            "servers": [
                                {
                                    "name": "saved-gpu",
                                    "host": "ops@gpu.example",
                                    "modelDirs": ["/srv/models"],
                                }
                            ]
                        }
                    }
                )
            if url.endswith("/api/model/cached"):
                return _Response({"models": []})
            raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr("httpx.AsyncClient", Client)

    override = await cookbook.do_list_cached_models(
        '{"host":"saved-gpu","model_dir":"/etc"}',
        owner="alice",
    )
    assert override["exit_code"] == 1
    assert "model_dir" in override["error"]
    assert calls == []

    unknown = await cookbook.do_list_cached_models(
        '{"host":"attacker@unconfigured.example"}',
        owner="alice",
    )
    assert unknown["exit_code"] == 1
    assert "configured Cookbook server" in unknown["error"]
    assert all(not url.endswith("/api/model/cached") for url, _params in calls)

    allowed = await cookbook.do_list_cached_models(
        '{"host":"saved-gpu"}',
        owner="alice",
    )
    assert "error" not in allowed
    cached_calls = [
        params for url, params in calls if url.endswith("/api/model/cached")
    ]
    assert cached_calls == [
        {
            "host": "ops@gpu.example",
            "model_dir": "/srv/models",
        }
    ]


@pytest.mark.asyncio
async def test_list_served_models_does_not_arm_diagnostic_ledger(monkeypatch):
    from src import cookbook_diagnostics

    cookbook_diagnostics._reset_for_tests()
    cookbook_diagnostics.record_launch(
        owner="alice",
        request_id="request-1",
        session_id="serve-owned1",
        remote_host="gpu.example",
        ssh_port="2222",
    )

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, **_kwargs):
            assert url.endswith("/api/cookbook/tasks/status")
            return _Response(
                {
                    "tasks": [
                        {
                            "session_id": "serve-owned1",
                            "status": "error",
                            "remote": "gpu.example",
                        }
                    ]
                }
            )

    monkeypatch.setattr("httpx.AsyncClient", Client)
    monkeypatch.setattr(cookbook, "_scan_running_model_processes", lambda: [])

    listed = await cookbook.do_list_served_models(
        "{}",
        owner="alice",
        request_id="request-1",
    )
    assert listed["exit_code"] == 0
    with pytest.raises(
        cookbook_diagnostics.DiagnosticAuthorizationError,
        match="observe this newly launched task failing",
    ):
        cookbook_diagnostics.authorize_tail(
            owner="alice",
            request_id="request-1",
            session_id="serve-owned1",
        )
    cookbook_diagnostics._reset_for_tests()
