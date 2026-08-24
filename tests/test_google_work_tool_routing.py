"""Regression coverage for canonical Google Workspace and personal-work routing."""

from src import agent_loop


def _intent(text: str):
    return agent_loop._classify_agent_request(
        [{"role": "user", "content": text}], text
    )


def _seeded_tools(text: str) -> set[str]:
    result: set[str] = set()
    for domain in _intent(text)["domains"]:
        result.update(agent_loop._DOMAIN_TOOL_MAP.get(domain, set()))
    return result


def test_gmail_intent_seeds_canonical_google_tools():
    tools = _seeded_tools("Find the latest message in my Gmail and draft a reply")
    assert {
        "query_gmail",
        "manage_gmail_draft",
        "send_gmail",
        "modify_gmail_message",
        "delete_gmail",
        "download_gmail_attachment",
    } <= tools


def test_google_calendar_intent_seeds_read_and_mutation_tools():
    tools = _seeded_tools("Check Google Calendar conflicts and place a tentative hold")
    assert {
        "query_google_calendar",
        "create_google_calendar_hold",
        "create_google_calendar_event",
        "update_google_calendar_event",
        "respond_google_calendar_invitation",
        "update_google_calendar_attendees",
        "delete_google_calendar_event",
    } <= tools


def test_personal_work_intent_is_not_lost_to_recurring_task_manager():
    intent = _intent("Show my blocked project tasks and overdue commitments")
    assert "work" in intent["domains"]
    assert {"query_work", "manage_work", "delete_work"} <= _seeded_tools(
        "Show my blocked project tasks and overdue commitments"
    )


def test_recurring_job_keeps_automation_and_work_semantics_visible():
    tools = _seeded_tools("Every weekday review my project tasks automatically")
    assert "manage_tasks" in tools
    assert "query_work" in tools


def test_new_tools_have_local_prompt_sections_and_rule_packs():
    names = (
        agent_loop._DOMAIN_TOOL_MAP["email"]
        | agent_loop._DOMAIN_TOOL_MAP["notes_calendar_tasks"]
        | agent_loop._DOMAIN_TOOL_MAP["work"]
    )
    canonical = {
        name
        for name in names
        if name.startswith(("query_", "create_google_", "update_google_", "respond_google_", "delete_google_"))
        or name in {
            "manage_gmail_draft",
            "send_gmail",
            "modify_gmail_message",
            "delete_gmail",
            "download_gmail_attachment",
            "manage_work",
            "delete_work",
        }
    }
    assert canonical <= set(agent_loop.TOOL_SECTIONS)

    prompt = agent_loop._assemble_prompt(canonical)
    assert "Google IDs, not IMAP UIDs" in prompt
    assert "Personal work rules" in prompt
    assert "recurring/background AI automations" in prompt
