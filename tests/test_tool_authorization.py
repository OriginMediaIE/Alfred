"""Registry authority and fail-closed execution-boundary tests."""

from __future__ import annotations

from types import SimpleNamespace
from dataclasses import replace

import pytest

from src.tool_authorization import (
    ExecutionAuthority,
    PolicyDecisionKind,
    ResolvedToolIdentity,
    all_typed_tool_permissions,
    evaluate_tool_policy,
    permissions_for_owner,
)
from src.tool_registry import (
    BUILTIN_TOOL_NAMES,
    MigrationState,
    PLAN_MODE_ALLOWED_TOOL_NAMES,
    ToolSurface,
    build_builtin_registry,
)


def _authority(*permissions: str, surface: ToolSurface = ToolSurface.FENCE):
    return ExecutionAuthority(
        owner="alice",
        permissions=frozenset(permissions),
        surface=surface,
    )


def _decision(name: object, *permissions: str, surface: ToolSurface | None = None):
    if surface is None:
        surface = (
            ToolSurface.DYNAMIC_MCP
            if isinstance(name, str) and name.startswith("mcp__")
            else ToolSurface.FENCE
        )
    return evaluate_tool_policy(
        name,
        authority=_authority(*permissions, surface=surface),
    )


def test_every_plan_mode_capability_is_now_typed() -> None:
    registry = build_builtin_registry()

    assert all(
        registry.resolve(name).migration_state is MigrationState.TYPED
        for name in PLAN_MODE_ALLOWED_TOOL_NAMES
    )


def test_level_zero_requires_its_exact_permission() -> None:
    denied = _decision("read_file")
    allowed = _decision("read_file", "files.read")

    assert denied.kind is PolicyDecisionKind.DENY
    assert denied.code == "missing_permission"
    assert denied.missing_permissions == frozenset({"files.read"})
    assert allowed.kind is PolicyDecisionKind.ALLOW
    assert allowed.may_execute is True


def test_newly_classified_broad_tool_requires_its_scope_and_approval() -> None:
    denied = _decision("edit_image")
    decision = _decision("edit_image", "images.edit")

    assert denied.kind is PolicyDecisionKind.DENY
    assert denied.code == "missing_permission"
    assert decision.kind is PolicyDecisionKind.REQUIRE_APPROVAL
    assert decision.code == "approval_required"
    assert decision.may_execute is False


def test_level_three_requires_approval_even_when_scope_exists() -> None:
    decision = _decision("bash", "shell.execute")

    assert decision.kind is PolicyDecisionKind.REQUIRE_APPROVAL
    assert decision.code == "approval_required"


@pytest.mark.parametrize(
    "tool,permission,expected_risk",
    (
        ("draft_email", "email.draft", 1),
        ("send_email", "email.send", 2),
        ("archive_email", "email.archive", 1),
        ("delete_email", "email.delete", 3),
        ("bulk_email", "email.bulk", 3),
    ),
)
def test_email_mutations_require_their_exact_scope_and_approval(
    tool,
    permission,
    expected_risk,
) -> None:
    missing = _decision(tool)
    allowed_scope = _decision(tool, permission)

    assert missing.kind is PolicyDecisionKind.DENY
    assert missing.code == "missing_permission"
    assert allowed_scope.kind is PolicyDecisionKind.REQUIRE_APPROVAL
    assert int(allowed_scope.definition.risk) == expected_risk


def test_email_delete_cannot_be_downgraded_by_using_qualified_alias() -> None:
    bare = _decision("delete_email", "email.delete")
    qualified = _decision(
        "mcp__email__delete_email",
        "email.delete",
        surface=ToolSurface.DYNAMIC_MCP,
    )

    assert qualified.kind is bare.kind is PolicyDecisionKind.REQUIRE_APPROVAL
    assert qualified.definition is bare.definition
    assert int(qualified.definition.risk) == 3


def test_malformed_binding_does_not_resolve_to_a_dispatch_target() -> None:
    from src.tool_execution import _resolve_runtime_binding

    definition = replace(
        build_builtin_registry().resolve("read_file"),
        binding="legacy_dispatch:not_read_file",
    )
    identity = ResolvedToolIdentity(
        requested_name="read_file",
        canonical_name="read_file",
        definition=definition,
        surface=ToolSurface.FENCE,
    )

    assert _resolve_runtime_binding(identity) is None


def test_qualified_builtin_email_read_resolves_to_static_policy() -> None:
    decision = _decision("mcp__email__list_emails", "email.read")

    assert decision.kind is PolicyDecisionKind.ALLOW
    assert decision.canonical_name == "list_emails"
    assert decision.definition is build_builtin_registry().resolve("list_emails")


