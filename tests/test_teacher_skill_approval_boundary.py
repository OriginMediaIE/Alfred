"""Teacher-generated skill writes must enter the generic approval ledger."""

from src.tool_authorization import ExecutionOrigin
from src.tool_registry import ToolSurface


def test_teacher_skill_is_proposed_without_direct_write(monkeypatch):
    import src.action_ledger as ledger_module
    from src.teacher_escalation import _propose_teacher_skill

    captured = []

    class Ledger:
        def propose(self, envelope, **kwargs):
            captured.append((envelope, kwargs))
            return {"id": "approval-1", "status": "pending"}

    monkeypatch.setattr(ledger_module, "get_action_ledger", lambda: Ledger())
    skill = {"action": "add", "name": "careful-review", "description": "Review first."}

    result = _propose_teacher_skill(skill, owner="alice")

    envelope, metadata = captured[0]
    assert result["status"] == "pending"
    assert envelope.owner == "alice"
    assert envelope.tool_name == "manage_skills"
    assert envelope.surface is ToolSurface.INTERNAL
    assert envelope.origin is ExecutionOrigin.SKILL_WORKFLOW
    assert envelope.arguments_dict() == skill
    assert metadata["risk_level"] == 3
    assert metadata["origin"] == ExecutionOrigin.SKILL_WORKFLOW.value


def test_teacher_escalation_has_no_direct_skill_write():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src/teacher_escalation.py").read_text()

    assert "do_manage_skills(" not in source
