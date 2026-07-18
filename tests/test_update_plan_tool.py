"""`update_plan` updates only the current approved plan execution."""
import asyncio
import json

import src.agent_loop as agent_loop
from src.agent_tools import ToolBlock, TOOL_TAGS  # import first to avoid circular
from src.tool_execution import execute_tool_block
from src.tool_index import ALWAYS_AVAILABLE, BUILTIN_TOOL_DESCRIPTIONS
from src.tool_security import is_public_blocked_tool


def _plan_state(*, version=3):
    from src.active_plan import ActivePlanState

    return ActivePlanState(
        session_id="session-a",
        plan_id="plan-a",
        text="- [ ] step one\n- [ ] step two\n- [ ] step three",
        version=version,
    )


def _run(content, *, state=None):
    async def invoke():
        if state is None:
            return await execute_tool_block(ToolBlock("update_plan", content))
        from src.active_plan import bind_active_plan

        with bind_active_plan(state):
            return await execute_tool_block(ToolBlock("update_plan", content))

    return asyncio.run(invoke())


def test_no_active_plan_is_rejected_without_false_success():
    _, result = _run(json.dumps({"plan": "- [x] not actually active"}))

    assert result.get("exit_code") == 1
    assert "no active approved plan" in result.get("error", "").lower()
    assert "plan_update" not in result


def test_valid_plan_returns_marker_and_counts():
    plan = "- [x] step one\n- [ ] step two\n- [ ] step three"
    state = _plan_state()
    desc, result = _run(json.dumps({"plan": plan}), state=state)
    assert result.get("exit_code") == 0
    assert result["plan_update"] == {
        "plan": plan,
        "session_id": "session-a",
        "plan_id": "plan-a",
        "base_version": 3,
        "version": 4,
    }
    assert state.text == plan
    assert state.version == 4
    assert "1/3" in result["output"]   # 1 done of 3


def test_plain_string_accepted():
    plan = "- [ ] a\n- [x] b"
    _, result = _run(plan, state=_plan_state())
    assert result["plan_update"]["plan"] == plan


def test_empty_rejected():
    _, result = _run(json.dumps({"plan": "   "}), state=_plan_state())
    assert "error" in result and result.get("exit_code") == 1


def test_repeated_updates_advance_from_the_current_plan_version():
    from src.active_plan import bind_active_plan

    state = _plan_state(version=8)

    async def invoke_twice():
        with bind_active_plan(state):
            first = await execute_tool_block(
                ToolBlock("update_plan", json.dumps({"plan": "- [x] first\n- [ ] second"}))
            )
            second = await execute_tool_block(
                ToolBlock("update_plan", json.dumps({"plan": "- [x] first\n- [x] second"}))
            )
            return first, second

    (_, first), (_, second) = asyncio.run(invoke_twice())

    assert first["plan_update"]["base_version"] == 8
    assert first["plan_update"]["version"] == 9
    assert second["plan_update"]["base_version"] == 9
    assert second["plan_update"]["version"] == 10
    assert state.version == 10
    assert state.text == "- [x] first\n- [x] second"


def _agent_events(chunks):
    return [
        json.loads(chunk[6:])
        for chunk in chunks
        if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]")
    ]


def _collect_agent(gen):
    async def invoke():
        return [chunk async for chunk in gen]

    return asyncio.run(invoke())


def _patch_agent_basics(monkeypatch):
    monkeypatch.setattr(agent_loop, "get_setting", lambda key, default=None: default)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *args, **kwargs: 10)


def test_agent_loop_emits_versioned_update_and_pins_new_revision(monkeypatch):
    _patch_agent_basics(monkeypatch)
    prompts = []

    async def fake_stream(_candidates, messages, **kwargs):
        prompts.append([dict(message) for message in messages])
        if len(prompts) == 1:
            call = {
                "name": "update_plan",
                "arguments": json.dumps({"plan": "- [x] first\n- [ ] second"}),
            }
            yield f'data: {json.dumps({"type": "tool_calls", "calls": [call]})}\n\n'
        else:
            yield f'data: {json.dumps({"delta": "Continuing."})}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream)
    chunks = _collect_agent(
        agent_loop.stream_agent_loop(
            "https://api.openai.com/v1",
            "gpt-test",
            [{"role": "user", "content": "Run the approved plan."}],
            max_rounds=2,
            relevant_tools={"update_plan"},
            session_id="session-a",
            approved_plan="- [ ] first\n- [ ] second",
            approved_plan_id="plan-a",
            approved_plan_version=7,
            _is_teacher_run=True,
        )
    )
    events = _agent_events(chunks)
    update = next(event for event in events if event.get("type") == "plan_update")

    assert update["data"] == {
        "plan": "- [x] first\n- [ ] second",
        "session_id": "session-a",
        "plan_id": "plan-a",
        "base_version": 7,
        "version": 8,
    }
    assert len(prompts) == 2
    assert "- [x] first\n- [ ] second" in prompts[1][0]["content"]
    assert "- [ ] first\n- [ ] second" not in prompts[1][0]["content"]


def test_agent_loop_hides_and_blocks_update_without_active_plan(monkeypatch):
    _patch_agent_basics(monkeypatch)
    advertised = []

    async def fake_stream(_candidates, messages, **kwargs):
        advertised.extend(
            tool.get("function", {}).get("name")
            for tool in (kwargs.get("tools") or [])
        )
        payload = {
            "type": "tool_calls",
            "calls": [
                {"name": "update_plan", "arguments": json.dumps({"plan": "- [x] fake"})}
            ],
        }
        yield f'data: {json.dumps(payload)}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream)
    chunks = _collect_agent(
        agent_loop.stream_agent_loop(
            "https://api.openai.com/v1",
            "gpt-test",
            [{"role": "user", "content": "Do something."}],
            max_rounds=1,
            relevant_tools={"update_plan"},
            session_id="session-a",
            _is_teacher_run=True,
        )
    )
    events = _agent_events(chunks)

    assert "update_plan" not in advertised
    assert not any(event.get("type") == "plan_update" for event in events)
    output = next(event for event in events if event.get("type") == "tool_output")
    assert output["exit_code"] == 1


def test_registered_everywhere():
    assert "update_plan" in TOOL_TAGS
    assert "update_plan" in ALWAYS_AVAILABLE
    assert "update_plan" in BUILTIN_TOOL_DESCRIPTIONS
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    assert "update_plan" in {s["function"]["name"] for s in FUNCTION_TOOL_SCHEMAS}
    # Not admin/public-gated — any user can drive their own plan.
    assert is_public_blocked_tool("update_plan") is False
