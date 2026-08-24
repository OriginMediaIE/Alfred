"""Relational models for personal tasks, projects and commitments.

These records deliberately live beside ``ScheduledTask``.  Scheduled tasks are
automation definitions; the ``work_*`` tables model human work and retain a
read-only source link when an automation is projected into the unified view.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from core.database import Base, TimestampMixin, engine, utcnow_naive
from src.schema_migrations import Migration, run_migrations


WORK_SCHEMA_VERSION = 1


class WorkSchemaMeta(Base):
    __tablename__ = "work_schema_meta"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive)


class WorkProject(TimestampMixin, Base):
    __tablename__ = "work_projects"

    id = Column(String, primary_key=True)
    owner = Column(String, nullable=False, default="", index=True)
    title = Column(String, nullable=False)
    goal = Column(Text, nullable=False, default="")
    desired_outcome = Column(Text, nullable=False, default="")
    status = Column(String, nullable=False, default="active", index=True)
    area = Column(String, nullable=False, default="")
    notes = Column(Text, nullable=False, default="")
    risks_json = Column(Text, nullable=False, default="[]")
    decisions_json = Column(Text, nullable=False, default="[]")
    tags_json = Column(Text, nullable=False, default="[]")
    budget_enabled = Column(Boolean, nullable=False, default=False)
    budget_currency = Column(String, nullable=False, default="")
    budget_amount_minor = Column(Integer, nullable=True)
    budget_spent_minor = Column(Integer, nullable=True)
    start_at = Column(DateTime, nullable=True)
    target_at = Column(DateTime, nullable=True, index=True)
    progress_summary = Column(Text, nullable=False, default="")
    created_by = Column(String, nullable=False, default="user")
    approval_state = Column(String, nullable=False, default="not_required")
    action_id = Column(String, nullable=True, index=True)
    revision = Column(Integer, nullable=False, default=1)

    __table_args__ = (
        Index("ix_work_projects_owner_status_target", "owner", "status", "target_at"),
    )


class WorkMilestone(TimestampMixin, Base):
    __tablename__ = "work_milestones"

    id = Column(String, primary_key=True)
    owner = Column(String, nullable=False, default="", index=True)
    project_id = Column(
        String,
        ForeignKey("work_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False, default="")
    status = Column(String, nullable=False, default="pending")
    target_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    revision = Column(Integer, nullable=False, default=1)

    __table_args__ = (
        Index("ix_work_milestones_project_order", "project_id", "sort_order"),
    )


class WorkTask(TimestampMixin, Base):
    __tablename__ = "work_tasks"

    id = Column(String, primary_key=True)
    owner = Column(String, nullable=False, default="", index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False, default="")
    status = Column(String, nullable=False, default="inbox", index=True)
    priority = Column(String, nullable=False, default="normal", index=True)
    due_at = Column(DateTime, nullable=True, index=True)
    start_at = Column(DateTime, nullable=True)
    estimated_minutes = Column(Integer, nullable=True)
    actual_minutes = Column(Integer, nullable=True)
    project_id = Column(
        String,
        ForeignKey("work_projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    milestone_id = Column(
        String,
        ForeignKey("work_milestones.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    parent_task_id = Column(
        String,
        ForeignKey("work_tasks.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    area = Column(String, nullable=False, default="")
    tags_json = Column(Text, nullable=False, default="[]")
    contexts_json = Column(Text, nullable=False, default="[]")
    assignees_json = Column(Text, nullable=False, default="[]")
    energy = Column(String, nullable=False, default="medium")
    effort = Column(Integer, nullable=True)
    recurrence_rule_json = Column(Text, nullable=False, default="{}")
    source_type = Column(String, nullable=False, default="manual")
    source_id = Column(String, nullable=False, default="")
    source_url = Column(Text, nullable=False, default="")
    source_excerpt = Column(Text, nullable=False, default="")
    completion_notes = Column(Text, nullable=False, default="")
    completed_at = Column(DateTime, nullable=True)
    created_by = Column(String, nullable=False, default="user")
    approval_state = Column(String, nullable=False, default="not_required")
    action_id = Column(String, nullable=True, index=True)
    legacy_scheduled_task_id = Column(String, nullable=True, unique=True, index=True)
    legacy_read_only = Column(Boolean, nullable=False, default=False)
    sort_order = Column(Integer, nullable=False, default=0)
    revision = Column(Integer, nullable=False, default=1)

    __table_args__ = (
        Index("ix_work_tasks_owner_status_due", "owner", "status", "due_at"),
        Index("ix_work_tasks_owner_project", "owner", "project_id"),
    )


class WorkTaskDependency(Base):
    __tablename__ = "work_task_dependencies"

    id = Column(String, primary_key=True)
    owner = Column(String, nullable=False, default="", index=True)
    task_id = Column(
        String,
        ForeignKey("work_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    depends_on_task_id = Column(
        String,
        ForeignKey("work_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)

    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "depends_on_task_id",
            name="ux_work_task_dependency_edge",
        ),
        Index("ix_work_task_dependencies_owner_task", "owner", "task_id"),
    )


class WorkReminder(TimestampMixin, Base):
    __tablename__ = "work_reminders"

    id = Column(String, primary_key=True)
    owner = Column(String, nullable=False, default="", index=True)
    entity_type = Column(String, nullable=False, index=True)
    entity_id = Column(String, nullable=False, index=True)
    remind_at = Column(DateTime, nullable=False, index=True)
    message = Column(Text, nullable=False, default="")
    channel = Column(String, nullable=False, default="in_app")
    status = Column(String, nullable=False, default="pending")
    recurrence_rule_json = Column(Text, nullable=False, default="{}")
    fired_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_work_reminders_owner_due", "owner", "status", "remind_at"),
        Index("ix_work_reminders_entity", "entity_type", "entity_id"),
    )


class WorkCommitment(TimestampMixin, Base):
    __tablename__ = "work_commitments"

    id = Column(String, primary_key=True)
    owner = Column(String, nullable=False, default="", index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False, default="")
    status = Column(String, nullable=False, default="open", index=True)
    review_state = Column(String, nullable=False, default="suggested", index=True)
    due_at = Column(DateTime, nullable=True, index=True)
    fulfilled_at = Column(DateTime, nullable=True)
    counterparty = Column(String, nullable=False, default="")
    project_id = Column(
        String,
        ForeignKey("work_projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_id = Column(
        String,
        ForeignKey("work_tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_type = Column(String, nullable=False)
    source_id = Column(String, nullable=False, default="")
    source_url = Column(Text, nullable=False, default="")
    source_excerpt = Column(Text, nullable=False, default="")
    source_occurred_at = Column(DateTime, nullable=True)
    confidence = Column(Integer, nullable=True)
    created_by = Column(String, nullable=False, default="user")
    action_id = Column(String, nullable=True, index=True)
    completion_notes = Column(Text, nullable=False, default="")
    revision = Column(Integer, nullable=False, default=1)

    __table_args__ = (
        Index("ix_work_commitments_owner_state_due", "owner", "status", "due_at"),
    )


class WorkReference(TimestampMixin, Base):
    __tablename__ = "work_references"

    id = Column(String, primary_key=True)
    owner = Column(String, nullable=False, default="", index=True)
    entity_type = Column(String, nullable=False, index=True)
    entity_id = Column(String, nullable=False, index=True)
    reference_type = Column(String, nullable=False, index=True)
    external_id = Column(String, nullable=False, default="")
    label = Column(String, nullable=False, default="")
    url = Column(Text, nullable=False, default="")
    metadata_json = Column(Text, nullable=False, default="{}")

    __table_args__ = (
        Index("ix_work_references_owner_entity", "owner", "entity_type", "entity_id"),
    )


class WorkPlan(TimestampMixin, Base):
    __tablename__ = "work_plans"

    id = Column(String, primary_key=True)
    owner = Column(String, nullable=False, default="", index=True)
    plan_type = Column(String, nullable=False, default="focus")
    title = Column(String, nullable=False)
    goal = Column(Text, nullable=False, default="")
    plan_date = Column(DateTime, nullable=True, index=True)
    status = Column(String, nullable=False, default="draft", index=True)
    proposals_json = Column(Text, nullable=False, default="[]")
    work_blocks_json = Column(Text, nullable=False, default="[]")
    assumptions_json = Column(Text, nullable=False, default="[]")
    created_by = Column(String, nullable=False, default="user")
    action_id = Column(String, nullable=True, index=True)
    applied_at = Column(DateTime, nullable=True)
    revision = Column(Integer, nullable=False, default=1)

    __table_args__ = (
        Index("ix_work_plans_owner_status_date", "owner", "status", "plan_date"),
    )


class WorkMutationReceipt(Base):
    """Append-only domain receipt; agent receipts join to the action ledger."""

    __tablename__ = "work_mutation_receipts"

    id = Column(String, primary_key=True)
    owner = Column(String, nullable=False, default="", index=True)
    entity_type = Column(String, nullable=False, index=True)
    entity_id = Column(String, nullable=False, index=True)
    operation = Column(String, nullable=False, index=True)
    actor_kind = Column(String, nullable=False)
    actor_id = Column(String, nullable=False, default="")
    action_id = Column(String, nullable=True, index=True)
    correlation_id = Column(String, nullable=False, default="", index=True)
    before_hash = Column(String, nullable=False, default="")
    after_hash = Column(String, nullable=False, default="")
    details_json = Column(Text, nullable=False, default="{}")
    occurred_at = Column(DateTime, nullable=False, default=utcnow_naive, index=True)

    __table_args__ = (
        Index("ix_work_receipts_owner_time", "owner", "occurred_at"),
    )


WORK_TABLES = (
    WorkSchemaMeta.__table__,
    WorkProject.__table__,
    WorkMilestone.__table__,
    WorkTask.__table__,
    WorkTaskDependency.__table__,
    WorkReminder.__table__,
    WorkCommitment.__table__,
    WorkReference.__table__,
    WorkPlan.__table__,
    WorkMutationReceipt.__table__,
)


def ensure_work_schema(*, bind=engine) -> None:
    """Create the Phase Ten schema without rerunning unrelated app migrations."""
    return run_migrations(
        bind,
        "personal_work",
        (Migration(1, "create_personal_work_domain", lambda target: Base.metadata.create_all(bind=target, tables=list(WORK_TABLES), checkfirst=True)),),
    )
