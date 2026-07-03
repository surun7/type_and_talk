# SPDX-License-Identifier: MIT
"""
Speech-to-text via faster-whisper (local, offline).

Hallucination patterns are based on common openai-whisper zh-mode failures.
Add new patterns here as you discover them — submit a PR.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

try:
    import numpy as np

    _HAS_NP = True
except ImportError:
    np = None  # type: ignore[assignment]
    _HAS_NP = False

from agent_uia.audio import model_manager
from agent_uia.performance.monitor import default_monitor, MetricType, MetricPoint

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ModelNotReadyError(Exception):
    """Raised when the Whisper model is not in a READY state."""

    def __init__(self, message: str = "Whisper model is not ready") -> None:
        super().__init__(message)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class TranscriptionResult:
    """Result of a speech-to-text transcription."""

    text: str
    language: str
    duration_s: float
    segments: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Chinese hallucination post-processing
# ---------------------------------------------------------------------------

_ZH_HALLUCINATION_PATTERNS: list[str] = [
    r"^\s*\(音乐\)\s*$",
    r"^\s*\[音乐\]\s*$",
    r"^\s*字幕\s*$",
    r"^\s*谢谢观看\s*$",
    r"^\s*请不吝点赞订阅转发打赏支持明德\s*$",
    r"^\s*Thank you\.?\s*$",
    r"^\s*Thanks for (watching|listening)\.?\s*$",
    r"^\s*(\.\s*){3,}$",
    r"^\s*\.+\s*$",
    r"^\s*(好|嗯|啊|哦)\s*$",
]

# Pre-compiled patterns for efficiency
_COMPILED_HALLUCINATION: list[re.Pattern[str]] = [
    re.compile(p) for p in _ZH_HALLUCINATION_PATTERNS
]

_REPEATED_PUNCTUATION: re.Pattern[str] = re.compile(r"([!?，。！？、；：,.])\1+")
_TRAILING_PUNCTUATION: re.Pattern[str] = re.compile(r"[!?，。！？、；：,.\s]+$")


def clean_transcript(text: str) -> str:
    """Remove common whisper hallucinations from Chinese transcripts.

    Returns an empty string if the entire text matches a known hallucination
    pattern. Otherwise strips whitespace, collapses repeated punctuation,
    and trims trailing punctuation.

    Parameters
    ----------
    text : str
        Raw transcription text.

    Returns
    -------
    str
        Cleaned transcription text (possibly empty).
    """
    if not text or not text.strip():
        return ""

    stripped = text.strip()

    # Full-text hallucination match
    for pattern in _COMPILED_HALLUCINATION:
        if pattern.fullmatch(stripped):
            return ""

    # Collapse repeated punctuation (e.g. "。。。" -> "。")
    cleaned = _REPEATED_PUNCTUATION.sub(r"\1", stripped)

    # Trim trailing punctuation / whitespace
    cleaned = _TRAILING_PUNCTUATION.sub("", cleaned)

    return cleaned.strip()


# ---------------------------------------------------------------------------
# Speech Recognizer
# ---------------------------------------------------------------------------

class SpeechRecognizer:
    """Local offline speech recognizer powered by faster-whisper.

    The model is loaded lazily on the first call to :meth:`transcribe` and
    can be explicitly loaded via :meth:`load`. Repeated calls to ``load``
    are idempotent once the model is in a READY state.
    """

    def __init__(
        self,
        model_manager: Any,  # noqa: ANN401 — any callable that produces a faster-whisper model
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "int8",
    ) -> None:
        """Initialise the recognizer.

        Parameters
        ----------
        model_manager :
            Module or object responsible for managing the Whisper model lifecycle
            (expected to expose a ``get_model`` callable).
        model_size :
            Whisper model size (e.g. ``"tiny"``, ``"base"``, ``"small"``,
            ``"medium"``, ``"large-v3"``).
        device :
            Torch device string (``"auto"``, ``"cpu"``, ``"cuda"``).
        compute_type :
            Compute type for faster-whisper (``"int8"``, ``"float16"``,
            ``"float32"``, etc.).
        """
        self._model_manager = model_manager
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._model: Any = None  # noqa: ANN401 — faster-whisper Whisper model
        self._ready: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load or verify the Whisper model.

        Idempotent: subsequent calls are no-ops once the model is ready.
        Raises :class:`ModelNotReadyError` if loading fails.
        """
        if self._ready and self._model is not None:
            return

        try:
            # The model_manager is expected to provide a ``get_model``
            # function that returns a faster-whisper Whisper instance.
            self._model = self._model_manager.get_model(
                model_size=self._model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
            self._ready = True
        except Exception as exc:
            self._ready = False
            raise ModelNotReadyError(
                f"Failed to load Whisper model '{self._model_size}': {exc}"
            ) from exc

    @property
    def is_ready(self) -> bool:
        """Whether the underlying Whisper model is loaded and ready."""
        return self._ready

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        language: str = "zh",
    ) -> TranscriptionResult:
        """Transcribe an audio array.

        Parameters
        ----------
        audio :
            Mono audio samples as a 1-D float32 NumPy array normalised to
            the range ``[-1, 1]``.
        sample_rate :
            Sample rate of the audio data (must match what the model expects;
            16 kHz is the faster-whisper default).
        language :
            Target language code (e.g. ``"zh"``, ``"en"``). Pass ``None``
            to let the model auto-detect.

        Returns
        -------
        TranscriptionResult
            The transcription result with cleaned text.
        """
        if not self._ready or self._model is None:
            self.load()

        if not self._ready or self._model is None:
            raise ModelNotReadyError(
                "Cannot transcribe: model failed to load or is not ready."
            )

        # faster-whisper expects float32 audio
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        duration_s = float(len(audio)) / sample_rate

        segments_raw: list[dict[str, Any]] = []
        text_parts: list[str] = []

        _monitor = default_monitor()
        with _monitor.time("asr_transcribe", model_size=self._model_size):
            # Run inference
            result = self._model.transcribe(
                audio,
                language=language,
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=500,
                    threshold=0.5,
                ),
            )

        for seg in result:
            seg_dict = {
                "start": seg.start,
                "end": seg.end,
                "text": seg.text,
                "avg_logprob": seg.avg_logprob,
                "no_speech_prob": seg.no_speech_prob,
            }
            segments_raw.append(seg_dict)
            text_parts.append(seg.text)

        raw_text = " ".join(text_parts).strip()
        cleaned_text = clean_transcript(raw_text)

        return TranscriptionResult(
            text=cleaned_text,
            language=language or "auto",
            duration_s=duration_s,
            segments=segments_raw,
        )
