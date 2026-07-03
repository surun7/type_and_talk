# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for SilenceDetector — silero-vad is mocked so no real model is needed."""

from __future__ import annotations

from unittest import mock

import pytest

from agent_uia.audio.vad import (
    SUPPORTED_FRAME_MS,
    SUPPORTED_SAMPLE_RATES,
    SilenceDetector,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_silent_frame(sample_rate: int, frame_ms: int) -> bytes:
    from agent_uia.audio.vad import _FRAME_SIZE_TABLE
    n = _FRAME_SIZE_TABLE[(sample_rate, frame_ms)]
    return b"\x00\x00" * n


def _make_loud_frame(sample_rate: int, frame_ms: int) -> bytes:
    from agent_uia.audio.vad import _FRAME_SIZE_TABLE
    n = _FRAME_SIZE_TABLE[(sample_rate, frame_ms)]
    return (0x7FFF).to_bytes(2, "little", signed=True) * n


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def silero_backend() -> mock.MagicMock:
    """Replace ``_init_backend`` with a fake that sets ``backend='silero'``.

    Returns the mock VADIterator so tests can control return values.
    """
    fake_iterator = mock.MagicMock()
    fake_iterator.return_value = None  # default: silence

    def _fake_init(self) -> None:
        self._model = mock.MagicMock()
        self._iterator = fake_iterator
        self._backend = "silero"

    with mock.patch.object(SilenceDetector, "_init_backend", _fake_init):
        yield fake_iterator


# ---------------------------------------------------------------------------
# Tests: backend selection
# ---------------------------------------------------------------------------


class TestBackendSelection:

    def test_silero_preferred(self, silero_backend):
        d = SilenceDetector(sample_rate=16000, frame_duration_ms=30, silence_timeout_s=0.3)
        d.feed(_make_silent_frame(16000, 30))
        assert d._backend == "silero"

    def test_rms_fallback(self):
        """RMS fallback works when _init_backend falls to RMS."""
        def _rms_init(self) -> None:
            self._model = None
            self._iterator = None
            self._backend = "rms"

        with mock.patch.object(SilenceDetector, "_init_backend", _rms_init):
            d = SilenceDetector(sample_rate=16000, frame_duration_ms=30, silence_timeout_s=0.3)
            assert d.feed(_make_loud_frame(16000, 30)) == "speech"
            assert d._backend == "rms"

    def test_rms_fallback_silence(self):
        def _rms_init(self) -> None:
            self._model = None
            self._iterator = None
            self._backend = "rms"

        with mock.patch.object(SilenceDetector, "_init_backend", _rms_init):
            d = SilenceDetector(sample_rate=16000, frame_duration_ms=30, silence_timeout_s=0.3)
            assert d.feed(_make_silent_frame(16000, 30)) == "silence"
            assert d._backend == "rms"


# ---------------------------------------------------------------------------
# Tests: parameter validation
# ---------------------------------------------------------------------------


class TestParameterValidation:

    def test_unsupported_sample_rate_raises(self):
        with pytest.raises(ValueError, match="sample_rate"):
            SilenceDetector(sample_rate=22050)

    def test_unsupported_frame_duration_raises(self):
        with pytest.raises(ValueError, match="frame_duration_ms"):
            SilenceDetector(frame_duration_ms=40)

    def test_supported_combinations(self):
        for sr in SUPPORTED_SAMPLE_RATES:
            for fd in SUPPORTED_FRAME_MS:
                sd = SilenceDetector(sample_rate=sr, frame_duration_ms=fd)
                assert sd._frame_size > 0


# ---------------------------------------------------------------------------
# Tests: state machine (silero backend)
# ---------------------------------------------------------------------------


class TestStateMachine:

    def test_speech_returns_speech(self, silero_backend):
        silero_backend.return_value = {"start": 0.0}
        d = SilenceDetector(sample_rate=16000, frame_duration_ms=30, silence_timeout_s=0.3)
        assert d.feed(_make_silent_frame(16000, 30)) == "speech"

    def test_silence_returns_silence(self, silero_backend):
        d = SilenceDetector(sample_rate=16000, frame_duration_ms=30, silence_timeout_s=0.3)
        assert d.feed(_make_silent_frame(16000, 30)) == "silence"

    def test_silence_timeout(self, silero_backend):
        d = SilenceDetector(sample_rate=16000, frame_duration_ms=30, silence_timeout_s=0.3)
        f = _make_silent_frame(16000, 30)
        for _ in range(20):
            d.feed(f)
        assert d.feed(f) == "silence_timeout"

    def test_speech_resets_silence_counter(self, silero_backend):
        d = SilenceDetector(sample_rate=16000, frame_duration_ms=30, silence_timeout_s=0.3)
        f = _make_silent_frame(16000, 30)
        for _ in range(5):
            d.feed(f)
        silero_backend.return_value = {"start": 0.0}
        assert d.feed(f) == "speech"
        silero_backend.return_value = None
        for _ in range(9):
            d.feed(f)
        assert d.feed(f) == "silence_timeout"

    def test_reset_clears_state(self, silero_backend):
        d = SilenceDetector(sample_rate=16000, frame_duration_ms=30, silence_timeout_s=0.3)
        f = _make_silent_frame(16000, 30)
        for _ in range(20):
            d.feed(f)
        assert d._stopped is True
        d.reset()
        assert d._stopped is False
        assert d.feed(f) == "silence"


# ---------------------------------------------------------------------------
# Tests: is_in_speech property
# ---------------------------------------------------------------------------


class TestIsInSpeech:

    def test_initial_false(self, silero_backend):
        d = SilenceDetector(sample_rate=16000, frame_duration_ms=30, silence_timeout_s=0.3)
        assert d.is_in_speech is False

    def test_true_on_speech(self, silero_backend):
        silero_backend.return_value = {"start": 0.0}
        d = SilenceDetector(sample_rate=16000, frame_duration_ms=30, silence_timeout_s=0.3)
        d.feed(_make_silent_frame(16000, 30))
        assert d.is_in_speech is True

    def test_reset_clears(self, silero_backend):
        silero_backend.return_value = {"start": 0.0}
        d = SilenceDetector(sample_rate=16000, frame_duration_ms=30, silence_timeout_s=0.3)
        d.feed(_make_silent_frame(16000, 30))
        assert d.is_in_speech is True
        d.reset()
        assert d.is_in_speech is False


# ---------------------------------------------------------------------------
# Tests: stopped state
# ---------------------------------------------------------------------------


class TestStoppedState:

    def test_stopped_returns_timeout(self, silero_backend):
        d = SilenceDetector(sample_rate=16000, frame_duration_ms=30, silence_timeout_s=0.3)
        f = _make_silent_frame(16000, 30)
        for _ in range(20):
            d.feed(f)
        assert d.feed(f) == "silence_timeout"
        assert d.feed(f) == "silence_timeout"
