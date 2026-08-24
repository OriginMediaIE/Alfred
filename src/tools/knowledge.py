"""Canonical agent adapters for grounded private knowledge."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from services.knowledge_service import KnowledgeError, KnowledgeNotFound, get_knowledge_service
from src.action_ledger import ActionLedgerError, get_action_ledger
from src.knowledge_tool_contract import DELETE_KNOWLEDGE_ACTIONS, MANAGE_KNOWLEDGE_ACTIONS, QUERY_KNOWLEDGE_ACTIONS
from src.tools._common import _configured_auth_requires_owner, _parse_tool_args


def _args(content: str) -> dict[str, Any]:
    value = _parse_tool_args(content)
    if not isinstance(value, dict): raise ValueError("Tool arguments must be an object")
    return value


def _error(exc: Exception) -> dict[str, Any]:
    return {"error": str(exc), "code": getattr(exc, "code", "invalid_arguments"), "exit_code": 1}


def _require_claim(owner, tool_name, approval_action_id, request_id):
    if not approval_action_id or not request_id: raise ValueError("Knowledge mutation requires an approved action-ledger claim")
    try: action = get_action_ledger().get_action(approval_action_id, owner)
    except ActionLedgerError as exc: raise ValueError("Knowledge approval evidence is unavailable") from exc
    raw = str(action.get("expires_at") or "").replace("Z", "+00:00")
    expires = datetime.fromisoformat(raw)
    if expires.tzinfo is None: expires = expires.replace(tzinfo=timezone.utc)
    if action.get("tool_name") != tool_name or action.get("status") != "executing" or not action.get("approval_consumed_at") or action.get("request_id") != request_id or expires <= datetime.now(timezone.utc):
        raise ValueError("Knowledge approval evidence is invalid, expired, or mismatched")


def _verify(record_id, expected, reader):
    try:
        actual = reader(); matches = all(actual.get(key) == value for key, value in expected.items())
    except Exception: matches = False
    return {"status": "verified" if matches else "mismatch", "provider": "local_knowledge", "read_back_id": record_id}


async def do_query_knowledge(content: str, owner: Optional[str] = None):
    if _configured_auth_requires_owner(owner): return {"error": "Authenticated owner is required", "code": "owner_required", "exit_code": 1}
    try:
        a = _args(content); action = str(a.get("action") or "")
        if action not in QUERY_KNOWLEDGE_ACTIONS: raise ValueError(f"Unknown knowledge query action: {action}")
        service = get_knowledge_service()
        if action == "search": result = service.grounded_context(owner, str(a.get("query") or ""), source_type=a.get("source_type"), sensitivity=a.get("sensitivity"), source_id=a.get("source_id"), date_from=a.get("date_from"), date_to=a.get("date_to"), limit=min(int(a.get("limit", 8)), 50))
        elif action == "list_sources": result = service.list_sources(owner, source_type=a.get("source_type"), sensitivity=a.get("sensitivity"), status=a.get("status"), query=a.get("query", ""), limit=a.get("limit", 100), offset=a.get("offset", 0))
        elif action == "get_source": result = {"source": service.get_source(owner, str(a.get("source_id") or ""), include_content=bool(a.get("include_content", False)))}
        else: result = {"memories": service.list_memories(owner, status=a.get("status"))}
        return {**result, "exit_code": 0}
    except Exception as exc: return _error(exc)


async def do_manage_knowledge(content: str, owner: Optional[str] = None, *, approval_action_id=None, request_id=""):
    try:
        _require_claim(owner, "manage_knowledge", approval_action_id, request_id)
        a = _args(content); action = str(a.get("action") or ""); record = a.get("record") or {}
        if action not in MANAGE_KNOWLEDGE_ACTIONS: raise ValueError(f"Unknown knowledge mutation action: {action}")
        service = get_knowledge_service()
        if action == "ingest_text":
            source = service.ingest_text(owner, **record); result = {"source": source}; record_id = source["id"]; reader = lambda: service.get_source(owner, record_id)
        elif action == "create_memory":
            memory = service.create_memory(owner, record); result = {"memory": memory}; record_id = memory["id"]; reader = lambda: next(item for item in service.list_memories(owner) if item["id"] == record_id)
        elif action == "update_memory":
            memory = service.update_memory(owner, str(a.get("memory_id") or ""), record, expected_revision=int(a.get("revision") or 0)); result = {"memory": memory}; record_id = memory["id"]; reader = lambda: next(item for item in service.list_memories(owner) if item["id"] == record_id)
        elif action == "rebuild_source":
            source = service.rebuild_source(owner, str(a.get("source_id") or "")); result = {"source": source}; record_id = source["id"]; reader = lambda: service.get_source(owner, record_id)
        else:
            removed = service.delete_derivatives(owner, str(a.get("source_id") or "")); result = removed; record_id = removed["id"]; reader = lambda: service.get_source(owner, record_id)
        expected = result.get("source") or result.get("memory") or {"id": record_id, "processing_status": "not_indexed"}
        return {**result, "verification": _verify(record_id, expected, reader), "exit_code": 0}
    except Exception as exc: return _error(exc)


async def do_delete_knowledge(content: str, owner: Optional[str] = None, *, approval_action_id=None, request_id=""):
    try:
        _require_claim(owner, "delete_knowledge", approval_action_id, request_id)
        a = _args(content); action = str(a.get("action") or ""); revision = int(a.get("revision") or 0); service = get_knowledge_service()
        if action not in DELETE_KNOWLEDGE_ACTIONS: raise ValueError(f"Unknown knowledge delete action: {action}")
        if action == "delete_source":
            record_id = str(a.get("source_id") or ""); result = service.delete_source(owner, record_id, expected_revision=revision, purge=bool(a.get("purge", False)))
            try:
                observed = service.get_source(owner, record_id)
                absent = observed.get("deletion_status") == "deleted"
                read_back = "deleted" if absent else "still_active"
            except KnowledgeNotFound:
                absent = True
                read_back = "not_found"
        else:
            record_id = str(a.get("memory_id") or ""); result = service.delete_memory(owner, record_id, expected_revision=revision)
            absent = not any(item["id"] == record_id for item in service.list_memories(owner))
            read_back = "not_found" if absent else "still_present"
        return {**result, "verification": {"status": "verified" if absent else "mismatch", "provider": "local_knowledge", "read_back_id": record_id, "read_back": read_back}, "exit_code": 0}
    except Exception as exc: return _error(exc)
