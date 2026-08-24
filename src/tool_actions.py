"""Validated, immutable action proposals for canonical tools.

Model output is untrusted text.  This module turns that text into one typed
object *before* risk/confirmation policy is evaluated.  Approval UIs and the
future action ledger can therefore bind to the exact canonical tool version
and normalized arguments instead of displaying an ambiguous fence body.

The module deliberately has no executable-handler imports.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping, Optional

from src.tool_authorization import ExecutionOrigin, ResolvedToolIdentity
from src.tool_registry import BUILTIN_EMAIL_TOOLS, ToolSurface


# Large enough for ordinary document/file operations while still placing a
# firm bound on model-produced JSON before parsing, hashing, logging, or UI
# rendering.  Individual tools can add tighter JSON-Schema limits over time.
MAX_ACTION_ARGUMENT_BYTES = 256 * 1024


class ActionArgumentError(ValueError):
    """One controlled, user-correctable argument validation failure."""

    def __init__(self, message: str, *, path: str = "") -> None:
        super().__init__(message)
        self.path = path


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _canonical_json(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ActionArgumentError("Arguments must contain finite JSON values.") from exc
    if len(encoded.encode("utf-8")) > MAX_ACTION_ARGUMENT_BYTES:
        raise ActionArgumentError(
            f"Arguments exceed the {MAX_ACTION_ARGUMENT_BYTES}-byte limit."
        )
    return encoded


def _parse_json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ActionArgumentError(f"Arguments are not valid JSON: {exc.msg}.") from exc
    if not isinstance(value, dict):
        raise ActionArgumentError("Tool arguments must be a JSON object.")
    return value


def _parse_generate_image(raw: str) -> dict[str, Any]:
    lines = raw.splitlines()
    args: dict[str, Any] = {"prompt": lines[0].strip() if lines else ""}
    for index, key in enumerate(("model", "size", "quality"), start=1):
        if len(lines) > index and lines[index].strip():
            args[key] = lines[index].strip()
    return args


def _parse_model_call(raw: str, *, second_key: str) -> dict[str, Any]:
    first, separator, remainder = raw.partition("\n")
    if not separator:
        # A model is optional for ask_teacher but mandatory for
        # chat_with_model.  Schema validation reports the latter cleanly.
        return {second_key: first.strip()}
    return {"model": first.strip(), second_key: remainder.strip()}


def _parse_two_line_integer(raw: str, *, first_key: str, second_key: str) -> dict[str, Any]:
    first, separator, remainder = raw.partition("\n")
    args: dict[str, Any] = {first_key: first.strip()}
    if separator and remainder.strip():
        try:
            args[second_key] = int(remainder.strip())
        except ValueError as exc:
            raise ActionArgumentError(
                f"'{second_key}' must be an integer.", path=second_key
            ) from exc
    return args


_SINGLE_TEXT_ARGUMENTS: Mapping[str, str] = MappingProxyType(
    {
        "bash": "command",
        "python": "code",
        "web_search": "query",
        "web_fetch": "url",
        "read_file": "path",
        "grep": "pattern",
        "glob": "pattern",
        "ls": "path",
        "search_chats": "query",
        "list_models": "filter",
        "list_sessions": "filter",
        "resolve_contact": "name",
        "update_plan": "plan",
        "list_cached_models": "host",
    }
)


def normalize_action_arguments(
    identity: ResolvedToolIdentity,
    raw_content: object,
) -> dict[str, Any]:
    """Parse one legacy/native fence body into canonical structured args.

    JSON objects are preferred and preserved.  A small, explicit compatibility
    map accepts the existing line-oriented syntax; arbitrary prose is never
    interpreted as a multi-field command.
    """

    raw = str(raw_content or "").strip()
    if len(raw.encode("utf-8")) > MAX_ACTION_ARGUMENT_BYTES:
        raise ActionArgumentError(
            f"Arguments exceed the {MAX_ACTION_ARGUMENT_BYTES}-byte limit."
        )

    if raw.startswith(("{", "[")):
        return _parse_json_object(raw)
    if not raw:
        return {}

    tool = identity.canonical_name
    # Email tools deliberately require structured JSON whenever arguments are
    # present.  Treating prose as an empty object can read/send against a
    # default mailbox different from the one the user intended.
    if tool in BUILTIN_EMAIL_TOOLS or tool == "ask_user" or tool == "edit_file":
        raise ActionArgumentError(
            f"'{tool}' arguments must be supplied as a JSON object."
        )
    if tool == "generate_image":
        return _parse_generate_image(raw)
    if tool == "write_file":
        path, separator, body = raw.partition("\n")
        return {"path": path.strip(), "content": body if separator else ""}
    if tool == "chat_with_model":
        return _parse_model_call(raw, second_key="message")
    if tool == "ask_teacher":
        args = _parse_model_call(raw, second_key="problem")
        if "model" not in args:
            args["model"] = "auto"
        return args
    if tool == "search_hf_models":
        return _parse_two_line_integer(raw, first_key="query", second_key="limit")
    if tool == "tail_serve_output":
        return _parse_two_line_integer(raw, first_key="session_id", second_key="tail")
    if tool in _SINGLE_TEXT_ARGUMENTS:
        return {_SINGLE_TEXT_ARGUMENTS[tool]: raw}

    raise ActionArgumentError(
        f"'{tool}' arguments must be supplied as a JSON object."
    )


def _schema_type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, (list, tuple))
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    # Registry validation owns supported schema vocabulary. Unknown types fail
    # closed here rather than silently skipping validation.
    return False


def _validate_schema_node(value: Any, schema: Mapping[str, Any], *, path: str) -> None:
    """Validate the JSON-Schema subset used by the built-in registry.

    Keeping this small validator dependency-free makes the execution boundary
    available during early application startup.  Registry schemas currently
    use object/array/scalar types, required, enum, items, and properties.
    """

    expected = schema.get("type")
    if isinstance(expected, (list, tuple)):
        matches = any(_schema_type_matches(value, str(item)) for item in expected)
    elif isinstance(expected, str):
        matches = _schema_type_matches(value, expected)
    else:
        matches = True
    if not matches:
        raise ActionArgumentError(
            f"expected {expected}, got {type(value).__name__}", path=path
        )

    enum = schema.get("enum")
    if isinstance(enum, (list, tuple)) and value not in enum:
        raise ActionArgumentError(
            f"value must be one of {list(enum)!r}", path=path
        )

    if isinstance(value, Mapping):
        properties = schema.get("properties") or {}
        required = schema.get("required") or ()
        for key in required:
            if key not in value:
                child_path = f"{path}.{key}" if path else str(key)
                raise ActionArgumentError("required property is missing", path=child_path)
        if schema.get("additionalProperties") is False:
            unexpected = sorted(str(key) for key in value if key not in properties)
            if unexpected:
                child_path = f"{path}.{unexpected[0]}" if path else unexpected[0]
                raise ActionArgumentError("unexpected property", path=child_path)
        for key, item in value.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, Mapping):
                child_path = f"{path}.{key}" if path else str(key)
                _validate_schema_node(item, child_schema, path=child_path)
    elif isinstance(value, (list, tuple)):
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                child_path = f"{path}.{index}" if path else str(index)
                _validate_schema_node(item, item_schema, path=child_path)


def validate_action_arguments(
    identity: ResolvedToolIdentity,
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate normalized arguments against the registry-owned schema."""

    schema = _thaw_json(identity.definition.input_schema)
    # Built-in schemas predate strict structured output.  At the canonical
    # boundary, undeclared top-level fields are never meaningful and are a
    # common source of approval/execution drift, so fail closed here.
    schema.setdefault("additionalProperties", False)
    try:
        _validate_schema_node(dict(arguments), schema, path="")
    except ActionArgumentError as exc:
        location = f" at '{exc.path}'" if exc.path else ""
        raise ActionArgumentError(
            f"Arguments do not match the '{identity.canonical_name}' schema{location}: "
            f"{exc}",
            path=exc.path,
        ) from exc

    # Canonical serialization catches NaN/infinity and enforces the normalized
    # size (which may differ from the raw input due to escapes/whitespace).
    _canonical_json(dict(arguments))
    return dict(arguments)


