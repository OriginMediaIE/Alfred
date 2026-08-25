"""
tool_execution.py

Tool dispatcher and result formatter for the agent loop.
Routes tool blocks to MCP servers or native implementations.

Extracted from agent_tools.py.
"""

import asyncio
import collections
import contextvars
import importlib
import json
import logging
import os
import pathlib
import re
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional, Tuple



from src.tool_security import (
    BUILTIN_EMAIL_TOOLS,
    email_tool_policy_names,
    is_public_blocked_tool,
    owner_is_admin_or_single_user,
)
from src.tool_policy import ToolPolicy
from src.tool_authorization import (
    ExecutionAuthority,
    PolicyDecisionKind,
    ResolvedToolIdentity,
    ToolPolicyDecision,
    authority_for_owner,
    deny_resolved_tool,
    evaluate_resolved_tool_policy,
    resolve_tool_identity,
)
from src.tool_actions import ActionArgumentError, build_action_envelope
from src.action_verification import (
    prepare_action_verification,
    result_with_verification,
    verification_status_from_result,
    verify_action_result,
)
from src.tool_registry import ToolDefinition, ToolSurface, build_builtin_registry
from src.constants import MAX_OUTPUT_CHARS, MAX_READ_CHARS, MAX_DIFF_LINES, DATA_DIR
from src.tool_utils import _truncate, get_mcp_manager

# Persistent working directory for agent subprocesses.
# The agent never receives the application control-plane data root. Its
# persistent default workspace is a dedicated subtree that cannot contain
# auth, OAuth, database, settings, or encryption-key state.
_AGENT_WORKDIR = str(pathlib.Path(DATA_DIR) / "agent-workspace")



# ---------------------------------------------------------------------------
# Path confinement for read_file / write_file
# ---------------------------------------------------------------------------
# read_file + write_file are admin-only tools, but the path the agent
# supplies is model-controlled. Prompt-injection in an admin's chat can
# weaponise "read /etc/shadow" or "write ~/.ssh/authorized_keys" without
# the admin noticing.
#
# Policy:
#   1. Sensitive-subpath deny list — checked FIRST. Blocks .ssh,
#      .gnupg, shell rc files, token/env files even if the root above
#      them is on the allowlist.
#   2. Allowlist — only the directories the agent legitimately needs
#      (project data/, system tmp). $HOME is NOT on the default list.
#   3. Opt-in extra roots — admin can add broader roots via the
#      "tool_path_extra_roots" setting (list of path strings).
# ---------------------------------------------------------------------------

_SENSITIVE_BASENAMES: set[str] = {
    ".ssh", ".gnupg", ".gitconfig",
    ".bashrc", ".bash_profile", ".bash_logout",
    ".zshrc", ".zprofile", ".zshenv",
    ".profile", ".tcshrc", ".cshrc",
    ".env", ".netrc",
}

_SENSITIVE_FILE_PATTERNS: tuple[str, ...] = (
    "authorized_keys", "id_rsa", "id_ed25519", "id_ecdsa",
    "known_hosts",
)

# Case-folded views used for matching. On a case-insensitive filesystem
# (Windows, default macOS) ".SSH/AUTHORIZED_KEYS" and ".env" resolve to the
# same protected files as their lowercase forms, so the deny-list has to fold
# case before comparing — the sibling resolver already normcases paths for the
# same reason. casefold (not os.path.normcase) because normcase is a no-op on
# POSIX, which is exactly where the macOS read-exfil path lives.
_SENSITIVE_BASENAMES_CF: frozenset[str] = frozenset(b.casefold() for b in _SENSITIVE_BASENAMES)
_SENSITIVE_FILE_PATTERNS_CF: frozenset[str] = frozenset(p.casefold() for p in _SENSITIVE_FILE_PATTERNS)


def _is_sensitive_path(resolved: str) -> bool:
    """Return True if *resolved* falls under a sensitive directory or
    matches a sensitive filename — regardless of what root it sits under.

    Matching is case-insensitive: on Windows / default macOS a case-variant
    name (``.SSH``, ``AUTHORIZED_KEYS``, ``Id_Rsa``) points at the same file as
    the lowercase form, so a case-sensitive check would let it slip past the
    deny-list in every file tool that relies on it.
    """
    parts = [p.casefold() for p in resolved.split(os.sep)]
    filename = parts[-1] if parts else ""

    # Check if any path component is a sensitive directory.
    for part in parts:
        if part in _SENSITIVE_BASENAMES_CF:
            return True

    # Check filename against known sensitive files.
    return filename in _SENSITIVE_FILE_PATTERNS_CF


def _is_control_plane_data_path(resolved: str) -> bool:
    """Block DATA_DIR even when it sits beneath an otherwise allowed temp root."""

    data_root = os.path.realpath(DATA_DIR)
    agent_root = os.path.realpath(_AGENT_WORKDIR)
    try:
        in_data = os.path.commonpath([resolved, data_root]) == data_root
        in_agent_workspace = os.path.commonpath([resolved, agent_root]) == agent_root
    except ValueError:
        return False
    return in_data and not in_agent_workspace


def _tool_path_roots() -> list[str]:
    """Return the list of directory roots that read_file / write_file
    may touch. Default: project data/ + system temp dirs. Extra roots
    are loaded from the ``tool_path_extra_roots`` setting.
    """
    roots: list[str] = []

    # Dedicated user-file workspace. The broad DATA_DIR is intentionally not
    # allowed because it also contains application secrets and databases.
    roots.append(_AGENT_WORKDIR)

    # /tmp (and its macOS realpath /private/tmp).
    roots.append("/tmp")
    try:
        private_tmp = os.path.realpath("/tmp")
        if private_tmp != "/tmp":
            roots.append(private_tmp)
    except OSError:
        pass

    # $TMPDIR — per-user temp root on macOS (e.g. /var/folders/.../T/).
    tmpdir = os.environ.get("TMPDIR")
    if tmpdir:
        roots.append(tmpdir)

    # Opt-in extra roots from settings.
    try:
        from src.settings import get_setting
        extra = get_setting("tool_path_extra_roots")
        if isinstance(extra, list):
            roots.extend(str(r) for r in extra if r)
    except Exception:
        pass

    # Deduplicate; resolve symlinks so containment is unambiguous.
    seen: set[str] = set()
    out: list[str] = []
    for r in roots:
        try:
            real = os.path.realpath(r)
        except OSError:
            continue
        if real in seen:
            continue
        seen.add(real)
        out.append(real)
    return out


def _resolve_tool_path(raw_path: str) -> str:
    """Resolve and confine a model-supplied path.

    Order of checks:
      1. Non-empty path.
      2. Sensitive-subpath deny list (blocks .ssh, .gnupg, etc.
         even when the root is on the allowlist).
      3. Allowlist containment (must land under one of the roots).

    Returns the realpath on success. Raises ValueError on rejection.
    Symlinks are resolved before comparison.

    When a workspace is active for this turn, paths are confined to it instead
    of the default allowlist (see _resolve_tool_path_in_workspace).
    """
    ws = get_active_workspace()
    if ws:
        return _resolve_tool_path_in_workspace(ws, raw_path)
    if raw_path is None or not str(raw_path).strip():
        raise ValueError("path is required")
    expanded = os.path.expanduser(str(raw_path).strip())
    # Relative tool paths belong to the agent's dedicated work directory, not
    # the server process cwd. The subprocess tools already use agent_cwd();
    # keeping file resolution aligned prevents both surprising denials and
    # accidental writes into the source checkout.
    candidate = expanded if os.path.isabs(expanded) else os.path.join(agent_cwd(), expanded)
    resolved = os.path.realpath(candidate)

    if _is_control_plane_data_path(resolved):
        raise ValueError(f"path '{raw_path}' is outside the allowed roots")

    if _is_sensitive_path(resolved):
        raise ValueError(
            f"path '{raw_path}' is inside a sensitive directory "
            f"(e.g. .ssh, .gnupg) or matches a sensitive filename"
        )

    for root in _tool_path_roots():
        if resolved == root:
            return resolved
        try:
            common = os.path.commonpath([resolved, root])
        except ValueError:
            continue
        if common == root:
            return resolved
    raise ValueError(
        f"path '{raw_path}' is outside the allowed roots"
    )


