"""Characterization tests for the SAFE-002 registry foundation."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "module",
    [
        "src.tool_types",
        "src.tool_registry",
        "src.tool_schema_catalog",
        "src.tool_schemas",
        "src.tool_parsing",
        "src.tool_security",
        "src.tool_policy",
    ],
)
def test_tool_modules_cold_import_in_fresh_process(module: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 0, completed.stderr


def test_building_static_registry_does_not_import_runtime_layers() -> None:
    script = r'''
import sys
from src.tool_registry import BUILTIN_TOOL_NAMES, build_builtin_registry

registry = build_builtin_registry()
assert len(registry) == len(BUILTIN_TOOL_NAMES)

forbidden = (
    "app",
    "core.database",
    "routes",
    "src.agent_loop",
    "src.agent_tools",
    "src.tool_execution",
    "src.tool_index",
    "src.tool_parsing",
    "src.tool_security",
)
loaded = sorted(
    name for name in sys.modules
    if any(name == item or name.startswith(item + ".") for item in forbidden)
)
assert not loaded, loaded
'''
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 0, completed.stderr


def test_plan_projection_and_known_names_are_cold_import_safe() -> None:
    script = r'''
import sys
from src.tool_registry import BUILTIN_TOOL_NAMES, PLAN_MODE_ALLOWED_TOOL_NAMES
from src.tool_policy import known_tool_names
from src.tool_security import PLAN_MODE_READONLY_TOOLS, plan_mode_disabled_tools

assert PLAN_MODE_READONLY_TOOLS is PLAN_MODE_ALLOWED_TOOL_NAMES
assert plan_mode_disabled_tools() == set(BUILTIN_TOOL_NAMES - PLAN_MODE_ALLOWED_TOOL_NAMES)
assert known_tool_names() == set(BUILTIN_TOOL_NAMES) | {"builtin_browser"}

forbidden = (
    "app",
    "core.database",
    "routes",
    "src.agent_loop",
    "src.agent_tools",
    "src.tool_execution",
    "src.tool_schema_catalog",
    "src.tool_schemas",
)
loaded = sorted(
    name for name in sys.modules
    if any(name == item or name.startswith(item + ".") for item in forbidden)
)
assert not loaded, loaded
'''
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 0, completed.stderr


def test_tail_serve_output_is_reachable_through_native_and_fenced_ingress() -> None:
    # Importing the compatibility facade first is the only order that works in
    # the baseline. The cold-import regression above separately removes that
    # historical constraint.
    from src.agent_tools import TOOL_TAGS
    from src.tool_parsing import parse_tool_blocks
    from src.tool_schemas import function_call_to_tool_block

    arguments = {"session_id": "serve-abc12345", "tail": 400}

    assert "tail_serve_output" in TOOL_TAGS

    native = function_call_to_tool_block(
        "tail_serve_output",
        json.dumps(arguments),
    )
    assert native is not None
    assert native.tool_type == "tail_serve_output"
    assert json.loads(native.content) == arguments

    fenced = parse_tool_blocks(
        "```tail_serve_output\n"
        '{"session_id":"serve-abc12345","tail":400}\n'
        "```"
    )
    assert len(fenced) == 1
    assert fenced[0].tool_type == "tail_serve_output"
    assert json.loads(fenced[0].content) == arguments
