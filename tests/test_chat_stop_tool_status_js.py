"""Browser-side regression for truthful tool status after explicit Stop."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
HAS_NODE = shutil.which("node") is not None


@pytest.mark.skipif(not HAS_NODE, reason="node binary not on PATH")
def test_cancelled_tool_node_no_longer_says_running() -> None:
    script = r'''
import { settleCancelledToolNode } from './static/js/toolRunStatus.js';

const classes = new Set(['agent-thread-node', 'running']);
const elements = {
  '.agent-thread-wave': { textContent: '▁▂▃' },
  '.agent-thread-icon': { textContent: '▶' },
  '.agent-thread-tool': { textContent: 'Running' },
};
const header = {
  appendChild(element) { elements['.agent-thread-status'] = element; },
};
globalThis.document = {
  createElement() { return { className: '', textContent: '' }; },
};
const node = {
  dataset: { tool: 'bash' },
  _waveInterval: 1,
  _elapsedTicker: 2,
  classList: {
    add(name) { classes.add(name); },
    remove(name) { classes.delete(name); },
    contains(name) { return classes.has(name); },
  },
  querySelector(selector) {
    if (selector === '.agent-thread-header') return header;
    return elements[selector] || null;
  },
};

settleCancelledToolNode(node);
console.log(JSON.stringify({
  classes: [...classes],
  wave: elements['.agent-thread-wave'].textContent,
  icon: elements['.agent-thread-icon'].textContent,
  label: elements['.agent-thread-tool'].textContent,
  status: elements['.agent-thread-status'].textContent,
  waveInterval: node._waveInterval,
  elapsedTicker: node._elapsedTicker,
}));
'''
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert "running" not in result["classes"]
    assert "cancelled" in result["classes"]
    assert result["wave"] == ""
    assert result["icon"] == "■"
    assert result["label"] == "Bash"
    assert result["status"] == "cancelled"
    assert result["waveInterval"] is None
    assert result["elapsedTicker"] is None


def test_chat_wires_tool_identity_and_cancelled_settling_helper() -> None:
    source = (ROOT / "static" / "js" / "chat.js").read_text(encoding="utf-8")

    assert "import { settleCancelledToolNode } from './toolRunStatus.js';" in source
    assert "node.dataset.tool = json.tool;" in source
    assert "settleCancelledToolNode(node);" in source
