import json
import io
import sqlite3
import zipfile
from pathlib import Path
import pytest
from services.backup_service import BackupError, BackupService, HEADER
from src.restore_bootstrap import apply_pending_restore, stage_restore_rollback
from services.automation_service import DefaultActionRunner


def test_backup_excludes_keys_and_sessions_and_validates(tmp_path):
    (tmp_path/"notes.txt").write_text("important",encoding="utf-8")
    (tmp_path/".app_key").write_text("never backup",encoding="utf-8")
    (tmp_path/"sessions.json").write_text('{"token":"secret"}',encoding="utf-8")
    service=BackupService(tmp_path);payload,manifest=service.create()
    preview=service.validate(payload)
    paths={item["path"] for item in manifest["files"]}
    assert "data/notes.txt" in paths and "data/.app_key" not in paths and "data/sessions.json" not in paths
    assert preview["validated"] is True and preview["key_included"] is False


def test_encrypted_backup_requires_correct_passphrase(tmp_path):
    (tmp_path/"file.txt").write_text("private",encoding="utf-8")
    service=BackupService(tmp_path);payload,_=service.create(passphrase="long secure passphrase")
    assert payload.startswith(HEADER)
    with pytest.raises(BackupError):service.validate(payload,passphrase="wrong passphrase")
    assert service.validate(payload,passphrase="long secure passphrase")["file_count"]==1


def test_encrypted_backup_restores_to_a_fresh_install(tmp_path):
    source=tmp_path/"source";target=tmp_path/"fresh";source.mkdir();target.mkdir()
    (source/".app_key").write_text("instance-secret",encoding="utf-8")
    database=source/"state.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE facts (value TEXT)")
        connection.execute("INSERT INTO facts VALUES ('portable')")
        connection.commit()
    payload,manifest=BackupService(source).create(passphrase="portable backup passphrase")
    service=BackupService(target)
    preview=service.preflight(payload,passphrase="portable backup passphrase")
    assert manifest["schema"]=="om-automate-backup-v2"
    assert preview["fresh_install_portable"] is True
    assert preview["database_checks"]==[{"path":"data/state.db","integrity":"ok"}]
    service.stage_restore(payload,passphrase="portable backup passphrase")
    apply_pending_restore(target)
    assert (target/".app_key").read_text(encoding="utf-8")=="instance-secret"
    with sqlite3.connect(target/"state.db") as connection:
        assert connection.execute("SELECT value FROM facts").fetchone()==("portable",)


def test_restore_is_staged_then_applied_with_rollback(tmp_path):
    source=tmp_path/"source";target=tmp_path/"target";source.mkdir();target.mkdir()
    (source/"state.txt").write_text("new",encoding="utf-8");payload,_=BackupService(source).create()
    (target/".app_key").write_text("original-instance-key",encoding="utf-8")
    (target/"state.txt").write_text("old",encoding="utf-8");service=BackupService(target);staged=service.stage_restore(payload)
    assert (target/"state.txt").read_text()=="old"
    result=apply_pending_restore(target)
    assert result["restore_id"]==staged["restore_id"] and (target/"state.txt").read_text()=="new"
    assert (Path(result["rollback"])/"state.txt").read_text()=="old"


def test_completed_restore_can_be_rolled_back_on_next_restart(tmp_path):
    source=tmp_path/"source";target=tmp_path/"target";source.mkdir();target.mkdir()
    (source/"state.txt").write_text("new",encoding="utf-8")
    (source/"introduced.txt").write_text("remove on rollback",encoding="utf-8")
    (target/"state.txt").write_text("old",encoding="utf-8")
    (target/".app_key").write_text("original-instance-key",encoding="utf-8")
    payload,_=BackupService(source).create()
    staged=BackupService(target).stage_restore(payload)
    apply_pending_restore(target)
    rollback=stage_restore_rollback(target,staged["restore_id"])
    assert rollback["status"]=="rollback_staged_restart_required"
    apply_pending_restore(target)
    assert (target/"state.txt").read_text(encoding="utf-8")=="old"
    assert not (target/"introduced.txt").exists()


