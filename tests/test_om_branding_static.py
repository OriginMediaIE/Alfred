import json
import re
from pathlib import Path

from PIL import Image

from scripts.generate_brand_assets import _render


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


def test_primary_pages_use_om_brand_and_central_projection():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    login = (STATIC / "login.html").read_text(encoding="utf-8")

    for page in (index, login):
        assert '{{BRAND_CONFIG}}' in page
        assert 'id="om-brand-config"' in page
        assert "/static/brand/om-mark.svg" in page
        assert "Odysseus Chat" not in page
        assert "Message Odysseus" not in page
        assert "logo-boat" not in page
    assert 'data-brand-text="product_name"' in index
    assert 'data-brand-text="positioning"' in login
    assert 'href="/static/legal.html"' in index
    assert 'href="/static/legal.html"' in login
    assert "fav.dataset.routeIcon = 'true'" in index
    assert "!favicon.dataset.routeIcon" in (STATIC / "js" / "brand.js").read_text(encoding="utf-8")


def test_manifest_and_service_worker_use_new_install_identity():
    manifest = json.loads((STATIC / "manifest.json").read_text(encoding="utf-8"))
    worker = (STATIC / "sw.js").read_text(encoding="utf-8")

    assert manifest["name"] == "OM Automate"
    assert manifest["short_name"] == "OM"
    assert manifest["description"] == "Your private AI operating system"
    assert all("/static/brand/om-" in icon["src"] for icon in manifest["icons"])
    assert "const CACHE_NAME = 'om-automate-v" in worker
    assert "caches.keys()" in worker and "caches.delete" in worker
    assert "'/static/js/brand.js'" in worker


def test_generated_brand_assets_are_present_and_correct_size():
    expected = {
        "om-icon-192.png": (192, 192),
        "om-icon-512.png": (512, 512),
        "om-icon-maskable-512.png": (512, 512),
    }
    for filename, size in expected.items():
        with Image.open(STATIC / "brand" / filename) as image:
            assert image.size == size
            assert image.mode == "RGBA"
    assert (STATIC / "icon.ico").read_bytes().startswith(b"\x00\x00\x01\x00")


def test_raster_brand_assets_match_the_deterministic_source_generator():
    for filename, size, maskable in (
        ("om-icon-192.png", 192, False),
        ("om-icon-512.png", 512, False),
        ("om-icon-maskable-512.png", 512, True),
    ):
        with Image.open(STATIC / "brand" / filename) as shipped:
            assert shipped.convert("RGBA").tobytes() == _render(size, maskable=maskable).tobytes()

    # Old URLs remain as pixel-identical aliases so existing PWA/bookmark
    # references upgrade without showing the retired sailboat.
    for old_name, canonical_name in (
        ("icon-192.png", "om-icon-192.png"),
        ("icon-512.png", "om-icon-512.png"),
        ("icon-maskable-512.png", "om-icon-maskable-512.png"),
    ):
        with Image.open(STATIC / "icons" / old_name) as old, Image.open(STATIC / "brand" / canonical_name) as canonical:
            assert old.convert("RGBA").tobytes() == canonical.convert("RGBA").tobytes()


def test_greek_default_persona_and_hidden_quote_command_are_removed():
    presets = (STATIC / "js" / "presets.js").read_text(encoding="utf-8")
    commands = (STATIC / "js" / "slashCommands.js").read_text(encoding="utf-8")
    calendar = (STATIC / "js" / "calendar.js").read_text(encoding="utf-8")
    research = (STATIC / "js" / "research" / "panel.js").read_text(encoding="utf-8")

    visible_corpus = "\n".join((commands, calendar, research))
    assert not re.search(r"\b(?:Ithaca|Odyssey|Homer|Penelope|Telemachus)\b", visible_corpus, re.I)
    assert "king of Ithaca" not in presets
    assert "default_persona" in presets
    assert "_cmdOdyssey" not in commands


def test_legal_source_attribution_remains_accessible():
    legal = (STATIC / "legal.html").read_text(encoding="utf-8")
    assert "modified version of the Odysseus software" in legal
    assert "GNU Affero General Public License" in legal
    assert "9844a2f9a1996b8c8135a9e7bbde6a72f41df5ed" in legal
    assert "ACKNOWLEDGMENTS.md" in legal


def test_public_documentation_uses_the_new_identity_without_mythic_marketing():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    setup = (ROOT / "docs" / "setup.md").read_text(encoding="utf-8")
    landing = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert "static/brand/om-wordmark" in readme
    assert "./install-om-automate.sh" in readme
    assert "./install-om-automate.sh --check" in setup
    assert "../static/brand/om-mark.svg" in landing
    assert "../static/js/brand.js" in landing
    assert "Your private AI operating system" in landing
    assert not re.search(r"\b(?:Ithaca|Odyssey|Homer|Penelope|Telemachus|Cyclopes)\b", landing, re.I)


def test_agent_integration_skills_rebrand_copy_but_keep_published_ids():
    for relative in (
        "integrations/codex/skills/odysseus/SKILL.md",
        "integrations/claude/skills/odysseus/SKILL.md",
    ):
        skill = (ROOT / relative).read_text(encoding="utf-8")
        assert "name: odysseus" in skill
        assert "ODYSSEUS_URL" in skill and "ODYSSEUS_API_TOKEN" in skill
        assert "# OM Automate" in skill
        assert "Odysseus" not in skill
