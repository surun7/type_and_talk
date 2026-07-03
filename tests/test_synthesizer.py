# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for SpeechSynthesizer — edge-tts, sounddevice, and soundfile are mocked."""

from __future__ import annotations

from typing import AsyncIterator
from unittest import mock

import pytest

from agent_uia.audio.synthesizer import SpeechSynthesizer, _strip_markdown


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_gen(*chunks: dict[str, object]) -> AsyncIterator[dict[str, object]]:
    """Yield chunks as an async generator (simulates Communicate.stream())."""
    for c in chunks:
        yield c


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_edge_tts() -> mock.MagicMock:
    """Mock edge_tts.Communicate so no network requests are made."""
    patcher = mock.patch("agent_uia.audio.synthesizer.Communicate")
    mock_comm_class = patcher.start()

    mock_instance = mock.AsyncMock()
    # Default: stream yields a single audio chunk.
    mock_instance.stream.return_value = _async_gen(
        {"type": "audio", "data": b"fake-mp3-data"}
    )
    mock_comm_class.return_value = mock_instance

    yield mock_comm_class

    patcher.stop()


@pytest.fixture(autouse=True)
def _mock_sounddevice() -> mock.MagicMock:
    """Mock sounddevice so no audio hardware is accessed."""
    patcher = mock.patch("agent_uia.audio.synthesizer.sd")
    mock_sd = patcher.start()

    # Return None from get_stream() so the playback loop is skipped.
    mock_sd.get_stream.return_value = None
    mock_sd.play.return_value = None
    mock_sd.stop.return_value = None

    yield mock_sd

    patcher.stop()



@pytest.fixture
def synthesizer() -> SpeechSynthesizer:
    """Return a fresh SpeechSynthesizer with the default voice."""
    return SpeechSynthesizer(voice="zh-CN-XiaoxiaoNeural")


# ---------------------------------------------------------------------------
# speak
# ---------------------------------------------------------------------------


class TestSpeak:
    """Tests for the speak() method."""

    @pytest.mark.asyncio
    async def test_speak_calls_communicate(
        self,
        synthesizer: SpeechSynthesizer,
        _mock_edge_tts: mock.MagicMock,
    ) -> None:
        """speak() instantiates edge_tts.Communicate with the right voice and text."""
        await synthesizer.speak("你好世界")

        _mock_edge_tts.assert_called_once_with(
            "你好世界", "zh-CN-XiaoxiaoNeural", rate="+0%"
        )
        mock_instance = _mock_edge_tts.return_value
        mock_instance.stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_speak_sets_speaking_flag(
        self, synthesizer: SpeechSynthesizer
    ) -> None:
        """During speak(), is_speaking is True."""
        async def _assert_speaking() -> None:
            assert synthesizer.is_speaking

        # Hook into the async flow by checking during execution.
        original = synthesizer._synthesize_and_play
        checked = False

        async def wrapped(text: str) -> None:
            nonlocal checked
            checked = True
            assert synthesizer.is_speaking
            await original(text)

        synthesizer._synthesize_and_play = wrapped  # type: ignore[assignment]

        await synthesizer.speak("test")
        assert checked

    @pytest.mark.asyncio
    async def test_speak_busy_raises(
        self, synthesizer: SpeechSynthesizer
    ) -> None:
        """Calling speak() while already speaking raises RuntimeError."""
        # Set the flag manually.
        synthesizer._speaking = True
        with pytest.raises(RuntimeError, match="already speaking"):
            await synthesizer.speak("test")

    @pytest.mark.asyncio
    async def test_speak_empty_text_is_noop(
        self,
        synthesizer: SpeechSynthesizer,
        _mock_edge_tts: mock.MagicMock,
    ) -> None:
        """Speaking an empty or whitespace-only string does nothing."""
        await synthesizer.speak("")
        _mock_edge_tts.assert_not_called()

        await synthesizer.speak("   ")
        _mock_edge_tts.assert_not_called()

    @pytest.mark.asyncio
    async def test_speak_plays_audio(
        self,
        synthesizer: SpeechSynthesizer,
        _mock_soundfile: mock.MagicMock,
        _mock_sounddevice: mock.MagicMock,
    ) -> None:
        """After synthesis, sounddevice.play() is called with decoded audio."""
        await synthesizer.speak("你好")

        _mock_soundfile.read.assert_called_once()
        _mock_sounddevice.play.assert_called_once()

    @pytest.mark.asyncio
    async def test_speak_clears_flag_on_finish(
        self, synthesizer: SpeechSynthesizer
    ) -> None:
        """After speak() completes, is_speaking returns to False."""
        assert not synthesizer.is_speaking
        await synthesizer.speak("test")
        assert not synthesizer.is_speaking


# ---------------------------------------------------------------------------
# Markdown stripping
# ---------------------------------------------------------------------------


