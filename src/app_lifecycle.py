"""Small, testable helpers for application-owned asyncio task teardown."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any


async def cancel_and_reap_tasks(tasks: Iterable[Any]) -> int:
    """Cancel every live task and wait until each one has settled."""

    live = [task for task in tasks if task is not None and not task.done()]
    for task in live:
        task.cancel()
    if live:
        await asyncio.gather(*live, return_exceptions=True)
    return len(live)


__all__ = ["cancel_and_reap_tasks"]
