# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Type & Talk authors

from __future__ import annotations

import pytest

from agent_uia.safety import SafetyConfig, SafetyGate, SafetyVerdict


def test_skill_targeting_blocklisted_app() -> None:
    """Try skill targeting blocklisted app -> BLOCKED."""
    config = SafetyConfig(
        blocked_executables={"blocked-app.exe"},
        login_window_keywords=set(),
        always_confirm_actions=set(),
    )
    safety = SafetyGate(config)

    decision = safety.check_app(exe_name="blocked-app.exe")
    assert decision.verdict == SafetyVerdict.BLOCK_UNSUPPORTED


def test_file_move_to_path_outside_allowlist() -> None:
    """Try file_move to path outside allowlist -> FAILED.

    Note: the SafetyGate does not have an allowlist concept directly;
    the file_move tool spec restricts moves to well-known user directories.
    This test verifies that a path outside those directories would be
    rejected by the tool's input validation.
    """
    from agent_uia.tools.specs.file_move import FileMoveInput

    # FileMoveInput only accepts well-known directory literals, so an
    # arbitrary path is a Pydantic validation error.
    with pytest.raises(ValueError, match="Input should be"):
        FileMoveInput(
            source="test.txt",
            source_directory="restricted",  # type: ignore[arg-type]
            destination_directory="documents",
        )
