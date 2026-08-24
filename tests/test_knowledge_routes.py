"""ASGI coverage for knowledge upload, search, privacy, and memory controls."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from routes.knowledge_routes import setup_knowledge_routes
from services.knowledge_service import KnowledgeService
from src.auth_helpers import require_user
from src.knowledge_models import KnowledgeBase, ensure_knowledge_schema


@pytest.fixture
def app_env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    ensure_knowledge_schema(engine)
    service = KnowledgeService(session_factory=sessionmaker(bind=engine, autocommit=False, autoflush=False))
    owner = {"value": "alice"}
    app = FastAPI()
    app.dependency_overrides[require_user] = lambda: owner["value"]
    app.include_router(setup_knowledge_routes(service))
    try:
        yield app, service, owner
    finally:
        KnowledgeBase.metadata.drop_all(engine)
        engine.dispose()


@pytest.mark.asyncio
async def test_upload_search_export_and_delete_derivatives(app_env):
    app, _, _ = app_env
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        uploaded = await client.post("/api/knowledge/sources/upload", files={"file": ("plan.md", b"# Launch\n\nApollo launches Friday.", "text/markdown")}, data={"sensitivity": "confidential"})
        assert uploaded.status_code == 200
        source = uploaded.json()
        result = (await client.get("/api/knowledge/search", params={"query": "Apollo launch"})).json()
        assert result["results"][0]["source_id"] == source["id"]
        assert result["citations"][0]["excerpt"].endswith("Friday.")

        export = await client.get("/api/knowledge/export")
        assert export.status_code == 200
        assert export.json()["sources"][0]["content"].endswith("Friday.")

        removed = await client.post(f"/api/knowledge/sources/{source['id']}/delete-derivatives", json={"confirm": True})
        assert removed.json()["chunks_deleted"] == 1
        missing = (await client.get("/api/knowledge/search", params={"query": "Apollo"})).json()
        assert missing["insufficient_evidence"] is True


@pytest.mark.asyncio
async def test_owner_isolation_memory_review_and_unsafe_file_rejection(app_env):
    app, _, owner = app_env
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        source = (await client.post("/api/knowledge/sources/text", json={"source_type": "note", "title": "Preference", "content": "Prefers mornings"})).json()
        memory = (await client.post("/api/knowledge/memories", json={"source_id": source["id"], "category": "preferences", "text": "Prefers mornings", "sensitive": True})).json()
        approved = await client.put(f"/api/knowledge/memories/{memory['id']}", json={"status": "approved", "revision": memory["revision"]})
        assert approved.json()["status"] == "approved"

        owner["value"] = "bob"
        assert (await client.get(f"/api/knowledge/sources/{source['id']}")).status_code == 404
        assert (await client.get("/api/knowledge/memories")).json()["memories"] == []

        unsafe = await client.post("/api/knowledge/sources/upload", files={"file": ("payload.exe", b"MZpayload", "application/octet-stream")})
        assert unsafe.status_code == 415
        assert unsafe.json()["detail"]["code"] == "unsafe_knowledge_upload"


@pytest.mark.asyncio
async def test_strict_input_and_unsupported_file_fail_closed(app_env):
    app, _, _ = app_env
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        strict = await client.post("/api/knowledge/sources/text", json={"source_type": "text", "title": "x", "content": "body", "unexpected": True})
        assert strict.status_code == 422
        unsupported = await client.post("/api/knowledge/sources/upload", files={"file": ("archive.zip", b"PK\x03\x04", "application/zip")})
        assert unsupported.status_code == 415


@pytest.mark.asyncio
async def test_vault_routes_analyze_review_search_and_reject_incognito_memory(app_env):
    app, _, _ = app_env
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        source = (await client.post("/api/knowledge/sources/text", json={"source_type": "document", "title": "Membership", "content": "Membership renewal is due 2027-06-01. You must notify the club before cancellation."})).json()
        analyzed = await client.post(f"/api/knowledge/sources/{source['id']}/analyze-vault", json={"confirm": True})
        assert analyzed.status_code == 200
        reviewed = await client.put(f"/api/knowledge/sources/{source['id']}/vault", json={"revision": analyzed.json()["revision"], "classification": "membership", "sensitivity": "sensitive"})
        assert reviewed.status_code == 200
        assert (await client.get("/api/knowledge/vault")).json()["total"] == 1
        answer = (await client.get("/api/knowledge/vault/search", params={"query": "When is renewal due?"})).json()
        assert answer["scope"] == "document_vault" and answer["citations"]
        rejected = await client.post("/api/knowledge/memories", json={"category": "preferences", "text": "private", "incognito": True})
        assert rejected.status_code == 422