def test_qualified_image_identity_is_derived_from_static_binding() -> None:
    decision = _decision(
        "mcp__image_gen__generate_image",
        "images.generate",
    )

    assert decision.code == "approval_required"
    assert decision.kind is PolicyDecisionKind.REQUIRE_APPROVAL
    assert decision.canonical_name == "generate_image"


def test_internal_only_tool_is_not_callable_from_a_model_surface() -> None:
    decision = _decision("vault_search", "legacy.unclassified")

    assert decision.kind is PolicyDecisionKind.DENY
    assert decision.code == "surface_not_allowed"
    assert decision.canonical_name == "vault_search"


@pytest.mark.parametrize(
    "name,code",
    (
        ("mcp__third_party__list_items", "dynamic_mcp_unregistered"),
        ("mcp__email__not_real", "dynamic_mcp_unregistered"),
        ("not_a_tool", "unknown_tool"),
        (None, "invalid_tool_name"),
    ),
)
def test_unknown_and_unregistered_names_fail_closed(name, code) -> None:
    decision = _decision(name)

    assert decision.kind is PolicyDecisionKind.DENY
    assert decision.code == code


class _FakeAuth:
    is_configured = True

    def __init__(self, *, admin: bool, denied=()):
        self.users = {"alice": {}}
        self._admin = admin
        self._denied = list(denied)

    def is_admin(self, owner):
        return owner == "alice" and self._admin

    def get_privileges(self, owner):
        assert owner == "alice"
        return {
            "can_use_agent": True,
            "can_use_research": True,
            "denied_tool_permissions": self._denied,
        }


