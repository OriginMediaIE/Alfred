"""Tests for the model-interaction tools after their move to the agent_tools
registry (#3629): chat_with_model, ask_teacher, list_models.

The implementations now live in src/agent_tools/model_interaction_tools.py
(moved out of src/ai_interaction.py). These assert (1) the handlers are
registered in TOOL_HANDLERS, (2) each handler runs the moved logic and threads
session_id/owner from the ctx, and (3) tool_execution.py dispatches them
through the registry rather than the legacy dispatch_ai_tool elif.
"""
import asyncio
from types import SimpleNamespace

import httpx
import src.ai_interaction as ai_interaction
import src.chatgpt_subscription as chatgpt_subscription
import src.endpoint_resolver as endpoint_resolver
import src.llm_core as llm_core
import src.database as database
from src.agent_tools import TOOL_HANDLERS
from src.agent_tools import model_interaction_tools as mit

_MODEL_TOOLS = ("chat_with_model", "ask_teacher", "list_models")


def test_model_interaction_tools_registered():
    for name in _MODEL_TOOLS:
        assert name in TOOL_HANDLERS, f"{name} missing from TOOL_HANDLERS"


def test_chat_with_model_threads_owner_and_returns(monkeypatch):
    seen = {}

    def fake_resolve(spec, owner=None):
        seen["spec"] = spec
        seen["owner"] = owner
        return ("http://x", "model-x", {})

    async def fake_call(url, model, messages, headers=None, timeout=None):
        seen["message"] = messages[-1]["content"]
        return "hi back"

    monkeypatch.setattr(ai_interaction, "_resolve_model", fake_resolve)
    monkeypatch.setattr(llm_core, "llm_call_async", fake_call)

    res = asyncio.run(mit.ChatWithModelTool().execute(
        "model-x\nhello there", {"owner": "alice", "session_id": "s1"}))

    assert res == {"model": "model-x", "response": "hi back"}
    assert seen["owner"] == "alice"
    assert seen["spec"] == "model-x"
    assert seen["message"] == "hello there"


def test_ask_teacher_threads_owner_and_marks_teacher(monkeypatch):
    seen = {}

    def fake_resolve(spec, owner=None):
        seen["owner"] = owner
        return ("http://x", "teacher-x", {})

    async def fake_call(url, model, messages, headers=None, timeout=None):
        return "do this and that"

    monkeypatch.setattr(ai_interaction, "_resolve_model", fake_resolve)
    monkeypatch.setattr(llm_core, "llm_call_async", fake_call)

    res = asyncio.run(mit.AskTeacherTool().execute(
        "teacher-x\nI am stuck", {"owner": "bob"}))

    assert res["teacher"] is True
    assert res["response"] == "do this and that"
    assert seen["owner"] == "bob"


def test_list_models_no_endpoints(monkeypatch):
    class _Q:
        def filter(self, *a, **k):
            return self

        def all(self):
            return []

    class _S:
        def query(self, *a, **k):
            return _Q()

        def close(self):
            pass

    monkeypatch.setattr(database, "SessionLocal", lambda: _S())

    res = asyncio.run(mit.ListModelsTool().execute("", {}))
    assert res["results"] == "No enabled model endpoints configured."
    assert res["models"] == []
    assert res["source"] == "local_endpoint_catalog"
    assert res["runtime_verified"] is False


def test_list_models_reads_only_local_cached_and_pinned_models(monkeypatch):
    endpoint = SimpleNamespace(
        id="endpoint-1",
        name="Configured OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        provider_auth_id="oauth-session-that-must-not-refresh",
        cached_models='["cached/model", "hidden/model", "duplicate/model"]',
        pinned_models='["pinned/model", "duplicate/model"]',
        hidden_models='["hidden/model"]',
    )

    class _Q:
        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return [endpoint]

    class _S:
        def query(self, *args, **kwargs):
            return _Q()

        def close(self):
            pass

    def forbidden_side_effect(*args, **kwargs):
        raise AssertionError("observational list_models must not resolve, refresh, or probe")

    monkeypatch.setattr(database, "SessionLocal", lambda: _S())
    monkeypatch.setattr(endpoint_resolver, "resolve_endpoint_runtime", forbidden_side_effect)
    monkeypatch.setattr(chatgpt_subscription, "resolve_runtime_credentials", forbidden_side_effect)
    monkeypatch.setattr(httpx, "get", forbidden_side_effect)

    res = asyncio.run(mit.ListModelsTool().execute("", {}))

    assert [model["id"] for model in res["models"]] == [
        "cached/model",
        "duplicate/model",
        "pinned/model",
    ]
    assert all(model["source"] == "local_endpoint_catalog" for model in res["models"])
    assert all(model["runtime_verified"] is False for model in res["models"])
    assert res["runtime_verified"] is False
    assert "runtime availability not probed" in res["results"]
    assert "hidden/model" not in res["results"]


def test_dispatched_via_registry_not_dispatch_ai_tool():
    """Model tools have exact handler bindings, never the AI catch-all."""
    import src.tool_execution as execution

    for name in _MODEL_TOOLS:
        module_name, class_name = execution._AGENT_HANDLER_CLASSES[name]
        assert module_name == "src.agent_tools.model_interaction_tools"
        assert class_name.endswith("Tool")
        assert name not in execution._AI_DISPATCH_TARGETS
