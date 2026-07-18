"""Canonical identity and surface inventory for built-in agent tools.

SAFE-002 starts by moving name ownership out of the high-fan-out
``src.agent_tools`` facade.  Typed definitions and policy/runtime bindings are
added around this dependency-light foundation in subsequent registry slices.
Importing this module must stay side-effect free.
"""

from __future__ import annotations


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
