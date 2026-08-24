from pathlib import Path


PAGE=Path(__file__).resolve().parents[1]/"static"/"companion.html"


def test_mobile_companion_has_core_privateos_views_and_session_only_token_storage():
    page=PAGE.read_text(encoding="utf-8")
    assert 'data-view="today"' in page
    assert 'data-view="approvals"' in page
    assert 'data-view="notifications"' in page
    assert 'data-view="chat"' in page
    assert "sessionStorage" in page
    assert "localStorage" not in page
    assert "Authorization:`Bearer ${state.token}`" in page


def test_mobile_companion_escapes_dynamic_content_and_uses_safe_area_insets():
    page=PAGE.read_text(encoding="utf-8")
    assert "const esc=" in page
    assert "env(safe-area-inset-bottom)" in page
    assert '<meta name="viewport"' in page
