import json
from pathlib import Path

import bcrypt

import setup as om_setup


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def test_admin_admin_is_rejected_without_internal_test_flag(tmp_path, monkeypatch):
    auth_file = tmp_path / "auth.json"
    monkeypatch.setattr(om_setup, "AUTH_FILE", str(auth_file))
    monkeypatch.setenv("ODYSSEUS_ADMIN_USER", "Admin")
    monkeypatch.setenv("ODYSSEUS_ADMIN_PASSWORD", "Admin")
    monkeypatch.delenv("OM_AUTOMATE_INTERNAL_TEST_DEFAULTS", raising=False)

    assert om_setup.create_default_admin() == "failed"
    assert not auth_file.exists()


def test_admin_admin_is_seeded_only_for_internal_first_run(tmp_path, monkeypatch):
    auth_file = tmp_path / "auth.json"
    monkeypatch.setattr(om_setup, "AUTH_FILE", str(auth_file))
    monkeypatch.setenv("ODYSSEUS_ADMIN_USER", "Admin")
    monkeypatch.setenv("ODYSSEUS_ADMIN_PASSWORD", "Admin")
    monkeypatch.setenv("OM_AUTOMATE_INTERNAL_TEST_DEFAULTS", "1")

    assert om_setup.create_default_admin() == "created"
    data = json.loads(auth_file.read_text(encoding="utf-8"))
    assert set(data["users"]) == {"admin"}
    assert bcrypt.checkpw(b"Admin", data["users"]["admin"]["password_hash"].encode())

    original = auth_file.read_bytes()
    assert om_setup.create_default_admin() == "exists"
    assert auth_file.read_bytes() == original


def test_internal_onboarding_frontend_contract():
    login = _read("static/login.html")
    app = _read("static/app.js")
    onboarding = _read("static/js/localLlmOnboarding.js")
    cookbook = _read("static/js/cookbookRunning.js")
    slash = _read("static/js/slashCommands.js")
    index = _read("static/index.html")
    chat = _read("static/js/chat.js")

    assert "/cookbook?onboarding=local-llm" in login
    assert "initLocalLlmOnboarding()" in app
    assert "onboarding_local_llm_started" in onboarding
    assert "onboarding_local_llm_completed" in onboarding
    assert "cookbook:model-serve-registered" in cookbook
    assert "data.endpoint_id" in cookbook
    assert "'tour-local-llm'" in slash
    assert 'class="input-icon-btn web-access-toggle"' in index
    assert 'aria-pressed="false"' in index
    assert "allow_web_search" in chat
    assert "#new-memory-input" in onboarding
    assert "#new-skill-title" in onboarding
    assert "#memory-enabled-header-toggle" in onboarding
    assert "#auto-memory-toggle" in onboarding


def test_internal_installer_payload_contract():
    builder = _read("scripts/build-internal-macos-test-installer.sh")
    installer = _read("scripts/install-internal-macos-test.command")
    native_builder = _read("build-macos-app.sh")
    native_source = _read("native/macos/OMAutomateApp.m")

    for excluded in ("'.git/'", "'/data/'", "'/logs/'", "'/venv/'", "'/tests/'", "'/tmp_pytest_probe/'", "'/dist/'"):
        assert excluded in builder
    assert 'OUTPUT_DMG="$DIST_DIR/OM Automate Internal Test.dmg"' in builder
    assert 'OM_INSTALL_DIRECTORY="$INSTALL_LOCATION"' in builder
    assert "OM_AUTOMATE_INTERNAL_TEST_DEFAULTS=1" in installer
    assert "ODYSSEUS_ADMIN_USER=Admin" in installer
    assert "ODYSSEUS_ADMIN_PASSWORD=Admin" in installer
    assert 'INSTALL_DIR="$INSTALL_ROOT/app"' in installer
    assert 'TARGET_APP="$HOME/Applications/OM Automate.app"' in installer
    assert "OM_INSTALL_DIRECTORY" in native_builder
    assert "stringByExpandingTildeInPath" in native_source
