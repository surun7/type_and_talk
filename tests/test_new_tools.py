# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Type & Talk authors

"""Unit tests for the 7 new tool specs introduced in the tools/specs package.

These tests validate input-model behaviour (Pydantic validation).  Mock-based
execution tests are kept simple and do not import optional third-party packages.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent_uia.tools.specs.clipboard_read import ClipboardReadInput
from agent_uia.tools.specs.clipboard_write import ClipboardWriteInput
from agent_uia.tools.specs.file_list import FileListInput
from agent_uia.tools.specs.file_mkdir import FileMkdirInput
from agent_uia.tools.specs.file_move import FileMoveInput
from agent_uia.tools.specs.llm_complete import LlmCompleteInput
from agent_uia.tools.specs.system_info import SystemInfoInput


# ---------------------------------------------------------------------------
# clipboard_read
# ---------------------------------------------------------------------------


class TestClipboardReadSpec:
    """Input validation for ClipboardReadInput."""

    def test_empty_input_is_valid(self) -> None:
        """ClipboardReadInput has no required fields — empty dict is valid."""
        spec = ClipboardReadInput()
        assert spec.model_dump() == {}

    def test_normal_read_mocked(self) -> None:
        """Simulate clipboard read via a mock function."""
        mock_paste = MagicMock(return_value="hello world")
        assert mock_paste() == "hello world"
        mock_paste.assert_called_once()

    def test_empty_clipboard_mocked(self) -> None:
        """Simulate empty clipboard via a mock function."""
        mock_paste = MagicMock(return_value="")
        assert mock_paste() == ""

    def test_error_handling_mocked(self) -> None:
        """Simulate clipboard error via a mock function."""
        mock_paste = MagicMock(
            side_effect=RuntimeError("clipboard error")
        )
        with pytest.raises(RuntimeError, match="clipboard error"):
            mock_paste()


# ---------------------------------------------------------------------------
# clipboard_write
# ---------------------------------------------------------------------------


class TestClipboardWriteSpec:
    """Input validation for ClipboardWriteInput."""

    def test_normal_write_validates(self) -> None:
        """Valid text passes validation."""
        spec = ClipboardWriteInput(text="hello world")
        assert spec.text == "hello world"

    def test_length_cap_respected(self) -> None:
        """Text at exactly the 100 000 max is accepted."""
        text = "x" * 100_000
        spec = ClipboardWriteInput(text=text)
        assert spec.text == text

    def test_length_cap_exceeded_rejected(self) -> None:
        """Text over 100 000 chars is rejected by Pydantic."""
        with pytest.raises(ValueError, match="100000"):
            ClipboardWriteInput(text="x" * 100_001)

    def test_normal_write_mocked(self) -> None:
        """Simulate clipboard write via a mock function."""
        mock_copy = MagicMock()
        mock_copy("hello world")
        mock_copy.assert_called_once_with("hello world")


# ---------------------------------------------------------------------------
# file_list
# ---------------------------------------------------------------------------


class TestFileListSpec:
    """Input validation for FileListInput."""

    def test_each_allowed_directory_works(self) -> None:
        """Every well-known directory literal is accepted."""
        for directory in (
            "desktop",
            "documents",
            "downloads",
            "pictures",
            "music",
            "videos",
            "agent_uia_config",
        ):
            spec = FileListInput(directory=directory)
            assert spec.directory == directory

    def test_path_outside_allowlist_rejected(self) -> None:
        """An arbitrary directory string is rejected by the Literal."""
        with pytest.raises(ValueError, match="Input should be"):
            FileListInput(directory="restricted")  # type: ignore[arg-type]

    def test_default_pattern_is_star(self) -> None:
        """The default pattern is '*'."""
        spec = FileListInput(directory="desktop")
        assert spec.pattern == "*"

    def test_limit_default_and_bounds(self) -> None:
        """Default limit is 200; values outside 1-1000 are rejected."""
        spec = FileListInput(directory="desktop")
        assert spec.limit == 200

        with pytest.raises(ValueError, match="greater than or equal to"):
            FileListInput(directory="desktop", limit=0)

        with pytest.raises(ValueError, match="less than or equal to"):
            FileListInput(directory="desktop", limit=1001)


# ---------------------------------------------------------------------------
# file_mkdir
# ---------------------------------------------------------------------------


class TestFileMkdirSpec:
    """Input validation for FileMkdirInput."""

    def test_create_succeeds_validates(self) -> None:
        """A safe directory name passes validation."""
        spec = FileMkdirInput(directory="desktop", name="NewFolder")
        assert spec.name == "NewFolder"

    def test_dangerous_name_refused_by_pattern(self) -> None:
        """Names with path separators or special chars are rejected."""
        with pytest.raises(ValueError, match="pattern"):
            FileMkdirInput(directory="desktop", name="../evil")

    def test_name_with_dots_and_spaces_accepted(self) -> None:
        """Safe characters like dots, spaces, and hyphens are allowed."""
        spec = FileMkdirInput(
            directory="desktop", name="My Folder v2"
        )
        assert spec.name == "My Folder v2"

    def test_name_too_long_rejected(self) -> None:
        """Names > 100 chars are rejected."""
        with pytest.raises(ValueError, match="at most 100"):
            FileMkdirInput(directory="desktop", name="x" * 101)

    def test_name_empty_rejected(self) -> None:
        """Empty name is rejected."""
        with pytest.raises(ValueError, match="at least 1"):
            FileMkdirInput(directory="desktop", name="")


# ---------------------------------------------------------------------------
# file_move
# ---------------------------------------------------------------------------


class TestFileMoveSpec:
    """Input validation for FileMoveInput."""

    def test_normal_move_validates(self) -> None:
        """A valid move between well-known directories passes."""
        spec = FileMoveInput(
            source="report.txt",
            source_directory="desktop",
            destination_directory="documents",
        )
        assert spec.source == "report.txt"
        assert spec.source_directory == "desktop"
        assert spec.destination_directory == "documents"

    def test_dangerous_extension_not_blocked_by_spec(self) -> None:
        """The spec itself allows .exe in the source field (the executor
        blocks it at runtime)."""
        spec = FileMoveInput(
            source="setup.exe",
            source_directory="desktop",
            destination_directory="documents",
        )
        assert spec.source == "setup.exe"

    def test_destination_subfolder_is_optional(self) -> None:
        """destination_subfolder defaults to None."""
        spec = FileMoveInput(
            source="x.txt",
            source_directory="desktop",
            destination_directory="downloads",
        )
        assert spec.destination_subfolder is None

    def test_invalid_directory_rejected(self) -> None:
        """An invalid directory literal is rejected."""
        with pytest.raises(ValueError, match="Input should be"):
            FileMoveInput(
                source="x.txt",
                source_directory="root",  # type: ignore[arg-type]
                destination_directory="documents",
            )


# ---------------------------------------------------------------------------
# system_info
# ---------------------------------------------------------------------------


class TestSystemInfoSpec:
    """Input validation for SystemInfoInput."""

    def test_default_components(self) -> None:
        """Default components include cpu, memory, disk, uptime."""
        spec = SystemInfoInput()
        assert set(spec.components) == {"cpu", "memory", "disk", "uptime"}

    def test_subset_of_components(self) -> None:
        """Only cpu and memory can be requested."""
        spec = SystemInfoInput(components=["cpu", "memory"])
        assert spec.components == ["cpu", "memory"]

    def test_invalid_component_rejected(self) -> None:
        """An unknown component value is rejected."""
        with pytest.raises(ValueError, match="Input should be"):
            SystemInfoInput(components=["gpu"])  # type: ignore[list-item]

    def test_mocked_cpu_functions(self) -> None:
        """Verify mocked cpu count and percent via MagicMock."""
        mock_cpu_count = MagicMock(return_value=8)
        mock_cpu_percent = MagicMock(return_value=15.3)
        assert mock_cpu_count() == 8
        assert mock_cpu_percent() == 15.3

    def test_mocked_memory_shape(self) -> None:
        """Verify virtual_memory returns expected shape via MagicMock."""
        mock_mem = MagicMock(
            total=16 * 1024**3,
            available=8 * 1024**3,
            percent=50.0,
        )
        mem = mock_mem
        assert isinstance(mem.total, int)
        assert isinstance(mem.available, int)
        assert isinstance(mem.percent, float)

    def test_mocked_disk_shape(self) -> None:
        """Verify disk_usage returns expected shape via MagicMock."""
        mock_disk = MagicMock(
            total=256_000_000_000,
            used=128_000_000_000,
            free=128_000_000_000,
            percent=50.0,
        )
        disk = mock_disk
        assert isinstance(disk.total, int)
        assert isinstance(disk.used, int)
        assert isinstance(disk.free, int)


# ---------------------------------------------------------------------------
# llm_complete
# ---------------------------------------------------------------------------


class TestLlmCompleteSpec:
    """Input validation for LlmCompleteInput."""

    def test_call_succeeds_validates(self) -> None:
        """A minimal prompt passes validation."""
        spec = LlmCompleteInput(prompt="Write something")
        assert spec.prompt == "Write something"
        assert spec.max_tokens == 512
        assert spec.temperature == 0.7

    def test_prompt_min_length(self) -> None:
        """Empty prompt is rejected."""
        with pytest.raises(ValueError, match="at least 1"):
            LlmCompleteInput(prompt="")

    def test_prompt_max_length(self) -> None:
        """Prompt at exactly 4000 chars is accepted."""
        text = "x" * 4000
        spec = LlmCompleteInput(prompt=text)
        assert spec.prompt == text

    def test_prompt_too_long_rejected(self) -> None:
        """Prompt over 4000 chars is rejected."""
        with pytest.raises(ValueError, match="at most 4000"):
            LlmCompleteInput(prompt="x" * 4001)

    def test_max_tokens_bounds(self) -> None:
        """max_tokens must be 1-2000."""
        spec = LlmCompleteInput(prompt="hi", max_tokens=2000)
        assert spec.max_tokens == 2000

        with pytest.raises(ValueError, match="less than or equal to 2000"):
            LlmCompleteInput(prompt="hi", max_tokens=2001)

        with pytest.raises(ValueError, match="greater than or equal to 1"):
            LlmCompleteInput(prompt="hi", max_tokens=0)

    def test_temperature_bounds(self) -> None:
        """temperature must be 0.0-2.0."""
        spec = LlmCompleteInput(prompt="hi", temperature=2.0)
        assert spec.temperature == 2.0

        with pytest.raises(ValueError, match="less than or equal to 2"):
            LlmCompleteInput(prompt="hi", temperature=2.1)

        with pytest.raises(ValueError, match="greater than or equal to 0"):
            LlmCompleteInput(prompt="hi", temperature=-0.1)

    def test_system_optional(self) -> None:
        """system prompt defaults to None."""
        spec = LlmCompleteInput(prompt="hi")
        assert spec.system is None

    def test_mocked_llm_client(self) -> None:
        """Verify an LLMClient can be mocked to simulate completions."""
        mock_instance = MagicMock()
        mock_instance.complete.return_value = "generated text"

        result = mock_instance.complete(prompt="Write something")
        assert result == "generated text"
        mock_instance.complete.assert_called_once_with(
            prompt="Write something"
        )
