"""Gmail API adapter with normalized, token-free OM Automate records."""

from __future__ import annotations

import base64
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import getaddresses
import html
import re
from typing import Any, Iterable, Mapping, Optional, Sequence
from urllib.parse import quote

from src.google_connection import (
    GoogleConfigurationError,
    GoogleConnectionService,
    GoogleProviderError,
    get_google_connection_service,
)


GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_COMPOSE = "https://www.googleapis.com/auth/gmail.compose"
GMAIL_SEND = "https://www.googleapis.com/auth/gmail.send"
GMAIL_MODIFY = "https://www.googleapis.com/auth/gmail.modify"
GMAIL_LABELS = "https://www.googleapis.com/auth/gmail.labels"

_MESSAGE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


class GmailValidationError(ValueError):
    """A caller supplied an invalid Gmail command."""


def _provider_id(value: object, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not _MESSAGE_ID_RE.fullmatch(normalized):
        raise GmailValidationError(f"{field} is invalid.")
    return normalized


def _decode_websafe(value: object) -> bytes:
    raw = str(value or "")
    if not raw:
        return b""
    padding = "=" * (-len(raw) % 4)
    try:
        return base64.urlsafe_b64decode((raw + padding).encode("ascii"))
    except Exception as exc:
        raise GmailValidationError("Gmail returned invalid base64 content.") from exc


def _encode_websafe(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _headers(payload: Mapping[str, Any]) -> dict[str, str]:
    output: dict[str, str] = {}
    for item in payload.get("headers") or []:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "").strip().lower()
        value = str(item.get("value") or "")
        if name:
            output[name] = value
    return output


def _walk_parts(part: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    yield part
    for child in part.get("parts") or []:
        if isinstance(child, Mapping):
            yield from _walk_parts(child)


def _message_body(payload: Mapping[str, Any]) -> tuple[str, str]:
    plain = ""
    rich = ""
    for part in _walk_parts(payload):
        mime = str(part.get("mimeType") or "").lower()
        data = (part.get("body") or {}).get("data") if isinstance(part.get("body"), Mapping) else None
        if not data:
            continue
        decoded = _decode_websafe(data).decode("utf-8", errors="replace")
        if mime == "text/plain" and not plain:
            plain = decoded
        elif mime == "text/html" and not rich:
            rich = decoded
    if not plain and rich:
        plain = re.sub(r"<[^>]+>", " ", rich)
        plain = html.unescape(re.sub(r"\s+", " ", plain)).strip()
    return plain, rich


def normalize_message(message: Mapping[str, Any]) -> dict[str, Any]:
    payload = message.get("payload") or {}
    if not isinstance(payload, Mapping):
        payload = {}
    headers = _headers(payload)
    plain, rich = _message_body(payload)
    attachments = []
    for part in _walk_parts(payload):
        body = part.get("body") or {}
        if not isinstance(body, Mapping):
            body = {}
        filename = str(part.get("filename") or "")
        attachment_id = str(body.get("attachmentId") or "")
        if filename or attachment_id:
            attachments.append(
                {
                    "attachment_id": attachment_id,
                    "filename": filename,
                    "mime_type": str(part.get("mimeType") or "application/octet-stream"),
                    "size": int(body.get("size") or 0),
                }
            )
    return {
        "id": str(message.get("id") or ""),
        "thread_id": str(message.get("threadId") or ""),
        "history_id": str(message.get("historyId") or ""),
        "internal_date": str(message.get("internalDate") or ""),
        "label_ids": [str(item) for item in message.get("labelIds") or []],
        "snippet": str(message.get("snippet") or ""),
        "subject": headers.get("subject", ""),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "cc": headers.get("cc", ""),
        "bcc": headers.get("bcc", ""),
        "date": headers.get("date", ""),
        "message_id": headers.get("message-id", ""),
        "in_reply_to": headers.get("in-reply-to", ""),
        "references": headers.get("references", ""),
        "body_text": plain,
        "body_html": rich,
        "attachments": attachments,
    }


def _address_header(value: object, *, field: str, required: bool = False) -> str:
    if isinstance(value, str):
        raw = value
    elif isinstance(value, Sequence):
        raw = ", ".join(str(item) for item in value)
    elif value is None:
        raw = ""
    else:
        raise GmailValidationError(f"{field} must be an address or address list.")
    if "\r" in raw or "\n" in raw:
        raise GmailValidationError(f"{field} contains a header newline.")
    parsed = getaddresses([raw]) if raw else []
    if required and not parsed:
        raise GmailValidationError(f"{field} is required.")
    for _name, address in parsed:
        if not address or "@" not in address or len(address) > 320:
            raise GmailValidationError(f"{field} contains an invalid email address.")
    return raw.strip()


def _build_message(
    *,
    to: object,
    subject: str,
    body: str,
    body_html: Optional[str] = None,
    cc: object = None,
    bcc: object = None,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
) -> EmailMessage:
    subject = str(subject or "")
    if not subject or len(subject) > 998 or "\r" in subject or "\n" in subject:
        raise GmailValidationError("subject is required and cannot contain newlines.")
    body = str(body if body is not None else "")
    if len(body.encode("utf-8")) > 10 * 1024 * 1024:
        raise GmailValidationError("email body exceeds 10 MiB.")
    message = EmailMessage()
    message["To"] = _address_header(to, field="to", required=True)
    cc_value = _address_header(cc, field="cc")
    bcc_value = _address_header(bcc, field="bcc")
    if cc_value:
        message["Cc"] = cc_value
    if bcc_value:
        message["Bcc"] = bcc_value
    message["Subject"] = subject
    if in_reply_to:
        if "\r" in in_reply_to or "\n" in in_reply_to:
            raise GmailValidationError("in_reply_to contains a header newline.")
        message["In-Reply-To"] = str(in_reply_to)[:998]
    if references:
        if "\r" in references or "\n" in references:
            raise GmailValidationError("references contains a header newline.")
        message["References"] = str(references)[:4096]
    message.set_content(body)
    if body_html:
        message.add_alternative(str(body_html), subtype="html")
    return message


class GoogleGmailService:
    def __init__(
        self,
        connection_service: Optional[GoogleConnectionService] = None,
    ) -> None:
        self._connections = connection_service or get_google_connection_service()

    def _select_scope(
        self,
        owner: Optional[str],
        connection_id: str,
        candidates: Iterable[str],
    ) -> str:
        granted = set(
            self._connections.get_connection(owner, connection_id)["granted_scopes"]
        )
        for scope in candidates:
            if scope in granted:
                return scope
        raise GoogleConfigurationError(
            "Google connection does not grant the required Gmail capability."
        )

    async def _api(
        self,
        owner: Optional[str],
        connection_id: str,
        *,
        method: str,
        path: str,
        scopes: Iterable[str],
        params: Optional[Mapping[str, Any]] = None,
        body: Optional[Mapping[str, Any]] = None,
        accept_empty: bool = False,
    ) -> dict[str, Any]:
        selected = self._select_scope(owner, connection_id, scopes)
        return await self._connections.authorized_request_json(
            owner,
            connection_id,
            method=method,
            url=f"{GMAIL_API}{path}",
            required_scopes={selected},
            params=params,
            json_body=body,
            accept_empty=accept_empty,
        )

    async def list_labels(self, owner: Optional[str], connection_id: str) -> list[dict]:
        result = await self._api(
            owner,
            connection_id,
            method="GET",
            path="/labels",
            scopes=(GMAIL_READONLY, GMAIL_MODIFY, GMAIL_LABELS),
        )
        return [dict(item) for item in result.get("labels") or [] if isinstance(item, Mapping)]

    async def search_messages(
        self,
        owner: Optional[str],
        connection_id: str,
        *,
        query: str = "",
        label_ids: Sequence[str] = (),
        max_results: int = 20,
        page_token: Optional[str] = None,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        if not 1 <= int(max_results) <= 100:
            raise GmailValidationError("max_results must be between 1 and 100.")
        if len(str(query).encode("utf-8")) > 4096:
            raise GmailValidationError("Gmail query is too long.")
        params: dict[str, Any] = {
            "q": str(query),
            "maxResults": int(max_results),
        }
        if label_ids:
            params["labelIds"] = [_provider_id(item, field="label_id") for item in label_ids]
        if page_token:
            params["pageToken"] = str(page_token)[:2048]
        result = await self._api(
            owner,
            connection_id,
            method="GET",
            path="/messages",
            scopes=(GMAIL_READONLY, GMAIL_MODIFY),
            params=params,
        )
        refs = [dict(item) for item in result.get("messages") or [] if isinstance(item, Mapping)]
        messages: list[dict[str, Any]] = []
        if include_metadata:
            for ref in refs:
                messages.append(
                    await self.read_message(
                        owner,
                        connection_id,
                        str(ref.get("id") or ""),
                        format="metadata",
                    )
                )
        else:
            messages = refs
        return {
            "messages": messages,
            "next_page_token": result.get("nextPageToken"),
            "result_size_estimate": int(result.get("resultSizeEstimate") or len(messages)),
        }

    async def read_message(
        self,
        owner: Optional[str],
        connection_id: str,
        message_id: str,
        *,
        format: str = "full",
    ) -> dict[str, Any]:
        message_id = _provider_id(message_id, field="message_id")
        if format not in {"full", "metadata", "minimal", "raw"}:
            raise GmailValidationError("Unsupported Gmail message format.")
        result = await self._api(
            owner,
            connection_id,
            method="GET",
            path=f"/messages/{quote(message_id, safe='')}",
            scopes=(GMAIL_READONLY, GMAIL_MODIFY),
            params={"format": format},
        )
        return normalize_message(result)

    async def read_thread(
        self,
        owner: Optional[str],
        connection_id: str,
        thread_id: str,
    ) -> dict[str, Any]:
        thread_id = _provider_id(thread_id, field="thread_id")
        result = await self._api(
            owner,
            connection_id,
            method="GET",
            path=f"/threads/{quote(thread_id, safe='')}",
            scopes=(GMAIL_READONLY, GMAIL_MODIFY),
            params={"format": "full"},
        )
        messages = [
            normalize_message(item)
            for item in result.get("messages") or []
            if isinstance(item, Mapping)
        ]
        return {
            "id": str(result.get("id") or thread_id),
            "history_id": str(result.get("historyId") or ""),
            "messages": messages,
        }

    async def get_attachment(
        self,
        owner: Optional[str],
        connection_id: str,
        message_id: str,
        attachment_id: str,
    ) -> bytes:
        message_id = _provider_id(message_id, field="message_id")
        attachment_id = _provider_id(attachment_id, field="attachment_id")
        result = await self._api(
            owner,
            connection_id,
            method="GET",
            path=(
                f"/messages/{quote(message_id, safe='')}/attachments/"
                f"{quote(attachment_id, safe='')}"
            ),
            scopes=(GMAIL_READONLY, GMAIL_MODIFY),
        )
        data = _decode_websafe(result.get("data"))
        declared = int(result.get("size") or len(data))
        if declared != len(data) or len(data) > 25 * 1024 * 1024:
            raise GmailValidationError("Gmail attachment size is invalid.")
        return data

    async def create_draft(
        self,
        owner: Optional[str],
        connection_id: str,
        **command: Any,
    ) -> dict[str, Any]:
        message = _build_message(**command)
        result = await self._api(
            owner,
            connection_id,
            method="POST",
            path="/drafts",
            scopes=(GMAIL_COMPOSE, GMAIL_MODIFY),
            body={"message": {"raw": _encode_websafe(message.as_bytes(policy=SMTP))}},
        )
        draft_id = _provider_id(result.get("id"), field="draft_id")
        return await self._verify_draft(
            owner,
            connection_id,
            draft_id,
            expected_subject=str(command.get("subject") or ""),
            expected_to=_address_header(command.get("to"), field="to", required=True),
        )

    async def update_draft(
        self,
        owner: Optional[str],
        connection_id: str,
        draft_id: str,
        **command: Any,
    ) -> dict[str, Any]:
        draft_id = _provider_id(draft_id, field="draft_id")
        message = _build_message(**command)
        result = await self._api(
            owner,
            connection_id,
            method="PUT",
            path=f"/drafts/{quote(draft_id, safe='')}",
            scopes=(GMAIL_COMPOSE, GMAIL_MODIFY),
            body={"id": draft_id, "message": {"raw": _encode_websafe(message.as_bytes(policy=SMTP))}},
        )
        stored_id = _provider_id(result.get("id") or draft_id, field="draft_id")
        return await self._verify_draft(
            owner,
            connection_id,
            stored_id,
            expected_subject=str(command.get("subject") or ""),
            expected_to=_address_header(command.get("to"), field="to", required=True),
        )

    async def list_drafts(
        self,
        owner: Optional[str],
        connection_id: str,
        *,
        max_results: int = 20,
        page_token: Optional[str] = None,
    ) -> dict[str, Any]:
        if not 1 <= int(max_results) <= 100:
            raise GmailValidationError("max_results must be between 1 and 100.")
        params: dict[str, Any] = {"maxResults": int(max_results)}
        if page_token:
            params["pageToken"] = str(page_token)[:2048]
        result = await self._api(
            owner,
            connection_id,
            method="GET",
            path="/drafts",
            scopes=(GMAIL_COMPOSE, GMAIL_MODIFY),
            params=params,
        )
        return {
            "drafts": [
                {
                    "draft_id": str(item.get("id") or ""),
                    "message_id": str((item.get("message") or {}).get("id") or ""),
                    "thread_id": str((item.get("message") or {}).get("threadId") or ""),
                }
                for item in result.get("drafts") or []
                if isinstance(item, Mapping)
            ],
            "next_page_token": result.get("nextPageToken"),
            "result_size_estimate": int(result.get("resultSizeEstimate") or 0),
        }

    async def get_draft(
        self,
        owner: Optional[str],
        connection_id: str,
        draft_id: str,
    ) -> dict[str, Any]:
        draft_id = _provider_id(draft_id, field="draft_id")
        result = await self._api(
            owner,
            connection_id,
            method="GET",
            path=f"/drafts/{quote(draft_id, safe='')}",
            scopes=(GMAIL_COMPOSE, GMAIL_MODIFY),
            params={"format": "full"},
        )
        return {
            "draft_id": str(result.get("id") or draft_id),
            "message": normalize_message(result.get("message") or {}),
        }

    async def delete_draft(
        self,
        owner: Optional[str],
        connection_id: str,
        draft_id: str,
    ) -> dict[str, Any]:
        draft_id = _provider_id(draft_id, field="draft_id")
        await self._api(
            owner,
            connection_id,
            method="DELETE",
            path=f"/drafts/{quote(draft_id, safe='')}",
            scopes=(GMAIL_COMPOSE, GMAIL_MODIFY),
            accept_empty=True,
        )
        try:
            await self.get_draft(owner, connection_id, draft_id)
        except GoogleProviderError as exc:
            if exc.status_code in {404, 410}:
                return {
                    "draft_id": draft_id,
                    "verification": {
                        "status": "verified",
                        "provider": "gmail",
                        "read_back": "not_found",
                    },
                }
            raise
        return {
            "draft_id": draft_id,
            "verification": {
                "status": "mismatch",
                "provider": "gmail",
                "read_back": "still_present",
            },
        }

    async def send_draft(
        self,
        owner: Optional[str],
        connection_id: str,
        draft_id: str,
    ) -> dict[str, Any]:
        draft_id = _provider_id(draft_id, field="draft_id")
        draft = await self.get_draft(owner, connection_id, draft_id)
        sent = await self._api(
            owner,
            connection_id,
            method="POST",
            path="/drafts/send",
            scopes=(GMAIL_COMPOSE, GMAIL_MODIFY),
            body={"id": draft_id},
        )
        return await self._verify_sent(
            owner,
            connection_id,
            sent,
            expected_subject=draft["message"]["subject"],
            expected_to=draft["message"]["to"],
        )

    async def send_message(
        self,
        owner: Optional[str],
        connection_id: str,
        *,
        thread_id: Optional[str] = None,
        **command: Any,
    ) -> dict[str, Any]:
        message = _build_message(**command)
        body: dict[str, Any] = {
            "raw": _encode_websafe(message.as_bytes(policy=SMTP))
        }
        if thread_id:
            body["threadId"] = _provider_id(thread_id, field="thread_id")
        sent = await self._api(
            owner,
            connection_id,
            method="POST",
            path="/messages/send",
            scopes=(GMAIL_SEND, GMAIL_COMPOSE, GMAIL_MODIFY),
            body=body,
        )
        return await self._verify_sent(
            owner,
            connection_id,
            sent,
            expected_subject=str(command.get("subject") or ""),
            expected_to=_address_header(command.get("to"), field="to", required=True),
        )

    async def reply(
        self,
        owner: Optional[str],
        connection_id: str,
        message_id: str,
        *,
        body: str,
        body_html: Optional[str] = None,
        reply_all: bool = False,
    ) -> dict[str, Any]:
        original = await self.read_message(owner, connection_id, message_id)
        reply_to = original["from"]
        recipients = [reply_to]
        cc = ""
        if reply_all:
            own_email = self._connections.get_connection(owner, connection_id)["email"].lower()
            candidates = getaddresses(
                [original.get("from", ""), original.get("to", ""), original.get("cc", "")]
            )
            unique = []
            for _name, address in candidates:
                lowered = address.lower()
                if address and lowered != own_email and lowered not in {item.lower() for item in unique}:
                    unique.append(address)
            recipients = unique[:1]
            cc = ", ".join(unique[1:])
        subject = str(original.get("subject") or "")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        references = " ".join(
            item
            for item in (original.get("references"), original.get("message_id"))
            if item
        )
        return await self.send_message(
            owner,
            connection_id,
            to=", ".join(recipients),
            cc=cc,
            subject=subject,
            body=body,
            body_html=body_html,
            in_reply_to=original.get("message_id") or None,
            references=references or None,
            thread_id=original.get("thread_id") or None,
        )

    async def forward(
        self,
        owner: Optional[str],
        connection_id: str,
        message_id: str,
        *,
        to: object,
        note: str = "",
    ) -> dict[str, Any]:
        original = await self.read_message(owner, connection_id, message_id)
        subject = str(original.get("subject") or "")
        if not subject.lower().startswith(("fwd:", "fw:")):
            subject = f"Fwd: {subject}"
        forwarded = (
            f"{str(note).strip()}\n\n" if str(note).strip() else ""
        ) + (
            "---------- Forwarded message ----------\n"
            f"From: {original.get('from', '')}\n"
            f"Date: {original.get('date', '')}\n"
            f"Subject: {original.get('subject', '')}\n"
            f"To: {original.get('to', '')}\n\n"
            f"{original.get('body_text', '')}"
        )
        return await self.send_message(
            owner,
            connection_id,
            to=to,
            subject=subject,
            body=forwarded,
        )

    async def modify_labels(
        self,
        owner: Optional[str],
        connection_id: str,
        message_id: str,
        *,
        add: Sequence[str] = (),
        remove: Sequence[str] = (),
    ) -> dict[str, Any]:
        message_id = _provider_id(message_id, field="message_id")
        add_ids = [_provider_id(item, field="label_id") for item in add]
        remove_ids = [_provider_id(item, field="label_id") for item in remove]
        if not add_ids and not remove_ids:
            raise GmailValidationError("At least one label change is required.")
        result = await self._api(
            owner,
            connection_id,
            method="POST",
            path=f"/messages/{quote(message_id, safe='')}/modify",
            scopes=(GMAIL_MODIFY,),
            body={"addLabelIds": add_ids, "removeLabelIds": remove_ids},
        )
        normalized = normalize_message(result)
        normalized["verification"] = {
            "status": "verified"
            if set(add_ids) <= set(normalized["label_ids"])
            and not set(remove_ids) & set(normalized["label_ids"])
            else "mismatch",
            "requested_add": add_ids,
            "requested_remove": remove_ids,
        }
        return normalized

    async def archive(self, owner, connection_id, message_id):
        return await self.modify_labels(
            owner, connection_id, message_id, remove=("INBOX",)
        )

    async def mark_read(self, owner, connection_id, message_id, *, read: bool):
        return await self.modify_labels(
            owner,
            connection_id,
            message_id,
            add=() if read else ("UNREAD",),
            remove=("UNREAD",) if read else (),
        )

    async def star(self, owner, connection_id, message_id, *, starred: bool):
        return await self.modify_labels(
            owner,
            connection_id,
            message_id,
            add=("STARRED",) if starred else (),
            remove=() if starred else ("STARRED",),
        )

    async def trash(self, owner, connection_id, message_id):
        message_id = _provider_id(message_id, field="message_id")
        result = await self._api(
            owner,
            connection_id,
            method="POST",
            path=f"/messages/{quote(message_id, safe='')}/trash",
            scopes=(GMAIL_MODIFY,),
            body={},
        )
        normalized = normalize_message(result)
        normalized["verification"] = {
            "status": "verified"
            if "TRASH" in normalized["label_ids"]
            else "mismatch"
        }
        return normalized

    async def _verify_sent(
        self,
        owner: Optional[str],
        connection_id: str,
        sent: Mapping[str, Any],
        *,
        expected_subject: Optional[str] = None,
        expected_to: Optional[str] = None,
    ) -> dict[str, Any]:
        message_id = _provider_id(sent.get("id"), field="sent_message_id")
        stored = await self.read_message(
            owner, connection_id, message_id, format="metadata"
        )
        matches = "SENT" in stored["label_ids"]
        if expected_subject is not None:
            matches = matches and stored["subject"] == expected_subject
        if expected_to is not None:
            expected_addresses = {
                address.lower() for _name, address in getaddresses([expected_to])
            }
            stored_addresses = {
                address.lower() for _name, address in getaddresses([stored["to"]])
            }
            matches = matches and expected_addresses <= stored_addresses
        return {
            "message": stored,
            "thread_id": str(sent.get("threadId") or stored.get("thread_id") or ""),
            "verification": {
                "status": "verified" if matches else "mismatch",
                "provider": "gmail",
                "read_back_id": message_id,
            },
        }

    async def _verify_draft(
        self,
        owner: Optional[str],
        connection_id: str,
        draft_id: str,
        *,
        expected_subject: str,
        expected_to: str,
    ) -> dict[str, Any]:
        stored = await self.get_draft(owner, connection_id, draft_id)
        expected_addresses = {
            address.lower() for _name, address in getaddresses([expected_to])
        }
        stored_addresses = {
            address.lower()
            for _name, address in getaddresses([stored["message"].get("to", "")])
        }
        matches = (
            stored["message"].get("subject") == expected_subject
            and expected_addresses <= stored_addresses
        )
        stored["verification"] = {
            "status": "verified" if matches else "mismatch",
            "provider": "gmail",
            "read_back_id": draft_id,
        }
        return stored


_gmail_service: Optional[GoogleGmailService] = None


def get_google_gmail_service() -> GoogleGmailService:
    global _gmail_service
    if _gmail_service is None:
        _gmail_service = GoogleGmailService()
    return _gmail_service
