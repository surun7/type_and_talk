# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for AudioRecorder — sounddevice is fully mocked."""

from __future__ import annotations

from unittest import mock

import numpy as np
import pytest

from agent_uia.audio.recorder import AudioRecorder, RecorderState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_sounddevice() -> mock.MagicMock:
    """Mock the sounddevice module so no real audio hardware is accessed.

    Returns the mock so tests can access captured callbacks if needed.
    """
    patcher = mock.patch("agent_uia.audio.recorder.sd")
    mock_sd = patcher.start()

    # InputStream mock: record the callback argument for later invocation.
    mock_stream = mock.MagicMock()
    # Track callbacks passed to InputStream
    mock_sd.InputStream.return_value = mock_stream
    mock_stream.start.return_value = None
    mock_stream.stop.return_value = None
    mock_stream.close.return_value = None

    yield mock_sd

    patcher.stop()


@pytest.fixture
def recorder() -> AudioRecorder:
    """Return a fresh AudioRecorder for each test."""
    return AudioRecorder(samplerate=16000, blocksize=1024)


@pytest.fixture
def recorder_and_stream(
    recorder: AudioRecorder, _mock_sounddevice: mock.MagicMock
) -> tuple[AudioRecorder, mock.MagicMock]:
    """Return (recorder, mock_stream) where the stream is the mock sd.InputStream."""
    mock_stream = _mock_sounddevice.InputStream.return_value
    return recorder, mock_stream


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------


class TestStateManagement:
    """Verify the state machine transitions correctly."""

    def test_initial_state(self, recorder: AudioRecorder) -> None:
        """A new recorder starts in IDLE state."""
        assert recorder.state == RecorderState.IDLE

    def test_start_transitions_to_recording(
        self, recorder: AudioRecorder
    ) -> None:
        """Calling start() transitions to RECORDING."""
        recorder.start()
        assert recorder.state == RecorderState.RECORDING

    def test_stop_transitions_to_stopped(
        self, recorder: AudioRecorder
    ) -> None:
        """Calling stop() transitions to STOPPED."""
        recorder.start()
        recorder.stop()
        assert recorder.state == RecorderState.STOPPED

    def test_start_twice_raises(self, recorder: AudioRecorder) -> None:
        """Calling start() while already recording raises RuntimeError."""
        recorder.start()
        with pytest.raises(RuntimeError, match="already recording"):
            recorder.start()

    def test_stop_idle_returns_empty(self, recorder: AudioRecorder) -> None:
        """Calling stop() on an idle recorder returns an empty array and stays IDLE-ish."""
        result = recorder.stop()
        assert isinstance(result, np.ndarray)
        assert result.size == 0
        # The state was IDLE; stop() checks IDLE and returns early.
        assert recorder.state == RecorderState.IDLE

    def test_error_state_on_stream_failure(
        self, recorder: AudioRecorder, _mock_sounddevice: mock.MagicMock
    ) -> None:
        """If InputStream creation fails, the state becomes ERROR."""
        _mock_sounddevice.InputStream.side_effect = OSError("No audio device")
        with pytest.raises(RuntimeError, match="Failed to start"):
            recorder.start()
        assert recorder.state == RecorderState.ERROR


# ---------------------------------------------------------------------------
# is_recording property
# ---------------------------------------------------------------------------

class TestIsRecording:
    """Verify the is_recording property."""

    def test_is_recording_false_initial(self, recorder: AudioRecorder) -> None:
        """Before start(), is_recording is False."""
        assert not recorder.is_recording

    def test_is_recording_true_during_recording(
        self, recorder: AudioRecorder
    ) -> None:
        """During recording, is_recording is True."""
        recorder.start()
        assert recorder.is_recording

    def test_is_recording_false_after_stop(
        self, recorder: AudioRecorder
    ) -> None:
        """After stop(), is_recording is False."""
        recorder.start()
        recorder.stop()
        assert not recorder.is_recording


# ---------------------------------------------------------------------------
# Start / Stop audio flow
# ---------------------------------------------------------------------------


