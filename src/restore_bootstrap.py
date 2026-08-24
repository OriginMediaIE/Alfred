"""Apply or stage restart-safe restores before database engines are opened."""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _within(path: Path, root: Path) -> bool:
    return os.path.commonpath([str(path.resolve()), str(root.resolve())]) == str(root.resolve())


def _safe_restore_id(value) -> str:
    restore_id = str(value or "")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,100}", restore_id):
        raise RuntimeError("Restore identifier is invalid")
    return restore_id


def apply_pending_restore(data_dir):
    root = Path(data_dir).resolve()
    marker_path = root / "pending_restore.json"
    if not marker_path.is_file():
        return None
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    stage = Path(marker.get("stage", "")).resolve()
    expected = (root / "restore_staging").resolve()
    if not stage.is_dir() or not _within(stage, expected):
        raise RuntimeError("Pending restore staging path is invalid")
    restore_id = _safe_restore_id(marker.get("restore_id"))
    rollback = root / "restore_rollback" / restore_id
    rollback.mkdir(parents=True, exist_ok=True)
    applied = []
    prior_files = []
    created_files = []
    deleted_files = []
    try:
        for source in sorted(stage.rglob("*")):
            if not source.is_file() or source.is_symlink():
                continue
            rel = source.relative_to(stage)
            target = (root / rel).resolve()
            if not _within(target, root):
                raise RuntimeError("Pending restore target escaped data directory")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                prior = rollback / rel
                prior.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, prior)
                prior_files.append(rel.as_posix())
            else:
                created_files.append(rel.as_posix())
            temporary = target.with_name(f".{target.name}.restore-{uuid.uuid4().hex}.tmp")
            shutil.copy2(source, temporary)
            os.replace(temporary, target)
            applied.append(rel.as_posix())
        for raw in marker.get("delete_paths") or []:
            target = (root / str(raw)).resolve()
            if not _within(target, root):
                raise RuntimeError("Pending restore deletion escaped data directory")
            if target.is_file() and not target.is_symlink():
                prior = rollback / str(raw)
                prior.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, prior)
                target.unlink()
                prior_files.append(str(raw))
                deleted_files.append(str(raw))
    except Exception:
        for rel in reversed(applied):
            target = root / rel
            prior = rollback / rel
            if prior.is_file():
                shutil.copy2(prior, target)
            elif rel in created_files:
                target.unlink(missing_ok=True)
        for rel in reversed(deleted_files):
            prior = rollback / rel
            target = root / rel
            if prior.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(prior, target)
        raise
    completed = root / "restore_rollback" / f"{restore_id}.completed.json"
    completed.write_text(json.dumps({**marker, "applied_at": datetime.now(timezone.utc).isoformat(), "files": applied, "prior_files": prior_files, "created_files": created_files}, indent=2), encoding="utf-8")
    marker_path.unlink()
    shutil.rmtree(stage)
    return {"restore_id": restore_id, "files": len(applied), "rollback": str(rollback), "rollback_available": True}


def stage_restore_rollback(data_dir, restore_id: str):
    root = Path(data_dir).resolve()
    restore_id = _safe_restore_id(restore_id)
    completed = root / "restore_rollback" / f"{restore_id}.completed.json"
    prior = root / "restore_rollback" / str(restore_id)
    if not completed.is_file() or not prior.is_dir():
        raise RuntimeError("Completed restore rollback was not found")
    evidence = json.loads(completed.read_text(encoding="utf-8"))
    rollback_id = f"rollback-{restore_id}-{uuid.uuid4().hex[:8]}"
    stage = root / "restore_staging" / rollback_id
    shutil.copytree(prior, stage)
    marker = {"restore_id": rollback_id, "rollback_of": restore_id, "stage": str(stage), "created_at": datetime.now(timezone.utc).isoformat(), "file_count": len(evidence.get("prior_files") or []), "delete_paths": list(evidence.get("created_files") or [])}
    from core.atomic_io import atomic_write_json
    atomic_write_json(str(root / "pending_restore.json"), marker, indent=2)
    return {**marker, "status": "rollback_staged_restart_required"}
