"""Trusted agent origins reuse the application-owned auth provider."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

from routes import skills_routes


@pytest.mark.asyncio
async def test_skill_test_agent_receives_shared_auth_manager(monkeypatch) -> None:
    captured = {}

    async def fake_stream_agent_loop(*args, **kwargs):
        captured.update(kwargs)
        yield "data: [DONE]\n\n"

    agent_loop = types.ModuleType("src.agent_loop")
    agent_loop.stream_agent_loop = fake_stream_agent_loop
    monkeypatch.setitem(sys.modules, "src.agent_loop", agent_loop)

    async def fake_eval(*args, **kwargs):
        return {"verdict": "inconclusive"}

    monkeypatch.setattr(skills_routes, "_eval_skill_run", fake_eval)
    auth_manager = object()

    await skills_routes._run_skill_test_once(
        "---\nname: demo\n---\n",
        "test it",
        "http://model.test/v1",
        "model",
        {},
        "alice",
        auth_manager=auth_manager,
    )

    assert captured["owner"] == "alice"
    assert captured["auth_manager"] is auth_manager


@pytest.mark.asyncio
async def test_audit_job_preserves_shared_auth_manager(monkeypatch) -> None:
    key = ("alice",)
    skills_routes._skill_audit_jobs[key] = {
        "status": "running",
        "log": [],
        "results": [],
        "done": 0,
        "cancel": False,
    }
    captured = {}

    class FakeSkillsManager:
        def load(self, owner=None):
            return [{"name": "demo", "owner": owner}]

    async def fake_audit(*args, **kwargs):
        captured.update(kwargs)
        return {"skill": "demo", "result": "pass"}

    monkeypatch.setattr(skills_routes, "_audit_one_skill", fake_audit)
    auth_manager = object()

    try:
        await skills_routes._run_audit_all_job(
            key,
            FakeSkillsManager(),
            ["demo"],
            "http://model.test/v1",
            "model",
            {},
            None,
            "alice",
            auth_manager=auth_manager,
        )
    finally:
        skills_routes._skill_audit_jobs.pop(key, None)

    assert captured["auth_manager"] is auth_manager


@pytest.mark.asyncio
async def test_scheduler_builtin_action_receives_shared_auth_manager(
    monkeypatch,
) -> None:
    from src import builtin_actions
    from src.task_scheduler import TaskScheduler

    captured = {}

    async def fake_action(**kwargs):
        captured.update(kwargs)
        return "ok", True

    monkeypatch.setitem(builtin_actions.BUILTIN_ACTIONS, "shared-auth-test", fake_action)
    auth_manager = object()
    scheduler = TaskScheduler(None, auth_manager=auth_manager)
    task = SimpleNamespace(
        action="shared-auth-test",
        owner="alice",
        name="test action",
        prompt="",
    )

    result = await scheduler._execute_action(task)

    assert result == ("ok", True)
    assert captured["auth_manager"] is auth_manager
