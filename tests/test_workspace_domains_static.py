"""Static regressions for first-class Meetings and Knowledge UI workspaces."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static/index.html").read_text(encoding="utf-8")
JS = (ROOT / "static/js/workspaceDomains.js").read_text(encoding="utf-8")
CSS = (ROOT / "static/style.css").read_text(encoding="utf-8")


def test_sidebar_exposes_meetings_and_knowledge_as_first_class_modules():
    assert 'id="tool-meetings-btn"' in HTML
    assert 'id="tool-knowledge-btn"' in HTML
    assert 'id="tool-today-btn"' in HTML
    assert 'id="tool-automations-btn"' in HTML
    assert '/static/js/workspaceDomains.js' in HTML


def test_meeting_ui_requires_consent_and_never_claims_realtime():
    assert "consent_confirmed" in JS
    assert "Confirm attendee consent before recording" in JS
    assert "Transcription is post-meeting, not realtime" in JS
    assert "navigator.mediaDevices.getUserMedia" in JS
    assert "MediaRecorder" in JS
    assert "/transcription-jobs" in JS


def test_meeting_ui_exposes_source_review_and_explicit_knowledge_save():
    assert "/analysis-jobs" in JS
    assert "transcript-span evidence" in JS
    assert "/claims/${encodeURIComponent(claim.id)}/review" in JS
    assert "Confirm decision" in JS
    assert "Save this private transcript" in JS
    assert "timestamps and speaker evidence" in JS


def test_knowledge_ui_is_grounded_accessible_and_responsive():
    assert "/api/knowledge/search" in JS
    assert "Insufficient evidence" in JS
    assert "item.source_url" in JS
    assert 'aria-live' in JS
    assert "@media(max-width:760px)" in CSS
    assert "prefers-reduced-motion" in CSS
    assert "Document vault" in JS
    assert "/analyze-vault" in JS
    assert "Approve vault metadata" in JS
    assert "Allow memory suggestions from this source" in JS


def test_today_dashboard_has_required_signals_and_quick_command():
    assert "/api/dashboard/today" in JS
    for label in (
        "Next event",
        "Priority tasks",
        "Messages requiring attention",
        "Pending approvals",
        "Unresolved commitments",
        "Meeting actions",
        "Important reminders",
        "Full schedule",
        "Morning briefing",
        "Integration health",
        "Local Core health",
        "Attention returned",
        "Proposal acceptance",
        "Briefing history",
    ):
        assert label in JS
    assert "Ask OM" in JS
    assert "/api/dashboard/metrics?days=30" in JS
    assert "/api/dashboard/briefings/${kind}/runs" in JS


def test_work_workspace_exposes_complete_planning_and_provenance_loop():
    for label in (
        "Daily focus",
        "Blocked",
        "Overdue commitments",
        "Due reminders",
        "Activity",
        "Dependencies",
        "Sources and references",
        "Status history",
    ):
        assert label in JS
    assert "/api/work/planning/focus" in JS
    assert "/api/work/audit?entity_type=" in JS


def test_automation_ui_exposes_bounded_definitions_and_run_history():
    assert "/api/automations" in JS
    assert "Run history" in JS
    assert "approval_state" in JS
    assert "Maximum 25 steps, depth 3" in JS
    assert "External communications and integration actions pause for approval" in JS
    assert "Routine templates" in JS
    assert "/api/automations/templates" in JS
    assert "attention_returned_minutes" in JS