@dataclass(frozen=True, slots=True)
class ActionEnvelope:
    """Exact immutable proposal evaluated by authorization and approval."""

    requested_name: str
    tool_name: str
    tool_version: int
    surface: ToolSurface
    origin: ExecutionOrigin
    owner: Optional[str]
    session_id: Optional[str]
    request_id: str
    arguments: Mapping[str, Any]
    canonical_arguments: str
    arguments_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", _freeze_json(dict(self.arguments)))

    def arguments_dict(self) -> dict[str, Any]:
        return _thaw_json(self.arguments)

    def as_preview(self) -> dict[str, Any]:
        return {
            "tool": self.tool_name,
            "tool_version": self.tool_version,
            "arguments": self.arguments_dict(),
            "arguments_hash": self.arguments_hash,
            "origin": self.origin.value,
        }

    def execution_content(self) -> str:
        """Render the validated object for one legacy handler adapter.

        The registry boundary owns this compatibility conversion.  Approval
        execution can reconstruct it solely from stored canonical arguments,
        so the handler can never receive unapproved raw model text.
        """

        args = self.arguments_dict()
        if self.tool_name == "bash":
            return str(args.get("command") or "")
        if self.tool_name == "python":
            return str(args.get("code") or "")
        if self.tool_name == "chat_with_model":
            return f"{args.get('model', '')}\n{args.get('message', '')}"
        if self.tool_name == "ask_teacher":
            return f"{args.get('model', 'auto')}\n{args.get('problem', '')}"
        if self.tool_name in {"search_chats", "resolve_contact"}:
            # resolve_contact itself expects JSON; search_chats remains a
            # single-query legacy adapter.
            if self.tool_name == "search_chats":
                return str(args.get("query") or "")
        if self.tool_name in {"list_models", "list_sessions"}:
            return str(args.get("filter") or "")
        return self.canonical_arguments


def build_action_envelope(
    identity: ResolvedToolIdentity,
    raw_content: object,
    *,
    owner: Optional[str],
    session_id: Optional[str],
    request_id: str,
    origin: ExecutionOrigin = ExecutionOrigin.INTERNAL,
) -> ActionEnvelope:
    """Normalize, validate, and bind one exact action proposal."""

    arguments = validate_action_arguments(
        identity,
        normalize_action_arguments(identity, raw_content),
    )
    canonical_arguments = _canonical_json(arguments)
    hash_payload = _canonical_json(
        {
            "arguments": arguments,
            "tool": identity.canonical_name,
            "tool_version": identity.definition.version,
        }
    )
    arguments_hash = hashlib.sha256(hash_payload.encode("utf-8")).hexdigest()
    return ActionEnvelope(
        requested_name=identity.requested_name,
        tool_name=identity.canonical_name,
        tool_version=identity.definition.version,
        surface=identity.surface,
        origin=origin,
        owner=owner,
        session_id=session_id,
        request_id=request_id,
        arguments=arguments,
        canonical_arguments=canonical_arguments,
        arguments_hash=arguments_hash,
    )
