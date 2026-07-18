"""Canonical identity and surface inventory for built-in agent tools.

SAFE-002 starts by moving name ownership out of the high-fan-out
``src.agent_tools`` facade.  Typed definitions and policy/runtime bindings are
added around this dependency-light foundation in subsequent registry slices.
Importing this module must stay side-effect free.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, fields
from enum import Enum, IntEnum
from functools import lru_cache
import math
import re
from types import MappingProxyType
from typing import Any


class RegistryValidationError(ValueError):
    """A static tool definition violates the registry contract."""


class RiskLevel(IntEnum):
    LEVEL_0 = 0
    LEVEL_1 = 1
    LEVEL_2 = 2
    LEVEL_3 = 3


class ConfirmationPolicy(str, Enum):
    NEVER = "never"
    TRUSTED_ONLY = "trusted_only"
    REQUIRED = "required"
    ALWAYS = "always"


class IdempotencyMode(str, Enum):
    READ_ONLY = "read_only"
    NONE = "none"
    LOCAL_KEY = "local_key"
    PROVIDER_KEY = "provider_key"


class AuditBehavior(str, Enum):
    METADATA = "metadata"
    REDACTED = "redacted"


class VerificationMode(str, Enum):
    RESULT_SCHEMA = "result_schema"
    READ_BACK = "read_back"
    PROCESS_EXIT = "process_exit"
    INDETERMINATE = "indeterminate"


class ToolSurface(str, Enum):
    INTERNAL = "internal"
    NATIVE = "native"
    FENCE = "fence"
    SEARCH = "search"
    PROMPT = "prompt"
    ADMIN_UI = "admin_ui"
    DYNAMIC_MCP = "dynamic_mcp"


class MigrationState(str, Enum):
    TYPED = "typed"
    LEGACY_UNCLASSIFIED = "legacy_unclassified"


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        frozen = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise RegistryValidationError(
                    f"JSON object key must be a string, got {key!r}"
                )
            frozen[key] = _freeze_json(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise RegistryValidationError(
        f"value is not finite JSON data: {value!r}"
    )


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 1
    backoff_seconds: tuple[float, ...] = ()
    retryable_errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "backoff_seconds", tuple(self.backoff_seconds))
        object.__setattr__(self, "retryable_errors", tuple(self.retryable_errors))


@dataclass(frozen=True, slots=True)
class ToolPresentation:
    label: str
    category: str
    action_label: str
    progress_label: str
    icon: str


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Immutable metadata for one canonical static tool capability."""

    name: str
    aliases: tuple[str, ...]
    description: str
    domain: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    permissions: frozenset[str]
    risk: RiskLevel
    confirmation: ConfirmationPolicy
    reversible: bool
    timeout_seconds: float
    retry: RetryPolicy
    idempotency: IdempotencyMode
    idempotency_key_fields: tuple[str, ...]
    audit_behavior: AuditBehavior
    audit_fields: tuple[str, ...]
    compensation: str
    verification: VerificationMode
    success_example: Mapping[str, Any]
    failure_example: Mapping[str, Any]
    presentation: ToolPresentation
    binding: str
    surfaces: frozenset[ToolSurface]
    migration_state: MigrationState = MigrationState.TYPED

    def __post_init__(self) -> None:
        object.__setattr__(self, "aliases", tuple(self.aliases))
        object.__setattr__(self, "input_schema", _freeze_json(self.input_schema))
        object.__setattr__(self, "output_schema", _freeze_json(self.output_schema))
        object.__setattr__(self, "permissions", frozenset(self.permissions))
        object.__setattr__(
            self,
            "idempotency_key_fields",
            tuple(self.idempotency_key_fields),
        )
        object.__setattr__(self, "audit_fields", tuple(self.audit_fields))
        object.__setattr__(
            self,
            "success_example",
            _freeze_json(self.success_example),
        )
        object.__setattr__(
            self,
            "failure_example",
            _freeze_json(self.failure_example),
        )
        object.__setattr__(self, "surfaces", frozenset(self.surfaces))

    @property
    def effective_risk(self) -> RiskLevel:
        """Return the fail-closed risk used before legacy policy is classified."""

        return self.risk

    @property
    def effective_confirmation(self) -> ConfirmationPolicy:
        if self.migration_state is MigrationState.LEGACY_UNCLASSIFIED:
            return ConfirmationPolicy.ALWAYS
        return self.confirmation

    def as_init_dict(self) -> dict[str, Any]:
        """Return constructor values for tests/migrations without sharing JSON."""

        values = {field.name: getattr(self, field.name) for field in fields(self)}
        for name in (
            "input_schema",
            "output_schema",
            "success_example",
            "failure_example",
        ):
            values[name] = _thaw_json(values[name])
        return values


