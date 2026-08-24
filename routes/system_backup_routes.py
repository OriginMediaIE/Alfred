"""Administrative full backup, validation preview, and restart-safe restore staging."""
from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from core.middleware import require_admin
from services.backup_service import BackupError, BackupService
from src.restore_bootstrap import stage_restore_rollback

MAX_UPLOAD=2*1024*1024*1024
async def _read(file):
    out=bytearray()
    while True:
        chunk=await file.read(1024*1024)
        if not chunk:break
        out.extend(chunk)
        if len(out)>MAX_UPLOAD:raise HTTPException(413,"Backup exceeds the 2 GiB safety limit")
    return bytes(out)
def setup_system_backup_routes(service=None):
    backups=service or BackupService();router=APIRouter(prefix="/api/system-backups",tags=["backups"])
    @router.post("/create")
    async def create(request:Request,passphrase:str=Form(default="")):
        require_admin(request)
        if len(passphrase) < 12:
            raise HTTPException(422,"A backup passphrase of at least 12 characters is required")
        try:payload,manifest=backups.create(passphrase=passphrase)
        except BackupError as exc:raise HTTPException(422,str(exc)) from exc
        return Response(payload,media_type="application/octet-stream",headers={"Content-Disposition":'attachment; filename="alfred-privateos-backup.ombak"',"X-OM-Backup-Files":str(len(manifest["files"])),"Cache-Control":"no-store"})
    @router.post("/preview")
    async def preview(request:Request,file:UploadFile=File(...),passphrase:str=Form(default="")):
        require_admin(request)
        try:return backups.preflight(await _read(file),passphrase=passphrase or None)
        except BackupError as exc:raise HTTPException(422,str(exc)) from exc
    @router.post("/stage-restore")
    async def stage(request:Request,file:UploadFile=File(...),confirm:bool=Form(False),passphrase:str=Form(default="")):
        require_admin(request)
        if confirm is not True:raise HTTPException(422,"Explicit restore confirmation is required")
        try:return backups.stage_restore(await _read(file),passphrase=passphrase or None)
        except BackupError as exc:raise HTTPException(422,str(exc)) from exc
    @router.post("/rollback/{restore_id}")
    async def rollback(request:Request,restore_id:str,confirm:bool=Form(False)):
        require_admin(request)
        if confirm is not True:raise HTTPException(422,"Explicit rollback confirmation is required")
        if (backups.root/"pending_restore.json").exists():
            raise HTTPException(409,"A restore is already pending; restart before staging another operation")
        try:return stage_restore_rollback(backups.root,restore_id)
        except RuntimeError as exc:raise HTTPException(422,str(exc)) from exc
    return router
