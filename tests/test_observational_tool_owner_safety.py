"""Owner-bound safety regressions for observational agent tools."""

import asyncio


def test_tool_owner_check_allows_only_explicit_auth_disabled(monkeypatch):
    from src.tools._common import _configured_auth_requires_owner

    monkeypatch.setenv("AUTH_ENABLED", "true")

    assert _configured_auth_requires_owner(None) is True
    assert _configured_auth_requires_owner("alice") is False

    # Explicit single-user mode is the documented ownerless exception.
    monkeypatch.setenv("AUTH_ENABLED", "false")
    assert _configured_auth_requires_owner(None) is False


def test_search_chats_requires_owner_when_auth_is_configured(monkeypatch):
    from src import session_search
    from src.tools import search

    monkeypatch.setattr(
        search,
        "_configured_auth_requires_owner",
        lambda owner: owner is None,
    )

    def forbidden_search(*args, **kwargs):
        raise AssertionError("session search must not run without an owner")

    monkeypatch.setattr(session_search, "search_session_messages", forbidden_search)

    result = asyncio.run(search.do_search_chats("private project", owner=None))

    assert result == {
        "error": "Authenticated owner is required to search chat history",
        "exit_code": 1,
    }


def test_search_chats_excludes_legacy_and_other_owner_sessions(monkeypatch):
    from src import session_search
    from src.tools import search

    captured = {}
    monkeypatch.setattr(search, "_configured_auth_requires_owner", lambda owner: False)

    def fake_search(query, **kwargs):
        captured["query"] = query
        captured.update(kwargs)
        return []

    monkeypatch.setattr(session_search, "search_session_messages", fake_search)

    result = asyncio.run(
        search.do_search_chats("private project", limit=7, owner="alice")
    )

    assert result == {"results": 'No chats found matching "private project".'}
    assert captured == {
        "query": "private project",
        "limit": 7,
        "owner": "alice",
        "restrict_owner": True,
        "include_legacy_owner": False,
    }


def test_resolve_contact_requires_owner_before_any_lookup(monkeypatch):
    import httpx

    from src.tools import contacts

    monkeypatch.setattr(
        contacts,
        "_configured_auth_requires_owner",
        lambda owner: owner is None,
    )

    class ForbiddenClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("loopback lookup must not run without an owner")

    monkeypatch.setattr(httpx, "AsyncClient", ForbiddenClient)

    result = asyncio.run(
        contacts.do_resolve_contact('{"name": "Ada"}', owner=None)
    )

    assert result == {
        "error": "Authenticated owner is required to resolve contacts",
        "exit_code": 1,
    }


def test_resolve_contact_uses_owner_authenticated_observational_gets(monkeypatch):
    import httpx

    from src.tools import contacts

    calls = []
    expected_headers = {
        "X-Test-Internal-Token": "secret",
        "X-Odysseus-Owner": "alice",
    }
    monkeypatch.setattr(contacts, "_configured_auth_requires_owner", lambda owner: False)
    monkeypatch.setattr(contacts, "_INTERNAL_BASE", "http://internal.test")
    monkeypatch.setattr(
        contacts,
        "_internal_headers",
        lambda owner: {**expected_headers, "X-Odysseus-Owner": owner},
    )

    class FakeResponse:
        def __init__(self, payload):
            self.status_code = 200
            self._payload = payload

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *, timeout):
            assert timeout == 30

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, *, params, headers):
            calls.append({"url": url, "params": params, "headers": dict(headers)})
            if url.endswith("/api/contacts/search"):
                return FakeResponse(
                    {
                        "results": [
                            {
                                "name": "Ada Lovelace",
                                "emails": ["ADA@example.test"],
                                "phones": [],
                            }
                        ]
                    }
                )
            if url.endswith("/api/email/resolve-contact"):
                return FakeResponse(
                    {
                        "contacts": [
                            {"name": "Ada Byron", "email": "byron@example.test"}
                        ]
                    }
                )
            raise AssertionError(f"unexpected lookup URL: {url}")

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    result = asyncio.run(
        contacts.do_resolve_contact('{"name": "Ada"}', owner="alice")
    )

    assert result["exit_code"] == 0
    assert "Ada Lovelace <ada@example.test> (contacts)" in result["output"]
    assert "Ada Byron <byron@example.test> (email history)" in result["output"]
    assert calls == [
        {
            "url": "http://internal.test/api/contacts/search",
            "params": {"q": "Ada"},
            "headers": expected_headers,
        },
        {
            "url": "http://internal.test/api/email/resolve-contact",
            "params": {"name": "Ada"},
            "headers": expected_headers,
        },
    ]