class TestMarkdownStripping:
    """Markdown formatting should be removed before TTS."""

    @pytest.mark.parametrize(
        ("raw_md", "expected_clean"),
        [
            # Fenced code blocks
            ("Some text\n```python\ncode\n```\nmore text", "Some text\n\nmore text"),
            ("```\ncode\n```", ""),
            # ATX headings
            ("# Title", "Title"),
            ("## Section", "Section"),
            ("### Sub section", "Sub section"),
            ("# Title\nbody", "Title\nbody"),
            # Blockquotes
            ("> quoted text", "quoted text"),
            ("> line1\n> line2", "line1\nline2"),
            # Bullet lists
            ("- item1\n- item2", "item1\nitem2"),
            ("* item1\n* item2", "item1\nitem2"),
            ("+ item1\n+ item2", "item1\nitem2"),
            # Horizontal rules
            ("---", ""),
            ("***", ""),
            ("___", ""),
            # Mixed
            ("# Title\n\n> quote\n- item", "Title\n\nquote\nitem"),
            # No markdown
            ("Hello world", "Hello world"),
            ("你好世界", "你好世界"),
        ],
    )
    def test_markdown_stripped(self, raw_md: str, expected_clean: str) -> None:
        """_strip_markdown removes common Markdown syntax."""
        assert _strip_markdown(raw_md) == expected_clean

    def test_empty_input(self) -> None:
        """Empty input produces empty output."""
        assert _strip_markdown("") == ""
        assert _strip_markdown("   ") == ""

    def test_newlines_collapsed(self) -> None:
        """Multiple consecutive newlines are reduced to at most two."""
        result = _strip_markdown("a\n\n\n\nb")
        assert result == "a\n\nb"


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------


class TestStop:
    """Tests for the stop() method."""

    def test_stop_sets_interrupt_flag(self, synthesizer: SpeechSynthesizer) -> None:
        """stop() sets the internal stop event."""
        assert not synthesizer._stop_event.is_set()
        synthesizer.stop()
        assert synthesizer._stop_event.is_set()

    def test_stop_clears_speaking_flag(
        self, synthesizer: SpeechSynthesizer
    ) -> None:
        """stop() sets is_speaking to False."""
        synthesizer._speaking = True
        synthesizer.stop()
        assert not synthesizer.is_speaking

    def test_stop_idempotent(self, synthesizer: SpeechSynthesizer) -> None:
        """Calling stop() multiple times does not raise."""
        synthesizer.stop()
        synthesizer.stop()  # second call
        assert not synthesizer.is_speaking

    @pytest.mark.asyncio
    async def test_stop_interrupts_speak(
        self,
        synthesizer: SpeechSynthesizer,
        _mock_edge_tts: mock.MagicMock,
    ) -> None:
        """Calling stop() during speak() interrupts playback."""
        # Make the stream yield multiple chunks slowly so we can interrupt.
        async def slow_stream() -> AsyncIterator[dict[str, object]]:
            yield {"type": "audio", "data": b"chunk1"}
            # Simulate streaming delay by yielding control.
            await __import__("asyncio").sleep(0)
            yield {"type": "audio", "data": b"chunk2"}

        mock_instance = _mock_edge_tts.return_value
        mock_instance.stream.return_value = slow_stream()

        # Start speaking and stop immediately.
        async def speak_and_stop() -> None:
            task = __import__("asyncio").create_task(synthesizer.speak("interrupt me"))
            await __import__("asyncio").sleep(0.02)
            synthesizer.stop()
            await task

        await speak_and_stop()
        assert not synthesizer.is_speaking


# ---------------------------------------------------------------------------
# is_speaking property
# ---------------------------------------------------------------------------


class TestIsSpeaking:
    """Verify the is_speaking property."""

    def test_is_speaking_initial(self, synthesizer: SpeechSynthesizer) -> None:
        """Initially, is_speaking is False."""
        assert not synthesizer.is_speaking

    def test_is_speaking_after_stop(
        self, synthesizer: SpeechSynthesizer
    ) -> None:
        """After stop(), is_speaking is False."""
        synthesizer._speaking = True
        synthesizer.stop()
        assert not synthesizer.is_speaking


# ---------------------------------------------------------------------------
# Voice / rate configuration
# ---------------------------------------------------------------------------


class TestConfiguration:
    """Verify constructor parameters are respected."""

    @pytest.mark.asyncio
    async def test_custom_voice(
        self,
        _mock_edge_tts: mock.MagicMock,
    ) -> None:
        """A custom voice is passed to Communicate."""
        synth = SpeechSynthesizer(voice="en-US-JennyNeural", rate="-10%")
        await synth.speak("hello")
        _mock_edge_tts.assert_called_once_with(
            "hello", "en-US-JennyNeural", rate="-10%"
        )
