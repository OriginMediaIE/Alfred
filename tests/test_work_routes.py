from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from routes.work_routes import setup_work_routes
from src.auth_helpers import require_user
from tests.work_support import make_work_service


@pytest.fixture
def route_env():
    service, _, bind = make_work_service()
    app = FastAPI()
    owner = {"value": "alice"}
    app.dependency_overrides[require_user] = lambda: owner["value"]
    app.include_router(setup_work_routes(service))
    try:
        yield app, owner
    finally:
        bind.dispose()


@pytest.mark.asyncio
async def test_work_routes_cover_crud_nested_fields_and_owner_isolation(route_env):
    app, owner = route_env
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        project_response = await client.post(
            "/api/work/projects",
            headers={"X-Request-ID": "route-1"},
            json={
                "title": "Launch",
                "goal": "Ship product",
                "milestones": [{"title": "Beta"}],
                "references": [{"type": "document", "external_id": "doc-1"}],
            },
        )
        assert project_response.status_code == 201
        project = project_response.json()

        task_response = await client.post(
            "/api/work/tasks",
            json={
                "title": "Prepare beta",
                "project_id": project["id"],
                "milestone_id": project["milestones"][0]["id"],
                "priority": "high",
                "contexts": ["office"],
                "source": {
                    "type": "email",
                    "id": "mail-1",
                    "excerpt": "Please prepare beta",
                },
                "references": [{"type": "email", "external_id": "mail-1"}],
            },
        )
        assert task_response.status_code == 201
        task = task_response.json()
        assert task["source"]["id"] == "mail-1"

        listed = (await client.get("/api/work/tasks", params={"project_id": project["id"]})).json()
        assert [item["id"] for item in listed["tasks"]] == [task["id"]]

        updated_response = await client.patch(
            f"/api/work/tasks/{task['id']}",
            json={
                "status": "completed",
                "completion_notes": "Beta ready",
                "revision": task["revision"],
            },
        )
        assert updated_response.status_code == 200
        assert updated_response.json()["completed_at"] is not None

        project_after = (await client.get(f"/api/work/projects/{project['id']}")).json()
        assert project_after["progress"]["percent"] == 100

        receipts = (await client.get("/api/work/audit", params={"entity_id": task["id"]})).json()
        assert [entry["operation"] for entry in receipts["receipts"]] == ["update", "create"]
        assert all(entry["actor_kind"] == "user" for entry in receipts["receipts"])

        owner["value"] = "bob"
        assert (await client.get("/api/work/tasks")).json() == {"tasks": []}
        hidden = await client.get(f"/api/work/tasks/{task['id']}")
        assert hidden.status_code == 404
        assert hidden.json()["detail"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_commitment_and_planning_routes_are_reviewable(route_env):
    app, _ = route_env
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        commitment_response = await client.post(
            "/api/work/commitments",
            json={
                "title": "Call Sarah",
                "due_at": "2026-07-10",
                "review_state": "suggested",
                "source": {
                    "type": "meeting",
                    "id": "meeting-1",
                    "excerpt": "I'll call next week",
                },
            },
        )
        assert commitment_response.status_code == 201
        commitment = commitment_response.json()

        overdue = await client.get(
            "/api/work/planning/overdue-commitments",
            params={"as_of": "2026-07-18"},
        )
        assert [item["id"] for item in overdue.json()["commitments"]] == [commitment["id"]]

        approved = await client.patch(
            f"/api/work/commitments/{commitment['id']}",
            json={"review_state": "approved", "revision": commitment["revision"]},
        )
        assert approved.status_code == 200
        assert approved.json()["review_state"] == "approved"

        plan_response = await client.post(
            "/api/work/plans",
            json={
                "plan_type": "breakdown",
                "goal": "Prepare launch",
                "steps": [{"title": "Review launch checklist", "estimated_minutes": 30}],
            },
        )
        assert plan_response.status_code == 201
        plan = plan_response.json()

        corrected_response = await client.patch(
            f"/api/work/plans/{plan['id']}",
            json={
                "proposals": [
                    {"title": "Review final checklist", "estimated_minutes": 45, "priority": "high"}
                ],
                "revision": plan["revision"],
            },
        )
        assert corrected_response.status_code == 200
        corrected = corrected_response.json()

        applied = await client.post(
            f"/api/work/plans/{plan['id']}/apply",
            json={"revision": corrected["revision"]},
        )
        assert applied.status_code == 200
        assert applied.json()["plan"]["status"] == "applied"
        assert applied.json()["affected"][0]["title"] == "Review final checklist"


@pytest.mark.asyncio
async def test_route_validation_is_strict_and_revision_conflicts_are_structured(route_env):
    app, _ = route_env
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        extra = await client.post(
            "/api/work/tasks",
            json={"title": "T", "unknown_field": "must reject"},
        )
        assert extra.status_code == 422

        invalid = await client.post(
            "/api/work/tasks",
            json={"title": "T", "effort": 9},
        )
        assert invalid.status_code == 422
        assert invalid.json()["detail"]["code"] == "invalid_work_record"

        task = (await client.post("/api/work/tasks", json={"title": "T"})).json()
        stale = await client.patch(
            f"/api/work/tasks/{task['id']}",
            json={"title": "Changed", "revision": task["revision"] + 10},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "conflict"

        meta = await client.get("/api/work/meta")
        assert "urgent" in meta.json()["task_priorities"]
        assert "suggested" in meta.json()["commitment_review_states"]
