"""Dependency-light canonical schemas for private knowledge agent tools."""

QUERY_KNOWLEDGE_ACTIONS = frozenset({"search", "list_sources", "get_source", "list_memories"})
MANAGE_KNOWLEDGE_ACTIONS = frozenset({"ingest_text", "create_memory", "update_memory", "rebuild_source", "delete_derivatives"})
DELETE_KNOWLEDGE_ACTIONS = frozenset({"delete_source", "delete_memory"})


def _tool(name, description, actions, *, destructive=False):
    properties = {
        "action": {"type": "string", "enum": sorted(actions)},
        "source_id": {"type": "string"},
        "memory_id": {"type": "string"},
        "query": {"type": "string", "maxLength": 2000},
        "source_type": {"type": "string"},
        "sensitivity": {"type": "string"},
        "status": {"type": "string"},
        "date_from": {"type": "string"},
        "date_to": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
        "offset": {"type": "integer", "minimum": 0},
        "include_content": {"type": "boolean"},
        "record": {"type": "object", "additionalProperties": True},
        "revision": {"type": "integer", "minimum": 1},
        "purge": {"type": "boolean"},
    }
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": ["action"] + (["revision"] if destructive else []), "additionalProperties": False}}}


QUERY_KNOWLEDGE_TOOL_SCHEMA = _tool("query_knowledge", "Search the owner-scoped private knowledge index with hybrid retrieval and return source-linked excerpts, or inspect sources and governed memories without changing them.", QUERY_KNOWLEDGE_ACTIONS)
MANAGE_KNOWLEDGE_TOOL_SCHEMA = _tool("manage_knowledge", "Ingest user-approved text, govern memory records, rebuild one source index, or delete derived chunks after an approved local mutation. Uploaded files use the Knowledge UI.", MANAGE_KNOWLEDGE_ACTIONS)
DELETE_KNOWLEDGE_TOOL_SCHEMA = _tool("delete_knowledge", "Delete one exact knowledge source or governed memory after explicit destructive approval and revision checking.", DELETE_KNOWLEDGE_ACTIONS, destructive=True)
KNOWLEDGE_TOOL_SCHEMAS = (QUERY_KNOWLEDGE_TOOL_SCHEMA, MANAGE_KNOWLEDGE_TOOL_SCHEMA, DELETE_KNOWLEDGE_TOOL_SCHEMA)