def _resolve_tool_path_in_workspace(workspace: str, raw_path: str) -> str:
    """Confine a model-supplied path to the active workspace.

    Layered on top of upstream's path policy: the workspace is the allowed
    root (relative paths resolve under it; paths that escape it are rejected),
    and the sensitive-file deny list (.ssh, .gnupg, id_rsa, …) still applies
    inside it. When no workspace is set, callers use _resolve_tool_path (the
    default data/tmp allowlist) instead.
    """
    if raw_path is None or not str(raw_path).strip():
        raise ValueError("path is required")
    base = os.path.realpath(workspace)
    expanded = os.path.expanduser(str(raw_path).strip())
    candidate = expanded if os.path.isabs(expanded) else os.path.join(base, expanded)
    resolved = os.path.realpath(candidate)
    if _is_sensitive_path(resolved):
        raise ValueError(
            f"path '{raw_path}' is inside a sensitive directory "
            f"(e.g. .ssh, .gnupg) or matches a sensitive filename"
        )
    if resolved != base:
        # normcase so containment holds on case-insensitive filesystems
        # (Windows, default macOS): it lowercases on Windows and is a no-op on
        # POSIX. commonpath raises ValueError across Windows drives (C: vs D:)
        # or mixed abs/rel — both mean "outside", so the except rejects them.
        nbase = os.path.normcase(base)
        try:
            if os.path.commonpath([os.path.normcase(resolved), nbase]) != nbase:
                raise ValueError
        except ValueError:
            raise ValueError(f"path '{raw_path}' is outside the workspace ({workspace})")
    return resolved



# ---------------------------------------------------------------------------
# Active workspace (per-turn, context-local)
# ---------------------------------------------------------------------------
# Set ONCE in execute_tool_block from the request's `workspace`. The path
# resolvers (_resolve_tool_path / _resolve_search_root) and the subprocess cwd
# helper (agent_cwd) read it from here, so confinement is enforced in a single
# place: any tool that resolves paths through these helpers is confined
# automatically and cannot accidentally bypass the workspace. contextvars are
# task-local, so concurrent turns don't leak into each other.
_active_workspace: contextvars.ContextVar = contextvars.ContextVar(
    "agent_active_workspace", default=None
)

# The canonical registry deadline for the currently executing tool.  Handler
# context derives this value from trusted registry metadata; model arguments
# cannot supply or widen it.  A context variable keeps concurrent tool calls
# isolated while avoiding timeout plumbing through every legacy dispatch arm.
_active_tool_timeout_seconds: contextvars.ContextVar = contextvars.ContextVar(
    "agent_active_tool_timeout_seconds", default=None
)


def get_active_workspace() -> Optional[str]:
    """The folder the agent is confined to this turn, or None."""
    return _active_workspace.get()


