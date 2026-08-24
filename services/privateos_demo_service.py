"""Idempotent synthetic data for the Alfred Private OS release demonstration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.automation_service import AutomationService
from services.knowledge_service import KnowledgeService
from services.meeting_service import MeetingService, create_default_meeting_session_factory
from src.work_service import MutationContext, WorkService


class PrivateOSDemoService:
    def __init__(self, data_dir):
        self.root = Path(data_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.knowledge = KnowledgeService(database_url=f"sqlite:///{self.root/'knowledge.db'}")
        self.automations = AutomationService(database_url=f"sqlite:///{self.root/'automations.db'}")
        meeting_factory, self._meeting_engine = create_default_meeting_session_factory(f"sqlite:///{self.root/'meetings.db'}")
        self.meetings = MeetingService(session_factory=meeting_factory, storage_root=self.root/"meeting-media")
        self._work_engine = create_engine(f"sqlite:///{self.root/'app.db'}",connect_args={"check_same_thread":False})
        work_factory = sessionmaker(bind=self._work_engine,autocommit=False,autoflush=False)
        self.work = WorkService(session_factory=work_factory,bind=self._work_engine,backfill_legacy=False)

    def seed(self, owner: str) -> dict:
        owner = str(owner or "").strip()
        if not owner:
            raise ValueError("owner is required")
        context = MutationContext.user(owner,correlation_id="privateos-demo-v1")
        projects = self.work.list_projects(owner,include_archived=True)
        project = next((item for item in projects if item["title"]=="Private OS launch rehearsal"),None)
        if project is None:
            project = self.work.create_project(owner,{"title":"Private OS launch rehearsal","goal":"Run Alfred privately from Today through verified action","desired_outcome":"A calm daily operating rhythm with recoverable local data","status":"active","area":"Personal systems","tags":["privateos","demo"],"progress_summary":"Release rehearsal ready"},context=context)
        tasks = self.work.list_tasks(owner,include_completed=True)
        if not any(item["title"]=="Review Today and choose three outcomes" for item in tasks):
            self.work.create_task(owner,{"title":"Review Today and choose three outcomes","description":"Use the synthetic dashboard to rehearse the morning workflow.","status":"ready","priority":"high","project_id":project["id"],"area":"Personal systems","tags":["privateos","demo"],"estimated_minutes":15},context=context)
        commitments = self.work.list_commitments(owner)
        if not any(item["title"]=="Send the release rehearsal summary" for item in commitments):
            self.work.create_commitment(owner,{"title":"Send the release rehearsal summary","description":"Synthetic commitment extracted from the release review.","due_at":(datetime.now(timezone.utc)+timedelta(days=2)).isoformat(),"counterparty":"Alex Morgan","project_id":project["id"],"source_type":"meeting","source_id":"privateos-demo-meeting","source_excerpt":"I will send the release rehearsal summary by Friday.","confidence":96,"review_state":"approved"},context=context)
        source = self.knowledge.ingest_text(owner,source_type="meeting_transcript",title="Private OS release review",content="# Decisions\n\nDecision: keep Alfred local-first and require encrypted portable backups.\n\n# Commitments\n\nAlex will review the restore evidence. I will send the release rehearsal summary by Friday.\n\n# Risks\n\nThe seven-day personal-use soak cannot be simulated; daily evidence must be recorded.",metadata={"project":"privateos-demo","synthetic":True},idempotency_key="privateos-demo-knowledge-v1",sensitivity="confidential")
        existing_meetings = self.meetings.list_meetings(owner,query="Private OS release review")["meetings"]
        meeting = existing_meetings[0] if existing_meetings else self.meetings.create_meeting(owner,{"title":"Private OS release review","description":"Synthetic review meeting for the ten-minute release walkthrough.","source_type":"manual","attendee_names":["Alex Morgan"],"scheduled_start":datetime.now(timezone.utc).isoformat(),"timezone":"Europe/Dublin"})
        routines = [self.automations.install_routine(owner,key) for key in ("weekly-review","backup-reminder","meeting-follow-up")]
        return {"owner":owner,"project_id":project["id"],"knowledge_source_id":source["id"],"meeting_id":meeting["id"],"routine_ids":[item["id"] for item in routines],"routine_count":len(routines),"synthetic":True}

    def close(self):
        self._meeting_engine.dispose()
        self._work_engine.dispose()