_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")


@dataclass(frozen=True, slots=True, init=False)
class ToolRegistry:
    """Immutable collection with deterministic aliases and strict validation."""

    _definitions: tuple[ToolDefinition, ...]
    _by_name: Mapping[str, ToolDefinition]
    _aliases: Mapping[str, str]
    _allowed_legacy_names: frozenset[str]

    def __init__(
        self,
        definitions: Iterable[ToolDefinition],
        *,
        allowed_legacy_names: frozenset[str] = frozenset(),
    ) -> None:
        ordered = tuple(definitions)
        by_name: dict[str, ToolDefinition] = {}
        for definition in ordered:
            if definition.name in by_name:
                raise RegistryValidationError(
                    f"duplicate tool name: {definition.name}"
                )
            by_name[definition.name] = definition

        aliases: dict[str, str] = {}
        for definition in ordered:
            for alias in definition.aliases:
                if alias in aliases:
                    raise RegistryValidationError(f"duplicate alias: {alias}")
                if alias in by_name:
                    raise RegistryValidationError(
                        f"alias/name collision: {alias}"
                    )
                aliases[alias] = definition.name

        object.__setattr__(self, "_definitions", ordered)
        object.__setattr__(self, "_by_name", MappingProxyType(by_name))
        object.__setattr__(self, "_aliases", MappingProxyType(aliases))
        object.__setattr__(
            self,
            "_allowed_legacy_names",
            frozenset(allowed_legacy_names),
        )
        self.validate(allow_legacy=True)

    def __len__(self) -> int:
        return len(self._definitions)

    def __iter__(self) -> Iterator[ToolDefinition]:
        return iter(self._definitions)

    def names(self) -> frozenset[str]:
        return frozenset(self._by_name)

    def names_for_surface(self, surface: ToolSurface) -> frozenset[str]:
        return frozenset(
            definition.name
            for definition in self._definitions
            if surface in definition.surfaces
        )

    def definitions_for_surface(
        self,
        surface: ToolSurface,
    ) -> tuple[ToolDefinition, ...]:
        return tuple(
            definition
            for definition in self._definitions
            if surface in definition.surfaces
        )

    @property
    def legacy_debt(self) -> frozenset[str]:
        return frozenset(
            definition.name
            for definition in self._definitions
            if definition.migration_state is MigrationState.LEGACY_UNCLASSIFIED
        )

    def resolve(
        self,
        name: str,
        *,
        surface: ToolSurface | None = None,
    ) -> ToolDefinition:
        canonical = self._aliases.get(name, name)
        try:
            definition = self._by_name[canonical]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc
        if surface is not None and surface not in definition.surfaces:
            raise KeyError(
                f"tool {definition.name!r} is not available on {surface.value!r}"
            )
        return definition

    def validate(self, *, allow_legacy: bool) -> None:
        for definition in self._definitions:
            self._validate_definition(definition, allow_legacy=allow_legacy)

    def _validate_definition(
        self,
        definition: ToolDefinition,
        *,
        allow_legacy: bool,
    ) -> None:
        name = definition.name
        if not _TOOL_NAME_RE.fullmatch(name):
            raise RegistryValidationError(f"invalid tool name: {name!r}")
        if name.startswith("mcp__"):
            raise RegistryValidationError(
                f"reserved dynamic MCP tool name: {name}"
            )
        for alias in definition.aliases:
            if not _TOOL_NAME_RE.fullmatch(alias):
                raise RegistryValidationError(f"invalid tool alias: {alias!r}")
            if alias.startswith("mcp__"):
                raise RegistryValidationError(
                    f"reserved dynamic MCP alias: {alias}"
                )

        if not definition.description.strip():
            raise RegistryValidationError(f"{name}: missing description")
        if not definition.domain.strip():
            raise RegistryValidationError(f"{name}: missing domain")
        self._validate_object_schema(name, "input", definition.input_schema)
        self._validate_object_schema(name, "output", definition.output_schema)
        timeout = definition.timeout_seconds
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(float(timeout))
            or not 0 < timeout <= 86_400
        ):
            raise RegistryValidationError(f"{name}: invalid timeout")
        if not definition.binding.strip():
            raise RegistryValidationError(f"{name}: missing binding")
        if ToolSurface.INTERNAL not in definition.surfaces:
            raise RegistryValidationError(f"{name}: missing internal surface")
        if not definition.audit_fields:
            raise RegistryValidationError(f"{name}: missing audit fields")
        if not definition.compensation.strip():
            raise RegistryValidationError(f"{name}: missing compensation")
        if not definition.success_example or not definition.failure_example:
            raise RegistryValidationError(f"{name}: missing response examples")
        presentation = definition.presentation
        if not all(
            value.strip()
            for value in (
                presentation.label,
                presentation.category,
                presentation.action_label,
                presentation.progress_label,
                presentation.icon,
            )
        ):
            raise RegistryValidationError(f"{name}: incomplete presentation")

        retry = definition.retry
        if (
            isinstance(retry.max_attempts, bool)
            or not isinstance(retry.max_attempts, int)
            or not 1 <= retry.max_attempts <= 5
        ):
            raise RegistryValidationError(f"{name}: invalid retry attempts")
        if len(retry.backoff_seconds) > retry.max_attempts - 1:
            raise RegistryValidationError(f"{name}: invalid retry backoff")
        if any(
            isinstance(delay, bool)
            or not isinstance(delay, (int, float))
            or not math.isfinite(float(delay))
            or delay < 0
            for delay in retry.backoff_seconds
        ):
            raise RegistryValidationError(f"{name}: invalid retry backoff")

        if definition.migration_state is MigrationState.LEGACY_UNCLASSIFIED:
            if not allow_legacy:
                raise RegistryValidationError(f"{name}: unclassified legacy tool")
            if name not in self._allowed_legacy_names:
                raise RegistryValidationError(
                    f"{name}: not in frozen legacy allowlist"
                )
            if (
                definition.risk is not RiskLevel.LEVEL_3
                or definition.confirmation is not ConfirmationPolicy.ALWAYS
                or definition.permissions != frozenset({"legacy.unclassified"})
                or definition.retry.max_attempts != 1
                or definition.idempotency is not IdempotencyMode.NONE
                or definition.verification is not VerificationMode.INDETERMINATE
            ):
                raise RegistryValidationError(
                    f"{name}: legacy tool policy is not fail-closed"
                )
            return

        if not definition.permissions:
            raise RegistryValidationError(f"{name}: missing permissions")
        if (
            definition.risk is RiskLevel.LEVEL_3
            and definition.confirmation is not ConfirmationPolicy.ALWAYS
        ):
            raise RegistryValidationError(
                f"{name}: Level 3 requires confirmation always"
            )
        if (
            definition.risk is RiskLevel.LEVEL_2
            and definition.confirmation
            not in {ConfirmationPolicy.REQUIRED, ConfirmationPolicy.ALWAYS}
        ):
            raise RegistryValidationError(
                f"{name}: Level 2 requires confirmation by default"
            )
        if (
            retry.max_attempts > 1
            and definition.idempotency is IdempotencyMode.NONE
        ):
            raise RegistryValidationError(
                f"{name}: unsafe retry for non-idempotent operation"
            )
        if (
            definition.idempotency
            in {IdempotencyMode.LOCAL_KEY, IdempotencyMode.PROVIDER_KEY}
            and not definition.idempotency_key_fields
        ):
            raise RegistryValidationError(
                f"{name}: idempotency key fields are required"
            )
        if definition.idempotency_key_fields:
            properties = definition.input_schema.get("properties", {})
            missing_keys = set(definition.idempotency_key_fields) - set(properties)
            if missing_keys:
                raise RegistryValidationError(
                    f"{name}: idempotency key field absent from input schema: "
                    f"{sorted(missing_keys)}"
                )

    @staticmethod
    def _validate_object_schema(
        name: str,
        kind: str,
        schema: Mapping[str, Any],
    ) -> None:
        if not isinstance(schema, Mapping) or schema.get("type") != "object":
            raise RegistryValidationError(
                f"{name}: {kind} schema must be an object schema"
            )
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            raise RegistryValidationError(
                f"{name}: {kind} schema properties must be an object"
            )