def vet_workspace(raw: str) -> Optional[str]:
    """Validate a requested workspace path at bind time.

    Returns the canonical path, or None when it is unusable: not a real
    directory, or itself a sensitive path (.ssh, .gnupg, ...). The in-workspace
    resolver deny-lists sensitive paths *inside* the workspace, but the
    empty-path search root is the workspace itself, so the root has to be
    vetted before it is ever bound.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    resolved = os.path.realpath(os.path.expanduser(raw))
    if not os.path.isdir(resolved) or _is_sensitive_path(resolved):
        return None
    # Reject filesystem roots: binding / (or a Windows drive/UNC root) as the
    # workspace would make every absolute path "inside" it, collapsing the
    # confinement into host-wide file access. A root is its own dirname, which
    # also covers C:\ and \\server\share without platform-specific lists.
    if os.path.dirname(resolved) == resolved:
        return None
    return resolved


def agent_cwd() -> str:
    """Working directory for agent subprocesses (bash/python/background jobs):
    the active workspace when set, else the persistent data dir."""
    workspace = get_active_workspace()
    if workspace:
        return workspace
    pathlib.Path(_AGENT_WORKDIR).mkdir(parents=True, exist_ok=True)
    return _AGENT_WORKDIR


def get_mcp_manager():
    from src import agent_tools
    return agent_tools.get_mcp_manager()




def _resolve_search_root(raw_path: str) -> str:
    """Resolve + confine a code-nav path (grep/glob/ls).

    With a workspace active, the workspace folder is the root and a supplied
    path is confined inside it. Otherwise an empty path defaults to the agent's
    primary root (project data dir) and a supplied path is confined by the
    global allowlist + sensitive-file policy.
    """
    raw = (raw_path or "").strip()
    ws = get_active_workspace()
    if ws:
        return os.path.realpath(ws) if not raw else _resolve_tool_path_in_workspace(ws, raw)
    if not raw:
        roots = _tool_path_roots()
        return roots[0] if roots else os.path.realpath(".")
    return _resolve_tool_path(raw)

logger = logging.getLogger(__name__)


_ADMIN_TOOLS = {
    "app_api",
    "manage_endpoints",
    "manage_mcp",
    "manage_webhooks",
    "manage_tokens",
    "manage_settings",
    "download_model",
    "serve_model",
    "serve_preset",
    "stop_served_model",
    "cancel_download",
}


# Legacy dispatcher branches that do not have a TOOL_HANDLERS entry.  This is
# not an authority list: registry classification and policy still decide
# whether they may run.  It exists solely to prove that a registry binding
# resolves to one live runtime path before the policy engine can return allow.
_LEGACY_BRANCH_TOOL_NAMES = frozenset(
    {
        "adopt_served_model",
        "api_call",
        "app_api",
        "cancel_download",
        "download_model",
        "edit_image",
        "list_cached_models",
        "list_cookbook_servers",
        "list_downloads",
        "list_serve_presets",
        "list_served_models",
        "manage_calendar",
        "manage_contact",
        "manage_memory",
        "manage_notes",
        "manage_research",
        "manage_skills",
        "manage_tasks",
        "query_work",
        "manage_work",
        "delete_work",
        "query_gmail",
        "manage_gmail_draft",
        "send_gmail",
        "modify_gmail_message",
        "delete_gmail",
        "download_gmail_attachment",
        "query_google_calendar",
        "create_google_calendar_hold",
        "create_google_calendar_event",
        "update_google_calendar_event",
        "respond_google_calendar_invitation",
        "update_google_calendar_attendees",
        "delete_google_calendar_event",
        "search_meetings",
        "create_meeting",
        "request_meeting_transcription",
        "approve_meeting_action_item",
        "save_meeting_knowledge",
        "delete_meeting",
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
        "pipeline",
        "resolve_contact",
        "search_chats",
        "search_hf_models",
        "serve_model",
        "serve_preset",
        "stop_served_model",
        "tail_serve_output",
        "trigger_research",
        "ui_control",
    }
)


class RuntimeBindingKind(str, Enum):
    LEGACY_DISPATCH = "legacy_dispatch"
    BUILTIN_MCP = "builtin_mcp"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class ResolvedRuntimeBinding:
    """Parsed registry binding used unchanged through dispatch."""

    definition: ToolDefinition
    kind: RuntimeBindingKind
    namespace: str
    target: str


def _resolve_runtime_binding(
    identity: ResolvedToolIdentity,
) -> Optional[ResolvedRuntimeBinding]:
    """Resolve binding metadata without importing a handler module.

    The binding must name the already-resolved canonical operation exactly.
    Actual handler presence is checked only after authorization and immediately
    before dispatch, so denied calls cannot trigger implementation imports.
    """

    definition = identity.definition
    parts = definition.binding.split(":")
    if (
        len(parts) == 2
        and parts[0] == RuntimeBindingKind.LEGACY_DISPATCH.value
        and parts[1] == definition.name
    ):
        return ResolvedRuntimeBinding(
            definition=definition,
            kind=RuntimeBindingKind.LEGACY_DISPATCH,
            namespace="",
            target=definition.name,
        )
    if (
        len(parts) == 3
        and parts[0] == RuntimeBindingKind.BUILTIN_MCP.value
        and parts[2] == definition.name
        and parts[1]
    ):
        return ResolvedRuntimeBinding(
            definition=definition,
            kind=RuntimeBindingKind.BUILTIN_MCP,
            namespace=parts[1],
            target=parts[2],
        )
    if (
        len(parts) == 3
        and parts[0] == RuntimeBindingKind.INTERNAL.value
        and parts[2] == definition.name
        and parts[1]
    ):
        return ResolvedRuntimeBinding(
            definition=definition,
            kind=RuntimeBindingKind.INTERNAL,
            namespace=parts[1],
            target=parts[2],
        )
    return None


def _owner_is_admin(owner: Optional[str]) -> bool:
    """Mirror route-level admin behavior for agent tool execution."""
    return owner_is_admin_or_single_user(owner)

# ---------------------------------------------------------------------------
# MCP-backed tool helpers
# ---------------------------------------------------------------------------

# Native tools are implemented by ``src.agent_tools.TOOL_HANDLERS``.  Keep
# them explicit here so an MCP server with a colliding ID can never intercept
# an unqualified native call.
_NATIVE_DIRECT_TOOLS = frozenset({
    "bash",
    "python",
    "read_file",
    "write_file",
    "web_search",
    "web_fetch",
})


# Bundled tools that intentionally retain an unqualified MCP alias.
_MCP_TOOL_MAP = {
    "generate_image": ("image_gen",  "generate_image"),
}
_EMAIL_MCP_OWNER_ARG = "_odysseus_owner"


def _parse_qualified_mcp_args(tool: str, content: str) -> tuple[Dict, Optional[str]]:
    raw = (content or "").strip()
    if not raw:
        return {}, None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        if tool.startswith("mcp__email__"):
            return {}, "Email MCP tool arguments must be a JSON object."
        return {}, None
    if not isinstance(parsed, dict):
        if tool.startswith("mcp__email__"):
            return {}, "Email MCP tool arguments must be a JSON object."
        return {}, None
    return parsed, None


def _parse_generate_image(content: str) -> Dict:
    lines = content.strip().split("\n")
    args = {"prompt": lines[0].strip() if lines else ""}
    for i, key in enumerate(["model", "size", "quality"], 1):
        if len(lines) > i and lines[i].strip():
            args[key] = lines[i].strip()
    return args


def _parse_manage_memory(content: str) -> Dict:
    lines = content.strip().split("\n")
    action = lines[0].strip().lower() if lines else ""
    args = {"action": action}
    if action == "add":
        args["text"] = lines[1].strip() if len(lines) > 1 else ""
        if len(lines) > 2 and lines[2].strip():
            args["category"] = lines[2].strip().lower()
    elif action == "edit":
        args["memory_id"] = lines[1].strip() if len(lines) > 1 else ""
        args["text"] = lines[2].strip() if len(lines) > 2 else ""
    elif action == "delete":
        args["memory_id"] = lines[1].strip() if len(lines) > 1 else ""
    elif action == "search":
        args["text"] = lines[1].strip() if len(lines) > 1 else ""
    elif action == "list":
        if len(lines) > 1 and lines[1].strip():
            args["category"] = lines[1].strip().lower()
    return args


_MCP_ARG_PARSERS: Dict[str, Callable[[str], Dict[str, str]]] = {
    "generate_image": _parse_generate_image,
    "manage_memory":  _parse_manage_memory,
}


# Primary argument key(s) for bundled line-parsed MCP tools. When a fenced
# block's content is a JSON object carrying one of these keys, it's structured
# inline args (the relaxed parser's ```generate_image {"prompt": "..."}```
# shape) —
# use the object directly instead of letting the line-based parsers wrap the
# whole JSON string as the query/url/path/prompt. Keyed off membership only
# (the primary key never changes), so this can't drift; an unrecognized object
# safely falls through to the line-based parser, i.e. the previous behavior.
#
# This only covers the MCP path. Native web/filesystem handlers decode their
# own inline JSON before execution and never pass through _build_mcp_args.
_MCP_JSON_PRIMARY_KEYS: Dict[str, tuple] = {
    "generate_image": ("prompt",),
}


def _build_mcp_args(tool: str, content: str) -> Dict:
    """Convert fenced-block text content to structured MCP arguments."""
    primaries = _MCP_JSON_PRIMARY_KEYS.get(tool)
    if primaries and content.strip().startswith("{"):
        try:
            decoded = json.loads(content.strip())
        except (json.JSONDecodeError, TypeError):
            decoded = None
        if isinstance(decoded, dict) and any(k in decoded for k in primaries):
            return decoded
    parser = _MCP_ARG_PARSERS.get(tool)
    return parser(content) if parser else {}


async def _call_mcp_tool(
    tool: str,
    content: str,
    progress_cb: Optional[Callable[[Dict], Awaitable[None]]] = None,
) -> Dict:
    """Route a bundled unqualified tool alias through the MCP manager."""
    mcp = get_mcp_manager()
    if not mcp:
        return await _direct_fallback(tool, content, progress_cb=progress_cb) or {"error": f"MCP manager not available for tool '{tool}'", "exit_code": 1}

    server_id, tool_name = _MCP_TOOL_MAP[tool]
    qualified = f"mcp__{server_id}__{tool_name}"
    args = _build_mcp_args(tool, content)
    result = await mcp.call_tool(qualified, args)

    # generate_image runs as a text-only MCP tool, so the saved image URL never
    # reaches the agent loop's structured forwarding (which renders the image via
    # buildImageBubble on result["image_url"]). Lift it out of the tool's stdout so
    # the image renders deterministically — no dependence on the model echoing the
    # URL into its prose (which it mangles/hallucinates).
    if tool == "generate_image":
        _promote_image_fields(result)

    return result


def _promote_image_fields(result: Dict) -> None:
    """Lift the image URL (+ prompt/model/size) from a successful generate_image MCP
    text result into structured fields the agent loop already forwards to
    buildImageBubble. Only acts on a dict result with exit_code 0; matches the
    generated-image URL by pattern (absolute or relative) so it's robust to the
    result's wording."""
    if not isinstance(result, dict) or result.get("exit_code") != 0:
        return
    out = result.get("stdout") or ""
    m = re.search(r'(?:https?://[^\s)\]]+)?/api/generated-image/[A-Za-z0-9._-]+', out)
    if not m:
        return
    result["image_url"] = m.group(0).strip()
    for field, pat in (
        ("image_prompt", r'^Generated image for:\s*(.+)$'),
        ("image_model", r'^model:\s*(.+)$'),
        ("image_size", r'^size:\s*(.+)$'),
    ):
        fm = re.search(pat, out, re.M)
        if fm:
            result[field] = fm.group(1).strip()


_BG_MARKERS = {"#!bg", "#bg", "# bg", "#background", "# background", "@background", "# @background"}


def _split_bg_marker(content: str):
    """If the bash content's first non-empty line is a background marker
    (e.g. `#!bg`), return (True, command_without_marker); else (False, content)."""
    lines = content.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].strip().lower() in _BG_MARKERS:
        del lines[i]
        return True, "\n".join(lines).strip()
    return False, content


