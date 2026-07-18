"""Browser-state regressions for versioned active-plan updates."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
HAS_NODE = shutil.which("node") is not None


@pytest.mark.skipif(not HAS_NODE, reason="node binary not on PATH")
def test_plan_update_applies_only_to_matching_current_version_and_refreshes_view():
    script = r'''
const values = new Map();
globalThis.localStorage = {
  getItem(key) { return values.has(key) ? values.get(key) : null; },
  setItem(key, value) { values.set(key, String(value)); },
  removeItem(key) { values.delete(key); },
};
const events = [];
globalThis.CustomEvent = class CustomEvent {
  constructor(type, options = {}) { this.type = type; this.detail = options.detail; }
};
globalThis.window = { dispatchEvent(event) { events.push(event); } };

const { activatePlan, applyPlanUpdate, getActivePlan } = await import('./static/js/planState.js');
activatePlan({
  sessionId: 'session-a',
  planId: 'plan-a',
  text: '- [ ] first\n- [ ] second',
  version: 4,
});

const dock = { textContent: '', dataset: {} };
const refreshDock = (record) => {
  dock.textContent = record.text;
  dock.dataset.planId = record.plan_id;
  dock.dataset.version = String(record.version);
};

const wrongSession = applyPlanUpdate({
  session_id: 'session-b', plan_id: 'plan-a', base_version: 4, version: 5,
  plan: '- [x] wrong session',
}, 'session-a', { onApplied: refreshDock });
const wrongPlan = applyPlanUpdate({
  session_id: 'session-a', plan_id: 'plan-old', base_version: 4, version: 5,
  plan: '- [x] wrong plan',
}, 'session-a', { onApplied: refreshDock });
const stale = applyPlanUpdate({
  session_id: 'session-a', plan_id: 'plan-a', base_version: 3, version: 4,
  plan: '- [x] stale',
}, 'session-a', { onApplied: refreshDock });
const applied = applyPlanUpdate({
  session_id: 'session-a', plan_id: 'plan-a', base_version: 4, version: 5,
  plan: '- [x] first\n- [ ] second',
}, 'session-a', { onApplied: refreshDock });
const replay = applyPlanUpdate({
  session_id: 'session-a', plan_id: 'plan-a', base_version: 4, version: 5,
  plan: '- [x] replay',
}, 'session-a', { onApplied: refreshDock });

console.log(JSON.stringify({
  wrongSession, wrongPlan, stale, applied, replay,
  active: getActivePlan('session-a'),
  dock,
  eventTypes: events.map((event) => event.type),
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
    assert result["wrongSession"]["applied"] is False
    assert result["wrongPlan"]["applied"] is False
    assert result["stale"]["applied"] is False
    assert result["replay"]["applied"] is False
    assert result["applied"]["applied"] is True
    assert result["active"]["text"] == "- [x] first\n- [ ] second"
    assert result["active"]["version"] == 5
    assert result["dock"] == {
        "textContent": "- [x] first\n- [ ] second",
        "dataset": {"planId": "plan-a", "version": "5"},
    }
    assert result["eventTypes"] == ["odysseus:plan-updated"]


def test_chat_uses_versioned_plan_modules_not_removed_undefined_helper():
    source = (ROOT / "static" / "js" / "chat.js").read_text(encoding="utf-8")

    assert "from './planState.js'" in source
    assert "from './planWindow.js'" in source
    assert "planStateModule.applyPlanUpdate" in source
    assert "planWindowModule.updateOpenPlanWindow" in source
    assert "approved_plan_version" in source
    assert "approved_plan_id" in source
    assert "_setStoredPlan(" not in source
