"""Private model reasoning must not cross the chat HTTP boundary."""

import json
from pathlib import Path

from routes.chat_routes import _PrivateReasoningFilter, _safe_reasoning_status_event


def test_flagged_reasoning_is_suppressed_without_retaining_raw_text():
    guard = _PrivateReasoningFilter()

    assert guard.feed("secret scratchpad", flagged=True) == ""
    assert guard.feed("Visible answer") == "Visible answer"
    assert guard.saw_reasoning is True
    assert "secret scratchpad" not in vars(guard).values()


def test_think_blocks_are_removed_across_chunk_boundaries():
    guard = _PrivateReasoningFilter()

    pieces = ["Before <thi", "nk>private", " reasoning</th", "ink> after"]
    visible = "".join(guard.feed(piece) for piece in pieces) + guard.finish()

    assert visible == "Before  after"
    assert guard.saw_reasoning is True
    assert "private" not in visible


def test_non_reasoning_angle_brackets_remain_visible():
    guard = _PrivateReasoningFilter()

    visible = guard.feed("Use x < y and <em>text</em>.") + guard.finish()

    assert visible == "Use x < y and <em>text</em>."
    assert guard.saw_reasoning is False


def test_reasoning_status_event_has_no_reasoning_content():
    event = _safe_reasoning_status_event()
    payload = json.loads(event.removeprefix("data: ").strip())

    assert payload == {"type": "reasoning_status", "data": {"status": "active"}}
    assert "delta" not in payload


def test_legacy_reasoning_metadata_is_never_reconstructed_into_dom():
    source = (Path(__file__).resolve().parents[1] / "static/js/chatRenderer.js").read_text()

    assert "metadata?.thinking" not in source
    assert "metadata.thinking + '</think>" not in source