# Exact legacy runtime adapters.  These tables contain implementation
# locations, not authority: the immutable registry decision is always made
# first.  Keeping locations narrow prevents one resolved binding from falling
# through unrelated handler imports or a similarly named MCP capability.
_AGENT_HANDLER_CLASSES: Mapping[str, tuple[str, str]] = {
    "bash": ("src.agent_tools.subprocess_tools", "BashTool"),
    "python": ("src.agent_tools.subprocess_tools", "PythonTool"),
    "web_search": ("src.agent_tools.web_tools", "WebSearchTool"),
    "web_fetch": ("src.agent_tools.web_tools", "WebFetchTool"),
    "read_file": ("src.agent_tools.filesystem_tools", "ReadFileTool"),
    "write_file": ("src.agent_tools.filesystem_tools", "WriteFileTool"),
    "edit_file": ("src.agent_tools.filesystem_tools", "EditFileTool"),
    "ls": ("src.agent_tools.filesystem_tools", "LsTool"),
    "glob": ("src.agent_tools.filesystem_tools", "GlobTool"),
    "grep": ("src.agent_tools.filesystem_tools", "GrepTool"),
    "get_workspace": ("src.agent_tools.filesystem_tools", "GetWorkspaceTool"),
    "create_document": ("src.agent_tools.document_tools", "CreateDocumentTool"),
    "update_document": ("src.agent_tools.document_tools", "UpdateDocumentTool"),
    "edit_document": ("src.agent_tools.document_tools", "EditDocumentTool"),
    "suggest_document": ("src.agent_tools.document_tools", "SuggestDocumentTool"),
    "manage_documents": ("src.agent_tools.document_tools", "ManageDocumentTool"),
    "ask_user": ("src.agent_tools.interaction_tools", "AskUserTool"),
    "update_plan": ("src.agent_tools.interaction_tools", "UpdatePlanTool"),
    "chat_with_model": (
        "src.agent_tools.model_interaction_tools",
        "ChatWithModelTool",
    ),
    "ask_teacher": ("src.agent_tools.model_interaction_tools", "AskTeacherTool"),
    "list_models": ("src.agent_tools.model_interaction_tools", "ListModelsTool"),
    "manage_bg_jobs": ("src.agent_tools.bg_job_tools", "ManageBgJobsTool"),
    "create_session": ("src.agent_tools.session_tools", "CreateSessionTool"),
    "list_sessions": ("src.agent_tools.session_tools", "ListSessionsTool"),
    "send_to_session": ("src.agent_tools.session_tools", "SendToSessionTool"),
    "manage_session": ("src.agent_tools.session_tools", "ManageSessionTool"),
}

_ADMIN_HANDLER_TARGETS = frozenset(
    {
        "manage_endpoints",
        "manage_mcp",
        "manage_webhooks",
        "manage_tokens",
        "manage_settings",
    }
)


def _load_exact_agent_handler(tool: str):
    """Load only the implementation declared for one exact legacy target.

    Tests and extension code historically patch ``src.agent_tools``'s facade
    registry.  Honour an already-loaded facade without importing it here;
    otherwise resolve from the explicit module/class table.
    """

    facade = sys.modules.get("src.agent_tools")
    handlers = getattr(facade, "TOOL_HANDLERS", None) if facade else None
    if isinstance(handlers, Mapping) and tool in handlers:
        return handlers[tool]

    location = _AGENT_HANDLER_CLASSES.get(tool)
    if location is not None:
        module_name, class_name = location
        module = importlib.import_module(module_name)
        handler_class = getattr(module, class_name, None)
        if handler_class is None:
            return None
        return handler_class().execute

    if tool in _ADMIN_HANDLER_TARGETS:
        module = importlib.import_module("src.agent_tools.admin_tools")
        table = getattr(module, "ADMIN_TOOL_HANDLERS", {})
        return table.get(tool) if isinstance(table, Mapping) else None
    return None


def _handler_context(
    *,
    progress_cb: Optional[Callable[[Dict], Awaitable[None]]],
    session_id: Optional[str],
    owner: Optional[str],
    request_id: str,
) -> dict[str, Any]:
    # Never pass provider keys, OAuth secrets, database URLs, internal tokens,
    # or the parent process's credential helpers into model-proposed code.
    # Keep only the small set required for ordinary command execution.
    permitted_env = {
        key: value for key, value in os.environ.items()
        if key in {
            "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TEMP", "TMP",
            "SYSTEMROOT", "WINDIR", "PATHEXT", "COMSPEC", "SSL_CERT_FILE",
            "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
        }
    }
    return {
        "progress_cb": progress_cb,
        "subproc_env": {
            **permitted_env,
            "TERM": "xterm-256color",
            "COLUMNS": "120",
            "LINES": "40",
            "HOME": _AGENT_WORKDIR,
        },
        "session_id": session_id,
        "owner": owner,
        "request_id": request_id,
        "timeout_seconds": _active_tool_timeout_seconds.get(),
        # The executor owns the wall-clock deadline. Subprocess handlers wait
        # for cancellation and reap their process trees before returning.
        "deadline_managed": True,
    }


async def _direct_fallback(
    tool: str,
    content: str,
    progress_cb: Optional[Callable[[Dict], Awaitable[None]]] = None,
    session_id: Optional[str] = None,
    owner: Optional[str] = None,
    request_id: str = "",
) -> Optional[Dict]:
    try:
        handler = _load_exact_agent_handler(tool)
        if handler is not None:
            return await handler(
                content,
                _handler_context(
                    progress_cb=progress_cb,
                    session_id=session_id,
                    owner=owner,
                    request_id=request_id,
                ),
            )

    except Exception as e:
        return {"error": f"{tool}: {e}", "exit_code": 1}

    return None


async def _document_tool_dispatch(
    tool: str,
    content: str,
    session_id: Optional[str] = None,
    owner: Optional[str] = None,
) -> Optional[Dict]:
    """Route a document tool through TOOL_HANDLERS with the right ctx shape."""
    handler = _load_exact_agent_handler(tool)
    if handler is not None:
        return await handler(content, {"session_id": session_id, "owner": owner})
    return None


_AI_DISPATCH_TARGETS = frozenset({"pipeline", "manage_memory", "ui_control"})

