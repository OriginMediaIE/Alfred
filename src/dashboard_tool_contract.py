"""Schema for source-grounded executive dashboard reads."""

DASHBOARD_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "query_dashboard",
        "description": "Read the owner-scoped Today dashboard or a source-grounded morning, evening, or weekly review without changing records.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["today", "morning", "evening", "weekly"]},
                "timezone": {"type": "string", "maxLength": 100},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
}
