import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.branding import get_brand_config, load_brand_config, public_brand_json


ROOT = Path(__file__).resolve().parents[1]


def test_central_brand_contract_matches_pwa_manifest():
    manifest = json.loads((ROOT / "static" / "manifest.json").read_text(encoding="utf-8"))
    brand = get_brand_config()

    assert brand.product_name == "OM Automate" == manifest["name"]
    assert brand.assistant_name == "OM" == manifest["short_name"]
    assert brand.positioning == "Your private AI operating system" == manifest["description"]
    assert brand.links.legal == "/static/legal.html"
    assert brand.links.source.startswith("https://github.com/odysseus-dev/odysseus/tree/")
    assert set(brand.navigation) >= {"home", "chat", "calendar", "inbox", "tasks", "projects", "meetings", "knowledge", "documents", "contacts", "automations", "integrations", "activity", "approvals", "settings"}


def test_brand_contract_is_frozen_and_script_safe():
    brand = get_brand_config()
    with pytest.raises(ValidationError):
        brand.product_name = "changed"

    rendered = public_brand_json()
    assert "</script" not in rendered.lower()
    assert json.loads(rendered)["copy"]["default_persona"].startswith("You are OM")


def test_brand_loader_rejects_manifest_drift(tmp_path):
    manifest = json.loads((ROOT / "static" / "manifest.json").read_text(encoding="utf-8"))
    manifest["name"] = "Drifted Product"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="PWA name"):
        load_brand_config(path)
