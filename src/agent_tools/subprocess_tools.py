import asyncio
import collections
import math
import sys
import time
import re
from typing import Awaitable, Callable, Dict, Optional, Tuple

from src.constants import MAX_OUTPUT_CHARS
from src.subprocess_lifecycle import (
    process_group_spawn_kwargs,
    terminate_process_tree,
)

DEFAULT_BASH_TIMEOUT = 60 * 60     # 1 hour
DEFAULT_PYTHON_TIMEOUT = 60 * 60

PROGRESS_INTERVAL_S = 2.0
PROGRESS_TAIL_LINES = 12

_SHELL_BLOCK_RULES = (
    (re.compile(r"(^|[;&|]\s*)(sudo|doas|pkexec|su)(\s|$)", re.I), "privilege escalation is blocked"),
    (re.compile(r"\b(mkfs(?:\.[a-z0-9]+)?|fdisk|parted|diskutil\s+erase|shutdown|reboot|halt|poweroff)\b", re.I), "destructive system command is blocked"),
    (re.compile(r"\brm\s+(?:-[A-Za-z]*[rf][A-Za-z]*\s+)+(?:/|~|\$HOME)(?:\s|$)", re.I), "recursive deletion of a broad path is blocked"),
    (re.compile(r"(?:^|[/\\])\.(?:ssh|gnupg)(?:[/\\]|$)|(?:^|[/\\])\.env(?:\.|$)|/etc/(?:shadow|sudoers)|\b(?:id_rsa|id_ed25519|authorized_keys)\b", re.I), "access to protected credential paths is blocked"),
    (re.compile(r"\bsecurity\s+find-(?:generic|internet)-password\b|\bsecret-tool\s+lookup\b", re.I), "credential-store extraction is blocked"),
)


def validate_agent_shell(content: str) -> None:
    """Reject high-confidence escalation, destruction, and secret extraction."""
    command = str(content or "")
    if not command.strip():
        raise ValueError("shell command is required")
    if len(command) > 100_000:
        raise ValueError("shell command exceeds the 100000 character limit")
    for pattern, reason in _SHELL_BLOCK_RULES:
        if pattern.search(command):
            raise ValueError(reason)


def _execution_timeout(ctx: dict, fallback: float) -> float:
    """Read the canonical registry deadline propagated by the executor."""

    value = ctx.get("timeout_seconds")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    value = float(value)
    return value if math.isfinite(value) and value > 0 else fallback


