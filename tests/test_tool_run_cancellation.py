"""Regression coverage for ownership of an in-flight agent tool task."""

import asyncio
from pathlib import Path

import pytest

from src.tool_run_lifecycle import CancellableToolRun


@pytest.mark.asyncio
async def test_outer_cancellation_cancels_and_awaits_the_tool_child() -> None:
    child_started = asyncio.Event()
    child_cancelled = asyncio.Event()
    consumer_waiting = asyncio.Event()
    never = asyncio.Event()
    seen_progress = []
    holder = {}

    async def operation(progress):
        await progress({"elapsed_s": 0.1, "tail": "started"})
        child_started.set()
        try:
            await never.wait()
        except asyncio.CancelledError:
            child_cancelled.set()
            raise

    async def consume():
        run = CancellableToolRun(operation)
        holder["run"] = run
        try:
            async for event in run.progress():
                seen_progress.append(event)
                consumer_waiting.set()
            return await run.result()
        finally:
            await run.close()

    consumer = asyncio.create_task(consume())
    await asyncio.wait_for(child_started.wait(), timeout=1)
    await asyncio.wait_for(consumer_waiting.wait(), timeout=1)

    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(consumer, timeout=1)

    run = holder["run"]
    assert child_cancelled.is_set()
    assert run.task.done()
    assert run.task.cancelled()
    assert seen_progress == [{"elapsed_s": 0.1, "tail": "started"}]


@pytest.mark.asyncio
async def test_normal_completion_preserves_progress_order_and_result() -> None:
    async def operation(progress):
        await progress({"step": 1})
        await progress({"step": 2})
        return "finished", {"ok": True}

    run = CancellableToolRun(operation)
    try:
        progress = [event async for event in run.progress()]
        result = await run.result()
    finally:
        await run.close()

    assert progress == [{"step": 1}, {"step": 2}]
    assert result == ("finished", {"ok": True})
    assert run.task.done()
    assert not run.task.cancelled()


@pytest.mark.asyncio
async def test_tool_exception_is_not_swallowed_by_cleanup() -> None:
    async def operation(progress):
        await progress({"step": "before-error"})
        raise RuntimeError("tool failed")

    run = CancellableToolRun(operation)
    try:
        assert [event async for event in run.progress()] == [
            {"step": "before-error"}
        ]
        with pytest.raises(RuntimeError, match="tool failed"):
            await run.result()
    finally:
        await run.close()


def test_agent_loop_uses_the_owned_tool_run_lifecycle() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "src" / "agent_loop.py"
    ).read_text(encoding="utf-8")

    assert "from src.tool_run_lifecycle import CancellableToolRun" in source
    assert "_tool_run = CancellableToolRun(" in source
    assert "await _tool_run.close()" in source
    assert "asyncio.create_task(_run_tool())" not in source
