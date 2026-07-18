"""Lifecycle ownership for one in-process agent tool execution.

The agent loop streams progress from a child task.  This wrapper makes that
child an explicitly owned resource so closing/cancelling the outer agent
generator cannot leave a side-effecting coroutine running in the background.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any, Dict, Generic, TypeVar, cast


ToolResult = TypeVar("ToolResult")
ProgressEvent = Dict[str, Any]
ProgressCallback = Callable[[ProgressEvent], Awaitable[None]]
ToolOperation = Callable[[ProgressCallback], Awaitable[ToolResult]]

_PROGRESS_DONE = object()


class CancellableToolRun(Generic[ToolResult]):
    """Own a tool task, its progress queue, and cancellation cleanup.

    Construct this class inside a running event loop.  Consumers drain
    :meth:`progress`, await :meth:`result`, and call :meth:`close` from a
    ``finally`` block.  ``close`` is idempotent and waits for cooperative child
    cancellation before returning.
    """

    def __init__(self, operation: ToolOperation[ToolResult]) -> None:
        self._progress_queue: asyncio.Queue[object] = asyncio.Queue()
        self._closed = False
        self.task: asyncio.Task[ToolResult] = asyncio.create_task(
            self._run(operation)
        )

    async def _run(self, operation: ToolOperation[ToolResult]) -> ToolResult:
        try:
            return await operation(self._publish_progress)
        finally:
            # The queue is unbounded, so put_nowait cannot block cancellation
            # cleanup or lose the sentinel behind another await.
            self._progress_queue.put_nowait(_PROGRESS_DONE)

    async def _publish_progress(self, event: ProgressEvent) -> None:
        await self._progress_queue.put(event)

    async def progress(self) -> AsyncGenerator[ProgressEvent, None]:
        """Yield progress in order until the operation reaches a terminal state."""

        while True:
            event = await self._progress_queue.get()
            if event is _PROGRESS_DONE:
                return
            yield cast(ProgressEvent, event)

    async def result(self) -> ToolResult:
        """Return the normal result or propagate the tool's exception."""

        return await self.task

    async def close(self) -> None:
        """Cancel and await a still-running child task exactly once."""

        if self._closed:
            return
        self._closed = True

        if self.task.done():
            # Retrieve an otherwise-unobserved exception when cancellation
            # races between the progress sentinel and result().  result()
            # remains the normal exception-propagation path.
            if not self.task.cancelled():
                self.task.exception()
            return

        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            # This is the expected acknowledgement from the owned child.  Any
            # ordinary tool exception still propagates to the caller.
            pass