def test_restore_rejects_tampered_restore_identifier(tmp_path):
    stage=tmp_path/"restore_staging"/"valid";stage.mkdir(parents=True)
    (stage/"state.txt").write_text("new",encoding="utf-8")
    (tmp_path/"pending_restore.json").write_text(json.dumps({"restore_id":"../escape","stage":str(stage)}),encoding="utf-8")
    with pytest.raises(RuntimeError,match="identifier"):
        apply_pending_restore(tmp_path)


@pytest.mark.asyncio
async def test_automation_action_can_create_a_scheduled_backup(tmp_path,monkeypatch):
    import services.backup_service as backup_module
    import services.automation_service as automation_module
    monkeypatch.setattr(backup_module,"DATA_DIR",str(tmp_path));monkeypatch.setattr(automation_module,"DATA_DIR",str(tmp_path))
    passphrase_file=tmp_path/"scheduled-backup-passphrase";passphrase_file.write_text("a strong separate passphrase",encoding="utf-8");monkeypatch.setenv("OM_SCHEDULED_BACKUP_PASSPHRASE_FILE",str(passphrase_file))
    (tmp_path/"state.txt").write_text("scheduled",encoding="utf-8")
    result=await DefaultActionRunner()("alice",{"type":"create_backup","parameters":{}},{"correlation_id":"c1"})
    path=Path(result["backup"]["path"])
    assert path.is_file() and path.parent==tmp_path/"backups"
    assert result["backup"]["key_included"] is False
    assert result["backup"]["encrypted"] is True and path.read_bytes().startswith(HEADER)


@pytest.mark.asyncio
async def test_scheduled_backup_fails_closed_without_separate_key_file(tmp_path,monkeypatch):
    import services.backup_service as backup_module
    import services.automation_service as automation_module
    monkeypatch.setattr(backup_module,"DATA_DIR",str(tmp_path));monkeypatch.setattr(automation_module,"DATA_DIR",str(tmp_path));monkeypatch.delenv("OM_SCHEDULED_BACKUP_PASSPHRASE_FILE",raising=False)
    with pytest.raises(Exception,match="OM_SCHEDULED_BACKUP_PASSPHRASE_FILE"):
        await DefaultActionRunner()("alice",{"type":"create_backup","parameters":{}},{"correlation_id":"c1"})


def test_backup_excludes_migration_lock_sidecars(tmp_path):
    (tmp_path/"state.db.om-migrate.lock").write_text("",encoding="utf-8")
    (tmp_path/"state.txt").write_text("ok",encoding="utf-8")
    _payload,manifest=BackupService(tmp_path).create()
    paths={item["path"] for item in manifest["files"]}
    assert "data/state.db.om-migrate.lock" not in paths


def test_backup_snapshot_removes_reasoning_and_incognito_residue(tmp_path):
    database=tmp_path/"odysseus.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY,name TEXT)")
        connection.execute("CREATE TABLE chat_messages (id TEXT PRIMARY KEY,session_id TEXT,content TEXT,metadata TEXT)")
        connection.execute("INSERT INTO sessions VALUES ('normal','Normal')")
        connection.execute("INSERT INTO sessions VALUES ('private','Nobody')")
        connection.execute(
            "INSERT INTO chat_messages VALUES (?,?,?,?)",
            ('m1','normal','<think>raw secret reasoning</think>Visible answer',json.dumps({'thinking':'legacy secret','model':'local'})),
        )
        connection.execute(
            "INSERT INTO chat_messages VALUES (?,?,?,?)",
            ('m2','private','incognito text','{}'),
        )
        connection.commit()

    payload,_manifest=BackupService(tmp_path).create()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        restored=tmp_path/"snapshot.db"
        restored.write_bytes(archive.read("data/odysseus.db"))
    with sqlite3.connect(restored) as connection:
        rows=connection.execute("SELECT content,metadata FROM chat_messages").fetchall()
        sessions=connection.execute("SELECT name FROM sessions").fetchall()

    assert rows == [("Visible answer", '{"model":"local"}')]
    assert sessions == [("Normal",)]
    assert "raw secret reasoning" not in payload.decode("latin-1")
    assert "legacy secret" not in payload.decode("latin-1")
