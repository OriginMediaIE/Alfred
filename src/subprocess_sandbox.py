"""Fail-closed OS sandbox selection for model-proposed subprocesses."""

from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
from typing import Iterable


class SandboxUnavailable(RuntimeError):
    pass


def _scheme_string(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _macos_profile(
    cwd: str,
    executable: str,
    extra_read_roots: Iterable[str] = (),
    extra_write_roots: Iterable[str] = (),
) -> str:
    readable = {
        "/bin", "/sbin", "/usr", "/System", "/Library",
        "/private/etc", "/private/var/db", "/dev",
        str(Path(executable).resolve().parent),
        str(Path(cwd).resolve()),
    }
    writable = {str(Path(cwd).resolve()), "/tmp", "/private/tmp"}
    readable.update(str(Path(path).resolve()) for path in extra_read_roots)
    writable.update(str(Path(path).resolve()) for path in extra_write_roots)
    clauses = ["(version 1)", "(deny default)", "(allow process*)", "(allow signal)",
               "(allow sysctl-read)", "(allow mach-lookup)"]
    clauses.append(
        "(allow file-read* "
        + " ".join(f'(subpath "{_scheme_string(path)}")' for path in sorted(readable))
        + ")"
    )
    clauses.append(
        "(allow file-write* "
        + " ".join(f'(subpath "{_scheme_string(path)}")' for path in sorted(writable))
        + ")"
    )
    # Network is intentionally absent. Web access has its own constrained
    # tools and must not become an exfiltration side channel for shell code.
    return " ".join(clauses)


def sandboxed_argv(
    executable: str,
    args: Iterable[str],
    *,
    cwd: str,
    extra_read_roots: Iterable[str] = (),
    extra_write_roots: Iterable[str] = (),
) -> list[str]:
    """Return an argv wrapped in an available OS sandbox or fail closed.

    Operators may explicitly accept the host risk with
    ``OM_ALLOW_UNSANDBOXED_AGENT_EXECUTION=1``. The default never silently
    falls back to an unrestricted child process.
    """

    executable = str(executable)
    arguments = [str(value) for value in args]
    # This is an explicit operator override, not an automatic fallback.  It
    # must take precedence even on macOS: sandbox-exec can be present while
    # being unusable inside a nested container/profile, which otherwise makes
    # the documented override impossible to exercise.
    if os.getenv("OM_ALLOW_UNSANDBOXED_AGENT_EXECUTION", "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return [executable, *arguments]
    if platform.system() == "Darwin" and Path("/usr/bin/sandbox-exec").exists():
        return [
            "/usr/bin/sandbox-exec", "-p", _macos_profile(
                cwd, executable, extra_read_roots, extra_write_roots
            ),
            executable, *arguments,
        ]
    available_hint = "Install/configure an OS subprocess sandbox"
    if platform.system() == "Linux" and shutil.which("bwrap") is None:
        available_hint = "Install bubblewrap or keep shell execution disabled"
    raise SandboxUnavailable(f"{available_hint}; unrestricted execution is blocked")


__all__ = ["SandboxUnavailable", "sandboxed_argv"]
