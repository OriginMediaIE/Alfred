from datetime import datetime, timedelta, timezone
import json
import sqlite3

from services.knowledge_service import KnowledgeService
from services.privacy_retention import purge_email_cache
from src.upload_handler import UploadHandler


def test_email_retention_purges_only_owner_cache_not_scheduled_mail(tmp_path):
    path=tmp_path/"scheduled.db";old=(datetime.now(timezone.utc)-timedelta(days=40)).isoformat()
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE email_summaries(message_id TEXT,owner TEXT,created_at TEXT)")
        db.execute("CREATE TABLE scheduled_emails(id TEXT,owner TEXT,created_at TEXT)")
        db.executemany("INSERT INTO email_summaries VALUES(?,?,?)",[("a","alice",old),("b","bob",old)])
        db.execute("INSERT INTO scheduled_emails VALUES(?,?,?)",("send","alice",old));db.commit()
    assert purge_email_cache("alice",30,database_path=path)==1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT owner FROM email_summaries").fetchall()==[("bob",)]
        assert db.execute("SELECT id FROM scheduled_emails").fetchall()==[("send",)]


def test_upload_retention_removes_owner_bytes_metadata_and_derivatives(tmp_path):
    root=tmp_path/"uploads";root.mkdir();handler=UploadHandler(str(tmp_path),str(root))
    upload_id="a"*32+".txt";stored=root/upload_id;stored.write_text("private")
    thumbs=root/".thumbs";thumbs.mkdir();(thumbs/(upload_id+".jpg")).write_bytes(b"thumb")
    old=(datetime.now()-timedelta(days=40)).isoformat()
    index={"alice:hash":{"id":upload_id,"path":str(stored),"owner":"alice","hash":"hash","uploaded_at":old,"last_accessed":old}}
    handler._atomic_write_json(str(root/"uploads.json"),index)
    assert handler.cleanup_old_uploads("alice",30)==1
    assert not stored.exists() and not (thumbs/(upload_id+".jpg")).exists()
    assert json.loads((root/"uploads.json").read_text())=={}


def test_knowledge_retention_purges_old_memories_and_expired_sources(tmp_path):
    service=KnowledgeService(database_url=f"sqlite:///{tmp_path/'knowledge.db'}")
    source=service.ingest_text("alice",source_type="note",title="Source",content="grounded evidence")
    memory=service.create_memory("alice",{"category":"goals","text":"old memory","status":"approved"})
    db=service.session_factory()
    try:
        from src.knowledge_models import KnowledgeMemory,KnowledgeSource
        db.query(KnowledgeMemory).filter(KnowledgeMemory.id==memory["id"]).update({"created_at":datetime.now(timezone.utc)-timedelta(days=50)})
        db.query(KnowledgeSource).filter(KnowledgeSource.id==source["id"]).update({"expires_at":datetime.now(timezone.utc)-timedelta(days=1)})
        db.commit()
    finally:db.close()
    result=service.purge_expired("alice",memory_retention_days=30)
    assert result=={"memories_purged":1,"sources_expired":1}
    assert service.list_memories("alice")==[]
    assert service.get_source("alice",source["id"],include_content=True)["content"]==""
