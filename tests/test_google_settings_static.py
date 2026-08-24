"""Static contract for the owner-facing Google Workspace settings surface."""

from pathlib import Path


SETTINGS_JS = (
    Path(__file__).resolve().parents[1] / "static" / "js" / "settings.js"
).read_text(encoding="utf-8")
EMAIL_ROUTES = (
    Path(__file__).resolve().parents[1] / "routes" / "email_routes.py"
).read_text(encoding="utf-8")


def test_google_workspace_is_a_first_class_integration_type():
    assert "google:  { label: 'Google'" in SETTINGS_JS
    assert "['google', 'Google Workspace']" in SETTINGS_JS
    assert "showGoogleForm(editId)" in SETTINGS_JS
    assert "/api/integrations/google/connections" in SETTINGS_JS


def test_google_form_supports_secure_lifecycle_and_preferences():
    for marker in (
        "/api/integrations/google/client",
        "/api/integrations/google/oauth/authorize",
        "Access requested",
        "Disconnect & revoke",
        "background_sync_enabled",
        "gmail_label_preferences",
        "default_send_behavior",
        "selected_calendars",
        "last_validated_at",
    ):
        assert marker in SETTINGS_JS

    assert "Credentials stay encrypted on this device" in SETTINGS_JS
    assert "type=\"password\"" in SETTINGS_JS
    assert "client.client_secret" not in SETTINGS_JS
    assert "connection.access_token" not in SETTINGS_JS
    assert "connection.refresh_token" not in SETTINGS_JS


def test_new_and_legacy_google_redirect_results_open_integrations():
    assert "sp.get('google_oauth')" in SETTINGS_JS
    assert "sp.has('email_oauth_success')" in SETTINGS_JS
    assert "window.settingsModule.open('integrations')" in SETTINGS_JS


def test_legacy_email_oauth_is_an_inert_migration_shim():
    assert "legacy_email_oauth_retired" in EMAIL_ROUTES
    assert "use_google_workspace" in EMAIL_ROUTES
    assert "https://mail.google.com/" not in EMAIL_ROUTES
    retired = EMAIL_ROUTES.split("# ── Retired legacy Google IMAP/SMTP OAuth routes", 1)[1]
    assert "oauth2.googleapis.com/token" not in retired
    assert "httpx.post" not in retired
    assert "/api/email/oauth/google/authorize" not in SETTINGS_JS
