"""Validated, non-sensitive OM Automate brand configuration.

``static/manifest.json`` is deliberately both the installable PWA manifest and
the single source of truth for product copy.  Server-rendered pages receive the
validated ``om_automate`` projection; browser code never reads environment
variables, compatibility identifiers, or secrets through this module.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.constants import STATIC_DIR


class _FrozenBrandModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BrandAssets(_FrozenBrandModel):
    logo_light: str = Field(min_length=1)
    logo_dark: str = Field(min_length=1)
    icon: str = Field(min_length=1)
    icon_maskable: str = Field(min_length=1)
    favicon: str = Field(min_length=1)
    apple_touch_icon: str = Field(min_length=1)
    alt_text: str = Field(min_length=1)


class BrandTitles(_FrozenBrandModel):
    default: str = Field(min_length=1)
    login: str = Field(min_length=1)
    legal: str = Field(min_length=1)
    routes: Dict[str, str]


class BrandLinks(_FrozenBrandModel):
    support: str = Field(min_length=1)
    documentation: str = Field(min_length=1)
    source: str = Field(pattern=r"^https://")
    legal: str = Field(min_length=1)


class BrandCopy(_FrozenBrandModel):
    welcome: str = Field(min_length=1)
    empty_state: str = Field(min_length=1)
    message_placeholder: str = Field(min_length=1)
    default_persona: str = Field(min_length=1)


class BrandConfig(_FrozenBrandModel):
    schema_version: int = Field(ge=1)
    product_name: str = Field(min_length=1)
    assistant_name: str = Field(min_length=1)
    positioning: str = Field(min_length=1)
    assets: BrandAssets
    titles: BrandTitles
    navigation: Dict[str, str]
    links: BrandLinks
    copy_text: BrandCopy = Field(alias="copy", serialization_alias="copy")
    native_labels: Dict[str, str]
    theme: Dict[str, str]

    @model_validator(mode="after")
    def validate_complete_public_contract(self) -> "BrandConfig":
        required_navigation = {
            "home", "chat", "calendar", "inbox", "tasks", "projects",
            "meetings", "knowledge", "documents", "contacts", "automations",
            "integrations", "activity", "approvals", "settings",
        }
        missing_navigation = required_navigation.difference(self.navigation)
        if missing_navigation:
            raise ValueError(f"missing navigation labels: {sorted(missing_navigation)}")
        required_theme = {"background", "surface", "foreground", "accent", "signal", "success", "danger"}
        missing_theme = required_theme.difference(self.theme)
        if missing_theme:
            raise ValueError(f"missing theme tokens: {sorted(missing_theme)}")
        return self


def load_brand_config(path: str | Path | None = None) -> BrandConfig:
    """Load and validate the public brand projection from the PWA manifest."""
    manifest_path = Path(path) if path is not None else Path(STATIC_DIR) / "manifest.json"
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    config = BrandConfig.model_validate(manifest.get("om_automate"))
    if manifest.get("name") != config.product_name:
        raise ValueError("PWA name must match central product_name")
    if manifest.get("description") != config.positioning:
        raise ValueError("PWA description must match central positioning")
    return config


@lru_cache(maxsize=1)
def get_brand_config() -> BrandConfig:
    return load_brand_config()


def public_brand_json() -> str:
    """Return script-safe JSON for the server-owned HTML projection."""
    payload = get_brand_config().model_dump(mode="json", by_alias=True)
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
