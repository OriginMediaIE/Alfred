"""Isolated SQLite fixture helpers for Phase Ten tests."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import AgentAction, ScheduledTask, Session
from src.work_service import WorkService


def make_work_service(*, backfill_legacy: bool = False):
    bind = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session.__table__.create(bind=bind, checkfirst=True)
    ScheduledTask.__table__.create(bind=bind, checkfirst=True)
    AgentAction.__table__.create(bind=bind, checkfirst=True)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=bind)
    service = WorkService(
        session_factory=sessions,
        bind=bind,
        backfill_legacy=backfill_legacy,
    )
    return service, sessions, bind
