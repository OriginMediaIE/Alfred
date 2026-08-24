"""Secure Google OAuth connection lifecycle for OM Automate.

This service keeps OAuth credentials behind the backend boundary.  Browser and
agent callers receive connection metadata only; access tokens, refresh tokens,
client secrets, and PKCE verifiers are encrypted by ``EncryptedText`` and are
never returned from this module.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import secrets
from typing import Any, Callable, Iterable, Mapping, Optional
from urllib.parse import urlencode, urlsplit, urlunsplit
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.database import (
    GoogleConnection,
    GoogleOAuthAttempt,
    GoogleOAuthClientConfig,
    SessionLocal,
)


GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_CALLBACK_PATH = "/api/integrations/google/oauth/callback"

IDENTITY_SCOPES = frozenset({"openid", "email", "profile"})
CAPABILITY_SCOPES: Mapping[str, frozenset[str]] = {
    "gmail.read": frozenset(
        {"https://www.googleapis.com/auth/gmail.readonly"}
    ),
    "gmail.draft": frozenset(
        {"https://www.googleapis.com/auth/gmail.compose"}
    ),
    "gmail.send": frozenset(
        {
            "https://www.googleapis.com/auth/gmail.send",
            # Read-back is mandatory after delivery; request the narrow read
            # scope alongside send rather than claiming success from the POST.
            "https://www.googleapis.com/auth/gmail.readonly",
        }
    ),
    "gmail.modify": frozenset(
        {"https://www.googleapis.com/auth/gmail.modify"}
    ),
    "gmail.labels": frozenset(
        {"https://www.googleapis.com/auth/gmail.labels"}
    ),
    "calendar.read": frozenset(
        {
            "https://www.googleapis.com/auth/calendar.events.readonly",
            "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
        }
    ),
    "calendar.write": frozenset(
        {
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
        }
    ),
    "calendar.freebusy": frozenset(
        {"https://www.googleapis.com/auth/calendar.freebusy"}
    ),
}


class GoogleConnectionError(RuntimeError):
    """Base class for controlled connection failures."""

    code = "google_connection_error"


class GoogleConfigurationError(GoogleConnectionError):
    code = "google_not_configured"


class GoogleOAuthStateError(GoogleConnectionError):
    code = "invalid_oauth_state"


class GoogleProviderError(GoogleConnectionError):
    code = "google_provider_error"

    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GoogleConnectionNotFound(GoogleConnectionError):
    code = "google_connection_not_found"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _owner_key(owner: Optional[str]) -> str:
    return str(owner or "__single_user__")


def _json_list(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _json_object(value: object) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _state_hash(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def validate_redirect_uri(value: str) -> str:
    """Allow HTTPS callbacks, or explicit loopback HTTP for local installs."""

    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise GoogleConfigurationError("Google redirect URI is invalid.") from exc
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise GoogleConfigurationError(
            "Google redirect URI cannot contain credentials, a query, or a fragment."
        )
    host = (parsed.hostname or "").lower()
    loopback = host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme == "http" and not loopback:
        raise GoogleConfigurationError(
            "Google redirect URI must use HTTPS except on localhost."
        )
    if parsed.scheme not in {"http", "https"} or not host:
        raise GoogleConfigurationError("Google redirect URI must be an HTTP(S) URL.")
    if parsed.path.rstrip("/") != GOOGLE_CALLBACK_PATH:
        raise GoogleConfigurationError(
            f"Google redirect URI path must be '{GOOGLE_CALLBACK_PATH}'."
        )
    return urlunsplit((parsed.scheme, parsed.netloc, GOOGLE_CALLBACK_PATH, "", ""))


@dataclass(frozen=True, slots=True)
class OAuthClientSettings:
    client_id: str
    client_secret: str
    redirect_uri: str
    source: str


class GoogleConnectionService:
    """Owner-scoped Google OAuth and connection manager."""

    def __init__(
        self,
        *,
        session_factory=SessionLocal,
        clock: Callable[[], datetime] = _utcnow,
        http_client: Any = None,
        attempt_ttl: timedelta = timedelta(minutes=10),
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._http_client = http_client
        self._attempt_ttl = attempt_ttl

    @staticmethod
    def available_capabilities() -> list[dict[str, Any]]:
        descriptions = {
            "gmail.read": "Read messages and threads.",
            "gmail.draft": "Create and update Gmail drafts.",
            "gmail.send": "Send email after OM approval.",
            "gmail.modify": "Archive, mark, label, and move messages to trash.",
            "gmail.labels": "Create and manage labels.",
            "calendar.read": "Read calendars and events.",
            "calendar.write": "Create and update calendar events after OM approval.",
            "calendar.freebusy": "Check availability without reading event details.",
        }
        return [
            {
                "id": name,
                "description": descriptions[name],
                "scopes": sorted(scopes),
            }
            for name, scopes in CAPABILITY_SCOPES.items()
        ]

    def get_client_status(
        self,
        owner: Optional[str],
        *,
        fallback_redirect_uri: Optional[str] = None,
    ) -> dict[str, Any]:
        try:
            settings = self._resolve_client_settings(
                owner, fallback_redirect_uri=fallback_redirect_uri
            )
        except GoogleConfigurationError:
            return {
                "configured": False,
                "source": None,
                "client_id": None,
                "has_client_secret": False,
                "redirect_uri": fallback_redirect_uri,
                "callback_path": GOOGLE_CALLBACK_PATH,
                "capabilities": self.available_capabilities(),
            }
        return {
            "configured": True,
            "source": settings.source,
            "client_id": settings.client_id,
            "has_client_secret": bool(settings.client_secret),
            "redirect_uri": settings.redirect_uri,
            "callback_path": GOOGLE_CALLBACK_PATH,
            "capabilities": self.available_capabilities(),
        }

    def save_client_settings(
        self,
        owner: Optional[str],
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        client_id = str(client_id or "").strip()
        client_secret = str(client_secret or "").strip()
        if not client_id or len(client_id) > 512:
            raise GoogleConfigurationError("A valid Google OAuth client ID is required.")
        if not client_secret or len(client_secret) > 2048:
            raise GoogleConfigurationError(
                "A valid Google OAuth client secret is required."
            )
        redirect_uri = validate_redirect_uri(redirect_uri)
        db = self._session_factory()
        try:
            key = _owner_key(owner)
            row = db.get(GoogleOAuthClientConfig, key)
            if row is None:
                row = GoogleOAuthClientConfig(owner=key)
                db.add(row)
            row.client_id = client_id
            row.client_secret = client_secret
            row.redirect_uri = redirect_uri
            db.commit()
        finally:
            db.close()
        return self.get_client_status(owner)

    def delete_client_settings(self, owner: Optional[str]) -> bool:
        db = self._session_factory()
        try:
            row = db.get(GoogleOAuthClientConfig, _owner_key(owner))
            if row is None:
                return False
            active = (
                db.query(GoogleConnection)
                .filter(
                    GoogleConnection.owner == _owner_key(owner),
                    GoogleConnection.status == "connected",
                )
                .count()
            )
            if active:
                raise GoogleConfigurationError(
                    "Disconnect Google accounts before removing OAuth client settings."
                )
            db.delete(row)
            db.commit()
            return True
        finally:
            db.close()

    def _resolve_client_settings(
        self,
        owner: Optional[str],
        *,
        fallback_redirect_uri: Optional[str] = None,
    ) -> OAuthClientSettings:
        db = self._session_factory()
        try:
            row = db.get(GoogleOAuthClientConfig, _owner_key(owner))
            if row is not None:
                return OAuthClientSettings(
                    client_id=str(row.client_id or ""),
                    client_secret=str(row.client_secret or ""),
                    redirect_uri=validate_redirect_uri(row.redirect_uri),
                    source="user",
                )
        finally:
            db.close()

        client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
        redirect_uri = (
            os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "").strip()
            or str(fallback_redirect_uri or "").strip()
        )
        if not client_id or not client_secret or not redirect_uri:
            raise GoogleConfigurationError(
                "Configure a Google OAuth client before connecting an account."
            )
        return OAuthClientSettings(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=validate_redirect_uri(redirect_uri),
            source="environment",
        )

    def begin_authorization(
        self,
        owner: Optional[str],
        capabilities: Iterable[str],
        *,
        fallback_redirect_uri: Optional[str] = None,
        login_hint: Optional[str] = None,
    ) -> dict[str, Any]:
        requested = tuple(dict.fromkeys(str(item) for item in capabilities))
        unknown = sorted(set(requested) - set(CAPABILITY_SCOPES))
        if unknown:
            raise GoogleConfigurationError(
                "Unknown Google capabilities: " + ", ".join(unknown)
            )
        if not requested:
            raise GoogleConfigurationError(
                "Choose at least one Gmail or Calendar capability."
            )
        settings = self._resolve_client_settings(
            owner, fallback_redirect_uri=fallback_redirect_uri
        )
        scopes = set(IDENTITY_SCOPES)
        for capability in requested:
            scopes.update(CAPABILITY_SCOPES[capability])

        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        now = self._clock()
        db = self._session_factory()
        try:
            db.query(GoogleOAuthAttempt).filter(
                GoogleOAuthAttempt.expires_at <= now
            ).delete(synchronize_session=False)
            db.add(
                GoogleOAuthAttempt(
                    state_hash=_state_hash(state),
                    owner=_owner_key(owner),
                    code_verifier=verifier,
                    requested_scopes_json=json.dumps(sorted(scopes)),
                    redirect_uri=settings.redirect_uri,
                    expires_at=now + self._attempt_ttl,
                )
            )
            db.commit()
        finally:
            db.close()

        params = {
            "client_id": settings.client_id,
            "redirect_uri": settings.redirect_uri,
            "response_type": "code",
            "scope": " ".join(sorted(scopes)),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent select_account",
            "state": state,
            "code_challenge": _pkce_challenge(verifier),
            "code_challenge_method": "S256",
        }
        if login_hint:
            params["login_hint"] = str(login_hint).strip()[:320]
        return {
            "authorization_url": f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}",
            "expires_at": (now + self._attempt_ttl).isoformat() + "Z",
            "requested_capabilities": list(requested),
            "requested_scopes": sorted(scopes),
        }

    async def complete_authorization(
        self,
        owner: Optional[str],
        *,
        state: str,
        code: str,
    ) -> dict[str, Any]:
        state = str(state or "")
        code = str(code or "")
        if not state or len(state) > 512 or not code or len(code) > 8192:
            raise GoogleOAuthStateError("OAuth callback is missing state or code.")
        now = self._clock()
        db = self._session_factory()
        try:
            digest = _state_hash(state)
            row = db.get(GoogleOAuthAttempt, digest)
            if (
                row is None
                or row.owner != _owner_key(owner)
                or row.consumed_at is not None
                or row.expires_at <= now
            ):
                raise GoogleOAuthStateError(
                    "OAuth state is invalid, expired, already used, or belongs to another user."
                )
            updated = (
                db.query(GoogleOAuthAttempt)
                .filter(
                    GoogleOAuthAttempt.state_hash == digest,
                    GoogleOAuthAttempt.owner == _owner_key(owner),
                    GoogleOAuthAttempt.consumed_at.is_(None),
                    GoogleOAuthAttempt.expires_at > now,
                )
                .update({GoogleOAuthAttempt.consumed_at: now})
            )
            if updated != 1:
                db.rollback()
                raise GoogleOAuthStateError("OAuth state has already been consumed.")
            verifier = str(row.code_verifier)
            redirect_uri = str(row.redirect_uri)
            requested_scopes = set(_json_list(row.requested_scopes_json))
            db.commit()
        finally:
            db.close()

        settings = self._resolve_client_settings(
            owner, fallback_redirect_uri=redirect_uri
        )
        token_response = await self._request_json(
            "POST",
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.client_id,
                "client_secret": settings.client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
        )
        access_token = str(token_response.get("access_token") or "")
        if not access_token:
            raise GoogleProviderError("Google did not return an access token.")
        granted_scopes = set(
            str(token_response.get("scope") or "").split()
        ) or requested_scopes
        # Never treat unrequested scopes in a malformed provider response as
        # authority. Incremental authorization may return prior grants, but OM
        # records only the current attempt's explicit scope set.
        granted_scopes.intersection_update(requested_scopes)

        userinfo = await self._request_json(
            "GET",
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        subject = str(userinfo.get("sub") or "").strip()
        email = str(userinfo.get("email") or "").strip().lower()
        if not subject or not email or userinfo.get("email_verified") is False:
            raise GoogleProviderError(
                "Google did not return a verified account identity."
            )

        expires_in = token_response.get("expires_in", 3600)
        try:
            expires_seconds = max(60, min(int(expires_in), 86400))
        except (TypeError, ValueError):
            expires_seconds = 3600
        db = self._session_factory()
        try:
            owner_key = _owner_key(owner)
            connection = (
                db.query(GoogleConnection)
                .filter(
                    GoogleConnection.owner == owner_key,
                    GoogleConnection.google_subject == subject,
                )
                .first()
            )
            if connection is None:
                connection = GoogleConnection(
                    id=uuid.uuid4().hex,
                    owner=owner_key,
                    google_subject=subject,
                    email=email,
                )
                db.add(connection)
            connection.email = email
            connection.display_name = str(userinfo.get("name") or "")[:512] or None
            connection.status = "connected"
            connection.granted_scopes_json = json.dumps(sorted(granted_scopes))
            connection.access_token = access_token
            refresh_token = str(token_response.get("refresh_token") or "")
            if refresh_token:
                connection.refresh_token = refresh_token
            if not connection.refresh_token:
                raise GoogleProviderError(
                    "Google did not return an offline refresh token; reconnect with consent."
                )
            connection.token_expiry = now + timedelta(seconds=expires_seconds)
            connection.token_type = str(token_response.get("token_type") or "Bearer")[:32]
            connection.last_validated_at = now
            connection.last_sync_error = None
            connection.revoked_at = None
            db.commit()
            connection_id = connection.id
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        return self.get_connection(owner, connection_id)

    def reject_authorization(self, owner: Optional[str], state: str) -> None:
        """Consume a denied OAuth attempt so its state cannot be replayed."""

        now = self._clock()
        db = self._session_factory()
        try:
            updated = (
                db.query(GoogleOAuthAttempt)
                .filter(
                    GoogleOAuthAttempt.state_hash == _state_hash(str(state or "")),
                    GoogleOAuthAttempt.owner == _owner_key(owner),
                    GoogleOAuthAttempt.consumed_at.is_(None),
                    GoogleOAuthAttempt.expires_at > now,
                )
                .update({GoogleOAuthAttempt.consumed_at: now})
            )
            if updated != 1:
                db.rollback()
                raise GoogleOAuthStateError(
                    "OAuth state is invalid, expired, already used, or belongs to another user."
                )
            db.commit()
        finally:
            db.close()

    def list_connections(self, owner: Optional[str]) -> list[dict[str, Any]]:
        db = self._session_factory()
        try:
            rows = (
                db.query(GoogleConnection)
                .filter(GoogleConnection.owner == _owner_key(owner))
                .order_by(GoogleConnection.created_at.asc())
                .all()
            )
            return [self._serialize_connection(row) for row in rows]
        finally:
            db.close()

    def get_connection(
        self, owner: Optional[str], connection_id: str
    ) -> dict[str, Any]:
        db = self._session_factory()
        try:
            row = self._owned_connection(db, owner, connection_id)
            return self._serialize_connection(row)
        finally:
            db.close()

    def update_preferences(
        self,
        owner: Optional[str],
        connection_id: str,
        changes: Mapping[str, Any],
    ) -> dict[str, Any]:
        allowed = {
            "selected_calendars",
            "gmail_label_preferences",
            "default_send_behavior",
            "default_calendar",
            "timezone",
            "background_sync_enabled",
        }
        unknown = sorted(set(changes) - allowed)
        if unknown:
            raise GoogleConfigurationError(
                "Unknown Google preferences: " + ", ".join(unknown)
            )
        db = self._session_factory()
        try:
            row = self._owned_connection(db, owner, connection_id)
            if "selected_calendars" in changes:
                calendars = changes["selected_calendars"]
                if not isinstance(calendars, list) or len(calendars) > 100:
                    raise GoogleConfigurationError(
                        "selected_calendars must be a list of at most 100 IDs."
                    )
                normalized = [str(item).strip()[:1024] for item in calendars]
                row.selected_calendars_json = json.dumps(
                    list(dict.fromkeys(item for item in normalized if item))
                )
            if "gmail_label_preferences" in changes:
                labels = changes["gmail_label_preferences"]
                if not isinstance(labels, dict) or len(labels) > 100:
                    raise GoogleConfigurationError(
                        "gmail_label_preferences must be an object."
                    )
                row.gmail_label_preferences_json = json.dumps(labels)
            if "default_send_behavior" in changes:
                behavior = str(changes["default_send_behavior"] or "")
                if behavior not in {"draft", "approval_required"}:
                    raise GoogleConfigurationError(
                        "default_send_behavior must be draft or approval_required."
                    )
                row.default_send_behavior = behavior
            if "default_calendar" in changes:
                row.default_calendar = str(changes["default_calendar"] or "")[:1024] or None
            if "timezone" in changes:
                timezone_name = str(changes["timezone"] or "")
                try:
                    ZoneInfo(timezone_name)
                except (ZoneInfoNotFoundError, ValueError) as exc:
                    raise GoogleConfigurationError("Timezone is not a valid IANA name.") from exc
                row.timezone = timezone_name
            if "background_sync_enabled" in changes:
                if not isinstance(changes["background_sync_enabled"], bool):
                    raise GoogleConfigurationError(
                        "background_sync_enabled must be a boolean."
                    )
                row.background_sync_enabled = changes["background_sync_enabled"]
            db.commit()
            return self._serialize_connection(row)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def refresh(
        self, owner: Optional[str], connection_id: str
    ) -> dict[str, Any]:
        db = self._session_factory()
        try:
            row = self._owned_connection(db, owner, connection_id)
            refresh_token = str(row.refresh_token or "")
            if not refresh_token:
                row.status = "reconnect_required"
                row.last_sync_error = "No refresh token is available."
                db.commit()
                raise GoogleProviderError("Reconnect Google to obtain a refresh token.")
        finally:
            db.close()
        settings = self._resolve_client_settings(owner)
        try:
            response = await self._request_json(
                "POST",
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": settings.client_id,
                    "client_secret": settings.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        except GoogleProviderError as exc:
            self._mark_connection_error(owner, connection_id, str(exc), reconnect=True)
            raise
        access_token = str(response.get("access_token") or "")
        if not access_token:
            self._mark_connection_error(
                owner, connection_id, "Google returned no access token.", reconnect=True
            )
            raise GoogleProviderError("Google returned no access token.")
        try:
            expires_seconds = max(60, min(int(response.get("expires_in", 3600)), 86400))
        except (TypeError, ValueError):
            expires_seconds = 3600
        now = self._clock()
        db = self._session_factory()
        try:
            row = self._owned_connection(db, owner, connection_id)
            row.access_token = access_token
            if response.get("refresh_token"):
                row.refresh_token = str(response["refresh_token"])
            row.token_expiry = now + timedelta(seconds=expires_seconds)
            row.status = "connected"
            row.last_sync_error = None
            db.commit()
            return self._serialize_connection(row)
        finally:
            db.close()

    async def check_connection(
        self, owner: Optional[str], connection_id: str
    ) -> dict[str, Any]:
        db = self._session_factory()
        try:
            row = self._owned_connection(db, owner, connection_id)
            needs_refresh = not row.access_token or (
                row.token_expiry is not None
                and row.token_expiry <= self._clock() + timedelta(seconds=60)
            )
        finally:
            db.close()
        if needs_refresh:
            await self.refresh(owner, connection_id)
        db = self._session_factory()
        try:
            row = self._owned_connection(db, owner, connection_id)
            access_token = str(row.access_token or "")
        finally:
            db.close()
        try:
            info = await self._request_json(
                "GET",
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if not info.get("sub"):
                raise GoogleProviderError("Google identity check returned no subject.")
        except GoogleProviderError as exc:
            self._mark_connection_error(owner, connection_id, str(exc), reconnect=False)
            raise
        now = self._clock()
        db = self._session_factory()
        try:
            row = self._owned_connection(db, owner, connection_id)
            if str(info.get("sub")) != row.google_subject:
                raise GoogleProviderError(
                    "Google identity no longer matches this connection."
                )
            row.status = "connected"
            row.last_validated_at = now
            row.last_successful_sync = now
            row.last_sync_error = None
            db.commit()
            return self._serialize_connection(row)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def authorized_request_json(
        self,
        owner: Optional[str],
        connection_id: str,
        *,
        method: str,
        url: str,
        required_scopes: Iterable[str],
        params: Optional[Mapping[str, Any]] = None,
        json_body: Optional[Mapping[str, Any]] = None,
        extra_headers: Optional[Mapping[str, str]] = None,
        accept_empty: bool = False,
    ) -> dict[str, Any]:
        """Call a fixed Google API endpoint without exposing bearer tokens.

        Provider adapters use this method; routes and model tools never receive
        the token.  Exact host/path validation prevents a compromised adapter
        argument from turning the connection manager into a bearer-token SSRF
        primitive.
        """

        method = str(method or "").upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise GoogleConfigurationError("Unsupported Google API method.")
        parsed = urlsplit(str(url or ""))
        allowed_prefixes = {
            "gmail.googleapis.com": ("/gmail/v1/",),
            "www.googleapis.com": ("/calendar/v3/", "/gmail/v1/"),
        }
        prefixes = allowed_prefixes.get((parsed.hostname or "").lower())
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not prefixes
            or not any(parsed.path.startswith(prefix) for prefix in prefixes)
        ):
            raise GoogleConfigurationError("Google API endpoint is not allowed.")

        required = frozenset(str(scope) for scope in required_scopes)
        db = self._session_factory()
        try:
            row = self._owned_connection(db, owner, connection_id)
            granted = frozenset(_json_list(row.granted_scopes_json))
            missing = required - granted
            if missing:
                raise GoogleConfigurationError(
                    "Google connection is missing required scopes: "
                    + ", ".join(sorted(missing))
                )
            needs_refresh = not row.access_token or (
                row.token_expiry is not None
                and row.token_expiry <= self._clock() + timedelta(seconds=60)
            )
        finally:
            db.close()
        if needs_refresh:
            await self.refresh(owner, connection_id)
        db = self._session_factory()
        try:
            row = self._owned_connection(db, owner, connection_id)
            access_token = str(row.access_token or "")
            if not access_token:
                raise GoogleProviderError("Google access token is unavailable.")
        finally:
            db.close()
        safe_headers: dict[str, str] = {
            "Authorization": f"Bearer {access_token}"
        }
        for name, value in (extra_headers or {}).items():
            if str(name).lower() not in {"if-match", "if-none-match"}:
                raise GoogleConfigurationError("Google API header is not allowed.")
            safe_headers[str(name)] = str(value)[:1024]
        return await self._request_json(
            method,
            url,
            headers=safe_headers,
            params=params,
            json_body=json_body,
            accept_empty=accept_empty,
        )

    async def disconnect(
        self,
        owner: Optional[str],
        connection_id: str,
        *,
        revoke_provider: bool,
    ) -> dict[str, Any]:
        db = self._session_factory()
        try:
            row = self._owned_connection(db, owner, connection_id)
            token = str(row.refresh_token or row.access_token or "")
        finally:
            db.close()
        if revoke_provider and token:
            await self._request_json(
                "POST",
                GOOGLE_REVOKE_URL,
                data={"token": token},
                accept_empty=True,
            )
        now = self._clock()
        db = self._session_factory()
        try:
            row = self._owned_connection(db, owner, connection_id)
            row.access_token = None
            row.refresh_token = None
            row.token_expiry = None
            row.status = "revoked" if revoke_provider else "disconnected"
            row.revoked_at = now if revoke_provider else None
            row.background_sync_enabled = False
            row.last_sync_error = None
            db.commit()
            return self._serialize_connection(row)
        finally:
            db.close()

    def _mark_connection_error(
        self,
        owner: Optional[str],
        connection_id: str,
        message: str,
        *,
        reconnect: bool,
    ) -> None:
        db = self._session_factory()
        try:
            row = self._owned_connection(db, owner, connection_id)
            row.status = "reconnect_required" if reconnect else "error"
            row.last_sync_error = str(message)[:2000]
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _owned_connection(db, owner: Optional[str], connection_id: str) -> GoogleConnection:
        row = (
            db.query(GoogleConnection)
            .filter(
                GoogleConnection.id == str(connection_id),
                GoogleConnection.owner == _owner_key(owner),
            )
            .first()
        )
        if row is None:
            raise GoogleConnectionNotFound("Google connection was not found.")
        return row

    @staticmethod
    def _serialize_connection(row: GoogleConnection) -> dict[str, Any]:
        def iso(value: Optional[datetime]) -> Optional[str]:
            return value.isoformat() + "Z" if value else None

        return {
            "id": row.id,
            "email": row.email,
            "display_name": row.display_name,
            "status": row.status,
            "granted_scopes": sorted(_json_list(row.granted_scopes_json)),
            "token_expires_at": iso(row.token_expiry),
            "last_successful_sync": iso(row.last_successful_sync),
            "last_sync_error": row.last_sync_error,
            "last_validated_at": iso(row.last_validated_at),
            "revoked_at": iso(row.revoked_at),
            "selected_calendars": _json_list(row.selected_calendars_json),
            "gmail_label_preferences": _json_object(
                row.gmail_label_preferences_json
            ),
            "default_send_behavior": row.default_send_behavior,
            "default_calendar": row.default_calendar,
            "timezone": row.timezone,
            "background_sync_enabled": bool(row.background_sync_enabled),
            "has_refresh_token": bool(row.refresh_token),
        }

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        data: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        params: Optional[Mapping[str, Any]] = None,
        json_body: Optional[Mapping[str, Any]] = None,
        accept_empty: bool = False,
    ) -> dict[str, Any]:
        async def invoke(client):
            return await client.request(
                method,
                url,
                data=dict(data or {}),
                headers=dict(headers or {}),
                params=dict(params or {}),
                json=dict(json_body) if json_body is not None else None,
                timeout=15.0,
            )

        try:
            if self._http_client is None:
                import httpx

                async with httpx.AsyncClient(
                    follow_redirects=False,
                    trust_env=False,
                ) as client:
                    response = await invoke(client)
            else:
                response = await invoke(self._http_client)
            status_code = int(getattr(response, "status_code", 0) or 0)
            if status_code >= 400:
                raise GoogleProviderError(
                    "Google rejected the requested API operation.",
                    status_code=status_code,
                )
            response.raise_for_status()
            if accept_empty and not getattr(response, "content", b""):
                return {}
            payload = response.json()
            if not isinstance(payload, dict):
                raise GoogleProviderError("Google returned an invalid response.")
            return payload
        except GoogleProviderError:
            raise
        except Exception as exc:
            # Do not include response bodies: OAuth errors can contain account
            # hints and no request credential should ever enter logs/API text.
            raise GoogleProviderError(
                "Google could not complete the requested OAuth operation."
            ) from exc


_service: Optional[GoogleConnectionService] = None


def get_google_connection_service() -> GoogleConnectionService:
    global _service
    if _service is None:
        _service = GoogleConnectionService()
    return _service
