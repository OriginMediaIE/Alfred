"""Static contract checks for the OM Approval Centre entry point and UI."""

from pathlib import Path


_REPO = Path(__file__).resolve().parent.parent
_INDEX = (_REPO / "static" / "index.html").read_text(encoding="utf-8")
_APP = (_REPO / "static" / "app.js").read_text(encoding="utf-8")
_CENTRE = (_REPO / "static" / "js" / "approvalCentre.js").read_text(encoding="utf-8")
_STYLE = (_REPO / "static" / "style.css").read_text(encoding="utf-8")
_SW = (_REPO / "static" / "sw.js").read_text(encoding="utf-8")


def test_approval_centre_is_first_class_sidebar_rail_and_route_navigation():
    assert 'id="tool-approvals-btn"' in _INDEX
    assert 'id="rail-approvals"' in _INDEX
    assert '>Approval Centre</span>' in _INDEX
    assert 'data-ui-key="tool-approvals"' in _INDEX
    assert "'/approvals': 'Approval Centre — OM'" in _INDEX

    assert "import approvalCentreModule from './js/approvalCentre.js'" in _APP
    assert "'rail-approvals': 'tool-approvals-btn'" in _APP
    assert "'/approvals': () => document.getElementById('tool-approvals-btn')?.click()" in _APP
    assert "approvalCentreModule.init();" in _APP


def test_view_exposes_required_review_fields_and_decisions():
    required_copy = [
        "Exact arguments",
        "Why approval is required",
        "Affected records",
        "Requested from",
        "Approve once",
        "Always allow exact action",
        "Reason (optional)",
        "Completed action history",
        "Action history",
        "Verification",
        "Stop action",
        "Confirm stop",
        "marked for reconciliation",
    ]
    for text in required_copy:
        assert text in _CENTRE

    assert "item.riskLevel >= 3" in _CENTRE
    assert "Level 3 actions always require an explicit one-time confirmation." in _CENTRE
    assert "always.disabled = true" in _CENTRE


def test_api_calls_use_detail_endpoint_and_stale_write_guards():
    assert "`${API_ROOT}?status=${encodeURIComponent(state.tab)}`" in _CENTRE
    assert "`${API_ROOT}/${encodeURIComponent(id)}`" in _CENTRE
    assert "path += '/approve'" in _CENTRE
    assert "path += '/reject'" in _CENTRE
    assert "path += '/cancel'" in _CENTRE
    assert "method = 'PATCH'" in _CENTRE
    assert "buildMutationBody(fresh, kind, extras)" in _CENTRE
    assert "latest.revision !== original.revision" in _CENTRE
    assert "latest.argumentsHash !== original.argumentsHash" in _CENTRE
    assert "error.status === 409" in _CENTRE
    assert "The action was updated or decided elsewhere" in _CENTRE


def test_accessibility_and_responsive_safety_styles_are_present():
    assert 'role="dialog"' in _CENTRE
    assert 'role="tablist"' in _CENTRE
    assert 'aria-live="polite"' in _CENTRE
    assert "setAttribute('aria-label', `Edit exact JSON arguments" in _CENTRE
    assert ".approval-btn:focus-visible" in _STYLE
    assert "@media (max-width: 768px)" in _STYLE
    assert "@media (prefers-reduced-motion: reduce)" in _STYLE
    assert ".approval-nav-badge[hidden]" in _STYLE


def test_approval_modules_are_in_the_offline_shell():
    assert "'/static/js/approvalCentre.js'" in _SW
    assert "'/static/js/approvalCore.js'" in _SW
