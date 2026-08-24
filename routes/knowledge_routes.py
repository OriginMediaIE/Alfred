"""Owner-scoped HTTP surface for private knowledge and governed memories."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import re
from typing import Any, Literal, Optional
import zipfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from services.knowledge_service import KnowledgeError, KnowledgeService, get_knowledge_service
from src.auth_helpers import require_user


MAX_KNOWLEDGE_UPLOAD = 50 * 1024 * 1024
_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm", ".xml", ".yaml", ".yml", ".log"}


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextIngestBody(StrictBody):
    source_type: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=50_000_000)
    original_location: Optional[str] = Field(default=None, max_length=4000)
    source_created_at: Optional[str] = Field(default=None, max_length=100)
    sensitivity: Literal["normal", "confidential", "sensitive", "restricted"] = "normal"
    metadata: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = Field(default=None, max_length=500)
    allow_memory_suggestions: bool = True


class ConfirmBody(StrictBody):
    confirm: Literal[True]


class DeleteSourceBody(ConfirmBody):
    revision: int = Field(ge=1)
    purge: bool = False


class MemoryCreateBody(StrictBody):
    source_id: Optional[str] = None
    category: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=20_000)
    status: Literal["suggested", "approved", "rejected", "expired"] = "suggested"
    sensitive: bool = False
    expires_at: Optional[str] = None
    incognito: bool = False


class MemoryUpdateBody(StrictBody):
    text: Optional[str] = Field(default=None, min_length=1, max_length=20_000)
    category: Optional[str] = Field(default=None, max_length=60)
    status: Optional[Literal["suggested", "approved", "rejected", "expired"]] = None
    sensitive: Optional[bool] = None
    expires_at: Optional[str] = None
    revision: int = Field(ge=1)


class MemoryDeleteBody(ConfirmBody):
    revision: int = Field(ge=1)


class VaultUpdateBody(StrictBody):
    revision: int = Field(ge=1)
    classification: Optional[Literal["identity", "financial", "insurance", "property", "vehicle", "legal", "medical", "travel", "employment", "membership", "general"]] = None
    document_expiry_at: Optional[str] = None
    obligations: Optional[list[str]] = Field(default=None, max_length=100)
    sensitivity: Optional[Literal["normal", "confidential", "sensitive", "restricted"]] = None
    allow_memory_suggestions: Optional[bool] = None


def _raise(exc: KnowledgeError) -> None:
    status = 404 if exc.code == "knowledge_not_found" else 409 if exc.code == "knowledge_conflict" else 422
    raise HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)}) from exc


async def _bounded_upload(file: UploadFile) -> bytes:
    value = bytearray()
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        value.extend(chunk)
        if len(value) > MAX_KNOWLEDGE_UPLOAD:
            raise HTTPException(413, detail={"code": "knowledge_upload_too_large", "message": "Knowledge upload exceeds 50 MiB"})
    return bytes(value)


def _extract_file(filename: str, content_type: str, body: bytes) -> tuple[str, str, dict[str, Any]]:
    safe_name = Path(filename or "upload").name
    suffix = Path(safe_name).suffix.lower()
    if not body:
        raise HTTPException(422, detail={"code": "empty_knowledge_upload", "message": "Uploaded file is empty"})
    if body.startswith((b"MZ", b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")):
        raise HTTPException(415, detail={"code": "unsafe_knowledge_upload", "message": "Executable files cannot be indexed"})
    metadata = {"filename": safe_name, "content_type": content_type, "bytes": len(body), "file_safety": "basic_signature_and_structure_checks"}
    try:
        if suffix in _TEXT_SUFFIXES:
            if b"\x00" in body:
                raise ValueError("binary NUL byte")
            text = body.decode("utf-8-sig")
            return "markdown" if suffix in {".md", ".markdown"} else "text", text, metadata
        if suffix == ".pdf":
            if not body.startswith(b"%PDF-"):
                raise ValueError("invalid PDF signature")
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(body), strict=True)
            if getattr(reader, "is_encrypted", False):
                raise ValueError("encrypted PDFs are not supported")
            pages = []
            for number, page in enumerate(reader.pages):
                pages.append(f"# Page {number + 1}\n\n{page.extract_text() or ''}")
            return "pdf", "\n\n".join(pages), {**metadata, "pages": len(pages)}
        if suffix == ".docx":
            with zipfile.ZipFile(BytesIO(body)) as archive:
                names = archive.namelist()
                if len(names) > 10_000 or sum(item.file_size for item in archive.infolist()) > 250 * 1024 * 1024:
                    raise ValueError("archive expansion limit exceeded")
                xml = archive.read("word/document.xml").decode("utf-8")
            text = re.sub(r"<w:tab[^>]*/>", "\t", xml)
            text = re.sub(r"</w:p>", "\n\n", text)
            text = re.sub(r"<[^>]+>", "", text)
            return "document", text, metadata
    except (ValueError, UnicodeError, zipfile.BadZipFile, KeyError) as exc:
        raise HTTPException(422, detail={"code": "knowledge_extraction_failed", "message": str(exc)[:500]}) from exc
    raise HTTPException(415, detail={"code": "unsupported_knowledge_file", "message": f"Unsupported file type: {suffix or content_type}"})


def setup_knowledge_routes(service: Optional[KnowledgeService] = None) -> APIRouter:
    knowledge = service or get_knowledge_service()
    router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

    @router.post("/sources/text")
    async def ingest_text(body: TextIngestBody, owner: str = Depends(require_user)):
        try:
            return knowledge.ingest_text(owner, **body.model_dump())
        except KnowledgeError as exc: _raise(exc)

    @router.post("/sources/upload")
    async def upload_source(file: UploadFile = File(...), title: str = Form(""), sensitivity: str = Form("normal"), allow_memory_suggestions: bool = Form(True), owner: str = Depends(require_user)):
        raw = await _bounded_upload(file)
        source_type, content, metadata = _extract_file(file.filename or "upload", file.content_type or "application/octet-stream", raw)
        try:
            return knowledge.ingest_text(owner, source_type=source_type, title=title.strip() or Path(file.filename or "Upload").stem, content=content, original_location=f"upload:{Path(file.filename or 'upload').name}", sensitivity=sensitivity, metadata=metadata, allow_memory_suggestions=allow_memory_suggestions)
        except KnowledgeError as exc: _raise(exc)

    @router.get("/sources")
    async def list_sources(source_type: Optional[str] = None, sensitivity: Optional[str] = None, status: Optional[str] = None, query: str = Query("", max_length=500), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), owner: str = Depends(require_user)):
        try: return knowledge.list_sources(owner, source_type=source_type, sensitivity=sensitivity, status=status, query=query, limit=limit, offset=offset)
        except KnowledgeError as exc: _raise(exc)

    @router.get("/sources/{source_id}")
    async def get_source(source_id: str, include_content: bool = False, owner: str = Depends(require_user)):
        try: return knowledge.get_source(owner, source_id, include_content=include_content)
        except KnowledgeError as exc: _raise(exc)

    @router.get("/search")
    async def search_knowledge(query: str = Query(min_length=1, max_length=2000), source_type: Optional[str] = None, sensitivity: Optional[str] = None, source_id: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None, limit: int = Query(8, ge=1, le=50), owner: str = Depends(require_user)):
        try: return knowledge.grounded_context(owner, query, source_type=source_type, sensitivity=sensitivity, source_id=source_id, date_from=date_from, date_to=date_to, limit=limit)
        except KnowledgeError as exc: _raise(exc)

    @router.get("/vault")
    async def list_vault(classification: Optional[str] = None, expiring_days: Optional[int] = Query(None, ge=0, le=3650), owner: str = Depends(require_user)):
        try: return knowledge.list_vault(owner, classification=classification, expiring_days=expiring_days)
        except KnowledgeError as exc: _raise(exc)

    @router.get("/vault/search")
    async def search_vault(query: str = Query(min_length=1, max_length=2000), limit: int = Query(8, ge=1, le=50), owner: str = Depends(require_user)):
        try: return knowledge.vault_context(owner, query, limit=limit)
        except KnowledgeError as exc: _raise(exc)

    @router.post("/sources/{source_id}/analyze-vault")
    async def analyze_vault(source_id: str, body: ConfirmBody, owner: str = Depends(require_user)):
        try: return knowledge.analyze_vault_source(owner, source_id)
        except KnowledgeError as exc: _raise(exc)

    @router.put("/sources/{source_id}/vault")
    async def update_vault(source_id: str, body: VaultUpdateBody, owner: str = Depends(require_user)):
        values = body.model_dump(exclude={"revision"}, exclude_none=True)
        try: return knowledge.update_vault_source(owner, source_id, values, expected_revision=body.revision)
        except KnowledgeError as exc: _raise(exc)

    @router.post("/sources/{source_id}/rebuild")
    async def rebuild_source(source_id: str, body: ConfirmBody, owner: str = Depends(require_user)):
        try: return knowledge.rebuild_source(owner, source_id)
        except KnowledgeError as exc: _raise(exc)

    @router.post("/sources/{source_id}/delete-derivatives")
    async def delete_derivatives(source_id: str, body: ConfirmBody, owner: str = Depends(require_user)):
        try: return knowledge.delete_derivatives(owner, source_id)
        except KnowledgeError as exc: _raise(exc)

    @router.delete("/sources/{source_id}")
    async def delete_source(source_id: str, body: DeleteSourceBody, owner: str = Depends(require_user)):
        try: return knowledge.delete_source(owner, source_id, expected_revision=body.revision, purge=body.purge)
        except KnowledgeError as exc: _raise(exc)

    @router.get("/export")
    async def export_knowledge(owner: str = Depends(require_user)):
        sources = knowledge.list_sources(owner, limit=500)["sources"]
        expanded = [knowledge.get_source(owner, item["id"], include_content=True) for item in sources]
        return JSONResponse({"schema": "om-automate-knowledge-export-v1", "sources": expanded, "memories": knowledge.list_memories(owner)}, headers={"Content-Disposition": "attachment; filename=om-automate-knowledge.json"})

    @router.post("/memories")
    async def create_memory(body: MemoryCreateBody, owner: str = Depends(require_user)):
        try: return knowledge.create_memory(owner, body.model_dump())
        except KnowledgeError as exc: _raise(exc)

    @router.get("/memories")
    async def list_memories(status: Optional[str] = None, owner: str = Depends(require_user)):
        try: return {"memories": knowledge.list_memories(owner, status=status)}
        except KnowledgeError as exc: _raise(exc)

    @router.put("/memories/{memory_id}")
    async def update_memory(memory_id: str, body: MemoryUpdateBody, owner: str = Depends(require_user)):
        values = body.model_dump(exclude={"revision"}, exclude_none=True)
        try: return knowledge.update_memory(owner, memory_id, values, expected_revision=body.revision)
        except KnowledgeError as exc: _raise(exc)

    @router.delete("/memories/{memory_id}")
    async def delete_memory(memory_id: str, body: MemoryDeleteBody, owner: str = Depends(require_user)):
        try: return knowledge.delete_memory(owner, memory_id, expected_revision=body.revision)
        except KnowledgeError as exc: _raise(exc)

    return router
