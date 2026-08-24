"""Scheduled tasks keep shell/file tools behind an explicit crew allowlist."""

from types import SimpleNamespace

from src.task_scheduler import (
    TASK_DEFAULT_SHELL_TOOLS,
    TaskScheduler,
    compose_task_relevant_tools,
)
from src.tool_index import ASSISTANT_ALWAYS_AVAILABLE


def test_assistant_always_available_lacks_shell():
    # Pins the precondition that made the bug possible: the assistant set the
    # task runner relied on does not contain the shell/Python tools.
    assert "bash" not in ASSISTANT_ALWAYS_AVAILABLE
    assert "python" not in ASSISTANT_ALWAYS_AVAILABLE


def test_shell_not_offered_when_rag_returns_nothing():
    tools = compose_task_relevant_tools(
        set(), ASSISTANT_ALWAYS_AVAILABLE, TASK_DEFAULT_SHELL_TOOLS
    )
    assert not (TASK_DEFAULT_SHELL_TOOLS & tools)


def test_assistant_and_rag_tools_preserved():
    tools = compose_task_relevant_tools(
        {"web_fetch"}, ASSISTANT_ALWAYS_AVAILABLE, None
    )
    assert "web_fetch" in tools          # RAG-selected tool kept
    assert "manage_calendar" in tools    # assistant-always member kept
    assert "bash" not in tools           # shell remains opt-in


def test_crew_allowlist_restriction_still_honored():
    # A crew that defines enabled_tools yields a `disabled_tools` set
    # (all_tools - enabled). Anything it disables must stay disabled, including
    # the shell defaults — the task owner explicitly scoped the tools.
    disabled = set(TASK_DEFAULT_SHELL_TOOLS)
    tools = compose_task_relevant_tools(set(), ASSISTANT_ALWAYS_AVAILABLE, disabled)
    assert "bash" not in tools
    assert "python" not in tools
    assert "edit_file" not in tools
    assert "read_file" not in tools


def test_explicit_shell_allowlist_maps_to_real_schemas_for_admin():
    from src.agent_loop import FUNCTION_TOOL_SCHEMAS

    schema_names = {s["function"]["name"] for s in FUNCTION_TOOL_SCHEMAS}
    offered = compose_task_relevant_tools(
        {"bash", "python"}, ASSISTANT_ALWAYS_AVAILABLE, set()
    )
    admin_schemas = offered & schema_names  # mirrors agent_loop's relevant∩schemas
    assert "bash" in admin_schemas
    assert "python" in admin_schemas


def test_non_admin_owner_block_strips_shell_end_to_end():
    # Defense check: the runner now OFFERS shell tools, but stream_agent_loop
    # subtracts blocked_tools_for_owner() (== NON_ADMIN_BLOCKED_TOOLS for a
    # non-admin multi-user owner) from both the prompt and the schemas. Reusing
    # that exact block set proves a non-admin task's model never sees the shell.
    from src.agent_loop import FUNCTION_TOOL_SCHEMAS
    from src.tool_security import NON_ADMIN_BLOCKED_TOOLS

    schema_names = {s["function"]["name"] for s in FUNCTION_TOOL_SCHEMAS}
    offered = compose_task_relevant_tools(
        {"bash", "python"}, ASSISTANT_ALWAYS_AVAILABLE, set()
    )
    non_admin_schemas = (offered - set(NON_ADMIN_BLOCKED_TOOLS)) & schema_names
    assert "bash" not in non_admin_schemas
    assert "python" not in non_admin_schemas


async def test_scheduled_task_honors_global_disabled_tools(monkeypatch):
    # RaresKeY review on #4398: the runner offers the shell/file group by
    # default, but the scheduled-task path only built disabled_tools from the
    # crew allowlist — it never merged the operator's global disabled_tools
    # setting. So an admin / AUTH_ENABLED=false task could still see and call
    # bash/python after the operator turned them off globally, because the
    # downstream prompt/schema/execution gates only enforce what is passed in.
    #
    # Drive the real _execute_llm_task and assert the global list reaches BOTH
    # sides: it is stripped from relevant_tools AND passed into the agent loop.
    global_off = ["bash", "python", "read_file"]

    monkeypatch.setattr(
        "src.settings.get_setting",
        lambda key, default=None: list(global_off) if key == "disabled_tools" else default,
    )

    # Degraded-index stand-in that still returns one RAG hit, so we can prove
    # non-disabled tools survive the merge.
    class _FakeIndex:
        def get_tools_for_query(self, query, k=8):
            return {"web_fetch"}

    monkeypatch.setattr("src.tool_index.get_tool_index", lambda: _FakeIndex())

    captured = {}

    async def _capture(endpoint_url, model, task, session_id, *,
                       system_prompt=None, disabled_tools=None, relevant_tools=None,
                       datetime_context_msg=None):
        captured["disabled_tools"] = disabled_tools
        captured["relevant_tools"] = relevant_tools
        return "done"

    scheduler = TaskScheduler(session_manager=None)
    scheduler._run_agent_loop = _capture

    # No crew_member_id + a preset session/endpoint means the DB is never
    # touched on this path, so a bare task object is enough to exercise it.
    task = SimpleNamespace(
        crew_member_id=None,
        endpoint_url="http://endpoint",
        model="util-model",
        session_id="sess-1",
        owner="admin",
        prompt="back up the logs",
        name="Nightly job",
        max_steps=5,
        character_id=None,
    )

    result = await scheduler._execute_llm_task(task, db=None)
    assert result == "done"

    # Enforcement side: the global list reached the agent loop, so the
    # prompt/schema/execution gates will strip these even for an admin owner.
    passed_disabled = captured["disabled_tools"]
    assert passed_disabled is not None
    assert set(global_off) <= set(passed_disabled)

    # Offer side: globally-disabled tools are gone from relevant_tools, but the
    # rest of the shell/file defaults and the RAG hit survive.
    offered = captured["relevant_tools"]
    assert "bash" not in offered
    assert "python" not in offered
    assert "read_file" not in offered
    assert "edit_file" not in offered  # shell/file group defaults off
    assert "web_fetch" in offered   # RAG-selected tool preserved
