"""Dependency-free value types shared by the agent tool pipeline.

This module deliberately imports no registry, parser, executor, facade, route,
or provider code.  Low-level tool modules can therefore share invocation types
without relying on the historical ``src.agent_tools`` import order.
"""

from __future__ import annotations

from typing import NamedTuple


class ToolBlock(NamedTuple):
    """One legacy fenced/native tool invocation awaiting validation/execution."""

    tool_type: str
    content: str
