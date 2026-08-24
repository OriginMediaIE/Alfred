import hashlib
import json

from core.auth import AuthManager, LOGIN_FAILURE_LIMIT


def _manager(tmp_path):
    manager = AuthManager(str(tmp_path / "auth.json"))
    assert manager.setup("alice", "correct horse battery staple")
    return manager


def test_login_failures_lock_and_success_clears_state(tmp_path):
    manager = _manager(tmp_path)
    for _ in range(LOGIN_FAILURE_LIMIT - 1):
        assert manager.record_login_failure("alice") is False
        assert manager.login_allowed("alice") is True
    assert manager.record_login_failure("alice") is True
    assert manager.login_allowed("alice") is False
    manager.record_login_success("alice")
    assert manager.login_allowed("alice") is True


def test_sessions_expose_metadata_not_tokens_and_can_be_revoked(tmp_path):
    manager = _manager(tmp_path)
    token = manager.create_session_trusted("alice")
    assert token
    manager.annotate_session(token, user_agent="Test Browser", ip="127.0.0.1")
    sessions = manager.list_user_sessions("alice", token)
    assert len(sessions) == 1
    assert sessions[0]["current"] is True
    assert sessions[0]["user_agent"] == "Test Browser"
    assert token not in json.dumps(sessions)
    assert manager.revoke_user_session_id("alice", sessions[0]["id"]) is True
    assert manager.validate_token(token) is False


def test_auth_audit_is_redacted_and_hash_chained(tmp_path):
    manager = _manager(tmp_path)
    manager.append_auth_audit("login_failed", target="alice", ip="127.0.0.1", details={"password": "never-store", "locked": False})
    manager.append_auth_audit("login_succeeded", actor="alice", target="alice", ip="127.0.0.1")
    rows = list(reversed(manager.list_auth_audit()))
    assert len(rows) == 2
    assert "never-store" not in json.dumps(rows)
    previous = "0" * 64
    for row in rows:
        digest = row.pop("hash")
        assert row["previous_hash"] == previous
        canonical = json.dumps(row, sort_keys=True, separators=(",", ":"))
        assert digest == hashlib.sha256((previous + canonical).encode("utf-8")).hexdigest()
        previous = digest


def test_admin_password_reset_revokes_every_session(tmp_path):
    manager = _manager(tmp_path)
    assert manager.create_user("bob", "a sufficiently long password")
    token = manager.create_session_trusted("bob")
    assert manager.reset_password("bob", "a newer sufficiently long password", "alice")
    assert manager.validate_token(token) is False
    assert manager.verify_password("bob", "a newer sufficiently long password") is True


def test_existing_corrupt_auth_store_fails_closed(tmp_path):
    path=tmp_path/"auth.json";path.write_text("{not valid json",encoding="utf-8")
    manager=AuthManager(str(path))
    assert manager.recovery_required is True
    assert manager.is_configured is True
    assert manager.setup("attacker","a sufficiently long password") is False
    assert path.read_text(encoding="utf-8")=="{not valid json"


def test_existing_empty_auth_store_is_recovery_not_first_boot(tmp_path):
    path=tmp_path/"auth.json";path.write_text("{}",encoding="utf-8")
    manager=AuthManager(str(path))
    assert manager.recovery_required is True
    assert manager.setup("attacker","a sufficiently long password") is False
