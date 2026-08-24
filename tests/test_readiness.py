"""Tests for the readiness / integrity self-check (src/readiness.py)."""

from src.readiness import check_readiness


def test_readiness_reports_core_subsystems():
    result = check_readiness()

    assert {"status", "live", "ready", "version", "checks", "timestamp"}.issubset(result.keys())
    checks = result["checks"]
    for name in ("database", "storage", "permissions", "vector_store"):
        assert name in checks, f"missing check: {name}"

    assert checks["database"]["status"] == "ok", checks["database"]
    assert checks["storage"]["status"] == "ok", checks["storage"]
    assert result["live"] is True
    assert result["status"] in {"ready", "degraded", "failed"}


def test_public_readiness_never_exposes_local_paths_or_exception_text():
    result = check_readiness()
    serialized = str(result).lower()

    assert "traceback" not in serialized
    assert "sqlite:///" not in serialized
    assert "/users/" not in serialized
