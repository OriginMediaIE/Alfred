import httpx
import pytest
from fastapi import HTTPException

import routes.cookbook_routes as cookbook_routes


def _route_endpoint(path: str, method: str):
    router = cookbook_routes.setup_cookbook_routes()
    for route in router.routes:
        if route.path == path and method in route.methods:
            return route.endpoint
    raise AssertionError(f"{method} {path} route not found")


class _Response:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


@pytest.mark.asyncio
async def test_hf_latest_forwards_bounded_search_to_huggingface(monkeypatch):
    requests = []

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, **kwargs):
            requests.append((url, kwargs))
            return _Response([
                {
                    "modelId": "Qwen/Qwen2.5-7B-Instruct",
                    "pipeline_tag": "text-generation",
                    "tags": ["transformers"],
                    "downloads": 12,
                }
            ])

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    endpoint = _route_endpoint("/api/cookbook/hf-latest", "GET")

    result = await endpoint(
        vram_gb=0,
        limit=7,
        pipeline="text-generation",
        search="  qwen instruct  ",
        owner="alice",
    )

    assert [model["repo_id"] for model in result["models"]] == [
        "Qwen/Qwen2.5-7B-Instruct"
    ]
    assert requests == [
        (
            "https://huggingface.co/api/models",
            {
                "params": {
                    "sort": "trendingScore",
                    "direction": -1,
                    "limit": 105,
                    "filter": "text-generation",
                    "search": "qwen instruct",
                }
            },
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 51, True])
async def test_hf_latest_rejects_out_of_bounds_limit_before_http(monkeypatch, limit):
    def forbidden_client(*args, **kwargs):
        raise AssertionError("invalid limit must be rejected before HTTP")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden_client)
    endpoint = _route_endpoint("/api/cookbook/hf-latest", "GET")

    with pytest.raises(HTTPException) as exc:
        await endpoint(limit=limit, search="qwen", owner="alice")

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_hf_latest_rejects_oversized_search_before_http(monkeypatch):
    def forbidden_client(*args, **kwargs):
        raise AssertionError("oversized search must be rejected before HTTP")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden_client)
    endpoint = _route_endpoint("/api/cookbook/hf-latest", "GET")

    with pytest.raises(HTTPException) as exc:
        await endpoint(search="x" * 201, owner="alice")

    assert exc.value.status_code == 422
    assert "at most 200 characters" in str(exc.value.detail)
