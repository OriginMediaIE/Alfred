"""Strict contract coverage for the incremental SAFE-002 tool registry."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import math

import pytest

from src.tool_registry import (
    AuditBehavior,
    BUILTIN_TOOL_NAMES,
    CLASSIFIED_TOOL_NAMES,
    ConfirmationPolicy,
    IdempotencyMode,
    LEGACY_UNCLASSIFIED_TOOL_NAMES,
    MigrationState,
    PLAN_MODE_ALLOWED_TOOL_NAMES,
    RegistryValidationError,
    RetryPolicy,
    RiskLevel,
    TOOL_TAGS,
    ToolDefinition,
    ToolPresentation,
    ToolRegistry,
    ToolSurface,
    VerificationMode,
    build_builtin_registry,
)


EXPECTED_BUILTIN_TOOL_NAMES = frozenset(
    {
        "adopt_served_model",
        "ai_draft_email_reply",
        "api_call",
        "app_api",
        "archive_email",
        "ask_teacher",
        "ask_user",
        "bash",
        "bulk_email",
        "cancel_download",
        "chat_with_model",
        "create_document",
        "create_google_calendar_event",
        "create_google_calendar_hold",
        "create_meeting",
        "create_session",
        "delete_email",
        "delete_gmail",
        "delete_google_calendar_event",
        "delete_meeting",
        "delete_work",
        "download_attachment",
        "download_gmail_attachment",
        "download_model",
        "draft_email",
        "draft_email_reply",
        "edit_document",
        "edit_file",
        "edit_image",
        "generate_image",
        "get_workspace",
        "glob",
        "grep",
        "list_cached_models",
        "list_cookbook_servers",
        "list_downloads",
        "list_email_accounts",
        "list_emails",
        "list_models",
        "list_serve_presets",
        "list_served_models",
        "list_sessions",
        "ls",
        "manage_bg_jobs",
        "manage_calendar",
        "manage_gmail_draft",
        "manage_contact",
        "manage_documents",
        "manage_endpoints",
        "manage_mcp",
        "manage_memory",
        "manage_notes",
        "manage_research",
        "manage_session",
        "manage_settings",
        "manage_skills",
        "manage_tasks",
        "manage_tokens",
        "manage_work",
        "approve_meeting_action_item",
        "request_meeting_transcription",
        "save_meeting_knowledge",
        "search_meetings",
        "manage_webhooks",
        "mark_email_read",
        "modify_gmail_message",
        "pipeline",
        "python",
        "query_gmail",
        "query_google_calendar",
        "query_work",
        "read_email",
        "read_file",
        "reply_to_email",
        "resolve_contact",
        "respond_google_calendar_invitation",
        "search_chats",
        "search_emails",
        "search_hf_models",
        "send_email",
        "send_gmail",
        "send_to_session",
        "serve_model",
        "serve_preset",
        "stop_served_model",
        "suggest_document",
        "tail_serve_output",
        "trigger_research",
        "ui_control",
        "update_document",
        "update_google_calendar_attendees",
        "update_google_calendar_event",
        "update_plan",
        "vault_get",
        "vault_search",
        "vault_unlock",
        "web_fetch",
        "web_search",
        "write_file",
        "query_knowledge",
        "manage_knowledge",
        "delete_knowledge",
        "query_dashboard",
        "query_automations",
        "manage_automation",
        "delete_automation",
        "query_life",
        "manage_life",
        "delete_life",
    }
)

EXPECTED_CLASSIFIED_TOOL_NAMES = EXPECTED_BUILTIN_TOOL_NAMES

EXPECTED_PLAN_MODE_ALLOWED_TOOL_NAMES = frozenset(
    {
        "get_workspace",
        "glob",
        "grep",
        "list_cached_models",
        "list_cookbook_servers",
        "list_downloads",
        "list_email_accounts",
        "list_emails",
        "list_models",
        "list_serve_presets",
        "list_served_models",
        "list_sessions",
        "ls",
        "query_work",
        "query_gmail",
        "query_google_calendar",
        "search_meetings",
        "query_knowledge",
        "query_dashboard",
        "query_automations",
        "query_life",
        "read_email",
        "read_file",
        "resolve_contact",
        "search_chats",
        "search_emails",
        "search_hf_models",
        "web_fetch",
        "web_search",
    }
)


def _definition(
    name: str,
    *,
    aliases: tuple[str, ...] = (),
    risk: RiskLevel = RiskLevel.LEVEL_0,
    confirmation: ConfirmationPolicy = ConfirmationPolicy.NEVER,
    attempts: int = 1,
    idempotency: IdempotencyMode = IdempotencyMode.READ_ONLY,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        aliases=aliases,
        description="A test-only read operation.",
        domain="test",
        input_schema={"type": "object", "properties": {}},
        output_schema={
            "type": "object",
            "properties": {"output": {"type": "string"}},
        },
        permissions=frozenset({"test.read"}),
        risk=risk,
        confirmation=confirmation,
        reversible=False,
        timeout_seconds=10,
        retry=RetryPolicy(max_attempts=attempts),
        idempotency=idempotency,
        idempotency_key_fields=(),
        audit_behavior=AuditBehavior.REDACTED,
        audit_fields=("tool_name", "owner", "outcome"),
        compensation="not_applicable",
        verification=VerificationMode.RESULT_SCHEMA,
        success_example={"output": "ok"},
        failure_example={"error": "failed", "exit_code": 1},
        presentation=ToolPresentation(
            label="Test",
            category="Test",
            action_label="Run test",
            progress_label="Running test",
            icon="tool",
        ),
        binding="test:read",
        surfaces=frozenset({ToolSurface.INTERNAL}),
        migration_state=MigrationState.TYPED,
    )


def test_golden_inventory_accounts_for_every_current_builtin_capability() -> None:
    registry = build_builtin_registry()

    assert BUILTIN_TOOL_NAMES == EXPECTED_BUILTIN_TOOL_NAMES
    assert registry.names() == EXPECTED_BUILTIN_TOOL_NAMES
    assert len(registry) == 109


def test_plan_mode_compatibility_allowlist_is_frozen_and_complete() -> None:
    disabled = BUILTIN_TOOL_NAMES - PLAN_MODE_ALLOWED_TOOL_NAMES

    assert PLAN_MODE_ALLOWED_TOOL_NAMES == EXPECTED_PLAN_MODE_ALLOWED_TOOL_NAMES
    assert len(PLAN_MODE_ALLOWED_TOOL_NAMES) == 29
    assert PLAN_MODE_ALLOWED_TOOL_NAMES <= BUILTIN_TOOL_NAMES
    assert not PLAN_MODE_ALLOWED_TOOL_NAMES & disabled
    assert PLAN_MODE_ALLOWED_TOOL_NAMES | disabled == BUILTIN_TOOL_NAMES
    assert {"edit_file", "vault_search", "vault_get", "vault_unlock"} <= disabled


def test_plan_mode_projection_pins_policy_migration_debt() -> None:
    registry = build_builtin_registry()
    legacy_allowed = {
        name
        for name in PLAN_MODE_ALLOWED_TOOL_NAMES
        if registry.resolve(name).migration_state is MigrationState.LEGACY_UNCLASSIFIED
    }

    assert legacy_allowed == set()
    assert "ask_teacher" not in PLAN_MODE_ALLOWED_TOOL_NAMES
    assert "chat_with_model" not in PLAN_MODE_ALLOWED_TOOL_NAMES
    assert "tail_serve_output" not in PLAN_MODE_ALLOWED_TOOL_NAMES
    assert registry.resolve("tail_serve_output").migration_state is MigrationState.TYPED


def test_surface_projections_preserve_exposure_without_advertising_vault() -> None:
    registry = build_builtin_registry()

    assert registry.names_for_surface(ToolSurface.FENCE) == TOOL_TAGS
    assert registry.names_for_surface(ToolSurface.INTERNAL) == BUILTIN_TOOL_NAMES
    assert not {
        "vault_search",
        "vault_get",
        "vault_unlock",
    } & registry.names_for_surface(ToolSurface.FENCE)

    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS

    native_names = {
        schema["function"]["name"] for schema in FUNCTION_TOOL_SCHEMAS
    }
    assert registry.names_for_surface(ToolSurface.NATIVE) == native_names


def test_definition_and_nested_contract_data_are_immutable() -> None:
    registry = build_builtin_registry()
    definition = registry.resolve("read_file")

    with pytest.raises(FrozenInstanceError):
        definition.description = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        definition.input_schema["type"] = "array"  # type: ignore[index]
    with pytest.raises(TypeError):
        definition.input_schema["properties"]["path"]["type"] = "integer"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        registry._definitions = ()  # type: ignore[misc]


def test_registry_alias_resolution_respects_requested_surface() -> None:
    definition = _definition("canonical", aliases=("compat",))
    registry = ToolRegistry((definition,))

    assert registry.resolve("compat") is definition
    assert registry.resolve("compat", surface=ToolSurface.INTERNAL) is definition
    with pytest.raises(KeyError, match="not available"):
        registry.resolve("compat", surface=ToolSurface.NATIVE)

    assert registry.definitions_for_surface(ToolSurface.INTERNAL) == (definition,)
    assert registry.definitions_for_surface(ToolSurface.NATIVE) == ()


@pytest.mark.parametrize(
    "definitions, match",
    [
        ((_definition("duplicate"), _definition("duplicate")), "duplicate"),
        (
            (
                _definition("first", aliases=("shared",)),
                _definition("second", aliases=("shared",)),
            ),
            "alias",
        ),
        (
            (
                _definition("first", aliases=("second",)),
                _definition("second"),
            ),
            "collision",
        ),
    ],
)
def test_registry_rejects_duplicate_names_and_aliases(
    definitions: tuple[ToolDefinition, ...],
    match: str,
) -> None:
    with pytest.raises(RegistryValidationError, match=match):
        ToolRegistry(definitions)


@pytest.mark.parametrize(
    "definition, match",
    [
        (
            _definition(
                "unsafe_level_3",
                risk=RiskLevel.LEVEL_3,
                confirmation=ConfirmationPolicy.REQUIRED,
                idempotency=IdempotencyMode.NONE,
            ),
            "Level 3",
        ),
        (
            _definition(
                "unsafe_level_2",
                risk=RiskLevel.LEVEL_2,
                confirmation=ConfirmationPolicy.NEVER,
                idempotency=IdempotencyMode.NONE,
            ),
            "Level 2",
        ),
        (
            _definition(
                "unsafe_retry",
                risk=RiskLevel.LEVEL_1,
                confirmation=ConfirmationPolicy.TRUSTED_ONLY,
                attempts=2,
                idempotency=IdempotencyMode.NONE,
            ),
            "retry",
        ),
    ],
)
def test_registry_rejects_unsafe_policy_combinations(
    definition: ToolDefinition,
    match: str,
) -> None:
    with pytest.raises(RegistryValidationError, match=match):
        ToolRegistry((definition,))


@pytest.mark.parametrize(
    "change, match",
    [
        ({"name": "Bad Name"}, "name"),
        ({"name": "mcp__reserved"}, "reserved"),
        ({"input_schema": {"type": "array"}}, "input schema"),
        ({"output_schema": {"type": "string"}}, "output schema"),
        ({"timeout_seconds": 0}, "timeout"),
        ({"timeout_seconds": True}, "timeout"),
        ({"timeout_seconds": math.inf}, "timeout"),
        ({"retry": RetryPolicy(max_attempts=True)}, "retry"),
        ({"retry": RetryPolicy(max_attempts=6)}, "retry"),
        ({"binding": ""}, "binding"),
    ],
)
def test_registry_rejects_malformed_definition_fields(
    change: dict,
    match: str,
) -> None:
    values = _definition("valid").as_init_dict()
    values.update(change)

    with pytest.raises(RegistryValidationError, match=match):
        ToolRegistry((ToolDefinition(**values),))


def test_registry_rejects_idempotency_keys_absent_from_input_schema() -> None:
    values = _definition("keyed_write").as_init_dict()
    values.update(
        {
            "risk": RiskLevel.LEVEL_2,
            "confirmation": ConfirmationPolicy.REQUIRED,
            "idempotency": IdempotencyMode.LOCAL_KEY,
            "idempotency_key_fields": ("request_id",),
        }
    )

    with pytest.raises(RegistryValidationError, match="idempotency key field"):
        ToolRegistry((ToolDefinition(**values),))


@pytest.mark.parametrize(
    "bad_value",
    [
        {1: {"type": "string"}},
        {"bad": object()},
        {"bad": math.inf},
    ],
)
def test_schema_contract_rejects_non_json_values(bad_value: dict) -> None:
    values = _definition("bad_json").as_init_dict()
    values["input_schema"] = {
        "type": "object",
        "properties": bad_value,
    }

    with pytest.raises(RegistryValidationError, match="JSON"):
        ToolDefinition(**values)


def test_definition_copies_caller_owned_nested_schema() -> None:
    schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
    }
    values = _definition("copied").as_init_dict()
    values["input_schema"] = schema
    definition = ToolDefinition(**values)

    schema["properties"]["query"]["type"] = "integer"
    assert definition.input_schema["properties"]["query"]["type"] == "string"


def test_phase_two_registry_has_no_legacy_policy_debt() -> None:
    registry = build_builtin_registry()

    assert CLASSIFIED_TOOL_NAMES == EXPECTED_CLASSIFIED_TOOL_NAMES
    assert LEGACY_UNCLASSIFIED_TOOL_NAMES == frozenset()
    assert registry.legacy_debt == frozenset()
    assert all(
        definition.migration_state is MigrationState.TYPED
        for definition in registry
    )
    registry.validate(allow_legacy=False)


def test_tail_diagnostics_are_scoped_redacted_and_admin_gated() -> None:
    definition = build_builtin_registry().resolve("tail_serve_output")

    assert definition.permissions == frozenset({"models.diagnostics.read"})
    assert definition.risk is RiskLevel.LEVEL_0
    assert definition.confirmation is ConfirmationPolicy.NEVER
    assert definition.audit_behavior is AuditBehavior.REDACTED

    from src.tool_security import is_public_blocked_tool

    assert is_public_blocked_tool("tail_serve_output") is True


def test_email_operations_have_operation_level_risk_and_scopes() -> None:
    registry = build_builtin_registry()

    expectations = {
        "draft_email": (RiskLevel.LEVEL_1, "email.draft", True),
        "draft_email_reply": (RiskLevel.LEVEL_1, "email.draft", True),
        "ai_draft_email_reply": (RiskLevel.LEVEL_2, "email.draft", False),
        "send_email": (RiskLevel.LEVEL_2, "email.send", False),
        "reply_to_email": (RiskLevel.LEVEL_2, "email.send", False),
        "archive_email": (RiskLevel.LEVEL_1, "email.archive", True),
        "mark_email_read": (RiskLevel.LEVEL_1, "email.modify", True),
        "download_attachment": (
            RiskLevel.LEVEL_1,
            "email.attachments.download",
            True,
        ),
        "delete_email": (RiskLevel.LEVEL_3, "email.delete", False),
        "bulk_email": (RiskLevel.LEVEL_3, "email.bulk", False),
    }
    for name, (risk, permission, reversible) in expectations.items():
        definition = registry.resolve(name)
        assert definition.migration_state is MigrationState.TYPED
        assert definition.risk is risk
        assert definition.permissions == frozenset({permission})
        assert definition.reversible is reversible
        assert definition.verification is VerificationMode.READ_BACK

    assert registry.resolve("draft_email").confirmation is ConfirmationPolicy.TRUSTED_ONLY
    assert registry.resolve("send_email").confirmation is ConfirmationPolicy.REQUIRED
    assert registry.resolve("delete_email").confirmation is ConfirmationPolicy.ALWAYS
    assert registry.resolve("bulk_email").confirmation is ConfirmationPolicy.ALWAYS


def test_personal_work_tools_are_split_by_operation_risk() -> None:
    registry = build_builtin_registry()

    query = registry.resolve("query_work")
    manage = registry.resolve("manage_work")
    delete = registry.resolve("delete_work")

    assert query.risk is RiskLevel.LEVEL_0
    assert query.permissions == frozenset({"tasks.read"})
    assert query.idempotency is IdempotencyMode.READ_ONLY
    assert manage.risk is RiskLevel.LEVEL_1
    assert manage.permissions == frozenset({"tasks.write"})
    assert manage.reversible is True
    assert manage.confirmation is ConfirmationPolicy.TRUSTED_ONLY
    assert delete.risk is RiskLevel.LEVEL_3
    assert delete.permissions == frozenset({"tasks.delete"})
    assert delete.confirmation is ConfirmationPolicy.ALWAYS


def test_google_workspace_tools_are_split_by_external_effect() -> None:
    registry = build_builtin_registry()

    assert registry.resolve("query_gmail").risk is RiskLevel.LEVEL_0
    assert registry.resolve("query_google_calendar").risk is RiskLevel.LEVEL_0
    assert registry.resolve("manage_gmail_draft").risk is RiskLevel.LEVEL_1
    assert registry.resolve("create_google_calendar_hold").risk is RiskLevel.LEVEL_1
    assert registry.resolve("send_gmail").risk is RiskLevel.LEVEL_2
    assert registry.resolve("create_google_calendar_event").risk is RiskLevel.LEVEL_2
    assert registry.resolve("update_google_calendar_event").risk is RiskLevel.LEVEL_2
    assert registry.resolve("delete_gmail").risk is RiskLevel.LEVEL_3
    assert registry.resolve("delete_google_calendar_event").risk is RiskLevel.LEVEL_3
    assert registry.resolve("delete_google_calendar_event").permissions == frozenset(
        {"calendar.delete"}
    )


def test_new_legacy_debt_cannot_sneak_outside_the_frozen_allowlist() -> None:
    values = _definition("new_unclassified").as_init_dict()
    values.update(
        {
            "risk": RiskLevel.LEVEL_3,
            "confirmation": ConfirmationPolicy.ALWAYS,
            "permissions": frozenset({"legacy.unclassified"}),
            "verification": VerificationMode.INDETERMINATE,
            "idempotency": IdempotencyMode.NONE,
            "migration_state": MigrationState.LEGACY_UNCLASSIFIED,
        }
    )

    with pytest.raises(RegistryValidationError, match="frozen legacy"):
        ToolRegistry(
            (ToolDefinition(**values),),
            allowed_legacy_names=LEGACY_UNCLASSIFIED_TOOL_NAMES,
        )


def test_every_builtin_has_complete_non_policy_contract_fields() -> None:
    registry = build_builtin_registry()

    for definition in registry:
        assert definition.description.strip()
        assert definition.domain.strip()
        assert definition.input_schema["type"] == "object"
        assert definition.output_schema["type"] == "object"
        assert definition.timeout_seconds > 0
        assert definition.retry.max_attempts >= 1
        assert definition.audit_fields
        assert definition.compensation.strip()
        assert definition.binding.strip()
        assert definition.presentation.label.strip()
        assert definition.success_example
        assert definition.failure_example
