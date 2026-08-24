"""HTTP API for personal tasks, projects, commitments and planning drafts."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from src.auth_helpers import require_user
from src.work_service import (
    APPROVAL_STATES,
    COMMITMENT_REVIEW_STATES,
    COMMITMENT_STATUSES,
    ENERGY_LEVELS,
    MILESTONE_STATUSES,
    PLAN_STATUSES,
    PLAN_TYPES,
    PROJECT_STATUSES,
    REFERENCE_TYPES,
    REMINDER_STATUSES,
    TASK_PRIORITIES,
    TASK_STATUSES,
    MutationContext,
    WorkError,
    WorkService,
)


class _StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskBody(_StrictBody):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_at: Optional[str] = None
    start_at: Optional[str] = None
    estimated_minutes: Optional[int] = None
    actual_minutes: Optional[int] = None
    project_id: Optional[str] = None
    milestone_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    area: Optional[str] = None
    tags: Optional[list[str]] = None
    contexts: Optional[list[str]] = None
    assignees: Optional[list[str]] = None
    energy: Optional[str] = None
    effort: Optional[int] = None
    recurrence: Optional[dict[str, Any]] = None
    source: Optional[dict[str, Any]] = None
    completion_notes: Optional[str] = None
    completed_at: Optional[str] = None
    dependency_ids: Optional[list[str]] = None
    references: Optional[list[dict[str, Any]]] = None
    reminders: Optional[list[dict[str, Any]]] = None
    sort_order: Optional[int] = None
    revision: Optional[int] = Field(default=None, ge=1)


class ProjectBody(_StrictBody):
    title: Optional[str] = None
    goal: Optional[str] = None
    desired_outcome: Optional[str] = None
    status: Optional[str] = None
    area: Optional[str] = None
    notes: Optional[str] = None
    risks: Optional[list[dict[str, Any]]] = None
    decisions: Optional[list[dict[str, Any]]] = None
    tags: Optional[list[str]] = None
    budget: Optional[dict[str, Any]] = None
    start_at: Optional[str] = None
    target_at: Optional[str] = None
    progress_summary: Optional[str] = None
    milestones: Optional[list[dict[str, Any]]] = None
    references: Optional[list[dict[str, Any]]] = None
    revision: Optional[int] = Field(default=None, ge=1)


class CommitmentBody(_StrictBody):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    review_state: Optional[str] = None
    due_at: Optional[str] = None
    fulfilled_at: Optional[str] = None
    counterparty: Optional[str] = None
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    source: Optional[dict[str, Any]] = None
    confidence: Optional[int] = None
    completion_notes: Optional[str] = None
    references: Optional[list[dict[str, Any]]] = None
    reminders: Optional[list[dict[str, Any]]] = None
    revision: Optional[int] = Field(default=None, ge=1)


class PlanBody(_StrictBody):
    plan_type: Optional[str] = None
    title: Optional[str] = None
    goal: Optional[str] = None
    plan_date: Optional[str] = None
    available_minutes: Optional[int] = None
    energy: Optional[str] = None
    contexts: Optional[list[str]] = None
    start_time: Optional[str] = None
    steps: Optional[list[dict[str, Any]]] = None
    task_ids: Optional[list[str]] = None


class PlanUpdateBody(_StrictBody):
    title: Optional[str] = None
    goal: Optional[str] = None
    proposals: Optional[list[dict[str, Any]]] = None
    work_blocks: Optional[list[dict[str, Any]]] = None
    status: Optional[str] = None
    revision: int = Field(ge=1)


class ApplyPlanBody(_StrictBody):
    revision: int = Field(ge=1)


def _raise_work_error(exc: WorkError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


def _request_id(request: Request) -> str:
    return str(
        getattr(request.state, "request_id", "")
        or request.headers.get("X-Request-ID", "")
    )[:200]


def _required_revision(revision: Optional[int]) -> int:
    if revision is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "revision_required", "message": "revision is required"},
        )
    return revision


def _payload(body: BaseModel) -> tuple[dict[str, Any], Optional[int]]:
    data = body.model_dump(exclude_unset=True)
    revision = data.pop("revision", None)
    source = data.pop("source", None)
    if source is not None:
        if not isinstance(source, dict):
            raise HTTPException(422, "source must be an object")
        data.update(
            {
                "source_type": source.get("type"),
                "source_id": source.get("id"),
                "source_url": source.get("url"),
                "source_excerpt": source.get("excerpt"),
                "source_occurred_at": source.get("occurred_at"),
            }
        )
    return data, revision


def setup_work_routes(service: Optional[WorkService] = None) -> APIRouter:
    service = service or WorkService()
    router = APIRouter(prefix="/api/work", tags=["work"])

    @router.get("/meta")
    async def work_metadata(owner: str = Depends(require_user)):
        del owner
        return {
            "task_statuses": sorted(TASK_STATUSES),
            "task_priorities": sorted(TASK_PRIORITIES),
            "energy_levels": sorted(ENERGY_LEVELS),
            "project_statuses": sorted(PROJECT_STATUSES),
            "milestone_statuses": sorted(MILESTONE_STATUSES),
            "commitment_statuses": sorted(COMMITMENT_STATUSES),
            "commitment_review_states": sorted(COMMITMENT_REVIEW_STATES),
            "approval_states": sorted(APPROVAL_STATES),
            "reminder_statuses": sorted(REMINDER_STATUSES),
            "reference_types": sorted(REFERENCE_TYPES),
            "plan_types": sorted(PLAN_TYPES),
            "plan_statuses": sorted(PLAN_STATUSES),
        }

    @router.get("/tasks")
    async def list_tasks(
        status: Optional[str] = None,
        project_id: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        tag: Optional[str] = None,
        context: Optional[str] = None,
        due_before: Optional[str] = None,
        include_completed: bool = False,
        query: Optional[str] = None,
        limit: int = Query(200, ge=1, le=500),
        owner: str = Depends(require_user),
    ):
        try:
            tasks = service.list_tasks(
                owner,
                status=status,
                project_id=project_id,
                parent_task_id=parent_task_id,
                tag=tag,
                context=context,
                due_before=due_before,
                include_completed=include_completed,
                query=query,
                limit=limit,
            )
            return {"tasks": tasks}
        except WorkError as exc:
            _raise_work_error(exc)

    @router.post("/tasks", status_code=201)
    async def create_task(
        request: Request,
        body: TaskBody,
        owner: str = Depends(require_user),
    ):
        data, _ = _payload(body)
        try:
            return service.create_task(
                owner,
                data,
                context=MutationContext.user(owner, correlation_id=_request_id(request)),
            )
        except WorkError as exc:
            _raise_work_error(exc)

    @router.get("/tasks/{task_id}")
    async def get_task(task_id: str, owner: str = Depends(require_user)):
        try:
            return service.get_task(owner, task_id)
        except WorkError as exc:
            _raise_work_error(exc)

    @router.patch("/tasks/{task_id}")
    async def update_task(
        request: Request,
        task_id: str,
        body: TaskBody,
        owner: str = Depends(require_user),
    ):
        data, revision = _payload(body)
        revision = _required_revision(revision)
        try:
            return service.update_task(
                owner,
                task_id,
                data,
                expected_revision=revision,
                context=MutationContext.user(owner, correlation_id=_request_id(request)),
            )
        except WorkError as exc:
            _raise_work_error(exc)

    @router.delete("/tasks/{task_id}")
    async def delete_task(
        request: Request,
        task_id: str,
        revision: int = Query(..., ge=1),
        owner: str = Depends(require_user),
    ):
        try:
            return service.delete_task(
                owner,
                task_id,
                context=MutationContext.user(owner, correlation_id=_request_id(request)),
                expected_revision=revision,
            )
        except WorkError as exc:
            _raise_work_error(exc)

    @router.get("/projects")
    async def list_projects(
        status: Optional[str] = None,
        include_archived: bool = False,
        limit: int = Query(200, ge=1, le=500),
        owner: str = Depends(require_user),
    ):
        try:
            return {
                "projects": service.list_projects(
                    owner,
                    status=status,
                    include_archived=include_archived,
                    limit=limit,
                )
            }
        except WorkError as exc:
            _raise_work_error(exc)

    @router.post("/projects", status_code=201)
    async def create_project(
        request: Request,
        body: ProjectBody,
        owner: str = Depends(require_user),
    ):
        data, _ = _payload(body)
        try:
            return service.create_project(
                owner,
                data,
                context=MutationContext.user(owner, correlation_id=_request_id(request)),
            )
        except WorkError as exc:
            _raise_work_error(exc)

    @router.get("/projects/{project_id}")
    async def get_project(project_id: str, owner: str = Depends(require_user)):
        try:
            return service.get_project(owner, project_id)
        except WorkError as exc:
            _raise_work_error(exc)

    @router.patch("/projects/{project_id}")
    async def update_project(
        request: Request,
        project_id: str,
        body: ProjectBody,
        owner: str = Depends(require_user),
    ):
        data, revision = _payload(body)
        revision = _required_revision(revision)
        try:
            return service.update_project(
                owner,
                project_id,
                data,
                expected_revision=revision,
                context=MutationContext.user(owner, correlation_id=_request_id(request)),
            )
        except WorkError as exc:
            _raise_work_error(exc)

    @router.delete("/projects/{project_id}")
    async def delete_project(
        request: Request,
        project_id: str,
        revision: int = Query(..., ge=1),
        owner: str = Depends(require_user),
    ):
        try:
            return service.delete_project(
                owner,
                project_id,
                context=MutationContext.user(owner, correlation_id=_request_id(request)),
                expected_revision=revision,
            )
        except WorkError as exc:
            _raise_work_error(exc)

    @router.get("/commitments")
    async def list_commitments(
        status: Optional[str] = None,
        review_state: Optional[str] = None,
        due_before: Optional[str] = None,
        limit: int = Query(200, ge=1, le=500),
        owner: str = Depends(require_user),
    ):
        try:
            return {
                "commitments": service.list_commitments(
                    owner,
                    status=status,
                    review_state=review_state,
                    due_before=due_before,
                    limit=limit,
                )
            }
        except WorkError as exc:
            _raise_work_error(exc)

    @router.post("/commitments", status_code=201)
    async def create_commitment(
        request: Request,
        body: CommitmentBody,
        owner: str = Depends(require_user),
    ):
        data, _ = _payload(body)
        try:
            return service.create_commitment(
                owner,
                data,
                context=MutationContext.user(owner, correlation_id=_request_id(request)),
            )
        except WorkError as exc:
            _raise_work_error(exc)

    @router.get("/commitments/{commitment_id}")
    async def get_commitment(
        commitment_id: str,
        owner: str = Depends(require_user),
    ):
        try:
            return service.get_commitment(owner, commitment_id)
        except WorkError as exc:
            _raise_work_error(exc)

    @router.patch("/commitments/{commitment_id}")
    async def update_commitment(
        request: Request,
        commitment_id: str,
        body: CommitmentBody,
        owner: str = Depends(require_user),
    ):
        data, revision = _payload(body)
        revision = _required_revision(revision)
        try:
            return service.update_commitment(
                owner,
                commitment_id,
                data,
                expected_revision=revision,
                context=MutationContext.user(owner, correlation_id=_request_id(request)),
            )
        except WorkError as exc:
            _raise_work_error(exc)

    @router.delete("/commitments/{commitment_id}")
    async def delete_commitment(
        request: Request,
        commitment_id: str,
        revision: int = Query(..., ge=1),
        owner: str = Depends(require_user),
    ):
        try:
            return service.delete_commitment(
                owner,
                commitment_id,
                context=MutationContext.user(owner, correlation_id=_request_id(request)),
                expected_revision=revision,
            )
        except WorkError as exc:
            _raise_work_error(exc)

    @router.get("/planning/blocked")
    async def blocked_tasks(owner: str = Depends(require_user)):
        return {"tasks": service.blocked_tasks(owner)}

    @router.get("/planning/overdue-commitments")
    async def overdue_commitments(
        as_of: Optional[str] = None,
        owner: str = Depends(require_user),
    ):
        try:
            return {"commitments": service.overdue_commitments(owner, as_of=as_of)}
        except WorkError as exc:
            _raise_work_error(exc)

    @router.get("/planning/focus")
    async def daily_focus(
        plan_date: Optional[str] = None,
        available_minutes: int = Query(480, ge=15, le=1440),
        energy: Optional[str] = None,
        contexts: Optional[str] = None,
        owner: str = Depends(require_user),
    ):
        try:
            return service.daily_focus(
                owner,
                plan_date=plan_date,
                available_minutes=available_minutes,
                energy=energy,
                contexts=[value.strip() for value in (contexts or "").split(",") if value.strip()],
            )
        except WorkError as exc:
            _raise_work_error(exc)

    @router.post("/plans", status_code=201)
    async def create_plan(
        request: Request,
        body: PlanBody,
        owner: str = Depends(require_user),
    ):
        try:
            return service.create_plan(
                owner,
                body.model_dump(exclude_unset=True),
                context=MutationContext.user(owner, correlation_id=_request_id(request)),
            )
        except WorkError as exc:
            _raise_work_error(exc)

    @router.get("/plans/{plan_id}")
    async def get_plan(plan_id: str, owner: str = Depends(require_user)):
        try:
            return service.get_plan(owner, plan_id)
        except WorkError as exc:
            _raise_work_error(exc)

    @router.patch("/plans/{plan_id}")
    async def update_plan(
        request: Request,
        plan_id: str,
        body: PlanUpdateBody,
        owner: str = Depends(require_user),
    ):
        data = body.model_dump(exclude_unset=True)
        revision = data.pop("revision")
        try:
            return service.update_plan(
                owner,
                plan_id,
                data,
                expected_revision=revision,
                context=MutationContext.user(owner, correlation_id=_request_id(request)),
            )
        except WorkError as exc:
            _raise_work_error(exc)

    @router.post("/plans/{plan_id}/apply")
    async def apply_plan(
        request: Request,
        plan_id: str,
        body: ApplyPlanBody,
        owner: str = Depends(require_user),
    ):
        try:
            return service.apply_plan(
                owner,
                plan_id,
                expected_revision=body.revision,
                context=MutationContext.user(owner, correlation_id=_request_id(request)),
            )
        except WorkError as exc:
            _raise_work_error(exc)

    @router.get("/reminders/due")
    async def due_reminders(
        due_before: Optional[str] = None,
        limit: int = Query(200, ge=1, le=500),
        owner: str = Depends(require_user),
    ):
        try:
            return {
                "reminders": service.pending_reminders(
                    owner,
                    due_before=due_before,
                    limit=limit,
                )
            }
        except WorkError as exc:
            _raise_work_error(exc)

    @router.get("/audit")
    async def mutation_receipts(
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        limit: int = Query(200, ge=1, le=500),
        owner: str = Depends(require_user),
    ):
        return {
            "receipts": service.list_receipts(
                owner,
                entity_type=entity_type,
                entity_id=entity_id,
                limit=limit,
            )
        }

    return router
