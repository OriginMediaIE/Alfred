"""Normalized Gmail provider adapter and read-back verification tests."""

from __future__ import annotations

import base64
from email import message_from_bytes
from email.policy import default

import pytest

from services.google_gmail import (
    GMAIL_COMPOSE,
    GMAIL_MODIFY,
    GMAIL_READONLY,
    GMAIL_SEND,
    GmailValidationError,
    GoogleGmailService,
    normalize_message,
)
from src.google_connection import GoogleConfigurationError, GoogleProviderError


def _websafe(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _provider_message(
    *,
    message_id="m-1",
    thread_id="t-1",
    subject="Quarterly plan",
    to="bob@example.com",
    sender="Alice <alice@example.com>",
    labels=("SENT",),
    body="Hello Bob",
):
    return {
        "id": message_id,
        "threadId": thread_id,
        "historyId": "42",
        "internalDate": "1784385600000",
        "labelIds": list(labels),
        "snippet": body[:20],
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "To", "value": to},
                {"name": "Message-ID", "value": f"<{message_id}@mail.test>"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _websafe(body.encode()), "size": len(body)},
                },
                {
                    "mimeType": "application/pdf",
                    "filename": "plan.pdf",
                    "body": {"attachmentId": "a-1", "size": 2048},
                },
            ],
        },
    }


