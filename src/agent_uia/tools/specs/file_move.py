# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool spec: file_move."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from agent_uia.tools.base import _ToolSpec

_Directory = Literal[
    "desktop",
    "documents",
    "downloads",
    "pictures",
    "music",
    "videos",
    "agent_uia_config",
]


class FileMoveInput(_ToolSpec):
    """Move a file from one user directory to another (or within the same one)."""

    source: str = Field(
        ...,
        description="Filename (basename only) of the file to move.",
    )
    source_directory: _Directory = Field(
        ...,
        description="Which user directory the source file lives in.",
    )
    destination_directory: _Directory = Field(
        ...,
        description="Which user directory to move the file into.",
    )
    destination_subfolder: str | None = Field(
        None,
        description="Optional subfolder name within the destination directory.",
    )

    @classmethod
    def tool_name(cls) -> str:
        return "file_move"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "Move a file between well-known user directories. "
            "Dangerous file extensions (.exe, .bat, .ps1, etc.) are blocked. "
            "An optional destination subfolder can be specified."
        )
