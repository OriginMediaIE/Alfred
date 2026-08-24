"""Owner-scoped privacy preferences and provider-routing enforcement."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Iterable

from core.atomic_io import atomic_write_json
from src.constants import DATA_DIR
from src.model_context import is_local_endpoint


DEFAULTS: dict[str, Any] = {
    "local_only_mode": False,
    "provider_routing_visibility": True,
    "conversation_retention_days": None,
    "email_retention_days": None,
    "transcript_retention_days": 365,
    "file_retention_days": None,
    "memory_retention_days": None,
    "model_logging_enabled": False,
    "telemetry_enabled": False,
    "sensitive_data_redaction": True,
    "integration_controls": {},
}
DAY_FIELDS = {
    "conversation_retention_days",
    "email_retention_days",
    "transcript_retention_days",
    "file_retention_days",
    "memory_retention_days",
}
BOOL_FIELDS = {
    "local_only_mode",
    "provider_routing_visibility",
    "model_logging_enabled",
    "telemetry_enabled",
    "sensitive_data_redaction",
}


class PrivacyError(ValueError):
    """A privacy policy is invalid or blocks the requested operation."""


class PrivacyService:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or (Path(DATA_DIR) / "privacy.json"))
        self.lock = threading.RLock()

    @staticmethod
    def _owner_key(owner: str | None) -> str:
        return str(owner or "__local__").strip().lower()

    def _all(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def get(self, owner: str | None) -> dict[str, Any]:
        stored = self._all().get(self._owner_key(owner), {})
        if not isinstance(stored, dict):
            stored = {}
        return {
            **DEFAULTS,
            **stored,
            "integration_controls": dict(stored.get("integration_controls") or {}),
        }

    def configured_owners(self) -> list[str | None]:
        """Owners with persisted privacy preferences (``None`` is local mode)."""
        owners = []
        for key in self._all():
            owners.append(None if key == "__local__" else key)
        return owners

    def update(self, owner: str | None, changes: dict[str, Any]) -> dict[str, Any]:
        unknown = set(changes) - set(DEFAULTS)
        if unknown:
            raise PrivacyError(
                f"Unknown privacy settings: {', '.join(sorted(unknown))}"
            )

        clean: dict[str, Any] = {}
        for key, value in changes.items():
            if key in BOOL_FIELDS:
                if not isinstance(value, bool):
                    raise PrivacyError(f"{key} must be boolean")
            elif key in DAY_FIELDS:
                if value is not None and (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or not 1 <= value <= 36500
                ):
                    raise PrivacyError(f"{key} must be null or 1-36500 days")
            elif key == "integration_controls":
                if not isinstance(value, dict) or len(value) > 200:
                    raise PrivacyError(
                        "integration_controls must be an object with at most 200 entries"
                    )
                normalized: dict[str, bool] = {}
                for integration_id, enabled in value.items():
                    integration_id = str(integration_id).strip()[:120]
                    if not integration_id or not isinstance(enabled, bool):
                        raise PrivacyError(
                            "integration_controls values must be booleans with non-empty IDs"
                        )
                    normalized[integration_id] = enabled
                value = normalized
            clean[key] = value

        with self.lock:
            data = self._all()
            key = self._owner_key(owner)
            data[key] = {**self.get(owner), **clean}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(str(self.path), data, indent=2)
        return data[key]

    def route_candidates(
        self, owner: str | None, candidates: Iterable[tuple]
    ) -> list[tuple]:
        values = list(candidates or [])
        if not self.get(owner)["local_only_mode"]:
            return values
        return [
            item
            for item in values
            if item and item[0] and is_local_endpoint(str(item[0]))
        ]

    def ensure_local_endpoint(
        self, owner: str | None, endpoint_url: str, *, purpose: str = "AI request"
    ) -> None:
        """Fail closed when an owner enabled local-only mode."""
        if self.get(owner)["local_only_mode"] and not is_local_endpoint(
            str(endpoint_url or "")
        ):
            raise PrivacyError(
                f"Local-only mode blocks this remote {purpose.lower()}. "
                "Select a local model endpoint or disable local-only mode."
            )

    def integration_enabled(self, owner: str | None, integration_id: str) -> bool:
        """Return the owner's explicit connector choice; unspecified means enabled."""
        controls = self.get(owner).get("integration_controls") or {}
        return controls.get(str(integration_id), True) is not False

    def require_integration(self, owner: str | None, integration_id: str) -> None:
        if not self.integration_enabled(owner, integration_id):
            raise PrivacyError(
                f"Integration '{integration_id}' is disabled in Privacy settings."
            )


_service: PrivacyService | None = None


def get_privacy_service() -> PrivacyService:
    global _service
    if _service is None:
        _service = PrivacyService()
    return _service