class _Connections:
    def __init__(self, scopes=None):
        self.scopes = list(
            scopes or (GMAIL_READONLY, GMAIL_SEND, GMAIL_COMPOSE, GMAIL_MODIFY)
        )
        self.responses = []
        self.calls = []

    def get_connection(self, owner, connection_id):
        assert owner == "alice"
        assert connection_id == "google-1"
        return {
            "granted_scopes": self.scopes,
            "email": "alice@example.com",
        }

    async def authorized_request_json(self, owner, connection_id, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError(f"Unexpected Gmail request: {kwargs}")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_normalize_message_extracts_headers_body_and_attachment_metadata():
    normalized = normalize_message(_provider_message())

    assert normalized["id"] == "m-1"
    assert normalized["thread_id"] == "t-1"
    assert normalized["subject"] == "Quarterly plan"
    assert normalized["body_text"] == "Hello Bob"
    assert normalized["attachments"] == [
        {
            "attachment_id": "a-1",
            "filename": "plan.pdf",
            "mime_type": "application/pdf",
            "size": 2048,
        }
    ]


@pytest.mark.asyncio
async def test_search_messages_uses_gmail_query_and_normalizes_metadata():
    connections = _Connections()
    connections.responses.extend(
        [
            {
                "messages": [{"id": "m-1", "threadId": "t-1"}],
                "resultSizeEstimate": 1,
            },
            _provider_message(),
        ]
    )
    gmail = GoogleGmailService(connections)

    result = await gmail.search_messages(
        "alice",
        "google-1",
        query="is:unread newer_than:7d",
        label_ids=("INBOX",),
        max_results=10,
    )

    assert result["messages"][0]["id"] == "m-1"
    assert connections.calls[0]["params"] == {
        "q": "is:unread newer_than:7d",
        "maxResults": 10,
        "labelIds": ["INBOX"],
    }
    assert connections.calls[1]["params"] == {"format": "metadata"}


@pytest.mark.asyncio
async def test_send_constructs_safe_mime_and_reads_sent_message_back():
    connections = _Connections()
    connections.responses.extend(
        [
            {"id": "m-1", "threadId": "t-1"},
            _provider_message(),
        ]
    )
    gmail = GoogleGmailService(connections)

    result = await gmail.send_message(
        "alice",
        "google-1",
        to=["Bob <bob@example.com>"],
        cc="carol@example.com",
        subject="Quarterly plan",
        body="Hello Bob",
        body_html="<p>Hello Bob</p>",
    )

    send_call = connections.calls[0]
    assert send_call["url"].endswith("/messages/send")
    encoded = send_call["json_body"]["raw"]
    raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    message = message_from_bytes(raw, policy=default)
    assert message["To"] == "Bob <bob@example.com>"
    assert message["Cc"] == "carol@example.com"
    assert message["Subject"] == "Quarterly plan"
    assert result["verification"] == {
        "status": "verified",
        "provider": "gmail",
        "read_back_id": "m-1",
    }
    assert connections.calls[1]["url"].endswith("/messages/m-1")


@pytest.mark.asyncio
async def test_draft_create_and_update_are_read_back_and_verified():
    connections = _Connections()
    draft = {"id": "d-1", "message": _provider_message(labels=("DRAFT",))}
    connections.responses.extend([{"id": "d-1"}, draft, {"id": "d-1"}, draft])
    gmail = GoogleGmailService(connections)

    created = await gmail.create_draft(
        "alice",
        "google-1",
        to="bob@example.com",
        subject="Quarterly plan",
        body="First version",
    )
    updated = await gmail.update_draft(
        "alice",
        "google-1",
        "d-1",
        to="bob@example.com",
        subject="Quarterly plan",
        body="Second version",
    )

    assert created["verification"]["status"] == "verified"
    assert updated["verification"]["status"] == "verified"
    assert connections.calls[1]["method"] == "GET"
    assert connections.calls[3]["method"] == "GET"


@pytest.mark.asyncio
async def test_send_draft_reads_draft_then_verifies_sent_message():
    connections = _Connections()
    connections.responses.extend(
        [
            {"id": "d-1", "message": _provider_message(labels=("DRAFT",))},
            {"id": "m-1", "threadId": "t-1"},
            _provider_message(),
        ]
    )
    gmail = GoogleGmailService(connections)

    result = await gmail.send_draft("alice", "google-1", "d-1")

    assert result["verification"]["status"] == "verified"
    assert [call["method"] for call in connections.calls] == ["GET", "POST", "GET"]


@pytest.mark.asyncio
async def test_delete_draft_verifies_not_found():
    connections = _Connections()
    connections.responses.extend(
        [{}, GoogleProviderError("not found", status_code=404)]
    )
    gmail = GoogleGmailService(connections)

    result = await gmail.delete_draft("alice", "google-1", "d-1")

    assert result["verification"]["status"] == "verified"
    assert result["verification"]["read_back"] == "not_found"


@pytest.mark.asyncio
async def test_send_fails_closed_when_read_back_does_not_match():
    connections = _Connections()
    connections.responses.extend(
        [
            {"id": "m-1", "threadId": "t-1"},
            _provider_message(subject="Different subject", labels=("INBOX",)),
        ]
    )
    gmail = GoogleGmailService(connections)

    result = await gmail.send_message(
        "alice",
        "google-1",
        to="bob@example.com",
        subject="Expected subject",
        body="Body",
    )

    assert result["verification"]["status"] == "mismatch"


@pytest.mark.asyncio
async def test_reply_all_excludes_connected_account_and_preserves_threading():
    connections = _Connections()
    original = _provider_message(
        sender="Bob <bob@example.com>",
        to="Alice <alice@example.com>, Carol <carol@example.com>",
        subject="Status",
        labels=("INBOX",),
    )
    original["payload"]["headers"].extend(
        [
            {"name": "Cc", "value": "Dan <dan@example.com>"},
            {"name": "References", "value": "<older@mail.test>"},
        ]
    )
    connections.responses.extend(
        [
            original,
            {"id": "m-2", "threadId": "t-1"},
            _provider_message(
                message_id="m-2",
                subject="Re: Status",
                to="bob@example.com",
            ),
        ]
    )
    gmail = GoogleGmailService(connections)

    result = await gmail.reply(
        "alice",
        "google-1",
        "m-1",
        body="Looks good.",
        reply_all=True,
    )

    send_body = connections.calls[1]["json_body"]
    assert send_body["threadId"] == "t-1"
    raw = base64.urlsafe_b64decode(
        send_body["raw"] + "=" * (-len(send_body["raw"]) % 4)
    )
    message = message_from_bytes(raw, policy=default)
    recipients = f"{message['To']},{message['Cc']}".lower()
    assert "bob@example.com" in recipients
    assert "carol@example.com" in recipients
    assert "dan@example.com" in recipients
    assert "alice@example.com" not in recipients
    assert message["In-Reply-To"] == "<m-1@mail.test>"
    assert result["verification"]["status"] == "verified"


@pytest.mark.asyncio
async def test_label_mutation_verifies_provider_result():
    connections = _Connections(scopes=(GMAIL_MODIFY,))
    connections.responses.append(
        _provider_message(labels=("IMPORTANT", "STARRED"))
    )
    gmail = GoogleGmailService(connections)

    result = await gmail.modify_labels(
        "alice",
        "google-1",
        "m-1",
        add=("STARRED",),
        remove=("INBOX",),
    )

    assert result["verification"]["status"] == "verified"
    assert connections.calls[0]["json_body"] == {
        "addLabelIds": ["STARRED"],
        "removeLabelIds": ["INBOX"],
    }


@pytest.mark.asyncio
async def test_scope_and_header_validation_fail_before_provider_call():
    connections = _Connections(scopes=(GMAIL_READONLY,))
    gmail = GoogleGmailService(connections)

    with pytest.raises(GoogleConfigurationError):
        await gmail.send_message(
            "alice",
            "google-1",
            to="bob@example.com",
            subject="No scope",
            body="Body",
        )
    with pytest.raises(GmailValidationError):
        await gmail.send_message(
            "alice",
            "google-1",
            to="bob@example.com\nBcc: attacker@example.com",
            subject="Header injection",
            body="Body",
        )
    assert connections.calls == []


@pytest.mark.asyncio
async def test_attachment_declared_size_must_match_decoded_bytes():
    connections = _Connections()
    connections.responses.append(
        {"data": _websafe(b"abc"), "size": 99}
    )
    gmail = GoogleGmailService(connections)

    with pytest.raises(GmailValidationError):
        await gmail.get_attachment("alice", "google-1", "m-1", "a-1")
