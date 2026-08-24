"""Contract tests for the offline faster-whisper adapter."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.local_transcription import FasterWhisperTranscriptionProvider
from src.meeting_contract import (
    TranscriptionCancelled,
    TranscriptionCapabilityError,
    TranscriptionConfig,
    TranscriptionUnavailable,
)


class _Model:
    def transcribe(self, path, **kwargs):
        word = SimpleNamespace(word=" hello", start=0.1, end=0.4, probability=0.91)
        segments = [
            SimpleNamespace(text=" Hello there ", start=0.1, end=1.2, words=[word])
        ]
        return iter(segments), SimpleNamespace(language="en", duration=1.2)


def test_adapter_loads_local_only_and_preserves_word_timestamps(tmp_path):
    calls = []

    def loader(model, **kwargs):
        calls.append((model, kwargs))
        return _Model()

    media = tmp_path / "meeting.wav"
    media.write_bytes(b"audio")
    provider = FasterWhisperTranscriptionProvider(model_loader=loader)
    progress = []
    result = provider.transcribe(
        media,
        TranscriptionConfig(model="base", timestamp_granularity="word"),
        cancel_requested=lambda: False,
        progress=progress.append,
    )

    assert calls[0][0] == "base"
    assert calls[0][1]["local_files_only"] is True
    assert result.metadata["local_only"] is True
    assert result.segments[0].words[0].start_ms == 100
    assert result.segments[0].words[0].confidence == pytest.approx(0.91)
    assert result.duration_ms == 1200
    assert progress[-1] == 70


def test_model_download_requires_explicit_opt_in(tmp_path):
    captured = {}

    def loader(_model, **kwargs):
        captured.update(kwargs)
        return _Model()

    media = tmp_path / "meeting.wav"
    media.write_bytes(b"audio")
    provider = FasterWhisperTranscriptionProvider(model_loader=loader)
    provider.transcribe(
        media,
        TranscriptionConfig(allow_model_download=True),
        cancel_requested=lambda: False,
        progress=lambda _value: None,
    )
    assert captured["local_files_only"] is False


def test_diarization_fails_clearly_when_not_configured(tmp_path):
    media = tmp_path / "meeting.wav"
    media.write_bytes(b"audio")
    provider = FasterWhisperTranscriptionProvider(model_loader=lambda *_a, **_k: _Model())
    with pytest.raises(TranscriptionCapabilityError, match="diarization"):
        provider.transcribe(
            media,
            TranscriptionConfig(diarization=True),
            cancel_requested=lambda: False,
            progress=lambda _value: None,
        )


def test_cancellation_and_missing_media_fail_without_model_load(tmp_path):
    loaded = []
    provider = FasterWhisperTranscriptionProvider(
        model_loader=lambda *_a, **_k: loaded.append(True)
    )
    media = tmp_path / "meeting.wav"
    media.write_bytes(b"audio")
    with pytest.raises(TranscriptionCancelled):
        provider.transcribe(
            media,
            TranscriptionConfig(),
            cancel_requested=lambda: True,
            progress=lambda _value: None,
        )
    with pytest.raises(TranscriptionUnavailable):
        provider.transcribe(
            tmp_path / "missing.wav",
            TranscriptionConfig(),
            cancel_requested=lambda: False,
            progress=lambda _value: None,
        )
    assert loaded == []


def test_health_never_claims_streaming_or_realtime():
    provider = FasterWhisperTranscriptionProvider(model_loader=lambda *_a, **_k: _Model())
    capabilities = provider.capabilities()
    assert capabilities["streaming"] is False
    assert capabilities["stable_realtime"] is False
    assert capabilities["local_only"] is True