# Every tool exposed by the bundled email MCP server. Keeping this surface in
# the dependency-light catalog lets schema, parsing, execution, and security
# derive the same aliases without the registry importing a policy module.
BUILTIN_EMAIL_TOOLS = frozenset(
    {
        "list_email_accounts",
        "list_emails",
        "read_email",
        "search_emails",
        "send_email",
        "reply_to_email",
        "draft_email",
        "draft_email_reply",
        "ai_draft_email_reply",
        "archive_email",
        "delete_email",
        "mark_email_read",
        "bulk_email",
        "download_attachment",
    }
)


# Tools models may invoke through fenced text.  This is intentionally a surface
# declaration, not every internal executor: adding a name here expands model
# authority and must be reviewed.  Native exposure is declared independently by
# FUNCTION_TOOL_SCHEMAS until that compatibility view is registry-generated.
_FENCE_TOOL_NAMES = frozenset(
    {
        "bash",
        "python",
        "web_search",
        "web_fetch",
        "read_file",
        "write_file",
        "edit_file",
        "grep",
        "glob",
        "ls",
        "get_workspace",
        "manage_bg_jobs",
        "create_document",
        "update_document",
        "edit_document",
        "search_chats",
        "chat_with_model",
        "create_session",
        "list_sessions",
        "send_to_session",
        "pipeline",
        "manage_session",
        "manage_memory",
        "list_models",
        "ui_control",
        "generate_image",
        "ask_user",
        "update_plan",
        "manage_tasks",
        "api_call",
        "ask_teacher",
        "manage_skills",
        "suggest_document",
        "manage_endpoints",
        "manage_mcp",
        "manage_webhooks",
        "manage_tokens",
        "manage_documents",
        "manage_settings",
        "manage_notes",
        "manage_calendar",
        "resolve_contact",
        "manage_contact",
        "download_model",
        "serve_model",
        "list_served_models",
        "stop_served_model",
        "tail_serve_output",
        "list_downloads",
        "cancel_download",
        "search_hf_models",
        "list_cached_models",
        "list_serve_presets",
        "serve_preset",
        "adopt_served_model",
        "list_cookbook_servers",
        "edit_image",
        "trigger_research",
        "manage_research",
        "app_api",
    }
)

