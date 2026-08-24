"""Validated full-data backup, encrypted envelopes, and restart-safe restore staging."""
from __future__ import annotations
import base64, hashlib, io, json, os, shutil, sqlite3, tempfile, uuid, zipfile
from datetime import datetime, timezone
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from src.constants import DATA_DIR

HEADER=b"OMBACKUP1\n";MAX_BACKUP_BYTES=2*1024*1024*1024
EXCLUDED_NAMES={".app_key","sessions.json","pending_restore.json"}
EXCLUDED_DIRS={"logs","backups","restore_staging","restore_rollback","__pycache__"}
class BackupError(RuntimeError):pass
def _derive(passphrase,salt):return base64.urlsafe_b64encode(PBKDF2HMAC(algorithm=hashes.SHA256(),length=32,salt=salt,iterations=600_000).derive(passphrase.encode()))
def _file_sha256(path):
    digest=hashlib.sha256()
    with open(path,"rb") as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b""):digest.update(chunk)
    return digest.hexdigest()

def _sanitize_database_snapshot(path):
    """Remove legacy private reasoning and incognito residue from a DB copy."""
    from src.research_utils import strip_thinking

    with sqlite3.connect(str(path)) as connection:
        tables={row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        message_columns={row[1] for row in connection.execute("PRAGMA table_info(chat_messages)")} if "chat_messages" in tables else set()
        if {"id","content","metadata"} <= message_columns:
            rows=connection.execute("SELECT id,content,metadata FROM chat_messages").fetchall()
            for message_id,content,metadata in rows:
                clean_content=strip_thinking(str(content or "")).strip()
                clean_content=clean_content or "Model reasoning ended without a visible answer."
                clean_metadata=metadata
                if metadata:
                    try:
                        parsed=json.loads(metadata)
                    except (TypeError,ValueError,json.JSONDecodeError):
                        parsed=None
                    if isinstance(parsed,dict):
                        for key in ("thinking","reasoning","reasoning_content","chain_of_thought"):
                            parsed.pop(key,None)
                        clean_metadata=json.dumps(parsed,ensure_ascii=False,separators=(",",":"))
                if clean_content!=content or clean_metadata!=metadata:
                    connection.execute(
                        "UPDATE chat_messages SET content=?,metadata=? WHERE id=?",
                        (clean_content,clean_metadata,message_id),
                    )
        session_columns={row[1] for row in connection.execute("PRAGMA table_info(sessions)")} if "sessions" in tables else set()
        if {"id","name"} <= session_columns:
            ephemeral=[row[0] for row in connection.execute(
                "SELECT id FROM sessions WHERE name IN ('Nobody','Incognito')"
            ).fetchall()]
            if ephemeral:
                placeholders=",".join("?" for _ in ephemeral)
                if "session_id" in message_columns:
                    connection.execute(
                        f"DELETE FROM chat_messages WHERE session_id IN ({placeholders})",
                        ephemeral,
                    )
                connection.execute(
                    f"DELETE FROM sessions WHERE id IN ({placeholders})",
                    ephemeral,
                )
        connection.commit()

class BackupService:
    def __init__(self,data_dir=None):self.root=Path(data_dir or DATA_DIR).resolve();self.root.mkdir(parents=True,exist_ok=True)
    def _files(self, *, include_instance_key=False):
        scheduled_secret = os.getenv("OM_SCHEDULED_BACKUP_PASSPHRASE_FILE")
        scheduled_secret_path = Path(scheduled_secret).expanduser().resolve() if scheduled_secret else None
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.is_symlink():continue
            rel=path.relative_to(self.root)
            is_instance_key = rel.as_posix() == ".app_key"
            if (scheduled_secret_path is not None and path.resolve()==scheduled_secret_path) or (path.name in EXCLUDED_NAMES and not (include_instance_key and is_instance_key)) or path.name.endswith(".om-migrate.lock") or (path.suffix.lower() in {".key",".pem"} and not (include_instance_key and is_instance_key)) or any(part in EXCLUDED_DIRS for part in rel.parts):continue
            if path.name.endswith(("-wal","-shm")):continue
            yield path,rel
    def create(self,*,passphrase=None):
        include_instance_key=bool(passphrase)
        manifest={"schema":"om-automate-backup-v2" if passphrase else "om-automate-backup-v1","created_at":datetime.now(timezone.utc).isoformat(),"encrypted":bool(passphrase),"key_included":False,"restore_requires_existing_instance_key":True,"files":[]}
        out=io.BytesIO();total=0
        with tempfile.TemporaryDirectory(prefix="om-backup-") as temp,zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED,allowZip64=True) as archive:
            for path,rel in self._files(include_instance_key=include_instance_key):
                source=path
                if path.suffix.lower()==".db":
                    snapshot=Path(temp)/path.name
                    try:
                        with sqlite3.connect(str(path)) as src,sqlite3.connect(str(snapshot)) as dst:src.backup(dst)
                        _sanitize_database_snapshot(snapshot)
                        source=snapshot
                    except sqlite3.Error as exc:raise BackupError(f"Could not snapshot database {rel}") from exc
                size=source.stat().st_size;total+=size
                if total>MAX_BACKUP_BYTES:raise BackupError("Backup exceeds the 2 GiB safety limit")
                digest=_file_sha256(source);name=f"data/{rel.as_posix()}";archive.write(source,name);manifest["files"].append({"path":name,"size":size,"sha256":digest})
                if rel.as_posix()==".app_key":manifest["key_included"]=True;manifest["restore_requires_existing_instance_key"]=False
            archive.writestr("manifest.json",json.dumps(manifest,sort_keys=True,indent=2))
        raw=out.getvalue()
        if not passphrase:return raw,manifest
        if len(passphrase)<12:raise BackupError("Backup passphrase must be at least 12 characters")
        salt=os.urandom(16);token=Fernet(_derive(passphrase,salt)).encrypt(raw)
        envelope={"salt":base64.urlsafe_b64encode(salt).decode(),"iterations":600000,"token":token.decode()}
        return HEADER+json.dumps(envelope,separators=(",",":")).encode(),manifest
    def _decrypt(self,payload,passphrase=None):
        if not payload.startswith(HEADER):return payload
        if not passphrase:raise BackupError("This backup is encrypted; provide its passphrase")
        try:
            env=json.loads(payload[len(HEADER):]);salt=base64.urlsafe_b64decode(env["salt"]);return Fernet(_derive(passphrase,salt)).decrypt(env["token"].encode())
        except (ValueError,KeyError,InvalidToken,json.JSONDecodeError) as exc:raise BackupError("Backup passphrase or encrypted envelope is invalid") from exc
    def validate(self,payload,*,passphrase=None):
        raw=self._decrypt(payload,passphrase)
        if len(raw)>MAX_BACKUP_BYTES:raise BackupError("Backup exceeds the 2 GiB safety limit")
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                archive_names=archive.namelist();names=set(archive_names)
                if len(names)!=len(archive_names):raise BackupError("Backup archive contains duplicate entries")
                manifest=json.loads(archive.read("manifest.json"))
                if manifest.get("schema") not in {"om-automate-backup-v1","om-automate-backup-v2"}:raise BackupError("Unsupported backup schema")
                if manifest.get("schema")=="om-automate-backup-v2" and (not manifest.get("encrypted") or not payload.startswith(HEADER)):raise BackupError("Portable backup v2 must be encrypted")
                listed=[];declared_total=0
                for item in manifest.get("files",[]):
                    name=str(item.get("path") or "");parts=Path(name).parts
                    if name not in names or not name.startswith("data/") or ".." in parts or Path(name).is_absolute():raise BackupError("Backup contains an unsafe or missing path")
                    if name in listed:raise BackupError("Backup manifest contains duplicate paths")
                    listed.append(name)
                    declared_size=int(item.get("size",-1));declared_total+=max(0,declared_size)
                    if declared_total>MAX_BACKUP_BYTES:raise BackupError("Backup expands beyond the 2 GiB safety limit")
                    data=archive.read(name)
                    if len(data)!=declared_size or hashlib.sha256(data).hexdigest()!=item.get("sha256"):raise BackupError(f"Backup integrity check failed for {name}")
                if names-set(listed)-{"manifest.json"}:raise BackupError("Backup contains files not declared in its manifest")
                return {**manifest,"validated":True,"file_count":len(manifest.get("files",[])),"archive_bytes":len(raw)}
        except (zipfile.BadZipFile,KeyError,json.JSONDecodeError) as exc:raise BackupError("Backup archive is invalid") from exc
    def preflight(self,payload,*,passphrase=None):
        preview=self.validate(payload,passphrase=passphrase);raw=self._decrypt(payload,passphrase);checks=[]
        with tempfile.TemporaryDirectory(prefix="om-restore-preflight-") as temp,zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for item in preview["files"]:
                if not item["path"].lower().endswith(".db"):continue
                target=Path(temp)/Path(item["path"]).name;target.write_bytes(archive.read(item["path"]))
                try:
                    with sqlite3.connect(f"file:{target}?mode=ro",uri=True) as connection:
                        result=connection.execute("PRAGMA integrity_check").fetchone()
                except sqlite3.Error as exc:raise BackupError(f"Database preflight failed for {item['path']}") from exc
                if not result or result[0]!="ok":raise BackupError(f"Database integrity check failed for {item['path']}")
                checks.append({"path":item["path"],"integrity":"ok"})
        if preview.get("restore_requires_existing_instance_key") and not (self.root/".app_key").is_file():raise BackupError("Backup requires the original instance key, which is not present in this installation")
        return {**preview,"preflight":"passed","database_checks":checks,"fresh_install_portable":bool(preview.get("key_included"))}
    def verify_restored_tree(self,manifest,*,root=None):
        restored_root=Path(root or self.root).resolve();verified=[]
        for item in manifest.get("files",[]):
            rel=Path(str(item.get("path") or "")).relative_to("data");target=(restored_root/rel).resolve()
            if os.path.commonpath([str(target),str(restored_root)])!=str(restored_root) or not target.is_file():raise BackupError(f"Restored file is missing: {rel}")
            if target.stat().st_size!=int(item.get("size",-1)) or _file_sha256(target)!=item.get("sha256"):raise BackupError(f"Restored file verification failed: {rel}")
            verified.append(rel.as_posix())
        return {"verified":True,"file_count":len(verified),"files":verified}
    def stage_restore(self,payload,*,passphrase=None):
        if (self.root/"pending_restore.json").exists():raise BackupError("A restore is already pending; restart before staging another operation")
        preview=self.preflight(payload,passphrase=passphrase);raw=self._decrypt(payload,passphrase);restore_id=uuid.uuid4().hex;stage=self.root/"restore_staging"/restore_id;stage.mkdir(parents=True)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for item in preview["files"]:
                rel=Path(item["path"]).relative_to("data");target=(stage/rel).resolve()
                if os.path.commonpath([str(target),str(stage.resolve())])!=str(stage.resolve()):raise BackupError("Restore path escaped staging")
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(item["path"]))
        marker={"restore_id":restore_id,"stage":str(stage),"created_at":datetime.now(timezone.utc).isoformat(),"file_count":preview["file_count"],"manifest_sha256":hashlib.sha256(raw).hexdigest(),"delete_paths":[]}
        from core.atomic_io import atomic_write_json
        atomic_write_json(str(self.root/"pending_restore.json"),marker,indent=2)
        return {**marker,"status":"staged_restart_required"}
