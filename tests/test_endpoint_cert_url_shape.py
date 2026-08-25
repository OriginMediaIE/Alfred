"""Regression: tool certification (ModelEndpoint.supports_tools) must be found
even when the chat session's endpoint_url uses a different API path shape than
the stored endpoint row. One Ollama daemon is reachable as both
`http://host:11434/api` (native) and `http://host:11434/v1/chat/completions`
(OpenAI-compat); sessions store whichever shape they were created with. Before
the host-level fallback in stream_agent_loop's lookup, a certified `/api` row
was invisible to a `/v1`-shaped session URL, silently stripping every tool.
"""

import asyncio
import json

import src.agent_loop as al
import core.database as cdb


def _collect(gen):
    async def _run():
        return [c async for c in gen]
    return asyncio.run(_run())


class _FakeEndpoint:
    def __init__(self, base_url, supports_tools):
        self.base_url = base_url
        self.supports_tools = supports_tools


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *a, **k):
        # Exact-match branch: simulate "no exact base_url hit" so the test
        # exercises the host-level fallback (.all()).
        return _FakeQuery([])

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *a, **k):
        return _FakeQuery(self._rows)

    def close(self):
        pass


def _patch_common(monkeypatch, rows):
    monkeypatch.setattr(al, "get_setting", lambda key, default=None: default, raising=False)
    monkeypatch.setattr(al, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(al, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(cdb, "SessionLocal", lambda: _FakeSession(rows), raising=False)

    executed = []

    async def _fake_exec(block, *a, **k):
        executed.append(block)
        return ("bash", {"output": "ok", "exit_code": 0})
    monkeypatch.setattr(al, "execute_tool_block", _fake_exec, raising=False)
    return executed


def _run_loop(monkeypatch, url):
    calls = {"n": 0}

    async def _fake_stream(_candidates, messages, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            payload = {"type": "tool_calls", "calls": [
                {"name": "bash", "arguments": json.dumps({"command": "echo hi"})}
            ]}
            yield f"data: {json.dumps(payload)}\n\n"
        else:
            yield f"data: {json.dumps({'delta': 'done'})}\n\n"
        yield "data: [DONE]\n\n"
    monkeypatch.setattr(al, "stream_llm_with_fallback", _fake_stream, raising=False)

    gen = al.stream_agent_loop(
        url, "qwen3:1.7b",
        [{"role": "user", "content": "run echo hi"}],
        max_rounds=3,
        relevant_tools={"bash"},
    )
    _collect(gen)


def test_v1_session_url_finds_api_shaped_certified_row(monkeypatch):
    rows = [_FakeEndpoint("http://localhost:11434/api", True)]
    executed = _patch_common(monkeypatch, rows)
    _run_loop(monkeypatch, "http://localhost:11434/v1/chat/completions")
    assert executed, "certified /api row must certify the /v1 session URL (same host)"


def test_other_host_row_does_not_certify(monkeypatch):
    rows = [_FakeEndpoint("http://otherhost:11434/api", True)]
    executed = _patch_common(monkeypatch, rows)
    _run_loop(monkeypatch, "http://localhost:11434/v1/chat/completions")
    assert not executed, "a different host's certification must not leak"


def test_same_host_uncertified_row_stays_chat_only(monkeypatch):
    rows = [_FakeEndpoint("http://localhost:11434/api", None)]
    executed = _patch_common(monkeypatch, rows)
    _run_loop(monkeypatch, "http://localhost:11434/v1/chat/completions")
    assert not executed, "host fallback must carry the row's flag, not invent one"