# These legacy dispatcher branches are deliberately not advertised to models.
# They remain visible to registry completeness checks until they are either
# given an approval-aware internal call path or formally retired.
INTERNAL_ONLY_TOOL_NAMES = frozenset(
    {"vault_search", "vault_get", "vault_unlock"}
)

TOOL_TAGS = _FENCE_TOOL_NAMES | BUILTIN_EMAIL_TOOLS
BUILTIN_TOOL_NAMES = TOOL_TAGS | INTERNAL_ONLY_TOOL_NAMES


# Compatibility-locked plan-mode exposure.  This is intentionally explicit
# rather than inferred from registry risk while policy migration is incomplete:
# sixteen currently read-only tools still carry LEGACY_UNCLASSIFIED metadata,
# while the typed diagnostics tool is deliberately excluded because its runtime
# ownership checks are not implemented yet.  Consumers must fail closed by
# subtracting this set from the complete canonical inventory.
PLAN_MODE_ALLOWED_TOOL_NAMES = frozenset(
    {
        "read_file",
        "grep",
        "glob",
        "ls",
        "get_workspace",
        "web_search",
        "web_fetch",
        "search_chats",
        "list_models",
        "list_sessions",
        "list_email_accounts",
        "list_emails",
        "read_email",
        "search_emails",
        "list_served_models",
        "list_downloads",
        "list_cached_models",
        "search_hf_models",
        "list_serve_presets",
        "list_cookbook_servers",
        "resolve_contact",
        "chat_with_model",
        "ask_teacher",
    }
)

