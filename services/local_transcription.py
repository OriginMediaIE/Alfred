"""Local-first Whisper-compatible meeting transcription adapter.

The adapter lazy-loads ``faster-whisper`` and defaults to offline model lookup.
It never sends media to a remote endpoint.  An optional local diarizer can be
injected; without one, requesting diarization fails clearly instead of
silently pretending that speakers were identified.
"""

from __future__ import annotations

from dataclasses import replace
from importlib import metadata as importlib_metadata
import math
from pathlib import Path
import re
import threading
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence

from src.meeting_contract import (
    TranscriptionCancelled,
    TranscriptionCapabilityError,
    TranscriptionConfig,
    TranscriptionInvalidResult,
    TranscriptionResult,
    TranscriptionSegmentResult,
    TranscriptionUnavailable,
    TranscriptionWord,
)


_MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")


class LocalDiarizationProvider(Protocol):
    name: str
    version: str

    def assign_speakers(
        self,
        media_path: Path,
        segments: Sequence[TranscriptionSegmentResult],
        *,
        cancel_requested: Callable[[], bool],
    ) -> Sequence[TranscriptionSegmentResult]: ...


class FasterWhisperTranscriptionProvider:
    """Whisper-compatible local adapter with bounded, mockable construction."""

    name = "faster-whisper-local"

    def __init__(
        self,
        *,
        model_root: Optional[Path] = None,
        model_loader: Optional[Callable[..., Any]] = None,
        diarizer: Optional[LocalDiarizationProvider] = None,
    ) -> None:
        self.model_root = Path(model_root).expanduser().resolve() if model_root else None
        self._model_loader = model_loader
        self._diarizer = diarizer
        self._models: dict[tuple[str, str, str, bool], Any] = {}
        self._models_lock = threading.RLock()
        try:
            self.version = importlib_metadata.version("faster-whisper")
        except importlib_metadata.PackageNotFoundError:
            self.version = "not-installed"

    def capabilities(self) -> Mapping[str, Any]:
        return {
            "contract_version": "1.0",
            "local_only": True,
            "streaming": False,
            "stable_realtime": False,
            "timestamps": ["segment", "word"],
            "diarization": self._diarizer is not None,
            "devices": ["cpu", "cuda", "auto"],
            "quantizations": [
                "auto",
                "int8",
                "int8_float16",
                "float16",
                "float32",
            ],
        }

    def health(self) -> Mapping[str, Any]:
        installed = self._model_loader is not None or self.version != "not-installed"
        return {
            "status": "available" if installed else "unavailable",
            "provider": self.name,
            "version": self.version,
            "local_only": True,
            "diarization_available": self._diarizer is not None,
            "recommended_repair": (
                None
                if installed
                else "Install the pinned optional faster-whisper dependency and a local model"
            ),
        }

    def _resolve_model(self, configured: str) -> str:
        value = str(configured or "").strip()
        if _MODEL_NAME_RE.fullmatch(value):
            return value
        if self.model_root is None:
            raise TranscriptionCapabilityError(
                "Custom model paths require a configured local model root"
            )
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = self.model_root / candidate
        try:
            resolved = candidate.expanduser().resolve(strict=True)
            resolved.relative_to(self.model_root)
        except (OSError, ValueError) as exc:
            raise TranscriptionCapabilityError(
                "Model path must resolve inside the configured local model root"
            ) from exc
        if not resolved.is_dir():
            raise TranscriptionCapabilityError("Configured model path is not a directory")
        return str(resolved)

    @staticmethod
    def _device(config: TranscriptionConfig) -> str:
        if config.device != "auto":
            return config.device
        try:
            import torch

            if bool(torch.cuda.is_available()):
                return "cuda"
        except Exception:
            pass
        return "cpu"

    @staticmethod
    def _compute_type(config: TranscriptionConfig, device: str) -> str:
        if config.quantization != "auto":
            return config.quantization
        return "float16" if device == "cuda" else "int8"

    def _loader(self) -> Callable[..., Any]:
        if self._model_loader is not None:
            return self._model_loader
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise TranscriptionUnavailable(
                "Local transcription is unavailable; install the pinned optional faster-whisper dependency"
            ) from exc
        return WhisperModel

    def _get_model(self, config: TranscriptionConfig) -> tuple[Any, str]:
        model_ref = self._resolve_model(config.model)
        device = self._device(config)
        compute_type = self._compute_type(config, device)
        key = (model_ref, device, compute_type, bool(config.allow_model_download))
        with self._models_lock:
            if key in self._models:
                return self._models[key], model_ref
            kwargs = {
                "device": device,
                "compute_type": compute_type,
                # faster-whisper forwards this to huggingface_hub.  False is
                # an explicit operator opt-in and remains visible in job config.
                "local_files_only": not config.allow_model_download,
            }
            if self.model_root is not None:
                kwargs["download_root"] = str(self.model_root)
            try:
                model = self._loader()(model_ref, **kwargs)
            except TranscriptionUnavailable:
                raise
            except Exception as exc:
                raise TranscriptionUnavailable(
                    "The configured local transcription model could not be loaded"
                ) from exc
            self._models[key] = model
            return model, model_ref

    @staticmethod
    def _probability(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            probability = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(probability):
            return None
        return max(0.0, min(1.0, probability))

    def transcribe(
        self,
        media_path: Path,
        config: TranscriptionConfig,
        *,
        cancel_requested: Callable[[], bool],
        progress: Callable[[int], None],
    ) -> TranscriptionResult:
        path = Path(media_path)
        if not path.is_file():
            raise TranscriptionUnavailable("The meeting media file is unavailable")
        if config.diarization and self._diarizer is None:
            raise TranscriptionCapabilityError(
                "Speaker diarization was requested but no local diarization provider is configured"
            )
        if cancel_requested():
            raise TranscriptionCancelled("Transcription was cancelled before it started")

        model, model_ref = self._get_model(config)
        kwargs: dict[str, Any] = {
            "word_timestamps": config.timestamp_granularity == "word",
        }
        if config.language:
            kwargs["language"] = config.language
        try:
            raw_segments, info = model.transcribe(str(path), **kwargs)
        except Exception as exc:
            raise TranscriptionUnavailable("Local transcription failed to start") from exc

        segments: list[TranscriptionSegmentResult] = []
        for index, raw in enumerate(raw_segments):
            if cancel_requested():
                raise TranscriptionCancelled("Transcription was cancelled")
            text = str(getattr(raw, "text", "") or "").strip()
            start_ms = max(0, int(round(float(getattr(raw, "start", 0.0)) * 1000)))
            end_ms = max(start_ms, int(round(float(getattr(raw, "end", 0.0)) * 1000)))
            words: list[TranscriptionWord] = []
            for word in getattr(raw, "words", None) or ():
                word_start = max(
                    start_ms,
                    int(round(float(getattr(word, "start", start_ms / 1000)) * 1000)),
                )
                word_end = max(
                    word_start,
                    int(round(float(getattr(word, "end", word_start / 1000)) * 1000)),
                )
                words.append(
                    TranscriptionWord(
                        text=str(getattr(word, "word", "") or ""),
                        start_ms=word_start,
                        end_ms=word_end,
                        confidence=self._probability(getattr(word, "probability", None)),
                    )
                )
            if text:
                # faster-whisper exposes average_logprob rather than a direct
                # confidence.  Do not invent a probability from it.
                segments.append(
                    TranscriptionSegmentResult(
                        text=text,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        words=tuple(words),
                    )
                )
            progress(min(70, 5 + ((index + 1) % 65)))

        if not segments:
            raise TranscriptionInvalidResult("The local provider returned no speech segments")

        diarization_applied = False
        if config.diarization and self._diarizer is not None:
            assigned = self._diarizer.assign_speakers(
                path,
                segments,
                cancel_requested=cancel_requested,
            )
            segments = list(assigned)
            diarization_applied = True

        duration = getattr(info, "duration", None)
        duration_ms = None
        if duration is not None:
            try:
                duration_ms = max(0, int(round(float(duration) * 1000)))
            except (TypeError, ValueError):
                duration_ms = None
        if duration_ms is None:
            duration_ms = max(segment.end_ms for segment in segments)
        language = str(getattr(info, "language", "") or config.language or "").strip() or None
        progress(70)
        return TranscriptionResult(
            segments=tuple(segments),
            language=language,
            duration_ms=duration_ms,
            provider=self.name,
            provider_version=self.version,
            model=model_ref,
            diarization_applied=diarization_applied,
            metadata={
                "local_only": True,
                "timestamp_granularity": config.timestamp_granularity,
            },
        )
