"""Startup-critical baseline smoke tests for the unmodified upstream app.

These tests intentionally exercise only public, side-effect-free endpoints.  The
full browser smoke procedure is recorded in
``docs/om-automate/baseline-smoke-test.md``.
"""

from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.fixture(scope="module")
def probe(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Import and probe the real composition root in an isolated interpreter.

    The shared test configuration intentionally installs a minimal
    ``src.database`` compatibility stub for lightweight unit tests.  A child
    interpreter avoids contaminating that unit-test environment while still
    exercising the real FastAPI application and middleware.
    """

    data_dir = tmp_path_factory.mktemp("baseline-app-data")
    script = r'''
import json
from starlette.testclient import TestClient
import app

client = TestClient(app.app, raise_server_exceptions=False)
health = client.get("/api/health")
version = client.get("/api/version")
root = client.get("/", follow_redirects=False)
login = client.get("/login")
print(json.dumps({
    "health_status": health.status_code,
    "health": health.json(),
    "version_status": version.status_code,
    "version": version.json(),
    "root_status": root.status_code,
    "root_location": root.headers.get("location"),
    "login_status": login.status_code,
    "login_html": login.text.lower(),
    "paths": [getattr(route, "path", None) for route in app.app.routes],
}))
'''
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": "sqlite:///:memory:",
            "ODYSSEUS_DATA_DIR": str(data_dir),
            "ODYSSEUS_AUTH_ENABLED": "true",
            "ODYSSEUS_STARTUP_WARMUPS": "0",
            "ODYSSEUS_MODEL_KEEPALIVE": "0",
        }
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(completed.stdout)


def test_liveness_endpoint_is_public_and_well_formed(probe: dict) -> None:
    assert probe["health_status"] == 200
    payload = probe["health"]
    assert payload["status"] == "healthy"
    timestamp = datetime.fromisoformat(payload["timestamp"])
    assert timestamp.tzinfo is not None


def test_version_endpoint_returns_a_nonempty_version(probe: dict) -> None:
    assert probe["version_status"] == 200
    version = probe["version"].get("version")
    assert isinstance(version, str)
    assert version.strip()


def test_unauthenticated_root_reaches_login_flow(probe: dict) -> None:
    assert probe["root_status"] == 302
    assert probe["root_location"] == "/login"


def test_login_page_contains_credential_controls(probe: dict) -> None:
    assert probe["login_status"] == 200
    html = probe["login_html"]
    assert "username" in html
    assert "password" in html


def test_readiness_route_is_registered(probe: dict) -> None:
    # Its unauthenticated 401 and limited dependency coverage are recorded
    # defects, so this baseline test deliberately does not freeze that behavior.
    assert "/api/ready" in probe["paths"]
