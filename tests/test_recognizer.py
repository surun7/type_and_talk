# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for SpeechRecognizer and the clean_transcript helper."""

from __future__ import annotations

from unittest import mock

import numpy as np
import pytest

from agent_uia.audio.recognizer import (
    ModelNotReadyError,
    SpeechRecognizer,
    TranscriptionResult,
    _ZH_HALLUCINATION_PATTERNS,
    clean_transcript,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_model_manager() -> mock.MagicMock:
    """Return a mocked model manager with a working get_model()."""
    mgr = mock.MagicMock()

    # Create a fake Whisper model stub.
    fake_model = mock.MagicMock()
    # transcribe() returns an iterable of segment-like objects.
    seg = mock.MagicMock()
    seg.start = 0.0
    seg.end = 1.0
    seg.text = " 你好世界 "
    seg.avg_logprob = -0.1
    seg.no_speech_prob = 0.02
    fake_model.transcribe.return_value = [seg]

    mgr.get_model.return_value = fake_model
    return mgr


@pytest.fixture
def recognizer(mock_model_manager: mock.MagicMock) -> SpeechRecognizer:
    """Return a SpeechRecognizer with the mocked model manager."""
    rec = SpeechRecognizer(model_manager=mock_model_manager)
    # Load so that _ready is True and _model is set.
    rec.load()
    return rec


@pytest.fixture
def sample_audio() -> np.ndarray:
    """Return a short float32 audio sample (16 kHz, 0.5 s of silence)."""
    return np.zeros(8000, dtype=np.float32)


# ---------------------------------------------------------------------------
# Model readiness
# ---------------------------------------------------------------------------


class TestModelReadiness:
    """Tests for the load / ready state machinery."""

    def test_initial_not_ready(self, mock_model_manager: mock.MagicMock) -> None:
        """A freshly created recognizer is not ready."""
        rec = SpeechRecognizer(model_manager=mock_model_manager)
        assert not rec.is_ready

    def test_load_sets_ready(self, mock_model_manager: mock.MagicMock) -> None:
        """After load() succeeds, is_ready is True."""
        rec = SpeechRecognizer(model_manager=mock_model_manager)
        rec.load()
        assert rec.is_ready

    def test_load_calls_get_model(self, mock_model_manager: mock.MagicMock) -> None:
        """load() invokes model_manager.get_model() with the right args."""
        rec = SpeechRecognizer(
            model_manager=mock_model_manager,
            model_size="small",
            device="cpu",
            compute_type="float32",
        )
        rec.load()
        mock_model_manager.get_model.assert_called_once_with(
            model_size="small", device="cpu", compute_type="float32"
        )

    def test_load_is_idempotent(self, mock_model_manager: mock.MagicMock) -> None:
        """Calling load() twice does not call get_model() twice."""
        rec = SpeechRecognizer(model_manager=mock_model_manager)
        rec.load()
        rec.load()  # second call
        mock_model_manager.get_model.assert_called_once()

    def test_load_failure_raises_model_not_ready(
        self, mock_model_manager: mock.MagicMock
    ) -> None:
        """When get_model() raises, load() raises ModelNotReadyError."""
        mock_model_manager.get_model.side_effect = RuntimeError("Download failed")
        rec = SpeechRecognizer(model_manager=mock_model_manager)
        with pytest.raises(ModelNotReadyError, match="Failed to load"):
            rec.load()
        assert not rec.is_ready

    def test_not_ready_raises_error(
        self, mock_model_manager: mock.MagicMock, sample_audio: np.ndarray
    ) -> None:
        """When the model is not ready, transcribe raises ModelNotReadyError."""
        mock_model_manager.get_model.side_effect = RuntimeError("Model unavailable")
        rec = SpeechRecognizer(model_manager=mock_model_manager)

        with pytest.raises(ModelNotReadyError, match="not ready"):
            rec.transcribe(sample_audio)


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------


class TestTranscription:
    """Tests for the transcribe method."""

    def test_transcribe_returns_result(
        self, recognizer: SpeechRecognizer, sample_audio: np.ndarray
    ) -> None:
        """A successful transcription returns a TranscriptionResult."""
        result = recognizer.transcribe(sample_audio)
        assert isinstance(result, TranscriptionResult)
        assert isinstance(result.text, str)
        assert isinstance(result.language, str)
        assert isinstance(result.duration_s, float)

    def test_transcribe_cleans_text(
        self, recognizer: SpeechRecognizer, sample_audio: np.ndarray
    ) -> None:
        """The result text goes through clean_transcript."""
        result = recognizer.transcribe(sample_audio)
        # The mock returns " 你好世界 " → after clean_transcript, it is stripped.
        assert result.text == "你好世界"

    def test_transcribe_includes_segments(
        self, recognizer: SpeechRecognizer, sample_audio: np.ndarray
    ) -> None:
        """The result includes the raw segment data."""
        result = recognizer.transcribe(sample_audio)
        assert len(result.segments) == 1
        assert result.segments[0]["text"] == " 你好世界 "
        assert result.segments[0]["start"] == 0.0
        assert result.segments[0]["end"] == 1.0

    def test_transcribe_converts_dtype(
        self, mock_model_manager: mock.MagicMock
    ) -> None:
        """Audio is converted to float32 if it is not already."""
        rec = SpeechRecognizer(model_manager=mock_model_manager)
        rec.load()

        int_audio = np.zeros(8000, dtype=np.int16)
        rec.transcribe(int_audio)

        # The model.transcribe should have been called with float32 audio.
        model = mock_model_manager.get_model.return_value
        call_args = model.transcribe.call_args
        assert call_args is not None
        assert call_args[0][0].dtype == np.float32

    def test_transcribe_auto_loads(
        self, mock_model_manager: mock.MagicMock, sample_audio: np.ndarray
    ) -> None:
        """transcribe() auto-loads the model if not already loaded."""
        rec = SpeechRecognizer(model_manager=mock_model_manager)
        assert not rec.is_ready
        result = rec.transcribe(sample_audio)
        assert isinstance(result, TranscriptionResult)
        assert rec.is_ready


# ---------------------------------------------------------------------------
# clean_transcript — hallucination patterns (parametrised)
# ---------------------------------------------------------------------------


class TestHallucinationPatterns:
    """Every known hallucination pattern should produce an empty string."""

    @pytest.mark.parametrize(
        "text",
        [
            # Pattern: (音乐)
            "(音乐)",
            " (音乐) ",
            # Pattern: [音乐]
            "[音乐]",
            "[音乐]",
            " [音乐] ",
            # Pattern: 字幕
            "字幕",
            " 字幕 ",
            # Pattern: 谢谢观看
            "谢谢观看",
            " 谢谢观看 ",
            # Pattern: full donation spam
            "请不吝点赞订阅转发打赏支持明德",
            " 请不吝点赞订阅转发打赏支持明德 ",
            # Pattern: Thank you.
            "Thank you.",
            " Thank you. ",
            "Thank you",
            # Pattern: Thanks for watching / listening
            "Thanks for watching",
            "Thanks for listening",
            " Thanks for watching. ",
            # Pattern: repeated dots (3+)
            "...",
            " . . . ",
            "....",
            " . . . . ",
            # Pattern: just dots
            ".",
            "..",
            # Pattern: single filler words
            "好",
            "嗯",
            "啊",
            "哦",
            " 好 ",
            " 嗯 ",
            " 啊 ",
            " 哦 ",
        ],
    )
    def test_hallucination_filters(self, text: str) -> None:
        """Text matching a full hallucination pattern should be stripped to empty."""
        assert clean_transcript(text) == "", f"Expected empty for {text!r}"

    def test_known_pattern_count(self) -> None:
        """There should be at least 10 hallucination patterns defined."""
        assert len(_ZH_HALLUCINATION_PATTERNS) >= 10


# ---------------------------------------------------------------------------
# clean_transcript — normal text
# ---------------------------------------------------------------------------


class TestCleanTranscriptNormal:
    """Normal Chinese text should pass through clean_transcript unchanged."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("你好世界", "你好世界"),
            (" 你好世界 ", "你好世界"),
            ("打开浏览器", "打开浏览器"),
            ("这是一个测试", "这是一个测试"),
            ("Hello World", "Hello World"),
            ("Mixed 中文 English", "Mixed 中文 English"),
            ("搜索天气预报", "搜索天气预报"),
            ("", ""),
            ("   ", ""),
        ],
    )
    def test_normal_text_passes_through(self, text: str, expected: str) -> None:
        """Normal input text should either pass through unchanged."""
        assert clean_transcript(text) == expected


# ---------------------------------------------------------------------------
# clean_transcript — post processing (punctuation collapsing)
# ---------------------------------------------------------------------------


class TestPostProcessing:
    """Punctuation cleaning behaviour."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("你好。。。", "你好。"),
            ("你好！！", "你好!"),
            ("你好，，", "你好,"),
            ("你好。。", "你好。"),
            ("好。。。的吧", "好。的吧"),
            ("嗯。。", "嗯。"),
            ("测试、、", "测试、"),
            ("测试；；", "测试；"),
            ("你好吗？？", "你好吗?"),
            ("好的。。谢谢", "好的。谢谢"),
            # Already clean
            ("你好。", "你好。"),
            ("你好!", "你好!"),
            # Trailing punctuation stripped
            ("你好。 ", "你好"),
            ("你好！ ", "你好"),
            ("你好， ", "你好"),
            ("你好。。 ", "你好"),
            ("你好！！！", "你好!"),
            ("Hello...", "Hello."),
        ],
    )
    def test_repeated_punctuation_collapsed(self, raw: str, expected: str) -> None:
        """Repeated punctuation characters are collapsed to a single occurrence."""
        assert clean_transcript(raw) == expected
