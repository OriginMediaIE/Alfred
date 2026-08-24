"""Pure schemas and action names for the personal-work agent tools.

This module intentionally has no database or service imports.  The native
schema catalogue and safety registry can import it without constructing the
work service or opening a database connection.
"""

from __future__ import annotations


QUERY_WORK_ACTIONS = frozenset(
    {
        "list_tasks",
        "get_task",
        "list_projects",
        "get_project",
        "list_commitments",
        "get_commitment",
        "daily_focus",
        "blocked_tasks",
        "overdue_commitments",
        "get_plan",
        "due_reminders",
        "list_receipts",
    }
)

MANAGE_WORK_ACTIONS = frozenset(
    {
        "create_task",
        "update_task",
        "create_project",
        "update_project",
        "create_commitment",
        "update_commitment",
        "create_plan",
        "update_plan",
        "apply_plan",
    }
)

DELETE_WORK_ACTIONS = frozenset({"delete_task", "delete_project", "delete_commitment"})


QUERY_WORK_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "query_work",
        "description": (
            "Read personal tasks, projects, commitments, reminders, planning "
            "signals and mutation receipts. This tool never changes records."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": sorted(QUERY_WORK_ACTIONS)},
                "task_id": {"type": "string"},
                "project_id": {"type": "string"},
                "commitment_id": {"type": "string"},
                "plan_id": {"type": "string"},
                "status": {"type": "string"},
                "review_state": {"type": "string"},
                "tag": {"type": "string"},
                "context": {"type": "string"},
                "contexts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 50,
                },
                "query": {"type": "string", "maxLength": 500},
                "due_before": {"type": "string", "format": "date-time"},
                "as_of": {"type": "string", "format": "date-time"},
                "plan_date": {"type": "string", "format": "date-time"},
                "available_minutes": {"type": "integer", "minimum": 15, "maximum": 1440},
                "energy": {"type": "string", "enum": ["low", "medium", "high"]},
                "include_completed": {"type": "boolean"},
                "include_archived": {"type": "boolean"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
}


MANAGE_WORK_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "manage_work",
        "description": (
            "Create or update local personal tasks, projects, commitments and "
            "correctable planning drafts. Requires a claimed approved action."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": sorted(MANAGE_WORK_ACTIONS)},
                "task_id": {"type": "string"},
                "project_id": {"type": "string"},
                "commitment_id": {"type": "string"},
                "plan_id": {"type": "string"},
                "revision": {"type": "integer", "minimum": 1},
                "record": {
                    "type": "object",
                    "description": (
                        "Validated record fields. Tasks support title, description, status, priority, "
                        "dates, durations, project/milestone/parent, tags, contexts, assignees, energy, "
                        "effort, recurrence, dependencies, source, references, reminders and completion notes."
                    ),
                    "additionalProperties": True,
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
}


DELETE_WORK_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "delete_work",
        "description": (
            "Permanently delete one personal task, project or commitment after explicit approval."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": sorted(DELETE_WORK_ACTIONS)},
                "task_id": {"type": "string"},
                "project_id": {"type": "string"},
                "commitment_id": {"type": "string"},
                "revision": {"type": "integer", "minimum": 1},
            },
            "required": ["action", "revision"],
            "additionalProperties": False,
        },
    },
}


WORK_TOOL_SCHEMAS = (
    QUERY_WORK_TOOL_SCHEMA,
    MANAGE_WORK_TOOL_SCHEMA,
    DELETE_WORK_TOOL_SCHEMA,
)


__all__ = [
    "DELETE_WORK_ACTIONS",
    "DELETE_WORK_TOOL_SCHEMA",
    "MANAGE_WORK_ACTIONS",
    "MANAGE_WORK_TOOL_SCHEMA",
    "QUERY_WORK_ACTIONS",
    "QUERY_WORK_TOOL_SCHEMA",
    "WORK_TOOL_SCHEMAS",
]
