"""Cancellation-safe lifecycle helpers for asyncio subprocesses.

Foreground tool subprocesses must never outlive the request that owns them.
Every process launched through this module starts in a distinct process group
(or Windows process group), and timeout/cancellation tears down the complete
tree before returning control to the caller.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
from contextlib import suppress
from typing import Any, Optional


_DEFAULT_TERMINATION_GRACE_SECONDS = 2.0


def process_group_spawn_kwargs() -> dict[str, Any]:
    """Return safe kwargs for an owned, foreground asyncio subprocess.

    POSIX ``start_new_session`` makes the child a process-group leader, so a
    signal can reach shell grandchildren too.  Windows has no equivalent
    signal semantics, but a new process group plus ``taskkill /T`` gives us a
    practical process-tree boundary.
    """

    if os.name == "nt":
        return {
            "creationflags": getattr(
                subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0x00000200,
            )
        }
    return {"start_new_session": True}


async def _wait_for_exit(proc: Any, timeout: float) -> bool:
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        return False
    except (ProcessLookupError, ChildProcessError):
        return True


def _signal_posix_tree(proc: Any, sig: signal.Signals) -> None:
    pid = getattr(proc, "pid", None)
    if not pid:
        return
    try:
        pgid = os.getpgid(pid)
        # Group signalling is safe only for subprocesses that were spawned as
        # their own leader.  Fall back to the Process API for legacy callers.
        if pgid == pid:
            os.killpg(pgid, sig)
            return
    except (OSError, ProcessLookupError):
        return
    try:
        if sig is signal.SIGKILL:
            proc.kill()
        else:
            proc.terminate()
    except (OSError, ProcessLookupError):
        pass


def _posix_group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except PermissionError:
        return True
    except (OSError, ProcessLookupError):
        return False


async def _terminate_owned_posix_group(
    proc: Any,
    grace_seconds: float,
) -> None:
    """Terminate a group we created, even if its leader already exited."""

    pgid = getattr(proc, "pid", None)
    if not pgid:
        return
    # Once the owned leader has exited, every remaining member is an escaped
    # descendant.  Kill it immediately: a background shell may ignore SIGTERM
    # or continue its command list after TERM interrupts a child sleep.
    leader_exited = getattr(proc, "returncode", None) is not None
    initial_signal = signal.SIGKILL if leader_exited else signal.SIGTERM
    try:
        os.killpg(pgid, initial_signal)
    except (OSError, ProcessLookupError):
        return

    if leader_exited:
        return

    deadline = time.monotonic() + grace_seconds
    while _posix_group_alive(pgid) and time.monotonic() < deadline:
        await asyncio.sleep(min(0.05, grace_seconds))
    if _posix_group_alive(pgid):
        with suppress(OSError, ProcessLookupError):
            os.killpg(pgid, signal.SIGKILL)
    if getattr(proc, "returncode", None) is None:
        await _wait_for_exit(proc, grace_seconds)


def _kill_windows_tree(pid: Optional[int]) -> None:
    if not pid:
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


async def terminate_process_tree(
    proc: Any,
    *,
    grace_seconds: float = _DEFAULT_TERMINATION_GRACE_SECONDS,
    owned_process_group: bool = False,
) -> None:
    """Terminate and reap an asyncio subprocess and all descendants.

    The operation is idempotent.  POSIX gets a graceful group SIGTERM followed
    by SIGKILL; Windows uses ``taskkill /T /F`` and falls back to ``proc.kill``.
    """

    grace = max(0.05, float(grace_seconds))
    if os.name != "nt" and owned_process_group:
        await _terminate_owned_posix_group(proc, grace)
        return

    if getattr(proc, "returncode", None) is not None:
        return

    if os.name == "nt":
        await asyncio.to_thread(_kill_windows_tree, getattr(proc, "pid", None))
        if await _wait_for_exit(proc, grace):
            return
        with suppress(OSError, ProcessLookupError):
            proc.kill()
        await _wait_for_exit(proc, grace)
        return

    _signal_posix_tree(proc, signal.SIGTERM)
    if await _wait_for_exit(proc, grace):
        return
    _signal_posix_tree(proc, signal.SIGKILL)
    await _wait_for_exit(proc, grace)


async def communicate_with_cleanup(
    proc: Any,
    *,
    input: Optional[bytes] = None,
    timeout: Optional[float] = None,
) -> tuple[bytes, bytes]:
    """Run ``proc.communicate`` and reap its tree on timeout/cancellation."""

    try:
        communication = proc.communicate(input=input)
        if timeout is None:
            return await communication
        return await asyncio.wait_for(communication, timeout=float(timeout))
    except (asyncio.TimeoutError, asyncio.CancelledError):
        # Cleanup is part of cancellation: the caller must not regain control
        # while an SSH/python/shell descendant is still running.
        await terminate_process_tree(proc, owned_process_group=True)
        raise
