"""Registry-driven authorization decisions for agent tool execution.

This module is deliberately free of handler imports.  It canonicalizes a
requested static capability, evaluates its typed registry policy, and returns a
typed allow/deny/approval decision.  The executor remains responsible for
proving that the declared binding is live and for enforcing the decision before
calling it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from types import MappingProxyType
from typing import Iterable, Mapping, Optional

from src.tool_registry import (
    ConfirmationPolicy,
    MigrationState,
    RiskLevel,
    ToolDefinition,
    ToolRegistry,
    ToolSurface,
    build_builtin_registry,
)


class PolicyDecisionKind(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class ExecutionOrigin(str, Enum):
    """Trusted workflow that caused a tool proposal.

    This is intentionally separate from :class:`ToolSurface`: a scheduled
    workflow may use native function calling or a fenced compatibility syntax,
    and an interactive chat may call a statically registered MCP binding.
    """

    INTERACTIVE_CHAT = "interactive_chat"
    SCHEDULED_AUTOMATION = "scheduled_automation"
    BACKGROUND_MONITOR = "background_monitor"
    SKILL_WORKFLOW = "skill_workflow"
    APPROVAL_CENTRE = "approval_centre"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class ExecutionAuthority:
    """Trusted request context used to evaluate a tool call.

    The authority is constructed by an application ingress, never from tool
    arguments.  Keeping principal, permission ceiling, and ingress surface in
    one immutable value prevents model-controlled keyword arguments from
    widening a call after it has been parsed.
    """

    owner: Optional[str]
    permissions: frozenset[str]
    surface: ToolSurface
    api_token_scopes: Optional[frozenset[str]] = None
    origin: ExecutionOrigin = ExecutionOrigin.INTERNAL

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "permissions",
            frozenset(str(permission) for permission in self.permissions),
        )
        if self.api_token_scopes is not None:
            object.__setattr__(
                self,
                "api_token_scopes",
                frozenset(str(scope) for scope in self.api_token_scopes),
            )
        if not isinstance(self.surface, ToolSurface):
            raise TypeError("execution authority requires a ToolSurface")
        if not isinstance(self.origin, ExecutionOrigin):
            raise TypeError("execution authority requires an ExecutionOrigin")


@dataclass(frozen=True, slots=True)
class ResolvedToolIdentity:
    """Canonical static identity resolved before any handler is imported."""

    requested_name: str
    canonical_name: str
    definition: ToolDefinition
    surface: ToolSurface


@dataclass(frozen=True, slots=True)
class ToolPolicyDecision:
    """One immutable policy evaluation result.

    ``definition`` is present only after successful canonical registry lookup.
    A caller must check :attr:`may_execute`; neither ``DENY`` nor
    ``REQUIRE_APPROVAL`` authorizes a handler call.
    """

    kind: PolicyDecisionKind
    code: str
    reason: str
    requested_name: str
    canonical_name: Optional[str] = None
    definition: Optional[ToolDefinition] = None
    missing_permissions: frozenset[str] = frozenset()
    surface: Optional[ToolSurface] = None

    @property
    def may_execute(self) -> bool:
        return self.kind is PolicyDecisionKind.ALLOW

    def as_result(self) -> dict:
        definition = self.definition
        result = {
            "error": self.reason,
            "exit_code": 1,
            "blocked": True,
            "policy_decision": self.kind.value,
            "policy_code": self.code,
            "requested_tool": self.requested_name,
        }
        if self.canonical_name:
            result["tool_name"] = self.canonical_name
        if definition is not None:
            result.update(
                {
                    "tool_version": definition.version,
                    "risk_level": int(definition.effective_risk),
                    "required_permissions": sorted(definition.permissions),
                    "tool_surface": self.surface.value if self.surface else None,
                }
            )
        if self.missing_permissions:
            result["missing_permissions"] = sorted(self.missing_permissions)
        return result


_TOKEN_SCOPE_PERMISSIONS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        # ``chat`` authorizes the conversation transport, not arbitrary data
        # access.  Request-local interaction/plan controls are the only tool
        # capabilities inherited from it.
        "chat": frozenset({"conversation.interact", "conversation.plan"}),
        "email:read": frozenset({"email.read"}),
        "email:draft": frozenset({"email.read", "email.draft"}),
        "email:send": frozenset(
            {"email.read", "email.draft", "email.send"}
        ),
        "email:archive": frozenset(
            {"email.read", "email.archive", "email.modify"}
        ),
        "email:attachments": frozenset(
            {"email.read", "email.attachments.download"}
        ),
        "cookbook:read": frozenset(
            {
                "models.cache.read",
                "models.catalog.read",
                "models.downloads.read",
                "models.infrastructure.read",
                "models.presets.read",
                "models.runtime.read",
            }
        ),
        "calendar:read": frozenset({"calendar.read"}),
        "calendar:write": frozenset({"calendar.read", "calendar.write"}),
        "calendar:delete": frozenset({"calendar.read", "calendar.delete"}),
        "meetings:read": frozenset({"meetings.read"}),
        "meetings:write": frozenset(
            {"meetings.read", "meetings.record", "meetings.transcribe", "meetings.write", "tasks.write", "knowledge.write"}
        ),
        "meetings:delete": frozenset({"meetings.read", "meetings.delete"}),
        "knowledge:read": frozenset({"knowledge.read"}),
        "knowledge:write": frozenset({"knowledge.read", "knowledge.write"}),
        "knowledge:delete": frozenset({"knowledge.read", "knowledge.delete"}),
        "life:read": frozenset({"life.read"}),
        "life:write": frozenset({"life.read", "life.write"}),
        "life:delete": frozenset({"life.read", "life.delete"}),
        "dashboard:read": frozenset({"dashboard.read"}),
        "automations:read": frozenset({"automations.read"}),
        "automations:write": frozenset({"automations.read","automations.write"}),
        "automations:delete": frozenset({"automations.read","automations.delete"}),
    }
)


_PERMISSION_COARSE_PRIVILEGE: Mapping[str, str] = MappingProxyType(
    {
        "conversation.interact": "can_use_agent",
        "conversation.plan": "can_use_agent",
        "conversation.read": "can_use_agent",
        "images.generate": "can_use_agent",
        "models.invoke": "can_use_agent",
        "models.catalog.read": "can_use_research",
        "research.web": "can_use_research",
        "tasks.read": "can_use_agent",
        "tasks.write": "can_use_agent",
        "tasks.delete": "can_use_agent",
        "calendar.read": "can_use_agent",
        "calendar.write": "can_use_agent",
        "calendar.delete": "can_use_agent",
        "meetings.read": "can_use_agent",
        "meetings.record": "can_use_agent",
        "meetings.transcribe": "can_use_agent",
        "meetings.write": "can_use_agent",
        "meetings.delete": "can_use_agent",
        "knowledge.write": "can_use_agent",
        "knowledge.read": "can_use_agent",
        "knowledge.delete": "can_use_agent",
        "life.read": "can_use_agent",
        "life.write": "can_use_agent",
        "life.delete": "can_use_agent",
        "dashboard.read": "can_use_agent",
        "automations.read": "can_use_agent",
        "automations.write": "can_use_agent",
        "automations.delete": "can_use_agent",
        "application.api.call": "can_use_agent",
        "calendar.manage": "can_use_agent",
        "contacts.write": "can_use_agent",
        "conversation.manage": "can_use_agent",
        "conversation.write": "can_use_agent",
        "documents.manage": "can_use_documents",
        "documents.suggest": "can_use_documents",
        "documents.write": "can_use_documents",
        "images.edit": "can_generate_images",
        "interface.control": "can_use_agent",
        "memory.manage": "can_use_agent",
        "models.downloads.cancel": "can_manage_models",
        "models.downloads.write": "can_manage_models",
        "models.pipeline": "can_use_agent",
        "models.runtime.write": "can_manage_models",
        "notes.manage": "can_use_agent",
        "processes.manage": "can_use_bash",
        "research.manage": "can_use_research",
        "research.run": "can_use_research",
        "scheduled_tasks.manage": "can_use_agent",
        "skills.manage": "can_use_agent",
    }
)


@lru_cache(maxsize=1)
def all_typed_tool_permissions() -> frozenset[str]:
    """Every permission currently owned by a typed static definition."""

    return frozenset(
        permission
        for definition in build_builtin_registry()
        if definition.migration_state is MigrationState.TYPED
        for permission in definition.permissions
    )


def _token_permission_ceiling(scopes: Iterable[str]) -> frozenset[str]:
    permissions: set[str] = set()
    for scope in scopes:
        permissions.update(_TOKEN_SCOPE_PERMISSIONS.get(str(scope), ()))
    return frozenset(permissions)


def permissions_for_owner(
    owner: Optional[str],
    *,
    auth_manager=None,
    api_token_scopes: Optional[Iterable[str]] = None,
) -> frozenset[str]:
    """Resolve the current human's typed tool permissions without widening access.

    Existing coarse privileges and the public/admin backstop remain in force
    while the granular permissions UI is introduced.  A configured unknown or
    missing owner fails closed.  API-token scopes are an additional ceiling:
    they can only remove permissions already held by the token owner.
    """

    from src.auth_helpers import _auth_disabled

    registry = build_builtin_registry()
    all_permissions = all_typed_tool_permissions()

    if _auth_disabled():
        granted = set(all_permissions)
    else:
        if auth_manager is None:
            # A tool execution boundary must consume the application-owned
            # auth provider supplied by its trusted ingress.  Constructing a
            # fresh AuthManager here can reload or migrate persisted auth state
            # for every call and lets one streamed turn observe mixed snapshots.
            # Missing trusted context therefore fails closed.
            return frozenset()

        if not getattr(auth_manager, "is_configured", False) or not owner:
            return frozenset()
        try:
            if not owner or owner not in getattr(auth_manager, "users", {}):
                return frozenset()
            is_admin = bool(auth_manager.is_admin(owner))
            privileges = auth_manager.get_privileges(owner) or {}
        except Exception:
            return frozenset()
        if not isinstance(privileges, dict):
            return frozenset()

        if is_admin:
            # Admin status grants scopes, but the policy evaluator below still
            # requires confirmation; role never bypasses risk policy.
            granted = set(all_permissions)
        else:
            from src.tool_security import is_public_blocked_tool

            granted = set()
            for definition in registry:
                if definition.migration_state is not MigrationState.TYPED:
                    continue
                if is_public_blocked_tool(definition.name):
                    continue
                for permission in definition.permissions:
                    privilege = _PERMISSION_COARSE_PRIVILEGE.get(permission)
                    if privilege and privileges.get(privilege, True) is True:
                        granted.add(permission)

        # Capability opt-outs are a ceiling for every role, including admins.
        # Admin status must not silently re-enable a scope the human explicitly
        # disabled; it grants availability, never consent.
        denied = privileges.get("denied_tool_permissions", ())
        if isinstance(denied, (list, tuple, set, frozenset)):
            granted.difference_update(str(item) for item in denied)

    if api_token_scopes is not None:
        granted.intersection_update(_token_permission_ceiling(api_token_scopes))
    return frozenset(granted)


def authority_for_owner(
    owner: Optional[str],
    *,
    surface: ToolSurface,
    auth_manager=None,
    api_token_scopes: Optional[Iterable[str]] = None,
    origin: ExecutionOrigin = ExecutionOrigin.INTERNAL,
) -> ExecutionAuthority:
    """Build immutable authority at a trusted request boundary."""

    scopes = (
        None
        if api_token_scopes is None
        else frozenset(str(scope) for scope in api_token_scopes)
    )
    return ExecutionAuthority(
        owner=owner,
        permissions=permissions_for_owner(
            owner,
            auth_manager=auth_manager,
            api_token_scopes=scopes,
        ),
        surface=surface,
        api_token_scopes=scopes,
        origin=origin,
    )


def _bundled_mcp_aliases(registry: ToolRegistry) -> Mapping[str, str]:
    """Derive qualified bundled aliases from canonical binding metadata."""

    aliases: dict[str, str] = {}
    for definition in registry:
        parts = definition.binding.split(":")
        if len(parts) != 3 or parts[0] != "builtin_mcp":
            continue
        server_id, tool_name = parts[1], parts[2]
        if tool_name != definition.name:
            continue
        aliases[f"mcp__{server_id}__{tool_name}"] = definition.name
    return MappingProxyType(aliases)


def resolve_tool_identity(
    requested_name: object,
    *,
    surface: ToolSurface,
    registry: Optional[ToolRegistry] = None,
) -> ResolvedToolIdentity | ToolPolicyDecision:
    """Resolve one exact canonical identity without loading an implementation."""

    if not isinstance(requested_name, str) or not requested_name:
        return ToolPolicyDecision(
            kind=PolicyDecisionKind.DENY,
            code="invalid_tool_name",
            reason="Tool name is missing or invalid.",
            requested_name="",
            surface=surface,
        )

    registry = registry or build_builtin_registry()
    canonical = requested_name
    if requested_name.startswith("mcp__"):
        canonical = _bundled_mcp_aliases(registry).get(requested_name, "")
        if not canonical:
            # Dynamic MCP definitions require a validated server-scoped
            # overlay.  Until discovery produces one, server descriptions and
            # annotations cannot grant authority.
            return ToolPolicyDecision(
                kind=PolicyDecisionKind.DENY,
                code="dynamic_mcp_unregistered",
                reason="Dynamic MCP tool has no validated permission/risk overlay.",
                requested_name=requested_name,
                surface=surface,
            )

    try:
        definition = registry.resolve(canonical, surface=surface)
    except KeyError:
        # Distinguish a known identity on the wrong ingress from an unknown
        # identity; both deny before any implementation import.
        try:
            known = registry.resolve(canonical)
        except KeyError:
            known = None
        if known is not None:
            return ToolPolicyDecision(
                kind=PolicyDecisionKind.DENY,
                code="surface_not_allowed",
                reason=(
                    f"Tool '{known.name}' is not available on the "
                    f"'{surface.value}' execution surface."
                ),
                requested_name=requested_name,
                canonical_name=known.name,
                definition=known,
                surface=surface,
            )
        return ToolPolicyDecision(
            kind=PolicyDecisionKind.DENY,
            code="unknown_tool",
            reason="Tool is not present in the canonical registry.",
            requested_name=requested_name,
            canonical_name=canonical or None,
            surface=surface,
        )

    return ResolvedToolIdentity(
        requested_name=requested_name,
        canonical_name=definition.name,
        definition=definition,
        surface=surface,
    )


def deny_resolved_tool(
    identity: ResolvedToolIdentity,
    *,
    code: str,
    reason: str,
) -> ToolPolicyDecision:
    """Build a structured request-local denial for a resolved identity."""

    return ToolPolicyDecision(
        kind=PolicyDecisionKind.DENY,
        code=code,
        reason=reason,
        requested_name=identity.requested_name,
        canonical_name=identity.canonical_name,
        definition=identity.definition,
        surface=identity.surface,
    )


def evaluate_resolved_tool_policy(
    identity: ResolvedToolIdentity,
    *,
    authority: ExecutionAuthority,
) -> ToolPolicyDecision:
    """Evaluate a previously resolved identity against immutable authority."""

    definition = identity.definition
    requested = identity.requested_name

    if authority.surface is not identity.surface:
        return deny_resolved_tool(
            identity,
            code="authority_surface_mismatch",
            reason="Execution authority does not match the resolved tool surface.",
        )

    if definition.migration_state is MigrationState.LEGACY_UNCLASSIFIED:
        return ToolPolicyDecision(
            kind=PolicyDecisionKind.DENY,
            code="unclassified_tool",
            reason=(
                f"Tool '{definition.name}' has no classified operation-level policy."
            ),
            requested_name=requested,
            canonical_name=definition.name,
            definition=definition,
            surface=identity.surface,
        )

    missing = definition.permissions - authority.permissions
    if missing:
        return ToolPolicyDecision(
            kind=PolicyDecisionKind.DENY,
            code="missing_permission",
            reason=(
                f"Tool '{definition.name}' requires permission: "
                + ", ".join(sorted(missing))
            ),
            requested_name=requested,
            canonical_name=definition.name,
            definition=definition,
            missing_permissions=frozenset(missing),
            surface=identity.surface,
        )

    confirmation = definition.effective_confirmation
    if confirmation is not ConfirmationPolicy.NEVER:
        return ToolPolicyDecision(
            kind=PolicyDecisionKind.REQUIRE_APPROVAL,
            code="approval_required",
            reason=f"Tool '{definition.name}' requires approval before execution.",
            requested_name=requested,
            canonical_name=definition.name,
            definition=definition,
            surface=identity.surface,
        )

    return ToolPolicyDecision(
        kind=PolicyDecisionKind.ALLOW,
        code="allowed",
        reason="Tool policy allows execution.",
        requested_name=requested,
        canonical_name=definition.name,
        definition=definition,
        surface=identity.surface,
    )


def evaluate_tool_policy(
    requested_name: object,
    *,
    authority: ExecutionAuthority,
    registry: Optional[ToolRegistry] = None,
) -> ToolPolicyDecision:
    """Evaluate one call without invoking its handler.

    Approval evidence is intentionally absent from this interim boundary.  A
    confirmation-required result can only become executable through the future
    durable exact-version approval service, not through a model-supplied flag.
    """

    identity = resolve_tool_identity(
        requested_name,
        surface=authority.surface,
        registry=registry,
    )
    if isinstance(identity, ToolPolicyDecision):
        return identity
    return evaluate_resolved_tool_policy(identity, authority=authority)
