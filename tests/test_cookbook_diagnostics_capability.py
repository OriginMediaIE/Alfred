"""Capability-ledger tests for sensitive cookbook log reads."""

from __future__ import annotations

import pytest

from src import cookbook_diagnostics as diagnostics


@pytest.fixture(autouse=True)
def clean_grants():
    diagnostics._reset_for_tests()
    yield
    diagnostics._reset_for_tests()


def _launch(**changes):
    values = {
        "owner": "alice",
        "request_id": "request-1",
        "session_id": "serve-abc123",
        "remote_host": "gpu.example",
        "ssh_port": "2222",
    }
    values.update(changes)
    assert diagnostics.record_launch(**values) is True


def _list(status="error", **changes):
    task = {
        "session_id": "serve-abc123",
        "status": status,
        "remote": "gpu.example",
    }
    task.update(changes.pop("task", {}))
    diagnostics.record_listed_statuses(
        owner=changes.pop("owner", "alice"),
        request_id=changes.pop("request_id", "request-1"),
        tasks=[task],
    )


def _authorize(**changes):
    values = {
        "owner": "alice",
        "request_id": "request-1",
        "session_id": "serve-abc123",
    }
    values.update(changes)
    return diagnostics.authorize_tail(**values)


def test_exact_launch_list_failure_sequence_grants_one_log_read():
    _launch()
    _list(status="crashed")

    grant = _authorize()

    assert grant.session_id == "serve-abc123"
    assert grant.remote_host == "gpu.example"
    assert grant.ssh_port == "2222"
    assert grant.status == "crashed"
    with pytest.raises(diagnostics.DiagnosticAuthorizationError, match="already used"):
        _authorize()


@pytest.mark.parametrize(
    "changes",
    [
        {"owner": "bob"},
        {"request_id": "request-2"},
        {"session_id": "serve-other"},
    ],
)
def test_owner_request_and_session_must_match_launch(changes):
    _launch()
    _list()

    with pytest.raises(diagnostics.DiagnosticAuthorizationError, match="launched"):
        _authorize(**changes)


@pytest.mark.parametrize("status", ["ready", "running", "loading", "stopped", "unknown"])
def test_non_failing_status_never_arms_diagnostics(status):
    _launch()
    _list(status=status)

    with pytest.raises(diagnostics.DiagnosticAuthorizationError, match="observe.*failing"):
        _authorize()


def test_caller_cannot_redirect_grant_to_another_host_or_port():
    _launch()
    _list()

    with pytest.raises(diagnostics.DiagnosticAuthorizationError, match="host"):
        _authorize(requested_remote_host="other.example")
    with pytest.raises(diagnostics.DiagnosticAuthorizationError, match="port"):
        _authorize(requested_ssh_port="22")


def test_grant_expires_and_missing_request_context_never_grants(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(diagnostics, "_clock", lambda: now[0])

    assert diagnostics.record_launch(
        owner="alice",
        request_id="",
        session_id="serve-missing",
    ) is False
    _launch()
    _list()
    now[0] += diagnostics._GRANT_TTL_SECONDS + 1

    with pytest.raises(diagnostics.DiagnosticAuthorizationError, match="launched"):
        _authorize()
