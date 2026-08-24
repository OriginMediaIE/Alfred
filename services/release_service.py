"""Local release preflight, restore rehearsal, and real-use soak evidence."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core.atomic_io import atomic_write_json
from services.backup_service import BackupError, BackupService
from services.privacy_service import PrivacyService
from src.restore_bootstrap import apply_pending_restore


class ReleaseService:
    def __init__(self, data_dir):
        self.root = Path(data_dir).resolve()
        self.evidence_dir = self.root / "release-evidence"
        self.soak_path = self.evidence_dir / "privateos-soak.json"

    def preflight(self, owner: str | None = None) -> dict:
        checks = []
        failures = []
        if not self.root.is_dir() or not os.access(self.root, os.W_OK):
            failures.append("Data directory is not writable")
        for database in sorted(self.root.glob("*.db")):
            try:
                with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
                    result = connection.execute("PRAGMA integrity_check").fetchone()
                ok = bool(result and result[0] == "ok")
            except sqlite3.Error:
                ok = False
            checks.append({"name": f"database:{database.name}", "passed": ok})
            if not ok:
                failures.append(f"Database integrity failed: {database.name}")
        for name in (".app_key", "auth.json"):
            path = self.root / name
            if not path.exists():
                continue
            secure = path.stat().st_mode & 0o077 == 0
            checks.append({"name": f"permissions:{name}", "passed": secure})
            if not secure:
                failures.append(f"Private file permissions are too broad: {name}")
        privacy = PrivacyService(self.root / "privacy.json").get(owner)
        privacy_ok = privacy["telemetry_enabled"] is False and privacy["model_logging_enabled"] is False
        checks.append({"name": "privacy-defaults", "passed": privacy_ok})
        if not privacy_ok:
            failures.append("Telemetry or model logging is enabled")
        pending = (self.root / "pending_restore.json").exists()
        checks.append({"name": "no-pending-restore", "passed": not pending})
        if pending:
            failures.append("A restore is pending restart")
        return {"passed": not failures, "checks": checks, "failures": failures}

    def rehearse_restore(self) -> dict:
        if not (self.root / ".app_key").is_file():
            raise BackupError("Fresh-install rehearsal requires the current instance key")
        passphrase = secrets.token_urlsafe(32)
        payload, manifest = BackupService(self.root).create(passphrase=passphrase)
        with tempfile.TemporaryDirectory(prefix="alfred-privateos-restore-") as temp:
            target = Path(temp)
            target_service = BackupService(target)
            preview = target_service.preflight(payload, passphrase=passphrase)
            staged = target_service.stage_restore(payload, passphrase=passphrase)
            applied = apply_pending_restore(target)
            verified = target_service.verify_restored_tree(manifest)
        return {
            "passed": True,
            "fresh_install_portable": preview["fresh_install_portable"],
            "database_count": len(preview["database_checks"]),
            "file_count": verified["file_count"],
            "restore_id": staged["restore_id"],
            "rollback_created": applied["rollback_available"],
        }

    def _read_soak(self) -> dict:
        try:
            data = json.loads(self.soak_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def record_soak_day(self, owner: str | None, *, day: date | None = None, note: str = "") -> dict:
        observed = day or datetime.now(timezone.utc).date()
        data = self._read_soak()
        entries = [item for item in data.get("entries", []) if item.get("date") != observed.isoformat()]
        entries.append({
            "date": observed.isoformat(),
            "owner": str(owner or "__local__"),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "note": str(note or "")[:500],
        })
        entries.sort(key=lambda item: item["date"])
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(str(self.soak_path), {"schema": "privateos-soak-v1", "entries": entries}, indent=2)
        return self.soak_status()

    def soak_status(self) -> dict:
        valid = []
        for item in self._read_soak().get("entries", []):
            try:
                valid.append(date.fromisoformat(str(item["date"])))
            except (KeyError, TypeError, ValueError):
                continue
        days = sorted(set(valid))
        longest = current = 0
        previous = None
        for observed in days:
            current = current + 1 if previous and observed == previous + timedelta(days=1) else 1
            longest = max(longest, current)
            previous = observed
        return {
            "recorded_days": len(days),
            "longest_consecutive_days": longest,
            "required_consecutive_days": 7,
            "acceptance_met": longest >= 7,
            "dates": [item.isoformat() for item in days],
        }
