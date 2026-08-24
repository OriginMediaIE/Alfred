"""Evidence-based verification for canonical agent actions.

Handler success is not proof that a side effect happened.  This module keeps
verification independent from providers and executors: callers prepare a
small immutable plan immediately before dispatch, then evaluate it against the
observed result immediately afterwards.  File verifiers use the same confined
path resolver as execution and compare bytes read back from disk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from typing import Any, Callable, Mapping, Optional

from src.tool_actions import ActionEnvelope
from src.tool_registry import ToolDefinition, VerificationMode


PathResolver = Callable[[str], str]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _path_fingerprint(path: str) -> str:
    """Identify a verified path without persisting its potentially private text."""

    return hashlib.sha256(path.encode("utf-8", errors="surrogatepass")).hexdigest()


@dataclass(frozen=True, slots=True)
class VerificationPlan:
    tool_name: str
    mode: VerificationMode
    path: Optional[str] = None
    source_path: Optional[str] = None
    expected_sha256: Optional[str] = None
    expected_size: Optional[int] = None
    preparation_error: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VerificationOutcome:
    status: str
    mode: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    reason: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "status": self.status,
            "mode": self.mode,
            "evidence": dict(self.evidence),
        }
        if self.reason:
            value["reason"] = self.reason
        return value


def _failed_result(result: Mapping[str, Any]) -> bool:
    return bool(result.get("error")) or result.get("exit_code") not in (None, 0)


def prepare_action_verification(
    definition: ToolDefinition,
    action: ActionEnvelope,
    *,
    path_resolver: PathResolver,
) -> VerificationPlan:
    """Prepare expected state without mutating anything.

    ``move_file`` is supported for forward compatibility even though the
    current built-in registry does not yet expose it.  Its canonical arguments
    are expected to use ``source`` and ``destination``.
    """

    mode = definition.verification
    if mode is not VerificationMode.READ_BACK:
        return VerificationPlan(tool_name=action.tool_name, mode=mode)

    args = action.arguments_dict()
    try:
        delegated_verifiers = {
            "manage_work": "local_work",
            "delete_work": "local_work",
            "manage_gmail_draft": "gmail",
            "send_gmail": "gmail",
            "modify_gmail_message": "gmail",
            "delete_gmail": "gmail",
            "download_gmail_attachment": "gmail_attachment",
            "create_google_calendar_hold": "google_calendar",
            "create_google_calendar_event": "google_calendar",
            "update_google_calendar_event": "google_calendar",
            "respond_google_calendar_invitation": "google_calendar",
            "update_google_calendar_attendees": "google_calendar",
            "delete_google_calendar_event": "google_calendar",
            "create_meeting": "local_meetings",
            "request_meeting_transcription": "local_meetings",
            "approve_meeting_action_item": "local_meetings",
            "save_meeting_knowledge": "local_meetings",
            "delete_meeting": "local_meetings",
            "manage_knowledge": "local_knowledge",
            "delete_knowledge": "local_knowledge",
            "manage_life": "local_personal_life",
            "delete_life": "local_personal_life",
            "manage_automation": "local_automations",
            "delete_automation": "local_automations",
        }
        if action.tool_name in delegated_verifiers:
            return VerificationPlan(
                tool_name=action.tool_name,
                mode=mode,
                metadata={
                    "delegated_verifier": delegated_verifiers[action.tool_name]
                },
            )

        if action.tool_name == "write_file":
            path = path_resolver(str(args.get("path") or ""))
            expected = str(args.get("content") or "").encode("utf-8")
            return VerificationPlan(
                tool_name=action.tool_name,
                mode=mode,
                path=path,
                expected_sha256=_sha256_bytes(expected),
                expected_size=len(expected),
            )

        if action.tool_name == "edit_file":
            path = path_resolver(str(args.get("path") or ""))
            with open(path, "r", encoding="utf-8") as handle:
                original = handle.read()
            old = str(args.get("old_string") or "")
            new = str(args.get("new_string") or "")
            replace_all = bool(args.get("replace_all", False))
            count = original.count(old) if old else 0
            if not old:
                raise ValueError("old_string is empty")
            if count == 0:
                raise ValueError("old_string was not present before dispatch")
            if count > 1 and not replace_all:
                raise ValueError("old_string was not unique before dispatch")
            expected_text = (
                original.replace(old, new)
                if replace_all
                else original.replace(old, new, 1)
            )
            expected = expected_text.encode("utf-8")
            return VerificationPlan(
                tool_name=action.tool_name,
                mode=mode,
                path=path,
                expected_sha256=_sha256_bytes(expected),
                expected_size=len(expected),
                metadata={"replacement_count": count if replace_all else 1},
            )

        if action.tool_name == "move_file":
            source = path_resolver(str(args.get("source") or ""))
            destination = path_resolver(str(args.get("destination") or ""))
            with open(source, "rb") as handle:
                expected = handle.read()
            return VerificationPlan(
                tool_name=action.tool_name,
                mode=mode,
                path=destination,
                source_path=source,
                expected_sha256=_sha256_bytes(expected),
                expected_size=len(expected),
            )
    except (OSError, UnicodeError, ValueError) as exc:
        return VerificationPlan(
            tool_name=action.tool_name,
            mode=mode,
            preparation_error=f"Could not prepare read-back verification: {exc}",
        )

    return VerificationPlan(
        tool_name=action.tool_name,
        mode=mode,
        preparation_error=(
            f"No read-back verifier is registered for '{action.tool_name}'."
        ),
    )


def verify_action_result(
    plan: VerificationPlan,
    result: Mapping[str, Any],
) -> VerificationOutcome:
    """Evaluate one handler result using only evidence supported by ``plan``."""

    if _failed_result(result):
        return VerificationOutcome(
            status="failed",
            mode=plan.mode.value,
            reason="The handler reported failure; no success was verified.",
        )

    if plan.mode is VerificationMode.RESULT_SCHEMA:
        return VerificationOutcome(
            status="schema_verified",
            mode=plan.mode.value,
            evidence={"result_is_mapping": isinstance(result, Mapping)},
        )
    if plan.mode is VerificationMode.PROCESS_EXIT:
        if result.get("exit_code") == 0:
            return VerificationOutcome(
                status="process_exit_verified",
                mode=plan.mode.value,
                evidence={"exit_code": 0},
            )
        return VerificationOutcome(
            status="failed",
            mode=plan.mode.value,
            reason="A zero process exit code was not observed.",
        )
    if plan.mode is not VerificationMode.READ_BACK:
        return VerificationOutcome(status="indeterminate", mode=plan.mode.value)

    delegated_verifier = plan.metadata.get("delegated_verifier")
    if delegated_verifier:
        reported = result.get("verification")
        if not isinstance(reported, Mapping):
            return VerificationOutcome(
                status="read_back_unavailable",
                mode=plan.mode.value,
                reason="The registered handler returned no read-back evidence.",
            )
        reported_status = str(reported.get("status") or "")
        evidence = {
            "delegated_verifier": str(delegated_verifier),
            "provider": str(reported.get("provider") or "")[:64],
            "read_back_id": str(reported.get("read_back_id") or "")[:256],
        }
        if reported.get("read_back"):
            evidence["read_back"] = str(reported["read_back"])[:64]
        return VerificationOutcome(
            status=(
                "read_back_verified"
                if reported_status == "verified"
                else "read_back_failed"
            ),
            mode=plan.mode.value,
            evidence=evidence,
            reason=(
                None
                if reported_status == "verified"
                else str(reported.get("reason") or "Handler read-back did not match.")[:512]
            ),
        )

    if plan.preparation_error or not plan.path or not plan.expected_sha256:
        return VerificationOutcome(
            status="read_back_unavailable",
            mode=plan.mode.value,
            reason=plan.preparation_error or "Read-back evidence was not prepared.",
        )

    try:
        with open(plan.path, "rb") as handle:
            observed = handle.read()
        source_absent = True
        if plan.source_path is not None:
            source_absent = not os.path.exists(plan.source_path)
    except OSError as exc:
        return VerificationOutcome(
            status="read_back_failed",
            mode=plan.mode.value,
            evidence={"path_sha256": _path_fingerprint(plan.path)},
            reason=f"Could not read the mutated file back: {exc}",
        )

    observed_sha256 = _sha256_bytes(observed)
    evidence = {
        "path_sha256": _path_fingerprint(plan.path),
        "expected_sha256": plan.expected_sha256,
        "observed_sha256": observed_sha256,
        "expected_size": plan.expected_size,
        "observed_size": len(observed),
        **dict(plan.metadata),
    }
    if plan.source_path is not None:
        evidence["source_path_sha256"] = _path_fingerprint(plan.source_path)
        evidence["source_absent"] = source_absent

    matches = (
        observed_sha256 == plan.expected_sha256
        and len(observed) == plan.expected_size
        and source_absent
    )
    return VerificationOutcome(
        status="read_back_verified" if matches else "read_back_failed",
        mode=plan.mode.value,
        evidence=evidence,
        reason=None if matches else "Observed state does not match the approved action.",
    )


def result_with_verification(
    result: Mapping[str, Any],
    outcome: VerificationOutcome,
) -> dict[str, Any]:
    """Return a live/durable result carrying executor-produced evidence."""

    output = dict(result)
    output["verification"] = outcome.as_dict()
    return output


def verification_status_from_result(result: Mapping[str, Any]) -> Optional[str]:
    verification = result.get("verification")
    if not isinstance(verification, Mapping):
        return None
    status = verification.get("status")
    return str(status)[:64] if isinstance(status, str) and status else None