if not PLAN_MODE_ALLOWED_TOOL_NAMES <= BUILTIN_TOOL_NAMES:
    raise RegistryValidationError("plan-mode allowlist contains unknown tools")


# This first policy slice deliberately covers only simple operations whose
# behavior does not vary by an action/method discriminator. Mixed tools stay
# explicit migration debt and resolve Level 3/ALWAYS until classified.
CLASSIFIED_TOOL_NAMES = frozenset(
    {
        "bash",
        "python",
        "web_search",
        "web_fetch",
        "read_file",
        "write_file",
        "edit_file",
        "grep",
        "glob",
        "ls",
        "get_workspace",
        "tail_serve_output",
    }
)
LEGACY_UNCLASSIFIED_TOOL_NAMES = BUILTIN_TOOL_NAMES - CLASSIFIED_TOOL_NAMES


_AUDIT_FIELDS = (
    "tool_name",
    "owner",
    "session_id",
    "arguments_hash",
    "started_at",
    "finished_at",
    "outcome",
)

_LEGACY_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "output": {"type": "string"},
        "error": {"type": "string"},
        "exit_code": {"type": "integer"},
    },
    "additionalProperties": True,
}


_DOMAIN_GROUPS = {
    "shell": {"bash", "python", "manage_bg_jobs"},
    "web": {"web_search", "web_fetch"},
    "files": {
        "read_file",
        "write_file",
        "edit_file",
        "grep",
        "glob",
        "ls",
        "get_workspace",
    },
    "documents": {
        "create_document",
        "update_document",
        "edit_document",
        "suggest_document",
        "manage_documents",
    },
    "conversation": {
        "ask_user",
        "update_plan",
        "search_chats",
        "create_session",
        "list_sessions",
        "send_to_session",
        "manage_session",
    },
    "models": {
        "chat_with_model",
        "ask_teacher",
        "list_models",
        "download_model",
        "serve_model",
        "list_served_models",
        "stop_served_model",
        "tail_serve_output",
        "list_downloads",
        "cancel_download",
        "search_hf_models",
        "list_cached_models",
        "list_serve_presets",
        "serve_preset",
        "adopt_served_model",
        "list_cookbook_servers",
    },
    "automation": {"pipeline", "manage_tasks"},
    "knowledge": {"manage_memory", "manage_skills"},
    "interface": {"ui_control"},
    "images": {"generate_image", "edit_image"},
    "integrations": {"api_call", "app_api", "manage_mcp", "manage_webhooks"},
    "administration": {
        "manage_endpoints",
        "manage_tokens",
        "manage_settings",
    },
    "notes": {"manage_notes"},
    "calendar": {"manage_calendar"},
    "contacts": {"resolve_contact", "manage_contact"},
    "email": set(BUILTIN_EMAIL_TOOLS),
    "research": {"trigger_research", "manage_research"},
    "vault": set(INTERNAL_ONLY_TOOL_NAMES),
}