def _display_seconds(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


async def _run_subprocess_streaming(
    proc: asyncio.subprocess.Process,
    *,
    timeout: Optional[float],
    progress_cb: Optional[Callable[[Dict], Awaitable[None]]] = None,
) -> Tuple[str, str, Optional[int], bool]:
    started = time.time()
    stdout_full: list[str] = []
    stderr_full: list[str] = []
    tail = collections.deque(maxlen=PROGRESS_TAIL_LINES)

    async def _reader(stream, full_buf, label: str):
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").rstrip("\n")
            full_buf.append(decoded)
            if label == "err":
                tail.append(f"! {decoded}")
            else:
                tail.append(decoded)

    async def _progress_emitter():
        await asyncio.sleep(PROGRESS_INTERVAL_S)
        while True:
            if progress_cb:
                try:
                    await progress_cb({
                        "elapsed_s": round(time.time() - started, 1),
                        "tail": "\n".join(list(tail)),
                    })
                except Exception:
                    pass
            await asyncio.sleep(PROGRESS_INTERVAL_S)

    rd_out = asyncio.create_task(_reader(proc.stdout, stdout_full, "out"))
    rd_err = asyncio.create_task(_reader(proc.stderr, stderr_full, "err"))
    prog_task = asyncio.create_task(_progress_emitter()) if progress_cb else None

    timed_out = False
    try:
        if timeout is None:
            await proc.wait()
        else:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        timed_out = True
        await terminate_process_tree(proc, owned_process_group=True)
    except asyncio.CancelledError:
        await terminate_process_tree(proc, owned_process_group=True)
        for t in (rd_out, rd_err):
            t.cancel()
        if prog_task is not None:
            prog_task.cancel()
        raise
    else:
        # A foreground shell may exit after spawning a detached descendant.
        # `#!bg` has its own explicit durable-job path; an ordinary bash/python
        # call must leave no local processes behind after reporting success.
        await terminate_process_tree(proc, owned_process_group=True)
    finally:
        if prog_task is not None:
            if not prog_task.done():
                prog_task.cancel()
            await asyncio.gather(prog_task, return_exceptions=True)
        for t in (rd_out, rd_err):
            try:
                await asyncio.wait_for(t, timeout=1)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                if not t.done():
                    t.cancel()
            except Exception:
                # Reader failures should be reflected by the process result,
                # not mask timeout/cancellation cleanup of the sibling stream.
                pass
        await asyncio.gather(rd_out, rd_err, return_exceptions=True)

    return (
        "\n".join(stdout_full),
        "\n".join(stderr_full),
        proc.returncode,
        timed_out,
    )


class BashTool:
    async def execute(self, content: str, ctx: dict) -> dict:
        from src.tool_execution import agent_cwd, _truncate
        progress_cb = ctx.get("progress_cb")
        _subproc_env = ctx.get("subproc_env")
        timeout = _execution_timeout(ctx, DEFAULT_BASH_TIMEOUT)
        try:
            validate_agent_shell(content)
        except ValueError as exc:
            return {"error": f"bash: {exc}", "exit_code": 126, "blocked": True}
        from src.subprocess_sandbox import SandboxUnavailable, sandboxed_argv
        from core.platform_compat import find_bash
        shell = find_bash()
        if not shell:
            return {"error": "bash: no supported shell is installed", "exit_code": 126, "blocked": True}
        try:
            argv = sandboxed_argv(shell, ["-c", content], cwd=agent_cwd())
        except SandboxUnavailable as exc:
            return {"error": f"bash: {exc}", "exit_code": 126, "blocked": True}
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_subproc_env,
            cwd=agent_cwd(),
            **process_group_spawn_kwargs(),
        )
        stdout, stderr, rc, timed_out = await _run_subprocess_streaming(
            proc,
            timeout=None if ctx.get("deadline_managed") is True else timeout,
            progress_cb=progress_cb,
        )
        if timed_out:
            return {
                "error": (
                    f"bash: timed out after {_display_seconds(timeout)}s — "
                    "process tree killed"
                ),
                "exit_code": 124,
                "stdout": _truncate(stdout, MAX_OUTPUT_CHARS),
                "stderr": _truncate(stderr, MAX_OUTPUT_CHARS),
                "timed_out": True,
                "timeout_seconds": timeout,
            }
        if rc == 71 and "sandbox_apply" in stderr:
            return {
                "error": "bash: the host denied creation of the required OS sandbox",
                "exit_code": 126,
                "blocked": True,
            }
        output = stdout.rstrip()
        err = stderr.rstrip()
        if err:
            output = (output + "\nSTDERR: " + err).strip() if output else "STDERR: " + err
        output = _truncate(output, MAX_OUTPUT_CHARS)
        return {"output": output or "(no output)", "exit_code": rc or 0}


class PythonTool:
    async def execute(self, content: str, ctx: dict) -> dict:
        from src.tool_execution import agent_cwd, _truncate
        progress_cb = ctx.get("progress_cb")
        _subproc_env = ctx.get("subproc_env")
        timeout = _execution_timeout(ctx, DEFAULT_PYTHON_TIMEOUT)
        from src.subprocess_sandbox import SandboxUnavailable, sandboxed_argv
        executable = sys.executable or "python"
        try:
            argv = sandboxed_argv(
                executable, ["-I", "-c", content], cwd=agent_cwd()
            )
        except SandboxUnavailable as exc:
            return {"error": f"python: {exc}", "exit_code": 126, "blocked": True}
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_subproc_env,
            cwd=agent_cwd(),
            **process_group_spawn_kwargs(),
        )
        stdout, stderr, rc, timed_out = await _run_subprocess_streaming(
            proc,
            timeout=None if ctx.get("deadline_managed") is True else timeout,
            progress_cb=progress_cb,
        )
        if timed_out:
            return {
                "error": (
                    f"python: timed out after {_display_seconds(timeout)}s — "
                    "process tree killed"
                ),
                "exit_code": 124,
                "stdout": _truncate(stdout, MAX_OUTPUT_CHARS),
                "stderr": _truncate(stderr, MAX_OUTPUT_CHARS),
                "timed_out": True,
                "timeout_seconds": timeout,
            }
        if rc == 71 and "sandbox_apply" in stderr:
            return {
                "error": "python: the host denied creation of the required OS sandbox",
                "exit_code": 126,
                "blocked": True,
            }
        output = stdout.rstrip()
        err = stderr.rstrip()
        if err:
            output = (output + "\nSTDERR: " + err).strip() if output else "STDERR: " + err
        output = _truncate(output, MAX_OUTPUT_CHARS)
        return {"output": output or "(no output)", "exit_code": rc or 0}
