"""Untrusted email extraction may propose calendar effects, never execute them."""

from src.tool_authorization import ExecutionOrigin
from src.tool_registry import ToolSurface


def test_email_calendar_change_is_an_exact_background_proposal(monkeypatch):
    from routes.email_pollers import _propose_email_calendar_action
    import src.action_ledger as ledger_module

    captured = []

    class Ledger:
        def propose(self, envelope, **kwargs):
            captured.append((envelope, kwargs))
            return {"id": "approval-1", "status": "pending"}

    monkeypatch.setattr(ledger_module, "get_action_ledger", lambda: Ledger())
    args = {
        "action": "update_event",
        "uid": "event-7",
        "dtstart": "2026-08-24T09:00:00",
    }

    proposal = _propose_email_calendar_action(
        "alice", args, message_id="private-provider-message-id", index=2
    )

    envelope, metadata = captured[0]
    assert proposal == {"id": "approval-1", "status": "pending"}
    assert envelope.owner == "alice"
    assert envelope.tool_name == "manage_calendar"
    assert envelope.surface is ToolSurface.INTERNAL
    assert envelope.origin is ExecutionOrigin.BACKGROUND_MONITOR
    assert envelope.arguments_dict() == args
    assert "private-provider-message-id" not in envelope.request_id
    assert metadata["origin"] == ExecutionOrigin.BACKGROUND_MONITOR.value
    assert metadata["risk_level"] == 3


def test_email_poller_has_no_direct_calendar_tool_execution():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "routes/email_pollers.py").read_text()

    assert "do_manage_calendar(" not in source
