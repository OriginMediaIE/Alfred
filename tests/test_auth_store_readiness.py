"""Readiness and auth-store shape coverage for OM-BUG-003.

A present-but-damaged auth store must never look like a clean first boot, must
never permit an unauthenticated first-admin claim, and must not report ready.
"""

import json
import os
import stat
import threading

import pytest

from core.auth import AuthManager
from src.readiness import _auth_store_check


class _State:
    """Minimal stand-in for ``app.state`` (see app.py:269)."""

    def __init__(self, auth_manager=None):
        if auth_manager is not None:
            self.auth_manager = auth_manager


# --------------------------------------------------------------------------
# Readiness contract
# --------------------------------------------------------------------------

def test_readiness_fails_closed_when_auth_store_is_damaged(tmp_path):
    path = tmp_path / "auth.json"
    path.write_text("{not valid json", encoding="utf-8")
    manager = AuthManager(str(path))
    assert manager.recovery_required is True

    check = _auth_store_check(_State(manager))
    assert check["status"] == "failed"
    assert check["required"] is True
    assert check["code"] == "auth_recovery_required"


def test_readiness_ok_for_healthy_store(tmp_path):
    path = tmp_path / "auth.json"
    manager = AuthManager(str(path))
    assert manager.setup("owner", "a sufficiently long password") is True

    check = _auth_store_check(_State(manager))
    assert check["status"] == "ok"
    assert check["required"] is True


def test_readiness_check_is_secret_free(tmp_path):
    """The public contract must not leak paths, identities, or exception text."""
    path = tmp_path / "auth.json"
    path.write_text("{not valid json", encoding="utf-8")
    manager = AuthManager(str(path))

    rendered = json.dumps(_auth_store_check(_State(manager)))
    assert str(tmp_path) not in rendered
    assert "auth.json" not in rendered
    assert set(json.loads(rendered)) <= {"status", "required", "code"}


def test_readiness_skips_when_manager_absent():
    """Unit contexts without app state must not fail the gate."""
    for state in (None, _State()):
        check = _auth_store_check(state)
        assert check["status"] == "skipped"
        assert check["required"] is False


# --------------------------------------------------------------------------
# Damaged store shapes the register requires (previously untested)
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name,payload",
    [
        ("truncated", '{"users": {"owner": {"password_'),
        ("wrong_shaped_list", '{"users": []}'),
        ("wrong_shaped_string", '{"users": "owner"}'),
        ("wrong_shaped_scalar", "[]"),
        ("empty_file", ""),
        ("empty_object", "{}"),
        ("null_users", '{"users": null}'),
    ],
)
def test_damaged_store_shapes_never_expose_first_run_setup(tmp_path, name, payload):
    path = tmp_path / f"auth-{name}.json"
    path.write_text(payload, encoding="utf-8")
    manager = AuthManager(str(path))

    assert manager.recovery_required is True, name
    assert manager.is_configured is True, name
    assert manager.setup("attacker", "a sufficiently long password") is False, name
    # The damaged material must survive for operator-led recovery.
    assert path.read_text(encoding="utf-8") == payload, name
    assert _auth_store_check(_State(manager))["status"] == "failed", name


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses mode bits")
def test_unreadable_store_fails_closed(tmp_path):
    path = tmp_path / "auth.json"
    path.write_text(json.dumps({"users": {"owner": {"password_hash": "x"}}}), encoding="utf-8")
    path.chmod(0o000)
    try:
        manager = AuthManager(str(path))
        assert manager.recovery_required is True
        assert manager.setup("attacker", "a sufficiently long password") is False
    finally:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


# --------------------------------------------------------------------------
# Concurrent first-admin initialization
# --------------------------------------------------------------------------

def test_concurrent_setup_creates_exactly_one_admin(tmp_path):
    manager = AuthManager(str(tmp_path / "auth.json"))
    barrier = threading.Barrier(8)
    results = []

    def claim(index):
        barrier.wait()
        results.append(manager.setup(f"claimant{index}", "a sufficiently long password"))

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(1 for r in results if r) == 1, results
    assert len(manager.users) == 1
