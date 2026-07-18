"""Short-lived capability grants for cookbook serve diagnostics.

``tail_serve_output`` executes local or remote shell commands and can expose
model logs.  A syntactically valid tmux session id is not authority.  This
module grants one diagnostic read only after the same agent request has:

1. launched the serve task;
2. observed that exact task in a failing state through list_served_models; and
3. requested the same owner/request/session/host tuple before the grant expires.

The ledger is intentionally process-local.  Restarting loses grants and fails
closed; durable action records will replace it in SAFE-005.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Any, Iterable, Mapping, Optional


class DiagnosticAuthorizationError(PermissionError):
    """The requested log read lacks the required launch/status capability."""


FAILURE_STATUSES = frozenset({"error", "crashed", "failed"})
_GRANT_TTL_SECONDS = 300.0
_lock = threading.RLock()
_clock = time.monotonic


@dataclass(slots=True)
class _DiagnosticGrant:
    principal: str
    request_id: str
    session_id: str
    remote_host: str
    ssh_port: str
    launched_at: float
    listed_at: Optional[float] = None
    listed_status: str = ""
    consumed: bool = False


@dataclass(frozen=True, slots=True)
class TailAuthorization:
    session_id: str
    remote_host: str
    ssh_port: str
    status: str


_grants: dict[tuple[str, str, str], _DiagnosticGrant] = {}


def _principal(owner: Optional[str]) -> str:
    # Auth-disabled single-user mode legitimately has no username.  Request IDs
    # still isolate concurrent turns; authenticated deployments supply owner.
    return str(owner or "__single_user__")


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _key(owner: Optional[str], request_id: str, session_id: str) -> tuple[str, str, str]:
    return (_principal(owner), _text(request_id), _text(session_id))


def _prune(now: float) -> None:
    stale = [
        key
        for key, grant in _grants.items()
        if now - grant.launched_at > _GRANT_TTL_SECONDS
    ]
    for key in stale:
        _grants.pop(key, None)


def record_launch(
    *,
    owner: Optional[str],
    request_id: str,
    session_id: str,
    remote_host: str = "",
    ssh_port: str = "",
) -> bool:
    """Record a fresh agent-owned serve launch; missing context grants nothing."""

    request_id = _text(request_id)
    session_id = _text(session_id)
    if not request_id or not session_id:
        return False
    now = _clock()
    grant = _DiagnosticGrant(
        principal=_principal(owner),
        request_id=request_id,
        session_id=session_id,
        remote_host=_text(remote_host),
        ssh_port=_text(ssh_port),
        launched_at=now,
    )
    with _lock:
        _prune(now)
        _grants[_key(owner, request_id, session_id)] = grant
    return True


def record_listed_statuses(
    *,
    owner: Optional[str],
    request_id: str,
    tasks: Iterable[Mapping[str, Any]],
) -> None:
    """Arm one log read for freshly launched tasks observed as failed."""

    request_id = _text(request_id)
    if not request_id:
        return
    now = _clock()
    with _lock:
        _prune(now)
        for task in tasks:
            if not isinstance(task, Mapping):
                continue
            session_id = _text(task.get("session_id") or task.get("sessionId"))
            grant = _grants.get(_key(owner, request_id, session_id))
            if grant is None:
                continue
            observed_host = _text(task.get("remote") or task.get("remoteHost"))
            if observed_host == "local":
                observed_host = ""
            if observed_host and observed_host != grant.remote_host:
                # Status for a different host cannot arm this launch grant.
                grant.listed_at = None
                grant.listed_status = ""
                grant.consumed = False
                continue
            status = _text(task.get("status") or task.get("phase")).lower()
            if status in FAILURE_STATUSES:
                grant.listed_at = now
                grant.listed_status = status
                grant.consumed = False
            else:
                grant.listed_at = None
                grant.listed_status = ""
                grant.consumed = False


def authorize_tail(
    *,
    owner: Optional[str],
    request_id: str,
    session_id: str,
    requested_remote_host: str = "",
    requested_ssh_port: str = "",
) -> TailAuthorization:
    """Consume and return the one-shot diagnostic capability or fail closed."""

    request_id = _text(request_id)
    session_id = _text(session_id)
    now = _clock()
    with _lock:
        _prune(now)
        grant = _grants.get(_key(owner, request_id, session_id))
        if grant is None:
            raise DiagnosticAuthorizationError(
                "tail_serve_output is limited to a serve task launched by this agent request"
            )
        if grant.listed_at is None or grant.listed_status not in FAILURE_STATUSES:
            raise DiagnosticAuthorizationError(
                "call list_served_models and observe this newly launched task failing before reading its logs"
            )
        if grant.consumed:
            raise DiagnosticAuthorizationError(
                "the diagnostic grant was already used; list the failing task again before another log read"
            )
        requested_host = _text(requested_remote_host)
        if requested_host == "local":
            requested_host = ""
        if requested_host and requested_host != grant.remote_host:
            raise DiagnosticAuthorizationError(
                "the requested diagnostic host does not match the launched task"
            )
        requested_port = _text(requested_ssh_port)
        if requested_port and requested_port != grant.ssh_port:
            raise DiagnosticAuthorizationError(
                "the requested diagnostic SSH port does not match the launched task"
            )
        grant.consumed = True
        return TailAuthorization(
            session_id=grant.session_id,
            remote_host=grant.remote_host,
            ssh_port=grant.ssh_port,
            status=grant.listed_status,
        )


def _reset_for_tests() -> None:
    with _lock:
        _grants.clear()
