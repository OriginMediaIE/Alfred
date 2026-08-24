"""Owner-scoped Google connection-management API."""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from src.auth_helpers import require_user
from src.google_connection import (
    GOOGLE_CALLBACK_PATH,
    GoogleConfigurationError,
    GoogleConnectionError,
    GoogleConnectionNotFound,
    GoogleOAuthStateError,
    GoogleProviderError,
    get_google_connection_service,
)


class GoogleClientConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(min_length=3, max_length=512)
    client_secret: SecretStr
    redirect_uri: str = Field(min_length=10, max_length=2048)


class GoogleAuthorizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capabilities: list[str] = Field(min_length=1, max_length=8)
    login_hint: Optional[str] = Field(default=None, max_length=320)


class GooglePreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_calendars: Optional[list[str]] = Field(default=None, max_length=100)
    gmail_label_preferences: Optional[dict[str, Any]] = None
    default_send_behavior: Optional[str] = None
    default_calendar: Optional[str] = Field(default=None, max_length=1024)
    timezone: Optional[str] = Field(default=None, max_length=128)
    background_sync_enabled: Optional[bool] = None


class GoogleDisconnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revoke_provider: bool = True


def _local_callback(request: Request) -> Optional[str]:
    """Return a safe localhost fallback without trusting a remote Host header."""

    request_host = (request.url.hostname or "").lower()
    client = getattr(request, "client", None)
    peer = ((client.host if client else "") or "").lower()
    loopback_names = {"localhost", "127.0.0.1", "::1"}
    if request_host not in loopback_names or peer not in loopback_names:
        return None
    port = request.url.port
    authority = "localhost" if port in (None, 80) else f"localhost:{port}"
    return f"http://{authority}{GOOGLE_CALLBACK_PATH}"


def _raise_google_error(exc: GoogleConnectionError) -> None:
    if isinstance(exc, GoogleConnectionNotFound):
        status = 404
    elif isinstance(exc, GoogleOAuthStateError):
        status = 400
    elif isinstance(exc, GoogleConfigurationError):
        status = 400
    elif isinstance(exc, GoogleProviderError):
        status = 502
    else:
        status = 500
    raise HTTPException(
        status_code=status,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


def setup_google_routes() -> APIRouter:
    router = APIRouter(prefix="/api/integrations/google", tags=["google"])

    @router.get("/client")
    async def get_client_configuration(
        request: Request,
        owner: str = Depends(require_user),
    ):
        service = get_google_connection_service()
        return service.get_client_status(
            owner,
            fallback_redirect_uri=_local_callback(request),
        )

    @router.put("/client")
    async def save_client_configuration(
        payload: GoogleClientConfigUpdate,
        owner: str = Depends(require_user),
    ):
        try:
            return get_google_connection_service().save_client_settings(
                owner,
                client_id=payload.client_id,
                client_secret=payload.client_secret.get_secret_value(),
                redirect_uri=payload.redirect_uri,
            )
        except GoogleConnectionError as exc:
            _raise_google_error(exc)

    @router.delete("/client")
    async def delete_client_configuration(
        owner: str = Depends(require_user),
    ):
        try:
            removed = get_google_connection_service().delete_client_settings(owner)
            return {"removed": removed}
        except GoogleConnectionError as exc:
            _raise_google_error(exc)

    @router.post("/oauth/authorize")
    async def begin_google_authorization(
        payload: GoogleAuthorizeRequest,
        request: Request,
        owner: str = Depends(require_user),
    ):
        try:
            return get_google_connection_service().begin_authorization(
                owner,
                payload.capabilities,
                fallback_redirect_uri=_local_callback(request),
                login_hint=payload.login_hint,
            )
        except GoogleConnectionError as exc:
            _raise_google_error(exc)

    @router.get("/oauth/callback")
    async def complete_google_authorization(
        request: Request,
        code: Optional[str] = Query(default=None, max_length=8192),
        state: Optional[str] = Query(default=None, max_length=512),
        error: Optional[str] = Query(default=None, max_length=256),
        owner: str = Depends(require_user),
    ):
        service = get_google_connection_service()
        if error:
            try:
                service.reject_authorization(owner, state or "")
                error_code = "access_denied"
            except GoogleConnectionError:
                error_code = "invalid_state"
            query = urlencode({"google_oauth": "error", "code": error_code})
            return RedirectResponse(f"/?section=integrations&{query}", status_code=303)
        if not code or not state:
            query = urlencode({"google_oauth": "error", "code": "missing_callback_data"})
            return RedirectResponse(f"/?section=integrations&{query}", status_code=303)
        try:
            connection = await service.complete_authorization(
                owner,
                state=state,
                code=code,
            )
        except GoogleConnectionError as exc:
            query = urlencode({"google_oauth": "error", "code": exc.code})
            return RedirectResponse(f"/?section=integrations&{query}", status_code=303)
        query = urlencode(
            {
                "google_oauth": "success",
                "connection": connection["id"],
            }
        )
        return RedirectResponse(f"/?section=integrations&{query}", status_code=303)

    @router.get("/connections")
    async def list_google_connections(owner: str = Depends(require_user)):
        return {
            "connections": get_google_connection_service().list_connections(owner)
        }

    @router.get("/connections/{connection_id}")
    async def get_google_connection(
        connection_id: str,
        owner: str = Depends(require_user),
    ):
        try:
            return get_google_connection_service().get_connection(owner, connection_id)
        except GoogleConnectionError as exc:
            _raise_google_error(exc)

    @router.patch("/connections/{connection_id}")
    async def update_google_connection_preferences(
        connection_id: str,
        payload: GooglePreferencesUpdate,
        owner: str = Depends(require_user),
    ):
        changes = payload.model_dump(exclude_unset=True)
        try:
            return get_google_connection_service().update_preferences(
                owner, connection_id, changes
            )
        except GoogleConnectionError as exc:
            _raise_google_error(exc)

    @router.post("/connections/{connection_id}/refresh")
    async def refresh_google_connection(
        connection_id: str,
        owner: str = Depends(require_user),
    ):
        try:
            return await get_google_connection_service().refresh(owner, connection_id)
        except GoogleConnectionError as exc:
            _raise_google_error(exc)

    @router.post("/connections/{connection_id}/check")
    async def check_google_connection(
        connection_id: str,
        owner: str = Depends(require_user),
    ):
        try:
            return await get_google_connection_service().check_connection(
                owner, connection_id
            )
        except GoogleConnectionError as exc:
            _raise_google_error(exc)

    @router.post("/connections/{connection_id}/disconnect")
    async def disconnect_google_connection(
        connection_id: str,
        payload: GoogleDisconnectRequest,
        owner: str = Depends(require_user),
    ):
        try:
            return await get_google_connection_service().disconnect(
                owner,
                connection_id,
                revoke_provider=payload.revoke_provider,
            )
        except GoogleConnectionError as exc:
            _raise_google_error(exc)

    return router