# target -> (module, function, invocation style)
_LEGACY_DOMAIN_BINDINGS: Mapping[str, tuple[str, str, str]] = {
    "search_chats": ("src.tools.search", "do_search_chats", "owner"),
    "manage_tasks": ("src.tools.system", "do_manage_tasks", "owner"),
    "manage_skills": ("src.tools.system", "do_manage_skills", "owner"),
    "api_call": ("src.tools.system", "do_api_call", "content"),
    "app_api": ("src.tools.system", "do_app_api", "owner"),
    "manage_notes": ("src.tools.notes", "do_manage_notes", "owner"),
    "manage_calendar": ("src.tools.calendar", "do_manage_calendar", "owner"),
    "query_calendar": ("src.tools.calendar", "do_query_calendar", "owner"),
    "download_model": ("src.tools.cookbook", "do_download_model", "owner"),
    "serve_model": ("src.tools.cookbook", "do_serve_model", "owner_request"),
    "list_served_models": (
        "src.tools.cookbook",
        "do_list_served_models",
        "owner_request",
    ),
    "stop_served_model": ("src.tools.cookbook", "do_stop_served_model", "owner"),
    "tail_serve_output": (
        "src.tools.cookbook",
        "do_tail_serve_output",
        "owner_request",
    ),
    "list_downloads": ("src.tools.cookbook", "do_list_downloads", "owner"),
    "cancel_download": ("src.tools.cookbook", "do_cancel_download", "owner"),
    "search_hf_models": ("src.tools.cookbook", "do_search_hf_models", "owner"),
    "list_cached_models": ("src.tools.cookbook", "do_list_cached_models", "owner"),
    "list_serve_presets": (
        "src.tools.cookbook",
        "do_list_serve_presets",
        "owner",
    ),
    "serve_preset": ("src.tools.cookbook", "do_serve_preset", "owner"),
    "adopt_served_model": (
        "src.tools.cookbook",
        "do_adopt_served_model",
        "owner",
    ),
    "list_cookbook_servers": (
        "src.tools.cookbook",
        "do_list_cookbook_servers",
        "owner",
    ),
    "edit_image": ("src.tools.image", "do_edit_image", "owner"),
    "trigger_research": ("src.tools.research", "do_trigger_research", "owner"),
    "manage_research": ("src.tools.research", "do_manage_research", "owner"),
    "resolve_contact": ("src.tools.contacts", "do_resolve_contact", "owner"),
    "manage_contact": ("src.tools.contacts", "do_manage_contact", "owner"),
    "query_work": ("src.tools.work", "do_query_work", "owner"),
    "manage_work": (
        "src.tools.work",
        "do_manage_work",
        "owner_request_approval",
    ),
    "delete_work": (
        "src.tools.work",
        "do_delete_work",
        "owner_request_approval",
    ),
    "query_gmail": (
        "src.tools.google_workspace",
        "do_query_gmail",
        "owner",
    ),
    "manage_gmail_draft": (
        "src.tools.google_workspace",
        "do_manage_gmail_draft",
        "owner_request_approval",
    ),
    "send_gmail": (
        "src.tools.google_workspace",
        "do_send_gmail",
        "owner_request_approval",
    ),
    "modify_gmail_message": (
        "src.tools.google_workspace",
        "do_modify_gmail_message",
        "owner_request_approval",
    ),
    "delete_gmail": (
        "src.tools.google_workspace",
        "do_delete_gmail",
        "owner_request_approval",
    ),
    "download_gmail_attachment": (
        "src.tools.google_workspace",
        "do_download_gmail_attachment",
        "owner_request_approval",
    ),
    "query_google_calendar": (
        "src.tools.google_workspace",
        "do_query_google_calendar",
        "owner",
    ),
    "create_google_calendar_hold": (
        "src.tools.google_workspace",
        "do_create_google_calendar_hold",
        "owner_request_approval",
    ),
    "create_google_calendar_event": (
        "src.tools.google_workspace",
        "do_create_google_calendar_event",
        "owner_request_approval",
    ),
    "update_google_calendar_event": (
        "src.tools.google_workspace",
        "do_update_google_calendar_event",
        "owner_request_approval",
    ),
    "respond_google_calendar_invitation": (
        "src.tools.google_workspace",
        "do_respond_google_calendar_invitation",
        "owner_request_approval",
    ),
    "update_google_calendar_attendees": (
        "src.tools.google_workspace",
        "do_update_google_calendar_attendees",
        "owner_request_approval",
    ),
    "delete_google_calendar_event": (
        "src.tools.google_workspace",
        "do_delete_google_calendar_event",
        "owner_request_approval",
    ),
    "search_meetings": ("src.tools.meetings", "do_search_meetings", "owner"),
    "create_meeting": (
        "src.tools.meetings", "do_create_meeting", "owner_request_approval"
    ),
    "request_meeting_transcription": (
        "src.tools.meetings",
        "do_request_meeting_transcription",
        "owner_request_approval",
    ),
    "approve_meeting_action_item": (
        "src.tools.meetings",
        "do_approve_meeting_action_item",
        "owner_request_approval",
    ),
    "save_meeting_knowledge": (
        "src.tools.meetings",
        "do_save_meeting_knowledge",
        "owner_request_approval",
    ),
    "delete_meeting": (
        "src.tools.meetings", "do_delete_meeting", "owner_request_approval"
    ),
    "query_knowledge": ("src.tools.knowledge", "do_query_knowledge", "owner"),
    "manage_knowledge": (
        "src.tools.knowledge", "do_manage_knowledge", "owner_request_approval"
    ),
    "delete_knowledge": (
        "src.tools.knowledge", "do_delete_knowledge", "owner_request_approval"
    ),
    "query_dashboard": ("src.tools.dashboard", "do_query_dashboard", "owner"),
    "query_automations": ("src.tools.automations", "do_query_automations", "owner"),
    "manage_automation": ("src.tools.automations", "do_manage_automation", "owner_request_approval"),
    "delete_automation": ("src.tools.automations", "do_delete_automation", "owner_request_approval"),
    "query_life": ("src.tools.life", "do_query_life", "owner"),
    "manage_life": ("src.tools.life", "do_manage_life", "owner_request_approval"),
    "delete_life": ("src.tools.life", "do_delete_life", "owner_request_approval"),
}

_INTERNAL_BINDINGS: Mapping[str, tuple[str, str]] = {
    "vault_search": ("src.tools.vault", "do_vault_search"),
    "vault_get": ("src.tools.vault", "do_vault_get"),
    "vault_unlock": ("src.tools.vault", "do_vault_unlock"),
}


def _binding_denial(
    binding: ResolvedRuntimeBinding,
    reason: str,
) -> Tuple[str, Dict]:
    definition = binding.definition
    return f"{definition.name}: BLOCKED", {
        "error": reason,
        "exit_code": 1,
        "blocked": True,
        "policy_decision": PolicyDecisionKind.DENY.value,
        "policy_code": "binding_dispatch_mismatch",
        "tool_name": definition.name,
        "tool_version": definition.version,
        "binding_kind": binding.kind.value,
        "binding_namespace": binding.namespace,
        "binding_target": binding.target,
    }


async def _dispatch_builtin_mcp_binding(
    binding: ResolvedRuntimeBinding,
    content: str,
    *,
    owner: Optional[str],
) -> Tuple[str, Dict]:
    target = binding.target
    expected_namespace = (
        "email" if target in BUILTIN_EMAIL_TOOLS
        else "image_gen" if target == "generate_image"
        else None
    )
    if expected_namespace is None or binding.namespace != expected_namespace:
        return _binding_denial(
            binding,
            "Canonical MCP binding namespace/target does not match a bundled adapter.",
        )

    mcp = get_mcp_manager()
    if not mcp:
        return f"{target}: failed", {
            "error": f"MCP manager not available for '{binding.namespace}:{target}'.",
            "exit_code": 1,
        }

    if target == "generate_image":
        args = _build_mcp_args(target, content)
        description = f"generate_image: {str(args.get('prompt') or '')[:80]}"
    else:
        args, parse_error = _parse_qualified_mcp_args(
            f"mcp__{binding.namespace}__{target}",
            content,
        )
        if parse_error:
            return f"email: {target}", {"error": parse_error, "exit_code": 1}
        # Copy normalized arguments before adding trusted transport metadata.
        # Provider approval receipts can be injected at this exact boundary;
        # model arguments can never supply the reserved owner value.
        args = dict(args)
        if owner:
            args[_EMAIL_MCP_OWNER_ARG] = owner
        description = f"email: {target}"

    qualified = f"mcp__{binding.namespace}__{target}"
    result = await mcp.call_tool(qualified, args)
    if target == "generate_image":
        _promote_image_fields(result)
    return description, result


async def _dispatch_internal_binding(
    binding: ResolvedRuntimeBinding,
    content: str,
    *,
    owner: Optional[str],
) -> Tuple[str, Dict]:
    location = _INTERNAL_BINDINGS.get(binding.target)
    if binding.namespace != "vault" or location is None:
        return _binding_denial(
            binding,
            "Canonical internal binding namespace/target has no exact adapter.",
        )
    module_name, function_name = location
    module = importlib.import_module(module_name)
    handler = getattr(module, function_name, None)
    if handler is None:
        return _binding_denial(binding, "Canonical internal handler is unavailable.")
    return binding.target, await handler(content, owner=owner)


async def _dispatch_legacy_binding(
    binding: ResolvedRuntimeBinding,
    content: str,
    *,
    session_id: Optional[str],
    owner: Optional[str],
    request_id: str,
    progress_cb: Optional[Callable[[Dict], Awaitable[None]]],
    approval_grant: Any = None,
) -> Tuple[str, Dict]:
    target = binding.target
    if binding.namespace or target != binding.definition.name:
        return _binding_denial(
            binding,
            "Legacy binding does not match its canonical target exactly.",
        )

    # Detached execution is an adapter of the canonical bash binding, not a
    # second dispatch path discoverable by name.
    if target == "bash" and session_id:
        is_background, command = _split_bg_marker(content)
        if is_background and command:
            from src import bg_jobs
            from src.agent_tools.subprocess_tools import validate_agent_shell

            try:
                validate_agent_shell(command)
            except ValueError as exc:
                return "bash: BLOCKED", {
                    "error": f"bash: {exc}", "exit_code": 126, "blocked": True,
                }

            record = bg_jobs.launch(command, session_id=session_id, cwd=agent_cwd())
            short = command.strip().split(chr(10))[0][:80]
            return f"bash (background): {short}", {
                "output": (
                    f"Started background job `{record['id']}`. It is running detached; "
                    "do NOT wait for it or poll it. You will be automatically re-invoked "
                    "with its full output when it finishes."
                ),
                "exit_code": 0,
                "bg_job_id": record["id"],
            }

    if target in _AGENT_HANDLER_CLASSES or target in _ADMIN_HANDLER_TARGETS:
        result = await _direct_fallback(
            target,
            content,
            progress_cb=progress_cb,
            session_id=session_id,
            owner=owner,
            request_id=request_id,
        )
        if isinstance(result, tuple):
            return result
        if result is None:
            return _binding_denial(binding, "Canonical legacy handler is unavailable.")
        first_line = content.split(chr(10))[0].strip()[:80]
        description = f"{target}: {first_line}" if first_line else target
        if target == "edit_file":
            description = result.get("output") or result.get("error") or target
        elif target in {"edit_document", "suggest_document"} and result.get("title"):
            description = f"{target}: {result['title']}"
        return description, result

    if target in _AI_DISPATCH_TARGETS:
        module = importlib.import_module("src.ai_interaction")
        dispatcher = getattr(module, "dispatch_ai_tool", None)
        if dispatcher is None:
            return _binding_denial(binding, "Canonical AI handler is unavailable.")
        return await dispatcher(target, content, session_id, owner=owner)

    location = _LEGACY_DOMAIN_BINDINGS.get(target)
    if location is None:
        return _binding_denial(binding, "Canonical legacy target has no exact adapter.")
    module_name, function_name, invocation = location
    # Preserve the long-standing patch/extension seam when its facade is
    # already loaded, but never import that broad facade from the executor.
    facade = sys.modules.get("src.tool_implementations")
    handler = getattr(facade, function_name, None) if facade else None
    if handler is None:
        module = importlib.import_module(module_name)
        handler = getattr(module, function_name, None)
    if handler is None:
        return _binding_denial(binding, "Canonical legacy handler is unavailable.")
    if invocation == "content":
        result = await handler(content)
    elif invocation == "owner_request":
        result = await handler(content, owner=owner, request_id=request_id)
    elif invocation == "owner_request_approval":
        result = await handler(
            content,
            owner=owner,
            request_id=request_id,
            approval_action_id=getattr(approval_grant, "approval_id", None),
        )
    else:
        result = await handler(content, owner=owner)
    return target, result


