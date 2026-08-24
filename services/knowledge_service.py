"""Local-first knowledge ingestion, hybrid retrieval, grounding, and memory controls."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Optional
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.constants import DATA_DIR
from src.knowledge_models import KnowledgeChunk, KnowledgeMemory, KnowledgeSource, ensure_knowledge_schema


SOURCE_TYPES = frozenset({"document", "pdf", "text", "markdown", "email", "attachment", "meeting_transcript", "note", "web_page", "imported_record", "calendar_event", "approved_memory"})
SENSITIVITIES = frozenset({"normal", "confidential", "sensitive", "restricted"})
MEMORY_CATEGORIES = frozenset({"preferences", "people", "organisations", "projects", "responsibilities", "goals", "routines", "decisions", "commitments", "important_dates", "assets", "properties", "travel", "professional_context", "personal_administration"})
MEMORY_STATES = frozenset({"suggested", "approved", "rejected", "expired"})
VAULT_SOURCE_TYPES = frozenset({"document", "pdf", "text", "markdown", "attachment", "imported_record"})
VAULT_CLASSIFICATIONS = frozenset({"identity", "financial", "insurance", "property", "vehicle", "legal", "medical", "travel", "employment", "membership", "general"})
_WORD = re.compile(r"[\w'-]+", re.UNICODE)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_OWNER_NONE = "__local__"


class KnowledgeError(RuntimeError):
    code = "knowledge_error"


class KnowledgeNotFound(KnowledgeError):
    code = "knowledge_not_found"


class KnowledgeConflict(KnowledgeError):
    code = "knowledge_conflict"


class KnowledgeValidationError(KnowledgeError):
    code = "invalid_knowledge_request"


def _owner(owner: Optional[str]) -> str:
    return str(owner or _OWNER_NONE)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _dt(value: Any, field: str) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value)
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise KnowledgeValidationError(f"{field} must be an ISO datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _text(value: Any, field: str, maximum: int, *, required: bool = False) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise KnowledgeValidationError(f"{field} is required")
    if len(result) > maximum or _CONTROL.search(result):
        raise KnowledgeValidationError(f"{field} is invalid or too long")
    return result


def _tokens(text: str) -> list[str]:
    return [match.group(0).casefold() for match in _WORD.finditer(text)]


def _embedding(text: str, dimensions: int = 256) -> list[float]:
    vector = [0.0] * dimensions
    for token, count in Counter(_tokens(text)).items():
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        slot = int.from_bytes(digest[:4], "big") % dimensions
        vector[slot] += count * (1 if digest[4] & 1 else -1)
    norm = math.sqrt(sum(item * item for item in vector)) or 1.0
    return [item / norm for item in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _chunks(text: str, *, size: int = 1400, overlap: int = 180) -> list[tuple[str, str]]:
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    result: list[tuple[str, str]] = []
    current = ""
    section = ""
    for paragraph in paragraphs or [text]:
        if paragraph.startswith("#"):
            section = paragraph.lstrip("# ")[:500]
        while len(paragraph) > size:
            if current:
                result.append((section, current))
                current = current[-overlap:]
            cut = paragraph.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            piece, paragraph = paragraph[:cut].strip(), paragraph[cut:].strip()
            current = (current + "\n\n" + piece).strip()
            result.append((section, current))
            current = current[-overlap:]
        candidate = (current + "\n\n" + paragraph).strip()
        if len(candidate) > size and current:
            result.append((section, current))
            current = (current[-overlap:] + "\n\n" + paragraph).strip()
        else:
            current = candidate
    if current:
        result.append((section, current))
    return result[:100_000]


def _vault_analysis(text: str) -> dict[str, Any]:
    lowered = text.casefold()
    keywords = {
        "identity": ("passport", "driving licence", "driver license", "birth certificate", "national id"),
        "financial": ("bank", "account statement", "invoice", "tax", "payment", "mortgage"),
        "insurance": ("insurance", "policy number", "premium", "insured"),
        "property": ("tenancy", "lease", "landlord", "property", "deed"),
        "vehicle": ("vehicle", "registration", "motor tax", "nct", "vin"),
        "legal": ("agreement", "contract", "legal", "solicitor", "terms and conditions"),
        "medical": ("medical", "prescription", "patient", "diagnosis", "clinic"),
        "travel": ("flight", "booking", "itinerary", "visa", "boarding pass"),
        "employment": ("employment", "salary", "payslip", "employer", "annual leave"),
        "membership": ("membership", "subscription", "member number", "renewal"),
    }
    scores = {kind: sum(lowered.count(term) for term in terms) for kind, terms in keywords.items()}
    classification = max(scores, key=scores.get) if any(scores.values()) else "general"
    expiry_candidates = []
    date_pattern = re.compile(r"\b(20\d{2}-\d{2}-\d{2}|(?:0?[1-9]|[12]\d|3[01])[/-](?:0?[1-9]|1[0-2])[/-]20\d{2})\b")
    expiry_terms = ("expir", "renew", "valid until", "valid through", "due date", "review date")
    for match in date_pattern.finditer(text):
        start = max(0, match.start() - 90); end = min(len(text), match.end() + 90)
        excerpt = " ".join(text[start:end].split())
        if any(term in excerpt.casefold() for term in expiry_terms):
            parsed = None
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                try:
                    parsed = datetime.strptime(match.group(0), fmt).replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue
            if parsed:
                expiry_candidates.append({"date": parsed.date().isoformat(), "excerpt": excerpt, "start": match.start(), "end": match.end()})
    obligations = []
    obligation_terms = re.compile(r"\b(must|required|shall|need to|renew|submit|pay|cancel|notify|provide|return)\b", re.IGNORECASE)
    for sentence in re.finditer(r"[^\n.!?]{1,500}(?:[.!?]|$)", text):
        value = " ".join(sentence.group(0).split())
        if value and obligation_terms.search(value):
            obligations.append({"text": value, "start": sentence.start(), "end": sentence.end()})
        if len(obligations) >= 50:
            break
    return {
        "classification": classification,
        "classification_scores": {key: value for key, value in scores.items() if value},
        "expiry_candidates": expiry_candidates[:25],
        "document_expiry_at": expiry_candidates[0]["date"] if expiry_candidates else None,
        "obligations": obligations,
        "analysis_method": "deterministic_keyword_and_span_v1",
        "review_status": "suggested",
        "analyzed_at": _iso(_now()),
    }


class KnowledgeService:
    def __init__(self, *, session_factory=None, database_url: Optional[str] = None):
        if session_factory is None:
            url = database_url or os.getenv("OM_KNOWLEDGE_DATABASE_URL") or f"sqlite:///{Path(DATA_DIR) / 'knowledge.db'}"
            engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
            ensure_knowledge_schema(engine)
            session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        self.session_factory = session_factory

    @staticmethod
    def _source(row: KnowledgeSource, *, include_content: bool = False) -> dict[str, Any]:
        value = {"id": row.id, "owner": None if row.owner == _OWNER_NONE else row.owner, "type": row.source_type, "title": row.title, "original_location": row.original_location, "source_created_at": _iso(row.source_created_at), "imported_at": _iso(row.imported_at), "last_indexed_at": _iso(row.last_indexed_at), "access_permissions": json.loads(row.access_permissions_json), "sensitivity": row.sensitivity, "hash": row.content_hash, "version": row.version, "processing_status": row.processing_status, "processing_error": row.processing_error, "deletion_status": row.deletion_status, "derivatives_deleted_at": _iso(row.derivatives_deleted_at), "metadata": json.loads(row.metadata_json), "allow_memory_suggestions": bool(row.allow_memory_suggestions), "expires_at": _iso(row.expires_at), "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at), "revision": row.revision}
        if include_content:
            value["content"] = row.content_text
        return value

    @staticmethod
    def _memory(row: KnowledgeMemory) -> dict[str, Any]:
        return {"id": row.id, "source_id": row.source_id, "category": row.category, "text": row.text, "status": row.status, "sensitive": bool(row.sensitive), "expires_at": _iso(row.expires_at), "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at), "revision": row.revision}

    def _owned(self, db, owner: Optional[str], source_id: str, *, active_only: bool = False) -> KnowledgeSource:
        row = db.query(KnowledgeSource).filter(KnowledgeSource.id == str(source_id), KnowledgeSource.owner == _owner(owner)).first()
        if row is None or (active_only and row.deletion_status != "active"):
            raise KnowledgeNotFound("Knowledge source not found")
        return row

    def ingest_text(self, owner: Optional[str], *, source_type: str, title: str, content: str, metadata: Optional[Mapping[str, Any]] = None, original_location: Optional[str] = None, source_created_at: Any = None, sensitivity: str = "normal", access_permissions: Optional[list[str]] = None, idempotency_key: Optional[str] = None, allow_memory_suggestions: bool = True) -> dict[str, Any]:
        kind = _text(source_type, "source_type", 60, required=True).lower()
        if kind not in SOURCE_TYPES:
            raise KnowledgeValidationError("source_type is unsupported")
        normalized = str(content or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized or len(normalized) > 50_000_000 or _CONTROL.search(normalized):
            raise KnowledgeValidationError("content is empty, unsafe, or too large")
        sensitivity = str(sensitivity or "normal").lower()
        if sensitivity not in SENSITIVITIES:
            raise KnowledgeValidationError("sensitivity is invalid")
        meta = dict(metadata or {})
        if len(json.dumps(meta, ensure_ascii=False)) > 1_000_000:
            raise KnowledgeValidationError("metadata is too large")
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        owner_key = _owner(owner)
        idem = _text(idempotency_key, "idempotency_key", 500) or None
        db = self.session_factory()
        try:
            if idem:
                existing = db.query(KnowledgeSource).filter(KnowledgeSource.owner == owner_key, KnowledgeSource.metadata_json.like(f'%"idempotency_key":"{idem}"%')).first()
                if existing:
                    return self._source(existing)
            duplicate = db.query(KnowledgeSource).filter(KnowledgeSource.owner == owner_key, KnowledgeSource.content_hash == digest, KnowledgeSource.source_type == kind, KnowledgeSource.deletion_status == "active").first()
            if duplicate:
                return self._source(duplicate)
            if idem:
                meta["idempotency_key"] = idem
            now = _now()
            source = KnowledgeSource(id=str(uuid.uuid4()), owner=owner_key, source_type=kind, title=_text(title, "title", 500, required=True), original_location=_text(original_location, "original_location", 4000) or None, source_created_at=_dt(source_created_at, "source_created_at"), imported_at=now, last_indexed_at=now, access_permissions_json=json.dumps(access_permissions or ["owner"], separators=(",", ":")), sensitivity=sensitivity, content_hash=digest, processing_status="indexing", metadata_json=json.dumps(meta, ensure_ascii=False, sort_keys=True, separators=(",", ":")), content_text=normalized, allow_memory_suggestions=bool(allow_memory_suggestions), created_at=now, updated_at=now)
            db.add(source); db.flush()
            for position, (section, body) in enumerate(_chunks(normalized)):
                chunk_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
                db.add(KnowledgeChunk(id=f"{source.id}:{position}:{chunk_hash[:12]}", source_id=source.id, owner=owner_key, position=position, section=section or None, text=body, text_hash=chunk_hash, token_count=len(_tokens(body)), embedding_json=json.dumps(_embedding(body), separators=(",", ":")), metadata_json=json.dumps({"source_version": 1}, separators=(",", ":"))))
            source.processing_status = "ready"; db.commit(); db.refresh(source)
            return self._source(source)
        except Exception:
            db.rollback(); raise
        finally:
            db.close()

    def get_source(self, owner: Optional[str], source_id: str, *, include_content: bool = False) -> dict[str, Any]:
        db = self.session_factory()
        try: return self._source(self._owned(db, owner, source_id), include_content=include_content)
        finally: db.close()

    def list_sources(self, owner: Optional[str], *, source_type: Optional[str] = None, sensitivity: Optional[str] = None, status: Optional[str] = None, query: str = "", limit: int = 100, offset: int = 0) -> dict[str, Any]:
        if not 1 <= int(limit) <= 500 or int(offset) < 0: raise KnowledgeValidationError("pagination is invalid")
        db = self.session_factory()
        try:
            q = db.query(KnowledgeSource).filter(KnowledgeSource.owner == _owner(owner), KnowledgeSource.deletion_status == "active")
            if source_type: q = q.filter(KnowledgeSource.source_type == source_type)
            if sensitivity: q = q.filter(KnowledgeSource.sensitivity == sensitivity)
            if status: q = q.filter(KnowledgeSource.processing_status == status)
            if query: q = q.filter(KnowledgeSource.title.ilike(f"%{_text(query, 'query', 500)}%"))
            total = q.count(); rows = q.order_by(KnowledgeSource.imported_at.desc()).offset(int(offset)).limit(int(limit)).all()
            return {"sources": [self._source(row) for row in rows], "total": total, "limit": int(limit), "offset": int(offset)}
        finally: db.close()

    def search(self, owner: Optional[str], query: str, *, source_type: Optional[str] = None, source_types: Optional[set[str]] = None, sensitivity: Optional[str] = None, source_id: Optional[str] = None, date_from: Any = None, date_to: Any = None, limit: int = 8) -> dict[str, Any]:
        query = _text(query, "query", 2000, required=True)
        if not 1 <= int(limit) <= 50: raise KnowledgeValidationError("limit must be 1-50")
        query_tokens = Counter(_tokens(query)); query_vector = _embedding(query); now = _now()
        db = self.session_factory()
        try:
            q = db.query(KnowledgeChunk, KnowledgeSource).join(KnowledgeSource, KnowledgeSource.id == KnowledgeChunk.source_id).filter(KnowledgeChunk.owner == _owner(owner), KnowledgeSource.deletion_status == "active", KnowledgeSource.processing_status == "ready")
            q = q.filter((KnowledgeSource.expires_at.is_(None)) | (KnowledgeSource.expires_at > now))
            if source_type: q = q.filter(KnowledgeSource.source_type == source_type)
            if source_types: q = q.filter(KnowledgeSource.source_type.in_(source_types))
            if sensitivity: q = q.filter(KnowledgeSource.sensitivity == sensitivity)
            if source_id: q = q.filter(KnowledgeSource.id == source_id)
            if date_from: q = q.filter(KnowledgeSource.source_created_at >= _dt(date_from, "date_from"))
            if date_to: q = q.filter(KnowledgeSource.source_created_at <= _dt(date_to, "date_to"))
            rows = q.all(); scored = []
            for chunk, source in rows:
                terms = Counter(_tokens(chunk.text)); overlap = sum(min(count, terms.get(token, 0)) for token, count in query_tokens.items())
                lexical = overlap / max(1, sum(query_tokens.values()))
                phrase = 1.0 if query.casefold() in chunk.text.casefold() else 0.0
                vector = max(0.0, _cosine(query_vector, json.loads(chunk.embedding_json)))
                score = 0.50 * lexical + 0.35 * vector + 0.15 * phrase
                if score <= 0: continue
                scored.append((score, chunk, source))
            scored.sort(key=lambda item: (-item[0], item[2].imported_at, item[1].position))
            results = []
            for score, chunk, source in scored[: int(limit)]:
                results.append({"source_id": source.id, "source_title": source.title, "source_type": source.source_type, "source_version": source.version, "sensitivity": source.sensitivity, "chunk_id": chunk.id, "section": chunk.section, "position": chunk.position, "excerpt": chunk.text, "score": round(score, 6), "source_url": f"/api/knowledge/sources/{source.id}", "fact_state": "source_excerpt"})
            return {"query": query, "results": results, "insufficient_evidence": not bool(results), "retrieval": {"method": "hybrid_lexical_vector_metadata_rerank", "owner_filtered": True}}
        finally: db.close()

    def grounded_context(self, owner: Optional[str], query: str, **filters) -> dict[str, Any]:
        found = self.search(owner, query, **filters)
        return {**found, "answer_policy": {"must_cite_source_id": True, "must_link_source_record": True, "must_distinguish_inference": True, "must_state_insufficient_evidence": True}, "citations": [{"source_id": item["source_id"], "chunk_id": item["chunk_id"], "title": item["source_title"], "url": item["source_url"], "excerpt": item["excerpt"]} for item in found["results"]]}

    def analyze_vault_source(self, owner: Optional[str], source_id: str) -> dict[str, Any]:
        db = self.session_factory()
        try:
            source = self._owned(db, owner, source_id, active_only=True)
            if source.source_type not in VAULT_SOURCE_TYPES:
                raise KnowledgeValidationError("Only document-like sources can enter the vault workflow")
            metadata = json.loads(source.metadata_json)
            metadata["vault"] = _vault_analysis(source.content_text)
            source.metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            source.revision += 1; source.updated_at = _now(); db.commit(); db.refresh(source)
            return self._source(source)
        except Exception:
            db.rollback(); raise
        finally:
            db.close()

    def update_vault_source(self, owner: Optional[str], source_id: str, values: Mapping[str, Any], *, expected_revision: int) -> dict[str, Any]:
        db = self.session_factory()
        try:
            source = self._owned(db, owner, source_id, active_only=True)
            if source.source_type not in VAULT_SOURCE_TYPES:
                raise KnowledgeValidationError("Only document-like sources can enter the vault workflow")
            if source.revision != int(expected_revision):
                raise KnowledgeConflict("Knowledge source was changed by another request")
            metadata = json.loads(source.metadata_json); vault = dict(metadata.get("vault") or {})
            if "classification" in values:
                classification = str(values["classification"] or "").lower()
                if classification not in VAULT_CLASSIFICATIONS:
                    raise KnowledgeValidationError("vault classification is invalid")
                vault["classification"] = classification
            if "document_expiry_at" in values:
                parsed = _dt(values["document_expiry_at"], "document_expiry_at")
                vault["document_expiry_at"] = parsed.date().isoformat() if parsed else None
            if "obligations" in values:
                obligations = values["obligations"]
                if not isinstance(obligations, list) or len(obligations) > 100:
                    raise KnowledgeValidationError("obligations must be a list of at most 100 items")
                vault["obligations"] = [{"text": _text(item, "obligation", 2000, required=True), "reviewed": True} for item in obligations]
            if "sensitivity" in values:
                sensitivity = str(values["sensitivity"] or "").lower()
                if sensitivity not in SENSITIVITIES:
                    raise KnowledgeValidationError("sensitivity is invalid")
                source.sensitivity = sensitivity
            if "allow_memory_suggestions" in values:
                source.allow_memory_suggestions = bool(values["allow_memory_suggestions"])
            vault["review_status"] = "approved"; vault["reviewed_at"] = _iso(_now())
            metadata["vault"] = vault; source.metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            source.revision += 1; source.updated_at = _now(); db.commit(); db.refresh(source)
            return self._source(source)
        except Exception:
            db.rollback(); raise
        finally:
            db.close()

    def list_vault(self, owner: Optional[str], *, classification: Optional[str] = None, expiring_days: Optional[int] = None) -> dict[str, Any]:
        rows = self.list_sources(owner, limit=500)["sources"]
        entries = []
        cutoff = (_now() + timedelta(days=int(expiring_days))).date() if expiring_days is not None else None
        for source in rows:
            if source["type"] not in VAULT_SOURCE_TYPES:
                continue
            vault = dict(source["metadata"].get("vault") or {})
            if not vault or (classification and vault.get("classification") != classification):
                continue
            expiry = vault.get("document_expiry_at")
            if cutoff and (not expiry or datetime.fromisoformat(expiry).date() > cutoff):
                continue
            entries.append({**source, "vault": vault})
        entries.sort(key=lambda item: (item["vault"].get("document_expiry_at") or "9999-12-31", item["title"].casefold()))
        return {"documents": entries, "total": len(entries), "owner_filtered": True}

    def vault_context(self, owner: Optional[str], query: str, *, limit: int = 8) -> dict[str, Any]:
        result = self.grounded_context(owner, query, source_types=set(VAULT_SOURCE_TYPES), limit=limit)
        return {**result, "scope": "document_vault", "sensitive_sources_require_owner": True}

    def delete_derivatives(self, owner: Optional[str], source_id: str) -> dict[str, Any]:
        db = self.session_factory()
        try:
            source = self._owned(db, owner, source_id); count = db.query(KnowledgeChunk).filter(KnowledgeChunk.source_id == source.id).delete(synchronize_session=False); source.derivatives_deleted_at = _now(); source.processing_status = "not_indexed"; source.revision += 1; source.updated_at = _now(); db.commit(); return {"id": source.id, "chunks_deleted": count}
        except Exception: db.rollback(); raise
        finally: db.close()

    def rebuild_source(self, owner: Optional[str], source_id: str) -> dict[str, Any]:
        db = self.session_factory()
        try:
            source = self._owned(db, owner, source_id, active_only=True); db.query(KnowledgeChunk).filter(KnowledgeChunk.source_id == source.id).delete(synchronize_session=False)
            for position, (section, body) in enumerate(_chunks(source.content_text)):
                digest = hashlib.sha256(body.encode()).hexdigest(); db.add(KnowledgeChunk(id=f"{source.id}:{position}:{digest[:12]}", source_id=source.id, owner=source.owner, position=position, section=section or None, text=body, text_hash=digest, token_count=len(_tokens(body)), embedding_json=json.dumps(_embedding(body), separators=(",", ":")), metadata_json=json.dumps({"source_version": source.version}, separators=(",", ":"))))
            source.processing_status = "ready"; source.processing_error = None; source.last_indexed_at = _now(); source.derivatives_deleted_at = None; source.revision += 1; source.updated_at = _now(); db.commit(); db.refresh(source); return self._source(source)
        except Exception: db.rollback(); raise
        finally: db.close()

    def delete_source(self, owner: Optional[str], source_id: str, *, expected_revision: int, purge: bool = False) -> dict[str, Any]:
        db = self.session_factory()
        try:
            source = self._owned(db, owner, source_id)
            if source.revision != int(expected_revision): raise KnowledgeConflict("Knowledge source was changed by another request")
            if purge: db.delete(source)
            else:
                db.query(KnowledgeChunk).filter(KnowledgeChunk.source_id == source.id).delete(synchronize_session=False); source.content_text = ""; source.deletion_status = "deleted"; source.processing_status = "deleted"; source.derivatives_deleted_at = _now(); source.updated_at = _now(); source.revision += 1
            db.commit(); return {"id": source_id, "deleted": True, "purged": bool(purge)}
        except Exception: db.rollback(); raise
        finally: db.close()

    def create_memory(self, owner: Optional[str], values: Mapping[str, Any]) -> dict[str, Any]:
        if values.get("incognito"):
            raise KnowledgeValidationError("Incognito content cannot create durable memory")
        category = str(values.get("category") or "").lower(); state = str(values.get("status") or "suggested").lower()
        if category not in MEMORY_CATEGORIES or state not in MEMORY_STATES: raise KnowledgeValidationError("memory category or status is invalid")
        db = self.session_factory()
        try:
            source_id = values.get("source_id")
            if source_id:
                source = self._owned(db, owner, str(source_id), active_only=True)
                if not source.allow_memory_suggestions: raise KnowledgeConflict("This source is blocked from creating memories")
            row = KnowledgeMemory(id=str(uuid.uuid4()), owner=_owner(owner), source_id=source_id or None, category=category, text=_text(values.get("text"), "text", 20_000, required=True), status=state, sensitive=bool(values.get("sensitive", False)), expires_at=_dt(values.get("expires_at"), "expires_at"), created_at=_now(), updated_at=_now())
            db.add(row); db.commit(); db.refresh(row); return self._memory(row)
        except Exception: db.rollback(); raise
        finally: db.close()

    def list_memories(self, owner: Optional[str], *, status: Optional[str] = None) -> list[dict[str, Any]]:
        db = self.session_factory()
        try:
            q = db.query(KnowledgeMemory).filter(KnowledgeMemory.owner == _owner(owner))
            if status: q = q.filter(KnowledgeMemory.status == status)
            return [self._memory(row) for row in q.order_by(KnowledgeMemory.updated_at.desc()).all()]
        finally: db.close()

    def update_memory(self, owner: Optional[str], memory_id: str, values: Mapping[str, Any], *, expected_revision: int) -> dict[str, Any]:
        db = self.session_factory()
        try:
            row = db.query(KnowledgeMemory).filter(KnowledgeMemory.id == str(memory_id), KnowledgeMemory.owner == _owner(owner)).first()
            if row is None: raise KnowledgeNotFound("Knowledge memory not found")
            if row.revision != int(expected_revision): raise KnowledgeConflict("Knowledge memory was changed by another request")
            if "text" in values: row.text = _text(values["text"], "text", 20_000, required=True)
            if "category" in values:
                if values["category"] not in MEMORY_CATEGORIES: raise KnowledgeValidationError("memory category is invalid")
                row.category = values["category"]
            if "status" in values:
                if values["status"] not in MEMORY_STATES: raise KnowledgeValidationError("memory status is invalid")
                row.status = values["status"]
            if "sensitive" in values: row.sensitive = bool(values["sensitive"])
            if "expires_at" in values: row.expires_at = _dt(values["expires_at"], "expires_at")
            row.revision += 1; row.updated_at = _now(); db.commit(); db.refresh(row); return self._memory(row)
        except Exception: db.rollback(); raise
        finally: db.close()

    def delete_memory(self, owner: Optional[str], memory_id: str, *, expected_revision: int) -> dict[str, Any]:
        db = self.session_factory()
        try:
            row = db.query(KnowledgeMemory).filter(KnowledgeMemory.id == str(memory_id), KnowledgeMemory.owner == _owner(owner)).first()
            if row is None: raise KnowledgeNotFound("Knowledge memory not found")
            if row.revision != int(expected_revision): raise KnowledgeConflict("Knowledge memory was changed by another request")
            db.delete(row); db.commit(); return {"id": memory_id, "deleted": True}
        except Exception: db.rollback(); raise
        finally: db.close()

    def purge_expired(self, owner: Optional[str], *, memory_retention_days: Optional[int] = None) -> dict[str, int]:
        """Purge expired memories and source derivatives for one owner."""
        now = _now()
        db = self.session_factory()
        try:
            memory_query = db.query(KnowledgeMemory).filter(
                KnowledgeMemory.owner == _owner(owner),
                KnowledgeMemory.expires_at.is_not(None),
                KnowledgeMemory.expires_at <= now,
            )
            if memory_retention_days is not None:
                policy_cutoff = now - timedelta(days=int(memory_retention_days))
                policy_ids = [row[0] for row in db.query(KnowledgeMemory.id).filter(
                    KnowledgeMemory.owner == _owner(owner),
                    KnowledgeMemory.created_at <= policy_cutoff,
                ).all()]
            else:
                policy_ids = []
            expired_ids = [row.id for row in memory_query.all()]
            memory_ids = list(dict.fromkeys([*expired_ids, *policy_ids]))
            if memory_ids:
                db.query(KnowledgeMemory).filter(KnowledgeMemory.id.in_(memory_ids)).delete(synchronize_session=False)
            sources = db.query(KnowledgeSource).filter(
                KnowledgeSource.owner == _owner(owner),
                KnowledgeSource.deletion_status == "active",
                KnowledgeSource.expires_at.is_not(None),
                KnowledgeSource.expires_at <= now,
            ).all()
            for source in sources:
                db.query(KnowledgeChunk).filter(KnowledgeChunk.source_id == source.id).delete(synchronize_session=False)
                source.content_text = ""
                source.deletion_status = "expired"
                source.processing_status = "expired"
                source.derivatives_deleted_at = now
                source.updated_at = now
                source.revision += 1
            db.commit()
            return {"memories_purged": len(memory_ids), "sources_expired": len(sources)}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


_knowledge_service: Optional[KnowledgeService] = None


def get_knowledge_service() -> KnowledgeService:
    global _knowledge_service
    if _knowledge_service is None:
        _knowledge_service = KnowledgeService()
    return _knowledge_service
