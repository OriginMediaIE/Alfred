"""Contract coverage for the durable private knowledge index."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.knowledge_service import KnowledgeConflict, KnowledgeNotFound, KnowledgeService
from services.meeting_integrations import KnowledgeMeetingSink
from src.knowledge_models import KnowledgeBase, ensure_knowledge_schema
from src.tools import knowledge as knowledge_tools
import json


@pytest.fixture
def knowledge():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    ensure_knowledge_schema(engine)
    service = KnowledgeService(session_factory=sessionmaker(bind=engine, autocommit=False, autoflush=False))
    try:
        yield service
    finally:
        KnowledgeBase.metadata.drop_all(engine)
        engine.dispose()


def test_ingestion_is_idempotent_owner_scoped_and_hybrid_grounded(knowledge):
    first = knowledge.ingest_text(
        "alice",
        source_type="markdown",
        title="Apollo plan",
        content="# Launch\n\nProject Apollo launches Friday from Dublin.\n\nOwner: Alice.",
        metadata={"project": "apollo"},
        idempotency_key="import-1",
    )
    replay = knowledge.ingest_text(
        "alice",
        source_type="markdown",
        title="Ignored replay title",
        content="different replay body",
        idempotency_key="import-1",
    )
    assert replay["id"] == first["id"]
    assert first["processing_status"] == "ready"

    result = knowledge.grounded_context("alice", "When does Apollo launch?")
    assert result["insufficient_evidence"] is False
    assert result["results"][0]["source_id"] == first["id"]
    assert result["results"][0]["section"] == "Launch"
    assert result["citations"][0]["url"].endswith(first["id"])
    assert result["answer_policy"]["must_distinguish_inference"] is True
    assert knowledge.search("bob", "Apollo")["results"] == []
    with pytest.raises(KnowledgeNotFound):
        knowledge.get_source("bob", first["id"])


def test_delete_derivatives_rebuild_and_source_delete_are_readable_and_safe(knowledge):
    source = knowledge.ingest_text("alice", source_type="text", title="Record", content="A durable indexed fact about Zephyr.")
    removed = knowledge.delete_derivatives("alice", source["id"])
    assert removed["chunks_deleted"] == 1
    assert knowledge.search("alice", "Zephyr")["insufficient_evidence"] is True

    rebuilt = knowledge.rebuild_source("alice", source["id"])
    assert rebuilt["processing_status"] == "ready"
    assert knowledge.search("alice", "Zephyr")["results"]
    with pytest.raises(KnowledgeConflict):
        knowledge.delete_source("alice", source["id"], expected_revision=source["revision"])
    deleted = knowledge.delete_source("alice", source["id"], expected_revision=rebuilt["revision"])
    assert deleted["deleted"] is True
    assert knowledge.list_sources("alice")["total"] == 0


def test_memory_lifecycle_retains_source_and_sensitivity_controls(knowledge):
    source = knowledge.ingest_text("alice", source_type="note", title="Preference", content="Alice prefers morning meetings.")
    memory = knowledge.create_memory("alice", {"source_id": source["id"], "category": "preferences", "text": "Prefers morning meetings", "sensitive": True})
    assert memory["status"] == "suggested"
    approved = knowledge.update_memory("alice", memory["id"], {"status": "approved"}, expected_revision=memory["revision"])
    assert approved["sensitive"] is True
    assert knowledge.list_memories("alice", status="approved")[0]["source_id"] == source["id"]
    assert knowledge.delete_memory("alice", memory["id"], expected_revision=approved["revision"])["deleted"] is True


def test_document_vault_analysis_is_source_backed_reviewable_and_owner_scoped(knowledge):
    source = knowledge.ingest_text(
        "alice",
        source_type="pdf",
        title="Home insurance",
        content="Insurance policy 42. You must renew this policy before expiry 2027-03-15. Pay the premium annually.",
        sensitivity="confidential",
    )
    analyzed = knowledge.analyze_vault_source("alice", source["id"])
    vault = analyzed["metadata"]["vault"]
    assert vault["classification"] == "insurance"
    assert vault["document_expiry_at"] == "2027-03-15"
    assert vault["obligations"][0]["start"] >= 0
    assert vault["review_status"] == "suggested"
    reviewed = knowledge.update_vault_source("alice", source["id"], {"classification": "financial", "obligations": ["Pay the premium annually."], "allow_memory_suggestions": False}, expected_revision=analyzed["revision"])
    assert reviewed["metadata"]["vault"]["review_status"] == "approved"
    assert reviewed["allow_memory_suggestions"] is False
    assert knowledge.list_vault("alice")["documents"][0]["id"] == source["id"]
    assert knowledge.vault_context("alice", "When is the policy expiry?")["citations"][0]["source_id"] == source["id"]
    assert knowledge.list_vault("bob")["documents"] == []


def test_incognito_content_cannot_create_durable_memory(knowledge):
    with pytest.raises(Exception, match="Incognito content"):
        knowledge.create_memory("alice", {"category": "preferences", "text": "do not persist", "incognito": True})


def test_meeting_sink_uses_transcript_revision_idempotency(knowledge):
    sink = KnowledgeMeetingSink(knowledge)
    values = dict(owner="alice", meeting_id="meeting-1", title="Review", content="[0-1000 ms] Alice: Decision: ship Friday.", metadata={"transcript_revision": 2}, idempotency_key="meeting-knowledge:meeting-1:2")
    first = sink.ingest_meeting(**values)
    second = sink.ingest_meeting(**values)
    assert first["id"] == second["id"]
    assert first["type"] == "meeting_transcript"
    assert first["sensitivity"] == "confidential"


@pytest.mark.asyncio
async def test_canonical_knowledge_tools_require_claim_and_return_grounded_citations(
    knowledge, monkeypatch
):
    monkeypatch.setattr(knowledge_tools, "get_knowledge_service", lambda: knowledge)
    payload = json.dumps(
        {
            "action": "ingest_text",
            "record": {
                "source_type": "text",
                "title": "Orion record",
                "content": "Orion review is scheduled for Tuesday.",
            },
        }
    )
    denied = await knowledge_tools.do_manage_knowledge(payload, owner="alice")
    assert denied["exit_code"] == 1
    assert knowledge.list_sources("alice")["total"] == 0

    monkeypatch.setattr(knowledge_tools, "_require_claim", lambda *a, **k: None)
    created = await knowledge_tools.do_manage_knowledge(
        payload,
        owner="alice",
        approval_action_id="approved",
        request_id="request",
    )
    assert created["verification"]["status"] == "verified"
    source = created["source"]

    searched = await knowledge_tools.do_query_knowledge(
        json.dumps({"action": "search", "query": "When is Orion review?"}),
        owner="alice",
    )
    assert searched["citations"][0]["source_id"] == source["id"]
    assert searched["answer_policy"]["must_cite_source_id"] is True

    deleted = await knowledge_tools.do_delete_knowledge(
        json.dumps(
            {
                "action": "delete_source",
                "source_id": source["id"],
                "revision": source["revision"],
            }
        ),
        owner="alice",
        approval_action_id="delete-approved",
        request_id="delete-request",
    )
    assert deleted["verification"]["status"] == "verified"