async def _dispatch_resolved_binding(
    binding: ResolvedRuntimeBinding,
    content: str,
    *,
    session_id: Optional[str],
    owner: Optional[str],
    request_id: str,
    progress_cb: Optional[Callable[[Dict], Awaitable[None]]],
    approval_grant: Any = None,
) -> Tuple[str, Dict]:
    """Dispatch solely from the resolved immutable binding."""

    if binding.kind is RuntimeBindingKind.BUILTIN_MCP:
        return await _dispatch_builtin_mcp_binding(binding, content, owner=owner)
    if binding.kind is RuntimeBindingKind.INTERNAL:
        return await _dispatch_internal_binding(binding, content, owner=owner)
    if binding.kind is RuntimeBindingKind.LEGACY_DISPATCH:
        return await _dispatch_legacy_binding(
            binding,
            content,
            session_id=session_id,
            owner=owner,
            request_id=request_id,
            progress_cb=progress_cb,
            approval_grant=approval_grant,
        )
    return _binding_denial(binding, "Unsupported canonical binding kind.")


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

async def _await_registry_deadline(
    execution: Awaitable[Tuple[str, Dict]],
    timeout_seconds: float,
) -> tuple[bool, Optional[Tuple[str, Dict]]]:
    """Await one tool call without confusing handler timeouts with ours.

    ``asyncio.wait_for`` raises ``TimeoutError`` both when its own deadline
    expires and when the wrapped handler raises that exception itself.  Using
    ``asyncio.wait`` keeps those cases distinct and still guarantees that an
    external cancellation cancels and reaps the owned execution task.
    """

    task = asyncio.create_task(execution)
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout_seconds)
    except asyncio.CancelledError:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise
    if task in done:
        return False, await task

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    return True, None


async def execute_tool_block(
    block: Any,
    session_id: Optional[str] = None,
    disabled_tools: Optional[set] = None,
    owner: Optional[str] = None,
    progress_cb: Optional[Callable[[Dict], Awaitable[None]]] = None,
    workspace: Optional[str] = None,
    tool_policy: Optional[Any] = None,
    request_id: str = "",
    authority: Optional[ExecutionAuthority] = None,
    approval_grant: Optional[Any] = None,
) -> Tuple[str, Dict]:
    """Execute a single tool block. Returns (description, result_dict).

    Thin wrapper: bind the per-turn workspace (so the path resolvers + subprocess
    cwd confine to it) for the duration of this call, then delegate. Reset on the
    way out so the binding never leaks to the next tool call. ``request_id`` is
    an application-generated correlation/capability identity; callers must not
    copy it from model arguments. ``authority`` is an immutable request value
    constructed by the ingress; model/tool arguments can never supply scopes,
    surface, or trust flags.
    """
    if authority is None:
        # Compatibility for internal/test callers. Model-originated production
        # calls pass an explicit authority from the agent loop.
        authority = authority_for_owner(owner, surface=ToolSurface.FENCE)
    requested_tool = getattr(block, "tool_type", None)
    resolved = resolve_tool_identity(requested_tool, surface=authority.surface)
    definition = (
        resolved.definition
        if isinstance(resolved, ResolvedToolIdentity)
        else None
    )
    timeout_seconds = (
        float(definition.timeout_seconds)
        if definition is not None
        else None
    )

    workspace_token = _active_workspace.set(workspace or None)
    timeout_token = _active_tool_timeout_seconds.set(timeout_seconds)
    try:
        execution = _execute_tool_block_impl(
            block,
            session_id=session_id,
            disabled_tools=disabled_tools,
            owner=owner,
            authority=authority,
            approval_grant=approval_grant,
            request_id=request_id,
            progress_cb=progress_cb,
            tool_policy=tool_policy,
        )
        # Unknown/denied identities have no executable binding and should
        # return their policy decision directly.  Every resolved static tool,
        # however, is bounded by its immutable ToolDefinition deadline.
        if timeout_seconds is None:
            return await execution
        timed_out, output = await _await_registry_deadline(
            execution,
            timeout_seconds,
        )
        if timed_out:
            canonical_name = definition.name
            logger.warning(
                "Registry timeout tool=%r version=%s timeout_seconds=%s owner=%r",
                canonical_name,
                definition.version,
                timeout_seconds,
                authority.owner,
            )
            return f"{canonical_name}: TIMED OUT", {
                "error": (
                    f"Tool '{canonical_name}' exceeded its registry timeout "
                    f"of {timeout_seconds:g} seconds."
                ),
                "exit_code": 124,
                "timed_out": True,
                "timeout_seconds": timeout_seconds,
                "policy_code": "tool_timeout",
                "requested_tool": requested_tool,
                "tool_name": canonical_name,
                "tool_version": definition.version,
            }
        assert output is not None
        return output
    finally:
        _active_tool_timeout_seconds.reset(timeout_token)
        _active_workspace.reset(workspace_token)


