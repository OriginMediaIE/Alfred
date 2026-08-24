from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.middleware import CookieCSRFMiddleware


def _client():
    app = FastAPI()
    app.add_middleware(CookieCSRFMiddleware)

    @app.post("/mutate")
    def mutate():
        return {"ok": True}

    return TestClient(app)


def test_cookie_authenticated_cross_site_mutation_is_rejected():
    client = _client()
    response = client.post(
        "/mutate",
        cookies={"odysseus_session": "ambient-cookie"},
        headers={"Origin": "https://attacker.example", "Sec-Fetch-Site": "cross-site"},
    )
    assert response.status_code == 403


def test_same_origin_cookie_mutation_is_allowed():
    client = _client()
    response = client.post(
        "/mutate",
        cookies={"odysseus_session": "ambient-cookie"},
        headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
    )
    assert response.status_code == 200


def test_signed_or_bearer_style_request_without_cookie_is_not_csrf_gated():
    client = _client()
    response = client.post(
        "/mutate",
        headers={"Origin": "https://external-automation.example", "Sec-Fetch-Site": "cross-site"},
    )
    assert response.status_code == 200
