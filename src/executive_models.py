"""Durable records for the Personal Operating Loop."""

from sqlalchemy import Column, DateTime, Index, String, Text

from core.database import Base, TimestampMixin, engine, utcnow_naive
from src.schema_migrations import Migration, run_migrations


EXECUTIVE_SCHEMA_VERSION = 1


class ExecutiveBriefingRun(TimestampMixin, Base):
    __tablename__ = "executive_briefing_runs"

    id = Column(String, primary_key=True)
    owner = Column(String, nullable=False, default="", index=True)
    kind = Column(String, nullable=False, index=True)
    period_key = Column(String, nullable=False, index=True)
    timezone = Column(String, nullable=False, default="UTC")
    source_digest = Column(String, nullable=False, index=True)
    idempotency_key = Column(String, nullable=False, unique=True)
    content_json = Column(Text, nullable=False)
    generated_at = Column(DateTime, nullable=False, default=utcnow_naive, index=True)

    __table_args__ = (
        Index(
            "ix_executive_briefing_owner_kind_generated",
            "owner",
            "kind",
            "generated_at",
        ),
    )


def ensure_executive_schema(*, bind=engine) -> None:
    run_migrations(
        bind,
        "executive",
        [
            Migration(
                EXECUTIVE_SCHEMA_VERSION,
                "create_executive_briefing_runs",
                lambda target: Base.metadata.create_all(
                    bind=target,
                    tables=[ExecutiveBriefingRun.__table__],
                ),
            )
        ],
    )


__all__ = ["ExecutiveBriefingRun", "ensure_executive_schema"]
