"""query_calendar: read-only split of manage_calendar.

Reads ("what's on my calendar") must run under a LEVEL_0 read policy with no
approval gate — mirroring the query_google_calendar / google-mutation split —
while any mutating action passed to it is refused with a redirect to
manage_calendar rather than executed.
"""

import asyncio
import json

import pytest


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_registered_with_read_policy_no_approval():
    from src.tool_registry import build_builtin_registry, ConfirmationPolicy, RiskLevel
    d = next(x for x in build_builtin_registry() if x.name == "query_calendar")
    assert d.risk is RiskLevel.LEVEL_0
    assert d.effective_confirmation is ConfirmationPolicy.NEVER
    assert d.permissions == frozenset({"calendar.read"})


def test_native_schema_present_and_convertible():
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS, function_call_to_tool_block
    names = {s["function"]["name"] for s in FUNCTION_TOOL_SCHEMAS}
    assert "query_calendar" in names
    blk = function_call_to_tool_block("query_calendar", json.dumps({"action": "list_events"}))
    assert blk is not None and blk.tool_type == "query_calendar"


def test_mutating_action_is_refused(monkeypatch):
    from src.tools.calendar import do_query_calendar
    for action in ("create_event", "update_event", "delete_event"):
        r = asyncio.run(do_query_calendar(json.dumps({"action": action}), owner="admin"))
        assert r.get("exit_code") == 1
        assert "manage_calendar" in r.get("error", "")


def test_read_aliases_normalize(monkeypatch):
    # "list" and hyphenated forms should reach list_events; verify by patching
    # do_manage_calendar and capturing the forwarded action.
    import src.tools.calendar as cal
    seen = {}

    async def _fake(content, owner=None):
        seen.update(json.loads(content))
        return {"response": "ok", "exit_code": 0}

    monkeypatch.setattr(cal, "do_manage_calendar", _fake)
    asyncio.run(cal.do_query_calendar(json.dumps({"action": "list"}), owner="admin"))
    assert seen.get("action") == "list_events"
    seen.clear()
    asyncio.run(cal.do_query_calendar(json.dumps({"action": "list-calendars"}), owner="admin"))
    assert seen.get("action") == "list_calendars"
