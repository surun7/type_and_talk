# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tool spec: file_list."""

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


class FileListInput(_ToolSpec):
    """List files in a user directory."""

    directory: _Directory = Field(
        ...,
        description="Which user directory to list.",
    )
    pattern: str = Field(
        "*",
        description="Glob-style file pattern (e.g. '*.txt', 'report*').",
    )
    limit: int = Field(
        default=200,
        ge=1,
        le=1000,
        description="Maximum number of file entries to return (1–1000).",
    )

    @classmethod
    def tool_name(cls) -> str:
        return "file_list"

    @classmethod
    def tool_description(cls) -> str:
        return (
            "List files in a well-known user directory (Desktop, Documents, "
            "Downloads, Pictures, Music, Videos, or agent_uia_config). "
            "Returns file name, size, modification time, and a flag indicating "
            "whether each entry is a directory."
        )
