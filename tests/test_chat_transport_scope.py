"""Bearer tokens cannot enter chat without the chat transport scope."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from routes.chat_routes import _require_chat_transport_scope


def _request(*, token: bool, scopes=(), owner="alice"):
    return SimpleNamespace(
        state=SimpleNamespace(
            api_token=token,
            api_token_scopes=list(scopes),
            api_token_owner=owner,
        )
    )


def test_browser_session_does_not_need_bearer_scope() -> None:
    _require_chat_transport_scope(_request(token=False))


def test_chat_scoped_token_is_allowed() -> None:
    _require_chat_transport_scope(
        _request(token=True, scopes={"chat", "email:read"})
    )


@pytest.mark.parametrize("scopes", ((), {"email:read"}, {"cookbook:read"}))
def test_non_chat_token_is_rejected_before_agent_transport(scopes) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _require_chat_transport_scope(_request(token=True, scopes=scopes))

    assert exc_info.value.status_code == 403
    assert "chat" in str(exc_info.value.detail)


def test_ownerless_chat_token_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _require_chat_transport_scope(
            _request(token=True, scopes={"chat"}, owner=None)
        )

    assert exc_info.value.status_code == 403
    assert "owner" in str(exc_info.value.detail).lower()
