# SPDX-License-Identifier: MIT
"""Audio recording via sounddevice."""

from __future__ import annotations

import threading
from enum import Enum
from typing import Optional

try:
    import numpy as np
    import sounddevice as sd
    _HAS_SD = True
except ImportError:
    np = None  # type: ignore[assignment]
    sd = None  # type: ignore[assignment]
    _HAS_SD = False


class RecorderState(Enum):
    """Current state of the audio recorder."""

    IDLE = "idle"
    RECORDING = "recording"
    STOPPED = "stopped"
    ERROR = "error"


class AudioRecorder:
    """Capture audio from a microphone using sounddevice.

    Records in a background thread via an :class:`sd.InputStream`. The
    audio buffer is accumulated as a list of NumPy arrays and concatenated
    when :meth:`stop` is called.

    Thread-safe: state transitions are guarded by a :class:`threading.Lock`.
    """

    def __init__(
        self,
        samplerate: int = 16000,
        channels: int = 1,
        blocksize: int = 1024,
        device: Optional[int] = None,
    ) -> None:
        """Initialise the recorder.

        Parameters
        ----------
        samplerate :
            Audio sample rate in Hz (default 16 kHz).
        channels :
            Number of input channels (default 1 for mono).
        blocksize :
            Number of frames per audio block passed to the callback.
        device :
            Device index (or ``None`` for the system default input device).
        """
        self._samplerate = samplerate
        self._channels = channels
        self._blocksize = blocksize
        self._device = device

        self._state: RecorderState = RecorderState.IDLE
        self._lock = threading.Lock()
        self._buffers: list[np.ndarray] = []
        self._stream: Optional[sd.InputStream] = None
        self._start_time: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin recording from the microphone.

        Creates and starts an :class:`sd.InputStream` in a background
        thread. The callback appends each audio block to an internal list.

        Raises
        ------
        RuntimeError
            If the recorder is already recording.
        ImportError
            If sounddevice or numpy are not installed.
        """
        if not _HAS_SD:
            raise ImportError(
                "sounddevice and numpy are required for audio recording. "
                "Install with: pip install sounddevice numpy"
            )

        with self._lock:
            if self._state == RecorderState.RECORDING:
                raise RuntimeError("Recorder is already recording.")

            self._buffers.clear()
            self._state = RecorderState.RECORDING
            self._start_time = 0.0  # will be set on first callback

        def callback(
            indata: np.ndarray,
            frames: int,  # noqa: ARG001
            _time_info: object,
            status: sd.CallbackFlags,
        ) -> None:
            if status:
                # Log or handle audio errors silently — don't raise from
                # the callback.
                return

            with self._lock:
                if self._state != RecorderState.RECORDING:
                    return
                # Copy the data so the buffer owns the memory
                self._buffers.append(indata.copy())

        try:
            self._stream = sd.InputStream(
                samplerate=self._samplerate,
                channels=self._channels,
                blocksize=self._blocksize,
                device=self._device,
                callback=callback,
            )
            self._stream.start()
        except Exception as exc:
            with self._lock:
                self._state = RecorderState.ERROR
            self._stream = None
            raise RuntimeError(f"Failed to start audio stream: {exc}") from exc

    def stop(self) -> np.ndarray:
        """Stop recording and return the captured audio.

        Returns
        -------
        np.ndarray
            1-D float32 array of concatenated audio samples, normalised to
            the range ``[-1, 1]``. Returns an empty array if no audio was
            captured.
        """
        if not _HAS_SD:
            return np.array([], dtype=np.float32) if np else b""  # type: ignore[return-value]

        with self._lock:
            if self._state == RecorderState.IDLE:
                return np.array([], dtype=np.float32)

            self._state = RecorderState.STOPPED
            buffers = self._buffers[:]
            self._buffers.clear()

        # Stop and close the stream outside the lock to avoid deadlocks
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass  # best-effort cleanup
            self._stream = None

        if not buffers:
            return np.array([], dtype=np.float32)

        audio = np.concatenate(buffers, axis=0)

        # Squeeze to 1-D if mono
        if audio.ndim > 1:
            audio = audio.squeeze()

        return audio.astype(np.float32)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        """Whether the recorder is currently capturing audio."""
        with self._lock:
            return self._state == RecorderState.RECORDING

    @property
    def duration_s(self) -> float:
        """Duration of the captured audio in seconds."""
        with self._lock:
            if not self._buffers:
                return 0.0
            total_frames = sum(buf.shape[0] for buf in self._buffers)
            return total_frames / self._samplerate

    @property
    def state(self) -> RecorderState:
        """Current recorder state."""
        with self._lock:
            return self._state
