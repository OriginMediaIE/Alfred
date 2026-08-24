"""Secure Google OAuth connection lifecycle regressions."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import hashlib
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base, GoogleConnection, GoogleOAuthAttempt
from src.google_connection import (
    GOOGLE_REVOKE_URL,
    GOOGLE_TOKEN_URL,
    GoogleConfigurationError,
    GoogleConnectionNotFound,
    GoogleConnectionService,
    GoogleOAuthStateError,
    GoogleProviderError,
    validate_redirect_uri,
)


class _Response:
    def __init__(self, payload=None, *, status=200, content=b"json"):
        self._payload = payload
        self.status_code = status
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeHttpClient:
    def __init__(self):
        self.calls = []
        self.responses = []

    def queue(self, response):
        self.responses.append(response)

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError(f"Unexpected provider call: {method} {url}")
        return self.responses.pop(0)


@pytest.fixture
def google_env(tmp_path, monkeypatch):
    import src.secret_storage as secret_storage

    monkeypatch.setattr(secret_storage, "_KEY_PATH", tmp_path / ".app_key")
    monkeypatch.setattr(secret_storage, "_fernet", None)
    for name in (
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_REDIRECT_URI",
    ):
        monkeypatch.delenv(name, raising=False)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    now = [datetime(2026, 7, 18, 12, 0, 0)]
    http = _FakeHttpClient()
    service = GoogleConnectionService(
        session_factory=factory,
        clock=lambda: now[0],
        http_client=http,
    )
    try:
        yield service, factory, engine, now, http
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _configure(service):
    return service.save_client_settings(
        "alice",
        client_id="client-id.apps.googleusercontent.com",
        client_secret="super-secret-client-value",
        redirect_uri="http://localhost:7000/api/integrations/google/oauth/callback",
    )


def _begin(service, capabilities=("gmail.read", "calendar.read")):
    started = service.begin_authorization("alice", capabilities)
    query = parse_qs(urlsplit(started["authorization_url"]).query)
    return started, query, query["state"][0]


def test_redirect_uri_requires_https_except_exact_loopback_callback():
    assert validate_redirect_uri(
        "http://localhost:7000/api/integrations/google/oauth/callback"
    ).startswith("http://localhost:7000/")
    assert validate_redirect_uri(
        "https://om.example/api/integrations/google/oauth/callback"
    ).startswith("https://om.example/")

    with pytest.raises(GoogleConfigurationError):
        validate_redirect_uri(
            "http://om.example/api/integrations/google/oauth/callback"
        )
    with pytest.raises(GoogleConfigurationError):
        validate_redirect_uri("https://om.example/wrong/callback")
    with pytest.raises(GoogleConfigurationError):
        validate_redirect_uri(
            "https://user:pass@om.example/api/integrations/google/oauth/callback"
        )


def test_authorization_uses_pkce_one_time_state_and_minimal_scopes(google_env):
    service, factory, engine, _now, _http = google_env
    status = _configure(service)

    started, query, state = _begin(service)

    assert status["configured"] is True
    assert status["has_client_secret"] is True
    assert "super-secret-client-value" not in str(status)
    assert query["code_challenge_method"] == ["S256"]
    assert len(query["code_challenge"][0]) >= 43
    assert query["access_type"] == ["offline"]
    assert query["include_granted_scopes"] == ["true"]
    scope = set(query["scope"][0].split())
    assert "openid" in scope
    assert "https://www.googleapis.com/auth/gmail.readonly" in scope
    assert "https://www.googleapis.com/auth/calendar.events.readonly" in scope
    assert "https://mail.google.com/" not in scope
    assert "https://www.googleapis.com/auth/gmail.modify" not in scope
    assert started["requested_capabilities"] == ["gmail.read", "calendar.read"]

    db = factory()
    try:
        row = db.get(GoogleOAuthAttempt, hashlib.sha256(state.encode()).hexdigest())
        assert row is not None
        assert row.owner == "alice"
        assert row.code_verifier
    finally:
        db.close()
    with engine.connect() as connection:
        raw = connection.execute(
            text("SELECT state_hash, code_verifier FROM google_oauth_attempts")
        ).one()
        config = connection.execute(
            text(
                "SELECT client_secret FROM google_oauth_client_configs WHERE owner='alice'"
            )
        ).scalar_one()
    assert raw.state_hash != state
    assert state not in raw.code_verifier
    assert str(raw.code_verifier).startswith("enc:")
    assert str(config).startswith("enc:")
    assert "super-secret-client-value" not in str(config)


def test_oauth_callback_is_owner_bound_one_time_and_encrypts_tokens(google_env):
    service, _factory, engine, _now, http = google_env
    _configure(service)
    _started, _query, state = _begin(service, ("gmail.send",))

    with pytest.raises(GoogleOAuthStateError):
        asyncio.run(
            service.complete_authorization("mallory", state=state, code="code-a")
        )
    assert http.calls == []

    http.queue(
        _Response(
            {
                "access_token": "raw-access-token",
                "refresh_token": "raw-refresh-token",
                "expires_in": 3600,
                "scope": "openid email profile https://www.googleapis.com/auth/gmail.send",
                "token_type": "Bearer",
            }
        )
    )
    http.queue(
        _Response(
            {
                "sub": "google-subject-1",
                "email": "Alice@Example.com",
                "email_verified": True,
                "name": "Alice Example",
            }
        )
    )
    connected = asyncio.run(
        service.complete_authorization("alice", state=state, code="code-a")
    )

    assert connected["email"] == "alice@example.com"
    assert connected["status"] == "connected"
    assert connected["has_refresh_token"] is True
    serialized = str(connected)
    assert "raw-access-token" not in serialized
    assert "raw-refresh-token" not in serialized
    token_call = http.calls[0]
    assert token_call[1] == GOOGLE_TOKEN_URL
    assert token_call[2]["data"]["code_verifier"]

    with engine.connect() as connection:
        raw = connection.execute(
            text("SELECT access_token, refresh_token FROM google_connections")
        ).one()
    assert str(raw.access_token).startswith("enc:")
    assert str(raw.refresh_token).startswith("enc:")
    assert "raw-access-token" not in str(raw)
    assert "raw-refresh-token" not in str(raw)

    with pytest.raises(GoogleOAuthStateError):
        asyncio.run(
            service.complete_authorization("alice", state=state, code="code-a")
        )
    assert len(http.calls) == 2


def test_preferences_validate_timezone_and_are_owner_isolated(google_env):
    service, factory, _engine, _now, _http = google_env
    db = factory()
    try:
        db.add(
            GoogleConnection(
                id="google-1",
                owner="alice",
                google_subject="sub-1",
                email="alice@example.com",
                refresh_token="refresh",
            )
        )
        db.commit()
    finally:
        db.close()

    updated = service.update_preferences(
        "alice",
        "google-1",
        {
            "timezone": "Europe/Dublin",
            "default_send_behavior": "draft",
            "selected_calendars": ["primary", "work", "primary"],
            "gmail_label_preferences": {"include": ["IMPORTANT"]},
            "background_sync_enabled": True,
        },
    )
    assert updated["timezone"] == "Europe/Dublin"
    assert updated["selected_calendars"] == ["primary", "work"]
    assert updated["background_sync_enabled"] is True

    with pytest.raises(GoogleConfigurationError):
        service.update_preferences("alice", "google-1", {"timezone": "Mars/Base"})
    with pytest.raises(GoogleConnectionNotFound):
        service.get_connection("mallory", "google-1")


def test_refresh_failure_marks_reconnect_without_exposing_refresh_token(google_env):
    service, factory, _engine, _now, http = google_env
    _configure(service)
    db = factory()
    try:
        db.add(
            GoogleConnection(
                id="google-1",
                owner="alice",
                google_subject="sub-1",
                email="alice@example.com",
                refresh_token="private-refresh",
            )
        )
        db.commit()
    finally:
        db.close()
    http.queue(_Response({"error": "invalid_grant"}, status=400))

    with pytest.raises(GoogleProviderError) as exc:
        asyncio.run(service.refresh("alice", "google-1"))

    assert "private-refresh" not in str(exc.value)
    connection = service.get_connection("alice", "google-1")
    assert connection["status"] == "reconnect_required"
    assert "private-refresh" not in str(connection)


def test_check_connection_validates_identity_and_updates_health(google_env):
    service, factory, _engine, now, http = google_env
    db = factory()
    try:
        db.add(
            GoogleConnection(
                id="google-check",
                owner="alice",
                google_subject="sub-check",
                email="alice@example.com",
                access_token="private-access",
                refresh_token="private-refresh",
                token_expiry=now[0] + timedelta(hours=1),
                status="error",
                last_sync_error="old failure",
            )
        )
        db.commit()
    finally:
        db.close()
    http.queue(
        _Response(
            {
                "sub": "sub-check",
                "email": "alice@example.com",
                "email_verified": True,
            }
        )
    )

    result = asyncio.run(service.check_connection("alice", "google-check"))

    assert result["status"] == "connected"
    assert result["last_validated_at"] == now[0].isoformat() + "Z"
    assert result["last_successful_sync"] == now[0].isoformat() + "Z"
    assert result["last_sync_error"] is None
    assert http.calls[0][1].endswith("/v1/userinfo")
    assert http.calls[0][2]["headers"]["Authorization"] == "Bearer private-access"
    assert "private-access" not in str(result)


def test_provider_revocation_precedes_local_credential_erasure(google_env):
    service, factory, _engine, _now, http = google_env
    db = factory()
    try:
        db.add(
            GoogleConnection(
                id="google-1",
                owner="alice",
                google_subject="sub-1",
                email="alice@example.com",
                access_token="access",
                refresh_token="refresh",
                background_sync_enabled=True,
            )
        )
        db.commit()
    finally:
        db.close()
    http.queue(_Response(None, content=b""))

    result = asyncio.run(
        service.disconnect("alice", "google-1", revoke_provider=True)
    )

    assert http.calls[0][1] == GOOGLE_REVOKE_URL
    assert http.calls[0][2]["data"] == {"token": "refresh"}
    assert result["status"] == "revoked"
    assert result["has_refresh_token"] is False
    assert result["background_sync_enabled"] is False
    assert "refresh_token" not in result
    assert "access_token" not in result


def test_expired_or_denied_state_is_consumed_without_provider_call(google_env):
    service, _factory, _engine, now, http = google_env
    _configure(service)
    _started, _query, state = _begin(service, ("calendar.freebusy",))

    service.reject_authorization("alice", state)
    with pytest.raises(GoogleOAuthStateError):
        service.reject_authorization("alice", state)
    with pytest.raises(GoogleOAuthStateError):
        asyncio.run(
            service.complete_authorization("alice", state=state, code="unused")
        )
    assert http.calls == []

    _started, _query, expired_state = _begin(service, ("calendar.freebusy",))
    now[0] += timedelta(minutes=11)
    with pytest.raises(GoogleOAuthStateError):
        asyncio.run(
            service.complete_authorization(
                "alice", state=expired_state, code="unused"
            )
        )


def test_remote_request_cannot_derive_redirect_uri_from_host_header():
    from routes.google_routes import _local_callback

    remote = SimpleNamespace(
        url=SimpleNamespace(hostname="localhost", port=7000),
        client=SimpleNamespace(host="203.0.113.5"),
    )
    local = SimpleNamespace(
        url=SimpleNamespace(hostname="localhost", port=7000),
        client=SimpleNamespace(host="127.0.0.1"),
    )

    assert _local_callback(remote) is None
    assert (
        _local_callback(local)
        == "http://localhost:7000/api/integrations/google/oauth/callback"
    )