def _domain_for(name: str) -> str:
    matches = [domain for domain, names in _DOMAIN_GROUPS.items() if name in names]
    if len(matches) != 1:
        raise RegistryValidationError(
            f"{name}: expected exactly one domain, found {matches}"
        )
    return matches[0]


def _object_schema(
    properties: Mapping[str, Any],
    *,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": dict(properties),
    }
    if required:
        schema["required"] = list(required)
    return schema


_EXTRA_INPUT_SCHEMAS = {
    "generate_image": _object_schema(
        {
            "prompt": {"type": "string"},
            "model": {"type": "string"},
            "size": {"type": "string"},
            "quality": {"type": "string"},
        },
        required=("prompt",),
    ),
    "manage_research": _object_schema(
        {
            "action": {
                "type": "string",
                "enum": ["list", "read", "delete"],
            },
            "id": {"type": "string"},
            "search": {"type": "string"},
        }
    ),
    "download_attachment": _object_schema(
        {
            "uid": {"type": "string"},
            "index": {"type": "integer"},
            "folder": {"type": "string", "default": "INBOX"},
            "account": {"type": "string"},
        },
        required=("uid", "index"),
    ),
    "draft_email": _object_schema(
        {
            "to": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "cc": {"type": "string"},
            "bcc": {"type": "string"},
            "title": {"type": "string"},
            "account": {"type": "string"},
        },
        required=("to", "subject", "body"),
    ),
    "draft_email_reply": _object_schema(
        {
            "uid": {"type": "string"},
            "body": {"type": "string"},
            "folder": {"type": "string", "default": "INBOX"},
            "reply_all": {"type": "boolean", "default": False},
            "title": {"type": "string"},
            "account": {"type": "string"},
        },
        required=("uid", "body"),
    ),
    "ai_draft_email_reply": _object_schema(
        {
            "uid": {"type": "string"},
            "folder": {"type": "string", "default": "INBOX"},
            "reply_all": {"type": "boolean", "default": False},
            "title": {"type": "string"},
            "account": {"type": "string"},
        },
        required=("uid",),
    ),
    "search_emails": _object_schema(
        {
            "query": {"type": "string"},
            "folders": {"type": "array", "items": {"type": "string"}},
            "max_results": {"type": "integer", "default": 20},
            "account": {"type": "string"},
        },
        required=("query",),
    ),
    "vault_search": _object_schema(
        {"query": {"type": "string"}},
        required=("query",),
    ),
    "vault_get": _object_schema(
        {
            "item_id": {"type": "string"},
            "reason": {"type": "string"},
        },
        required=("item_id", "reason"),
    ),
    "vault_unlock": _object_schema(
        {"master_password": {"type": "string"}},
        required=("master_password",),
    ),
}

_EXTRA_DESCRIPTIONS = {
    "generate_image": "Generate an image with a configured image-capable model.",
    "manage_research": "List, read, or delete saved deep-research reports.",
    "download_attachment": "Download one email attachment to approved local storage.",
    "draft_email": "Create a reviewable email draft without sending it.",
    "draft_email_reply": "Create a reviewable reply draft without sending it.",
    "ai_draft_email_reply": "Generate and save an AI-assisted reply draft for review.",
    "search_emails": "Search configured mailboxes for matching messages.",
    "vault_search": "Search vault item metadata without returning passwords.",
    "vault_get": "Retrieve a sensitive vault item for an explicit reason.",
    "vault_unlock": "Unlock the configured vault using a master password.",
}