def test_admin_role_grants_scopes_but_token_scope_is_an_extra_ceiling(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    auth = _FakeAuth(admin=True)

    browser = permissions_for_owner("alice", auth_manager=auth)
    token = permissions_for_owner(
        "alice",
        auth_manager=auth,
        api_token_scopes={"chat", "email:read"},
    )
    cookbook_token = permissions_for_owner(
        "alice",
        auth_manager=auth,
        api_token_scopes={"cookbook:read"},
    )

    assert browser == all_typed_tool_permissions()
    assert "shell.execute" in browser
    assert token == {
        "conversation.interact",
        "conversation.plan",
        "email.read",
    }
    assert "shell.execute" not in token
    assert cookbook_token == {
        "models.cache.read",
        "models.catalog.read",
        "models.downloads.read",
        "models.infrastructure.read",
        "models.presets.read",
        "models.runtime.read",
    }


def test_admin_capability_opt_out_is_an_authority_ceiling(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    auth = _FakeAuth(admin=True, denied={"email.send", "shell.execute"})

    granted = permissions_for_owner("alice", auth_manager=auth)

    assert "email.read" in granted
    assert "email.send" not in granted
    assert "shell.execute" not in granted


def test_email_token_scopes_do_not_widen_the_owners_permissions(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    auth = _FakeAuth(admin=True, denied={"email.send"})

    draft = permissions_for_owner(
        "alice", auth_manager=auth, api_token_scopes={"email:draft"}
    )
    send = permissions_for_owner(
        "alice", auth_manager=auth, api_token_scopes={"email:send"}
    )

    assert draft == {"email.read", "email.draft"}
    assert send == {"email.read", "email.draft"}
    assert "email.send" not in send


def test_regular_user_permissions_preserve_public_backstop_and_individual_deny(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    auth = _FakeAuth(admin=False, denied={"models.invoke"})

    granted = permissions_for_owner("alice", auth_manager=auth)

    assert "conversation.read" in granted
    assert "models.catalog.read" in granted
    assert "research.web" in granted
    assert {"tasks.read", "tasks.write", "tasks.delete"} <= granted
    assert "models.invoke" not in granted
    assert "files.read" not in granted
    assert "email.read" not in granted
    assert "contacts.read" not in granted
    assert "models.runtime.read" not in granted
    assert "models.cache.read" not in granted
    assert "models.downloads.read" not in granted
    assert "models.infrastructure.read" not in granted
    assert "models.presets.read" not in granted


def test_missing_configured_owner_has_no_permissions(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    auth = _FakeAuth(admin=True)

    assert permissions_for_owner(None, auth_manager=auth) == frozenset()
    assert permissions_for_owner("bob", auth_manager=auth) == frozenset()


def test_missing_trusted_auth_provider_fails_closed_without_constructing_one(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")

    def unexpected_constructor():
        raise AssertionError("tool execution constructed a fresh AuthManager")

    monkeypatch.setattr("core.auth.AuthManager", unexpected_constructor)

    assert permissions_for_owner("alice", auth_manager=None) == frozenset()


def test_every_static_registry_binding_resolves_to_one_runtime_path() -> None:
    from src.tool_execution import _resolve_runtime_binding

    assert build_builtin_registry().names() == BUILTIN_TOOL_NAMES
    assert all(
        _resolve_runtime_binding(
            ResolvedToolIdentity(
                requested_name=definition.name,
                canonical_name=definition.name,
                definition=definition,
                surface=ToolSurface.INTERNAL,
            )
        )
        is not None
        for definition in build_builtin_registry()
    )


@pytest.mark.asyncio
async def test_executor_never_invokes_unknown_or_dynamic_mcp(monkeypatch) -> None:
    import src.tool_execution as execution

    class UnexpectedMcp:
        async def call_tool(self, *_args, **_kwargs):
            raise AssertionError("denied call reached MCP")

    monkeypatch.setattr(execution, "get_mcp_manager", lambda: UnexpectedMcp())
    monkeypatch.setattr(execution, "_owner_is_admin", lambda _owner: True)
    monkeypatch.setattr(execution, "is_public_blocked_tool", lambda _name: False)

    for name in ("not_a_tool", "mcp__third_party__list_items"):
        description, result = await execution.execute_tool_block(
            SimpleNamespace(tool_type=name, content="{}"),
            authority=_authority(
                *all_typed_tool_permissions(),
                surface=(
                    ToolSurface.DYNAMIC_MCP
                    if name.startswith("mcp__")
                    else ToolSurface.FENCE
                ),
            ),
        )
        assert description.endswith("BLOCKED")
        assert result["policy_decision"] == "deny"


@pytest.mark.asyncio
async def test_denied_identity_imports_no_handler_modules(monkeypatch) -> None:
    import builtins
    import src.tool_execution as execution

    real_import = builtins.__import__
    imported_executable_module = False

    def guarded_import(name, *args, **kwargs):
        nonlocal imported_executable_module
        if name in {"src.agent_tools", "src.tool_implementations"}:
            imported_executable_module = True
            raise AssertionError(f"denied call imported {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    _, result = await execution.execute_tool_block(
        SimpleNamespace(tool_type="not_a_tool", content="{}"),
        authority=_authority(*all_typed_tool_permissions()),
    )

    assert result["policy_code"] == "unknown_tool"
    assert imported_executable_module is False


@pytest.mark.asyncio
async def test_executor_rejects_owner_authority_mismatch_before_dispatch() -> None:
    import src.tool_execution as execution

    _, result = await execution.execute_tool_block(
        SimpleNamespace(tool_type="read_file", content="note.txt"),
        owner="mallory",
        authority=_authority("files.read"),
    )

    assert result["policy_code"] == "authority_owner_mismatch"
    assert result["policy_decision"] == "deny"


@pytest.mark.asyncio
async def test_executor_returns_structured_approval_without_invoking_handler(
    monkeypatch,
) -> None:
    import src.agent_tools as agent_tools
    import src.tool_execution as execution

    async def unexpected_handler(*_args, **_kwargs):
        raise AssertionError("approval-required call reached handler")

    monkeypatch.setitem(agent_tools.TOOL_HANDLERS, "bash", unexpected_handler)
    monkeypatch.setattr(execution, "_owner_is_admin", lambda _owner: True)
    monkeypatch.setattr(execution, "is_public_blocked_tool", lambda _name: False)

    description, result = await execution.execute_tool_block(
        SimpleNamespace(tool_type="bash", content="echo unsafe"),
        authority=_authority("shell.execute"),
    )

    assert description == "bash: APPROVAL REQUIRED"
    assert result["policy_decision"] == "require_approval"
    assert result["tool_name"] == "bash"
    assert result["tool_version"] == 1
    assert result["risk_level"] == 3


@pytest.mark.asyncio
async def test_executor_allows_scoped_typed_email_read(monkeypatch) -> None:
    import src.tool_execution as execution

    class RecordingMcp:
        def __init__(self):
            self.calls = []

        async def call_tool(self, name, args):
            self.calls.append((name, args))
            return {"stdout": "mail", "stderr": "", "exit_code": 0}

    mcp = RecordingMcp()
    monkeypatch.setattr(execution, "get_mcp_manager", lambda: mcp)
    monkeypatch.setattr(execution, "_owner_is_admin", lambda _owner: True)
    monkeypatch.setattr(execution, "is_public_blocked_tool", lambda _name: False)

    _, result = await execution.execute_tool_block(
        SimpleNamespace(tool_type="list_email_accounts", content=""),
        authority=_authority("email.read"),
    )

    assert result["exit_code"] == 0
    assert mcp.calls == [
        (
            "mcp__email__list_email_accounts",
            {"_odysseus_owner": "alice"},
        )
    ]
