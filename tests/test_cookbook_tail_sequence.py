"""End-to-end tool-domain sequence for cookbook diagnostic capabilities."""

from __future__ import annotations

import json

import pytest

from src import cookbook_diagnostics
from src.tools import cookbook


class _Response:
    def __init__(self, payload, *, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.headers = {"content-type": "application/json"}
        self.content = b"{}"
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _Client:
    def __init__(self, calls):
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url, **_kwargs):
        self.calls.append(("GET", url, None))
        if url.endswith("/api/cookbook/tasks/status"):
            return _Response(
                {
                    "tasks": [
                        {
                            "session_id": "serve-owned1",
                            "type": "serve",
                            "model": "example-model",
                            "status": "error",
                            "phase": "crashed",
                            "remote": "gpu.example",
                            "output_tail": "Traceback",
                        }
                    ]
                }
            )
        raise AssertionError(f"unexpected GET {url}")

    async def post(self, url, json=None, **_kwargs):
        self.calls.append(("POST", url, json))
        if url.endswith("/api/model/serve"):
            return _Response(
                {
                    "ok": True,
                    "session_id": "serve-owned1",
                    "endpoint_id": "endpoint-1",
                }
            )
        if url.endswith("/api/shell/exec"):
            return _Response(
                {"stdout": "owned traceback", "stderr": "", "exit_code": 0}
            )
        raise AssertionError(f"unexpected POST {url}")


@pytest.fixture(autouse=True)
def clear_diagnostics():
    cookbook_diagnostics._reset_for_tests()
    yield
    cookbook_diagnostics._reset_for_tests()


@pytest.mark.asyncio
async def test_observational_list_does_not_arm_tail_capability(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda *args, **kwargs: _Client(calls),
    )

    async def _host(value):
        return value

    async def _env(_host_name):
        return {"ssh_port": "2222"}

    async def _registered(**_kwargs):
        return True

    monkeypatch.setattr(cookbook, "_resolve_cookbook_host", _host)
    monkeypatch.setattr(cookbook, "_cookbook_env_for_host", _env)
    monkeypatch.setattr(cookbook, "_cookbook_register_task", _registered)
    monkeypatch.setattr(cookbook, "_scan_running_model_processes", lambda: [])

    launch = await cookbook.do_serve_model(
        json.dumps(
            {
                "repo_id": "org/example-model",
                "cmd": "vllm serve org/example-model",
                "host": "gpu.example",
            }
        ),
        owner="alice",
        request_id="request-1",
    )
    assert launch["exit_code"] == 0

    before_list = await cookbook.do_tail_serve_output(
        json.dumps({"session_id": "serve-owned1"}),
        owner="alice",
        request_id="request-1",
    )
    assert before_list["exit_code"] == 1
    assert "list_served_models" in before_list["error"]

    listed = await cookbook.do_list_served_models(
        "{}",
        owner="alice",
        request_id="request-1",
    )
    assert listed["exit_code"] == 0

    after_list = await cookbook.do_tail_serve_output(
        json.dumps({"session_id": "serve-owned1"}),
        owner="alice",
        request_id="request-1",
    )
    assert after_list["exit_code"] == 1
    assert "list_served_models" in after_list["error"]
    assert not [call for call in calls if call[1].endswith("/api/shell/exec")]

    # A trusted action path may separately attest the status.  The
    # observational list above deliberately cannot mutate this ledger.
    cookbook_diagnostics.record_listed_statuses(
        owner="alice",
        request_id="request-1",
        tasks=[
            {
                "session_id": "serve-owned1",
                "status": "error",
                "remote": "gpu.example",
            }
        ],
    )
    tailed = await cookbook.do_tail_serve_output(
        json.dumps({"session_id": "serve-owned1"}),
        owner="alice",
        request_id="request-1",
    )
    assert tailed["output"] == "owned traceback"
    shell_calls = [call for call in calls if call[1].endswith("/api/shell/exec")]
    assert len(shell_calls) == 1
    assert "gpu.example" in shell_calls[0][2]["command"]
    assert "-p 2222" in shell_calls[0][2]["command"]

    second_tail = await cookbook.do_tail_serve_output(
        json.dumps({"session_id": "serve-owned1"}),
        owner="alice",
        request_id="request-1",
    )
    assert second_tail["exit_code"] == 1
    assert "already used" in second_tail["error"]


@pytest.mark.asyncio
async def test_tail_denies_cross_owner_and_cross_request_before_shell(monkeypatch):
    def _forbidden_client(*_args, **_kwargs):
        raise AssertionError("unauthorized tail must not reach HTTP or shell")

    monkeypatch.setattr("httpx.AsyncClient", _forbidden_client)
    cookbook_diagnostics.record_launch(
        owner="alice",
        request_id="request-1",
        session_id="serve-owned1",
    )
    cookbook_diagnostics.record_listed_statuses(
        owner="alice",
        request_id="request-1",
        tasks=[{"session_id": "serve-owned1", "status": "error", "remote": "local"}],
    )

    for owner, request_id in (("bob", "request-1"), ("alice", "request-2")):
        result = await cookbook.do_tail_serve_output(
            json.dumps({"session_id": "serve-owned1"}),
            owner=owner,
            request_id=request_id,
        )
        assert result["exit_code"] == 1
        assert "launched by this agent request" in result["error"]