@dataclass(frozen=True, slots=True)
class _PolicySeed:
    permissions: frozenset[str]
    risk: RiskLevel
    confirmation: ConfirmationPolicy
    timeout_seconds: float
    retry: RetryPolicy
    idempotency: IdempotencyMode
    audit_behavior: AuditBehavior
    verification: VerificationMode
    compensation: str


def _read_policy(
    permission: str,
    *,
    timeout: float = 30,
    attempts: int = 1,
) -> _PolicySeed:
    backoff = (0.5,) if attempts == 2 else ()
    return _PolicySeed(
        permissions=frozenset({permission}),
        risk=RiskLevel.LEVEL_0,
        confirmation=ConfirmationPolicy.NEVER,
        timeout_seconds=timeout,
        retry=RetryPolicy(
            max_attempts=attempts,
            backoff_seconds=backoff,
            retryable_errors=("timeout", "temporarily_unavailable")
            if attempts > 1
            else (),
        ),
        idempotency=IdempotencyMode.READ_ONLY,
        audit_behavior=AuditBehavior.METADATA,
        verification=VerificationMode.RESULT_SCHEMA,
        compensation="not_applicable",
    )


def _level_three_policy(
    permission: str,
    *,
    timeout: float,
    verification: VerificationMode,
) -> _PolicySeed:
    return _PolicySeed(
        permissions=frozenset({permission}),
        risk=RiskLevel.LEVEL_3,
        confirmation=ConfirmationPolicy.ALWAYS,
        timeout_seconds=timeout,
        retry=RetryPolicy(max_attempts=1),
        idempotency=IdempotencyMode.NONE,
        audit_behavior=AuditBehavior.REDACTED,
        verification=verification,
        compensation="manual_reconciliation_required",
    )


_CLASSIFIED_POLICIES = {
    "bash": _level_three_policy(
        "shell.execute",
        timeout=3600,
        verification=VerificationMode.INDETERMINATE,
    ),
    "python": _level_three_policy(
        "shell.execute",
        timeout=3600,
        verification=VerificationMode.INDETERMINATE,
    ),
    "write_file": _level_three_policy(
        "files.write",
        timeout=30,
        verification=VerificationMode.READ_BACK,
    ),
    "edit_file": _level_three_policy(
        "files.write",
        timeout=30,
        verification=VerificationMode.READ_BACK,
    ),
    "web_search": _read_policy("research.web"),
    "web_fetch": _read_policy("research.web"),
    "read_file": _read_policy("files.read"),
    "grep": _read_policy("files.read", timeout=60),
    "glob": _read_policy("files.read"),
    "ls": _read_policy("files.read"),
    "get_workspace": _read_policy("files.read", timeout=5),
    "tail_serve_output": _PolicySeed(
        permissions=frozenset({"models.diagnostics.read"}),
        risk=RiskLevel.LEVEL_0,
        confirmation=ConfirmationPolicy.NEVER,
        timeout_seconds=30,
        retry=RetryPolicy(max_attempts=1),
        idempotency=IdempotencyMode.READ_ONLY,
        audit_behavior=AuditBehavior.REDACTED,
        verification=VerificationMode.RESULT_SCHEMA,
        compensation="not_applicable",
    ),
}


def _human_label(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split("_"))


def _binding_for(name: str) -> str:
    if name in BUILTIN_EMAIL_TOOLS:
        return f"builtin_mcp:email:{name}"
    if name == "generate_image":
        return "builtin_mcp:image_gen:generate_image"
    if name in INTERNAL_ONLY_TOOL_NAMES:
        return f"internal:vault:{name}"
    return f"legacy_dispatch:{name}"


