"""Execute the Approval Centre's pure risk and mutation helpers in Node."""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parent.parent
_HAS_NODE = shutil.which("node") is not None


def _run_node(source: str) -> dict:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", source],
        cwd=_REPO,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_normalization_preserves_exact_arguments_context_and_level_three_rule():
    output = _run_node(textwrap.dedent("""
        import {
          extractApprovalItems,
          normalizeApproval,
        } from './static/js/approvalCore.js';

        const payload = { approvals: [{
          id: 'act-1',
          revision: 7,
          arguments_hash: 'sha256:exact',
          arguments_json: '{"recipient":"ops@example.test","subject":"Quarterly plan"}',
          tool_name: 'send_email',
          tool_version: 3,
          risk_level: 'Level 3',
          status: 'pending',
          approval_reason: 'External side effect',
          session_id: 'chat-9',
          session_title: 'Operations review',
          affected_records: [{type: 'email', id: 'draft-2', title: 'Quarterly plan'}],
        }] };
        const item = normalizeApproval(extractApprovalItems(payload)[0]);
        console.log(JSON.stringify({
          id: item.id,
          revision: item.revision,
          hash: item.argumentsHash,
          arguments: item.arguments,
          tool: item.tool,
          riskLevel: item.riskLevel,
          alwaysAllowEligible: item.alwaysAllowEligible,
          conversation: [item.sessionId, item.conversationTitle],
          affected: item.affectedRecords,
        }));
    """))

    assert output == {
        "id": "act-1",
        "revision": 7,
        "hash": "sha256:exact",
        "arguments": {"recipient": "ops@example.test", "subject": "Quarterly plan"},
        "tool": "send_email",
        "riskLevel": 3,
        "alwaysAllowEligible": False,
        "conversation": ["chat-9", "Operations review"],
        "affected": [
            {
                "label": "Quarterly plan",
                "id": "draft-2",
                "type": "email",
                "url": "",
            }
        ],
    }


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_mutations_carry_revision_and_approval_also_carries_argument_hash():
    output = _run_node(textwrap.dedent("""
        import { buildMutationBody, normalizeApproval } from './static/js/approvalCore.js';
        const item = normalizeApproval({
          id: 'act-2', revision: 11, arguments_hash: 'h11',
          arguments: {calendar_id: 'work', title: 'Review'},
          tool_name: 'create_calendar_event', risk_level: 2, status: 'pending',
        });
        console.log(JSON.stringify({
          once: buildMutationBody(item, 'approve', {alwaysAllow: false}),
          standing: buildMutationBody(item, 'approve', {alwaysAllow: true}),
          reject: buildMutationBody(item, 'reject', {reason: '  Wrong calendar  '}),
          rejectNoReason: buildMutationBody(item, 'reject'),
          cancel: buildMutationBody(item, 'cancel', {reason: '  Stop now  '}),
          edit: buildMutationBody(item, 'edit', {arguments: {calendar_id: 'personal', title: 'Review'}}),
          standingEligible: item.alwaysAllowEligible,
        }));
    """))

    guard = {"revision": 11}
    approval_guard = {**guard, "arguments_hash": "h11"}
    assert output["once"] == {**approval_guard, "always_allow": False}
    assert output["standing"] == {**approval_guard, "always_allow": True}
    assert output["reject"] == {**guard, "reason": "Wrong calendar"}
    assert output["rejectNoReason"] == guard
    assert output["cancel"] == {**guard, "reason": "Stop now"}
    assert output["edit"] == {
        **guard,
        "arguments": {"calendar_id": "personal", "title": "Review"},
    }
    assert output["standingEligible"] is True


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_edit_rejects_non_object_top_level_json():
    output = _run_node(textwrap.dedent("""
        import { buildMutationBody, normalizeApproval } from './static/js/approvalCore.js';
        const item = normalizeApproval({id: 'x', revision: 1, arguments_hash: 'h'});
        let message = '';
        try { buildMutationBody(item, 'edit', {arguments: ['not', 'an', 'object']}); }
        catch (error) { message = error.message; }
        console.log(JSON.stringify({message}));
    """))
    assert output["message"] == "Edited arguments must be a JSON object."