async def _execute_tool_block_impl(
    block: Any,
    session_id: Optional[str] = None,
    disabled_tools: Optional[set] = None,
    owner: Optional[str] = None,
    progress_cb: Optional[Callable[[Dict], Awaitable[None]]] = None,
    tool_policy: Optional[Any] = None,
    request_id: str = "",
    authority: Optional[ExecutionAuthority] = None,
    approval_grant: Optional[Any] = None,
) -> Tuple[str, Dict]:
    """Execute a single tool block. Returns (description, result_dict).

    `progress_cb` is forwarded to long-running subprocess tools
    (bash, python) so the agent loop can emit `tool_progress` SSE
    events while the command is in flight. Ignored by other tools.
    """
    requested_tool = getattr(block, "tool_type", None)
    content = str(getattr(block, "content", "") or "")
    if authority is None:
        authority = authority_for_owner(owner, surface=ToolSurface.FENCE)

    identity_or_denial = resolve_tool_identity(
        requested_tool,
        surface=authority.surface,
    )
    if isinstance(identity_or_denial, ToolPolicyDecision):
        requested_label = requested_tool if isinstance(requested_tool, str) else "tool"
        return f"{requested_label}: BLOCKED", identity_or_denial.as_result()
    identity = identity_or_denial

    if owner is not None and owner != authority.owner:
        denial = deny_resolved_tool(
            identity,
            code="authority_owner_mismatch",
            reason="Execution authority does not belong to the supplied owner.",
        )
        return f"{identity.canonical_name}: BLOCKED", denial.as_result()

    binding = _resolve_runtime_binding(identity)
    if binding is None:
        denial = deny_resolved_tool(
            identity,
            code="missing_binding",
            reason=f"Tool '{identity.canonical_name}' has no valid canonical binding.",
        )
        return f"{identity.canonical_name}: BLOCKED", denial.as_result()

    tool = identity.canonical_name
    owner = authority.owner

    # The block/disable gates below must match every policy-equivalent
    # spelling of the tool name (bare email names alias their mcp__email__
    # form — see email_tool_policy_names), not just the spelling the model
    # happened to emit.
    policy_names = set(email_tool_policy_names(tool))
    if isinstance(requested_tool, str):
        policy_names.update(email_tool_policy_names(requested_tool))

    # Misformatted tool call detection: model put JSON inside ```python``` (or
    # similar) without naming the tool. Common with MiniMax-style outputs.
    # Return a helpful error so the model retries with the correct format.
    if tool in ("python", "json", "xml") and content.strip().startswith("{") and content.strip().endswith("}"):
        try:
            parsed = json.loads(content.strip())
            if isinstance(parsed, dict):
                desc = f"{tool}: misformatted tool call"
                denial = deny_resolved_tool(
                    identity,
                    code="invalid_arguments",
                    reason=(
                        f"You wrote a JSON object inside a ```{tool}``` block, but that's not a tool call.\n"
                        "To call a tool, use the tool name as the fence tag, e.g.\n"
                        "```resolve_contact\n"
                        "{\"name\": \"...\"}\n"
                        "```\n"
                        "or\n"
                        "```send_email\n"
                        "{\"to\": \"...\", \"subject\": \"...\", \"body\": \"...\"}\n"
                        "```"
                    ),
                )
                return desc, denial.as_result()
        except (ValueError, TypeError):
            pass

    # Reject tools that the user has disabled for this request
    if disabled_tools and not policy_names.isdisjoint(disabled_tools):
        # Preserve the spelling presented at the ingress in the audit/UI
        # description.  The canonical name remains in the structured result.
        # This matters for qualified bundled aliases: callers must be able to
        # correlate the denial with the exact capability they attempted.
        desc = f"{identity.requested_name}: BLOCKED"
        result = deny_resolved_tool(
            identity,
            code="user_disabled",
            reason=f"Tool '{tool}' is disabled by user.",
        ).as_result()
        logger.info(f"Tool blocked by user: {tool}")
        return desc, result

    if tool_policy and any(tool_policy.blocks(name) for name in policy_names):
        desc = f"{tool}: BLOCKED"
        result = deny_resolved_tool(
            identity,
            code="request_policy_denied",
            reason=f"Execution of tool '{tool}' is forbidden by the active guide-only policy.",
        ).as_result()
        logger.warning("Tool policy blocked tool=%s", tool)
        return desc, result

    # Role gates precede argument validation.  Besides avoiding useless work,
    # this prevents an unauthorized principal from using validation errors as
    # a schema-discovery oracle for privileged capabilities.
    if tool in _ADMIN_TOOLS and not _owner_is_admin(owner):
        result = deny_resolved_tool(
            identity,
            code="admin_required",
            reason=f"Tool '{tool}' requires an admin user.",
        ).as_result()
        return f"{identity.requested_name}: BLOCKED", result
    if is_public_blocked_tool(tool) and not _owner_is_admin(owner):
        result = deny_resolved_tool(
            identity,
            code="role_denied",
            reason=(
                f"Tool '{tool}' is restricted to admin users on this deployment. "
                "Ask an admin to perform this action or grant the needed permission."
            ),
        ).as_result()
        return f"{identity.requested_name}: BLOCKED", result

    # Normalize and validate model-produced arguments before risk policy can
    # return either allow or approval-required. An approval must bind to the
    # exact typed object the executor understood, never an unparsed fence body.
    try:
        action = build_action_envelope(
            identity,
            content,
            owner=owner,
            session_id=session_id,
            request_id=request_id,
            origin=authority.origin,
        )
    except ActionArgumentError as exc:
        desc = f"{tool}: BLOCKED"
        result = deny_resolved_tool(
            identity,
            code="invalid_arguments",
            reason=str(exc),
        ).as_result()
        if exc.path:
            result["argument_path"] = exc.path
        return desc, result
    # From here onward dispatch sees only content deterministically rendered
    # from the schema-validated object. This is essential for later approval
    # replay: stored arguments, not raw model prose, are the source of truth.
    content = action.execution_content()

    # Forbidden filesystem targets are not approvable. Reject them before a
    # Level-3 proposal is stored so the Approval Centre never asks a human to
    # authorize an operation the confined runtime will categorically refuse.
    if tool in {"read_file", "write_file", "edit_file"}:
        candidate_path = action.arguments.get("path")
        if isinstance(candidate_path, str):
            try:
                _resolve_tool_path(candidate_path)
            except ValueError as exc:
                result = deny_resolved_tool(
                    identity,
                    code="path_not_allowed",
                    reason=str(exc),
                ).as_result()
                result["argument_path"] = "path"
                return f"{identity.requested_name}: BLOCKED", result

    registry_decision = evaluate_resolved_tool_policy(identity, authority=authority)
    execution_ledger = None
    auto_approval_grant = None
    accepted_approval_grant = None
    if not registry_decision.may_execute:
        if registry_decision.kind is not PolicyDecisionKind.REQUIRE_APPROVAL:
            return f"{tool}: BLOCKED", registry_decision.as_result()

        try:
            from src.action_ledger import ApprovalGrant, get_action_ledger

            execution_ledger = get_action_ledger()
        except Exception:
            ApprovalGrant = None  # type: ignore[assignment,misc]

        if approval_grant is not None:
            if (
                ApprovalGrant is None
                or not isinstance(approval_grant, ApprovalGrant)
                or not approval_grant.matches(action)
            ):
                result = deny_resolved_tool(
                    identity,
                    code="approval_evidence_mismatch",
                    reason="Approval evidence does not match this exact action.",
                ).as_result()
                return f"{tool}: BLOCKED", result
            accepted_approval_grant = approval_grant
        elif execution_ledger is not None and int(identity.definition.effective_risk) < 3:
            # Exact standing rules are scoped to owner, operation/version,
            # typed arguments, surface, and trusted origin. Level 3 is never
            # eligible here or inside the ledger transaction.
            auto_approval_grant = execution_ledger.claim_matching_rule(
                action,
                risk_level=int(identity.definition.effective_risk),
                approval_reason=registry_decision.reason,
                origin=action.origin.value,
                execution_context={"workspace": get_active_workspace()},
            )
            if auto_approval_grant is not None and auto_approval_grant.matches(action):
                accepted_approval_grant = auto_approval_grant
            elif auto_approval_grant is not None:
                logger.error(
                    "Ledger returned mismatched standing approval id=%r tool=%r",
                    auto_approval_grant.approval_id,
                    tool,
                )
                try:
                    # Close the ledger-owned claim without dispatching. The
                    # nonce is consumed only to make the row terminal; it is
                    # never treated as evidence for this mismatched action.
                    execution_ledger.consume_grant(auto_approval_grant)
                    execution_ledger.fail_claimed_execution(
                        auto_approval_grant,
                        "Standing approval evidence did not match the action.",
                    )
                except Exception:
                    logger.exception("Could not close mismatched standing approval")
                auto_approval_grant = None

        if accepted_approval_grant is not None:
            try:
                if execution_ledger is None:
                    raise RuntimeError("Approval ledger is unavailable.")
                execution_ledger.consume_grant(accepted_approval_grant)
            except Exception as exc:
                logger.warning(
                    "Approval consumption failed tool=%r approval_id=%r: %s",
                    tool,
                    getattr(accepted_approval_grant, "approval_id", None),
                    exc,
                )
                result = deny_resolved_tool(
                    identity,
                    code="approval_evidence_unavailable",
                    reason="Approval evidence is invalid, expired, or already consumed.",
                ).as_result()
                return f"{tool}: BLOCKED", result
        else:
            result = registry_decision.as_result()
            try:
                if execution_ledger is None:
                    raise RuntimeError("Approval ledger is unavailable.")
                proposal = execution_ledger.propose(
                    action,
                    risk_level=int(identity.definition.effective_risk),
                    approval_reason=registry_decision.reason,
                    origin=action.origin.value,
                    execution_context={"workspace": get_active_workspace()},
                )
            except Exception:
                logger.exception("Could not persist approval proposal tool=%r", tool)
                result.update(
                    {
                        "error": "Approval storage is unavailable; the action was not executed.",
                        "policy_code": "approval_persistence_failed",
                        "approval_required": True,
                    }
                )
                return f"{tool}: APPROVAL REQUIRED", result
            if (
                proposal.get("tool_name") != action.tool_name
                or proposal.get("tool_version") != action.tool_version
                or proposal.get("arguments_hash") != action.arguments_hash
                or proposal.get("surface") != action.surface.value
                or proposal.get("origin") != action.origin.value
            ):
                result.update(
                    {
                        "error": (
                            "This request id is already bound to a different action "
                            "revision; it cannot authorize these arguments."
                        ),
                        "policy_code": "approval_action_mismatch",
                        "approval_required": False,
                        "approval_id": proposal["id"],
                        "approval_status": proposal["status"],
                    }
                )
                return f"{tool}: BLOCKED", result
            if proposal["status"] != "pending":
                result.update(
                    {
                        "error": (
                            "This exact request already has a non-pending action "
                            f"record ({proposal['status']}); it cannot be replayed."
                        ),
                        "policy_code": "approval_action_not_pending",
                        "approval_required": False,
                        "approval_id": proposal["id"],
                        "approval_status": proposal["status"],
                    }
                )
                return f"{tool}: BLOCKED", result
            result.update(
                {
                    "approval_required": True,
                    "approval_id": proposal["id"],
                    "approval_status": proposal["status"],
                    "approval_expires_at": proposal["expires_at"],
                    "approval_revision": proposal["revision"],
                    "approval_url": f"/approvals/{proposal['id']}",
                    "action_preview": action.as_preview(),
                }
            )
            return f"{tool}: APPROVAL REQUIRED", result
    elif approval_grant is not None:
        result = deny_resolved_tool(
            identity,
            code="unexpected_approval_evidence",
            reason="Approval evidence was supplied for an action that does not require it.",
        ).as_result()
        return f"{tool}: BLOCKED", result

    try:
        verification_plan = None
        if accepted_approval_grant is not None:
            verification_plan = prepare_action_verification(
                identity.definition,
                action,
                path_resolver=_resolve_tool_path,
            )
        desc, result = await _dispatch_resolved_binding(
            binding,
            content,
            session_id=session_id,
            owner=owner,
            request_id=request_id,
            progress_cb=progress_cb,
            approval_grant=accepted_approval_grant,
        )
    except asyncio.CancelledError:
        if auto_approval_grant is not None and execution_ledger is not None:
            try:
                execution_ledger.fail_claimed_execution(
                    auto_approval_grant,
                    "Auto-approved execution was cancelled or exceeded its timeout.",
                )
            except Exception:
                logger.exception(
                    "Could not close cancelled auto-approved action %s",
                    auto_approval_grant.approval_id,
                )
        raise
    except Exception as exc:
        if auto_approval_grant is not None and execution_ledger is not None:
            try:
                execution_ledger.fail_claimed_execution(auto_approval_grant, str(exc))
            except Exception:
                logger.exception(
                    "Could not close failed auto-approved action %s",
                    auto_approval_grant.approval_id,
                )
        raise

    try:
        if verification_plan is not None:
            outcome = verify_action_result(verification_plan, result)
            result = result_with_verification(result, outcome)

        if auto_approval_grant is not None and execution_ledger is not None:
            # The rule-created proposal has no route waiting to close it; the
            # executor therefore owns its success/failure lifecycle.
            result["auto_approved"] = True
            result["approval_id"] = auto_approval_grant.approval_id
            completed = execution_ledger.finish_execution(
                auto_approval_grant,
                result,
                verification_status=(
                    verification_status_from_result(result) or "indeterminate"
                ),
            )
            result["approval_status"] = completed["status"]
    except Exception as exc:
        if auto_approval_grant is not None and execution_ledger is not None:
            try:
                execution_ledger.fail_claimed_execution(auto_approval_grant, str(exc))
            except Exception:
                logger.exception(
                    "Could not close verification failure for auto-approved action %s",
                    auto_approval_grant.approval_id,
                )
        raise

    logger.info(
        "Tool executed via binding=%s namespace=%r target=%r -> exit_code=%s",
        binding.kind.value,
        binding.namespace,
        binding.target,
        result.get("exit_code", "n/a"),
    )
    return desc, result