@lru_cache(maxsize=1)
def build_builtin_registry() -> ToolRegistry:
    """Build and validate the static registry without eager handler imports.

    Native schema seeds are imported lazily from the dependency-light catalog;
    the public ``tool_schemas`` facade remains downstream. Calling this function
    from a cold interpreter therefore cannot recreate the former module cycle.
    """

    from src.tool_schema_catalog import FUNCTION_TOOL_SCHEMAS

    native: dict[str, Mapping[str, Any]] = {}
    descriptions: dict[str, str] = {}
    for entry in FUNCTION_TOOL_SCHEMAS:
        function = entry.get("function") or {}
        name = function.get("name")
        if not isinstance(name, str) or name in native:
            raise RegistryValidationError(
                f"invalid or duplicate native schema name: {name!r}"
            )
        native[name] = function.get("parameters") or {}
        descriptions[name] = str(function.get("description") or "")

    all_inputs = {**native, **_EXTRA_INPUT_SCHEMAS}
    if frozenset(all_inputs) != BUILTIN_TOOL_NAMES:
        missing = sorted(BUILTIN_TOOL_NAMES - frozenset(all_inputs))
        extra = sorted(frozenset(all_inputs) - BUILTIN_TOOL_NAMES)
        raise RegistryValidationError(
            f"schema inventory drift; missing={missing}, extra={extra}"
        )

    definitions = []
    for name in sorted(BUILTIN_TOOL_NAMES):
        policy = _CLASSIFIED_POLICIES.get(name)
        typed = policy is not None
        domain = _domain_for(name)
        label = _human_label(name)
        surfaces = {ToolSurface.INTERNAL}
        if name in TOOL_TAGS:
            surfaces.add(ToolSurface.FENCE)
        if name in native:
            surfaces.add(ToolSurface.NATIVE)

        if typed:
            permissions = policy.permissions
            risk = policy.risk
            confirmation = policy.confirmation
            timeout_seconds = policy.timeout_seconds
            retry = policy.retry
            idempotency = policy.idempotency
            audit_behavior = policy.audit_behavior
            verification = policy.verification
            compensation = policy.compensation
            migration_state = MigrationState.TYPED
        else:
            # This is deliberately not a guessed policy. Every consumer must
            # treat legacy debt as Level 3/ALWAYS until its operation is typed.
            permissions = frozenset({"legacy.unclassified"})
            risk = RiskLevel.LEVEL_3
            confirmation = ConfirmationPolicy.ALWAYS
            timeout_seconds = 60
            retry = RetryPolicy(max_attempts=1)
            idempotency = IdempotencyMode.NONE
            audit_behavior = AuditBehavior.REDACTED
            verification = VerificationMode.INDETERMINATE
            compensation = "manual_reconciliation_required"
            migration_state = MigrationState.LEGACY_UNCLASSIFIED

        definitions.append(
            ToolDefinition(
                name=name,
                aliases=(),
                description=descriptions.get(name)
                or _EXTRA_DESCRIPTIONS.get(name, ""),
                domain=domain,
                input_schema=all_inputs[name],
                output_schema=_LEGACY_RESULT_SCHEMA,
                permissions=permissions,
                risk=risk,
                confirmation=confirmation,
                reversible=False,
                timeout_seconds=timeout_seconds,
                retry=retry,
                idempotency=idempotency,
                idempotency_key_fields=(),
                audit_behavior=audit_behavior,
                audit_fields=_AUDIT_FIELDS,
                compensation=compensation,
                verification=verification,
                success_example={"output": "Operation completed.", "exit_code": 0},
                failure_example={"error": "Operation failed.", "exit_code": 1},
                presentation=ToolPresentation(
                    label=label,
                    category=domain.capitalize(),
                    action_label=f"Run {label}",
                    progress_label=f"Running {label}",
                    icon="tool",
                ),
                binding=_binding_for(name),
                surfaces=frozenset(surfaces),
                migration_state=migration_state,
            )
        )

    registry = ToolRegistry(
        definitions,
        allowed_legacy_names=LEGACY_UNCLASSIFIED_TOOL_NAMES,
    )
    return registry