class TestStartStop:
    """Verify the start/stop lifecycle and buffer handling."""

    def test_start_creates_input_stream(
        self, recorder: AudioRecorder, _mock_sounddevice: mock.MagicMock
    ) -> None:
        """start() creates an sd.InputStream with the expected parameters."""
        recorder.start()
        _mock_sounddevice.InputStream.assert_called_once_with(
            samplerate=16000,
            channels=1,
            blocksize=1024,
            device=None,
            callback=mock.ANY,
        )

    def test_start_starts_stream(
        self, recorder_and_stream: tuple[AudioRecorder, mock.MagicMock]
    ) -> None:
        """start() calls .start() on the InputStream."""
        recorder, mock_stream = recorder_and_stream
        recorder.start()
        mock_stream.start.assert_called_once()

    def test_stop_stops_and_closes_stream(
        self, recorder_and_stream: tuple[AudioRecorder, mock.MagicMock]
    ) -> None:
        """stop() calls .stop() and .close() on the InputStream."""
        recorder, mock_stream = recorder_and_stream
        recorder.start()
        recorder.stop()
        mock_stream.stop.assert_called_once()
        mock_stream.close.assert_called_once()

    def test_stop_returns_audio_buffer(
        self, recorder: AudioRecorder, _mock_sounddevice: mock.MagicMock
    ) -> None:
        """stop() returns the concatenated audio captured via the callback."""
        recorder.start()

        # Retrieve the callback that was passed to InputStream.
        callback = _mock_sounddevice.InputStream.call_args.kwargs["callback"]

        # Simulate audio data arriving via the callback (two frames).
        frame1 = np.ones((1024, 1), dtype=np.float32) * 0.1
        frame2 = np.ones((1024, 1), dtype=np.float32) * 0.2

        callback(frame1, 1024, None, None)
        callback(frame2, 1024, None, None)

        audio = recorder.stop()

        # Expected: concatenated, squeezed to 1-D, float32.
        expected = np.concatenate([frame1, frame2], axis=0).squeeze().astype(np.float32)
        np.testing.assert_array_equal(audio, expected)

    def test_stop_without_buffers_returns_empty(
        self, recorder: AudioRecorder
    ) -> None:
        """If no audio was captured, stop() returns an empty array."""
        recorder.start()
        audio = recorder.stop()
        assert isinstance(audio, np.ndarray)
        assert audio.size == 0

    def test_callback_ignored_after_stop(
        self, recorder: AudioRecorder, _mock_sounddevice: mock.MagicMock
    ) -> None:
        """After stop(), the callback should not add more data to buffers."""
        recorder.start()
        callback = _mock_sounddevice.InputStream.call_args.kwargs["callback"]

        frame = np.ones((1024, 1), dtype=np.float32) * 0.5
        callback(frame, 1024, None, None)
        recorder.stop()

        # This extra callback should be ignored.
        callback(frame, 1024, None, None)

        # Expected: only the frame captured before stop.
        audio = recorder.stop()  # second stop returns empty
        assert audio.size == 0

    def test_restart_after_stop_clears_buffers(
        self, recorder: AudioRecorder, _mock_sounddevice: mock.MagicMock
    ) -> None:
        """Starting again after stop() clears the old buffer."""
        recorder.start()
        callback = _mock_sounddevice.InputStream.call_args.kwargs["callback"]

        frame1 = np.ones((1024, 1), dtype=np.float32) * 0.5
        callback(frame1, 1024, None, None)
        recorder.stop()

        # Start again and capture new data.
        recorder.start()
        callback2 = _mock_sounddevice.InputStream.call_args.kwargs["callback"]

        frame2 = np.ones((1024, 1), dtype=np.float32) * 0.9
        callback2(frame2, 1024, None, None)

        audio = recorder.stop()
        expected = frame2.squeeze().astype(np.float32)
        np.testing.assert_array_equal(audio, expected)
        assert len(audio) == 1024  # old frame1 was cleared


# ---------------------------------------------------------------------------
# duration_s property
# ---------------------------------------------------------------------------


class TestDuration:
    """Verify the duration_s property."""

    def test_duration_zero_initial(
        self, recorder: AudioRecorder
    ) -> None:
        """Before any recording, duration_s is 0.0."""
        assert recorder.duration_s == 0.0

    def test_duration_after_callback(
        self, recorder: AudioRecorder, _mock_sounddevice: mock.MagicMock
    ) -> None:
        """duration_s reflects captured buffer length."""
        recorder.start()
        callback = _mock_sounddevice.InputStream.call_args.kwargs["callback"]

        # One frame of 1024 samples at 16 kHz = 0.064 s
        frame = np.zeros((1024, 1), dtype=np.float32)
        callback(frame, 1024, None, None)

        # Another frame = 0.128 s total
        callback(frame, 1024, None, None)

        expected_duration = (1024 + 1024) / 16000.0
        assert recorder.duration_s == pytest.approx(expected_duration)

    def test_duration_resets_on_restart(
        self, recorder: AudioRecorder, _mock_sounddevice: mock.MagicMock
    ) -> None:
        """Starting a new recording resets the duration counter."""
        recorder.start()
        callback = _mock_sounddevice.InputStream.call_args.kwargs["callback"]
        callback(np.zeros((1024, 1), dtype=np.float32), 1024, None, None)
        recorder.stop()

        # Start again; duration should be 0.
        recorder.start()
        assert recorder.duration_s == 0.0


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """Verify basic thread-safety properties."""

    def test_is_recording_thread_safe(
        self, recorder: AudioRecorder
    ) -> None:
        """The is_recording property can be called from multiple threads."""
        import concurrent.futures

        recorder.start()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(lambda: recorder.is_recording) for _ in range(10)]
            results = [f.result() for f in futures]
        assert all(results)

        recorder.stop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(lambda: recorder.is_recording) for _ in range(10)]
            results = [f.result() for f in futures]
        assert not any(results)
