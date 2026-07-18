"""Compatibility facade for native tool schemas and call conversion.

Static schema data lives in :mod:`src.tool_schema_catalog`, which is safe for
the canonical registry to import. Existing callers retain this module path.
"""

from src.tool_schema_catalog import (
    FUNCTION_TOOL_SCHEMAS,
    function_call_to_tool_block,
)

__all__ = ["FUNCTION_TOOL_SCHEMAS", "function_call_to_tool_block"]
