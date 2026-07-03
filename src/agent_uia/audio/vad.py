# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Voice Activity Detection for TNT audio input.

Uses silero-vad (https://github.com/snakers4/silero-vad) when available.
silero-vad is a small, accurate, ML-based VAD that runs on CPU and handles
background noise well. It auto-downloads its model (~2 MB) via torch.hub
on first use, cached at ``~/.cache/torch/hub/``.

Falls back to RMS-energy threshold if silero-vad or torch cannot be imported
(e.g. install failed). The fallback is documented as degraded accuracy.
"""

from __future__ import annotations

import math
import struct
from typing import Literal

from loguru import logger

__all__ = [
    "SilenceDetector",
    "SUPPORTED_FRAME_MS",
    "SUPPORTED_SAMPLE_RATES",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FRAME_SIZE_TABLE: dict[tuple[int, int], int] = {
    (16000, 10): 160,
    (16000, 20): 320,
    (16000, 30): 480,
    (8000, 10): 80,
    (8000, 20): 160,
    (8000, 30): 240,
}

SUPPORTED_FRAME_MS: tuple[int, ...] = (10, 20, 30)
SUPPORTED_SAMPLE_RATES: tuple[int, ...] = (8000, 16000)

# ---------------------------------------------------------------------------
# State machine constants
# ---------------------------------------------------------------------------

_RMS_SILENCE_THRESHOLD: float = 500.0


# ---------------------------------------------------------------------------
# SilenceDetector
# ---------------------------------------------------------------------------


class SilenceDetector:
    """Voice activity detector with a speech/silence state machine.

    Args:
        sample_rate: Audio sample rate in Hz (8000 or 16000).
        frame_duration_ms: Duration of each frame in ms (10, 20, or 30).
        silence_timeout_s: Seconds of continuous silence before timing out.
        threshold: Silero-VAD confidence threshold (0.0–1.0, default 0.5).

    Raises:
        ValueError: If ``sample_rate`` or ``frame_duration_ms`` is not
            in the supported tables.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_duration_ms: int = 30,
        silence_timeout_s: float = 1.5,
        threshold: float = 0.5,
    ) -> None:
        if sample_rate not in SUPPORTED_SAMPLE_RATES:
            raise ValueError(
                f"Unsupported sample_rate {sample_rate}. "
                f"Supported: {SUPPORTED_SAMPLE_RATES}"
            )
        if frame_duration_ms not in SUPPORTED_FRAME_MS:
            raise ValueError(
                f"Unsupported frame_duration_ms {frame_duration_ms}. "
                f"Supported: {SUPPORTED_FRAME_MS}"
            )

        self._sample_rate = sample_rate
        self._frame_duration_ms = frame_duration_ms
        self._silence_timeout_s = silence_timeout_s
        self._threshold = threshold

        self._frame_size = _FRAME_SIZE_TABLE[(sample_rate, frame_duration_ms)]

        # Backend: lazily initialised on first call to feed().
        self._backend: Literal["silero", "rms"] | None = None
        self._model: object = None
        self._iterator: object = None

        # State machine.
        self._in_speech: bool = False
        self._silence_frame_count: int = 0
        self._silence_frames_before_timeout: int = int(
            silence_timeout_s * 1000 / frame_duration_ms
        )
        self._stopped: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset the internal state machine.

        Call this between recording sessions.
        """
        self._in_speech = False
        self._silence_frame_count = 0
        self._stopped = False

    def feed(self, frame_bytes: bytes) -> Literal["speech", "silence", "silence_timeout"]:
        """Process a single audio frame.

        Args:
            frame_bytes: Raw PCM int16 mono audio data. Must have
                ``sample_rate * frame_duration_ms / 1000`` samples.

        Returns:
            ``"speech"`` if speech is detected,
            ``"silence"`` if silence is detected (but timeout not yet reached),
            ``"silence_timeout"`` when the silence timeout has elapsed.
        """
        if self._stopped:
            return "silence_timeout"

        # Lazy-load the backend on first call.
        if self._backend is None:
            self._init_backend()

        # Detect speech.
        if self._backend == "silero":
            is_speech = self._feed_silero(frame_bytes)
        else:
            is_speech = self._feed_rms(frame_bytes)

        # State machine.
        if is_speech:
            self._in_speech = True
            self._silence_frame_count = 0
            return "speech"
        else:
            self._silence_frame_count += 1
            if self._silence_frame_count >= self._silence_frames_before_timeout:
                self._stopped = True
                return "silence_timeout"
            return "silence"

    @property
    def is_in_speech(self) -> bool:
        """Whether we are currently in a speech segment."""
        return self._in_speech

    # ------------------------------------------------------------------
    # Internal : backend init
    # ------------------------------------------------------------------

    def _init_backend(self) -> None:
        """Attempt to load silero-vad; fall back to RMS energy threshold."""
        # Silero-VAD path.
        try:
            from silero_vad import VADIterator, load_silero_vad

            model = load_silero_vad(onnx=False)
            self._iterator = VADIterator(
                model,
                threshold=self._threshold,
                sampling_rate=self._sample_rate,
            )
            self._model = model
            self._backend = "silero"
            logger.info("silero-vad loaded successfully")
        except ImportError as exc:
            logger.warning(
                "silero-vad unavailable ({}); falling back to RMS-energy VAD. "
                "Install with: pip install silero-vad torch",
                exc,
            )
            self._model = None
            self._iterator = None
            self._backend = "rms"
        except Exception as exc:
            logger.warning(
                "silero-vad init failed ({}); falling back to RMS-energy VAD",
                exc,
            )
            self._model = None
            self._iterator = None
            self._backend = "rms"

    # ------------------------------------------------------------------
    # Internal : silero-vad backend
    # ------------------------------------------------------------------

    def _feed_silero(self, frame_bytes: bytes) -> bool:
        """Run one frame through silero-vad's VADIterator.

        Returns True if speech is detected, False otherwise.
        """
        iterator = self._iterator
        if iterator is None:
            return False

        try:
            # Convert int16 PCM bytes → float32 torch tensor.
            import torch

            expected_samples = self._frame_size
            if len(frame_bytes) != expected_samples * 2:  # 2 bytes per int16
                logger.warning(
                    "silero-vad: expected {} bytes, got {}; padding/truncating",
                    expected_samples * 2,
                    len(frame_bytes),
                )
                frame_bytes = frame_bytes.ljust(expected_samples * 2, b"\x00")[
                    : expected_samples * 2
                ]

            audio = (
                torch.frombuffer(
                    bytearray(frame_bytes), dtype=torch.int16
                ).float()
                / 32768.0
            )

            result = iterator(audio)
            # VADIterator returns dict with "start" or "end" keys when
            # speech boundaries are detected, or None otherwise.
            if result is None:
                return False
            if isinstance(result, dict):
                if "start" in result:
                    return True
                if "end" in result:
                    return False
            return False
        except Exception:
            logger.exception("silero-vad inference failed")
            return False

    # ------------------------------------------------------------------
    # Internal : RMS-energy fallback backend
    # ------------------------------------------------------------------

    def _feed_rms(self, frame_bytes: bytes) -> bool:
        """Compute RMS energy of an int16 PCM frame.

        Returns True if RMS exceeds the silence threshold, False otherwise.
        """
        if not frame_bytes:
            return False

        try:
            # Decode int16 PCM (little-endian).
            samples = len(frame_bytes) // 2
            if samples == 0:
                return False

            # Use struct for fast unpacking.
            fmt = "<" + "h" * samples
            vals = struct.unpack(fmt, frame_bytes)

            sum_sq = sum(v * v for v in vals)
            rms = math.sqrt(sum_sq / samples)
            return rms > _RMS_SILENCE_THRESHOLD
        except Exception:
            logger.exception("RMS VAD fallback failed")
            return False
