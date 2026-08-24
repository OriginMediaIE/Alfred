"""Durable models for validated OM Automate workflows and their runs."""

from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text, UniqueConstraint, inspect, text
from sqlalchemy.orm import declarative_base
from src.schema_migrations import Migration, run_migrations

AutomationBase = declarative_base()


def utcnow(): return datetime.now(timezone.utc)


class AutomationDefinition(AutomationBase):
    __tablename__ = "automation_definitions"
    id = Column(String(36), primary_key=True); owner = Column(String(255), nullable=False, index=True)
    name = Column(String(300), nullable=False); definition_json = Column(Text, nullable=False)
    webhook_secret_enc = Column(Text, nullable=True)
    status = Column(String(30), nullable=False, default="enabled"); version = Column(Integer, nullable=False, default=1)
    next_run_at = Column(DateTime(timezone=True), nullable=True, index=True); last_run_at = Column(DateTime(timezone=True), nullable=True)
    consecutive_failures = Column(Integer, nullable=False, default=0); cooldown_until = Column(DateTime(timezone=True), nullable=True)
    run_count = Column(Integer, nullable=False, default=0); created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow); updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    __table_args__ = (Index("ix_automation_owner_status", "owner", "status"),)


class AutomationRun(AutomationBase):
    __tablename__ = "automation_runs"
    id = Column(String(36), primary_key=True); automation_id = Column(String(36), nullable=False, index=True); owner = Column(String(255), nullable=False, index=True)
    trigger_json = Column(Text, nullable=False); inputs_json = Column(Text, nullable=False); steps_json = Column(Text, nullable=False, default="[]"); tool_calls_json = Column(Text, nullable=False, default="[]")
    output_json = Column(Text, nullable=True); logs_json = Column(Text, nullable=False, default="[]"); status = Column(String(30), nullable=False, default="running"); retry_status = Column(String(30), nullable=False, default="not_retried"); approval_state = Column(String(30), nullable=False, default="not_required")
    correlation_id = Column(String(100), nullable=False, index=True); idempotency_key = Column(String(128), nullable=False, unique=True); depth = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime(timezone=True), nullable=False, default=utcnow); finished_at = Column(DateTime(timezone=True), nullable=True); duration_ms = Column(Integer, nullable=True); error = Column(Text, nullable=True)


class AutomationEvent(AutomationBase):
    __tablename__ = "automation_events"
    id = Column(String(36), primary_key=True); owner = Column(String(255), nullable=False); event_type = Column(String(80), nullable=False); dedupe_key = Column(String(300), nullable=False); received_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    __table_args__ = (UniqueConstraint("owner", "event_type", "dedupe_key", name="uq_automation_event_dedupe"),)


class AutomationDeadLetter(AutomationBase):
    __tablename__ = "automation_dead_letters"
    id = Column(String(36), primary_key=True); automation_id = Column(String(36), nullable=False, index=True); owner = Column(String(255), nullable=False, index=True); run_id = Column(String(36), nullable=False); reason = Column(Text, nullable=False); payload_json = Column(Text, nullable=False); created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow); resolved_at = Column(DateTime(timezone=True), nullable=True)


def _create_automation_tables(engine): AutomationBase.metadata.create_all(bind=engine)
def _add_webhook_secret(engine):
    columns = {column["name"] for column in inspect(engine).get_columns("automation_definitions")}
    if "webhook_secret_enc" not in columns:
        with engine.begin() as connection: connection.execute(text("ALTER TABLE automation_definitions ADD COLUMN webhook_secret_enc TEXT"))

AUTOMATION_MIGRATIONS = (Migration(1, "create_automation_domain", _create_automation_tables), Migration(2, "add_encrypted_webhook_secret", _add_webhook_secret))
def ensure_automation_schema(engine): return run_migrations(engine, "automations", AUTOMATION_MIGRATIONS)