# ---------------------------------------------------------------------------
# Result formatting
# ---------------------------------------------------------------------------

# Keys handled by the dedicated branches below — never echo them as raw JSON.
_FORMATTER_HANDLED_KEYS = {
    "stdout", "stderr", "exit_code", "content", "size",
    "response", "results", "session_id", "name", "model", "session_name",
    "success", "path", "action", "title", "doc_id", "version", "applied",
    "error", "output",
}


def format_tool_result(description: str, result: Dict) -> str:
    """Format a tool result into text for feeding back to the LLM."""
    parts = [f"### {description}"]

    if "stdout" in result:
        if result.get("stdout"):
            parts.append(f"**stdout:**\n```\n{result['stdout']}\n```")
        if result.get("stderr"):
            parts.append(f"**stderr:**\n```\n{result['stderr']}\n```")
        parts.append(f"**exit_code:** {result.get('exit_code', 'unknown')}")
    elif "output" in result:
        # bash / python canonical result shape: {"output": ..., "exit_code": ...}
        parts.append(f"```\n{result['output']}\n```")
        if result.get("exit_code") not in (0, None):
            parts.append(f"**exit_code:** {result['exit_code']}")
    elif "content" in result:
        parts.append(f"**content ({result.get('size', '?')} chars):**\n```\n{result['content']}\n```")
    elif "response" in result:
        model = result.get("model", result.get("session_name", ""))
        if model:
            parts.append(f"**{model} responded:**\n{result['response']}")
        else:
            parts.append(result["response"])
    elif "results" in result:
        parts.append(result["results"])
    elif "session_id" in result and "name" in result:
        parts.append(f"Session created: **{result['name']}** (id: `{result['session_id']}`, model: {result.get('model', 'unknown')})")
    elif "success" in result:
        if result["success"]:
            parts.append(f"File written: {result['path']} ({result['size']} bytes)")
        else:
            parts.append(f"Error: {result.get('error', 'unknown')}")
    elif "action" in result:
        action = result["action"]
        if action == "create":
            parts.append(f"Document created: \"{result.get('title', '')}\" (id: {result['doc_id']}, v{result['version']})")
        elif action == "update":
            parts.append(f"Document updated: \"{result.get('title', '')}\" (v{result['version']})")
        elif action == "edit":
            parts.append(f'Document edited: "{result.get("title", "")}" (v{result.get("version", "?")}, {result.get("applied", 0)} edit(s) applied)')
    elif "error" in result:
        parts.append(f"**Error:** {result['error']}")

    # Result shapes may carry an error alongside stdout/stderr (notably
    # subprocess timeouts).  The shape-specific branch above must not hide it,
    # but avoid echoing it again when a stream already contains the same text.
    error = result.get("error")
    if error not in (None, ""):
        error_text = str(error)
        if not any(error_text in part for part in parts[1:]):
            parts.append(f"**Error:** {error_text}")

    # Surface any additional structured payload (events, tasks, notes, calendars,
    # documents, attachments, etc.) that the dedicated branches above don't show.
    # Without this, tools that return {"response": "...", "events": [...]} would
    # silently drop the events list and the model would only see the summary line.
    extra = {k: v for k, v in result.items() if k not in _FORMATTER_HANDLED_KEYS}
    if extra:
        try:
            extra_json = json.dumps(extra, indent=2, default=str, ensure_ascii=False)
            # Cap to avoid blowing the context window on huge payloads.
            if len(extra_json) > 8000:
                extra_json = extra_json[:8000] + f"\n... (truncated, {len(extra_json)} chars total)"
            parts.append(f"**data:**\n```json\n{extra_json}\n```")
        except (TypeError, ValueError):
            pass

    return "\n".join(parts)
