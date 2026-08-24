"""Durable owner-scoped models for knowledge sources and derived chunks."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship
from src.schema_migrations import Migration, run_migrations


KnowledgeBase = declarative_base()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeSource(KnowledgeBase):
    __tablename__ = "knowledge_sources"

    id = Column(String(36), primary_key=True)
    owner = Column(String(255), nullable=False, index=True)
    source_type = Column(String(60), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    original_location = Column(Text, nullable=True)
    source_created_at = Column(DateTime(timezone=True), nullable=True)
    imported_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_indexed_at = Column(DateTime(timezone=True), nullable=True)
    access_permissions_json = Column(Text, nullable=False, default='["owner"]')
    sensitivity = Column(String(30), nullable=False, default="normal")
    content_hash = Column(String(64), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    processing_status = Column(String(30), nullable=False, default="pending")
    processing_error = Column(Text, nullable=True)
    deletion_status = Column(String(30), nullable=False, default="active")
    derivatives_deleted_at = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column(Text, nullable=False, default="{}")
    content_text = Column(Text, nullable=False, default="")
    allow_memory_suggestions = Column(Boolean, nullable=False, default=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    revision = Column(Integer, nullable=False, default=1)

    chunks = relationship("KnowledgeChunk", cascade="all, delete-orphan", passive_deletes=True)

    __table_args__ = (
        Index("ix_knowledge_source_owner_status", "owner", "deletion_status", "processing_status"),
        Index("ix_knowledge_source_owner_hash", "owner", "content_hash"),
    )


class KnowledgeChunk(KnowledgeBase):
    __tablename__ = "knowledge_chunks"

    id = Column(String(80), primary_key=True)
    source_id = Column(String(36), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    owner = Column(String(255), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    section = Column(String(500), nullable=True)
    text = Column(Text, nullable=False)
    text_hash = Column(String(64), nullable=False)
    token_count = Column(Integer, nullable=False)
    embedding_json = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("source_id", "position", name="uq_knowledge_chunk_position"),
        Index("ix_knowledge_chunk_owner_source", "owner", "source_id"),
    )


class KnowledgeMemory(KnowledgeBase):
    __tablename__ = "knowledge_memories"

    id = Column(String(36), primary_key=True)
    owner = Column(String(255), nullable=False, index=True)
    source_id = Column(String(36), ForeignKey("knowledge_sources.id", ondelete="SET NULL"), nullable=True, index=True)
    category = Column(String(60), nullable=False)
    text = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, default="suggested")
    sensitive = Column(Boolean, nullable=False, default=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    revision = Column(Integer, nullable=False, default=1)


def ensure_knowledge_schema(engine) -> None:
    return run_migrations(engine, "knowledge", (Migration(1, "create_knowledge_domain", lambda bind: KnowledgeBase.metadata.create_all(bind=bind)),))
