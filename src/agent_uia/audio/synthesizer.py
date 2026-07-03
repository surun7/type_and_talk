# SPDX-License-Identifier: MIT
"""Text-to-speech via edge-tts with sounddevice playback."""

from __future__ import annotations

import io
import re
import threading
from typing import Optional

try:
    import sounddevice as sd
    from edge_tts import Communicate

    _HAS_TTS = True
except ImportError:
    sd = None  # type: ignore[assignment]
    Communicate = None  # type: ignore[assignment,misc]
    _HAS_TTS = False


# Markdown elements to strip before TTS
_MD_FENCED_BLOCK: re.Pattern[str] = re.compile(
    r"```[\s\S]*?```", re.MULTILINE
)
_MD_HEADING: re.Pattern[str] = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MD_BLOCKQUOTE: re.Pattern[str] = re.compile(r"^>\s?", re.MULTILINE)
_MD_BULLET: re.Pattern[str] = re.compile(r"^[-*+]\s+", re.MULTILINE)
_MD_HORIZONTAL_RULE: re.Pattern[str] = re.compile(
    r"^[-*_]{3,}\s*$", re.MULTILINE
)


def _strip_markdown(text: str) -> str:
    """Remove common Markdown formatting for cleaner TTS output.

    Strips fenced code blocks, ATX headings, blockquotes, bullet lists,
    and horizontal rules.

    Parameters
    ----------
    text :
        Input text that may contain Markdown syntax.

    Returns
    -------
    str
        Cleaned text suitable for speech synthesis.
    """
    text = _MD_FENCED_BLOCK.sub("", text)
    text = _MD_HEADING.sub("", text)
    text = _MD_BLOCKQUOTE.sub("", text)
    text = _MD_BULLET.sub("", text)
    text = _MD_HORIZONTAL_RULE.sub("", text)
    # Collapse multiple consecutive blank lines into one
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Speech Synthesizer
# ---------------------------------------------------------------------------

class SpeechSynthesizer:
    """Text-to-speech using edge-tts (Microsoft Edge online TTS).

    Audio is streamed into an in-memory MP3 buffer and then played back
    via sounddevice. The current utterance can be interrupted with
    :meth:`stop`.
    """

    def __init__(
        self,
        voice: str = "zh-CN-XiaoxiaoNeural",
        rate: str = "+0%",
    ) -> None:
        """Initialise the synthesizer.

        Parameters
        ----------
        voice :
            Edge TTS voice name (see ``edge-tts --list-voices``).
        rate :
            Speaking rate adjustment (e.g. ``"+20%"``, ``"-10%"``).
        """
        self._voice = voice
        self._rate = rate

        self._speaking = False
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def speak(self, text: str) -> None:
        """Synthesise and play text asynchronously.

        Parameters
        ----------
        text :
            The text to speak. Markdown formatting is automatically
            stripped before synthesis.

        Raises
        ------
        RuntimeError
            If TTS is already speaking (call :meth:`stop` first).
        """
        cleaned = _strip_markdown(text)
        if not cleaned:
            return

        with self._lock:
            if self._speaking:
                raise RuntimeError(
                    "SpeechSynthesizer is already speaking. Call stop() first."
                )
            self._speaking = True
            self._stop_event.clear()

        try:
            await self._synthesize_and_play(cleaned)
        finally:
            with self._lock:
                self._speaking = False
                self._stop_event.clear()

    def stop(self) -> None:
        """Interrupt the current TTS utterance.

        This sets an internal event flag that the playback loop checks
        between chunks. It does **not** immediately halt sounddevice;
        the current chunk plays to completion before stopping.
        """
        self._stop_event.set()
        with self._lock:
            self._speaking = False

    @property
    def is_speaking(self) -> bool:
        """Whether the synthesizer is currently playing audio."""
        with self._lock:
            return self._speaking

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _synthesize_and_play(self, text: str) -> None:
        """Stream edge-tts output and play via sounddevice.

        The MP3 audio is collected in a :class:`io.BytesIO` buffer and
        then decoded/played by sounddevice.
        """
        buffer = io.BytesIO()

        communicate = Communicate(text, self._voice, rate=self._rate)

        # Stream TTS output into an in-memory MP3
        async for chunk in communicate.stream():
            if self._stop_event.is_set():
                return
            if chunk["type"] == "audio":
                buffer.write(chunk["data"])

        buffer.seek(0)
        mp3_data = buffer.getvalue()

        if not mp3_data:
            return

        if self._stop_event.is_set():
            return

        # Play the MP3 via sounddevice.
        # sounddevice.play() accepts a numpy array; we read the MP3 using
        # soundfile (a dependency of sounddevice).
        try:
            import soundfile as sf  # noqa: PLC0415 — lazy import for the optional reader

            data, samplerate = sf.read(io.BytesIO(mp3_data), dtype="float32")

            sd.play(data, samplerate)
            # Block while playing, checking the stop event periodically
            while sd.get_stream() is not None and sd.get_stream().active:
                if self._stop_event.wait(0.1):
                    sd.stop()
                    break
        except ImportError:
            # Fallback: try plain playback via sounddevice's built-in
            # support for raw PCM (edge-tts provides MP3 which requires
            # soundfile or pydub for decoding).
            raise RuntimeError(
                "Missing dependency 'soundfile'. Install it with:\n"
                "  pip install soundfile\n"
                "or provide a decoded PCM buffer."
            ) from None
        except Exception as exc:
            raise RuntimeError(f"Audio playback failed: {exc}") from exc
        finally:
            sd.stop()
